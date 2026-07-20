# Supported boards

The current source tree contains three QEMU boards.

| Machine | Architecture | BSP directory | Toolchain package | QEMU binary |
| --- | --- | --- | --- | --- |
| `qemu-virt-aarch64` | AArch64 | `qemu-virt64-aarch64` | `aarch64-linux-musleabi-gcc-latest` | `qemu-system-aarch64` |
| `qemu-virt-riscv64` | RISC-V 64 | `qemu-virt64-riscv` | `riscv64-linux-musleabi-gcc-latest` | `qemu-system-riscv64` |
| `qemu-vexpress-a9` | Arm | `qemu-vexpress-a9` | `arm-linux-musleabi-gcc-stable` | `qemu-system-arm` |

Run the environment check for a machine before building it:

```sh
./smart-build doctor --machine qemu-virt-aarch64
```

All three boards default to a 16 MB expandable ext4 root filesystem. Their
toolchain package names are env sdk package identifiers and may resolve to
different concrete toolchain revisions as the local env sdk installation
changes.

Their kernel defconfigs enable the RT-Thread lwext4 package and pin
`v2.0.0-dfsv2`. Change the version through `smart-build configure kernel`; Env
installs the selected version during the next kernel build.

QEMU support is profile-specific. A board description containing arbitrary
QEMU values does not automatically add a new QEMU command profile; the profile
must also be implemented by smart-build.
