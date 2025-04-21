DESCRIPTION = "RT-Smart musl toolchain"
LICENSE = "MIT"

# 在配方开头添加以下内容，禁用默认任务链
# 禁止继承默认的构建类（如base.bbclass)
#BBCLASSEXTEND = ""
# 声明使用外部源码路径，避免触发自动解压/编译
#INHERIT += "externalsrc"

#默认工具链定义
TOOLCHAIN_PATH_aarch64 = "/opt/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu"
TOOLCHAIN_PATH_riscv64 = "/opt/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu"

#设置默认工具链
DEF_TOOLCHAIN = "${@bb.utils.contains('MACHINE', 'qemuarm64', d.getVar('TOOLCHAIN_PATH_aarch64'), d.getVar('TOOLCHAIN_PATH_riscv64'), d)}"
DEF_TOOLCHAIN_pn-${PN} = "${DEF_TOOLCHAIN}"

python do_fetch() {
    #import shutil
    toolchain_url = {
        "qemuarm64": "https://download.rt-thread.org/download/rt-smart/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2;md5sum=d5b27f50c20d8b2324db6614c874f3df",
        "qemuriscv64": "https://download.rt-thread.org/download/rt-smart/toolchains/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2;md5sum=c94a74bbe33dcb77d826ddf910b025cc"
    }
    machine = d.getVar('MACHINE')  #qemuarm64
    tc_url = toolchain_url[machine] #https://download...
    def_tc = d.getVar('DEF_TOOLCHAIN')  #/opt/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu

    if os.path.exists(d.getVar('DEF_TOOLCHAIN')):
         bb.plain("##############################")
         bb.plain("Find default toolchain:")
         bb.plain(def_tc)
         bb.plain("Need do nothing!")
         bb.plain("##############################")

    else:
         bb.plain("##############################")
         bb.plain("Not find default toolchain, download and unpacked to:")
         bb.plain(d.getVar('WORKDIR'))
         #bb.plain(tc_url)
         uri = tc_url.split()
         fetcher = bb.fetch2.Fetch(uri, d)
         bb.plain("Begin downloading...")
         fetcher.download()
         bb.plain("Begin unpacking...")
         fetcher.unpack(d.getVar('WORKDIR'))
         bb.plain("Build smart-gcc done.")
         bb.plain("##############################")
}

