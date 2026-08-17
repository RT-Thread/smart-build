from types import SimpleNamespace

from smart_build.domains.qemu import qemu_command


def test_aarch64_qemu_command_passes_rootfs_bootargs():
    machine = SimpleNamespace(
        qemu_profile="virt-aarch64",
        qemu_binary="qemu-system-aarch64",
        qemu_machine="virt",
        qemu_cpu="max",
    )
    command = qemu_command(machine, rootfs_format="ext4")
    assert command[command.index("-smp") + 1] == "1"
    assert command[command.index("-m") + 1] == "256M"
    assert "-append" in command
    bootargs = command[command.index("-append") + 1]
    assert "console=ttyAMA0" in bootargs
    assert "root=vda0" in bootargs
    assert "rootfstype=ext" in bootargs


def test_riscv64_qemu_command_passes_rootfs_bootargs():
    machine = SimpleNamespace(
        qemu_profile="virt-riscv64",
        qemu_binary="qemu-system-riscv64",
        qemu_machine="virt",
        qemu_cpu=None,
    )
    command = qemu_command(machine, rootfs_format="ext4")
    assert "-append" in command
    bootargs = command[command.index("-append") + 1]
    assert "console=ttyS0" in bootargs
    assert "root=vda0" in bootargs
    assert "rootfstype=ext" in bootargs
