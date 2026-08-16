import gzip
import io
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..cache import path_record
from ..errors import SmartBuildError
from ..tasks import Task


IPKG_VERSION = b"2.0\n"
AR_MAGIC = b"!<arch>\n"
CONTROL_FIELDS = ("Package", "Version", "Architecture", "Depends", "Provides", "Description")
CONTROL_STATUS_FIELDS = ("Package", "Version", "Architecture", "Depends", "Provides", "Description", "Status")
IPKG_BACKEND_SOURCE = Path(__file__).resolve()


@dataclass(frozen=True)
class PackageFile:
    source: Path
    path: str
    mode: int = 0o755


def ipkg_tasks(paths, build_tasks):
    return [ipkg_task(paths, task) for task in build_tasks if _has_ipkg_manifest(task)]


def ipkg_task(paths, build_task):
    app = dict(build_task.manifest_fields.get("app", {}))
    if app:
        return _app_ipkg_task(paths, build_task, app)
    library = dict(build_task.manifest_fields.get("library", {}))
    if library:
        return _library_ipkg_task(paths, build_task, library)
    executable = dict(build_task.manifest_fields.get("executable", {}))
    if _is_executable_package_manifest(executable):
        return _executable_ipkg_task(paths, build_task, executable)
    raise SmartBuildError("IPKG", f"build task missing package manifest fields: {build_task.id}")


def _has_ipkg_manifest(task):
    app = task.manifest_fields.get("app", {})
    if app:
        return True
    library = task.manifest_fields.get("library", {})
    if library:
        return True
    return _is_executable_package_manifest(task.manifest_fields.get("executable", {}))


def _is_executable_package_manifest(executable):
    return bool(
        isinstance(executable, dict)
        and executable.get("name")
        and isinstance(executable.get("install_files"), list)
        and executable.get("install_files")
    )


def _app_ipkg_task(paths, app_build_task, app):
    name = app.get("name")
    version = app.get("version", "0.1.0")
    output = paths.packages_dir / f"{name}.ipk"
    package_manifest = {
        "name": name,
        "version": version,
        "architecture": paths.machine,
        "depends": app.get("depends", ""),
        "provides": app.get("provides", name),
        "description": app.get("package_description", name),
        "file": str(output),
        "install_path": app["install_path"],
        "app_task_id": app_build_task.id,
        "app_output": str(app_build_task.outputs[0]),
        "checksum": None,
    }
    if "extension" in app:
        package_manifest["extension"] = app["extension"]

    return Task(
        id=f"ipkg:{name}:package",
        domain="ipkg",
        action="package",
        inputs=[app_build_task.outputs[0], IPKG_BACKEND_SOURCE],
        outputs=[output],
        deps=[app_build_task.id],
        workdir=paths.work_dir / "ipkg" / name,
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"ipkg-{name}-package.log",
        executor=_make_ipkg_executor(package_manifest),
        cache_extra={"package": {key: value for key, value in package_manifest.items() if key != "checksum"}},
        manifest_fields={"package": package_manifest},
    )


def _library_ipkg_task(paths, library_build_task, library):
    name = library.get("name")
    version = library.get("version", "0.1.0")
    output = paths.packages_dir / f"{name}.ipk"
    files = _package_files_from_manifest(library, "library")
    package_manifest = {
        "name": name,
        "version": version,
        "architecture": paths.machine,
        "depends": library.get("depends", ""),
        "provides": library.get("provides", name),
        "description": library.get("package_description", name),
        "selected_options": dict(library.get("selected_options", {})),
        "file": str(output),
        "install_path": files[0]["path"],
        "library_task_id": library_build_task.id,
        "library_output": str(library_build_task.outputs[0]),
        "files": files,
        "checksum": None,
    }
    return Task(
        id=f"ipkg:{name}:package",
        domain="ipkg",
        action="package",
        inputs=[library_build_task.outputs[0], IPKG_BACKEND_SOURCE],
        outputs=[output],
        deps=[library_build_task.id],
        workdir=paths.work_dir / "ipkg" / name,
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"ipkg-{name}-package.log",
        executor=_make_files_ipkg_executor(package_manifest, library_build_task, "library"),
        cache_extra={"package": {key: value for key, value in package_manifest.items() if key != "checksum"}},
        manifest_fields={"package": package_manifest},
    )


def _executable_ipkg_task(paths, executable_build_task, executable):
    name = executable.get("name")
    version = executable.get("version", "0.1.0")
    output = paths.packages_dir / f"{name}.ipk"
    files = _package_files_from_manifest(executable, "executable")
    package_manifest = {
        "name": name,
        "version": version,
        "type": "executable",
        "architecture": paths.machine,
        "depends": executable.get("depends", ""),
        "provides": executable.get("provides", name),
        "description": executable.get("package_description", name),
        "selected_options": dict(executable.get("selected_options", {})),
        "file": str(output),
        "install_path": files[0]["path"],
        "executable_task_id": executable_build_task.id,
        "executable_output": str(executable_build_task.outputs[0]),
        "files": files,
        "smoke": executable.get("smoke", {}),
        "checksum": None,
    }
    return Task(
        id=f"ipkg:{name}:package",
        domain="ipkg",
        action="package",
        inputs=[executable_build_task.outputs[0], IPKG_BACKEND_SOURCE],
        outputs=[output],
        deps=[executable_build_task.id],
        workdir=paths.work_dir / "ipkg" / name,
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="inputs",
        log_path=paths.logs_dir / f"ipkg-{name}-package.log",
        executor=_make_files_ipkg_executor(package_manifest, executable_build_task, "executable"),
        cache_extra={"package": {key: value for key, value in package_manifest.items() if key != "checksum"}},
        manifest_fields={"package": package_manifest},
    )


def create_ipkg(path, package, version, architecture, depends, description, files, provides=""):
    package_path = Path(path)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    control = _control_archive(
        {
            "Package": package,
            "Version": version,
            "Architecture": architecture,
            "Depends": depends,
            "Provides": provides,
            "Description": description,
        }
    )
    data = _data_archive(files)
    _write_ar(
        package_path,
        [
            ("debian-binary", IPKG_VERSION),
            ("control.tar.gz", control),
            ("data.tar.gz", data),
        ],
    )


def read_control_fields(path):
    members = _read_ar(Path(path))
    if members.get("debian-binary") != IPKG_VERSION:
        raise SmartBuildError("IPKG", f"{path}: unsupported debian-binary")
    control_bytes = members.get("control.tar.gz")
    if control_bytes is None:
        raise SmartBuildError("IPKG", f"{path}: missing control.tar.gz")
    try:
        with tarfile.open(fileobj=io.BytesIO(control_bytes), mode="r:gz") as archive:
            try:
                member = archive.getmember("./control")
            except KeyError:
                member = archive.getmember("control")
            handle = archive.extractfile(member)
            if handle is None:
                raise SmartBuildError("IPKG", f"{path}: control is not a file")
            return _parse_control(handle.read().decode("utf-8"))
    except SmartBuildError:
        raise
    except (KeyError, tarfile.TarError, OSError, EOFError, UnicodeDecodeError) as exc:
        raise SmartBuildError("IPKG", f"{path}: invalid control.tar.gz: {exc}") from exc


def install_ipkg(path, rootfs_dir):
    package_path = Path(path)
    rootfs = Path(rootfs_dir)
    fields = read_control_fields(package_path)
    members = _read_ar(package_path)
    data_bytes = members.get("data.tar.gz")
    if data_bytes is None:
        raise SmartBuildError("IPKG", f"{package_path}: missing data.tar.gz")
    rootfs.mkdir(parents=True, exist_ok=True)
    records = []
    created_files = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data_bytes), mode="r:gz") as archive:
            for member in archive.getmembers():
                if member.isdir():
                    destination = _safe_destination(rootfs, member.name)
                    destination.mkdir(parents=True, exist_ok=True)
                    destination.chmod(member.mode & 0o7777)
                    continue
                if member.issym() or member.islnk():
                    raise SmartBuildError("IPKG", f"{package_path}: refusing symlink member: {member.name}")
                if not member.isfile():
                    raise SmartBuildError("IPKG", f"{package_path}: unsupported data member: {member.name}")
                destination = _safe_destination(rootfs, member.name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                handle = archive.extractfile(member)
                if handle is None:
                    raise SmartBuildError("IPKG", f"{package_path}: cannot read data member: {member.name}")
                payload = handle.read()
                existed = destination.exists() or destination.is_symlink()
                try:
                    _install_file(package_path, destination, payload, member.mode & 0o7777)
                except (SmartBuildError, OSError):
                    if not existed and (destination.is_file() or destination.is_symlink()):
                        destination.unlink()
                    raise
                if not existed:
                    created_files.append(destination)
                record = path_record(destination)
                records.append(
                    {
                        "path": destination.relative_to(rootfs).as_posix(),
                        "package": fields.get("Package", ""),
                        "version": fields.get("Version", ""),
                        "source": str(package_path),
                        "checksum": record.get("sha256"),
                    }
                )
    except SmartBuildError:
        for destination in reversed(created_files):
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        for destination in reversed(created_files):
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
        raise SmartBuildError("IPKG", f"{package_path}: invalid data.tar.gz: {exc}") from exc
    return records


class IpkgDatabase:
    """Small opkg-compatible status database for staged/runtime IPK tests."""

    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.info_dir = self.state_dir / "info"
        self.status_path = self.state_dir / "status"

    def records(self):
        if not self.status_path.is_file():
            return []
        try:
            text = self.status_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SmartBuildError("IPKG", f"failed to read package status: {self.status_path}: {exc}") from exc
        result = []
        for stanza in text.split("\n\n"):
            fields = _parse_status_stanza(stanza)
            if fields.get("Package"):
                result.append(fields)
        return result

    def get(self, package):
        _validate_package_name(package)
        return next((item for item in self.records() if item.get("Package") == package), None)

    def commit(self, fields, records):
        package = fields.get("Package", "")
        _validate_package_name(package)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.info_dir.mkdir(parents=True, exist_ok=True)
        current = [item for item in self.records() if item.get("Package") != package]
        installed = {key: str(fields.get(key, "")) for key in CONTROL_STATUS_FIELDS}
        installed["Status"] = "install ok installed"
        current.append(installed)
        status_text = "\n\n".join(_format_status_stanza(item) for item in current) + "\n"
        _atomic_write_text(self.status_path, status_text)
        list_path = self.info_dir / f"{package}.list"
        list_text = "".join(f"{item['path']}\n" for item in records)
        _atomic_write_text(list_path, list_text)

    def remove(self, package):
        _validate_package_name(package)
        records = self.records()
        current = [item for item in records if item.get("Package") != package]
        if len(current) == len(records):
            raise SmartBuildError("IPKG", f"package is not installed: {package}")
        status_text = "\n\n".join(_format_status_stanza(item) for item in current)
        if status_text:
            status_text += "\n"
        _atomic_write_text(self.status_path, status_text)
        list_path = self.info_dir / f"{package}.list"
        if list_path.exists() or list_path.is_symlink():
            list_path.unlink()


def install_ipkg_runtime(path, rootfs_dir, state_dir=None):
    """Install an IPK and record ownership in a compact opkg-style database."""

    package_path = Path(path)
    rootfs = Path(rootfs_dir)
    fields = read_control_fields(package_path)
    package = fields.get("Package", "")
    _validate_package_name(package)
    database = IpkgDatabase(state_dir or rootfs / "var/lib/opkg")
    records = install_ipkg(package_path, rootfs)
    database.commit(fields, records)
    return records


def remove_ipkg_runtime(package, rootfs_dir, state_dir=None):
    """Remove files owned by an installed IPK and update the status database."""

    rootfs = Path(rootfs_dir)
    database = IpkgDatabase(state_dir or rootfs / "var/lib/opkg")
    installed = database.get(package)
    if installed is None:
        raise SmartBuildError("IPKG", f"package is not installed: {package}")
    list_path = database.info_dir / f"{package}.list"
    if list_path.is_file():
        for raw_path in list_path.read_text(encoding="utf-8").splitlines():
            destination = _safe_destination(rootfs, raw_path)
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
    database.remove(package)


def list_ipkg_runtime(state_dir):
    return IpkgDatabase(state_dir).records()


def _validate_package_name(package):
    if not package or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-" for char in package):
        raise SmartBuildError("IPKG", f"unsafe package name: {package}")


def _parse_status_stanza(text):
    fields = {}
    for line in text.splitlines():
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key] = value.lstrip()
    return fields


def _format_status_stanza(fields):
    lines = []
    for key in CONTROL_STATUS_FIELDS:
        if fields.get(key, ""):
            lines.append(f"{key}: {fields[key]}")
    return "\n".join(lines)


def _atomic_write_text(path, text):
    destination = Path(path)
    temporary = destination.with_name(f".{destination.name}.new")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, destination)
    except OSError as exc:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        raise SmartBuildError("IPKG", f"failed to update package database: {destination}: {exc}") from exc


def _make_ipkg_executor(package_manifest):
    def executor(task, log):
        source = Path(package_manifest["app_output"])
        if not source.is_file():
            raise SmartBuildError("IPKG", f"app output not found: {source}")
        output = Path(package_manifest["file"])
        if output.exists() or output.is_symlink():
            _prepare_package_output(output)
        create_ipkg(
            output,
            package=package_manifest["name"],
            version=package_manifest["version"],
            architecture=package_manifest["architecture"],
            depends=package_manifest["depends"],
            provides=package_manifest["provides"],
            description=package_manifest["description"],
            files=[
                PackageFile(
                    source=source,
                    path=package_manifest["install_path"],
                    mode=0o755,
                )
            ],
        )
        package_manifest["checksum"] = path_record(output).get("sha256")
        task.manifest_fields["package"]["checksum"] = package_manifest["checksum"]
        log.write(f"packaged app: {source} -> {output}\n")
        return 0

    return executor


def _make_files_ipkg_executor(package_manifest, build_task=None, manifest_key=None):
    def executor(task, log):
        output = Path(package_manifest["file"])
        if output.exists() or output.is_symlink():
            _prepare_package_output(output)
        if build_task is not None:
            package_manifest["files"] = _package_files_from_manifest(
                build_task.manifest_fields[manifest_key],
                manifest_key,
            )
        expanded_files = []
        for item in package_manifest["files"]:
            expanded_files.extend(_expanded_package_files(item))
        package_manifest["files"] = expanded_files
        task.manifest_fields["package"]["files"] = expanded_files
        files = [
            PackageFile(source=Path(item["source"]), path=item["path"], mode=int(item.get("mode", 0o755)))
            for item in expanded_files
        ]
        create_ipkg(
            output,
            package=package_manifest["name"],
            version=package_manifest["version"],
            architecture=package_manifest["architecture"],
            depends=package_manifest["depends"],
            provides=package_manifest["provides"],
            description=package_manifest["description"],
            files=files,
        )
        package_manifest["checksum"] = path_record(output).get("sha256")
        task.manifest_fields["package"]["checksum"] = package_manifest["checksum"]
        log.write(f"packaged files: {len(files)} -> {output}\n")
        return 0

    return executor


def _package_files_from_manifest(manifest, package_type):
    files = manifest.get("install_files")
    if not isinstance(files, list) or not files:
        raise SmartBuildError(
            "IPKG",
            f"{package_type} package {manifest.get('name', '<unknown>')} has no install files",
        )
    result = []
    for item in files:
        if not isinstance(item, dict):
            raise SmartBuildError("IPKG", f"{package_type} install files must be mappings")
        result.extend(_expanded_package_files(item))
    return result


def _expanded_package_files(item):
    source = Path(str(item.get("source", "")))
    path = str(item.get("path", ""))
    mode = int(item.get("mode", 0o755))
    if not source.is_dir():
        return [{"source": str(source), "path": path, "mode": mode}]

    result = []
    for child in sorted(source.rglob("*")):
        if child.is_symlink():
            raise SmartBuildError("IPKG", f"refusing symlink package source: {child}")
        if child.is_dir():
            continue
        if not child.is_file():
            raise SmartBuildError("IPKG", f"unsupported package source: {child}")
        relative = child.relative_to(source).as_posix()
        result.append(
            {
                "source": str(child),
                "path": _join_install_path(path, relative),
                "mode": mode,
            }
        )
    return result


def _join_install_path(root, relative):
    return f"{root.rstrip('/')}/{relative}"


def _control_archive(fields):
    missing = [field for field in CONTROL_FIELDS if field not in fields]
    if missing:
        raise SmartBuildError("IPKG", f"missing control fields: {', '.join(missing)}")
    control_text = "".join(f"{field}: {fields[field]}\n" for field in CONTROL_FIELDS)
    return _tar_gz([("./control", control_text.encode("utf-8"), 0o644)])


def _data_archive(files):
    entries = []
    for package_file in files:
        source = Path(package_file.source)
        if not source.is_file():
            raise SmartBuildError("IPKG", f"package source not found: {source}")
        archive_path = _package_file_member_name(package_file.path)
        entries.append((archive_path, source.read_bytes(), package_file.mode))
    return _tar_gz(entries)


def _tar_gz(entries):
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name, payload, mode in entries:
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mode = mode
                info.mtime = 0
                archive.addfile(info, io.BytesIO(payload))
    return stream.getvalue()


def _write_ar(path, members):
    with Path(path).open("wb") as archive:
        archive.write(AR_MAGIC)
        for name, payload in members:
            encoded_name = f"{name}/".encode("ascii")
            if len(encoded_name) > 16:
                raise SmartBuildError("IPKG", f"ar member name too long: {name}")
            header = (
                encoded_name.ljust(16, b" ")
                + b"0".ljust(12, b" ")
                + b"0".ljust(6, b" ")
                + b"0".ljust(6, b" ")
                + b"100644".ljust(8, b" ")
                + str(len(payload)).encode("ascii").ljust(10, b" ")
                + b"`\n"
            )
            archive.write(header)
            archive.write(payload)
            if len(payload) % 2:
                archive.write(b"\n")


def _read_ar(path):
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise SmartBuildError("IPKG", f"{path}: failed to read ar archive: {exc}") from exc
    if not data.startswith(AR_MAGIC):
        raise SmartBuildError("IPKG", f"{path}: invalid ar archive")
    offset = len(AR_MAGIC)
    members = {}
    while offset < len(data):
        if offset + 60 > len(data):
            raise SmartBuildError("IPKG", f"{path}: truncated ar header")
        header = data[offset : offset + 60]
        if header[58:60] != b"`\n":
            raise SmartBuildError("IPKG", f"{path}: invalid ar header")
        try:
            raw_name = header[:16].decode("ascii").rstrip()
            size = int(header[48:58].decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise SmartBuildError("IPKG", f"{path}: invalid ar header: {exc}") from exc
        offset += 60
        payload = data[offset : offset + size]
        if len(payload) != size:
            raise SmartBuildError("IPKG", f"{path}: truncated ar member")
        offset += size + (size % 2)
        members[raw_name.rstrip("/")] = payload
    return members


def _parse_control(text):
    fields = {}
    for line in text.splitlines():
        if not line:
            continue
        if ":" not in line:
            raise SmartBuildError("IPKG", f"invalid control line: {line}")
        key, value = line.split(":", 1)
        fields[key] = value.lstrip()
    for field in CONTROL_FIELDS:
        fields.setdefault(field, "")
    return fields


def _data_member_name(raw_path):
    relative = _safe_relative_path(raw_path)
    return f"./{relative.as_posix()}"


def _package_file_member_name(raw_path):
    path = PurePosixPath(str(raw_path))
    if path.is_absolute():
        path = PurePosixPath(*path.parts[1:])
    return _data_member_name(path.as_posix())


def _safe_destination(rootfs, raw_name):
    relative = _safe_relative_path(raw_name)
    destination = Path(rootfs).joinpath(*relative.parts)
    root = Path(rootfs).resolve()
    if destination.is_symlink():
        raise SmartBuildError("IPKG", f"refusing existing symlink destination: {raw_name}")
    resolved_parent = destination.parent.resolve()
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("IPKG", f"rootfs path escapes rootfs: {raw_name}") from exc
    return destination


def _safe_relative_path(raw_path):
    path = PurePosixPath(str(raw_path))
    if path.is_absolute():
        raise SmartBuildError("IPKG", f"absolute package path is not allowed: {raw_path}")
    parts = [part for part in path.parts if part != "."]
    if not parts:
        raise SmartBuildError("IPKG", f"empty package path: {raw_path}")
    for part in parts:
        if part in {"", ".."}:
            raise SmartBuildError("IPKG", f"unsafe package path: {raw_path}")
    return PurePosixPath(*parts)


def _install_file(package_path, destination, payload, mode):
    if destination.exists():
        if not destination.is_file():
            raise SmartBuildError("IPKG", f"package file conflict: {destination}")
        if path_record(destination).get("sha256") != _incoming_file_checksum(destination, payload, mode):
            raise SmartBuildError("IPKG", f"package file conflict: {destination}")
        return
    destination.write_bytes(payload)
    destination.chmod(mode)


def _incoming_file_checksum(destination, payload, mode):
    probe = Path(f"{destination}.ipkg-new")
    try:
        if probe.exists() or probe.is_symlink():
            raise SmartBuildError("IPKG", f"temporary package path already exists: {probe}")
        probe.write_bytes(payload)
        probe.chmod(mode)
        return path_record(probe).get("sha256")
    finally:
        if probe.exists() or probe.is_symlink():
            probe.unlink()


def _prepare_package_output(path):
    output = Path(path)
    if output.is_symlink():
        raise SmartBuildError("IPKG", f"refusing to replace symlink package output: {output}")
    if not output.exists():
        return
    if not output.is_file():
        raise SmartBuildError("IPKG", f"refusing to replace non-file package output: {output}")
    if output.stat().st_nlink > 1:
        raise SmartBuildError("IPKG", f"refusing to replace hardlink package output: {output}")
    output.unlink()
