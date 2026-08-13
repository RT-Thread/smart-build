from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import re

from .descriptions import load_description
from .errors import SmartBuildError
from .paths import board_description_path, board_dir, validate_safe_name


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ToolchainRelease:
    version: str
    package: str
    gcc_version: str | None = None
    url: str | None = None
    archive: str | None = None
    sha256: str | None = None
    strip_root: bool = True

    @property
    def downloadable(self):
        return self.url is not None


@dataclass(frozen=True)
class Machine:
    name: str
    arch: str
    bsp: str
    kernel_defconfig: Path
    toolchain_package: str
    target_triple: str
    prefix: str
    loader: str | None
    qemu_binary: str
    qemu_profile: str
    qemu_machine: str
    qemu_cpu: str | None
    root: Path = Path(".")
    toolchain_version: str = ""
    toolchain_releases: tuple[ToolchainRelease, ...] = ()


def load_machine(root, machine):
    root_path = Path(root)
    machine_name = validate_safe_name(_non_empty_string("machine", machine), "machine")
    owner_dir = board_dir(root_path, machine_name)
    board_path = board_description_path(root_path, machine_name)
    if not board_path.exists():
        raise SmartBuildError("CONFIG", f"unknown machine {machine_name!r}: {board_path} not found")

    description = load_description(board_path)
    if description.kind != "board":
        raise SmartBuildError("CONFIG", f"{board_path}: expected kind 'board', got {description.kind!r}")
    if description.name != machine_name:
        raise SmartBuildError(
            "CONFIG",
            f"{board_path}: board name {description.name!r} does not match machine {machine_name!r}",
        )

    data = description.data
    toolchain = _required_mapping(board_path, data, "toolchain")
    qemu = _required_mapping(board_path, data, "qemu")
    loader = _optional_string(board_path, toolchain, "toolchain.loader")

    package = validate_safe_name(
        _required_string(board_path, toolchain, "toolchain.package"),
        "toolchain package",
    )
    releases = _toolchain_releases(board_path, toolchain, package)
    default_version = _optional_string(board_path, toolchain, "toolchain.version")
    if releases:
        if default_version is None:
            default_version = releases[0].version
        if not any(release.version == default_version for release in releases):
            raise SmartBuildError(
                "CONFIG",
                f"{board_path}: toolchain.version {default_version!r} is not declared in toolchain.versions",
            )
        default_release = next(release for release in releases if release.version == default_version)
        if default_release.package != package:
            raise SmartBuildError(
                "CONFIG",
                f"{board_path}: default toolchain package {package!r} does not match "
                f"toolchain.versions entry {default_release.package!r}",
            )
    else:
        default_version = default_version or ""
        releases = (ToolchainRelease(version=default_version, package=package),)

    return Machine(
        root=root_path,
        name=machine_name,
        arch=_required_string(board_path, data, "arch"),
        bsp=_required_string(board_path, data, "bsp"),
        kernel_defconfig=_kernel_defconfig_path(owner_dir, board_path, data),
        toolchain_package=package,
        target_triple=_required_string(board_path, toolchain, "toolchain.target"),
        prefix=_required_string(board_path, toolchain, "toolchain.prefix"),
        loader=loader,
        toolchain_version=default_version,
        toolchain_releases=releases,
        qemu_binary=_required_string(board_path, qemu, "qemu.binary"),
        qemu_profile=_required_string(board_path, qemu, "qemu.profile"),
        qemu_machine=_required_string(board_path, qemu, "qemu.machine"),
        qemu_cpu=_optional_string(board_path, qemu, "qemu.cpu"),
    )


def _non_empty_string(field, value):
    if not isinstance(value, str) or not value:
        raise SmartBuildError("CONFIG", f"{field} must be a non-empty string")
    return value


def _required_mapping(path, data, field):
    value = data.get(field)
    if not isinstance(value, dict):
        raise SmartBuildError("CONFIG", f"{path}: {field} must be a mapping")
    return value


def _required_string(path, data, field):
    key = field.rsplit(".", 1)[-1]
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SmartBuildError("CONFIG", f"{path}: {field} must be a non-empty string")
    return value


def _kernel_defconfig_path(owner_dir, board_path, data):
    value = _required_string(board_path, data, "kernel_defconfig")
    relative = Path(value)
    if relative.is_absolute():
        raise SmartBuildError("CONFIG", f"{board_path}: kernel_defconfig must be board-relative")
    if ".." in relative.parts:
        raise SmartBuildError("CONFIG", f"{board_path}: kernel_defconfig must not escape board directory")

    owner = owner_dir.resolve()
    resolved = (owner / relative).resolve()
    try:
        resolved.relative_to(owner)
    except ValueError as exc:
        raise SmartBuildError(
            "CONFIG",
            f"{board_path}: kernel_defconfig must stay under {owner_dir}",
        ) from exc
    return resolved


def _optional_string(path, data, field):
    key = field.rsplit(".", 1)[-1]
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, str) and value.lower() == "none":
        return None
    if not isinstance(value, str):
        raise SmartBuildError("CONFIG", f"{path}: {field} must be a string when set")
    return value or None


def _toolchain_releases(board_path, toolchain, default_package):
    raw_releases = toolchain.get("versions")
    if raw_releases is None:
        return ()
    if not isinstance(raw_releases, list) or not raw_releases:
        raise SmartBuildError("CONFIG", f"{board_path}: toolchain.versions must be a non-empty list")

    releases = []
    versions = set()
    for index, raw_release in enumerate(raw_releases):
        label = f"toolchain.versions[{index}]"
        if not isinstance(raw_release, dict):
            raise SmartBuildError("CONFIG", f"{board_path}: {label} must be a mapping")
        version = validate_safe_name(
            _required_string(board_path, raw_release, f"{label}.version"),
            "toolchain version",
        )
        package = validate_safe_name(
            raw_release.get("package", default_package),
            "toolchain package",
        )
        if version in versions:
            raise SmartBuildError("CONFIG", f"{board_path}: duplicate toolchain version {version!r}")
        versions.add(version)
        releases.append(_toolchain_release(board_path, label, raw_release, version, package))
    return tuple(releases)


def _toolchain_release(board_path, label, data, version, package):
    gcc_version = _optional_string(board_path, data, f"{label}.gcc_version")
    source = data.get("source")
    if source is None:
        return ToolchainRelease(version=version, package=package, gcc_version=gcc_version)
    if not isinstance(source, dict):
        raise SmartBuildError("CONFIG", f"{board_path}: {label}.source must be a mapping")
    url = _required_string(board_path, source, f"{label}.source.url")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SmartBuildError("CONFIG", f"{board_path}: {label}.source.url must use HTTPS")
    archive = validate_safe_name(
        _required_string(board_path, source, f"{label}.source.archive"),
        "toolchain archive",
    )
    sha256 = _required_string(board_path, source, f"{label}.source.sha256")
    if not SHA256_RE.fullmatch(sha256):
        raise SmartBuildError(
            "CONFIG",
            f"{board_path}: {label}.source.sha256 must be 64 hex characters",
        )
    strip_root = source.get("strip_root", True)
    if not isinstance(strip_root, bool):
        raise SmartBuildError("CONFIG", f"{board_path}: {label}.source.strip_root must be a boolean")
    return ToolchainRelease(
        version=version,
        package=package,
        gcc_version=gcc_version,
        url=url,
        archive=archive,
        sha256=sha256.lower(),
        strip_root=strip_root,
    )
