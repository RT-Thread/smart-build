**English** | [中文](troubleshooting_zh.md)

# Troubleshooting

## Toolchain is not found

Run `./smart-build doctor --machine <machine>` and compare the expected package
with `boards/<machine>/board.yaml`. Toolchains are discovered only below
`~/.env/tools/scripts/packages`; setting an arbitrary compiler on `PATH` does
not replace the declared env sdk toolchain.

## RT-Thread BSP is missing

Check that the repository-root `rt-thread` path exists and contains
`bsp/<board.yaml bsp value>`. A symbolic link to a local RT-Thread checkout is
supported.

## Kernel package update fails

Run `./smart-build doctor --machine <machine>` and confirm both `env-pkgs` and
`env-package-index` pass. Kernel packages are selected by
`boards/<machine>/kernel_defconfig` and installed by:

```sh
cd rt-thread/bsp/<bsp>
~/.env/tools/scripts/pkgs --update
```

Review `build/<machine>/logs/kernel-packages.log`, the BSP
`packages/pkgs_error.json`, network access, and whether the selected version
exists in the installed Env package index. Use `smart-build configure kernel`
to choose another package version.

## Package download fails

Downloaded archives are cached under `downloads/`. Check network and proxy
settings, the URL in `package.yaml`, and the declared SHA256. Remove only the
affected invalid archive, or use `./smart-build download-clean` to remove the
whole download cache.

The current package downloader may retry through a local proxy at
`127.0.0.1:10808` after a direct failure. There is no CLI offline switch yet.

## Image format is not implemented

Select ext4 in `menuconfig`. FAT and romfs are present in configuration but the
current image executor cannot create them.

## A target reports an unknown task

First confirm that the target matches the configured rootfs. For example,
`full-rootfs` requires the full rootfs selection. Some unsupported target and
configuration combinations currently reach an internal-style error; use
`build rootfs` for the active selection.

## A task is unexpectedly skipped

Delete the selected machine's build directory with `./smart-build clean` and
retry. The current cache checks that outputs exist but does not verify their
stored content checksum when deciding a hit.

## QEMU smoke passes but a subsystem failed

Read `build/<machine>/logs/qemu-smoke.log`. The current pass condition accepts a
known RT-Thread banner or shell marker and does not treat every driver, mount,
or network error as a smoke failure.

## Find the failing command

Use:

```sh
./smart-build build <target> --verbose
```

Each task also writes a dedicated log below `build/<machine>/logs/`. Error
prefixes such as `CONFIG`, `SCHEMA`, `PACKAGE`, `TOOLCHAIN`, and `BUILD`
identify the subsystem that rejected the operation.
