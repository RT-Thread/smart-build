import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import SmartBuildError


@dataclass(frozen=True)
class EnvPackages:
    env_root: Path
    command: Path
    index: Path

    @classmethod
    def discover(cls, home=None):
        root = Path(home) / ".env" if home is not None else Path.home() / ".env"
        return cls(
            env_root=root,
            command=root / "tools" / "scripts" / "pkgs",
            index=root / "packages" / "packages",
        )

    def validate(self):
        if not self.command.is_file() or not os.access(self.command, os.X_OK):
            raise SmartBuildError(
                "CONFIG",
                f"RT-Thread Env package command is not executable: {self.command}",
            )
        index_kconfig = self.index / "Kconfig"
        if not index_kconfig.is_file():
            raise SmartBuildError(
                "CONFIG",
                f"RT-Thread Env package index is missing Kconfig: {index_kconfig}",
            )
        return self

    def environment(self, base=None):
        env = os.environ.copy() if base is None else dict(base)
        scripts = str(self.command.parent)
        current_path = env.get("PATH", "")
        env.update(
            {
                "ENV_ROOT": str(self.env_root),
                "PKGS_ROOT": str(self.index.parent),
                "PKGS_DIR": str(self.index.parent),
                "PATH": scripts if not current_path else f"{scripts}{os.pathsep}{current_path}",
            }
        )
        return env

    def manifest_record(self):
        return {
            "command": str(self.command),
            "index": str(self.index),
            "index_revision": _git_output(self.index, "rev-parse", "HEAD"),
            "index_dirty": bool(_git_output(self.index, "status", "--porcelain") or ""),
        }


def _git_output(path, *args):
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
