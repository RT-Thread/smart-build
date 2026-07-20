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
from ..errors import SmartBuildError
from ..machines import load_machine
from ..paths import board_defconfig_path, board_kernel_overlay_dir
from ..tasks import Task
from .sources import RT_THREAD_TASK_ID, prepare_lwext4_bsp_package
from .toolchain import toolchain_task_fields


KERNEL_TASK_ID = "kernel:build"
LWEXT4_CONFIG_KEYS = (
    "CONFIG_PKG_USING_LWEXT4=y",
    "CONFIG_RT_USING_DFS_LWEXT4=y",
)


def kernel_tasks(paths, toolchain=None, command_runner=None):
    context = _resolve_kernel_context(paths)
    fields = toolchain_task_fields(toolchain)
    commands = _scons_commands(context["bsp"])
    deps = ["toolchain:check", RT_THREAD_TASK_ID]
    if context["lwext4_enabled"]:
        deps.append("source:lwext4")
    manifest_fields = {
        **fields["manifest_fields"],
        "source": _source_record(context["source"]),
        "bsp": str(context["bsp"]),
        "defconfig": str(context["defconfig"]),
        "commands": [list(command) for command in commands],
        "lwext4": _lwext4_manifest(context),
        "overlays": _overlay_manifest(context),
    }
    cache_extra = {
        **fields["cache_extra"],
        "source": manifest_fields["source"],
        "bsp": str(context["bsp"]),
        "defconfig": path_record(context["defconfig"]),
        "commands": manifest_fields["commands"],
    }
    executor = _make_kernel_executor(paths, context, commands, command_runner)
    return [
        Task(
            id=KERNEL_TASK_ID,
            domain="kernel",
            action="build",
            inputs=[context["defconfig"], context["bsp"] / "SConstruct"],
            outputs=[paths.images_dir / "rtthread.bin"],
            deps=deps,
            workdir=paths.work_dir / "kernel-build",
            env={"MACHINE": paths.machine, **fields["env"]},
            run_class="build",
            cache_policy="never",
            log_path=paths.logs_dir / "kernel-build.log",
            executor=executor,
            cache_extra=cache_extra,
            manifest_fields=manifest_fields,
        )
    ]


def kernel_configuration(paths, toolchain=None, command_runner=None):
    context = _resolve_kernel_context(paths)
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
        env=env,
        sync=(
            ConfigurationSync(
                source=context["bsp"] / ".config",
                destination=context["defconfig"],
            ),
        ),
    )
    return execute_configuration(spec, command_runner=command_runner)


def _make_kernel_executor(paths, context, commands, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        _validate_kernel_context(context)
        _copy_defconfig(context["defconfig"], context["bsp"] / ".config", log)
        lwext4_state = _prepare_lwext4(paths, context, log)
        overlay_manifest = _apply_machine_overlays(context, log)
        env = _kernel_env(task.env)

        for command in commands:
            completed = runner(list(command), cwd=context["bsp"], env=env)
            _write_completed_command(log, command, context["bsp"], completed)
            if completed.returncode != 0:
                _raise_kernel_command_error(task, command, completed, lwext4_state)

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
        task.manifest_fields["lwext4"] = lwext4_state["manifest"]
        task.manifest_fields["overlays"] = overlay_manifest
        return 0

    return executor


def _resolve_kernel_context(paths):
    source = paths.root / "rt-thread"
    machine = load_machine(paths.root, paths.machine)
    config_values = load_defconfig(board_defconfig_path(paths.root, paths.machine))
    package_dir = paths.root / "packages" / "rt-thread"
    defconfig = machine.kernel_defconfig
    bsp_name = _kernel_bsp(paths, config_values, machine)
    bsp = source / "bsp" / bsp_name
    overlay_dir = board_kernel_overlay_dir(paths.root, paths.machine)
    return {
        "source": source,
        "bsp": bsp,
        "defconfig": defconfig,
        "lwext4_enabled": kernel_defconfig_enables_lwext4(defconfig),
        "lwext4_package_dir": bsp / "packages" / "lwext4-latest",
        "lwext4_package_sconscript": package_dir / "lwext4_SConscript",
        "overlay_dir": overlay_dir,
    }


def _validate_kernel_context(context):
    source = context["source"]
    bsp = context["bsp"]
    defconfig = context["defconfig"]
    if not source.is_dir():
        raise SmartBuildError("SOURCE", f"RT-Thread source not found: {source}")
    if not (source / "bsp").is_dir():
        raise SmartBuildError("SOURCE", f"RT-Thread source missing bsp directory: {source}")
    if not bsp.is_dir():
        raise SmartBuildError("SOURCE", f"RT-Thread BSP path not found: {bsp}")
    if not (bsp / "SConstruct").is_file():
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


def _prepare_lwext4(paths, context, log):
    package_dir = context["lwext4_package_dir"]
    enabled = context["lwext4_enabled"]
    manifest = _lwext4_manifest(context)
    manifest["enabled_in_defconfig"] = enabled
    if not enabled:
        return {"available": False, "manifest": manifest}
    try:
        package_manifest = prepare_lwext4_bsp_package(
            paths,
            package_dir,
            log,
            package_sconscript_source=context["lwext4_package_sconscript"],
        )
    except SmartBuildError as exc:
        if exc.code == "SOURCE":
            raise SmartBuildError(
                "SOURCE",
                "lwext4 source not found; required by kernel defconfig; "
                f"expected BSP package {package_dir}: {exc}",
            ) from exc
        raise
    manifest.update(package_manifest)
    return {"available": True, "manifest": manifest}


def _apply_machine_overlays(context, log):
    overlay_dir = context["overlay_dir"]
    manifest = _overlay_manifest(context)
    if not overlay_dir.is_dir():
        return manifest

    for source in sorted(path for path in overlay_dir.rglob("*") if path.is_file()):
        relative = source.relative_to(overlay_dir)
        destination = context["bsp"] / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        record = {
            "source": str(source),
            "destination": str(destination),
            "sha256": path_record(destination).get("sha256"),
        }
        manifest["files"].append(record)
        log.write(f"applied kernel overlay: {source} -> {destination}\n")
    return manifest


def _overlay_manifest(context):
    return {
        "source_dir": str(context["overlay_dir"]),
        "files": [],
    }


def _lwext4_manifest(context):
    return {
        "enabled_in_defconfig": None,
        "package_dir": str(context["lwext4_package_dir"]),
        "package_sconscript_source": str(context["lwext4_package_sconscript"]),
        "prepared": False,
        "prepared_source": None,
        "already_present": context["lwext4_package_dir"].is_dir(),
    }


def kernel_defconfig_enables_lwext4(defconfig):
    try:
        text = Path(defconfig).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(key in text for key in LWEXT4_CONFIG_KEYS)


def _scons_commands(bsp):
    return (
        ("scons", "--pyconfig-silent", "-C", str(bsp)),
        ("scons", "-C", str(bsp)),
    )


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
    log.write(f"command: {' '.join(command)}\n")
    log.write(f"workdir: {cwd}\n")
    log.write("summary: command started\n")
    if completed.stdout:
        log.write(completed.stdout)
        if not completed.stdout.endswith("\n"):
            log.write("\n")
    log.write(f"summary: command exit={completed.returncode}\n")
    log.write(f"exit: {completed.returncode}\n")


def _raise_kernel_command_error(task, command, completed, lwext4_state):
    output = completed.stdout or ""
    manifest = lwext4_state["manifest"]
    if (
        manifest["enabled_in_defconfig"]
        and not lwext4_state["available"]
        and ("lwext4" in output or "packages/" in output or "SConscript" in output)
    ):
        searched = ", ".join(manifest["source_candidates"])
        raise SmartBuildError(
            "SOURCE",
            "lwext4 source not found for enabled kernel config; "
            f"expected BSP package {manifest['package_dir']}; searched: {searched}",
        )
    raise SmartBuildError(
        "BUILD",
        "task {task_id} command failed: command={command} workdir={workdir} "
        "exit code {exit_code} log={log_path}".format(
            task_id=task.id,
            command=" ".join(command),
            workdir=task.workdir,
            exit_code=completed.returncode,
            log_path=task.log_path,
        ),
    )


def _source_record(source):
    record = {
        "path": str(source),
        "dirty": None,
        "revision": None,
        "git_root": None,
    }
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
