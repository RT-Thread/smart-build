from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess


def _load_iperf3_sbuild():
    script = Path(__file__).resolve().parents[1] / "packages" / "iperf3" / "sbuild.py"
    spec = spec_from_file_location("iperf3_sbuild", script)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_iperf3_sbuild_disables_shared_library(tmp_path, monkeypatch):
    source = tmp_path / "source"
    stage = tmp_path / "stage"
    source.mkdir()
    (source / "configure").write_text("", encoding="utf-8")

    monkeypatch.setenv("SMART_BUILD_SOURCE_DIR", str(source))
    monkeypatch.setenv("SMART_BUILD_STAGE_DIR", str(stage))
    monkeypatch.setenv("SMART_BUILD_TARGET", "aarch64-linux-musleabi")

    commands = []

    def fake_run(command, cwd, env=None, check=False, **kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    _load_iperf3_sbuild()
    configure = next(command for command in commands if "configure" in command[0])
    assert "--disable-shared" in configure
    assert "--enable-static" in configure
