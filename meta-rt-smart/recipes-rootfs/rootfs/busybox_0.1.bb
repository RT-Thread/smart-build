DESCRIPTION = "RT-Smart User Applications"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://LICENSE;md5=de10de48642ab74318e893a61105afbb"

APP_NAME = "busybox-1.35.0"
APP_MD5SUM = "585949b1dd4292b604b7d199866e9913"
SRC_URI = "https://www.busybox.net/downloads/${APP_NAME}.tar.bz2;md5sum=${APP_MD5SUM}"

BP = "busybox-1.35.0"


python do_build_rootfs() {
    bb.plain("##############################")
    uri = d.getVar('SRC_URI').split()
    fetcher = bb.fetch2.Fetch(uri, d)
    bb.plain("****** Begin downloading busybox...")
    fetcher.download()
    bb.plain("****** Begin unpacking busybox...")
    fetcher.unpack(d.getVar('WORKDIR'))
    bb.plain("****** Finished downloading busybox.")
    bb.build.exec_func('do_compile', d)   
}
do_build_rootfs[depends] = "smart-gcc:do_install_toolchain"

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
        bbplain "****** Do patch for busybox"
        TagFile=".patched"
        if [ -f ${TagFile} ]; then
            bbplain "  *** have been patched, need do nothing!"
        else
            touch ${TagFile}
            patch -Np1 -i ${FILE_DIRNAME}/patches/01_${MACHINE}.diff
            patch -Np1 -i ${FILE_DIRNAME}/patches/02_*.diff
        fi

        bbplain "****** Copy default config for busybox"
        cp ${FILE_DIRNAME}/conf/def_config ${SRC}/.config

        bbplain "****** Compile busybox"
        export FILE_DIRNAME="${FILE_DIRNAME}"
        make V=1
        bbplain "****** Install busybox"
        make install
        bbplain "****** Create rootfs img"
        if [ ! -d "${TOPDIR}/${MACHINE}" ]; then
            mkdir ${TOPDIR}/${MACHINE}
        fi
        cp ${FILE_DIRNAME}/conf/inittab ${SRC}
        do_create_ext4img
        bbplain "****** Install ext4.img to: ${TOPDIR}/${MACHINE}"
    else
        bbfatal "Error: ${SRC} not found!"
    fi
}

do_create_ext4img() {
    cd ${WORKDIR}/${APP_NAME}

    bbplain "   *** Create rootfs dir"
    if [ -d rootfs ]; then
        rm -rf rootfs
    fi
    mkdir rootfs
    cp -ra install/* rootfs
    cd rootfs
    mkdir -p dev/shm etc lib mnt proc root run services tmp var
    cp ../inittab etc/
    cd var
    ln -s ../run run
    cd ../..

    bbplain "   *** Create ext4.img"
    rm -rf ext4.img
    dd if=/dev/zero of=ext4.img bs=1M count=256
    mke2fs -t ext4 -d rootfs ext4.img
    cp ext4.img ${TOPDIR}/${MACHINE}
}

addtask do_build_rootfs
