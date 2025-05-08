DESCRIPTION = "RT-Smart musl toolchain"
LICENSE = "GPL-3.0-with-GCC-exception & GPL-3.0-only"

#关闭校验
BB_STRICT_CHECKSUM = "0"

#默认工具链定义
TOOLCHAIN_PATH_aarch64 = "${TOPDIR}/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu"
TOOLCHAIN_PATH_riscv64 = "${TOPDIR}/toolchains/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu"

#设置默认工具链
DEF_TOOLCHAIN = "${@bb.utils.contains('MACHINE', 'qemuarm64', d.getVar('TOOLCHAIN_PATH_aarch64'), d.getVar('TOOLCHAIN_PATH_riscv64'), d)}"
DEF_TOOLCHAIN_pn-${PN} = "${DEF_TOOLCHAIN}"

python do_fetch() {
    toolchain_url = {
        "qemuarm64": "https://download.rt-thread.org/download/rt-smart/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2",
        "qemuriscv64": "https://download.rt-thread.org/download/rt-smart/toolchains/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2"
    }

    machine = d.getVar('MACHINE')  #qemuarm64
    tc_url = toolchain_url[machine] #https://download...
    def_tc = d.getVar('DEF_TOOLCHAIN')  #build/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu

    if os.path.exists(d.getVar('DEF_TOOLCHAIN')):
         bb.plain("##############################")
         bb.plain("****** Find default toolchain:")
         bb.plain(def_tc)
         bb.plain("****** Need do nothing!")

    else:
         bb.plain("##############################")
         bb.plain("****** Not find default toolchain, download and unpacked to:")
         #bb.plain(tc_url)
         uri = tc_url.split()
         fetcher = bb.fetch2.Fetch(uri, d)
         bb.plain("****** Begin downloading...")
         fetcher.download()
         bb.plain("****** Begin unpacking...")
         tpath = d.getVar('TOPDIR') + "/toolchains"
         #检查build/toolchains目录是否存在
         if not os.path.exists(tpath):
             os.makedirs(tpath)
         fetcher.unpack(tpath)
         bb.plain("****** Install smart-gcc toolchain done.")
}

do_unpack() {
  :
}
do_patch() {
  :
}
do_configure() {
  :
}
do_compile() {
  :
}
do_install() {
  :
}
do_build() {
  :
}

