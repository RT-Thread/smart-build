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

## 工具链

```sh
./smart-build toolchain list [--machine MACHINE]
./smart-build toolchain install [--machine MACHINE] [--version VERSION] [--yes]
```

`list` 显示板卡兼容版本、当前选择，以及版本是否已在 Env SDK 或
`downloads/toolchains/` 中发现。`install` 只下载板卡声明的 HTTPS 归档，校验
SHA-256 后安装到 `downloads/toolchains/<package>-<version>`。非交互 shell 必须使用
`--yes`。

## 配置

```sh
./smart-build menuconfig [--machine MACHINE]
./smart-build configure TARGET [--machine MACHINE]
```

`menuconfig` 在所选机器的 `Cross toolchain` 菜单中选择工具链版本并编辑可选的
`TOOLCHAIN_PATH`。界面只保存配置；缺失工具链时由构建确认下载，或使用上面的
`toolchain install` 命令显式安装。

`configure` 的 `TARGET` 可以是 `kernel`、`busybox`、`bootloader` 或
`package:<name>`。是否支持取决于所选板卡或软件包的元数据。使用 native
Kconfig 的 `build.rtthread_scons` 包通过此命令提供 RT-Thread 软件包选项；在线
包下载仍在 `build` 阶段执行。

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

未使用 `--verbose` 时，交互式终端会显示彩色进度条，并在其上方输出已完成
任务的状态。成功和跳过的任务使用
`build: [2/12] toolchain:check: success` 格式，不显示日志路径。重定向输出时只
输出不含 ANSI 控制符的普通状态行；失败任务仍会显示日志路径。

`--verbose` 会将任务日志同步输出到终端，并显示各任务的构建域、动作、工作
目录、依赖、输入、输出、缓存策略和日志路径。在该模式下，RT-Thread 内核
编译使用 `scons --verbose`，显示完整的编译器和链接器命令。`--jobs` 目前只在
部分构建流水线中生效。`--dry-run` 使用占位任务，不能将其视为真实任务图的
精确表示。

内核构建包含 `kernel:packages:update` 任务。该任务会在 `kernel:build` 前，
从所选 BSP 运行 `~/.env/tools/scripts/pkgs --force-update`。它会在 warning
提示后删除未登记但会参与构建的软件包目录，并将已安装版本和删除路径记录到
manifest。

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

`download-clean` 也会删除 `downloads/` 下已安装和缓存的工具链。

这些命令可以通过全局选项选择机器，例如
`./smart-build --machine qemu-virt-riscv64 clean`。
