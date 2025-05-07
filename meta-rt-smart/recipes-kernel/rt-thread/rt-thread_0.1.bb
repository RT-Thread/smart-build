DESCRIPTION = "RT-Thread Smart Kernel"
LICENSE="CLOSED"

#PROVIDES += "virtual/kernel"
#inherit kernel

#SRC_URI = "${@'https://github.com/RT-Thread/rt-thread/archive/refs/tags/v5.2.0.zip' \
#		if d.getVar('RT_SRC_TYPE') == 'release' \
#		else 'git://github.com/RT-Thread/rt-thread.git;protocol=https;branch=master'}"

# 可选：添加提交哈希或标签
#SRCREV = "${@'v5.2.0' if (d.getVar('RT_SRC_TYPE') or '') == 'release' else 'AUTOINC'}"
# ZIP包的版本标签
#SRCREV:release = "v5.2.0"
# 指定Git仓库的哈希，AUTOINC表示最新提交
#SRCREV:dev = "${AUTOINC}"

SRC_URI = "git://gitee.com/rtthread/rt-thread.git;branch=master;protocol=https"
#SRCREV = "${AUTOINC}"
SRCREV = "AUTOINC"
S = "${WORKDIR}/git"

#DEPENDS = "smart-gcc"
#DEPENDS = "ncurses"

export SCONS_BUILD_DIR = "${S}/bsp/${@'qemu-virt64-aarch64' if d.getVar('MACHINE') == 'qemuarm64' else 'qemu-virt64-riscv'}"

do_build_kernel() {
    bbplain "****** Build rt-smart kernel"
    #bbplain "${SCONS_BUILD_DIR}"
    export RTT_CC="gcc"
    export RTT_CC_PREFIX="aarch64-linux-musleabi-"
    scons --pyconfig-silent -C ${SCONS_BUILD_DIR}
    scons -C ${SCONS_BUILD_DIR}
}


addtask do_build_kernel after do_unpack
