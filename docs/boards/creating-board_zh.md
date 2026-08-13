[English](creating-board.md) | **中文**

# 添加板卡支持

每个机器使用一个小写、连字符命名的目录，其名称必须与配置的 `MACHINE` 值
一致：

```text
boards/<machine>/
  Kconfig
  board.yaml
  defconfig
  kernel_defconfig
  kernel-overlay/       # 可选
```

## 添加板卡描述

示例：

```yaml
schema_version: 1
kind: board
name: qemu-example
version: 0.1.0
arch: aarch64
bsp: qemu-example
kernel_defconfig: kernel_defconfig
toolchain:
  package: aarch64-linux-musleabi-gcc-latest
  version: 12.2.0
  target: aarch64-linux-musleabi
  prefix: aarch64-linux-musleabi-
  loader: ld-musl-aarch64.so.1
  versions:
    - version: 12.2.0
      package: aarch64-linux-musleabi-gcc-latest
      gcc_version: 12.2.0
      source:
        url: https://example.org/toolchains/aarch64.tar.bz2
        archive: aarch64.tar.bz2
        sha256: 0000000000000000000000000000000000000000000000000000000000000000
qemu:
  binary: qemu-system-aarch64
  profile: virt-aarch64
  machine: virt
  cpu: max
```

必填字段包括 `arch`、`bsp`、`kernel_defconfig`，除可选 `loader` 外的四个
toolchain 字符串，以及 QEMU 的 `binary`、`profile` 和 `machine`。
`qemu.cpu` 为可选字段。`kernel_defconfig` 必须是包含在板卡目录内的相对
路径。

`bsp` 值指定 `rt-thread/bsp` 下的目录。工具链软件包必须提供所声明的编译器
前缀。旧板卡可以不声明 `toolchain.versions`；新增条目可以指定软件包名称和
经过校验的 HTTPS `source`（URL、归档文件名和 SHA-256）。没有 `source` 的条目
需要由 Env SDK 安装，或通过 `TOOLCHAIN_PATH` 提供。

## 添加 Kconfig 选项

创建 `boards/<machine>/Kconfig`，定义机器布尔选项及其派生字符串，然后从
`boards/Kconfig` 中 source 该文件。目录名、`MACHINE`、`board.yaml` 中的
名称、架构、BSP 和工具链值必须保持一致。

## 添加默认配置

`defconfig` 包含机器、根文件系统、镜像和工具链选择等 smart-build 默认值。
内核准备期间，`kernel_defconfig` 会被复制到所选 RT-Thread BSP 配置中。

使用已安装 Env 软件包索引提供的符号，在 `kernel_defconfig` 中选择
RT-Thread 内核软件包及其版本。例如，通过 `PKG_USING_LWEXT4` 及其版本选项
启用 ext4 支持。内核构建期间，smart-build 会根据 Env `pkgs.json` 对可构建
目录进行同步，在 warning 提示后删除未登记目录，并运行 Env
`pkgs --force-update`。

可选的 `kernel-overlay/` 按照相对于 RT-Thread BSP 的路径组织，并在内核源码
准备期间应用。overlay 内容应仅限此机器需要的文件。overlay 不得写入
`packages/` 下；对 Env 管理软件包的更改应进入软件包上游，或由板卡选择相应的
软件包版本。

## 实现 QEMU 支持

当前 QEMU 构建域只识别特定 profile。只有新板卡的内核镜像、设备、存储接口、
控制台和命令行均与已有 profile 匹配时，才适合复用它。否则，必须先为新
profile 添加代码支持，`qemu-script` 和 `qemu-smoke` 才能工作。

## 验证板卡

```sh
./smart-build doctor --machine <machine>
./smart-build build kernel --machine <machine>
./smart-build build all --machine <machine>
./smart-build qemu-smoke --machine <machine>
python -m pytest
```

确认 QEMU 能够进入 RT-Thread Smart shell，并检查完整日志中的驱动、挂载或
网络错误。
