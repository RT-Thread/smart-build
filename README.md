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

### 11. Docker操作指南：
注意：以下操作均是在Docker内进行，以Ubuntu 22.04 Docker为例。

有关Docker启动的基本操作，这里不再赘述。
进入Docker后默认是root用户，但是Bitbake不允许使用root用户操作，所以需要创建一个普通用户，如：rtt （你可以换成自己喜欢的用户名称）
```bash
# adduser rtt  #设置password如: rt-smart
# aptitude install sudo
# usermod -aG sudo rtt  #将rtt用户添加sudo组
# su rtt  #切换到rtt用户
$ cd ~  #回到rtt的home目录，后面所有操作均在/home/rtt下进行
```

安装依赖环境：
```bash
$ sudo apt update
$ sudo apt install vim gcc make scons git bzip2 net-tools iputils-ping libncurses-dev
$ sudo apt install qemu-system-arm qemu-system-common qemu-utils
$ sudo apt install python3 python3-lib2to3 python3-git python3-jinja2 python3-pexpect python3-pip python3-subunit
$ sudo apt install build-essential chrpath cpio debianutils diffstat file gawk libacl1 liblz4-tool locales socat texinfo unzip wget xz-utils zstd bash-completion
$ pip3 install kconfiglib
```

然后就可以参照前面的第2, 3, 4, 5, 6, 7章节进行操作了。

如果本地Host系统已经有了smart-build和poky的仓库数据，则可以直接拷贝到Docker里面，避免重新git clone下载。
注意：下面拷贝操作在Host系统里面进行。其中$Container_Name是指当前在运行docker的容器名称，可以通过"docker ps -l 查看"，用实际名称替换。
```bash
$ docker cp smart-build $Container_Name:/home/rtt/  
$ docker cp poky $Container_Name:/home/rtt/smart-build/
```
