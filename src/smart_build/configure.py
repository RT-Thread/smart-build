import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .descriptions import load_description
from .errors import SmartBuildError
from .machines import load_machine
from .paths import board_description_path, board_dir, validate_safe_name


CONFIGURATION_FIELDS = frozenset(("command", "workdir", "env", "sync"))
PACKAGE_WORKDIRS = frozenset(("source", "package", "build"))
PROTECTED_ENV = frozenset(
    (
        "AR",
        "AS",
        "CC",
        "CROSS_COMPILE",
        "CXX",
        "LD",
        "MACHINE",
        "NM",
        "OBJCOPY",
        "PATH",
        "RANLIB",
        "READELF",
        "RTT_CC",
        "RTT_CC_PREFIX",
        "RTT_EXEC_PATH",
        "STRIP",
    )
)


@dataclass(frozen=True)
class ConfigurationSync:
    source: Path
    destination: Path


@dataclass(frozen=True)
class ConfigurationSpec:
    target: str
    command: tuple
    workdir: Path
    env: dict
    sync: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "command", tuple(str(part) for part in self.command))
        object.__setattr__(self, "workdir", Path(self.workdir))
        object.__setattr__(self, "env", {key: str(value) for key, value in self.env.items()})
        object.__setattr__(self, "sync", tuple(self.sync))


@dataclass(frozen=True)
class ConfigurationResult:
    target: str
    updated: tuple


def configure_target(paths, target, toolchain=None, command_runner=None):
    target_name = str(target).strip()
    if target_name == "kernel":
        from .domains.kernel import kernel_configuration

        return kernel_configuration(paths, toolchain=toolchain, command_runner=command_runner)
    if target_name == "busybox":
        from .domains.busybox import busybox_configuration

        return busybox_configuration(paths, toolchain=toolchain, command_runner=command_runner)
    if target_name == "bootloader":
        return _board_configuration(
            paths,
            "bootloader",
            toolchain=toolchain,
            command_runner=command_runner,
        )
    if target_name.startswith("package:") and target_name != "package:":
        from .domains.package import package_configuration

        package_name = validate_safe_name(target_name.split(":", 1)[1], "package")
        return package_configuration(
            paths,
            package_name,
            toolchain=toolchain,
            command_runner=command_runner,
        )
    raise SmartBuildError(
        "CONFIG",
        "unsupported configure target {target!r}; expected kernel, busybox, "
        "bootloader, or package:<name>".format(target=target_name),
    )


def execute_configuration(spec, command_runner=None):
    _require_directory(spec.workdir, f"configuration workdir for {spec.target}")
    for item in spec.sync:
        _seed_configuration(item, spec.target)

    runner = command_runner or _run_interactive_command
    env = os.environ.copy()
    env.update(spec.env)
    try:
        completed = runner(list(spec.command), cwd=spec.workdir, env=env)
    except OSError as exc:
        raise SmartBuildError(
            "BUILD",
            f"failed to run configuration command for {spec.target}: {exc}",
        ) from exc
    if completed.returncode != 0:
        raise SmartBuildError(
            "BUILD",
            "configuration command failed for {target}: command={command} "
            "workdir={workdir} exit code {exit_code}".format(
                target=spec.target,
                command=" ".join(spec.command),
                workdir=spec.workdir,
                exit_code=completed.returncode,
            ),
        )

    for item in spec.sync:
        _require_regular_file(item.source, f"generated configuration for {spec.target}")
    for item in spec.sync:
        _atomic_copy(item.source, item.destination, spec.target)
    return ConfigurationResult(spec.target, tuple(item.destination for item in spec.sync))


def configuration_spec_from_mapping(
    target,
    mapping,
    workdir,
    source_root,
    destination_root,
    base_env=None,
    label="configure",
):
    config = _configuration_mapping(mapping, label)
    command = _configuration_command(config, label)
    env = dict(base_env or {})
    env.update(_configuration_env(config, env, label))
    sync = configuration_sync_paths(
        config,
        source_root,
        destination_root,
        label=label,
    )
    return ConfigurationSpec(
        target=target,
        command=command,
        workdir=workdir,
        env=env,
        sync=sync,
    )


def package_configuration_workdir(mapping, source_dir, package_dir, build_dir, label):
    config = _configuration_mapping(mapping, label)
    value = config.get("workdir", "source")
    if value not in PACKAGE_WORKDIRS:
        raise SmartBuildError(
            "CONFIG",
            f"{label}.workdir must be source, package, or build",
        )
    return {
        "source": Path(source_dir),
        "package": Path(package_dir),
        "build": Path(build_dir),
    }[value]


def validate_configuration_mapping(mapping, source_root, destination_root, label="configure"):
    config = _configuration_mapping(mapping, label)
    _configuration_command(config, label)
    _configuration_env(config, {}, label)
    configuration_sync_paths(config, source_root, destination_root, label=label)


def configuration_sync_paths(mapping, source_root, destination_root, label="configure"):
    config = _configuration_mapping(mapping, label)
    raw_sync = config.get("sync", [])
    if raw_sync is None:
        raw_sync = []
    if not isinstance(raw_sync, list):
        raise SmartBuildError("CONFIG", f"{label}.sync must be a list")

    result = []
    destinations = set()
    for index, item in enumerate(raw_sync):
        item_label = f"{label}.sync[{index}]"
        if not isinstance(item, dict) or set(item) != {"source", "destination"}:
            raise SmartBuildError(
                "CONFIG",
                f"{item_label} must contain only source and destination",
            )
        source = _owned_path(source_root, item.get("source"), f"{item_label}.source")
        destination = _owned_path(
            destination_root,
            item.get("destination"),
            f"{item_label}.destination",
        )
        if destination in destinations:
            raise SmartBuildError("CONFIG", f"{label}.sync has duplicate destination: {destination}")
        destinations.add(destination)
        result.append(ConfigurationSync(source=source, destination=destination))
    return tuple(result)


def restore_configuration_sync(mapping, source_root, destination_root, label="configure"):
    if mapping is None:
        return ()
    restored = []
    for item in configuration_sync_paths(mapping, source_root, destination_root, label=label):
        if not item.destination.exists() and not item.destination.is_symlink():
            continue
        _require_regular_file(item.destination, f"saved configuration for {label}")
        _copy_file(item.destination, item.source, label)
        restored.append(item.source)
    return tuple(restored)


def toolchain_configuration_env(paths, toolchain, **values):
    if hasattr(toolchain, "compile_env"):
        env = toolchain.compile_env()
        env["MACHINE"] = paths.machine
    else:
        env = {"MACHINE": paths.machine}
    env = {key: str(value) for key, value in env.items()}
    env.update(
        {
            "SMART_BUILD_MACHINE": paths.machine,
            "SMART_BUILD_TARGET": str(toolchain.target),
            "SMART_BUILD_TOOLCHAIN_ROOT": str(toolchain.root),
            "SMART_BUILD_TOOLCHAIN_BIN": str(toolchain.bin_dir),
            "SMART_BUILD_CROSS_COMPILE": str(toolchain.prefix),
            "CROSS_COMPILE": str(toolchain.prefix),
        }
    )
    tools = {
        "CC": "gcc",
        "CXX": "g++",
        "LD": "ld",
        "NM": "nm",
        "AS": "as",
        "AR": "ar",
        "RANLIB": "ranlib",
        "STRIP": "strip",
        "OBJCOPY": "objcopy",
        "READELF": "readelf",
    }
    for variable, executable in tools.items():
        value = getattr(toolchain, variable.lower(), None)
        env[variable] = str(value or (Path(toolchain.bin_dir) / f"{toolchain.prefix}{executable}"))
    env.update({key: str(value) for key, value in values.items()})
    return env


def _board_configuration(paths, name, toolchain=None, command_runner=None):
    description_path = board_description_path(paths.root, paths.machine)
    description = load_description(description_path)
    if description.kind != "board" or description.name != paths.machine:
        raise SmartBuildError(
            "CONFIG",
            f"{description_path}: expected board description for {paths.machine}",
        )
    configurations = description.data.get("configurations", {})
    if not isinstance(configurations, dict):
        raise SmartBuildError("CONFIG", f"{description_path}: configurations must be a mapping")
    mapping = configurations.get(name)
    if mapping is None:
        raise SmartBuildError(
            "CONFIG",
            f"{description_path}: no {name} configuration provider declared",
        )
    config = _configuration_mapping(mapping, f"{description_path}: configurations.{name}")
    raw_workdir = config.get("workdir")
    workdir = _owned_path(paths.root, raw_workdir, f"{description_path}: configurations.{name}.workdir")
    validate_configuration_mapping(
        config,
        workdir,
        board_dir(paths.root, paths.machine),
        label=f"{description_path}: configurations.{name}",
    )
    resolved_toolchain = toolchain
    if resolved_toolchain is None:
        from .domains.toolchain import resolve_toolchain

        resolved_toolchain = resolve_toolchain(machine=load_machine(paths.root, paths.machine))
    env = toolchain_configuration_env(
        paths,
        resolved_toolchain,
        SMART_BUILD_WORK_DIR=paths.work_dir / "configure" / name,
        SMART_BUILD_SOURCE_DIR=workdir,
        SMART_BUILD_BOARD_DIR=board_dir(paths.root, paths.machine),
    )
    spec = configuration_spec_from_mapping(
        name,
        config,
        workdir,
        source_root=workdir,
        destination_root=board_dir(paths.root, paths.machine),
        base_env=env,
        label=f"{description_path}: configurations.{name}",
    )
    return execute_configuration(spec, command_runner=command_runner)


def _configuration_mapping(mapping, label):
    if not isinstance(mapping, dict):
        raise SmartBuildError("CONFIG", f"{label} must be a mapping")
    unsupported = sorted(set(mapping) - CONFIGURATION_FIELDS)
    if unsupported:
        raise SmartBuildError(
            "CONFIG",
            f"{label} has unsupported field(s): {', '.join(unsupported)}",
        )
    return mapping


def _configuration_command(mapping, label):
    command = mapping.get("command")
    if not isinstance(command, list) or not command:
        raise SmartBuildError("CONFIG", f"{label}.command must be a non-empty string list")
    if any(not isinstance(part, str) or not part for part in command):
        raise SmartBuildError("CONFIG", f"{label}.command entries must be non-empty strings")
    return tuple(command)


def _configuration_env(mapping, base_env, label):
    raw_env = mapping.get("env", {})
    if not isinstance(raw_env, dict):
        raise SmartBuildError("CONFIG", f"{label}.env must be a mapping")
    result = {}
    for key, value in raw_env.items():
        if not isinstance(key, str) or not key:
            raise SmartBuildError("CONFIG", f"{label}.env keys must be non-empty strings")
        if key.startswith("SMART_BUILD_") or key in PROTECTED_ENV or key in base_env:
            raise SmartBuildError("CONFIG", f"{label}.env must not override protected variable {key}")
        if not isinstance(value, (str, int, float, bool)):
            raise SmartBuildError("CONFIG", f"{label}.env values must be scalar")
        result[key] = str(value)
    return result


def _owned_path(root, raw_path, label):
    if not isinstance(raw_path, str) or not raw_path:
        raise SmartBuildError("CONFIG", f"{label} must be a non-empty relative path")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or "\\" in raw_path:
        raise SmartBuildError("CONFIG", f"{label} must be a safe relative path: {raw_path}")
    parts = tuple(part for part in relative.parts if part != ".")
    if not parts or any(part in {"", ".."} for part in parts):
        raise SmartBuildError("CONFIG", f"{label} must be a safe relative path: {raw_path}")
    owner = Path(root).resolve()
    candidate = Path(root).joinpath(*parts)
    try:
        candidate.resolve(strict=False).relative_to(owner)
    except ValueError as exc:
        raise SmartBuildError("CONFIG", f"{label} escapes owner directory: {raw_path}") from exc
    return candidate


def _seed_configuration(item, target):
    if not item.destination.exists() and not item.destination.is_symlink():
        return
    _require_regular_file(item.destination, f"saved configuration for {target}")
    _copy_file(item.destination, item.source, target)


def _copy_file(source, destination, target):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise SmartBuildError("CONFIG", f"refusing symlink configuration path for {target}: {destination}")
    if destination.exists() and not destination.is_file():
        raise SmartBuildError("CONFIG", f"refusing non-file configuration path for {target}: {destination}")
    shutil.copy2(source, destination)


def _atomic_copy(source, destination, target):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise SmartBuildError("CONFIG", f"refusing symlink configuration path for {target}: {destination}")
    if destination.exists():
        _require_regular_file(destination, f"saved configuration for {target}")

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    except OSError as exc:
        raise SmartBuildError(
            "CONFIG",
            f"failed to save configuration for {target}: {source} -> {destination}: {exc}",
        ) from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _require_directory(path, label):
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_dir():
        raise SmartBuildError("CONFIG", f"{label} not found or unsafe: {candidate}")


def _require_regular_file(path, label):
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.exists():
        raise SmartBuildError("CONFIG", f"{label} not found or unsafe: {candidate}")
    file_stat = candidate.stat()
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise SmartBuildError("CONFIG", f"{label} must be a single-link regular file: {candidate}")


def _run_interactive_command(command, cwd, env):
    return subprocess.run(command, cwd=cwd, env=env, check=False)
