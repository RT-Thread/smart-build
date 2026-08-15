#!/usr/bin/env python3
import os
import shutil
import stat
import subprocess
from pathlib import Path

source = os.environ["SMART_BUILD_SOURCE_DIR"]
stage = os.environ["SMART_BUILD_STAGE_DIR"]
work = Path(os.environ["SMART_BUILD_WORK_DIR"])
env = os.environ.copy()
env.setdefault("DESTDIR", stage)

packages_stage = Path(
    os.environ.get("SMART_BUILD_PACKAGES_STAGING_DIR", "")
)
ncurses_root = packages_stage / "ncurses"
ncurses_include = ncurses_root / "usr" / "include" / "ncurses"
ncurses_lib = ncurses_root / "usr" / "lib"
if not (ncurses_include / "curses.h").is_file():
    raise SystemExit(f"missing ncurses header: {ncurses_include / 'curses.h'}")
if not (ncurses_lib / "libncurses.a").is_file():
    raise SystemExit(f"missing ncurses library: {ncurses_lib / 'libncurses.a'}")
compat_include = work / "compat-include"
linux_vt = compat_include / "linux" / "vt.h"
linux_vt.parent.mkdir(parents=True, exist_ok=True)
linux_vt.write_text(
    """#ifndef SMART_BUILD_LINUX_VT_H
#define SMART_BUILD_LINUX_VT_H
struct vt_stat {
    unsigned short v_active;
    unsigned short v_signal;
    unsigned short v_state;
    unsigned short v_mode;
    unsigned short v_waitv;
};
#define VT_GETSTATE 0x5603
#endif
""",
    encoding="ascii",
)
env["CPPFLAGS"] = (
    f"-I{compat_include} -I{ncurses_include} "
    f"-I{ncurses_root / 'usr' / 'include'}"
)
env["LDFLAGS"] = f"-L{ncurses_lib}"
env["LIBS"] = "-lncurses"
env["ac_cv_prog_NCURSESW_CONFIG"] = "false"
env["CURSES_LIB"] = "-lncurses"
env["PKG_CONFIG"] = "false"
env["NCURSESW_CONFIG"] = "no"
env["NCURSESW_CFLAGS"] = ""
env["NCURSESW_LIBS"] = ""
env["NCURSES_CFLAGS"] = f"-I{ncurses_include} -I{ncurses_root / 'usr' / 'include'}"
env["NCURSES_LIBS"] = "-lncurses"


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


commands = []
configure = os.path.join(source, "configure")
if os.path.isfile(configure):
    commands.append([configure, "--host=" + env["SMART_BUILD_TARGET"], "--prefix=/usr"])
commands.extend([["make"], ["make", "DESTDIR=" + stage, "install"]])
for command in commands:
    subprocess.run(command, cwd=source, env=env, check=True)
materialize_internal_symlinks(stage)
