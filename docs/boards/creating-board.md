# Adding board support

A machine owns a lowercase, hyphenated directory whose name must equal the
configured `MACHINE` value:

```text
boards/<machine>/
  Kconfig
  board.yaml
  defconfig
  kernel_defconfig
  kernel-overlay/       # optional
```

## Add the board description

Example:

```yaml
schema_version: 1
kind: board
name: qemu-example
version: 0.1.0
arch: aarch64
bsp: qemu-example
kernel_defconfig: kernel_defconfig
toolchain:
  package: aarch64-linux-musleabi-gcc-latest
  target: aarch64-linux-musleabi
  prefix: aarch64-linux-musleabi-
  loader: ld-musl-aarch64.so.1
qemu:
  binary: qemu-system-aarch64
  profile: virt-aarch64
  machine: virt
  cpu: max
```

Required fields are `arch`, `bsp`, `kernel_defconfig`, the four toolchain
strings except optional `loader`, and the QEMU `binary`, `profile`, and
`machine`. `qemu.cpu` is optional. `kernel_defconfig` must be a relative path
contained by the board directory.

The `bsp` value names a directory below `rt-thread/bsp`. The toolchain package
must exist below the env sdk package root and provide the declared compiler
prefix.

## Add Kconfig selection

Create `boards/<machine>/Kconfig` with the machine boolean and its derived
strings, then source it from `boards/Kconfig`. Keep the directory name,
`MACHINE`, `board.yaml` name, architecture, BSP, and toolchain values aligned.

## Add defaults

`defconfig` contains smart-build defaults such as machine, rootfs, image, and
toolchain selection. `kernel_defconfig` is copied into the selected RT-Thread
BSP configuration during kernel preparation.

Select RT-Thread kernel packages and their versions in `kernel_defconfig` using
the symbols provided by the installed Env package index. For example, ext4
support is enabled through `PKG_USING_LWEXT4` and its version choice. During a
kernel build, smart-build runs Env `pkgs --update` and does not maintain a
separate package source copy.

An optional `kernel-overlay/` mirrors paths relative to the RT-Thread BSP and
is applied during kernel source preparation. Keep overlay contents limited to
files required by this machine. An overlay must not write below `packages/`;
changes to Env-managed packages belong in the package upstream or package
version selected by the board.

## Implement QEMU support

The current QEMU domain recognizes specific profiles. Reusing a supported
profile is appropriate only when its kernel image, devices, storage interface,
console, and command line match the new board. Otherwise, the new profile needs
code support before `qemu-script` and `qemu-smoke` can work.

## Verify the board

```sh
./smart-build doctor --machine <machine>
./smart-build build kernel --machine <machine>
./smart-build build all --machine <machine>
./smart-build qemu-smoke --machine <machine>
python -m pytest
```

Confirm that QEMU reaches the RT-Thread Smart shell and inspect the full log for
driver, mount, or network failures.
