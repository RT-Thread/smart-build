import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from ..cache import path_record
from ..errors import SmartBuildError
from ..machines import load_machine
from ..paths import validate_safe_name
from ..tasks import Task


DEVICETREE_TASK_ID = "devicetree:build"
CUSTOM_DTB_NAME = "devicetree.dtb"
QEMU_DTB_NAME = "qemu.dtb"
VIRT_PROFILES = {"virt-aarch64", "virt-riscv64"}


def output_path(paths, name, suffix):
    name = validate_safe_name(name, "device tree output")
    if Path(name).suffix != suffix:
        raise SmartBuildError("CONFIG", f"device tree output must end in {suffix}: {name}")
    output = paths.images_dir / name
    _validate_output(paths, output)
    return output


def _validate_output(paths, output):
    output = Path(output)
    owner = (paths.root / "build" / paths.machine).absolute()
    if not owner.resolve().is_relative_to((paths.root / "build").resolve()):
        raise SmartBuildError("CONFIG", f"device tree build directory escapes build root: {owner}")
    if not output.resolve().is_relative_to(owner.resolve()) or output.is_symlink():
        raise SmartBuildError("CONFIG", f"unsafe device tree output: {output}")
    if output.exists() and not output.is_file():
        raise SmartBuildError("CONFIG", f"device tree output is not a regular file: {output}")
    for directory in (paths.images_dir, paths.work_dir, paths.logs_dir):
        if not directory.resolve().is_relative_to(owner.resolve()):
            raise SmartBuildError("CONFIG", f"device tree directory escapes machine build: {directory}")


def source_path(source, suffix):
    path = Path(source).resolve()
    if path.suffix != suffix or not path.is_file():
        raise SmartBuildError("CONFIG", f"expected an existing {suffix} file: {source}")
    return path


def validate_dtb(source):
    path = source_path(source, ".dtb")
    try:
        with path.open("rb") as stream:
            header = stream.read(40)
        if len(header) != 40:
            raise ValueError("truncated header")
        magic, size, structure, strings, reserve, version, compatible, _, string_size, struct_size = (
            struct.unpack(">10I", header)
        )
        if magic != 0xD00DFEED or not 40 <= size <= path.stat().st_size:
            raise ValueError("invalid magic or total size")
        if version < 17 or compatible > 17 or not 40 <= reserve < size or reserve % 8:
            raise ValueError("unsupported header or reservation block")
        if not 40 <= structure < size or structure % 4 or structure + struct_size > size:
            raise ValueError("invalid structure block")
        if not 40 <= strings <= size or strings + string_size > size:
            raise ValueError("invalid strings block")
    except (OSError, ValueError) as exc:
        raise SmartBuildError("CONFIG", f"invalid DTB {path}: {exc}") from exc
    return path


def _tool(name):
    executable = shutil.which(name)
    if executable is None:
        raise SmartBuildError("CONFIG", f"required host tool not found: {name}")
    return executable


def _run(command, log, timeout=60):
    log.write(f"command: {json.dumps([str(part) for part in command])}\n")
    log.flush()
    try:
        result = subprocess.run(
            [str(part) for part in command], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmartBuildError("BUILD", f"device tree command failed: {exc}; log={log.name}") from exc
    log.write(result.stdout or "")
    log.flush()
    if result.returncode:
        raise SmartBuildError(
            "BUILD", f"device tree command exited {result.returncode}; log={log.name}"
        )


def convert_tree(paths, source, action, output_name=None, include_dirs=()):
    if action not in {"compile", "decompile"}:
        raise SmartBuildError("CONFIG", f"unsupported device tree conversion: {action}")
    compiling = action == "compile"
    source = source_path(source, ".dts" if compiling else ".dtb")
    if not compiling:
        validate_dtb(source)
    directories = tuple(Path(directory).resolve() for directory in include_dirs)
    for directory in directories:
        if not directory.is_dir():
            raise SmartBuildError("CONFIG", f"device tree include directory not found: {directory}")
    suffix = ".dtb" if compiling else ".dts"
    output = output_path(paths, output_name or source.with_suffix(suffix).name, suffix)
    if output.resolve() == source:
        raise SmartBuildError("CONFIG", "device tree output must not overwrite its input")
    dtc = _tool("dtc")
    cpp = _tool("cpp") if compiling else None
    work = paths.work_dir / "devicetree"
    work.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = paths.logs_dir / f"devicetree-{action}.log"
    with tempfile.TemporaryDirectory(dir=work) as temporary, log_path.open("w", encoding="utf-8") as log:
        result = Path(temporary) / f"result{suffix}"
        input_file = source
        if compiling:
            input_file = Path(temporary) / "preprocessed.dts"
            command = [cpp, "-nostdinc", "-undef", "-D__DTS__", "-x", "assembler-with-cpp", "-P"]
            for directory in (source.parent, *directories):
                command.extend(["-I", str(directory)])
            command.extend([str(source), "-o", str(input_file)])
            _run(command, log)
        command = [dtc, "-I", "dts" if compiling else "dtb", "-O", "dtb" if compiling else "dts"]
        for directory in (source.parent, *directories):
            command.extend(["-i", str(directory)])
        command.extend(["-o", str(result), str(input_file)])
        _run(command, log)
        if compiling:
            validate_dtb(result)
        if not result.is_file() or result.stat().st_size == 0:
            raise SmartBuildError("BUILD", f"device tree command produced no output; log={log_path}")
        _validate_output(paths, output)
        output.parent.mkdir(parents=True, exist_ok=True)
        result.replace(output)
    return output


def dump_qemu_tree(paths, output_name=QEMU_DTB_NAME, bootargs=None):
    from .qemu import _configured_rootfs_format, qemu_command

    machine = load_machine(paths.root, paths.machine)
    if machine.qemu_profile not in VIRT_PROFILES:
        raise SmartBuildError("CONFIG", "device tree dump requires a QEMU virt profile")
    output = output_path(paths, output_name, ".dtb")
    command = qemu_command(machine, _configured_rootfs_format(paths), dtb=False, bootargs=bootargs)
    command[0] = _tool(machine.qemu_binary)
    work = paths.work_dir / "devicetree"
    work.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = paths.logs_dir / "devicetree-dump.log"
    with tempfile.TemporaryDirectory(dir=work) as temporary, log_path.open("w", encoding="utf-8") as log:
        result = Path(temporary).resolve() / "qemu.dtb"
        command[command.index("-M") + 1] += f",dumpdtb={str(result).replace(',', ',,')}"
        # QEMU requires -kernel with -append, even when dumpdtb exits before boot.
        kernel = Path(temporary).resolve() / "kernel.bin"
        kernel.write_bytes(bytes(64))
        command[command.index("-kernel") + 1] = str(kernel)
        disk = Path(temporary).resolve() / "disk.img"
        with disk.open("wb") as stream:
            stream.truncate(1024 * 1024)
        command[command.index("-drive") + 1] = (
            f"if=none,file={str(disk).replace(',', ',,')},format=raw,id=blk0"
        )
        command[command.index("-netdev") + 1] = "user,id=net0"
        _run(command, log, timeout=15)
        validate_dtb(result)
        _validate_output(paths, output)
        output.parent.mkdir(parents=True, exist_ok=True)
        result.replace(output)
    return output


def devicetree_task(paths, machine=None):
    machine = machine or load_machine(paths.root, paths.machine)
    source = machine.devicetree_source
    name = CUSTOM_DTB_NAME if source is not None else QEMU_DTB_NAME
    output = output_path(paths, name, ".dtb")
    if source is not None:
        source_path(source, source.suffix)
        if source.suffix == ".dtb":
            validate_dtb(source)
        else:
            _tool("cpp")
            _tool("dtc")
    else:
        if machine.qemu_profile not in VIRT_PROFILES:
            raise SmartBuildError("CONFIG", "automatic device tree requires a QEMU virt profile")
        _tool(machine.qemu_binary)
    record = {
        "mode": "custom" if source is not None else "automatic",
        "source": str(source) if source is not None else None,
        "include_dirs": [str(path) for path in machine.devicetree_include_dirs],
        "output": str(output),
    }

    def executor(task, log):
        if source is None:
            artifact = dump_qemu_tree(paths)
        elif source.suffix == ".dts":
            artifact = convert_tree(paths, source, "compile", name, machine.devicetree_include_dirs)
        else:
            validate_dtb(source)
            _validate_output(paths, output)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
            artifact = output
        task.manifest_fields["devicetree"]["artifact"] = path_record(artifact)
        log.write(f"device tree {record['mode']}: {artifact}\n")
        return 0

    return Task(
        id=DEVICETREE_TASK_ID, domain="devicetree", action="build",
        inputs=[paths.root / "boards" / paths.machine / "board.yaml", *([source] if source else [])],
        outputs=[output], workdir=paths.work_dir / "devicetree", run_class="serial",
        cache_policy="never", log_path=paths.logs_dir / "devicetree-build.log",
        executor=executor, manifest_fields={"devicetree": record},
    )
