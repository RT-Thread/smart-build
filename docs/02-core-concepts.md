# 第二章 核心概念

本章介绍 smart-build 涉及的核心概念，包括 BitBake 构建系统的术语以及 RT-Thread Smart 本身的关键概念。理解这些概念，是高效使用和扩展 smart-build 的基础。

## 2.1 BitBake 构建系统

### 2.1.1 BitBake

BitBake 是一个通用的任务执行引擎，最初为 OpenEmbedded 项目设计，也被 Yocto Project 广泛使用。它的核心能力包括：

- **任务调度**：自动解析任务之间的依赖关系，以正确的顺序执行
- **并行执行**：充分利用多核 CPU，并行处理无依赖关系的任务
- **配方解析**：读取 `.bb` 文件（配方），理解构建指令
- **跨平台编译**：天然支持交叉编译场景

在 smart-build 中，BitBake 充当"总调度器"的角色，协调工具链安装、BusyBox 编译、内核构建等所有环节。

### 2.1.2 OpenEmbedded-Core（OE-Core）

OpenEmbedded-Core 是一个精简的元数据集合，提供嵌入式系统构建所需的基础设施。它包含：

- 约 830 个核心配方
- 通用的机器配置和类定义
- 软件包管理支持
- 跨平台编译基础

smart-build 使用 OE-Core 作为底层构建框架，`meta-smart` 层叠加在 OE-Core 之上，继承其基础能力并定义 RT-Smart 特有的构建逻辑。

### 2.1.3 层（Layer）

**层**是 BitBake 构建系统中最核心的组织单元。每个层是一个包含配方、类、配置文件的目录，按照约定的结构组织。

层的设计哲学：
- **模块化**：不同功能放在不同层中，互不干扰
- **可叠加**：多个层可以层叠使用，上层可以覆盖下层的配方
- **可复用**：一个层可以被多个项目共享

在 smart-build 中，使用了两个层：

| 层 | 路径 | 优先级 | 作用 |
| --- | --- | --- | --- |
| `core` | `oe-core/meta` | 默认 | OE-Core 基础层，提供构建框架 |
| `smart` | `meta-smart` | 10 | RT-Smart 自定义层，包含所有业务逻辑 |

层的命名约定：**必须以 `meta-` 为前缀**，如 `meta-smart`、`meta-myapp`。

### 2.1.4 配方（Recipe）

配方是一个 `.bb` 文件，描述了**如何获取、配置、编译、安装一个软件组件**。每个配方文件包含：

- 元信息（`SUMMARY`、`DESCRIPTION`、`LICENSE`）
- 源码地址（`SRC_URI`）
- 构建指令（各种 `do_*` 任务函数）
- 依赖关系（`DEPENDS`、`[depends]` 标记）

smart-build 中的主要配方：

| 配方 | 文件 | 功能 |
| --- | --- | --- |
| `smart-gcc` | `recipes-devtools/toolchain/smart-gcc_0.1.bb` | 下载、安装交叉编译工具链 |
| `busybox` | `recipes-core/busybox/busybox_0.1.bb` | 编译 BusyBox，生成 ext4 文件系统镜像 |
| `smart` | `recipes-kernel/rt-thread/smart_0.1.bb` | 编译 RT-Thread Smart 内核 |
| `env` | `recipes-devtools/env/env_0.1.bb` | 安装 RT-Thread 开发环境 |
| `example` | `recipes-example/example/example_0.1.bb` | 配方模板示例 |

配方文件的命名规范：**`<名称>_<版本>.bb`**，例如 `busybox_0.1.bb`。

### 2.1.5 任务（Task）

任务是配方中定义的具体执行步骤，以 `do_` 开头的函数。BitBake 标准任务链如下：

```
do_fetch → do_unpack → do_patch → do_configure → do_compile → do_install → do_build
```

smart-build **使用自定义任务**而非标准任务链，这是一个重要的设计决策：

| 自定义任务 | 所属配方 | 说明 |
| --- | --- | --- |
| `do_install_toolchain` | `smart-gcc` | 下载并安装交叉编译器 |
| `do_build_rootfs` | `busybox` | 编译 BusyBox 并生成文件系统 |
| `do_build_kernel` | `smart` | 编译 RT-Smart 内核 |
| `do_build_all` | `smart` | 一键完成内核 + 文件系统编译 |
| `do_install_env` | `env` | 安装 RT-Thread 开发环境 |

> **为什么使用自定义任务？** 标准任务链会触发大量自动依赖解析和包下载，对于 RT-Smart 这种独立的嵌入式构建场景，使用自定义任务可以精确控制构建流程，避免不必要的开销。

### 2.1.6 类（Class）

类是 `.bbclass` 文件，定义了可被多个配方共享的函数和变量。配方通过 `inherit` 关键字继承类。

smart-build 中的类：

| 类 | 文件 | 作用 |
| --- | --- | --- |
| `machine` | `classes/machine.bbclass` | 根据 `MACHINE` 变量解析目标架构、BSP 路径、工具链前缀 |
| `region-source` | `classes/region-source.bbclass` | 根据 `REGION` 配置选择代码源（Gitee / GitHub） |

### 2.1.7 配置文件

BitBake 使用多层配置体系：

| 文件 | 路径 | 作用 |
| --- | --- | --- |
| `local.conf` | `build/conf/local.conf` | 本地构建配置（机器类型、线程数等） |
| `bblayers.conf` | `build/conf/bblayers.conf` | 层注册配置（告诉 BitBake 使用哪些层） |
| `layer.conf` | `meta-smart/conf/layer.conf` | 层自身的配置（配方路径、优先级、PATH 设置） |
| `<machine>.conf` | `meta-smart/conf/machine/` | 机器特定配置（设备树、串口、镜像类型等） |

## 2.2 RT-Thread Smart 核心概念

### 2.2.1 RT-Thread

RT-Thread 是一款开源的实时操作系统（RTOS），广泛应用于物联网和嵌入式领域。它具有以下特点：

- 实时内核（纳秒级任务切换）
- 丰富的组件生态（文件系统、网络协议栈、设备驱动框架）
- 支持多种 CPU 架构（ARM、RISC-V、MIPS 等）
- 使用 SCons 构建系统
- 使用 Kconfig 配置系统

### 2.2.2 RT-Thread Smart（RT-Smart）

RT-Smart 是 RT-Thread 的高级版本，核心特征是**支持用户态与内核态分离**：

- **内核态**：运行 RT-Thread 内核和驱动程序，具有最高权限
- **用户态**：运行应用程序（如 BusyBox），通过系统调用与内核交互

这种架构类似于 Linux 的设计，但保持了 RTOS 的实时性和小巧性，特别适合资源受限但需要进程隔离的嵌入式场景。

### 2.2.3 BSP（Board Support Package）

BSP 是板级支持包，包含特定硬件平台的初始化代码、驱动程序和配置。在 RT-Thread 源码中，BSP 位于 `bsp/` 目录下。

smart-build 当前支持的 BSP：

| BSP | 架构 | 说明 |
| --- | --- | --- |
| `bsp/qemu-virt64-aarch64` | aarch64 | QEMU ARM64 虚拟平台 |
| `bsp/qemu-virt64-riscv` | riscv64 | QEMU RISC-V 64 虚拟平台 |
| `bsp/qemu-vexpress-a9` | arm | QEMU ARM32 虚拟平台 |
| `bsp/raspberry-pi/raspi4-64` | aarch64 | 树莓派 4B（64位） |
| `bsp/rockchip/rk3500` | aarch64 | 瑞芯微 RK3500 |
| `bsp/k230` | riscv64 | 嘉楠 K230 |

### 2.2.4 musl libc

RT-Smart 的用户态程序使用 **musl libc** 作为 C 运行时库。musl 是一个轻量级、高效的 C 标准库实现，特别适合嵌入式环境。对应的交叉编译工具链前缀为 `<arch>-linux-musleabi-`。

### 2.2.5 MACHINE 变量

`MACHINE` 是 smart-build 中最核心的配置变量，它决定了：

- 目标 CPU 架构（`ARCH`）
- BSP 路径（`BSP`）
- 交叉编译器前缀（`RTT_CC_PREFIX`）
- 内核配置文件（`<MACHINE>_defconfig`）
- BusyBox 补丁文件（`01_<ARCH>.diff`）
- 输出目录（`build/<MACHINE>/`）

`MACHINE` 的映射关系定义在 `meta-smart/classes/machine.bbclass` 中：

```python
bsps = {
    'qemuarm64':   {'ARCH': 'aarch64',  'BSP': 'bsp/qemu-virt64-aarch64'},
    'qemuriscv64': {'ARCH': 'riscv64',  'BSP': 'bsp/qemu-virt64-riscv'},
    'qemuarm32':   {'ARCH': 'arm',      'BSP': 'bsp/qemu-vexpress-a9'},
    'raspi4-64':   {'ARCH': 'aarch64',  'BSP': 'bsp/raspberry-pi/raspi4-64'},
    'rk3500':      {'ARCH': 'aarch64',  'BSP': 'bsp/rockchip/rk3500'},
    'k230':        {'ARCH': 'riscv64',  'BSP': 'bsp/k230'},
}
```

### 2.2.6 SCons

SCons 是 RT-Thread 内核使用的构建工具（类似 Make），基于 Python 编写。smart-build 在 BitBake 配方中调用 `scons` 来编译内核：

```bash
# 应用内核配置
scons --pyconfig-silent -C ${SCONS_BUILD_DIR}

# 编译内核
scons -C ${SCONS_BUILD_DIR}
```

### 2.2.7 ext4.img

ext4.img 是 RT-Smart 的根文件系统镜像，采用 ext4 文件系统格式。它包含：

- BusyBox 提供的基础命令工具（`ls`、`cat`、`cp`、`sh` 等）
- 系统目录结构（`/dev`、`/etc`、`/proc`、`/tmp` 等）
- 初始化配置（`/etc/inittab`）

这个镜像在 QEMU 中作为 virtio 块设备挂载，为 RT-Smart 提供用户态运行环境。
