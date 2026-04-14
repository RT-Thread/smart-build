# 第六章 示例：增加软件包

本章演示如何将一个开源软件包集成到 smart-build 中。我们以一个轻量级 JSON 解析库 **cJSON** 为例，展示从下载源码到集成编译的完整流程。

## 6.1 场景说明

假设你的项目需要在 RT-Smart 用户态程序中解析 JSON 数据，需要引入 [cJSON](https://github.com/DaveGamble/cJSON) 这个开源库。我们将：

1. 创建一个 BitBake 配方来下载和编译 cJSON
2. 编写一个使用 cJSON 的示例程序
3. 将两者集成到构建系统中

## 6.2 创建配方目录

```bash
mkdir -p meta-smart/recipes-libs/cjson/files
```

## 6.3 编写配方文件

创建 `meta-smart/recipes-libs/cjson/cjson_0.1.bb`：

```bash
inherit machine

SUMMARY = "cJSON - Ultralightweight JSON parser in ANSI C"
DESCRIPTION = "cJSON library cross-compiled for RT-Smart"
LICENSE = "MIT"

# 源码下载地址（以 GitHub Release 为例）
CJSON_VERSION = "1.7.18"
SRC_URI = "https://github.com/DaveGamble/cJSON/archive/refs/tags/v${CJSON_VERSION}.tar.gz"

python () {
    handle_machine(d)
}

do_build_cjson() {
    bbplain "##############################"
    bbplain "****** Building cJSON library"

    # 下载并解压源码
    uri="${SRC_URI}"
    SRC="${WORKDIR}/cJSON-${CJSON_VERSION}"

    if [ ! -d "${SRC}" ]; then
        python3 -c "
import bb.fetch2
uri = '${SRC_URI}'.split()
fetcher = bb.fetch2.Fetch(uri, d)
fetcher.download()
fetcher.unpack('${WORKDIR}')
"
    fi

    CC="${RTT_CC_PREFIX}gcc"
    AR="${RTT_CC_PREFIX}ar"

    # 编译 cJSON 为静态库
    bbplain "****** Compiling cJSON"
    cd ${SRC}
    ${CC} -c cJSON.c -o cJSON.o -static
    ${AR} rcs libcjson.a cJSON.o

    # 安装头文件和库
    INSTALL_DIR="${TOPDIR}/${MACHINE}/sdk"
    mkdir -p ${INSTALL_DIR}/include ${INSTALL_DIR}/lib
    cp cJSON.h ${INSTALL_DIR}/include/
    cp libcjson.a ${INSTALL_DIR}/lib/
    bbplain "****** cJSON installed to: ${INSTALL_DIR}"
}
do_build_cjson[depends] = "smart-gcc:do_install_toolchain"

addtask do_build_cjson
```

### 配方要点

| 要素 | 说明 |
| --- | --- |
| `SRC_URI` | 指定源码下载地址，支持 HTTP、Git 等多种协议 |
| `CJSON_VERSION` | 使用变量管理版本号，便于后续升级 |
| `inherit machine` | 获取交叉编译器前缀 |
| `do_build_cjson` | 自定义编译任务 |

## 6.4 编译软件包

```bash
source smart-env
bitbake cjson -c build_cjson
```

编译完成后，头文件和库文件会安装到 `build/<MACHINE>/sdk/` 目录：

```
build/<MACHINE>/sdk/
├── include/
│   └── cJSON.h
└── lib/
    └── libcjson.a
```

## 6.5 编写使用示例

创建一个使用 cJSON 的应用程序配方。

### 目录结构

```bash
mkdir -p meta-smart/recipes-apps/json-demo/files
```

### 源码 `meta-smart/recipes-apps/json-demo/files/json_demo.c`

```c
/* json_demo.c - cJSON 使用示例 */
#include <stdio.h>
#include <stdlib.h>
#include "cJSON.h"

int main(void)
{
    /* 创建一个 JSON 对象 */
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "name", "RT-Smart");
    cJSON_AddStringToObject(root, "type", "RTOS");
    cJSON_AddNumberToObject(root, "version", 5.0);

    cJSON *features = cJSON_CreateArray();
    cJSON_AddItemToArray(features, cJSON_CreateString("user-space"));
    cJSON_AddItemToArray(features, cJSON_CreateString("real-time"));
    cJSON_AddItemToArray(features, cJSON_CreateString("multi-arch"));
    cJSON_AddItemToObject(root, "features", features);

    /* 输出 JSON 字符串 */
    char *json_str = cJSON_Print(root);
    printf("Generated JSON:\n%s\n", json_str);

    /* 清理 */
    free(json_str);
    cJSON_Delete(root);

    return 0;
}
```

### 配方 `meta-smart/recipes-apps/json-demo/json-demo_0.1.bb`

```bash
inherit machine

SUMMARY = "JSON demo application using cJSON on RT-Smart"
LICENSE = "MIT"

python () {
    handle_machine(d)
}

do_build_json_demo() {
    bbplain "##############################"
    bbplain "****** Building json-demo"

    CC="${RTT_CC_PREFIX}gcc"
    SDK_DIR="${TOPDIR}/${MACHINE}/sdk"
    DEMO_SRC="${FILE_DIRNAME}/files/json_demo.c"

    ${CC} ${DEMO_SRC} -o ${WORKDIR}/json_demo \
        -I${SDK_DIR}/include \
        -L${SDK_DIR}/lib \
        -lcjson \
        -static

    cp ${WORKDIR}/json_demo ${TOPDIR}/${MACHINE}/
    bbplain "****** json_demo installed to: ${TOPDIR}/${MACHINE}/"
}
do_build_json_demo[depends] = "cjson:do_build_cjson"

addtask do_build_json_demo
```

> 注意配方中的 `[depends]` 声明了对 cjson 的依赖，BitBake 会确保 cjson 先编译完成。

## 6.6 编译并运行

```bash
# 编译 json-demo（自动触发 cjson 编译）
bitbake json-demo -c build_json_demo
```

将 `json_demo` 打包到 ext4.img 后，在 RT-Smart 中运行：

```
msh /> json_demo
Generated JSON:
{
    "name":     "RT-Smart",
    "type":     "RTOS",
    "version":  5.0,
    "features": ["user-space", "real-time", "multi-arch"]
}
```

## 6.7 集成 Git 仓库形式的软件包

对于以 Git 仓库形式发布的软件包，可以使用 Git 协议下载。以下是一个通用模板：

```bash
inherit machine
inherit region-source

SUMMARY = "My Package"
LICENSE = "MIT"

SRC_URI_GITEE = "git://gitee.com/mirrors/my-package.git;branch=master;protocol=https"
SRC_URI_GITHUB = "git://github.com/original/my-package.git;branch=master;protocol=https"

SRCREV = "AUTOINC"

python () {
    handle_machine(d)
    set_preferred_source(d)
}

do_build_my_package() {
    bbplain "****** Building my-package"
    cd ${WORKDIR}/git
    # 执行编译命令...
}
do_build_my_package[depends] = "smart-gcc:do_install_toolchain"

addtask do_build_my_package after do_unpack
```

**关键点**：

- 继承 `region-source` 实现源码镜像自动切换
- `SRCREV = "AUTOINC"` 表示始终拉取最新代码（也可以指定具体的 commit hash）
- `after do_unpack` 确保源码先被解压

## 6.8 目录结构总结

```
meta-smart/
├── recipes-libs/
│   └── cjson/
│       └── cjson_0.1.bb            # 库的编译配方
└── recipes-apps/
    └── json-demo/
        ├── json-demo_0.1.bb        # 应用的编译配方
        └── files/
            └── json_demo.c         # 应用源码
```

## 6.9 配方编写规范总结

通过以上示例，可以总结出 smart-build 配方的编写模式：

### 目录命名规范

| 目录 | 说明 |
| --- | --- |
| `recipes-libs/` | 库和中间件 |
| `recipes-apps/` | 用户应用程序 |
| `recipes-core/` | 核心系统组件 |
| `recipes-devtools/` | 开发工具 |
| `recipes-kernel/` | 内核和驱动 |
| `recipes-boards/` | 板卡特定配方 |
| `recipes-example/` | 示例和模板 |

目录前缀**必须**为 `recipes-`，否则 BitBake 无法识别。

### 配方模板

一个最小可用的 smart-build 配方：

```bash
inherit machine

SUMMARY = "My Recipe"
LICENSE = "MIT"

python () {
    handle_machine(d)
}

do_my_task() {
    bbplain "****** Executing my_task"
    # 你的编译逻辑
}
do_my_task[depends] = "smart-gcc:do_install_toolchain"

addtask do_my_task
```

### 常见注意事项

1. **避免使用 BitBake 预定义的任务名**（如 `do_compile`、`do_install`），使用自定义名称以避免与标准任务链冲突
2. **任务依赖必须显式声明**，使用 `[depends]` 语法
3. **配方文件名必须包含版本号**，格式为 `<name>_<version>.bb`
4. **工具链依赖**：几乎所有编译类配方都需要依赖 `smart-gcc:do_install_toolchain`
