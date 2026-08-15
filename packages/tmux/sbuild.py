#!/usr/bin/env python3
"""Build static tmux against staged ncurses and libevent."""

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
    if source.is_symlink():
        source = source.resolve()
    if not source.is_file():
        raise SystemExit(f"expected file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(mode)


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
    include_dir = work_dir / "ncurses-compat"
    jobs = str(os.cpu_count() or 1)
    ncurses = dependency_prefix("ncurses", "lib/libncurses.a")
    libevent = dependency_prefix("libevent", "lib/libevent.a")

    run(
        ["patch", "-p1", "--batch", "--forward", "-i", str(source_dir / "tmux-3.3a.patch")],
        cwd=source_dir,
    )
    (source_dir / "compat/forkpty-linux.c").touch()
    reset_dir(build_dir)
    reset_dir(dest_dir)
    reset_dir(stage_dir)
    reset_dir(include_dir)
    copy_file(source_dir / "tmux-ncurses-dll.h", include_dir / "ncurses/ncurses_dll.h", 0o644)
    copy_file(source_dir / "tmux-unctrl.h", include_dir / "ncurses/unctrl.h", 0o644)
    copy_file(source_dir / "tmux-ncurses.h", include_dir / "ncurses.h", 0o644)
    copy_file(source_dir / "tmux-term.h", include_dir / "term.h", 0o644)
    env = {
        "CPPFLAGS": (
            f"-DNCURSES_NOMACROS -I{include_dir} -I{ncurses / 'include'} "
            f"-I{ncurses / 'include/ncurses'} -I{libevent / 'include'}"
        ),
        "LDFLAGS": f"-L{ncurses / 'lib'} -L{libevent / 'lib'}",
        "LIBS": "-levent -lncurses",
        "PKG_CONFIG": "false",
    }
    configure = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        "--prefix=/usr",
        "--libdir=/usr/lib",
        "--enable-static",
    ]
    run([item for item in configure if item != "--host="], cwd=build_dir, env=env)
    run(["make", "-j" + jobs], cwd=build_dir, env=env)
    run(["make", "install", f"DESTDIR={dest_dir}"], cwd=build_dir, env=env)

    copy_file(dest_dir / "usr/bin/tmux", stage_dir / "usr/bin/tmux", 0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
