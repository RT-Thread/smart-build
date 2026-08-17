import contextvars
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .descriptions import load_description
from .errors import SmartBuildError


_metadata_cache = contextvars.ContextVar("smart_build_package_metadata_cache", default=None)


OPTION_TYPES = frozenset(("bool", "choice", "string"))
RELATION_FIELDS = ("depends", "host_depends", "selects", "conflicts", "provides", "requires_toolchain")
KCONFIG_SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DESCRIPTION_MAX_LENGTH = 80
PACKAGE_GROUP_DIRECTORIES = frozenset(("ros2", "host"))


@dataclass(frozen=True)
class PackageOption:
    name: str
    type: str
    prompt: str
    default: object = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageKconfig:
    mode: str
    source: str
    symbol: str
    path: Path


@dataclass(frozen=True)
class PackageMetadata:
    name: str
    version: str
    versions: tuple[str, ...]
    default_version: str
    description: str
    category: str
    options: tuple[PackageOption, ...]
    depends: tuple[str, ...]
    host_depends: tuple[str, ...]
    selects: tuple[str, ...]
    conflicts: tuple[str, ...]
    provides: tuple[str, ...]
    requires_toolchain: tuple[str, ...]
    kconfig: PackageKconfig
    path: Path


def normalize_package_metadata(description):
    if description.kind != "package":
        raise SmartBuildError("PACKAGE", f"{description.path}: expected package description")

    versions = _versions(description)
    default_version = _default_version(description, versions)
    provides = _relation_list(description, "provides")
    if description.name not in provides:
        provides = (description.name, *provides)

    options = _options(description)
    kconfig = _kconfig(description, options, versions)
    return PackageMetadata(
        name=description.name,
        version=default_version,
        versions=versions,
        default_version=default_version,
        description=_description(description),
        category=_category(description),
        options=options,
        depends=_relation_list(description, "depends"),
        host_depends=_relation_list(description, "host_depends"),
        selects=_relation_list(description, "selects"),
        conflicts=_relation_list(description, "conflicts"),
        provides=provides,
        requires_toolchain=_relation_list(description, "requires_toolchain"),
        kconfig=kconfig,
        path=description.path,
    )


def load_package_metadata(root, name):
    description = load_description(package_description_path(root, name))
    return normalize_package_metadata(description)


class cached_package_metadata:
    def __init__(self):
        self.token = None

    def __enter__(self):
        self.token = _metadata_cache.set({})
        return self

    def __exit__(self, exc_type, exc, tb):
        _metadata_cache.reset(self.token)
        return False


def load_all_package_metadata(root):
    cache = _metadata_cache.get()
    cache_key = str(Path(root).resolve())
    if isinstance(cache, dict) and cache_key in cache:
        return list(cache[cache_key])
    package_dir = Path(root) / "packages"
    if not package_dir.is_dir():
        packages = []
        if isinstance(cache, dict):
            cache[cache_key] = ()
        return packages
    descriptions = []
    seen = {}
    for path in package_description_paths(root):
        description = load_description(path)
        if description.name in seen:
            raise SmartBuildError(
                "PACKAGE",
                f"duplicate package description for {description.name}: {seen[description.name]} and {path}",
            )
        seen[description.name] = path
        descriptions.append(description)
    packages = [normalize_package_metadata(description) for description in descriptions]
    symbols = {}
    for package in packages:
        symbol = package_selection_symbol(package)
        if symbol in symbols:
            raise SmartBuildError(
                "PACKAGE",
                f"duplicate package selection symbol {symbol}: {symbols[symbol]} and {package.name}",
            )
        symbols[symbol] = package.name
    if isinstance(cache, dict):
        cache[cache_key] = tuple(packages)
    return packages


def package_description_path(root, name):
    package_dir = Path(root) / "packages"
    candidates = [package_dir / name / "package.yaml"]
    candidates.extend(package_dir / group / name / "package.yaml" for group in sorted(PACKAGE_GROUP_DIRECTORIES))
    found = [path for path in candidates if path.is_file()]
    legacy_path = package_dir / f"{name}.yaml"
    if legacy_path.is_file():
        found.append(legacy_path)
    if len(found) > 1:
        listed = ", ".join(path.as_posix() for path in found)
        raise SmartBuildError("PACKAGE", f"duplicate package description for {name}: {listed}")
    if found:
        return found[0]
    return candidates[0]


def package_description_paths(root):
    package_dir = Path(root) / "packages"
    if not package_dir.is_dir():
        return ()
    paths = [
        path
        for path in package_dir.glob("*/package.yaml")
        if path.parent.is_dir() and path.parent.name not in PACKAGE_GROUP_DIRECTORIES
    ]
    for group in sorted(PACKAGE_GROUP_DIRECTORIES):
        group_dir = package_dir / group
        if not group_dir.is_dir():
            continue
        paths.extend(path for path in group_dir.glob("*/package.yaml") if path.parent.is_dir())
    paths.extend(package_dir.glob("*.yaml"))
    return tuple(sorted(paths))


def package_kconfig_relative(root, metadata):
    root_path = Path(root).resolve()
    kconfig_path = Path(metadata.path).parent / metadata.kconfig.source
    try:
        return kconfig_path.resolve(strict=False).relative_to(root_path).as_posix()
    except ValueError as exc:
        raise SmartBuildError(
            "PACKAGE",
            f"{metadata.path}: Kconfig path escapes project: {kconfig_path}",
        ) from exc


def is_host_package_path(path, root=None):
    candidate = Path(path)
    parts = candidate.parts
    if "packages" not in parts:
        return False
    index = parts.index("packages")
    return index + 1 < len(parts) and parts[index + 1] == "host"


def is_ros2_package_path(path):
    candidate = Path(path)
    parts = candidate.parts
    if "packages" not in parts:
        return False
    index = parts.index("packages")
    return index + 1 < len(parts) and parts[index + 1] == "ros2"


def package_symbol(name):
    return f"PACKAGE_{symbol_token(name)}"


def package_selection_symbol(metadata):
    return metadata.kconfig.symbol


def package_version_symbol(name, version):
    return f"{package_symbol(name)}_VERSION_{symbol_token(version)}"


def package_option_symbol(package_name, option_name):
    return f"{package_symbol(package_name)}_OPTION_{symbol_token(option_name)}"


def package_option_choice_symbol(package_name, option_name, choice):
    return f"{package_option_symbol(package_name, option_name)}_{symbol_token(choice)}"


def symbol_token(value):
    token = []
    previous_underscore = False
    for char in str(value).upper():
        if char.isalnum():
            token.append(char)
            previous_underscore = False
        elif not previous_underscore:
            token.append("_")
            previous_underscore = True
    result = "".join(token).strip("_")
    if not result:
        raise SmartBuildError("PACKAGE", f"cannot build Kconfig symbol from {value!r}")
    return result


def _versions(description):
    raw_versions = description.data.get("versions")
    if raw_versions is None:
        return (description.version,)
    return _non_empty_string_tuple(description, raw_versions, "versions")


def _kconfig(description, options, versions):
    raw = description.data.get("kconfig")
    if raw is None:
        return PackageKconfig(
            mode="generated",
            source="Kconfig",
            symbol=package_symbol(description.name),
            path=description.path.parent / "Kconfig",
        )
    if not isinstance(raw, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: kconfig must be a mapping")
    unsupported = sorted(set(raw) - {"mode", "source", "symbol"})
    if unsupported:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: unsupported kconfig field(s): {', '.join(unsupported)}",
        )
    if raw.get("mode") != "native":
        raise SmartBuildError("PACKAGE", f"{description.path}: kconfig.mode must be native")
    build = description.data.get("build")
    if not isinstance(build, dict) or "rtthread_scons" not in build:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: native Kconfig is supported only by build.rtthread_scons",
        )
    source = raw.get("source")
    if source != "source/Kconfig":
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: native kconfig.source must be source/Kconfig",
        )
    symbol = raw.get("symbol")
    if not isinstance(symbol, str) or not KCONFIG_SYMBOL_RE.fullmatch(symbol):
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: kconfig.symbol must be a valid Kconfig symbol",
        )
    if options:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: native Kconfig packages must not declare package.yaml options",
        )
    if len(versions) != 1:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: native Kconfig packages support one package version",
        )
    relative = PurePosixPath(source)
    path = description.path.parent.joinpath(*relative.parts)
    package_dir = description.path.parent.resolve()
    if path.is_symlink():
        raise SmartBuildError("PACKAGE", f"{description.path}: refusing symlink native Kconfig: {path}")
    try:
        path.resolve(strict=False).relative_to(package_dir)
    except ValueError as exc:
        raise SmartBuildError("PACKAGE", f"{description.path}: native Kconfig escapes package directory") from exc
    if not path.is_file():
        raise SmartBuildError("PACKAGE", f"{description.path}: native Kconfig not found: {path}")
    return PackageKconfig(mode="native", source=source, symbol=symbol, path=path)


def _category(description):
    raw = description.data.get("category")
    if raw is None:
        return ""
    if not isinstance(raw, str) or not raw.strip():
        raise SmartBuildError("PACKAGE", f"{description.path}: category must be a non-empty string")
    return raw.strip()


def shorten_package_description(text):
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= DESCRIPTION_MAX_LENGTH:
        return cleaned
    without_url = cleaned
    for marker in (" http://", " https://"):
        if marker in without_url:
            without_url = without_url.split(marker, 1)[0].strip()
    if without_url and len(without_url) <= DESCRIPTION_MAX_LENGTH:
        return without_url
    for separator in (". ", "; "):
        if separator in without_url:
            first = without_url.split(separator, 1)[0].strip()
            if first and len(first) <= DESCRIPTION_MAX_LENGTH:
                return first
    trimmed = without_url[:DESCRIPTION_MAX_LENGTH].rsplit(" ", 1)[0].rstrip(".,;:")
    return trimmed or without_url[:DESCRIPTION_MAX_LENGTH]


def _description(description):
    raw = description.data.get("description", "")
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise SmartBuildError("PACKAGE", f"{description.path}: description must be a string")
    text = " ".join(raw.split())
    if "description" in description.data and not text:
        raise SmartBuildError("PACKAGE", f"{description.path}: description must be a non-empty string")
    if len(text) > DESCRIPTION_MAX_LENGTH:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: description must be at most {DESCRIPTION_MAX_LENGTH} characters",
        )
    return text


def _default_version(description, versions):
    default = description.data.get("default_version", description.version)
    if not isinstance(default, str) or not default:
        raise SmartBuildError("PACKAGE", f"{description.path}: default_version must be a non-empty string")
    if default not in versions:
        raise SmartBuildError("PACKAGE", f"{description.path}: default_version must be one of versions")
    return default


def _options(description):
    raw_options = description.data.get("options", {})
    if not isinstance(raw_options, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: options must be a mapping")

    options = []
    for name, option in raw_options.items():
        if not isinstance(name, str) or not name:
            raise SmartBuildError("PACKAGE", f"{description.path}: option names must be non-empty strings")
        if not isinstance(option, dict):
            raise SmartBuildError("PACKAGE", f"{description.path}: option {name} must be a mapping")
        option_type = option.get("type")
        if option_type not in OPTION_TYPES:
            raise SmartBuildError("PACKAGE", f"{description.path}: option {name} type must be bool, choice, or string")
        prompt = option.get("prompt", name)
        if not isinstance(prompt, str) or not prompt:
            raise SmartBuildError("PACKAGE", f"{description.path}: option {name} prompt must be a non-empty string")
        choices = ()
        if option_type == "bool":
            default = option.get("default", False)
            if not isinstance(default, bool):
                raise SmartBuildError("PACKAGE", f"{description.path}: option {name} default must be a bool")
        elif option_type == "choice":
            choices = _choice_values(description, name, option.get("choices"))
            default = option.get("default", choices[0])
            if not isinstance(default, str) or default not in choices:
                raise SmartBuildError("PACKAGE", f"{description.path}: option {name} default must be one of choices")
        else:
            default = option.get("default", "")
            if not isinstance(default, str):
                raise SmartBuildError("PACKAGE", f"{description.path}: option {name} default must be a string")
        options.append(
            PackageOption(
                name=name,
                type=option_type,
                prompt=prompt,
                default=default,
                choices=choices,
            )
        )
    return tuple(options)


def _choice_values(description, option_name, values):
    choices = _non_empty_string_tuple(description, values, f"option {option_name} choices")
    if len(choices) < 2:
        raise SmartBuildError(f"PACKAGE", f"{description.path}: option {option_name} choices must contain at least two entries")
    return choices


def _relation_list(description, field):
    value = description.data.get(field, [])
    if isinstance(value, str):
        if field in {"depends", "host_depends"}:
            return tuple(item.strip() for item in value.split(",") if item.strip())
        raise SmartBuildError("PACKAGE", f"{description.path}: {field} must be a list")
    return _string_tuple(description, value, field)


def _non_empty_string_tuple(description, value, label):
    result = _string_tuple(description, value, label)
    if not result:
        raise SmartBuildError("PACKAGE", f"{description.path}: {label} must be a non-empty list")
    return result


def _string_tuple(description, value, label):
    if not isinstance(value, list):
        raise SmartBuildError("PACKAGE", f"{description.path}: {label} must be a list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise SmartBuildError("PACKAGE", f"{description.path}: {label} entries must be non-empty strings")
        result.append(item)
    return tuple(result)
