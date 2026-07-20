#!/usr/bin/env python3
"""Build OpenSSL for the Smart package stage."""

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


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f"expected directory not found: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=False)


def openssl_target() -> str:
    text = f"{os.environ.get('SMART_BUILD_TARGET', '')} {os.environ.get('MACHINE', '')}".lower()
    if "riscv64" in text:
        return "linux64-riscv64"
    if "aarch64" in text or "arm64" in text:
        return "linux-aarch64"
    if "arm" in text:
        return "linux-armv4"
    return "linux-aarch64"


def toolchain_env() -> dict[str, str]:
    env = os.environ.copy()
    if Path(env.get("CC", "")).is_absolute():
        env["CROSS_COMPILE"] = ""
    else:
        env.setdefault("CROSS_COMPILE", env.get("SMART_BUILD_CROSS_COMPILE", ""))
    return env


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    install_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)

    require(source_dir / "Configure", "upstream file")
    reset_dir(install_dir)
    reset_dir(stage_dir)

    configure = [
        "perl",
        str(source_dir / "Configure"),
        openssl_target(),
        "no-tests",
        "no-apps",
        "no-engine",
        "no-module",
        "no-autoload-config",
        "no-secure-memory",
        "no-asm",
        "no-shared",
        "no-pinshared",
        "--prefix=/usr",
        "--openssldir=/etc/ssl",
    ]
    env = toolchain_env()
    run(configure, cwd=source_dir, env=env)
    run(["make", "-j", jobs], cwd=source_dir, env=env)
    run(["make", f"DESTDIR={install_dir}", "install_sw"], cwd=source_dir, env=env)

    copy_tree(install_dir / "usr" / "include" / "openssl", stage_dir / "usr" / "include" / "openssl")
    copy_file(install_dir / "usr" / "lib" / "libssl.a", stage_dir / "usr" / "lib" / "libssl.a", 0o644)
    copy_file(install_dir / "usr" / "lib" / "libcrypto.a", stage_dir / "usr" / "lib" / "libcrypto.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
