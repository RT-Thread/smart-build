import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import warnings
import zipfile
from pathlib import Path

from ..cache import path_record
from ..errors import SmartBuildError
from ..tasks import Task


RT_THREAD_TASK_ID = "source:rt-thread"
RT_THREAD_GIT_URL = "https://github.com/RT-Thread/rt-thread.git"
RT_THREAD_GIT_BRANCH = "master"
LWEXT4_TASK_ID = "source:lwext4"
LWEXT4_PACKAGE_METADATA = Path.home() / ".env" / "packages" / "packages" / "system" / "lwext4" / "package.json"
LWEXT4_ARCHIVE_SUFFIXES = (
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".zip",
)


def rt_thread_source_task(paths, command_runner=None):
    source = paths.root / "rt-thread"
    marker = paths.stamps_dir / "sources" / "rt-thread.ok"
    return Task(
        id=RT_THREAD_TASK_ID,
        domain="source",
        action="rt-thread",
        outputs=[marker],
        deps=["config:load"],
        workdir=paths.work_dir / "sources" / "rt-thread-task",
        env={"MACHINE": paths.machine},
        run_class="fetch",
        cache_policy="never",
        log_path=paths.logs_dir / "source-rt-thread.log",
        executor=_make_rt_thread_executor(paths, command_runner),
        cache_extra={
            "url": RT_THREAD_GIT_URL,
            "branch": RT_THREAD_GIT_BRANCH,
            "source": str(source),
        },
        manifest_fields={
            "rt_thread": _rt_thread_source_record(source, reused=None),
        },
    )


def _make_rt_thread_executor(paths, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        source = paths.root / "rt-thread"
        if _is_valid_rt_thread_source(source):
            _complete_rt_thread_task(task, source, reused=True, log=log)
            log.write(f"using existing RT-Thread source: {source}\n")
            return 0

        if source.exists() or source.is_symlink():
            raise SmartBuildError(
                "SOURCE",
                f"invalid RT-Thread source at {source}: expected a directory containing bsp; "
                "refusing to replace the existing path",
            )

        clone_dir = paths.work_dir / "sources" / "rt-thread-clone"
        _remove_path(clone_dir)
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        command = _rt_thread_git_clone_command(clone_dir)
        try:
            completed = runner(command, cwd=clone_dir.parent, env=os.environ.copy())
            _write_completed_command(log, command, clone_dir.parent, completed)
            if completed.returncode != 0:
                raise SmartBuildError(
                    "SOURCE",
                    "failed to fetch RT-Thread source from {url} branch {branch}; "
                    "log={log_path}".format(
                        url=RT_THREAD_GIT_URL,
                        branch=RT_THREAD_GIT_BRANCH,
                        log_path=task.log_path,
                    ),
                )
            if not _is_valid_rt_thread_source(clone_dir):
                raise SmartBuildError(
                    "SOURCE",
                    f"fetched RT-Thread source missing bsp directory: {clone_dir}",
                )
            try:
                clone_dir.rename(source)
            except OSError as exc:
                raise SmartBuildError(
                    "SOURCE",
                    f"failed to install RT-Thread source at {source}: {exc}",
                ) from exc
        finally:
            _remove_path(clone_dir)

        _complete_rt_thread_task(task, source, reused=False, log=log)
        log.write(
            "fetched RT-Thread source: {url} branch={branch} -> {source}\n".format(
                url=RT_THREAD_GIT_URL,
                branch=RT_THREAD_GIT_BRANCH,
                source=source,
            )
        )
        return 0

    return executor


def _rt_thread_git_clone_command(clone_dir):
    return [
        "git",
        "clone",
        "--branch",
        RT_THREAD_GIT_BRANCH,
        "--depth",
        "1",
        RT_THREAD_GIT_URL,
        str(clone_dir),
    ]


def _is_valid_rt_thread_source(path):
    source = Path(path)
    return source.is_dir() and (source / "bsp").is_dir()


def _rt_thread_source_record(source, reused):
    return {
        "path": str(source),
        "url": RT_THREAD_GIT_URL,
        "branch": RT_THREAD_GIT_BRANCH,
        "revision": _git_output(source, "rev-parse", "HEAD", require_own_repo=True),
        "dirty": _git_dirty(source),
        "reused": reused,
    }


def _complete_rt_thread_task(task, source, reused, log):
    record = _rt_thread_source_record(source, reused=reused)
    task.manifest_fields["rt_thread"] = record
    marker = task.outputs[0]
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log.write(f"wrote RT-Thread source record: {marker}\n")


def lwext4_source_task(paths, command_runner=None, package_metadata_path=None):
    metadata_path = Path(package_metadata_path) if package_metadata_path is not None else LWEXT4_PACKAGE_METADATA
    prepared = lwext4_prepared_source(paths)
    manifest = _initial_manifest(paths, metadata_path)
    return Task(
        id=LWEXT4_TASK_ID,
        domain="source",
        action="lwext4",
        inputs=_task_inputs(paths, metadata_path),
        outputs=[prepared],
        deps=["config:load"],
        workdir=paths.work_dir / "sources" / "lwext4-task",
        env={"MACHINE": paths.machine},
        run_class="fetch",
        cache_policy="never",
        log_path=paths.logs_dir / "source-lwext4.log",
        executor=_make_lwext4_executor(paths, metadata_path, command_runner),
        cache_extra={
            "prepared": str(prepared),
            "source_candidates": [str(path) for path in _local_directory_candidates(paths)],
            "archive_candidates": [str(path) for path in _archive_candidates(paths)],
            "package_metadata": str(metadata_path),
        },
        manifest_fields={"lwext4": manifest},
    )


def lwext4_prepared_source(paths):
    return paths.root / "downloads" / "sources-unpack" / "lwext4"


def lwext4_source_candidates(paths):
    return (
        lwext4_prepared_source(paths),
        paths.root / "downloads" / "lwext4",
    )


def prepare_lwext4_bsp_package(paths, package_dir, log, package_sconscript_source=None):
    source = lwext4_prepared_source(paths)
    manifest = {
        "package_dir": str(package_dir),
        "prepared_source": str(source),
        "prepared": False,
        "package_sconscript": None,
    }
    if not source.is_dir():
        log.write(f"lwext4 source not found: prepared source not found: {source}\n")
        raise SmartBuildError(
            "SOURCE",
            f"lwext4 prepared source not found: {source}; run source:lwext4 before kernel:build",
        )
    sconscript = source / "SConscript"
    if not sconscript.is_file():
        log.write(f"invalid lwext4 source: prepared source missing SConscript: {sconscript}\n")
        raise SmartBuildError("SOURCE", f"lwext4 prepared source missing SConscript: {sconscript}")
    _replace_directory(source, package_dir, ignore=_ignore_git_directories)
    package_sconscript = _ensure_package_sconscript(package_dir.parent, package_sconscript_source, log)
    manifest["prepared"] = True
    manifest["package_sconscript"] = str(package_sconscript)
    log.write(f"prepared lwext4 package: {source} -> {package_dir}\n")
    return manifest


def _make_lwext4_executor(paths, metadata_path, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        prepared = lwext4_prepared_source(paths)
        manifest = _initial_manifest(paths, metadata_path)
        task.manifest_fields["lwext4"] = manifest

        prepared_candidate = prepared
        if _is_valid_lwext4_source(prepared_candidate):
            manifest["source"] = _local_source_record("prepared", prepared_candidate, reused=True)
            _remove_prepared_git_metadata(prepared_candidate, log)
            log.write(f"using existing prepared lwext4 source: {prepared_candidate}\n")
            _complete_manifest(paths, manifest, log)
            return 0

        local_source = _first_existing_directory(
            candidate for candidate in _local_directory_candidates(paths) if candidate != prepared_candidate
        )
        if local_source is not None:
            _copy_valid_source(local_source, prepared, log, manifest, "local-directory", cleanup_source_git=True)
            return 0

        archive = _first_existing_archive(_archive_candidates(paths))
        if archive is not None:
            _extract_valid_archive(archive, prepared, log, manifest)
            return 0

        fetch_info = _latest_git_source(metadata_path)
        if fetch_info is None:
            searched = _searched_paths(paths, metadata_path)
            log.write("lwext4 source not found; searched:\n")
            for path in searched:
                log.write(f"  - {path}\n")
            raise SmartBuildError(
                "SOURCE",
                "lwext4 source not found and package metadata does not provide a latest git source; "
                f"searched: {', '.join(str(path) for path in searched)}",
            )

        clone_dir = paths.work_dir / "sources" / "lwext4"
        _remove_path(clone_dir)
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        command = _git_clone_command(fetch_info, clone_dir)
        completed = runner(command, cwd=clone_dir.parent, env=os.environ.copy())
        _write_completed_command(log, command, clone_dir.parent, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "SOURCE",
                "failed to fetch lwext4 source from {url} branch {branch}; log={log_path}".format(
                    url=fetch_info["url"],
                    branch=fetch_info["branch"],
                    log_path=task.log_path,
                ),
            )
        if not _is_valid_lwext4_source(clone_dir):
            sconscript = clone_dir / "SConscript"
            log.write(f"invalid fetched lwext4 source: missing SConscript: {sconscript}\n")
            raise SmartBuildError("SOURCE", f"lwext4 source missing SConscript: {sconscript}")
        _replace_directory(clone_dir, prepared, ignore=_ignore_git_directories)
        log.write(f"fetched lwext4 source: {fetch_info['url']} branch={fetch_info['branch']} -> {prepared}\n")
        manifest["source"] = _git_source_record(fetch_info, clone_dir)
        _complete_manifest(paths, manifest, log)
        return 0

    return executor


def _copy_valid_source(source, prepared, log, manifest, kind, cleanup_source_git=False):
    if not _is_valid_lwext4_source(source):
        sconscript = source / "SConscript"
        log.write(f"invalid lwext4 source: missing SConscript: {sconscript}\n")
        raise SmartBuildError("SOURCE", f"lwext4 source missing SConscript: {sconscript}")
    _replace_directory(source, prepared, ignore=_ignore_git_directories)
    log.write(f"copied lwext4 source: {source} -> {prepared}\n")
    manifest["source"] = _local_source_record(kind, source, reused=False)
    if cleanup_source_git:
        _remove_git_metadata(source, log, "downloads")
    _complete_manifest_from_prepared(prepared, manifest, log)


def _extract_valid_archive(archive, prepared, log, manifest):
    work_parent = prepared.parent / ".extract-work"
    _remove_path(work_parent)
    work_parent.mkdir(parents=True, exist_ok=True)
    try:
        if archive.suffix == ".zip":
            _extract_zip_safely(archive, work_parent)
        else:
            _extract_tar_safely(archive, work_parent)
        source = _archive_source_root(work_parent)
        if not _is_valid_lwext4_source(source):
            sconscript = source / "SConscript"
            log.write(f"invalid lwext4 archive: missing SConscript: {sconscript}\n")
            raise SmartBuildError("SOURCE", f"lwext4 source missing SConscript: {sconscript}")
        _replace_directory(source, prepared, ignore=_ignore_git_directories)
        log.write(f"extracted lwext4 archive: {archive} -> {prepared}\n")
        manifest["source"] = _archive_source_record(archive)
        _complete_manifest_from_prepared(prepared, manifest, log)
    finally:
        _remove_path(work_parent)


def _archive_source_root(work_parent):
    if (work_parent / "SConscript").is_file():
        return work_parent
    children = [child for child in work_parent.iterdir() if child.name != "__MACOSX"]
    directories = [child for child in children if child.is_dir()]
    if len(children) == 1 and directories:
        return directories[0]
    return work_parent


def _extract_tar_safely(archive, destination):
    try:
        with tarfile.open(archive) as handle:
            members = handle.getmembers()
            for member in members:
                _validate_archive_member(destination, member.name)
                if member.issym() or member.islnk():
                    raise SmartBuildError("SOURCE", f"unsafe lwext4 archive member link: {member.name}")
                if not (member.isfile() or member.isdir()):
                    raise SmartBuildError(
                        "SOURCE",
                        f"unsupported lwext4 archive member type: {member.name}",
                    )
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning, module="tarfile")
                handle.extractall(destination, members=members)
    except (tarfile.TarError, OSError) as exc:
        raise SmartBuildError("SOURCE", f"failed to extract lwext4 archive {archive}: {exc}") from exc


def _extract_zip_safely(archive, destination):
    try:
        with zipfile.ZipFile(archive) as handle:
            for member in handle.infolist():
                _validate_archive_member(destination, member.filename)
            handle.extractall(destination)
    except (zipfile.BadZipFile, OSError) as exc:
        raise SmartBuildError("SOURCE", f"failed to extract lwext4 archive {archive}: {exc}") from exc


def _validate_archive_member(destination, name):
    if not name or Path(name).is_absolute():
        raise SmartBuildError("SOURCE", f"unsafe lwext4 archive member path: {name}")
    target = (destination / name).resolve()
    root = destination.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("SOURCE", f"unsafe lwext4 archive member path: {name}") from exc


def _latest_git_source(metadata_path):
    path = Path(metadata_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmartBuildError("SOURCE", f"failed to read lwext4 package metadata {path}: {exc}") from exc
    for entry in data.get("site", []):
        if entry.get("version") != "latest":
            continue
        url = (entry.get("URL") or "").strip()
        if not url:
            continue
        branch = (entry.get("VER_SHA") or "master").strip() or "master"
        return {"url": url, "branch": branch, "metadata_path": str(path)}
    return None


def _git_clone_command(fetch_info, clone_dir):
    return [
        "git",
        "clone",
        "--branch",
        fetch_info["branch"],
        "--depth",
        "1",
        fetch_info["url"],
        str(clone_dir),
    ]


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
        raise SmartBuildError("SOURCE", f"failed to run source command {command}: {exc}") from exc


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


def _task_inputs(paths, metadata_path):
    inputs = [candidate for candidate in _local_directory_candidates(paths) if candidate.exists()]
    inputs.extend(candidate for candidate in _archive_candidates(paths) if candidate.exists())
    if Path(metadata_path).exists():
        inputs.append(Path(metadata_path))
    return inputs


def _local_directory_candidates(paths):
    return (
        lwext4_prepared_source(paths),
        paths.root / "downloads" / "lwext4",
    )


def _archive_candidates(paths):
    downloads = paths.root / "downloads"
    if not downloads.is_dir():
        return ()
    candidates = []
    for child in sorted(downloads.iterdir(), key=lambda item: item.name):
        if child.is_file() and _is_lwext4_archive_name(child.name):
            candidates.append(child)
    return tuple(candidates)


def _is_lwext4_archive_name(name):
    return name.startswith("lwext4") and any(name.endswith(suffix) for suffix in LWEXT4_ARCHIVE_SUFFIXES)


def _first_existing_directory(candidates):
    for candidate in candidates:
        if Path(candidate).is_dir():
            return Path(candidate)
    return None


def _first_existing_archive(candidates):
    for candidate in candidates:
        if Path(candidate).is_file():
            return Path(candidate)
    return None


def _is_valid_lwext4_source(path):
    candidate = Path(path)
    return candidate.is_dir() and (candidate / "SConscript").is_file()


def _initial_manifest(paths, metadata_path):
    prepared = lwext4_prepared_source(paths)
    return {
        "prepared": str(prepared),
        "source": None,
        "source_candidates": [str(path) for path in _local_directory_candidates(paths)],
        "archive_candidates": [str(path) for path in _archive_candidates(paths)],
        "package_metadata": str(metadata_path),
        "downloads_has_git": _downloads_has_git(paths),
        "prepared_checksum": path_record(prepared).get("sha256"),
    }


def _complete_manifest(paths, manifest, log):
    _remove_downloads_git_metadata(paths, log)
    prepared = lwext4_prepared_source(paths)
    manifest["prepared_checksum"] = path_record(prepared).get("sha256")
    manifest["downloads_has_git"] = _downloads_has_git_from_prepared(prepared)


def _complete_manifest_from_prepared(prepared, manifest, log):
    downloads = Path(prepared).parents[1]
    _remove_git_metadata(downloads, log, "downloads")
    manifest["prepared_checksum"] = path_record(prepared).get("sha256")
    manifest["downloads_has_git"] = _downloads_has_git_from_prepared(prepared)


def _local_source_record(kind, source, reused):
    return {
        "kind": kind,
        "path": str(source),
        "reused": reused,
        "revision": _git_output(source, "rev-parse", "HEAD", require_own_repo=True),
        "dirty": _git_dirty(source),
    }


def _archive_source_record(archive):
    record = path_record(archive)
    return {
        "kind": "archive",
        "path": str(archive),
        "sha256": record.get("sha256"),
        "reused": False,
        "revision": None,
        "dirty": None,
    }


def _git_source_record(fetch_info, clone_dir):
    return {
        "kind": "git",
        "url": fetch_info["url"],
        "branch": fetch_info["branch"],
        "metadata_path": fetch_info["metadata_path"],
        "worktree": str(clone_dir),
        "revision": _git_output(clone_dir, "rev-parse", "HEAD", require_own_repo=True),
        "dirty": _git_dirty(clone_dir),
        "reused": False,
    }


def _git_dirty(path):
    status = _git_output(path, "status", "--porcelain", require_own_repo=True)
    return bool(status.strip()) if status is not None else None


def _git_output(path, *args, require_own_repo=False):
    if require_own_repo and not _is_own_git_repository(path):
        return None
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
    return completed.stdout.strip()


def _is_own_git_repository(path):
    git_dir = Path(path) / ".git"
    return git_dir.exists() or git_dir.is_symlink()


def _searched_paths(paths, metadata_path):
    return (
        *_local_directory_candidates(paths),
        *_archive_candidates(paths),
        Path(metadata_path),
    )


def _downloads_has_git(paths):
    downloads = Path(paths.root) / "downloads"
    return any(_git_metadata_paths(downloads))


def _downloads_has_git_from_prepared(prepared):
    downloads = Path(prepared).parents[1]
    return any(_git_metadata_paths(downloads))


def _remove_prepared_git_metadata(prepared, log):
    _remove_git_metadata(prepared, log, "prepared lwext4 source")


def _remove_downloads_git_metadata(paths, log):
    _remove_git_metadata(Path(paths.root) / "downloads", log, "downloads")


def _remove_git_metadata(root, log, label):
    for git_dir in sorted(_git_metadata_paths(Path(root)), key=lambda path: len(path.parts), reverse=True):
        _remove_path(git_dir)
        log.write(f"removed Git metadata from {label}: {git_dir}\n")


def _git_metadata_paths(prepared):
    if not prepared.is_dir():
        return ()
    return tuple(path for path in prepared.rglob(".git") if path.exists() or path.is_symlink())


def _replace_directory(source, destination, ignore=None):
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=parent))
    temp_destination = temp_root / destination.name
    backup = None
    try:
        shutil.copytree(source, temp_destination, symlinks=True, ignore=ignore)
        if destination.exists() or destination.is_symlink():
            backup = _unique_backup_path(destination)
            destination.rename(backup)
        temp_destination.rename(destination)
        if backup is not None:
            _remove_path(backup)
    except Exception:
        if backup is not None and not destination.exists() and backup.exists():
            backup.rename(destination)
        raise
    finally:
        _remove_path(temp_root)


def _ignore_git_directories(_directory, names):
    return {name for name in names if name == ".git"}


def _unique_backup_path(path):
    parent = path.parent
    stem = f".{path.name}.old-{os.getpid()}"
    candidate = parent / stem
    index = 0
    while candidate.exists() or candidate.is_symlink():
        index += 1
        candidate = parent / f"{stem}-{index}"
    return candidate


def _remove_path(path):
    candidate = Path(path)
    if candidate.is_symlink() or candidate.is_file():
        candidate.unlink()
    elif candidate.is_dir():
        shutil.rmtree(candidate)


def _ensure_package_sconscript(packages_dir, source, log):
    destination = Path(packages_dir) / "SConscript"
    if destination.is_file():
        return destination
    if source is None:
        raise SmartBuildError("SOURCE", f"package SConscript reference not configured for {destination}")
    reference = Path(source)
    if not reference.is_file():
        log.write(f"package SConscript reference not found: {reference}\n")
        raise SmartBuildError("SOURCE", f"package SConscript reference not found: {reference}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(reference, destination)
    log.write(f"copied package SConscript: {reference} -> {destination}\n")
    return destination
