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

这些板卡的内核 defconfig 会启用 RT-Thread lwext4 软件包，并固定为
`v2.0.0-dfsv2`。通过 `smart-build configure kernel` 可以更改版本；Env 会
在下一次内核构建时安装所选版本。

QEMU 支持取决于具体 profile。在板卡描述中填写任意 QEMU 值，并不会自动添加
新的 QEMU 命令 profile；smart-build 中也必须实现该 profile。
