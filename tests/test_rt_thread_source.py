import io
import subprocess
from pathlib import Path

import pytest

from smart_build.domains.sources import (
    RT_THREAD_GIT_BRANCH,
    RT_THREAD_GIT_URL,
    rt_thread_source_task,
)
from smart_build.errors import SmartBuildError
from smart_build.paths import BuildPaths
from smart_build.tasks import create_default_plan


def _paths(tmp_path):
    return BuildPaths.for_machine("test-machine", root=tmp_path)


def test_rt_thread_source_task_clones_missing_source(tmp_path):
    paths = _paths(tmp_path)
    calls = []

    def runner(command, cwd, env):
        calls.append((command, cwd, env))
        clone_dir = Path(command[-1])
        (clone_dir / "bsp").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(command, 0, stdout="clone complete\n")

    task = rt_thread_source_task(paths, command_runner=runner)
    result = task.executor(task, io.StringIO())

    assert result == 0
    assert (tmp_path / "rt-thread" / "bsp").is_dir()
    assert task.outputs[0].is_file()
    assert calls[0][0] == [
        "git",
        "clone",
        "--branch",
        RT_THREAD_GIT_BRANCH,
        "--depth",
        "1",
        RT_THREAD_GIT_URL,
        str(paths.work_dir / "sources" / "rt-thread-clone"),
    ]
    assert task.manifest_fields["rt_thread"]["reused"] is False


def test_rt_thread_source_task_cleans_up_failed_clone(tmp_path):
    paths = _paths(tmp_path)
    clone_dir = paths.work_dir / "sources" / "rt-thread-clone"

    def runner(command, cwd, env):
        clone_dir.mkdir(parents=True)
        (clone_dir / "partial").write_text("incomplete", encoding="utf-8")
        return subprocess.CompletedProcess(command, 128, stdout="network error\n")

    task = rt_thread_source_task(paths, command_runner=runner)
    with pytest.raises(SmartBuildError, match="failed to fetch RT-Thread") as error:
        task.executor(task, io.StringIO())

    assert error.value.code == "SOURCE"
    assert not (tmp_path / "rt-thread").exists()
    assert not clone_dir.exists()
    assert not task.outputs[0].exists()


def test_rt_thread_source_task_reuses_existing_directory_or_symlink(tmp_path):
    paths = _paths(tmp_path)
    checkout = tmp_path / "checkout"
    (checkout / "bsp").mkdir(parents=True)
    (tmp_path / "rt-thread").symlink_to(checkout, target_is_directory=True)

    def unexpected_runner(command, cwd, env):
        raise AssertionError(f"unexpected command: {command}")

    task = rt_thread_source_task(paths, command_runner=unexpected_runner)
    result = task.executor(task, io.StringIO())

    assert result == 0
    assert task.manifest_fields["rt_thread"]["reused"] is True


def test_rt_thread_source_task_refuses_to_replace_invalid_path(tmp_path):
    paths = _paths(tmp_path)
    (tmp_path / "rt-thread").write_text("local data", encoding="utf-8")
    task = rt_thread_source_task(paths)

    with pytest.raises(SmartBuildError, match="refusing to replace") as error:
        task.executor(task, io.StringIO())

    assert error.value.code == "SOURCE"
    assert (tmp_path / "rt-thread").read_text(encoding="utf-8") == "local data"


def test_dry_run_plan_fetches_rt_thread_before_kernel(tmp_path):
    paths = _paths(tmp_path)
    plan = create_default_plan("test-machine", paths, resolve_real=False)
    by_id = {task.id: task for task in plan}

    assert "source:rt-thread" in by_id
    assert "source:lwext4" not in by_id
    assert by_id["kernel:packages:update"].deps == ("toolchain:check", "source:rt-thread")
    assert by_id["kernel:build"].deps == ("kernel:packages:update",)
