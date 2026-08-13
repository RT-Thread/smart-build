import os
from contextlib import nullcontext
from pathlib import Path

from .config import (
    DEFAULT_MACHINE,
    load_defconfig,
    load_workspace_config,
    workspace_config_path,
    write_workspace_config,
)
from .errors import SmartBuildError
from .package_kconfig import (
    load_native_package_kconfig,
    native_kconfig_environment,
    native_package_configuration_symbols,
    native_package_symbols_from_kconfig,
)
from .package_metadata import load_all_package_metadata, package_selection_symbol
from .paths import board_defconfig_path


BASE_OWNED_KEYS = (
    "MACHINE",
    "ARCH",
    "BSP",
    "ROOTFS",
    "ROOTFS_BUILD_MODE",
    "ROOTFS_PROFILE",
    "ROOTFS_IMAGE_FORMAT",
    "ROOTFS_IMAGE_SIZE_MB",
    "ROOTFS_IMAGE_SIZE_MODE",
    "ROOTFS_PACKAGE_MODE",
    "TOOLCHAIN",
    "TOOLCHAIN_VERSION",
    "TOOLCHAIN_PATH",
)
OWNED_KEYS = (
    *BASE_OWNED_KEYS[:-1],
    "PACKAGE_HELLO",
    "PACKAGE_ZLIB",
    "PACKAGE_MICROPYTHON",
    BASE_OWNED_KEYS[-1],
)
PACKAGE_KEYS = frozenset({
    "PACKAGE_HELLO",
    "PACKAGE_ZLIB",
    "PACKAGE_MICROPYTHON",
})
ROOTFS_LOCAL_CHOICE_KEYS = frozenset({
    "ROOTFS_BUILD_MODE",
    "ROOTFS_IMAGE_FORMAT",
    "ROOTFS_IMAGE_SIZE_MB",
    "ROOTFS_IMAGE_SIZE_MODE",
})
MACHINE_CHOICES = {
    "MACHINE_QEMU_VIRT_AARCH64": {
        "MACHINE": "qemu-virt-aarch64",
        "ARCH": "aarch64",
        "BSP": "qemu-virt64-aarch64",
        "TOOLCHAIN": "aarch64-linux-musleabi-gcc-latest",
        "TOOLCHAIN_VERSION": "12.2.0",
        "TOOLCHAIN_CHOICES": {"TOOLCHAIN_QEMU_VIRT_AARCH64_12_2_0": ("12.2.0", "aarch64-linux-musleabi-gcc-latest")},
    },
    "MACHINE_QEMU_VIRT_RISCV64": {
        "MACHINE": "qemu-virt-riscv64",
        "ARCH": "riscv64",
        "BSP": "qemu-virt64-riscv",
        "TOOLCHAIN": "riscv64-linux-musleabi-gcc-latest",
        "TOOLCHAIN_VERSION": "12.2.0",
        "TOOLCHAIN_CHOICES": {"TOOLCHAIN_QEMU_VIRT_RISCV64_12_2_0": ("12.2.0", "riscv64-linux-musleabi-gcc-latest")},
    },
    "MACHINE_QEMU_VEXPRESS_A9": {
        "MACHINE": "qemu-vexpress-a9",
        "ARCH": "arm",
        "BSP": "qemu-vexpress-a9",
        "TOOLCHAIN": "arm-linux-musleabi-gcc-stable",
        "TOOLCHAIN_VERSION": "7.3.0",
        "TOOLCHAIN_CHOICES": {
            "TOOLCHAIN_QEMU_VEXPRESS_A9_7_3_0": ("7.3.0", "arm-linux-musleabi-gcc-stable"),
            "TOOLCHAIN_QEMU_VEXPRESS_A9_12_2_0": ("12.2.0", "arm-linux-musleabi-gcc-latest"),
        },
    },
}


def run_menuconfig(paths, frontend=None):
    try:
        import kconfiglib
    except ImportError as exc:
        raise SmartBuildError("CONFIG", "kconfiglib is required for menuconfig") from exc

    kconfig_path = paths.root / "Kconfig"
    defconfig_path = board_defconfig_path(paths.root, paths.machine)
    if not kconfig_path.is_file():
        raise SmartBuildError("CONFIG", f"Kconfig not found: {kconfig_path}")
    if not defconfig_path.is_file():
        raise SmartBuildError("CONFIG", f"defconfig not found: {defconfig_path}")

    workspace_config = workspace_config_path(paths.root)
    packages = load_all_package_metadata(paths.root)
    package_environment = (
        native_kconfig_environment()
        if any(metadata.kconfig.mode == "native" for metadata in packages)
        else nullcontext()
    )
    with package_environment:
        old_srctree = os.environ.get("srctree")
        old_kconfig_config = os.environ.get("KCONFIG_CONFIG")
        old_config_prefix = os.environ.get("CONFIG_")
        os.environ["srctree"] = str(paths.root)
        os.environ["KCONFIG_CONFIG"] = str(workspace_config)
        os.environ["CONFIG_"] = ""
        try:
            kconf = kconfiglib.Kconfig(str(kconfig_path), warn=False)
            kconf.config_prefix = ""
            _load_values(kconf, _initial_values(paths.root, paths.machine, defconfig_path))
            _write_frontend_config(kconf, workspace_config)
            selected_frontend = frontend if frontend is not None else default_menuconfig_frontend()
            selected_frontend(kconf)
            values = _config_values(kconf, paths.root)
            selected_defconfig_path = board_defconfig_path(paths.root, values["MACHINE"])
            _write_defconfig(
                selected_defconfig_path,
                values,
                _owned_keys(kconf, paths.root),
                _package_keys(kconf, paths.root),
            )
            write_workspace_config(paths.root, values)
        finally:
            if old_srctree is None:
                os.environ.pop("srctree", None)
            else:
                os.environ["srctree"] = old_srctree
            if old_kconfig_config is None:
                os.environ.pop("KCONFIG_CONFIG", None)
            else:
                os.environ["KCONFIG_CONFIG"] = old_kconfig_config
            if old_config_prefix is None:
                os.environ.pop("CONFIG_", None)
            else:
                os.environ["CONFIG_"] = old_config_prefix

    return selected_defconfig_path


def run_package_menuconfig(paths, metadata, frontend=None, env_packages=None):
    defconfig_path = board_defconfig_path(paths.root, paths.machine)
    if not defconfig_path.is_file():
        raise SmartBuildError("CONFIG", f"defconfig not found: {defconfig_path}")

    workspace_config = workspace_config_path(paths.root)
    frontend_config = (
        paths.work_dir
        / "configure"
        / f"package-{metadata.name}"
        / ".config"
    )
    frontend_config.parent.mkdir(parents=True, exist_ok=True)
    with native_kconfig_environment(env_packages):
        old_srctree = os.environ.get("srctree")
        old_kconfig_config = os.environ.get("KCONFIG_CONFIG")
        old_config_prefix = os.environ.get("CONFIG_")
        os.environ["srctree"] = str(metadata.kconfig.path.parent)
        os.environ["KCONFIG_CONFIG"] = str(frontend_config)
        os.environ["CONFIG_"] = "CONFIG_"
        try:
            kconf = load_native_package_kconfig(metadata, env_packages=env_packages)
            symbols = native_package_configuration_symbols(kconf, metadata)
            initial_values = _initial_values(
                paths.root,
                paths.machine,
                defconfig_path,
            )
            _load_values(kconf, initial_values)
            _enable_package_symbol(kconf, metadata)
            _write_frontend_config(kconf, frontend_config)
            selected_frontend = frontend if frontend is not None else default_menuconfig_frontend()
            selected_frontend(kconf)
            _enable_package_symbol(kconf, metadata)
            package_values = _package_config_values(kconf, symbols)
            board_values = _replace_package_values(
                load_defconfig(defconfig_path),
                symbols,
                package_values,
            )
            _write_defconfig(
                defconfig_path,
                board_values,
                tuple(board_values),
                symbols,
            )
            workspace_values = _replace_package_values(
                initial_values,
                symbols,
                package_values,
            )
            write_workspace_config(paths.root, workspace_values)
        finally:
            if old_srctree is None:
                os.environ.pop("srctree", None)
            else:
                os.environ["srctree"] = old_srctree
            if old_kconfig_config is None:
                os.environ.pop("KCONFIG_CONFIG", None)
            else:
                os.environ["KCONFIG_CONFIG"] = old_kconfig_config
            if old_config_prefix is None:
                os.environ.pop("CONFIG_", None)
            else:
                os.environ["CONFIG_"] = old_config_prefix

    return defconfig_path, workspace_config


def _write_frontend_config(kconf, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    kconf.write_config(str(path))


def _initial_values(root, machine, defconfig_path):
    values = load_defconfig(defconfig_path)
    workspace_values = load_workspace_config(root)
    if workspace_values.get("MACHINE") == machine:
        values.update(workspace_values)
    return values


def default_menuconfig_frontend():
    import kconfiglib

    frontend = getattr(kconfiglib, "menuconfig", None)
    if frontend is not None:
        return frontend

    try:
        from menuconfig import menuconfig as external_frontend
    except ImportError as exc:
        raise SmartBuildError("CONFIG", "installed kconfiglib has no menuconfig frontend") from exc
    return external_frontend


def _load_values(kconf, values):
    _set_choice_value(kconf, "MACHINE", values.get("MACHINE"))
    _set_choice_value(kconf, "ROOTFS", values.get("ROOTFS"))
    _set_rootfs_local_choice_value(kconf, "ROOTFS_BUILD_MODE", _rootfs_build_mode(values))
    _set_choice_value(kconf, "ROOTFS_PROFILE", values.get("ROOTFS_PROFILE"))
    _set_rootfs_local_choice_value(kconf, "ROOTFS_IMAGE_FORMAT", values.get("ROOTFS_IMAGE_FORMAT"))
    _set_rootfs_local_choice_value(kconf, "ROOTFS_IMAGE_SIZE_MB", values.get("ROOTFS_IMAGE_SIZE_MB"))
    _set_rootfs_local_choice_value(kconf, "ROOTFS_IMAGE_SIZE_MODE", values.get("ROOTFS_IMAGE_SIZE_MODE"))
    for key, value in values.items():
        if key == "ROOTFS_PROFILE":
            continue
        symbol = kconf.syms.get(key)
        if symbol is None:
            continue
        if value in {"y", "n", "m"}:
            symbol.set_value(2 if value == "y" else 0 if value == "n" else 1)
        else:
            symbol.set_value(value)
    _set_toolchain_choice_value(kconf, values)


def _enable_package_symbol(kconf, metadata):
    symbol = kconf.syms.get(metadata.kconfig.symbol)
    if symbol is None or not symbol.nodes:
        raise SmartBuildError(
            "PACKAGE",
            f"{metadata.kconfig.path}: native Kconfig does not define {metadata.kconfig.symbol}",
        )
    symbol.set_value(2)
    if symbol.str_value != "y":
        raise SmartBuildError(
            "CONFIG",
            f"native Kconfig dependencies prevent enabling {metadata.kconfig.symbol}",
        )


def _package_config_values(kconf, symbols):
    values = {}
    for name in symbols:
        symbol = kconf.syms.get(name)
        if symbol is None:
            continue
        value = symbol.str_value
        if value not in {"", "n"}:
            values[name] = value
    return values


def _replace_package_values(values, symbols, package_values):
    result = {
        key: value
        for key, value in values.items()
        if key not in symbols
    }
    result.update(package_values)
    return result


def _write_defconfig(path, values, owned_keys=OWNED_KEYS, package_keys=PACKAGE_KEYS):
    lines = []
    for key in owned_keys:
        if key not in values:
            continue
        value = values[key]
        if key in package_keys and value == "n":
            continue
        if value in {"y", "n"}:
            lines.append(f"{key}={value}")
        else:
            lines.append(f"{key}={_quote_if_needed(value)}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _config_values(kconf, root=None):
    result = {}
    package_keys = _package_keys(kconf, root)
    for key in _owned_keys(kconf, root):
        symbol = kconf.syms.get(key)
        if symbol is None:
            continue
        value = symbol.str_value
        if value == "":
            continue
        result[key] = value
    result["ROOTFS"] = _selected_choice_value(
        kconf,
        "ROOTFS",
        {
            "ROOTFS_MINIMAL": "minimal",
            "ROOTFS_BASIC": "basic",
            "ROOTFS_FULL": "full",
            "ROOTFS_NONE": "none",
        },
        result.get("ROOTFS"),
    )
    if result.get("ROOTFS") == "none":
        result.pop("ROOTFS_BUILD_MODE", None)
        result.pop("ROOTFS_PROFILE", None)
        _drop_rootfs_image_values(result)
        result.pop("ROOTFS_PACKAGE_MODE", None)
        _drop_package_values(result, package_keys)
    elif result.get("ROOTFS") == "basic":
        result["ROOTFS_BUILD_MODE"] = "static"
        result.pop("ROOTFS_PROFILE", None)
        _set_rootfs_image_values(kconf, result)
        result.pop("ROOTFS_PACKAGE_MODE", None)
        _drop_package_values(result, package_keys)
    else:
        result["ROOTFS_BUILD_MODE"] = _selected_rootfs_local_choice_value(
            kconf,
            "ROOTFS_BUILD_MODE",
            ("static", "dynamic", "mixed"),
            result.get("ROOTFS_BUILD_MODE"),
        )
        _set_rootfs_image_values(kconf, result)
        if result.get("ROOTFS") == "full":
            result["ROOTFS_PROFILE"] = _selected_choice_value(
                kconf,
                "ROOTFS_PROFILE",
                {
                    "ROOTFS_PROFILE_BASE": "base",
                    "ROOTFS_PROFILE_DEVEL": "devel",
                    "ROOTFS_PROFILE_FULL": "full",
                },
                result.get("ROOTFS_PROFILE") or "base",
            )
            result["ROOTFS_PACKAGE_MODE"] = _rootfs_package_mode_value(kconf, result.get("ROOTFS_PACKAGE_MODE"))
        else:
            result.pop("ROOTFS_PROFILE", None)
            result.pop("ROOTFS_PACKAGE_MODE", None)
            _drop_package_values(result, package_keys)
    machine_values = _selected_machine_values(kconf)
    if machine_values:
        result.update(machine_values)
    elif "MACHINE" not in result:
        machine_symbol = kconf.syms.get("MACHINE")
        if machine_symbol is not None:
            result["MACHINE"] = machine_symbol.str_value or DEFAULT_MACHINE
    return result


def _set_choice_value(kconf, base_key, value):
    mappings = {
        "MACHINE": {
            metadata["MACHINE"]: symbol_name
            for symbol_name, metadata in MACHINE_CHOICES.items()
        },
        "ROOTFS": {
            "minimal": "ROOTFS_MINIMAL",
            "basic": "ROOTFS_BASIC",
            "full": "ROOTFS_FULL",
            "none": "ROOTFS_NONE",
        },
        "ROOTFS_PROFILE": {
            "base": "ROOTFS_PROFILE_BASE",
            "devel": "ROOTFS_PROFILE_DEVEL",
            "full": "ROOTFS_PROFILE_FULL",
        },
    }
    symbol_name = mappings.get(base_key, {}).get(value)
    symbol = kconf.syms.get(symbol_name)
    if symbol is not None:
        symbol.set_value(2)


def _selected_machine_values(kconf):
    for symbol_name, values in MACHINE_CHOICES.items():
        symbol = kconf.syms.get(symbol_name)
        if symbol is not None and symbol.str_value == "y":
            result = {key: value for key, value in values.items() if key != "TOOLCHAIN_CHOICES"}
            choices = values.get("TOOLCHAIN_CHOICES", {})
            for choice_symbol, choice_values in choices.items():
                choice = kconf.syms.get(choice_symbol)
                if choice is not None and choice.str_value == "y":
                    result["TOOLCHAIN_VERSION"], result["TOOLCHAIN"] = choice_values
                    break
            return result
    return {}


def _set_toolchain_choice_value(kconf, values):
    """Restore the active machine's toolchain choice from saved config values."""
    machine = values.get("MACHINE")
    for symbol_name, machine_values in MACHINE_CHOICES.items():
        if machine_values.get("MACHINE") != machine:
            continue
        version = values.get("TOOLCHAIN_VERSION")
        package = values.get("TOOLCHAIN")
        for choice_symbol, choice_values in machine_values.get("TOOLCHAIN_CHOICES", {}).items():
            if choice_values == (version, package):
                symbol = kconf.syms.get(choice_symbol)
                if symbol is not None:
                    symbol.set_value(2)
                return
        return


def _rootfs_package_mode(values, root=None):
    mode = values.get("ROOTFS_PACKAGE_MODE")
    if mode is not None:
        return mode
    if any(key in values for key in _package_selection_keys(root)):
        return "manual"
    return None


def _owned_keys(kconf, root=None):
    return (
        *BASE_OWNED_KEYS[:-1],
        *_package_keys(kconf, root),
        BASE_OWNED_KEYS[-1],
    )


def _package_keys(kconf, root=None):
    keys = {key for key in kconf.syms if key.startswith("PACKAGE_")}
    if root is not None:
        for metadata in load_all_package_metadata(root):
            keys.update(native_package_symbols_from_kconfig(kconf, metadata))
    return tuple(sorted(keys))


def _package_selection_keys(root=None):
    if root is None:
        return PACKAGE_KEYS
    return frozenset(
        package_selection_symbol(metadata)
        for metadata in load_all_package_metadata(root)
    )


def _drop_package_values(values, package_keys):
    for key in package_keys:
        values.pop(key, None)


def _drop_rootfs_image_values(values):
    values.pop("ROOTFS_IMAGE_FORMAT", None)
    values.pop("ROOTFS_IMAGE_SIZE_MB", None)
    values.pop("ROOTFS_IMAGE_SIZE_MODE", None)


def _set_rootfs_image_values(kconf, result):
    result["ROOTFS_IMAGE_FORMAT"] = _selected_rootfs_local_choice_value(
        kconf,
        "ROOTFS_IMAGE_FORMAT",
        ("ext4", "fat", "romfs"),
        result.get("ROOTFS_IMAGE_FORMAT") or "ext4",
    )
    if result["ROOTFS_IMAGE_FORMAT"] == "romfs":
        result.pop("ROOTFS_IMAGE_SIZE_MB", None)
        result.pop("ROOTFS_IMAGE_SIZE_MODE", None)
        return
    result["ROOTFS_IMAGE_SIZE_MB"] = _selected_rootfs_local_choice_value(
        kconf,
        "ROOTFS_IMAGE_SIZE_MB",
        ("1", "4", "8", "16", "32", "64", "128", "256", "512", "1024"),
        result.get("ROOTFS_IMAGE_SIZE_MB") or "16",
    )
    if result["ROOTFS_IMAGE_FORMAT"] == "ext4":
        result["ROOTFS_IMAGE_SIZE_MODE"] = _selected_rootfs_local_choice_value(
            kconf,
            "ROOTFS_IMAGE_SIZE_MODE",
            ("fixed", "expandable"),
            result.get("ROOTFS_IMAGE_SIZE_MODE") or "expandable",
        )
    else:
        result["ROOTFS_IMAGE_SIZE_MODE"] = "fixed"


def _rootfs_build_mode(values):
    if values.get("ROOTFS") == "basic":
        return "static"
    return values.get("ROOTFS_BUILD_MODE") or values.get("ROOTFS_PROFILE")


def _rootfs_package_mode_value(kconf, fallback):
    return "manual"


def _active_rootfs_prefix(kconf):
    for symbol_name in ("ROOTFS_MINIMAL", "ROOTFS_BASIC", "ROOTFS_FULL"):
        symbol = kconf.syms.get(symbol_name)
        if symbol is not None and symbol.str_value == "y":
            return symbol_name
    return None


def _rootfs_local_choice_symbol(kconf, base_key, value):
    prefix = _active_rootfs_prefix(kconf)
    if prefix is None or value is None:
        return None
    suffix = base_key.removeprefix("ROOTFS_")
    normalized = str(value).upper().replace("-", "_")
    return f"{prefix}_{suffix}_{normalized}"


def _set_rootfs_local_choice_value(kconf, base_key, value):
    symbol_name = _rootfs_local_choice_symbol(kconf, base_key, value)
    symbol = kconf.syms.get(symbol_name)
    if symbol is not None:
        symbol.set_value(2)


def _selected_rootfs_local_choice_value(kconf, base_key, values, fallback):
    for value in values:
        symbol_name = _rootfs_local_choice_symbol(kconf, base_key, value)
        symbol = kconf.syms.get(symbol_name)
        if symbol is not None and symbol.str_value == "y":
            return value
    return fallback


def _selected_choice_value(kconf, base_key, mapping, fallback):
    for symbol_name, value in mapping.items():
        symbol = kconf.syms.get(symbol_name)
        if symbol is not None and symbol.str_value == "y":
            return value
    return fallback


def _quote_if_needed(value):
    text = str(value)
    if text == "" or any(char.isspace() for char in text) or text in {"y", "n"}:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text
