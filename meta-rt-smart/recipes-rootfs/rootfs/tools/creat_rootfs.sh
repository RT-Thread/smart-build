#!/bin/bash

DIR="rootfs"
if [ -d ${DIR} ]; then
    rm -rf ${DIR}
fi

echo "  *** create rootfs dir"
mkdir ${DIR}
cp -ra install/* ${DIR}
cd ${DIR}
mkdir -p dev/shm etc lib mnt proc root run services tmp var
#cp ${FILE_DIRNAME}/conf/inittab etc
cp ../inittab etc/
cd var
ln -s ../run run
cd ../..

echo "  *** create ext4.img"
sudo rm -rf ext4 ext4.img
mkdir ext4
dd if=/dev/zero of=ext4.img bs=1024 count=262144
mkfs.ext4 ext4.img
sudo mount ext4.img ext4/
sudo cp -fra ./rootfs/* ./ext4
sudo umount ext4/
