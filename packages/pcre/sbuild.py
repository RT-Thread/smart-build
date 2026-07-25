#!/usr/bin/env python3
"""Build the PCRE 8.x ABI as static libraries."""

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


def target_processor() -> str:
    target = os.environ.get("SMART_BUILD_TARGET", "").lower()
    if "riscv64" in target:
        return "riscv64"
    if "aarch64" in target or "arm64" in target:
        return "aarch64"
    if "arm" in target:
        return "arm"
    raise SystemExit(f"unsupported CMake target: {target or '<empty>'}")


def write_toolchain_file(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "set(CMAKE_SYSTEM_NAME Generic)",
                f"set(CMAKE_SYSTEM_PROCESSOR {target_processor()})",
                'set(CMAKE_C_COMPILER "$ENV{CC}")',
                'set(CMAKE_CXX_COMPILER "$ENV{CXX}")',
                'set(CMAKE_AR "$ENV{AR}")',
                'set(CMAKE_RANLIB "$ENV{RANLIB}")',
                "set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    toolchain_file = work_dir / "toolchain.cmake"
    jobs = str(os.cpu_count() or 1)

    reset_dir(build_dir)
    reset_dir(dest_dir)
    reset_dir(stage_dir)
    write_toolchain_file(toolchain_file)
    run(
        [
            "cmake",
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}",
            "-DCMAKE_INSTALL_PREFIX=/usr",
            "-DCMAKE_INSTALL_LIBDIR=lib",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DPCRE_BUILD_PCRECPP=OFF",
            "-DPCRE_BUILD_PCREGREP=OFF",
            "-DPCRE_BUILD_TESTS=OFF",
        ],
        cwd=work_dir,
    )
    run(["cmake", "--build", str(build_dir), "--parallel", jobs], cwd=work_dir)
    run(["cmake", "--install", str(build_dir)], cwd=work_dir, env={"DESTDIR": str(dest_dir)})

    copy_file(dest_dir / "usr/include/pcre.h", stage_dir / "usr/include/pcre.h", 0o644)
    copy_file(dest_dir / "usr/include/pcreposix.h", stage_dir / "usr/include/pcreposix.h", 0o644)
    copy_file(dest_dir / "usr/lib/libpcre.a", stage_dir / "usr/lib/libpcre.a", 0o644)
    copy_file(dest_dir / "usr/lib/libpcreposix.a", stage_dir / "usr/lib/libpcreposix.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
