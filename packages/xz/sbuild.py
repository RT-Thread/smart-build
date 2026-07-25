#!/usr/bin/env python3
"""Build xz and static liblzma."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


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
    if source.is_symlink():
        source = source.resolve()
    if not source.is_file():
        raise SystemExit(f"expected file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(mode)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f"expected directory not found: {source}")
    shutil.copytree(source, destination, symlinks=False)


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)

    run(
        ["patch", "-p1", "--batch", "--forward", "-i", str(source_dir / "01_src_xz_hardware.diff")],
        cwd=source_dir,
    )
    reset_dir(build_dir)
    reset_dir(dest_dir)
    reset_dir(stage_dir)
    configure = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        "--prefix=/usr",
        "--libdir=/usr/lib",
        "--enable-static=yes",
        "--enable-shared=no",
        "--enable-threads=posix",
        "--disable-debug",
        "--disable-doc",
    ]
    run([item for item in configure if item != "--host="], cwd=build_dir)
    run(["make", "-j" + jobs], cwd=build_dir)
    run(["make", "install", f"DESTDIR={dest_dir}"], cwd=build_dir)

    copy_file(dest_dir / "usr/bin/xz", stage_dir / "usr/bin/xz", 0o755)
    copy_tree(dest_dir / "usr/include/lzma", stage_dir / "usr/include/lzma")
    copy_file(dest_dir / "usr/include/lzma.h", stage_dir / "usr/include/lzma.h", 0o644)
    copy_file(dest_dir / "usr/lib/liblzma.a", stage_dir / "usr/lib/liblzma.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
