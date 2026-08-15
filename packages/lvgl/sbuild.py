#!/usr/bin/env python3
"""Build a static LVGL library for RT-Thread Smart userspace."""

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


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f"expected directory not found: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=False)


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


def enable_lv_conf(template: str) -> str:
    updated = template.replace("#if 0", "#if 1", 1)
    for old, new in (
        ("#define LV_BUILD_EXAMPLES 1", "#define LV_BUILD_EXAMPLES 0"),
        ("#define LV_BUILD_DEMOS 1", "#define LV_BUILD_DEMOS 0"),
    ):
        updated = updated.replace(old, new)
    return updated


def write_lv_conf(source_dir: Path) -> Path:
    template = source_dir / "lv_conf_template.h"
    if not template.is_file():
        raise SystemExit(f"expected file not found: {template}")
    path = source_dir / "lv_conf.h"
    path.write_text(enable_lv_conf(template.read_text(encoding="utf-8")), encoding="utf-8")
    return path


def installed_library(dest_dir: Path) -> Path:
    for candidate in (
        dest_dir / "usr/lib/liblvgl.a",
        dest_dir / "usr/lib64/liblvgl.a",
        dest_dir / "usr/lib/liblvgl_static.a",
    ):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"expected LVGL library not found under {dest_dir / 'usr'}")


def installed_headers(dest_dir: Path) -> Path:
    for candidate in (dest_dir / "usr/include/lvgl", dest_dir / "usr/include"):
        if (candidate / "lvgl.h").is_file():
            return candidate
    raise SystemExit(f"expected LVGL headers not found under {dest_dir / 'usr/include'}")


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    toolchain_file = work_dir / "toolchain.cmake"
    jobs = str(os.cpu_count() or 1)
    lv_conf = write_lv_conf(source_dir)

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
            "-DCMAKE_BUILD_TYPE=MinSizeRel",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DCONFIG_LV_BUILD_EXAMPLES=OFF",
            "-DCONFIG_LV_BUILD_DEMOS=OFF",
            "-DCONFIG_LV_USE_THORVG_INTERNAL=OFF",
            "-DLV_BUILD_LVGL_H_SYSTEM_INCLUDE=ON",
            f"-DLV_BUILD_CONF_PATH={lv_conf}",
            f"-DLV_CONF_PATH={lv_conf}",
        ],
        cwd=work_dir,
    )
    run(["cmake", "--build", str(build_dir), "--parallel", jobs], cwd=work_dir)
    run(["cmake", "--install", str(build_dir)], cwd=work_dir, env={"DESTDIR": str(dest_dir)})

    headers = installed_headers(dest_dir)
    copy_tree(headers, stage_dir / "usr/include/lvgl")
    copy_file(installed_library(dest_dir), stage_dir / "usr/lib/liblvgl.a", 0o644)
    copy_file(lv_conf, stage_dir / "usr/include/lvgl/lv_conf.h", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
