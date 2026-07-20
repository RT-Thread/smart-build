#!/usr/bin/env python3
"""Build Lua for the Smart package stage."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def required_path(name: str) -> Path:
    return Path(required_env(name))


def require(path: Path, label: str = "dependency or upstream file") -> None:
    if not path.exists():
        raise SystemExit(f"missing required {label}: {path}")


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None, allow_failure: bool = False) -> None:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=command_env, check=False)
    if completed.returncode != 0 and not allow_failure:
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


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    install_dir = work_dir / "dest"

    require(source_dir / "src" / "lua.c", "upstream file")
    reset_dir(install_dir)
    reset_dir(stage_dir)

    make_vars = [
        f"CC={required_env('CC')}",
        f"AR={os.environ.get('AR', 'ar')} rcu",
        f"RANLIB={os.environ.get('RANLIB', 'ranlib')}",
        "MYCFLAGS=-DLUA_USE_POSIX",
        "MYLDFLAGS=",
        "MYLIBS=",
    ]
    run(["make", "clean"], cwd=source_dir, allow_failure=True)
    run(["make", "generic", *make_vars], cwd=source_dir)
    run(["make", f"INSTALL_TOP={install_dir / 'usr'}", "install"], cwd=source_dir)

    copy_file(install_dir / "usr" / "bin" / "lua", stage_dir / "usr" / "bin" / "lua", 0o755)
    copy_file(install_dir / "usr" / "lib" / "liblua.a", stage_dir / "usr" / "lib" / "liblua.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
