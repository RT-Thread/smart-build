#!/usr/bin/env python3
"""Build libffi as a static Smart package."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=command_env, check=False)
    if completed.returncode != 0:
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


def copy_headers(source_dir: Path, destination_dir: Path) -> None:
    for source in sorted(source_dir.iterdir()):
        if source.is_dir():
            copy_headers(source, destination_dir / source.name)
            continue
        if source.is_symlink():
            source = source.resolve()
        if not source.is_file():
            raise SystemExit(f"unexpected libffi header entry: {source}")
        copy_file(source, destination_dir / source.name, 0o644)


def first_existing(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    raise SystemExit("expected file not found: " + " or ".join(str(path) for path in paths))


def configure(source_dir: Path, build_dir: Path, options: list[str], env: dict[str, str] | None = None) -> None:
    command = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        *options,
    ]
    run([item for item in command if item != "--host="], cwd=build_dir, env=env)


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)

    reset_dir(build_dir)
    reset_dir(dest_dir)
    configure(
        source_dir,
        build_dir,
        [
            "--prefix=/usr",
            "--libdir=/usr/lib",
            "--includedir=/usr/include",
            "--enable-static",
            "--disable-shared",
            "--disable-docs",
            "--disable-exec-static-tramp",
        ],
    )
    run(["make", "-j" + jobs], cwd=build_dir)
    run(["make", "install", f"DESTDIR={dest_dir}"], cwd=build_dir)
    archive = first_existing(dest_dir / "usr/lib/libffi.a", dest_dir / "usr/lib64/libffi.a")
    _add_riscv_icache_stub(build_dir, archive)

    copy_headers(dest_dir / "usr/include", stage_dir / "usr/include")
    copy_file(archive, stage_dir / "usr/lib/libffi.a", 0o644)
    return 0


def _add_riscv_icache_stub(build_dir, archive):
    target = os.environ.get("SMART_BUILD_TARGET", "")
    if "riscv" not in target:
        return
    stub = build_dir / "riscv_flush_icache.c"
    stub.write_text(
        "void __riscv_flush_icache(void *start, void *end, unsigned long flags)\n"
        "{\n"
        "    (void)start;\n"
        "    (void)end;\n"
        "    (void)flags;\n"
        "}\n",
        encoding="ascii",
    )
    obj = build_dir / "riscv_flush_icache.o"
    cc = os.environ.get("CC") or (os.environ.get("SMART_BUILD_CROSS_COMPILE", "") + "gcc")
    run([cc, "-c", str(stub), "-o", str(obj)], cwd=build_dir)
    run(["ar", "r", str(archive), str(obj)], cwd=build_dir)


if __name__ == "__main__":
    raise SystemExit(main())
