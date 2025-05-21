DESCRIPTION = "RT-Thread Smart Kernel"
LICENSE = "CLOSED"

SRC_URI = "git://gitee.com/rtthread/rt-thread.git;branch=master;protocol=https;name=rtthread \
           git://gitee.com/RT-Thread-Mirror/env.git;branch=master;protocol=https;name=env;subdir=env \
           git://gitee.com/RT-Thread-Mirror/packages.git;branch=master;protocol=https;name=packages;subdir=packages \
           git://gitee.com/RT-Thread-Mirror/sdk.git;branch=main;protocol=https;name=sdk;subdir=sdk \
           git://gitee.com/RT-Thread-Mirror/lwext4.git;branch=master;protocol=https;name=lwext4;subdir=lwext4 \
"
#SRCREV = "${AUTOINC}"
#SRCREV = "AUTOINC"
SRCREV_rtthread = "AUTOINC"
SRCREV_env = "AUTOINC"
SRCREV_packages = "AUTOINC"
SRCREV_sdk = "AUTOINC"
SRCREV_lwext4 = "AUTOINC"

SRCREV_FORMAT = "rtthread_env_packages_sdk_lwext4"

S = "${WORKDIR}/git"

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
    bbplain "****** Create ~/.env and copy lwext4 package"

    mkdir -p ~/.env/local_pkgs ~/.env/packages ~/.env/tools

    cp -r ${WORKDIR}/sources-unpack/env ~/.env/tools/scripts
    cp ${WORKDIR}/sources-unpack/env/env.sh ~/.env/
    cp ${WORKDIR}/sources-unpack/env/Kconfig ~/.env/tools/
    cp -r ${WORKDIR}/sources-unpack/packages ~/.env/packages/
    cp -r ${WORKDIR}/sources-unpack/sdk ~/.env/packages/
    echo "source \"\$PKGS_DIR/packages/Kconfig\"" > ~/.env/packages/Kconfig
    if [ -d ${SCONS_BUILD_DIR}/packages ]; then
        rm -rf ${SCONS_BUILD_DIR}/packages/lwext4*
    else
        mkdir -p ${SCONS_BUILD_DIR}/packages
    fi
    cp -r ${WORKDIR}/sources-unpack/lwext4 ${SCONS_BUILD_DIR}/packages/lwext4-latest
    cp ${FILE_DIRNAME}/lwext4_SConscript ${SCONS_BUILD_DIR}/packages/SConscript
    #cd ${SCONS_BUILD_DIR}
    #pkgs --update
    bbplain "****** Copy default config for ${MACHINE}"
    cp ${FILE_DIRNAME}/${MACHINE}_defconfig ${SCONS_BUILD_DIR}/.config
    bbplain "****** Build rt-smart kernel"
    scons --pyconfig-silent -C ${SCONS_BUILD_DIR}
    scons -C ${SCONS_BUILD_DIR}
    bbplain "****** Install rt-smart kernel to: ${TOPDIR}/${MACHINE}"
    if [ ! -d "${TOPDIR}/${MACHINE}" ]; then
        mkdir ${TOPDIR}/${MACHINE}
    fi
    cp ${SCONS_BUILD_DIR}/rtthread.bin ${TOPDIR}/${MACHINE}
    if [ -f ${TOPDIR}/../../tools/run_${MACHINE}.sh ]; then
        cp ${TOPDIR}/../../tools/run_${MACHINE}.sh ${TOPDIR}/${MACHINE}
    fi
}
do_build_kernel[depends] = "smart-gcc:do_install_toolchain"


# build kernel and rootfs 
do_build_all() {
    do_build_kernel
    bbplain "****** All build down! You can enter ${TOPDIR}/${MACHINE} to run qemu."
}
do_build_all[depends] = "busybox:do_build_rootfs"


do_clean[depends] = "smart-gcc:do_clean"
do_clean[depends] += "busybox:do_clean"

do_cleansstate[depends] = "smart-gcc:do_cleansstate"
do_cleansstate[depends] += "busybox:do_cleansstate"
    
do_cleanall[depends] = "smart-gcc:do_cleanall"
do_cleanall[depends] += "busybox:do_cleanall"

addtask do_build_kernel after do_unpack
addtask do_build_all after do_unpack
