import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .errors import SmartBuildError


CMAKE_MODES = ("static", "dynamic", "mixed")
RESERVED_OPTION_PREFIXES = (
    "-S",
    "-B",
    "--build",
    "--install",
    "-DCMAKE_TOOLCHAIN_FILE",
    "-DCMAKE_INSTALL_PREFIX",
    "-DSMART_BUILD_LINKAGE",
)
INTERPRETER_RE = re.compile(r"Requesting program interpreter:\s*([^\]]+)\]")
NEEDED_RE = re.compile(r"\(NEEDED\).*Shared library:\s*\[([^\]]+)\]")


@dataclass(frozen=True)
class CMakeOutput:
    path: PurePosixPath
    linkage: str


@dataclass(frozen=True)
class CMakeBuildConfig:
    outputs: dict[str, tuple[CMakeOutput, ...]]
    options: tuple[str, ...]


def parse_cmake_build(description):
    build = description.data.get("build")
    cmake = build.get("cmake") if isinstance(build, dict) else None
    if not isinstance(cmake, dict):
        raise SmartBuildError(
            "PACKAGE", f"{description.path}: build.cmake must be a mapping"
        )
    raw_outputs = cmake.get("outputs")
    if not isinstance(raw_outputs, dict):
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.cmake.outputs must be a mapping",
        )

    parsed_paths = {
        mode: _output_paths(
            description, raw_outputs.get(mode), f"build.cmake.outputs.{mode}"
        )
        for mode in CMAKE_MODES
    }
    static_paths = set(parsed_paths["static"])
    dynamic_paths = set(parsed_paths["dynamic"])
    overlap = sorted(static_paths & dynamic_paths, key=str)
    if overlap:
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: CMake output appears in both static and dynamic modes: {overlap[0]}",
        )

    linkage = {path: "static" for path in static_paths}
    linkage.update({path: "dynamic" for path in dynamic_paths})
    for path in parsed_paths["mixed"]:
        if path not in linkage:
            raise SmartBuildError(
                "PACKAGE",
                f"{description.path}: mixed output must also appear in static or dynamic outputs: {path}",
            )

    options = _options(description, cmake.get("options", []))
    outputs = {
        mode: tuple(CMakeOutput(path=path, linkage=linkage[path]) for path in paths)
        for mode, paths in parsed_paths.items()
    }
    return CMakeBuildConfig(outputs=outputs, options=options)


def select_cmake_outputs(config, mode):
    if mode not in CMAKE_MODES:
        raise SmartBuildError("PACKAGE", f"unsupported CMake linkage mode: {mode}")
    return config.outputs[mode]


def cmake_toolchain_text(toolchain):
    processor = _cmake_processor(toolchain)

    def tool(name):
        return toolchain.bin_dir / f"{toolchain.prefix}{name}"

    cxx = getattr(toolchain, "gxx", tool("g++"))
    lines = [
        "set(CMAKE_SYSTEM_NAME Generic)",
        f"set(CMAKE_SYSTEM_PROCESSOR {processor})",
        f'set(CMAKE_C_COMPILER "{toolchain.gcc}")',
        f'set(CMAKE_CXX_COMPILER "{cxx}")',
        f'set(CMAKE_LINKER "{tool("ld")}")',
        f'set(CMAKE_NM "{tool("nm")}")',
        f'set(CMAKE_AR "{tool("ar")}")',
        f'set(CMAKE_RANLIB "{tool("ranlib")}")',
        f'set(CMAKE_STRIP "{tool("strip")}")',
        f'set(CMAKE_OBJCOPY "{tool("objcopy")}")',
        "set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)",
        "",
    ]
    return "\n".join(lines)


def cmake_commands(
    cmake,
    source_dir,
    build_dir,
    toolchain_file,
    linkage_mode,
    options=(),
):
    if linkage_mode not in CMAKE_MODES:
        raise SmartBuildError(
            "PACKAGE", f"unsupported CMake linkage mode: {linkage_mode}"
        )
    return (
        (
            str(cmake),
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}",
            "-DCMAKE_INSTALL_PREFIX=/",
            f"-DSMART_BUILD_LINKAGE={linkage_mode}",
            *tuple(options),
        ),
        (str(cmake), "--build", str(build_dir), "--parallel"),
        (str(cmake), "--install", str(build_dir)),
    )


def parse_readelf_linkage(program_headers, dynamic_section):
    program_text = str(program_headers)
    dynamic_text = str(dynamic_section)
    program_recognized = (
        "Program Headers:" in program_text or "Elf file type is" in program_text
    )
    dynamic_recognized = (
        "Dynamic section" in dynamic_text
        or "There is no dynamic section" in dynamic_text
        or "NEEDED" in dynamic_text
    )
    if not program_recognized or not dynamic_recognized:
        raise SmartBuildError("BUILD", "cannot parse readelf linkage output")

    interpreter_match = INTERPRETER_RE.search(program_text)
    interpreter = interpreter_match.group(1).strip() if interpreter_match else None
    needed = NEEDED_RE.findall(dynamic_text)
    return {
        "interpreter": interpreter,
        "needed": needed,
        "linkage": "dynamic" if interpreter or needed else "static",
    }


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
        if not relative.parts or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise SmartBuildError(
                "PACKAGE", f"{description.path}: unsafe {label} path: {raw_path}"
            )
        if relative in result:
            raise SmartBuildError(
                "PACKAGE",
                f"{description.path}: duplicate {label} path: {raw_path}",
            )
        result.append(relative)
    return tuple(result)


def _options(description, value):
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise SmartBuildError(
            "PACKAGE",
            f"{description.path}: build.cmake.options must be a string list",
        )
    for option in value:
        if option.startswith(RESERVED_OPTION_PREFIXES):
            raise SmartBuildError(
                "PACKAGE", f"{description.path}: reserved CMake option: {option}"
            )
    return tuple(value)


def _cmake_processor(toolchain):
    target = str(getattr(toolchain, "target", "")).lower()
    if "riscv64" in target:
        return "riscv64"
    if "aarch64" in target or "arm64" in target:
        return "aarch64"
    if "arm" in target:
        return "arm"
    raise SmartBuildError(
        "PACKAGE", f"unsupported CMake target processor: {target or '<empty>'}"
    )
