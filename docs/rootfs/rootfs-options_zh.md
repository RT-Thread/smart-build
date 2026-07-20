[English](rootfs-options.md) | **中文**

# 根文件系统支持

smart-build 当前定义了四种 rootfs 选项。

| 选项 | 构建模式 | 软件包 | 镜像 |
| --- | --- | --- | --- |
| `minimal` | static、dynamic、mixed | `hello` | `minirootfs.img` |
| `basic` | static | BusyBox 和 `hello` | `busybox-rootfs.img` |
| `full` | static、dynamic、mixed | profile 或手动选择 | `rootfs.img` |
| `none` | 无 | 无 | 无 |

完整 rootfs 的 profile 如下：

- `base`：hello 和 zlib。
- `devel`：hello、zlib 和 MicroPython。
- `full`：`rootfs/full/rootfs.yaml` 当前包含的所有软件包描述。

软件包依赖和 `selects` 关系可能会添加 profile 列表之外的软件包。

## 镜像格式

ext4 是唯一已经实现的镜像创建后端。FAT 和 romfs 会显示在 Kconfig 中，但在
实际镜像构建期间会失败。所有当前板卡均应使用 ext4。

镜像创建和内核文件系统支持相互独立。smart-build 使用宿主机工具创建 rootfs
镜像；RT-Thread 内核的 ext4 支持则来自内核 menuconfig 中选择并由 Env 安装的
lwext4 软件包。

可扩展 ext4 镜像会在暂存 rootfs 需要更多空间时，扩展到配置的最小值以上。
固定大小镜像无法容纳暂存文件时会构建失败。

## 禁用 rootfs 模式

`ROOTFS=none` 会禁用 rootfs 和镜像组装任务。仅构建内核的行为尚未在所有
QEMU 命令中完全一致，因此使用此模式进行冒烟测试前，应检查生成的脚本。
