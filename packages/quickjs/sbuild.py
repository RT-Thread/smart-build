#!/usr/bin/env python3
"""Build QuickJS for the Smart package stage."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def required_path(name: str) -> Path:
    return Path(required_env(name))


def require(path: Path, label: str = "dependency or upstream file") -> None:
    if not path.exists():
        raise SystemExit(f"missing required {label}: {path}")


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None, allow_failure: bool = False) -> None:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=command_env, check=False)
    if completed.returncode != 0 and not allow_failure:
        raise SystemExit(completed.returncode)


def copy_file(source: Path, destination: Path, mode: int) -> None:
    if source.is_symlink():
        source = source.resolve()
    if not source.is_file():
        raise SystemExit(f"expected file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    shutil.copy2(source, destination)
    destination.chmod(mode)


def first_existing(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    raise SystemExit("expected file not found: " + " or ".join(str(path) for path in paths))


def target_extra_libs() -> str:
    target = os.environ.get("SMART_BUILD_TARGET", "")
    if target.startswith("riscv64-") or target.startswith("arm-"):
        return "-latomic"
    return ""


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    install_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)

    require(source_dir / "qjs.c", "upstream file")
    reset_dir(install_dir)
    reset_dir(stage_dir)

    make_vars = [
        f"CROSS_PREFIX={os.environ.get('SMART_BUILD_CROSS_COMPILE', '')}",
        f"CC={required_env('CC')}",
        f"AR={os.environ.get('AR', 'ar')}",
        f"STRIP={os.environ.get('STRIP', 'strip')}",
        "CONFIG_LTO=",
        "CONFIG_WERROR=",
    ]
    extra_libs = target_extra_libs()
    if extra_libs:
        make_vars.append(f"EXTRA_LIBS={extra_libs}")
    run(["make", "clean"], cwd=source_dir, allow_failure=True)
    run(["make", "-j", jobs, "qjs", "libquickjs.a", *make_vars], cwd=source_dir)
    run(["make", f"DESTDIR={install_dir}", "PREFIX=/usr", "install", *make_vars], cwd=source_dir)

    qjs = first_existing(install_dir / "usr" / "bin" / "qjs", source_dir / "qjs")
    libquickjs = first_existing(
        install_dir / "usr" / "lib" / "quickjs" / "libquickjs.a",
        source_dir / "libquickjs.a",
    )
    copy_file(qjs, stage_dir / "usr" / "bin" / "qjs", 0o755)
    copy_file(libquickjs, stage_dir / "usr" / "lib" / "libquickjs.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
