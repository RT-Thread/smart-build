from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess


def _load_libffi_sbuild():
    script = Path(__file__).resolve().parents[1] / "packages" / "libffi" / "sbuild.py"
    spec = spec_from_file_location("libffi_sbuild", script)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_libffi_adds_riscv_icache_stub(tmp_path, monkeypatch):
    module = _load_libffi_sbuild()
    archive = tmp_path / "libffi.a"
    archive.write_bytes(b"!<arch>\n")
    commands = []

    def fake_run(command, cwd, env=None, check=False, **kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setenv("SMART_BUILD_TARGET", "riscv64-linux-musleabi")
    monkeypatch.setenv("CC", "riscv64-linux-musleabi-gcc")
    monkeypatch.setattr(subprocess, "run", fake_run)

    module._add_riscv_icache_stub(tmp_path, archive)
    stub = (tmp_path / "riscv_flush_icache.c").read_text(encoding="ascii")
    assert "__riscv_flush_icache" in stub
    assert any(command[0] == "ar" and str(archive) in command for command in commands)


def test_libffi_skips_icache_stub_on_aarch64(tmp_path, monkeypatch):
    module = _load_libffi_sbuild()
    archive = tmp_path / "libffi.a"
    archive.write_bytes(b"!<arch>\n")
    monkeypatch.setenv("SMART_BUILD_TARGET", "aarch64-linux-musleabi")
    module._add_riscv_icache_stub(tmp_path, archive)
    assert not (tmp_path / "riscv_flush_icache.c").exists()
