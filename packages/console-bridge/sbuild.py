#!/usr/bin/env python3
"""Build console_bridge for the target toolchain."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def required(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def reset(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    print("+ " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=cwd, env=merged, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def processor() -> str:
    target = os.environ.get("SMART_BUILD_TARGET", "").lower()
    if "riscv64" in target:
        return "riscv64"
    if "aarch64" in target or "arm64" in target:
        return "aarch64"
    raise SystemExit(f"unsupported target: {target or '<empty>'}")


def write_toolchain(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "set(CMAKE_SYSTEM_NAME Linux)",
                f"set(CMAKE_SYSTEM_PROCESSOR {processor()})",
                "set(UNIX TRUE)",
                'set(CMAKE_C_COMPILER "$ENV{CC}")',
                'set(CMAKE_CXX_COMPILER "$ENV{CXX}")',
                'set(CMAKE_AR "$ENV{AR}")',
                'set(CMAKE_RANLIB "$ENV{RANLIB}")',
                "set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)",
                "",
            ]
        ),
        encoding="ascii",
    )


def main() -> int:
    source = required("SMART_BUILD_SOURCE_DIR")
    work = required("SMART_BUILD_WORK_DIR")
    stage = required("SMART_BUILD_STAGE_DIR")
    build = work / "build"
    dest = work / "dest"
    reset(build)
    reset(dest)
    reset(stage)
    toolchain = work / "toolchain.cmake"
    write_toolchain(toolchain)
    run(
        [
            "cmake", "-S", str(source), "-B", str(build),
            f"-DCMAKE_TOOLCHAIN_FILE={toolchain}",
            "-DCMAKE_INSTALL_PREFIX=/usr",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_SHARED_LIBS=ON",
            "-DBUILD_TESTING=OFF",
        ],
        work,
    )
    run(["cmake", "--build", str(build), "--parallel", str(os.cpu_count() or 1)], work)
    run(["cmake", "--install", str(build)], work, {"DESTDIR": str(dest)})
    installed = dest / "usr"
    if not (installed / "include").is_dir() or not (installed / "lib").is_dir():
        raise SystemExit("console_bridge install did not produce include and lib directories")
    shutil.copytree(installed / "include", stage / "usr/include", symlinks=False)
    shutil.copytree(installed / "lib", stage / "usr/lib", symlinks=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
