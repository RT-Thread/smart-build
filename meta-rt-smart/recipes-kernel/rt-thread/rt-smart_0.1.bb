DESCRIPTION = "RT-Thread Smart Kernel"
LICENSE = "CLOSED"

SRC_URI = "git://gitee.com/rtthread/rt-thread.git;branch=master;protocol=https"
#SRCREV = "${AUTOINC}"
SRCREV = "AUTOINC"
S = "${WORKDIR}/git"

DEPENDS = "busybox"

export SCONS_BUILD_DIR = "${S}/bsp/${@'qemu-virt64-aarch64' if d.getVar('MACHINE') == 'qemuarm64' else 'qemu-virt64-riscv'}"

do_compile() {
    bbplain "##############################"
    bbplain "****** Build rt-smart kernel"
    #bbplain "${SCONS_BUILD_DIR}"
    export RTT_CC="gcc"
    export RTT_CC_PREFIX="aarch64-linux-musleabi-"
    scons --pyconfig-silent -C ${SCONS_BUILD_DIR}
    scons -C ${SCONS_BUILD_DIR}
    bbplain "****** Install rt-smart kernel to: ${TOPDIR}/${MACHINE}"
    if [ ! -d "${TOPDIR}/${MACHINE}" ]; then
        mkdir ${TOPDIR}/${MACHINE}
    fi
    cp ${SCONS_BUILD_DIR}/rtthread.bin ${TOPDIR}/${MACHINE}
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




