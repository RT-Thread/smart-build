[English](troubleshooting.md) | **中文**

# 故障排查

## 找不到工具链

运行 `./smart-build toolchain list --machine <machine>` 查看所有兼容版本及其状态。
工具链会从配置的 `TOOLCHAIN_PATH`、Env SDK 的
`~/.env/tools/scripts/packages` 和仓库的 `downloads/toolchains/` 缓存中查找。
缺少可下载版本时，运行
`./smart-build toolchain install --machine <machine> --version <version> --yes`。
在 `PATH` 中设置任意编译器不能替代声明的工具链。

## 缺少 RT-Thread BSP

检查仓库根目录的 `rt-thread` 路径是否存在，并确认其中包含
`bsp/<board.yaml 中的 bsp 值>`。支持使用指向本地 RT-Thread 源码树的符号
链接。

## 内核软件包更新失败

运行 `./smart-build doctor --machine <machine>`，确认 `env-pkgs` 和
`env-package-index` 均通过。内核软件包由
`boards/<machine>/kernel_defconfig` 选择，并通过以下命令安装：

```sh
cd rt-thread/bsp/<bsp>
~/.env/tools/scripts/pkgs --force-update
```

检查 `build/<machine>/logs/kernel-packages.log`、BSP 下的
`packages/pkgs_error.json`、网络访问情况，以及所选版本是否存在于已安装的
Env 软件包索引中。使用 `smart-build configure kernel` 可以选择其他软件包
版本。关于已删除软件包目录的 warning 表示该目录包含 `SConscript`，但未在
`pkgs.json` 中登记。

## 软件包下载失败

下载的归档文件缓存在 `downloads/` 下。检查网络与代理设置、`package.yaml`
中的 URL 以及声明的 SHA256。只删除受影响的无效归档文件，或者使用
`./smart-build download-clean` 删除整个下载缓存。

当前软件包下载器在直接下载失败后，可能通过 `127.0.0.1:10808` 的本地代理
重试。目前还没有 CLI 离线开关。

## 镜像格式尚未实现

在 `menuconfig` 中选择 ext4。配置中虽然提供 FAT 和 romfs，但当前镜像执行器
无法创建这些格式。

## 目标报告未知任务

先确认目标与当前配置的根文件系统一致。例如，`full-rootfs` 要求选择完整根
文件系统。部分不支持的目标与配置组合目前会产生偏内部实现风格的错误；对于
当前选择，应使用 `build rootfs`。

## 任务被意外跳过

使用 `./smart-build clean` 删除所选机器的构建目录后重试。当前缓存决定是否
命中时，会检查输出是否存在，但不会校验已保存的内容校验和。

## QEMU 冒烟测试通过但子系统失败

查看 `build/<machine>/logs/qemu-smoke.log`。当前通过条件接受已知的 RT-Thread
横幅或 shell 标记，不会将每个驱动、挂载或网络错误都视为冒烟测试失败。

## 查找失败的命令

使用：

```sh
./smart-build build <target> --verbose
```

每个任务还会在 `build/<machine>/logs/` 下写入独立日志。`CONFIG`、`SCHEMA`、
`PACKAGE`、`TOOLCHAIN` 和 `BUILD` 等错误前缀用于标识拒绝该操作的子系统。
内核详细构建会通过 RT-Thread 的 `scons --verbose` 模式显示完整的编译器和
链接器命令。
