#!/usr/bin/env python3
"""Build libuv as a static Smart package."""

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


def configure(source_dir: Path, build_dir: Path, options: list[str], env: dict[str, str] | None = None) -> None:
    command = [
        str(source_dir / "configure"),
        f"--host={os.environ.get('SMART_BUILD_TARGET', '')}",
        *options,
    ]
    run([item for item in command if item != "--host="], cwd=build_dir, env=env)


def _patch_linux_errqueue_optional(source_dir: Path) -> None:
    udp_c = source_dir / "src/unix/udp.c"
    text = udp_c.read_text(encoding="utf-8")
    if "SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE" in text:
        return

    replacements = [
        (
            "#if defined(__linux__)\n#include <linux/errqueue.h>\n#endif\n",
            "#if defined(__linux__) && defined(__has_include)\n"
            "# if __has_include(<linux/errqueue.h>)\n"
            "#  define SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE 1\n"
            "# endif\n"
            "#endif\n"
            "#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)\n"
            "#include <linux/errqueue.h>\n"
            "#endif\n",
        ),
        (
            "#if defined(__linux__)\nstatic int uv__udp_recvmsg_errqueue",
            "#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)\nstatic int uv__udp_recvmsg_errqueue",
        ),
        (
            "/* Just Linux support for now. */\n#if defined(__linux__)",
            "/* Just Linux support for now. */\n#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)",
        ),
        (
            "#if defined(__linux__)\n  char control[ARRAY_SIZE(peers)][64];",
            "#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)\n  char control[ARRAY_SIZE(peers)][64];",
        ),
        (
            "#if defined(__linux__)\n    if (flag & MSG_ERRQUEUE) {",
            "#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)\n    if (flag & MSG_ERRQUEUE) {",
        ),
        (
            "#if defined(__linux__)\n      if ((flag & MSG_ERRQUEUE) &&",
            "#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)\n      if ((flag & MSG_ERRQUEUE) &&",
        ),
        (
            "#if defined(__linux__)\n  char control[256];",
            "#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)\n  char control[256];",
        ),
        (
            "#if defined(__linux__)\n    if ((flag & MSG_ERRQUEUE) &&",
            "#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)\n    if ((flag & MSG_ERRQUEUE) &&",
        ),
        (
            "static int uv__set_recverr(int fd, sa_family_t ss_family) {\n"
            "#if defined(__linux__)\n"
            "  int yes;\n"
            "\n"
            "  yes = 1;\n"
            "  if (ss_family == AF_INET) {\n"
            "    if (setsockopt(fd, IPPROTO_IP, IP_RECVERR, &yes, sizeof(yes)))\n"
            "      return UV__ERR(errno);\n"
            "  } else if (ss_family == AF_INET6) {\n"
            "    if (setsockopt(fd, IPPROTO_IPV6, IPV6_RECVERR, &yes, sizeof(yes)))\n"
            "       return UV__ERR(errno);\n"
            "  }\n"
            "#endif\n"
            "  return 0;\n"
            "}\n",
            "static int uv__set_recverr(int fd, sa_family_t ss_family) {\n"
            "#if defined(SMART_BUILD_LIBUV_HAS_LINUX_ERRQUEUE)\n"
            "  int yes;\n"
            "\n"
            "  yes = 1;\n"
            "  if (ss_family == AF_INET) {\n"
            "    if (setsockopt(fd, IPPROTO_IP, IP_RECVERR, &yes, sizeof(yes)))\n"
            "      return UV__ERR(errno);\n"
            "  } else if (ss_family == AF_INET6) {\n"
            "    if (setsockopt(fd, IPPROTO_IPV6, IPV6_RECVERR, &yes, sizeof(yes)))\n"
            "       return UV__ERR(errno);\n"
            "  }\n"
            "  return 0;\n"
            "#else\n"
            "  (void) fd;\n"
            "  (void) ss_family;\n"
            "  return UV_ENOTSUP;\n"
            "#endif\n"
            "}\n",
        ),
    ]

    for old, new in replacements:
        if old not in text:
            raise SystemExit(f"libuv udp.c pattern not found: {old.splitlines()[0]}")
        text = text.replace(old, new)
    udp_c.write_text(text, encoding="utf-8")


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    build_dir = work_dir / "build"
    dest_dir = work_dir / "dest"
    jobs = str(os.cpu_count() or 1)

    _patch_linux_errqueue_optional(source_dir)
    reset_dir(build_dir)
    reset_dir(dest_dir)
    configure(
        source_dir,
        build_dir,
        [
            "--prefix=/usr",
            "--libdir=/usr/lib",
            "--enable-static",
            "--disable-shared",
        ],
    )
    run(["make", "-j" + jobs], cwd=build_dir)
    run(["make", "install", f"DESTDIR={dest_dir}"], cwd=build_dir)

    copy_file(dest_dir / "usr/include/uv.h", stage_dir / "usr/include/uv.h", 0o644)
    copy_file(dest_dir / "usr/lib/libuv.a", stage_dir / "usr/lib/libuv.a", 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
