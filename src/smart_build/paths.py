from dataclasses import dataclass
from pathlib import Path

from .errors import SmartBuildError


def project_root():
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "smart-build").is_file():
            return candidate
    raise SmartBuildError("CONFIG", f"failed to locate smart-build project root from {__file__}")


@dataclass(frozen=True)
class BuildPaths:
    root: Path
    machine: str
    machine_dir: Path
    work_dir: Path
    staging_dir: Path
    images_dir: Path
    packages_dir: Path
    logs_dir: Path
    stamps_dir: Path
    manifest_path: Path

    @classmethod
    def for_machine(cls, machine, root=None):
        machine_name = _validate_machine(machine)
        root_path = Path(root) if root is not None else project_root()
        machine_dir = root_path / "build" / machine_name
        return cls(
            root=root_path,
            machine=machine_name,
            machine_dir=machine_dir,
            work_dir=machine_dir / "work",
            staging_dir=machine_dir / "staging",
            images_dir=machine_dir / "images",
            packages_dir=machine_dir / "packages",
            logs_dir=machine_dir / "logs",
            stamps_dir=machine_dir / "stamps",
            manifest_path=machine_dir / "manifest.yaml",
        )

    def ensure_execution_dirs(self):
        for directory in (
            self.work_dir,
            self.staging_dir,
            self.images_dir,
            self.packages_dir,
            self.logs_dir,
            self.stamps_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def display_path(self, path):
        candidate = Path(path)
        try:
            return candidate.relative_to(self.root).as_posix()
        except ValueError:
            return str(candidate)


def board_dir(root, machine):
    machine_name = validate_safe_name(machine, "machine")
    return Path(root) / "boards" / machine_name


def board_description_path(root, machine):
    return board_dir(root, machine) / "board.yaml"


def board_defconfig_path(root, machine):
    return board_dir(root, machine) / "defconfig"


def board_kernel_overlay_dir(root, machine):
    return board_dir(root, machine) / "kernel-overlay"


def rootfs_dir(root, rootfs):
    rootfs_name = validate_safe_name(rootfs, "rootfs")
    return Path(root) / "rootfs" / rootfs_name


def rootfs_description_path(root, rootfs):
    return rootfs_dir(root, rootfs) / "rootfs.yaml"


def _validate_machine(machine):
    return validate_safe_name(machine, "machine")


def validate_safe_name(value, label):
    if not isinstance(value, str):
        raise SmartBuildError("CONFIG", f"{label} must be a non-empty string")
    name = value.strip()
    if not name:
        raise SmartBuildError("CONFIG", f"{label} must be a non-empty string")
    candidate = Path(name)
    if candidate.is_absolute() or len(candidate.parts) != 1 or name in {".", ".."}:
        raise SmartBuildError("CONFIG", f"unsafe {label} name: {value}")
    if "/" in name or "\\" in name or ".." in candidate.parts:
        raise SmartBuildError("CONFIG", f"unsafe {label} name: {value}")
    return name
