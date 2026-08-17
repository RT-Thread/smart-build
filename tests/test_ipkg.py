from io import StringIO
from types import SimpleNamespace

import pytest

from smart_build.domains.ipkg import (
    _make_files_ipkg_executor,
    create_ipkg,
    install_ipkg,
    install_ipkg_runtime,
    list_ipkg_runtime,
    remove_ipkg_runtime,
    PackageFile,
)
from smart_build.errors import SmartBuildError


def test_ipkg_executor_uses_build_task_install_file_modes(tmp_path):
    talker = tmp_path / "stage" / "usr" / "lib" / "demo_nodes_cpp" / "talker"
    talker.parent.mkdir(parents=True)
    talker.write_bytes(b"\x7fELF" + b"\0" * 12)
    talker.chmod(0o755)
    output = tmp_path / "demo-nodes-cpp.ipk"
    package_manifest = {
        "name": "demo-nodes-cpp",
        "version": "0.33.11",
        "architecture": "qemu-virt-aarch64",
        "depends": "",
        "provides": "demo-nodes-cpp",
        "description": "ROS 2 demo nodes",
        "file": str(output),
        "files": [{"source": str(talker), "path": "/usr/lib/demo_nodes_cpp/talker", "mode": 0o644}],
        "checksum": None,
    }
    build_task = SimpleNamespace(
        manifest_fields={
            "executable": {
                "install_files": [
                    {"source": str(talker), "path": "/usr/lib/demo_nodes_cpp/talker", "mode": 0o755}
                ]
            }
        }
    )
    task = SimpleNamespace(manifest_fields={"package": {}})

    executor = _make_files_ipkg_executor(package_manifest, build_task, "executable")
    assert executor(task, StringIO()) == 0

    rootfs = tmp_path / "rootfs"
    install_ipkg(output, rootfs)
    assert (rootfs / "usr/lib/demo_nodes_cpp/talker").stat().st_mode & 0o777 == 0o755


def test_ipkg_runtime_database_tracks_install_and_remove(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("payload\n", encoding="utf-8")
    package = tmp_path / "demo.ipk"
    create_ipkg(
        package,
        package="demo",
        version="1.0",
        architecture="all",
        depends="",
        description="demo package",
        files=[PackageFile(source=source, path="/usr/share/demo.txt", mode=0o644)],
    )
    rootfs = tmp_path / "rootfs"
    state = tmp_path / "state"

    records = install_ipkg_runtime(package, rootfs, state)

    assert records[0]["path"] == "usr/share/demo.txt"
    assert (rootfs / "usr/share/demo.txt").read_text(encoding="utf-8") == "payload\n"
    assert list_ipkg_runtime(state)[0]["Package"] == "demo"
    assert (state / "info/demo.list").read_text(encoding="utf-8") == "usr/share/demo.txt\n"

    remove_ipkg_runtime("demo", rootfs, state)

    assert not (rootfs / "usr/share/demo.txt").exists()
    assert list_ipkg_runtime(state) == []


def test_ipkg_install_rolls_back_files_when_a_later_file_conflicts(tmp_path):
    first = tmp_path / "first.txt"
    conflict = tmp_path / "conflict.txt"
    first.write_text("first\n", encoding="utf-8")
    conflict.write_text("incoming\n", encoding="utf-8")
    package = tmp_path / "rollback.ipk"
    create_ipkg(
        package,
        package="rollback",
        version="1.0",
        architecture="all",
        depends="",
        description="rollback package",
        files=[
            PackageFile(source=first, path="/usr/share/first.txt", mode=0o644),
            PackageFile(source=conflict, path="/usr/share/conflict.txt", mode=0o644),
        ],
    )
    rootfs = tmp_path / "rootfs"
    existing = rootfs / "usr/share/conflict.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("existing\n", encoding="utf-8")

    with pytest.raises(SmartBuildError, match="package file conflict"):
        install_ipkg(package, rootfs)

    assert not (rootfs / "usr/share/first.txt").exists()
    assert existing.read_text(encoding="utf-8") == "existing\n"
