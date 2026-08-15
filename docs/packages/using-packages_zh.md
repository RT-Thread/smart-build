[English](using-packages.md) | **中文**

# 使用软件包

软件包通过配置的 rootfs 选择，也可以按名称直接构建。

## 构建单个软件包

```sh
./smart-build build package:hello
./smart-build build package:curl
```

解析器会加载每个 `packages/<name>/package.yaml`，解析 provider 和依赖，拒绝
已声明的冲突，并创建源码和构建任务。例如，选择 curl 还会选择 OpenSSL 和
zlib。

下载的归档文件保存在 `downloads/` 下。准备后的源码、工作目录、日志和暂存
文件保存在 `build/<machine>/` 下。

## 为 rootfs 选择软件包

运行：

```sh
./smart-build menuconfig
```

选择完整 rootfs 以手动选择软件包，或使用其某个 profile。软件包 Kconfig
条目由软件包元数据生成，其中包括版本、依赖、冲突、选项选择，以及显示在菜单中的软件包描述。
勾选某个软件包时会自动选中它声明的依赖，因此即使依赖库尚未打开，软件包本身
也始终可以勾选。菜单按 Networking、Libraries、Development and testing
等类别分组展示。

## 配置软件包

包含 `configure` 映射的软件包，以及使用 native Kconfig 的独立 RT-Thread SCons
包，可以使用以下命令配置：

```sh
./smart-build configure package:<name>
```

native Kconfig 配置由 smart-build 保存，不修改软件包源码目录，也不会在配置
阶段下载在线包。其他没有 `configure` 映射的软件包不提供交互式配置步骤。

## 软件包输出

库软件包会暂存头文件和库文件。可执行软件包会将文件暂存到其构建和安装元数据
声明的 rootfs 路径。根文件系统组装步骤会拒绝来自不同软件包的冲突文件。

部分元数据选项目前会被记录，但并非所有软件包后端都会使用。更改软件包特定
选项时，应确认生成的文件。
