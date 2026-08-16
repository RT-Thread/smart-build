#!/usr/bin/env python3
"""Install Jazzy ament CMake modules and rosidl generators on the build host."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path


AMENT_CMAKE_PACKAGES = (
    "ament_cmake_core",
    "ament_cmake_python",
    "ament_cmake_include_directories",
    "ament_cmake_libraries",
    "ament_cmake_export_definitions",
    "ament_cmake_export_include_directories",
    "ament_cmake_export_interfaces",
    "ament_cmake_export_libraries",
    "ament_cmake_export_link_flags",
    "ament_cmake_export_targets",
    "ament_cmake_export_dependencies",
    "ament_cmake_vendor_package",
    "ament_cmake_gmock",
    "ament_cmake_gtest",
    "ament_cmake_target_dependencies",
    "ament_cmake_test",
    "ament_cmake_pytest",
    "ament_cmake_version",
    "ament_cmake_gen_version_h",
    "ament_cmake",
)

ROSIDL_PACKAGES = (
    "rosidl_cli",
    "rosidl_adapter",
    "rosidl_parser",
    "rosidl_pycommon",
    "rosidl_cmake",
    "rosidl_typesupport_interface",
    "rosidl_generator_type_description",
    "rosidl_generator_c",
    "rosidl_generator_cpp",
)


def required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def host_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "CC",
        "CXX",
        "LD",
        "AR",
        "AS",
        "NM",
        "RANLIB",
        "STRIP",
        "OBJCOPY",
        "CFLAGS",
        "CXXFLAGS",
        "LDFLAGS",
    ):
        env.pop(key, None)
    return env


def machine_paths() -> tuple[Path, Path, Path]:
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    machine_dir = stage_dir.parents[2]
    sdk_dir = machine_dir / "host" / "ros2-sdk"
    downloads = machine_dir.parents[1] / "downloads" / "ros2-host-sdk"
    downloads.mkdir(parents=True, exist_ok=True)
    return machine_dir, sdk_dir, downloads


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_archive(item: dict, downloads: Path) -> Path:
    destination = downloads / item["archive"]
    expected = item["sha256"]
    if destination.is_file() and expected != "PENDING" and sha256_file(destination) == expected:
        return destination
    print(f"GET {item['url']}", flush=True)
    with urllib.request.urlopen(item["url"], timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    digest = sha256_file(destination)
    if expected != "PENDING" and digest != expected:
        destination.unlink(missing_ok=True)
        raise SystemExit(f"{item['archive']} sha256 mismatch: {digest} != {expected}")
    print(f"{digest}  {destination}", flush=True)
    return destination


def extract_archive(archive: Path, destination: Path) -> Path:
    reset_dir(destination)
    with tarfile.open(archive) as tar:
        tar.extractall(destination)
    children = [path for path in destination.iterdir() if path.is_dir()]
    if len(children) == 1:
        return children[0]
    return destination


def pip_install(python: Path, *args: str, env: dict[str, str]) -> None:
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--index-url",
            os.environ.get("SMART_BUILD_PYPI_INDEX", "https://pypi.org/simple"),
            "--timeout",
            "30",
            "--retries",
            "3",
            *args,
        ],
        env=env,
    )


def cmake_install(source: Path, work_dir: Path, prefix: Path, env: dict[str, str], extra: list[str] | None = None) -> None:
    build_dir = work_dir / "cmake" / source.name
    reset_dir(build_dir)
    command = [
        "cmake",
        "-S",
        str(source),
        "-B",
        str(build_dir),
        f"-DCMAKE_INSTALL_PREFIX={prefix}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_TESTING=OFF",
        "-DAMENT_CMAKE_UNINSTALL_TARGET=OFF",
        f"-DPython3_EXECUTABLE={env['VIRTUAL_ENV']}/bin/python",
        f"-DPYTHON_EXECUTABLE={env['VIRTUAL_ENV']}/bin/python",
        f"-DCMAKE_PREFIX_PATH={prefix}",
    ]
    if extra:
        command.extend(extra)
    run(command, env=env)
    run(["cmake", "--build", str(build_dir), "--parallel"], env=env)
    run(["cmake", "--install", str(build_dir)], env=env)


def install_python_tree(source: Path, python: Path, env: dict[str, str]) -> None:
    if (source / "setup.py").is_file() or (source / "pyproject.toml").is_file():
        pip_install(python, "--no-deps", str(source), env=env)
        return
    raise SystemExit(f"no Python project in {source}")


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    _, sdk_dir, downloads = machine_paths()
    sources = json.loads((source_dir / "sources.json").read_text(encoding="utf-8"))
    env = host_env()
    extracted = work_dir / "src"
    venv_dir = sdk_dir / "venv"

    reset_dir(work_dir / "src")
    reset_dir(sdk_dir)
    reset_dir(stage_dir)

    trees = {}
    for item in sources["archives"]:
        archive = fetch_archive(item, downloads)
        trees[item["name"]] = extract_archive(archive, extracted / item["name"])

    run(["python3", "-m", "venv", "--system-site-packages", str(venv_dir)], env=env)
    python = venv_dir / "bin" / "python"
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PATH"] = f"{venv_dir / 'bin'}:{env.get('PATH', '')}"
    env["AMENT_PREFIX_PATH"] = str(sdk_dir)
    env["CMAKE_PREFIX_PATH"] = str(sdk_dir)
    pip_install(python, "--no-deps", *sources["python_packages"], env=env)

    install_python_tree(trees["ament_package"], python, env)
    for name in AMENT_CMAKE_PACKAGES:
        cmake_install(trees["ament_cmake"] / name, work_dir, sdk_dir, env)

    ament_index_python = trees["ament_index"] / "ament_index_python"
    if ament_index_python.is_dir():
        install_python_tree(ament_index_python, python, env)

    ros_root = trees["ament_cmake_ros"]
    domain_coordinator = ros_root / "domain_coordinator"
    if domain_coordinator.is_dir():
        install_python_tree(domain_coordinator, python, env)
    for name in ("ament_cmake_ros_core", "ament_cmake_ros"):
        candidate = ros_root / name
        if candidate.is_dir():
            cmake_install(candidate, work_dir, sdk_dir, env)
        elif name == "ament_cmake_ros" and (ros_root / "CMakeLists.txt").is_file():
            cmake_install(ros_root, work_dir, sdk_dir, env)

    if "osrf_pycommon" in trees:
        install_python_tree(trees["osrf_pycommon"], python, env)

    rosidl_root = trees["rosidl"]
    for name in ROSIDL_PACKAGES:
        candidate = rosidl_root / name
        if candidate.is_dir():
            if (candidate / "CMakeLists.txt").is_file():
                cmake_install(candidate, work_dir, sdk_dir, env)
            elif (candidate / "setup.py").is_file() or (candidate / "pyproject.toml").is_file():
                install_python_tree(candidate, python, env)

    defaults_root = trees["rosidl_defaults"]
    for name in ("rosidl_default_generators",):
        candidate = defaults_root / name
        if candidate.is_dir():
            cmake_install(candidate, work_dir, sdk_dir, env)

    for name in ("rosidl_core_generators", "rosidl_core_runtime"):
        candidate = trees[name]
        if candidate.is_dir() and (candidate / "CMakeLists.txt").is_file():
            cmake_install(candidate, work_dir, sdk_dir, env)

    rmw_root = trees["rmw"]
    rmw_implementation_cmake = rmw_root / "rmw_implementation_cmake"
    if rmw_implementation_cmake.is_dir():
        cmake_install(rmw_implementation_cmake, work_dir, sdk_dir, env)

    marker = stage_dir / "usr" / "share" / "ros2-host-sdk"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("jazzy-2.5.5\n", encoding="utf-8")
    (sdk_dir / "VERSION").write_text("jazzy-2.5.5\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
