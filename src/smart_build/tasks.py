import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from .cache import path_record
from .config import load_defconfig, load_workspace_config, resolve_rootfs_selection, workspace_config_path
from .errors import SmartBuildError
from .machines import Machine
from .paths import board_defconfig_path, validate_safe_name
from .progress import report_items, report_phase


VALID_RUN_CLASSES = {"fetch", "build", "serial"}
VALID_CACHE_POLICIES = {"inputs", "never"}


@dataclass(frozen=True)
class Task:
    id: str
    domain: str
    action: str
    inputs: tuple = ()
    outputs: tuple = ()
    deps: tuple = ()
    workdir: Path = Path(".")
    env: dict = field(default_factory=dict)
    run_class: str = "build"
    cache_policy: str = "inputs"
    log_path: Path = Path("task.log")
    executor: object = None
    command: tuple = ()
    cache_extra: dict = field(default_factory=dict)
    manifest_fields: dict = field(default_factory=dict)
    placeholder: bool = False

    def __post_init__(self):
        if not self.id:
            raise SmartBuildError("TASK", "task id is required")
        if not self.domain:
            raise SmartBuildError("TASK", f"task {self.id} missing domain")
        if not self.action:
            raise SmartBuildError("TASK", f"task {self.id} missing action")
        if self.run_class not in VALID_RUN_CLASSES:
            raise SmartBuildError("TASK", f"task {self.id} has unsupported run_class {self.run_class}")
        if self.cache_policy not in VALID_CACHE_POLICIES:
            raise SmartBuildError(
                "TASK",
                f"task {self.id} has unsupported cache_policy {self.cache_policy}",
            )
        object.__setattr__(self, "inputs", tuple(Path(path) for path in self.inputs))
        object.__setattr__(self, "outputs", tuple(Path(path) for path in self.outputs))
        object.__setattr__(self, "deps", tuple(self.deps))
        object.__setattr__(self, "workdir", Path(self.workdir))
        object.__setattr__(self, "env", dict(self.env))
        object.__setattr__(self, "log_path", Path(self.log_path))
        object.__setattr__(self, "command", tuple(str(part) for part in self.command))
        object.__setattr__(self, "cache_extra", dict(self.cache_extra))
        object.__setattr__(self, "manifest_fields", dict(self.manifest_fields))

    def command_hash(self):
        payload = {
            "command": self.command,
            "env": {key: self.env[key] for key in sorted(self.env)},
            "cache_extra": _sorted_json_value(self.cache_extra),
            "executor": _executor_fingerprint(self.executor),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def manifest_record(self):
        output_records = {str(path): path_record(path) for path in self.outputs}
        manifest_fields = _manifest_fields_with_output_checksums(
            self.manifest_fields,
            self.outputs,
            output_records,
        )
        return {
            "id": self.id,
            "domain": self.domain,
            "action": self.action,
            "inputs": [str(path) for path in self.inputs],
            "outputs": [str(path) for path in self.outputs],
            "deps": list(self.deps),
            "workdir": str(self.workdir),
            "env": {key: self.env[key] for key in sorted(self.env)},
            "run_class": self.run_class,
            "cache_policy": self.cache_policy,
            "log_path": str(self.log_path),
            "command_hash": self.command_hash(),
            "manifest_fields": _sorted_json_value(manifest_fields),
            "output_checksums": {
                path: record.get("sha256")
                for path, record in output_records.items()
                if record.get("sha256")
            },
        }


class TaskGraph:
    def __init__(self, tasks):
        self.tasks = list(tasks)
        self.by_id = {}
        for task in self.tasks:
            if task.id in self.by_id:
                raise SmartBuildError("TASK", f"duplicate task id {task.id}")
            self.by_id[task.id] = task

    def topological_order(self):
        order_index = {task.id: index for index, task in enumerate(self.tasks)}
        missing = []
        indegree = {task.id: 0 for task in self.tasks}
        children = {task.id: [] for task in self.tasks}

        for task in self.tasks:
            for dep in task.deps:
                if dep not in self.by_id:
                    missing.append((task.id, dep))
                    continue
                indegree[task.id] += 1
                children[dep].append(task.id)

        if missing:
            details = ", ".join(f"{task_id}->{dep}" for task_id, dep in missing)
            raise SmartBuildError("TASK", f"missing task dependencies: {details}")

        ready = [task.id for task in self.tasks if indegree[task.id] == 0]
        result = []

        while ready:
            task_id = ready.pop(0)
            result.append(self.by_id[task_id])
            for child_id in sorted(children[task_id], key=lambda item: order_index[item]):
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    ready.append(child_id)
            ready.sort(key=lambda item: order_index[item])

        if len(result) != len(self.tasks):
            blocked = [task_id for task_id, degree in indegree.items() if degree > 0]
            raise SmartBuildError("TASK", f"cycle detected in task graph: {', '.join(blocked)}")

        return result

    def has_only_placeholders(self):
        return bool(self.tasks) and all(task.placeholder for task in self.tasks)


def create_default_plan(
    machine,
    paths,
    resolve_real=False,
    toolchain=None,
    real_minirootfs=False,
    real_busybox_rootfs=False,
    real_qemu_script=False,
    force_minirootfs_image=False,
    jobs=None,
    rootfs_selection=None,
    verbose=False,
):
    machine_metadata = machine if isinstance(machine, Machine) else machine
    rootfs_disabled = rootfs_selection is not None and rootfs_selection.rootfs == "none"
    rootfs_task_ids = _rootfs_task_ids(rootfs_selection)
    if force_minirootfs_image:
        rootfs_task_ids = ("minirootfs:image",)
    include_package_rootfs = not rootfs_disabled and (
        real_minirootfs or "minirootfs:image" in rootfs_task_ids or "rootfs:image" in rootfs_task_ids
    )
    include_busybox_rootfs = not rootfs_disabled and (
        real_busybox_rootfs or "busybox-rootfs:image" in rootfs_task_ids
    )
    if resolve_real and toolchain is None:
        from .domains.toolchain import resolve_toolchain

        toolchain = resolve_toolchain(machine=machine_metadata)
    config_task = _config_load_task(paths) if resolve_real else _placeholder_task(
        "config:load",
        "config",
        "load",
        [],
        [paths.machine_dir / "config.json"],
        [],
        paths,
    )
    toolchain_task = _toolchain_check_task(
        paths,
        toolchain=toolchain,
        machine=machine_metadata,
    ) if resolve_real else _placeholder_task(
        "toolchain:check",
        "toolchain",
        "check",
        [],
        [paths.staging_dir / "host" / "toolchain.ok"],
        ["config:load"],
        paths,
    )
    if resolve_real:
        from .domains.kernel import kernel_tasks
        from .domains.sources import rt_thread_source_task

        report_phase("analyzing kernel")
        rt_thread_task = rt_thread_source_task(paths)
        kernel_plan_tasks = kernel_tasks(paths, toolchain=toolchain, verbose=verbose)
    else:
        rt_thread_task = _placeholder_task(
            "source:rt-thread",
            "source",
            "rt-thread",
            [],
            [paths.stamps_dir / "sources" / "rt-thread.ok"],
            ["config:load"],
            paths,
            run_class="fetch",
        )
        kernel_package_task = _placeholder_task(
            "kernel:packages:update",
            "kernel",
            "packages-update",
            [],
            [paths.stamps_dir / "kernel-packages.ok"],
            ["toolchain:check", "source:rt-thread"],
            paths,
            run_class="serial",
        )
        kernel_task = _placeholder_task(
            "kernel:build",
            "kernel",
            "build",
            [],
            [paths.images_dir / "rtthread.bin"],
            ["kernel:packages:update"],
            paths,
            run_class="build",
        )
        kernel_plan_tasks = [kernel_package_task, kernel_task]

    minirootfs_tasks = (
        _minirootfs_tasks(paths, toolchain, selection=rootfs_selection, force_minirootfs=force_minirootfs_image)
        if resolve_real and real_minirootfs and include_package_rootfs
        else []
    )
    busybox_tasks = (
        _busybox_rootfs_tasks(paths, toolchain, jobs=jobs, selection=rootfs_selection)
        if resolve_real and real_busybox_rootfs and include_busybox_rootfs
        else []
    )
    rootfs_task = None if not include_package_rootfs else minirootfs_tasks[-2] if minirootfs_tasks else _placeholder_task(
        "rootfs:stage",
        "rootfs",
        "stage",
        [],
        [paths.staging_dir / "rootfs"],
        ["toolchain:check"],
        paths,
        run_class="serial",
    )
    package_rootfs_task_id = _package_rootfs_image_task_id(rootfs_selection, force_minirootfs_image)
    package_rootfs_output = _package_rootfs_image_output(paths, rootfs_selection, force_minirootfs_image)
    package_rootfs_task = None if not include_package_rootfs else minirootfs_tasks[-1] if minirootfs_tasks else _placeholder_task(
        package_rootfs_task_id,
        "rootfs",
        "image",
        [],
        [package_rootfs_output],
        ["rootfs:stage"],
        paths,
        run_class="serial",
    )
    busybox_plan_tasks = [] if not include_busybox_rootfs else busybox_tasks if busybox_tasks else [
        _placeholder_task(
            "busybox-rootfs:image",
            "rootfs",
            "image",
            [],
            [paths.images_dir / "busybox-rootfs.img"],
            _busybox_placeholder_deps(include_package_rootfs),
            paths,
            run_class="serial",
        )
    ]

    if resolve_real and real_qemu_script:
        from .domains.qemu import qemu_script_task

        qemu_task = qemu_script_task(paths)
        if rootfs_selection is not None and not rootfs_disabled:
            qemu_task = replace(qemu_task, deps=tuple(_qemu_placeholder_deps(rootfs_task_ids)))
        elif rootfs_disabled:
            qemu_task = replace(qemu_task, deps=("kernel:build",))
    else:
        qemu_task = _placeholder_task(
            "qemu-script:generate",
            "deploy",
            "qemu-script",
            [],
            [paths.machine_dir / "run_qemu_nographic.sh"],
            _qemu_placeholder_deps(rootfs_task_ids),
            paths,
            run_class="serial",
        )

    image_task = _image_assemble_task(paths, rootfs_task_ids=rootfs_task_ids) if resolve_real else _placeholder_task(
        "image:assemble",
        "image",
        "assemble",
        [],
        [paths.images_dir / "system.img"],
        ("kernel:build", *rootfs_task_ids),
        paths,
        run_class="serial",
    )

    return [
        config_task,
        toolchain_task,
        rt_thread_task,
        *kernel_plan_tasks,
        *minirootfs_tasks[:-2],
        *([rootfs_task] if rootfs_task is not None else []),
        *([package_rootfs_task] if package_rootfs_task is not None else []),
        *busybox_plan_tasks,
        *([] if rootfs_disabled else [image_task]),
        qemu_task,
    ]


def tasks_for_target(
    target,
    machine,
    paths,
    resolve_real=False,
    toolchain=None,
    jobs=None,
    verbose=False,
):
    report_phase("resolving configuration")
    rootfs_selection = _rootfs_selection_for_target(target, paths)
    _reject_disabled_rootfs_target(target, paths, selection=rootfs_selection)
    _reject_unsupported_package_target(target, paths, selection=rootfs_selection)
    rootfs_task_ids = _rootfs_task_ids(rootfs_selection)
    if target == "minirootfs":
        rootfs_task_ids = ("minirootfs:image",)
    resolved_toolchain = toolchain
    if resolve_real and resolved_toolchain is None:
        from .domains.toolchain import resolve_toolchain

        resolved_toolchain = resolve_toolchain(machine=machine)
    graph = TaskGraph(
        create_default_plan(
            machine,
            paths,
            resolve_real=resolve_real,
            toolchain=resolved_toolchain,
            real_minirootfs=target == "minirootfs"
            or (
                target in {"all", "rootfs", "full-rootfs", "qemu-script"}
                and rootfs_selection is not None
                and {"minirootfs:image", "rootfs:image"}.intersection(rootfs_task_ids)
            ),
            real_busybox_rootfs=target == "busybox-rootfs"
            or (
                target in {"all", "rootfs", "qemu-script"}
                and rootfs_selection is not None
                and "busybox-rootfs:image" in rootfs_task_ids
            ),
            real_qemu_script=(target in {"qemu-script", "all"}),
            force_minirootfs_image=target == "minirootfs",
            jobs=jobs,
            rootfs_selection=rootfs_selection,
            verbose=verbose,
        )
        + _app_tasks(target, paths, resolve_real=resolve_real, toolchain=resolved_toolchain)
        + _package_tasks(target, paths, resolve_real=resolve_real, toolchain=resolved_toolchain)
    )
    target_ids = _target_task_ids(target, rootfs_selection=rootfs_selection)
    selected_ids = _dependency_closure(graph, target_ids)
    return [task for task in graph.topological_order() if task.id in selected_ids]


def _placeholder_task(task_id, domain, action, inputs, outputs, deps, paths, run_class="serial"):
    return Task(
        id=task_id,
        domain=domain,
        action=action,
        inputs=inputs,
        outputs=outputs,
        deps=deps,
        workdir=paths.work_dir / task_id.replace(":", "-"),
        env={"MACHINE": paths.machine},
        run_class=run_class,
        cache_policy="never",
        log_path=paths.logs_dir / f"{task_id.replace(':', '-')}.log",
        executor=_placeholder_executor,
        manifest_fields={"placeholder": True},
        placeholder=True,
    )


def _config_load_task(paths):
    defconfig = board_defconfig_path(paths.root, paths.machine)
    workspace_config = workspace_config_path(paths.root)
    inputs = [defconfig]
    if workspace_config.is_file():
        inputs.append(workspace_config)
    return Task(
        id="config:load",
        domain="config",
        action="load",
        inputs=inputs,
        outputs=[paths.machine_dir / "config.json"],
        deps=[],
        workdir=paths.work_dir / "config-load",
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="inputs",
        log_path=paths.logs_dir / "config-load.log",
        executor=_config_load_executor,
        manifest_fields={"defconfig": str(defconfig)},
    )


def _config_load_executor(task, log):
    values = load_defconfig(task.inputs[0])
    workspace_values = load_workspace_config(task.outputs[0].parents[2])
    if workspace_values.get("MACHINE") == task.env.get("MACHINE"):
        values.update(workspace_values)
        log.write(f"loaded workspace config: {workspace_config_path(task.outputs[0].parents[2])}\n")
    log.write(f"loaded defconfig: {task.inputs[0]}\n")
    task.outputs[0].write_text(
        json.dumps(values, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _toolchain_check_task(paths, toolchain=None, machine=None):
    from .domains.toolchain import toolchain_task_fields

    fields = toolchain_task_fields(toolchain if toolchain is not None else machine)
    return Task(
        id="toolchain:check",
        domain="toolchain",
        action="check",
        inputs=[],
        outputs=[paths.staging_dir / "host" / "toolchain.ok"],
        deps=["config:load"],
        workdir=paths.work_dir / "toolchain-check",
        env={"MACHINE": paths.machine, **fields["env"]},
        run_class="serial",
        cache_policy="inputs",
        log_path=paths.logs_dir / "toolchain-check.log",
        executor=_toolchain_check_executor,
        cache_extra=fields["cache_extra"],
        manifest_fields=fields["manifest_fields"],
    )


def _toolchain_check_executor(task, log):
    record = task.manifest_fields.get("toolchain", {})
    log.write(f"toolchain: {record.get('root', '<unknown>')}\n")
    log.write(f"fingerprint: {record.get('fingerprint', '<unknown>')}\n")
    task.outputs[0].write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _image_assemble_task(paths, rootfs_task_ids=None):
    marker = paths.staging_dir / "image-assemble.ok"
    rootfs_task_ids = tuple(rootfs_task_ids or ("minirootfs:image", "busybox-rootfs:image"))
    image_inputs = _image_assemble_inputs(paths, rootfs_task_ids)
    return Task(
        id="image:assemble",
        domain="image",
        action="assemble",
        inputs=[
            paths.images_dir / "rtthread.bin",
            *image_inputs,
        ],
        outputs=[marker],
        deps=("kernel:build", *rootfs_task_ids),
        workdir=paths.work_dir / "image-assemble",
        env={"MACHINE": paths.machine},
        run_class="serial",
        cache_policy="never",
        log_path=paths.logs_dir / "image-assemble.log",
        executor=_image_assemble_executor,
        manifest_fields={
            "image_assemble": {
                "marker": str(marker),
                "kernel": str(paths.images_dir / "rtthread.bin"),
                **_image_assemble_manifest(paths, rootfs_task_ids),
            }
        },
    )


def _image_assemble_inputs(paths, rootfs_task_ids):
    images = []
    if "minirootfs:image" in rootfs_task_ids:
        images.append(paths.images_dir / "minirootfs.img")
    if "rootfs:image" in rootfs_task_ids:
        images.append(paths.images_dir / "rootfs.img")
    if "busybox-rootfs:image" in rootfs_task_ids:
        images.append(paths.images_dir / "busybox-rootfs.img")
    return images


def _image_assemble_manifest(paths, rootfs_task_ids):
    manifest = {}
    if "minirootfs:image" in rootfs_task_ids:
        manifest["minirootfs"] = str(paths.images_dir / "minirootfs.img")
    if "rootfs:image" in rootfs_task_ids:
        manifest["rootfs"] = str(paths.images_dir / "rootfs.img")
    if "busybox-rootfs:image" in rootfs_task_ids:
        manifest["busybox_rootfs"] = str(paths.images_dir / "busybox-rootfs.img")
    return manifest


def _image_assemble_executor(task, log):
    payload = dict(task.manifest_fields["image_assemble"])
    payload["inputs"] = [str(path) for path in task.inputs]
    task.outputs[0].write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    log.write(f"wrote image aggregate marker: {task.outputs[0]}\n")
    return 0


def _placeholder_executor(task, log):
    raise SmartBuildError(
        "BUILD",
        f"task {task.id} is a placeholder for later build domains; use --dry-run",
    )


def _executor_fingerprint(executor):
    if executor is None:
        return None
    return {
        "module": getattr(executor, "__module__", ""),
        "qualname": getattr(executor, "__qualname__", repr(executor)),
    }


def _manifest_fields_with_output_checksums(manifest_fields, outputs, output_records):
    fields = dict(manifest_fields)
    package = fields.get("package")
    if isinstance(package, dict) and outputs and not package.get("checksum"):
        output = str(outputs[0])
        checksum = output_records.get(output, {}).get("sha256")
        if checksum:
            package = dict(package)
            package["checksum"] = checksum
            fields["package"] = package
    return fields


def _sorted_json_value(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _target_task_ids(target, rootfs_selection=None):
    rootfs_task_ids = _rootfs_task_ids(rootfs_selection)
    if target == "all":
        return ["image:assemble", "qemu-script:generate"]
    if target == "kernel":
        return ["kernel:build"]
    if target == "rootfs":
        return list(rootfs_task_ids)
    if target == "minirootfs":
        return ["minirootfs:image"]
    if target == "full-rootfs":
        return ["rootfs:image"]
    if target == "busybox-rootfs":
        return ["busybox-rootfs:image"]
    if target == "qemu-script":
        return ["qemu-script:generate"]
    if target.startswith("app:") and target != "app:":
        app_name = _app_name_from_target(target)
        return [f"app:{app_name}:build"]
    if target.startswith("package:") and target != "package:":
        package_name = _package_name_from_target(target)
        return [f"ipkg:{package_name}:package"]
    raise SmartBuildError("CONFIG", f"unknown build target: {target}")


def _rootfs_task_ids(rootfs_selection):
    if rootfs_selection is None:
        return ("minirootfs:image", "busybox-rootfs:image")
    if rootfs_selection.rootfs == "none":
        return ()
    if rootfs_selection.rootfs == "basic":
        return ("busybox-rootfs:image",)
    if rootfs_selection.rootfs == "full":
        return ("rootfs:image",)
    return ("minirootfs:image",)


def _qemu_placeholder_deps(rootfs_task_ids):
    deps = ["kernel:build"]
    if "busybox-rootfs:image" in rootfs_task_ids:
        deps.append("busybox-rootfs:image")
    elif "rootfs:image" in rootfs_task_ids:
        deps.append("rootfs:image")
    elif "minirootfs:image" in rootfs_task_ids:
        deps.append("minirootfs:image")
    return deps


def _busybox_placeholder_deps(include_minirootfs):
    return ["rootfs:stage"] if include_minirootfs else ["toolchain:check"]


def _dependency_closure(graph, target_ids):
    selected = set()

    def visit(task_id):
        if task_id not in graph.by_id:
            raise SmartBuildError("CONFIG", f"unknown build target task: {task_id}")
        if task_id in selected:
            return
        selected.add(task_id)
        for dep in graph.by_id[task_id].deps:
            visit(dep)

    for target_id in target_ids:
        visit(target_id)
    return selected


def _rootfs_selection_for_target(target, paths):
    if target == "qemu-script":
        if _machine_defconfig_exists(paths):
            return resolve_rootfs_selection(paths.root, paths.machine)
        return None
    if target in {"all", "minirootfs", "rootfs", "full-rootfs", "busybox-rootfs"}:
        if not _machine_defconfig_exists(paths):
            return None
        return resolve_rootfs_selection(paths.root, paths.machine)
    if target.startswith("package:") and target != "package:":
        if not _machine_defconfig_exists(paths):
            return None
        return resolve_rootfs_selection(paths.root, paths.machine)
    return None


def _machine_defconfig_exists(paths):
    defconfig = board_defconfig_path(paths.root, paths.machine)
    return defconfig.exists()


def _reject_disabled_rootfs_target(target, paths, selection=None):
    if target not in {"all", "minirootfs", "rootfs", "busybox-rootfs"}:
        return
    if selection is None:
        return
    if selection.rootfs == "none":
        raise SmartBuildError(
            "CONFIG",
            f"target {target} is not supported for machine={paths.machine}: ROOTFS=none",
        )


def _reject_unsupported_package_target(target, paths, selection=None):
    if not target.startswith("package:") or target == "package:":
        return
    if selection is None:
        return
    if selection.rootfs == "none":
        raise SmartBuildError(
            "CONFIG",
            f"target {target} is not supported for machine={paths.machine}: ROOTFS=none",
        )


def _minirootfs_tasks(paths, toolchain, selection=None, force_minirootfs=False):
    from .domains.app import app_tasks
    from .domains.ipkg import ipkg_tasks
    from .domains.rootfs import rootfs_stage_task

    selection = selection if selection is not None else resolve_rootfs_selection(paths.root, paths.machine)
    if selection.rootfs == "none":
        return []
    if not selection.packages:
        raise SmartBuildError(
            "CONFIG",
            f"target minirootfs has no selected packages for machine={paths.machine}",
        )
    apps = app_tasks(paths, toolchain=toolchain)
    app_ipkgs = ipkg_tasks(paths, [task for task in apps if _has_ipkg_manifest(task)])
    app_package_by_dep = {package.deps[0]: package for package in app_ipkgs}
    app_build_tasks = []
    for build_task in apps:
        app_build_tasks.append(build_task)
        package = app_package_by_dep.get(build_task.id)
        if package is not None:
            app_build_tasks.append(package)

    report_phase("creating package tasks")
    package_build_tasks = _resolved_package_tasks(
        paths,
        _library_or_executable_selected_packages(paths, selection.selected_packages),
        toolchain,
    )
    packages = [*app_ipkgs, *[task for task in package_build_tasks if task.domain == "ipkg"]]
    busybox_base_tasks = (
        _busybox_rootfs_tasks(paths, toolchain, selection=selection, image=False)
        if selection.rootfs == "full" and not force_minirootfs
        else []
    )
    base_rootfs_task = busybox_base_tasks[-1] if busybox_base_tasks else None
    return [
        *app_build_tasks,
        *package_build_tasks,
        *busybox_base_tasks,
        rootfs_stage_task(paths, packages, toolchain=toolchain, base_rootfs_task=base_rootfs_task),
        _package_rootfs_image_task(paths, selection, force_minirootfs=force_minirootfs),
    ]


def _package_rootfs_image_task(paths, selection, force_minirootfs=False):
    from .domains.image import minirootfs_image_task, rootfs_image_task

    if selection.rootfs == "full" and not force_minirootfs:
        return rootfs_image_task(paths, selection=selection)
    return minirootfs_image_task(paths, selection=selection)


def _package_rootfs_image_task_id(rootfs_selection, force_minirootfs=False):
    if rootfs_selection is not None and rootfs_selection.rootfs == "full" and not force_minirootfs:
        return "rootfs:image"
    return "minirootfs:image"


def _package_rootfs_image_output(paths, rootfs_selection, force_minirootfs=False):
    if rootfs_selection is not None and rootfs_selection.rootfs == "full" and not force_minirootfs:
        return paths.images_dir / "rootfs.img"
    return paths.images_dir / "minirootfs.img"


def _busybox_rootfs_tasks(paths, toolchain, jobs=None, selection=None, image=True):
    from .domains.busybox import busybox_rootfs_tasks

    tasks = busybox_rootfs_tasks(paths, toolchain=toolchain, jobs=jobs, selection=selection)
    return tasks if image else tasks[:-1]


def _app_tasks(target, paths, resolve_real=False, toolchain=None):
    if not target.startswith("app:") or target == "app:":
        return []
    app_name = _app_name_from_target(target)
    if resolve_real:
        from .domains.app import app_task

        return [app_task(paths, app_name, toolchain=toolchain)]
    task_id = f"app:{app_name}:build"
    return [
        _placeholder_task(
            task_id,
            "app",
            "build",
            [],
            [paths.staging_dir / "apps" / app_name],
            ["toolchain:check"],
            paths,
            run_class="build",
        )
    ]


def _package_tasks(target, paths, resolve_real=False, toolchain=None):
    if not target.startswith("package:") or target == "package:":
        return []
    package_name = _package_name_from_target(target)
    if resolve_real:
        from .package_resolver import resolve_package_selection

        report_phase("creating package tasks")
        values = _package_config_values(paths)
        selection = resolve_package_selection(paths.root, [package_name], values)
        return _resolved_package_tasks(paths, selection.packages, toolchain)
    rtthread_scons = _uses_rtthread_scons_backend(paths, package_name)
    env_package_task = None
    build_deps = ["toolchain:check"]
    if rtthread_scons:
        env_package_task = _placeholder_task(
            f"package:{package_name}:env-packages",
            "package",
            "env-packages",
            [],
            [paths.stamps_dir / "packages" / f"{package_name}-env-packages.json"],
            ["toolchain:check", "source:rt-thread"],
            paths,
            run_class="fetch",
        )
        build_deps = [env_package_task.id]
    build_task = _placeholder_task(
        f"package:{package_name}:build",
        "package",
        "build",
        [],
        [paths.staging_dir / "packages" / package_name],
        build_deps,
        paths,
        run_class="build",
    )
    package_task = _placeholder_task(
        f"ipkg:{package_name}:package",
        "ipkg",
        "package",
        [paths.staging_dir / "packages" / package_name],
        [paths.packages_dir / f"{package_name}.ipk"],
        [build_task.id],
        paths,
        run_class="serial",
    )
    return [*([env_package_task] if env_package_task is not None else []), build_task, package_task]


def _uses_rtthread_scons_backend(paths, package_name):
    from .descriptions import load_description
    from .package_metadata import package_description_path

    description_path = package_description_path(paths.root, package_name)
    if not description_path.is_file():
        return False
    build = load_description(description_path).data.get("build")
    return isinstance(build, dict) and "rtthread_scons" in build


def _package_config_values(paths):
    defconfig = board_defconfig_path(paths.root, paths.machine)
    values = load_defconfig(defconfig) if defconfig.exists() else {}
    workspace_values = load_workspace_config(paths.root)
    if workspace_values.get("MACHINE") == paths.machine:
        values.update(workspace_values)
    return values


def _resolved_package_tasks(paths, selected_packages, toolchain):
    from .domains.ipkg import ipkg_tasks
    from .domains.package import package_task

    selected = list(reversed(tuple(selected_packages)))
    package_names = {package.name for package in selected}
    providers = {
        provided: package.name
        for package in selected
        for provided in package.metadata.provides
    }
    tasks = []
    total = len(selected)
    for index, package in enumerate(selected, start=1):
        report_items("tasks", index, total, package.name)
        build_task = package_task(paths, package.name, toolchain=toolchain)
        build_tasks = build_task if isinstance(build_task, list) else [build_task]
        dependency_ipkgs = _package_dependency_ipkg_ids(package, package_names, providers)
        build_tasks = _with_package_dependency_deps(paths, build_tasks, dependency_ipkgs)
        package_inputs = [task for task in build_tasks if _has_ipkg_manifest(task)]
        tasks.extend([*build_tasks, *ipkg_tasks(paths, package_inputs)])
    return tasks


def _library_or_executable_selected_packages(paths, selected_packages):
    from .descriptions import load_description
    from .package_metadata import package_description_path

    result = []
    total = len(selected_packages)
    for index, package in enumerate(selected_packages, start=1):
        report_items("packages", index, total, package.name)
        description = load_description(package_description_path(paths.root, package.name))
        if description.data.get("type") in {"library", "executable"}:
            result.append(package)
    return result


def _package_dependency_ipkg_ids(package, package_names, providers):
    deps = []
    for raw_dependency in (*package.metadata.depends, *package.metadata.selects):
        dependency = raw_dependency if raw_dependency in package_names else providers.get(raw_dependency)
        if dependency is None or dependency == package.name:
            continue
        task_id = f"ipkg:{dependency}:package"
        if task_id not in deps:
            deps.append(task_id)
    return deps


def _with_package_dependency_deps(paths, build_tasks, dependency_ipkgs):
    if not dependency_ipkgs:
        return build_tasks
    dependency_stage_inputs = [
        paths.staging_dir / "packages" / task_id.split(":", 2)[1]
        for task_id in dependency_ipkgs
    ]
    result = []
    for task in build_tasks:
        if _has_ipkg_manifest(task):
            result.append(replace(task, inputs=(*task.inputs, *dependency_stage_inputs), deps=(*task.deps, *dependency_ipkgs)))
        else:
            result.append(task)
    return result


def _has_ipkg_manifest(task):
    return any(key in task.manifest_fields for key in ("app", "library", "executable")) and (
        "name" in task.manifest_fields.get("app", {})
        or "name" in task.manifest_fields.get("library", {})
        or "name" in task.manifest_fields.get("executable", {})
    )


def _app_name_from_target(target):
    raw_name = target.split(":", 1)[1]
    try:
        return validate_safe_name(raw_name, "app")
    except SmartBuildError as exc:
        raise SmartBuildError("CONFIG", f"invalid app target {target}: {exc}") from exc


def _package_name_from_target(target):
    raw_name = target.split(":", 1)[1]
    try:
        return validate_safe_name(raw_name, "package")
    except SmartBuildError as exc:
        raise SmartBuildError("CONFIG", f"invalid package target {target}: {exc}") from exc
