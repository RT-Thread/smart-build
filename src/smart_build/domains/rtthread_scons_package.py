import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

from ..cache import path_record
from ..config import load_defconfig, load_workspace_config, resolve_rootfs_selection
from ..env_packages import (
    EnvPackages,
    read_env_package_state,
    validate_package_update_output,
)
from ..errors import SmartBuildError
from ..paths import board_defconfig_path
from ..rtthread_scons import (
    command_env,
    parse_rtthread_scons_config,
    resolve_scons,
    scons_command,
    scons_pyconfig_command,
    select_linkage,
    write_package_config,
)
from ..tasks import Task
from .smart_sdk import smart_sdk_dir
from .sources import RT_THREAD_TASK_ID
from .toolchain import resolve_toolchain, toolchain_task_fields


GENERATED_SOURCE_ENTRIES = frozenset(
    (".config", ".sconsign.dblite", "build", "packages", "pkg_config.h", "rtconfig.h")
)


def rtthread_scons_package_task(
    paths,
    name,
    description,
    metadata,
    selected,
    toolchain=None,
    command_runner=None,
    env_packages=None,
):
    packages = (env_packages or EnvPackages.discover()).validate()
    config = parse_rtthread_scons_config(
        paths.root,
        description,
        metadata,
        env_packages=packages,
    )
    linkage = select_linkage(config, _effective_linkage(paths))
    sdk_dir = smart_sdk_dir(paths)
    rtt_root = paths.root / "rt-thread"

    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    scons, scons_version = resolve_scons()
    workdir = paths.work_dir / "packages" / name
    isolated_source = workdir / "source"
    build_dir = workdir / "build"
    config_path = isolated_source / ".config"
    staged_dir = paths.staging_dir / "packages" / name
    marker = paths.stamps_dir / "packages" / f"{name}-env-packages.json"
    _validate_managed_path(workdir, paths.work_dir, "package work directory")
    _validate_managed_path(staged_dir, paths.staging_dir, "package staging directory")
    _validate_managed_path(marker, paths.stamps_dir, "package Env marker")

    pyconfig_command = scons_pyconfig_command(scons, isolated_source)
    package_command = [str(packages.command), "--update"]
    build_command = scons_command(
        scons,
        isolated_source,
        build_dir,
        staged_dir,
        config_path,
        sdk_dir,
        resolved_toolchain.prefix,
        linkage,
    )
    output_paths = tuple(staged_dir.joinpath(*path.parts) for path in config.outputs)
    install_files = _install_files(staged_dir, config.outputs)
    manifest_key, manifest = _package_manifest(
        name,
        description,
        metadata,
        selected,
        config,
        install_files,
        isolated_source,
        build_dir,
        config_path,
        staged_dir,
        sdk_dir,
        rtt_root,
        linkage,
        scons,
        scons_version,
        build_command,
        marker,
    )
    config_inputs = [board_defconfig_path(paths.root, paths.machine)]
    workspace_config = paths.root / "build" / ".config"
    if workspace_config.is_file():
        config_inputs.append(workspace_config)
    source_inputs = _source_inputs(config.source_dir)
    base_env = {"MACHINE": paths.machine, **fields["env"]}
    fetch_task = Task(
        id=f"package:{name}:env-packages",
        domain="package",
        action="env-packages",
        inputs=[
            description.path,
            *source_inputs,
            packages.command,
            packages.index / "Kconfig",
            sdk_dir,
            rtt_root / "tools",
            *config_inputs,
        ],
        outputs=[marker],
        deps=["toolchain:check", RT_THREAD_TASK_ID],
        workdir=workdir,
        env=base_env,
        run_class="fetch",
        cache_policy="never",
        log_path=paths.logs_dir / f"package-{name}-env-packages.log",
        executor=_make_env_packages_executor(
            paths,
            name,
            config,
            metadata,
            packages,
            config_path,
            isolated_source,
            build_dir,
            staged_dir,
            sdk_dir,
            rtt_root,
            linkage,
            resolved_toolchain,
            pyconfig_command,
            package_command,
            command_runner,
        ),
        cache_extra={
            **fields["cache_extra"],
            "commands": [pyconfig_command, package_command],
            "env_packages": packages.manifest_record(),
            "selection_symbol": config.selection_symbol,
        },
        manifest_fields={
            **fields["manifest_fields"],
            "rtthread_scons_packages": {
                **packages.manifest_record(),
                "config": str(config_path),
                "state": str(isolated_source / "packages" / "pkgs.json"),
                "packages": [],
            },
        },
    )
    build_task = Task(
        id=f"package:{name}:build",
        domain="package",
        action="build",
        inputs=[description.path, marker],
        outputs=[staged_dir],
        deps=[fetch_task.id],
        workdir=workdir,
        env=base_env,
        run_class="build",
        cache_policy="never",
        log_path=paths.logs_dir / f"package-{name}-build.log",
        executor=_make_build_executor(
            name,
            config,
            packages,
            config_path,
            isolated_source,
            build_dir,
            staged_dir,
            output_paths,
            build_command,
            sdk_dir,
            rtt_root,
            linkage,
            resolved_toolchain,
            manifest_key,
            marker,
            command_runner,
        ),
        cache_extra={
            **fields["cache_extra"],
            manifest_key: deepcopy(manifest),
            "env_packages": packages.manifest_record(),
        },
        manifest_fields={
            **fields["manifest_fields"],
            manifest_key: manifest,
        },
    )
    return [fetch_task, build_task]


def _package_manifest(
    name,
    description,
    metadata,
    selected,
    config,
    install_files,
    isolated_source,
    build_dir,
    config_path,
    staged_dir,
    sdk_dir,
    rtt_root,
    linkage,
    scons,
    scons_version,
    build_command,
    marker,
):
    package_type = description.data.get("type")
    manifest = {
        "name": name,
        "description": str(description.path),
        "package_description": str(description.data.get("description", name)),
        "version": selected.version,
        "selected_options": dict(selected.options),
        "depends": ", ".join(metadata.depends),
        "provides": ", ".join(metadata.provides),
        "type": package_type,
        "build_system": "rtthread-scons",
        "source_dir": str(config.source_dir),
        "staged_dir": str(staged_dir),
        "install_files": install_files,
        "architecture_check": {"status": "pending"},
        "rtthread_scons": {
            "scons": str(scons),
            "scons_version": scons_version,
            "command": build_command,
            "source_copy": str(isolated_source),
            "build_dir": str(build_dir),
            "config": str(config_path),
            "kconfig": str(config.kconfig_path),
            "config_symbols": list(config.symbols),
            "selection_symbol": config.selection_symbol,
            "smart_sdk_dir": str(sdk_dir),
            "rtt_root": str(rtt_root),
            "linkage": linkage,
            "install_target": config.install_target,
            "outputs": [f"/{path.as_posix()}" for path in config.outputs],
            "env_packages_marker": str(marker),
            "online_packages": [],
        },
    }
    if package_type == "library":
        manifest["headers"] = [item["path"] for item in install_files if _is_header(item["path"])]
        manifest["libraries"] = [item["path"] for item in install_files if _is_library(item["path"])]
        return "library", manifest
    if package_type == "executable":
        manifest["install_path"] = install_files[0]["path"]
        manifest["smoke"] = _smoke_config(description)
        return "executable", manifest
    raise SmartBuildError("PACKAGE", f"{description.path}: package type must be library or executable")


def _make_env_packages_executor(
    paths,
    name,
    config,
    metadata,
    packages,
    config_path,
    isolated_source,
    build_dir,
    staged_dir,
    sdk_dir,
    rtt_root,
    linkage,
    toolchain,
    pyconfig_command,
    package_command,
    command_runner,
):
    runner = command_runner or _run_command

    def executor(task, log):
        packages.validate()
        _validate_environment_sources(sdk_dir, rtt_root)
        _replace_source_copy(config.source_dir, isolated_source)
        _replace_directory(build_dir)
        values = _package_config_values(paths)
        symbols = write_package_config(
            config_path,
            metadata,
            values,
            env_packages=packages,
        )
        env = _package_env(
            packages,
            task.env,
            build_dir,
            staged_dir,
            config_path,
            sdk_dir,
            rtt_root,
            toolchain.prefix,
            linkage,
        )
        _run_required_command(
            task,
            pyconfig_command,
            isolated_source,
            env,
            runner,
            log,
            "SCons pyconfig",
        )
        completed = _run_required_command(
            task,
            package_command,
            isolated_source,
            env,
            runner,
            log,
            "RT-Thread Env package update",
        )
        validate_package_update_output(completed)
        package_state = read_env_package_state(
            isolated_source,
            config_path=config_path,
            state_label=f"package {name} online package",
            config_label="the package .config",
        )
        record = {
            **packages.manifest_record(),
            "config": str(config_path),
            "config_sha256": path_record(config_path).get("sha256"),
            "config_symbols": list(symbols),
            "state": str(isolated_source / "packages" / "pkgs.json"),
            "packages": package_state,
        }
        task.manifest_fields["rtthread_scons_packages"] = record
        marker = task.outputs[0]
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log.write(f"wrote RT-Thread SCons package state: {marker}\n")
        return 0

    return executor


def _make_build_executor(
    name,
    config,
    packages,
    config_path,
    isolated_source,
    build_dir,
    staged_dir,
    output_paths,
    command,
    sdk_dir,
    rtt_root,
    linkage,
    toolchain,
    manifest_key,
    marker,
    command_runner,
):
    runner = command_runner or _run_command

    def executor(task, log):
        package_record = _read_marker(marker)
        _validate_prepared_source(isolated_source, config_path)
        _replace_directory(staged_dir)
        env = _package_env(
            packages,
            task.env,
            build_dir,
            staged_dir,
            config_path,
            sdk_dir,
            rtt_root,
            toolchain.prefix,
            linkage,
        )
        _run_required_command(
            task,
            command,
            isolated_source,
            env,
            runner,
            log,
            "SCons build",
        )
        install_files = _require_declared_outputs(staged_dir, config.outputs)
        checks = _architecture_checks(
            toolchain,
            output_paths,
            staged_dir,
            runner,
            build_dir,
            env,
            log,
        )
        manifest = task.manifest_fields[manifest_key]
        manifest["install_files"] = install_files
        manifest["architecture_check"] = _architecture_manifest(checks)
        manifest["rtthread_scons"]["online_packages"] = package_record["packages"]
        log.write(f"staged RT-Thread SCons package: {staged_dir}\n")
        return 0

    return executor


def _package_env(
    packages,
    base_env,
    build_dir,
    staged_dir,
    config_path,
    sdk_dir,
    rtt_root,
    cross_compile,
    linkage,
):
    env = command_env(
        base_env,
        build_dir,
        staged_dir,
        config_path,
        sdk_dir,
        rtt_root,
        cross_compile,
        linkage,
    )
    return packages.environment(env)


def _run_required_command(task, command, cwd, env, runner, log, label):
    completed = runner(list(command), cwd=cwd, env=env)
    _write_completed_command(log, command, cwd, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "BUILD",
            f"package task {task.id} {label} failed: exit code {completed.returncode} log={task.log_path}",
        )
    return completed


def _effective_linkage(paths):
    if not board_defconfig_path(paths.root, paths.machine).is_file():
        return "mixed"
    return resolve_rootfs_selection(paths.root, paths.machine).build_mode or "mixed"


def _package_config_values(paths):
    path = board_defconfig_path(paths.root, paths.machine)
    values = load_defconfig(path) if path.is_file() else {}
    workspace = load_workspace_config(paths.root)
    if workspace.get("MACHINE") == paths.machine:
        values.update(workspace)
    return values


def _source_inputs(source_dir):
    result = []
    for path in sorted(Path(source_dir).rglob("*")):
        relative = path.relative_to(source_dir)
        if relative.parts and relative.parts[0] in GENERATED_SOURCE_ENTRIES:
            continue
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_file():
            result.append(path)
    return result


def _replace_source_copy(source, destination):
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise SmartBuildError("BUILD", f"refusing unsafe isolated source path: {destination}")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, ignore=_ignore_generated_source_entries)


def _ignore_generated_source_entries(directory, names):
    ignored = {name for name in names if name in GENERATED_SOURCE_ENTRIES or name.startswith(".sconsign")}
    ignored.update(name for name in names if name == "__pycache__" or name.endswith((".pyc", ".pyo")))
    return ignored


def _replace_directory(path):
    candidate = Path(path)
    if candidate.exists() or candidate.is_symlink():
        if candidate.is_symlink() or not candidate.is_dir():
            raise SmartBuildError("BUILD", f"refusing unsafe managed directory: {candidate}")
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True)


def _validate_environment_sources(sdk_dir, rtt_root):
    if Path(sdk_dir).is_symlink() or not Path(sdk_dir).is_dir():
        raise SmartBuildError("SOURCE", f"smart-sdk package not found: {sdk_dir}")
    if not Path(rtt_root).is_dir() or not (Path(rtt_root) / "tools").is_dir():
        raise SmartBuildError(
            "SOURCE",
            f"RT-Thread source with tools directory not found: {rtt_root}",
        )


def _validate_prepared_source(source_dir, config_path):
    for path in (
        Path(source_dir) / "SConstruct",
        Path(source_dir) / "SConscript",
        Path(config_path),
        Path(source_dir) / "packages" / "SConscript",
        Path(source_dir) / "packages" / "pkgs.json",
    ):
        if not path.is_file():
            raise SmartBuildError("BUILD", f"prepared RT-Thread SCons package input not found: {path}")


def _read_marker(path):
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmartBuildError("BUILD", f"failed to read RT-Thread SCons package marker {path}: {exc}") from exc
    if not isinstance(record, dict) or not isinstance(record.get("packages"), list):
        raise SmartBuildError("BUILD", f"invalid RT-Thread SCons package marker: {path}")
    return record


def _require_declared_outputs(staged_dir, outputs):
    expected = {Path(staged_dir).joinpath(*path.parts).resolve(strict=False) for path in outputs}
    actual = set()
    for path in sorted(Path(staged_dir).rglob("*")):
        if path.is_symlink():
            raise SmartBuildError("BUILD", f"refusing symlink SCons package output: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SmartBuildError("BUILD", f"unsupported SCons package output: {path}")
        file_stat = path.stat()
        if file_stat.st_nlink > 1:
            raise SmartBuildError("BUILD", f"refusing hardlink SCons package output: {path}")
        relative = path.relative_to(staged_dir)
        path.chmod(_default_mode(relative))
        actual.add(path.resolve())
    missing = sorted(expected - actual)
    if missing:
        raise SmartBuildError("BUILD", f"SCons package did not create declared output: {missing[0]}")
    undeclared = sorted(actual - expected)
    if undeclared:
        raise SmartBuildError("BUILD", f"SCons package created undeclared output: {undeclared[0]}")
    return _install_files(staged_dir, outputs)


def _install_files(staged_dir, outputs):
    result = []
    for output in outputs:
        source = Path(staged_dir).joinpath(*output.parts)
        mode = source.stat().st_mode & 0o777 if source.is_file() else _default_mode(output)
        result.append(
            {
                "source": str(source),
                "path": f"/{output.as_posix()}",
                "mode": mode,
            }
        )
    return result


def _default_mode(path):
    value = f"/{path.as_posix()}"
    return 0o755 if "/bin/" in value or "/sbin/" in value or _is_shared_library(value) else 0o644


def _architecture_checks(toolchain, outputs, staged_dir, runner, workdir, env, log):
    from .package import _verify_binary_architecture, _verify_library_output_architecture

    checks = []
    for output in outputs:
        path = f"/{output.relative_to(staged_dir).as_posix()}"
        if path.endswith(".a"):
            checks.append(_verify_library_output_architecture(toolchain, output, runner, workdir, env, log))
        elif _is_shared_library(path) or "/bin/" in path or "/sbin/" in path:
            checks.append(_verify_binary_architecture(toolchain, output, runner, workdir, env, log))
    return checks


def _architecture_manifest(checks):
    if not checks:
        return {"status": "skipped", "reason": "no executable or library outputs"}
    if len(checks) == 1:
        return checks[0]
    return {"status": "verified", "checks": checks}


def _validate_managed_path(path, root, label):
    root_path = Path(root).resolve()
    candidate = Path(path)
    try:
        candidate.resolve(strict=False).relative_to(root_path)
    except ValueError as exc:
        raise SmartBuildError("BUILD", f"{label} escapes managed root: {candidate}") from exc
    if candidate.is_symlink():
        raise SmartBuildError("BUILD", f"refusing symlink {label}: {candidate}")


def _smoke_config(description):
    smoke = description.data.get("smoke", {})
    if not smoke:
        return {}
    if not isinstance(smoke, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: smoke must be a mapping")
    command = smoke.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise SmartBuildError("PACKAGE", f"{description.path}: smoke.command must be a non-empty string list")
    expected_stdout = smoke.get("expected_stdout", "")
    if not isinstance(expected_stdout, str):
        raise SmartBuildError("PACKAGE", f"{description.path}: smoke.expected_stdout must be a string")
    return {"command": list(command), "expected_stdout": expected_stdout}


def _is_header(path):
    return "/include/" in path or path.endswith((".h", ".hpp"))


def _is_library(path):
    return "/lib/" in path or path.endswith((".a", ".so"))


def _is_shared_library(path):
    return path.endswith(".so") or ".so." in path


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
        raise SmartBuildError("BUILD", f"failed to run SCons package command {command}: {exc}") from exc


def _write_completed_command(log, command, cwd, completed):
    log.write(f"command: {' '.join(str(part) for part in command)}\n")
    log.write(f"workdir: {cwd}\n")
    if completed.stdout:
        log.write(completed.stdout)
        if not completed.stdout.endswith("\n"):
            log.write("\n")
    log.write(f"exit: {completed.returncode}\n")
