[English](README.md) | **中文**

# smart-build

smart-build 是面向 RT-Thread Smart 的独立构建系统。它提供统一的命令行界面，
用于机器配置、软件包选择、内核与根文件系统构建、增量任务执行、构建清单生成
以及 QEMU 冒烟测试。

本项目从源码树运行。构建产物、下载的归档文件、工具链以及 RT-Thread 源码树
均不纳入版本控制。

## 支持的机器

| 机器 | 架构 | RT-Thread BSP | QEMU 配置 |
| --- | --- | --- | --- |
| `qemu-virt-aarch64` | AArch64 | `qemu-virt64-aarch64` | `virt-aarch64` |
| `qemu-virt-riscv64` | RISC-V 64 | `qemu-virt64-riscv` | `virt-riscv64` |
| `qemu-vexpress-a9` | Arm | `qemu-vexpress-a9` | `vexpress-a9` |

目前已实现的根文件系统镜像格式为 ext4。FAT 和 romfs 会显示在配置界面中，
但尚不能构建。

## 环境要求

- Python 3.10 或更高版本。
- `~/.env/tools/scripts/packages` 下存在与所选机器 `board.yaml` 匹配的
  env sdk 工具链。
- `~/.env/tools/scripts` 下存在 RT-Thread Env 软件包脚本，并且
  `~/.env/packages/packages` 下存在软件包索引。
- 仓库根目录的 `rt-thread` 路径指向 RT-Thread 源码树，通常使用符号链接。
- 已安装 `smart-build doctor` 所报告的宿主机构建工具。
- 进行冒烟测试时，已安装所选板卡声明的 QEMU 系统程序。

以可编辑模式安装 Python 软件包：

```sh
python -m pip install -e .
```

## 快速开始

```sh
./smart-build doctor
./smart-build menuconfig
./smart-build build all
./smart-build qemu-smoke
```

无需修改工作区配置即可选择其他机器：

```sh
./smart-build --machine qemu-virt-riscv64 doctor
./smart-build build kernel --machine qemu-virt-riscv64
```

构建结果写入 `build/<machine>/`，下载的源码归档文件保存在 `downloads/` 下。

编译内核前，smart-build 会将内核 defconfig 同步到 RT-Thread BSP，并运行
`~/.env/tools/scripts/pkgs --update`。内核软件包及其版本由 RT-Thread 内核配置
选择，而不是由 smart-build 软件包元数据选择。

## 常用命令

```sh
./smart-build --help
./smart-build doctor
./smart-build menuconfig
./smart-build configure kernel
./smart-build configure package:curl
./smart-build build all
./smart-build build kernel
./smart-build build rootfs
./smart-build graph
./smart-build qemu-smoke
./smart-build clean
```

`build --dry-run` 目前输出占位任务计划。它可用于总体预览，但不能保证与实际
构建中的每项任务完全一致。

## 文档

- [入门指南](docs/getting-started_zh.md)
- [配置说明](docs/configuration_zh.md)
- [命令参考](docs/commands_zh.md)
- [使用软件包](docs/packages/using-packages_zh.md)
- [添加软件包](docs/packages/creating-package_zh.md)
- [软件包描述文件参考](docs/packages/package-yaml_zh.md)
- [支持的板卡](docs/boards/supported-boards_zh.md)
- [添加板卡支持](docs/boards/creating-board_zh.md)
- [根文件系统支持](docs/rootfs/rootfs-options_zh.md)
- [添加根文件系统类型](docs/rootfs/creating-rootfs_zh.md)
- [故障排查](docs/troubleshooting_zh.md)
- [兼容性与当前限制](docs/compatibility_zh.md)
- [贡献指南](CONTRIBUTING_zh.md)

## 许可证

本仓库尚未为项目选择许可证。在面向第三方广泛分发前，必须先添加许可证。
