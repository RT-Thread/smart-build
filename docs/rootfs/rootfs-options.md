# Root filesystem support

smart-build currently defines four rootfs selections.

| Selection | Build modes | Packages | Image |
| --- | --- | --- | --- |
| `minimal` | static, dynamic, mixed | `hello` | `minirootfs.img` |
| `basic` | static | BusyBox and `hello` | `busybox-rootfs.img` |
| `full` | static, dynamic, mixed | profile or manual selection | `rootfs.img` |
| `none` | none | none | none |

The full rootfs profiles are:

- `base`: hello and zlib.
- `devel`: hello, zlib, and MicroPython.
- `full`: all package descriptions currently included by `rootfs/full/rootfs.yaml`.

Package dependencies and `selects` relations can add packages beyond the list
shown by a profile.

## Image formats

ext4 is the only implemented image creation backend. FAT and romfs are visible
in Kconfig but fail during a real image build. Use ext4 for all current boards.

An expandable ext4 image grows beyond its configured minimum when the staged
rootfs needs more space. A fixed image fails when its configured size cannot
contain the staged files.

## Rootfs disabled mode

`ROOTFS=none` disables rootfs and image assembly tasks. Kernel-only behavior is
not yet consistent across every QEMU command, so inspect the generated script
before using this mode for a smoke test.
