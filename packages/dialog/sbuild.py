#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path

source = os.environ["SMART_BUILD_SOURCE_DIR"]
stage = os.environ["SMART_BUILD_STAGE_DIR"]
env = os.environ.copy()
env.setdefault("DESTDIR", stage)
packages_stage = Path(os.environ["SMART_BUILD_PACKAGES_STAGING_DIR"])
ncurses_root = packages_stage / "ncurses"
iconv_root = packages_stage / "libiconv"
ncurses_include = ncurses_root / "usr" / "include" / "ncurses"
ncurses_lib = ncurses_root / "usr" / "lib"
iconv_include = iconv_root / "usr" / "include"
iconv_lib = iconv_root / "usr" / "lib"
if not (ncurses_include / "curses.h").is_file():
    raise SystemExit(f"missing ncurses header: {ncurses_include / 'curses.h'}")
if not (ncurses_lib / "libncurses.a").is_file():
    raise SystemExit(f"missing ncurses library: {ncurses_lib / 'libncurses.a'}")
env["CPPFLAGS"] = f"-I{ncurses_include} -I{ncurses_root / 'usr' / 'include'} -I{iconv_include}"
env["LDFLAGS"] = f"-L{ncurses_lib} -L{iconv_lib}"
env["LIBS"] = "-lncurses -liconv"
env["CURSES_LIB"] = "-lncurses"
env["NCURSES_CFLAGS"] = f"-I{ncurses_include} -I{ncurses_root / 'usr' / 'include'}"
env["NCURSES_LIBS"] = f"-L{ncurses_lib} -lncurses"
env["PKG_CONFIG"] = "false"
commands = []
configure = os.path.join(source, "configure")
if os.path.isfile(configure):
    commands.append([configure, "--host=" + env["SMART_BUILD_TARGET"], "--prefix=/usr"])
commands.extend([["make"], ["make", "DESTDIR=" + stage, "install"]])
for command in commands:
    subprocess.run(command, cwd=source, env=env, check=True)
