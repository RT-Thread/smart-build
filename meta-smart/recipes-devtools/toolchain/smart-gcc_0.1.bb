inherit machine

DESCRIPTION = "RT-Smart musl toolchain"
LICENSE = "GPL-3.0-with-GCC-exception & GPL-3.0-only"

#关闭校验
BB_STRICT_CHECKSUM = "0"

python do_install_toolchain() {
    import os
    import shutil

    tc_url = toolchain_for_machine(d)
    local_tc_path = os.path.expanduser("~/.env/tools/scripts/packages/" + d.getVar("LOCAL_TC"))
    def_toolchain_path = d.getVar('TOPDIR') + "/toolchains/" + d.getVar("TARGET_TC")

    # 首先检查目标目录是否已存在
    if os.path.exists(def_toolchain_path):
        bb.plain("##############################")
        bb.plain("****** Find default toolchain:")
        bb.plain(def_toolchain_path)
        bb.plain("****** Need do nothing!")
        return

    # 检查本地工具链是否存在
    if os.path.exists(local_tc_path):
        bb.plain("##############################")
        bb.plain("****** Find local toolchain:")
        bb.plain(local_tc_path)
        
        # 确保toolchains目录存在
        tpath = d.getVar('TOPDIR') + "/toolchains"
        if not os.path.exists(tpath):
            os.makedirs(tpath)
        
        # 创建符号链接
        bb.plain("****** Creating symbolic link to local toolchain")
        if os.path.islink(def_toolchain_path):
            os.unlink(def_toolchain_path)
        os.symlink(local_tc_path, def_toolchain_path)
        bb.plain("****** Symbolic link created successfully")
    else:
        # 如果本地工具链不存在，则下载
        bb.plain("##############################")
        tpath = d.getVar('TOPDIR') + "/toolchains"
        bb.plain("****** Not find local or default toolchain, download and unpacked to: " + tpath)
        uri = tc_url.split()
        fetcher = bb.fetch2.Fetch(uri, d)
        bb.plain("****** Begin downloading...")
        fetcher.download()
        bb.plain("****** Begin unpacking...")
        if not os.path.exists(tpath):
            os.makedirs(tpath)
        fetcher.unpack(tpath)
        bb.plain("****** Install smart-gcc toolchain done.")
}

addtask do_install_toolchain
