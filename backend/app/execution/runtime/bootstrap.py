"""Sandbox bootstrap for AI-generated experiment code.

Runs in a *separate* Python process (``python -I -B bootstrap.py ...``) started by
the local runner, or as the container entrypoint of a Nebius Serverless AI Job.

Layers of defence (in addition to static AST validation done before submission):

1. Process isolation   — separate interpreter in isolated mode (-I: no user site,
                         no PYTHON* env vars), started with an empty environment
                         and a throw-away working directory.
2. Resource limits     — CPU seconds, address space, file size and open-file limits
                         via ``resource`` on POSIX. (Windows has no ``resource``
                         module: the parent enforces a wall-clock timeout and
                         output cap — LOCAL DEVELOPMENT MODE only.)
3. Restricted builtins — no open/eval/exec/compile/input/breakpoint/globals/vars...;
                         ``__import__`` only resolves allow-listed modules.
4. Runtime audit hook  — PEP 578 hook vetoes process spawning, sockets, ctypes,
                         filesystem mutation/listing, env mutation, and any file
                         write outside the working directory.
"""

from __future__ import annotations

import argparse
import builtins
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ALLOWED_MODULES = frozenset(
    {"experimentos_sdk", "math", "statistics", "random", "json", "itertools", "functools",
     "collections", "time", "typing"}
)

BLOCKED_EVENT_PREFIXES = (
    "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork",
    "os.forkpty", "os.kill", "os.killpg", "os.remove", "os.unlink", "os.rename",
    "os.rmdir", "os.removedirs", "os.chmod", "os.chown", "os.link", "os.symlink",
    "os.truncate", "os.putenv", "os.unsetenv", "os.listdir", "os.scandir", "os.walk",
    "os.startfile", "os.chdir", "shutil.", "socket.", "ctypes.", "winreg.", "_winapi.",
    "msvcrt.", "urllib.", "http.", "ftplib.", "smtplib.", "webbrowser.", "pty.",
    "sys.addaudithook", "sys.setprofile", "sys.settrace", "cpython.remote_debugger",
)


def _apply_resource_limits(cpu_seconds: int, memory_mb: int) -> str:
    try:
        import resource  # POSIX only
    except ImportError:
        return "resource limits unavailable on this platform (parent enforces wall-clock timeout)"
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    mem = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    return f"cpu={cpu_seconds}s memory={memory_mb}MB fsize=16MB nofile=64"


def _install_audit_hook(workdir: str) -> None:
    workdir = os.path.realpath(workdir)
    read_roots = tuple(
        os.path.realpath(p) for p in {sys.prefix, sys.base_prefix, sys.exec_prefix, HERE} if p
    )

    def hook(event: str, args: tuple) -> None:
        if event.startswith(BLOCKED_EVENT_PREFIXES):
            raise PermissionError(f"sandbox: operation {event!r} is not permitted")
        if event == "import":
            name = (args[0] or "").split(".")[0]
            if name not in ALLOWED_MODULES and args[0] not in sys.modules:
                raise PermissionError(f"sandbox: import of {args[0]!r} is not permitted")
        elif event == "open":
            path, mode = args[0], args[1] if len(args) > 1 else "r"
            if path is None or isinstance(path, int):
                return
            real = os.path.realpath(os.fsdecode(path))
            writing = mode is not None and any(c in str(mode) for c in "wax+")
            if real == workdir or real.startswith(workdir + os.sep):
                return
            if not writing and real.startswith(read_roots):
                return
            raise PermissionError(f"sandbox: file access to {real!r} is not permitted")

    sys.addaudithook(hook)


def _safe_builtins() -> dict:
    banned = {
        "open", "eval", "exec", "compile", "input", "breakpoint", "globals", "locals", "vars",
        "help", "exit", "quit", "memoryview", "__loader__", "__spec__", "copyright", "credits",
        "license", "delattr", "setattr", "getattr",
    }
    safe = {k: v for k, v in vars(builtins).items() if k not in banned}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level != 0 or name.split(".")[0] not in ALLOWED_MODULES:
            raise ImportError(f"sandbox: import of {name!r} is not permitted")
        return real_import(name, globals, locals, fromlist, level)

    safe["__import__"] = guarded_import
    return safe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--experiment-id", default="unknown")
    ap.add_argument("--cpu-seconds", type=int, default=300)
    ap.add_argument("--memory-mb", type=int, default=1024)
    ns = ap.parse_args()

    os.makedirs(ns.workdir, exist_ok=True)
    limits = _apply_resource_limits(ns.cpu_seconds, ns.memory_mb)

    # Everything that needs the filesystem happens *before* the sandbox is sealed.
    with open(ns.code, encoding="utf-8") as fh:
        source = fh.read()
    with open(ns.dataset, encoding="utf-8") as fh:
        dataset = json.load(fh)
    for mod in sorted(ALLOWED_MODULES):
        __import__(mod)
    import experimentos_sdk.runtime as rt

    rt._configure(ns.experiment_id, dataset, ns.workdir)
    code = compile(source, "experiment.py", "exec")

    print("@@EOS " + json.dumps({"type": "sandbox", "limits": limits, "python": sys.version.split()[0]}), flush=True)
    _install_audit_hook(ns.workdir)

    namespace = {"__name__": "__main__", "__builtins__": _safe_builtins()}
    try:
        exec(code, namespace)  # noqa: S102 — this *is* the sandbox entrypoint
    except SystemExit as e:
        return int(e.code or 0)
    except BaseException as e:  # report, never leak a traceback with host paths
        print("@@EOS " + json.dumps({"type": "error", "error": f"{type(e).__name__}: {e}"}), flush=True)
        return 1
    if not rt._STATE["finished"]:
        print("@@EOS " + json.dumps({"type": "error", "error": "experiment did not call finish()"}), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
