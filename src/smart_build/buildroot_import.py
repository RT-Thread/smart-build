"""Best-effort import of Buildroot target packages into smart-build."""

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from .errors import SmartBuildError
from .package_kconfig import generate_package_kconfig_files, generate_package_kconfig_index
from .package_metadata import load_all_package_metadata, shorten_package_description, symbol_token


PACKAGE_SYMBOL_RE = re.compile(r"^BR2_PACKAGE_([A-Za-z0-9_]+)=y$")
ASSIGNMENT_RE = re.compile(r"^([A-Za-z0-9_]+)\s*(?::=|\+=|=)\s*(.*)$")
URL_RE = re.compile(r"https?://[^\s)]+")
GITHUB_CALL_RE = re.compile(r"^\$\(call github,([^,]+),([^,]+),([^\)]+)\)$")
GITLAB_CALL_RE = re.compile(r"^\$\(call gitlab,([^,]+),([^,]+),([^\)]+)\)$")
BUILDROOT_GIT_URL = "https://github.com/buildroot/buildroot.git"


@dataclass(frozen=True)
class BuildrootPackage:
    symbol: str
    name: str
    directory: Path
    version: str
    url: str
    archive: str
    sha256: str | None
    source_type: str = "archive"
    revision: str | None = None
    dependencies: tuple[str, ...] = ()
    description: str = ""
    variables: dict = field(default_factory=dict)
    make_target: str | None = None


@dataclass(frozen=True)
class ImportItem:
    name: str
    symbol: str
    status: str
    message: str


@dataclass(frozen=True)
class ImportSummary:
    items: tuple[ImportItem, ...]

    @property
    def imported(self):
        return sum(item.status == "success" for item in self.items)

    @property
    def skipped(self):
        return sum(item.status == "skipped" for item in self.items)

    @property
    def failed(self):
        return sum(item.status == "failed" for item in self.items)


def buildroot_dir(root):
    path = Path(root) / "buildroot"
    if not path.is_dir() or not (path / "Makefile").is_file():
        raise SmartBuildError("BUILDROOT", f"Buildroot tree not found: {path}")
    return path


def buildroot_config_path(paths, config_path=None):
    if config_path is not None:
        path = Path(config_path)
    else:
        path = paths.work_dir / "buildroot" / ".config"
        if not path.is_file():
            path = Path(paths.root) / "buildroot" / ".config"
    if not path.is_file():
        raise SmartBuildError("BUILDROOT", f"Buildroot configuration not found: {path}")
    return path


def parse_buildroot_config(path):
    selected = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        match = PACKAGE_SYMBOL_RE.match(raw.strip())
        if match and not match.group(1).startswith("HOST_"):
            selected.append("BR2_PACKAGE_" + match.group(1))
    return tuple(dict.fromkeys(selected))


def run_buildroot_menuconfig(paths, command_runner=None, confirm_runner=None):
    root = _ensure_buildroot_tree(paths.root, command_runner, confirm_runner)
    output = paths.work_dir / "buildroot"
    output.mkdir(parents=True, exist_ok=True)
    source = paths.work_dir / "buildroot-menuconfig-source"
    owners = _existing_owners(paths.root)
    _prepare_menuconfig_source(root, source, _buildroot_owned_symbols(root, owners))
    source_config = root / ".config"
    output_config = output / ".config"
    if source_config.is_file() and not output_config.is_file():
        shutil.copy2(source_config, output_config)
    command = ["make", "-C", str(source), f"O={output}", "menuconfig"]
    runner = command_runner or _run_command
    completed = runner(command, cwd=source, env=os.environ.copy())
    if completed.returncode != 0:
        raise SmartBuildError("CONFIG", f"Buildroot menuconfig failed with exit code {completed.returncode}")
    _force_owned_symbols(output_config, _buildroot_owned_symbols(root, owners))
    return output_config


def _ensure_buildroot_tree(root, command_runner=None, confirm_runner=None):
    project_root = Path(root)
    buildroot = project_root / "buildroot"
    if buildroot.exists():
        return buildroot_dir(project_root)

    confirm = confirm_runner or _confirm_buildroot_clone
    if not confirm(buildroot):
        raise SmartBuildError(
            "BUILDROOT",
            f"Buildroot tree not found: {buildroot}; clone was not confirmed",
        )

    clone_dir = project_root / ".buildroot-clone"
    if clone_dir.exists() or clone_dir.is_symlink():
        raise SmartBuildError(
            "BUILDROOT",
            f"temporary Buildroot clone path already exists: {clone_dir}; remove it and retry",
        )
    runner = command_runner or _run_command
    command = ["git", "clone", "--depth", "1", BUILDROOT_GIT_URL, str(clone_dir)]
    try:
        completed = runner(command, cwd=project_root, env=os.environ.copy())
        if completed.returncode != 0:
            raise SmartBuildError(
                "BUILDROOT",
                f"failed to clone latest Buildroot from {BUILDROOT_GIT_URL} "
                f"(exit code {completed.returncode})",
            )
        if not (clone_dir / "Makefile").is_file():
            raise SmartBuildError(
                "BUILDROOT",
                f"cloned Buildroot tree is missing Makefile: {clone_dir}",
            )
        if buildroot.exists() or buildroot.is_symlink():
            raise SmartBuildError(
                "BUILDROOT",
                f"Buildroot path appeared during clone: {buildroot}; refusing to overwrite it",
            )
        clone_dir.rename(buildroot)
        return buildroot
    except OSError as exc:
        raise SmartBuildError("BUILDROOT", f"failed to install Buildroot at {buildroot}: {exc}") from exc
    finally:
        if clone_dir.exists() or clone_dir.is_symlink():
            _remove_buildroot_clone(clone_dir, project_root)


def _confirm_buildroot_clone(buildroot):
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return False
    print(
        f"Buildroot tree not found at {buildroot}.\n"
        f"Clone the latest Buildroot from {BUILDROOT_GIT_URL} to {buildroot}? [y/N] ",
        end="",
        file=sys.stderr,
    )
    try:
        answer = input().strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _remove_buildroot_clone(path, project_root):
    candidate = Path(path)
    try:
        candidate.resolve(strict=False).relative_to(Path(project_root).resolve())
    except ValueError:
        return
    if candidate.is_symlink() or candidate.is_file():
        candidate.unlink()
    elif candidate.is_dir():
        shutil.rmtree(candidate)


def import_buildroot_packages(
    paths,
    config_path=None,
    package=None,
    check=False,
    update=False,
    console=None,
):
    root = buildroot_dir(paths.root)
    config = buildroot_config_path(paths, config_path)
    symbols = parse_buildroot_config(config)
    if package:
        requested = "BR2_PACKAGE_" + symbol_token(package)
        symbols = tuple(symbol for symbol in symbols if symbol == requested)
        if not symbols:
            raise SmartBuildError("BUILDROOT", f"package is not selected in Buildroot configuration: {package}")

    existing = _existing_owners(paths.root)
    never_import = load_never_import_names(paths.root)
    selected_names = {_symbol_name(symbol) for symbol in symbols}
    items = []
    total = len(symbols)
    for index, symbol in enumerate(symbols, start=1):
        name = _symbol_name(symbol)
        _progress(console, index, total, name)
        try:
            item = _import_one(
                paths.root,
                root,
                symbol,
                existing,
                selected_names,
                never_import,
                check=check,
                update=update,
            )
        except SmartBuildError as exc:
            item = ImportItem(name, symbol, "failed", str(exc))
        items.append(item)
        _result(console, index, total, item)

    summary = ImportSummary(tuple(items))
    if not check:
        _write_ownership(paths.root, existing, never_import)
        _refresh_package_index(paths.root)
    if console is not None:
        console.write(
            f"import: complete imported={summary.imported} skipped={summary.skipped} failed={summary.failed}\n"
        )
    return summary


def _import_one(root, buildroot, symbol, existing, selected_names, never_import, check, update):
    owner = existing.get(symbol)
    package_name = _symbol_name(symbol)
    if package_name in never_import:
        existing.pop(symbol, None)
        return ImportItem(package_name, symbol, "skipped", "listed in never-import")
    if owner and owner.get("owner") == "native":
        return ImportItem(package_name, symbol, "skipped", "existing native smart-build package")
    if owner and owner.get("package") == package_name and not update:
        return ImportItem(package_name, symbol, "skipped", "existing smart-build package")

    package = extract_buildroot_package(buildroot, symbol)
    owner = existing.get(symbol)
    package_dir = root / "packages" / package.name
    if owner and owner.get("owner") == "native":
        return ImportItem(package.name, symbol, "skipped", "existing native smart-build package")
    if owner and owner.get("package") == package.name and not update:
        return ImportItem(package.name, symbol, "skipped", "existing smart-build package")
    if package_dir.is_dir() and not (update and owner and owner.get("owner") == "imported"):
        existing[symbol] = {"owner": "native", "package": package.name}
        return ImportItem(package.name, symbol, "skipped", "existing smart-build package")
    if not package.url:
        raise SmartBuildError("BUILDROOT", f"{symbol}: source URL could not be determined")
    if check:
        return ImportItem(package.name, symbol, "success", "importable")
    package = replace(
        package,
        dependencies=tuple(
            dependency
            for dependency in package.dependencies
            if dependency in selected_names or (root / "packages" / dependency).is_dir()
        ),
    )
    _write_package(root, package)
    existing[symbol] = {"owner": "imported", "package": package.name}
    return ImportItem(package.name, symbol, "success", "generated network-backed package")


def extract_buildroot_package(buildroot, symbol):
    package_dir = _find_package_dir(buildroot, symbol)
    if package_dir is None:
        raise SmartBuildError("BUILDROOT", f"{symbol}: Buildroot package metadata not found")
    mk = package_dir / f"{package_dir.name}.mk"
    name = package_dir.name
    variables = _make_variables(mk, name)
    version = variables.get("VERSION", "0.0.0").strip('"')
    source = variables.get("SOURCE", "").strip('"')
    site = variables.get("SITE", "").strip('"').rstrip("/")
    source_type = variables.get("SITE_METHOD", "").strip('"') or "wget"
    # pkg-generic.mk defaults SOURCE to RAWNAME-VERSION plus the archive
    # extension when a package makefile does not define it explicitly.
    if not source and source_type != "git" and version:
        source = f"{name}-{version}.tar.gz"
    url = _source_url(site, source, source_type)
    archive = Path(source).name if source else f"{name}-{version}.tar.gz"
    sha256 = _sha256_from_package(package_dir, variables)
    dependencies = _dependencies(variables)
    description = _package_description(package_dir, symbol, name)
    make_target = _build_make_target(mk)
    if "$(" in url or "${" in url or "$(" in source or "${" in source:
        raise SmartBuildError("BUILDROOT", f"{symbol}: source URL contains unresolved Buildroot variables")
    return BuildrootPackage(
        symbol=symbol,
        name=name,
        directory=package_dir,
        version=version,
        url=url,
        archive=archive,
        sha256=sha256,
        source_type="git" if source_type == "git" else "archive",
        revision=_site_macro_revision(site) or version if source_type == "git" else None,
        dependencies=dependencies,
        description=description,
        variables=variables,
        make_target=make_target,
    )


def _find_package_dir(buildroot, symbol):
    token = _symbol_name(symbol)
    candidates = []
    for path in (Path(buildroot) / "package").rglob(f"{token}.mk"):
        if path.is_file():
            candidates.append(path.parent)
    if not candidates:
        package_root = Path(buildroot) / "package"
        for config in package_root.rglob("Config.in*"):
            if not config.is_file() or config.is_symlink():
                continue
            text = config.read_text(encoding="utf-8", errors="replace")
            if re.search(rf"^\s*config\s+{re.escape(symbol)}\s*$", text, re.MULTILINE):
                candidates.extend(path.parent for path in config.parent.glob("*.mk") if path.is_file())
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.as_posix())[0]


def _make_variables(path, package_name):
    if not path.is_file():
        raise SmartBuildError("BUILDROOT", f"package makefile not found: {path}")
    raw_variables = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = ASSIGNMENT_RE.match(raw.strip())
        if match:
            key, value = match.groups()
            raw_variables[key] = value.strip()
    prefix = symbol_token(package_name) + "_"
    result = {
        key[len(prefix) :]: value
        for key, value in raw_variables.items()
        if key.startswith(prefix)
    }
    expansion_variables = {**raw_variables, **result}
    for key, value in tuple(result.items()):
        result[key] = _expand_make_value(value, expansion_variables)
        expansion_variables[key] = result[key]
    return result


def _expand_make_value(value, variables):
    pattern = re.compile(r"\$\(([A-Za-z0-9_]+)\)|\$\{([A-Za-z0-9_]+)\}")
    expanded = value
    for _ in range(len(variables) + 1):
        updated = pattern.sub(lambda match: variables.get(match.group(1) or match.group(2), match.group(0)), expanded)
        if updated == expanded:
            return updated
        expanded = updated
    return expanded


def _source_url(site, source, source_type="wget"):
    macro_match = GITHUB_CALL_RE.match(site) or GITLAB_CALL_RE.match(site)
    if macro_match:
        owner, repository, _revision = macro_match.groups()
        host = "github.com" if site.startswith("$(call github,") else "gitlab.com"
        if source_type == "git":
            return f"https://{host}/{owner}/{repository}.git"
        archive_path = "/-/archive/" if host == "gitlab.com" else "/archive/"
        return f"https://{host}/{owner}/{repository}{archive_path}{_revision}/{source}"
    if source_type == "git" and site:
        return site
    if not source:
        return ""
    if URL_RE.match(source):
        return source
    if site.startswith("http://") or site.startswith("https://"):
        return f"{site}/{source}"
    mirrors = {
        "$(GNU_MIRROR)": "https://ftp.gnu.org/gnu",
        "$(KERNEL_MIRROR)": "https://cdn.kernel.org/pub",
        "$(BR2_KERNEL_MIRROR)": "https://cdn.kernel.org/pub",
        "$(SOURCEFORGE_MIRROR)": "https://downloads.sourceforge.net/project",
    }
    for macro, base in mirrors.items():
        if site.startswith(macro):
            suffix = site[len(macro) :].strip("/")
            return "/".join(part for part in (base, suffix, source) if part)
    return ""


def _site_macro_revision(site):
    match = GITHUB_CALL_RE.match(site) or GITLAB_CALL_RE.match(site)
    return match.group(3) if match else None


def _sha256_from_package(package_dir, variables):
    for key in ("SOURCE_HASH", "HASH"):
        value = variables.get(key, "").strip('"')
        match = re.search(r"[0-9a-fA-F]{64}", value)
        if match:
            return match.group(0).lower()
    for path in sorted(package_dir.glob("*.hash")):
        match = re.search(r"\b([0-9a-fA-F]{64})\b", path.read_text(encoding="utf-8", errors="replace"))
        if match:
            return match.group(1).lower()
    return None


def _dependencies(variables):
    value = variables.get("DEPENDENCIES", "")
    return tuple(
        item
        for item in re.findall(r"[A-Za-z0-9_.+-]+", value)
        if item != "host" and not item.startswith("host-")
    )


def _package_description(package_dir, symbol, name):
    help_text = _package_help(package_dir, symbol)
    if help_text:
        return shorten_package_description(help_text)
    prompt = _package_prompt(package_dir, symbol)
    if prompt:
        return shorten_package_description(prompt)
    return name


def _package_prompt(package_dir, symbol):
    config = package_dir / "Config.in"
    if not config.is_file():
        return ""
    token = symbol
    matched = False
    for raw in config.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.strip().startswith("config ") and token in raw:
            matched = True
            continue
        if matched and raw.strip().startswith(("bool ", "tristate ")) and '"' in raw:
            return raw.split('"', 1)[1].rsplit('"', 1)[0]
    return ""


def _package_help(package_dir, symbol):
    config = package_dir / "Config.in"
    if not config.is_file():
        return ""
    matched = False
    in_help = False
    help_indent = None
    collected = []
    for raw in config.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if stripped.startswith("config ") and symbol in raw.split():
            matched = True
            continue
        if not matched:
            continue
        if stripped.startswith(("config ", "menuconfig ", "comment ", "menu ", "if ", "endif", "source ")):
            break
        if not in_help:
            if stripped == "help":
                in_help = True
                help_indent = len(raw) - len(raw.lstrip())
            continue
        if not stripped:
            if collected:
                collected.append("")
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent <= help_indent:
            break
        collected.append(stripped)
    return " ".join(part for part in collected if part)


def _write_package(root, package):
    package_dir = Path(root) / "packages" / package.name
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    output_paths, install_path, materialize_symlinks = _package_layout(package)
    script = _build_script(package.name, package.make_target, materialize_symlinks)
    (package_dir / "sbuild.py").write_text(script, encoding="utf-8")
    data = {
        "schema_version": 1,
        "kind": "package",
        "name": package.name,
        "version": package.version,
        "type": "executable",
        "description": package.description,
        "depends": list(package.dependencies),
        "source": _source_metadata(package),
        "build": {
            "python": {
                "script": "sbuild.py",
                "outputs": list(output_paths),
                "upstream_markers": [],
            }
        },
        "install": {"path": install_path},
    }
    (package_dir / "package.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _write_generated_package_kconfig(root, package.name)
    (package_dir / "import.yaml").write_text(
        yaml.safe_dump(
            {
                "origin": {
                    "system": "buildroot",
                    "symbol": package.symbol,
                    "package_path": _origin_package_path(root, package.directory),
                },
                "source": {
                    "type": package.source_type,
                    "url": package.url,
                    "archive": package.archive if package.source_type == "archive" else None,
                    "revision": package.revision,
                    "sha256": package.sha256,
                },
                "build": {
                    "make_target": package.make_target,
                    "outputs": list(output_paths),
                    "install_path": install_path,
                    "materialize_symlinks": materialize_symlinks,
                },
                "warnings": ["build was not verified during import"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _origin_package_path(root, directory):
    package_dir = Path(directory)
    project_root = Path(root)
    try:
        relative = package_dir.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise SmartBuildError(
            "BUILDROOT",
            f"imported package path is outside the project: {package_dir}",
        ) from exc
    if relative.is_absolute() or ".." in relative.parts:
        raise SmartBuildError(
            "BUILDROOT",
            f"imported package path is not project-relative: {package_dir}",
        )
    return relative.as_posix()


def _package_layout(package):
    if package.name == "tinyssh" and package.make_target == "cross-compile":
        return (("/usr/sbin", "/usr/share/man"), "/usr/sbin/tinysshd", True)
    return (("/usr/bin",), f"/usr/bin/{package.name}", False)


def _build_script(name, make_target=None, materialize_symlinks=False):
    build_commands = (
        f'commands.append(["make", {make_target!r}])'
        if make_target
        else 'commands.append(["make"])'
    )
    symlink_support = """
import shutil
import stat


def materialize_internal_symlinks(root):
    root = os.path.realpath(root)
    for candidate in sorted(Path(root).rglob("*")):
        if not candidate.is_symlink():
            continue
        target = candidate.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"package symlink escapes staging directory: {candidate}") from exc
        if not target.is_file():
            raise RuntimeError(f"package symlink target is not a file: {candidate}")
        mode = stat.S_IMODE(target.stat().st_mode)
        candidate.unlink()
        shutil.copy2(target, candidate)
        candidate.chmod(mode)
""" if materialize_symlinks else ""
    materialize_call = "materialize_internal_symlinks(stage)" if materialize_symlinks else ""
    return f'''#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
{symlink_support}

source = os.environ["SMART_BUILD_SOURCE_DIR"]
stage = os.environ["SMART_BUILD_STAGE_DIR"]
env = os.environ.copy()
env.setdefault("DESTDIR", stage)
commands = []
configure = os.path.join(source, "configure")
if os.path.isfile(configure):
    commands.append([configure, "--host=" + env["SMART_BUILD_TARGET"], "--prefix=/usr"])
{build_commands}
commands.append(["make", "DESTDIR=" + stage, "install"])
for command in commands:
    subprocess.run(command, cwd=source, env=env, check=True)
{materialize_call}
'''


def _build_make_target(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    targets = []
    in_build_commands = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if re.match(r"^define\s+[A-Za-z0-9_]+_BUILD_CMDS\s*$", stripped):
            in_build_commands = True
            continue
        if in_build_commands and stripped == "endef":
            break
        if not in_build_commands or "$(MAKE)" not in stripped:
            continue
        tokens = stripped.rstrip("\\").split()
        make_index = tokens.index("$(MAKE)")
        skip_option_value = False
        for token in tokens[make_index + 1 :]:
            if skip_option_value:
                skip_option_value = False
                continue
            if token in {"-C", "-f", "--directory", "--file"}:
                skip_option_value = True
                continue
            if token.startswith("-") or "$" in token or "=" in token:
                continue
            if re.fullmatch(r"[A-Za-z0-9_.+-]+", token):
                targets.append(token)
    return targets[0] if len(targets) == 1 else None


def _source_metadata(package):
    if package.source_type == "git":
        return {
            "type": "git",
            "url": package.url,
            "commit": package.revision or package.version,
            "local_files": ["sbuild.py"],
            "files": ["sbuild.py"],
        }
    return {
        "type": "archive",
        "url": package.url,
        "archive": package.archive,
        "strip_root": True,
        "allow_unverified": package.sha256 is None,
        **({"sha256": package.sha256} if package.sha256 else {}),
        "local_files": ["sbuild.py"],
        "files": ["sbuild.py"],
    }


def _existing_owners(root):
    result = {}
    never_import = load_never_import_names(root)
    registry = Path(root) / "packages" / ".imports" / "buildroot-ownership.yaml"
    if registry.is_file():
        data = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
        result.update(data.get("symbols", {}))
    for metadata in load_all_package_metadata(root):
        if metadata.name in never_import:
            continue
        result.setdefault(
            "BR2_PACKAGE_" + symbol_token(metadata.name),
            {"owner": "native", "package": metadata.name},
        )
    for symbol in list(result):
        package = str(result[symbol].get("package", ""))
        if package in never_import or _symbol_name(symbol) in never_import:
            result.pop(symbol, None)
    return result


def _buildroot_owned_symbols(buildroot, owners):
    """Add Buildroot symbol aliases for existing smart-build package directories."""
    result = dict(owners)
    package_names = {
        metadata.name
        for metadata in load_all_package_metadata(Path(buildroot).parent)
    }
    for package_name in package_names:
        package_dirs = [
            path
            for path in (Path(buildroot) / "package").rglob("*")
            if path.is_dir() and path.name in {package_name, package_name.replace("-", "_")}
        ]
        for package_dir in package_dirs:
            for config in package_dir.glob("Config.in*"):
                if not config.is_file() or config.is_symlink():
                    continue
                text = config.read_text(encoding="utf-8", errors="replace")
                for symbol in re.findall(r"^\s*config\s+(BR2_PACKAGE_[A-Za-z0-9_]+)\s*$", text, re.MULTILINE):
                    result.setdefault(symbol, {"owner": "native", "package": package_name})
    return result


def _write_ownership(root, owners, never_import=None):
    blocked = set(never_import or ())
    cleaned = {}
    for symbol, record in owners.items():
        package = str(record.get("package", ""))
        if package in blocked or _symbol_name(symbol) in blocked:
            continue
        if not (Path(root) / "packages" / package).is_dir():
            continue
        cleaned[symbol] = record
    path = Path(root) / "packages" / ".imports" / "buildroot-ownership.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"symbols": cleaned}, sort_keys=True), encoding="utf-8")


def _force_owned_symbols(config, owners):
    if not Path(config).is_file():
        return
    locked = {symbol for symbol, record in owners.items() if record.get("owner") in {"native", "imported"}}
    if not locked:
        return
    lines = Path(config).read_text(encoding="utf-8").splitlines()
    filtered = [
        line
        for line in lines
        if not any(line.strip() in {f"{symbol}=y", f"# {symbol} is not set"} for symbol in locked)
    ]
    filtered.extend(f"{symbol}=y" for symbol in sorted(locked))
    Path(config).write_text("\n".join(filtered) + "\n", encoding="utf-8")


def _prepare_menuconfig_source(root, destination, owners):
    locked = {symbol for symbol, record in owners.items() if record.get("owner") in {"native", "imported"}}
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        root,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns(".git", "output", "dl"),
    )
    if locked:
        _lock_buildroot_symbols(destination, locked)


def _lock_buildroot_symbols(source, symbols):
    symbol_pattern = "|".join(re.escape(symbol) for symbol in sorted(symbols))
    block_re = re.compile(
        rf"(?ms)^(?P<header>\s*(?:menu)?config\s+(?:{symbol_pattern})\b)(?P<body>.*?)(?=^\s*(?:menu)?config\s+|\Z)"
    )
    prompt_re = re.compile(r'^(\s*)(bool|tristate)\s+"[^"]*"\s*$', re.MULTILINE)
    for config in source.rglob("Config.in*"):
        if not config.is_file() or config.is_symlink():
            continue
        text = config.read_text(encoding="utf-8", errors="replace")

        def replace_block(match):
            body = match.group("body")
            updated, count = prompt_re.subn(r"\1\2", body, count=1)
            if count == 0:
                return match.group(0)
            if re.search(r"^\s*default\s+", updated, re.MULTILINE) is None:
                updated = "\n    default y" + updated
            return match.group("header") + updated

        updated = block_re.sub(replace_block, text)
        if updated != text:
            config.write_text(updated, encoding="utf-8")


def load_never_import_names(root):
    path = Path(root) / "packages" / ".imports" / "never-import.yaml"
    if not path.is_file():
        return frozenset()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("packages", [])
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise SmartBuildError("BUILDROOT", f"{path}: packages must be a list of names")
    return frozenset(item.strip() for item in raw)


def _write_generated_package_kconfig(root, package_name):
    generated = generate_package_kconfig_files(root)
    relative = f"packages/{package_name}/Kconfig"
    content = generated.get(relative)
    if not content:
        raise SmartBuildError("BUILDROOT", f"failed to generate native Kconfig for {package_name}")
    (Path(root) / relative).write_text(content, encoding="utf-8")


def _refresh_package_index(root):
    index = Path(root) / "packages" / "Kconfig"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(generate_package_kconfig_index(root), encoding="utf-8")


def _symbol_name(symbol):
    return symbol.removeprefix("BR2_PACKAGE_").lower().replace("_", "-")


def _progress(console, index, total, name):
    if console is not None:
        if hasattr(console, "isatty") and console.isatty():
            width = 24
            filled = width * index // total if total else width
            console.write(f"\r\033[2Kimport: [{'#' * filled}{'-' * (width - filled)}] {index}/{total} {name}")
            console.flush()
        else:
            console.write(f"import: [{index}/{total}] {name}\n")


def _result(console, index, total, item):
    if console is None:
        return
    colors = {"success": "32", "skipped": "33", "failed": "31"}
    line = f"{item.status}: {item.name} ({item.message})"
    if hasattr(console, "isatty") and console.isatty() and os.environ.get("NO_COLOR") is None:
        line = f"\033[{colors[item.status]}m{line}\033[0m"
    if hasattr(console, "isatty") and console.isatty():
        console.write("\r\033[2K" + line + "\n")
    else:
        console.write(line + "\n")
    console.flush()


def _run_command(command, cwd, env):
    try:
        return subprocess.run(command, cwd=cwd, env=env, check=False, text=True)
    except OSError as exc:
        raise SmartBuildError("CONFIG", f"failed to run Buildroot command: {exc}") from exc
