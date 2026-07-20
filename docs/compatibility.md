**English** | [中文](compatibility_zh.md)

# Compatibility and current limitations

This page records user-visible limits in the current source tree.

## Installation model

smart-build currently expects to run from its source repository. An editable
Python installation works, but a standalone wheel does not include or discover
the repository's boards, packages, rootfs descriptions, and launcher layout.

## Build planning

`build --dry-run` and `graph` use placeholder tasks. Their task identifiers,
dependencies, and outputs can differ from a real build after toolchain and
package resolution. Do not consume them as a stable automation API.

## Parallel jobs

The scheduler executes tasks serially. `--jobs` is passed to BusyBox, while
several package scripts select their own CPU-based job count. The option does
not currently impose a build-wide concurrency limit.

## Rootfs images

Only ext4 image creation is implemented. FAT and romfs are not buildable even
though the Kconfig interface exposes them.

`ROOTFS=none` and target-specific rootfs commands do not have consistent QEMU
behavior in all combinations.

## Package options

Package option values are selected and recorded, but generic and Python
backends do not consistently consume them. Treat each option as package-specific
until its build implementation demonstrates the resulting artifact change.

## Cache and manifest

The cache validates input signatures and output existence, but not output
content on a hit. Clean the machine before release or reproducibility checks.

The build manifest uses a `.yaml` filename but contains JSON. It records host
absolute paths and can be large when task inputs contain directories.

## Source revisions

Userspace package release archives normally use SHA256. BusyBox currently uses
MD5, and automatic RT-Thread source checkout uses a moving branch. Preserve
local source revisions when reproducing an older build.

RT-Thread kernel package versions come from the board kernel defconfig and the
installed Env package index. Stable versions are reproducible only while their
index entry and upstream archive remain available. Selecting `latest` follows
the package index's moving source and can access the network on every update.

## QEMU smoke scope

The smoke check detects broad boot markers. It does not prove that every
filesystem, network service, driver, or packaged application initialized
successfully. Inspect logs and run target-specific checks for release testing.
