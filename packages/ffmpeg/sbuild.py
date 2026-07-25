#!/usr/bin/env python3
"""Build static FFmpeg libraries and tools."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


LIBRARIES = (
    "avcodec",
    "avdevice",
    "avfilter",
    "avformat",
    "avutil",
    "postproc",
    "swresample",
    "swscale",
)


def required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def run(command: list[str], cwd: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=os.environ.copy(), check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def copy_file(source: Path, destination: Path, mode: int) -> None:
    if not source.is_file():
        raise SystemExit(f"expected file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(mode)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f"expected directory not found: {source}")
    shutil.copytree(source, destination, symlinks=False)


def target_arch() -> str:
    target = os.environ.get("SMART_BUILD_TARGET", "").lower()
    if "riscv64" in target:
        return "riscv64"
    if "aarch64" in target or "arm64" in target:
        return "aarch64"
    if "arm" in target:
        return "arm"
    raise SystemExit(f"unsupported FFmpeg target: {target or '<empty>'}")


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)

    reset_dir(build_dir)
    reset_dir(dest_dir)
    reset_dir(stage_dir)
    configure = [
        str(source_dir / "configure"),
        "--prefix=/usr",
        "--enable-cross-compile",
        "--target-os=none",
        f"--arch={target_arch()}",
        f"--cross-prefix={os.environ.get('SMART_BUILD_CROSS_COMPILE', '')}",
        f"--cc={os.environ['CC']}",
        f"--cxx={os.environ['CXX']}",
        f"--ar={os.environ['AR']}",
        f"--ranlib={os.environ['RANLIB']}",
        f"--strip={os.environ['STRIP']}",
        "--enable-static",
        "--enable-gpl",
        "--disable-shared",
        "--disable-doc",
        "--disable-debug",
        "--disable-autodetect",
        "--disable-x86asm",
    ]
    run(configure, cwd=build_dir)
    run(["make", "-j" + jobs], cwd=build_dir)
    run(["make", "install", f"DESTDIR={dest_dir}"], cwd=build_dir)

    for name in ("ffmpeg", "ffprobe"):
        copy_file(dest_dir / "usr/bin" / name, stage_dir / "usr/bin" / name, 0o755)
    for name in LIBRARIES:
        copy_tree(dest_dir / "usr/include" / f"lib{name}", stage_dir / "usr/include" / f"lib{name}")
        copy_file(
            dest_dir / "usr/lib" / f"lib{name}.a",
            stage_dir / "usr/lib" / f"lib{name}.a",
            0o644,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
