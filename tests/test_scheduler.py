import io
import re

import pytest

from smart_build.cache import Cache
from smart_build.errors import SmartBuildError
from smart_build.scheduler import Scheduler
from smart_build.tasks import Task, TaskGraph


ANSI_ESCAPE = re.compile(r"\033\[[0-9;]*[A-Za-z]")


class _TerminalBuffer(io.StringIO):
    def isatty(self):
        return True


def _task(tmp_path, task_id, cache_policy="never", warning=None, error=None):
    source = tmp_path / "input.txt"
    source.write_text("input\n", encoding="utf-8")
    output = tmp_path / "output.txt"

    def executor(task, log):
        if warning:
            log.console_message(f"warning: {warning}\n")
        if error:
            raise SmartBuildError("BUILD", error)
        output.write_text("output\n", encoding="utf-8")
        log.write("executor output\n")
        return 0

    return Task(
        id=task_id,
        domain="demo",
        action="build",
        inputs=[source],
        outputs=[output],
        workdir=tmp_path / "work",
        cache_policy=cache_policy,
        log_path=tmp_path / "task.log",
        executor=executor,
    )


def _display_path(root, path):
    return path.relative_to(root).as_posix()


def test_verbose_prints_task_details(tmp_path, capsys):
    task = _task(tmp_path, "demo:build")

    Scheduler(
        TaskGraph([task]),
        Cache(tmp_path / "stamps"),
        verbose=True,
        display_path=lambda path: _display_path(tmp_path, path),
    ).run()

    output = capsys.readouterr().out
    assert "domain: demo\n" in output
    assert "action: build\n" in output
    assert "workdir: work\n" in output
    assert "deps: -\n" in output
    assert "inputs: input.txt\n" in output
    assert "outputs: output.txt\n" in output
    assert "cache_policy: never\n" in output
    assert "executor output\n" in output
    assert "success: demo:build log=task.log\n" in output


def test_default_output_omits_verbose_task_details(tmp_path, capsys):
    task = _task(tmp_path, "demo:build")

    Scheduler(
        TaskGraph([task]),
        Cache(tmp_path / "stamps"),
        display_path=lambda path: _display_path(tmp_path, path),
    ).run()

    output = capsys.readouterr().out
    assert output == "build: [1/1] demo:build: success\n"
    assert "domain: demo\n" not in output
    assert "executor output\n" not in output
    assert "log=" not in output


def test_default_output_reports_cache_hit_without_log_path(tmp_path):
    task = _task(tmp_path, "demo:build", cache_policy="inputs")
    cache = Cache(tmp_path / "stamps")

    Scheduler(TaskGraph([task]), cache, console=io.StringIO()).run()
    console = io.StringIO()
    Scheduler(TaskGraph([task]), cache, console=console).run()

    assert console.getvalue() == "build: [1/1] demo:build: skipped\n"


def test_interactive_output_uses_color_and_live_progress(tmp_path, monkeypatch):
    task = _task(tmp_path, "demo:build")
    console = _TerminalBuffer()
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)

    Scheduler(TaskGraph([task]), Cache(tmp_path / "stamps"), console=console).run()

    output = console.getvalue()
    plain_output = ANSI_ESCAPE.sub("", output)
    assert "\033[36m" in output
    assert "\033[32m" in output
    assert "\r\033[2K" in output
    assert "build: [1/1] demo:build: success\n" in plain_output
    assert "build: [########################] 1/1\n" in plain_output


def test_interactive_warning_is_printed_above_progress(tmp_path, monkeypatch):
    task = _task(tmp_path, "demo:build", warning="check this")
    console = _TerminalBuffer()
    monkeypatch.delenv("TERM", raising=False)

    Scheduler(TaskGraph([task]), Cache(tmp_path / "stamps"), console=console).run()

    plain_output = ANSI_ESCAPE.sub("", console.getvalue())
    warning_position = plain_output.index("warning: check this\n")
    success_position = plain_output.index("build: [1/1] demo:build: success\n")
    assert warning_position < success_position
    assert "\rwarning: check this\n" in plain_output


def test_default_failure_reports_log_path(tmp_path):
    task = _task(tmp_path, "demo:build", error="broken")
    console = io.StringIO()

    with pytest.raises(SmartBuildError, match="broken"):
        Scheduler(
            TaskGraph([task]),
            Cache(tmp_path / "stamps"),
            display_path=lambda path: _display_path(tmp_path, path),
            console=console,
        ).run()

    assert console.getvalue() == "build: [1/1] demo:build: failed log=task.log\n"
