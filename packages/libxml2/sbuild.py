#!/usr/bin/env python3
"""Build static libxml2 against staged libiconv."""

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


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=command_env, check=False)
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


def dependency_prefix(package: str, required: str) -> Path:
    root = required_path("SMART_BUILD_PACKAGES_STAGING_DIR") / package
    for prefix in (root / "usr", root):
        if (prefix / required).is_file():
            return prefix
    raise SystemExit(f"missing dependency output: {root}/{required}")


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)
    iconv = dependency_prefix("libiconv", "lib/libiconv.a")

    run(["autoreconf", "-fiv"], cwd=source_dir)
    reset_dir(build_dir)
    reset_dir(dest_dir)
    reset_dir(stage_dir)
    env = {
        "CPPFLAGS": f"-I{iconv / 'include'}",
        "LDFLAGS": f"-L{iconv / 'lib'}",
        "LIBS": "-liconv",
    }
    configure = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        "--prefix=/usr",
        "--libdir=/usr/lib",
        "--enable-static=yes",
        "--enable-shared=no",
        "--without-zlib",
        "--without-lzma",
        "--without-python",
        "--without-debug",
        "--without-mem-debug",
        "--without-run-debug",
        "--disable-ipv6",
        f"--with-iconv={iconv}",
    ]
    run([item for item in configure if item != "--host="], cwd=build_dir, env=env)
    run(["make", "-j" + jobs], cwd=build_dir, env=env)
    run(["make", "install", f"DESTDIR={dest_dir}"], cwd=build_dir, env=env)

    copy_tree(dest_dir / "usr/include/libxml2", stage_dir / "usr/include/libxml2")
    copy_file(dest_dir / "usr/lib/libxml2.a", stage_dir / "usr/lib/libxml2.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
