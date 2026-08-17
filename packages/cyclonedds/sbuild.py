#!/usr/bin/env python3
"""Build CycloneDDS 11.0.1 for RT-Thread Smart."""

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


def write_target_compat_headers(work_dir: Path) -> Path:
    include_dir = work_dir / "compat" / "linux"
    include_dir.mkdir(parents=True, exist_ok=True)
    wrappers = {
        "if_ether.h": ("SMART_BUILD_LINUX_IF_ETHER_H", "netinet/if_ether.h"),
        "if_packet.h": ("SMART_BUILD_LINUX_IF_PACKET_H", "netpacket/packet.h"),
    }
    for name, (guard, target) in wrappers.items():
        (include_dir / name).write_text(
            f"#ifndef {guard}\n"
            f"#define {guard}\n"
            f"#include <{target}>\n"
            "#endif\n",
            encoding="utf-8",
        )
    (include_dir / "if_packet.h").write_text(
        "#ifndef SMART_BUILD_LINUX_IF_PACKET_H\n"
        "#define SMART_BUILD_LINUX_IF_PACKET_H\n"
        "#include <stdint.h>\n"
        "#include <netpacket/packet.h>\n"
        "struct tpacket_auxdata {\n"
        "  uint32_t tp_status;\n"
        "  uint32_t tp_len;\n"
        "  uint32_t tp_snaplen;\n"
        "  uint16_t tp_mac;\n"
        "  uint16_t tp_net;\n"
        "  uint16_t tp_vlan_tci;\n"
        "  uint16_t tp_vlan_tpid;\n"
        "};\n"
        "#endif\n",
        encoding="utf-8",
    )
    (include_dir / "filter.h").write_text(
        "#ifndef SMART_BUILD_LINUX_FILTER_H\n"
        "#define SMART_BUILD_LINUX_FILTER_H\n"
        "#include <stdint.h>\n"
        "struct sock_filter { uint16_t code; uint8_t jt; uint8_t jf; uint32_t k; };\n"
        "struct sock_fprog { unsigned short len; struct sock_filter *filter; };\n"
        "#define BPF_LD 0x00\n"
        "#define BPF_JMP 0x05\n"
        "#define BPF_RET 0x06\n"
        "#define BPF_H 0x08\n"
        "#define BPF_JEQ 0x10\n"
        "#define BPF_ABS 0x20\n"
        "#define BPF_K 0x00\n"
        "#define BPF_STMT(code, k) { (uint16_t)(code), 0, 0, (uint32_t)(k) }\n"
        "#define BPF_JUMP(code, k, jt, jf) \\\n"
        "  { (uint16_t)(code), (uint8_t)(jt), (uint8_t)(jf), (uint32_t)(k) }\n"
        "#endif\n",
        encoding="utf-8",
    )
    return include_dir.parent


def install_rt_smart_ifaddrs(source_dir: Path) -> None:
    adaptation = source_dir / "rt-smart-ifaddrs.c"
    destination = source_dir / "src/ddsrt/src/ifaddrs/posix/ifaddrs.c"
    if not adaptation.is_file():
        raise SystemExit(f"missing RT-Smart interface adaptation: {adaptation}")
    if not destination.is_file():
        raise SystemExit(f"CycloneDDS interface source not found: {destination}")
    shutil.copy2(adaptation, destination)


def install_jazzy_compat_headers(stage_dir: Path) -> None:
    ddsi_dir = stage_dir / "usr/include/dds/ddsi"
    ddsc_dir = stage_dir / "usr/include/dds/ddsc"
    ddsi_dir.mkdir(parents=True, exist_ok=True)
    ddsc_dir.mkdir(parents=True, exist_ok=True)
    (ddsi_dir / "q_radmin.h").write_text(
        "#ifndef SMART_BUILD_Q_RADMIN_H\n"
        "#define SMART_BUILD_Q_RADMIN_H\n"
        "#include <dds/ddsi/ddsi_radmin.h>\n"
        "#define nn_rdata ddsi_rdata\n"
        "#define NN_RMSG_PAYLOADOFF(rmsg, off) DDSI_RMSG_PAYLOADOFF((rmsg), (off))\n"
        "#define NN_RDATA_PAYLOAD_OFF(rdata) DDSI_RDATA_PAYLOAD_OFF((rdata))\n"
        "#endif\n",
        encoding="utf-8",
    )
    (ddsc_dir / "dds_loan_api.h").write_text(
        "#ifndef SMART_BUILD_DDS_LOAN_API_H\n"
        "#define SMART_BUILD_DDS_LOAN_API_H\n"
        "#include <dds/ddsc/dds_public_loan_api.h>\n"
        "#endif\n",
        encoding="utf-8",
    )
    (ddsc_dir / "dds_data_allocator.h").write_text(
        "#ifndef SMART_BUILD_DDS_DATA_ALLOCATOR_H\n"
        "#define SMART_BUILD_DDS_DATA_ALLOCATOR_H\n"
        "#include <stdbool.h>\n"
        "#include <stddef.h>\n"
        "#include <dds/dds.h>\n"
        "#include <dds/ddsc/dds_public_alloc.h>\n"
        "#include <dds/ddsc/dds_public_loan_api.h>\n"
        "typedef struct dds_data_allocator { dds_entity_t entity; bool heap; } "
        "dds_data_allocator_t;\n"
        "static inline dds_return_t dds_data_allocator_init(\n"
        "  dds_entity_t entity, dds_data_allocator_t *allocator)\n"
        "{ allocator->entity = entity; allocator->heap = false; return DDS_RETCODE_OK; }\n"
        "static inline dds_return_t dds_data_allocator_init_heap(\n"
        "  dds_data_allocator_t *allocator)\n"
        "{ allocator->entity = 0; allocator->heap = true; return DDS_RETCODE_OK; }\n"
        "static inline void *dds_data_allocator_alloc(\n"
        "  dds_data_allocator_t *allocator, size_t size)\n"
        "{\n"
        "  void *sample = NULL;\n"
        "  if (allocator->heap) return dds_alloc(size);\n"
        "  return dds_request_loan_of_size(allocator->entity, size, &sample) == "
        "DDS_RETCODE_OK ? sample : NULL;\n"
        "}\n"
        "static inline dds_return_t dds_data_allocator_free(\n"
        "  dds_data_allocator_t *allocator, void *sample)\n"
        "{\n"
        "  if (allocator->heap) { dds_free(sample); return DDS_RETCODE_OK; }\n"
        "  return dds_return_loan(allocator->entity, &sample, 1);\n"
        "}\n"
        "static inline dds_return_t dds_data_allocator_fini(\n"
        "  dds_data_allocator_t *allocator)\n"
        "{ (void)allocator; return DDS_RETCODE_OK; }\n"
        "#endif\n",
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
    compat_include = write_target_compat_headers(work_dir)

    install_rt_smart_ifaddrs(source_dir)
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
            "-DBUILD_TESTING=OFF",
            f"-DCMAKE_C_FLAGS=-I{compat_include}",
            "-DBUILD_EXAMPLES=OFF",
            "-DBUILD_IDLC=OFF",
            "-DBUILD_DDSPERF=OFF",
            "-DENABLE_SSL=OFF",
            "-DENABLE_SECURITY=OFF",
            "-DENABLE_SHM=OFF",
            "-DENABLE_ICEORYX=OFF",
            "-DENABLE_ICEORYX2=OFF",
            "-DENABLE_TYPELIB=ON",
            "-DENABLE_TYPE_DISCOVERY=ON",
            "-DENABLE_TOPIC_DISCOVERY=ON",
        ],
        cwd=work_dir,
    )
    run(["cmake", "--build", str(build_dir), "--parallel", jobs], cwd=work_dir)
    run(["cmake", "--install", str(build_dir)], cwd=work_dir, env={"DESTDIR": str(dest_dir)})

    include_dir = dest_dir / "usr/include/dds"
    if not include_dir.is_dir():
        raise SystemExit("CycloneDDS headers were not installed")
    copy_tree(include_dir, stage_dir / "usr/include/dds")
    install_jazzy_compat_headers(stage_dir)
    lib_dir = dest_dir / "usr/lib"
    candidates = [
        path for path in sorted(lib_dir.glob("libddsc.so*"))
        if path.is_file()
    ]
    if not candidates:
        raise SystemExit("libddsc.so was not installed")
    for candidate in candidates:
        copy_tree(candidate, stage_dir / "usr/lib" / candidate.name)
    cmake_dir = dest_dir / "usr/lib/cmake/CycloneDDS"
    if cmake_dir.is_dir():
        copy_tree(cmake_dir, stage_dir / "usr/lib/cmake/CycloneDDS")
    for name in ("cyclonedds.xml", "cyclonedds.network.xml"):
        source = source_dir / name
        if not source.is_file():
            source = source_dir / "files" / name
        if not source.is_file():
            raise SystemExit(f"missing CycloneDDS config: {name}")
        copy_tree(source, stage_dir / "etc" / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
