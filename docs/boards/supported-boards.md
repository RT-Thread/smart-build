**English** | [中文](supported-boards_zh.md)

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

Their kernel defconfigs enable the RT-Thread lwext4 package and select `latest`,
which currently resolves to the v2.2 release. Change the version through
`smart-build configure kernel`; Env installs the selected version during the
next kernel build.

QEMU support is profile-specific. A board description containing arbitrary
QEMU values does not automatically add a new QEMU command profile; the profile
must also be implemented by smart-build. The `virt-aarch64` and
`virt-riscv64` profiles pass a root filesystem on virtio-blk and set
`root=vda0` in the kernel command line (`ttyAMA0` on AArch64, `ttyS0` on
RISC-V).

Both virt boards enable `RT_USING_DM` and `RT_USING_OFW` in their kernel
defconfigs and leave `RT_USING_BUILTIN_FDT` disabled. By default QEMU supplies
the DTB at boot, including the kernel command line; no separate DTS
compilation or `-dtb` argument is needed. Serial, interrupt-controller and
virtio-mmio drivers discover devices through this tree. The RISC-V board uses
the unified RISC-V port (`RT_USING_RISCV_NEW_COMMON`), the 8250 serial driver
and SiFive PLIC; its command line selects `earlycon=sbi` and reserves DMA
memory with `cma=8M coherent_pool=2M`. Its QEMU CPU disables Sv48/Sv57 to match
the Smart kernel's Sv39 virtual address layout, and virtio-mmio uses modern
transport. The vexpress-a9 board retains its existing non-OFW configuration.
