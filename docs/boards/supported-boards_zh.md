[English](supported-boards.md) | **中文**

# 支持的板卡

当前源码树包含三个 QEMU 板卡。

| 机器 | 架构 | BSP 目录 | 工具链软件包 | QEMU 程序 |
| --- | --- | --- | --- | --- |
| `qemu-virt-aarch64` | AArch64 | `qemu-virt64-aarch64` | `aarch64-linux-musleabi-gcc-latest` | `qemu-system-aarch64` |
| `qemu-virt-riscv64` | RISC-V 64 | `qemu-virt64-riscv` | `riscv64-linux-musleabi-gcc-latest` | `qemu-system-riscv64` |
| `qemu-vexpress-a9` | Arm | `qemu-vexpress-a9` | `arm-linux-musleabi-gcc-stable` | `qemu-system-arm` |

构建机器前，先运行环境检查：

```sh
./smart-build doctor --machine qemu-virt-aarch64
```

三个板卡均默认使用 16 MB、可扩展的 ext4 根文件系统。其工具链软件包名称为
env sdk 软件包标识符；随着本地 env sdk 安装发生变化，它们可能解析为不同的
具体工具链版本。

这些板卡的内核 defconfig 会启用 RT-Thread lwext4 软件包并选择 `latest`，
当前解析到 v2.2 发布版本。通过 `smart-build configure kernel` 可以更改版本；
Env 会在下一次内核构建时安装所选版本。

QEMU 支持取决于具体 profile。在板卡描述中填写任意 QEMU 值，并不会自动添加
新的 QEMU 命令 profile；smart-build 中也必须实现该 profile。`virt-aarch64` 和
`virt-riscv64` 会通过 virtio-blk 挂载根文件系统，并在内核命令行中设置
`root=vda0`（AArch64 使用 `ttyAMA0`，RISC-V 使用 `ttyS0`）。

两个 virt 板卡的内核 defconfig 均启用 `RT_USING_DM` 和 `RT_USING_OFW`，
并关闭 `RT_USING_BUILTIN_FDT`。默认情况下 QEMU 在启动时传入包含内核命令行的
DTB，无需单独编译 DTS 或指定 `-dtb`。串口、中断控制器和 virtio-mmio 驱动通过
设备树发现设备。RISC-V 板卡使用统一 RISC-V 移植层
（`RT_USING_RISCV_NEW_COMMON`）、8250 串口驱动和 SiFive PLIC；命令行设置
`earlycon=sbi`，并通过 `cma=8M coherent_pool=2M` 预留 DMA 内存。
QEMU CPU 关闭 Sv48/Sv57，以匹配 Smart 内核的 Sv39 虚拟地址布局，
virtio-mmio 使用现代传输模式。
vexpress-a9 板卡保留现有的非 OFW 配置。
