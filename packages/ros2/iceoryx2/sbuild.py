#!/usr/bin/env python3
"""Build the Iceoryx2 C FFI shared library for RT-Thread Smart."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


RUST_VERSION_PREFIX = "rustc 1.85."
IOX2_VERSION = "0.9.3"


def required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def capture(command: list[str], cwd: Path, env: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}"
        )
    return completed.stdout


def rust_tools() -> tuple[Path, Path]:
    cargo_value = os.environ.get("CARGO")
    cargo = Path(cargo_value) if cargo_value else None
    if cargo is None:
        found = shutil.which("cargo")
        cargo = Path(found) if found else Path.home() / ".cargo/bin/cargo"
    if not cargo.is_file():
        raise SystemExit(
            "Rust 1.85 is required; install rustup without modifying the shell and add "
            "the rust-src and aarch64-unknown-linux-musl components"
        )
    rustc_value = os.environ.get("RUSTC")
    rustc = Path(rustc_value) if rustc_value else cargo.with_name("rustc")
    if not rustc.is_file():
        found = shutil.which("rustc")
        rustc = Path(found) if found else rustc
    if not rustc.is_file():
        raise SystemExit("rustc 1.85 is required")
    return cargo, rustc


def target_config(source_dir: Path) -> tuple[str, str, bool]:
    target = os.environ.get("SMART_BUILD_TARGET", "").lower()
    if "aarch64" in target or "arm64" in target:
        return "aarch64-unknown-linux-musl", "aarch64_unknown_linux_musl", False
    if "riscv64" in target:
        target_file = source_dir / "riscv64imafdc-unknown-linux-musl.json"
        if not target_file.is_file():
            raise SystemExit(f"missing Rust target: {target_file}")
        return str(target_file), "riscv64imafdc_unknown_linux_musl", True
    raise SystemExit(f"unsupported Rust target: {target or '<empty>'}")


def artifact_target_name(target: str) -> str:
    return Path(target).stem if target.endswith(".json") else target


def write_cmake_config(stage_dir: Path) -> None:
    config_dir = stage_dir / "usr/lib/cmake/iceoryx2-c"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = """get_filename_component(_IOX2_PREFIX
  "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
if(NOT TARGET iceoryx2-c::includes-only)
  add_library(iceoryx2-c::includes-only INTERFACE IMPORTED)
  set_target_properties(iceoryx2-c::includes-only PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES
      "${_IOX2_PREFIX}/include/iceoryx2/v0.9.3")
endif()
if(NOT TARGET iceoryx2-c::shared-lib)
  add_library(iceoryx2-c::shared-lib SHARED IMPORTED)
  set_target_properties(iceoryx2-c::shared-lib PROPERTIES
    IMPORTED_LOCATION "${_IOX2_PREFIX}/lib/libiceoryx2_ffi_c.so"
    IMPORTED_NO_SONAME TRUE
    INTERFACE_LINK_LIBRARIES iceoryx2-c::includes-only)
endif()
set("iceoryx2-c_FOUND" TRUE)
"""
    (config_dir / "iceoryx2-cConfig.cmake").write_text(config, encoding="utf-8")


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    target_dir = work_dir / "rust"
    reset_dir(target_dir)
    reset_dir(stage_dir)

    cargo, rustc = rust_tools()
    env = os.environ.copy()
    env["PATH"] = f"{cargo.parent}:{env.get('PATH', '')}"
    env["RUSTUP_TOOLCHAIN"] = "1.85.0"
    version = capture([str(rustc), "--version"], source_dir, env).strip()
    if not version.startswith(RUST_VERSION_PREFIX):
        raise SystemExit(f"Rust 1.85 is required, found: {version}")

    target, env_target, build_std = target_config(source_dir)
    env_key = env_target.upper()
    env[f"CARGO_TARGET_{env_key}_LINKER"] = os.environ["CC"]
    env[f"CC_{env_target}"] = os.environ["CC"]
    env[f"AR_{env_target}"] = os.environ["AR"]
    if build_std:
        env["RUSTC_BOOTSTRAP"] = "1"
    rustflags = ["--cfg=rt_smart"]
    if not build_std:
        rustflags.append("-Ctarget-feature=-crt-static")
    env[f"CARGO_TARGET_{env_key}_RUSTFLAGS"] = " ".join(rustflags)

    command = [str(cargo), "build"]
    if build_std:
        command.extend(["-Z", "build-std=std,panic_abort"])
    command.extend(
        [
            "--release",
            "--locked",
            "--package",
            "iceoryx2-ffi-c",
            "--target",
            target,
            "--target-dir",
            str(target_dir),
            "--jobs",
            str(os.cpu_count() or 1),
        ]
    )
    run(command, source_dir, env)

    artifact_dir = target_dir / artifact_target_name(target) / "release"
    header = artifact_dir / "iceoryx2-ffi-c-cbindgen/include/iox2/iceoryx2.h"
    library = artifact_dir / "libiceoryx2_ffi_c.so"
    if not header.is_file() or not library.is_file():
        raise SystemExit(f"missing Iceoryx2 C artifacts in {artifact_dir}")

    if build_std:
        elf_header = capture([os.environ["READELF"], "-h", str(library)], work_dir, env)
        if "soft-float ABI" not in elf_header:
            raise SystemExit("RISC-V Iceoryx2 library is not using the required LP64 ABI")

    header_dest = stage_dir / f"usr/include/iceoryx2/v{IOX2_VERSION}/iox2/iceoryx2.h"
    library_dest = stage_dir / "usr/lib/libiceoryx2_ffi_c.so"
    header_dest.parent.mkdir(parents=True, exist_ok=True)
    library_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(header, header_dest)
    shutil.copy2(library, library_dest)
    library_dest.chmod(0o755)
    write_cmake_config(stage_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
