import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_MACHINE
from .domains.toolchain import resolve_toolchain
from .errors import SmartBuildError
from .machines import Machine, load_machine
from .paths import project_root


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    detail: str
    path: str = None


def run_doctor(paths, machine=None):
    metadata = _resolve_machine_metadata(paths, machine)
    checks = [
        _check_python(),
        _check_host_tool(metadata.qemu_binary),
        _check_host_tool("scons"),
        _check_host_tool("make"),
        _check_host_tool("cmake"),
        _check_host_tool("mke2fs"),
    ]
    toolchain = resolve_toolchain(machine=metadata)
    checks.append(DoctorCheck("toolchain", str(toolchain.root)))
    checks.append(_check_rt_thread_bsp(paths, metadata))
    checks.append(_check_build_directory(paths))
    return checks


def toolchain_manifest_record(machine=None):
    return resolve_toolchain(machine=machine).manifest_record()


def host_tools_record(machine=None):
    metadata = _resolve_machine_metadata(None, machine)
    checks = [
        _check_python(),
        _check_host_tool(metadata.qemu_binary),
        _check_host_tool("scons"),
        _check_host_tool("make"),
        _check_host_tool("cmake"),
        _check_host_tool("mke2fs"),
    ]
    return host_tools_from_checks(checks)


def host_tools_from_checks(checks):
    records = {}
    for check in checks:
        if check.name == "python":
            records["python"] = check.path or sys.executable
        elif check.path:
            records[check.name] = check.path
    return records


def resolve_host_tool(name):
    return _check_host_tool(name).path


def _check_python():
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < (3, 10):
        raise SmartBuildError("CONFIG", f"Python 3.10 or newer is required, found {version}")
    return DoctorCheck("python", f"{sys.executable} ({version})", sys.executable)


def _check_host_tool(name):
    path = shutil.which(name)
    if path is None and name == "mke2fs":
        path = _find_absolute_tool(name, ("/usr/sbin", "/sbin"))
    if path is None:
        search = f"PATH={os.environ.get('PATH', '')}"
        if name == "mke2fs":
            search = f"{search}; extra search=/usr/sbin:/sbin"
        raise SmartBuildError("CONFIG", f"required host tool not found: {name} ({search})")
    return DoctorCheck(name, path, path)


def _find_absolute_tool(name, directories):
    for directory in directories:
        path = Path(directory) / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _check_rt_thread_bsp(paths, machine=None):
    metadata = _resolve_machine_metadata(paths, machine)
    bsp_path = paths.root / "rt-thread" / "bsp" / metadata.bsp
    if not bsp_path.is_dir():
        raise SmartBuildError("SOURCE", f"RT-Thread BSP path not found: {bsp_path}")
    if not (bsp_path / "SConstruct").is_file():
        raise SmartBuildError("SOURCE", f"RT-Thread BSP missing SConstruct: {bsp_path}")
    return DoctorCheck("rt-thread-bsp", str(bsp_path))


def _check_build_directory(paths):
    check_dir = _nearest_existing_directory(paths.machine_dir)
    if check_dir is None or not check_dir.is_dir():
        raise SmartBuildError("CONFIG", f"build directory parent does not exist: {paths.machine_dir}")
    if paths.machine_dir.exists() and not paths.machine_dir.is_dir():
        raise SmartBuildError("CONFIG", f"build directory exists but is not a directory: {paths.machine_dir}")
    if not os.access(check_dir, os.W_OK | os.X_OK):
        raise SmartBuildError("CONFIG", f"build directory location is not writable: {check_dir}")
    if paths.machine_dir.exists():
        detail = f"{paths.machine_dir}"
    else:
        detail = f"{paths.machine_dir} absent; writable parent {check_dir}"
    return DoctorCheck("build-directory", detail, str(check_dir))


def _nearest_existing_directory(path):
    candidate = Path(path)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate if candidate.exists() else None


def _resolve_machine_metadata(paths=None, machine=None):
    if isinstance(machine, Machine):
        return machine
    if machine is None:
        machine_name = paths.machine if paths is not None else DEFAULT_MACHINE
    else:
        machine_name = machine
    root = paths.root if paths is not None else project_root()
    return load_machine(root, machine_name)
