import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import load_defconfig
from .errors import SmartBuildError


@dataclass(frozen=True)
class EnvPackages:
    env_root: Path
    command: Path
    index: Path

    @classmethod
    def discover(cls, home=None):
        root = Path(home) / ".env" if home is not None else Path.home() / ".env"
        return cls(
            env_root=root,
            command=root / "tools" / "scripts" / "pkgs",
            index=root / "packages" / "packages",
        )

    def validate(self):
        if not self.command.is_file() or not os.access(self.command, os.X_OK):
            raise SmartBuildError(
                "CONFIG",
                f"RT-Thread Env package command is not executable: {self.command}",
            )
        index_kconfig = self.index / "Kconfig"
        if not index_kconfig.is_file():
            raise SmartBuildError(
                "CONFIG",
                f"RT-Thread Env package index is missing Kconfig: {index_kconfig}",
            )
        return self

    def environment(self, base=None):
        env = os.environ.copy() if base is None else dict(base)
        scripts = str(self.command.parent)
        current_path = env.get("PATH", "")
        env.update(
            {
                "ENV_ROOT": str(self.env_root),
                "PKGS_ROOT": str(self.index.parent),
                "PKGS_DIR": str(self.index.parent),
                "PATH": scripts if not current_path else f"{scripts}{os.pathsep}{current_path}",
            }
        )
        return env

    def manifest_record(self):
        return {
            "command": str(self.command),
            "index": str(self.index),
            "index_revision": _git_output(self.index, "rev-parse", "HEAD"),
            "index_dirty": bool(_git_output(self.index, "status", "--porcelain") or ""),
        }


def validate_package_update_output(completed):
    output = completed.stdout or ""
    if "Operation completed successfully." not in output:
        raise SmartBuildError(
            "BUILD",
            "RT-Thread Env package update did not report success; "
            "review the package log and packages/pkgs_error.json",
        )


def read_recorded_env_package_paths(project_dir, state_label="package", missing_ok=False):
    project = Path(project_dir)
    packages_dir = project / "packages"
    state_path = packages_dir / "pkgs.json"
    if missing_ok and not state_path.exists():
        return ()
    state = _read_json_list(state_path, f"{state_label} state")
    paths = []
    for item in state:
        _name, _index_path, _version, managed_path = _env_package_state_entry(
            item,
            packages_dir,
            state_path,
            state_label,
        )
        paths.append(managed_path)
    return tuple(sorted(paths, key=str))


def read_env_package_state(project_dir, config_path=None, state_label="package", config_label="project .config"):
    project = Path(project_dir)
    packages_dir = project / "packages"
    selected_config = Path(config_path) if config_path is not None else project / ".config"
    state_path = packages_dir / "pkgs.json"
    error_path = packages_dir / "pkgs_error.json"
    state = _read_json_list(state_path, f"{state_label} state")
    errors = _read_json_list(error_path, f"{state_label} errors")
    if errors:
        names = ", ".join(
            str(item.get("name", item)) if isinstance(item, dict) else str(item)
            for item in errors
        )
        raise SmartBuildError("BUILD", f"RT-Thread Env package update reported errors: {names}")
    if not (packages_dir / "SConscript").is_file():
        raise SmartBuildError(
            "BUILD",
            f"RT-Thread Env package update did not create {packages_dir / 'SConscript'}",
        )

    result = []
    actual = []
    for item in state:
        name, index_path, version, managed_path = _env_package_state_entry(
            item,
            packages_dir,
            state_path,
            state_label,
        )
        actual.append((name, index_path, version))
        if managed_path.is_symlink() or not managed_path.is_dir():
            raise SmartBuildError(
                "BUILD",
                "RT-Thread Env package is not installed at its managed path: "
                f"{name} version={version} path={managed_path}",
            )
        result.append(
            {
                "name": name,
                "version": version,
                "index_path": index_path,
                "installed_path": str(managed_path),
                "managed_by_env": True,
            }
        )

    expected = _configured_packages(selected_config)
    if sorted(actual) != expected:
        raise SmartBuildError(
            "BUILD",
            f"RT-Thread Env {state_label} state does not match {config_label}: "
            f"expected={expected!r} actual={sorted(actual)!r}",
        )
    return sorted(result, key=lambda item: item["name"])


def _env_package_state_entry(item, packages_dir, state_path, state_label):
    if not isinstance(item, dict):
        raise SmartBuildError("BUILD", f"invalid {state_label} state entry in {state_path}: {item!r}")
    name = item.get("name")
    version = item.get("ver")
    index_path = item.get("path")
    if not all(isinstance(value, str) and value for value in (name, version, index_path)):
        raise SmartBuildError("BUILD", f"incomplete {state_label} state entry in {state_path}: {item!r}")
    package_name = _package_index_name(index_path, state_path)
    _validate_package_version(version, state_path)
    return name, index_path, version, packages_dir / f"{package_name}-{version}"


def _git_output(path, *args):
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _configured_packages(config_path):
    values = load_defconfig(config_path)
    prefix = "CONFIG_PKG_"
    suffix = "_PATH"
    result = []
    for key, index_path in values.items():
        if not key.startswith(prefix) or not key.endswith(suffix) or index_path == "n":
            continue
        name = key[len(prefix) : -len(suffix)]
        version = values.get(f"{prefix}{name}_VER")
        if not name or not version or version == "n":
            raise SmartBuildError(
                "CONFIG",
                f"RT-Thread Env package {name or key} has a path but no version in {config_path}",
            )
        result.append((name, index_path, version))
    return sorted(result)


def _package_index_name(index_path, state_path):
    normalized = index_path.replace("\\", "/")
    path = PurePosixPath(normalized)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SmartBuildError(
            "BUILD",
            f"unsafe RT-Thread Env package index path in {state_path}: {index_path!r}",
        )
    return parts[-1]


def _validate_package_version(version, state_path):
    if version in {"", ".", ".."} or "/" in version or "\\" in version:
        raise SmartBuildError(
            "BUILD",
            f"unsafe RT-Thread Env package version in {state_path}: {version!r}",
        )


def _read_json_list(path, label):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmartBuildError("BUILD", f"failed to read {label} {path}: {exc}") from exc
    if not isinstance(value, list):
        raise SmartBuildError("BUILD", f"{label} must be a list: {path}")
    return value
