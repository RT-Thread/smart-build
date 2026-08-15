#!/usr/bin/env python3
import shutil
import stat
import os
import subprocess
from pathlib import Path

source = os.environ["SMART_BUILD_SOURCE_DIR"]
stage = os.environ["SMART_BUILD_STAGE_DIR"]
env = os.environ.copy()
configure = os.path.join(source, "configure")
if os.path.isfile(configure):
    subprocess.run([configure, "--host=" + env["SMART_BUILD_TARGET"], "--prefix=/usr"], cwd=source, env=env, check=True)
subprocess.run(["make"], cwd=source, env=env, check=True)
subprocess.run(["make", f"PREFIX={Path(stage) / 'usr'}", "install"], cwd=source, env=env, check=True)

def materialize_internal_symlinks(root: str) -> None:
    package_root = Path(root).resolve()
    for candidate in sorted(package_root.rglob("*")):
        if not candidate.is_symlink():
            continue
        target = candidate.resolve()
        try:
            target.relative_to(package_root)
        except ValueError as exc:
            raise RuntimeError(f"package symlink escapes staging directory: {candidate}") from exc
        if not target.is_file():
            raise RuntimeError(f"package symlink target is not a file: {candidate}")
        mode = stat.S_IMODE(target.stat().st_mode)
        candidate.unlink()
        shutil.copy2(target, candidate)
        candidate.chmod(mode)


materialize_internal_symlinks(stage)
