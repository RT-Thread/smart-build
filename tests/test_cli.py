from types import SimpleNamespace

from smart_build import cli


def test_build_verbose_is_passed_to_task_planner(monkeypatch):
    captured = {}

    def tasks_for_target(target, machine, paths, **options):
        captured.update(options)
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
    assert captured["verbose"] is True
