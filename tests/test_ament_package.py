from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

from smart_build.ament_package import (
    ament_cmake_commands,
    ament_python_executable,
    ament_prefix_dirs,
    ament_python_paths,
    ament_toolchain_text,
    parse_ament_cmake_build,
)
from smart_build.descriptions import load_description
from smart_build.domains import package as package_domain
from smart_build.errors import SmartBuildError


def _write_ament_package(directory, extra=""):
    directory.mkdir(parents=True)
    (directory / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: rcutils\nversion: '6.7.2'\n"
        "type: library\ncategory: ROS 2\n"
        "description: ROS 2 C utilities\n"
        "source:\n  type: archive\n  url: https://example.invalid/rcutils.tar.gz\n"
        "  archive: rcutils.tar.gz\n  sha256: "
        + ("ab" * 32)
        + "\n  strip_root: true\n"
        "build:\n  ament_cmake:\n    testing: false\n    outputs:\n"
        "      - /usr/lib\n      - /usr/include\n      - /usr/share\n"
        f"{extra}",
        encoding="utf-8",
    )
    return directory / "package.yaml"


def test_parse_ament_cmake_build_reads_outputs_and_args(tmp_path):
    path = _write_ament_package(
        tmp_path / "packages" / "ros2" / "rcutils",
        extra="    cmake_args:\n      - -DCMAKE_BUILD_TYPE=Release\n",
    )
    parsed = parse_ament_cmake_build(load_description(path))
    assert parsed.testing is False
    assert [path.as_posix() for path in parsed.outputs] == ["usr/lib", "usr/include", "usr/share"]
    assert parsed.cmake_args == ("-DCMAKE_BUILD_TYPE=Release",)
    assert parsed.linkage == "shared"
    assert parsed.host_python == "sdk"


def test_parse_ament_cmake_build_rejects_protected_cmake_args(tmp_path):
    path = _write_ament_package(
        tmp_path / "packages" / "ros2" / "rcutils",
        extra="    cmake_args:\n      - -DCMAKE_PREFIX_PATH=/tmp/override\n",
    )
    with pytest.raises(SmartBuildError, match="cannot override protected"):
        parse_ament_cmake_build(load_description(path))


def test_parse_ament_cmake_build_reads_linkage_and_host_python(tmp_path):
    path = _write_ament_package(
        tmp_path / "packages" / "ros2" / "rcutils",
        extra="    linkage: static\n    host_python: system\n",
    )
    parsed = parse_ament_cmake_build(load_description(path))
    assert parsed.linkage == "static"
    assert parsed.host_python == "system"


def test_parse_ament_cmake_build_rejects_relative_outputs(tmp_path):
    path = _write_ament_package(tmp_path / "packages" / "ros2" / "rcutils")
    text = path.read_text(encoding="utf-8").replace("- /usr/lib", "- usr/lib")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SmartBuildError, match="must be absolute"):
        parse_ament_cmake_build(load_description(path))


def test_ament_toolchain_text_marks_unix_and_target(tmp_path):
    toolchain = SimpleNamespace(
        target="aarch64-linux-musleabi",
        prefix="aarch64-linux-musleabi-",
        gcc=tmp_path / "aarch64-linux-musleabi-gcc",
        gxx=tmp_path / "aarch64-linux-musleabi-g++",
        bin_dir=tmp_path,
        sysroot_lib_dir=tmp_path / "sysroot" / "lib",
    )
    text = ament_toolchain_text(toolchain)
    assert "set(CMAKE_SYSTEM_NAME Linux)" in text
    assert "set(CMAKE_SYSTEM_PROCESSOR aarch64)" in text
    assert "set(UNIX TRUE)" in text
    assert f'list(PREPEND CMAKE_LIBRARY_PATH "{tmp_path / "sysroot" / "lib"}")' in text
    assert "CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY" in text


def test_ament_prefix_dirs_prefer_usr_install_root(tmp_path):
    staging = tmp_path / "packages"
    (staging / "tinyxml2" / "usr" / "lib").mkdir(parents=True)
    (staging / "empty").mkdir()
    prefixes = ament_prefix_dirs(staging, ("tinyxml2", "missing", "empty"))
    assert prefixes == (staging / "tinyxml2" / "usr", staging / "empty")


def test_ament_cmake_commands_disable_testing_and_set_prefix(tmp_path):
    dependency_prefix = tmp_path / "dep" / "usr"
    (dependency_prefix / "lib").mkdir(parents=True)
    configure, build, install = ament_cmake_commands(
        "/usr/bin/cmake",
        tmp_path / "src",
        tmp_path / "build",
        tmp_path / "toolchain.cmake",
        "/usr",
        (dependency_prefix,),
        testing=False,
        cmake_args=("-DCMAKE_BUILD_TYPE=Release",),
        host_sdk_dir=tmp_path / "host" / "ros2-sdk",
    )
    assert configure[0] == "/usr/bin/cmake"
    assert "-DBUILD_TESTING=OFF" in configure
    assert "-DBUILD_SHARED_LIBS=ON" in configure
    assert "-DCMAKE_INSTALL_PREFIX=/usr" in configure
    prefix = next(item for item in configure if item.startswith("-DCMAKE_PREFIX_PATH="))
    assert str(tmp_path / "host" / "ros2-sdk") in prefix
    assert str(tmp_path / "dep" / "usr") in prefix
    assert ";" in prefix
    linker_flags = [item for item in configure if "_LINKER_FLAGS=" in item]
    assert len(linker_flags) == 3
    assert all(str(dependency_prefix / "lib") in item for item in linker_flags)
    assert all(str(tmp_path / "host" / "ros2-sdk") not in item for item in linker_flags)
    assert build[1] == "--build"
    assert install[1] == "--install"


def test_ament_cmake_commands_support_static_and_mixed_linkage(tmp_path):
    static, _, _ = ament_cmake_commands(
        "/usr/bin/cmake",
        tmp_path / "src",
        tmp_path / "build",
        tmp_path / "toolchain.cmake",
        "/usr",
        (),
        testing=False,
        linkage="static",
    )
    mixed, _, _ = ament_cmake_commands(
        "/usr/bin/cmake",
        tmp_path / "src",
        tmp_path / "build-mixed",
        tmp_path / "toolchain.cmake",
        "/usr",
        (),
        testing=False,
        linkage="mixed",
    )
    assert "-DBUILD_SHARED_LIBS=OFF" in static
    assert not any(item.startswith("-DBUILD_SHARED_LIBS=") for item in mixed)


def test_ament_python_paths_collects_site_packages(tmp_path):
    sdk = tmp_path / "host" / "ros2-sdk"
    site = sdk / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    assert ament_python_paths((sdk,)) == (site,)


def test_ament_python_executable_uses_host_sdk_venv(tmp_path):
    python = tmp_path / "host" / "ros2-sdk" / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    assert ament_python_executable(python.parents[2]) == python


def test_ament_python_executable_rejects_missing_sdk_python(tmp_path):
    with pytest.raises(SmartBuildError, match="Host SDK Python not found"):
        ament_python_executable(tmp_path / "host" / "ros2-sdk")


def test_ament_architecture_checks_scan_installed_file_content(tmp_path, monkeypatch):
    elf_library = tmp_path / "usr" / "lib" / "libexample.so"
    elf_executable = tmp_path / "usr" / "lib" / "demo_nodes_cpp" / "talker"
    archive = tmp_path / "usr" / "lib" / "libexample.a"
    package_xml = tmp_path / "usr" / "share" / "example" / "package.xml"
    for path, content in (
        (elf_library, b"\x7fELF" + b"\0" * 12),
        (elf_executable, b"\x7fELF" + b"\0" * 12),
        (archive, b"!<arch>\n"),
        (package_xml, b"<package/>\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    binary_paths = []
    archive_paths = []
    monkeypatch.setattr(
        package_domain,
        "_verify_binary_architecture",
        lambda _toolchain, path, *_args: binary_paths.append(path) or {"status": "verified"},
    )
    monkeypatch.setattr(
        package_domain,
        "_verify_static_archive_architecture",
        lambda _toolchain, path, *_args: archive_paths.append(path) or {"status": "verified"},
    )

    install_files = [
        {"source": str(path), "path": f"/{path.relative_to(tmp_path).as_posix()}"}
        for path in (elf_library, elf_executable, archive, package_xml)
    ]
    result = package_domain._verify_ament_install_architectures(
        SimpleNamespace(), install_files, None, tmp_path, {}, None
    )

    assert result["status"] == "verified"
    assert result["artifact_count"] == 3
    assert binary_paths == [elf_library, elf_executable]
    assert archive_paths == [archive]
    assert [check["install_path"] for check in result["checks"]] == [
        "/usr/lib/libexample.so",
        "/usr/lib/demo_nodes_cpp/talker",
        "/usr/lib/libexample.a",
    ]


def test_ament_architecture_checks_skip_data_only_package(tmp_path):
    package_xml = tmp_path / "package.xml"
    package_xml.write_text("<package/>\n", encoding="utf-8")

    result = package_domain._verify_ament_install_architectures(
        SimpleNamespace(),
        [{"source": str(package_xml), "path": "/usr/share/example/package.xml"}],
        None,
        tmp_path,
        {},
        None,
    )

    assert result == {"status": "skipped", "reason": "no ELF files or static archives"}


def test_ament_cache_inputs_include_command_and_executor_modules():
    assert {path.name for path in package_domain.AMENT_BACKEND_SOURCES} == {
        "ament_package.py",
        "package.py",
    }


def test_ament_install_files_preserve_executable_mode_outside_bin(tmp_path):
    executable = tmp_path / "stage" / "usr" / "lib" / "demo_nodes_cpp" / "talker"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"\x7fELF" + b"\0" * 12)
    executable.chmod(0o755)

    files = package_domain._python_install_files(
        tmp_path / "stage",
        [PurePosixPath("usr/lib")],
    )

    talker = next(item for item in files if item["path"] == "/usr/lib/demo_nodes_cpp/talker")
    assert talker["mode"] == 0o755
