import os
import subprocess
import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
import warnings
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..cache import path_record
from ..config import DEFAULT_MACHINE, load_machine_config
from ..errors import SmartBuildError
from ..machines import Machine, ToolchainRelease, load_machine
from ..paths import project_root


TOOLCHAIN_PACKAGE = "aarch64-linux-musleabi-gcc-latest"
TARGET_TRIPLE = "aarch64-linux-musleabi"
PREFIX = f"{TARGET_TRIPLE}-"
LOADER_NAME = "ld-musl-aarch64.so.1"
TOOLCHAIN_ID = f"{TARGET_TRIPLE}-gcc"


@dataclass(frozen=True)
class Toolchain:
    root: Path
    prefix: str = PREFIX
    target: str = TARGET_TRIPLE
    package: str = TOOLCHAIN_PACKAGE
    loader_name: str | None = LOADER_NAME
    dumpmachine: str = TARGET_TRIPLE
    gcc_version: str = ""
    crt1: Path = None
    libgcc_runtime: Path = None
    libgcc_static: Path = None
    libatomic_runtime: Path = None
    libstdcxx_runtime: Path = None
    source: str = "env-sdk"
    configured_version: str = ""

    @property
    def bin_dir(self):
        return self.root / "bin"

    @property
    def sysroot_lib_dir(self):
        return self.root / self.target / "lib"

    @property
    def gcc(self):
        return self.bin_dir / f"{self.prefix}gcc"

    @property
    def gxx(self):
        return self.bin_dir / f"{self.prefix}g++"

    @property
    def libc(self):
        if self.loader_name is None:
            return None
        return self.sysroot_lib_dir / "libc.so"

    @property
    def loader(self):
        if self.loader_name is None:
            return None
        return self.sysroot_lib_dir / self.loader_name

    def validate(self):
        _validate_compiler(self.gcc)
        _validate_compiler(self.gxx)
        if self.loader_name is not None:
            _validate_resolved_file(self.libc, self.root, self.target)
            _validate_resolved_file(self.loader, self.root, self.target)
            crt1 = _find_required_file("crt1.o", (self.sysroot_lib_dir / "crt1.o",), self.root)
            libgcc_runtime = _find_optional_file(
                "libgcc_s.so.1",
                (
                    self.root / self.target / "lib64" / "libgcc_s.so.1",
                    self.sysroot_lib_dir / "libgcc_s.so.1",
                ),
            )
            libatomic_runtime = _find_optional_file(
                "libatomic.so.1",
                (
                    self.root / self.target / "lib64" / "libatomic.so.1",
                    self.sysroot_lib_dir / "libatomic.so.1",
                ),
            )
            libstdcxx_runtime = _find_optional_file(
                "libstdc++.so.6",
                (
                    self.root / self.target / "lib64" / "libstdc++.so.6",
                    self.sysroot_lib_dir / "libstdc++.so.6",
                ),
            )
        else:
            crt1 = None
            libgcc_runtime = None
            libatomic_runtime = None
            libstdcxx_runtime = None
        libgcc_static = _find_optional_file(
            "libgcc.a",
            (
                self.root / "lib" / "gcc" / self.target / self.gcc_version / "libgcc.a",
                self.root / self.target / "lib" / "libgcc.a",
                self.root / self.target / "lib64" / "libgcc.a",
            ),
        )
        if libgcc_static is None:
            libgcc_static = _find_first_by_name(self.root, "libgcc.a")
        if self.loader_name is not None and libgcc_runtime is None:
            raise SmartBuildError(
                "TOOLCHAIN",
                f"missing toolchain runtime: libgcc_s.so.1 under {self.root}",
            )
        if self.loader_name is not None and libstdcxx_runtime is None:
            raise SmartBuildError(
                "TOOLCHAIN",
                f"missing toolchain C++ runtime: libstdc++.so.6 under {self.root}",
            )
        if libgcc_static is None:
            raise SmartBuildError(
                "TOOLCHAIN",
                f"missing toolchain static runtime: libgcc.a under {self.root}",
            )
        if self.dumpmachine != self.target:
            raise SmartBuildError(
                "TOOLCHAIN",
                f"gcc -dumpmachine expected {self.target}, got {self.dumpmachine}",
            )
        return Toolchain(
            root=self.root,
            prefix=self.prefix,
            target=self.target,
            package=self.package,
            loader_name=self.loader_name,
            dumpmachine=self.dumpmachine,
            gcc_version=self.gcc_version,
            crt1=crt1,
            libgcc_runtime=libgcc_runtime,
            libgcc_static=libgcc_static,
            libatomic_runtime=libatomic_runtime,
            libstdcxx_runtime=libstdcxx_runtime,
            source=self.source,
            configured_version=self.configured_version,
        )

    def missing_required_files(self):
        missing = []
        required_paths = [self.gcc, self.gxx]
        if self.loader_name is not None:
            required_paths.extend([self.libc, self.loader])
        for path in required_paths:
            if not _path_exists_or_symlink(path):
                missing.append(str(path))
        if self.loader_name is not None:
            if not _find_optional_file("crt1.o", (self.sysroot_lib_dir / "crt1.o",)):
                missing.append(str(self.sysroot_lib_dir / "crt1.o"))
            runtime = _find_optional_file(
                "libgcc_s.so.1",
                (
                    self.root / self.target / "lib64" / "libgcc_s.so.1",
                    self.sysroot_lib_dir / "libgcc_s.so.1",
                ),
            )
            cxx_runtime = _find_optional_file(
                "libstdc++.so.6",
                (
                    self.root / self.target / "lib64" / "libstdc++.so.6",
                    self.sysroot_lib_dir / "libstdc++.so.6",
                ),
            )
        else:
            runtime = True
            cxx_runtime = True
        static = _find_first_by_name(self.root, "libgcc.a")
        if runtime is None:
            missing.append(f"{self.root}/{{libgcc_s.so.1}}")
        if cxx_runtime is None:
            missing.append(f"{self.root}/{{libstdc++.so.6}}")
        if static is None:
            missing.append(f"{self.root}/{{libgcc.a}}")
        return missing

    def validate_required_files_present(self):
        missing = self.missing_required_files()
        if missing:
            raise SmartBuildError("TOOLCHAIN", f"missing toolchain files: {', '.join(missing)}")
        for compiler in (self.gcc, self.gxx):
            _validate_compiler(compiler)
        if self.loader_name is not None:
            _validate_resolved_file(self.libc, self.root, self.target)
            _validate_resolved_file(self.loader, self.root, self.target)
        return self

    def compile_env(self, base_env=None):
        source_env = os.environ if base_env is None else base_env
        existing_path = source_env.get("PATH", "")
        path = str(self.bin_dir)
        if existing_path:
            path = f"{path}{os.pathsep}{existing_path}"
        return {
            "PATH": path,
            "RTT_CC": "gcc",
            "RTT_EXEC_PATH": str(self.bin_dir),
            "RTT_CC_PREFIX": self.prefix,
            "CROSS_COMPILE": self.prefix,
        }

    def manifest_record(self):
        checksums = {
            "gcc": _path_sha256(self.gcc),
            "gxx": _path_sha256(self.gxx),
            "libc": _path_sha256(self.libc),
            "loader": _path_sha256(self.loader),
            "crt1": _path_sha256(self.crt1),
            "libgcc_runtime": _path_sha256(self.libgcc_runtime),
            "libgcc_static": _path_sha256(self.libgcc_static),
            "libatomic_runtime": _path_sha256(self.libatomic_runtime),
            "libstdcxx_runtime": _path_sha256(self.libstdcxx_runtime),
        }
        paths = {
            "gcc": str(self.gcc),
            "gxx": str(self.gxx),
            "libc": _path_string(self.libc),
            "loader": _path_string(self.loader),
            "crt1": _path_string(self.crt1),
            "libgcc_runtime": str(self.libgcc_runtime) if self.libgcc_runtime else None,
            "libgcc_static": str(self.libgcc_static) if self.libgcc_static else None,
            "libatomic_runtime": str(self.libatomic_runtime) if self.libatomic_runtime else None,
            "libstdcxx_runtime": str(self.libstdcxx_runtime) if self.libstdcxx_runtime else None,
        }
        fingerprint_payload = {
            "id": self.id,
            "package": self.package,
            "source": self.source,
            "configured_version": self.configured_version,
            "target": self.target,
            "prefix": self.prefix,
            "gcc_version": self.gcc_version,
            "dumpmachine": self.dumpmachine,
            "paths": paths,
            "checksums": checksums,
        }
        return {
            "id": self.id,
            "package": self.package,
            "source": self.source,
            "configured_version": self.configured_version,
            "target": self.target,
            "prefix": self.prefix,
            "root": str(self.root),
            "bin_dir": str(self.bin_dir),
            "gcc": str(self.gcc),
            "gxx": str(self.gxx),
            "libc": _path_string(self.libc),
            "loader": _path_string(self.loader),
            "gcc_version": self.gcc_version,
            "dumpmachine": self.dumpmachine,
            "crt1": _path_string(self.crt1),
            "libgcc": {
                "runtime": str(self.libgcc_runtime) if self.libgcc_runtime else None,
                "static": str(self.libgcc_static) if self.libgcc_static else None,
            },
            "libatomic": {
                "runtime": str(self.libatomic_runtime) if self.libatomic_runtime else None,
            },
            "libstdcxx": {
                "runtime": str(self.libstdcxx_runtime) if self.libstdcxx_runtime else None,
            },
            "paths": paths,
            "checksums": checksums,
            "fingerprint": _fingerprint(fingerprint_payload),
        }

    @property
    def id(self):
        return f"{self.target}-gcc"


@dataclass(frozen=True)
class ToolchainSelection:
    machine: Machine
    release: ToolchainRelease
    custom_root: Path | None = None


@dataclass(frozen=True)
class ToolchainStatus:
    version: str
    package: str
    selected: bool
    downloadable: bool
    state: str
    source: str | None
    root: Path | None


def default_toolchain_root(machine=None):
    metadata = _resolve_machine(machine)
    selection = resolve_toolchain_selection(metadata)
    return env_toolchain_root(selection.release)


def env_toolchain_root(release, home=None):
    home_path = Path.home() if home is None else Path(home)
    return home_path / ".env" / "tools" / "scripts" / "packages" / release.package


def downloaded_toolchain_root(root, release):
    suffix = f"-{release.version}" if release.version else ""
    return Path(root) / "downloads" / "toolchains" / f"{release.package}{suffix}"


def resolve_toolchain_selection(machine=None, *, version=None, package=None, custom_root=None):
    metadata = _resolve_machine(machine)
    values = load_machine_config(metadata.root, metadata.name)
    configured_package = package or values.get("TOOLCHAIN") or metadata.toolchain_package
    configured_version = version or values.get("TOOLCHAIN_VERSION") or metadata.toolchain_version
    configured_root = custom_root
    if configured_root is None:
        configured_root = values.get("TOOLCHAIN_PATH") or None

    releases = metadata.toolchain_releases or (
        ToolchainRelease(version=metadata.toolchain_version, package=metadata.toolchain_package),
    )
    if version is not None:
        matching = [release for release in releases if release.version == configured_version]
        if package is not None:
            matching = [release for release in matching if release.package == configured_package]
    else:
        matching = [release for release in releases if release.package == configured_package]
        if configured_version:
            matching = [release for release in matching if release.version == configured_version]
    if len(matching) != 1:
        supported = ", ".join(
            f"{release.version or '<default>'} ({release.package})" for release in releases
        )
        raise SmartBuildError(
            "TOOLCHAIN",
            f"machine {metadata.name} does not support TOOLCHAIN={configured_package!r} "
            f"TOOLCHAIN_VERSION={configured_version!r}; supported: {supported}",
        )
    root_path = Path(configured_root).expanduser() if configured_root is not None else None
    if root_path is not None and not root_path.is_absolute():
        root_path = metadata.root / root_path
    return ToolchainSelection(machine=metadata, release=matching[0], custom_root=root_path)


def resolve_toolchain(root=None, *, machine=None, version=None, package=None, home=None):
    selection = resolve_toolchain_selection(
        machine,
        version=version,
        package=package,
        custom_root=root,
    )
    candidates = _toolchain_candidates(selection, home=home)
    for source, candidate_root in candidates:
        if not candidate_root.exists() and not candidate_root.is_symlink():
            continue
        return _resolve_toolchain_at(candidate_root, selection, source)
    raise _missing_toolchain_error(selection, candidates)


def _resolve_toolchain_at(toolchain_root, selection, source):
    metadata = selection.machine
    release = selection.release
    toolchain_root = Path(toolchain_root).expanduser().resolve()
    if not toolchain_root.is_dir():
        raise SmartBuildError("TOOLCHAIN", f"toolchain package is not a directory: {toolchain_root}")
    candidate = Toolchain(
        root=toolchain_root,
        prefix=metadata.prefix,
        target=metadata.target_triple,
        package=release.package,
        loader_name=metadata.loader,
        source=source,
        configured_version=release.version,
    )
    candidate.validate_required_files_present()
    dumpmachine = _run_compiler_query(candidate.gcc, "-dumpmachine")
    gcc_version = _run_compiler_query(candidate.gcc, "-dumpversion")
    resolved = Toolchain(
        root=toolchain_root,
        prefix=metadata.prefix,
        target=metadata.target_triple,
        package=release.package,
        loader_name=metadata.loader,
        dumpmachine=dumpmachine,
        gcc_version=gcc_version,
        source=source,
        configured_version=release.version,
    ).validate()
    if release.gcc_version and resolved.gcc_version != release.gcc_version:
        raise SmartBuildError(
            "TOOLCHAIN",
            f"toolchain {toolchain_root} expected GCC {release.gcc_version}, "
            f"got {resolved.gcc_version}",
        )
    return resolved


def toolchain_statuses(machine=None, *, home=None):
    selected = resolve_toolchain_selection(machine)
    metadata = selected.machine
    statuses = []
    releases = metadata.toolchain_releases or (selected.release,)
    for release in releases:
        is_selected = release == selected.release
        release_selection = ToolchainSelection(
            machine=metadata,
            release=release,
            custom_root=selected.custom_root if is_selected else None,
        )
        status = _release_status(release_selection, home=home)
        statuses.append(
            ToolchainStatus(
                version=release.version,
                package=release.package,
                selected=is_selected,
                downloadable=release.downloadable,
                state=status[0],
                source=status[1],
                root=status[2],
            )
        )
    return tuple(statuses)


def install_toolchain(machine=None, *, version=None, package=None, home=None, downloader=None, output=None):
    selection = resolve_toolchain_selection(machine, version=version, package=package)
    selection = ToolchainSelection(machine=selection.machine, release=selection.release)
    release = selection.release
    stream = output

    for source, candidate_root in _toolchain_candidates(selection, home=home):
        if candidate_root.exists() or candidate_root.is_symlink():
            resolved = _resolve_toolchain_at(candidate_root, selection, source)
            _write_install_message(stream, f"using installed toolchain: {resolved.root}")
            return resolved

    install_root = downloaded_toolchain_root(selection.machine.root, release)
    if install_root.exists() or install_root.is_symlink():
        return _resolve_toolchain_at(install_root, selection, "downloads")
    if not release.downloadable:
        raise SmartBuildError(
            "TOOLCHAIN",
            f"toolchain {release.package} version {release.version} has no download source; "
            "install it with Env SDK or select another version",
        )

    archive = _toolchain_archive_path(selection.machine.root, release)
    _ensure_toolchain_archive(release, archive, downloader=downloader, output=stream)
    install_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{release.package}.install-", dir=install_root.parent))
    raw_root = temporary_root / "raw"
    raw_root.mkdir()
    try:
        _extract_toolchain_archive(archive, raw_root, selection.machine.target_triple)
        source_root = _toolchain_source_root(raw_root, release.strip_root)
        resolved = _resolve_toolchain_at(source_root, selection, "downloads")
        if install_root.exists() or install_root.is_symlink():
            raise SmartBuildError("TOOLCHAIN", f"toolchain install path already exists: {install_root}")
        source_root.replace(install_root)
        resolved = _resolve_toolchain_at(install_root, selection, "downloads")
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    _write_install_message(stream, f"installed toolchain: {resolved.root}")
    return resolved


def _toolchain_candidates(selection, home=None):
    candidates = []
    if selection.custom_root is not None:
        candidates.append(("custom", selection.custom_root))
    candidates.append(("env-sdk", env_toolchain_root(selection.release, home=home)))
    candidates.append(("downloads", downloaded_toolchain_root(selection.machine.root, selection.release)))
    legacy_root = Path(selection.machine.root) / "downloads" / "toolchains" / selection.release.package
    if legacy_root != downloaded_toolchain_root(selection.machine.root, selection.release):
        candidates.append(("downloads", legacy_root))
    return tuple(candidates)


def _release_status(selection, home=None):
    for source, root in _toolchain_candidates(selection, home=home):
        if not root.exists() and not root.is_symlink():
            continue
        try:
            resolved = _resolve_toolchain_at(root, selection, source)
        except SmartBuildError:
            return "invalid", source, Path(root)
        return "installed", source, resolved.root
    return "missing", None, None


def _missing_toolchain_error(selection, candidates):
    release = selection.release
    searched = ", ".join(str(path) for _source, path in candidates)
    command = (
        f"./smart-build toolchain install --machine {selection.machine.name} "
        f"--version {release.version} --yes"
    )
    if release.downloadable:
        hint = f"run {command} or configure TOOLCHAIN_PATH"
    else:
        hint = "install it with Env SDK, configure TOOLCHAIN_PATH, or select another version"
    return SmartBuildError(
        "TOOLCHAIN",
        f"toolchain {release.package} version {release.version or '<default>'} not found; "
        f"searched: {searched}; {hint}",
    )


def _toolchain_archive_path(root, release):
    filename = f"{release.package}-{release.version}-{release.archive}" if release.version else release.archive
    return Path(root) / "downloads" / "toolchains" / "archives" / filename


def _ensure_toolchain_archive(release, archive, downloader=None, output=None):
    archive = Path(archive)
    if archive.is_file():
        _verify_toolchain_archive(archive, release.sha256)
        _write_install_message(output, f"using cached toolchain archive: {archive}")
        return
    if archive.exists() or archive.is_symlink():
        raise SmartBuildError("TOOLCHAIN", f"toolchain archive path is not a regular file: {archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(f".{archive.name}.download-{os.getpid()}")
    fetcher = downloader or _download_file
    try:
        _write_install_message(output, f"downloading toolchain: {release.url}")
        fetcher(release.url, temporary)
        if not temporary.is_file():
            raise SmartBuildError("TOOLCHAIN", f"download did not create toolchain archive: {temporary}")
        _verify_toolchain_archive(temporary, release.sha256)
        temporary.replace(archive)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _download_file(url, destination):
    try:
        with urllib.request.urlopen(url) as response, Path(destination).open("wb") as output:
            shutil.copyfileobj(response, output)
    except (OSError, urllib.error.URLError) as exc:
        raise SmartBuildError("TOOLCHAIN", f"failed to download toolchain {url}: {exc}") from exc


def _verify_toolchain_archive(path, expected_sha256):
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SmartBuildError("TOOLCHAIN", f"failed to read toolchain archive {path}: {exc}") from exc
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise SmartBuildError(
            "TOOLCHAIN",
            f"toolchain archive sha256 mismatch: {path} expected {expected_sha256} got {actual}",
        )
    return actual


def _extract_toolchain_archive(archive, destination, target):
    Path(destination).mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, mode="r:*") as handle:
            members = handle.getmembers()
            _validate_toolchain_members(members, destination, target)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning, module="tarfile")
                handle.extractall(destination, members=members)
    except (tarfile.TarError, OSError) as exc:
        raise SmartBuildError("TOOLCHAIN", f"failed to extract toolchain archive {archive}: {exc}") from exc


def _validate_toolchain_members(members, destination, target):
    names = {member.name for member in members}
    members_by_name = {member.name: member for member in members}
    symlink_paths = set()
    for member in members:
        path = _validated_archive_path(destination, member.name)
        if member.issym():
            _validate_toolchain_symlink(member, path, destination, target)
            symlink_paths.add(PurePosixPath(member.name))
        elif member.islnk():
            _validated_archive_path(destination, member.linkname)
            link_target = members_by_name.get(member.linkname)
            if member.linkname not in names or link_target is None or not link_target.isfile():
                raise SmartBuildError("TOOLCHAIN", f"unsafe toolchain archive hard link: {member.name}")
        elif not (member.isfile() or member.isdir()):
            raise SmartBuildError("TOOLCHAIN", f"unsupported toolchain archive member type: {member.name}")
    for member in members:
        member_path = PurePosixPath(member.name)
        if any(link_path in member_path.parents for link_path in symlink_paths):
            raise SmartBuildError("TOOLCHAIN", f"toolchain archive member traverses a link: {member.name}")


def _validated_archive_path(destination, name):
    if not name or "\\" in name:
        raise SmartBuildError("TOOLCHAIN", f"unsafe toolchain archive member path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".."} for part in path.parts):
        raise SmartBuildError("TOOLCHAIN", f"unsafe toolchain archive member path: {name}")
    root = Path(destination).resolve()
    resolved = (root / Path(*path.parts)).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("TOOLCHAIN", f"unsafe toolchain archive member path: {name}") from exc
    return resolved


def _validate_toolchain_symlink(member, member_path, destination, target):
    link = PurePosixPath(member.linkname)
    root = Path(destination).resolve()
    if link.is_absolute():
        member_parts = PurePosixPath(member.name).parts
        if target not in member_parts:
            raise SmartBuildError("TOOLCHAIN", f"unsafe absolute toolchain archive link: {member.name}")
        target_index = member_parts.index(target)
        resolved = root.joinpath(*member_parts[: target_index + 1], *link.parts[1:]).resolve(strict=False)
    else:
        resolved = (member_path.parent / Path(*link.parts)).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("TOOLCHAIN", f"unsafe toolchain archive link: {member.name}") from exc


def _toolchain_source_root(raw_root, strip_root):
    if not strip_root:
        return Path(raw_root)
    children = list(Path(raw_root).iterdir())
    if len(children) != 1 or not children[0].is_dir() or children[0].is_symlink():
        raise SmartBuildError("TOOLCHAIN", "toolchain archive must contain one top-level directory")
    return children[0]


def _write_install_message(output, message):
    if output is not None:
        output.write(message + "\n")


def toolchain_task_fields(toolchain=None):
    if _is_resolved_toolchain(toolchain):
        resolved = toolchain
    else:
        resolved = resolve_toolchain(machine=toolchain)
    record = resolved.manifest_record()
    return {
        "env": resolved.compile_env(),
        "cache_extra": {"toolchain": record},
        "manifest_fields": {"toolchain": record},
        "record": record,
    }


def _resolve_machine(machine):
    if isinstance(machine, Machine):
        return machine
    machine_name = DEFAULT_MACHINE if machine is None else machine
    return load_machine(project_root(), machine_name)


def _is_resolved_toolchain(value):
    return (
        value is not None
        and hasattr(value, "compile_env")
        and callable(value.compile_env)
        and hasattr(value, "manifest_record")
        and callable(value.manifest_record)
    )


def _path_exists_or_symlink(path):
    candidate = Path(path)
    return candidate.exists() or candidate.is_symlink()


def _validate_compiler(path):
    candidate = Path(path)
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise SmartBuildError("TOOLCHAIN", f"toolchain compiler must be an executable file: {candidate}")


def _validate_resolved_file(path, root, target):
    candidate = Path(path)
    resolved = _resolve_target_file(candidate, root, target)
    if candidate.is_symlink() and resolved is None:
        raise SmartBuildError("TOOLCHAIN", f"toolchain file is a dangling symlink: {candidate}")
    if resolved is None or not resolved.is_file():
        raise SmartBuildError("TOOLCHAIN", f"toolchain file must resolve to a file: {candidate}")


def _find_required_file(name, candidates, root):
    found = _find_optional_file(name, candidates)
    if found is not None:
        return found
    found = _find_first_by_name(root, name)
    if found is not None:
        return found
    raise SmartBuildError("TOOLCHAIN", f"missing toolchain file: {name} under {root}")


def _find_optional_file(name, candidates):
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path
    return None


def _find_first_by_name(root, name):
    for path in sorted(Path(root).rglob(name)):
        if path.exists() and path.is_file():
            return path.resolve()
    return None


def _run_compiler_query(gcc, flag):
    try:
        completed = subprocess.run(
            [str(gcc), flag],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise SmartBuildError("TOOLCHAIN", f"failed to run {gcc} {flag}: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SmartBuildError(
            "TOOLCHAIN",
            f"{gcc} {flag} failed with exit code {completed.returncode}: {detail}",
        )
    return completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""


def _path_sha256(path):
    if path is None:
        return None
    return path_record(path).get("sha256")


def _path_string(path):
    return str(path) if path is not None else None


def _fingerprint(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_target_file(path, root, target):
    candidate = Path(path)
    if not candidate.is_symlink():
        return candidate.resolve() if candidate.exists() else None
    link_target = candidate.readlink()
    resolved = candidate.resolve(strict=False)
    if resolved.exists():
        return resolved
    if link_target.is_absolute():
        sysroot_target = Path(root) / target / link_target.relative_to("/")
        if sysroot_target.exists():
            return sysroot_target.resolve()
    return None
