#!/usr/bin/env python3
"""Build fmt as a shared library."""

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
                "set(CMAKE_SYSTEM_NAME Linux)",
                f"set(CMAKE_SYSTEM_PROCESSOR {target_processor()})",
                "set(UNIX TRUE)",
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


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        raise SystemExit(f"expected path not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=False)
        return
    shutil.copy2(source, destination)


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
            "-DBUILD_SHARED_LIBS=ON",
            "-DFMT_DOC=OFF",
            "-DFMT_TEST=OFF",
        ],
        cwd=work_dir,
    )
    run(["cmake", "--build", str(build_dir), "--parallel", jobs], cwd=work_dir)
    run(["cmake", "--install", str(build_dir)], cwd=work_dir, env={"DESTDIR": str(dest_dir)})

    copy_tree(dest_dir / "usr/include/fmt", stage_dir / "usr/include/fmt")
    lib_dir = dest_dir / "usr/lib"
    candidates = [path for path in sorted(lib_dir.glob("libfmt.so*")) if path.is_file()]
    if not any(not path.is_symlink() for path in candidates):
        raise SystemExit("libfmt.so was not installed")
    for candidate in candidates:
        copy_tree(candidate, stage_dir / "usr/lib" / candidate.name)
    cmake_dir = dest_dir / "usr/lib/cmake/fmt"
    if cmake_dir.is_dir():
        copy_tree(cmake_dir, stage_dir / "usr/lib/cmake/fmt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
