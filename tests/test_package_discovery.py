import pytest

from smart_build.descriptions import load_description
from smart_build.errors import SmartBuildError
from smart_build.package_categories import package_category
from smart_build.package_kconfig import generate_package_kconfig_files, generate_package_kconfig_index
from smart_build.package_metadata import (
    is_host_package_path,
    load_all_package_metadata,
    normalize_package_metadata,
    package_description_path,
    package_description_paths,
    package_kconfig_relative,
)


def _write_package(directory, name, description="Example package"):
    directory.mkdir(parents=True)
    (directory / "package.yaml").write_text(
        "schema_version: 1\nkind: package\n"
        f"name: {name}\nversion: '1.0'\n"
        "type: library\n"
        f"description: {description}\n"
        "source:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/lib/libexample.a]\n"
        "install:\n  libraries: [usr/lib/libexample.a]\n",
        encoding="utf-8",
    )
    (directory / "sbuild.py").write_text("", encoding="utf-8")
    return directory / "package.yaml"


def test_package_description_paths_include_ros2_and_host_groups(tmp_path):
    _write_package(tmp_path / "packages" / "tinyxml2", "tinyxml2", "TinyXML2 XML parser")
    _write_package(tmp_path / "packages" / "ros2" / "rcutils", "rcutils", "ROS 2 C utilities")
    _write_package(tmp_path / "packages" / "host" / "ros2-host-sdk", "ros2-host-sdk", "ROS 2 host SDK")
    (tmp_path / "packages" / "ros2").mkdir(exist_ok=True)

    paths = package_description_paths(tmp_path)
    names = [path.parent.name for path in paths]
    assert names == ["ros2-host-sdk", "rcutils", "tinyxml2"]
    assert (tmp_path / "packages" / "ros2").is_dir()
    assert tmp_path / "packages" / "ros2" / "package.yaml" not in paths


def test_package_description_path_resolves_group_directories(tmp_path):
    _write_package(tmp_path / "packages" / "tinyxml2", "tinyxml2")
    _write_package(tmp_path / "packages" / "ros2" / "rcutils", "rcutils")
    _write_package(tmp_path / "packages" / "host" / "ros2-host-sdk", "ros2-host-sdk")

    assert package_description_path(tmp_path, "tinyxml2") == tmp_path / "packages" / "tinyxml2" / "package.yaml"
    assert package_description_path(tmp_path, "rcutils") == tmp_path / "packages" / "ros2" / "rcutils" / "package.yaml"
    assert (
        package_description_path(tmp_path, "ros2-host-sdk")
        == tmp_path / "packages" / "host" / "ros2-host-sdk" / "package.yaml"
    )


def test_duplicate_package_name_across_groups_is_rejected(tmp_path):
    _write_package(tmp_path / "packages" / "rcutils", "rcutils")
    _write_package(tmp_path / "packages" / "ros2" / "rcutils", "rcutils")

    with pytest.raises(SmartBuildError, match="duplicate package description for rcutils"):
        package_description_path(tmp_path, "rcutils")


def test_grouped_packages_generate_kconfig_at_real_paths(tmp_path):
    _write_package(tmp_path / "packages" / "ros2" / "rcutils", "rcutils", "ROS 2 C utilities")
    _write_package(tmp_path / "packages" / "host" / "ros2-host-sdk", "ros2-host-sdk", "ROS 2 host SDK")

    generated = generate_package_kconfig_files(tmp_path)
    assert "packages/ros2/rcutils/Kconfig" in generated
    assert "packages/host/ros2-host-sdk/Kconfig" in generated
    index = generate_package_kconfig_index(tmp_path)
    assert 'source "packages/ros2/rcutils/Kconfig"' in index
    assert 'source "packages/host/ros2-host-sdk/Kconfig"' in index
    assert 'menu "ROS 2"' in index
    assert 'menu "Host tools"' in index


def test_host_and_ros2_path_helpers(tmp_path):
    host = _write_package(tmp_path / "packages" / "host" / "ros2-host-sdk", "ros2-host-sdk")
    ros2 = _write_package(tmp_path / "packages" / "ros2" / "rcutils", "rcutils")
    top = _write_package(tmp_path / "packages" / "tinyxml2", "tinyxml2")

    assert is_host_package_path(host) is True
    assert is_host_package_path(ros2) is False
    assert is_host_package_path(top) is False

    host_meta = normalize_package_metadata(load_description(host))
    ros2_meta = normalize_package_metadata(load_description(ros2))
    top_meta = normalize_package_metadata(load_description(top))
    assert package_category(host_meta) == "Host tools"
    assert package_category(ros2_meta) == "ROS 2"
    assert package_kconfig_relative(tmp_path, host_meta) == "packages/host/ros2-host-sdk/Kconfig"


def test_load_all_package_metadata_reads_grouped_packages(tmp_path):
    _write_package(tmp_path / "packages" / "tinyxml2", "tinyxml2")
    _write_package(tmp_path / "packages" / "ros2" / "rcutils", "rcutils")
    names = {package.name for package in load_all_package_metadata(tmp_path)}
    assert names == {"tinyxml2", "rcutils"}
