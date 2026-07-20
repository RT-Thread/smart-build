#!/usr/bin/env python3
"""Build curl against staged OpenSSL and zlib."""

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


def dependency_root() -> Path:
    root = os.environ.get("SMART_BUILD_PACKAGES_STAGING_DIR") or os.environ.get("SMART_BUILD_STAGING_DIR")
    if not root:
        raise SystemExit("SMART_BUILD_PACKAGES_STAGING_DIR or SMART_BUILD_STAGING_DIR is required")
    path = Path(root)
    if path.name != "packages" and (path / "packages").is_dir():
        path = path / "packages"
    return path


def dependency_prefix(package_name: str, required_file: str) -> Path:
    package_dir = dependency_root() / package_name
    for prefix in (package_dir / "usr", package_dir):
        if (prefix / required_file).exists():
            return prefix
    return package_dir / "usr"


def target_libs() -> str:
    libs = ["-lssl", "-lcrypto", "-lz"]
    target = os.environ.get("SMART_BUILD_TARGET", "")
    if target.startswith("arm-") or target.startswith("riscv64-"):
        libs.append("-latomic")
    return " ".join(libs)


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    install_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)
    openssl = dependency_prefix("openssl", "lib/libssl.a")
    zlib = dependency_prefix("zlib", "lib/libz.a")

    require(source_dir / "configure")
    require(openssl / "lib" / "libssl.a")
    require(openssl / "lib" / "libcrypto.a")
    require(zlib / "lib" / "libz.a")
    reset_dir(install_dir)
    reset_dir(stage_dir)

    env = {
        "CPPFLAGS": f"-I{openssl / 'include'} -I{zlib / 'include'}",
        "LDFLAGS": f"-L{openssl / 'lib'} -L{zlib / 'lib'}",
        "LIBS": target_libs(),
        "PKG_CONFIG": "false",
    }
    configure = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        "--prefix=/usr",
        "--disable-shared",
        "--enable-static",
        f"--with-openssl={openssl}",
        f"--with-zlib={zlib}",
        "--without-libpsl",
        "--without-brotli",
        "--without-zstd",
        "--without-nghttp2",
        "--without-nghttp3",
        "--without-ngtcp2",
        "--without-libidn2",
        "--without-librtmp",
        "--without-libssh2",
        "--without-gssapi",
        "--disable-ldap",
        "--disable-ldaps",
        "--disable-manual",
        "--disable-docs",
        "--disable-debug",
        "--disable-curldebug",
    ]
    run([item for item in configure if item != "--host="], cwd=source_dir, env=env)
    run(["make", "-C", "lib", "-j", jobs], cwd=source_dir, env=env)
    run(["make", "-C", "src", "-j", jobs], cwd=source_dir, env=env)
    run(["make", "-C", "include", f"DESTDIR={install_dir}", "install-data"], cwd=source_dir, env=env)
    run(["make", "-C", "lib", f"DESTDIR={install_dir}", "install-exec"], cwd=source_dir, env=env)
    run(["make", "-C", "src", f"DESTDIR={install_dir}", "install-exec"], cwd=source_dir, env=env)

    copy_file(install_dir / "usr" / "bin" / "curl", stage_dir / "usr" / "bin" / "curl", 0o755)
    copy_file(install_dir / "usr" / "lib" / "libcurl.a", stage_dir / "usr" / "lib" / "libcurl.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
