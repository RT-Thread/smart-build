import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import warnings
from dataclasses import replace
from pathlib import Path

from ..cache import Cache, path_record
from ..config import resolve_rootfs_selection
from ..configure import (
    ConfigurationSpec,
    ConfigurationSync,
    execute_configuration,
    toolchain_configuration_env,
)
from ..doctor import resolve_host_tool
from ..errors import SmartBuildError
from ..scheduler import Scheduler
from ..tasks import Task, TaskGraph
from .rootfs import ROOTFS_MANIFEST
from .smart_sdk import smart_sdk_dir
from .toolchain import resolve_toolchain, toolchain_task_fields


BUSYBOX_VERSION = "1.35.0"
BUSYBOX_SOURCE_DIR = f"busybox-{BUSYBOX_VERSION}"
BUSYBOX_ARCHIVE_NAME = f"{BUSYBOX_SOURCE_DIR}.tar.bz2"
BUSYBOX_MD5 = "585949b1dd4292b604b7d199866e9913"
BUSYBOX_URL = f"https://busybox.net/downloads/{BUSYBOX_ARCHIVE_NAME}"
BUSYBOX_ROOTFS_DIR_NAME = "rootfs-busybox"
BUSYBOX_ROOTFS_MANIFEST_NAME = "rootfs-busybox.manifest.json"
TIME64_COMPAT_SOURCE_NAME = "smart-rtthread-time64-compat.c"
TIME64_COMPAT_OBJECT_NAME = "smart-rtthread-time64-compat.o"
MIN_IMAGE_SIZE = 16 * 1024 * 1024
IMAGE_BLOCK = 1024 * 1024
REQUIRED_ROOTFS_DIRS = (
    "bin",
    "dev",
    "dev/shm",
    "etc",
    "lib",
    "mnt",
    "proc",
    "root",
    "run",
    "services",
    "tmp",
    "var",
)


def busybox_rootfs_tasks(paths, toolchain=None, command_runner=None, downloader=None, jobs=None, selection=None):
    return [
        busybox_fetch_task(paths, downloader=downloader),
        busybox_prepare_task(paths, command_runner=command_runner),
        busybox_build_task(paths, toolchain=toolchain, command_runner=command_runner, jobs=jobs),
        busybox_stage_rootfs_task(paths),
        busybox_image_task(paths, command_runner=command_runner, selection=selection),
    ]


def busybox_configuration(paths, toolchain=None, command_runner=None):
    resolved_toolchain = toolchain
    if resolved_toolchain is None:
        from ..machines import load_machine

        resolved_toolchain = resolve_toolchain(machine=load_machine(paths.root, paths.machine))
    paths.ensure_execution_dirs()
    _prepare_busybox_configuration_source(paths)
    source = busybox_source_dir(paths)
    config = busybox_config_path(paths)
    env = toolchain_configuration_env(
        paths,
        resolved_toolchain,
        SMART_BUILD_PACKAGE="busybox",
        SMART_BUILD_PACKAGE_DIR=busybox_reference_dir(paths),
        SMART_BUILD_SOURCE_DIR=source,
        SMART_BUILD_WORK_DIR=source,
        SMART_BUILD_CONFIG_PATH=config,
    )
    spec = ConfigurationSpec(
        target="busybox",
        command=("make", "menuconfig", f"CROSS_COMPILE={resolved_toolchain.prefix}"),
        workdir=source,
        env=env,
        sync=(ConfigurationSync(source=source / ".config", destination=config),),
    )
    return execute_configuration(spec, command_runner=command_runner)


def _prepare_busybox_configuration_source(paths):
    fetch = replace(busybox_fetch_task(paths), deps=())
    prepare = busybox_prepare_task(paths)
    Scheduler(
        TaskGraph([fetch, prepare]),
        Cache(paths.stamps_dir),
        display_path=paths.display_path,
    ).run()


def busybox_fetch_task(paths, downloader=None, md5=BUSYBOX_MD5, url=BUSYBOX_URL, allow_network=True):
    archive = busybox_archive_path(paths)
    manifest = _base_busybox_manifest(paths, archive, url, md5)
    return Task(
        id="busybox:fetch",
        domain="busybox",
        action="fetch",
        inputs=[archive] if archive.exists() else [],
        outputs=[archive],
        deps=["toolchain:check"],
        workdir=paths.work_dir / "busybox" / "fetch",
        env={"MACHINE": paths.machine},
        run_class="fetch",
        cache_policy="never",
        log_path=paths.logs_dir / "busybox-fetch.log",
        executor=_make_fetch_executor(archive, url, md5, downloader, allow_network),
        cache_extra={
            "busybox": {
                "version": BUSYBOX_VERSION,
                "archive": str(archive),
                "url": url,
                "md5": md5,
                "allow_network": allow_network,
            }
        },
        manifest_fields={"busybox": manifest},
    )


def busybox_prepare_task(paths, command_runner=None, md5=BUSYBOX_MD5):
    archive = busybox_archive_path(paths)
    source = busybox_source_dir(paths)
    reference = busybox_reference_dir(paths)
    patches = busybox_patch_paths(paths)
    config = busybox_config_path(paths)
    manifest = _base_busybox_manifest(paths, archive, BUSYBOX_URL, md5)
    manifest.update(
        {
            "source_dir": str(source),
            "reference_dir": str(reference),
            "patches": [str(path) for path in patches],
            "config": str(config),
        }
    )
    return Task(
        id="busybox:prepare",
        domain="busybox",
        action="prepare",
        inputs=[archive, config, *patches],
        outputs=[source, source / ".config", source / ".smart-build-prepared.json"],
        deps=["busybox:fetch"],
        workdir=paths.work_dir / "busybox",
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="inputs",
        log_path=paths.logs_dir / "busybox-prepare.log",
        executor=_make_prepare_executor(paths, command_runner, md5),
        cache_extra={
            "busybox": {
                "version": BUSYBOX_VERSION,
                "source_dir": str(source),
                "patches": [str(path) for path in patches],
                "config": str(config),
            }
        },
        manifest_fields={"busybox": manifest},
    )


def busybox_build_task(paths, toolchain=None, command_runner=None, jobs=None):
    resolved_toolchain = toolchain if toolchain is not None else resolve_toolchain()
    fields = toolchain_task_fields(resolved_toolchain)
    source = busybox_source_dir(paths)
    install = busybox_install_dir(paths)
    sdk = smart_sdk_dir(paths)
    flags = _busybox_target_flags(resolved_toolchain, sdk)
    compat_outputs = _time64_compat_outputs(paths, resolved_toolchain)
    build_jobs = _normalize_jobs(jobs)
    commands = busybox_build_commands(
        resolved_toolchain.prefix,
        install,
        build_jobs,
        _time64_compat_object(paths, resolved_toolchain),
    )
    manifest = {
        **_base_busybox_manifest(paths, busybox_archive_path(paths), BUSYBOX_URL, BUSYBOX_MD5),
        "source_dir": str(source),
        "install_dir": str(install),
        "smart_sdk_dir": str(sdk),
        "target_flags": flags,
        "commands": commands,
        "jobs": build_jobs,
    }
    return Task(
        id="busybox:build",
        domain="busybox",
        action="build",
        inputs=[source / ".smart-build-prepared.json", source / ".config", sdk, *busybox_patch_paths(paths)],
        outputs=[install, install / "bin" / "busybox", *compat_outputs],
        deps=["busybox:prepare"],
        workdir=source,
        env={"MACHINE": paths.machine, **fields["env"], **flags},
        run_class="build",
        cache_policy="inputs",
        log_path=paths.logs_dir / "busybox-build.log",
        executor=_make_build_executor(paths, resolved_toolchain, commands, install, command_runner),
        cache_extra={
            **fields["cache_extra"],
            "busybox": {
                "version": BUSYBOX_VERSION,
                "source_dir": str(source),
                "install_dir": str(install),
                "smart_sdk_dir": str(sdk),
                "target_flags": flags,
                "commands": commands,
                "jobs": build_jobs,
            },
        },
        manifest_fields={**fields["manifest_fields"], "busybox": manifest},
    )


def busybox_stage_rootfs_task(paths):
    source_install = busybox_install_dir(paths)
    rootfs = busybox_rootfs_dir(paths)
    manifest_path = paths.staging_dir / BUSYBOX_ROOTFS_MANIFEST_NAME
    inittab = busybox_inittab_path(paths)
    return Task(
        id="busybox:stage-rootfs",
        domain="busybox",
        action="stage-rootfs",
        inputs=[source_install, inittab],
        outputs=[rootfs, manifest_path],
        deps=["busybox:build"],
        workdir=paths.work_dir / "busybox" / "stage-rootfs",
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="never",
        log_path=paths.logs_dir / "busybox-stage-rootfs.log",
        executor=_make_stage_rootfs_executor(paths, source_install, rootfs, manifest_path, inittab),
        cache_extra={
            "busybox_rootfs": {
                "install_dir": str(source_install),
                "path": str(rootfs),
                "inittab": str(inittab),
                "required_dirs": list(REQUIRED_ROOTFS_DIRS),
            }
        },
        manifest_fields={
            "busybox_rootfs": {
                "name": "busybox",
                "install_dir": str(source_install),
                "path": str(rootfs),
                "manifest": str(manifest_path),
                "inittab": str(inittab),
                "required_dirs": list(REQUIRED_ROOTFS_DIRS),
            }
        },
    )


def busybox_image_task(paths, command_runner=None, selection=None):
    selection = selection if selection is not None else resolve_rootfs_selection(paths.root, paths.machine)
    rootfs = busybox_rootfs_dir(paths)
    image = paths.images_dir / "busybox-rootfs.img"
    filesystem = selection.image_format or "ext4"
    size_mb = selection.image_size_mb
    size_mode = selection.image_size_mode
    if filesystem != "romfs":
        size_mb = 16 if size_mb is None else size_mb
        size_mode = "expandable" if size_mode is None else size_mode
    command = _image_command(filesystem, rootfs, image)
    return Task(
        id="busybox-rootfs:image",
        domain="image",
        action="busybox-rootfs",
        inputs=[rootfs],
        outputs=[image],
        deps=["busybox:stage-rootfs"],
        workdir=paths.work_dir / "busybox" / "image",
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="never",
        log_path=paths.logs_dir / "busybox-image.log",
        executor=_make_image_executor(rootfs, image, command, command_runner),
        cache_extra={
            "busybox_images": {
                "rootfs": str(rootfs),
                "busybox_rootfs": str(image),
                "filesystem": filesystem,
                "size_mb": size_mb,
                "size_mode": size_mode,
                "command": command,
            }
        },
        manifest_fields={
            "busybox_images": {
                "rootfs": str(rootfs),
                "busybox_rootfs": str(image),
                "filesystem": filesystem,
                "size_mb": size_mb,
                "size_mode": size_mode,
                "command": command,
            }
        },
    )


def busybox_archive_path(paths):
    return paths.root / "downloads" / BUSYBOX_ARCHIVE_NAME


def busybox_source_dir(paths):
    return paths.work_dir / "busybox" / BUSYBOX_SOURCE_DIR


def busybox_install_dir(paths):
    return busybox_source_dir(paths) / "install"


def busybox_rootfs_dir(paths):
    return paths.staging_dir / BUSYBOX_ROOTFS_DIR_NAME


def busybox_reference_dir(paths):
    return paths.root / "packages" / "busybox"


def busybox_config_path(paths):
    return busybox_reference_dir(paths) / "conf" / "def_config"


def busybox_inittab_path(paths):
    return busybox_reference_dir(paths) / "conf" / "inittab"


def busybox_patch_paths(paths):
    reference = busybox_reference_dir(paths)
    return (
        reference / "patches" / "01_aarch64.diff",
        reference / "patches" / "02_adapt_smart.diff",
    )


def busybox_build_commands(prefix, install, jobs, extra_ldlibs=None):
    extra_ldlibs_arg = [] if extra_ldlibs is None else [f"CONFIG_EXTRA_LDLIBS=-Wl,{extra_ldlibs}"]
    commands = [
        ["make", "oldconfig", f"CROSS_COMPILE={prefix}"],
        ["make", f"CROSS_COMPILE={prefix}", f"-j{jobs}", *extra_ldlibs_arg],
        ["make", f"CROSS_COMPILE={prefix}", f"CONFIG_PREFIX={install}", "install", *extra_ldlibs_arg],
    ]
    return commands


def _busybox_target_flags(toolchain, sdk):
    target = str(getattr(toolchain, "target", ""))
    prefix = str(getattr(toolchain, "prefix", ""))
    if target.startswith("aarch64-"):
        arch_cflags = "-march=armv8-a"
        sdk_arch = "aarch64/cortex-a"
    elif target.startswith("riscv64-"):
        arch_cflags = ""
        sdk_arch = "risc-v/rv64gc"
    elif target == "arm-none-eabi" or target.startswith("arm-"):
        arch_cflags = "-march=armv7-a -msoft-float"
        sdk_arch = "arm/cortex-a"
    else:
        raise SmartBuildError("BUILD", f"unsupported busybox target architecture: {target}")

    rt_thread = sdk / "rt-thread"
    lib_dir = sdk / "lib" / sdk_arch
    rt_lib_dir = rt_thread / "lib" / sdk_arch
    time64_compat = _needs_time64_compat(target)
    cflags = " ".join(
        item
        for item in (
            arch_cflags,
            "-fvisibility=hidden",
            "-O3",
            "-I.",
            f"-I{rt_thread / 'include'}",
            f"-I{rt_thread / 'components' / 'dfs'}",
            f"-I{rt_thread / 'components' / 'drivers'}",
            f"-I{rt_thread / 'components' / 'finsh'}",
            f"-I{rt_thread / 'components' / 'net'}",
        )
        if item
    )
    ldflags = (
        f"-L. -L{lib_dir} -L{rt_lib_dir} "
        "-Wl,--start-group -Wl,-whole-archive -lrtthread -Wl,-no-whole-archive -Wl,--end-group"
    )
    return {
        "SMART_BUSYBOX_CROSS_COMPILE": prefix,
        "SMART_SDK_LIB_DIR": str(lib_dir),
        "SMART_SDK_RT_LIB_DIR": str(rt_lib_dir),
        "SMART_BUSYBOX_CFLAGS": cflags,
        "SMART_BUSYBOX_LDFLAGS": ldflags,
        "SMART_BUSYBOX_TIME64_COMPAT": "1" if time64_compat else "",
    }


def _needs_time64_compat(target):
    return target == "arm-linux-musleabi"


def _time64_compat_outputs(source, toolchain):
    return _time64_compat_paths(source, toolchain)


def _time64_compat_object(paths, toolchain):
    compat_paths = _time64_compat_paths(paths, toolchain)
    if not compat_paths:
        return None
    return compat_paths[1]


def _time64_compat_paths(paths, toolchain):
    if not _needs_time64_compat(str(getattr(toolchain, "target", ""))):
        return []
    compat_dir = paths.work_dir / "busybox" / "time64-compat"
    return [compat_dir / TIME64_COMPAT_SOURCE_NAME, compat_dir / TIME64_COMPAT_OBJECT_NAME]


def _image_command(filesystem, rootfs, image):
    if filesystem == "ext4":
        return _mke2fs_command(rootfs, image)
    return []


def _mke2fs_command(rootfs, image):
    return [resolve_host_tool("mke2fs"), "-F", "-t", "ext4", "-d", str(rootfs), str(image)]


def verify_busybox_archive(path, expected_md5=BUSYBOX_MD5):
    archive = Path(path)
    if not archive.is_file():
        raise SmartBuildError("SOURCE", f"busybox archive not found: {archive}")
    digest = hashlib.md5()
    try:
        with archive.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SmartBuildError("SOURCE", f"failed to read busybox archive {archive}: {exc}") from exc
    actual = digest.hexdigest()
    if actual != expected_md5:
        raise SmartBuildError(
            "SOURCE",
            f"busybox archive md5 mismatch: {archive} expected {expected_md5} got {actual}",
        )
    return actual


def _make_fetch_executor(archive, url, md5, downloader, allow_network):
    fetcher = downloader or _download_file

    def executor(task, log):
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.is_file():
            actual_md5 = verify_busybox_archive(archive, md5)
            log.write(f"using existing busybox archive: {archive} md5={actual_md5}\n")
            _update_fetch_manifest(task, archive, url, md5, actual_md5, source="local")
            return 0
        if archive.exists() or archive.is_symlink():
            raise SmartBuildError("SOURCE", f"busybox archive path is not a regular file: {archive}")
        if not allow_network:
            raise SmartBuildError("SOURCE", f"busybox archive missing and network disabled: {archive}")

        temp_path = archive.with_name(f".{archive.name}.tmp-{os.getpid()}")
        _prepare_new_file_output(temp_path, "SOURCE")
        try:
            log.write(f"downloading busybox archive: {url} -> {archive}\n")
            fetcher(url, temp_path)
            if not temp_path.is_file():
                raise SmartBuildError("SOURCE", f"busybox download did not create archive: {temp_path}")
            actual_md5 = verify_busybox_archive(temp_path, md5)
            _prepare_new_file_output(archive, "SOURCE")
            temp_path.rename(archive)
            log.write(f"downloaded busybox archive: {archive} md5={actual_md5}\n")
            _update_fetch_manifest(task, archive, url, md5, actual_md5, source="download")
        finally:
            if temp_path.exists() or temp_path.is_symlink():
                _remove_path(temp_path)
        return 0

    return executor


def _make_prepare_executor(paths, command_runner, md5):
    runner = command_runner or _run_prepare_command

    def executor(task, log):
        archive = busybox_archive_path(paths)
        source = busybox_source_dir(paths)
        config = busybox_config_path(paths)
        patches = busybox_patch_paths(paths)
        for reference_file in (*patches, config):
            if not reference_file.is_file():
                raise SmartBuildError("SOURCE", f"busybox reference file not found: {reference_file}")

        verify_busybox_archive(archive, md5)
        _extract_busybox_archive(archive, source, log)
        for patch in patches:
            command = ["patch", "-p1", "-i", str(patch)]
            completed = runner(command, cwd=source, env=os.environ.copy())
            _write_completed_command(log, command, source, completed)
            if completed.returncode != 0:
                raise SmartBuildError(
                    "BUILD",
                    "busybox patch failed: command={command} exit code {exit_code} log={log_path}".format(
                        command=" ".join(command),
                        exit_code=completed.returncode,
                        log_path=task.log_path,
                    ),
                )

        shutil.copy2(config, source / ".config")
        prepared = {
            "version": BUSYBOX_VERSION,
            "archive": str(archive),
            "archive_md5": verify_busybox_archive(archive, md5),
            "source_dir": str(source),
            "patches": [str(path) for path in patches],
            "config": str(config),
            "source_checksum": path_record(source).get("sha256"),
        }
        (source / ".smart-build-prepared.json").write_text(
            json.dumps(prepared, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        task.manifest_fields["busybox"].update(prepared)
        log.write(f"prepared busybox source: {source}\n")
        return 0

    return executor


def _make_build_executor(paths, toolchain, commands, install, command_runner):
    runner = command_runner or _run_build_command

    def executor(task, log):
        source = busybox_source_dir(paths)
        if not (source / ".config").is_file():
            raise SmartBuildError("BUILD", f"busybox source missing .config: {source}")
        sdk = smart_sdk_dir(paths)
        if not sdk.is_dir():
            raise SmartBuildError("SOURCE", f"smart-sdk package not found: {sdk}")
        _validate_work_output(paths, install)
        _remove_path(install)
        env = _build_env(task.env, paths)
        _prepare_time64_compat(paths, source, toolchain, env, runner, log, task.log_path)
        for command in commands:
            completed = runner(list(command), cwd=source, env=env)
            _write_completed_command(log, command, source, completed)
            if completed.returncode != 0:
                raise SmartBuildError(
                    "BUILD",
                    "busybox build failed: command={command} exit code {exit_code} log={log_path}".format(
                        command=" ".join(command),
                        exit_code=completed.returncode,
                        log_path=task.log_path,
                    ),
                )
        busybox = install / "bin" / "busybox"
        if not busybox.is_file():
            raise SmartBuildError("BUILD", f"busybox install did not create output: {busybox}")
        task.manifest_fields["busybox"]["install_checksum"] = path_record(install).get("sha256")
        task.manifest_fields["busybox"]["busybox_binary"] = str(busybox)
        task.manifest_fields["busybox"]["busybox_checksum"] = path_record(busybox).get("sha256")
        log.write(f"installed busybox into: {install}\n")
        return 0

    return executor


def _prepare_time64_compat(paths, source, toolchain, env, runner, log, log_path):
    _remove_path(source / TIME64_COMPAT_SOURCE_NAME)
    _remove_path(source / TIME64_COMPAT_OBJECT_NAME)
    if env.get("SMART_BUSYBOX_TIME64_COMPAT") != "1":
        return
    compat_source, compat_object = _time64_compat_paths(paths, toolchain)
    compat_source.parent.mkdir(parents=True, exist_ok=True)
    compat_source.write_text(_time64_compat_source(), encoding="utf-8")
    command = [
        str(toolchain.gcc),
        *shlex.split(env.get("SMART_BUSYBOX_CFLAGS", "")),
        "-c",
        str(compat_source),
        "-o",
        str(compat_object),
    ]
    completed = runner(command, cwd=source, env=env)
    _write_completed_command(log, command, source, completed)
    if completed.returncode != 0:
        raise SmartBuildError(
            "BUILD",
            "busybox time64 compat build failed: command={command} exit code {exit_code} log={log_path}".format(
                command=" ".join(command),
                exit_code=completed.returncode,
                log_path=log_path,
            ),
        )


def _time64_compat_source():
    return (
        "#include <sys/select.h>\n"
        "#include <time.h>\n"
        "\n"
        "time_t __time64(time_t *t)\n"
        "{\n"
        "    return time(t);\n"
        "}\n"
        "\n"
        "int __select_time64(int nfds, fd_set *readfds, fd_set *writefds,\n"
        "                    fd_set *exceptfds, struct timeval *timeout)\n"
        "{\n"
        "    return select(nfds, readfds, writefds, exceptfds, timeout);\n"
        "}\n"
    )


def _make_stage_rootfs_executor(paths, source_install, rootfs, manifest_path, inittab):
    def executor(task, log):
        if not source_install.is_dir():
            raise SmartBuildError("ROOTFS", f"busybox install directory not found: {source_install}")
        if not inittab.is_file():
            raise SmartBuildError("ROOTFS", f"busybox inittab not found: {inittab}")
        _validate_staging_output(paths, rootfs)
        _remove_path(rootfs)
        rootfs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_install, rootfs, symlinks=True)
        source_map = {}
        for path in rootfs.rglob("*"):
            relative = path.relative_to(rootfs).as_posix()
            source_map[relative] = str(source_install / relative)

        for dirname in REQUIRED_ROOTFS_DIRS:
            directory = _rootfs_child(rootfs, dirname)
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o1777 if dirname == "tmp" else 0o755)
            source_map.setdefault(directory.relative_to(rootfs).as_posix(), "rootfs-directory")

        destination = _rootfs_child(rootfs, "etc/inittab")
        shutil.copy2(inittab, destination)
        source_map[destination.relative_to(rootfs).as_posix()] = str(inittab)

        var_run = _rootfs_child(rootfs, "var/run")
        if var_run.exists() or var_run.is_symlink():
            if var_run.is_dir() and not var_run.is_symlink():
                shutil.rmtree(var_run)
            else:
                var_run.unlink()
        var_run.symlink_to("../run")
        source_map[var_run.relative_to(rootfs).as_posix()] = "generated-symlink"

        manifest = _rootfs_manifest(rootfs, source_map)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        task.manifest_fields["busybox_rootfs"]["manifest"] = str(manifest_path)
        task.manifest_fields["busybox_rootfs"]["entry_count"] = len(manifest["entries"])
        task.manifest_fields["busybox_rootfs"]["checksum"] = path_record(rootfs).get("sha256")
        log.write(f"staged busybox rootfs: {rootfs}\n")
        log.write(f"wrote busybox rootfs manifest: {manifest_path}\n")
        return 0

    return executor


def _make_image_executor(rootfs, image, command, command_runner):
    runner = command_runner or _run_image_command

    def executor(task, log):
        if not rootfs.is_dir():
            raise SmartBuildError("IMAGE", f"busybox rootfs directory not found: {rootfs}")
        image_fields = task.manifest_fields["busybox_images"]
        filesystem = image_fields["filesystem"]
        if filesystem != "ext4":
            raise SmartBuildError("IMAGE", f"rootfs image format {filesystem} is not implemented")
        image.parent.mkdir(parents=True, exist_ok=True)
        _prepare_new_file_output(image, "IMAGE")
        image_size = _image_size(
            rootfs,
            configured_size_mb=image_fields["size_mb"],
            size_mode=image_fields["size_mode"],
        )
        with image.open("wb") as handle:
            handle.truncate(image_size)

        completed = runner(list(command), cwd=task.workdir, env=os.environ.copy())
        _write_completed_command(log, command, task.workdir, completed)
        if completed.returncode != 0:
            raise SmartBuildError(
                "IMAGE",
                "busybox rootfs image creation failed: command={command} exit code {exit_code} "
                "log={log_path}".format(
                    command=" ".join(command),
                    exit_code=completed.returncode,
                    log_path=task.log_path,
                ),
            )
        if not image.is_file() or image.stat().st_size == 0:
            raise SmartBuildError("IMAGE", f"mke2fs did not create a non-empty image: {image}")
        task.manifest_fields["busybox_images"]["size"] = image.stat().st_size
        task.manifest_fields["busybox_images"]["checksum"] = path_record(image).get("sha256")
        log.write(f"created busybox rootfs image: {image}\n")
        return 0

    return executor


def _extract_busybox_archive(archive, source, log):
    work_parent = source.parent / ".extract-work"
    _remove_path(work_parent)
    work_parent.mkdir(parents=True, exist_ok=True)
    try:
        _extract_tar_safely(archive, work_parent)
        extracted_source = _archive_source_root(work_parent)
        if not (extracted_source / "Makefile").is_file():
            raise SmartBuildError("SOURCE", f"busybox archive missing Makefile: {extracted_source}")
        _replace_directory(extracted_source, source)
        log.write(f"extracted busybox archive: {archive} -> {source}\n")
    finally:
        _remove_path(work_parent)


def _extract_tar_safely(archive, destination):
    try:
        with tarfile.open(archive) as handle:
            members = handle.getmembers()
            for member in members:
                _validate_archive_member(destination, member.name)
                if member.issym() or member.islnk():
                    raise SmartBuildError("SOURCE", f"unsafe busybox archive member link: {member.name}")
                if not (member.isfile() or member.isdir()):
                    raise SmartBuildError("SOURCE", f"unsupported busybox archive member type: {member.name}")
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning, module="tarfile")
                handle.extractall(destination, members=members)
    except (tarfile.TarError, OSError) as exc:
        raise SmartBuildError("SOURCE", f"failed to extract busybox archive {archive}: {exc}") from exc


def _validate_archive_member(destination, name):
    member_path = Path(name)
    if not name or member_path.is_absolute() or any(part in {"", ".", ".."} for part in member_path.parts):
        raise SmartBuildError("SOURCE", f"unsafe busybox archive member path: {name}")
    target = (destination / name).resolve()
    root = destination.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("SOURCE", f"unsafe busybox archive member path: {name}") from exc


def _archive_source_root(work_parent):
    expected = work_parent / BUSYBOX_SOURCE_DIR
    if expected.is_dir():
        return expected
    children = [child for child in work_parent.iterdir() if child.name != "__MACOSX"]
    directories = [child for child in children if child.is_dir()]
    if len(children) == 1 and directories:
        return directories[0]
    return work_parent


def _replace_directory(source, destination):
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=parent))
    temp_destination = temp_root / destination.name
    backup = None
    try:
        shutil.copytree(source, temp_destination, symlinks=True)
        if destination.exists() or destination.is_symlink():
            backup = _unique_backup_path(destination)
            destination.rename(backup)
        temp_destination.rename(destination)
        if backup is not None:
            _remove_path(backup)
    except Exception:
        if backup is not None and not destination.exists() and backup.exists():
            backup.rename(destination)
        raise
    finally:
        _remove_path(temp_root)


def _rootfs_manifest(rootfs_dir, source_map):
    entries = []
    for path in sorted(rootfs_dir.rglob("*"), key=lambda item: item.relative_to(rootfs_dir).as_posix()):
        if path.name == ROOTFS_MANIFEST and path.parent == rootfs_dir:
            continue
        record = path_record(path)
        relative = path.relative_to(rootfs_dir).as_posix()
        entries.append(
            {
                "path": relative,
                "type": record.get("type"),
                "mode": record.get("mode"),
                "source": source_map.get(relative, "generated"),
                "checksum": record.get("sha256"),
            }
        )
    return {
        "schema_version": 1,
        "name": "busybox",
        "entries": entries,
    }


def _rootfs_child(rootfs_dir, relative_path):
    relative = _safe_relative_path(relative_path)
    destination = rootfs_dir.joinpath(*relative.parts)
    root = rootfs_dir.resolve()
    resolved = destination.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("ROOTFS", f"rootfs install path escapes rootfs: {relative_path}") from exc
    return destination


def _safe_relative_path(raw_path):
    path = Path(raw_path)
    if path.is_absolute():
        path = Path(*path.parts[1:])
    if not path.parts:
        raise SmartBuildError("ROOTFS", f"empty rootfs path: {raw_path}")
    for part in path.parts:
        if part in {"", ".", ".."}:
            raise SmartBuildError("ROOTFS", f"unsafe rootfs path: {raw_path}")
    return path


def _image_size(rootfs_dir, configured_size_mb, size_mode):
    configured_size = configured_size_mb * IMAGE_BLOCK
    if size_mode == "fixed":
        return configured_size
    content_size = 0
    seen_files = set()
    for path in rootfs_dir.rglob("*"):
        if path.is_symlink():
            content_size += len(os.readlink(path))
        elif path.is_file():
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity in seen_files:
                continue
            seen_files.add(identity)
            content_size += stat.st_size
    requested = max(MIN_IMAGE_SIZE, configured_size, content_size * 4 + 8 * 1024 * 1024)
    return ((requested + IMAGE_BLOCK - 1) // IMAGE_BLOCK) * IMAGE_BLOCK


def _prepare_new_file_output(path, code):
    output = Path(path)
    if output.is_symlink():
        raise SmartBuildError(code, f"refusing to replace symlink output: {output}")
    if not output.exists():
        return
    if not output.is_file():
        raise SmartBuildError(code, f"refusing to replace non-file output: {output}")
    if output.stat().st_nlink > 1:
        raise SmartBuildError(code, f"refusing to replace hardlink output: {output}")
    output.unlink()


def _validate_work_output(paths, destination):
    work_root = paths.work_dir.resolve()
    target = Path(destination).resolve(strict=False)
    try:
        target.relative_to(work_root)
    except ValueError as exc:
        raise SmartBuildError("BUILD", f"busybox output path escapes work dir: {destination}") from exc
    if destination.exists() and not destination.is_dir():
        raise SmartBuildError("BUILD", f"busybox install output is not a directory: {destination}")
    if destination.is_symlink():
        raise SmartBuildError("BUILD", f"refusing to replace symlink output: {destination}")


def _validate_staging_output(paths, destination):
    staging_root = paths.staging_dir.resolve()
    target = Path(destination).resolve(strict=False)
    try:
        target.relative_to(staging_root)
    except ValueError as exc:
        raise SmartBuildError("ROOTFS", f"busybox rootfs path escapes staging dir: {destination}") from exc
    if destination.is_symlink():
        raise SmartBuildError("ROOTFS", f"refusing to replace symlink output: {destination}")
    if destination.exists() and not destination.is_dir():
        raise SmartBuildError("ROOTFS", f"refusing to replace non-directory output: {destination}")


def _remove_path(path):
    candidate = Path(path)
    if candidate.is_symlink() or candidate.is_file():
        candidate.unlink()
    elif candidate.is_dir():
        shutil.rmtree(candidate)


def _unique_backup_path(path):
    parent = path.parent
    stem = f".{path.name}.old-{os.getpid()}"
    candidate = parent / stem
    index = 0
    while candidate.exists() or candidate.is_symlink():
        index += 1
        candidate = parent / f"{stem}-{index}"
    return candidate


def _build_env(task_env, paths):
    env = os.environ.copy()
    env.update({key: str(value) for key, value in task_env.items()})
    env["FILE_DIRNAME"] = str(busybox_reference_dir(paths))
    env["SMART_SDK_DIR"] = str(smart_sdk_dir(paths))
    for key in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"):
        env.pop(key, None)
    return env


def _download_file(url, destination):
    try:
        with urllib.request.urlopen(url) as response, Path(destination).open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except OSError as exc:
        raise SmartBuildError("SOURCE", f"failed to download busybox archive {url}: {exc}") from exc


def _run_prepare_command(command, cwd, env):
    return _run_command(command, cwd, env, "BUILD")


def _run_build_command(command, cwd, env):
    return _run_command(command, cwd, env, "BUILD")


def _run_image_command(command, cwd, env):
    return _run_command(command, cwd, env, "IMAGE")


def _run_command(command, cwd, env, code):
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
        raise SmartBuildError(code, f"failed to run command {command}: {exc}") from exc


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


def _base_busybox_manifest(paths, archive, url, md5):
    return {
        "version": BUSYBOX_VERSION,
        "archive": str(archive),
        "url": url,
        "md5": md5,
        "reference_dir": str(busybox_reference_dir(paths)),
    }


def _update_fetch_manifest(task, archive, url, expected_md5, actual_md5, source):
    task.manifest_fields["busybox"].update(
        {
            "archive": str(archive),
            "url": url,
            "md5": expected_md5,
            "actual_md5": actual_md5,
            "source": source,
            "archive_sha256": path_record(archive).get("sha256"),
        }
    )


def _normalize_jobs(jobs):
    if jobs is None:
        return max(1, os.cpu_count() or 1)
    try:
        value = int(jobs)
    except (TypeError, ValueError) as exc:
        raise SmartBuildError("CONFIG", f"jobs must be a positive integer: {jobs}") from exc
    if value <= 0:
        raise SmartBuildError("CONFIG", f"jobs must be a positive integer: {jobs}")
    return value
