import json
import os
import shutil
import subprocess
from pathlib import Path

from ..cache import path_record
from ..config import load_defconfig
from ..configure import (
    ConfigurationSpec,
    ConfigurationSync,
    execute_configuration,
    toolchain_configuration_env,
)
from ..env_packages import (
    EnvPackages,
    read_env_package_state,
    validate_package_update_output,
)
from ..errors import SmartBuildError
from ..machines import load_machine
from ..paths import board_defconfig_path, board_kernel_overlay_dir
from ..tasks import Task
from .sources import RT_THREAD_TASK_ID
from .toolchain import toolchain_task_fields


KERNEL_PACKAGE_TASK_ID = "kernel:packages:update"
KERNEL_TASK_ID = "kernel:build"


def kernel_tasks(paths, toolchain=None, command_runner=None, env_packages=None):
    context = _resolve_kernel_context(paths)
    packages = (env_packages or EnvPackages.discover()).validate()
    fields = toolchain_task_fields(toolchain)
    package_commands = _package_commands(context["bsp"], packages)
    build_commands = _build_commands(context["bsp"])
    package_manifest = {
        **packages.manifest_record(),
        "config": str(context["bsp"] / ".config"),
        "state": str(context["bsp"] / "packages" / "pkgs.json"),
        "packages": [],
    }
    common_env = {"MACHINE": paths.machine, **fields["env"]}
    package_task = Task(
        id=KERNEL_PACKAGE_TASK_ID,
        domain="kernel",
        action="packages-update",
        inputs=[
            context["defconfig"],
            context["bsp"] / "SConstruct",
            packages.command,
            packages.index / "Kconfig",
        ],
        outputs=[paths.stamps_dir / "kernel-packages.ok"],
        deps=["toolchain:check", RT_THREAD_TASK_ID],
        workdir=paths.work_dir / "kernel-packages",
        env=common_env,
        run_class="serial",
        cache_policy="never",
        log_path=paths.logs_dir / "kernel-packages.log",
        executor=_make_package_executor(context, packages, package_commands, command_runner),
        cache_extra={
            **fields["cache_extra"],
            "defconfig": path_record(context["defconfig"]),
            "commands": [list(command) for command in package_commands],
            "env_packages": packages.manifest_record(),
        },
        manifest_fields={
            **fields["manifest_fields"],
            "kernel_packages": package_manifest,
        },
    )
    kernel_manifest = {
        **fields["manifest_fields"],
        "source": _source_record(context["source"]),
        "bsp": str(context["bsp"]),
        "defconfig": str(context["defconfig"]),
        "commands": [list(command) for command in build_commands],
        "overlays": _overlay_manifest(context),
    }
    kernel_task = Task(
        id=KERNEL_TASK_ID,
        domain="kernel",
        action="build",
        inputs=[
            context["defconfig"],
            context["bsp"] / "SConstruct",
            *_overlay_inputs(context),
        ],
        outputs=[paths.images_dir / "rtthread.bin"],
        deps=[KERNEL_PACKAGE_TASK_ID],
        workdir=paths.work_dir / "kernel-build",
        env=common_env,
        run_class="build",
        cache_policy="never",
        log_path=paths.logs_dir / "kernel-build.log",
        executor=_make_kernel_executor(context, build_commands, command_runner),
        cache_extra={
            **fields["cache_extra"],
            "source": kernel_manifest["source"],
            "bsp": str(context["bsp"]),
            "defconfig": path_record(context["defconfig"]),
            "commands": kernel_manifest["commands"],
        },
        manifest_fields=kernel_manifest,
    )
    return [package_task, kernel_task]


def kernel_configuration(paths, toolchain=None, command_runner=None):
    context = _resolve_kernel_context(paths)
    packages = EnvPackages.discover().validate()
    _validate_kernel_context(context)
    resolved_toolchain = toolchain
    if resolved_toolchain is None:
        from .toolchain import resolve_toolchain

        resolved_toolchain = resolve_toolchain(machine=load_machine(paths.root, paths.machine))
    env = toolchain_configuration_env(
        paths,
        resolved_toolchain,
        SMART_BUILD_SOURCE_DIR=context["source"],
        SMART_BUILD_WORK_DIR=context["bsp"],
        SMART_BUILD_BSP_DIR=context["bsp"],
        SMART_BUILD_CONFIG_PATH=context["defconfig"],
    )
    spec = ConfigurationSpec(
        target="kernel",
        command=("scons", "--menuconfig"),
        workdir=context["bsp"],
        env=packages.environment(env),
        sync=(
            ConfigurationSync(
                source=context["bsp"] / ".config",
                destination=context["defconfig"],
            ),
        ),
    )
    return execute_configuration(spec, command_runner=command_runner)


def _make_package_executor(context, packages, commands, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        _validate_kernel_context(context)
        packages.validate()
        _copy_defconfig(context["defconfig"], context["bsp"] / ".config", log)
        env = packages.environment(_kernel_env(task.env))
        env["BSP_DIR"] = str(context["bsp"])
        completed = _run_commands(task, commands, context["bsp"], env, runner, log)
        validate_package_update_output(completed[-1])
        package_state = _read_package_state(context["bsp"])
        record = {
            **packages.manifest_record(),
            "config": str(context["bsp"] / ".config"),
            "state": str(context["bsp"] / "packages" / "pkgs.json"),
            "packages": package_state,
        }
        task.manifest_fields["kernel_packages"] = record
        marker = task.outputs[0]
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log.write(f"wrote kernel package state: {marker}\n")
        return 0

    return executor


def _make_kernel_executor(context, commands, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        _validate_kernel_context(context)
        overlay_manifest = _apply_machine_overlays(context, log)
        _run_commands(task, commands, context["bsp"], _kernel_env(task.env), runner, log)

        source_bin = context["bsp"] / "rtthread.bin"
        if not source_bin.is_file():
            raise SmartBuildError("BUILD", f"kernel build did not create rtthread.bin: {source_bin}")
        output = task.outputs[0]
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_bin, output)
        log.write(f"installed rtthread.bin: {output}\n")
        task.manifest_fields["source"] = _source_record(context["source"])
        task.manifest_fields["artifact"] = {
            "path": str(output),
            "sha256": path_record(output).get("sha256"),
        }
        task.manifest_fields["overlays"] = overlay_manifest
        return 0

    return executor


def _resolve_kernel_context(paths):
    source = paths.root / "rt-thread"
    machine = load_machine(paths.root, paths.machine)
    config_values = load_defconfig(board_defconfig_path(paths.root, paths.machine))
    defconfig = machine.kernel_defconfig
    bsp = source / "bsp" / _kernel_bsp(paths, config_values, machine)
    return {
        "source": source,
        "bsp": bsp,
        "defconfig": defconfig,
        "overlay_dir": board_kernel_overlay_dir(paths.root, paths.machine),
    }


def _validate_kernel_context(context):
    source = context["source"]
    bsp = context["bsp"]
    defconfig = context["defconfig"]
    if not source.is_dir() or not (source / "bsp").is_dir():
        raise SmartBuildError("SOURCE", f"RT-Thread source missing bsp directory: {source}")
    if not bsp.is_dir() or not (bsp / "SConstruct").is_file():
        raise SmartBuildError("SOURCE", f"RT-Thread BSP missing SConstruct: {bsp}")
    if not defconfig.is_file():
        raise SmartBuildError("SOURCE", f"kernel defconfig not found: {defconfig}")


def _kernel_bsp(paths, config_values, machine):
    config_bsp = config_values.get("BSP", "").strip()
    if not config_bsp:
        raise SmartBuildError("CONFIG", f"machine defconfig missing BSP: {paths.machine}")
    if config_bsp != machine.bsp:
        raise SmartBuildError(
            "CONFIG",
            "machine {machine} BSP mismatch: metadata uses {metadata_bsp}, "
            "defconfig uses {config_bsp}".format(
                machine=paths.machine,
                metadata_bsp=machine.bsp,
                config_bsp=config_bsp,
            ),
        )
    return machine.bsp


def _copy_defconfig(source, destination, log):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    log.write(f"copied defconfig: {source} -> {destination}\n")


def _apply_machine_overlays(context, log):
    overlay_dir = context["overlay_dir"]
    manifest = _overlay_manifest(context)
    if not overlay_dir.is_dir():
        return manifest

    sources = sorted(path for path in overlay_dir.rglob("*") if path.is_file())
    for source in sources:
        relative = source.relative_to(overlay_dir)
        if relative.parts and relative.parts[0] == "packages":
            raise SmartBuildError(
                "CONFIG",
                f"kernel overlay must not modify Env-managed packages: {source}",
            )
    for source in sources:
        relative = source.relative_to(overlay_dir)
        destination = context["bsp"] / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest["files"].append(
            {
                "source": str(source),
                "destination": str(destination),
                "sha256": path_record(destination).get("sha256"),
            }
        )
        log.write(f"applied kernel overlay: {source} -> {destination}\n")
    return manifest


def _overlay_inputs(context):
    overlay_dir = context["overlay_dir"]
    if not overlay_dir.is_dir():
        return []
    return sorted(path for path in overlay_dir.rglob("*") if path.is_file())


def _overlay_manifest(context):
    return {"source_dir": str(context["overlay_dir"]), "files": []}


def _package_commands(bsp, packages):
    return (
        ("scons", "--pyconfig-silent", "-C", str(bsp)),
        (str(packages.command), "--update"),
    )


def _build_commands(bsp):
    return (("scons", "-C", str(bsp)),)


def _read_package_state(bsp):
    return read_env_package_state(
        bsp,
        state_label="kernel package",
        config_label="the BSP .config",
    )


def _run_commands(task, commands, cwd, env, runner, log):
    results = []
    for command in commands:
        completed = runner(list(command), cwd=cwd, env=env)
        _write_completed_command(log, command, cwd, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "BUILD",
                "task {task_id} command failed: command={command} workdir={workdir} "
                "exit code {exit_code} log={log_path}".format(
                    task_id=task.id,
                    command=" ".join(str(part) for part in command),
                    workdir=cwd,
                    exit_code=completed.returncode,
                    log_path=task.log_path,
                ),
            )
        results.append(completed)
    return results


def _kernel_env(task_env):
    env = os.environ.copy()
    env.update({key: str(value) for key, value in task_env.items()})
    for key in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"):
        env.pop(key, None)
    return env


def _run_command(command, cwd, env):
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise SmartBuildError("BUILD", f"failed to run kernel command {command}: {exc}") from exc


def _write_completed_command(log, command, cwd, completed):
    log.write(f"command: {' '.join(str(part) for part in command)}\n")
    log.write(f"workdir: {cwd}\n")
    log.write("summary: command started\n")
    if completed.stdout:
        log.write(completed.stdout)
        if not completed.stdout.endswith("\n"):
            log.write("\n")
    log.write(f"summary: command exit={completed.returncode}\n")
    log.write(f"exit: {completed.returncode}\n")


def _source_record(source):
    record = {"path": str(source), "dirty": None, "revision": None, "git_root": None}
    if not source.exists():
        return record
    git_root = _git_output(source, "rev-parse", "--show-toplevel")
    if not git_root:
        return record
    dirty = _git_output(source, "status", "--porcelain")
    revision = _git_output(source, "rev-parse", "HEAD")
    record["dirty"] = bool(dirty.strip()) if dirty is not None else None
    record["revision"] = revision.strip() if revision else None
    record["git_root"] = git_root.strip()
    return record


def _git_output(path, *args):
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout
