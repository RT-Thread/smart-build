import hashlib
import json
from pathlib import Path

from .errors import SmartBuildError


class Cache:
    def __init__(self, stamp_dir):
        self.stamp_dir = Path(stamp_dir)

    def is_hit(self, task):
        if task.cache_policy != "inputs":
            return False
        stamp_path = self.stamp_path(task)
        if not stamp_path.exists():
            return False
        try:
            stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return stamp.get("signature") == self.signature(task) and _outputs_exist(task.outputs)

    def write(self, task):
        if task.cache_policy != "inputs":
            return
        self.stamp_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_id": task.id,
            "signature": self.signature(task),
            "outputs": [str(path) for path in task.outputs],
        }
        self.stamp_path(task).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def signature(self, task):
        payload = {
            "id": task.id,
            "domain": task.domain,
            "action": task.action,
            "inputs": [path_record(path) for path in task.inputs],
            "outputs": [str(path) for path in task.outputs],
            "workdir": str(task.workdir),
            "run_class": task.run_class,
            "command_hash": task.command_hash(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def stamp_path(self, task):
        digest = hashlib.sha256(task.id.encode("utf-8")).hexdigest()[:16]
        safe_prefix = "".join(char if char.isalnum() or char in "._-" else "_" for char in task.id)
        safe_prefix = safe_prefix[:40] or "task"
        return self.stamp_dir / f"{safe_prefix}-{digest}.json"


def path_record(path):
    candidate = Path(path)
    if not candidate.exists() and not candidate.is_symlink():
        return {"path": str(candidate), "exists": False}
    if candidate.is_symlink():
        return {
            "path": str(candidate),
            "exists": True,
            "type": "symlink",
            "mode": _mode(candidate, follow_symlinks=False),
            "target": str(candidate.readlink()),
            "sha256": sha256_path(candidate),
        }
    if candidate.is_file():
        return {
            "path": str(candidate),
            "exists": True,
            "type": "file",
            "mode": _mode(candidate),
            "sha256": sha256_path(candidate),
        }
    if candidate.is_dir():
        entries = _directory_entries(candidate)
        return {
            "path": str(candidate),
            "exists": True,
            "type": "directory",
            "mode": _mode(candidate),
            "entries": entries,
            "sha256": sha256_path(candidate),
        }
    return {
        "path": str(candidate),
        "exists": True,
        "type": "other",
        "sha256": None,
    }


def sha256_path(path):
    candidate = Path(path)
    if candidate.is_symlink():
        payload = {
            "type": "symlink",
            "mode": _mode(candidate, follow_symlinks=False),
            "target": str(candidate.readlink()),
        }
        return _sha256_json(payload)
    if candidate.is_dir():
        return _sha256_json(_directory_entries(candidate))
    if candidate.is_file():
        payload = {
            "type": "file",
            "mode": _mode(candidate),
            "content_sha256": _sha256_file(candidate),
        }
        return _sha256_json(payload)
    raise SmartBuildError("INTERNAL", f"cannot checksum missing path {candidate}")


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _outputs_exist(outputs):
    return all(Path(path).exists() for path in outputs)


def _directory_entries(directory):
    entries = []
    for child in sorted(directory.rglob("*"), key=lambda item: item.relative_to(directory).as_posix()):
        relative = child.relative_to(directory).as_posix()
        if child.is_symlink():
            entries.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "mode": _mode(child, follow_symlinks=False),
                    "target": str(child.readlink()),
                }
            )
        elif child.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": _mode(child),
                    "content_sha256": _sha256_file(child),
                }
            )
        elif child.is_dir():
            entry_type = "empty-directory" if not any(child.iterdir()) else "directory"
            entries.append(
                {
                    "path": relative,
                    "type": entry_type,
                    "mode": _mode(child),
                }
            )
    return entries


def _mode(path, follow_symlinks=True):
    return oct(Path(path).stat(follow_symlinks=follow_symlinks).st_mode & 0o7777)


def _sha256_json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
