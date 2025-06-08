inherit region-source

DESCRIPTION = "RT-Thread Smart Kernel"
LICENSE = "CLOSED"

SRC_URI_GITEE = "git://gitee.com/rtthread/rt-thread.git;branch=master;protocol=https;name=rtthread \
                 git://gitee.com/RT-Thread-Mirror/lwext4.git;branch=master;protocol=https;name=lwext4;subdir=lwext4 \
"

SRC_URI_GITHUB = "git://github.com/RT-Thread/rt-thread.git;branch=master;protocol=https;name=rtthread \
                  git://github.com/RT-Thread-packages/lwext4.git;branch=master;protocol=https;name=lwext4;subdir=lwext4 \
"

python () {
    import os
    
    # 检查是否存在本地 rt-thread 目录
    local_rtt = os.path.join(d.getVar('SMARTROOT', True), 'rt-thread')
    if os.path.exists(local_rtt):
        # 如果存在本地目录，清空 SRC_URI
        d.setVar('SRC_URI', '')
        # 设置 S 为本地目录
        d.setVar('S', local_rtt)
        bb.plain("Using local rt-thread directory: %s" % local_rtt)
    else:
        # 如果不存在本地目录，使用远程仓库
        set_preferred_source(d)
        bb.plain("Local rt-thread not found, using remote repository")
}

SRCREV_rtthread = "AUTOINC"
SRCREV_lwext4 = "AUTOINC"

SRCREV_FORMAT = "rtthread_lwext4"

S ?= "${WORKDIR}/git"

# 使用 LAYERDIR 来定位 meta-smart 层的位置
LAYERDIR_smart = "${@os.path.dirname(os.path.dirname(os.path.dirname(d.getVar('FILE', True))))}"
# 通过 LAYERDIR 向上一级找到项目根目录
SMARTROOT = "${@os.path.dirname(d.getVar('LAYERDIR_smart', True))}"

# only build rt-smart kernel
do_build_kernel() {
    bbplain "##############################"
    export RTT_CC="gcc"
    if [ ${MACHINE} = "qemuarm64" ]; then
        export RTT_CC_PREFIX="aarch64-linux-musleabi-"
        export SCONS_BUILD_DIR="${S}/bsp/qemu-virt64-aarch64"
    else
        export RTT_CC_PREFIX="riscv64-linux-musleabi-"
        export SCONS_BUILD_DIR="${S}/bsp/qemu-virt64-riscv"
    fi
    
    # 检查是否存在本地 rt-thread 目录
    if [ -d "${SMARTROOT}/rt-thread" ]; then
        bbplain "****** Using local rt-thread directory"
    else
        bbplain "****** Using downloaded rt-thread source"

        if [ -d ${SCONS_BUILD_DIR}/packages ]; then
            rm -rf ${SCONS_BUILD_DIR}/packages/lwext4*
        else
            mkdir -p ${SCONS_BUILD_DIR}/packages
        fi
        cp -r ${WORKDIR}/sources-unpack/lwext4 ${SCONS_BUILD_DIR}/packages/lwext4-latest
        cp ${FILE_DIRNAME}/lwext4_SConscript ${SCONS_BUILD_DIR}/packages/SConscript

        bbplain "****** Copy default config for ${MACHINE}"
        cp ${FILE_DIRNAME}/${MACHINE}_defconfig ${SCONS_BUILD_DIR}/.config
        scons --pyconfig-silent -C ${SCONS_BUILD_DIR}
    fi

    bbplain "****** Build rt-smart kernel"
    scons -C ${SCONS_BUILD_DIR}
    bbplain "****** Install rt-smart kernel to: ${TOPDIR}/${MACHINE}"
    if [ ! -d "${TOPDIR}/${MACHINE}" ]; then
        mkdir ${TOPDIR}/${MACHINE}
    fi
    cp ${SCONS_BUILD_DIR}/rtthread.bin ${TOPDIR}/${MACHINE}
    
    # copy the run_qemu script
    bbplain "****** Copy QEMU script for ${MACHINE}"
    bbplain "****** Looking in: ${SMARTROOT}/tools/run_${MACHINE}.sh"
    if [ -f "${SMARTROOT}/tools/run_${MACHINE}.sh" ]; then
        cp "${SMARTROOT}/tools/run_${MACHINE}.sh" "${TOPDIR}/${MACHINE}/"
        chmod +x "${TOPDIR}/${MACHINE}/run_${MACHINE}.sh"
        bbplain "****** Successfully copied QEMU script"
    else
        bbwarn "QEMU script not found at ${SMARTROOT}/tools/run_${MACHINE}.sh"
        bbwarn "Current directory structure:"
        ls -la "${SMARTROOT}/tools/" || true
    fi
}
do_build_kernel[depends] = "smart-gcc:do_install_toolchain env:do_install_env"

# build kernel and rootfs 
do_build_all() {
    do_build_kernel
    bbplain "****** All build down! You can enter ${TOPDIR}/${MACHINE} to run qemu."
}
do_build_all[depends] = "busybox:do_build_rootfs"

do_clean[depends] = "smart-gcc:do_clean"
do_clean[depends] += "busybox:do_clean"
do_clean[depends] += "env:do_clean"

do_cleansstate[depends] = "smart-gcc:do_cleansstate"
do_cleansstate[depends] += "busybox:do_cleansstate"
do_cleansstate[depends] += "env:do_cleansstate"

do_cleanall[depends] = "smart-gcc:do_cleanall"
do_cleanall[depends] += "busybox:do_cleanall"
do_cleanall[depends] += "env:do_cleanall"

addtask do_build_kernel after do_unpack
addtask do_build_all after do_unpack
