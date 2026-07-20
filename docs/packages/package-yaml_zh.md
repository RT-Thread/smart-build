[English](package-yaml.md) | **中文**

# 软件包描述文件参考

软件包描述使用 YAML schema 版本 1，并保存在
`packages/<name>/package.yaml`。

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
| `description` | 否 | 面向用户的软件包说明 |
| `depends` | 否 | 依赖名称或已提供的能力 |
| `selects` | 否 | 自动选择的软件包或能力 |
| `conflicts` | 否 | 不能同时选择的软件包 |
| `provides` | 否 | 此软件包提供的能力 |
| `requires_toolchain` | 否 | 所需的工具链能力 |
| `options` | 否 | 软件包选项定义 |
| `source` | 源码构建时为是 | 仓库目录或归档源码 |
| `build` | 是 | 构建后端配置 |
| `install` | 取决于后端 | rootfs 安装路径 |
| `smoke` | 否 | 运行时检查命令及可选的预期标准输出 |
| `configure` | 否 | 交互式上游配置映射 |

## 关系

`depends`、`selects`、`conflicts`、`provides` 和 `requires_toolchain` 通常使用
列表。出于兼容性考虑，`depends` 也接受逗号分隔的字符串。依赖可以引用软件包
名称，或者另一个软件包在 `provides` 字段中列出的名称。

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
  files:
    - configure
```

归档解压会拒绝路径遍历和不安全的链接目标。`local_files` 会从软件包目录复制到
准备好的源码树中。

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
