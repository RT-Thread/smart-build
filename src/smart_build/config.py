from dataclasses import dataclass
from pathlib import Path

from .descriptions import load_description
from .errors import SmartBuildError
from .package_metadata import load_all_package_metadata, package_selection_symbol
from .package_resolver import resolve_package_selection
from .paths import board_defconfig_path, rootfs_description_path


DEFAULT_MACHINE = "qemu-virt-aarch64"
PACKAGE_CONFIGS = {
    "PACKAGE_HELLO": "hello",
    "PACKAGE_ZLIB": "zlib",
    "PACKAGE_MICROPYTHON": "micropython",
}
ROOTFS_BUILD_MODES = {"static", "dynamic", "mixed"}
ROOTFS_IMAGE_FORMATS = {"ext4", "fat", "romfs"}
ROOTFS_IMAGE_SIZES_MB = {1, 4, 8, 16, 32, 64, 128, 256, 512, 1024}
ROOTFS_IMAGE_SIZE_MODES = {"fixed", "expandable"}
DEFAULT_ROOTFS_IMAGE_FORMAT = "ext4"
DEFAULT_ROOTFS_IMAGE_SIZE_MB = 16
DEFAULT_ROOTFS_IMAGE_SIZE_MODE = "expandable"


@dataclass(frozen=True)
class RootfsSelection:
    rootfs: str
    build_mode: str | None
    profile: str | None
    packages: list[str]
    selected_packages: tuple = ()
    image_format: str | None = None
    image_size_mb: int | None = None
    image_size_mode: str | None = None


def load_defconfig(path):
    values = {}
    config_path = Path(path)
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SmartBuildError("CONFIG", f"failed to read defconfig {config_path}: {exc}") from exc

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            unset = _parse_unset_config(line)
            if unset is not None:
                values[unset] = "n"
            continue
        if "=" not in line:
            raise SmartBuildError(
                "CONFIG",
                f"invalid defconfig line {config_path}:{line_number}: missing '='",
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            raise SmartBuildError(
                "CONFIG",
                f"invalid defconfig line {config_path}:{line_number}: empty key",
            )
        values[key] = value

    return values


def workspace_config_path(root):
    return Path(root) / "build" / ".config"


def load_workspace_config(root):
    path = workspace_config_path(root)
    if not path.exists():
        return {}
    return load_defconfig(path)


def load_machine_config(root, machine):
    root_path = Path(root)
    values = load_defconfig(board_defconfig_path(root_path, machine))
    workspace_values = load_workspace_config(root_path)
    if workspace_values.get("MACHINE") == machine:
        values.update(workspace_values)
    return values


def write_workspace_config(root, values):
    path = workspace_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in values.items():
        if value in {"y", "n"}:
            lines.append(f"{key}={value}")
        else:
            lines.append(f"{key}={_quote_if_needed(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def resolve_rootfs_selection(root, machine):
    root_path = Path(root)
    defconfig = board_defconfig_path(root_path, machine)
    values = load_machine_config(root_path, machine)
    rootfs = values.get("ROOTFS", "minimal")
    if rootfs == "none":
        return RootfsSelection(rootfs=rootfs, build_mode=None, profile=None, packages=[])
    if rootfs == "basic":
        image_config = _rootfs_image_config(values)
        return RootfsSelection(
            rootfs=rootfs,
            build_mode="static",
            profile=None,
            packages=[],
            image_format=image_config["format"],
            image_size_mb=image_config["size_mb"],
            image_size_mode=image_config["size_mode"],
        )
    if rootfs not in {"minimal", "full"}:
        raise SmartBuildError("ROOTFS", f"{defconfig}: unsupported ROOTFS={rootfs}")

    build_mode = _rootfs_build_mode(values)
    if rootfs == "minimal":
        profile = build_mode
        packages = _profile_packages(root_path, rootfs, profile)
    else:
        profile = _rootfs_profile(root_path, rootfs, values)
        profile_packages = _profile_packages(root_path, rootfs, profile)
        explicit_package_keys = _explicit_package_keys(root_path, values)
        package_mode = _rootfs_package_mode(values, explicit_package_keys)
        explicit_packages = _explicit_packages(root_path, values)
        packages = explicit_packages if package_mode == "manual" else profile_packages
    resolved_packages = resolve_package_selection(root_path, packages, values)
    image_config = _rootfs_image_config(values)
    return RootfsSelection(
        rootfs=rootfs,
        build_mode=build_mode,
        profile=profile if rootfs == "full" else None,
        packages=resolved_packages.package_names,
        selected_packages=resolved_packages.packages,
        image_format=image_config["format"],
        image_size_mb=image_config["size_mb"],
        image_size_mode=image_config["size_mode"],
    )


def _parse_unset_config(line):
    if not line.startswith("# ") or not line.endswith(" is not set"):
        return None
    key = line[2 : -len(" is not set")].strip()
    return key or None


def _quote_if_needed(value):
    text = str(value)
    if text == "" or any(char.isspace() for char in text) or text in {"y", "n"}:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _is_enabled(value):
    return str(value).strip().lower() in {"y", "yes", "true", "1"}


def _rootfs_package_mode(values, explicit_package_keys):
    mode = values.get("ROOTFS_PACKAGE_MODE")
    if mode is None:
        return "manual" if explicit_package_keys else "profile"
    if mode not in {"profile", "manual"}:
        raise SmartBuildError("CONFIG", f"unsupported ROOTFS_PACKAGE_MODE={mode}")
    return mode


def _rootfs_build_mode(values):
    mode = values.get("ROOTFS_BUILD_MODE")
    if mode is None and values.get("ROOTFS") != "full":
        mode = values.get("ROOTFS_PROFILE")
    if mode is None:
        mode = "mixed"
    if mode not in ROOTFS_BUILD_MODES:
        raise SmartBuildError("CONFIG", f"unsupported ROOTFS_BUILD_MODE={mode}")
    return mode


def _rootfs_profile(root, rootfs, values):
    profile = values.get("ROOTFS_PROFILE")
    if profile is None:
        return _default_profile_or_none(root, rootfs)
    if not profile:
        raise SmartBuildError("CONFIG", "ROOTFS_PROFILE must be a non-empty string")
    return profile


def _rootfs_image_config(values):
    image_format = values.get("ROOTFS_IMAGE_FORMAT", DEFAULT_ROOTFS_IMAGE_FORMAT)
    if image_format not in ROOTFS_IMAGE_FORMATS:
        raise SmartBuildError("CONFIG", f"unsupported ROOTFS_IMAGE_FORMAT={image_format}")
    if image_format == "romfs":
        if "ROOTFS_IMAGE_SIZE_MB" in values:
            raise SmartBuildError("CONFIG", "ROOTFS_IMAGE_SIZE_MB is not supported for romfs")
        if "ROOTFS_IMAGE_SIZE_MODE" in values:
            raise SmartBuildError("CONFIG", "ROOTFS_IMAGE_SIZE_MODE is not supported for romfs")
        return {"format": image_format, "size_mb": None, "size_mode": None}

    image_size_mb = _rootfs_image_size_mb(values)
    if image_format == "fat":
        size_mode = values.get("ROOTFS_IMAGE_SIZE_MODE", "fixed")
        if size_mode != "fixed":
            raise SmartBuildError("CONFIG", "ROOTFS_IMAGE_SIZE_MODE=expandable is supported only for ext4")
        return {"format": image_format, "size_mb": image_size_mb, "size_mode": "fixed"}

    size_mode = values.get("ROOTFS_IMAGE_SIZE_MODE", DEFAULT_ROOTFS_IMAGE_SIZE_MODE)
    if size_mode not in ROOTFS_IMAGE_SIZE_MODES:
        raise SmartBuildError("CONFIG", f"unsupported ROOTFS_IMAGE_SIZE_MODE={size_mode}")
    return {"format": image_format, "size_mb": image_size_mb, "size_mode": size_mode}


def _rootfs_image_size_mb(values):
    raw_size = values.get("ROOTFS_IMAGE_SIZE_MB", str(DEFAULT_ROOTFS_IMAGE_SIZE_MB))
    try:
        size_mb = int(raw_size)
    except (TypeError, ValueError) as exc:
        raise SmartBuildError("CONFIG", f"ROOTFS_IMAGE_SIZE_MB must be an integer: {raw_size}") from exc
    if size_mb not in ROOTFS_IMAGE_SIZES_MB:
        choices = ", ".join(str(size) for size in sorted(ROOTFS_IMAGE_SIZES_MB))
        raise SmartBuildError(
            "CONFIG",
            f"unsupported ROOTFS_IMAGE_SIZE_MB={size_mb}; expected one of: {choices}",
        )
    return size_mb


def _explicit_package_keys(root, values):
    symbols = {
        package_selection_symbol(metadata)
        for metadata in load_all_package_metadata(root)
    }
    return [key for key in values if key in symbols]


def _explicit_packages(root, values):
    packages = [
        metadata.name
        for metadata in load_all_package_metadata(root)
        if _is_enabled(values.get(package_selection_symbol(metadata)))
    ]
    if packages:
        return packages
    return [
        package
        for key, package in PACKAGE_CONFIGS.items()
        if _is_enabled(values.get(key))
    ]
def _profile_packages(root, rootfs, profile=None):
    description = _rootfs_description(root, rootfs)
    if "profiles" not in description.data:
        return _validated_package_list(description, description.data.get("packages", []))
    selected = profile or _default_profile(root, rootfs)
    profiles = description.data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise SmartBuildError("ROOTFS", f"{description.path}: profiles must be a non-empty mapping")
    profile_data = profiles.get(selected)
    if not isinstance(profile_data, dict):
        raise SmartBuildError("ROOTFS", f"{description.path}: unknown rootfs profile: {selected}")
    return _validated_package_list(description, profile_data.get("packages", []))


def _validated_package_list(description, packages):
    if not isinstance(packages, list) or not packages:
        raise SmartBuildError("ROOTFS", f"{description.path}: packages must be a non-empty list")
    for package in packages:
        if not isinstance(package, str):
            raise SmartBuildError("ROOTFS", f"{description.path}: package names must be strings")
    return list(packages)


def _default_profile(root, rootfs):
    description = _rootfs_description(root, rootfs)
    default = description.data.get("default_profile")
    if not isinstance(default, str) or not default:
        raise SmartBuildError("ROOTFS", f"{description.path}: default_profile must be a non-empty string")
    return default


def _default_profile_or_none(root, rootfs):
    description = _rootfs_description(root, rootfs)
    if "profiles" not in description.data:
        return None
    return _default_profile(root, rootfs)


def _rootfs_description(root, rootfs):
    description = load_description(rootfs_description_path(root, rootfs))
    if description.kind != "rootfs" or description.name != rootfs:
        raise SmartBuildError("ROOTFS", f"{description.path}: expected rootfs description named {rootfs}")
    return description
