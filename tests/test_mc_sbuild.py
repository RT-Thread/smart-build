from pathlib import Path

import yaml

from smart_build.domains.package import _is_executable_output_path, _python_install_files
from smart_build.package_metadata import package_description_path


def test_mc_package_installs_runtime_data_directories():
    path = package_description_path(Path(__file__).resolve().parents[1], "mc")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    outputs = data["build"]["python"]["outputs"]
    assert "/usr/bin" in outputs
    assert "/usr/etc/mc" in outputs
    assert "/usr/libexec/mc" in outputs
    assert "/usr/share/mc" in outputs


def test_libexec_helpers_keep_executable_mode(tmp_path):
    staged = tmp_path / "stage"
    helper = staged / "usr/libexec/mc/extfs.d/uzip"
    config = staged / "usr/etc/mc/sfs.ini"
    helper.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    config.write_text("[sfs]\n", encoding="utf-8")

    files = {
        item["path"]: item
        for item in _python_install_files(
            staged,
            [
                Path("usr/etc/mc"),
                Path("usr/libexec/mc"),
            ],
        )
    }
    assert files["/usr/libexec/mc/extfs.d/uzip"]["mode"] == 0o755
    assert files["/usr/etc/mc/sfs.ini"]["mode"] == 0o644
    assert _is_executable_output_path("/usr/libexec/mc/cons.saver")
    assert not _is_executable_output_path("/usr/share/mc/mc.charsets")
