#!/bin/bash

type=${1}
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -n "${type}" ]; then
    type="ext4"
fi

qemu-system-riscv64 \
    -machine virt \
    -m 256M \
    -kernel ${script_dir}/rtthread.bin \
    -nographic \
    -drive if=none,file=${script_dir}/${type}.img,format=raw,id=blk0 \
    -device virtio-blk-device,drive=blk0,bus=virtio-mmio-bus.0 \
    -netdev user,id=tap0 \
    -device virtio-net-device,netdev=tap0,bus=virtio-mmio-bus.1 \
    -device virtio-serial-device \
    -chardev socket,host=127.0.0.1,port=4321,server=on,wait=off,telnet=on,id=console0 \
    -device virtserialport,chardev=console0
