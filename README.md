**English** | [中文](README_zh.md)

# smart-build

smart-build is a standalone build system for RT-Thread Smart. It provides one
command-line interface for machine configuration, package selection, kernel
and root filesystem builds, incremental task execution, build manifests, and
QEMU smoke checks.

The project runs from its source tree. Build outputs, downloaded archives,
toolchains, and the RT-Thread source tree are kept outside version control.

## Supported machines

| Machine | Architecture | RT-Thread BSP | QEMU profile |
| --- | --- | --- | --- |
| `qemu-virt-aarch64` | AArch64 | `qemu-virt64-aarch64` | `virt-aarch64` |
| `qemu-virt-riscv64` | RISC-V 64 | `qemu-virt64-riscv` | `virt-riscv64` |
| `qemu-vexpress-a9` | Arm | `qemu-vexpress-a9` | `vexpress-a9` |

The currently implemented root filesystem image format is ext4. FAT and romfs
appear in the configuration interface but are not yet buildable.

## Prerequisites

- Python 3.10 or newer.
- An env sdk toolchain under `~/.env/tools/scripts/packages` matching the
  selected machine's `board.yaml`.
- RT-Thread Env package scripts under `~/.env/tools/scripts` and a package
  index under `~/.env/packages/packages`.
- An RT-Thread source tree available as the repository-root `rt-thread` path,
  usually as a symbolic link.
- Host build tools reported by `smart-build doctor`.
- The QEMU system binary declared by the selected board for smoke tests.

Install the Python package in editable mode:

```sh
python -m pip install -e .
```

## Quick start

```sh
./smart-build doctor
./smart-build menuconfig
./smart-build build all
./smart-build qemu-smoke
```

To select a machine without changing the workspace configuration:

```sh
./smart-build --machine qemu-virt-riscv64 doctor
./smart-build build kernel --machine qemu-virt-riscv64
```

Build results are written below `build/<machine>/`. Downloaded source archives
are stored below `downloads/`.

Before compiling the kernel, smart-build synchronizes its defconfig to the
RT-Thread BSP and runs `~/.env/tools/scripts/pkgs --update`. Kernel packages
and their versions are selected by the RT-Thread kernel configuration, not by
smart-build package metadata.

## Common commands

```sh
./smart-build --help
./smart-build doctor
./smart-build menuconfig
./smart-build configure kernel
./smart-build configure package:curl
./smart-build build all
./smart-build build kernel
./smart-build build rootfs
./smart-build graph
./smart-build qemu-smoke
./smart-build clean
```

`build --dry-run` currently prints a placeholder task plan. It is useful for a
high-level preview, but it is not guaranteed to match every task in a real
build.

## Documentation

- [Getting started](docs/getting-started.md)
- [Configuration](docs/configuration.md)
- [Command reference](docs/commands.md)
- [Using packages](docs/packages/using-packages.md)
- [Adding a package](docs/packages/creating-package.md)
- [Package description reference](docs/packages/package-yaml.md)
- [Supported boards](docs/boards/supported-boards.md)
- [Adding board support](docs/boards/creating-board.md)
- [Root filesystem support](docs/rootfs/rootfs-options.md)
- [Adding a root filesystem type](docs/rootfs/creating-rootfs.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Compatibility and current limitations](docs/compatibility.md)
- [Contributing](CONTRIBUTING.md)

## License

No project license has been selected in this repository yet. A license must be
added before distributing the project for general third-party use.
