from dataclasses import dataclass

from .errors import SmartBuildError
from .package_metadata import (
    PackageMetadata,
    load_all_package_metadata,
    package_option_symbol,
    package_symbol,
)


@dataclass(frozen=True)
class ResolvedPackage:
    name: str
    version: str
    options: dict
    metadata: PackageMetadata


@dataclass(frozen=True)
class PackageSelection:
    packages: tuple[ResolvedPackage, ...]
    by_name: dict

    @property
    def package_names(self):
        return [package.name for package in self.packages]


def resolve_package_selection(root, package_names, values):
    metadata = {package.name: package for package in load_all_package_metadata(root)}
    providers = _provider_map(metadata.values())
    selected = []
    selected_names = set()
    package_requirements = {}

    def include(raw_name, required_version=None, required=False):
        provider = _resolve_provider(raw_name, metadata, providers)
        if provider is None:
            if required:
                raise SmartBuildError("PACKAGE", f"selected package not found: {raw_name}")
            return
        _record_version_requirement(package_requirements, provider, required_version)
        if provider in selected_names:
            return
        selected_names.add(provider)
        selected.append(provider)
        package = metadata[provider]
        for dependency in package.depends:
            include(dependency, _required_version(values, dependency))
        for selected_dependency in package.selects:
            include(selected_dependency, _required_version(values, selected_dependency), required=True)

    for package_name in package_names:
        include(package_name, _required_version(values, package_name), required=True)

    _reject_conflicts(selected, metadata)
    resolved = tuple(
        ResolvedPackage(
            name=name,
            version=_selected_version(metadata[name], values, package_requirements.get(name)),
            options=_selected_options(metadata[name], values),
            metadata=metadata[name],
        )
        for name in selected
    )
    return PackageSelection(packages=resolved, by_name={package.name: package for package in resolved})


def _provider_map(packages):
    providers = {}
    for package in packages:
        for provided in package.provides:
            providers.setdefault(provided, package.name)
    return providers


def _resolve_provider(name, metadata, providers):
    if name in metadata:
        return name
    return providers.get(name)


def _record_version_requirement(requirements, package_name, required_version):
    if required_version is None:
        return
    existing = requirements.get(package_name)
    if existing is not None and existing != required_version:
        raise SmartBuildError(
            "PACKAGE",
            f"version conflict for {package_name}: {existing} vs {required_version}",
        )
    requirements[package_name] = required_version


def _required_version(values, package_name):
    return values.get(f"{package_symbol(package_name)}_REQUIRE_VERSION")


def _selected_version(metadata, values, required_version):
    symbol = f"{package_symbol(metadata.name)}_VERSION"
    version = values.get(symbol, required_version or metadata.default_version)
    if required_version is not None and version != required_version:
        raise SmartBuildError(
            "PACKAGE",
            f"version conflict for {metadata.name}: selected {version} but required {required_version}",
        )
    if version not in metadata.versions:
        raise SmartBuildError("PACKAGE", f"{metadata.name}: unsupported version {version}")
    return version


def _selected_options(metadata, values):
    result = {}
    for option in metadata.options:
        symbol = package_option_symbol(metadata.name, option.name)
        raw_value = values.get(symbol)
        if option.type == "bool":
            result[option.name] = _bool_value(raw_value, option.default)
        elif option.type == "choice":
            value = raw_value if raw_value is not None else option.default
            if value not in option.choices:
                raise SmartBuildError("PACKAGE", f"{metadata.name}: option {option.name} unsupported value {value}")
            result[option.name] = value
        else:
            result[option.name] = raw_value if raw_value is not None else option.default
    return result


def _bool_value(value, default):
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"y", "yes", "true", "1"}


def _reject_conflicts(selected, metadata):
    selected_set = set(selected)
    for name in selected:
        package = metadata[name]
        for conflict in package.conflicts:
            conflict_name = conflict if conflict in metadata else None
            if conflict_name is None:
                continue
            if conflict_name in selected_set:
                raise SmartBuildError("PACKAGE", f"package conflict: {name} conflicts with {conflict_name}")
