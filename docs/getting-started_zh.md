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

## 提供交叉工具链

交叉工具链从以下路径发现：

```text
~/.env/tools/scripts/packages
```

所需的软件包名称、目标三元组、编译器前缀和动态加载器在
`boards/<machine>/board.yaml` 中声明。smart-build 不负责下载或安装交叉
工具链。

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

`menuconfig` 用于选择机器、根文件系统、构建模式、镜像设置和软件包。它会
写入工作区 `.config`，目前还会更新所选板卡的 defconfig。提交前应检查板卡
defconfig 的变更。

只处理某个构建域时，可以构建更小的目标：

```sh
./smart-build build kernel
./smart-build build package:zlib
./smart-build build rootfs
```

`build kernel` 会先将板卡的 `kernel_defconfig` 复制到 RT-Thread BSP，通过
`scons --pyconfig-silent` 进行规范化，再运行 Env `pkgs --update`，最后编译
内核。如果所选内核软件包尚未安装，此更新过程可能访问网络。

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
`download-clean` 删除已下载的归档文件。
