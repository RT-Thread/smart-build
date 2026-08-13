**English** | [中文](configuration_zh.md)

# Configuration

smart-build combines board defaults with the repository-root `.config` written
by `menuconfig`. When no workspace machine is selected,
`qemu-virt-aarch64` is used.

## Machine selection

The machine can be selected in three ways, from highest to lowest priority:

1. The subcommand's `--machine` option, where available.
2. The global `smart-build --machine <name>` option.
3. `MACHINE` in the workspace `.config`.
4. The built-in default `qemu-virt-aarch64`.

Example:

```sh
./smart-build build kernel --machine qemu-virt-riscv64
```

## Toolchain selection

In `./smart-build menuconfig`, open the `Cross toolchain` menu under the selected
machine to choose a version and edit the optional custom toolchain root. Saving
configuration only records the selection; Kconfig does not perform network
downloads. If the selected toolchain is missing, an interactive build asks
before downloading it into `downloads/toolchains/`, or you can run
`toolchain install` explicitly.

`TOOLCHAIN` and `TOOLCHAIN_VERSION` select one of the compatible entries declared
by the board. `TOOLCHAIN_PATH` can point to a custom toolchain root; it is still
validated for the target triple, compiler prefix, sysroot, and runtime files.
The current QEMU AArch64 and RISC-V boards provide GCC 12.2.0 downloads. The
Arm vexpress board keeps its Env SDK GCC 7.3.0 default and also provides a
downloadable GCC 12.2.0 entry.

Use `./smart-build toolchain list` to inspect the selection and installation
source. Missing downloadable versions can be installed with
`./smart-build toolchain install --yes`.

## Root filesystem selection

The Kconfig interface currently offers:

| Value | Purpose | Default package set |
| --- | --- | --- |
| `minimal` | Small application rootfs | `hello` |
| `basic` | BusyBox rootfs | BusyBox and `hello` |
| `full` | Profile or manually selected packages | `base`, `devel`, or `full` profile |
| `none` | Disable the Smart rootfs | None |

Build modes are `static`, `dynamic`, and `mixed` where the selected rootfs type
supports them. The basic BusyBox rootfs uses static mode.

## Image settings

`ROOTFS_IMAGE_SIZE_MB` accepts 1, 4, 8, 16, 32, 64, 128, 256, 512, or 1024 MB.
For ext4, size mode can be `fixed` or `expandable`.

Only ext4 image creation is currently implemented. Do not select FAT or romfs
for a real build even though they are visible in menuconfig.

## Packages

Packages for the full rootfs are selected under its Packages menu. Package
dependencies selected by metadata are added automatically. See
[Using packages](packages/using-packages.md).

Package option values are resolved and recorded in the build manifest, but not
all existing build backends consume those values yet. Check the package's
implementation before relying on an option to alter generated binaries.

## Configure build targets

The `configure` command opens configuration for domains that provide a
configuration mapping and for independent RT-Thread SCons packages that use
native Kconfig:

```sh
./smart-build configure kernel
./smart-build configure busybox
./smart-build configure bootloader
./smart-build configure package:<name>
```

Not every board or package supplies every configure target. Unsupported targets
fail with a `CONFIG` error. For a native Kconfig package, the command enables
the package selection symbol, opens its RT-Thread package configuration, and
saves that package's configuration subtree to the selected board defconfig and
workspace configuration. It does not run SCons or update Env packages.

## Configure kernel packages

RT-Thread kernel packages are selected in the kernel menuconfig rather than the
smart-build rootfs Packages menu:

```sh
./smart-build configure kernel
```

For ext4 kernel support, enable lwext4 and choose its version in the RT-Thread
package menu. The three included QEMU boards default to `latest`, which
currently resolves to the lwext4 v2.2 release. The next kernel build runs Env
`pkgs --force-update` using the saved selection.

These packages are separate from userspace packages under the repository's
`packages/` directory. The BSP `packages/pkgs.json` is the ownership record for
kernel package directories. smart-build warns and removes any unrecorded direct
child containing `SConscript`; Env downloads the selected sources.
