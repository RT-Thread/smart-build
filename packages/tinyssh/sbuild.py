#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess

import shutil
import stat


def materialize_internal_symlinks(root):
    root = os.path.realpath(root)
    for candidate in sorted(Path(root).rglob("*")):
        if not candidate.is_symlink():
            continue
        target = candidate.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"package symlink escapes staging directory: {candidate}") from exc
        if not target.is_file():
            raise RuntimeError(f"package symlink target is not a file: {candidate}")
        mode = stat.S_IMODE(target.stat().st_mode)
        candidate.unlink()
        shutil.copy2(target, candidate)
        candidate.chmod(mode)


source = os.environ["SMART_BUILD_SOURCE_DIR"]
stage = os.environ["SMART_BUILD_STAGE_DIR"]
env = os.environ.copy()
env.setdefault("DESTDIR", stage)
commands = []
configure = os.path.join(source, "configure")
if os.path.isfile(configure):
    commands.append([configure, "--host=" + env["SMART_BUILD_TARGET"], "--prefix=/usr"])
commands.append(["make", 'cross-compile'])
commands.append(["make", "DESTDIR=" + stage, "install"])
for command in commands:
    subprocess.run(command, cwd=source, env=env, check=True)
materialize_internal_symlinks(stage)
