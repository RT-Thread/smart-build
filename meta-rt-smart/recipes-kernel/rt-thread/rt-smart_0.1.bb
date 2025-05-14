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

DEPENDS = "busybox"

export SCONS_BUILD_DIR = "${S}/bsp/${@'qemu-virt64-aarch64' if d.getVar('MACHINE') == 'qemuarm64' else 'qemu-virt64-riscv'}"

do_compile() {
    bbplain "##############################"
    export RTT_CC="gcc"
    export RTT_CC_PREFIX="aarch64-linux-musleabi-"
    #bbplain $PATH
    bbplain "****** Create ~/.env and copy lwext4 package"
    if [ -d ~/.env ]; then
        rm -rf ~/.env
    fi
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
    bbplain "****** Copy default config"
    cp ${FILE_DIRNAME}/${MACHINE}_defconfig ${SCONS_BUILD_DIR}/.config
    bbplain "****** Build rt-smart kernel"
    scons --pyconfig-silent -C ${SCONS_BUILD_DIR}
    scons -C ${SCONS_BUILD_DIR}
    bbplain "****** Install rt-smart kernel to: ${TOPDIR}/${MACHINE}"
    if [ ! -d "${TOPDIR}/${MACHINE}" ]; then
        mkdir ${TOPDIR}/${MACHINE}
    fi
    cp ${SCONS_BUILD_DIR}/rtthread.bin ${TOPDIR}/${MACHINE}
    cp ${TOPDIR}/../../tools/run*.sh ${TOPDIR}/${MACHINE}
}

do_patch() {
  :
}
do_configure() {
  :
}
do_install() {
  :
}
do_build() {
  :
}

