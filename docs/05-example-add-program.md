# 第五章 示例：增加全新程序

本章演示如何从零编写一个用户态应用程序，并将其集成到 smart-build 的构建系统中。我们将创建一个名为 **"hello"** 的程序，它在 RT-Smart 系统中打印一条欢迎信息。

## 5.1 背景知识

RT-Smart 支持用户态程序，这些程序：

- 使用 musl libc 标准库
- 通过 RT-Thread 提供的交叉编译工具链编译
- 以 ELF 可执行文件的形式运行在用户态
- 可以访问 RT-Thread 的系统调用接口

## 5.2 创建目录结构

在 `meta-smart` 层中创建新的配方目录：

```bash
mkdir -p meta-smart/recipes-apps/hello
```

## 5.3 编写源码

创建源码文件 `meta-smart/recipes-apps/hello/files/hello.c`：

```bash
mkdir -p meta-smart/recipes-apps/hello/files
```

```c
/* hello.c - RT-Smart 用户态示例程序 */
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[])
{
    printf("Hello from RT-Smart!\n");
    printf("This is a user-space application.\n");

    if (argc > 1) {
        printf("Arguments:\n");
        for (int i = 1; i < argc; i++) {
            printf("  [%d] %s\n", i, argv[i]);
        }
    }

    return 0;
}
```

## 5.4 编写 BitBake 配方

创建配方文件 `meta-smart/recipes-apps/hello/hello_0.1.bb`：

```bash
inherit machine

SUMMARY = "Hello World application for RT-Smart"
DESCRIPTION = "A simple user-space application demonstrating RT-Smart development"
LICENSE = "MIT"

python () {
    handle_machine(d)
}

do_build_hello() {
    bbplain "##############################"
    bbplain "****** Building hello application"

    # 设置编译器和标志
    CC="${RTT_CC_PREFIX}gcc"
    HELLO_SRC="${FILE_DIRNAME}/files/hello.c"

    # 编译
    bbplain "****** Compiling hello.c"
    ${CC} ${HELLO_SRC} -o ${WORKDIR}/hello -static

    # 安装到输出目录
    if [ ! -d "${TOPDIR}/${MACHINE}" ]; then
        mkdir -p ${TOPDIR}/${MACHINE}
    fi
    cp ${WORKDIR}/hello ${TOPDIR}/${MACHINE}/
    bbplain "****** hello application installed to: ${TOPDIR}/${MACHINE}/hello"
}
do_build_hello[depends] = "smart-gcc:do_install_toolchain"

addtask do_build_hello
```

### 配方关键说明

| 字段 / 语句 | 说明 |
| --- | --- |
| `inherit machine` | 继承 machine 类，获取架构和工具链信息 |
| `handle_machine(d)` | 在 Python 阶段解析 MACHINE 变量，设置 ARCH、RTT_CC_PREFIX 等 |
| `do_build_hello` | 自定义任务，负责编译和安装 |
| `[depends]` | 声明依赖工具链安装任务 |
| `FILE_DIRNAME` | BitBake 内置变量，指向当前 `.bb` 文件所在目录 |
| `WORKDIR` | BitBake 为每个配方分配的工作目录 |
| `TOPDIR` | 构建根目录（即 `build/`） |

## 5.5 执行编译

```bash
source smart-env
bitbake hello -c build_hello
```

编译成功后，`hello` 可执行文件会出现在 `build/<MACHINE>/` 目录下。

## 5.6 集成到文件系统

要让程序在 RT-Smart 启动后可用，需要将其打包进 ext4.img。有两种方式：

### 方式一：手动拷贝到 rootfs（快速验证）

在 busybox 配方编译完成后，将 hello 二进制手动拷贝到 rootfs 中：

```bash
# 找到 busybox 的 rootfs 目录（在 tmp/work 下）
# 将 hello 拷贝到 rootfs/bin/
# 然后重新生成 ext4.img
```

### 方式二：修改 busybox 配方集成（推荐）

在 `busybox_0.1.bb` 的 `do_create_ext4img` 函数中，添加拷贝逻辑：

```bash
# 在创建 ext4.img 之前，拷贝额外的应用程序
if [ -f "${TOPDIR}/${MACHINE}/hello" ]; then
    cp ${TOPDIR}/${MACHINE}/hello rootfs/bin/
fi
```

这样每次编译文件系统时，都会自动将 hello 程序包含进去。

## 5.7 在 RT-Smart 中运行

启动 QEMU 后，在 RT-Smart Shell 中执行：

```
msh /> hello
Hello from RT-Smart!
This is a user-space application.

msh /> hello world test
Hello from RT-Smart!
This is a user-space application.
Arguments:
  [1] world
  [2] test
```

## 5.8 进阶：使用 RT-Thread SDK 头文件

如果你的程序需要使用 RT-Thread 特有的 API（如设备操作、线程管理等），可以使用 SDK 中提供的头文件和库：

```c
#include <rtthread.h>
#include <dfs_posix.h>
```

编译时需要添加包含路径和链接库：

```bash
SDK_DIR="${FILE_DIRNAME}/../../recipes-core/busybox/sdk"
RT_DIR="${SDK_DIR}/rt-thread"

${CC} hello.c -o hello \
    -I${RT_DIR}/include \
    -I${RT_DIR}/components/dfs/dfs_v2/include \
    -L${RT_DIR}/lib/${ARCH}/cortex-a \
    -Wl,--start-group -Wl,-whole-archive -lrtthread \
    -Wl,-no-whole-archive -Wl,--end-group
```

> **说明**：SDK 的头文件和库位于 `meta-smart/recipes-core/busybox/sdk/` 目录中，涵盖了 RT-Thread 的核心组件。

## 5.9 目录结构总结

完成后的目录结构：

```
meta-smart/
└── recipes-apps/
    └── hello/
        ├── hello_0.1.bb        # BitBake 配方文件
        └── files/
            └── hello.c         # 源代码
```

## 5.10 常见问题

### Q: 编译报错 "command not found: xxx-linux-musleabi-gcc"

确保工具链已安装。先执行 `bitbake smart-gcc -c install_toolchain`，然后重试。

### Q: 程序在 RT-Smart 中无法运行

确认编译时使用了正确的工具链前缀和静态链接选项。RT-Smart 用户态程序需要使用 `<arch>-linux-musleabi-gcc` 编译。

### Q: 如何调试程序？

可以使用 `printf` 输出调试信息到串口。对于更复杂的调试需求，可以使用 GDB 远程调试（需要在 QEMU 启动时添加 `-s -S` 参数）。
