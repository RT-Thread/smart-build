DESCRIPTION = "RT-Smart User Applications"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=b97a012949927931feb7793eee5ed924"

SRC_URI = "git://github.com/RT-Thread/userapps.git;branch=main;protocol=https"
#指定Git仓库哈希，AUTOINC表示最新提交
SRCREV = "${AUTOREV}"
#SRCREV = "f1611c9f4b15f79ae8a5d58cb672940959a5f72f"
#${WORKDIR}: tmp/work/cortexa57-poky-linux/busybox/0.1
S = "${WORKDIR}/git"

# 禁用默认任务
#do_patch[noexec] = "1"

do_build_userapps() {
    bbplain "==================================="
    #bbplain "${PATH}"
    bbplain "****** Begin to build userapps..."
    bbplain "****** Checking source directory: ${S}"
    if [ -d "${S}" ]; then
        cd "${S}" || bbfatal "Failed to enter ${S}"
        bbplain "****** Set env"
        #source env.sh  ##source command not found 
        #bash env.sh    ##后面xmake执行提示返回错误代码
        export XMAKE_RCFILES="${S}/tools/scripts/xmake.lua"
        export RT_XMAKE_LINK_TYPE="shared"

        cd apps || bbfatal "apps directory missing"
        bbplain "****** Set arch architecture based MACHINE"
        # 根据MACHINE动态选择架构
        if [ "${MACHINE}" = "qemuarm64" ]; then
            target_arch="aarch64"
        else
            target_arch="riscv64"
        fi
        bbplain "****** xmake f -a ${target_arch}"
        xmake f -a "${target_arch}"
        bbplain "****** xmake -j8"
        xmake -j8
        bbplain "****** xmake smart-rootfs"
        xmake smart-rootfs
        bbplain "****** xmake smart-image -o ext4.img"
        xmake smart-image -o ext4.img
        bbplain "****** Build done! ${S}/apps/ext4.img"
        bbplain "==================================="
    else
        bbfatal "Error: ${S} not found!"
    fi
}

# 自定义的task需要通过addtask添加到任务队列
# 理论上，Bitbake会在do_fetch环节获取git代码
# 实际上，在do_fetch的下一环节do_unpack才会下载
addtask do_build_userapps after do_unpack
