#!/usr/bin/env python3
import os
import subprocess

source = os.environ["SMART_BUILD_SOURCE_DIR"]
stage = os.environ["SMART_BUILD_STAGE_DIR"]
env = os.environ.copy()
env.setdefault("DESTDIR", stage)
commands = []
configure = os.path.join(source, "configure")
if os.path.isfile(configure):
    commands.append(
        [
            configure,
            "--host=" + env["SMART_BUILD_TARGET"],
            "--prefix=/usr",
            "--disable-shared",
            "--enable-static",
        ]
    )
commands.extend([["make"], ["make", "DESTDIR=" + stage, "install"]])
for command in commands:
    subprocess.run(command, cwd=source, env=env, check=True)
