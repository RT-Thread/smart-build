#!/usr/bin/env python3
"""Build Vim with staged ncurses support."""

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


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
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
    dest_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)
    ncurses = dependency_prefix("ncurses", "lib/libncurses.a")

    reset_dir(dest_dir)
    reset_dir(stage_dir)
    env = os.environ.copy()
    env.update(
        {
            "CPPFLAGS": f"-I{ncurses / 'include'} -I{ncurses / 'include/ncurses'}",
            "LDFLAGS": f"-L{ncurses / 'lib'}",
            "LIBS": "-lncurses",
            "ac_cv_sizeof_int": "4",
            "vim_cv_getcwd_broken": "no",
            "vim_cv_memmove_handles_overlap": "yes",
            "vim_cv_stat_ignores_slash": "yes",
            "vim_cv_tgetent": "zero",
            "vim_cv_terminfo": "yes",
            "vim_cv_toupper_broken": "no",
        }
    )
    configure = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        "--prefix=/usr",
        "--libdir=/usr/lib",
        "--with-features=huge",
        "--disable-gui",
        "--without-x",
        "--disable-selinux",
        "--disable-acl",
        "--with-tlib=ncurses",
    ]
    run([item for item in configure if item != "--host="], cwd=source_dir, env=env)
    run(["make", "-j" + jobs], cwd=source_dir, env=env)
    run(["make", "install", f"DESTDIR={dest_dir}"], cwd=source_dir, env=env)

    copy_file(dest_dir / "usr/bin/vim", stage_dir / "usr/bin/vim", 0o755)
    copy_tree(dest_dir / "usr/share/vim", stage_dir / "usr/share/vim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
