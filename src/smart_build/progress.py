import contextvars
import os


_active = contextvars.ContextVar("smart_build_progress", default=None)


def current_progress():
    return _active.get()


def report_phase(name):
    progress = _active.get()
    if progress is not None:
        progress.phase(name)


def report_items(name, current, total, detail=None):
    progress = _active.get()
    if progress is not None:
        progress.items(name, current, total, detail)


class use_progress:
    def __init__(self, progress):
        self.progress = progress
        self.token = None

    def __enter__(self):
        self.token = _active.set(self.progress)
        return self.progress

    def __exit__(self, exc_type, exc, tb):
        if self.progress is not None:
            self.progress.close()
        _active.reset(self.token)
        return False


class PlanProgress:
    _BAR_WIDTH = 24

    def __init__(self, stream, verbose=False):
        self.stream = stream
        self.verbose = verbose
        self.interactive = not verbose and _supports_terminal_updates(stream)
        self.color = _supports_color(stream)
        self.rendered = False

    def phase(self, name):
        if self.verbose or not self.interactive:
            self._write_line(self._style(f"plan: {name}", "36"))
            return
        self._render(f"plan: {name}")

    def items(self, name, current, total, detail=None):
        label = detail or name
        if self.verbose:
            self._write_line(self._style(f"plan: [{current}/{total}] {label}", "36"))
            return
        if not self.interactive:
            return
        filled = self._BAR_WIDTH * current // total if total else self._BAR_WIDTH
        bar = "#" * filled + "-" * (self._BAR_WIDTH - filled)
        self._render(f"plan: [{bar}] {current}/{total} {label}")

    def finish(self, message):
        self.clear()
        self._write_line(self._style(f"plan: {message}", "36"))

    def clear(self):
        if self.rendered:
            self.stream.write("\r\033[2K")
            self.stream.flush()
            self.rendered = False

    def close(self):
        self.clear()

    def _render(self, line):
        self.clear()
        self.stream.write("\r" + self._style(line, "36"))
        self.stream.flush()
        self.rendered = True

    def _write_line(self, text):
        self.clear()
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
