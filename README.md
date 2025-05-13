# smart-build
build kernel/rootfs/bootloader for rt-smart

This README file contains information on the contents of the meta-rt-smart layer.

meta-rt-smart 依赖 openembedded poky，作为poly的一个layer存在。

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

### 3. 进入smart-build目录，然后下载poky：
```bash
$ cd smart-build/
$ git clone git://git.yoctoproject.org/poky
```

### 4. 切换到最新的styhead分支：
```bash
$ cd poky
$ git branch -a
$ git checkout -t origin/styhead -b my-styhead
$ git pull
```

### 5. 设置bitbake编译环境：
```bash
$ source oe-init-build-env  #会自动进入build目录
```
然后修改conf/local.conf:
```bash
MACHINE ??= "qemuarm64"
```

### 6. 将meta-rt-smart添加到poky下
```bash
$ cd poky
$ bitbake-layers add-layer ../meta-rt-smart  #将meta-rt-smart添加到layers
$ bitbake-layers show-layers  #查看添加的layers
```

### 7. 编译 smart-build 整个工程：
```bash
$ cd poky
$ source oe-init-build-env  #会自动进入build目录
$ bitbake rt-smart  #"rt-samrt"是配方名称
```

注意：首次编译可能需要一些时间用于安装所指定架构的基础软件包。  
所以，建议首次先执行一遍：bitbake core-image-minimal 编译一个最小镜像构建缓存数据包。

依赖关系说明：rt-smart依赖busybox，busybox依赖smart-gcc

所以会依次下载smart-gcc，并解压到build/toolchain目录下；  
然后编译busybox，将生成的ext4.img拷贝到build/$MACHINE目录下（如build/qemuarm64）；  
最后编译rt-smart kernel，并将生成的rtthread.bin拷贝到build/$MACHINE目录下。

如果需要重新编译，可以执行：
```bash
$ ../../tools/clean_rt_smart.sh
```

制作ext4.img及运行qemu（以qemuarm64为例）：
```bash
$ cd build/qemuarm64
$ ./run_qemuarm64.sh
```

### 8. 单独安装 smart-gcc 工具链：
```bash
$ cd poky/build
$ bitbake smart-gcc -c cleansstate  #清除之前的编译状态
$ rm -rf build/toolchains  #删除之前安装的toolchain
$ bitbake smart-gcc  #"smart-gcc"是配方的名称
```
该配方会先判断 build/toolchains 目录下是否存在系统默认的工具链，如果有的话不做任何操作；  
如果没有，会从指定的链接下载工具链压缩包，然后解压到 build/toolchains 目录。

### 9. 单独编译 busybox 生成ext4.img文件系统：
```bash
$ cd poky/build
$ bitbake busybox -c cleansstate  #清除之前的编译状态
$ bitbake busybox
```
该配方会从指定地址下载busybox，然后解压、打patch、编译、以及生成ext4.img。
最后将生成的ext4.img拷贝到build/$MACHINE目录下；  

### 10. 单独编译 rt-samrt kernel：
```bash
$ cd poky/build
$ bitbake rt-smart -c cleansstate  #清除之前的编译状态
$ bitbake rt-smart
```
该配方会从指定地址下载rt-thread，然后进行编译。  
生成的kernel地址如：tmp/work/cortexa57-poky-linux/rt-smart/0.1/git/bsp/qemu-virt64-aarch64；  
编译完成后会将生成的rtthread.bin拷贝到build/$MACHINE目录下；  
说明：由于bitbake不支持终端交互，所以暂无法通过bitbake方式直接进行menuconfig配置。  
可以去源码目录（如 tmp/work/cortexa57-poky-linux/rt-smart/0.1/git/bsp/qemu-virt64-aarch64 ）执行"scons --menuconfig"进行配置。

### 11. 其它注意事项：
在 Docker 容器内执行 mount 命令时出现 Operation not permitted 错误，通常是因为容器默认以非特权模式运行，缺少挂载文件系统所需的权限。  
可以在启动容器时添加 --privileged 参数，赋予容器完整的宿主内核权限。然后就能mount操作了。

