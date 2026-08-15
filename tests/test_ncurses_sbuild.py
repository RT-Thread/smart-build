from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess


def _load_ncurses_sbuild():
    script = Path(__file__).resolve().parents[1] / "packages" / "ncurses" / "sbuild.py"
    spec = spec_from_file_location("ncurses_sbuild", script)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ncurses_sbuild_stages_linux_terminfo(tmp_path, monkeypatch):
    module = _load_ncurses_sbuild()
    source = tmp_path / "source"
    work = tmp_path / "work"
    stage = tmp_path / "stage"
    (source / "misc").mkdir(parents=True)
    (source / "configure").write_text("", encoding="utf-8")
    (source / "misc" / "terminfo.src").write_text("linux|Linux console,\n", encoding="utf-8")

    monkeypatch.setenv("SMART_BUILD_SOURCE_DIR", str(source))
    monkeypatch.setenv("SMART_BUILD_WORK_DIR", str(work))
    monkeypatch.setenv("SMART_BUILD_STAGE_DIR", str(stage))
    monkeypatch.setenv("SMART_BUILD_TARGET", "aarch64-linux-musleabi")
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/tic" if name == "tic" else None)

    commands = []

    def fake_run(command, cwd, env=None):
        commands.append((tuple(command), Path(cwd)))
        dest = Path(work) / "dest"
        if command and command[0] == "make" and "install.libs" in command:
            header = dest / "usr/include/ncurses/curses.h"
            library = dest / "usr/lib/libncurses.a"
            header.parent.mkdir(parents=True, exist_ok=True)
            library.parent.mkdir(parents=True, exist_ok=True)
            header.write_text("/* curses */\n", encoding="utf-8")
            library.write_text("lib", encoding="utf-8")
        if command and Path(command[0]).name == "tic":
            output = Path(command[command.index("-o") + 1])
            linux = output / "l" / "linux"
            xterm = output / "x" / "xterm-color"
            alias = output / "n" / "nxterm"
            linux.parent.mkdir(parents=True, exist_ok=True)
            xterm.parent.mkdir(parents=True, exist_ok=True)
            alias.parent.mkdir(parents=True, exist_ok=True)
            linux.write_bytes(b"linux-terminfo")
            xterm.write_bytes(b"xterm-terminfo")
            alias.symlink_to("../x/xterm-color")
        return None

    monkeypatch.setattr(module, "run", fake_run)

    assert module.main() == 0
    tic_command = next(command for command, _ in commands if Path(command[0]).name == "tic")
    assert "-e" in tic_command
    assert "linux" in tic_command[tic_command.index("-e") + 1].split(",")
    assert (stage / "usr/share/terminfo/l/linux").read_bytes() == b"linux-terminfo"
    assert (stage / "usr/share/terminfo/n/nxterm").read_bytes() == b"xterm-terminfo"
    assert not (stage / "usr/share/terminfo/n/nxterm").is_symlink()
    assert (stage / "usr/lib/libncurses.a").is_file()
