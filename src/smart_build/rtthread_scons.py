import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .doctor import resolve_host_tool
from .errors import SmartBuildError
from .package_kconfig import (
    load_native_package_kconfig,
    native_package_configuration_symbols,
    native_package_symbols,
)


SUPPORTED_LINKAGES = frozenset(("static", "dynamic", "mixed"))
SCONS_VERSION_RE = re.compile(r"SCons by Steven Knight et al\.:", re.IGNORECASE)


@dataclass(frozen=True)
class RtThreadSConsConfig:
    source_dir: Path
    kconfig_path: Path
    selection_symbol: str
    symbols: tuple[str, ...]
    supported_linkage: tuple[str, ...]
    install_target: str
    outputs: tuple[PurePosixPath, ...]


def parse_rtthread_scons_config(root, description, metadata, env_packages=None):
    if metadata.kconfig.mode != "native":
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.rtthread_scons requires kconfig.mode=native",
        )
    build = description.data.get("build")
    if not isinstance(build, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: build must be a mapping")
    if set(build) != {"rtthread_scons"}:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.rtthread_scons must be the package's only build backend",
        )
    raw = build.get("rtthread_scons")
    if not isinstance(raw, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: build.rtthread_scons must be a mapping")
    unsupported = sorted(set(raw) - {"supported_linkage", "install_target", "outputs"})
    if unsupported:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: unsupported build.rtthread_scons field(s): {', '.join(unsupported)}",
        )

    source_dir = _source_dir(root, description)
    _validate_source_tree(source_dir, description.path)
    if metadata.kconfig.path.resolve() != (source_dir / "Kconfig").resolve():
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: native Kconfig must belong to the independent source directory",
        )
    symbols = native_package_symbols(metadata, env_packages=env_packages)
    if metadata.kconfig.symbol not in symbols:
        raise SmartBuildError(
            "PACKAGE",
            f"{metadata.kconfig.path}: native Kconfig does not define {metadata.kconfig.symbol}",
        )

    supported_linkage = _supported_linkage(raw.get("supported_linkage"), description.path)
    install_target = raw.get("install_target")
    if install_target != "install":
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.rtthread_scons.install_target must be install",
        )
    outputs = _outputs(raw.get("outputs"), description.path)
    return RtThreadSConsConfig(
        source_dir=source_dir,
        kconfig_path=metadata.kconfig.path,
        selection_symbol=metadata.kconfig.symbol,
        symbols=symbols,
        supported_linkage=supported_linkage,
        install_target=install_target,
        outputs=outputs,
    )


def select_linkage(config, requested):
    if requested not in SUPPORTED_LINKAGES:
        raise SmartBuildError("PACKAGE", f"unsupported rootfs package linkage: {requested}")
    if requested == "mixed":
        return config.supported_linkage[0]
    if requested not in config.supported_linkage:
        supported = ", ".join(config.supported_linkage)
        raise SmartBuildError(
            "PACKAGE",
            f"RT-Thread SCons package does not support linkage {requested}; supported: {supported}",
        )
    return requested


def resolve_scons():
    path = Path(resolve_host_tool("scons")).resolve()
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise SmartBuildError("CONFIG", f"failed to query SCons version: {exc}") from exc
    output = completed.stdout or ""
    if completed.returncode != 0 or not SCONS_VERSION_RE.search(output):
        raise SmartBuildError("CONFIG", f"failed to query SCons version from {path}")
    version_line = next(
        (line.strip() for line in output.splitlines() if line.strip().startswith("SCons:")),
        "SCons",
    )
    return path, version_line


def scons_command(scons, source_dir, build_dir, stage_dir, config_path, sdk_dir, cross_compile, linkage):
    return [
        str(scons),
        "-C",
        str(source_dir),
        f"BUILD_DIR={build_dir}",
        f"DESTDIR={stage_dir}",
        f"KCONFIG_CONFIG={config_path}",
        f"SMART_SDK_DIR={sdk_dir}",
        f"CROSS_COMPILE={cross_compile}",
        f"LINKAGE={linkage}",
        "install",
    ]


def scons_pyconfig_command(scons, source_dir):
    return [str(scons), "--pyconfig-silent", "-C", str(source_dir)]


def write_package_config(path, metadata, values, env_packages=None):
    kconf = load_native_package_kconfig(metadata, env_packages=env_packages)
    symbol_names = native_package_configuration_symbols(kconf, metadata)
    for name in symbol_names:
        raw_value = values.get(name)
        if raw_value is None:
            raw_value = values.get(f"CONFIG_{name}")
        if raw_value is not None:
            _set_symbol_value(kconf.syms[name], raw_value)
    _set_symbol_value(kconf.syms[metadata.kconfig.symbol], "y")
    if kconf.syms[metadata.kconfig.symbol].str_value != "y":
        raise SmartBuildError(
            "CONFIG",
            f"native Kconfig dependencies prevent enabling {metadata.kconfig.symbol}",
        )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    kconf.write_config(str(destination))
    return tuple(symbol_names)


def command_env(
    base_env,
    build_dir,
    stage_dir,
    config_path,
    sdk_dir,
    rtt_root,
    cross_compile,
    linkage,
):
    env = os.environ.copy()
    env.update({key: str(value) for key, value in base_env.items()})
    env.update(
        {
            "BUILD_DIR": str(build_dir),
            "DESTDIR": str(stage_dir),
            "KCONFIG_CONFIG": str(config_path),
            "SMART_SDK_DIR": str(sdk_dir),
            "RTT_ROOT": str(rtt_root),
            "RTTHREAD_TOOLS_DIR": str(Path(rtt_root) / "tools"),
            "CROSS_COMPILE": str(cross_compile),
            "LINKAGE": str(linkage),
        }
    )
    python_path = str(Path(rtt_root) / "tools")
    if env.get("PYTHONPATH"):
        python_path = f"{python_path}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = python_path
    for key in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"):
        env.pop(key, None)
    return env


def _source_dir(root, description):
    source = description.data.get("source")
    if not isinstance(source, dict):
        raise SmartBuildError("PACKAGE", f"{description.path}: source must be a mapping")
    unsupported = sorted(set(source) - {"directory"})
    if unsupported:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: unsupported RT-Thread SCons source field(s): {', '.join(unsupported)}",
        )
    raw_directory = source.get("directory")
    root_path = Path(root).resolve()
    expected = (description.path.parent / "source").resolve()
    try:
        expected.relative_to(root_path)
    except ValueError as exc:
        raise SmartBuildError("PACKAGE", f"{description.path}: package source escapes repository") from exc
    if not isinstance(raw_directory, str) or not raw_directory:
        raise SmartBuildError("PACKAGE", f"{description.path}: source.directory must be a non-empty string")
    raw_path = PurePosixPath(raw_directory)
    if raw_path.is_absolute() or any(part in {"", ".."} for part in raw_path.parts):
        raise SmartBuildError("PACKAGE", f"{description.path}: unsafe source.directory: {raw_directory}")
    candidate = root_path.joinpath(*raw_path.parts)
    relative = expected.relative_to(root_path).as_posix()
    if raw_directory != relative or candidate.resolve(strict=False) != expected:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: source.directory must be {relative}",
        )
    if candidate.is_symlink() or not candidate.is_dir():
        raise SmartBuildError("PACKAGE", f"{description.path}: independent source directory not found: {candidate}")
    return candidate


def _validate_source_tree(source_dir, description_path):
    for entry in ("Kconfig", "SConstruct", "SConscript", "main.c"):
        path = source_dir / entry
        if path.is_symlink() or not path.is_file():
            raise SmartBuildError("PACKAGE", f"{description_path}: independent source missing {entry}: {path}")
    for path in source_dir.rglob("*"):
        if path.is_symlink():
            raise SmartBuildError("PACKAGE", f"{description_path}: source tree contains symlink: {path}")
        if not (path.is_dir() or path.is_file()):
            raise SmartBuildError("PACKAGE", f"{description_path}: source tree contains unsupported entry: {path}")


def _supported_linkage(raw, description_path):
    if not isinstance(raw, list) or not raw:
        raise SmartBuildError(
            "PACKAGE",
            f"{description_path}: build.rtthread_scons.supported_linkage must be a non-empty list",
        )
    result = []
    for item in raw:
        if not isinstance(item, str) or item not in SUPPORTED_LINKAGES:
            raise SmartBuildError(
                "PACKAGE",
                f"{description_path}: unsupported RT-Thread SCons linkage: {item}",
            )
        if item in result:
            raise SmartBuildError(
                "PACKAGE",
                f"{description_path}: duplicate RT-Thread SCons linkage: {item}",
            )
        result.append(item)
    return tuple(result)


def _outputs(raw, description_path):
    if not isinstance(raw, list) or not raw:
        raise SmartBuildError(
            "PACKAGE",
            f"{description_path}: build.rtthread_scons.outputs must be a non-empty list",
        )
    result = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise SmartBuildError(
                "PACKAGE",
                f"{description_path}: build.rtthread_scons.outputs entries must be non-empty strings",
            )
        path = PurePosixPath(item)
        if (
            "\\" in item
            or not path.is_absolute()
            or len(path.parts) < 2
            or any(part in {"", ".", ".."} for part in path.parts[1:])
        ):
            raise SmartBuildError(
                "PACKAGE",
                f"{description_path}: unsafe RT-Thread SCons output path: {item}",
            )
        relative = PurePosixPath(*path.parts[1:])
        if item != f"/{relative.as_posix()}":
            raise SmartBuildError(
                "PACKAGE",
                f"{description_path}: RT-Thread SCons output path must be canonical: {item}",
            )
        if relative in result:
            raise SmartBuildError(
                "PACKAGE",
                f"{description_path}: duplicate RT-Thread SCons output path: {item}",
            )
        result.append(relative)
    return tuple(result)


def _set_symbol_value(symbol, value):
    text = str(value)
    if text in {"y", "m", "n"}:
        symbol.set_value({"n": 0, "m": 1, "y": 2}[text])
    else:
        symbol.set_value(text)
