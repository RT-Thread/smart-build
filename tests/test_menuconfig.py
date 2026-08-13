from pathlib import Path

import kconfiglib
import pytest

from smart_build.menuconfig import run_menuconfig
from smart_build.paths import BuildPaths
from smart_build.menuconfig import _config_values, _load_values


ROOT = Path(__file__).resolve().parents[1]


def _kconfig(tmp_path, monkeypatch):
    # Native package Kconfigs expect an Env package index even when the
    # selected rootfs does not expose the package menu.
    env_root = tmp_path / "env-packages"
    env_root.mkdir(exist_ok=True)
    (env_root / "Kconfig").write_text("", encoding="utf-8")
    monkeypatch.setenv("PKGS_ROOT", str(env_root))
    monkeypatch.setenv("PKGS_DIR", str(env_root))
    monkeypatch.setenv("srctree", str(ROOT))
    return kconfiglib.Kconfig(str(ROOT / "Kconfig"), warn=False)


def _visible_children(node):
    prompts = []
    child = node.list
    while child is not None:
        if child.prompt is not None and kconfiglib.expr_value(child.prompt[1]):
            prompts.append(child.prompt[0])
        child = child.next
    return prompts


def _find_prompt(node, prompt):
    child = node.list
    while child is not None:
        if (
            child.prompt is not None
            and child.prompt[0] == prompt
            and kconfiglib.expr_value(child.prompt[1])
        ):
            return child
        found = _find_prompt(child, prompt)
        if found is not None:
            return found
        child = child.next
    return None


@pytest.mark.parametrize(
    ("machine", "package", "version_prompts"),
    (
        (
            "qemu-virt-aarch64",
            "aarch64-linux-musleabi-gcc-latest",
            ["GCC 12.2.0"],
        ),
        (
            "qemu-virt-riscv64",
            "riscv64-linux-musleabi-gcc-latest",
            ["GCC 12.2.0"],
        ),
        (
            "qemu-vexpress-a9",
            "arm-linux-musleabi-gcc-stable",
            ["GCC 7.3.0 (Env SDK)", "GCC 12.2.0"],
        ),
    ),
)
def test_menuconfig_exposes_selected_machine_toolchain_menu(
    tmp_path, monkeypatch, machine, package, version_prompts
):
    kconf = _kconfig(tmp_path, monkeypatch)
    _load_values(
        kconf,
        {
            "MACHINE": machine,
            "TOOLCHAIN": package,
            "TOOLCHAIN_VERSION": "7.3.0" if machine == "qemu-vexpress-a9" else "12.2.0",
        },
    )

    menu = _find_prompt(kconf.top_node, "Cross toolchain")
    assert menu is not None
    assert kconfiglib.expr_value(menu.prompt[1])
    assert _visible_children(menu) == ["Toolchain version", "Custom toolchain path"]
    assert _visible_children(_find_prompt(menu, "Toolchain version")) == version_prompts


def test_menuconfig_restores_toolchain_version_and_path(tmp_path, monkeypatch):
    values = {
        "MACHINE": "qemu-vexpress-a9",
        "TOOLCHAIN": "arm-linux-musleabi-gcc-latest",
        "TOOLCHAIN_VERSION": "12.2.0",
        "TOOLCHAIN_PATH": "/opt/arm-toolchain",
    }
    kconf = _kconfig(tmp_path, monkeypatch)
    _load_values(kconf, values)
    assert kconf.syms["TOOLCHAIN_QEMU_VEXPRESS_A9_7_3_0"].str_value == "n"
    assert kconf.syms["TOOLCHAIN_QEMU_VEXPRESS_A9_12_2_0"].str_value == "y"
    assert kconf.syms["TOOLCHAIN_PATH"].str_value == values["TOOLCHAIN_PATH"]

    saved = _config_values(kconf)
    assert saved["TOOLCHAIN"] == values["TOOLCHAIN"]
    assert saved["TOOLCHAIN_VERSION"] == values["TOOLCHAIN_VERSION"]
    assert saved["TOOLCHAIN_PATH"] == values["TOOLCHAIN_PATH"]

    reopened = _kconfig(tmp_path, monkeypatch)
    _load_values(reopened, saved)
    assert reopened.syms["TOOLCHAIN_QEMU_VEXPRESS_A9_12_2_0"].str_value == "y"
    assert reopened.syms["TOOLCHAIN_VERSION"].str_value == "12.2.0"
    assert reopened.syms["TOOLCHAIN"].str_value == "arm-linux-musleabi-gcc-latest"
    assert reopened.syms["TOOLCHAIN_PATH"].str_value == "/opt/arm-toolchain"


def test_menuconfig_machine_switch_uses_new_machine_toolchain_defaults(tmp_path, monkeypatch):
    kconf = _kconfig(tmp_path, monkeypatch)
    _load_values(
        kconf,
        {
            "MACHINE": "qemu-vexpress-a9",
            "TOOLCHAIN": "arm-linux-musleabi-gcc-stable",
            "TOOLCHAIN_VERSION": "7.3.0",
        },
    )
    kconf.syms["MACHINE_QEMU_VIRT_AARCH64"].set_value(2)

    selected = _config_values(kconf)
    assert selected["MACHINE"] == "qemu-virt-aarch64"
    assert selected["TOOLCHAIN"] == "aarch64-linux-musleabi-gcc-latest"
    assert selected["TOOLCHAIN_VERSION"] == "12.2.0"


def test_run_menuconfig_persists_toolchain_selection(tmp_path, monkeypatch):
    root = tmp_path
    (root / "boards" / "qemu-vexpress-a9").mkdir(parents=True)
    (root / "Kconfig").write_text(
        'mainmenu "Test configuration"\nsource "boards/Kconfig"\n',
        encoding="utf-8",
    )
    (root / "boards" / "Kconfig").write_text(
        'choice\n    prompt "Machine"\n    default MACHINE_QEMU_VEXPRESS_A9\n'
        'source "boards/qemu-vexpress-a9/Kconfig"\nendchoice\n',
        encoding="utf-8",
    )
    (root / "boards" / "qemu-vexpress-a9" / "Kconfig").write_text(
        (ROOT / "boards" / "qemu-vexpress-a9" / "Kconfig").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    defconfig = root / "boards" / "qemu-vexpress-a9" / "defconfig"
    defconfig.write_text(
        "MACHINE=qemu-vexpress-a9\n"
        "TOOLCHAIN=arm-linux-musleabi-gcc-stable\n"
        "TOOLCHAIN_VERSION=7.3.0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("srctree", str(root))
    paths = BuildPaths.for_machine("qemu-vexpress-a9", root=root)

    def frontend(kconf):
        kconf.syms["TOOLCHAIN_QEMU_VEXPRESS_A9_12_2_0"].set_value(2)
        kconf.syms["TOOLCHAIN_PATH"].set_value("/opt/arm-toolchain")

    run_menuconfig(paths, frontend=frontend)
    workspace = (root / "build" / ".config").read_text(encoding="utf-8")
    saved_defconfig = defconfig.read_text(encoding="utf-8")
    for content in (workspace, saved_defconfig):
        assert "TOOLCHAIN=arm-linux-musleabi-gcc-latest\n" in content
        assert "TOOLCHAIN_VERSION=12.2.0\n" in content
        assert "TOOLCHAIN_PATH=/opt/arm-toolchain\n" in content
