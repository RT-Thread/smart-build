import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path, PurePosixPath

from ..config import resolve_rootfs_selection
from ..descriptions import load_description
from ..errors import SmartBuildError
from ..package_metadata import package_description_path
from ..package_extensions import load_package_extension
from ..paths import rootfs_description_path, validate_safe_name
from ..tasks import Task
from .toolchain import resolve_toolchain, toolchain_task_fields


APP_STAGE_DIR = "apps"


def app_tasks(paths, toolchain=None, app_names=None, command_runner=None):
    names = list(app_names) if app_names is not None else selected_rootfs_app_names(paths)
    return [
        app_task(paths, name, toolchain=toolchain, command_runner=command_runner)
        for name in names
    ]


def app_task(paths, app_name, toolchain=None, command_runner=None):
    name = validate_safe_name(app_name, "app")
    description = _load_package_description(paths, name)
    linkage = _package_linkage(description)
    source = _package_source_path(paths, description, name)
    install_path = _package_install_path(description)
    version = str(description.data.get("version", "0.1.0"))
    depends = _package_depends(description)
    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    work_output = paths.work_dir / APP_STAGE_DIR / name / name
    staged_output = paths.staging_dir / APP_STAGE_DIR / name
    command = _compile_command(resolved_toolchain, linkage, source, work_output)
    base_env = {"MACHINE": paths.machine, **fields["env"]}
    extension = load_package_extension(
        paths.root,
        description,
        _extension_context(name, description, source, install_path, depends, command, paths),
    )
    extension_record = None
    extension_env = {}
    if extension is not None:
        extension_record = extension.manifest_record()
        delta = extension.delta
        depends = _merge_depends(depends, delta.get("depends", ""))
        extension_env = {key: str(value) for key, value in delta.get("env", {}).items()}
        _reject_env_collisions(description.path, extension_env, base_env)
        install_path = _extension_install_path(description, delta, install_path)
        command = _apply_command_delta(command, delta.get("command", {}))
    manifest_app = {
        "name": name,
        "description": str(description.path),
        "package_description": description.data.get("description", name),
        "version": version,
        "depends": depends,
        "source": str(source),
        "linkage": linkage,
        "install_path": f"/{install_path.as_posix()}",
        "staged_output": str(staged_output),
        "command": command,
    }
    if extension_record is not None:
        manifest_app["extension"] = extension_record
    cache_app = deepcopy(manifest_app)

    return Task(
        id=f"app:{name}:build",
        domain="app",
        action="build",
        inputs=[description.path, source],
        outputs=[staged_output],
        deps=["toolchain:check"],
        workdir=work_output.parent,
        env={**base_env, **extension_env},
        run_class="build",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"app-{name}-build.log",
        executor=_make_app_executor(command, work_output, command_runner),
        cache_extra={
            **fields["cache_extra"],
            "app": cache_app,
        },
        manifest_fields={
            **fields["manifest_fields"],
            "app": manifest_app,
        },
    )


def minimal_rootfs_app_names(paths, profile=None):
    description = load_description(rootfs_description_path(paths.root, "minimal"))
    if description.kind != "rootfs" or description.name != "minimal":
        raise SmartBuildError("ROOTFS", f"{description.path}: expected rootfs description named minimal")
    packages = _rootfs_profile_packages(description, profile)
    if not isinstance(packages, list) or not packages:
        raise SmartBuildError("ROOTFS", f"{description.path}: packages must be a non-empty list")
    names = []
    for package in packages:
        if not isinstance(package, str):
            raise SmartBuildError("ROOTFS", f"{description.path}: package names must be strings")
        names.append(validate_safe_name(package, "package"))
    return names


def selected_rootfs_app_names(paths):
    selection = resolve_rootfs_selection(paths.root, paths.machine)
    if selection.rootfs == "none":
        return []
    names = []
    for package in selection.packages:
        name = validate_safe_name(package, "package")
        description = _load_package_description(paths, name)
        if description.data.get("type") not in {"library", "executable"}:
            names.append(name)
    return names


def _rootfs_profile_packages(description, profile):
    if "profiles" not in description.data:
        return description.data.get("packages", [])

    profiles = description.data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise SmartBuildError("ROOTFS", f"{description.path}: profiles must be a non-empty mapping")
    selected = profile or description.data.get("default_profile")
    if not isinstance(selected, str) or not selected:
        raise SmartBuildError("ROOTFS", f"{description.path}: default_profile must be a non-empty string")
    profile_data = profiles.get(selected)
    if not isinstance(profile_data, dict):
        raise SmartBuildError("ROOTFS", f"{description.path}: unknown rootfs profile: {selected}")
    return profile_data.get("packages", [])


def _make_app_executor(command, work_output, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        source = Path(task.manifest_fields["app"]["source"])
        if not source.is_file():
            raise SmartBuildError("PACKAGE", f"app source not found: {source}")
        if source.resolve().is_relative_to(Path(task.workdir).resolve()):
            raise SmartBuildError("PACKAGE", f"app source must not be inside workdir: {source}")

        work_output.parent.mkdir(parents=True, exist_ok=True)
        if work_output.exists() or work_output.is_symlink():
            work_output.unlink()

        env = _compile_env(task.env)
        completed = runner(list(command), cwd=task.workdir, env=env)
        _write_completed_command(log, command, task.workdir, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "BUILD",
                "app {task_id} compile failed: command={command} exit code {exit_code} "
                "log={log_path}".format(
                    task_id=task.id,
                    command=" ".join(command),
                    exit_code=completed.returncode,
                    log_path=task.log_path,
                ),
            )
        if not work_output.is_file():
            raise SmartBuildError("BUILD", f"app compile did not create output: {work_output}")

        staged_output = Path(task.outputs[0])
        staged_output.parent.mkdir(parents=True, exist_ok=True)
        _prepare_new_output(staged_output)
        shutil.copy2(work_output, staged_output)
        staged_output.chmod(0o755)
        log.write(f"installed app: {work_output} -> {staged_output}\n")
        return 0

    return executor


def _load_package_description(paths, name):
    description = load_description(package_description_path(paths.root, name))
    if description.kind != "package":
        raise SmartBuildError("PACKAGE", f"{description.path}: expected package description")
    if description.name != name:
        raise SmartBuildError("PACKAGE", f"{description.path}: package name must be {name}")
    return description


def _package_source_path(paths, description, name):
    source_name = description.data.get("source", name)
    source_name = validate_safe_name(source_name, "package source")
    return paths.root / "apps" / source_name / "hello.c"


def _package_linkage(description):
    linkage = description.data.get("linkage")
    if linkage not in {"static", "dynamic"}:
        raise SmartBuildError("PACKAGE", f"{description.path}: linkage must be static or dynamic")
    language = description.data.get("language")
    if language != "c":
        raise SmartBuildError("PACKAGE", f"{description.path}: only language c is supported")
    return linkage


def _package_depends(description):
    depends = description.data.get("depends", "")
    if isinstance(depends, list):
        return ", ".join(str(item) for item in depends)
    if not isinstance(depends, str):
        raise SmartBuildError("PACKAGE", f"{description.path}: depends must be a string or list")
    return depends


def _merge_depends(base, extra):
    values = []
    for value in (base, extra):
        if isinstance(value, str):
            chunks = [item.strip() for item in value.split(",")]
        else:
            chunks = [str(item).strip() for item in value]
        values.extend(item for item in chunks if item)
    return ", ".join(values)


def _package_install_path(description):
    install = description.data.get("install", {})
    if not isinstance(install, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: install must be a mapping")
    raw_path = install.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise SmartBuildError("PACKAGE", f"{description.path}: install.path must be a non-empty string")
    return _safe_rootfs_relative_path(raw_path, "install.path", description.path)


def _extension_install_path(description, delta, fallback):
    install = delta.get("install")
    if not install or "path" not in install:
        return fallback
    return _safe_rootfs_relative_path(install["path"], "extension install.path", description.path)


def _reject_env_collisions(description_path, extension_env, base_env):
    collisions = sorted(set(extension_env) & set(base_env))
    if collisions:
        raise SmartBuildError(
            "PACKAGE",
            f"{description_path}: extension env collision would override build env: {', '.join(collisions)}",
        )


def _extension_context(name, description, source, install_path, depends, command, paths):
    return {
        "name": name,
        "version": str(description.data.get("version", "0.1.0")),
        "description_path": str(description.path),
        "repository": str(Path(paths.root).resolve()),
        "machine": paths.machine,
        "source": str(source),
        "install_path": f"/{install_path.as_posix()}",
        "depends": depends,
        "command": list(command),
        "metadata": deepcopy(description.data),
    }


def _safe_rootfs_relative_path(raw_path, label, source):
    posix_path = PurePosixPath(raw_path)
    if not posix_path.is_absolute():
        raise SmartBuildError("PACKAGE", f"{source}: {label} must be absolute inside rootfs: {raw_path}")
    relative = PurePosixPath(*posix_path.parts[1:])
    if not relative.parts:
        raise SmartBuildError("PACKAGE", f"{source}: {label} must name a file: {raw_path}")
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise SmartBuildError("PACKAGE", f"{source}: unsafe {label}: {raw_path}")
    return relative


def _compile_command(toolchain, linkage, source, output):
    command = [str(toolchain.gcc)]
    if linkage == "static":
        command.append("-static")
    command.extend([str(source), "-o", str(output)])
    return command


def _apply_command_delta(command, delta):
    prefix = _string_list(delta.get("prefix", []))
    suffix = _string_list(delta.get("suffix", []))
    return [*prefix, *command, *suffix]


def _string_list(value):
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _compile_env(task_env):
    env = os.environ.copy()
    env.update({key: str(value) for key, value in task_env.items()})
    for key in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"):
        env.pop(key, None)
    return env


def _prepare_new_output(path):
    output = Path(path)
    if output.is_symlink():
        raise SmartBuildError("BUILD", f"refusing to replace symlink output: {output}")
    if not output.exists():
        return
    if not output.is_file():
        raise SmartBuildError("BUILD", f"refusing to replace non-file output: {output}")
    if output.stat().st_nlink > 1:
        raise SmartBuildError("BUILD", f"refusing to replace hardlink output: {output}")
    output.unlink()


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
        raise SmartBuildError("BUILD", f"failed to run app command {command}: {exc}") from exc


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
