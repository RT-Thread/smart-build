import io
import json
import subprocess
from pathlib import Path

import pytest

from smart_build.domains.kernel import KERNEL_PACKAGE_TASK_ID, KERNEL_TASK_ID, kernel_tasks
from smart_build.env_packages import EnvPackages
from smart_build.errors import SmartBuildError
from smart_build.paths import BuildPaths


class _Toolchain:
    def compile_env(self):
        return {"CC": "/toolchain/bin/target-gcc"}

    def manifest_record(self):
        return {"root": "/toolchain", "target": "test-target"}


def _project(tmp_path):
    machine = "test-machine"
    board = tmp_path / "boards" / machine
    board.mkdir(parents=True)
    (board / "board.yaml").write_text(
        "\n".join(
            (
                "schema_version: 1",
                "kind: board",
                f"name: {machine}",
                "version: 0.1.0",
                "arch: test",
                "bsp: test-bsp",
                "kernel_defconfig: kernel_defconfig",
                "toolchain:",
                "  package: test-toolchain",
                "  target: test-target",
                "  prefix: test-target-",
                "  loader: none",
                "qemu:",
                "  binary: qemu-system-test",
                "  profile: test",
                "  machine: test",
                "",
            )
        ),
        encoding="utf-8",
    )
    (board / "defconfig").write_text(
        f"MACHINE={machine}\nARCH=test\nBSP=test-bsp\nROOTFS=none\nTOOLCHAIN=test-toolchain\n",
        encoding="utf-8",
    )
    (board / "kernel_defconfig").write_text(
        "\n".join(
            (
                "CONFIG_PKG_USING_LWEXT4=y",
                'CONFIG_PKG_LWEXT4_PATH="/packages/system/lwext4"',
                'CONFIG_PKG_LWEXT4_VER="v2.0.0-dfsv2"',
                "",
            )
        ),
        encoding="utf-8",
    )
    bsp = tmp_path / "rt-thread" / "bsp" / "test-bsp"
    bsp.mkdir(parents=True)
    (bsp / "SConstruct").write_text("# test\n", encoding="utf-8")

    env_root = tmp_path / "home" / ".env"
    command = env_root / "tools" / "scripts" / "pkgs"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    command.chmod(0o755)
    index = env_root / "packages" / "packages"
    index.mkdir(parents=True)
    (index / "Kconfig").write_text("# packages\n", encoding="utf-8")
    packages = EnvPackages(env_root=env_root, command=command, index=index)
    return BuildPaths.for_machine(machine, root=tmp_path), bsp, packages


def _write_package_state(bsp, errors=None, installed=True, state=None):
    packages_dir = bsp / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    if installed:
        (packages_dir / "lwext4-v2.0.0-dfsv2").mkdir(parents=True)
    (packages_dir / "SConscript").write_text("# packages\n", encoding="utf-8")
    package_state = state
    if package_state is None:
        package_state = [
            {
                "name": "LWEXT4",
                "path": "/packages/system/lwext4",
                "ver": "v2.0.0-dfsv2",
            }
        ]
    (packages_dir / "pkgs.json").write_text(
        json.dumps(package_state),
        encoding="utf-8",
    )
    (packages_dir / "pkgs_error.json").write_text(json.dumps(errors or []), encoding="utf-8")


def test_kernel_package_task_updates_env_packages_before_build(tmp_path):
    paths, bsp, packages = _project(tmp_path)
    calls = []

    def runner(command, cwd, env):
        calls.append((command, cwd, env))
        if command == [str(packages.command), "--update"]:
            _write_package_state(bsp)
        return subprocess.CompletedProcess(command, 0, stdout="Operation completed successfully.\n")

    package_task, kernel_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=runner,
        env_packages=packages,
    )
    result = package_task.executor(package_task, io.StringIO())

    assert result == 0
    assert package_task.id == KERNEL_PACKAGE_TASK_ID
    assert package_task.deps == ("toolchain:check", "source:rt-thread")
    assert kernel_task.id == KERNEL_TASK_ID
    assert kernel_task.deps == (KERNEL_PACKAGE_TASK_ID,)
    assert calls[0][0] == ["scons", "--pyconfig-silent", "-C", str(bsp)]
    assert calls[1][0] == [str(packages.command), "--update"]
    assert calls[1][1] == bsp
    assert calls[1][2]["ENV_ROOT"] == str(packages.env_root)
    assert (bsp / ".config").read_text(encoding="utf-8") == (
        paths.root / "boards" / paths.machine / "kernel_defconfig"
    ).read_text(encoding="utf-8")
    assert package_task.outputs[0].is_file()
    record = package_task.manifest_fields["kernel_packages"]["packages"][0]
    assert record["name"] == "LWEXT4"
    assert record["version"] == "v2.0.0-dfsv2"
    assert record["managed_by_env"] is True


def test_kernel_package_task_rejects_env_reported_errors(tmp_path):
    paths, bsp, packages = _project(tmp_path)

    def runner(command, cwd, env):
        if command == [str(packages.command), "--update"]:
            _write_package_state(bsp, errors=[{"name": "LWEXT4"}])
        return subprocess.CompletedProcess(command, 0, stdout="Operation completed successfully.\n")

    package_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=runner,
        env_packages=packages,
    )[0]

    with pytest.raises(SmartBuildError, match="package update reported errors") as error:
        package_task.executor(package_task, io.StringIO())

    assert error.value.code == "BUILD"
    assert not package_task.outputs[0].exists()


def test_kernel_package_task_rejects_env_reported_failure(tmp_path):
    paths, bsp, packages = _project(tmp_path)

    def runner(command, cwd, env):
        if command == [str(packages.command), "--update"]:
            _write_package_state(bsp, state=[])
            return subprocess.CompletedProcess(command, 0, stdout="Operation failed.\n")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n")

    package_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=runner,
        env_packages=packages,
    )[0]

    with pytest.raises(SmartBuildError, match="did not report success") as error:
        package_task.executor(package_task, io.StringIO())

    assert error.value.code == "BUILD"
    assert not package_task.outputs[0].exists()


def test_kernel_package_task_rejects_nonzero_command(tmp_path):
    paths, _bsp, packages = _project(tmp_path)

    def runner(command, cwd, env):
        return subprocess.CompletedProcess(command, 2, stdout="failed\n")

    package_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=runner,
        env_packages=packages,
    )[0]

    with pytest.raises(SmartBuildError, match="command failed") as error:
        package_task.executor(package_task, io.StringIO())

    assert error.value.code == "BUILD"


@pytest.mark.parametrize("contents", ("not json", "{}"))
def test_kernel_package_task_rejects_invalid_package_state(tmp_path, contents):
    paths, bsp, packages = _project(tmp_path)

    def runner(command, cwd, env):
        if command == [str(packages.command), "--update"]:
            _write_package_state(bsp)
            (bsp / "packages" / "pkgs.json").write_text(contents, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="Operation completed successfully.\n")

    package_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=runner,
        env_packages=packages,
    )[0]

    with pytest.raises(SmartBuildError, match="kernel package state") as error:
        package_task.executor(package_task, io.StringIO())

    assert error.value.code == "BUILD"


def test_kernel_package_task_rejects_missing_installed_package(tmp_path):
    paths, bsp, packages = _project(tmp_path)

    def runner(command, cwd, env):
        if command == [str(packages.command), "--update"]:
            _write_package_state(bsp, installed=False)
        return subprocess.CompletedProcess(command, 0, stdout="Operation completed successfully.\n")

    package_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=runner,
        env_packages=packages,
    )[0]

    with pytest.raises(SmartBuildError, match="not installed at its managed path") as error:
        package_task.executor(package_task, io.StringIO())

    assert error.value.code == "BUILD"


def test_kernel_package_task_accepts_empty_selection(tmp_path):
    paths, bsp, packages = _project(tmp_path)
    (paths.root / "boards" / paths.machine / "kernel_defconfig").write_text(
        "# CONFIG_PKG_USING_LWEXT4 is not set\n",
        encoding="utf-8",
    )

    def runner(command, cwd, env):
        if command == [str(packages.command), "--update"]:
            _write_package_state(bsp, installed=False, state=[])
        return subprocess.CompletedProcess(command, 0, stdout="Operation completed successfully.\n")

    package_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=runner,
        env_packages=packages,
    )[0]

    assert package_task.executor(package_task, io.StringIO()) == 0
    assert package_task.manifest_fields["kernel_packages"]["packages"] == []


def test_kernel_package_task_rejects_state_mismatch(tmp_path):
    paths, bsp, packages = _project(tmp_path)

    def runner(command, cwd, env):
        if command == [str(packages.command), "--update"]:
            _write_package_state(bsp, installed=False, state=[])
        return subprocess.CompletedProcess(command, 0, stdout="Operation completed successfully.\n")

    package_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=runner,
        env_packages=packages,
    )[0]

    with pytest.raises(SmartBuildError, match="does not match the BSP .config") as error:
        package_task.executor(package_task, io.StringIO())

    assert error.value.code == "BUILD"


def test_kernel_build_rejects_overlay_into_env_packages(tmp_path):
    paths, bsp, packages = _project(tmp_path)
    overlay = paths.root / "boards" / paths.machine / "kernel-overlay" / "packages" / "example.c"
    overlay.parent.mkdir(parents=True)
    overlay.write_text("/* test */\n", encoding="utf-8")

    def unexpected_runner(command, cwd, env):
        raise AssertionError(f"unexpected command: {command}")

    kernel_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        command_runner=unexpected_runner,
        env_packages=packages,
    )[1]

    with pytest.raises(SmartBuildError, match="must not modify Env-managed packages") as error:
        kernel_task.executor(kernel_task, io.StringIO())

    assert error.value.code == "CONFIG"
    assert not (bsp / "packages" / "example.c").exists()


def test_kernel_verbose_build_uses_scons_verbose(tmp_path):
    paths, bsp, packages = _project(tmp_path)

    default_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        env_packages=packages,
    )[1]
    verbose_task = kernel_tasks(
        paths,
        toolchain=_Toolchain(),
        env_packages=packages,
        verbose=True,
    )[1]

    assert default_task.manifest_fields["commands"] == [["scons", "-C", str(bsp)]]
    assert verbose_task.manifest_fields["commands"] == [
        ["scons", "--verbose", "-C", str(bsp)]
    ]


def test_env_packages_requires_command_and_index(tmp_path):
    packages = EnvPackages.discover(home=tmp_path)

    with pytest.raises(SmartBuildError, match="package command is not executable"):
        packages.validate()

    packages.command.parent.mkdir(parents=True)
    packages.command.write_text("#!/bin/sh\n", encoding="utf-8")
    packages.command.chmod(0o755)

    with pytest.raises(SmartBuildError, match="package index is missing Kconfig"):
        packages.validate()
