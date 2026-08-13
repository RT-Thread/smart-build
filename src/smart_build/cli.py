import argparse
import math
import shutil
import sys

from . import menuconfig
from .cache import Cache
from .config import DEFAULT_MACHINE, load_defconfig, load_workspace_config
from .configure import configure_target
from .doctor import host_tools_record, run_doctor, toolchain_manifest_record
from .domains.qemu import ALLOWED_ROOTFS_IMAGES, run_qemu_smoke
from .domains.toolchain import (
    install_toolchain,
    resolve_toolchain,
    resolve_toolchain_selection,
    toolchain_statuses,
)
from .errors import SmartBuildError
from .machines import load_machine
from .manifest import task_manifest_sections, write_manifest
from .paths import BuildPaths, board_defconfig_path
from .scheduler import Scheduler
from .tasks import TaskGraph, create_default_plan, tasks_for_target


def build_parser():
    parser = argparse.ArgumentParser(prog="smart-build")
    parser.add_argument(
        "--machine",
        dest="global_machine",
        default=None,
        help="target machine",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    doctor = subparsers.add_parser("doctor", help="check host environment")
    doctor.add_argument("--machine", default=None, help="target machine")

    build = subparsers.add_parser("build", help="build selected target")
    build.add_argument("target", nargs="?", default="all", help="target name")
    build.add_argument("--machine", default=None, help="target machine")
    build.add_argument("--jobs", type=_positive_int, default=None, help="parallel jobs")
    build.add_argument("--dry-run", action="store_true", help="print planned tasks")
    build.add_argument(
        "--verbose",
        action="store_true",
        help="print detailed task and build logs to console",
    )

    graph = subparsers.add_parser("graph", help="print task graph")
    graph.add_argument("--machine", default=None, help="target machine")

    menuconfig_parser = subparsers.add_parser("menuconfig", help="configure machine build options")
    menuconfig_parser.add_argument("--machine", default=None, help="target machine")

    configure_parser = subparsers.add_parser("configure", help="configure one build target")
    configure_parser.add_argument("target", help="kernel, busybox, bootloader, or package:<name>")
    configure_parser.add_argument("--machine", default=None, help="target machine")

    qemu_smoke = subparsers.add_parser("qemu-smoke", help="run QEMU smoke check")
    qemu_smoke.add_argument("--machine", default=None, help="target machine")
    qemu_smoke.add_argument(
        "--timeout",
        type=_positive_float,
        default=30,
        help="seconds to wait for QEMU boot output",
    )

    toolchain = subparsers.add_parser("toolchain", help="manage cross toolchains")
    toolchain_subparsers = toolchain.add_subparsers(dest="toolchain_command", metavar="action")
    toolchain_list = toolchain_subparsers.add_parser("list", help="list machine toolchain versions")
    toolchain_list.add_argument("--machine", default=None, help="target machine")
    toolchain_install = toolchain_subparsers.add_parser("install", help="download a machine toolchain")
    toolchain_install.add_argument("--machine", default=None, help="target machine")
    toolchain_install.add_argument("--version", default=None, help="toolchain version")
    toolchain_install.add_argument("--yes", action="store_true", help="confirm download")
    qemu_smoke.add_argument(
        "--rootfs-image",
        choices=ALLOWED_ROOTFS_IMAGES,
        default=None,
        help="rootfs image for virt QEMU machines",
    )

    for command in ("clean", "distclean", "download-clean"):
        subparsers.add_parser(command, help=f"run {command}")

    return parser


def _positive_int(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--jobs must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("--jobs must be a positive integer")
    return number


def _positive_float(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--timeout must be a positive number") from exc
    if number <= 0 or not math.isfinite(number):
        raise argparse.ArgumentTypeError("--timeout must be a positive number")
    return number


def _selected_machine(args):
    machine = getattr(args, "machine", None)
    if machine is not None:
        return machine
    global_machine = getattr(args, "global_machine", None)
    if global_machine is not None:
        return global_machine
    workspace_machine = load_workspace_config(".").get("MACHINE")
    if workspace_machine:
        return workspace_machine
    return DEFAULT_MACHINE


def _run_doctor(args):
    machine = _selected_machine(args)
    paths = BuildPaths.for_machine(machine)
    metadata = load_machine(paths.root, machine)
    print(f"doctor: machine={machine}")
    for check in run_doctor(paths, machine=metadata):
        print(f"ok: {check.name} {check.detail}")
    return 0


def _run_build(args):
    machine = _selected_machine(args)
    paths = BuildPaths.for_machine(machine)
    metadata = None if args.dry_run else _load_machine_if_available(paths, machine)
    toolchain = None if args.dry_run else _resolve_or_offer_toolchain(metadata, paths)
    graph = TaskGraph(
        tasks_for_target(
            args.target,
            metadata if metadata is not None else machine,
            paths,
            resolve_real=not args.dry_run,
            toolchain=toolchain,
            jobs=args.jobs,
            verbose=args.verbose,
        )
    )
    if args.dry_run:
        _print_dry_run(args.target, machine, paths, graph)
        return 0
    if graph.has_only_placeholders():
        raise SmartBuildError(
            "BUILD",
            f"target {args.target} for machine={machine} only has placeholder tasks; use --dry-run",
        )
    placeholder_ids = [task.id for task in graph.topological_order() if task.placeholder]
    if placeholder_ids:
        raise SmartBuildError(
            "BUILD",
            "target {target} for machine={machine} includes placeholder tasks: {tasks}; "
            "use --dry-run or build a completed target".format(
                target=args.target,
                machine=machine,
                tasks=", ".join(placeholder_ids),
            ),
        )
    paths.ensure_execution_dirs()
    results = Scheduler(
        graph,
        Cache(paths.stamps_dir),
        jobs=args.jobs or 1,
        verbose=args.verbose,
        display_path=paths.display_path,
    ).run()
    toolchain_record = (
        toolchain.manifest_record()
        if toolchain is not None
        else toolchain_manifest_record(machine=metadata)
    )
    ordered_tasks = graph.topological_order()
    extra_sections = {"toolchain": toolchain_record}
    extra_sections.update(task_manifest_sections(ordered_tasks))
    write_manifest(
        paths.manifest_path,
        config={"MACHINE": machine, "TARGET": args.target},
        tasks=ordered_tasks,
        artifacts=_collect_artifacts(graph),
        host_tools=_host_tools_record_for_cli(metadata),
        extra_sections=extra_sections,
    )
    _print_build_summary(results)
    return 0


def _run_graph(args):
    machine = _selected_machine(args)
    paths = BuildPaths.for_machine(machine)
    graph = TaskGraph(_graph_tasks(machine, paths))
    print(f"graph: machine={machine}")
    for index, task in enumerate(graph.topological_order(), start=1):
        deps = ", ".join(task.deps) if task.deps else "-"
        outputs = ", ".join(paths.display_path(path) for path in task.outputs) or "-"
        print(f"{index}. {task.id} [{task.run_class}] deps={deps} outputs={outputs}")
    return 0


def _graph_tasks(machine, paths):
    defconfig = board_defconfig_path(paths.root, paths.machine)
    if defconfig.exists() and load_defconfig(defconfig).get("ROOTFS") == "none":
        return tasks_for_target("qemu-script", machine, paths, resolve_real=False)
    return tasks_for_target("all", machine, paths, resolve_real=False)


def _run_menuconfig(args):
    machine = _selected_machine(args)
    paths = BuildPaths.for_machine(machine)
    defconfig = menuconfig.run_menuconfig(paths)
    print(f"menuconfig: wrote {paths.display_path(defconfig)}")
    return 0


def _run_configure(args):
    machine = _selected_machine(args)
    paths = BuildPaths.for_machine(machine)
    result = configure_target(paths, args.target)
    if result.updated:
        updated = ", ".join(paths.display_path(path) for path in result.updated)
        print(f"configure: target={result.target} updated={updated}")
    else:
        print(f"configure: target={result.target} completed")
    return 0


def _run_qemu_smoke(args):
    machine = _selected_machine(args)
    paths = BuildPaths.for_machine(machine)
    log_path = run_qemu_smoke(
        paths,
        timeout_seconds=args.timeout,
        rootfs_image=args.rootfs_image,
    )
    print(f"qemu-smoke: pass machine={machine} log={paths.display_path(log_path)}")
    return 0


def _run_toolchain(args):
    machine = _selected_machine(args)
    paths = BuildPaths.for_machine(machine)
    metadata = load_machine(paths.root, machine)
    if args.toolchain_command == "list":
        print(f"toolchain: machine={machine}")
        for status in toolchain_statuses(metadata):
            selected = "selected" if status.selected else "available"
            source = status.source or "-"
            root = str(status.root) if status.root is not None else "-"
            downloadable = "downloadable" if status.downloadable else "manual-only"
            print(
                f"toolchain: version={status.version or '<default>'} package={status.package} "
                f"state={status.state} source={source} {downloadable} {selected} root={root}"
            )
        return 0
    if args.toolchain_command == "install":
        selection = resolve_toolchain_selection(metadata, version=args.version)
        try:
            existing = resolve_toolchain(machine=metadata, version=args.version)
        except SmartBuildError as exc:
            if exc.code != "TOOLCHAIN" or not _toolchain_not_found(exc):
                raise
        else:
            print(
                f"toolchain: already installed version={existing.configured_version} "
                f"source={existing.source} root={existing.root}"
            )
            return 0
        if not selection.release.downloadable:
            raise SmartBuildError(
                "TOOLCHAIN",
                f"toolchain version {selection.release.version} has no download source; "
                "install it with Env SDK or select a downloadable version",
            )
        if not args.yes and not _is_interactive():
            raise SmartBuildError(
                "TOOLCHAIN",
                "toolchain install requires confirmation; rerun with --yes in a non-interactive environment",
            )
        if not args.yes and not _confirm_toolchain_install(selection):
            print("toolchain: download cancelled")
            return 1
        toolchain = install_toolchain(metadata, version=args.version, output=sys.stdout)
        print(f"toolchain: installed version={toolchain.configured_version} root={toolchain.root}")
        return 0
    raise SmartBuildError("CONFIG", "toolchain requires an action: list or install")


def _run_clean(command, args):
    machine = _selected_machine(args)
    paths = BuildPaths.for_machine(machine)
    if command == "clean":
        return _clean_machine(paths)
    if command == "distclean":
        return _remove_tree(command, paths.root / "build", paths)
    if command == "download-clean":
        return _remove_tree(command, paths.root / "downloads", paths)
    raise SmartBuildError("CONFIG", f"unsupported clean command: {command}")


def _clean_machine(paths):
    machine_dir = paths.machine_dir
    if not machine_dir.exists():
        print(f"clean: nothing to remove for machine={paths.machine}")
        return 0
    _require_child_of(paths.root / "build", machine_dir, "machine build directory")
    shutil.rmtree(machine_dir)
    print(f"clean: removed {paths.display_path(machine_dir)}")
    return 0


def _remove_tree(command, path, paths):
    if not path.exists():
        print(f"{command}: nothing to remove")
        return 0
    _require_child_of(paths.root, path, command)
    shutil.rmtree(path)
    print(f"{command}: removed {paths.display_path(path)}")
    return 0


def _require_child_of(root, path, label):
    root = root.resolve()
    target = path.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SmartBuildError("CONFIG", f"refusing to remove {label} outside {root}: {path}") from exc


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "build":
            return _run_build(args)
        if args.command == "graph":
            return _run_graph(args)
        if args.command == "menuconfig":
            return _run_menuconfig(args)
        if args.command == "configure":
            return _run_configure(args)
        if args.command == "qemu-smoke":
            return _run_qemu_smoke(args)
        if args.command == "toolchain":
            return _run_toolchain(args)
        if args.command in ("clean", "distclean", "download-clean"):
            return _run_clean(args.command, args)
        parser.print_help()
        return 0
    except SmartBuildError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return _exit_code_for_error(exc.code)


def _print_dry_run(target, machine, paths, graph):
    print(f"dry-run: planned tasks target={target} machine={machine}")
    for task in graph.topological_order():
        deps = ", ".join(task.deps) if task.deps else "-"
        outputs = ", ".join(paths.display_path(path) for path in task.outputs) or "-"
        print(f"task: {task.id}")
        print(f"  domain: {task.domain}")
        print(f"  action: {task.action}")
        print(f"  run_class: {task.run_class}")
        print(f"  deps: {deps}")
        print(f"  outputs: {outputs}")


def _collect_artifacts(graph):
    artifacts = []
    for task in graph.topological_order():
        artifacts.extend(task.outputs)
    return artifacts


def _print_build_summary(results):
    counts = {"success": 0, "skipped": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    print(
        "build: complete success={success} skipped={skipped}".format(
            success=counts.get("success", 0),
            skipped=counts.get("skipped", 0),
        )
    )


def _load_machine_if_available(paths, machine):
    try:
        return load_machine(paths.root, machine)
    except SmartBuildError:
        if (paths.root / "boards").exists():
            raise
        return None


def _resolve_toolchain_for_cli(metadata):
    if metadata is None:
        return resolve_toolchain()
    return resolve_toolchain(machine=metadata)


def _resolve_or_offer_toolchain(metadata, paths):
    try:
        return _resolve_toolchain_for_cli(metadata)
    except SmartBuildError as exc:
        if exc.code != "TOOLCHAIN" or not _toolchain_not_found(exc):
            raise
        selection = resolve_toolchain_selection(metadata)
        if not selection.release.downloadable:
            raise
        if not _is_interactive() or not _confirm_toolchain_install(selection):
            raise SmartBuildError(
                "TOOLCHAIN",
                f"{exc}; run ./smart-build toolchain install --machine {paths.machine} --yes",
            ) from exc
        return install_toolchain(metadata, output=sys.stdout)


def _toolchain_not_found(error):
    return "not found" in str(error).lower() and "searched:" in str(error).lower()


def _is_interactive():
    return bool(getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stdout, "isatty", lambda: False)())


def _confirm_toolchain_install(selection):
    release = selection.release
    print(
        f"Toolchain {release.package} version {release.version} is missing.\n"
        f"Download from {release.url}\n"
        f"Install into {selection.machine.root / 'downloads' / 'toolchains' / (release.package + '-' + release.version)}? [y/N] ",
        end="",
        file=sys.stderr,
    )
    try:
        answer = input().strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _host_tools_record_for_cli(metadata):
    if metadata is None:
        return host_tools_record()
    return host_tools_record(machine=metadata)


def _exit_code_for_error(code):
    if code in {"CONFIG", "SCHEMA"}:
        return 2
    if code == "TOOLCHAIN":
        return 3
    if code == "SOURCE":
        return 4
    if code in {"BUILD", "PACKAGE", "IPKG", "ROOTFS", "IMAGE", "DEPLOY"}:
        return 5
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
