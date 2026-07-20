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
from .domains.toolchain import resolve_toolchain
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
    build.add_argument("--verbose", action="store_true", help="print task logs to console")

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
    toolchain = None if args.dry_run else _resolve_toolchain_for_cli(metadata)
    graph = TaskGraph(
        tasks_for_target(
            args.target,
            metadata if metadata is not None else machine,
            paths,
            resolve_real=not args.dry_run,
            toolchain=toolchain,
            jobs=args.jobs,
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
