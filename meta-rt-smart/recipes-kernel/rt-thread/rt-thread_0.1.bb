DESCRIPTION = "RT-Thread Smart Kernel"
LICENSE="MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=b97a012949927931feb7793eee5ed924"

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

SRC_URI = "git://github.com/RT-Thread/rt-thread.git;branch=master;protocol=https"
#SRCREV = "${AUTOINC}"
SRCREV = "AUTOINC"
S = "${WORKDIR}/git"

#DEPENDS = "smart-gcc"
#DEPENDS = "ncurses"

export SCONS_BUILD_DIR = "${S}/bsp/${@'qemu-virt64-aarch64' if d.getVar('MACHINE') == 'qemuarm64' else 'qemu-virt64-riscv'}"

do_menuconfig() {
    bbplain "======= Enter menuconfig"
    bbplain "${SCONS_BUILD_DIR}"
    #bbplain "${TERM}"
    export TERM=xterm
    #export RTT_CC="gcc"
    #export RTT_CC_PREFIX="aarch64-linux-musleabi-"
    #export RTT_EXEC_PATH="/opt/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu/bin"
    #export RTT_EXEC_PATH2="/opt/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu/aarch64-linux-musleabi/bin"
    #export PATH=$PATH:"$RTT_EXEC_PATH":"$RTT_EXEC_PATH2"
    #export PATH="${PATH}:/opt/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu/bin"
    ##bbplain "${PATH}"
    #oe_runall scons -C ${SCONS_BUILD_DIR} --menuconfig
    #scons -C ${SCONS_BUILD_DIR} --menuconfig
    scons -C ${SCONS_BUILD_DIR}
    #script -qefc "scons -C /Data/poky/build/tmp/work/cortexa57-poky-linux/rt-thread/0.1/git/bsp/qemu-virt64-aarch64 --menuconfig" /dev/null
}



do_compile() {
    oe_runall -C ${SCONS_BUILD_DIR} -j ${BB_NUMBER_THREADS}
}

addtask do_menuconfig after do_unpack
