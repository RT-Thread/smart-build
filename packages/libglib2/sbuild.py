#!/usr/bin/env python3
"""Build GLib with Meson against the Smart package staging dependencies."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


def required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def write_pkgconfig(directory: Path, name: str, version: str, include: Path, lib: Path, library: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.pc").write_text(
        "prefix=/usr\n"
        f"includedir={include}\n"
        f"libdir={lib}\n\n"
        f"Name: {name}\nDescription: {name} dependency\nVersion: {version}\n"
        f"Cflags: -I{include}\nLibs: -L{lib} -l{library}\n",
        encoding="ascii",
    )


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


def main() -> int:
    source = required_path("SMART_BUILD_SOURCE_DIR")
    work = required_path("SMART_BUILD_WORK_DIR")
    stage = required_path("SMART_BUILD_STAGE_DIR")
    staging = required_path("SMART_BUILD_PACKAGES_STAGING_DIR")
    build = work / "meson-build"
    pkgconfig = work / "pkgconfig"
    if build.exists():
        shutil.rmtree(build)
    if pkgconfig.exists():
        shutil.rmtree(pkgconfig)
    pkgconfig.mkdir(parents=True)

    dependency_roots = {
        name: staging / name / "usr"
        for name in ("libffi", "pcre2", "zlib")
    }
    write_pkgconfig(
        pkgconfig,
        "libffi",
        "3.5.2",
        dependency_roots["libffi"] / "include",
        dependency_roots["libffi"] / "lib",
        "ffi",
    )
    write_pkgconfig(
        pkgconfig,
        "libpcre2-8",
        "10.47",
        dependency_roots["pcre2"] / "include",
        dependency_roots["pcre2"] / "lib",
        "pcre2-8",
    )
    write_pkgconfig(
        pkgconfig,
        "zlib",
        "1.3.2",
        staging / "zlib" / "include",
        staging / "zlib" / "lib",
        "z",
    )
    # GLib asks for iconv even when the target libc provides it directly.
    (pkgconfig / "iconv.pc").write_text(
        "Name: iconv\nDescription: libc iconv\nVersion: 1.0\nCflags:\nLibs:\n",
        encoding="ascii",
    )

    toolchain_bin = Path(os.environ["SMART_BUILD_TOOLCHAIN_BIN"])
    cross_file = work / "meson-cross.txt"
    cross_file.write_text(
        "[binaries]\n"
        f"c = '{toolchain_bin / (os.environ['SMART_BUILD_CROSS_COMPILE'] + 'gcc')}'\n"
        f"cpp = '{toolchain_bin / (os.environ['SMART_BUILD_CROSS_COMPILE'] + 'g++')}'\n"
        f"ar = '{toolchain_bin / (os.environ['SMART_BUILD_CROSS_COMPILE'] + 'ar')}'\n"
        f"strip = '{toolchain_bin / (os.environ['SMART_BUILD_CROSS_COMPILE'] + 'strip')}'\n"
        "pkgconfig = 'pkg-config'\n\n"
        "[host_machine]\n"
        "system = 'linux'\n"
        "cpu_family = 'aarch64'\n"
        "cpu = 'aarch64'\n"
        "endian = 'little'\n",
        encoding="ascii",
    )
    env = os.environ.copy()
    env["PKG_CONFIG_PATH"] = str(pkgconfig)
    env["PKG_CONFIG_SYSROOT_DIR"] = ""
    options = [
        "-Ddefault_library=static",
        "-Dglib_debug=disabled",
        "-Dlibelf=disabled",
        "-Dgio_module_dir=/usr/lib/gio/modules",
        "-Dtests=false",
        "-Doss_fuzz=disabled",
        "-Dintrospection=disabled",
        "-Ddtrace=false",
        "-Dsystemtap=false",
        "-Dsysprof=disabled",
        "-Dselinux=disabled",
        "-Dxattr=false",
        "-Dlibmount=disabled",
        "--prefix=/usr",
        "--buildtype=release",
        "--wrap-mode=nodownload",
    ]
    run(["meson", "setup", str(build), str(source), "--cross-file", str(cross_file), *options], cwd=work, env=env)
    run(["meson", "compile", "-C", str(build)], cwd=work, env=env)
    run(["meson", "install", "-C", str(build), "--destdir", str(stage)], cwd=work, env=env)
    materialize_internal_symlinks(stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
