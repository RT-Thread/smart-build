# 第四章 示例：增加板卡支持

本章以一个虚构的开发板 **"MyBoard"**（基于 aarch64 架构）为例，演示如何为 smart-build 添加新的硬件平台支持。

## 4.1 前置条件

在开始之前，请确保：

1. RT-Thread 源码中已有对应的 BSP 目录（例如 `bsp/myboard`）
2. 已有对应架构的交叉编译工具链（smart-build 已支持 aarch64、riscv64、arm）
3. 了解目标板的基本硬件信息（CPU 型号、内存大小、串口配置等）

## 4.2 整体步骤概览

添加新板卡需要修改以下文件：

| 步骤 | 文件 | 操作 |
| --- | --- | --- |
| 1 | `classes/machine.bbclass` | 注册新机器的架构和 BSP 映射 |
| 2 | `conf/machine/myboard.conf` | 创建机器配置文件（可选） |
| 3 | `conf/layer.conf` | 添加工具链路径（如有新架构） |
| 4 | `recipes-core/busybox/patches/` | 创建 BusyBox 补丁（如有新架构） |
| 5 | `recipes-kernel/rt-thread/` | 添加内核 defconfig 配置 |
| 6 | `tools/` | 创建 QEMU 启动脚本（如适用） |

## 4.3 步骤一：注册机器映射

编辑 `meta-smart/classes/machine.bbclass`，在 `bsps` 字典中添加新板卡：

```python
def handle_machine(d):
    bsps = {
        'qemuarm64': {
            'ARCH': 'aarch64',
            'BSP': 'bsp/qemu-virt64-aarch64'
        },
        # ... 已有的其他板卡 ...

        # ========== 新增 MyBoard ==========
        'myboard': {
            'ARCH': 'aarch64',
            'BSP': 'bsp/myboard'
        },
    }
    # ... 其余代码无需修改 ...
```

**关键字段说明**：

- 字典的 key（`'myboard'`）就是 `MACHINE` 变量的值，也是 `local.conf` 中需要配置的名称
- `ARCH` 必须是 `aarch64`、`riscv64` 或 `arm` 之一（对应已有的工具链）
- `BSP` 是 RT-Thread 源码中 BSP 的相对路径

## 4.4 步骤二：创建机器配置文件（可选）

如果新板卡需要特定的 OpenEmbedded 机器配置（如设备树、镜像类型等），创建 `meta-smart/conf/machine/myboard.conf`：

```conf
#@TYPE: Machine
#@NAME: MyBoard
#@DESCRIPTION: Machine configuration for MyBoard (aarch64)

# 内核配置
KERNEL_DEVICETREE = "myboard.dtb"
KERNEL_IMAGETYPE = "Image"

# 串口配置
SERIAL_CONSOLES = "115200;ttyS0"

# 镜像类型
IMAGE_FSTYPES = "ext4"

# 系统特性
MACHINE_FEATURES = ""
MACHINE_EXTRA_RRECOMMENDS = ""
```

> **说明**：对于 QEMU 虚拟平台，这个文件通常不需要创建。它主要用于真实硬件板卡，配合 OE-Core 的标准镜像生成流程使用。

## 4.5 步骤三：确认工具链路径

如果新板卡使用已有架构（aarch64、riscv64、arm），则工具链路径已经在 `layer.conf` 中配置好，无需修改。

如果需要支持全新架构（例如假设支持 MIPS），则需要：

1. 在 `machine.bbclass` 的 `prefix` 字典中添加工具链前缀映射
2. 在 `machine.bbclass` 的 `toolchain_for_machine` 函数中添加下载地址
3. 在 `layer.conf` 的 `PATH` 中添加新的工具链路径

## 4.6 步骤四：创建 BusyBox 补丁

BusyBox 需要为每种**架构**准备适配补丁。如果新板卡使用已有架构，已有的补丁即可复用（如 `01_aarch64.diff`）。

如果是全新架构或者需要板卡特有的适配，创建对应的补丁文件：

```
meta-smart/recipes-core/busybox/patches/01_<ARCH>.diff
```

可以参照已有的补丁文件格式。补丁主要处理：

- 交叉编译器路径配置
- 架构特定的编译选项
- 头文件和库文件路径

## 4.7 步骤五：添加内核 defconfig

为新板卡创建内核默认配置文件：

```
meta-smart/recipes-kernel/rt-thread/myboard_defconfig
```

可以通过以下方式生成：

1. 进入 RT-Thread 源码的 BSP 目录
2. 使用 `scons --menuconfig` 进行配置
3. 保存生成的 `.config` 文件
4. 将其拷贝为 `myboard_defconfig`

也可以基于已有的 defconfig 文件修改，例如：

```bash
cp meta-smart/recipes-kernel/rt-thread/qemuarm64_defconfig \
   meta-smart/recipes-kernel/rt-thread/myboard_defconfig
```

然后根据目标板的硬件特性调整配置项。

## 4.8 步骤六：创建 QEMU 启动脚本（如适用）

如果新板卡是 QEMU 虚拟平台，在 `tools/` 目录下创建启动脚本 `tools/run_myboard.sh`：

```bash
#!/bin/bash

type=${1}
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -n "${type}" ]; then
    type="ext4"
fi

qemu-system-aarch64 \
    -M virt \
    -cpu cortex-a53 \
    -smp 4 \
    -m 128M \
    -kernel ${script_dir}/rtthread.bin \
    -nographic \
    -drive if=none,file=${script_dir}/${type}.img,format=raw,id=blk0 \
    -device virtio-blk-device,drive=blk0,bus=virtio-mmio-bus.0 \
    -netdev user,id=net0 \
    -device virtio-net-device,netdev=net0,bus=virtio-mmio-bus.1
```

> **提示**：对于真实硬件，不需要 QEMU 启动脚本。烧录方式请参考具体硬件的文档。

## 4.9 验证新板卡

### 配置目标机器

编辑 `build/conf/local.conf`：

```bash
MACHINE ??= "myboard"
```

### 执行编译

```bash
source smart-env
bitbake smart -c build_all
```

### 检查输出

```bash
ls build/myboard/
# 应该包含：rtthread.bin  ext4.img  run_myboard.sh（如果创建了）
```

## 4.10 完整示例参考

以下是 smart-build 中已有板卡的文件清单，可作为参考：

### qemuarm64（QEMU ARM64）

```
meta-smart/
├── classes/machine.bbclass              # 'qemuarm64' → aarch64, bsp/qemu-virt64-aarch64
├── recipes-core/busybox/patches/
│   └── 01_aarch64.diff                  # aarch64 架构补丁
├── recipes-kernel/rt-thread/
│   └── qemuarm64_defconfig              # 内核默认配置
└── ...

tools/
└── run_qemuarm64.sh                     # QEMU 启动脚本
```

### k230（嘉楠 K230，RISC-V）

```
meta-smart/
├── classes/machine.bbclass              # 'k230' → riscv64, bsp/k230
├── conf/machine/k230.conf              # 机器配置（设备树、串口等）
├── recipes-core/busybox/patches/
│   └── 01_riscv64.diff                  # riscv64 架构补丁
└── ...
```

## 4.11 注意事项

1. **MACHINE 名称不能包含下划线**：BitBake 对变量名中的下划线有特殊处理，建议使用连字符（`-`），如 `raspi4-64`
2. **BSP 路径必须与 RT-Thread 源码一致**：`BSP` 字段的值必须是 RT-Thread 仓库中实际存在的目录路径
3. **工具链必须与架构匹配**：`ARCH` 对应的工具链前缀在 `prefix` 字典中查找
4. **defconfig 文件名必须匹配**：文件名格式为 `<MACHINE>_defconfig`，与 `local.conf` 中的 `MACHINE` 值对应
