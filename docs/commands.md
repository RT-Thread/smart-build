# Command reference

All commands are run from the repository root. Use `./smart-build <command>
--help` for the arguments accepted by the current version.

## Global option

```text
--machine <name>    select the target machine
```

The global option must appear before the subcommand. Several subcommands also
accept their own `--machine` option after the subcommand.

## Environment checks

```sh
./smart-build doctor [--machine MACHINE]
```

Checks host tools, QEMU, the RT-Thread BSP, the env sdk toolchain, and writable
build locations needed by the selected machine.

## Configuration

```sh
./smart-build menuconfig [--machine MACHINE]
./smart-build configure TARGET [--machine MACHINE]
```

`TARGET` for `configure` is `kernel`, `busybox`, `bootloader`, or
`package:<name>`. Support depends on the selected board or package metadata.

## Build

```sh
./smart-build build [TARGET] [--machine MACHINE] [--jobs N] [--dry-run] [--verbose]
```

Common targets are:

| Target | Result |
| --- | --- |
| `all` | Selected kernel, packages, rootfs, image aggregation, and QEMU script |
| `kernel` | Env kernel packages followed by the RT-Thread Smart kernel |
| `rootfs` | Rootfs selected by the current configuration |
| `minirootfs` | Minimal rootfs image |
| `busybox-rootfs` | BusyBox rootfs image |
| `full-rootfs` | Full package rootfs when selected |
| `package:<name>` | One package and its resolved dependencies |
| `qemu-script` | QEMU launch script |

`--verbose` mirrors task logs to the terminal. `--jobs` is currently honored
by only part of the build pipeline. `--dry-run` uses placeholder tasks and must
not be treated as an exact representation of a real task graph.

Kernel builds include a `kernel:packages:update` task. It runs
`~/.env/tools/scripts/pkgs --update` from the selected BSP before
`kernel:build` and records the installed package versions in the manifest.

## Task graph

```sh
./smart-build graph [--machine MACHINE]
```

Prints task identifiers, run classes, dependencies, and outputs. The current
graph command uses the placeholder planner.

## QEMU smoke check

```sh
./smart-build qemu-smoke [--machine MACHINE] [--timeout SECONDS] \
  [--rootfs-image minirootfs.img|busybox-rootfs.img|rootfs.img]
```

The selected image must already exist. The command writes a QEMU smoke log
below the machine build directory.

## Cleaning

```sh
./smart-build clean
./smart-build distclean
./smart-build download-clean
```

Machine selection for these commands is currently available through the global
option, for example `./smart-build --machine qemu-virt-riscv64 clean`.
