[English](package-yaml.md) | **中文**

# 软件包描述文件参考

软件包描述使用 YAML schema 版本 1，并保存在
`packages/<name>/package.yaml`、`packages/ros2/<name>/package.yaml` 或
`packages/host/<name>/package.yaml`。

## 通用字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema_version` | 是 | 当前必须为 `1` |
| `kind` | 是 | 必须为 `package` |
| `name` | 是 | 与目录匹配的软件包名称 |
| `version` | 是 | 描述版本，并作为默认软件包版本的后备值 |
| `versions` | 否 | 非空的可选软件包版本列表 |
| `default_version` | 否 | `versions` 中的一个条目 |
| `type` | 取决于构建 | `library` 或 `executable` |
| `description` | 否 | 面向用户的软件包说明，会写入生成的 Kconfig 菜单项和 help，最多 80 个字符 |
| `category` | 否 | menuconfig 分组；未填写时使用内置分类表 |
| `depends` | 否 | 构建所需的软件包或能力；menuconfig 会自动选中它们 |
| `host_depends` | 否 | 仅开发主机的构建依赖；会构建但不会进入目标 IPKG |
| `selects` | 否 | 额外自动选中的软件包或能力 |
| `conflicts` | 否 | 不能同时选择的软件包 |
| `provides` | 否 | 此软件包提供的能力 |
| `requires_toolchain` | 否 | 所需的工具链能力 |
| `options` | 否 | 软件包选项定义 |
| `kconfig` | native SCons 包 | native Kconfig 来源和软件包选择符号 |
| `source` | 源码构建时为是 | 仓库目录或归档源码 |
| `build` | 是 | 构建后端配置 |
| `install` | 取决于后端 | rootfs 安装路径 |
| `smoke` | 否 | 运行时检查命令及可选的预期标准输出 |
| `configure` | 否 | 交互式上游配置映射 |

## 关系

`depends`、`host_depends`、`selects`、`conflicts`、`provides` 和
`requires_toolchain` 通常使用列表。出于兼容性考虑，`depends` 和
`host_depends` 也接受逗号分隔的字符串。依赖可以引用软件包名称，或者另一个
软件包在 `provides` 字段中列出的名称。生成的软件包 Kconfig 会把 `depends`、
`host_depends` 和 `selects` 都写成 `select`，因此软件包始终可以勾选，并自动
带上所需依赖。Host 依赖只参与构建图，不进入目标 IPKG。

生成的 `packages/Kconfig` 索引会按 Networking、Libraries、Development and
testing 等菜单分组。可用 `category` 覆盖默认分组；未分类的软件包会出现在
Other 中。

## 选项

选项类型包括 `bool`、`choice` 和 `string`：

```yaml
options:
  shared:
    type: bool
    prompt: Build shared library
    default: true
  compression_level:
    type: choice
    prompt: Default compression level
    choices: [fast, balanced, best]
    default: balanced
  heap_size:
    type: string
    prompt: Heap size
    default: 64k
```

选项会生成软件包 Kconfig 符号，并记录到 manifest 中。当前构建后端不会始终
将这些选项转发给构建脚本，因此软件包作者必须确认某个选项是否影响其输出。

## 仓库内源码

```yaml
source:
  directory: apps/example
  files:
    - CMakeLists.txt
    - main.c
```

该目录必须位于仓库内。声明的源码文件必须是该目录下的普通文件。

## 归档源码

```yaml
source:
  type: archive
  url: https://example.org/example-1.0.0.tar.gz
  archive: example-1.0.0.tar.gz
  sha256: <sha256>
  strip_root: true
  local_files:
    - sbuild.py
    - patches/example.patch
  patches:
    - example.patch
  files:
    - configure
```

对于上游未提供 hash 的尽力导入软件包，可以显式使用
`source.allow_unverified: true`。普通软件包定义仍应使用不可变的归档 URL 和
SHA-256 校验值。

归档解压会拒绝路径遍历和不安全的链接目标。`local_files` 会从软件包目录复制到
准备好的源码树中。`patches` 中的每一项还必须列入 `local_files`；补丁会在恢复
配置前按声明顺序通过 `git apply` 应用到准备好的源码树，任一补丁失败都会终止
源码准备。

## Python 后端

```yaml
build:
  python:
    script: sbuild.py
    outputs:
      - /usr/bin/example
      - /usr/lib/libexample.a
    upstream_markers:
      - configure
install:
  path: /usr/bin/example
```

每个声明的输出都必须创建在软件包暂存目录下。元数据中的输出路径是绝对
rootfs 路径，但不能越出暂存目录。

## ament CMake 后端

```yaml
type: library
category: ROS 2
build:
  ament_cmake:
    testing: false
    linkage: shared
    host_python: sdk
    cmake_args:
      - -DCMAKE_BUILD_TYPE=Release
    outputs:
      - /usr/lib
      - /usr/include
      - /usr/share
```

此后端会写入 Generic/UNIX 的 CMake toolchain 文件；除非 `testing` 为 true，
否则关闭测试；按 `linkage` 应用链接策略；安装时将 `DESTDIR` 设为软件包
暂存目录。`CMAKE_PREFIX_PATH` 和 `AMENT_PREFIX_PATH` 包含完整依赖闭包以及
`build/<machine>/host/ros2-sdk`。`host_python: sdk` 时，CMake 和 ament 生成器
使用 Host SDK 虚拟环境。toolchain、prefix、安装路径和 Python 参数不能由
`cmake_args` 覆盖。安装后必须存在已声明的输出。

## CMake 可执行程序后端

```yaml
type: executable
source:
  directory: apps/example
  files: [CMakeLists.txt, main.c]
build:
  cmake:
    outputs:
      static: [/bin/example-static]
      dynamic: [/bin/example-dynamic]
      mixed: [/bin/example-static, /bin/example-dynamic]
    options:
      - -DCMAKE_BUILD_TYPE=Release
```

所选 rootfs 构建模式决定输出集合。CMake 选项不能覆盖由 smart-build 管理的
工具链、安装前缀或链接方式定义。

## 独立 RT-Thread SCons 后端

此后端仅支持经过调整的、仓库内的独立 RT-Thread 软件包，目录结构固定为：

```text
packages/example/
  package.yaml
  source/
    Kconfig
    SConstruct
    SConscript
    main.c
```

软件包在 RT-Thread 和 smart-build 中共同使用唯一的 `source/Kconfig`，不得在
`package.yaml` 中再声明生成式 `options` 或多个版本。选择符号必须由该 Kconfig
入口所包含的 Kconfig 闭包定义。软件包本地 bool 可以选择 RT-Thread Env 在线包，
同时让 smart-build 软件包选择保持显式。

```yaml
type: executable
source:
  directory: packages/webclient/source
kconfig:
  mode: native
  source: source/Kconfig
  symbol: PACKAGE_WEBCLIENT
build:
  rtthread_scons:
    supported_linkage: [static]
    install_target: install
    outputs:
      - /bin/webclient
```

需要使用 RT-Thread 在线包时，native Kconfig 可以按独立 RT-Thread 工程的方式
包含已安装的 Env 索引：

```kconfig
config PKGS_DIR
    string
    option env="PKGS_ROOT"
    default "packages"

menu "webclient"

config PACKAGE_WEBCLIENT
    bool "Enable webclient"
    select PKG_USING_WEBCLIENT

source "$PKGS_DIR/Kconfig"

endmenu
```

`./smart-build configure package:<name>` 会打开该 native Kconfig，并保存以
`kconfig.symbol` 为根的配置子树。配置阶段不会运行 SCons 或 Env
`pkgs --update`；后续构建会使用已保存的值。

`source.directory`、`kconfig.source`、`SConstruct`、`SConscript` 和 `install`
target 均由此契约固定。每个 output 都是绝对 rootfs 路径。install target 必须在
`DESTDIR` 下仅创建这些普通文件；缺失文件、未声明文件、链接和越界路径都会被
拒绝。

当 rootfs 构建模式为 `static` 或 `dynamic` 时，该模式作为 `LINKAGE` 传入，并且
必须列在 `supported_linkage` 中。`mixed` rootfs 接受软件包支持的任意链接模式；
smart-build 选择 `supported_linkage` 的第一项，因此列表顺序同时表示软件包的
选择优先级。smart-build 提供以下构建环境；从 `BUILD_DIR` 到 `LINKAGE` 的变量
还会作为 SCons 命令行变量传入：

| 变量 | 含义 |
| --- | --- |
| `BUILD_DIR` | 位于隔离源码副本之外的软件包构建目录 |
| `DESTDIR` | 软件包专用暂存目录 |
| `KCONFIG_CONFIG` | 生成的软件包配置快照 |
| `SMART_SDK_DIR` | 仓库中的 RT-Thread Smart SDK 软件包 |
| `RTT_ROOT` | 仓库中的 RT-Thread 源码根目录 |
| `RTTHREAD_TOOLS_DIR` | RT-Thread Python 构建工具目录 |
| `CROSS_COMPILE` | 所选 machine 的工具链前缀 |
| `MACHINE` | 所选目标 machine |
| `LINKAGE` | 为当前软件包选择的链接模式 |
| `ENV_ROOT` | 已安装的 RT-Thread Env 根目录 |
| `PKGS_ROOT` | Kconfig 使用的 Env 软件包元数据根目录 |
| `PKGS_DIR` | Kconfig 使用的 Env 软件包元数据根目录 |
| `PYTHONPATH` | 包含 `RTTHREAD_TOOLS_DIR` |

smart-build 会把 `source/` 复制到 machine work 目录，并排除本地生成状态。随后
写入 `.config`，执行 `scons --pyconfig-silent`，再执行已安装 Env 的
`pkgs --update`。校验生成的 `packages/SConscript`、软件包状态和下载源码后，
从同一隔离副本执行 `scons install`。源软件包不会被修改。

在线依赖仍由 RT-Thread Env 管理，并通过 `packages/SConscript` 参与构建。它们
不会成为独立的 smart-build package 或 IPKG；只有顶层独立工程声明的输出会被
打包。此后端不支持完整 userapps、应用扫描、其他 SConstruct 入口名、任意远程
源码准备，也不会解释 SCons 脚本。
