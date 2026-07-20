import os
import subprocess
from pathlib import Path

from ..cache import path_record
from ..config import resolve_rootfs_selection
from ..doctor import resolve_host_tool
from ..errors import SmartBuildError
from ..tasks import Task
from .rootfs import ROOTFS_DIR_NAME


IMAGE_BLOCK = 1024 * 1024


def minirootfs_image_task(paths, command_runner=None, selection=None):
    selection = selection if selection is not None else resolve_rootfs_selection(paths.root, paths.machine)
    rootfs_dir = paths.staging_dir / ROOTFS_DIR_NAME
    minirootfs_image = paths.images_dir / "minirootfs.img"
    command = _image_command(selection.image_format, rootfs_dir, minirootfs_image)
    return Task(
        id="minirootfs:image",
        domain="image",
        action="minirootfs",
        inputs=[rootfs_dir],
        outputs=[minirootfs_image],
        deps=["rootfs:stage"],
        workdir=paths.work_dir / "minirootfs-image",
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="never",
        log_path=paths.logs_dir / "minirootfs-image.log",
        executor=_make_minirootfs_image_executor(rootfs_dir, minirootfs_image, command_runner),
        cache_extra={
            "rootfs": str(rootfs_dir),
            "minirootfs_image": str(minirootfs_image),
            "filesystem": selection.image_format,
            "size_mb": selection.image_size_mb,
            "size_mode": selection.image_size_mode,
            "command": command,
        },
        manifest_fields={
            "images": {
                "rootfs": str(rootfs_dir),
                "minirootfs": str(minirootfs_image),
                "filesystem": selection.image_format,
                "size_mb": selection.image_size_mb,
                "size_mode": selection.image_size_mode,
                "command": command,
            }
        },
    )


def rootfs_image_task(paths, command_runner=None, selection=None):
    selection = selection if selection is not None else resolve_rootfs_selection(paths.root, paths.machine)
    rootfs_dir = paths.staging_dir / ROOTFS_DIR_NAME
    image = paths.images_dir / "rootfs.img"
    command = _image_command(selection.image_format, rootfs_dir, image)
    qemu_sd_power_of_two = _requires_qemu_sd_power_of_two(paths)
    return Task(
        id="rootfs:image",
        domain="image",
        action="rootfs",
        inputs=[rootfs_dir],
        outputs=[image],
        deps=["rootfs:stage"],
        workdir=paths.work_dir / "rootfs-image",
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="never",
        log_path=paths.logs_dir / "rootfs-image.log",
        executor=_make_single_image_executor(rootfs_dir, image, command_runner),
        cache_extra={
            "rootfs": str(rootfs_dir),
            "rootfs_image": str(image),
            "filesystem": selection.image_format,
            "size_mb": selection.image_size_mb,
            "size_mode": selection.image_size_mode,
            "qemu_sd_power_of_two": qemu_sd_power_of_two,
            "command": command,
        },
        manifest_fields={
            "images": {
                "rootfs": str(rootfs_dir),
                "rootfs_image": str(image),
                "filesystem": selection.image_format,
                "size_mb": selection.image_size_mb,
                "size_mode": selection.image_size_mode,
                "qemu_sd_power_of_two": qemu_sd_power_of_two,
                "command": command,
            }
        },
    )


def _make_minirootfs_image_executor(rootfs_dir, minirootfs_image, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        if not rootfs_dir.is_dir():
            raise SmartBuildError("IMAGE", f"rootfs directory not found: {rootfs_dir}")
        image_fields = task.manifest_fields["images"]
        filesystem = image_fields["filesystem"]
        if filesystem != "ext4":
            raise SmartBuildError("IMAGE", f"rootfs image format {filesystem} is not implemented")
        minirootfs_image.parent.mkdir(parents=True, exist_ok=True)
        _remove_stale_minimal_alias(minirootfs_image.parent / "minimal-rootfs.img", minirootfs_image)
        _remove_stale_images(minirootfs_image.parent, current_name="minirootfs.img")
        _prepare_new_output(minirootfs_image)
        image_size = _image_size(
            rootfs_dir,
            configured_size_mb=image_fields["size_mb"],
            size_mode=image_fields["size_mode"],
        )
        with minirootfs_image.open("wb") as handle:
            handle.truncate(image_size)

        command = image_fields["command"]
        completed = runner(command, cwd=task.workdir, env=os.environ.copy())
        _write_completed_command(log, command, task.workdir, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "IMAGE",
                "minirootfs image creation failed: command={command} exit code {exit_code} "
                "log={log_path}".format(
                    command=" ".join(command),
                    exit_code=completed.returncode,
                    log_path=task.log_path,
                ),
            )
        if not minirootfs_image.is_file() or minirootfs_image.stat().st_size == 0:
            raise SmartBuildError("IMAGE", f"mke2fs did not create a non-empty image: {minirootfs_image}")

        image_fields["size"] = minirootfs_image.stat().st_size
        image_fields["minirootfs_checksum"] = path_record(minirootfs_image).get("sha256")
        log.write(f"created minirootfs image: {minirootfs_image}\n")
        return 0

    return executor


def _make_single_image_executor(rootfs_dir, image, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        if not rootfs_dir.is_dir():
            raise SmartBuildError("IMAGE", f"rootfs directory not found: {rootfs_dir}")
        image_fields = task.manifest_fields["images"]
        filesystem = image_fields["filesystem"]
        if filesystem != "ext4":
            raise SmartBuildError("IMAGE", f"rootfs image format {filesystem} is not implemented")
        image.parent.mkdir(parents=True, exist_ok=True)
        _remove_stale_images(image.parent, current_name="rootfs.img")
        _prepare_new_output(image)
        image_size = _image_size(
            rootfs_dir,
            configured_size_mb=image_fields["size_mb"],
            size_mode=image_fields["size_mode"],
            power_of_two=image_fields.get("qemu_sd_power_of_two", False),
        )
        with image.open("wb") as handle:
            handle.truncate(image_size)

        command = image_fields["command"]
        completed = runner(command, cwd=task.workdir, env=os.environ.copy())
        _write_completed_command(log, command, task.workdir, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "IMAGE",
                "rootfs image creation failed: command={command} exit code {exit_code} "
                "log={log_path}".format(
                    command=" ".join(command),
                    exit_code=completed.returncode,
                    log_path=task.log_path,
                ),
            )
        if not image.is_file() or image.stat().st_size == 0:
            raise SmartBuildError("IMAGE", f"mke2fs did not create a non-empty image: {image}")

        image_fields["size"] = image.stat().st_size
        image_fields["rootfs_checksum"] = path_record(image).get("sha256")
        log.write(f"created rootfs image: {image}\n")
        return 0

    return executor


def _image_command(filesystem, rootfs_dir, image):
    if filesystem == "ext4":
        return _mke2fs_command(rootfs_dir, image)
    return []


def _mke2fs_command(rootfs_dir, image):
    return [resolve_host_tool("mke2fs"), "-F", "-t", "ext4", "-d", str(rootfs_dir), str(image)]


def _image_size(rootfs_dir, configured_size_mb, size_mode, power_of_two=False):
    configured_size = configured_size_mb * IMAGE_BLOCK
    if size_mode == "fixed":
        return _round_power_of_two(configured_size) if power_of_two else configured_size
    content_size = 0
    for path in rootfs_dir.rglob("*"):
        if path.is_file():
            content_size += path.stat().st_size
        elif path.is_symlink():
            content_size += len(os.readlink(path))
    requested = max(configured_size, content_size * 4 + 8 * IMAGE_BLOCK)
    image_size = ((requested + IMAGE_BLOCK - 1) // IMAGE_BLOCK) * IMAGE_BLOCK
    return _round_power_of_two(image_size) if power_of_two else image_size


def _requires_qemu_sd_power_of_two(paths):
    return paths.machine == "qemu-vexpress-a9"


def _round_power_of_two(value):
    if value <= 1:
        return 1
    return 1 << (value - 1).bit_length()


def _remove_stale_minimal_alias(path, minirootfs_image):
    stale = Path(path)
    if not stale.exists() and not stale.is_symlink():
        return
    if stale.is_symlink():
        raise SmartBuildError("IMAGE", f"refusing to replace symlink output: {stale}")
    if not stale.is_file():
        raise SmartBuildError("IMAGE", f"refusing to replace non-file output: {stale}")
    stale_stat = stale.stat()
    if stale_stat.st_nlink > 1 and not _same_file(stale, minirootfs_image):
        raise SmartBuildError("IMAGE", f"refusing to replace hardlink output: {stale}")
    stale.unlink()
    if _same_inode_path(minirootfs_image, stale_stat):
        Path(minirootfs_image).unlink()


def _remove_stale_images(images_dir, current_name):
    for name in ("minirootfs.img", "busybox-rootfs.img", "rootfs.img"):
        if name != current_name:
            _remove_stale_image(Path(images_dir) / name)


def _remove_stale_image(path):
    stale = Path(path)
    if not stale.exists() and not stale.is_symlink():
        return
    if stale.is_symlink():
        raise SmartBuildError("IMAGE", f"refusing to replace symlink output: {stale}")
    if not stale.is_file():
        raise SmartBuildError("IMAGE", f"refusing to replace non-file output: {stale}")
    if stale.stat().st_nlink > 1:
        raise SmartBuildError("IMAGE", f"refusing to replace hardlink output: {stale}")
    stale.unlink()


def _same_file(first, second):
    first = Path(first)
    second = Path(second)
    if not first.exists() or not second.exists():
        return False
    return _same_inode_path(second, first.stat())


def _same_inode_path(path, expected_stat):
    path = Path(path)
    if not path.exists():
        return False
    current_stat = path.stat()
    return (current_stat.st_dev, current_stat.st_ino) == (expected_stat.st_dev, expected_stat.st_ino)


def _prepare_new_output(path):
    output = Path(path)
    if output.is_symlink():
        raise SmartBuildError("IMAGE", f"refusing to replace symlink output: {output}")
    if not output.exists():
        return
    if not output.is_file():
        raise SmartBuildError("IMAGE", f"refusing to replace non-file output: {output}")
    if output.stat().st_nlink > 1:
        raise SmartBuildError("IMAGE", f"refusing to replace hardlink output: {output}")
    output.unlink()


def _run_command(command, cwd, env):
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise SmartBuildError("IMAGE", f"failed to run image command {command}: {exc}") from exc


def _write_completed_command(log, command, cwd, completed):
    log.write(f"command: {' '.join(str(part) for part in command)}\n")
    log.write(f"workdir: {cwd}\n")
    log.write("summary: command started\n")
    if completed.stdout:
        log.write(completed.stdout)
        if not completed.stdout.endswith("\n"):
            log.write("\n")
    log.write(f"summary: command exit={completed.returncode}\n")
    log.write(f"exit: {completed.returncode}\n")
