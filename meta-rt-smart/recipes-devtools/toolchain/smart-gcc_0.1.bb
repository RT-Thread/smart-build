DESCRIPTION = "RT-Smart musl toolchain"
LICENSE = "GPL-3.0-with-GCC-exception & GPL-3.0-only"

#关闭校验
BB_STRICT_CHECKSUM = "0"

python do_install_toolchain() {
    toolchain_url = {
        "qemuarm64": "https://download.rt-thread.org/download/rt-smart/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2",
        "qemuriscv64": "https://download.rt-thread.org/download/rt-smart/toolchains/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2"
    }

    machine = d.getVar('MACHINE')  #qemuarm64
    tc_url = toolchain_url[machine] #https://download...

    if machine == "qemuarm64":
        def_toolchain_path = d.getVar('TOPDIR')+"/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu"
    else:
        def_toolchain_path = d.getVar('TOPDIR')+"/toolchains/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu"

    if os.path.exists(def_toolchain_path):
         bb.plain("##############################")
         bb.plain("****** Find default toolchain:")
         bb.plain(def_toolchain_path)
         bb.plain("****** Need do nothing!")
    else:
         bb.plain("##############################")
         tpath = d.getVar('TOPDIR') + "/toolchains"
         bb.plain("****** Not find default toolchain, download and unpacked to: " + tpath)
         uri = tc_url.split()
         fetcher = bb.fetch2.Fetch(uri, d)
         bb.plain("****** Begin downloading...")
         fetcher.download()
         bb.plain("****** Begin unpacking...")
         #检查build/toolchains目录是否存在
         if not os.path.exists(tpath):
             os.makedirs(tpath)
         fetcher.unpack(tpath)
         bb.plain("****** Install smart-gcc toolchain done.")
}

addtask do_install_toolchain
