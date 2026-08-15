#!/usr/bin/env python3
import os
import shutil
import stat
import subprocess
from pathlib import Path

source = os.environ["SMART_BUILD_SOURCE_DIR"]
stage = os.environ["SMART_BUILD_STAGE_DIR"]
env = os.environ.copy()
env.setdefault("DESTDIR", stage)
packages_stage = Path(os.environ["SMART_BUILD_PACKAGES_STAGING_DIR"])
work = Path(os.environ["SMART_BUILD_WORK_DIR"])
glib_root = packages_stage / "libglib2"
ncurses_root = packages_stage / "ncurses"
glib_include = glib_root / "usr" / "include" / "glib-2.0"
glib_lib = glib_root / "usr" / "lib"
ffi_lib = packages_stage / "libffi" / "usr" / "lib"
pcre2_lib = packages_stage / "pcre2" / "usr" / "lib"
zlib_lib = packages_stage / "zlib" / "lib"
ncurses_include = ncurses_root / "usr" / "include" / "ncurses"
ncurses_lib = ncurses_root / "usr" / "lib"
for required in (
    glib_include / "glib.h",
    ncurses_include / "curses.h",
):
    if not required.is_file():
        raise SystemExit(f"missing required dependency file: {required}")


def materialize_internal_symlinks(root: Path) -> None:
    package_root = root.resolve()
    for candidate in sorted(package_root.rglob("*")):
        if not candidate.is_symlink():
            continue
        target = candidate.resolve()
        try:
            target.relative_to(package_root)
        except ValueError as exc:
            raise SystemExit(f"package symlink escapes staging directory: {candidate}") from exc
        if not target.is_file():
            raise SystemExit(f"package symlink target is not a file: {candidate}")
        mode = stat.S_IMODE(target.stat().st_mode)
        candidate.unlink()
        shutil.copy2(target, candidate)
        candidate.chmod(mode)
env["PKG_CONFIG"] = "false"
env["CPPFLAGS"] = (
    f"-I{glib_include} -I{glib_lib / 'glib-2.0' / 'include'} "
    f"-I{ncurses_include} -I{ncurses_root / 'usr' / 'include'} "
    "-DNCURSES_WIDECHAR=0"
)
env["LDFLAGS"] = (
    f"-L{glib_lib} -L{ncurses_lib} -L{ffi_lib} "
    f"-L{pcre2_lib} -L{zlib_lib}"
)
env["GLIB_CFLAGS"] = env["CPPFLAGS"]
env["GLIB_LIBS"] = (
    f"-L{glib_lib} -L{ffi_lib} -L{pcre2_lib} -L{zlib_lib} "
    f"-lgmodule-2.0 -lglib-2.0 -lffi -lpcre2-8 -lz -latomic -lm -pthread"
)
env["NCURSES_CFLAGS"] = f"-I{ncurses_include} -I{ncurses_root / 'usr' / 'include'}"
env["NCURSES_LIBS"] = f"-L{ncurses_lib} -lncurses"
pkgconfig = work / "pkgconfig"
if pkgconfig.exists():
    import shutil

    shutil.rmtree(pkgconfig)
pkgconfig.mkdir(parents=True)
glib_cflags = f"-I{glib_root / 'usr' / 'include' / 'glib-2.0'} -I{glib_root / 'usr' / 'lib' / 'glib-2.0' / 'include'}"
glib_libs = f"-L{glib_lib} -lgmodule-2.0 -lglib-2.0 -lffi -lpcre2-8 -lz -latomic -lm -pthread"
(pkgconfig / "glib-2.0.pc").write_text(
    f"Name: glib-2.0\nDescription: GLib\nVersion: 2.88.3\nCflags: {glib_cflags}\nLibs: {glib_libs}\n",
    encoding="ascii",
)
(pkgconfig / "gmodule-no-export-2.0.pc").write_text(
    f"Name: gmodule-no-export-2.0\nDescription: GLib modules\nVersion: 2.88.3\nCflags: {glib_cflags}\nLibs: {glib_libs}\n",
    encoding="ascii",
)
env["PKG_CONFIG"] = "/usr/bin/pkg-config"
env["PKG_CONFIG_PATH"] = str(pkgconfig)
env.pop("PKG_CONFIG_LIBDIR", None)
commands = []
configure = os.path.join(source, "configure")
if os.path.isfile(configure):
    commands.append(
        [
            configure,
            "--host=" + env["SMART_BUILD_TARGET"],
            "--prefix=/usr",
            "--with-screen=ncurses",
            "--without-gpm-mouse",
            "--disable-vfs-sftp",
            "--without-x",
        ]
    )
commands.extend([["make"], ["make", "DESTDIR=" + stage, "install"]])
for command in commands:
    subprocess.run(command, cwd=source, env=env, check=True)
materialize_internal_symlinks(Path(stage))
