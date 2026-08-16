from io import StringIO

from smart_build.domains.busybox import busybox_stage_rootfs_task
from smart_build.paths import BuildPaths


def test_busybox_rootfs_installs_executable_init_script(tmp_path):
    paths = BuildPaths.for_machine("test-machine", root=tmp_path)
    source_install = paths.work_dir / "busybox" / "busybox-1.35.0" / "install"
    source_install.mkdir(parents=True)
    package_conf = tmp_path / "packages" / "busybox" / "conf"
    package_conf.mkdir(parents=True)
    (package_conf / "inittab").write_text("::sysinit:/etc/init.d/rcS\n", encoding="utf-8")
    (package_conf / "rcS").write_text(
        "#!/bin/sh\nmkdir -p /dev/shm\nmount -t tmp tmp /dev/shm\n",
        encoding="utf-8",
    )
    paths.ensure_execution_dirs()

    task = busybox_stage_rootfs_task(paths)
    assert task.executor(task, StringIO()) == 0

    init_script = paths.staging_dir / "rootfs-busybox" / "etc" / "init.d" / "rcS"
    assert init_script.stat().st_mode & 0o777 == 0o755
    assert "mount -t tmp tmp /dev/shm" in init_script.read_text(encoding="utf-8")
