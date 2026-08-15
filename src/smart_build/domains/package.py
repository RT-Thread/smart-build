import os
import shutil
import stat
import subprocess
from copy import deepcopy
from pathlib import Path, PurePosixPath

from ..cache import Cache
from ..cmake_package import (
    cmake_commands,
    cmake_toolchain_text,
    parse_cmake_build,
    parse_readelf_linkage,
    select_cmake_outputs,
)
from ..config import resolve_rootfs_selection
from ..configure import (
    ConfigurationResult,
    configuration_spec_from_mapping,
    execute_configuration,
    package_configuration_workdir,
    toolchain_configuration_env,
    validate_configuration_mapping,
)
from ..descriptions import load_description
from ..doctor import resolve_host_tool
from ..errors import SmartBuildError
from ..package_metadata import normalize_package_metadata, package_description_path
from ..paths import board_defconfig_path, validate_safe_name
from ..scheduler import Scheduler
from ..tasks import Task, TaskGraph
from .package_sources import package_source_config, package_source_task
from .toolchain import resolve_toolchain, toolchain_task_fields


PACKAGE_STAGE_DIR = "packages"


def package_tasks(paths, toolchain=None, package_names=None, command_runner=None, env_packages=None):
    names = list(package_names) if package_names is not None else selected_rootfs_package_names(paths)
    tasks = []
    for name in names:
        item = package_task(
            paths,
            name,
            toolchain=toolchain,
            command_runner=command_runner,
            env_packages=env_packages,
        )
        if isinstance(item, list):
            tasks.extend(item)
        else:
            tasks.append(item)
    return tasks


def package_task(paths, package_name, toolchain=None, command_runner=None, env_packages=None):
    name = validate_safe_name(package_name, "package")
    description = _load_package_description(paths, name)
    package_type = description.data.get("type")
    if package_type not in {"library", "executable"}:
        raise SmartBuildError("PACKAGE", f"{description.path}: package type must be library or executable")
    build = description.data.get("build")
    if isinstance(build, dict) and "rtthread_scons" in build:
        from .rtthread_scons_package import rtthread_scons_package_task

        metadata = normalize_package_metadata(description)
        return rtthread_scons_package_task(
            paths,
            name,
            description,
            metadata,
            _selected_package(paths, name, description),
            toolchain=toolchain,
            command_runner=command_runner,
            env_packages=env_packages,
        )
    source_task = package_source_task(paths, name, description)
    if package_type == "executable":
        tasks = _executable_package_tasks(paths, name, description, toolchain=toolchain, command_runner=command_runner)
        return _with_source_task(source_task, tasks)
    task = _library_package_task(paths, name, description, toolchain=toolchain, command_runner=command_runner)
    return _with_source_task(source_task, task)


def package_configuration(
    paths,
    package_name,
    toolchain=None,
    command_runner=None,
    frontend=None,
    env_packages=None,
):
    name = validate_safe_name(package_name, "package")
    description = _load_package_description(paths, name)
    metadata = normalize_package_metadata(description)
    if metadata.kconfig.mode == "native":
        from ..menuconfig import run_package_menuconfig
        from ..rtthread_scons import parse_rtthread_scons_config

        parse_rtthread_scons_config(
            paths.root,
            description,
            metadata,
            env_packages=env_packages,
        )
        updated = run_package_menuconfig(
            paths,
            metadata,
            frontend=frontend,
            env_packages=env_packages,
        )
        return ConfigurationResult(f"package:{name}", updated)

    mapping = description.data.get("configure")
    if mapping is None:
        raise SmartBuildError(
            "CONFIG",
            f"{description.path}: no package configuration provider declared",
        )

    source_context = _source_context(paths, name, description)
    source_dir = source_context["source_dir"]
    package_dir = description.path.parent
    build_dir = paths.work_dir / "configure" / f"package-{name}"
    workdir = package_configuration_workdir(
        mapping,
        source_dir,
        package_dir,
        build_dir,
        label=f"{description.path}: configure",
    )
    validate_configuration_mapping(
        mapping,
        source_dir,
        package_dir,
        label=f"{description.path}: configure",
    )

    resolved_toolchain = toolchain
    if resolved_toolchain is None:
        from ..machines import load_machine

        resolved_toolchain = resolve_toolchain(machine=load_machine(paths.root, paths.machine))
    paths.ensure_execution_dirs()
    source_task = package_source_task(paths, name, description)
    if source_task is not None:
        Scheduler(
            TaskGraph([source_task]),
            Cache(paths.stamps_dir),
            display_path=paths.display_path,
        ).run()
    if not source_dir.is_dir():
        raise SmartBuildError("SOURCE", f"package source directory not found: {source_dir}")
    build_dir.mkdir(parents=True, exist_ok=True)
    env = toolchain_configuration_env(
        paths,
        resolved_toolchain,
        SMART_BUILD_PACKAGE=name,
        SMART_BUILD_PACKAGE_DIR=package_dir,
        SMART_BUILD_SOURCE_DIR=source_dir,
        SMART_BUILD_WORK_DIR=build_dir,
    )
    spec = configuration_spec_from_mapping(
        f"package:{name}",
        mapping,
        workdir,
        source_root=source_dir,
        destination_root=package_dir,
        base_env=env,
        label=f"{description.path}: configure",
    )
    return execute_configuration(spec, command_runner=command_runner)


def _library_package_task(paths, name, description, toolchain=None, command_runner=None):
    build = _build_config(description)
    if "python" in build:
        return _python_library_package_task(
            paths,
            name,
            description,
            build,
            toolchain=toolchain,
            command_runner=command_runner,
        )

    selected = _selected_package(paths, name, description)
    version = selected.version
    selected_options = dict(selected.options)
    package_description = str(description.data.get("description", name))
    depends = _package_depends(description)
    source_context = _source_context(paths, name, description)
    source_dir = source_context["source_dir"]
    source_files = _source_files(description)
    install = _install_config(description)
    objects = _object_sources(description, build, source_files)
    static_library = _required_install_file(description, build, "static_library")
    shared_library = _required_install_file(description, build, "shared_library")
    headers = _install_files(description, install, "headers")
    libraries = _install_files(description, install, "libraries")
    if sorted(libraries) != sorted([static_library, shared_library]):
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: install.libraries must include {static_library} and {shared_library}",
        )
    if not source_context["deferred"]:
        _validate_sources(source_dir, [*source_files, *headers])

    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    workdir = paths.work_dir / PACKAGE_STAGE_DIR / name
    staged_dir = paths.staging_dir / PACKAGE_STAGE_DIR / name
    _validate_existing_stage(staged_dir, paths.staging_dir)
    _validate_existing_install_files(staged_dir, headers, libraries)
    base_env = {"MACHINE": paths.machine, **fields["env"]}
    expected_machine = _expected_readelf_machine(resolved_toolchain)["display"]
    commands = _build_commands(
        resolved_toolchain,
        source_dir,
        workdir,
        objects,
        static_library,
        shared_library,
    )
    manifest_library = {
        "name": name,
        "description": str(description.path),
        "package_description": package_description,
        "version": version,
        "selected_options": selected_options,
        "depends": depends,
        "provides": _package_provides(selected),
        "type": "library",
        "source_dir": str(source_dir),
        "source_files": source_files,
        "headers": [f"/include/{header}" for header in headers],
        "libraries": [f"/lib/{library}" for library in libraries],
        "staged_dir": str(staged_dir),
        "commands": commands,
        "install_files": _install_package_files(staged_dir, headers, libraries),
        "architecture_check": {
            "status": "pending",
            "tool": str(_tool_path(resolved_toolchain, "readelf")),
            "library": str(staged_dir / "lib" / shared_library),
            "expected_machine": expected_machine,
        },
    }
    if source_context["manifest"] is not None:
        manifest_library["source"] = source_context["manifest"]
    return Task(
        id=f"package:{name}:build",
        domain="package",
        action="build",
        inputs=[description.path, *source_context["inputs"], *_package_input_paths(source_dir, source_files, headers)],
        outputs=[staged_dir],
        deps=["toolchain:check", *source_context["deps"]],
        workdir=workdir,
        env=base_env,
        run_class="build",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"package-{name}-build.log",
        executor=_make_library_executor(
            name,
            source_dir,
            paths.work_dir,
            workdir,
            staged_dir,
            paths.staging_dir,
            headers,
            libraries,
            commands,
            resolved_toolchain,
            shared_library,
            command_runner,
        ),
        cache_extra={
            **fields["cache_extra"],
            "library": deepcopy(manifest_library),
        },
        manifest_fields={
            **fields["manifest_fields"],
            "library": manifest_library,
        },
    )


def _python_library_package_task(paths, name, description, build, toolchain=None, command_runner=None):
    selected = _selected_package(paths, name, description)
    version = selected.version
    selected_options = dict(selected.options)
    package_description = str(description.data.get("description", name))
    depends = _package_depends(description)
    source_context = _source_context(paths, name, description)
    source_dir = source_context["source_dir"]
    source_files = _source_files(description)
    python_build = _python_build_config(paths, description, build, require_output=False)
    output_paths = _python_output_paths(description, python_build)
    if not source_context["deferred"]:
        _validate_sources(source_dir, [*source_files, *python_build["upstream_markers"]])

    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    workdir = paths.work_dir / PACKAGE_STAGE_DIR / name
    staged_dir = paths.staging_dir / PACKAGE_STAGE_DIR / name
    _validate_existing_stage(staged_dir, paths.staging_dir)
    _validate_existing_package_paths(staged_dir, output_paths)
    base_env = {"MACHINE": paths.machine, **fields["env"]}
    execution_script = _python_execution_script(source_context, source_dir, python_build)
    command = ["python3", str(execution_script)]
    install_files = _python_install_files(staged_dir, output_paths)
    manifest_library = {
        "name": name,
        "description": str(description.path),
        "package_description": package_description,
        "version": version,
        "selected_options": selected_options,
        "depends": depends,
        "provides": _package_provides(selected),
        "type": "library",
        "build_system": "python",
        "source_dir": str(source_dir),
        "source_files": source_files,
        "headers": [item["path"] for item in install_files if _is_header_path(item["path"])],
        "libraries": [item["path"] for item in install_files if _is_library_path(item["path"])],
        "staged_dir": str(staged_dir),
        "python": {
            "script": python_build["relative_script"],
            "execution_script": str(execution_script),
            "command": command,
            "outputs": [f"/{path.as_posix()}" for path in output_paths],
            "upstream_markers": python_build["upstream_markers"],
        },
        "install_files": install_files,
        "architecture_check": {
            "status": "pending",
            "tool": str(_tool_path(resolved_toolchain, "readelf")),
            "expected_machine": _expected_readelf_machine(resolved_toolchain)["display"],
        },
    }
    if source_context["manifest"] is not None:
        manifest_library["source"] = source_context["manifest"]
    return Task(
        id=f"package:{name}:build",
        domain="package",
        action="build",
        inputs=[
            description.path,
            python_build["script"],
            *source_context["inputs"],
            *_package_input_paths(source_dir, source_files, python_build["upstream_markers"]),
        ],
        outputs=[staged_dir],
        deps=["toolchain:check", *source_context["deps"]],
        workdir=workdir,
        env=base_env,
        run_class="build",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"package-{name}-build.log",
        executor=_make_python_library_executor(
            name,
            source_dir,
            paths.work_dir,
            workdir,
            staged_dir,
            paths.staging_dir,
            output_paths,
            command,
            python_build["upstream_markers"],
            resolved_toolchain,
            command_runner,
        ),
        cache_extra={
            **fields["cache_extra"],
            "library": deepcopy(manifest_library),
        },
        manifest_fields={
            **fields["manifest_fields"],
            "library": manifest_library,
        },
    )


def selected_rootfs_package_names(paths):
    selection = resolve_rootfs_selection(paths.root, paths.machine)
    if selection.rootfs == "none":
        return []
    names = []
    for package in selection.packages:
        description = _load_package_description(paths, validate_safe_name(package, "package"))
        if description.data.get("type") in {"library", "executable"}:
            names.append(description.name)
    return names


def is_library_package(paths, name):
    try:
        description = _load_package_description(paths, validate_safe_name(name, "package"))
    except SmartBuildError:
        raise
    return description.data.get("type") == "library"


def _with_source_task(source_task, build_tasks):
    if source_task is None:
        return build_tasks
    tasks = build_tasks if isinstance(build_tasks, list) else [build_tasks]
    return [source_task, *tasks]


def _executable_package_tasks(paths, name, description, toolchain=None, command_runner=None):
    build = _build_config(description)
    if "cmake" in build:
        return [
            _cmake_executable_package_task(
                paths,
                name,
                description,
                toolchain=toolchain,
                command_runner=command_runner,
            )
        ]
    if "python" in build:
        return [
            _python_executable_package_task(
                paths,
                name,
                description,
                build,
                toolchain=toolchain,
                command_runner=command_runner,
            )
        ]

    selected = _selected_package(paths, name, description)
    version = selected.version
    selected_options = dict(selected.options)
    package_description = str(description.data.get("description", name))
    depends = _package_depends(description)
    source_context = _source_context(paths, name, description)
    source_dir = source_context["source_dir"]
    source_files = _source_files(description)
    build = _build_config(description)
    host = _host_tool_config(description, build)
    target = _target_build_config(description, build)
    install_path = _executable_install_path(description)
    smoke = _smoke_config(description)
    host_source = _safe_file_name(host["source"], "build.host_tool.source", description.path)
    host_output = _safe_file_name(host["output"], "build.host_tool.output", description.path)
    generated_header = _safe_file_name(host["generated_header"], "build.host_tool.generated_header", description.path)
    target_sources = _target_sources(description, target, source_files)
    target_output = _safe_file_name(target["output"], "build.target.output", description.path)
    if not source_context["deferred"]:
        _validate_sources(source_dir, [*source_files, host_source, *target_sources])

    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    workdir = paths.work_dir / PACKAGE_STAGE_DIR / name
    host_workdir = workdir / "host"
    target_workdir = workdir / "target"
    staged_dir = paths.staging_dir / PACKAGE_STAGE_DIR / name
    _validate_existing_stage(staged_dir, paths.staging_dir)
    _validate_existing_package_paths(staged_dir, [install_path])
    base_env = {"MACHINE": paths.machine, **fields["env"]}
    host_tool_path = host_workdir / host_output
    generated_header_path = host_workdir / generated_header
    target_binary_path = target_workdir / target_output
    _validate_existing_host_outputs(paths.work_dir, [host_tool_path, generated_header_path])
    commands = {
        "host": [
            [
                "cc",
                "-O2",
                str(source_dir / host_source),
                "-o",
                str(host_tool_path),
            ],
            [
                str(host_tool_path),
                "--output",
                str(generated_header_path),
                "--version",
                version,
            ],
        ],
        "target": _executable_target_commands(
            resolved_toolchain,
            source_dir,
            target_workdir,
            host_workdir,
            target_sources,
            target_binary_path,
        ),
    }
    manifest_executable = {
        "name": name,
        "description": str(description.path),
        "package_description": package_description,
        "version": version,
        "selected_options": selected_options,
        "depends": depends,
        "provides": _package_provides(selected),
        "type": "executable",
        "source_dir": str(source_dir),
        "source_files": source_files,
        "install_path": f"/{install_path.as_posix()}",
        "staged_dir": str(staged_dir),
        "host_phase": {
            "task_id": f"package:{name}:host-tool",
            "source": str(source_dir / host_source),
            "tool": str(host_tool_path),
            "output": str(generated_header_path),
            "commands": commands["host"],
        },
        "target_phase": {
            "task_id": f"package:{name}:target-build",
            "sources": [str(source_dir / source) for source in target_sources],
            "output": str(target_binary_path),
            "commands": commands["target"],
            "command": commands["target"][-1],
        },
        "install_files": [
            {
                "source": str(staged_dir / install_path),
                "path": f"/{install_path.as_posix()}",
                "mode": 0o755,
            }
        ],
        "smoke": smoke,
        "architecture_check": {
            "status": "pending",
            "tool": str(_tool_path(resolved_toolchain, "readelf")),
            "binary": str(staged_dir / install_path),
            "expected_machine": _expected_readelf_machine(resolved_toolchain)["display"],
        },
    }
    if source_context["manifest"] is not None:
        manifest_executable["source"] = source_context["manifest"]
    host_task = Task(
        id=f"package:{name}:host-tool",
        domain="package",
        action="host-tool",
        inputs=[description.path, *source_context["inputs"], source_dir / host_source],
        outputs=[generated_header_path],
        deps=source_context["deps"],
        workdir=host_workdir,
        env={"MACHINE": paths.machine},
        run_class="build",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"package-{name}-host-tool.log",
        executor=_make_executable_host_executor(
            name,
            paths.work_dir,
            host_workdir,
            commands["host"],
            host_tool_path,
            generated_header_path,
            command_runner,
        ),
        cache_extra={"executable": {"host_phase": deepcopy(manifest_executable["host_phase"])}},
        manifest_fields={"executable": {"host_phase": deepcopy(manifest_executable["host_phase"])}},
    )
    target_task = Task(
        id=f"package:{name}:target-build",
        domain="package",
        action="target-build",
        inputs=[description.path, *source_context["inputs"], *_package_input_paths(source_dir, target_sources, [host_source]), generated_header_path],
        outputs=[staged_dir],
        deps=["toolchain:check", *source_context["deps"], host_task.id],
        workdir=target_workdir,
        env=base_env,
        run_class="build",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"package-{name}-target-build.log",
        executor=_make_executable_target_executor(
            name,
            source_dir,
            paths.work_dir,
            target_workdir,
            staged_dir,
            paths.staging_dir,
            install_path,
            target_binary_path,
            commands["target"],
            generated_header_path,
            resolved_toolchain,
            command_runner,
        ),
        cache_extra={
            **fields["cache_extra"],
            "executable": deepcopy(manifest_executable),
        },
        manifest_fields={
            **fields["manifest_fields"],
            "executable": manifest_executable,
        },
    )
    return [host_task, target_task]


def _cmake_executable_package_task(
    paths, name, description, toolchain=None, command_runner=None
):
    selected = _selected_package(paths, name, description)
    source_context = _source_context(paths, name, description)
    source_dir = source_context["source_dir"]
    source_files = _source_files(description)
    config = parse_cmake_build(description)
    mode = _effective_package_build_mode(paths)
    selected_outputs = select_cmake_outputs(config, mode)
    install_path = _executable_install_path(description)
    if not source_context["deferred"]:
        _validate_sources(source_dir, source_files)

    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    cmake = resolve_host_tool("cmake")
    workdir = paths.work_dir / PACKAGE_STAGE_DIR / name / "target"
    build_dir = workdir / "build"
    toolchain_file = workdir / "toolchain.cmake"
    staged_dir = paths.staging_dir / PACKAGE_STAGE_DIR / name
    output_paths = [item.path for item in selected_outputs]
    _validate_existing_stage(staged_dir, paths.staging_dir)
    _validate_existing_package_paths(staged_dir, output_paths)
    toolchain_text = cmake_toolchain_text(resolved_toolchain)
    commands = cmake_commands(
        cmake,
        source_dir,
        build_dir,
        toolchain_file,
        mode,
        config.options,
    )
    install_files = [
        {
            "source": str(staged_dir.joinpath(*item.path.parts)),
            "path": f"/{item.path.as_posix()}",
            "mode": 0o755,
        }
        for item in selected_outputs
    ]
    manifest = {
        "name": name,
        "description": str(description.path),
        "package_description": str(description.data.get("description", name)),
        "version": selected.version,
        "selected_options": dict(selected.options),
        "depends": _package_depends(description),
        "provides": _package_provides(selected),
        "type": "executable",
        "build_system": "cmake",
        "linkage_mode": mode,
        "source_dir": str(source_dir),
        "source_files": source_files,
        "install_path": f"/{install_path.as_posix()}",
        "staged_dir": str(staged_dir),
        "target_phase": {
            "task_id": f"package:{name}:target-build",
            "cmake": cmake,
            "toolchain_file": str(toolchain_file),
            "toolchain_text": toolchain_text,
            "commands": [list(command) for command in commands],
            "outputs": [f"/{item.path.as_posix()}" for item in selected_outputs],
        },
        "install_files": install_files,
        "smoke": _smoke_config(description),
        "architecture_check": {"status": "pending"},
    }
    if source_context["manifest"] is not None:
        manifest["source"] = source_context["manifest"]
    base_env = {"MACHINE": paths.machine, **fields["env"]}
    return Task(
        id=f"package:{name}:target-build",
        domain="package",
        action="target-build",
        inputs=[
            description.path,
            *source_context["inputs"],
            *_package_input_paths(source_dir, source_files, []),
        ],
        outputs=[staged_dir],
        deps=["toolchain:check", *source_context["deps"]],
        workdir=workdir,
        env=base_env,
        run_class="build",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"package-{name}-target-build.log",
        executor=_make_cmake_executable_executor(
            name,
            source_dir,
            workdir,
            build_dir,
            toolchain_file,
            toolchain_text,
            staged_dir,
            paths.staging_dir,
            selected_outputs,
            commands,
            resolved_toolchain,
            command_runner,
        ),
        cache_extra={**fields["cache_extra"], "executable": deepcopy(manifest)},
        manifest_fields={**fields["manifest_fields"], "executable": manifest},
    )


def _python_executable_package_task(paths, name, description, build, toolchain=None, command_runner=None):
    selected = _selected_package(paths, name, description)
    version = selected.version
    selected_options = dict(selected.options)
    package_description = str(description.data.get("description", name))
    depends = _package_depends(description)
    source_context = _source_context(paths, name, description)
    source_dir = source_context["source_dir"]
    source_files = _source_files(description)
    python_build = _python_build_config(paths, description, build)
    install_path = _executable_install_path(description)
    output_paths = python_build["outputs"] or [install_path]
    smoke = _smoke_config(description)
    if not source_context["deferred"]:
        _validate_sources(source_dir, [*source_files, *python_build["upstream_markers"]])

    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    workdir = paths.work_dir / PACKAGE_STAGE_DIR / name / "target"
    staged_dir = paths.staging_dir / PACKAGE_STAGE_DIR / name
    target_binary_path = workdir / python_build["output"] if python_build["output"] else None
    _validate_existing_stage(staged_dir, paths.staging_dir)
    _validate_existing_package_paths(staged_dir, output_paths)
    _validate_existing_host_outputs(paths.work_dir, [target_binary_path] if target_binary_path is not None else [])
    base_env = {"MACHINE": paths.machine, **fields["env"]}
    execution_script = _python_execution_script(source_context, source_dir, python_build)
    command = ["python3", str(execution_script)]
    manifest_executable = {
        "name": name,
        "description": str(description.path),
        "package_description": package_description,
        "version": version,
        "selected_options": selected_options,
        "depends": depends,
        "provides": _package_provides(selected),
        "type": "executable",
        "build_system": "python",
        "source_dir": str(source_dir),
        "source_files": source_files,
        "install_path": f"/{install_path.as_posix()}",
        "staged_dir": str(staged_dir),
        "target_phase": {
            "task_id": f"package:{name}:target-build",
            "script": python_build["relative_script"],
            "execution_script": str(execution_script),
            "command": command,
            "output": str(target_binary_path) if target_binary_path is not None else None,
            "outputs": [f"/{path.as_posix()}" for path in output_paths],
            "upstream_markers": python_build["upstream_markers"],
        },
        "install_files": _python_install_files(staged_dir, output_paths),
        "smoke": smoke,
        "architecture_check": {
            "status": "pending",
            "tool": str(_tool_path(resolved_toolchain, "readelf")),
            "binary": str(staged_dir / install_path),
            "expected_machine": _expected_readelf_machine(resolved_toolchain)["display"],
        },
    }
    if source_context["manifest"] is not None:
        manifest_executable["source"] = source_context["manifest"]
    return Task(
        id=f"package:{name}:target-build",
        domain="package",
        action="target-build",
        inputs=[
            description.path,
            python_build["script"],
            *source_context["inputs"],
            *_package_input_paths(source_dir, source_files, python_build["upstream_markers"]),
        ],
        outputs=[staged_dir],
        deps=["toolchain:check", *source_context["deps"]],
        workdir=workdir,
        env=base_env,
        run_class="build",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"package-{name}-target-build.log",
        executor=_make_python_executable_target_executor(
            name,
            source_dir,
            paths.work_dir,
            workdir,
            staged_dir,
            paths.staging_dir,
            install_path,
            target_binary_path,
            output_paths,
            command,
            python_build["upstream_markers"],
            resolved_toolchain,
            command_runner,
        ),
        cache_extra={
            **fields["cache_extra"],
            "executable": deepcopy(manifest_executable),
        },
        manifest_fields={
            **fields["manifest_fields"],
            "executable": manifest_executable,
        },
    )


def _make_library_executor(
    name,
    source_dir,
    work_root,
    workdir,
    staged_dir,
    staging_root,
    headers,
    libraries,
    commands,
    toolchain,
    shared_library,
    command_runner,
):
    runner = command_runner or _run_command

    def executor(task, log):
        _validate_sources(source_dir, [*headers, *_command_source_files(commands)])
        workdir.mkdir(parents=True, exist_ok=True)
        _prepare_work_outputs(work_root, _command_output_files(commands))
        _prepare_stage(staged_dir, staging_root)
        env = _compile_env(task.env)
        for command in commands:
            completed = runner(list(command), cwd=workdir, env=env)
            _write_completed_command(log, command, workdir, completed)
            if completed.returncode != 0:
                raise SmartBuildError(
                    "BUILD",
                    "package {name} build failed: command={command} exit code {exit_code} log={log_path}".format(
                        name=name,
                        command=" ".join(command),
                        exit_code=completed.returncode,
                        log_path=task.log_path,
                    ),
                )

        include_dir = staged_dir / "include"
        lib_dir = staged_dir / "lib"
        include_dir.mkdir(parents=True, exist_ok=True)
        lib_dir.mkdir(parents=True, exist_ok=True)
        for header in headers:
            _copy_source_file(source_dir / header, include_dir / header, mode=0o644)
        for library in libraries:
            source = workdir / library
            if not source.is_file():
                raise SmartBuildError("BUILD", f"package {name} did not create library: {source}")
            _copy_source_file(source, lib_dir / library, mode=0o755 if library.endswith(".so") else 0o644)

        check = _verify_architecture(toolchain, lib_dir / shared_library, runner, workdir, env, log)
        task.manifest_fields["library"]["architecture_check"] = check
        log.write(f"staged package: {staged_dir}\n")
        return 0

    return executor


def _make_python_library_executor(
    name,
    source_dir,
    work_root,
    workdir,
    staged_dir,
    staging_root,
    output_paths,
    command,
    upstream_markers,
    toolchain,
    command_runner,
):
    runner = command_runner or _run_command

    def executor(task, log):
        _validate_sources(source_dir, upstream_markers)
        workdir.mkdir(parents=True, exist_ok=True)
        _prepare_stage(staged_dir, staging_root)
        env = _sbuild_env(task.env, name, source_dir, workdir, staged_dir, staging_root, toolchain)
        completed = runner(list(command), cwd=workdir, env=env)
        _write_completed_command(log, command, workdir, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "BUILD",
                "package {name} python build failed: command={command} exit code {exit_code} log={log_path}".format(
                    name=name,
                    command=" ".join(command),
                    exit_code=completed.returncode,
                    log_path=task.log_path,
                ),
            )
        install_files = _require_python_outputs(staged_dir, output_paths)
        checks = [
            _verify_library_output_architecture(toolchain, Path(item["source"]), runner, workdir, env, log)
            for item in install_files
            if _is_library_path(item["path"])
        ]
        task.manifest_fields["library"]["install_files"] = install_files
        if checks:
            task.manifest_fields["library"]["architecture_check"] = checks[0] if len(checks) == 1 else {
                "status": "verified",
                "checks": checks,
            }
        else:
            task.manifest_fields["library"]["architecture_check"] = {
                "status": "skipped",
                "reason": "no library outputs",
            }
        log.write(f"staged python-built library package: {staged_dir}\n")
        return 0

    return executor


def _make_executable_host_executor(
    name,
    work_root,
    workdir,
    commands,
    host_tool,
    generated_header,
    command_runner,
):
    runner = command_runner or _run_command

    def executor(task, log):
        workdir.mkdir(parents=True, exist_ok=True)
        _prepare_work_outputs(work_root, _command_output_files(commands))
        env = _compile_env(task.env)
        for command in commands:
            completed = runner(list(command), cwd=workdir, env=env)
            _write_completed_command(log, command, workdir, completed)
            if completed.returncode != 0:
                raise SmartBuildError(
                    "BUILD",
                    "package {name} host tool failed: command={command} exit code {exit_code} log={log_path}".format(
                        name=name,
                        command=" ".join(command),
                        exit_code=completed.returncode,
                        log_path=task.log_path,
                    ),
                )
            if "-o" in command and Path(command[command.index("-o") + 1]) == host_tool:
                _require_safe_host_output(work_root, host_tool, f"package {name} host tool")
        _require_safe_host_output(work_root, host_tool, f"package {name} host tool")
        _require_safe_host_output(
            work_root,
            generated_header,
            f"package {name} generated header",
            missing_message=f"package {name} host tool did not create header: {generated_header}",
        )
        log.write(f"generated host tool output: {generated_header}\n")
        return 0

    return executor


def _make_executable_target_executor(
    name,
    source_dir,
    work_root,
    workdir,
    staged_dir,
    staging_root,
    install_path,
    target_output,
    commands,
    generated_header,
    toolchain,
    command_runner,
):
    runner = command_runner or _run_command

    def executor(task, log):
        _validate_sources(source_dir, _command_source_files(commands))
        _require_safe_host_output(
            work_root,
            generated_header,
            f"package {name} generated header",
            missing_message=f"package {name} missing generated header: {generated_header}",
        )
        workdir.mkdir(parents=True, exist_ok=True)
        _prepare_work_outputs(work_root, _command_output_files(commands))
        _prepare_stage(staged_dir, staging_root)
        env = _compile_env(task.env)
        for command in commands:
            completed = runner(list(command), cwd=workdir, env=env)
            _write_completed_command(log, command, workdir, completed)
            if completed.returncode != 0:
                raise SmartBuildError(
                    "BUILD",
                    "package {name} target build failed: command={command} exit code {exit_code} log={log_path}".format(
                        name=name,
                        command=" ".join(command),
                        exit_code=completed.returncode,
                        log_path=task.log_path,
                    ),
                )
        if not target_output.is_file():
            raise SmartBuildError("BUILD", f"package {name} did not create executable: {target_output}")
        destination = staged_dir.joinpath(*install_path.parts)
        _copy_source_file(target_output, destination, mode=0o755)
        check = _verify_binary_architecture(toolchain, destination, runner, workdir, env, log)
        task.manifest_fields["executable"]["architecture_check"] = check
        log.write(f"staged executable package: {staged_dir}\n")
        return 0

    return executor


def _make_python_executable_target_executor(
    name,
    source_dir,
    work_root,
    workdir,
    staged_dir,
    staging_root,
    install_path,
    target_output,
    output_paths,
    command,
    upstream_markers,
    toolchain,
    command_runner,
):
    runner = command_runner or _run_command

    def executor(task, log):
        _validate_sources(source_dir, upstream_markers)
        workdir.mkdir(parents=True, exist_ok=True)
        _prepare_work_outputs(work_root, [target_output] if target_output is not None else [])
        _prepare_stage(staged_dir, staging_root)
        env = _sbuild_env(task.env, name, source_dir, workdir, staged_dir, staging_root, toolchain)
        env["SMART_BUILD_INSTALL_PATH"] = f"/{install_path.as_posix()}"
        if target_output is not None:
            env["SMART_BUILD_OUTPUT"] = str(target_output)
        completed = runner(list(command), cwd=workdir, env=env)
        _write_completed_command(log, command, workdir, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "BUILD",
                "package {name} python target build failed: command={command} exit code {exit_code} log={log_path}".format(
                    name=name,
                    command=" ".join(command),
                    exit_code=completed.returncode,
                    log_path=task.log_path,
                ),
            )
        if target_output is not None and output_paths == [install_path]:
            _require_safe_host_output(
                work_root,
                target_output,
                f"package {name} python target output",
                missing_message=f"package {name} did not create executable: {target_output}",
            )
            destination = staged_dir.joinpath(*install_path.parts)
            _copy_source_file(target_output, destination, mode=0o755)
        install_files = _require_python_outputs(staged_dir, output_paths)
        checks = [
            _verify_binary_architecture(toolchain, staged_dir.joinpath(*path.parts), runner, workdir, env, log)
            for path in output_paths
            if _is_executable_output_path(f"/{path.as_posix()}")
            and not path.as_posix().endswith(".a")
            and staged_dir.joinpath(*path.parts).is_file()
        ]
        task.manifest_fields["executable"]["install_files"] = install_files
        if checks:
            task.manifest_fields["executable"]["architecture_check"] = checks[0] if len(checks) == 1 else {
                "status": "verified",
                "checks": checks,
            }
        else:
            task.manifest_fields["executable"]["architecture_check"] = {
                "status": "skipped",
                "reason": "no executable or shared library outputs",
            }
        log.write(f"staged executable package: {staged_dir}\n")
        return 0

    return executor


def _make_cmake_executable_executor(
    name,
    source_dir,
    workdir,
    build_dir,
    toolchain_file,
    toolchain_text,
    staged_dir,
    staging_root,
    selected_outputs,
    commands,
    toolchain,
    command_runner,
):
    runner = command_runner or _run_command

    def executor(task, log):
        _validate_sources(
            source_dir, task.manifest_fields["executable"]["source_files"]
        )
        _prepare_stage(staged_dir, staging_root)
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True)
        workdir.mkdir(parents=True, exist_ok=True)
        toolchain_file.write_text(toolchain_text, encoding="utf-8")
        env = _sbuild_env(
            task.env,
            name,
            source_dir,
            workdir,
            staged_dir,
            staging_root,
            toolchain,
        )
        env["DESTDIR"] = str(staged_dir)
        for phase, command in zip(("configure", "build", "install"), commands):
            completed = runner(list(command), cwd=workdir, env=env)
            _write_completed_command(log, command, workdir, completed)
            if completed.returncode != 0:
                raise SmartBuildError(
                    "BUILD",
                    "package {name} CMake {phase} failed: command={command} "
                    "exit code {exit_code} log={log_path}".format(
                        name=name,
                        phase=phase,
                        command=" ".join(command),
                        exit_code=completed.returncode,
                        log_path=task.log_path,
                    ),
                )
        for output in selected_outputs:
            path = staged_dir.joinpath(*output.path.parts)
            _require_safe_stage_output(staged_dir, path, name)
            path.chmod(0o755)
        checks = [
            _verify_cmake_output(
                toolchain,
                staged_dir.joinpath(*output.path.parts),
                output.linkage,
                runner,
                workdir,
                env,
                log,
            )
            for output in selected_outputs
        ]
        task.manifest_fields["executable"]["architecture_check"] = (
            checks[0]
            if len(checks) == 1
            else {
                "status": (
                    "verified"
                    if all(
                        check["linkage_status"] == "verified"
                        for check in checks
                    )
                    else "skipped"
                ),
                "checks": checks,
            }
        )
        log.write(f"staged CMake executable package: {staged_dir}\n")
        return 0

    return executor


def _load_library_description(paths, name):
    description = _load_package_description(paths, name)
    if description.data.get("type") != "library":
        raise SmartBuildError("PACKAGE", f"{description.path}: package type must be library")
    return description


def _effective_package_build_mode(paths):
    if not board_defconfig_path(paths.root, paths.machine).is_file():
        return "mixed"
    return resolve_rootfs_selection(paths.root, paths.machine).build_mode or "mixed"


def _load_package_description(paths, name):
    description = load_description(package_description_path(paths.root, name))
    if description.kind != "package":
        raise SmartBuildError("PACKAGE", f"{description.path}: expected package description")
    if description.name != name:
        raise SmartBuildError("PACKAGE", f"{description.path}: package name must be {name}")
    return description


def _selected_package(paths, name, description):
    try:
        selection = resolve_rootfs_selection(paths.root, paths.machine)
    except SmartBuildError:
        return _default_selected_package(name, description)
    for package in selection.selected_packages:
        if package.name == name:
            return package
    return _default_selected_package(name, description)


def _default_selected_package(name, description):
    metadata = normalize_package_metadata(description)
    return type(
        "SelectedPackage",
        (),
        {
            "name": name,
            "version": metadata.default_version,
            "options": {
                option.name: option.default
                for option in metadata.options
            },
            "metadata": metadata,
        },
    )()


def _source_context(paths, name, description):
    config = package_source_config(paths, name, description)
    if config is None:
        return {
            "source_dir": _source_dir(paths, description),
            "deps": [],
            "inputs": [],
            "deferred": False,
            "manifest": None,
        }
    return {
        "source_dir": config.prepared,
        "deps": [config.task_id],
        "inputs": [config.prepared],
        "deferred": True,
        "manifest": _deferred_source_manifest(config),
    }


def _deferred_source_manifest(config):
    manifest = {
        "task_id": config.task_id,
        "type": config.kind,
        "version": config.version,
        "url": config.url,
        "prepared": str(config.prepared),
    }
    if config.kind == "archive":
        manifest.update(
            {
                "archive": str(config.archive),
                "sha256": config.sha256,
                "strip_root": config.strip_root,
            }
        )
    else:
        manifest["revision"] = config.revision
    return manifest


def _source_dir(paths, description):
    source = description.data.get("source")
    if not isinstance(source, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: source must be a mapping")
    raw_dir = source.get("directory")
    if not isinstance(raw_dir, str) or not raw_dir:
        raise SmartBuildError("PACKAGE", f"{description.path}: source.directory must be a non-empty string")
    relative = _safe_relative_path(raw_dir, "source.directory", description.path)
    source_dir = paths.root.joinpath(*relative.parts)
    _validate_source_dir(paths.root, source_dir, description.path)
    return source_dir


def _source_files(description):
    source = description.data.get("source")
    files = source.get("files") if isinstance(source, dict) else None
    build = description.data.get("build")
    allow_relative = isinstance(build, dict) and "python" in build
    if allow_relative:
        return _non_empty_relative_source_list(description, files, "source.files")
    return _non_empty_string_list(description, files, "source.files")


def _build_config(description):
    build = description.data.get("build")
    if not isinstance(build, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: build must be a mapping")
    return build


def _install_config(description):
    install = description.data.get("install")
    if not isinstance(install, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: install must be a mapping")
    return install


def _object_sources(description, build, source_files):
    objects = _non_empty_string_list(description, build.get("objects"), "build.objects")
    missing = sorted(set(objects) - set(source_files))
    if missing:
        raise SmartBuildError("PACKAGE", f"{description.path}: build.objects not in source.files: {', '.join(missing)}")
    return objects


def _required_install_file(description, build, key):
    value = build.get(key)
    if not isinstance(value, str) or not value:
        raise SmartBuildError("PACKAGE", f"{description.path}: build.{key} must be a non-empty string")
    return _safe_file_name(value, f"build.{key}", description.path)


def _install_files(description, install, key):
    values = _non_empty_string_list(description, install.get(key), f"install.{key}")
    return [_safe_file_name(value, f"install.{key}", description.path) for value in values]


def _host_tool_config(description, build):
    host = build.get("host_tool")
    if not isinstance(host, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: build.host_tool must be a mapping")
    for key in ("source", "output", "generated_header"):
        if not isinstance(host.get(key), str) or not host.get(key):
            raise SmartBuildError("PACKAGE", f"{description.path}: build.host_tool.{key} must be a non-empty string")
    return host


def _target_build_config(description, build):
    target = build.get("target")
    if not isinstance(target, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: build.target must be a mapping")
    if not isinstance(target.get("output"), str) or not target.get("output"):
        raise SmartBuildError("PACKAGE", f"{description.path}: build.target.output must be a non-empty string")
    return target


def _python_build_config(paths, description, build, require_output=True):
    config = build.get("python")
    if not isinstance(config, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: build.python must be a mapping")
    relative_script = _safe_relative_path(config.get("script"), "build.python.script", description.path).as_posix()
    script = _package_local_or_repository_file_path(
        paths.root,
        description.path,
        config.get("script"),
        "build.python.script",
    )
    outputs = _optional_rootfs_output_paths(description, config.get("outputs"), "build.python.outputs")
    output_required = require_output and not outputs
    output = _safe_file_name(config.get("output"), "build.python.output", description.path) if output_required else None
    if not output_required and config.get("output"):
        output = _safe_file_name(config.get("output"), "build.python.output", description.path)
    raw_markers = config.get("upstream_markers", [])
    if raw_markers is None:
        raw_markers = []
    if not isinstance(raw_markers, list) or not all(isinstance(item, str) and item for item in raw_markers):
        raise SmartBuildError("PACKAGE", f"{description.path}: build.python.upstream_markers must be a string list")
    upstream_markers = [_safe_relative_source_file(item, "build.python.upstream_markers", description.path) for item in raw_markers]
    return {
        "script": script,
        "relative_script": relative_script,
        "script_name": script.name,
        "output": output,
        "outputs": outputs,
        "upstream_markers": upstream_markers,
    }


def _python_execution_script(source_context, source_dir, python_build):
    if source_context["deferred"]:
        return source_dir / python_build["script_name"]
    return python_build["script"]


def _target_sources(description, target, source_files):
    sources = _non_empty_string_list(description, target.get("sources"), "build.target.sources")
    missing = sorted(set(sources) - set(source_files))
    if missing:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.target.sources not in source.files: {', '.join(missing)}",
        )
    return sources


def _python_output_paths(description, python_build):
    outputs = python_build.get("outputs")
    if not outputs:
        raise SmartBuildError("PACKAGE", f"{description.path}: build.python.outputs must be a non-empty list")
    return outputs


def _executable_install_path(description):
    install = _install_config(description)
    raw_path = install.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise SmartBuildError("PACKAGE", f"{description.path}: install.path must be a non-empty string")
    return _safe_rootfs_relative_path(raw_path, "install.path", description.path)


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
    return {
        "command": list(command),
        "expected_stdout": expected_stdout,
    }


def _package_depends(description):
    depends = description.data.get("depends", "")
    if isinstance(depends, list):
        return ", ".join(str(item) for item in depends)
    if not isinstance(depends, str):
        raise SmartBuildError("PACKAGE", f"{description.path}: depends must be a string or list")
    return depends


def _package_provides(selected):
    return ", ".join(selected.metadata.provides)


def _non_empty_string_list(description, value, label):
    if not isinstance(value, list) or not value:
        raise SmartBuildError("PACKAGE", f"{description.path}: {label} must be a non-empty list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise SmartBuildError("PACKAGE", f"{description.path}: {label} entries must be non-empty strings")
        result.append(_safe_file_name(item, label, description.path))
    return result


def _non_empty_relative_source_list(description, value, label):
    if not isinstance(value, list) or not value:
        raise SmartBuildError("PACKAGE", f"{description.path}: {label} must be a non-empty list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise SmartBuildError("PACKAGE", f"{description.path}: {label} entries must be non-empty strings")
        result.append(_safe_relative_source_file(item, label, description.path))
    return result


def _safe_file_name(raw_name, label, source):
    if not isinstance(raw_name, str) or not raw_name:
        raise SmartBuildError("PACKAGE", f"{source}: {label} must be a non-empty string")
    path = PurePosixPath(str(raw_name))
    if path.is_absolute() or len(path.parts) != 1 or path.name in {"", ".", ".."}:
        raise SmartBuildError("PACKAGE", f"{source}: unsafe {label}: {raw_name}")
    return path.name


def _safe_relative_source_file(raw_path, label, source):
    path = _safe_relative_path(raw_path, label, source)
    if path.name in {"", ".", ".."}:
        raise SmartBuildError("PACKAGE", f"{source}: unsafe {label}: {raw_path}")
    return path.as_posix()


def _repository_file_path(repo_root, raw_path, label, description_path):
    if not isinstance(raw_path, str) or not raw_path:
        raise SmartBuildError("PACKAGE", f"{description_path}: {label} must be a repository-local path")
    relative = _safe_relative_path(raw_path, label, description_path)
    root = Path(repo_root).resolve()
    candidate = root.joinpath(*relative.parts)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("PACKAGE", f"{description_path}: {label} escapes repository: {raw_path}") from exc
    if candidate.is_symlink():
        raise SmartBuildError("PACKAGE", f"{description_path}: refusing symlink {label}: {raw_path}")
    if not candidate.is_file():
        raise SmartBuildError("PACKAGE", f"{description_path}: {label} not found: {raw_path}")
    return resolved


def _package_local_or_repository_file_path(repo_root, description_path, raw_path, label):
    if not isinstance(raw_path, str) or not raw_path:
        raise SmartBuildError("PACKAGE", f"{description_path}: {label} must be a repository-local path")
    relative = _safe_relative_path(raw_path, label, description_path)
    root = Path(repo_root).resolve()
    description_dir = Path(description_path).parent
    local_candidate = description_dir.joinpath(*relative.parts)
    local_resolved = local_candidate.resolve(strict=False)
    try:
        local_resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("PACKAGE", f"{description_path}: {label} escapes repository: {raw_path}") from exc
    if local_candidate.is_symlink():
        raise SmartBuildError("PACKAGE", f"{description_path}: refusing symlink {label}: {raw_path}")
    if local_candidate.is_file():
        return local_resolved
    return _repository_file_path(repo_root, raw_path, label, description_path)


def _safe_relative_path(raw_path, label, source):
    path = PurePosixPath(str(raw_path))
    if path.is_absolute():
        raise SmartBuildError("PACKAGE", f"{source}: {label} must be relative: {raw_path}")
    parts = [part for part in path.parts if part != "."]
    if not parts:
        raise SmartBuildError("PACKAGE", f"{source}: empty {label}: {raw_path}")
    for part in parts:
        if part in {"", ".."}:
            raise SmartBuildError("PACKAGE", f"{source}: unsafe {label}: {raw_path}")
    return PurePosixPath(*parts)


def _safe_rootfs_relative_path(raw_path, label, source):
    path = PurePosixPath(str(raw_path))
    if not path.is_absolute():
        raise SmartBuildError("PACKAGE", f"{source}: {label} must be absolute inside rootfs: {raw_path}")
    relative = PurePosixPath(*path.parts[1:])
    if not relative.parts:
        raise SmartBuildError("PACKAGE", f"{source}: {label} must name a file: {raw_path}")
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise SmartBuildError("PACKAGE", f"{source}: unsafe {label}: {raw_path}")
    return relative


def _optional_rootfs_output_paths(description, value, label):
    if value is None:
        return []
    if not isinstance(value, list) or not value:
        raise SmartBuildError("PACKAGE", f"{description.path}: {label} must be a non-empty list")
    return [_safe_rootfs_relative_path(item, label, description.path) for item in value]


def _build_commands(toolchain, source_dir, workdir, sources, static_library, shared_library):
    objects = [Path(source).with_suffix(".o").name for source in sources]
    commands = []
    for source, obj in zip(sources, objects):
        commands.append(
            [
                str(toolchain.gcc),
                "-c",
                "-fPIC",
                "-O2",
                "-I",
                str(source_dir),
                str(source_dir / source),
                "-o",
                str(workdir / obj),
            ]
        )
    commands.append([str(_tool_path(toolchain, "ar")), "rcs", str(workdir / static_library), *[str(workdir / obj) for obj in objects]])
    commands.append([str(toolchain.gcc), "-shared", "-o", str(workdir / shared_library), *[str(workdir / obj) for obj in objects]])
    return commands


def _executable_target_commands(toolchain, source_dir, workdir, host_include_dir, sources, output):
    return [
        [
            str(toolchain.gcc),
            "-O2",
            "-I",
            str(source_dir),
            "-I",
            str(host_include_dir),
            *[str(source_dir / source) for source in sources],
            "-o",
            str(output),
        ]
    ]


def _install_package_files(staged_dir, headers, libraries):
    files = []
    for header in headers:
        files.append({"source": str(staged_dir / "include" / header), "path": f"/include/{header}", "mode": 0o644})
    for library in libraries:
        files.append(
            {
                "source": str(staged_dir / "lib" / library),
                "path": f"/lib/{library}",
                "mode": 0o755 if library.endswith(".so") else 0o644,
            }
        )
    return files


def _python_install_files(staged_dir, output_paths):
    files = []
    stage_root = Path(staged_dir)
    for path in output_paths:
        candidate = stage_root.joinpath(*path.parts)
        install_path = f"/{path.as_posix()}"
        if candidate.is_dir():
            for child in sorted(candidate.rglob("*")):
                if child.is_dir():
                    continue
                try:
                    relative = child.relative_to(stage_root)
                except ValueError as exc:
                    raise SmartBuildError("BUILD", f"package install file escapes staged package: {child}") from exc
                child_install_path = f"/{relative.as_posix()}"
                files.append(
                    {
                        "source": str(child),
                        "path": child_install_path,
                        "mode": 0o755 if _is_executable_output_path(child_install_path) else 0o644,
                    }
                )
            continue
        files.append(
            {
                "source": str(candidate),
                "path": install_path,
                "mode": 0o755 if _is_executable_output_path(install_path) else 0o644,
            }
        )
    return files


def _require_python_outputs(staged_dir, output_paths):
    files = _python_install_files(staged_dir, output_paths)
    stage_root = Path(staged_dir).resolve()
    for item in files:
        candidate = Path(item["source"])
        if not candidate.exists():
            raise SmartBuildError("BUILD", f"sbuild.py did not create output: {candidate}")
        if candidate.is_symlink():
            raise SmartBuildError("BUILD", f"refusing symlink package install file: {candidate}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(stage_root)
        except ValueError as exc:
            raise SmartBuildError("BUILD", f"package install file escapes staged package: {candidate}") from exc
        if not candidate.is_file():
            raise SmartBuildError("BUILD", f"refusing non-file package install file: {candidate}")
        candidate.chmod(item["mode"])
    return files


def _is_header_path(path):
    return "/include/" in path or path.endswith(".h") or path.endswith(".hpp")


def _is_library_path(path):
    name = Path(path).name
    if name.endswith((".a", ".so")):
        return True
    if ".so." not in name:
        return False
    version = name.split(".so.", 1)[1]
    return bool(version) and version.replace(".", "").isdigit()


def _is_shared_library_path(path):
    return path.endswith(".so") or ".so." in path


def _is_executable_output_path(path):
    if _is_header_path(path):
        return False
    if path.endswith(".a"):
        return False
    return (
        _is_shared_library_path(path)
        or "/bin/" in path
        or "/sbin/" in path
        or "/libexec/" in path
    )


def _package_input_paths(source_dir, source_files, headers):
    inputs = []
    seen = set()
    for name in [*source_files, *headers]:
        if name in seen:
            continue
        seen.add(name)
        inputs.append(source_dir / name)
    return inputs


def _validate_source_dir(repo_root, source_dir, description_path):
    root = Path(repo_root).resolve()
    resolved = Path(source_dir).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError(
            "PACKAGE",
            f"{description_path}: source.directory escapes repository: {source_dir}",
        ) from exc


def _validate_sources(source_dir, files):
    if not source_dir.is_dir():
        raise SmartBuildError("PACKAGE", f"source directory not found: {source_dir}")
    source_root = source_dir.resolve()
    for name in sorted(set(files)):
        source = source_dir / name
        if not source.is_file():
            raise SmartBuildError("PACKAGE", f"package source not found: {source}")
        resolved = source.resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise SmartBuildError(
                "PACKAGE",
                f"package source escapes source directory: {source}",
            ) from exc
        if source.is_symlink():
            raise SmartBuildError("PACKAGE", f"refusing symlink package source: {source}")


def _command_source_files(commands):
    result = []
    for command in commands:
        for value in command:
            if str(value).endswith(".c"):
                result.append(Path(value).name)
    return result


def _command_output_files(commands):
    outputs = []
    for command in commands:
        if "-o" in command:
            outputs.append(Path(command[command.index("-o") + 1]))
        if "--output" in command:
            outputs.append(Path(command[command.index("--output") + 1]))
        elif len(command) > 2 and Path(command[0]).name.endswith("ar"):
            outputs.append(Path(command[2]))
    return outputs


def _prepare_work_outputs(work_root, outputs):
    resolved_work_root = Path(work_root).resolve()
    for output in outputs:
        target = Path(output)
        if target.is_symlink():
            raise SmartBuildError("BUILD", f"refusing to replace symlink output: {target}")
        resolved = target.resolve(strict=False)
        try:
            resolved.relative_to(resolved_work_root)
        except ValueError as exc:
            raise SmartBuildError("BUILD", f"package work output escapes work dir: {target}") from exc
        if not target.exists():
            continue
        if not target.is_file():
            raise SmartBuildError("BUILD", f"refusing to replace non-file output: {target}")
        if target.stat().st_nlink > 1:
            raise SmartBuildError("BUILD", f"refusing to replace hardlink output: {target}")
        target.unlink()


def _prepare_stage(path, staging_root):
    root = Path(staging_root).resolve()
    stage = Path(path)
    if stage.is_symlink():
        raise SmartBuildError("BUILD", f"refusing to replace symlink package stage: {stage}")
    resolved = stage.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("BUILD", f"package stage path escapes staging dir: {stage}") from exc
    if stage.exists():
        if not stage.is_dir():
            raise SmartBuildError("BUILD", f"refusing to replace non-directory package stage: {stage}")
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)


def _validate_existing_stage(path, staging_root):
    root = Path(staging_root).resolve()
    stage = Path(path)
    if stage.is_symlink():
        raise SmartBuildError("BUILD", f"refusing symlink package stage: {stage}")
    resolved = stage.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("BUILD", f"package stage path escapes staging dir: {stage}") from exc
    if stage.exists() and not stage.is_dir():
        raise SmartBuildError("BUILD", f"refusing non-directory package stage: {stage}")


def _validate_existing_install_files(staged_dir, headers, libraries):
    stage_root = Path(staged_dir).resolve()
    for candidate in _expected_install_paths(staged_dir, headers, libraries):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if candidate.is_symlink():
            raise SmartBuildError("BUILD", f"refusing symlink package install file: {candidate}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(stage_root)
        except ValueError as exc:
            raise SmartBuildError("BUILD", f"package install file escapes staged package: {candidate}") from exc
        file_stat = candidate.stat()
        if stat.S_ISDIR(file_stat.st_mode):
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            raise SmartBuildError("BUILD", f"refusing non-file package install file: {candidate}")
        if file_stat.st_nlink > 1:
            raise SmartBuildError("BUILD", f"refusing hardlink package install file: {candidate}")


def _validate_existing_package_paths(staged_dir, paths):
    stage_root = Path(staged_dir).resolve()
    for relative in paths:
        candidate = Path(staged_dir).joinpath(*relative.parts)
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if candidate.is_symlink():
            raise SmartBuildError("BUILD", f"refusing symlink package install file: {candidate}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(stage_root)
        except ValueError as exc:
            raise SmartBuildError("BUILD", f"package install file escapes staged package: {candidate}") from exc
        file_stat = candidate.stat()
        if stat.S_ISDIR(file_stat.st_mode):
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            raise SmartBuildError("BUILD", f"refusing non-file package install file: {candidate}")
        if file_stat.st_nlink > 1:
            raise SmartBuildError("BUILD", f"refusing hardlink package install file: {candidate}")


def _require_safe_stage_output(staged_dir, output, package_name):
    candidate = Path(output)
    relative = candidate.relative_to(staged_dir)
    _validate_existing_package_paths(staged_dir, [relative])
    if not candidate.is_file():
        raise SmartBuildError(
            "BUILD", f"package {package_name} missing CMake output: {candidate}"
        )


def _validate_existing_host_outputs(work_root, outputs):
    for output in outputs:
        if output.exists() or output.is_symlink():
            _require_safe_host_output(work_root, output, "cached package host output")


def _require_safe_host_output(work_root, output, label, missing_message=None):
    root = Path(work_root).resolve()
    candidate = Path(output)
    if candidate.is_symlink():
        raise SmartBuildError("BUILD", f"refusing symlink {label}: {candidate}")
    if not candidate.exists():
        raise SmartBuildError("BUILD", missing_message or f"{label} not found: {candidate}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("BUILD", f"{label} escapes work dir: {candidate}") from exc
    file_stat = candidate.stat()
    if not stat.S_ISREG(file_stat.st_mode):
        raise SmartBuildError("BUILD", f"refusing non-file {label}: {candidate}")
    if file_stat.st_nlink > 1:
        raise SmartBuildError("BUILD", f"refusing hardlink {label}: {candidate}")


def _expected_install_paths(staged_dir, headers, libraries):
    for header in headers:
        yield Path(staged_dir) / "include" / header
    for library in libraries:
        yield Path(staged_dir) / "lib" / library


def _copy_source_file(source, destination, mode):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink():
            raise SmartBuildError("BUILD", f"refusing to replace symlink output: {destination}")
        destination.unlink()
    shutil.copy2(source, destination)
    destination.chmod(mode)


def _sbuild_env(task_env, name, source_dir, workdir, staged_dir, staging_root, toolchain):
    env = _compile_env(task_env)
    env.update(
        {
            "SMART_BUILD_PACKAGE": name,
            "SMART_BUILD_SOURCE_DIR": str(source_dir),
            "SMART_BUILD_WORK_DIR": str(workdir),
            "SMART_BUILD_STAGE_DIR": str(staged_dir),
            "SMART_BUILD_STAGING_DIR": str(staging_root),
            "SMART_BUILD_PACKAGES_STAGING_DIR": str(Path(staging_root) / PACKAGE_STAGE_DIR),
            "SMART_BUILD_TARGET": str(toolchain.target),
            "SMART_BUILD_TOOLCHAIN_ROOT": str(toolchain.root),
            "SMART_BUILD_TOOLCHAIN_BIN": str(toolchain.bin_dir),
            "SMART_BUILD_CROSS_COMPILE": str(toolchain.prefix),
            "CC": str(toolchain.gcc),
            "CXX": str(getattr(toolchain, "gxx", _tool_path(toolchain, "g++"))),
            "LD": str(_tool_path(toolchain, "ld")),
            "NM": str(_tool_path(toolchain, "nm")),
            "AS": str(_tool_path(toolchain, "as")),
            "AR": str(_tool_path(toolchain, "ar")),
            "RANLIB": str(_tool_path(toolchain, "ranlib")),
            "STRIP": str(_tool_path(toolchain, "strip")),
            "OBJCOPY": str(_tool_path(toolchain, "objcopy")),
            "READELF": str(_tool_path(toolchain, "readelf")),
        }
    )
    return env


def _verify_architecture(toolchain, library, runner, workdir, env, log):
    tool = _tool_path(toolchain, "readelf")
    expected = _expected_readelf_machine(toolchain)
    if not tool.is_file():
        reason = f"{tool} not found"
        log.write(f"architecture check skipped: {reason}\n")
        return {
            "status": "skipped",
            "tool": str(tool),
            "library": str(library),
            "expected_machine": expected["display"],
            "reason": reason,
        }
    command = [str(tool), "-h", str(library)]
    completed = runner(command, cwd=workdir, env=_inspection_env(env))
    _write_completed_command(log, command, workdir, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "BUILD",
            f"architecture check failed: command={' '.join(command)} exit code {completed.returncode} log={log.name}",
        )
    actual = _readelf_machine(completed.stdout)
    if not _machine_matches(actual, expected["accepted"]):
        raise SmartBuildError(
            "BUILD",
            "architecture check failed for {library}: expected {expected}, got {actual}".format(
                library=library,
                expected=expected["display"],
                actual=actual or "<unknown>",
            ),
        )
    return {
        "status": "verified",
        "tool": str(tool),
        "library": str(library),
        "expected_machine": expected["display"],
        "actual_machine": actual,
    }


def _verify_library_output_architecture(toolchain, library, runner, workdir, env, log):
    library = Path(library)
    if library.name.endswith(".a"):
        return _verify_static_archive_architecture(toolchain, library, runner, workdir, env, log)
    return _verify_architecture(toolchain, library, runner, workdir, env, log)


def _verify_static_archive_architecture(toolchain, archive, runner, workdir, env, log):
    ar_tool = _tool_path(toolchain, "ar")
    readelf_tool = _tool_path(toolchain, "readelf")
    expected = _expected_readelf_machine(toolchain)
    if not ar_tool.is_file() or not readelf_tool.is_file():
        missing = [str(tool) for tool in (ar_tool, readelf_tool) if not tool.is_file()]
        reason = "missing tools: " + ", ".join(missing)
        log.write(f"architecture check skipped: {reason}\n")
        return {
            "status": "skipped",
            "tool": str(readelf_tool),
            "archive_tool": str(ar_tool),
            "library": str(archive),
            "expected_machine": expected["display"],
            "reason": reason,
        }
    command = [str(ar_tool), "t", str(archive)]
    completed = runner(command, cwd=workdir, env=env)
    _write_completed_command(log, command, workdir, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "BUILD",
            f"architecture check failed: command={' '.join(command)} exit code {completed.returncode} log={log.name}",
        )
    first_member = _first_archive_member(completed.stdout)
    if not first_member:
        raise SmartBuildError("BUILD", f"architecture check failed for {archive}: archive has no members")
    extract_dir = Path(workdir) / ".smart-build-archive-check"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    command = [str(ar_tool), "x", str(archive), first_member]
    completed = runner(command, cwd=extract_dir, env=env)
    _write_completed_command(log, command, extract_dir, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "BUILD",
            f"architecture check failed: command={' '.join(command)} exit code {completed.returncode} log={log.name}",
        )
    extracted = extract_dir / first_member
    if not extracted.is_file():
        raise SmartBuildError("BUILD", f"architecture check failed for {archive}: failed to extract {first_member}")
    command = [str(readelf_tool), "-h", str(extracted)]
    completed = runner(command, cwd=workdir, env=_inspection_env(env))
    _write_completed_command(log, command, workdir, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "BUILD",
            f"architecture check failed: command={' '.join(command)} exit code {completed.returncode} log={log.name}",
        )
    actual = _readelf_machine(completed.stdout)
    if not _machine_matches(actual, expected["accepted"]):
        raise SmartBuildError(
            "BUILD",
            "architecture check failed for {library}: expected {expected}, got {actual}".format(
                library=archive,
                expected=expected["display"],
                actual=actual or "<unknown>",
            ),
        )
    return {
        "status": "verified",
        "tool": str(readelf_tool),
        "archive_tool": str(ar_tool),
        "library": str(archive),
        "member": first_member,
        "expected_machine": expected["display"],
        "actual_machine": actual,
    }


def _verify_binary_architecture(toolchain, binary, runner, workdir, env, log):
    tool = _tool_path(toolchain, "readelf")
    expected = _expected_readelf_machine(toolchain)
    if not tool.is_file():
        reason = f"{tool} not found"
        log.write(f"architecture check skipped: {reason}\n")
        return {
            "status": "skipped",
            "tool": str(tool),
            "binary": str(binary),
            "expected_machine": expected["display"],
            "reason": reason,
        }
    command = [str(tool), "-h", str(binary)]
    completed = runner(command, cwd=workdir, env=_inspection_env(env))
    _write_completed_command(log, command, workdir, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "BUILD",
            f"architecture check failed: command={' '.join(command)} exit code {completed.returncode} log={log.name}",
        )
    actual = _readelf_machine(completed.stdout)
    if not _machine_matches(actual, expected["accepted"]):
        raise SmartBuildError(
            "BUILD",
            "architecture check failed for {binary}: expected {expected}, got {actual}".format(
                binary=binary,
                expected=expected["display"],
                actual=actual or "<unknown>",
            ),
        )
    return {
        "status": "verified",
        "tool": str(tool),
        "binary": str(binary),
        "expected_machine": expected["display"],
        "actual_machine": actual,
    }


def _verify_cmake_output(
    toolchain, binary, expected_linkage, runner, workdir, env, log
):
    architecture = _verify_binary_architecture(
        toolchain, binary, runner, workdir, env, log
    )
    if architecture["status"] == "skipped":
        return {
            **architecture,
            "expected_linkage": expected_linkage,
            "linkage_status": "skipped",
        }

    readelf = _tool_path(toolchain, "readelf")
    inspection_env = _inspection_env(env)
    outputs = []
    for option in ("-lW", "-dW"):
        command = [str(readelf), option, str(binary)]
        completed = runner(command, cwd=workdir, env=inspection_env)
        _write_completed_command(log, command, workdir, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "BUILD",
                "linkage check failed: command={command} exit code {exit_code}".format(
                    command=" ".join(command),
                    exit_code=completed.returncode,
                ),
            )
        outputs.append(completed.stdout or "")

    linkage = parse_readelf_linkage(*outputs)
    if linkage["linkage"] != expected_linkage:
        raise SmartBuildError(
            "BUILD",
            f"{binary} declared {expected_linkage} but ELF is {linkage['linkage']}",
        )
    return {
        **architecture,
        "expected_linkage": expected_linkage,
        "actual_linkage": linkage["linkage"],
        "interpreter": linkage["interpreter"],
        "needed": linkage["needed"],
        "linkage_status": "verified",
    }


def _readelf_machine(output):
    for line in str(output).splitlines():
        if "Machine:" in line:
            return line.split("Machine:", 1)[1].strip()
        if ":" in line:
            label, value = line.split(":", 1)
            if "架构" in label:
                return value.strip()
    return ""


def _first_archive_member(output):
    for line in str(output).splitlines():
        name = line.strip()
        if name:
            return name
    return None


def _expected_readelf_machine(toolchain):
    target = str(getattr(toolchain, "target", ""))
    if target.startswith("aarch64-"):
        return {"display": "AArch64", "accepted": ("aarch64",)}
    if target.startswith("riscv64-"):
        return {"display": "RISC-V", "accepted": ("risc-v", "riscv")}
    if target == "arm-none-eabi" or target.startswith("arm-"):
        return {"display": "ARM", "accepted": ("arm",)}
    raise SmartBuildError("BUILD", f"unsupported package target architecture: {target}")


def _machine_matches(actual, accepted):
    normalized = str(actual).strip().lower()
    return any(token in normalized for token in accepted)


def _tool_path(toolchain, tool):
    return Path(toolchain.bin_dir) / f"{toolchain.prefix}{tool}"


def _inspection_env(env):
    result = dict(env)
    result.update({"LC_ALL": "C", "LANG": "C", "LANGUAGE": "C"})
    return result


def _compile_env(task_env):
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
        raise SmartBuildError("BUILD", f"failed to run package command {command}: {exc}") from exc


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
