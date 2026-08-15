import io
import re

from smart_build.descriptions import load_description
from smart_build.package_metadata import cached_package_metadata, load_all_package_metadata
from smart_build.progress import PlanProgress, report_items
from smart_build import cli


ANSI_ESCAPE = re.compile(r"\033\[[0-9;]*[A-Za-z]")


class _TerminalBuffer(io.StringIO):
    def isatty(self):
        return True


def test_plan_progress_noninteractive_prints_phases_not_items():
    console = io.StringIO()
    progress = PlanProgress(console)

    progress.phase("loading machine")
    progress.items("packages", 1, 2, "curl")
    progress.finish("ready 3 tasks")

    assert console.getvalue() == "plan: loading machine\nplan: ready 3 tasks\n"


def test_plan_progress_verbose_prints_items():
    console = io.StringIO()
    progress = PlanProgress(console, verbose=True)

    progress.phase("analyzing target")
    progress.items("packages", 1, 2, "curl")
    progress.finish("ready 3 tasks")

    assert console.getvalue() == (
        "plan: analyzing target\n"
        "plan: [1/2] curl\n"
        "plan: ready 3 tasks\n"
    )


def test_plan_progress_interactive_uses_live_bar(monkeypatch):
    console = _TerminalBuffer()
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    progress = PlanProgress(console)

    progress.phase("analyzing target")
    progress.items("packages", 1, 2, "curl")
    progress.finish("ready 3 tasks")

    output = console.getvalue()
    plain = ANSI_ESCAPE.sub("", output)
    assert "\033[36m" in output
    assert "\r\033[2K" in output
    assert "plan: analyzing target" in plain
    assert "plan: [############------------] 1/2 curl" in plain
    assert "plan: ready 3 tasks\n" in plain


def test_cached_package_metadata_reuses_loaded_packages(tmp_path, monkeypatch):
    package_dir = tmp_path / "packages" / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "package.yaml").write_text(
        "schema_version: 1\nkind: package\nname: demo\nversion: 0.1.0\n",
        encoding="utf-8",
    )
    loads = []

    def counting_load(path):
        loads.append(path)
        return load_description(path)

    monkeypatch.setattr("smart_build.package_metadata.load_description", counting_load)
    with cached_package_metadata():
        first = load_all_package_metadata(tmp_path)
        second = load_all_package_metadata(tmp_path)

    assert [package.name for package in first] == ["demo"]
    assert [package.name for package in second] == ["demo"]
    assert len(loads) == 1


def test_build_prints_plan_progress_before_tasks(monkeypatch, capsys):
    from types import SimpleNamespace

    def tasks_for_target(target, machine, paths, **options):
        report_items("packages", 1, 1, "curl")
        return []

    monkeypatch.setattr(cli, "tasks_for_target", tasks_for_target)
    args = SimpleNamespace(
        target="kernel",
        machine="test-machine",
        global_machine=None,
        jobs=None,
        dry_run=True,
        verbose=True,
    )

    assert cli._run_build(args) == 0
    output = capsys.readouterr().out
    assert "plan: loading machine\n" in output
    assert "plan: analyzing target\n" in output
    assert "plan: [1/1] curl\n" in output
    assert "plan: ready 0 tasks\n" in output
    assert output.index("plan: ready 0 tasks\n") < output.index("dry-run: planned tasks")
