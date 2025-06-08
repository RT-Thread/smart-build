# Smart Build

[![Manual Build Status](https://github.com/RT-Thread/smart-build/actions/workflows/manual-build.yml/badge.svg)](https://github.com/RT-Thread/smart-build/actions/workflows/manual-build.yml)

# smart-build
build kernel/rootfs/bootloader for smart

This README file contains information on the contents of the meta-smart layer.

meta-smart 依赖 openembedded-core，作为openembedded的一个layer存在。

以下是基于Ubuntu22.04的编译流程：
### 1. Host环境准备：
```bash
$ sudo apt install build-essential chrpath cpio debianutils diffstat file gawk gcc git iputils-ping libacl1 liblz4-tool locales python3 python3-git python3-jinja2 python3-pexpect python3-pip python3-subunit socat texinfo unzip wget xz-utils zstd scons
```

### 2. 下载smart-build，切换到openembedded分支:
```bash
$ git clone https://github.com/RT-Thread/smart-build.git
$ git checkout -t origin/openembedded -b openembedded
```

### 3. 进入smart-build目录，然后下载openembedded-core和bitbake：
```bash
$ cd smart-build/
$ git clone git://git.openembedded.org/openembedded-core oe-core
$ git clone git://git.openembedded.org/bitbake
```

### 4. 切换到最新的master分支：
```bash
$ cd oe-core
$ git branch -a
$ git checkout -t origin/master -b my-master
$ git pull
$ cd ..
```

### 5. 设置bitbake编译环境：
```bash
$ source smart-env  #会自动进入build目录
```
或者指定自定义的构建目录名称：
```bash
$ source smart-env custom-build  #会自动进入custom-build目录
```

默认配置为：
```bash
MACHINE ??= "qemuarm64"  #支持 qemuarm64 和 qemuriscv64
```

### 6. 编译 smart-build 整个工程：
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

### 7. 单独安装 smart-gcc 工具链：
```bash
$ cd openembedded-core/build
$ bitbake smart-gcc -c clean  #清除之前的编译
$ rm -rf build/toolchains  #删除之前安装的toolchain
$ bitbake smart-gcc -c install_toolchain  #"smart-gcc"是配方的名称, install_toolchain是自定义的Task。
```
该配方会先判断 build/toolchains 目录下是否存在系统默认的工具链，如果有的话不做任何操作；  
如果没有，会从指定的链接下载工具链压缩包，然后解压到 build/toolchains 目录。

### 8. 单独编译 busybox 生成ext4.img文件系统：
```bash
$ cd openembedded-core/build
$ bitbake busybox -c clean  #清除之前的编译
$ bitbake busybox -c build_rootfs
```
该配方会从指定地址下载busybox，然后解压、打patch、编译、以及生成ext4.img。
最后将生成的ext4.img拷贝到build/$MACHINE目录下；

编译Busybox之前会先判断Toolchain是否就绪，否则的话会先下载安装Toolchain。

### 9. 单独编译 smart kernel：
```bash
$ cd openembedded-core/build
$ bitbake smart -c clean  #清除之前的编译
$ bitbake smart -c build_kernel
```

该配方会从指定地址下载rt-thread，然后进行编译。  
生成的kernel地址如：tmp/work/cortexa57-poky-linux/smart/0.1/git/bsp/qemu-virt64-aarch64；  
编译完成后会将生成的rtthread.bin拷贝到build/$MACHINE目录下；  

编译smart之前会先判断Toolchain是否就绪，否则的话会先下载安装Toolchain。

说明：由于bitbake不支持终端交互，所以暂无法通过bitbake方式直接进行menuconfig配置。  
可以去源码目录（如 tmp/work/cortexa57-poky-linux/smart/0.1/git/bsp/qemu-virt64-aarch64 ）执行"scons --menuconfig"进行配置。
然后将生成的.config文件去替换对应架构的默认配置文件，如recipes-kernel/rt-thread/qemuarm64_defconfig，下次再编译就会使用用户自己的默认配置了。

### 10. smart-build常用的操作指令：
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

### 11. Docker操作指南：
本项目提供了开箱即用的Docker环境，位于 `tools/docker` 目录下。使用Docker可以避免环境配置问题，推荐使用此方式进行开发。

1. 构建Docker镜像：
```bash
$ cd tools/docker
$ ./docker_build.sh
```
这将创建一个名为 `smart-build` 的Docker镜像，基于Ubuntu 24.04，已预装所有必要的开发工具和依赖。

2. 运行Docker容器：
```bash
$ ./docker_run.sh
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
