from pathlib import Path

import pytest

from smart_build.descriptions import load_description
from smart_build.errors import SmartBuildError
from smart_build.package_categories import OTHER_CATEGORY, PACKAGE_CATEGORIES, grouped_packages
from smart_build.package_kconfig import generate_package_kconfig_files, generate_package_kconfig_index
from smart_build.package_metadata import (
    DESCRIPTION_MAX_LENGTH,
    load_all_package_metadata,
    normalize_package_metadata,
    package_kconfig_relative,
    shorten_package_description,
)


def test_generated_package_kconfig_uses_description_as_prompt_and_help(tmp_path):
    package_dir = tmp_path / "packages" / "nano"
    package_dir.mkdir(parents=True)
    (package_dir / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: nano\nversion: '9.0'\n"
        "type: executable\ndescription: GNU nano terminal text editor\n"
        "source:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/bin/nano]\n"
        "install:\n  path: /usr/bin/nano\n",
        encoding="utf-8",
    )
    (package_dir / "sbuild.py").write_text("", encoding="utf-8")

    generated = generate_package_kconfig_files(tmp_path)
    content = generated["packages/nano/Kconfig"]

    assert 'menu "nano - GNU nano terminal text editor"' in content
    assert 'bool "nano - GNU nano terminal text editor"' in content
    assert "    help" in content
    assert "      GNU nano terminal text editor" in content


def test_generated_package_kconfig_selects_dependencies(tmp_path):
    packages = tmp_path / "packages"
    (packages / "ncurses").mkdir(parents=True)
    (packages / "ncurses" / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: ncurses\nversion: '6.6'\n"
        "type: library\ndescription: Terminal handling library\n"
        "source:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/lib/libncurses.a]\n"
        "install:\n  libraries: [usr/lib/libncurses.a]\n",
        encoding="utf-8",
    )
    (packages / "dialog").mkdir()
    (packages / "dialog" / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: dialog\nversion: '1.3'\n"
        "type: executable\ndescription: dialog script-driven curses widgets\n"
        "depends:\n- ncurses\n"
        "source:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/bin/dialog]\n"
        "install:\n  path: /usr/bin/dialog\n",
        encoding="utf-8",
    )
    (packages / "ncurses" / "sbuild.py").write_text("", encoding="utf-8")
    (packages / "dialog" / "sbuild.py").write_text("", encoding="utf-8")

    content = generate_package_kconfig_files(tmp_path)["packages/dialog/Kconfig"]

    assert "    select PACKAGE_NCURSES" in content
    assert "    depends on PACKAGE_NCURSES" not in content


def test_generated_package_kconfig_selects_host_dependencies(tmp_path):
    packages = tmp_path / "packages"
    for name in ("ros2-host-sdk", "rcutils"):
        (packages / name).mkdir(parents=True)
    (packages / "ros2-host-sdk" / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: ros2-host-sdk\nversion: '1.0'\n"
        "type: library\ndescription: Host ROS 2 SDK\nsource:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/share/ros2-host-sdk]\n"
        "install:\n  headers: [usr/share/ros2-host-sdk]\n",
        encoding="utf-8",
    )
    (packages / "rcutils" / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: rcutils\nversion: '1.0'\n"
        "type: library\ndescription: ROS 2 C utilities\nhost_depends: [ros2-host-sdk]\n"
        "source:\n  directory: apps/hello\n"
        "build:\n  ament_cmake:\n    outputs: [/usr/lib, /usr/include, /usr/share]\n",
        encoding="utf-8",
    )
    (packages / "ros2-host-sdk" / "sbuild.py").write_text("", encoding="utf-8")
    content = generate_package_kconfig_files(tmp_path)["packages/rcutils/Kconfig"]
    assert "    select PACKAGE_ROS2_HOST_SDK" in content


def test_repository_generated_package_kconfigs_do_not_gate_selection():
    root = Path(__file__).resolve().parents[1]
    gated = []
    for relative, content in generate_package_kconfig_files(root).items():
        yaml_path = root / Path(relative).parent / "package.yaml"
        metadata = normalize_package_metadata(load_description(yaml_path))
        header = f"config {metadata.kconfig.symbol}\n"
        block = content.split(header, 1)
        if len(block) != 2:
            continue
        for line in block[1].splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("config ") or stripped == "endmenu":
                break
            if stripped.startswith("depends on PACKAGE_"):
                gated.append(f"{name}: {stripped}")
    assert gated == []


def test_generated_package_kconfig_index_groups_packages_by_category(tmp_path):
    packages = tmp_path / "packages"
    (packages / "curl").mkdir(parents=True)
    (packages / "curl" / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: curl\nversion: '8.20.0'\n"
        "type: executable\ndescription: curl command-line URL transfer tool\n"
        "source:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/bin/curl]\n"
        "install:\n  path: /usr/bin/curl\n",
        encoding="utf-8",
    )
    (packages / "nano").mkdir()
    (packages / "nano" / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: nano\nversion: '9.0'\n"
        "type: executable\ncategory: Shell and editors\n"
        "description: GNU nano terminal text editor\n"
        "source:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/bin/nano]\n"
        "install:\n  path: /usr/bin/nano\n",
        encoding="utf-8",
    )
    (packages / "odd").mkdir()
    (packages / "odd" / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: odd\nversion: '1.0'\n"
        "type: executable\ndescription: Unclassified example\n"
        "source:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/bin/odd]\n"
        "install:\n  path: /usr/bin/odd\n",
        encoding="utf-8",
    )
    for name in ("curl", "nano", "odd"):
        (packages / name / "sbuild.py").write_text("", encoding="utf-8")

    index = generate_package_kconfig_index(tmp_path)

    assert 'menu "Networking"' in index
    assert 'menu "Shell and editors"' in index
    assert f'menu "{OTHER_CATEGORY}"' in index
    assert index.index('menu "Networking"') < index.index('source "packages/curl/Kconfig"')
    assert index.index('source "packages/curl/Kconfig"') < index.index('menu "Shell and editors"')
    assert index.index('source "packages/nano/Kconfig"') < index.index(f'menu "{OTHER_CATEGORY}"')
    assert 'source "packages/odd/Kconfig"' in index


def test_repository_package_kconfig_index_classifies_every_package():
    root = Path(__file__).resolve().parents[1]
    packages = load_all_package_metadata(root)
    grouped = grouped_packages(packages)
    titles = [title for title, _items in grouped]
    assert titles
    assert OTHER_CATEGORY not in titles
    assert all(title in PACKAGE_CATEGORIES for title in titles)
    classified = {metadata.name for _title, items in grouped for metadata in items}
    assert classified == {metadata.name for metadata in packages}
    index = generate_package_kconfig_index(root)
    assert index.count("menu ") == index.count("endmenu")
    for title, items in grouped:
        assert f'menu "{title}"' in index
        for metadata in items:
            assert f'source "{package_kconfig_relative(root, metadata)}"' in index


def test_package_description_must_fit_menu_limit(tmp_path):
    package_dir = tmp_path / "packages" / "wide"
    package_dir.mkdir(parents=True)
    (package_dir / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: wide\nversion: '1.0'\n"
        "type: executable\n"
        "description: "
        + ("x" * (DESCRIPTION_MAX_LENGTH + 1))
        + "\nsource:\n  directory: apps/hello\n"
        "build:\n  python:\n    script: sbuild.py\n    outputs: [/usr/bin/wide]\n"
        "install:\n  path: /usr/bin/wide\n",
        encoding="utf-8",
    )
    (package_dir / "sbuild.py").write_text("", encoding="utf-8")
    with pytest.raises(SmartBuildError, match="at most 80 characters"):
        normalize_package_metadata(load_description(package_dir / "package.yaml"))


def test_shorten_package_description_drops_url_and_limits_length():
    text = (
        "XNNPACK is a highly optimized solution for neural network inference on "
        "ARM, x86, WebAssembly, and RISC-V platforms. https://github.com/google/XNNPACK"
    )
    shortened = shorten_package_description(text)
    assert len(shortened) <= DESCRIPTION_MAX_LENGTH
    assert "https://" not in shortened


def test_repository_generated_package_kconfigs_include_descriptions():
    root = Path(__file__).resolve().parents[1]
    generated = generate_package_kconfig_files(root)
    missing = []
    for relative, content in generated.items():
        yaml_path = root / Path(relative).parent / "package.yaml"
        metadata = normalize_package_metadata(load_description(yaml_path))
        if not metadata.description or metadata.description == metadata.name:
            missing.append(name)
            continue
        if "    help" not in content or metadata.description.splitlines()[0] not in content:
            missing.append(name)
    assert missing == []
    long_descriptions = [
        metadata.name
        for metadata in load_all_package_metadata(root)
        if len(metadata.description) > DESCRIPTION_MAX_LENGTH
    ]
    assert long_descriptions == []
