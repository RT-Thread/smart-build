from smart_build.cache import Cache
from smart_build.scheduler import Scheduler
from smart_build.tasks import Task, TaskGraph


def _task(tmp_path, task_id):
    source = tmp_path / "input.txt"
    source.write_text("input\n", encoding="utf-8")
    output = tmp_path / "output.txt"

    def executor(task, log):
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
        cache_policy="never",
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


def test_default_output_omits_verbose_task_details(tmp_path, capsys):
    task = _task(tmp_path, "demo:build")

    Scheduler(
        TaskGraph([task]),
        Cache(tmp_path / "stamps"),
        display_path=lambda path: _display_path(tmp_path, path),
    ).run()

    output = capsys.readouterr().out
    assert "build: [1/1] demo:build\n" in output
    assert "domain: demo\n" not in output
    assert "executor output\n" not in output
