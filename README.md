# Smart Build

[![Manual Build Status](https://github.com/RT-Thread/smart-build/actions/workflows/manual-build.yml/badge.svg)](https://github.com/RT-Thread/smart-build/actions/workflows/manual-build.yml)

# smart-build
build kernel/rootfs/bootloader for smart

This README file contains information on the contents of the meta-smart layer.

meta-smart 依赖 openembedded-core，作为openembedded的一个layer存在。

以下是基于Ubuntu22.04的编译流程：

### 1. Host环境准备：
```bash
$ sudo apt install build-essential git curl vim python3 pip tmux bison flex file texinfo chrpath cpio diffstat gawk lz4 wget zstd qemu-system-arm
$ sudo pip install requests scons kconfiglib tqdm
```

### 2. 下载smart-build:
```bash
$ git clone https://github.com/RT-Thread/smart-build.git
```

### 3. 进入smart-build目录，然后下载openembedded-core和bitbake仓库：

```bash
$ cd smart-build/
$ git clone git://git.openembedded.org/openembedded-core oe-core
$ git clone git://git.openembedded.org/bitbake
```

### 4. 设置bitbake编译环境：
```bash
$ source smart-env  #会自动进入build目录
```
或者指定自定义的构建目录名称：
```bash
$ source smart-env build-custom  #会自动进入build-custom目录
```

默认配置为 (参见 `build/conf/local.conf`)：
```bash
MACHINE ??= "qemuarm64"
```

也可以根据需要自行更改成 `qemuriscv64`

### 5. 编译 smart-build 整个工程：

```bash
$ bitbake smart -c build_all  #"smart"是配方名称, build_all表示同时完成toolchain安装、busybox编译及生成ext4.img，以及smart的kernel的编译。
```

所以会依次下载smart-gcc，并解压到build/toolchain目录下；  
然后编译busybox，将生成的ext4.img拷贝到build/$MACHINE目录下（如build/qemuarm64）；  
最后编译smart kernel，并将生成的rtthread.bin拷贝到build/$MACHINE目录下。

如果需要重新编译，可以执行清除处理：

```bash
$ bitbake smart -c clean  #同时清除toolchain，busybox， smart的编译文件
```

然后可以进去到build/$MACHINE目录运行qemu（以qemuarm64为例）：
```bash
$ cd build/qemuarm64
$ ./run_qemuarm64.sh
```
### 6. smart-build常用的操作指令：

1. 安装toolchain:
```bash
$ bitbake smart-gcc -c install_toolchain
```

2. 编译busybox并生成ext4.img (会先判断toolchain是否安装，否则会先安装)
```bash
$ bitbake busybox -c build_rootfs
```

3. 编译smart内核  (会先判断toolchain是否安装，否则会先安装)
```bash
$ bitbake smart -c build_kernel 
```

4. 编译busybox及smart内核
```bash
$ bitbake smart -c build_all
```

5. 同时清除toolchain, busybox, smart的编译数据
```bash
$ bitbake smart -c clean/cleansstate/cleanall
```

参数说明：
  * clean - 清除掉tmp下的编译目录；
  * cleansstate - 清除掉编译状态；
  * cleanall - 同时会清除掉下载的源文件；（慎用，否则又得下半天）

### 7. Docker操作指南：
本项目提供了开箱即用的Docker环境，位于 `tools/docker` 目录下。使用Docker可以避免环境配置问题，推荐使用此方式进行开发。

1. 构建Docker镜像：
```bash
$ cd tools/docker
$ sh ./docker_build.sh
```
这将创建一个名为 `smart-build` 的Docker镜像，基于Ubuntu 24.04，已预装所有必要的开发工具和依赖。

2. 运行Docker容器：
```bash
$ sh ./docker_run.sh
```

该脚本会：
- 以当前用户身份启动容器（避免权限问题）
- 挂载当前用户的工作目录到容器中
- 挂载用户配置文件（.bashrc, .profile等）
- 设置合适的工作目录

进入容器后，您可以按照上述第2步骤开始进行开发。所有在容器内的操作都会直接反映到主机的工作目录中。

注意：
- Docker环境已预配置了中国时区和国内镜像源，可加快开发效率
- 容器是临时性的，退出后会自动删除，但您的工作目录数据会保留在主机上
- 如需自定义Docker环境，可以修改 `tools/docker` 目录下的配置文件
