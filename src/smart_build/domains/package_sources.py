import hashlib
import fcntl
import os
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from ..cache import path_record
from ..configure import restore_configuration_sync
from ..errors import SmartBuildError
from ..paths import validate_safe_name
from ..tasks import Task


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
LOCAL_PROXY_URL = "http://127.0.0.1:10808"


@dataclass(frozen=True)
class PackageSourceConfig:
    task_id: str
    kind: str
    name: str
    version: str
    url: str
    prepared: Path
    description_path: Path
    local_files: tuple
    configuration: dict | None = None
    archive: Path | None = None
    sha256: str | None = None
    allow_unverified: bool = False
    strip_root: bool | None = None
    revision: str | None = None


def package_source_config(paths, name, description):
    source = description.data.get("source")
    if not isinstance(source, dict):
        raise SmartBuildError("SOURCE", f"{description.path}: source must be a mapping")
    source_type = source.get("type")
    safe_name = validate_safe_name(name, "package")
    if source_type is None and "directory" in source:
        return None
    if source_type == "git":
        return _git_source_config(paths, safe_name, description, source)
    if source_type != "archive":
        return None

    version = _source_version(description, source)
    url = _required_string(source, "url", description.path)
    archive_name = _safe_archive_name(_required_string(source, "archive", description.path), description.path)
    sha256 = _optional_sha256(source, description.path)
    allow_unverified = source.get("allow_unverified", False)
    if not isinstance(allow_unverified, bool):
        raise SmartBuildError("SOURCE", f"{description.path}: source.allow_unverified must be a boolean")
    if sha256 is None and not allow_unverified:
        raise SmartBuildError(
            "SOURCE",
            f"{description.path}: source.sha256 is required unless source.allow_unverified is true",
        )
    strip_root = _strip_root(source, description.path)
    prepared = paths.work_dir / "sources" / f"{safe_name}-{version}"
    local_files = _local_files(paths.root, source, description.path)
    return PackageSourceConfig(
        task_id=f"package:{safe_name}:source",
        kind="archive",
        name=safe_name,
        version=version,
        url=url,
        prepared=prepared,
        description_path=Path(description.path),
        local_files=local_files,
        configuration=description.data.get("configure"),
        archive=paths.root / "downloads" / archive_name,
        sha256=sha256,
        allow_unverified=allow_unverified,
        strip_root=strip_root,
    )


def package_source_task(paths, name, description, command_runner=None):
    config = package_source_config(paths, name, description)
    if config is None:
        return None
    manifest = _source_manifest(config, reused=_source_reused(config))
    return Task(
        id=config.task_id,
        domain="package",
        action="source",
        inputs=_task_inputs(config),
        outputs=[config.prepared],
        deps=[],
        workdir=paths.work_dir / "sources" / f"{config.name}-source-task",
        env={"MACHINE": paths.machine},
        run_class="fetch",
        cache_policy="never",
        log_path=paths.logs_dir / f"package-{config.name}-source.log",
        executor=_make_source_executor(config, command_runner),
        cache_extra={"source": dict(manifest)},
        manifest_fields={"source": manifest},
    )


def package_source_prepared_dir(paths, name, description):
    config = package_source_config(paths, name, description)
    return None if config is None else config.prepared


def _git_source_config(paths, safe_name, description, source):
    version = _source_version(description, source)
    url = _required_string(source, "url", description.path)
    revision = _git_revision(source, description.path)
    prepared = paths.work_dir / "sources" / f"{safe_name}-{version}"
    local_files = _local_files(paths.root, source, description.path)
    return PackageSourceConfig(
        task_id=f"package:{safe_name}:source",
        kind="git",
        name=safe_name,
        version=version,
        url=url,
        prepared=prepared,
        description_path=Path(description.path),
        local_files=local_files,
        configuration=description.data.get("configure"),
        revision=revision,
    )


def _make_source_executor(config, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        manifest = _source_manifest(config, reused=_source_reused(config))
        task.manifest_fields["source"] = manifest

        if config.kind == "git":
            reused = _prepare_git_source(config, runner, task, log)
        else:
            reused = _ensure_archive_available(config, runner, task, log)
            _extract_archive(config.archive, config.prepared, config.strip_root)
        _copy_local_files(config.local_files, config.prepared)
        restored = restore_configuration_sync(
            config.configuration,
            config.prepared,
            config.description_path.parent,
            label=f"{config.description_path}: configure",
        )
        manifest["reused"] = reused
        manifest["local_files"] = _local_file_manifest(config.local_files)
        manifest["restored_configuration"] = [str(path) for path in restored]
        if config.archive is not None:
            manifest["archive_sha256"] = _sha256_file(config.archive)
        manifest["prepared_checksum"] = path_record(config.prepared).get("sha256")
        log.write(f"prepared package source: {config.url} -> {config.prepared}\n")
        return 0

    return executor


def _source_reused(config):
    if config.kind == "archive":
        return config.archive.is_file()
    return config.prepared.is_dir()


def _prepare_git_source(config, runner, task, log):
    reused = config.prepared.is_dir()
    if reused:
        _remove_path(config.prepared)
    config.prepared.parent.mkdir(parents=True, exist_ok=True)
    clone_command = ["git", "clone", "--no-checkout", config.url, str(config.prepared)]
    completed = runner(clone_command, cwd=config.prepared.parent, env=os.environ.copy())
    _write_completed_command(log, clone_command, config.prepared.parent, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "SOURCE",
            f"failed to clone package source {config.url}; log={task.log_path}",
        )
    checkout_command = ["git", "-C", str(config.prepared), "checkout", "--detach", config.revision]
    completed = runner(checkout_command, cwd=config.prepared.parent, env=os.environ.copy())
    _write_completed_command(log, checkout_command, config.prepared.parent, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "SOURCE",
            f"failed to checkout package source {config.url}@{config.revision}; log={task.log_path}",
        )
    if not config.prepared.is_dir():
        raise SmartBuildError("SOURCE", f"git source did not create prepared directory: {config.prepared}")
    return reused


def _ensure_archive_available(config, runner, task, log):
    if config.archive.is_file():
        _verify_archive_sha256(config.archive, config.sha256)
        log.write(f"using existing package source archive: {config.archive}\n")
        return True

    with _archive_download_lock(config.archive, log):
        if config.archive.is_file():
            _verify_archive_sha256(config.archive, config.sha256)
            log.write(f"using existing package source archive after waiting: {config.archive}\n")
            return True

        _download_archive(config, runner, task, log)
        _verify_archive_sha256(config.archive, config.sha256)
        log.write(f"downloaded package source archive: {config.url} -> {config.archive}\n")
        return False


def _archive_download_lock(archive, log):
    return _FileLock(archive.with_name(f".{archive.name}.lock"), log)


class _FileLock:
    def __init__(self, path, log):
        self.path = Path(path)
        self.log = log
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")
        self.log.write(f"waiting for package source download lock: {self.path}\n")
        fcntl.flock(self._handle, fcntl.LOCK_EX)
        self.log.write(f"acquired package source download lock: {self.path}\n")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            fcntl.flock(self._handle, fcntl.LOCK_UN)
        finally:
            self._handle.close()
        return False


def _download_archive(config, runner, task, log):
    config.archive.parent.mkdir(parents=True, exist_ok=True)
    temp_archive = config.archive.with_name(f".{config.archive.name}.download")
    completed = None
    for url in _download_urls(config.url):
        if url != config.url:
            log.write(f"retrying package source download from mirror: {url}\n")
        completed = _download_archive_url(url, temp_archive, config.archive.parent, runner, log)
        if completed.returncode == 0:
            break
    if completed is None or completed.returncode != 0:
        raise SmartBuildError(
            "SOURCE",
            f"failed to download package source {config.url}; log={task.log_path}",
        )
    if temp_archive.is_file():
        _verify_archive_sha256(temp_archive, config.sha256)
        temp_archive.replace(config.archive)
    if not config.archive.is_file():
        raise SmartBuildError(
            "SOURCE",
            f"download did not create package source archive: {config.archive}",
        )


def _download_archive_url(url, temp_archive, cwd, runner, log):
    command = _download_command(url, temp_archive, resume=True)
    completed = runner(command, cwd=cwd, env=os.environ.copy())
    _write_completed_command(log, command, cwd, completed)
    if completed.returncode != 0 and _download_resume_not_supported(completed):
        log.write("download resume is not supported by server; retrying from scratch\n")
        _remove_path(temp_archive)
        command = _download_command(url, temp_archive, resume=False)
        completed = runner(command, cwd=cwd, env=os.environ.copy())
        _write_completed_command(log, command, cwd, completed)
    if completed.returncode != 0:
        log.write(f"direct download failed; retrying with local proxy {LOCAL_PROXY_URL}\n")
        command = _download_command(url, temp_archive, resume=True, proxy=LOCAL_PROXY_URL)
        completed = runner(command, cwd=cwd, env=os.environ.copy())
        _write_completed_command(log, command, cwd, completed)
        if completed.returncode != 0 and _download_resume_not_supported(completed):
            log.write("download resume is not supported by proxy path; retrying from scratch\n")
            _remove_path(temp_archive)
            command = _download_command(url, temp_archive, resume=False, proxy=LOCAL_PROXY_URL)
            completed = runner(command, cwd=cwd, env=os.environ.copy())
            _write_completed_command(log, command, cwd, completed)
    return completed


def _download_urls(url):
    urls = [url]
    mirror = _gnu_mirror_url(url)
    if mirror and mirror not in urls:
        urls.append(mirror)
    return tuple(urls)


def _gnu_mirror_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "ftp.gnu.org":
        return None
    prefix = "/gnu/"
    if not parsed.path.startswith(prefix):
        return None
    return "https://mirrors.kernel.org/gnu/" + parsed.path[len(prefix):]


def _download_command(url, output, resume, proxy=None):
    command = [
        "curl",
        "--http1.1",
        "--retry",
        "5",
        "--retry-all-errors",
        "--retry-delay",
        "2",
        "--retry-max-time",
        "40",
        "--connect-timeout",
        "20",
        "--speed-limit",
        "1024",
        "--speed-time",
        "20",
        "-L",
        "--fail",
    ]
    if proxy:
        command.extend(["--proxy", proxy])
    if resume:
        command.extend([
            "-C",
            "-",
        ])
    command.extend(["-o", str(output), url])
    return command


def _download_resume_not_supported(completed):
    output = str(getattr(completed, "stdout", ""))
    return completed.returncode == 33 or "doesn't seem to support byte ranges" in output


def _extract_archive(archive, prepared, strip_root):
    prepared = Path(prepared)
    work_root = prepared.parent / f".{prepared.name}.extract"
    raw_root = work_root / "raw"
    _remove_path(work_root)
    raw_root.mkdir(parents=True, exist_ok=True)
    try:
        if _is_zip_archive(archive):
            _extract_zip_safely(archive, raw_root)
        else:
            _extract_tar_safely(archive, raw_root)
        source = _stripped_source_root(raw_root) if strip_root else raw_root
        _replace_directory(source, prepared)
    finally:
        _remove_path(work_root)


def _extract_tar_safely(archive, destination):
    try:
        with tarfile.open(archive, mode="r:*") as handle:
            members = handle.getmembers()
            for member in members:
                _validate_archive_member(destination, member.name)
                if member.issym() or member.islnk():
                    _validate_archive_link(member)
                if not (member.isfile() or member.isdir()):
                    if member.issym() or member.islnk():
                        continue
                    raise SmartBuildError("SOURCE", f"unsupported archive member type: {member.name}")
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning, module="tarfile")
                handle.extractall(destination, members=members)
    except (tarfile.TarError, OSError) as exc:
        raise SmartBuildError("SOURCE", f"failed to extract package source archive {archive}: {exc}") from exc


def _extract_zip_safely(archive, destination):
    try:
        with zipfile.ZipFile(archive) as handle:
            for member in handle.infolist():
                _validate_archive_member(destination, member.filename)
                _validate_zip_member_type(member)
            handle.extractall(destination)
    except (zipfile.BadZipFile, OSError) as exc:
        raise SmartBuildError("SOURCE", f"failed to extract package source archive {archive}: {exc}") from exc


def _validate_zip_member_type(member):
    mode = member.external_attr >> 16
    if mode == 0 or member.is_dir():
        return
    file_type = stat.S_IFMT(mode)
    if file_type == 0:
        return
    if file_type in (stat.S_IFREG, stat.S_IFDIR):
        return
    if file_type == stat.S_IFLNK:
        raise SmartBuildError("SOURCE", f"unsafe archive member link: {member.filename}")
    raise SmartBuildError("SOURCE", f"unsupported archive member type: {member.filename}")


def _validate_archive_member(destination, name):
    if not name or "\\" in name:
        raise SmartBuildError("SOURCE", f"unsafe archive member path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part == ".." for part in path.parts):
        raise SmartBuildError("SOURCE", f"unsafe archive member path: {name}")
    root = Path(destination).resolve()
    target = (Path(destination) / Path(*path.parts)).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("SOURCE", f"unsafe archive member path: {name}") from exc


def _validate_archive_link(member):
    linkname = member.linkname
    if not linkname or "\\" in linkname:
        raise SmartBuildError("SOURCE", f"unsafe archive member link: {member.name}")
    link = PurePosixPath(linkname)
    if link.is_absolute():
        raise SmartBuildError("SOURCE", f"unsafe archive member link: {member.name}")

    if member.issym():
        base = PurePosixPath(member.name).parent
        resolved = PurePosixPath(posixpath.normpath(str(base / link)))
    else:
        # Tar hard-link names identify another member from the archive root.
        resolved = PurePosixPath(posixpath.normpath(str(link)))
    if resolved.is_absolute() or not resolved.parts or resolved.parts[0] == "..":
        raise SmartBuildError("SOURCE", f"unsafe archive member link: {member.name}")


def _stripped_source_root(raw_root):
    children = list(Path(raw_root).iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return raw_root


def _source_manifest(config, reused):
    manifest = {
        "type": config.kind,
        "name": config.name,
        "version": config.version,
        "url": config.url,
        "prepared": str(config.prepared),
        "reused": bool(reused),
        "local_files": _local_file_manifest(config.local_files),
        "prepared_checksum": path_record(config.prepared).get("sha256") if config.prepared.exists() else None,
    }
    if config.kind == "archive":
        manifest.update(
            {
                "archive": str(config.archive),
                "sha256": config.sha256,
                "strip_root": config.strip_root,
                "allow_unverified": config.allow_unverified,
                "archive_sha256": path_record(config.archive).get("sha256") if config.archive.exists() else None,
            }
        )
    else:
        manifest["revision"] = config.revision
    return manifest


def _task_inputs(config):
    inputs = [config.description_path]
    if config.archive is not None and config.archive.exists():
        inputs.append(config.archive)
    inputs.extend(source for source, _destination in config.local_files)
    return inputs


def _source_version(description, source):
    raw_version = source.get("version", description.version)
    if not isinstance(raw_version, str) or not raw_version:
        raise SmartBuildError("SOURCE", f"{description.path}: source.version must be a non-empty string")
    return _safe_segment(raw_version, "source.version", description.path)


def _required_string(source, key, description_path):
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise SmartBuildError("SOURCE", f"{description_path}: source.{key} must be a non-empty string")
    return value


def _optional_sha256(source, description_path):
    value = source.get("sha256")
    if value is None:
        return None
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SmartBuildError("SOURCE", f"{description_path}: source.sha256 must be 64 hex characters")
    return value.lower()


def _git_revision(source, description_path):
    revision = source.get("commit") or source.get("tag")
    if not isinstance(revision, str) or not revision:
        raise SmartBuildError("SOURCE", f"{description_path}: git source requires commit or tag")
    return _safe_git_revision(revision, description_path)


def _safe_git_revision(raw_value, description_path):
    value = str(raw_value)
    if value.startswith("-") or any(char.isspace() for char in value) or "\\" in value:
        raise SmartBuildError("SOURCE", f"{description_path}: unsafe git revision: {raw_value}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SmartBuildError("SOURCE", f"{description_path}: unsafe git revision: {raw_value}")
    return value


def _strip_root(source, description_path):
    value = source.get("strip_root", True)
    if not isinstance(value, bool):
        raise SmartBuildError("SOURCE", f"{description_path}: source.strip_root must be a boolean")
    return value


def _local_files(repo_root, source, description_path):
    raw_files = source.get("local_files", [])
    if raw_files is None:
        return ()
    if not isinstance(raw_files, list):
        raise SmartBuildError("SOURCE", f"{description_path}: source.local_files must be a list")
    repository = Path(repo_root).resolve()
    description_dir = Path(description_path).parent
    result = []
    for raw_file in raw_files:
        if not isinstance(raw_file, str) or not raw_file:
            raise SmartBuildError("SOURCE", f"{description_path}: source.local_files entries must be strings")
        relative = _safe_relative_file_path(raw_file, "source.local_files", description_path)
        source_path = _local_file_candidate(repository, description_dir, relative, raw_file, description_path)
        if source_path.is_symlink():
            raise SmartBuildError("SOURCE", f"{description_path}: refusing symlink source.local_files entry: {raw_file}")
        if not source_path.is_file():
            raise SmartBuildError("SOURCE", f"{description_path}: source.local_files entry not found: {raw_file}")
        result.append((source_path, relative.name))
    return tuple(result)


def _local_file_candidate(repository, description_dir, relative, raw_file, description_path):
    local_path = description_dir.joinpath(*relative.parts)
    local_resolved = local_path.resolve(strict=False)
    if _is_relative_to(local_resolved, repository) and local_path.exists():
        return local_path

    root_path = repository.joinpath(*relative.parts)
    root_resolved = root_path.resolve(strict=False)
    try:
        root_resolved.relative_to(repository)
    except ValueError as exc:
        raise SmartBuildError(
            "SOURCE",
            f"{description_path}: source.local_files path escapes repository: {raw_file}",
        ) from exc
    return root_path


def _is_relative_to(path, root):
    try:
        Path(path).relative_to(root)
    except ValueError:
        return False
    return True


def _safe_relative_file_path(raw_value, label, description_path):
    path = PurePosixPath(str(raw_value))
    if path.is_absolute() or "\\" in str(raw_value):
        raise SmartBuildError("SOURCE", f"{description_path}: unsafe {label}: {raw_value}")
    parts = [part for part in path.parts if part != "."]
    if not parts or any(part in {"", ".."} for part in parts):
        raise SmartBuildError("SOURCE", f"{description_path}: unsafe {label}: {raw_value}")
    return PurePosixPath(*parts)


def _copy_local_files(local_files, prepared):
    prepared = Path(prepared)
    for source, destination_name in local_files:
        destination = prepared / destination_name
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.copy2(source, destination)


def _local_file_manifest(local_files):
    return [
        {
            "source": str(source),
            "destination": destination,
        }
        for source, destination in local_files
    ]


def _safe_archive_name(raw_name, description_path):
    return _safe_segment(raw_name, "source.archive", description_path)


def _safe_segment(raw_value, label, description_path):
    path = PurePosixPath(str(raw_value))
    if path.is_absolute() or len(path.parts) != 1 or path.name in {"", ".", ".."} or "\\" in str(raw_value):
        raise SmartBuildError("SOURCE", f"{description_path}: unsafe {label}: {raw_value}")
    return path.name


def _verify_archive_sha256(archive, expected):
    if expected is None:
        return
    actual = _sha256_file(archive)
    if actual != expected:
        raise SmartBuildError(
            "SOURCE",
            f"package source archive sha256 mismatch: {archive}: expected {expected}, actual {actual}",
        )


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_zip_archive(archive):
    return str(archive).lower().endswith(".zip")


def _replace_directory(source, destination):
    _remove_path(destination)
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _remove_path(path):
    candidate = Path(path)
    if candidate.is_symlink() or candidate.is_file():
        candidate.unlink()
    elif candidate.is_dir():
        shutil.rmtree(candidate)


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
