# Smart Build 开发指南

## BitBake 与 OpenEmbedded-Core 介绍

### BitBake
BitBake 是一个通用的任务执行引擎，专门用于构建和编译软件包。它能够并行执行任务，处理依赖关系，并根据配方（recipes）中的指令执行构建步骤。

BitBake 的主要特点包括：
- 处理依赖关系（包括编译时依赖和运行时依赖）
- 支持跨平台编译
- 能够并行执行任务以提高构建效率
- 使用配方（recipes）和类（classes）来描述构建过程
- 支持配置继承和覆盖

### OpenEmbedded-Core
OpenEmbedded-Core（OE-Core）是一个精简的元数据集合，提供了现代嵌入式系统所需的基本功能。

它包含：
- 约830个核心配方（recipes）
- 通用的机器配置
- 常用的软件包管理功能
- 跨平台编译支持
- 基础系统组件

OE-Core 的设计理念是"小而精"，只包含最基本且经过充分测试的组件。这使得它非常适合作为自定义嵌入式 Linux 发行版的基础。用户可以在此基础上添加自己的层（layers）来扩展功能。

## Smart Build 项目简介

smart-build 是一个基于 BitBake 和 OpenEmbedded 构建系统的项目，其中 meta-smart 是一个自定义的层（Layer），可以被添加到 OpenEmbedded 构建系统中。

每个层下可以包含多个配方（recipes），配方是通过 BB 文件定义的。每个 BB 文件可以定义多个任务（Task）。
通过 bitbake 方式可以进行指定架构（如 aarch64, riscv64 等）工具链的安装，以及 busybox（用于生成文件系统 image）, rt-smart 的编译。

### 项目目录结构

```bash
smart-build/
├── bitbake/           # BitBake构建工具
├── oe-core/           # OpenEmbedded Core
├── meta-smart/        # 自定义层
├── tools/             # 工具脚本
└── smart-env          # 环境设置脚本
```

## Layer 创建指南

### 目录结构规范
Layer 及 Recipes 目录结构必须严格参考如下结构：

```bash
meta-myapp/                 # Layer定义必须以"meta-"为前缀
├── recipes-example/        # recipes定义必须以"recipes-"为前缀
│   └── example/           # 这一层目录不可或缺，名称随意
│       └── example_0.1.bb # bb文件必须带"_version"版本信息
└── conf/                  # 每个Layer必须包含conf/layer.conf
    └── layer.conf
```

### 配置文件说明
`layer.conf` 除了常规配置之外，额外增加了 PATH 环境变量的设置。BitBake 运行在独立的隔离环境中，自定义的 Task 需要使用系统工具，因此需要添加相关路径：

```bash
PATH := "${PATH}:/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin:${TOPDIR}/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu/bin:${TOPDIR}/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu/aarch64-linux-musleabi/bin"
```

## 配方（Recipe）说明

### 工具链配方
**文件位置**: `recipes-devtools/toolchain/smart-gcc_0.1.bb`

该配方根据平台架构下载对应的 toolchain 压缩包，并解压到 `build/toolchains` 目录。架构通过 `build/conf/local.conf` 中的 `MACHINE` 变量指定（如：`MACHINE ??= "qemuarm64"`）。

特点说明：
1. 关闭了 toolchain 压缩包的 MD5 校验（因为包可能会更新）：
   ```bash
   BB_STRICT_CHECKSUM = "0"
   ```
2. 支持 aarch64 和 riscv64 两种架构
3. 主要实现下载与解压操作

### 文件系统配方
**文件位置**: `recipes-core/busybox/busybox_0.1.bb`

该配方负责下载 busybox 源码包，解压、打补丁、编译，并生成 ext4.img 文件系统镜像。

注意事项：
1. 依赖工具链：
   ```bash
   do_build_rootfs[depends] = "smart-gcc:do_install_toolchain"
   ```
2. 需要提供源码的 MD5 校验码
3. 需要相关依赖文件（头文件和基础库）
4. 使用 mke2fs 工具生成 ext4.img（不使用需要 root 权限的命令）

### 内核配方
**文件位置**: `recipes-kernel/rt-thread/rt-smart_0.1.bb`

该配方负责下载和编译 RT-Thread 内核及其依赖。

配置说明：
1. Git 资源配置：
   - branch：指定分支
   - protocol：指定协议类型
   - name：设置仓库标识
   - subdir：指定存储位置

2. 版本控制：
   - 可通过 `SRCREV_$name` 设置仓库哈希值
   - 使用 `AUTOINC` 获取最新代码

3. 特殊处理：
   - 预下载 env、packages、sdk 依赖库
   - 预下载 lwext4 仓库避免动态下载错误
   - 支持 `do_build_kernel` 和 `do_build_all` 任务
   - 扩展了清理任务的范围

## Task 系统说明

### 为什么使用自定义 Task？
标准任务链：
```bash
do_fetch → do_unpack → do_patch → do_configure → do_compile → do_install → do_build
```

使用自定义 task 可以避免下载大量依赖包。注意：避免使用系统预定义的 task 名称。

### Task 管理命令
```bash
# 查看任务列表
$ bitbake -c listtasks $recipe-name

# 查看任务依赖关系
$ bitbake -g $recipe-name  # 结果在 task-depends.dot
```

## 使用指南

### 环境初始化
```bash
# 使用默认 build 目录
$ source smart-env

# 使用自定义目录
$ source smart-env custom-build
```

### 构建命令
```bash
# 完整构建（推荐首次使用）
$ bitbake smart -c build_all

# 单独步骤
$ bitbake smart-gcc -c install_toolchain  # 安装工具链
$ bitbake busybox -c build_rootfs         # 构建文件系统
$ bitbake smart -c build_kernel           # 构建内核

# 清理命令
$ bitbake smart -c clean        # 清理编译目录
$ bitbake smart -c cleansstate  # 清理编译状态
$ bitbake smart -c cleanall     # 清理所有（包括下载的源码）
```

## BSP 支持扩展

### 当前支持的架构
通过 `build/conf/local.conf` 配置：
```bash
MACHINE ??= "qemuarm64"   # 编译 aarch64
MACHINE ??= "qemuriscv64" # 编译 riscv64
```

### 添加新 BSP 支持
需要修改以下内容：

1. **工具链支持**：
   - 修改 `recipe_toolchain/toolchain/smart-gcc.bb`
   - 添加新的 toolchain 下载信息

2. **Busybox 支持**：
   - 参照 `01_qemuarm64.diff` 创建新的 patch
   - 命名为 `01_$MACHINE.diff`
   - 提供必要的头文件和库文件

3. **BSP 编译支持**：
   - 在 `rt-smart.bb` 中添加支持
   - 如有必要，创建新的 bb 文件

4. **QEMU 支持**：
   - 参考 `tools/run_qemuarm64.sh`
   - 创建 `run_$MACHINE.sh`

5. **工具链路径**：
   - 修改 `conf/layer.conf`
   - 添加新的 Toolchain PATH

