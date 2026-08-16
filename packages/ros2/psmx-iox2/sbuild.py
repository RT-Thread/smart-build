#!/usr/bin/env python3
"""Build the CycloneDDS Iceoryx2 PSMX plugin for RT-Thread Smart."""

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


def run(command: list[str], cwd: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=os.environ.copy(), check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def capture(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=os.environ.copy(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stdout)
    return completed.stdout


def target_processor() -> str:
    target = os.environ.get("SMART_BUILD_TARGET", "").lower()
    if "riscv64" in target:
        return "riscv64"
    if "aarch64" in target or "arm64" in target:
        return "aarch64"
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


def write_target_compat_headers(work_dir: Path) -> Path:
    linux_dir = work_dir / "compat/linux"
    linux_dir.mkdir(parents=True, exist_ok=True)
    (linux_dir / "if_ether.h").write_text(
        "#ifndef SMART_BUILD_LINUX_IF_ETHER_H\n"
        "#define SMART_BUILD_LINUX_IF_ETHER_H\n"
        "#include <netinet/if_ether.h>\n"
        "#endif\n",
        encoding="utf-8",
    )
    (linux_dir / "if_packet.h").write_text(
        "#ifndef SMART_BUILD_LINUX_IF_PACKET_H\n"
        "#define SMART_BUILD_LINUX_IF_PACKET_H\n"
        "#include <stdint.h>\n"
        "#include <netpacket/packet.h>\n"
        "struct tpacket_auxdata {\n"
        "  uint32_t tp_status; uint32_t tp_len; uint32_t tp_snaplen;\n"
        "  uint16_t tp_mac; uint16_t tp_net; uint16_t tp_vlan_tci; uint16_t tp_vlan_tpid;\n"
        "};\n"
        "#endif\n",
        encoding="utf-8",
    )
    (linux_dir / "filter.h").write_text(
        "#ifndef SMART_BUILD_LINUX_FILTER_H\n"
        "#define SMART_BUILD_LINUX_FILTER_H\n"
        "#include <stdint.h>\n"
        "struct sock_filter { uint16_t code; uint8_t jt; uint8_t jf; uint32_t k; };\n"
        "struct sock_fprog { unsigned short len; struct sock_filter *filter; };\n"
        "#define BPF_LD 0x00\n#define BPF_JMP 0x05\n#define BPF_RET 0x06\n"
        "#define BPF_H 0x08\n#define BPF_JEQ 0x10\n#define BPF_ABS 0x20\n#define BPF_K 0x00\n"
        "#define BPF_STMT(code, k) { (uint16_t)(code), 0, 0, (uint32_t)(k) }\n"
        "#define BPF_JUMP(code, k, jt, jf) { (uint16_t)(code), (uint8_t)(jt), (uint8_t)(jf), (uint32_t)(k) }\n"
        "#endif\n",
        encoding="utf-8",
    )
    return linux_dir.parent


def install_rt_smart_ifaddrs(source_dir: Path) -> None:
    source = source_dir / "rt-smart-ifaddrs.c"
    destination = source_dir / "src/ddsrt/src/ifaddrs/posix/ifaddrs.c"
    if not source.is_file() or not destination.is_file():
        raise SystemExit("CycloneDDS RT-Smart ifaddrs adaptation is missing")
    shutil.copy2(source, destination)


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    packages_dir = required_path("SMART_BUILD_PACKAGES_STAGING_DIR")
    build_dir = work_dir / "build"
    toolchain_file = work_dir / "toolchain.cmake"
    iceoryx_dir = packages_dir / "iceoryx2/usr/lib/cmake/iceoryx2-c"
    if not (iceoryx_dir / "iceoryx2-cConfig.cmake").is_file():
        raise SystemExit(f"Iceoryx2 target package is not staged: {iceoryx_dir}")

    install_rt_smart_ifaddrs(source_dir)
    reset_dir(build_dir)
    reset_dir(stage_dir)
    write_toolchain_file(toolchain_file)
    compat_include = write_target_compat_headers(work_dir)
    run(
        [
            "cmake",
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}",
            f"-Diceoryx2-c_DIR={iceoryx_dir}",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_INSTALL_PREFIX=/usr",
            "-DCMAKE_INSTALL_LIBDIR=lib",
            "-DCMAKE_SKIP_RPATH=ON",
            "-DBUILD_SHARED_LIBS=ON",
            "-DBUILD_TESTING=OFF",
            f"-DCMAKE_C_FLAGS=-I{compat_include}",
            "-DBUILD_EXAMPLES=OFF",
            "-DBUILD_IDLC=OFF",
            "-DBUILD_DDSPERF=OFF",
            "-DENABLE_SSL=OFF",
            "-DENABLE_SECURITY=OFF",
            "-DENABLE_SHM=OFF",
            "-DENABLE_ICEORYX=OFF",
            "-DENABLE_ICEORYX2=ON",
            "-DENABLE_TYPELIB=ON",
            "-DENABLE_TYPE_DISCOVERY=ON",
            "-DENABLE_TOPIC_DISCOVERY=ON",
        ],
        work_dir,
    )
    run(
        [
            "cmake",
            "--build",
            str(build_dir),
            "--target",
            "psmx_iox2",
            "--parallel",
            str(os.cpu_count() or 1),
        ],
        work_dir,
    )

    built = build_dir / "lib/libpsmx_iox2.so.11.0.1"
    if not built.is_file():
        raise SystemExit(f"PSMX plugin was not built: {built}")
    dynamic = capture([os.environ["READELF"], "-d", str(built)], work_dir)
    for dependency in ("libddsc.so.11", "libiceoryx2_ffi_c.so"):
        if dependency not in dynamic:
            raise SystemExit(f"PSMX plugin does not depend on {dependency}")
    if "RPATH" in dynamic or "RUNPATH" in dynamic:
        raise SystemExit("PSMX plugin contains a build-time RPATH")

    lib_dir = stage_dir / "usr/lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    for name in ("libpsmx_iox2.so", "libpsmx_iox2.so.11", "libpsmx_iox2.so.11.0.1"):
        destination = lib_dir / name
        shutil.copy2(built, destination)
        destination.chmod(0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
