from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess


def _load_bzip2_sbuild():
    script = Path(__file__).resolve().parents[1] / "packages" / "bzip2" / "sbuild.py"
    spec = spec_from_file_location("bzip2_sbuild", script)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bzip2_sbuild_installs_into_stage_prefix(tmp_path, monkeypatch):
    source = tmp_path / "source"
    work = tmp_path / "work"
    stage = tmp_path / "stage"
    source.mkdir()
    (source / "configure").write_text("", encoding="utf-8")

    monkeypatch.setenv("SMART_BUILD_SOURCE_DIR", str(source))
    monkeypatch.setenv("SMART_BUILD_WORK_DIR", str(work))
    monkeypatch.setenv("SMART_BUILD_STAGE_DIR", str(stage))
    monkeypatch.setenv("SMART_BUILD_TARGET", "aarch64-linux-musleabi")

    commands = []

    def fake_run(command, cwd, env=None, check=False, **kwargs):
        commands.append(tuple(command))
        if command and command[0] == "make" and "install" in command:
            prefix = Path(next(part.split("=", 1)[1] for part in command if part.startswith("PREFIX=")))
            bin_dir = prefix / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name in ("bzip2", "bunzip2", "bzcat", "bzip2recover", "bzgrep", "bzmore", "bzdiff"):
                (bin_dir / name).write_text(name + "\n", encoding="utf-8")
            (bin_dir / "bzegrep").symlink_to(bin_dir / "bzgrep")
            (bin_dir / "bzfgrep").symlink_to(bin_dir / "bzgrep")
            (bin_dir / "bzless").symlink_to(bin_dir / "bzmore")
            (bin_dir / "bzcmp").symlink_to(bin_dir / "bzdiff")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    _load_bzip2_sbuild()
    assert ("make", f"PREFIX={stage / 'usr'}", "install") in commands
    assert not (stage / "usr" / "bin" / "bzcmp").is_symlink()
    assert (stage / "usr" / "bin" / "bzcmp").read_text(encoding="utf-8") == (
        stage / "usr" / "bin" / "bzdiff"
    ).read_text(encoding="utf-8")
