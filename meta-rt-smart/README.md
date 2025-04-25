This README file contains information on the contents of the meta-rt-smart layer.

meta-rt-smart 依赖 openembedded poky，作为poly的一个layer存在。

以下是基于Ubuntu22.04的编译流程：
### 1. Host环境准备：
```bash
$ sudo apt install build-essential chrpath cpio debianutils diffstat file gawk gcc git iputils-ping libacl1 liblz4-tool locales python3 python3-git python3-jinja2 python3-pexpect python3-pip python3-subunit socat texinfo unzip wget xz-utils zstd
```

### 2. 下载poky：
```bash
$ git clone git://git.yoctoproject.org/poky
```

### 3. 切换到最新的styhead分支：
```bash
$ cd poky
$ git branch -a
$ git checkout -t origin/styhead -b my-styhead
$ git pull
```

### 4. 安装 xmake 和 scons 编译工具：
```bash
$ sudo add-apt-repository ppa:xmake-io/xmake
$ sudo apt update
$ sudo apt install xmake
$ sudo apt-get install scons
```

### 5. 设置编译环境：
```bash
$ source oe-init-build-env  #会自动进入build目录
```
然后修改conf/local.conf:
```bash
MACHINE ??= "qemuarm64"
PATH := "${PATH}:/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin"
```
由于bitbake使用自己独立的环境变量，所以需要将系统的一些环境变量加进来。

### 6. 将meta-rt-smart拷贝到poky下，并添加到层
```bash
$ cp -r meta-rt-smart poky
$ cd poky
$ bitbake-layers create-layer meta-rt-smart  #添加到layers
$ bitbake-layers show-layers  #查看添加的layers
```

### 7. 获取smart-gcc工具链：
```bash
$ cd poky/build
$ bitbake smart-gcc -c fetch  #"smart-gcc"是配方的名称， "fetch"是该配方定义的任务。
```
该配方会先判断/opt下是否存在系统默认的工具链，如果有的话不做任何操作；
如果没有，会从指定的链接下载工具链压缩包，然后解压到${WORKDIR}目录备用。

下载的tar包会存放在${DL_DIR}目录，即使执行clean操作也不会删除。
clean操作只会删除解压的目录，所以如果需要重新解压，可以先clean:
```bash
$ bitbake smart-gcc -c clean
```

### 8. 编译userapps生成ext4.img文件系统：
```bash
$ cd poky/build
$ bitbake busybox -c build_busybox  #"busybox"是配方的名称，"build_busybox"是该配方定义的任务。
```
该配方会从指定地址下载busybox，然后解压、打patch、编译。
编译完成后根据提示信息前往busybox源码目录，执行create_rootfs.sh脚本生成ext4.img。

说明：由于sudo权限问题，无法在bitbake执行过程直接进行生成ext4.img。

如果需要重新获取git代码及重新编译，可以先clean:
```bash
$ bitbake busybox -c clean
```

9. 编译kernel：
[[Todo]]




