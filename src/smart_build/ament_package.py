"""ament_cmake package backend for ROS 2 C/C++ native packages."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import SmartBuildError


LINKAGE_VALUES = frozenset(("shared", "static", "mixed"))
HOST_PYTHON_VALUES = frozenset(("sdk", "system"))
PROTECTED_CMAKE_ARGS = (
    "-DBUILD_SHARED_LIBS=",
    "-DCMAKE_EXE_LINKER_FLAGS=",
    "-DCMAKE_INSTALL_LIBDIR=",
    "-DCMAKE_INSTALL_PREFIX=",
    "-DCMAKE_MODULE_LINKER_FLAGS=",
    "-DCMAKE_PREFIX_PATH=",
    "-DCMAKE_SHARED_LINKER_FLAGS=",
    "-DCMAKE_TOOLCHAIN_FILE=",
    "-DPYTHON_EXECUTABLE=",
    "-DPython3_EXECUTABLE=",
)


@dataclass(frozen=True)
class AmentCMakeBuild:
    testing: bool
    outputs: tuple[PurePosixPath, ...]
    cmake_args: tuple[str, ...]
    linkage: str
    host_python: str


def parse_ament_cmake_build(description):
    build = description.data.get("build")
    raw = build.get("ament_cmake") if isinstance(build, dict) else None
    if not isinstance(raw, dict):
        raise SmartBuildError(
            "PACKAGE", f"{description.path}: build.ament_cmake must be a mapping"
        )
    testing = raw.get("testing", False)
    if not isinstance(testing, bool):
        raise SmartBuildError(
            "PACKAGE", f"{description.path}: build.ament_cmake.testing must be a bool"
        )
    outputs = _output_paths(description, raw.get("outputs"), "build.ament_cmake.outputs")
    cmake_args = _cmake_args(description, raw.get("cmake_args", []))
    linkage = raw.get("linkage", "shared")
    if linkage not in LINKAGE_VALUES:
        values = ", ".join(sorted(LINKAGE_VALUES))
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.ament_cmake.linkage must be one of {values}",
        )
    host_python = raw.get("host_python", "sdk")
    if host_python not in HOST_PYTHON_VALUES:
        values = ", ".join(sorted(HOST_PYTHON_VALUES))
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.ament_cmake.host_python must be one of {values}",
        )
    return AmentCMakeBuild(
        testing=testing,
        outputs=outputs,
        cmake_args=cmake_args,
        linkage=linkage,
        host_python=host_python,
    )


def ament_toolchain_text(toolchain):
    processor = _cmake_processor(toolchain)
    sysroot_lib_dir = getattr(
        toolchain,
        "sysroot_lib_dir",
        Path(toolchain.bin_dir).parent / toolchain.target / "lib",
    )

    def tool(name):
        return toolchain.bin_dir / f"{toolchain.prefix}{name}"

    cxx = getattr(toolchain, "gxx", tool("g++"))
    return "\n".join(
        [
            "set(CMAKE_SYSTEM_NAME Linux)",
            f"set(CMAKE_SYSTEM_PROCESSOR {processor})",
            "set(UNIX TRUE)",
            f'set(CMAKE_C_COMPILER "{toolchain.gcc}")',
            f'set(CMAKE_CXX_COMPILER "{cxx}")',
            f'set(CMAKE_AR "{tool("ar")}")',
            f'set(CMAKE_RANLIB "{tool("ranlib")}")',
            f'set(CMAKE_LINKER "{tool("ld")}")',
            f'set(CMAKE_NM "{tool("nm")}")',
            f'set(CMAKE_OBJCOPY "{tool("objcopy")}")',
            f'set(CMAKE_STRIP "{tool("strip")}")',
            f'list(PREPEND CMAKE_LIBRARY_PATH "{sysroot_lib_dir}")',
            "set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)",
            "set(CMAKE_C_STANDARD 17)",
            "set(CMAKE_CXX_STANDARD 17)",
            "set(CMAKE_CXX_STANDARD_REQUIRED ON)",
            "",
        ]
    )


def ament_prefix_dirs(packages_staging_dir, depends):
    prefixes = []
    staging_root = Path(packages_staging_dir)
    for name in depends:
        staged = staging_root / name
        usr = staged / "usr"
        if usr.is_dir():
            if usr not in prefixes:
                prefixes.append(usr)
        elif staged.is_dir():
            if staged not in prefixes:
                prefixes.append(staged)
    return tuple(prefixes)


def join_prefix_path(directories):
    return ";".join(str(path) for path in directories)


def ament_python_paths(prefix_dirs):
    paths = []
    for prefix in prefix_dirs:
        root = Path(prefix)
        for candidate in (
            *sorted(root.glob("lib/python*/site-packages")),
            *sorted(root.glob("local/lib/python*/site-packages")),
        ):
            if candidate.is_dir() and candidate not in paths:
                paths.append(candidate)
    return tuple(paths)


def ament_cmake_commands(
    cmake,
    source_dir,
    build_dir,
    toolchain_file,
    install_prefix,
    prefix_path,
    testing,
    cmake_args=(),
    host_sdk_dir=None,
    python_executable=None,
    linkage="shared",
    link_prefix_path=None,
):
    if linkage not in LINKAGE_VALUES:
        raise SmartBuildError("PACKAGE", f"unsupported ament linkage: {linkage}")
    prefix_dirs = list(prefix_path)
    if host_sdk_dir is not None:
        prefix_dirs = [Path(host_sdk_dir), *prefix_dirs]
    configure = [
        str(cmake),
        "-S",
        str(source_dir),
        "-B",
        str(build_dir),
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}",
        f"-DCMAKE_INSTALL_PREFIX={install_prefix}",
        f"-DBUILD_TESTING={'ON' if testing else 'OFF'}",
        "-DCMAKE_INSTALL_LIBDIR=lib",
        "-DCMAKE_PREFIX_PATH=" + join_prefix_path(prefix_dirs),
        "-DAMENT_CMAKE_UNINSTALL_TARGET=OFF",
    ]
    if linkage == "shared":
        configure.append("-DBUILD_SHARED_LIBS=ON")
    elif linkage == "static":
        configure.append("-DBUILD_SHARED_LIBS=OFF")
    link_prefix_dirs = prefix_path if link_prefix_path is None else link_prefix_path
    link_dirs = [Path(prefix) / "lib" for prefix in link_prefix_dirs]
    link_dirs = [path for path in link_dirs if path.is_dir()]
    if link_dirs:
        rpath_link = "-Wl,-rpath-link," + ":".join(str(path) for path in link_dirs)
        configure.extend(
            [
                f"-DCMAKE_EXE_LINKER_FLAGS={rpath_link}",
                f"-DCMAKE_SHARED_LINKER_FLAGS={rpath_link}",
                f"-DCMAKE_MODULE_LINKER_FLAGS={rpath_link}",
            ]
        )
    if python_executable is not None:
        configure.extend(
            [
                f"-DPython3_EXECUTABLE={python_executable}",
                f"-DPYTHON_EXECUTABLE={python_executable}",
            ]
        )
    configure.extend(tuple(cmake_args))
    return (
        tuple(configure),
        (str(cmake), "--build", str(build_dir), "--parallel"),
        (str(cmake), "--install", str(build_dir)),
    )


def _output_paths(description, value, label):
    if not isinstance(value, list) or not value:
        raise SmartBuildError(
            "PACKAGE", f"{description.path}: {label} must be a non-empty list"
        )
    result = []
    for raw_path in value:
        if not isinstance(raw_path, str) or not raw_path:
            raise SmartBuildError(
                "PACKAGE",
                f"{description.path}: {label} entries must be non-empty strings",
            )
        path = PurePosixPath(raw_path)
        if not path.is_absolute():
            raise SmartBuildError(
                "PACKAGE",
                f"{description.path}: {label} path must be absolute: {raw_path}",
            )
        relative = PurePosixPath(*path.parts[1:])
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise SmartBuildError("PACKAGE", f"{description.path}: unsafe {label} path: {raw_path}")
        if relative in result:
            raise SmartBuildError(
                "PACKAGE", f"{description.path}: duplicate {label} path: {raw_path}"
            )
        result.append(relative)
    return tuple(result)


def _cmake_args(description, value):
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SmartBuildError(
            "PACKAGE", f"{description.path}: build.ament_cmake.cmake_args must be a string list"
        )
    protected = [
        item
        for item in value
        if any(item.startswith(prefix) for prefix in PROTECTED_CMAKE_ARGS)
    ]
    if protected:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.ament_cmake.cmake_args cannot override protected argument(s): "
            + ", ".join(protected),
        )
    return tuple(value)


def ament_python_executable(host_sdk_dir):
    candidate = Path(host_sdk_dir) / "venv" / "bin" / "python"
    if not candidate.is_file():
        raise SmartBuildError("BUILD", f"ROS 2 Host SDK Python not found: {candidate}")
    return candidate


def _cmake_processor(toolchain):
    target = str(getattr(toolchain, "target", "")).lower()
    if "riscv64" in target:
        return "riscv64"
    if "aarch64" in target or "arm64" in target:
        return "aarch64"
    if "arm" in target:
        return "arm"
    return "unknown"
