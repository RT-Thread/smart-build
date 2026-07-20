"""Trusted package extension loading.

Package extensions are repository-local Python files executed as trusted build
code. smart-build hashes only the declared extension file and normalized delta
for cache keys and manifests. Ordinary Python helper imports are still trusted
code, but their contents are not discovered automatically and are not included
in the extension hash/cache key; after changing a helper, trigger a rebuild or
touch the declared extension file.
"""

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

from .errors import SmartBuildError


EXTENSION_ENTRYPOINT = "extend_package"
SUPPORTED_DELTA_FIELDS = frozenset(("depends", "env", "command", "install"))


@dataclass(frozen=True)
class PackageExtension:
    path: Path
    relative_path: str
    sha256: str
    delta: dict

    def manifest_record(self):
        return {
            "path": self.relative_path,
            "sha256": self.sha256,
            "delta": self.delta,
        }


def load_package_extension(root, description, context):
    raw_path = description.data.get("extension")
    if raw_path is None:
        return None
    extension_path = _resolve_extension_path(root, raw_path, description.path)
    delta = _load_trusted_delta(extension_path, context)
    return PackageExtension(
        path=extension_path,
        relative_path=extension_path.relative_to(Path(root).resolve()).as_posix(),
        sha256=_file_sha256(extension_path),
        delta=delta,
    )


def _resolve_extension_path(root, raw_path, description_path):
    if not isinstance(raw_path, str) or not raw_path:
        raise SmartBuildError("PACKAGE", f"{description_path}: extension must be a repository-local path")
    repository = Path(root).resolve()
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise SmartBuildError(
            "PACKAGE",
            f"{description_path}: extension must be a portable repository-local path: {raw_path}",
        )
    candidate = repository / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SmartBuildError("PACKAGE", f"{description_path}: extension not found: {raw_path}") from exc
    try:
        resolved.relative_to(repository)
    except ValueError as exc:
        raise SmartBuildError(
            "PACKAGE",
            f"{description_path}: extension path is outside repository: {raw_path}",
        ) from exc
    if not resolved.is_file():
        raise SmartBuildError("PACKAGE", f"{description_path}: extension is not a file: {raw_path}")
    return resolved


def _load_trusted_delta(extension_path, context):
    module_name = f"_smart_build_package_extension_{_file_sha256(extension_path)[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, extension_path)
    if spec is None or spec.loader is None:
        raise SmartBuildError("PACKAGE", f"{extension_path}: failed to load package extension")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SmartBuildError("PACKAGE", f"{extension_path}: package extension failed: {exc}") from exc
    entrypoint = getattr(module, EXTENSION_ENTRYPOINT, None)
    if not callable(entrypoint):
        raise SmartBuildError("PACKAGE", f"{extension_path}: missing callable {EXTENSION_ENTRYPOINT}")
    try:
        raw_delta = entrypoint(_normalize_json_like(context, extension_path, "context"))
    except SmartBuildError:
        raise
    except Exception as exc:
        raise SmartBuildError("PACKAGE", f"{extension_path}: package extension failed: {exc}") from exc
    delta = _normalize_json_like(raw_delta, extension_path, "delta")
    if not isinstance(delta, dict):
        raise SmartBuildError("PACKAGE", f"{extension_path}: extension delta must be a mapping")
    unsupported = sorted(set(delta) - SUPPORTED_DELTA_FIELDS)
    if unsupported:
        raise SmartBuildError(
            "PACKAGE",
            f"{extension_path}: unsupported extension delta field(s): {', '.join(unsupported)}",
        )
    _validate_delta_schema(delta, extension_path)
    return delta


def _normalize_json_like(value, extension_path, label):
    try:
        _validate_json_like(value)
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise SmartBuildError(
            "PACKAGE",
            f"{extension_path}: extension {label} must be JSON-like: {exc}",
        ) from exc


def _validate_json_like(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_like(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"mapping key must be a string: {key!r}")
            _validate_json_like(item)
        return
    raise TypeError(f"unsupported value {value!r}")


def _validate_delta_schema(delta, extension_path):
    depends = delta.get("depends")
    if depends is not None and not _is_string_or_string_list(depends):
        raise SmartBuildError("PACKAGE", f"{extension_path}: extension depends must be a string or list")

    env = delta.get("env")
    if env is not None:
        if not isinstance(env, dict):
            raise SmartBuildError("PACKAGE", f"{extension_path}: extension env must be a mapping")
        for key, value in env.items():
            if not isinstance(key, str) or not key:
                raise SmartBuildError("PACKAGE", f"{extension_path}: extension env keys must be strings")
            if not isinstance(value, (str, int, float, bool)):
                raise SmartBuildError("PACKAGE", f"{extension_path}: extension env values must be scalar")

    command = delta.get("command")
    if command is not None:
        if not isinstance(command, dict):
            raise SmartBuildError("PACKAGE", f"{extension_path}: extension command must be a mapping")
        unsupported = sorted(set(command) - {"prefix", "suffix"})
        if unsupported:
            raise SmartBuildError(
                "PACKAGE",
                f"{extension_path}: unsupported extension command field(s): {', '.join(unsupported)}",
            )
        for key in ("prefix", "suffix"):
            value = command.get(key)
            if value is not None and not _is_string_or_string_list(value):
                raise SmartBuildError(
                    "PACKAGE",
                    f"{extension_path}: extension command.{key} must be a string or list",
                )

    install = delta.get("install")
    if install is not None:
        if not isinstance(install, dict):
            raise SmartBuildError("PACKAGE", f"{extension_path}: extension install must be a mapping")
        unsupported = sorted(set(install) - {"path"})
        if unsupported:
            raise SmartBuildError(
                "PACKAGE",
                f"{extension_path}: unsupported extension install field(s): {', '.join(unsupported)}",
            )
        if "path" in install and not isinstance(install["path"], str):
            raise SmartBuildError("PACKAGE", f"{extension_path}: extension install.path must be a string")


def _is_string_or_string_list(value):
    if isinstance(value, str):
        return True
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
