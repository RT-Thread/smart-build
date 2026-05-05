# 第三章 构建流程

本章从宏观角度介绍 smart-build 的整体构建流程，帮助你建立全局视角。

## 3.1 总体架构

smart-build 采用**分层架构**，自下而上分为三层：

```
┌─────────────────────────────────────────────────────────────────┐
│                      用户操作层                                  │
│  source smart-env → bitbake smart -c build_all → run_qemu.sh   │
├─────────────────────────────────────────────────────────────────┤
│                    meta-smart 业务层                              │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌───────────────┐  │
│  │smart-gcc │  │  busybox  │  │  smart   │  │     env       │  │
│  │(工具链)  │  │(文件系统) │  │ (内核)   │  │ (开发环境)    │  │
│  └──────────┘  └───────────┘  └──────────┘  └───────────────┘  │
│  ┌───────────────────┐  ┌──────────────────────────┐            │
│  │ machine.bbclass   │  │ region-source.bbclass     │            │
│  │ (架构 / BSP 映射) │  │ (源码镜像自动选择)       │            │
│  └───────────────────┘  └──────────────────────────┘            │
├─────────────────────────────────────────────────────────────────┤
│                  BitBake / OE-Core 基础层                        │
│  任务调度 · 依赖解析 · 配方解析 · 下载管理 · 缓存机制          │
└─────────────────────────────────────────────────────────────────┘
```

## 3.2 环境初始化流程

执行 `source smart-env` 时，发生以下步骤：

```
source smart-env
    │
    ├── 1. 检测 oe-core/ 和 bitbake/ 是否存在
    │       └── 不存在则报错退出
    │
    ├── 2. 设置环境变量
    │       ├── SMARTROOT  → 项目根目录
    │       ├── BUILDDIR   → 构建目录（默认 build/）
    │       ├── PATH       → 添加 bitbake/bin
    │       └── PYTHONPATH → 添加 bitbake/lib 和 oe-core/meta/lib
    │
    ├── 3. 创建构建目录（首次）
    │       ├── build/conf/local.conf    → 本地配置（MACHINE 等）
    │       └── build/conf/bblayers.conf → 层注册配置
    │
    └── 4. 切换到构建目录，显示帮助信息
```

## 3.3 完整编译流程

执行 `bitbake smart -c build_all` 时，BitBake 会解析所有配方的依赖关系，按照以下顺序执行：

```
bitbake smart -c build_all
    │
    │  ┌── 阶段一：工具链安装 ──────────────────────────────┐
    │  │                                                      │
    │  │  smart-gcc:do_install_toolchain                      │
    │  │    ├── 根据 MACHINE 确定目标架构（ARCH）             │
    │  │    ├── 查找本地缓存工具链                            │
    │  │    │   ├── 已存在 → 跳过，直接使用                   │
    │  │    │   └── 不存在 → 从 rt-thread.org 下载            │
    │  │    └── 解压到 build/toolchains/                      │
    │  │                                                      │
    │  └──────────────────────────────────────────────────────┘
    │
    │  ┌── 阶段二：开发环境安装（与阶段一并行）──────────────┐
    │  │                                                      │
    │  │  env:do_install_env                                  │
    │  │    ├── 检测地理区域（CN / GLOBAL）                   │
    │  │    ├── 克隆 env / packages / sdk 仓库               │
    │  │    └── 安装到 ~/.env/ 目录                           │
    │  │                                                      │
    │  └──────────────────────────────────────────────────────┘
    │
    │  ┌── 阶段三：文件系统构建 ─────────────────────────────┐
    │  │  依赖：smart-gcc:do_install_toolchain                │
    │  │                                                      │
    │  │  busybox:do_build_rootfs                             │
    │  │    ├── 下载 BusyBox 1.35.0 源码                     │
    │  │    ├── 解压并打补丁                                  │
    │  │    │   ├── 01_<ARCH>.diff    → 架构适配补丁          │
    │  │    │   └── 02_adapt_smart.diff → RT-Smart 适配补丁   │
    │  │    ├── 编译 BusyBox（静态链接）                      │
    │  │    ├── 创建 rootfs 目录结构                          │
    │  │    ├── 生成 256MB ext4.img                           │
    │  │    └── 拷贝到 build/<MACHINE>/ext4.img               │
    │  │                                                      │
    │  └──────────────────────────────────────────────────────┘
    │
    │  ┌── 阶段四：内核编译 ─────────────────────────────────┐
    │  │  依赖：smart-gcc + env + busybox                     │
    │  │                                                      │
    │  │  smart:do_build_all → smart:do_build_kernel           │
    │  │    ├── 获取 RT-Thread 源码                           │
    │  │    │   ├── 本地 rt-thread/ 目录存在 → 使用本地源码   │
    │  │    │   └── 不存在 → 从 Gitee/GitHub 克隆             │
    │  │    ├── 准备 lwext4 文件系统库                        │
    │  │    ├── 拷贝 <MACHINE>_defconfig 内核配置             │
    │  │    ├── scons --pyconfig-silent 应用配置              │
    │  │    ├── scons 编译内核                                │
    │  │    ├── 拷贝 rtthread.bin 到 build/<MACHINE>/         │
    │  │    └── 拷贝 QEMU 启动脚本（如存在）                 │
    │  │                                                      │
    │  └──────────────────────────────────────────────────────┘
    │
    └── 编译完成！输出目录：build/<MACHINE>/
         ├── rtthread.bin         # RT-Smart 内核二进制
         ├── ext4.img             # 根文件系统镜像
         └── run_<MACHINE>.sh     # QEMU 启动脚本
```

## 3.4 任务依赖关系

下图展示了 smart-build 中各任务的依赖关系：

```
                    smart:do_build_all
                     │            │
                     │            ▼
                     │    busybox:do_build_rootfs
                     │            │
                     ▼            ▼
              smart:do_build_kernel
               │            │
               ▼            ▼
  env:do_install_env    smart-gcc:do_install_toolchain
```

关键依赖说明：

- `do_build_all` 依赖 `busybox:do_build_rootfs`，确保文件系统先于内核编译完成
- `do_build_kernel` 依赖 `smart-gcc:do_install_toolchain` 和 `env:do_install_env`
- `do_build_rootfs` 依赖 `smart-gcc:do_install_toolchain`
- 清理任务（`clean`/`cleansstate`/`cleanall`）会级联清理所有依赖

## 3.5 构建输出结构

完整编译后，`build/` 目录的结构如下：

```
build/
├── conf/
│   ├── local.conf              # 本地构建配置
│   └── bblayers.conf           # 层注册配置
├── downloads/                  # 下载缓存（源码包）
├── sstate-cache/               # BitBake 状态缓存
├── tmp/                        # 临时编译目录
├── toolchains/                 # 交叉编译工具链
│   ├── aarch64-linux-musleabi_for_x86_64-pc-linux-gnu/
│   └── riscv64-linux-musleabi_for_x86_64-pc-linux-gnu/
└── <MACHINE>/                  # 目标机器输出
    ├── rtthread.bin            # RT-Smart 内核
    ├── ext4.img                # 根文件系统
    └── run_<MACHINE>.sh        # QEMU 启动脚本
```

## 3.6 源码获取策略

smart-build 对源码获取有智能化处理：

### RT-Thread 内核源码

1. **优先使用本地源码**：如果 `smart-build/rt-thread/` 目录存在，直接使用（方便本地开发调试）
2. **远程克隆**：如果本地不存在，根据地理区域自动选择 Gitee（中国）或 GitHub（全球）

### 工具链

1. **检查目标目录**：`build/toolchains/<TARGET_TC>/` 已存在则跳过
2. **检查本地缓存**：`~/.env/tools/scripts/packages/` 中存在则创建符号链接
3. **远程下载**：以上均不存在则从 `download.rt-thread.org` 下载

### 源码区域配置

`region-source.bbclass` 根据 `REGION` 选择源码地址：
- `REGION = "CN"`：使用 Gitee / 中国大陆镜像，加速下载
- `REGION = "GLOBAL"`：使用 GitHub / 官方源

默认值为 `CN`，可以在 `local.conf` 中手动指定 `REGION = "GLOBAL"`。
