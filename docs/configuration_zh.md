[English](configuration.md) | **中文**

# 配置说明

smart-build 将板卡默认值与 `menuconfig` 写入仓库根目录的 `.config` 合并使用。
工作区没有选择机器时，默认使用 `qemu-virt-aarch64`。

## 选择机器

机器可以通过以下方式选择，优先级从高到低：

1. 子命令的 `--machine` 选项，如果该子命令提供此选项。
2. 全局 `smart-build --machine <name>` 选项。
3. 工作区 `.config` 中的 `MACHINE`。
4. 内置默认值 `qemu-virt-aarch64`。

示例：

```sh
./smart-build build kernel --machine qemu-virt-riscv64
```

## 工具链选择

在 `./smart-build menuconfig` 的所选机器下进入 `Cross toolchain` 菜单，可以选择
工具链版本并编辑可选的自定义工具链根目录。保存配置只记录选择，不会在 Kconfig
界面中联网下载；缺少工具链时，构建会在交互终端中确认是否下载到
`downloads/toolchains/`，也可以显式运行 `toolchain install`。

`TOOLCHAIN` 和 `TOOLCHAIN_VERSION` 从板卡声明的兼容条目中选择工具链。
`TOOLCHAIN_PATH` 可指向自定义工具链根目录，但仍会校验目标三元组、编译器前缀、
sysroot 和运行库。当前 QEMU AArch64、RISC-V 板卡提供 GCC 12.2.0 下载；Arm
vexpress 板卡保留 Env SDK GCC 7.3.0 默认值，同时提供可下载的 GCC 12.2.0。

使用 `./smart-build toolchain list` 查看当前选择和来源。缺少可下载版本时，使用
`./smart-build toolchain install --yes` 安装。

## 选择根文件系统

Kconfig 界面目前提供以下选项：

| 值 | 用途 | 默认软件包集合 |
| --- | --- | --- |
| `minimal` | 小型应用根文件系统 | `hello` |
| `basic` | BusyBox 根文件系统 | BusyBox 和 `hello` |
| `full` | 使用 profile 或手动选择软件包 | `base`、`devel` 或 `full` profile |
| `none` | 禁用 Smart 根文件系统 | 无 |

在所选根文件系统类型支持的情况下，构建模式包括 `static`、`dynamic` 和
`mixed`。基本 BusyBox 根文件系统使用静态模式。

## 镜像设置

`ROOTFS_IMAGE_SIZE_MB` 可取 1、4、8、16、32、64、128、256、512 或
1024 MB。ext4 的大小模式可以是 `fixed` 或 `expandable`。

目前仅实现 ext4 镜像创建。即使 menuconfig 中显示 FAT 或 romfs，也不要将其
用于实际构建。

## 软件包

完整根文件系统的软件包在其 Packages 菜单中选择。元数据选中的软件包依赖会
自动加入。详见[使用软件包](packages/using-packages_zh.md)。

软件包选项值会被解析并记录到构建 manifest 中，但并非所有现有构建后端都会
使用这些值。依赖某个选项改变生成的二进制文件前，应先检查该软件包的实现。

## 配置构建目标

`configure` 命令可以打开提供配置映射的构建域配置界面，也可以配置使用 native
Kconfig 的独立 RT-Thread SCons 软件包：

```sh
./smart-build configure kernel
./smart-build configure busybox
./smart-build configure bootloader
./smart-build configure package:<name>
```

并非每个板卡或软件包都会提供所有 configure 目标。不支持的目标会以
`CONFIG` 错误失败。对于 native Kconfig 包，该命令会启用软件包选择符号、打开
其 RT-Thread 软件包配置界面，并把该软件包的配置子树保存到所选板卡 defconfig
和工作区配置。配置阶段不会运行 SCons 或更新 Env 软件包。

## 配置内核软件包

RT-Thread 内核软件包在内核 menuconfig 中选择，而不是在 smart-build 根文件
系统的 Packages 菜单中选择：

```sh
./smart-build configure kernel
```

如需 ext4 内核支持，请在 RT-Thread 软件包菜单中启用 lwext4 并选择其版本。
随附的三个 QEMU 板卡默认使用 `latest`，当前解析到 lwext4 v2.2 发布版本。
下一次内核构建会根据保存的选择运行 Env `pkgs --force-update`。

这些软件包与仓库 `packages/` 目录下的用户态软件包相互独立。smart-build
将 BSP `packages/pkgs.json` 作为内核软件包目录的所有权记录；未登记且直接包含
`SConscript` 的子目录会在 warning 提示后被删除，所选源码仍由 Env 下载。
