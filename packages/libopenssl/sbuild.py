#!/usr/bin/env python3
"""Build the OpenSSL libraries for the Smart package stage."""

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


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode:
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
    target = os.environ.get("SMART_BUILD_TARGET", "").lower()
    if "riscv64" in target:
        return "linux64-riscv64"
    if "aarch64" in target or "arm64" in target:
        return "linux-aarch64"
    if "arm" in target:
        return "linux-armv4"
    return "linux-aarch64"


def main() -> int:
    source = required_path("SMART_BUILD_SOURCE_DIR")
    work = required_path("SMART_BUILD_WORK_DIR")
    stage = required_path("SMART_BUILD_STAGE_DIR")
    install = work / "dest"
    if install.exists():
        shutil.rmtree(install)
    install.mkdir(parents=True)

    if not (source / "Configure").is_file():
        raise SystemExit(f"missing OpenSSL Configure script: {source / 'Configure'}")
    env = os.environ.copy()
    if Path(env.get("CC", "")).is_absolute():
        env["CROSS_COMPILE"] = ""
    else:
        env.setdefault("CROSS_COMPILE", env.get("SMART_BUILD_CROSS_COMPILE", ""))
    run(
        [
            "perl",
            str(source / "Configure"),
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
        ],
        cwd=source,
        env=env,
    )
    run(["make", "-j" + str(os.cpu_count() or 1)], cwd=source, env=env)
    run(["make", f"DESTDIR={install}", "install_sw"], cwd=source, env=env)

    copy_tree(install / "usr" / "include" / "openssl", stage / "usr" / "include" / "openssl")
    copy_file(install / "usr" / "lib" / "libssl.a", stage / "usr" / "lib" / "libssl.a", 0o644)
    copy_file(install / "usr" / "lib" / "libcrypto.a", stage / "usr" / "lib" / "libcrypto.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
