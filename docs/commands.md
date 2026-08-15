**English** | [中文](commands_zh.md)

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

## Toolchains

```sh
./smart-build toolchain list [--machine MACHINE]
./smart-build toolchain install [--machine MACHINE] [--version VERSION] [--yes]
```

`list` shows board-compatible versions, the selected version, and whether each
one is found in Env SDK or `downloads/toolchains/`. `install` downloads only a
board-declared HTTPS archive, verifies its SHA-256, and installs it under
`downloads/toolchains/<package>-<version>`. `--yes` is required in non-interactive shells.

## Configuration

```sh
./smart-build menuconfig [--machine MACHINE]
./smart-build configure TARGET [--machine MACHINE]
```

`menuconfig` exposes a `Cross toolchain` menu for the selected machine, where
the toolchain version and optional `TOOLCHAIN_PATH` are saved. The interface
does not download files; a missing downloadable toolchain is confirmed by an
interactive build or installed explicitly with `toolchain install` above.

`TARGET` for `configure` is `kernel`, `busybox`, `bootloader`, or
`package:<name>`. Support depends on the selected board or package metadata.
Packages using `build.rtthread_scons` with native Kconfig expose their RT-Thread
package options through this command; downloads still occur during `build`.

## Buildroot package import

With a Buildroot checkout at `buildroot/`, configure package selection with:

```sh
./smart-build buildroot menuconfig [--machine MACHINE]
```

If `buildroot/` is missing, the command asks whether to clone the latest
Buildroot repository from GitHub. After confirmation it performs a shallow
clone into the repository root and continues directly into menuconfig. A
non-interactive invocation or a declined prompt does not clone anything.

Import the selected target packages with:

```sh
./smart-build buildroot import [--machine MACHINE] [--config PATH]
./smart-build buildroot import --check
./smart-build buildroot import --package NAME
```

The importer is deliberately best effort. Existing smart-build packages are
skipped, unsupported packages are reported as failures, and later packages are
still attempted. A nonzero exit status means at least one package failed.
Successful imports create `package.yaml`, `Kconfig`, `sbuild.py`, and
`import.yaml` under `packages/<name>/`; they do not copy upstream sources into
the package directory. The generated source metadata retains the Buildroot
archive URL, so smart-build downloads the archive during the normal package
build and verifies it when a hash is available. Imported packages are not
cross-compiled during import. Their Kconfig is generated from package metadata
the same way as other smart-build packages; it does not carry a Buildroot label.

Names listed in `packages/.imports/never-import.yaml` are never imported.
That list includes C library implementations, Linux kernel surfaces,
packages that need kernel features RT-Thread Smart does not provide
(eBPF, KVM, seccomp, ptrace, RDMA, V4L2, audio, UEFI), and packages that
were imported and then removed by hand. The importer also refreshes
`packages/Kconfig` from current package metadata so leftover `source`
lines for deleted packages do not remain.

Package symbols already owned by smart-build are restored as selected after the
Buildroot menuconfig command. The ownership registry is stored under
`packages/.imports/buildroot-ownership.yaml`.

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

Before any build task starts, `build` analyzes the selected machine, toolchain,
packages, and task graph. Interactive terminals show a live `plan:` progress
bar while package metadata is scanned and package tasks are created.
Redirected output prints each planning phase as a line. Planning finishes with
`plan: ready N tasks`.

Without `--verbose`, interactive terminals then show a colored progress bar and
print completed task statuses above it. Successful and skipped tasks use the
form `build: [2/12] toolchain:check: success` without a log path. Redirected
output uses plain status lines without ANSI control sequences. Failed tasks
still report their log path.

`--verbose` prints each planning item, mirrors task logs to the terminal, and
prints each task's domain, action, working directory, dependencies, inputs,
outputs, cache policy, and log path. RT-Thread kernel compilation uses `scons --verbose` in this mode,
exposing the complete compiler and linker commands. `--jobs` is currently
honored by only part of the build pipeline. `--dry-run` uses placeholder tasks
and must not be treated as an exact representation of a real task graph.

Kernel builds include a `kernel:packages:update` task. It runs
`~/.env/tools/scripts/pkgs --force-update` from the selected BSP before
`kernel:build`. It warns and removes unrecorded buildable package directories,
then records the installed versions and removed paths in the manifest.

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

`download-clean` also removes installed and cached toolchains below `downloads/`.

Machine selection for these commands is currently available through the global
option, for example `./smart-build --machine qemu-virt-riscv64 clean`.
