DESCRIPTION = "RT-Smart User Applications"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=b97a012949927931feb7793eee5ed924"

APP_NAME = "busybox-1.35.0"
APP_MD5SUM = "585949b1dd4292b604b7d199866e9913"
SRC_URI = "https://www.busybox.net/downloads/${APP_NAME}.tar.bz2;md5sum=${APP_MD5SUM}"

# 禁用默认任务
#do_patch[noexec] = "1"

python do_fetch() {
     bb.plain("##############################")
     uri = d.getVar('SRC_URI').split()
     fetcher = bb.fetch2.Fetch(uri, d)
     bb.plain("****** Begin downloading busybox...")
     fetcher.download()
     bb.plain("****** Begin unpacking...")
     fetcher.unpack(d.getVar('WORKDIR'))
     bb.plain("****** Finish downloaded busybox.")
}

do_build_busybox() {
    bbplain "##############################"
    #bbplain "${PATH}"
    bbplain "${FILE_DIRNAME}"
    SRC=${WORKDIR}/${APP_NAME}
    bbplain "****** Begin to build busybox..."
    bbplain "****** Checking source directory: ${SRC}"
    if [ -d "${SRC}" ]; then
        cd "${SRC}"
       #bbplain "${PATH}"
       bbplain "****** Do patch"
       TagFile=".patched"
       if [ -f ${TagFile} ]; then
           bbplain "  *** have been patched, need do nothing!"
       else
           touch ${TagFile}
           patch -Np1 -i ${FILE_DIRNAME}/patches/01_*.diff
           patch -Np1 -i ${FILE_DIRNAME}/patches/02_*.diff
       fi

       bbplain "****** Copy default config"
       cp ${FILE_DIRNAME}/conf/def_config ${SRC}/.config

       bbplain "****** Compile busybox"
       export FILE_DIRNAME="${FILE_DIRNAME}"
       make V=1
       bbplain "****** install busybox"
       make install
       #bbplain "****** Create rootfs img"
       #bash ${FILE_DIRNAME}/tools/creat_rootfs.sh
       cp ${FILE_DIRNAME}/tools/creat_rootfs.sh .
       cp ${FILE_DIRNAME}/conf/inittab .
       bbplain "****** Build busybox done! You can go to ${SRC} generate ext4.img with creat_rootfs.sh"
    else
        bbfatal "Error: ${SRC} not found!"
    fi
}


# 自定义的task需要通过addtask添加到任务队列
addtask do_build_busybox after do_fetch
