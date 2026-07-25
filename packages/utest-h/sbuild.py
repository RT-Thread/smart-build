#!/usr/bin/env python3
"""Install the public utest.h header."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def main() -> int:
    source = required_path("SMART_BUILD_SOURCE_DIR") / "utest.h"
    stage_dir = required_path("SMART_BUILD_STAGE_DIR")
    destination = stage_dir / "usr/include/utest.h"
    if not source.is_file():
        raise SystemExit(f"expected file not found: {source}")
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    destination.parent.mkdir(parents=True)
    shutil.copy2(source, destination)
    destination.chmod(0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
