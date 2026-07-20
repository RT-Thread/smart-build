#!/usr/bin/env python3
"""Build RT-Thread MicroPython as a Smart rootfs executable."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


UPSTREAM_MARKERS = (
    "SConscript",
    "py/mpstate.h",
    "py/runtime.c",
    "port/mpy_main.c",
    "port/mpconfigport.h",
    "port/genhdr/qstrdefs.generated.h",
    "port/genhdr/mpversion.h",
)

BYTE_QSTR_METHODS = (
    "MP_QSTR___int__",
    "MP_QSTR___ne__",
)

SKIP_PY_SOURCES = {
    "asmarm.c",
    "asmthumb.c",
    "asmx64.c",
    "asmx86.c",
    "asmxtensa.c",
    "emitinlinethumb.c",
    "emitinlinextensa.c",
    "emitnarm.c",
    "emitnative.c",
    "emitnthumb.c",
    "emitnx64.c",
    "emitnx86.c",
    "emitnxtensa.c",
    "emitnxtensawin.c",
    "modcmath.c",
    "modmath.c",
    "modthread.c",
    "nlrpowerpc.c",
    "nlrthumb.c",
    "nlrx64.c",
    "nlrx86.c",
    "nlrxtensa.c",
    "objcomplex.c",
    "objfloat.c",
}


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def required_path(name: str) -> Path:
    return Path(required_env(name))


def run(command: list[str], cwd: Path, capture_output: bool = False) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=os.environ.copy(),
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.STDOUT if capture_output else None,
    )
    if capture_output and completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _require_upstream_tree(source_dir: Path) -> None:
    missing = [marker for marker in UPSTREAM_MARKERS if not (source_dir / marker).is_file()]
    if missing:
        raise SystemExit("prepared MicroPython source is incomplete: " + ", ".join(missing))


def _prepare_port(source_dir: Path, port_dir: Path) -> None:
    if port_dir.exists():
        shutil.rmtree(port_dir)
    (port_dir / "genhdr").mkdir(parents=True, exist_ok=True)
    _write_smart_qstrdefs(
        source_dir / "port" / "genhdr" / "qstrdefs.generated.h",
        port_dir / "genhdr" / "qstrdefs.generated.h",
    )
    shutil.copy2(source_dir / "port" / "genhdr" / "mpversion.h", port_dir / "genhdr" / "mpversion.h")
    (port_dir / "genhdr" / "moduledefs.h").write_text("", encoding="utf-8")
    (port_dir / "mphalport.h").write_text(MPHALPORT_H, encoding="utf-8")
    (port_dir / "mpconfigport.h").write_text(MPCONFIGPORT_H, encoding="utf-8")
    (port_dir / "main.c").write_text(MAIN_C, encoding="utf-8")


def _write_smart_qstrdefs(source: Path, destination: Path) -> None:
    lines = source.read_text(encoding="utf-8").splitlines()
    qdefs = [line for line in lines if line.startswith("QDEF(")]
    by_name = {_qdef_name(line): line for line in qdefs}
    missing = [name for name in BYTE_QSTR_METHODS if name not in by_name]
    if missing:
        raise SystemExit("prepared MicroPython qstr table is incomplete: " + ", ".join(missing))

    promoted = list(BYTE_QSTR_METHODS)
    rewritten = []
    inserted = False
    for line in lines:
        if not line.startswith("QDEF("):
            rewritten.append(line)
            continue
        name = _qdef_name(line)
        if not inserted:
            rewritten.extend(by_name[item] for item in promoted)
            inserted = True
        if name in promoted:
            continue
        rewritten.append(line)

    destination.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def _qdef_name(line: str) -> str:
    end = line.find(",")
    if end == -1:
        raise SystemExit(f"invalid MicroPython qstr definition: {line}")
    return line[len("QDEF("):end]


def _micro_python_sources(source_dir: Path) -> list[Path]:
    sources = []
    for source in sorted((source_dir / "py").glob("*.c")):
        if source.name in SKIP_PY_SOURCES:
            continue
        sources.append(source)
    nlr_setjmp = source_dir / "py" / "nlrsetjmp.c"
    if nlr_setjmp not in sources:
        sources.insert(1, nlr_setjmp)
    return sources


MPCONFIGPORT_H = r'''
#ifndef SMART_BUILD_MICROPY_MPCONFIGPORT_H
#define SMART_BUILD_MICROPY_MPCONFIGPORT_H

#include <stdint.h>
#include <stddef.h>
#include <sys/types.h>

#define MICROPY_ALLOC_PATH_MAX (256)
#define MICROPY_QSTR_BYTES_IN_HASH (1)
#define MICROPY_ENABLE_COMPILER (1)
#define MICROPY_ENABLE_GC (1)
#define MICROPY_GC_ALLOC_THRESHOLD (0)
#define MICROPY_ENABLE_FINALISER (0)
#define MICROPY_ENABLE_PYSTACK (0)
#define MICROPY_STACK_CHECK (0)
#define MICROPY_KBD_EXCEPTION (0)
#define MICROPY_ENABLE_SCHEDULER (0)
#define MICROPY_PY_ASYNC_AWAIT (0)
#define MICROPY_REPL_EVENT_DRIVEN (0)
#define MICROPY_HELPER_REPL (0)
#define MICROPY_HELPER_LEXER_UNIX (0)
#define MICROPY_ENABLE_SOURCE_LINE (1)
#define MICROPY_ERROR_REPORTING (MICROPY_ERROR_REPORTING_TERSE)
#define MICROPY_CPYTHON_COMPAT (1)
#define MICROPY_LONGINT_IMPL (MICROPY_LONGINT_IMPL_MPZ)
#define MICROPY_FLOAT_IMPL (MICROPY_FLOAT_IMPL_NONE)
#define MICROPY_PY_BUILTINS_COMPLEX (0)
#define MICROPY_PY_BUILTINS_STR_UNICODE (0)
#define MICROPY_PY_BUILTINS_BYTEARRAY (1)
#define MICROPY_PY_BUILTINS_MEMORYVIEW (0)
#define MICROPY_PY_BUILTINS_SET (1)
#define MICROPY_PY_BUILTINS_SLICE (1)
#define MICROPY_PY_BUILTINS_PROPERTY (1)
#define MICROPY_PY_BUILTINS_ENUMERATE (1)
#define MICROPY_PY_BUILTINS_FILTER (1)
#define MICROPY_PY_BUILTINS_REVERSED (1)
#define MICROPY_PY_BUILTINS_MIN_MAX (1)
#define MICROPY_PY_BUILTINS_POW3 (1)
#define MICROPY_PY_BUILTINS_HELP (0)
#define MICROPY_PY_COLLECTIONS (1)
#define MICROPY_PY_COLLECTIONS_ORDEREDDICT (1)
#define MICROPY_PY_MATH (0)
#define MICROPY_PY_CMATH (0)
#define MICROPY_PY_GC (1)
#define MICROPY_PY_ARRAY (1)
#define MICROPY_PY_STRUCT (1)
#define MICROPY_PY_SYS (1)
#define MICROPY_PY_SYS_MODULES (1)
#define MICROPY_PY_SYS_EXIT (1)
#define MICROPY_PY_IO (0)
#define MICROPY_PY_THREAD (0)
#define MICROPY_PY_MICROPYTHON_MEM_INFO (0)
#define MICROPY_PY_MICROPYTHON_STACK_USE (0)
#define MICROPY_USE_INTERNAL_ERRNO (0)
#define MICROPY_USE_INTERNAL_PRINTF (0)
#define MICROPY_MODULE_FROZEN (0)
#define MICROPY_MODULE_FROZEN_STR (0)
#define MICROPY_MODULE_FROZEN_MPY (0)
#define MICROPY_ENABLE_EXTERNAL_IMPORT (0)
#define MICROPY_READER_POSIX (0)
#define MICROPY_READER_VFS (0)
#define MICROPY_EMIT_X64 (0)
#define MICROPY_EMIT_X86 (0)
#define MICROPY_EMIT_THUMB (0)
#define MICROPY_EMIT_INLINE_THUMB (0)
#define MICROPY_EMIT_ARM (0)
#define MICROPY_EMIT_XTENSA (0)
#define MICROPY_EMIT_INLINE_XTENSA (0)
#define MICROPY_EMIT_XTENSAWIN (0)
#define MICROPY_NLR_SETJMP (1)
#define MICROPY_PORT_ROOT_POINTERS const char *readline_hist[8];
#define MICROPY_PORT_BUILTINS
#define MICROPY_PORT_BUILTIN_MODULES
#define MICROPY_PORT_CONSTANTS
#define MICROPY_HW_BOARD_NAME "RT-Thread Smart"
#define MICROPY_HW_MCU_NAME "smart-rootfs"

typedef intptr_t mp_int_t;
typedef uintptr_t mp_uint_t;
typedef long mp_off_t;

#endif
'''.lstrip()


MPHALPORT_H = r'''
#ifndef SMART_BUILD_MICROPY_MPHALPORT_H
#define SMART_BUILD_MICROPY_MPHALPORT_H

#include <stddef.h>
#include <stdint.h>

#endif
'''.lstrip()


MAIN_C = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "py/compile.h"
#include "py/gc.h"
#include "py/runtime.h"
#include "py/stackctrl.h"

static char heap[256 * 1024];

void nlr_jump_fail(void *val)
{
    (void)val;
    abort();
}

void NORETURN __fatal_error(const char *msg)
{
    fputs(msg, stderr);
    abort();
}

void gc_collect(void)
{
    gc_collect_start();
    gc_collect_end();
}

uintptr_t mp_hal_stdio_poll(uintptr_t poll_flags)
{
    return poll_flags;
}

int mp_hal_stdin_rx_chr(void)
{
    return getchar();
}

void mp_hal_stdout_tx_strn(const char *str, size_t len)
{
    fwrite(str, 1, len, stdout);
}

void mp_hal_stdout_tx_strn_cooked(const char *str, size_t len)
{
    fwrite(str, 1, len, stdout);
}

void mp_hal_stdout_tx_str(const char *str)
{
    fputs(str, stdout);
}

void mp_hal_delay_ms(mp_uint_t ms)
{
    usleep((useconds_t)ms * 1000U);
}

void mp_hal_delay_us(mp_uint_t us)
{
    usleep((useconds_t)us);
}

mp_uint_t mp_hal_ticks_ms(void)
{
    return (mp_uint_t)(clock() * 1000 / CLOCKS_PER_SEC);
}

mp_uint_t mp_hal_ticks_us(void)
{
    return (mp_uint_t)(clock() * 1000000 / CLOCKS_PER_SEC);
}

mp_uint_t mp_hal_ticks_cpu(void)
{
    return (mp_uint_t)clock();
}

uint64_t mp_hal_time_ns(void)
{
    return (uint64_t)mp_hal_ticks_us() * 1000ULL;
}

static int execute_code(const char *code)
{
    nlr_buf_t nlr;

    if (nlr_push(&nlr) == 0)
    {
        mp_lexer_t *lex = mp_lexer_new_from_str_len(MP_QSTR__lt_stdin_gt_, code, strlen(code), 0);
        qstr source_name = lex->source_name;
        mp_parse_tree_t parse_tree = mp_parse(lex, MP_PARSE_FILE_INPUT);
        mp_obj_t module_fun = mp_compile(&parse_tree, source_name, false);

        mp_call_function_0(module_fun);
        nlr_pop();
        return 0;
    }

    mp_obj_print_exception(&mp_plat_print, (mp_obj_t)nlr.ret_val);
    return 1;
}

int main(int argc, char **argv)
{
    const char *code = NULL;

    for (int index = 1; index < argc; ++index)
    {
        if (strcmp(argv[index], "-c") == 0 && index + 1 < argc)
        {
            code = argv[++index];
        }
    }

    if (code == NULL)
    {
        fputs("MicroPython smart rootfs port requires -c <code>\n", stderr);
        return 2;
    }

    mp_stack_ctrl_init();
    gc_init(heap, heap + sizeof(heap));
    mp_init();
    int result = execute_code(code);
    mp_deinit();
    return result;
}
'''.lstrip()


def main() -> int:
    source_dir = required_path("SMART_BUILD_SOURCE_DIR")
    work_dir = required_path("SMART_BUILD_WORK_DIR")
    output = required_path("SMART_BUILD_OUTPUT")
    cc = required_env("CC")

    _require_upstream_tree(source_dir)
    port_dir = work_dir / "smart-port"
    _prepare_port(source_dir, port_dir)
    output.parent.mkdir(parents=True, exist_ok=True)

    sources = _micro_python_sources(source_dir)
    command = [
        cc,
        "-Os",
        "-ffunction-sections",
        "-fdata-sections",
        "-include",
        "alloca.h",
        f"-DMP_CONFIGFILE=\"{port_dir / 'mpconfigport.h'}\"",
        f"-DMICROPY_MPHALPORT_H=\"{port_dir / 'mphalport.h'}\"",
        "-I",
        str(port_dir),
        "-I",
        str(work_dir),
        "-I",
        str(source_dir),
        "-I",
        str(source_dir / "py"),
        *[str(path) for path in sources],
        str(port_dir / "main.c"),
        "-Wl,--gc-sections",
        "-lm",
        "-o",
        str(output),
    ]
    run(command, cwd=work_dir, capture_output=True)
    output.chmod(0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
