#!/usr/bin/env python3
"""Build static SDL2_image with JPEG and PNG support."""

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
    path.mkdir(parents=True)


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
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)
    sdl2 = dependency_prefix("sdl2", "lib/libSDL2.a")
    libjpeg = dependency_prefix("libjpeg", "lib/libjpeg.a")
    libpng = dependency_prefix("libpng", "lib/libpng16.a")
    zlib = dependency_prefix("zlib", "lib/libz.a")

    reset_dir(build_dir)
    reset_dir(dest_dir)
    reset_dir(stage_dir)
    config = work_dir / "sdl2-config"
    config.write_text(
        "#!/bin/sh\n"
        f"case \"$*\" in *--cflags*) echo -I{sdl2 / 'include/SDL2'};; "
        f"*--libs*) echo -L{sdl2 / 'lib'} -lSDL2;; *) echo 2.0.16;; esac\n",
        encoding="utf-8",
    )
    config.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "CPPFLAGS": (
                f"-I{source_dir} -I{sdl2 / 'include'} -I{sdl2 / 'include/SDL2'} "
                f"-I{libjpeg / 'include'} -I{libpng / 'include'}"
            ),
            "LDFLAGS": (
                f"-L{sdl2 / 'lib'} -L{libjpeg / 'lib'} "
                f"-L{libpng / 'lib'} -L{zlib / 'lib'}"
            ),
            "LIBS": "-lSDL2 -ljpeg -lpng16 -lz",
            "SDL2_CONFIG": str(config),
            "SDL_CFLAGS": f"-I{sdl2 / 'include/SDL2'}",
            "SDL_LIBS": f"-L{sdl2 / 'lib'} -lSDL2",
            "JPEG_LIBS": "-ljpeg",
            "LIBPNG_CFLAGS": f"-I{source_dir} -I{libpng / 'include'}",
            "LIBPNG_LIBS": f"-L{libpng / 'lib'} -lpng16 -L{zlib / 'lib'} -lz",
            "PATH": str(work_dir) + os.pathsep + os.environ.get("PATH", ""),
        }
    )
    for generated in ("configure", "aclocal.m4", "Makefile.in"):
        (source_dir / generated).touch()
    configure = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        "--build=i686-pc-linux-gnu",
        "--prefix=/usr",
        "--libdir=/usr/lib",
        "--enable-static=yes",
        "--enable-shared=no",
        "--enable-bmp=yes",
        "--enable-jpg=yes",
        "--enable-png=yes",
        "--enable-png-shared=no",
        "--enable-gif=no",
        "--enable-lbm=no",
        "--enable-pcx=no",
        "--enable-pnm=no",
        "--enable-svg=no",
        "--enable-tga=no",
        "--enable-tif=no",
        "--enable-webp=no",
        "--enable-xcf=no",
        "--enable-xpm=no",
        "--enable-xv=no",
    ]
    run([item for item in configure if item != "--host="], cwd=build_dir, env=env)
    run(["make", "-j" + jobs], cwd=build_dir, env=env)
    run(["make", "install", f"DESTDIR={dest_dir}"], cwd=build_dir, env=env)

    copy_file(
        dest_dir / "usr/include/SDL2/SDL_image.h",
        stage_dir / "usr/include/SDL2/SDL_image.h",
        0o644,
    )
    copy_file(
        dest_dir / "usr/lib/libSDL2_image.a",
        stage_dir / "usr/lib/libSDL2_image.a",
        0o644,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
