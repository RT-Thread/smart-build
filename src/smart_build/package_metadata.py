from dataclasses import dataclass
from pathlib import Path

from .descriptions import load_description
from .errors import SmartBuildError


OPTION_TYPES = frozenset(("bool", "choice", "string"))
RELATION_FIELDS = ("depends", "selects", "conflicts", "provides", "requires_toolchain")


@dataclass(frozen=True)
class PackageOption:
    name: str
    type: str
    prompt: str
    default: object = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageMetadata:
    name: str
    version: str
    versions: tuple[str, ...]
    default_version: str
    options: tuple[PackageOption, ...]
    depends: tuple[str, ...]
    selects: tuple[str, ...]
    conflicts: tuple[str, ...]
    provides: tuple[str, ...]
    requires_toolchain: tuple[str, ...]


def normalize_package_metadata(description):
    if description.kind != "package":
        raise SmartBuildError("PACKAGE", f"{description.path}: expected package description")

    versions = _versions(description)
    default_version = _default_version(description, versions)
    provides = _relation_list(description, "provides")
    if description.name not in provides:
        provides = (description.name, *provides)

    return PackageMetadata(
        name=description.name,
        version=default_version,
        versions=versions,
        default_version=default_version,
        options=_options(description),
        depends=_relation_list(description, "depends"),
        selects=_relation_list(description, "selects"),
        conflicts=_relation_list(description, "conflicts"),
        provides=provides,
        requires_toolchain=_relation_list(description, "requires_toolchain"),
    )


def load_package_metadata(root, name):
    description = load_description(package_description_path(root, name))
    return normalize_package_metadata(description)


def load_all_package_metadata(root):
    package_dir = Path(root) / "packages"
    if not package_dir.is_dir():
        return []
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
    return [normalize_package_metadata(description) for description in descriptions]


def package_description_path(root, name):
    package_dir = Path(root) / "packages"
    directory_path = package_dir / name / "package.yaml"
    legacy_path = package_dir / f"{name}.yaml"
    if directory_path.is_file():
        if legacy_path.is_file():
            raise SmartBuildError(
                "PACKAGE",
                f"duplicate package description for {name}: {directory_path} and {legacy_path}",
            )
        return directory_path
    return legacy_path


def package_description_paths(root):
    package_dir = Path(root) / "packages"
    if not package_dir.is_dir():
        return ()
    paths = [
        path
        for path in package_dir.glob("*/package.yaml")
        if path.parent.is_dir()
    ]
    paths.extend(package_dir.glob("*.yaml"))
    return tuple(sorted(paths))


def package_symbol(name):
    return f"PACKAGE_{symbol_token(name)}"


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
        if field == "depends":
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
