#!/usr/bin/env python3
"""Build uhttpd with CGI and statically linked Lua support."""

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


def dependency_prefix(package: str, required: str) -> Path:
    root = required_path("SMART_BUILD_PACKAGES_STAGING_DIR") / package
    for prefix in (root / "usr", root):
        if (prefix / required).is_file():
            return prefix
    raise SystemExit(f"missing dependency output: {root}/{required}")


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    jobs = str(os.cpu_count() or 1)
    lua = dependency_prefix("lua", "lib/liblua.a")

    run(
        ["patch", "-p1", "--batch", "--forward", "-i", str(source_dir / "02_uhttpd.diff")],
        cwd=source_dir,
    )
    run(
        ["patch", "-p1", "--batch", "--forward", "-i", str(source_dir / "03_lua_5_5.diff")],
        cwd=source_dir,
    )
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    env = os.environ.copy()
    env["CFLAGS"] = (env.get("CFLAGS", "") + f" -O2 -I{source_dir}").strip()
    env["LDFLAGS"] = (env.get("LDFLAGS", "") + f" -L{lua / 'lib'}").strip()
    run(["make", "clean"], cwd=source_dir, env=env)
    run(
        [
            "make",
            "-j" + jobs,
            "CGI_SUPPORT=1",
            "LUA_SUPPORT=1",
            "TLS_SUPPORT=0",
            f"CC={os.environ['CC']}",
            f"AR={os.environ['AR']}",
            f"RANLIB={os.environ['RANLIB']}",
            "compile",
        ],
        cwd=source_dir,
        env=env,
    )
    copy_file(source_dir / "uhttpd", stage_dir / "usr/bin/uhttpd", 0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
