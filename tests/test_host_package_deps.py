from types import SimpleNamespace

from smart_build.descriptions import load_description
from smart_build.package_metadata import normalize_package_metadata
from smart_build.tasks import _package_dependency_closure, _package_dependency_task_ids


def test_host_dependencies_use_package_build_tasks():
    package = SimpleNamespace(
        name="rcutils",
        metadata=SimpleNamespace(
            depends=("tinyxml2",),
            host_depends=("ros2-host-sdk",),
            selects=(),
            provides=("rcutils",),
        ),
    )
    ids = _package_dependency_task_ids(
        package,
        {"rcutils", "ros2-host-sdk", "tinyxml2"},
        {},
        {"ros2-host-sdk"},
    )
    assert ids == ["package:ros2-host-sdk:build", "ipkg:tinyxml2:package"]


def test_host_and_target_prefixes_include_the_complete_dependency_closure():
    root = SimpleNamespace(
        name="rclcpp",
        metadata=SimpleNamespace(
            depends=("rcl",),
            host_depends=("ros2-host-sdk",),
            selects=(),
            provides=("rclcpp",),
        ),
    )
    rcl = SimpleNamespace(
        name="rcl",
        metadata=SimpleNamespace(
            depends=("rcutils",),
            host_depends=(),
            selects=(),
            provides=("rcl",),
        ),
    )
    rcutils = SimpleNamespace(
        name="rcutils",
        metadata=SimpleNamespace(
            depends=(),
            host_depends=("ros2-host-sdk",),
            selects=(),
            provides=("rcutils",),
        ),
    )
    sdk = SimpleNamespace(
        name="ros2-host-sdk",
        metadata=SimpleNamespace(
            depends=(),
            host_depends=(),
            selects=(),
            provides=("ros2-host-sdk",),
        ),
    )

    assert _package_dependency_closure(root, (root, rcl, rcutils, sdk)) == (
        "ros2-host-sdk",
        "rcl",
        "rcutils",
    )


def test_host_depends_accepts_a_comma_separated_string(tmp_path):
    path = tmp_path / "package.yaml"
    path.write_text(
        "schema_version: 1\nkind: package\nname: rcutils\nversion: '1.0'\n"
        "host_depends: ros2-host-sdk, rosidl-generator-c\n",
        encoding="utf-8",
    )
    metadata = normalize_package_metadata(load_description(path))
    assert metadata.host_depends == ("ros2-host-sdk", "rosidl-generator-c")
