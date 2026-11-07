from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_build.config import load_defconfig
from smart_build.domains.qemu import _script_text, qemu_command
from smart_build.errors import SmartBuildError
from smart_build.machines import load_machine


@pytest.mark.parametrize(
    ("machine", "serial_driver", "interrupt_driver"),
    (
        ("qemu-virt-aarch64", "RT_SERIAL_PL011", "RT_PIC_ARM_GIC"),
        ("qemu-virt-riscv64", "RT_SERIAL_8250", "RT_PIC_SIFIVE_PLIC"),
    ),
)
def test_virt_kernel_defaults_use_qemu_device_tree(machine, serial_driver, interrupt_driver):
    root = Path(__file__).resolve().parents[1]
    config = load_defconfig(root / "boards" / machine / "kernel_defconfig")
    for symbol in (
        "RT_USING_SMART",
        "RT_USING_DFS_PROCFS",
        "RT_USING_DFS_PROCFS_OFW",
        "RT_USING_DM",
        "RT_USING_OFW",
        "RT_USING_DMA",
        "RT_USING_BLK",
        "RT_USING_VIRTIO",
        "RT_VIRTIO_TRANSPORT_MMIO",
        "RT_VIRTIO_BLK",
        "RT_USING_PIC",
        serial_driver,
        interrupt_driver,
    ):
        assert config.get(f"CONFIG_{symbol}") == "y", symbol
    assert config["CONFIG_RT_USING_BUILTIN_FDT"] == "n"
    assert config["CONFIG_RT_VIRTIO_9P"] == "n"
    assert config["CONFIG_RT_VIRTIO_GPU"] == "n"
    if machine == "qemu-virt-riscv64":
        assert config["CONFIG_RT_USING_RISCV_NEW_COMMON"] == "y"
        assert config["CONFIG_BSP_QEMU_RISCV64"] == "y"
        assert config["CONFIG_ARCH_REMAP_KERNEL"] == "y"
        assert config["CONFIG_RT_USING_RESET"] == "y"
        assert config["CONFIG_RT_USING_CLK"] == "y"
        assert config["CONFIG_RT_PAGE_MPR_SIZE_DYNAMIC"] == "y"
        assert config["CONFIG_RT_USING_MEMBLOCK"] == "y"
        assert "CONFIG_ARCH_USING_RISCV_COMMON64" not in config


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
    assert command[command.index("-cpu") + 1] == "rv64,sv48=off,sv57=off"
    assert command[command.index("-global") + 1] == "virtio-mmio.force-legacy=false"
    assert "-append" in command
    bootargs = command[command.index("-append") + 1]
    assert "console=ttyS0" in bootargs
    assert "earlycon=sbi" in bootargs
    assert "cma=8M" in bootargs
    assert "coherent_pool=2M" in bootargs
    assert "root=vda0" in bootargs
    assert "rootfstype=ext" in bootargs


def test_riscv64_qemu_command_preserves_cpu_selection_with_sv39():
    machine = SimpleNamespace(
        qemu_profile="virt-riscv64",
        qemu_binary="qemu-system-riscv64",
        qemu_machine="virt",
        qemu_cpu="max",
    )
    command = qemu_command(machine)
    assert command[command.index("-cpu") + 1] == "max,sv48=off,sv57=off"


def test_custom_device_tree_is_added_to_qemu_command():
    machine = SimpleNamespace(
        qemu_profile="virt-aarch64",
        qemu_binary="qemu-system-aarch64",
        qemu_machine="virt",
        qemu_cpu="max",
        devicetree_source=Path("boards/demo/virt.dts"),
        qemu_bootargs=None,
    )
    command = qemu_command(machine)
    assert command[command.index("-dtb") + 1] == "images/devicetree.dtb"


def test_qemu_script_tree_options_replace_default_dtb():
    machine = SimpleNamespace(
        qemu_profile="virt-aarch64",
        devicetree_source=Path("boards/demo/virt.dts"),
    )
    command = [
        "qemu-system-aarch64",
        "-kernel",
        "images/rtthread.bin",
        "-append",
        "console=ttyAMA0",
        "-dtb",
        "images/devicetree.dtb",
    ]
    script = _script_text(command, machine)
    assert "--dtb FILE|--auto-dtb" in script
    assert 'cmd+=(-dtb "${DTB}")' in script
    assert script.count('cmd+=(-dtb "${DTB}")') == 1
    assert script.count("images/devicetree.dtb") == 1
    assert "  -dtb\n" not in script


def test_board_device_tree_metadata_is_board_relative(tmp_path):
    board = tmp_path / "boards" / "demo"
    (board / "devicetree" / "include").mkdir(parents=True)
    (board / "devicetree" / "virt.dts").write_text("/dts-v1/; / {};\n", encoding="utf-8")
    (board / "board.yaml").write_text(
        "schema_version: 1\nkind: board\nname: demo\nversion: 0.1.0\n"
        "arch: aarch64\nbsp: demo\nkernel_defconfig: kernel_defconfig\n"
        "toolchain:\n  package: demo-toolchain\n  target: demo\n  prefix: demo-\n"
        "qemu:\n  binary: qemu-system-aarch64\n  profile: virt-aarch64\n  machine: virt\n  cpu: max\n"
        "devicetree:\n  source: devicetree/virt.dts\n  include_dirs:\n    - devicetree/include\n",
        encoding="utf-8",
    )
    machine = load_machine(tmp_path, "demo")
    assert machine.devicetree_source.name == "virt.dts"
    assert machine.devicetree_include_dirs[0].name == "include"

    (board / "devicetree" / "escape.dts").symlink_to(tmp_path / "outside.dts")
    with pytest.raises(SmartBuildError, match="must stay under"):
        (board / "board.yaml").write_text(
            (board / "board.yaml").read_text(encoding="utf-8").replace(
                "devicetree/virt.dts", "devicetree/escape.dts"
            ),
            encoding="utf-8",
        )
        load_machine(tmp_path, "demo")
