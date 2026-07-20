from dataclasses import dataclass
from pathlib import Path

from .descriptions import load_description
from .errors import SmartBuildError
from .paths import board_description_path, board_dir, validate_safe_name


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

    return Machine(
        name=machine_name,
        arch=_required_string(board_path, data, "arch"),
        bsp=_required_string(board_path, data, "bsp"),
        kernel_defconfig=_kernel_defconfig_path(owner_dir, board_path, data),
        toolchain_package=_required_string(board_path, toolchain, "toolchain.package"),
        target_triple=_required_string(board_path, toolchain, "toolchain.target"),
        prefix=_required_string(board_path, toolchain, "toolchain.prefix"),
        loader=loader,
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
