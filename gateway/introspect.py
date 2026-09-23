"""§14: Jarvis reading his own implementation.

    *"Self-introspection is analytical authority, not modification authority.
    Reading and analyzing code does not automatically grant permission to
    change it."*

So this module **cannot write**. There is no open-for-write, no `Path.write_*`,
no `subprocess` that could invoke an editor, and `tests/test_jarvis_selfmod.py`
asserts that over the parsed source rather than by grepping for the word. The
separation is not a convention to be remembered at the call site; it is the
absence of the capability.

## What he may read, and what he may change

Two different questions, deliberately answered by two different lists.

`may_read` is nearly everything: the specification wants Jarvis able to trace
control flow, review configuration and tests, and compare behaviour against
requirements, and a Jarvis who cannot read `dba/` cannot understand what
happens to his own memory. What is withheld is **secrets and stores** - a token
file is not architecture, and a database read as a file is a way around the
DBA's entire access policy.

`may_modify` is much narrower: `gateway/` and `app/`, which are Jarvis's own
runtime. `dba/` and `backend/` are other systems that happen to share a
checkout; a change there is a change to somebody else's service made by an
agent nobody asked. Inside the modifiable roots there is a second, absolute
list - `GOVERNANCE` - and it is §16 in file form: the modules that decide what
Jarvis is allowed to do, and the tests that hold them to it.

## Why the governance list is not just "trust the approval gate"

Because §16 says *"JARVIS must never autonomously ... alter the approval
mechanism so that approval is no longer required"*, and an approval gate that
can itself be edited by an approved change is a gate with a handle on the
inside. Krish can still change those files; he is a person with a text editor.
What he cannot do is change them *by approving a Jarvis proposal*, because
`gateway/selfmod.py` refuses to draft one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Jarvis's own runtime. A proposal may touch these and nothing else.
MODIFIABLE_ROOTS = ("gateway", "app")

# §16, as files. Everything that decides what Jarvis may do, plus the tests
# that prove it. A proposal naming any of these is refused before it is
# written, at every boldness setting, approved or not.
GOVERNANCE = (
    "app/initiative.py",
    "app/initiative_config.py",
    "app/permissions.py",
    "app/admin_auth.py",
    "app/boundaries.py",
    "gateway/auth.py",
    "gateway/roles.py",
    "gateway/selfmod.py",
    # The sandbox a candidate is tested in. A sandbox Jarvis could rewrite is a
    # sandbox that reports whatever he needs it to report, and the approval gate
    # then turns on a verdict he produced.
    "gateway/candidate.py",
    "gateway/introspect.py",
    "gateway/failures.py",
    "config/initiative.yaml",
    "tests/test_boundaries.py",
    "tests/test_initiative.py",
    "tests/test_jarvis_selfmod.py",
)

# Not architecture, and not Jarvis's to read as files. A database read around
# the DBA is the DBA's access policy walked around from the filesystem.
UNREADABLE_SUFFIXES = (".db", ".db-wal", ".db-shm", ".sqlite", ".pem", ".key")
UNREADABLE_NAMES = (".env", "users.json", "sessions.json", "boot_config.json")
UNREADABLE_DIRECTORIES = ("data", ".git", "__pycache__", "node_modules")


class NotReadable(PermissionError):
    """Something outside what §14 grants, refused by name."""


class NotModifiable(PermissionError):
    """Something §16 or the scope decision puts out of reach."""


def _relative(path: str | Path) -> Path:
    """A repository-relative path, refusing anything that escapes the tree."""
    candidate = Path(path)
    absolute = (candidate if candidate.is_absolute()
                else PROJECT_ROOT / candidate).resolve()
    try:
        return absolute.relative_to(PROJECT_ROOT)
    except ValueError:
        raise NotReadable(
            f"{path!r} is outside the repository. Jarvis inspects his own "
            f"implementation, not the machine it runs on.") from None


def may_read(path: str | Path) -> tuple[bool, str]:
    relative = _relative(path)
    if relative.suffix in UNREADABLE_SUFFIXES:
        return False, (f"{relative} is a store or a key, not source. Reading a "
                       f"database as a file is the DBA's access policy walked "
                       f"around from the filesystem.")
    if relative.name in UNREADABLE_NAMES:
        return False, f"{relative} holds credentials or runtime secrets."
    if relative.parts and relative.parts[0] in UNREADABLE_DIRECTORIES:
        return False, f"{relative.parts[0]}/ is not part of the implementation."
    return True, ""


def may_modify(path: str | Path) -> tuple[bool, str]:
    """Whether a change proposal may name this file. §16 and the scope decision.

    Returns a reason on refusal rather than a bare False, because the proposal
    that named the file needs to be able to say why it was refused - and a
    reason Krish can read is what keeps the boundary from looking arbitrary."""
    relative = _relative(path)
    as_posix = relative.as_posix()

    if as_posix in GOVERNANCE:
        return False, (
            f"{as_posix} decides what Jarvis is permitted to do. §16: knowledge "
            f"may grow autonomously, authority may not. This file is not "
            f"reachable by an approved proposal either - an approval gate that "
            f"can be edited by an approved change is a gate with a handle on "
            f"the inside.")
    if not relative.parts or relative.parts[0] not in MODIFIABLE_ROOTS:
        return False, (
            f"{as_posix} is outside Jarvis's own runtime "
            f"({', '.join(f'{root}/' for root in MODIFIABLE_ROOTS)}). It "
            f"belongs to another system in this checkout, and changing it "
            f"would be an edit to somebody else's service that nobody asked "
            f"for.")
    readable, why = may_read(relative)
    if not readable:
        return False, why
    return True, ""


def require_modifiable(paths: list[str]) -> None:
    """Raise unless every path may be changed. The check `selfmod` runs first."""
    refused = []
    for path in paths:
        allowed, why = may_modify(path)
        if not allowed:
            refused.append(f"{path}: {why}")
    if refused:
        raise NotModifiable(
            "this proposal names files Jarvis may not change.\n\n"
            + "\n\n".join(refused))


# --- reading ------------------------------------------------------------------


def read_source(path: str | Path) -> str:
    """One file's text, if §14 allows it."""
    relative = _relative(path)
    allowed, why = may_read(relative)
    if not allowed:
        raise NotReadable(why)
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def structure(path: str | Path) -> dict:
    """A module's shape: its docstring, its classes, its functions, its imports.

    Parsed, not guessed. §14 asks Jarvis to understand component structure and
    trace control flow, and an inventory built from a regular expression would
    mislead him about the one thing he is least able to check."""
    relative = _relative(path)
    tree = ast.parse(read_source(relative))
    functions, classes, imports = [], [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({"name": node.name, "line": node.lineno,
                              "doc": ast.get_docstring(node)})
        elif isinstance(node, ast.ClassDef):
            classes.append({
                "name": node.name, "line": node.lineno,
                "doc": ast.get_docstring(node),
                "methods": [child.name for child in node.body
                            if isinstance(child, (ast.FunctionDef,
                                                  ast.AsyncFunctionDef))]})
        elif isinstance(node, ast.Import):
            imports += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return {
        "path": relative.as_posix(),
        "doc": ast.get_docstring(tree),
        "functions": functions,
        "classes": classes,
        "imports": sorted(set(imports)),
        "lines": len(read_source(relative).splitlines()),
        "may_modify": may_modify(relative)[0],
    }


def components(root: str | None = None) -> list[dict]:
    """Every module Jarvis may read, with whether he may change it.

    The `may_modify` column is the point: an inventory that did not carry it
    would invite a proposal naming a file that was never in reach."""
    roots = [root] if root else list(MODIFIABLE_ROOTS) + ["backend", "dba"]
    found = []
    for name in roots:
        directory = PROJECT_ROOT / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(PROJECT_ROOT)
            if not may_read(relative)[0]:
                continue
            found.append({"path": relative.as_posix(),
                          "lines": len(path.read_text(encoding="utf-8").splitlines()),
                          "may_modify": may_modify(relative)[0]})
    return found


def tests_covering(module_path: str | Path) -> list[str]:
    """Test files that mention this module by name.

    §17 asks for a test plan, and a proposal that names no existing coverage is
    one where "run the tests" means something different from what the author
    assumed."""
    relative = _relative(module_path)
    stem = relative.stem
    package = relative.parts[0] if len(relative.parts) > 1 else ""
    dotted = relative.with_suffix("").as_posix().replace("/", ".")

    # Over imports, not over the whole text. The first version looked for
    # " ledger." anywhere and matched the words "spend ledger." in a docstring,
    # reporting four test files that have never imported it. A coverage list
    # that includes files which do not touch the module makes §17's test plan
    # worse than having none.
    patterns = [re.compile(rf"^\s*import\s+{re.escape(dotted)}\b", re.MULTILINE),
                re.compile(rf"^\s*from\s+{re.escape(dotted)}\s+import\b", re.MULTILINE)]
    if package:
        # Both spellings, including the parenthesised one that wraps over
        # several lines - `from gateway import (a, b,\n  ledger, c)`. Missing
        # it meant the module's own test file was reported as not covering it.
        patterns.append(re.compile(
            rf"^\s*from\s+{re.escape(package)}\s+import\s+[^(\n]*"
            rf"\b{re.escape(stem)}\b", re.MULTILINE))
        patterns.append(re.compile(
            rf"^\s*from\s+{re.escape(package)}\s+import\s+\([^)]*"
            rf"\b{re.escape(stem)}\b[^)]*\)", re.MULTILINE | re.DOTALL))

    found = []
    for path in sorted((PROJECT_ROOT / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in patterns):
            found.append(path.relative_to(PROJECT_ROOT).as_posix())
    return found


def describe() -> dict:
    """What Jarvis can see and what he can touch, for a diagnostics page."""
    return {
        "modifiable_roots": list(MODIFIABLE_ROOTS),
        "governance_files": list(GOVERNANCE),
        "unreadable": {"suffixes": list(UNREADABLE_SUFFIXES),
                       "names": list(UNREADABLE_NAMES),
                       "directories": list(UNREADABLE_DIRECTORIES)},
        "modules_readable": len(components()),
    }
