#!/bin/bash

# 启动 QEMU 并运行 rtthread.bin 和 ext4.img
qemu-system-aarch64 -M virt,gic-version=2 -cpu cortex-a53 -m 128M -smp 4 -kernel ./models/rtthread.bin -nographic \
-drive if=none,file=./models/build/ext4.img,format=raw,id=blk0 \
-device virtio-blk-device,drive=blk0,bus=virtio-mmio-bus.0 \
-netdev user,id=net0 -device virtio-net-device,netdev=net0,bus=virtio-mmio-bus.1 \
-device virtio-serial-device \
-chardev socket,host=127.0.0.1,port=4321,server=on,wait=off,telnet=on,id=console0 \
-device virtserialport,chardev=console0 \
-nographic \
-append "console=ttyAMA0" &

# 等待 10 秒钟，以便 QEMU 启动并执行 /bin/hello
sleep 10

# 在 QEMU 虚拟机上执行 /bin/hello 任务
echo "Running /bin/hello in QEMU..."
telnet 127.0.0.1 4321 <<EOF
/bin/hello
EOF

# 等待 10 秒后杀死 QEMU 进程
sleep 10
echo "Terminating QEMU..."
pkill -f "qemu-system-aarch64"