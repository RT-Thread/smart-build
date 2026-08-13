[English](getting-started.md) | **中文**

# 入门指南

smart-build 从仓库根目录运行。启动脚本会将 `src/` 添加到 Python 导入路径；
以可编辑模式安装后，也可以通过已安装的控制台脚本使用相同命令。

## 安装 Python 依赖

```sh
python -m pip install -e .
```

Python 软件包要求 Python 3.10 或更高版本，并依赖 PyYAML 和 kconfiglib。

## 提供 RT-Thread 源码

在仓库根目录创建 `rt-thread` 路径，使其指向包含所选板卡对应 BSP 的
RT-Thread 源码树：

```sh
ln -s /path/to/rt-thread rt-thread
```

默认机器为 `qemu-virt-aarch64`，其 BSP 为 `qemu-virt64-aarch64`。

## 选择并提供交叉工具链

所选机器会在 `boards/<machine>/board.yaml` 中声明兼容工具链版本。
`menuconfig` 将所选软件包和版本写入工作区 `.config`。工具链按以下顺序查找：

```text
~/.env/tools/scripts/packages
```

可选的 `TOOLCHAIN_PATH`，以及仓库缓存：

```text
downloads/toolchains/<package>-<version>
```

使用 `./smart-build toolchain list --machine qemu-virt-aarch64` 查看版本和状态。
交互式构建发现所选的可下载工具链缺失时，会先询问是否下载到
`downloads/toolchains/`。脚本中使用
`./smart-build toolchain install --machine qemu-virt-aarch64 --version 12.2.0 --yes`。
下载完成后会按板卡声明的 SHA-256 校验，再进行解包。仅能由 Env SDK 提供的
版本必须通过 Env SDK 安装，或使用 `TOOLCHAIN_PATH` 指定外部目录。

## 提供 RT-Thread Env 软件包

内核软件包使用以下位置的 RT-Thread Env 安装：

```text
~/.env/tools/scripts/pkgs
~/.env/packages/packages
```

smart-build 会在所选 BSP 目录中，以 `--update` 参数调用第一个路径。该命令会
安装 BSP `.config` 所选择的软件包版本。Env 软件包索引必须已经安装并保持
最新；smart-build 不负责升级该索引。

## 检查环境

```sh
./smart-build doctor
```

可以通过全局选项或提供本地机器选项的命令选择其他机器：

```sh
./smart-build --machine qemu-vexpress-a9 doctor
./smart-build doctor --machine qemu-vexpress-a9
```

开始实际构建前，应解决所有检查失败项。

## 配置并构建

```sh
./smart-build menuconfig
./smart-build build all
```

`menuconfig` 用于选择机器、根文件系统、构建模式、镜像设置、软件包以及
`Cross toolchain` 菜单中的工具链版本和可选路径。它会写入工作区 `.config`，
目前还会更新所选板卡的 defconfig。提交前应检查板卡 defconfig 的变更。工具链
下载不会由 Kconfig 自动触发；缺少工具链时由构建确认，或使用
`toolchain install` 显式安装。

只处理某个构建域时，可以构建更小的目标：

```sh
./smart-build build kernel
./smart-build build package:zlib
./smart-build build rootfs
```

`build kernel` 会先将板卡的 `kernel_defconfig` 复制到 RT-Thread BSP，通过
`scons --pyconfig-silent` 进行规范化，在 warning 提示后删除未登记但会参与
构建的软件包目录，再运行 Env `pkgs --force-update`，最后编译内核。如果所选
内核软件包尚未安装，此更新过程可能访问网络。

输出位于 `build/<machine>/` 下，任务日志位于该机器目录的 `logs/` 子目录。
构建完成后还会写入 `manifest.yaml`；尽管后缀为 YAML，该文件目前包含 JSON
数据。

## 运行 QEMU

构建支持的 QEMU 机器后，运行：

```sh
./smart-build qemu-smoke
```

该命令会生成或使用对应机器的 QEMU 脚本，捕获启动输出，并检查已知的
RT-Thread 启动标记。验证网络或应用启动时，即使命令通过，也应检查冒烟测试
日志。

## 清理输出

```sh
./smart-build clean
./smart-build distclean
./smart-build download-clean
```

`clean` 删除所选机器的目录，`distclean` 删除所有构建目录，
`download-clean` 删除 `downloads/` 下的源码归档、工具链归档和已安装工具链。
