DESCRIPTION = "RT-Smart User Applications"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://LICENSE;md5=de10de48642ab74318e893a61105afbb"

APP_NAME = "busybox-1.35.0"
APP_MD5SUM = "585949b1dd4292b604b7d199866e9913"
SRC_URI = "https://www.busybox.net/downloads/${APP_NAME}.tar.bz2;md5sum=${APP_MD5SUM}"

BP = "busybox-1.35.0"

DEPENDS = "smart-gcc"

python do_fetch() {
    bb.plain("##############################")
    uri = d.getVar('SRC_URI').split()
    fetcher = bb.fetch2.Fetch(uri, d)
    bb.plain("****** Begin downloading busybox...")
    fetcher.download()
    bb.plain("****** Begin unpacking...")
    fetcher.unpack(d.getVar('WORKDIR'))
    bb.plain("****** Finish downloaded busybox.")
    ##bb.build.exec_func('do_build_busybox', d)   
}

do_compile() {
    bbplain "##############################"
    #bbplain "${PATH}"
    #bbplain "${FILE_DIRNAME}"
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
        if [ ! -d "${TOPDIR}/${MACHINE}" ]; then
            mkdir ${TOPDIR}/${MACHINE}
        fi
        if [ -d "${TOPDIR}/${MACHINE}/install" ]; then
            rm -rf ${TOPDIR}/${MACHINE}/install
        fi
        cp -ra install ${TOPDIR}/${MACHINE}
        cp ${FILE_DIRNAME}/tools/creat_rootfs.sh ${TOPDIR}/${MACHINE}
        cp ${FILE_DIRNAME}/conf/inittab ${TOPDIR}/${MACHINE}
        bbplain "****** Build busybox done! You can go to ${TOPDIR}/${MACHINE} generate ext4.img with: bash creat_rootfs.sh"
    else
        bbfatal "Error: ${SRC} not found!"
    fi
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
do_install() {
  :
}
do_build() {
  :
}

