SUMMARY = "QEMU ARM64 BSP"
#require recipes-boards/qemu-common.inc
LICENSE = "MIT"

MACHINE = "qemuarm64"
COMPATIBLE_MACHINE = "qemuarm64"

DEPENDS = "smart-gcc rt-thread"
