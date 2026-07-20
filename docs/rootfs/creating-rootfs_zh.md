[English](creating-rootfs.md) | **中文**

# 添加根文件系统类型

每种 rootfs 类型使用一个小写、连字符命名的目录：

```text
rootfs/<type>/
  Kconfig
  rootfs.yaml
```

## 添加描述文件

```yaml
schema_version: 1
kind: rootfs
name: example
version: 0.1.0
default_profile: base
profiles:
  base:
    packages:
      - hello
filesystem:
  type: ext4
```

通用描述加载器要求 `schema_version`、`kind`、`name` 和 `version`。rootfs
软件包和 profile 行为由 rootfs 构建域解释，因此应以现有 minimal 和 full
描述作为当前示例。

## 添加 Kconfig

定义 rootfs 选择布尔值及派生的 `ROOTFS`、`ROOTFS_BUILD_MODE`、镜像格式、
镜像大小和大小模式。由 `rootfs/Kconfig` source 新文件，并将其加入 rootfs
choice。

只应提供 rootfs 和 image 构建域能够执行的值。特别是，当前镜像后端仅支持
ext4。

## 添加执行支持

仅添加元数据不会创建构建域。新的 rootfs 布局或镜像类型必须根据需要映射到
rootfs、image、任务规划和 QEMU 构建域中的实际任务。对于受支持的配置，每个
公开构建目标都必须能够解析为真实任务。

## 验证类型

测试所有受支持的机器、构建模式、profile 和镜像大小行为：

```sh
./smart-build menuconfig
./smart-build build rootfs
./smart-build build all
./smart-build qemu-smoke
python -m pytest
```

还应检查禁用 rootfs 和不支持的组合，确保它们在执行构建任务前以清晰的配置
错误失败。
