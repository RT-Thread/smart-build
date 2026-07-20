import json
import os
import shutil
import subprocess
from pathlib import Path

from ..errors import SmartBuildError
from ..tasks import Task


RT_THREAD_TASK_ID = "source:rt-thread"
RT_THREAD_GIT_URL = "https://github.com/RT-Thread/rt-thread.git"
RT_THREAD_GIT_BRANCH = "master"


def rt_thread_source_task(paths, command_runner=None):
    source = paths.root / "rt-thread"
    marker = paths.stamps_dir / "sources" / "rt-thread.ok"
    return Task(
        id=RT_THREAD_TASK_ID,
        domain="source",
        action="rt-thread",
        outputs=[marker],
        deps=["config:load"],
        workdir=paths.work_dir / "sources" / "rt-thread-task",
        env={"MACHINE": paths.machine},
        run_class="fetch",
        cache_policy="never",
        log_path=paths.logs_dir / "source-rt-thread.log",
        executor=_make_rt_thread_executor(paths, command_runner),
        cache_extra={
            "url": RT_THREAD_GIT_URL,
            "branch": RT_THREAD_GIT_BRANCH,
            "source": str(source),
        },
        manifest_fields={"rt_thread": _rt_thread_source_record(source, reused=None)},
    )


def _make_rt_thread_executor(paths, command_runner):
    runner = command_runner or _run_command

    def executor(task, log):
        source = paths.root / "rt-thread"
        if _is_valid_rt_thread_source(source):
            _complete_rt_thread_task(task, source, reused=True, log=log)
            log.write(f"using existing RT-Thread source: {source}\n")
            return 0

        if source.exists() or source.is_symlink():
            raise SmartBuildError(
                "SOURCE",
                f"invalid RT-Thread source at {source}: expected a directory containing bsp; "
                "refusing to replace the existing path",
            )

        clone_dir = paths.work_dir / "sources" / "rt-thread-clone"
        _remove_path(clone_dir)
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        command = _rt_thread_git_clone_command(clone_dir)
        try:
            completed = runner(command, cwd=clone_dir.parent, env=os.environ.copy())
            _write_completed_command(log, command, clone_dir.parent, completed)
            if completed.returncode != 0:
                raise SmartBuildError(
                    "SOURCE",
                    "failed to fetch RT-Thread source from {url} branch {branch}; "
                    "log={log_path}".format(
                        url=RT_THREAD_GIT_URL,
                        branch=RT_THREAD_GIT_BRANCH,
                        log_path=task.log_path,
                    ),
                )
            if not _is_valid_rt_thread_source(clone_dir):
                raise SmartBuildError(
                    "SOURCE",
                    f"fetched RT-Thread source missing bsp directory: {clone_dir}",
                )
            try:
                clone_dir.rename(source)
            except OSError as exc:
                raise SmartBuildError(
                    "SOURCE",
                    f"failed to install RT-Thread source at {source}: {exc}",
                ) from exc
        finally:
            _remove_path(clone_dir)

        _complete_rt_thread_task(task, source, reused=False, log=log)
        log.write(
            "fetched RT-Thread source: {url} branch={branch} -> {source}\n".format(
                url=RT_THREAD_GIT_URL,
                branch=RT_THREAD_GIT_BRANCH,
                source=source,
            )
        )
        return 0

    return executor


def _rt_thread_git_clone_command(clone_dir):
    return [
        "git",
        "clone",
        "--branch",
        RT_THREAD_GIT_BRANCH,
        "--depth",
        "1",
        RT_THREAD_GIT_URL,
        str(clone_dir),
    ]


def _is_valid_rt_thread_source(path):
    source = Path(path)
    return source.is_dir() and (source / "bsp").is_dir()


def _rt_thread_source_record(source, reused):
    return {
        "path": str(source),
        "url": RT_THREAD_GIT_URL,
        "branch": RT_THREAD_GIT_BRANCH,
        "revision": _git_output(source, "rev-parse", "HEAD", require_own_repo=True),
        "dirty": _git_dirty(source),
        "reused": reused,
    }


def _complete_rt_thread_task(task, source, reused, log):
    record = _rt_thread_source_record(source, reused=reused)
    task.manifest_fields["rt_thread"] = record
    marker = task.outputs[0]
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log.write(f"wrote RT-Thread source record: {marker}\n")


def _run_command(command, cwd, env):
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise SmartBuildError("SOURCE", f"failed to run source command {command}: {exc}") from exc


def _write_completed_command(log, command, cwd, completed):
    log.write(f"command: {' '.join(str(part) for part in command)}\n")
    log.write(f"workdir: {cwd}\n")
    log.write("summary: command started\n")
    if completed.stdout:
        log.write(completed.stdout)
        if not completed.stdout.endswith("\n"):
            log.write("\n")
    log.write(f"summary: command exit={completed.returncode}\n")
    log.write(f"exit: {completed.returncode}\n")


def _git_dirty(path):
    status = _git_output(path, "status", "--porcelain", require_own_repo=True)
    return bool(status.strip()) if status is not None else None


def _git_output(path, *args, require_own_repo=False):
    if require_own_repo and not _is_own_git_repository(path):
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _is_own_git_repository(path):
    git_dir = Path(path) / ".git"
    return git_dir.exists() or git_dir.is_symlink()


def _remove_path(path):
    candidate = Path(path)
    if candidate.is_symlink() or candidate.is_file():
        candidate.unlink()
    elif candidate.is_dir():
        shutil.rmtree(candidate)
