from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import SmartBuildError


SUPPORTED_SCHEMA_VERSION = 1
REQUIRED_FIELDS = ("schema_version", "kind", "name", "version")
SUPPORTED_KINDS = frozenset(("board", "component", "package", "rootfs", "image"))


@dataclass(frozen=True)
class Description:
    path: Path
    schema_version: int
    kind: str
    name: str
    version: str
    data: dict


def load_description(path):
    description_path = Path(path)
    try:
        data = yaml.safe_load(description_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SmartBuildError("SCHEMA", f"invalid YAML in {description_path}: {exc}") from exc
    except OSError as exc:
        raise SmartBuildError("SCHEMA", f"failed to read {description_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SmartBuildError("SCHEMA", f"{description_path}: description must be a mapping")

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        fields = ", ".join(missing)
        raise SmartBuildError("SCHEMA", f"{description_path}: missing required field(s): {fields}")

    schema_version = data["schema_version"]
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise SmartBuildError(
            "SCHEMA",
            f"{description_path}: unsupported schema_version {schema_version}; "
            f"supported: {SUPPORTED_SCHEMA_VERSION}",
        )

    kind = _required_string(description_path, data, "kind")
    name = _required_string(description_path, data, "name")
    version = _required_string(description_path, data, "version")
    _optional_string(description_path, data, "extension")
    if kind not in SUPPORTED_KINDS:
        kinds = ", ".join(sorted(SUPPORTED_KINDS))
        raise SmartBuildError(
            "SCHEMA",
            f"{description_path}: unsupported kind {kind!r}; supported: {kinds}",
        )

    return Description(
        path=description_path,
        schema_version=schema_version,
        kind=kind,
        name=name,
        version=version,
        data=data,
    )


def _required_string(path, data, field):
    value = data[field]
    if not isinstance(value, str) or not value:
        raise SmartBuildError("SCHEMA", f"{path}: {field} must be a non-empty string")
    return value


def _optional_string(path, data, field):
    if field not in data:
        return None
    value = data[field]
    if not isinstance(value, str) or not value:
        raise SmartBuildError("SCHEMA", f"{path}: {field} must be a non-empty string")
    return value
