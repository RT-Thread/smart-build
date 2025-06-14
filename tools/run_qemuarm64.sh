#!/bin/bash

type=${1}
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -n "${type}" ]; then
    type="ext4"
fi

qemu-system-aarch64 \
    -M virt,gic-version=2 \
    -cpu cortex-a53 \
    -smp 4 \
    -m 128M \
    -kernel ${script_dir}/rtthread.bin \
    -nographic \
    -drive if=none,file=${script_dir}/${type}.img,format=raw,id=blk0 \
    -device virtio-blk-device,drive=blk0,bus=virtio-mmio-bus.0 \
    -netdev user,id=net0,hostfwd=tcp::58080-:22 \
    -device virtio-net-device,netdev=net0,bus=virtio-mmio-bus.1 \
    -device virtio-serial-device \
    -chardev socket,host=127.0.0.1,port=43210,server=on,wait=off,telnet=on,id=console0 \
    -device virtserialport,chardev=console0
