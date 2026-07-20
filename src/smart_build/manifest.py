import json
from copy import deepcopy
from pathlib import Path

from .cache import path_record


def write_manifest(path, config, tasks, artifacts, host_tools, extra_sections=None):
    manifest_path = Path(path)
    artifact_records = [_artifact_record(artifact) for artifact in artifacts]
    data = {
        "schema_version": 1,
        "config": dict(config),
        "tasks": [task.manifest_record() for task in tasks],
        "artifacts": artifact_records,
        "host_tools": {name: str(value) for name, value in host_tools.items()},
        "host_tool_checksums": {
            name: _optional_checksum(value) for name, value in host_tools.items()
        },
        "checksums": {
            record["path"]: record.get("sha256")
            for record in artifact_records
            if record.get("sha256")
        },
    }
    if extra_sections:
        for section, value in extra_sections.items():
            data[section] = value
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def task_manifest_sections(tasks):
    sections = {}
    apps = []
    packages = []
    for task in tasks:
        fields = task.manifest_fields
        if "app" in fields:
            app = deepcopy(fields["app"])
            if task.outputs:
                app["artifact"] = path_record(task.outputs[0])
            apps.append(app)
        if "package" in fields:
            package = deepcopy(fields["package"])
            if task.outputs:
                package["artifact"] = path_record(task.outputs[0])
                package["checksum"] = package["artifact"].get("sha256")
            packages.append(package)
        if "rootfs" in fields:
            sections["rootfs"] = fields["rootfs"]
        if "images" in fields:
            sections["images"] = fields["images"]
        if "busybox" in fields:
            sections.setdefault("busybox", {}).update(fields["busybox"])
        if "busybox_rootfs" in fields:
            sections.setdefault("busybox_rootfs", {}).update(fields["busybox_rootfs"])
        if "busybox_images" in fields:
            sections.setdefault("busybox_images", {}).update(fields["busybox_images"])
        if "qemu" in fields:
            sections.setdefault("qemu", {}).update(fields["qemu"])
    if apps:
        sections["apps"] = apps
    if packages:
        sections["packages"] = packages
    return sections


def _optional_checksum(path):
    record = path_record(path)
    return record.get("sha256")


def _artifact_record(path):
    record = path_record(path)
    record["checksum"] = {"sha256": record.get("sha256")}
    return record
