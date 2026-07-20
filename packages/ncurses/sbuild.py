#!/usr/bin/env python3
"""Build ncurses as a static Smart package."""

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
    path.mkdir(parents=True, exist_ok=True)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=command_env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def copy_file(source: Path, destination: Path, mode: int) -> None:
    if source.is_symlink():
        source = source.resolve()
    if not source.is_file():
        raise SystemExit(f"expected file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    shutil.copy2(source, destination)
    destination.chmod(mode)


def configure(source_dir: Path, build_dir: Path, options: list[str], env: dict[str, str] | None = None) -> None:
    command = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        *options,
    ]
    run([item for item in command if item != "--host="], cwd=build_dir, env=env)


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)

    reset_dir(build_dir)
    reset_dir(dest_dir)
    configure(
        source_dir,
        build_dir,
        [
            "--prefix=/usr",
            "--libdir=/usr/lib",
            "--includedir=/usr/include/ncurses",
            "--without-shared",
            "--with-normal",
            "--without-debug",
            "--without-ada",
            "--without-cxx",
            "--without-cxx-binding",
            "--without-progs",
            "--without-tests",
            "--without-manpages",
            "--without-dlsym",
            "--enable-termcap",
            "--disable-widec",
        ],
    )
    run(["make", "-j" + jobs], cwd=build_dir)
    run(["make", "install.libs", "install.includes", f"DESTDIR={dest_dir}"], cwd=build_dir)

    copy_file(dest_dir / "usr/include/ncurses/curses.h", stage_dir / "usr/include/ncurses/curses.h", 0o644)
    copy_file(dest_dir / "usr/lib/libncurses.a", stage_dir / "usr/lib/libncurses.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
