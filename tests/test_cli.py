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


def test_buildroot_import_returns_nonzero_for_partial_failure(monkeypatch, tmp_path):
    captured = {}

    class _Summary:
        failed = 1

    def importer(paths, **options):
        captured.update(options)
        return _Summary()

    monkeypatch.setattr(cli, "import_buildroot_packages", importer)
    args = SimpleNamespace(
        buildroot_command="import",
        machine="test-machine",
        config=None,
        package=None,
        check=False,
        update=False,
    )
    assert cli._run_buildroot(args) == 1
    assert captured["check"] is False


def test_buildroot_menuconfig_dispatches_to_importer(monkeypatch):
    captured = {}

    def menuconfig(paths):
        captured["root"] = paths.root
        return paths.work_dir / "buildroot" / ".config"

    monkeypatch.setattr(cli, "run_buildroot_menuconfig", menuconfig)
    args = SimpleNamespace(buildroot_command="menuconfig", machine="test-machine")
    assert cli._run_buildroot(args) == 0
    assert (captured["root"] / "smart-build").is_file()
