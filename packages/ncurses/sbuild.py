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


def copy_headers(source_dir: Path, destination_dir: Path) -> None:
    source_root = source_dir.resolve()
    for source in sorted(source_dir.iterdir()):
        if source.is_symlink():
            resolved = source.resolve()
            try:
                resolved.relative_to(source_root)
            except ValueError as exc:
                raise SystemExit(f"ncurses header link escapes source directory: {source}") from exc
            copy_file(source, destination_dir / source.name, 0o644)
            continue
        if source.is_dir():
            copy_headers(source, destination_dir / source.name)
            continue
        if not source.is_file():
            raise SystemExit(f"unexpected ncurses header entry: {source}")
        copy_file(source, destination_dir / source.name, 0o644)


# Serial consoles and common ncurses clients need these compiled descriptions.
TERMINFO_ENTRIES = (
    "ansi",
    "dumb",
    "linux",
    "putty",
    "putty-256color",
    "screen",
    "screen-256color",
    "tmux",
    "tmux-256color",
    "vt100",
    "vt102",
    "vt220",
    "xterm",
    "xterm-256color",
    "xterm-color",
)


def materialize_terminfo_links(root: Path) -> None:
    package_root = root.resolve()
    for candidate in sorted(package_root.rglob("*")):
        if not candidate.is_symlink():
            continue
        target = candidate.resolve()
        try:
            target.relative_to(package_root)
        except ValueError as exc:
            raise SystemExit(f"terminfo symlink escapes directory: {candidate}") from exc
        if not target.is_file():
            raise SystemExit(f"terminfo symlink target is not a file: {candidate}")
        candidate.unlink()
        shutil.copy2(target, candidate)
        candidate.chmod(0o644)


def install_terminfo(source_dir: Path, dest_dir: Path) -> Path:
    terminfo_src = source_dir / "misc" / "terminfo.src"
    if not terminfo_src.is_file():
        raise SystemExit(f"missing terminfo source: {terminfo_src}")
    tic = shutil.which("tic")
    if not tic:
        raise SystemExit("host tic is required to compile a target terminfo database")
    output = dest_dir / "usr/share/terminfo"
    reset_dir(output)
    run(
        [
            tic,
            "-x",
            "-o",
            str(output),
            "-e",
            ",".join(TERMINFO_ENTRIES),
            str(terminfo_src),
        ],
        cwd=source_dir,
    )
    materialize_terminfo_links(output)
    linux_entry = output / "l" / "linux"
    if not linux_entry.is_file():
        raise SystemExit(f"failed to compile linux terminfo: {linux_entry}")
    return output


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
    terminfo_dir = install_terminfo(source_dir, dest_dir)

    copy_headers(dest_dir / "usr/include/ncurses", stage_dir / "usr/include/ncurses")
    copy_file(dest_dir / "usr/lib/libncurses.a", stage_dir / "usr/lib/libncurses.a", 0o644)
    copy_headers(terminfo_dir, stage_dir / "usr/share/terminfo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
