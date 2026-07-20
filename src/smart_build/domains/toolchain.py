import os
import subprocess
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..cache import path_record
from ..config import DEFAULT_MACHINE
from ..errors import SmartBuildError
from ..machines import Machine, load_machine
from ..paths import project_root


TOOLCHAIN_PACKAGE = "aarch64-linux-musleabi-gcc-latest"
TARGET_TRIPLE = "aarch64-linux-musleabi"
PREFIX = f"{TARGET_TRIPLE}-"
LOADER_NAME = "ld-musl-aarch64.so.1"
TOOLCHAIN_ID = f"{TARGET_TRIPLE}-gcc"


@dataclass(frozen=True)
class Toolchain:
    root: Path
    prefix: str = PREFIX
    target: str = TARGET_TRIPLE
    package: str = TOOLCHAIN_PACKAGE
    loader_name: str | None = LOADER_NAME
    dumpmachine: str = TARGET_TRIPLE
    gcc_version: str = ""
    crt1: Path = None
    libgcc_runtime: Path = None
    libgcc_static: Path = None
    libatomic_runtime: Path = None

    @property
    def bin_dir(self):
        return self.root / "bin"

    @property
    def sysroot_lib_dir(self):
        return self.root / self.target / "lib"

    @property
    def gcc(self):
        return self.bin_dir / f"{self.prefix}gcc"

    @property
    def gxx(self):
        return self.bin_dir / f"{self.prefix}g++"

    @property
    def libc(self):
        if self.loader_name is None:
            return None
        return self.sysroot_lib_dir / "libc.so"

    @property
    def loader(self):
        if self.loader_name is None:
            return None
        return self.sysroot_lib_dir / self.loader_name

    def validate(self):
        _validate_compiler(self.gcc)
        _validate_compiler(self.gxx)
        if self.loader_name is not None:
            _validate_resolved_file(self.libc, self.root, self.target)
            _validate_resolved_file(self.loader, self.root, self.target)
            crt1 = _find_required_file("crt1.o", (self.sysroot_lib_dir / "crt1.o",), self.root)
            libgcc_runtime = _find_optional_file(
                "libgcc_s.so.1",
                (
                    self.root / self.target / "lib64" / "libgcc_s.so.1",
                    self.sysroot_lib_dir / "libgcc_s.so.1",
                ),
            )
            libatomic_runtime = _find_optional_file(
                "libatomic.so.1",
                (
                    self.root / self.target / "lib64" / "libatomic.so.1",
                    self.sysroot_lib_dir / "libatomic.so.1",
                ),
            )
        else:
            crt1 = None
            libgcc_runtime = None
            libatomic_runtime = None
        libgcc_static = _find_optional_file(
            "libgcc.a",
            (
                self.root / "lib" / "gcc" / self.target / self.gcc_version / "libgcc.a",
                self.root / self.target / "lib" / "libgcc.a",
                self.root / self.target / "lib64" / "libgcc.a",
            ),
        )
        if libgcc_static is None:
            libgcc_static = _find_first_by_name(self.root, "libgcc.a")
        if self.loader_name is not None and libgcc_runtime is None:
            raise SmartBuildError(
                "TOOLCHAIN",
                f"missing toolchain runtime: libgcc_s.so.1 under {self.root}",
            )
        if libgcc_static is None:
            raise SmartBuildError(
                "TOOLCHAIN",
                f"missing toolchain static runtime: libgcc.a under {self.root}",
            )
        if self.dumpmachine != self.target:
            raise SmartBuildError(
                "TOOLCHAIN",
                f"gcc -dumpmachine expected {self.target}, got {self.dumpmachine}",
            )
        return Toolchain(
            root=self.root,
            prefix=self.prefix,
            target=self.target,
            package=self.package,
            loader_name=self.loader_name,
            dumpmachine=self.dumpmachine,
            gcc_version=self.gcc_version,
            crt1=crt1,
            libgcc_runtime=libgcc_runtime,
            libgcc_static=libgcc_static,
            libatomic_runtime=libatomic_runtime,
        )

    def missing_required_files(self):
        missing = []
        required_paths = [self.gcc, self.gxx]
        if self.loader_name is not None:
            required_paths.extend([self.libc, self.loader])
        for path in required_paths:
            if not _path_exists_or_symlink(path):
                missing.append(str(path))
        if self.loader_name is not None:
            if not _find_optional_file("crt1.o", (self.sysroot_lib_dir / "crt1.o",)):
                missing.append(str(self.sysroot_lib_dir / "crt1.o"))
            runtime = _find_optional_file(
                "libgcc_s.so.1",
                (
                    self.root / self.target / "lib64" / "libgcc_s.so.1",
                    self.sysroot_lib_dir / "libgcc_s.so.1",
                ),
            )
        else:
            runtime = True
        static = _find_first_by_name(self.root, "libgcc.a")
        if runtime is None:
            missing.append(f"{self.root}/{{libgcc_s.so.1}}")
        if static is None:
            missing.append(f"{self.root}/{{libgcc.a}}")
        return missing

    def validate_required_files_present(self):
        missing = self.missing_required_files()
        if missing:
            raise SmartBuildError("TOOLCHAIN", f"missing toolchain files: {', '.join(missing)}")
        for compiler in (self.gcc, self.gxx):
            _validate_compiler(compiler)
        if self.loader_name is not None:
            _validate_resolved_file(self.libc, self.root, self.target)
            _validate_resolved_file(self.loader, self.root, self.target)
        return self

    def compile_env(self, base_env=None):
        source_env = os.environ if base_env is None else base_env
        existing_path = source_env.get("PATH", "")
        path = str(self.bin_dir)
        if existing_path:
            path = f"{path}{os.pathsep}{existing_path}"
        return {
            "PATH": path,
            "RTT_CC": "gcc",
            "RTT_EXEC_PATH": str(self.bin_dir),
            "RTT_CC_PREFIX": self.prefix,
            "CROSS_COMPILE": self.prefix,
        }

    def manifest_record(self):
        checksums = {
            "gcc": _path_sha256(self.gcc),
            "gxx": _path_sha256(self.gxx),
            "libc": _path_sha256(self.libc),
            "loader": _path_sha256(self.loader),
            "crt1": _path_sha256(self.crt1),
            "libgcc_runtime": _path_sha256(self.libgcc_runtime),
            "libgcc_static": _path_sha256(self.libgcc_static),
            "libatomic_runtime": _path_sha256(self.libatomic_runtime),
        }
        paths = {
            "gcc": str(self.gcc),
            "gxx": str(self.gxx),
            "libc": _path_string(self.libc),
            "loader": _path_string(self.loader),
            "crt1": _path_string(self.crt1),
            "libgcc_runtime": str(self.libgcc_runtime) if self.libgcc_runtime else None,
            "libgcc_static": str(self.libgcc_static) if self.libgcc_static else None,
            "libatomic_runtime": str(self.libatomic_runtime) if self.libatomic_runtime else None,
        }
        fingerprint_payload = {
            "id": self.id,
            "target": self.target,
            "prefix": self.prefix,
            "gcc_version": self.gcc_version,
            "dumpmachine": self.dumpmachine,
            "paths": paths,
            "checksums": checksums,
        }
        return {
            "id": self.id,
            "package": self.package,
            "source": "env-sdk",
            "target": self.target,
            "prefix": self.prefix,
            "root": str(self.root),
            "bin_dir": str(self.bin_dir),
            "gcc": str(self.gcc),
            "gxx": str(self.gxx),
            "libc": _path_string(self.libc),
            "loader": _path_string(self.loader),
            "gcc_version": self.gcc_version,
            "dumpmachine": self.dumpmachine,
            "crt1": _path_string(self.crt1),
            "libgcc": {
                "runtime": str(self.libgcc_runtime) if self.libgcc_runtime else None,
                "static": str(self.libgcc_static) if self.libgcc_static else None,
            },
            "libatomic": {
                "runtime": str(self.libatomic_runtime) if self.libatomic_runtime else None,
            },
            "paths": paths,
            "checksums": checksums,
            "fingerprint": _fingerprint(fingerprint_payload),
        }

    @property
    def id(self):
        return f"{self.target}-gcc"


def default_toolchain_root(machine=None):
    metadata = _resolve_machine(machine)
    return Path.home() / ".env" / "tools" / "scripts" / "packages" / metadata.toolchain_package


def resolve_toolchain(root=None, *, machine=None):
    metadata = _resolve_machine(machine)
    toolchain_root = Path(root).expanduser() if root is not None else default_toolchain_root(metadata)
    toolchain_root = toolchain_root.resolve()
    if not toolchain_root.exists():
        raise SmartBuildError(
            "TOOLCHAIN",
            "env sdk managed toolchain not found: "
            f"{toolchain_root}; install or enable package {metadata.toolchain_package} under "
            "~/.env/tools/scripts/packages",
        )
    if not toolchain_root.is_dir():
        raise SmartBuildError("TOOLCHAIN", f"toolchain package is not a directory: {toolchain_root}")
    candidate = Toolchain(
        root=toolchain_root,
        prefix=metadata.prefix,
        target=metadata.target_triple,
        package=metadata.toolchain_package,
        loader_name=metadata.loader,
    )
    candidate.validate_required_files_present()
    dumpmachine = _run_compiler_query(candidate.gcc, "-dumpmachine")
    gcc_version = _run_compiler_query(candidate.gcc, "-dumpversion")
    return Toolchain(
        root=toolchain_root,
        prefix=metadata.prefix,
        target=metadata.target_triple,
        package=metadata.toolchain_package,
        loader_name=metadata.loader,
        dumpmachine=dumpmachine,
        gcc_version=gcc_version,
    ).validate()


def toolchain_task_fields(toolchain=None):
    if _is_resolved_toolchain(toolchain):
        resolved = toolchain
    else:
        resolved = resolve_toolchain(machine=toolchain)
    record = resolved.manifest_record()
    return {
        "env": resolved.compile_env(),
        "cache_extra": {"toolchain": record},
        "manifest_fields": {"toolchain": record},
        "record": record,
    }


def _resolve_machine(machine):
    if isinstance(machine, Machine):
        return machine
    machine_name = DEFAULT_MACHINE if machine is None else machine
    return load_machine(project_root(), machine_name)


def _is_resolved_toolchain(value):
    return (
        value is not None
        and hasattr(value, "compile_env")
        and callable(value.compile_env)
        and hasattr(value, "manifest_record")
        and callable(value.manifest_record)
    )


def _path_exists_or_symlink(path):
    candidate = Path(path)
    return candidate.exists() or candidate.is_symlink()


def _validate_compiler(path):
    candidate = Path(path)
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise SmartBuildError("TOOLCHAIN", f"toolchain compiler must be an executable file: {candidate}")


def _validate_resolved_file(path, root, target):
    candidate = Path(path)
    resolved = _resolve_target_file(candidate, root, target)
    if candidate.is_symlink() and resolved is None:
        raise SmartBuildError("TOOLCHAIN", f"toolchain file is a dangling symlink: {candidate}")
    if resolved is None or not resolved.is_file():
        raise SmartBuildError("TOOLCHAIN", f"toolchain file must resolve to a file: {candidate}")


def _find_required_file(name, candidates, root):
    found = _find_optional_file(name, candidates)
    if found is not None:
        return found
    found = _find_first_by_name(root, name)
    if found is not None:
        return found
    raise SmartBuildError("TOOLCHAIN", f"missing toolchain file: {name} under {root}")


def _find_optional_file(name, candidates):
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path
    return None


def _find_first_by_name(root, name):
    for path in sorted(Path(root).rglob(name)):
        if path.exists() and path.is_file():
            return path.resolve()
    return None


def _run_compiler_query(gcc, flag):
    try:
        completed = subprocess.run(
            [str(gcc), flag],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise SmartBuildError("TOOLCHAIN", f"failed to run {gcc} {flag}: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SmartBuildError(
            "TOOLCHAIN",
            f"{gcc} {flag} failed with exit code {completed.returncode}: {detail}",
        )
    return completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""


def _path_sha256(path):
    if path is None:
        return None
    return path_record(path).get("sha256")


def _path_string(path):
    return str(path) if path is not None else None


def _fingerprint(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_target_file(path, root, target):
    candidate = Path(path)
    if not candidate.is_symlink():
        return candidate.resolve() if candidate.exists() else None
    link_target = candidate.readlink()
    resolved = candidate.resolve(strict=False)
    if resolved.exists():
        return resolved
    if link_target.is_absolute():
        sysroot_target = Path(root) / target / link_target.relative_to("/")
        if sysroot_target.exists():
            return sysroot_target.resolve()
    return None
