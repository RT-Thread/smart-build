import os
import subprocess
import sys
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
    def __init__(self, graph, cache, jobs=1, verbose=False, display_path=None, console=None):
        self.graph = graph
        self.cache = cache
        self.jobs = jobs
        self.verbose = verbose
        self.display_path = display_path or str
        self.console = console

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
        console = self.console if self.console is not None else sys.stdout
        display = _BuildDisplay(
            console,
            total,
            verbose=self.verbose,
            display_path=self.display_path,
        )
        try:
            for index, task in enumerate(tasks, start=1):
                display.task_started(index, task)
                task.log_path.parent.mkdir(parents=True, exist_ok=True)
                task.workdir.mkdir(parents=True, exist_ok=True)
                for output in task.outputs:
                    output.parent.mkdir(parents=True, exist_ok=True)

                with task.log_path.open("w", encoding="utf-8") as log_file:
                    log = (
                        _ConsoleTee(log_file, console)
                        if self.verbose
                        else _TaskLog(log_file, display)
                    )
                    log.write(f"== task {task.id} ==\n")
                    log.write(f"run_class: {task.run_class}\n")
                    if self.verbose:
                        self._write_task_details(task, log)
                    if self.cache.is_hit(task):
                        log.write("cache hit\n")
                        display.task_finished(index, task, "skipped")
                        results.append(TaskResult(task.id, "skipped", task.log_path))
                        continue

                    try:
                        status = _run_task(task, log)
                        if status not in (None, 0):
                            raise _build_error(task, status)
                        _verify_outputs(task)
                        self.cache.write(task)
                        log.write("status: success\n")
                        display.task_finished(index, task, "success")
                        results.append(TaskResult(task.id, "success", task.log_path))
                    except SmartBuildError as exc:
                        log.write(f"{exc.code}: {exc}\n")
                        display.task_finished(index, task, "failed")
                        raise
                    except Exception as exc:
                        log.write(f"BUILD: task {task.id} failed: {exc}\n")
                        display.task_finished(index, task, "failed")
                        raise SmartBuildError("BUILD", f"task {task.id} failed: {exc}") from exc
        finally:
            display.close()
        return results

    def _write_task_details(self, task, log):
        deps = ", ".join(task.deps) or "-"
        inputs = ", ".join(self.display_path(path) for path in task.inputs) or "-"
        outputs = ", ".join(self.display_path(path) for path in task.outputs) or "-"
        log.write(f"domain: {task.domain}\n")
        log.write(f"action: {task.action}\n")
        log.write(f"workdir: {self.display_path(task.workdir)}\n")
        log.write(f"deps: {deps}\n")
        log.write(f"inputs: {inputs}\n")
        log.write(f"outputs: {outputs}\n")
        log.write(f"cache_policy: {task.cache_policy}\n")


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


class _BuildDisplay:
    _BAR_WIDTH = 24
    _STATUS_COLORS = {
        "success": "32",
        "skipped": "33",
        "failed": "31",
    }

    def __init__(self, stream, total, verbose, display_path):
        self.stream = stream
        self.total = total
        self.verbose = verbose
        self.display_path = display_path
        self.interactive = not verbose and _supports_terminal_updates(stream)
        self.color = _supports_color(stream)
        self.rendered = False
        self.completed = 0
        self.current_task = None

    def task_started(self, index, task):
        self.current_task = task.id
        if self.verbose:
            self._write_line(self._style(f"build: [{index}/{self.total}] {task.id}", "36"))
        elif self.interactive:
            self._render_progress(self.completed, task.id)

    def task_finished(self, index, task, status):
        log_path = self.display_path(task.log_path)
        if self.verbose:
            line = f"{status}: {task.id} log={log_path}"
            self._write_line(self._style(line, self._STATUS_COLORS[status]))
            return

        if self.interactive:
            self._clear_progress()
        line = f"build: [{index}/{self.total}] {task.id}: {status}"
        if status == "failed":
            line += f" log={log_path}"
        self._write_line(self._style(line, self._STATUS_COLORS[status]))

        if status in {"success", "skipped"}:
            self.completed = index
        if self.interactive:
            current_task = None if self.completed == self.total else task.id
            self._render_progress(self.completed, current_task)

    def console_message(self, message):
        if self.interactive:
            self._clear_progress()
        self.stream.write(message)
        if message and not message.endswith("\n"):
            self.stream.write("\n")
        if self.interactive:
            self._render_progress(self.completed, self.current_task)
        else:
            self.stream.flush()

    def close(self):
        if self.interactive and self.rendered:
            self.stream.write("\n")
            self.stream.flush()
            self.rendered = False

    def _render_progress(self, completed, task_id):
        filled = self._BAR_WIDTH * completed // self.total if self.total else self._BAR_WIDTH
        bar = "#" * filled + "-" * (self._BAR_WIDTH - filled)
        line = f"build: [{bar}] {completed}/{self.total}"
        if task_id:
            line += f" {task_id}"
        self._clear_progress()
        self.stream.write("\r" + self._style(line, "36"))
        self.stream.flush()
        self.rendered = True

    def _clear_progress(self):
        if self.rendered:
            self.stream.write("\r\033[2K")
            self.rendered = False

    def _write_line(self, text):
        self.stream.write(text + "\n")
        self.stream.flush()

    def _style(self, text, code):
        if not self.color:
            return text
        return f"\033[{code}m{text}\033[0m"


def _supports_terminal_updates(stream):
    return _is_tty(stream) and os.environ.get("TERM") != "dumb"


def _supports_color(stream):
    return (
        _is_tty(stream)
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
    )


def _is_tty(stream):
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


class _TaskLog:
    mirrors_console = False

    def __init__(self, log_file, display):
        self.log_file = log_file
        self.display = display
        self.name = log_file.name

    def write(self, text):
        self.log_file.write(text)

    def flush(self):
        self.log_file.flush()

    def console_message(self, message):
        self.display.console_message(message)


class _ConsoleTee:
    mirrors_console = True

    def __init__(self, log_file, console):
        self.log_file = log_file
        self.console = console
        self.name = log_file.name

    def write(self, text):
        self.log_file.write(text)
        self.console.write(text)

    def flush(self):
        self.log_file.flush()
        self.console.flush()
