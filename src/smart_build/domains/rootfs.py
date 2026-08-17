import json
import shutil
from pathlib import Path

from ..cache import path_record
from ..errors import SmartBuildError
from ..tasks import Task
from .ipkg import install_ipkg
from .toolchain import resolve_toolchain, toolchain_task_fields


ROOTFS_TASK_ID = "rootfs:stage"
ROOTFS_DIR_NAME = "rootfs-minimal"
ROOTFS_MANIFEST = "MANIFEST.json"
ROOTFS_MANIFEST_NAME = "rootfs-minimal.manifest.json"
REQUIRED_DIRS = (
    "bin",
    "dev",
    "dev/shm",
    "etc",
    "lib",
    "mnt",
    "proc",
    "root",
    "run",
    "services",
    "tmp",
    "var",
)


def rootfs_stage_task(paths, package_tasks, toolchain=None, base_rootfs_task=None):
    packages = list(package_tasks)
    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    rootfs_dir = paths.staging_dir / ROOTFS_DIR_NAME
    manifest_path = paths.staging_dir / ROOTFS_MANIFEST_NAME
    runtime_libs = _runtime_libraries(resolved_toolchain)
    package_records = [_package_record(task) for task in packages]
    base_rootfs = Path(base_rootfs_task.outputs[0]) if base_rootfs_task is not None else None

    return Task(
        id=ROOTFS_TASK_ID,
        domain="rootfs",
        action="stage",
        inputs=[*(task.outputs[0] for task in packages), *runtime_libs, *([base_rootfs] if base_rootfs is not None else [])],
        outputs=[rootfs_dir, manifest_path],
        deps=("toolchain:check", *(task.id for task in packages), *([base_rootfs_task.id] if base_rootfs_task is not None else [])),
        workdir=paths.work_dir / "rootfs-stage",
        env={"MACHINE": paths.machine, **fields["env"]},
        run_class="serial",
        cache_policy="never",
        log_path=paths.logs_dir / "rootfs-stage.log",
        executor=_make_rootfs_executor(
            paths,
            rootfs_dir,
            manifest_path,
            package_records,
            runtime_libs,
            resolved_toolchain,
            base_rootfs,
        ),
        cache_extra={
            **fields["cache_extra"],
            "rootfs": {
                "path": str(rootfs_dir),
                "base_rootfs": str(base_rootfs) if base_rootfs is not None else None,
                "required_dirs": list(REQUIRED_DIRS),
                "packages": package_records,
                "runtime_libs": [str(path) for path in runtime_libs],
            },
        },
        manifest_fields={
            **fields["manifest_fields"],
            "rootfs": {
                "name": "full" if base_rootfs is not None else "minimal",
                "path": str(rootfs_dir),
                "base_rootfs": str(base_rootfs) if base_rootfs is not None else None,
                "manifest": str(manifest_path),
                "required_dirs": list(REQUIRED_DIRS),
                "packages": package_records,
                "runtime_libs": [str(path) for path in runtime_libs],
            },
        },
    )


def _make_rootfs_executor(paths, rootfs_dir, manifest_path, package_records, runtime_libs, toolchain, base_rootfs=None):
    def executor(task, log):
        _validate_staging_target(paths, rootfs_dir)
        if rootfs_dir.exists() or rootfs_dir.is_symlink():
            shutil.rmtree(rootfs_dir)
        source_map = {}
        if base_rootfs is None:
            rootfs_dir.mkdir(parents=True)
        else:
            if not base_rootfs.is_dir():
                raise SmartBuildError("ROOTFS", f"base rootfs directory not found: {base_rootfs}")
            shutil.copytree(base_rootfs, rootfs_dir, symlinks=True)
            for path in rootfs_dir.rglob("*"):
                relative = path.relative_to(rootfs_dir).as_posix()
                source_map[relative] = str(base_rootfs / relative)
            log.write(f"copied base rootfs: {base_rootfs} -> {rootfs_dir}\n")

        for dirname in REQUIRED_DIRS:
            directory = _rootfs_child(rootfs_dir, dirname)
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o1777 if dirname == "tmp" else 0o755)
            source_map.setdefault(dirname, "rootfs-directory")

        for library in runtime_libs:
            requested = Path(library)
            source = _runtime_library_source(requested, toolchain)
            destination = _rootfs_child(rootfs_dir, f"lib/{requested.name}")
            shutil.copy2(source, destination)
            source_map[destination.relative_to(rootfs_dir).as_posix()] = str(source)
            log.write(f"installed runtime library: {source} -> {destination}\n")

        package_entries = []
        for package in package_records:
            source = Path(package["file"])
            if not source.is_file():
                raise SmartBuildError("ROOTFS", f"ipkg package not found: {source}")
            records = install_ipkg(source, rootfs_dir)
            package["checksum"] = path_record(source).get("sha256")
            for record in records:
                source_map[record["path"]] = record
                package_entries.append(record)
                log.write(f"installed package file into rootfs: {source} -> {record['path']}\n")

        rootfs_name = task.manifest_fields["rootfs"]["name"]
        manifest = _rootfs_manifest(rootfs_dir, source_map, rootfs_name)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        task.manifest_fields["rootfs"]["manifest"] = str(manifest_path)
        task.manifest_fields["rootfs"]["entry_count"] = len(manifest["entries"])
        task.manifest_fields["rootfs"]["checksum"] = path_record(rootfs_dir).get("sha256")
        task.manifest_fields["rootfs"]["installed_packages"] = package_entries
        log.write(f"wrote rootfs manifest: {manifest_path}\n")
        return 0

    return executor


def _package_record(task):
    package = dict(task.manifest_fields.get("package", {}))
    if not package:
        raise SmartBuildError("ROOTFS", f"package task missing package manifest fields: {task.id}")
    install_path = package.get("install_path", "")
    if not install_path.startswith("/"):
        raise SmartBuildError("ROOTFS", f"package task has unsafe install path: {task.id} {install_path}")
    _safe_relative_install_path(install_path)
    package["task_id"] = task.id
    package["file"] = str(task.outputs[0])
    return package


def _runtime_libraries(toolchain):
    candidates = [
        toolchain.loader,
        toolchain.libc,
        toolchain.libgcc_runtime,
        getattr(toolchain, "libatomic_runtime", None),
        getattr(toolchain, "libstdcxx_runtime", None),
    ]
    return [Path(path) for path in candidates if path is not None]


def _runtime_library_source(path, toolchain):
    requested = Path(path)
    if requested.is_file():
        return requested
    if requested.is_symlink():
        link_target = requested.readlink()
        if link_target.is_absolute():
            sysroot_target = Path(toolchain.root) / toolchain.target / link_target.relative_to("/")
            if sysroot_target.is_file():
                return sysroot_target
    raise SmartBuildError("ROOTFS", f"runtime library not found: {requested}")


def _rootfs_manifest(rootfs_dir, source_map, name="minimal"):
    entries = []
    for path in sorted(rootfs_dir.rglob("*"), key=lambda item: item.relative_to(rootfs_dir).as_posix()):
        if path.name == ROOTFS_MANIFEST and path.parent == rootfs_dir:
            continue
        record = path_record(path)
        relative = path.relative_to(rootfs_dir).as_posix()
        entries.append(
            {
                "path": relative,
                "type": record.get("type"),
                "mode": record.get("mode"),
                "source": source_map.get(relative, "generated"),
                **_package_entry_fields(source_map.get(relative)),
                "checksum": record.get("sha256"),
            }
        )
    return {
        "schema_version": 1,
        "name": name,
        "entries": entries,
    }


def _package_entry_fields(source):
    if not isinstance(source, dict):
        return {}
    return {
        "source": source["source"],
        "package": source["package"],
        "package_version": source["version"],
    }


def _validate_staging_target(paths, rootfs_dir):
    staging_root = paths.staging_dir.resolve()
    target = rootfs_dir.resolve()
    try:
        target.relative_to(staging_root)
    except ValueError as exc:
        raise SmartBuildError("ROOTFS", f"rootfs path escapes staging dir: {rootfs_dir}") from exc


def _rootfs_child(rootfs_dir, relative_path):
    relative = _safe_relative_install_path(relative_path)
    destination = rootfs_dir.joinpath(*relative.parts)
    root = rootfs_dir.resolve()
    resolved = destination.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("ROOTFS", f"rootfs install path escapes rootfs: {relative_path}") from exc
    return destination


def _safe_relative_install_path(raw_path):
    path = Path(raw_path)
    if path.is_absolute():
        path = Path(*path.parts[1:])
    if not path.parts:
        raise SmartBuildError("ROOTFS", f"empty rootfs path: {raw_path}")
    for part in path.parts:
        if part in {"", ".", ".."}:
            raise SmartBuildError("ROOTFS", f"unsafe rootfs path: {raw_path}")
    return path
