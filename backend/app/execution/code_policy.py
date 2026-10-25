"""Static (AST) safety policy for AI-generated experiment code.

This is the first gate; the sandbox bootstrap enforces the same rules again at runtime.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from dataclasses import dataclass, field

ALLOWED_IMPORTS = frozenset(
    {"experimentos_sdk", "math", "statistics", "random", "json", "itertools", "functools",
     "collections", "time", "typing"}
)
SDK_API = frozenset(
    {"set_seed", "plan_evaluations", "run_configuration", "finish", "load_dataset", "RAGConfig",
     "evaluate_rag", "RETRIEVERS", "RERANKERS"}
)
BANNED_NAMES = frozenset(
    {"eval", "exec", "compile", "open", "__import__", "globals", "locals", "vars", "getattr",
     "setattr", "delattr", "input", "breakpoint", "exit", "quit", "help", "memoryview",
     "os", "sys", "subprocess", "socket", "builtins", "importlib", "shutil", "pathlib", "ctypes"}
)
BANNED_ATTRS = frozenset(
    {"system", "popen", "environ", "getenv", "putenv", "remove", "unlink", "rmdir", "rename",
     "modules", "spawn", "fork", "kill", "load_module", "exec_module", "f_globals", "f_locals",
     "gi_frame", "cr_frame", "tb_frame", "mro", "subclasses"}
)
MAX_SOURCE_BYTES = 20_000
MAX_LINES = 300


@dataclass
class PolicyResult:
    syntax_ok: bool
    syntax_error: str = ""
    violations: list[str] = field(default_factory=list)
    calls_finish: bool = False
    calls_run_configuration: bool = False

    @property
    def ok(self) -> bool:
        return self.syntax_ok and not self.violations and self.calls_finish and self.calls_run_configuration


def check_code(source: str) -> PolicyResult:
    if len(source.encode()) > MAX_SOURCE_BYTES or source.count("\n") > MAX_LINES:
        return PolicyResult(syntax_ok=True, violations=[f"code exceeds size limit ({MAX_SOURCE_BYTES} bytes / {MAX_LINES} lines)"])
    try:
        tree = ast.parse(source, filename="experiment.py")
    except SyntaxError as e:
        return PolicyResult(syntax_ok=False, syntax_error=f"line {e.lineno}: {e.msg}")

    res = PolicyResult(syntax_ok=True)
    v = res.violations
    # Names bound to modules, so `json.codecs` / `math.sys`-style traversal into other modules
    # (a classic sandbox escape route) can be rejected statically.
    module_aliases = {a.asname or a.name: a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                      for a in n.names if a.name in ALLOWED_IMPORTS}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    v.append(f"line {node.lineno}: import of '{alias.name}' is not permitted")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in ALLOWED_IMPORTS:
                v.append(f"line {node.lineno}: import from '{node.module}' is not permitted")
            elif node.module == "experimentos_sdk":
                for alias in node.names:
                    if alias.name not in SDK_API:
                        v.append(f"line {node.lineno}: '{alias.name}' is not part of the experimentos_sdk API")
            else:
                for alias in node.names:
                    if _is_submodule(node.module, alias.name):
                        v.append(f"line {node.lineno}: importing module '{node.module}.{alias.name}' is not permitted")
            if any(a.name == "*" for a in node.names):
                v.append(f"line {node.lineno}: wildcard imports are not permitted")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or node.id.startswith("__"):
                v.append(f"line {node.lineno}: use of '{node.id}' is not permitted")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in BANNED_ATTRS:
                v.append(f"line {node.lineno}: attribute '{node.attr}' is not permitted")
            elif isinstance(node.value, ast.Name) and node.value.id in module_aliases:
                mod = module_aliases[node.value.id]
                if mod == "experimentos_sdk" and node.attr not in SDK_API:
                    v.append(f"line {node.lineno}: '{node.attr}' is not part of the experimentos_sdk API")
                elif mod != "experimentos_sdk" and _is_submodule(mod, node.attr):
                    v.append(f"line {node.lineno}: reaching module '{mod}.{node.attr}' is not permitted")
        elif isinstance(node, ast.While):
            # Experiments iterate over planned configurations; unbounded loops only burn the timeout.
            v.append(f"line {node.lineno}: while-loops are not permitted (iterate over configurations instead)")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            v.append(f"line {node.lineno}: async code is not permitted")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name == "finish":
                res.calls_finish = True
            elif name == "run_configuration":
                res.calls_run_configuration = True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            v.append(f"line {node.lineno}: dunder strings are not permitted")
    res.violations = sorted(set(v), key=lambda s: int(s.split(":")[0].split()[-1]) if s.startswith("line") else 0)
    return res


def _is_submodule(module: str, attr: str) -> bool:
    """True if ``module.attr`` is itself a module (only allow-listed stdlib modules are imported here)."""
    try:
        return inspect.ismodule(getattr(importlib.import_module(module), attr, None))
    except ImportError:
        return False
