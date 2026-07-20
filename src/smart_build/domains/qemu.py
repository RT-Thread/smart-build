import shutil
import shlex
import subprocess
from pathlib import Path

from ..config import DEFAULT_ROOTFS_IMAGE_FORMAT, load_defconfig, load_workspace_config
from ..errors import SmartBuildError
from ..machines import load_machine
from ..paths import board_defconfig_path
from ..tasks import Task


QEMU_SCRIPT_TASK_ID = "qemu-script:generate"
QEMU_SCRIPT_NAME = "run_qemu_nographic.sh"
DEFAULT_ROOTFS_IMAGE = "minirootfs.img"
FULL_ROOTFS_IMAGE = "rootfs.img"
ALLOWED_ROOTFS_IMAGES = ("minirootfs.img", "busybox-rootfs.img", FULL_ROOTFS_IMAGE)
QEMU_SMOKE_LOG_NAME = "qemu-smoke.log"
QEMU_SMOKE_MARKERS = ("RT-Thread", "msh />")
QEMU_SMOKE_FAILURE_MARKERS = (
    "assertion failed",
    "rt_aspace_fault_try_fix",
    "User prefetch abort",
    "User data abort",
)
ROOTFS_DRIVER_BY_IMAGE_FORMAT = {
    "ext4": "ext",
    "fat": "elm",
}


def qemu_script_task(paths):
    script = paths.machine_dir / QEMU_SCRIPT_NAME
    machine = load_machine(paths.root, paths.machine)
    rootfs_format = _configured_rootfs_format(paths)
    command = qemu_command(machine, rootfs_format=rootfs_format)
    manifest = {
        "script": str(script),
        "command": command,
        "kernel": str(paths.images_dir / "rtthread.bin"),
        "profile": machine.qemu_profile,
        "binary": machine.qemu_binary,
        "machine": machine.qemu_machine,
        "cpu": machine.qemu_cpu,
        "rootfs_format": rootfs_format,
    }
    if machine.qemu_profile == "virt-aarch64":
        manifest["bootargs"] = _aarch64_bootargs(rootfs_format)
    manifest.update(_rootfs_manifest(paths, machine))
    return Task(
        id=QEMU_SCRIPT_TASK_ID,
        domain="qemu",
        action="script",
        inputs=[],
        outputs=[script],
        deps=["kernel:build"],
        workdir=paths.work_dir / "qemu-script",
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="never",
        log_path=paths.logs_dir / "qemu-script.log",
        executor=_make_qemu_script_executor(script, command, machine),
        cache_extra={"qemu": manifest},
        manifest_fields={"qemu": manifest},
    )


def qemu_command(machine, rootfs_format=DEFAULT_ROOTFS_IMAGE_FORMAT):
    if machine.qemu_profile == "virt-aarch64":
        if not machine.qemu_cpu:
            raise SmartBuildError("CONFIG", "qemu profile 'virt-aarch64' requires qemu.cpu")
        return [
            machine.qemu_binary,
            "-M",
            f"{machine.qemu_machine},acpi=on,its=on,gic-version=2",
            "-cpu",
            machine.qemu_cpu,
            "-smp",
            "4",
            "-m",
            "128M",
            "-kernel",
            "images/rtthread.bin",
            "-append",
            _aarch64_bootargs(rootfs_format),
            "-nographic",
            "-serial",
            "mon:stdio",
            "-drive",
            "if=none,file=images/${ROOTFS_IMAGE},format=raw,id=blk0",
            "-device",
            "virtio-blk-device,drive=blk0",
            "-netdev",
            "user,id=net0,hostfwd=tcp::58080-:22",
            "-device",
            "virtio-net-device,netdev=net0,speed=800000",
            "-device",
            "virtio-rng-device",
            "-device",
            "virtio-serial-device",
        ]
    if machine.qemu_profile == "virt-riscv64":
        return [
            machine.qemu_binary,
            "-M",
            machine.qemu_machine,
            "-m",
            "256M",
            "-kernel",
            "images/rtthread.bin",
            "-nographic",
            "-drive",
            "if=none,file=images/${ROOTFS_IMAGE},format=raw,id=blk0",
            "-device",
            "virtio-blk-device,drive=blk0",
            "-netdev",
            "user,id=net0,hostfwd=tcp::58081-:22",
            "-device",
            "virtio-net-device,netdev=net0",
            "-device",
            "virtio-serial-device",
        ]
    if machine.qemu_profile == "vexpress-a9":
        return [
            machine.qemu_binary,
            "-M",
            machine.qemu_machine,
            "-m",
            "128M",
            "-kernel",
            "images/rtthread.bin",
            "-nographic",
            "-sd",
            "images/${ROOTFS_IMAGE}",
        ]
    raise SmartBuildError("CONFIG", f"unsupported qemu profile {machine.qemu_profile!r}")


def run_qemu_smoke(paths, timeout_seconds=30, rootfs_image=None, env=None):
    machine = load_machine(paths.root, paths.machine)
    launcher = paths.machine_dir / QEMU_SCRIPT_NAME
    log_path = paths.logs_dir / QEMU_SMOKE_LOG_NAME
    if not launcher.is_file():
        raise SmartBuildError("DEPLOY", f"missing qemu launcher: {launcher}")
    rootfs_argument, cleanup_paths = _qemu_smoke_rootfs_argument(paths, machine, rootfs_image)

    command = [str(launcher), *rootfs_argument]
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    try:
        try:
            result = subprocess.run(
                command,
                cwd=paths.machine_dir,
                check=False,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_seconds,
            )
            output = result.stdout or ""
            status = f"exit {result.returncode}"
        except subprocess.TimeoutExpired as exc:
            output = _timeout_output(exc)
            status = f"timeout after {timeout_seconds:g}s"
        except OSError as exc:
            raise SmartBuildError(
                "DEPLOY", f"failed to run qemu launcher {launcher}: {exc}; log={log_path}"
            ) from exc
    finally:
        for path in cleanup_paths:
            path.unlink(missing_ok=True)

    log_path.write_text(output, encoding="utf-8")
    failure_marker = _qemu_smoke_failure_marker(output)
    if failure_marker:
        raise SmartBuildError(
            "DEPLOY",
            f"qemu smoke failed ({status}); failure marker {failure_marker!r} found; log={log_path}",
        )
    if _has_qemu_smoke_marker(output):
        return log_path
    raise SmartBuildError(
        "DEPLOY",
        f"qemu smoke failed ({status}); boot marker not found; log={log_path}",
    )


def _rootfs_manifest(paths, machine):
    if _qemu_profile_accepts_rootfs_image(machine.qemu_profile):
        choices = ", ".join(ALLOWED_ROOTFS_IMAGES[:-1]) + f", or {ALLOWED_ROOTFS_IMAGES[-1]}"
        policy = "sd-image-argument" if machine.qemu_profile == "vexpress-a9" else "virtio-image-argument"
        return {
            "rootfs_policy": policy,
            "default_image": _configured_rootfs_image(paths),
            "allowed_images": list(ALLOWED_ROOTFS_IMAGES),
            "image_argument": f"optional rootfs image name: {choices}",
        }
    raise SmartBuildError("CONFIG", f"unsupported qemu profile {machine.qemu_profile!r}")


def _qemu_smoke_rootfs_argument(paths, machine, rootfs_image):
    if _qemu_profile_accepts_rootfs_image(machine.qemu_profile):
        image_name = rootfs_image or _configured_rootfs_image(paths)
        if image_name not in ALLOWED_ROOTFS_IMAGES:
            choices = ", ".join(ALLOWED_ROOTFS_IMAGES)
            raise SmartBuildError(
                "DEPLOY", f"unsupported rootfs image {image_name!r}; expected one of: {choices}"
            )
        image = paths.images_dir / image_name
        if not image.is_file():
            raise SmartBuildError("DEPLOY", f"missing rootfs image: {image}")
        smoke_image_name = _prepare_qemu_smoke_rootfs_copy(paths, image, image_name)
        return [smoke_image_name], [paths.images_dir / smoke_image_name]
    raise SmartBuildError("CONFIG", f"unsupported qemu profile {machine.qemu_profile!r}")


def _prepare_qemu_smoke_rootfs_copy(paths, image, image_name):
    smoke_image = paths.images_dir / f"qemu-smoke-{image_name}"
    shutil.copy2(image, smoke_image)
    return smoke_image.name


def _qemu_profile_accepts_rootfs_image(profile):
    return profile in {"virt-aarch64", "virt-riscv64", "vexpress-a9"}


def _configured_rootfs_image(paths):
    values = _configured_build_values(paths)
    rootfs = values.get("ROOTFS")
    if rootfs == "basic":
        return "busybox-rootfs.img"
    if rootfs == "full":
        return FULL_ROOTFS_IMAGE
    return DEFAULT_ROOTFS_IMAGE


def _configured_rootfs_format(paths):
    values = _configured_build_values(paths)
    return values.get("ROOTFS_IMAGE_FORMAT", DEFAULT_ROOTFS_IMAGE_FORMAT)


def _configured_build_values(paths):
    defconfig = board_defconfig_path(paths.root, paths.machine)
    values = load_defconfig(defconfig) if defconfig.exists() else {}
    workspace_values = load_workspace_config(paths.root)
    if workspace_values.get("MACHINE") == paths.machine:
        values.update(workspace_values)
    return values


def _aarch64_bootargs(rootfs_format):
    filesystem = ROOTFS_DRIVER_BY_IMAGE_FORMAT.get(rootfs_format)
    if filesystem is None:
        raise SmartBuildError(
            "CONFIG",
            f"qemu profile 'virt-aarch64' does not support rootfs image format {rootfs_format!r}",
        )
    return (
        "console=ttyAMA0 earlycon cma=8M coherent_pool=2M "
        f"root=vda0 rootfstype={filesystem} rootwait rw"
    )


def _timeout_output(exc):
    output = exc.output if exc.output is not None else exc.stdout
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _has_qemu_smoke_marker(output):
    return any(marker in output for marker in QEMU_SMOKE_MARKERS)


def _qemu_smoke_failure_marker(output):
    return next((marker for marker in QEMU_SMOKE_FAILURE_MARKERS if marker in output), None)


def _make_qemu_script_executor(script, command, machine):
    def executor(task, log):
        _write_qemu_script(
            script,
            command,
            machine,
            task.manifest_fields["qemu"].get("default_image", DEFAULT_ROOTFS_IMAGE),
        )
        task.manifest_fields["qemu"]["script"] = str(script)
        task.manifest_fields["qemu"]["command"] = command
        log.write(f"wrote qemu launcher: {script}\n")
        return 0

    return executor


def _write_qemu_script(script, command, machine, default_image=DEFAULT_ROOTFS_IMAGE):
    path = Path(script)
    if path.is_symlink():
        raise SmartBuildError("DEPLOY", f"refusing to replace symlink output: {path}")
    if path.exists() and not path.is_file():
        raise SmartBuildError("DEPLOY", f"refusing to replace non-file output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_script_text(command, machine, default_image), encoding="utf-8")
    path.chmod(0o755)


def _script_text(command, machine, default_image=DEFAULT_ROOTFS_IMAGE):
    if _qemu_profile_accepts_rootfs_image(machine.qemu_profile):
        return _virt_script_text(command, default_image)
    raise SmartBuildError("CONFIG", f"unsupported qemu profile {machine.qemu_profile!r}")


def _virt_script_text(command, default_image=DEFAULT_ROOTFS_IMAGE):
    return (
        f"{_script_header()}"
        'usage() {\n'
        '    echo "usage: $(basename "$0") [minirootfs.img|busybox-rootfs.img|rootfs.img]" >&2\n'
        "}\n"
        f"{_rootfs_argument_text(default_image)}"
        f"{_kernel_check_text()}"
        'if [ ! -f "${ROOTFS}" ]; then\n'
        '    echo "missing rootfs image: ${ROOTFS}" >&2\n'
        "    exit 1\n"
        "fi\n"
        "\n"
        f"{_qemu_command_text(command)}\n"
    )


def _kernel_only_script_text(command):
    return (
        f"{_script_header()}"
        'usage() {\n'
        '    echo "usage: $(basename "$0")" >&2\n'
        "}\n"
        'if [ "$#" -ne 0 ]; then\n'
        "    usage\n"
        "    exit 2\n"
        "fi\n"
        f"{_kernel_check_text()}"
        "\n"
        f"{_qemu_command_text(command)}\n"
    )


def _script_header():
    return (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    )


def _rootfs_argument_text(default_image=DEFAULT_ROOTFS_IMAGE):
    return (
        'if [ "$#" -gt 1 ]; then\n'
        "    usage\n"
        "    exit 2\n"
        "fi\n"
        f'ROOTFS_IMAGE="{default_image}"\n'
        'if [ "$#" -eq 1 ]; then\n'
        '    ROOTFS_IMAGE="$1"\n'
        "fi\n"
        'case "${ROOTFS_IMAGE}" in\n'
        "    minirootfs.img|busybox-rootfs.img|rootfs.img|qemu-smoke-minirootfs.img|qemu-smoke-busybox-rootfs.img|qemu-smoke-rootfs.img) ;;\n"
        "    *)\n"
        "        usage\n"
        "        exit 2\n"
        "        ;;\n"
        "esac\n"
        'ROOTFS="${SCRIPT_DIR}/images/${ROOTFS_IMAGE}"\n'
        "\n"
    )


def _kernel_check_text():
    return (
        'KERNEL="${SCRIPT_DIR}/images/rtthread.bin"\n'
        "\n"
        'if [ ! -f "${KERNEL}" ]; then\n'
        '    echo "missing kernel image: ${KERNEL}" >&2\n'
        "    exit 1\n"
        "fi\n"
    )


def _qemu_command_text(command):
    parts = [_script_command_part(part) for part in command]
    lines = ["cmd=("]
    lines.extend(f"  {part}" for part in parts)
    lines.append(")")
    lines.append('exec "${cmd[@]}"')
    return "\n".join(lines)


def _script_command_part(part):
    if part == "images/rtthread.bin":
        return '"${KERNEL}"'
    if part == "images/${ROOTFS_IMAGE}":
        return '"${ROOTFS}"'
    if part == "if=none,file=images/${ROOTFS_IMAGE},format=raw,id=blk0":
        return '"if=none,file=${ROOTFS},format=raw,id=blk0"'
    return shlex.quote(part)
