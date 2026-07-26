import os
import re

from SCons.Script import *


_build_env = None
_build_dir = None
_build_options = {}
_group_index = 0


def ConfigureBuild(env, build_dir, options):
    global _build_env
    global _build_dir
    global _build_options
    global _group_index

    _build_env = env
    _build_dir = str(build_dir)
    _build_options = dict(options)
    _group_index = 0


def GetDepend(depend):
    names = [depend] if isinstance(depend, str) else list(depend or [])
    names = [name for name in names if name]
    return all(_enabled(_build_options.get(name)) for name in names)


def GetCurrentDir():
    sconscript = File("SConscript")
    return os.path.dirname(sconscript.rfile().abspath)


def DefineGroup(name, src, depend, **parameters):
    global _group_index

    if _build_env is None or _build_dir is None:
        raise RuntimeError("RT-Thread SConscript environment is not configured")
    if not GetDepend(depend):
        return []

    group_env = _build_env.Clone()
    cpppath = parameters.pop("CPPPATH", [])
    cppdefines = parameters.pop("CPPDEFINES", [])
    if cpppath:
        group_env.AppendUnique(CPPPATH=list(cpppath))
    if cppdefines:
        group_env.AppendUnique(CPPDEFINES=list(cppdefines))
    if parameters:
        group_env.AppendUnique(**parameters)

    group_name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name))
    group_dir = os.path.join(_build_dir, "objects", f"{_group_index:02d}-{group_name}")
    _group_index += 1
    objects = []
    for index, source in enumerate(Flatten(src)):
        source_node = source if hasattr(source, "get_path") else File(source)
        stem = os.path.splitext(os.path.basename(str(source_node)))[0]
        target = os.path.join(group_dir, f"{index:03d}-{stem}.o")
        objects.extend(group_env.Object(target=target, source=source_node))
    return objects


def _enabled(value):
    return str(value).strip().lower() in {"y", "m", "1", "yes", "true"}
