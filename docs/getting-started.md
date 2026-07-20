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

## Provide the cross toolchain

Cross toolchains are discovered from:

```text
~/.env/tools/scripts/packages
```

The required package name, target triple, compiler prefix, and dynamic loader
are declared in `boards/<machine>/board.yaml`. smart-build does not download or
install the cross toolchain.

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
and packages. It writes the workspace `.config` and currently also updates the
selected board defconfig. Review board defconfig changes before committing.

Build a smaller target while working on one domain:

```sh
./smart-build build kernel
./smart-build build package:zlib
./smart-build build rootfs
```

`build kernel` first copies the board's `kernel_defconfig` to the RT-Thread BSP,
normalizes it with `scons --pyconfig-silent`, runs Env `pkgs --update`, and then
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
directories. `download-clean` removes downloaded archives.
