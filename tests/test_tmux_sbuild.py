from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess


def _load_tmux_sbuild():
    script = Path(__file__).resolve().parents[1] / "packages" / "tmux" / "sbuild.py"
    spec = spec_from_file_location("tmux_sbuild", script)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_tmux_sbuild_disables_host_pkg_config(tmp_path, monkeypatch):
    module = _load_tmux_sbuild()

    source = tmp_path / "source"
    work = tmp_path / "work"
    stage = tmp_path / "stage"
    packages_stage = tmp_path / "staging"
    source.mkdir()
    (source / "compat").mkdir()
    (source / "tmux-3.3a.patch").write_text("", encoding="utf-8")
    for name in (
        "tmux-ncurses-dll.h",
        "tmux-ncurses.h",
        "tmux-term.h",
        "tmux-unctrl.h",
    ):
        (source / name).write_text("/* stub */\n", encoding="utf-8")

    ncurses_lib = packages_stage / "ncurses" / "usr" / "lib"
    libevent_lib = packages_stage / "libevent" / "usr" / "lib"
    ncurses_lib.mkdir(parents=True)
    libevent_lib.mkdir(parents=True)
    (ncurses_lib / "libncurses.a").write_text("", encoding="utf-8")
    (libevent_lib / "libevent.a").write_text("", encoding="utf-8")

    monkeypatch.setenv("SMART_BUILD_SOURCE_DIR", str(source))
    monkeypatch.setenv("SMART_BUILD_WORK_DIR", str(work))
    monkeypatch.setenv("SMART_BUILD_STAGE_DIR", str(stage))
    monkeypatch.setenv("SMART_BUILD_PACKAGES_STAGING_DIR", str(packages_stage))
    monkeypatch.setenv("SMART_BUILD_TARGET", "aarch64-linux-musleabi")

    commands = []

    def fake_run(command, cwd, env=None, check=False, text=False, stdout=None, stderr=None):
        commands.append((tuple(command), Path(cwd), dict(env or {})))
        if command[:2] == ["make", "install"]:
            dest = Path(env["SMART_BUILD_WORK_DIR"]) / "dest" / "usr" / "bin"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "tmux").write_text("tmux", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.main() == 0

    configure_env = next(
        env
        for command, _, env in commands
        if command and command[0].endswith("configure")
    )
    assert configure_env["PKG_CONFIG"] == "false"
    assert configure_env["LIBS"] == "-levent -lncurses"
