import hashlib
import io
import shutil
import tarfile
from pathlib import Path

import pytest

from smart_build.domains.toolchain import (
    _extract_toolchain_archive,
    install_toolchain,
    resolve_toolchain,
    resolve_toolchain_selection,
)
from smart_build.errors import SmartBuildError
from smart_build.machines import load_machine


TARGET = "test-linux-musleabi"
PREFIX = f"{TARGET}-"
PACKAGE = "test-linux-musleabi-gcc-test"


def _project(tmp_path, *, source_url=None, sha256=None):
    board = tmp_path / "boards" / "test-machine"
    board.mkdir(parents=True)
    source = ""
    if source_url:
        source = (
            "      source:\n"
            f"        url: {source_url}\n"
            "        archive: test-toolchain.tar.bz2\n"
            f"        sha256: \"{sha256}\"\n"
        )
    (board / "board.yaml").write_text(
        "schema_version: 1\n"
        "kind: board\n"
        "name: test-machine\n"
        "version: 0.1.0\n"
        "arch: test\n"
        "bsp: test-bsp\n"
        "kernel_defconfig: kernel_defconfig\n"
        "toolchain:\n"
        f"  package: {PACKAGE}\n"
        "  version: \"1.0\"\n"
        "  target: test-linux-musleabi\n"
        "  prefix: test-linux-musleabi-\n"
        "  loader: ld-musl-test.so.1\n"
        "  versions:\n"
        "    - version: \"1.0\"\n"
        f"      package: {PACKAGE}\n"
        "      gcc_version: \"12.2.0\"\n"
        f"{source}"
        "qemu:\n"
        "  binary: qemu-system-test\n"
        "  profile: test\n"
        "  machine: test\n",
        encoding="utf-8",
    )
    (board / "defconfig").write_text(
        "MACHINE=test-machine\nTOOLCHAIN=" + PACKAGE + "\nTOOLCHAIN_VERSION=1.0\n",
        encoding="utf-8",
    )
    (board / "kernel_defconfig").write_text("", encoding="utf-8")
    return tmp_path


def _fake_toolchain_archive(tmp_path):
    source = tmp_path / "source-toolchain"
    target_lib = source / TARGET / "lib"
    target_lib.mkdir(parents=True)
    (source / "bin").mkdir()
    (source / "lib" / "gcc" / TARGET / "12.2.0").mkdir(parents=True)
    compiler = source / "bin" / f"{PREFIX}gcc"
    compiler.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        f"-dumpmachine) echo {TARGET};;\n"
        "-dumpversion) echo 12.2.0;;\n"
        "*) exit 0;;\n"
        "esac\n",
        encoding="utf-8",
    )
    compiler.chmod(0o755)
    shutil.copy2(compiler, source / "bin" / f"{PREFIX}g++")
    (target_lib / "libc.so").write_text("libc\n", encoding="utf-8")
    (target_lib / "crt1.o").write_text("crt1\n", encoding="utf-8")
    (target_lib / "libgcc_s.so.1").write_text("runtime\n", encoding="utf-8")
    (source / "lib" / "gcc" / TARGET / "12.2.0" / "libgcc.a").write_text("static\n", encoding="utf-8")
    (target_lib / "ld-musl-test.so.1").symlink_to("/lib/libc.so")
    archive = tmp_path / "test-toolchain.tar.bz2"
    with tarfile.open(archive, "w:bz2") as handle:
        handle.add(source, arcname="test-toolchain")
    return archive


def test_toolchain_selection_uses_workspace_path_and_version(tmp_path):
    root = _project(tmp_path)
    config = root / "build" / ".config"
    config.parent.mkdir()
    custom = root / "custom-toolchain"
    config.write_text(
        "MACHINE=test-machine\n"
        "TOOLCHAIN=" + PACKAGE + "\n"
        "TOOLCHAIN_VERSION=1.0\n"
        "TOOLCHAIN_PATH=custom-toolchain\n",
        encoding="utf-8",
    )
    metadata = load_machine(root, "test-machine")
    selection = resolve_toolchain_selection(metadata)
    assert selection.release.package == PACKAGE
    assert selection.custom_root == custom


def test_install_toolchain_downloads_verifies_and_resolves(tmp_path):
    archive = _fake_toolchain_archive(tmp_path)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    root = _project(
        tmp_path / "project",
        source_url="https://example.invalid/test-toolchain.tar.bz2",
        sha256=digest,
    )
    metadata = load_machine(root, "test-machine")
    calls = []

    def downloader(url, destination):
        calls.append((url, Path(destination)))
        shutil.copy2(archive, destination)

    installed = install_toolchain(metadata, downloader=downloader, output=io.StringIO())
    assert installed.source == "downloads"
    assert installed.configured_version == "1.0"
    assert calls and calls[0][0].startswith("https://")
    assert resolve_toolchain(machine=metadata).root == installed.root


def test_install_toolchain_rejects_checksum_without_leaving_archive(tmp_path):
    archive = _fake_toolchain_archive(tmp_path)
    root = _project(
        tmp_path / "project",
        source_url="https://example.invalid/test-toolchain.tar.bz2",
        sha256="0" * 64,
    )
    metadata = load_machine(root, "test-machine")

    with pytest.raises(SmartBuildError, match="sha256 mismatch"):
        install_toolchain(metadata, downloader=lambda _url, destination: shutil.copy2(archive, destination))
    assert not list((root / "downloads" / "toolchains" / "archives").glob("*.tar.bz2"))


def test_toolchain_archive_rejects_path_traversal(tmp_path):
    archive = tmp_path / "unsafe.tar.bz2"
    with tarfile.open(archive, "w:bz2") as handle:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        handle.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(SmartBuildError, match="unsafe toolchain archive member path"):
        _extract_toolchain_archive(archive, tmp_path / "extract", TARGET)
