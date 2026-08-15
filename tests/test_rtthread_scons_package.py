import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import kconfiglib
import pytest

from smart_build.config import resolve_rootfs_selection
from smart_build.configure import configure_target
from smart_build.descriptions import load_description
from smart_build.domains.ipkg import install_ipkg, ipkg_task
from smart_build.domains.package import package_task
from smart_build.env_packages import EnvPackages
from smart_build.errors import SmartBuildError
from smart_build.menuconfig import _package_keys, _write_defconfig
from smart_build.package_kconfig import (
    generate_package_kconfig_files,
    generate_package_kconfig_index,
    load_native_package_kconfig,
    native_kconfig_environment,
)
from smart_build.package_metadata import normalize_package_metadata
from smart_build.paths import BuildPaths
from smart_build.rtthread_scons import parse_rtthread_scons_config
from smart_build.tasks import _package_tasks


class _Toolchain:
    prefix = ""
    target = "test-target"
    root = Path("/toolchain")
    bin_dir = Path("/toolchain/bin")

    def compile_env(self):
        return {"PATH": os.environ.get("PATH", ""), "CROSS_COMPILE": self.prefix}

    def manifest_record(self):
        return {
            "id": "test-gcc",
            "target": self.target,
            "prefix": self.prefix,
            "root": str(self.root),
        }


def _project(tmp_path, *, package_mode="profile", linkage="static", output="/share/demo.txt"):
    machine = "test-machine"
    board = tmp_path / "boards" / machine
    board.mkdir(parents=True)
    selection = "PKG_USING_DEMO_ONLINE=y\n" if package_mode == "manual" else ""
    (board / "defconfig").write_text(
        "".join(
            (
                f"MACHINE={machine}\n",
                "ROOTFS=full\n",
                f"ROOTFS_BUILD_MODE={linkage}\n",
                "ROOTFS_PROFILE=base\n",
                f"ROOTFS_PACKAGE_MODE={package_mode}\n",
                selection,
            )
        ),
        encoding="utf-8",
    )
    rootfs = tmp_path / "rootfs" / "full"
    rootfs.mkdir(parents=True)
    (rootfs / "rootfs.yaml").write_text(
        "\n".join(
            (
                "schema_version: 1",
                "kind: rootfs",
                "name: full",
                "version: 1.0.0",
                "default_profile: base",
                "profiles:",
                "  base:",
                "    packages: [demo]",
                "",
            )
        ),
        encoding="utf-8",
    )

    (tmp_path / "packages" / "smart-sdk").mkdir(parents=True)
    (tmp_path / "rt-thread" / "tools").mkdir(parents=True)
    package_dir = tmp_path / "packages" / "demo"
    source_dir = package_dir / "source"
    source_dir.mkdir(parents=True)
    (package_dir / "package.yaml").write_text(
        "\n".join(
            (
                "schema_version: 1",
                "kind: package",
                "name: demo",
                "version: 1.0.0",
                "type: library",
                "description: Independent RT-Thread SCons demo",
                "source:",
                "  directory: packages/demo/source",
                "kconfig:",
                "  mode: native",
                "  source: source/Kconfig",
                "  symbol: PKG_USING_DEMO_ONLINE",
                "build:",
                "  rtthread_scons:",
                "    supported_linkage: [static]",
                "    install_target: install",
                "    outputs:",
                f"      - {output}",
                "      - /share/online.txt",
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_dir / "Kconfig").write_text(
        "\n".join(
            (
                'mainmenu "RT-Thread package test"',
                "",
                "config PKGS_DIR",
                "    string",
                '    option env="PKGS_ROOT"',
                '    default "packages"',
                "",
                'source "$PKGS_DIR/Kconfig"',
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_dir / "SConstruct").write_text(
        "\n".join(
            (
                "import os",
                "from pathlib import Path",
                "",
                "AddOption('--pyconfig-silent', dest='pyconfig_silent', action='store_true', default=False)",
                "if GetOption('pyconfig_silent'):",
                "    config = Path(os.environ['KCONFIG_CONFIG'])",
                "    if not config.is_file():",
                "        Exit(2)",
                "    Path('rtconfig.h').write_text('/* generated */\\n', encoding='utf-8')",
                "    Path('pkg_config.h').write_text('/* generated */\\n', encoding='utf-8')",
                "    Exit(0)",
                "",
                "variables = Variables()",
                "for name in ('BUILD_DIR', 'DESTDIR', 'KCONFIG_CONFIG', 'SMART_SDK_DIR', 'CROSS_COMPILE', 'LINKAGE'):",
                "    variables.Add(name)",
                "env = Environment(variables=variables, ENV=os.environ)",
                "Export('env')",
                "local = SConscript('SConscript')",
                "online = SConscript('packages/SConscript')",
                "Alias('install', [local, online])",
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_dir / "SConscript").write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "",
                "Import('env')",
                "",
                "def generate(target, source, env):",
                "    config = Path(env['KCONFIG_CONFIG']).read_text(encoding='utf-8')",
                "    main = Path(str(source[0])).read_text(encoding='utf-8')",
                "    payload = main + '\\n' + config + '\\n' + '\\n'.join(",
                "        f'{name}={env[name]}'",
                "        for name in ('SMART_SDK_DIR', 'CROSS_COMPILE', 'LINKAGE')",
                "    ) + '\\n'",
                "    target_path = Path(str(target[0]))",
                "    target_path.parent.mkdir(parents=True, exist_ok=True)",
                "    target_path.write_text(payload, encoding='utf-8')",
                "    return 0",
                "",
                "generated = env.Command(env['BUILD_DIR'] + '/demo.txt', 'main.c', generate)",
                "installed = env.Command(env['DESTDIR'] + '/share/demo.txt', generated, Copy('$TARGET', '$SOURCE'))",
                "Return('installed')",
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")

    # These are generated in a developer source tree and must never be copied or changed.
    (source_dir / ".config").write_text("STALE=y\n", encoding="utf-8")
    (source_dir / ".sconsign.source").write_text("stale\n", encoding="utf-8")
    (source_dir / "rtconfig.h").write_text("stale\n", encoding="utf-8")
    (source_dir / "pkg_config.h").write_text("stale\n", encoding="utf-8")
    (source_dir / "build").mkdir()
    (source_dir / "build" / "stale.txt").write_text("stale\n", encoding="utf-8")
    (source_dir / "packages").mkdir()
    (source_dir / "packages" / "stale.txt").write_text("stale\n", encoding="utf-8")

    packages_index = tmp_path / "packages" / "Kconfig"
    packages_index.write_text('source "packages/demo/source/Kconfig"\n', encoding="utf-8")
    (tmp_path / "Kconfig").write_text(
        "\n".join(
            (
                'mainmenu "test"',
                "config PKG_UNRELATED",
                '    bool "unrelated"',
                'source "packages/Kconfig"',
                "",
            )
        ),
        encoding="utf-8",
    )

    env_root = tmp_path / "fake-env"
    command = env_root / "tools" / "scripts" / "pkgs"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    command.chmod(0o755)
    env_package_root = env_root / "packages"
    env_index = env_package_root / "packages"
    env_index.mkdir(parents=True)
    (env_package_root / "Kconfig").write_text(
        'source "$PKGS_ROOT/packages/Kconfig"\n',
        encoding="utf-8",
    )
    (env_index / "Kconfig").write_text(
        "\n".join(
            (
                "menuconfig PKG_USING_DEMO_ONLINE",
                '    bool "demo online package"',
                "",
                "if PKG_USING_DEMO_ONLINE",
                "config PKG_DEMO_ONLINE_PATH",
                "    string",
                '    default "/misc/demo-online"',
                "",
                "config PKG_DEMO_ONLINE_VER",
                "    string",
                '    default "v1.0.0"',
                "config DEMO_ONLINE_FEATURE",
                '    bool "demo feature"',
                "    default n",
                "endif",
                "",
            )
        ),
        encoding="utf-8",
    )
    env_packages = EnvPackages(env_root=env_root, command=command, index=env_index)
    return BuildPaths.for_machine(machine, root=tmp_path), package_dir, source_dir, env_packages


def _description(package_dir):
    return load_description(package_dir / "package.yaml")


def _write_package_state(project_dir, *, errors=None, installed=True, state=None):
    packages_dir = project_dir / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    package_state = state
    if package_state is None:
        package_state = [
            {
                "name": "DEMO_ONLINE",
                "path": "/misc/demo-online",
                "ver": "v1.0.0",
            }
        ]
    if installed:
        online_dir = packages_dir / "demo-online-v1.0.0"
        online_dir.mkdir(parents=True, exist_ok=True)
        (online_dir / "payload.txt").write_text("downloaded online package\n", encoding="utf-8")
    (packages_dir / "SConscript").write_text(
        "\n".join(
            (
                "Import('env')",
                "online = env.Command(",
                "    env['DESTDIR'] + '/share/online.txt',",
                "    '#packages/demo-online-v1.0.0/payload.txt',",
                "    Copy('$TARGET', '$SOURCE'),",
                ")",
                "Return('online')",
                "",
            )
        ),
        encoding="utf-8",
    )
    (packages_dir / "pkgs.json").write_text(json.dumps(package_state), encoding="utf-8")
    (packages_dir / "pkgs_error.json").write_text(json.dumps(errors or []), encoding="utf-8")


def _real_runner(env_packages, calls, update=None):
    def runner(command, cwd, env):
        calls.append((list(command), Path(cwd), dict(env)))
        if command == [str(env_packages.command), "--update"]:
            if update is None:
                _write_package_state(Path(cwd))
            else:
                update(Path(cwd))
            return subprocess.CompletedProcess(command, 0, stdout="Operation completed successfully.\n")
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    return runner


def _tasks(paths, env_packages, command_runner=None):
    tasks = package_task(
        paths,
        "demo",
        toolchain=_Toolchain(),
        command_runner=command_runner,
        env_packages=env_packages,
    )
    assert [task.id for task in tasks] == [
        "package:demo:env-packages",
        "package:demo:build",
    ]
    return tasks


def test_native_kconfig_is_indexed_with_env_online_symbols(tmp_path, monkeypatch):
    paths, package_dir, _source_dir, env_packages = _project(tmp_path)
    description = _description(package_dir)
    metadata = normalize_package_metadata(description)

    with native_kconfig_environment(env_packages):
        assert generate_package_kconfig_files(paths.root) == {}
        index = generate_package_kconfig_index(paths.root)
        assert 'source "packages/demo/source/Kconfig"' in index
        monkeypatch.setenv("srctree", str(paths.root))
        kconf = kconfiglib.Kconfig(str(paths.root / "Kconfig"), warn=False)
        package_keys = _package_keys(kconf, paths.root)

    assert metadata.kconfig.symbol == "PKG_USING_DEMO_ONLINE"
    assert "PKG_USING_DEMO_ONLINE" in package_keys
    assert "PKG_DEMO_ONLINE_PATH" in package_keys
    assert "PKG_DEMO_ONLINE_VER" in package_keys
    assert "PKG_UNRELATED" not in package_keys
    saved = paths.root / "saved-defconfig"
    _write_defconfig(
        saved,
        {
            "PKG_USING_DEMO_ONLINE": "y",
            "PKG_DEMO_ONLINE_PATH": "/misc/demo-online",
            "PKG_DEMO_ONLINE_VER": "v1.0.0",
        },
        owned_keys=package_keys,
        package_keys=package_keys,
    )
    saved_text = saved.read_text(encoding="utf-8")
    assert "PKG_USING_DEMO_ONLINE=y\n" in saved_text
    assert "PKG_DEMO_ONLINE_PATH=/misc/demo-online\n" in saved_text
    assert "PKG_DEMO_ONLINE_VER=v1.0.0\n" in saved_text


def test_native_package_configure_opens_menuconfig_and_persists_values(tmp_path):
    paths, _package_dir, source_dir, env_packages = _project(tmp_path)
    source_config = (source_dir / ".config").read_bytes()
    calls = []

    def frontend(kconf):
        calls.append(Path(os.environ["KCONFIG_CONFIG"]))
        assert kconf.syms["PKG_USING_DEMO_ONLINE"].str_value == "y"
        kconf.syms["DEMO_ONLINE_FEATURE"].set_value(2)

    result = configure_target(
        paths,
        "package:demo",
        frontend=frontend,
        env_packages=env_packages,
    )

    assert result.target == "package:demo"
    assert result.updated == (
        paths.root / "boards" / paths.machine / "defconfig",
        paths.root / "build" / ".config",
    )
    assert calls == [
        paths.work_dir / "configure" / "package-demo" / ".config"
    ]
    board_values = (result.updated[0]).read_text(encoding="utf-8")
    workspace_values = (result.updated[1]).read_text(encoding="utf-8")
    for values in (board_values, workspace_values):
        assert "MACHINE=test-machine\n" in values
        assert "ROOTFS=full\n" in values
        assert "PKG_USING_DEMO_ONLINE=y\n" in values
        assert "PKG_DEMO_ONLINE_PATH=/misc/demo-online\n" in values
        assert "PKG_DEMO_ONLINE_VER=v1.0.0\n" in values
        assert "DEMO_ONLINE_FEATURE=y\n" in values

    def disable_feature(kconf):
        kconf.syms["DEMO_ONLINE_FEATURE"].set_value(0)

    configure_target(
        paths,
        "package:demo",
        frontend=disable_feature,
        env_packages=env_packages,
    )
    for path in result.updated:
        assert "DEMO_ONLINE_FEATURE" not in path.read_text(encoding="utf-8")
    assert (source_dir / ".config").read_bytes() == source_config
    assert not (source_dir / "packages" / "pkgs.json").exists()


def test_native_selection_symbol_selects_package_in_manual_mode(tmp_path):
    paths, _package_dir, _source_dir, _env_packages = _project(tmp_path, package_mode="manual")

    selection = resolve_rootfs_selection(paths.root, paths.machine)

    assert selection.packages == ["demo"]
    assert selection.selected_packages[0].metadata.kconfig.symbol == "PKG_USING_DEMO_ONLINE"


def test_rtthread_scons_package_placeholder_includes_env_update(tmp_path):
    paths, _package_dir, _source_dir, _env_packages = _project(tmp_path)

    tasks = _package_tasks("package:demo", paths)

    assert [task.id for task in tasks] == [
        "package:demo:env-packages",
        "package:demo:build",
        "ipkg:demo:package",
    ]
    assert tasks[0].deps == ("toolchain:check", "source:rt-thread")
    assert tasks[1].deps == (tasks[0].id,)


@pytest.mark.skipif(shutil.which("scons") is None, reason="SCons is required")
def test_real_scons_fetch_build_and_ipkg_are_isolated(tmp_path):
    paths, _package_dir, source_dir, env_packages = _project(tmp_path)
    original = {
        path.relative_to(source_dir): path.read_bytes()
        for path in sorted(source_dir.rglob("*"))
        if path.is_file()
    }
    calls = []
    fetch_task, build_task = _tasks(paths, env_packages, _real_runner(env_packages, calls))
    package = ipkg_task(paths, build_task)

    assert fetch_task.executor(fetch_task, io.StringIO()) == 0
    assert build_task.executor(build_task, io.StringIO()) == 0

    assert "--pyconfig-silent" in calls[0][0]
    assert calls[1][0] == [str(env_packages.command), "--update"]
    assert calls[2][0][-1] == "install"
    assert fetch_task.run_class == "fetch"
    assert fetch_task.cache_policy == "never"
    assert fetch_task.command == ()
    assert build_task.deps == (fetch_task.id,)
    assert build_task.cache_policy == "never"
    assert build_task.command == ()
    assert calls[1][2]["ENV_ROOT"] == str(env_packages.env_root)
    assert calls[1][2]["PKGS_ROOT"] == str(env_packages.index.parent)
    assert calls[1][2]["RTT_ROOT"] == str(paths.root / "rt-thread")
    assert calls[1][2]["RTTHREAD_TOOLS_DIR"] == str(paths.root / "rt-thread" / "tools")

    isolated = fetch_task.workdir / "source"
    config = (isolated / ".config").read_text(encoding="utf-8")
    assert "CONFIG_PKG_USING_DEMO_ONLINE=y" in config
    assert 'CONFIG_PKG_DEMO_ONLINE_PATH="/misc/demo-online"' in config
    assert 'CONFIG_PKG_DEMO_ONLINE_VER="v1.0.0"' in config
    assert (isolated / "rtconfig.h").read_text(encoding="utf-8") == "/* generated */\n"
    assert (isolated / "packages" / "demo-online-v1.0.0" / "payload.txt").is_file()

    stage = paths.staging_dir / "packages" / "demo" / "share"
    payload = (stage / "demo.txt").read_text(encoding="utf-8")
    assert "int main(void)" in payload
    assert "LINKAGE=static" in payload
    assert "SMART_SDK_DIR=" in payload
    assert (stage / "online.txt").read_text(encoding="utf-8") == "downloaded online package\n"
    assert {
        path.relative_to(source_dir): path.read_bytes()
        for path in sorted(source_dir.rglob("*"))
        if path.is_file()
    } == original

    marker = json.loads(fetch_task.outputs[0].read_text(encoding="utf-8"))
    assert marker["packages"][0]["name"] == "DEMO_ONLINE"
    assert marker["packages"][0]["version"] == "v1.0.0"
    scons_manifest = build_task.manifest_fields["library"]["rtthread_scons"]
    assert scons_manifest["selection_symbol"] == "PKG_USING_DEMO_ONLINE"
    assert scons_manifest["online_packages"] == marker["packages"]

    assert package.executor(package, io.StringIO()) == 0
    rootfs = tmp_path / "installed-rootfs"
    records = install_ipkg(package.outputs[0], rootfs)
    assert (rootfs / "share" / "demo.txt").read_text(encoding="utf-8") == payload
    assert (rootfs / "share" / "online.txt").read_text(encoding="utf-8") == "downloaded online package\n"
    assert {record["path"] for record in records} == {"share/demo.txt", "share/online.txt"}


def test_rtthread_scons_rejects_unsupported_linkage(tmp_path):
    paths, _package_dir, _source_dir, env_packages = _project(tmp_path, linkage="dynamic")

    with pytest.raises(SmartBuildError, match="does not support linkage dynamic"):
        package_task(paths, "demo", toolchain=_Toolchain(), env_packages=env_packages)


def test_rtthread_scons_mixed_rootfs_uses_package_linkage(tmp_path):
    paths, _package_dir, _source_dir, env_packages = _project(tmp_path, linkage="mixed")

    _fetch_task, build_task = _tasks(paths, env_packages)

    package_manifest = build_task.manifest_fields["library"]["rtthread_scons"]
    assert package_manifest["linkage"] == "static"
    assert "LINKAGE=static" in package_manifest["command"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda text: text.replace("source/Kconfig", "../Kconfig"), "kconfig.source must be source/Kconfig"),
        (lambda text: text.replace("/share/demo.txt", "../demo.txt"), "unsafe RT-Thread SCons output path"),
        (
            lambda text: text.replace("install_target: install", "install_target: deploy"),
            "install_target must be install",
        ),
    ),
)
def test_rtthread_scons_rejects_invalid_contract(tmp_path, mutation, message):
    paths, package_dir, _source_dir, env_packages = _project(tmp_path)
    description_path = package_dir / "package.yaml"
    description_path.write_text(mutation(description_path.read_text(encoding="utf-8")), encoding="utf-8")
    description = _description(package_dir)

    with pytest.raises(SmartBuildError, match=message):
        metadata = normalize_package_metadata(description)
        parse_rtthread_scons_config(paths.root, description, metadata, env_packages=env_packages)


@pytest.mark.parametrize("missing", ("SConscript", "main.c"))
def test_rtthread_scons_rejects_missing_independent_source_entry(tmp_path, missing):
    paths, package_dir, source_dir, env_packages = _project(tmp_path)
    (source_dir / missing).unlink()
    description = _description(package_dir)
    metadata = normalize_package_metadata(description)

    with pytest.raises(SmartBuildError, match=f"independent source missing {missing}"):
        parse_rtthread_scons_config(paths.root, description, metadata, env_packages=env_packages)


def test_rtthread_scons_defers_rtthread_source_validation_to_fetch(tmp_path):
    paths, _package_dir, _source_dir, env_packages = _project(tmp_path)
    shutil.rmtree(paths.root / "rt-thread")
    fetch_task, _build_task = _tasks(paths, env_packages, lambda command, cwd, env: None)

    assert fetch_task.deps == ("toolchain:check", "source:rt-thread")
    with pytest.raises(SmartBuildError, match="RT-Thread source with tools directory not found"):
        fetch_task.executor(fetch_task, io.StringIO())


@pytest.mark.skipif(shutil.which("scons") is None, reason="SCons is required")
def test_rtthread_scons_reports_pyconfig_failure(tmp_path):
    paths, _package_dir, _source_dir, env_packages = _project(tmp_path)

    def failed(command, cwd, env):
        return subprocess.CompletedProcess(command, 2, stdout="failed\n")

    fetch_task, _build_task = _tasks(paths, env_packages, failed)
    with pytest.raises(SmartBuildError, match="SCons pyconfig failed"):
        fetch_task.executor(fetch_task, io.StringIO())


def test_rtthread_scons_reports_package_update_command_failure(tmp_path):
    paths, _package_dir, _source_dir, env_packages = _project(tmp_path)
    calls = []

    def runner(command, cwd, env):
        calls.append(command)
        if command == [str(env_packages.command), "--update"]:
            return subprocess.CompletedProcess(command, 2, stdout="failed\n")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n")

    fetch_task, _build_task = _tasks(paths, env_packages, runner)
    with pytest.raises(SmartBuildError, match="Env package update failed"):
        fetch_task.executor(fetch_task, io.StringIO())

    assert len(calls) == 2


def test_rtthread_scons_rejects_package_update_without_success(tmp_path):
    paths, _package_dir, _source_dir, env_packages = _project(tmp_path)

    def runner(command, cwd, env):
        if command == [str(env_packages.command), "--update"]:
            _write_package_state(Path(cwd))
            return subprocess.CompletedProcess(command, 0, stdout="Operation failed.\n")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n")

    fetch_task, _build_task = _tasks(paths, env_packages, runner)
    with pytest.raises(SmartBuildError, match="did not report success"):
        fetch_task.executor(fetch_task, io.StringIO())


@pytest.mark.parametrize(
    ("update", "message"),
    (
        (lambda project: _write_package_state(project, errors=[{"name": "DEMO_ONLINE"}]), "reported errors"),
        (lambda project: _write_package_state(project, installed=False), "not installed at its managed path"),
        (lambda project: _write_package_state(project, state=[]), "does not match the package .config"),
        (
            lambda project: _write_package_state(
                project,
                state=[{"name": "DEMO_ONLINE", "path": "/misc/demo-online", "ver": "../v1.0.0"}],
            ),
            "unsafe RT-Thread Env package version",
        ),
    ),
)
def test_rtthread_scons_rejects_invalid_online_package_state(tmp_path, update, message):
    paths, _package_dir, _source_dir, env_packages = _project(tmp_path)
    calls = []
    runner = _real_runner(env_packages, calls, update=update)
    fetch_task, _build_task = _tasks(paths, env_packages, runner)

    with pytest.raises(SmartBuildError, match=message):
        fetch_task.executor(fetch_task, io.StringIO())


@pytest.mark.skipif(shutil.which("scons") is None, reason="SCons is required")
def test_rtthread_scons_rejects_missing_declared_output(tmp_path):
    paths, _package_dir, _source_dir, env_packages = _project(tmp_path, output="/share/missing.txt")
    calls = []
    fetch_task, build_task = _tasks(paths, env_packages, _real_runner(env_packages, calls))
    fetch_task.executor(fetch_task, io.StringIO())

    with pytest.raises(SmartBuildError, match="did not create declared output"):
        build_task.executor(build_task, io.StringIO())


@pytest.mark.skipif(shutil.which("scons") is None, reason="SCons is required")
def test_rtthread_scons_rejects_undeclared_output(tmp_path):
    paths, _package_dir, source_dir, env_packages = _project(tmp_path)
    sconscript = source_dir / "SConscript"
    sconscript.write_text(
        sconscript.read_text(encoding="utf-8").replace(
            "Return('installed')",
            "\n".join(
                (
                    "extra = env.Command(env['DESTDIR'] + '/share/extra.txt', generated, Copy('$TARGET', '$SOURCE'))",
                    "Return('installed', 'extra')",
                )
            ),
        ),
        encoding="utf-8",
    )
    calls = []
    fetch_task, build_task = _tasks(paths, env_packages, _real_runner(env_packages, calls))
    fetch_task.executor(fetch_task, io.StringIO())

    with pytest.raises(SmartBuildError, match="created undeclared output"):
        build_task.executor(build_task, io.StringIO())


def _webclient_env_packages(tmp_path):
    env_root = tmp_path / "webclient-env"
    command = env_root / "tools" / "scripts" / "pkgs"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    command.chmod(0o755)
    package_root = env_root / "packages"
    index = package_root / "packages"
    index.mkdir(parents=True)
    (package_root / "Kconfig").write_text(
        'source "$PKGS_ROOT/packages/Kconfig"\n',
        encoding="utf-8",
    )
    (index / "Kconfig").write_text(
        "\n".join(
            (
                "menuconfig PKG_USING_WEBCLIENT",
                '    bool "webclient"',
                "",
                "if PKG_USING_WEBCLIENT",
                "config PKG_WEBCLIENT_PATH",
                "    string",
                '    default "/packages/iot/webclient"',
                "config PKG_WEBCLIENT_VER",
                "    string",
                '    default "v2.2.0"',
                "endif",
                "",
            )
        ),
        encoding="utf-8",
    )
    return EnvPackages(env_root=env_root, command=command, index=index)


def _webnet_env_packages(tmp_path):
    env_root = tmp_path / "webnet-env"
    command = env_root / "tools" / "scripts" / "pkgs"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    command.chmod(0o755)
    package_root = env_root / "packages"
    index = package_root / "packages"
    index.mkdir(parents=True)
    (package_root / "Kconfig").write_text(
        'source "$PKGS_ROOT/packages/Kconfig"\n',
        encoding="utf-8",
    )
    (index / "Kconfig").write_text(
        "\n".join(
            (
                "menuconfig PKG_USING_WEBNET",
                '    bool "webnet"',
                "",
                "if PKG_USING_WEBNET",
                "config PKG_WEBNET_PATH",
                "    string",
                '    default "/packages/iot/webnet"',
                "config WEBNET_PORT",
                "    int",
                "    default 80",
                "config WEBNET_CONN_MAX",
                "    int",
                "    default 16",
                "config WEBNET_ROOT",
                "    string",
                '    default "/webnet"',
                "config PKG_WEBNET_VER",
                "    string",
                '    default "v2.0.3"',
                "endif",
                "",
            )
        ),
        encoding="utf-8",
    )
    return EnvPackages(env_root=env_root, command=command, index=index)


def test_repository_webclient_example_matches_backend_contract(tmp_path):
    root = Path(__file__).resolve().parents[1]
    description = load_description(root / "packages" / "webclient" / "package.yaml")
    metadata = normalize_package_metadata(description)
    env_packages = _webclient_env_packages(tmp_path)
    config = parse_rtthread_scons_config(
        root,
        description,
        metadata,
        env_packages=env_packages,
    )
    kconf = load_native_package_kconfig(metadata, env_packages=env_packages)

    assert config.selection_symbol == "PACKAGE_WEBCLIENT"
    assert "PACKAGE_WEBCLIENT" in config.symbols
    assert "PKG_USING_WEBCLIENT" in config.symbols
    assert config.supported_linkage == ("static",)
    assert [path.as_posix() for path in config.outputs] == ["bin/webclient"]
    assert _visible_prompts(kconf.top_node.list) == ["webclient"]
    webclient_menu = _prompt_node(kconf.top_node.list, "webclient")
    assert _visible_prompts(webclient_menu.list)[0] == "Enable webclient"
    kconf.syms["PACKAGE_WEBCLIENT"].set_value(2)
    assert kconf.syms["PKG_USING_WEBCLIENT"].str_value == "y"
    assert (config.source_dir / "building.py").is_file()
    assert (description.path.parent / "README.md").is_file()


def test_repository_webnet_example_matches_backend_contract(tmp_path):
    root = Path(__file__).resolve().parents[1]
    description = load_description(root / "packages" / "webnet" / "package.yaml")
    metadata = normalize_package_metadata(description)
    env_packages = _webnet_env_packages(tmp_path)
    config = parse_rtthread_scons_config(
        root,
        description,
        metadata,
        env_packages=env_packages,
    )
    kconf = load_native_package_kconfig(metadata, env_packages=env_packages)

    assert config.selection_symbol == "PACKAGE_WEBNET"
    assert set(config.symbols) == {
        "PACKAGE_WEBNET",
        "PKG_USING_WEBNET",
        "PKG_WEBNET_PATH",
        "PKG_WEBNET_VER",
        "WEBNET_CONN_MAX",
        "WEBNET_PORT",
        "WEBNET_ROOT",
    }
    assert config.supported_linkage == ("static",)
    assert [path.as_posix() for path in config.outputs] == ["bin/webnet"]
    assert _visible_prompts(kconf.top_node.list) == ["webnet"]
    webnet_menu = _prompt_node(kconf.top_node.list, "webnet")
    assert _visible_prompts(webnet_menu.list)[0] == "Enable webnet"
    kconf.syms["PACKAGE_WEBNET"].set_value(2)
    assert kconf.syms["PKG_USING_WEBNET"].str_value == "y"
    assert (config.source_dir / "building.py").is_file()
    assert 'Export("env", "RTT_ROOT")' in (config.source_dir / "SConstruct").read_text(
        encoding="utf-8"
    )
    assert (description.path.parent / "README.md").is_file()


def test_rootfs_menu_exposes_selected_type_configuration(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    env_root = tmp_path / "env-packages"
    env_root.mkdir()
    (env_root / "Kconfig").write_text("", encoding="utf-8")
    monkeypatch.setenv("PKGS_ROOT", str(env_root))
    monkeypatch.setenv("PKGS_DIR", str(env_root))
    monkeypatch.setenv("srctree", str(root))

    kconf = kconfiglib.Kconfig(str(root / "rootfs" / "Kconfig"), warn=False)
    rootfs_menu = kconf.top_node.list

    assert rootfs_menu.prompt[0] == "Root filesystem"
    assert kconf.syms["PACKAGE_WEBCLIENT"].str_value == "n"
    assert kconf.syms["PACKAGE_WEBNET"].str_value == "n"
    assert _visible_prompts(rootfs_menu.list) == [
        "Root filesystem type",
        "Rootfs build mode",
        "Rootfs image format",
        "Rootfs image size",
        "Rootfs image size mode",
    ]


def _visible_prompts(node):
    prompts = []
    while node is not None:
        if node.prompt is not None and kconfiglib.expr_value(node.prompt[1]):
            prompts.append(node.prompt[0])
        node = node.next
    return prompts


def _prompt_node(node, prompt):
    while node is not None:
        if node.prompt is not None and node.prompt[0] == prompt:
            return node
        node = node.next
    raise AssertionError(f"Kconfig prompt not found: {prompt}")


@pytest.mark.skipif(shutil.which("scons") is None, reason="SCons is required")
def test_repository_webclient_example_runs_real_scons_pyconfig(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = root / "packages" / "webclient" / "source"
    isolated = tmp_path / "webclient"
    shutil.copytree(source, isolated)
    config = isolated / ".config"
    config.write_text(
        "\n".join(
            (
                "CONFIG_RT_VER_NUM=0x50100",
                "CONFIG_PACKAGE_WEBCLIENT=y",
                "CONFIG_PKG_USING_WEBCLIENT=y",
                'CONFIG_PKG_WEBCLIENT_PATH="/packages/iot/webclient"',
                'CONFIG_PKG_WEBCLIENT_VER="v2.2.0"',
                "",
            )
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["KCONFIG_CONFIG"] = str(config)

    completed = subprocess.run(
        [shutil.which("scons"), "--pyconfig-silent", "-C", str(isolated)],
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert completed.returncode == 0, completed.stdout
    package_header = (isolated / "pkg_config.h").read_text(encoding="utf-8")
    assert "#define PACKAGE_WEBCLIENT 1" in package_header
    assert "#define PKG_USING_WEBCLIENT 1" in package_header
    assert '#define PKG_WEBCLIENT_VER "v2.2.0"' in package_header
    assert (isolated / "rtconfig.h").is_file()


@pytest.mark.skipif(shutil.which("scons") is None, reason="SCons is required")
def test_repository_webnet_example_runs_real_scons_pyconfig(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = root / "packages" / "webnet" / "source"
    isolated = tmp_path / "webnet"
    shutil.copytree(source, isolated)
    config = isolated / ".config"
    config.write_text(
        "\n".join(
            (
                "CONFIG_RT_VER_NUM=0x50100",
                "CONFIG_PACKAGE_WEBNET=y",
                "CONFIG_PKG_USING_WEBNET=y",
                'CONFIG_PKG_WEBNET_PATH="/packages/iot/webnet"',
                "CONFIG_WEBNET_PORT=80",
                "CONFIG_WEBNET_CONN_MAX=16",
                'CONFIG_WEBNET_ROOT="/webnet"',
                'CONFIG_PKG_WEBNET_VER="v2.0.3"',
                "",
            )
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["KCONFIG_CONFIG"] = str(config)

    completed = subprocess.run(
        [shutil.which("scons"), "--pyconfig-silent", "-C", str(isolated)],
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert completed.returncode == 0, completed.stdout
    package_header = (isolated / "pkg_config.h").read_text(encoding="utf-8")
    assert "#define PACKAGE_WEBNET 1" in package_header
    assert "#define PKG_USING_WEBNET 1" in package_header
    assert "#define WEBNET_PORT 80" in package_header
    assert '#define WEBNET_ROOT "/webnet"' in package_header
    assert '#define PKG_WEBNET_VER "v2.0.3"' in package_header
    assert (isolated / "rtconfig.h").is_file()
