# 第一章 上手指南

本章将引导你从零开始搭建 smart-build 开发环境，完成一次完整的编译，并在 QEMU 虚拟机上运行 RT-Thread Smart 系统。

## 1.1 环境要求

### 操作系统

推荐使用 **Ubuntu 22.04** 或更高版本。也可以使用项目提供的 Docker 环境（基于 Ubuntu 24.04），省去手动配置的步骤。

### 硬件要求

- 磁盘空间：至少 10GB（含工具链、源码和编译产物）
- 内存：建议 4GB 以上
- 网络：需要访问 GitHub / Gitee 下载源码

## 1.2 安装宿主机依赖

在 Ubuntu 系统上安装必要的编译工具和库：

```bash
sudo apt install build-essential git curl vim python3 pip tmux \
    bison flex file texinfo chrpath cpio diffstat gawk lz4 wget zstd \
    qemu-system-arm
sudo pip install requests scons kconfiglib tqdm
```

> **说明**：`qemu-system-arm` 用于运行 QEMU ARM64 / RISC-V 虚拟机。`scons` 是 RT-Thread 内核的构建工具，`kconfiglib` 用于内核配置。

## 1.3 获取源码

### 1.3.1 克隆 smart-build

```bash
git clone https://github.com/RT-Thread/smart-build.git
cd smart-build/
```

### 1.3.2 获取 OpenEmbedded-Core 和 BitBake

smart-build 依赖 OpenEmbedded-Core（提供基础构建框架）和 BitBake（任务执行引擎），需要单独克隆：

```bash
git clone git://git.openembedded.org/openembedded-core oe-core
git clone git://git.openembedded.org/bitbake
```

完成后，目录结构如下：

```
smart-build/
├── bitbake/          # BitBake 构建引擎
├── oe-core/          # OpenEmbedded-Core 基础层
├── meta-smart/       # RT-Smart 自定义层
├── tools/            # 辅助工具脚本
└── smart-env         # 环境初始化脚本
```

## 1.4 初始化构建环境

```bash
source smart-env
```

该命令会：

1. 检测 `oe-core` 和 `bitbake` 目录是否存在
2. 自动创建 `build/` 目录及其配置文件
3. 设置 `PATH`、`PYTHONPATH` 等环境变量
4. 切换到 `build/` 目录，准备开始构建

> **提示**：你也可以指定自定义的构建目录名称：
> ```bash
> source smart-env my-build
> ```

### 默认配置

环境初始化后，`build/conf/local.conf` 中默认的目标机器为：

```bash
MACHINE ??= "qemuarm64"
```

如需编译 RISC-V 版本，可修改为：

```bash
MACHINE ??= "qemuriscv64"
```

## 1.5 执行编译

### 一键完整编译（推荐首次使用）

```bash
bitbake smart -c build_all
```

这条命令会依次完成以下步骤：

1. **安装工具链** — 下载并解压对应架构的交叉编译器到 `build/toolchains/`
2. **编译 BusyBox** — 下载、打补丁、编译 BusyBox，生成 `ext4.img` 文件系统镜像
3. **编译内核** — 下载并编译 RT-Thread Smart 内核，生成 `rtthread.bin`

编译产物会输出到 `build/<MACHINE>/` 目录，例如 `build/qemuarm64/`。

### 分步编译

如果只需要执行某一步骤，可以使用以下命令：

```bash
# 仅安装交叉编译工具链
bitbake smart-gcc -c install_toolchain

# 仅编译 BusyBox 并生成 ext4.img（自动检查工具链）
bitbake busybox -c build_rootfs

# 仅编译 RT-Smart 内核（自动检查工具链）
bitbake smart -c build_kernel
```

## 1.6 运行 QEMU

编译完成后，进入目标机器的输出目录并启动 QEMU：

```bash
cd build/qemuarm64
./run_qemuarm64.sh
```

对于 RISC-V 64 版本：

```bash
cd build/qemuriscv64
./run_qemuriscv64.sh
```

启动成功后，你将看到 RT-Thread Smart 的终端交互界面，可以执行 shell 命令。

> **退出 QEMU**：按 `Ctrl+A`，然后按 `X` 退出 QEMU。

## 1.7 清理编译

smart-build 提供三个级别的清理命令：

```bash
# 清除 tmp 下的编译目录
bitbake smart -c clean

# 清除编译状态（下次将重新编译）
bitbake smart -c cleansstate

# 清除所有数据，包括下载的源码（慎用！）
bitbake smart -c cleanall
```

> **注意**：`cleanall` 会删除已下载的源码压缩包，下次编译需要重新下载，耗时较长，请谨慎使用。

## 1.8 使用 Docker 环境（可选）

如果你不想在宿主机上安装依赖，可以使用项目提供的 Docker 环境：

### 构建 Docker 镜像

```bash
cd tools/docker
sh ./docker_build.sh
```

### 启动容器

```bash
sh ./docker_run.sh
```

该脚本会：
- 以当前用户身份启动容器（避免权限问题）
- 挂载当前工作目录到容器中
- 预配置中国时区和国内镜像源

进入容器后，按照 [1.3.2](#132-获取-openembedded-core-和-bitbake) 开始操作即可。

> **提示**：容器退出后自动删除，但工作目录的数据保留在宿主机上。

## 1.9 常见问题

### Q: `source smart-env` 报错找不到 oe-core

确保已正确克隆 `oe-core` 和 `bitbake` 到 smart-build 根目录下。

### Q: 下载工具链 / 源码速度很慢

系统会自动检测地理位置，中国大陆用户会优先使用 Gitee 镜像。如果自动检测失败，可以在 `build/conf/local.conf` 中手动设置：

```bash
REGION = "CN"
```

### Q: 编译报错找不到交叉编译器

确认工具链已正确安装。可以单独执行：

```bash
bitbake smart-gcc -c install_toolchain
```

然后检查 `build/toolchains/` 目录下是否存在对应的编译器。
