import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import SmartBuildError


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    status: str
    log_path: Path


@dataclass(frozen=True)
class TaskBatch:
    run_class: str
    tasks: tuple


class Scheduler:
    def __init__(self, graph, cache, jobs=1, verbose=False, display_path=None):
        self.graph = graph
        self.cache = cache
        self.jobs = jobs
        self.verbose = verbose
        self.display_path = display_path or str

    def plan_batches(self):
        order = self.graph.topological_order()
        remaining = {task.id: set(task.deps) for task in order}
        by_id = {task.id: task for task in order}
        ordered_ids = [task.id for task in order]
        completed = set()
        batches = []

        while len(completed) < len(order):
            ready = [
                by_id[task_id]
                for task_id in ordered_ids
                if task_id not in completed and remaining[task_id].issubset(completed)
            ]
            if not ready:
                raise SmartBuildError("TASK", "task graph cannot be batched")

            serial_ready = [task for task in ready if task.run_class == "serial"]
            if serial_ready:
                batch_tasks = (serial_ready[0],)
                run_class = "serial"
            else:
                batch_tasks = tuple(task for task in ready if task.run_class in {"fetch", "build"})
                run_class = "parallel"

            batches.append(TaskBatch(run_class, batch_tasks))
            completed.update(task.id for task in batch_tasks)

        return batches

    def run(self):
        results = []
        tasks = self.graph.topological_order()
        total = len(tasks)
        for index, task in enumerate(tasks, start=1):
            print(f"build: [{index}/{total}] {task.id}")
            task.log_path.parent.mkdir(parents=True, exist_ok=True)
            task.workdir.mkdir(parents=True, exist_ok=True)
            for output in task.outputs:
                output.parent.mkdir(parents=True, exist_ok=True)

            with task.log_path.open("w", encoding="utf-8") as log_file:
                log = _ConsoleTee(log_file) if self.verbose else log_file
                log.write(f"== task {task.id} ==\n")
                log.write(f"run_class: {task.run_class}\n")
                if self.cache.is_hit(task):
                    log.write("cache hit\n")
                    print(f"skipped: {task.id} log={self.display_path(task.log_path)}")
                    results.append(TaskResult(task.id, "skipped", task.log_path))
                    continue

                try:
                    status = _run_task(task, log)
                    if status not in (None, 0):
                        raise _build_error(task, status)
                    _verify_outputs(task)
                    self.cache.write(task)
                    log.write("status: success\n")
                    print(f"success: {task.id} log={self.display_path(task.log_path)}")
                    results.append(TaskResult(task.id, "success", task.log_path))
                except SmartBuildError as exc:
                    log.write(f"{exc.code}: {exc}\n")
                    raise
                except Exception as exc:
                    log.write(f"BUILD: task {task.id} failed: {exc}\n")
                    raise SmartBuildError("BUILD", f"task {task.id} failed: {exc}") from exc
        return results


def _run_task(task, log):
    if task.command:
        env = os.environ.copy()
        env.update({key: str(value) for key, value in task.env.items()})
        log.write(f"command: {_format_command(task.command)}\n")
        log.write(f"workdir: {task.workdir}\n")
        log.write("summary: command started\n")
        completed = subprocess.run(
            list(task.command),
            cwd=task.workdir,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.stdout:
            log.write(completed.stdout)
            if not completed.stdout.endswith("\n"):
                log.write("\n")
        log.write(f"summary: command exit={completed.returncode}\n")
        if completed.returncode != 0:
            raise _build_error(task, completed.returncode)
        return 0
    if task.executor is None:
        raise SmartBuildError("BUILD", f"task {task.id} has no executor")
    return task.executor(task, log)


def _verify_outputs(task):
    missing = [str(output) for output in task.outputs if not output.exists()]
    if missing:
        raise SmartBuildError(
            "BUILD",
            f"task {task.id} did not create expected outputs: {', '.join(missing)}",
        )


def _build_error(task, exit_code):
    return SmartBuildError(
        "BUILD",
        "task {task_id} command failed: command={command} workdir={workdir} "
        "exit code {exit_code} log={log_path}".format(
            task_id=task.id,
            command=_format_command(task.command),
            workdir=task.workdir,
            exit_code=exit_code,
            log_path=task.log_path,
        ),
    )


def _format_command(command):
    return " ".join(str(part) for part in command) if command else "<executor>"


class _ConsoleTee:
    def __init__(self, log_file):
        self.log_file = log_file
        self.name = log_file.name

    def write(self, text):
        self.log_file.write(text)
        print(text, end="")

    def flush(self):
        self.log_file.flush()
