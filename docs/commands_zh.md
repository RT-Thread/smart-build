[English](commands.md) | **中文**

# 命令参考

所有命令均从仓库根目录运行。使用 `./smart-build <command> --help` 查看当前
版本接受的参数。

## 全局选项

```text
--machine <name>    选择目标机器
```

全局选项必须位于子命令之前。部分子命令也接受位于子命令之后的本地
`--machine` 选项。

## 环境检查

```sh
./smart-build doctor [--machine MACHINE]
```

检查所选机器需要的宿主机工具、QEMU、RT-Thread BSP、env sdk 工具链和可写
构建路径。

## 配置

```sh
./smart-build menuconfig [--machine MACHINE]
./smart-build configure TARGET [--machine MACHINE]
```

`configure` 的 `TARGET` 可以是 `kernel`、`busybox`、`bootloader` 或
`package:<name>`。是否支持取决于所选板卡或软件包的元数据。

## 构建

```sh
./smart-build build [TARGET] [--machine MACHINE] [--jobs N] [--dry-run] [--verbose]
```

常用目标如下：

| 目标 | 结果 |
| --- | --- |
| `all` | 所选内核、软件包、根文件系统、镜像聚合及 QEMU 脚本 |
| `kernel` | Env 内核软件包及随后的 RT-Thread Smart 内核 |
| `rootfs` | 当前配置所选择的根文件系统 |
| `minirootfs` | 最小根文件系统镜像 |
| `busybox-rootfs` | BusyBox 根文件系统镜像 |
| `full-rootfs` | 选中时构建完整软件包根文件系统 |
| `package:<name>` | 单个软件包及其解析出的依赖 |
| `qemu-script` | QEMU 启动脚本 |

`--verbose` 会将任务日志同步输出到终端。`--jobs` 目前只在部分构建流水线中
生效。`--dry-run` 使用占位任务，不能将其视为真实任务图的精确表示。

内核构建包含 `kernel:packages:update` 任务。该任务会在 `kernel:build` 前，
从所选 BSP 运行 `~/.env/tools/scripts/pkgs --update`，并将已安装的软件包版本
记录到 manifest。

## 任务图

```sh
./smart-build graph [--machine MACHINE]
```

输出任务标识符、运行类别、依赖和输出。当前 `graph` 命令使用占位规划器。

## QEMU 冒烟测试

```sh
./smart-build qemu-smoke [--machine MACHINE] [--timeout SECONDS] \
  [--rootfs-image minirootfs.img|busybox-rootfs.img|rootfs.img]
```

所选镜像必须已经存在。该命令会在对应机器的构建目录下写入 QEMU 冒烟测试
日志。

## 清理

```sh
./smart-build clean
./smart-build distclean
./smart-build download-clean
```

这些命令可以通过全局选项选择机器，例如
`./smart-build --machine qemu-virt-riscv64 clean`。
