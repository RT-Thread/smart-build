**English** | [中文](getting-started_zh.md)

# Getting started

smart-build is run from the repository root. The launcher adds `src/` to the
Python import path, while an editable installation provides the same command as
an installed console script.

## Install Python dependencies

```sh
python -m pip install -e .
```

The Python package requires Python 3.10 or newer, PyYAML, and kconfiglib.

## Provide RT-Thread sources

Create the repository-root `rt-thread` path so that it points to an RT-Thread
source tree containing the BSP named by the selected board:

```sh
ln -s /path/to/rt-thread rt-thread
```

The default machine is `qemu-virt-aarch64`, whose BSP is
`qemu-virt64-aarch64`.

## Choose and provide the cross toolchain

The selected machine declares compatible toolchain versions in
`boards/<machine>/board.yaml`. `menuconfig` stores the selected package and
version in the workspace `.config`. Toolchains are searched in this order:

```text
~/.env/tools/scripts/packages
```

an optional `TOOLCHAIN_PATH`, and the repository cache:

```text
downloads/toolchains/<package>-<version>
```

List versions and state with `./smart-build toolchain list --machine
qemu-virt-aarch64`. When an interactive build finds a missing downloadable
version, it asks before downloading into `downloads/toolchains/`. In scripts,
use `./smart-build toolchain install --machine qemu-virt-aarch64 --version
12.2.0 --yes`. Downloads are checked with the board-declared SHA-256 before
extraction. An Env SDK-only version must be installed by Env SDK or supplied
through `TOOLCHAIN_PATH`.

## Provide RT-Thread Env packages

Kernel packages use the RT-Thread Env installation at:

```text
~/.env/tools/scripts/pkgs
~/.env/packages/packages
```

smart-build invokes the first path with `--update` from the selected BSP. The
command installs the package versions selected in the BSP `.config`. The Env
package index must already be installed and up to date; smart-build does not
upgrade that index.

## Check the environment

```sh
./smart-build doctor
```

Select another machine either globally or on commands which expose a local
machine option:

```sh
./smart-build --machine qemu-vexpress-a9 doctor
./smart-build doctor --machine qemu-vexpress-a9
```

Resolve every failed check before starting a real build.

## Configure and build

```sh
./smart-build menuconfig
./smart-build build all
```

`menuconfig` selects the machine, root filesystem, build mode, image settings,
packages, and the toolchain version and optional path under `Cross toolchain`.
It writes the workspace `.config` and currently also updates the selected board
defconfig. Review board defconfig changes before committing. Kconfig does not
start toolchain downloads; a missing toolchain is confirmed by the build or
installed explicitly with `toolchain install`.

Build a smaller target while working on one domain:

```sh
./smart-build build kernel
./smart-build build package:zlib
./smart-build build rootfs
```

`build kernel` first copies the board's `kernel_defconfig` to the RT-Thread BSP,
normalizes it with `scons --pyconfig-silent`, removes unrecorded buildable
package directories with a warning, runs Env `pkgs --force-update`, and then
compiles the kernel. This update can access the network when a selected kernel
package is not already installed.

Outputs are placed below `build/<machine>/`. Task logs are placed below that
machine's `logs/` directory. A completed build also writes `manifest.yaml`; the
file currently contains JSON data despite its suffix.

## Run QEMU

After building a supported QEMU machine:

```sh
./smart-build qemu-smoke
```

The command generates or uses the machine's QEMU script, captures boot output,
and checks for known RT-Thread boot markers. Inspect the smoke log even after a
pass when validating networking or application startup.

## Clean outputs

```sh
./smart-build clean
./smart-build distclean
./smart-build download-clean
```

`clean` removes the selected machine directory. `distclean` removes all build
directories. `download-clean` removes downloaded source and toolchain archives
and installed toolchains below `downloads/`.
