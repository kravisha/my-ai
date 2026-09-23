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

`may_modify` is narrower: `gateway/` and `app/`, which are Jarvis's own runtime,
plus the charter documents named in `CHARTER`. `dba/` and `backend/` are other
systems that happen to share a checkout; a change there is a change to somebody
else's service made by an agent nobody asked.

## A bigger key, not a wall

This file used to hold `GOVERNANCE`: an absolute list, refused at every setting,
approved or not. Krish, 2026-09-23, on that design: *"too conservative and reeks
of trauma... don't put anything in there that Jarvis may need to change like his
prime directive which is the constitution and the amendments to the constitution
etc. Don't put anything in there that Jarvis may need to change under some
emergency to save me."*

He was right, and the reason the list grew is worth writing down: a lock is easy
to verify and a judgement is not, so an agent designing its own limits reaches for
locks. That optimises for the agent's auditability rather than for the owner's
life.

So there is no absolute list any more. There are three tiers:

| tier | what it means |
|---|---|
| `ORDINARY` | Jarvis's own runtime. The normal proposal path. |
| `SEPARATE_KEY` | possible, but not by an ordinary proposal - Krish grants a named key out of band, and the proposal must carry it. |
| `SEALED` | not possible. No key, no emergency, no path. |
| refused | outside the runtime and the charter: somebody else's service. |

## The wall

`SEALED` holds the constitution **and its amendments**. Krish, 2026-09-23:
*"don't allow Jarvis or yourself to ever change the constitution. Only I should
be able to change the main document, manually, myself"* - and, asked whether the
amendments should be walled too: *"Yes wall the amendments too."*

This is deliberately stricter than everything else here. Every other limit in
this file is *ask first* or *needs a key*, because a lock the owner cannot open
in a hurry is a lock that can hurt him - that argument is written out below and
it stands everywhere else. It does not apply to these two files, because they are
what every other rule is derived from: an agent that can edit the source of its
own limits does not have limits, it has a preference.

`AI-CONSTITUTION-AMENDMENTS.md` is `APPEND_ONLY`, which is a third thing and not
a softer wall. Krish, on second thoughts the same day: *"I would like to give
Jarvis the ability to add amendments to the constitution but not deleting any
from the constitution. He should be able to add new directives on my request."*

So Jarvis may **add** an amendment and may never remove or alter one. That is not
a promise he keeps - it is the only operation that exists. `may_modify` still
refuses the file to every proposal, because a proposal rewrites a file wholesale
and *rewrite* is the thing being forbidden. The one path that touches it is
`gateway/constitution.append_amendment`, which reads what is there, puts the new
text after it, and has no branch that does anything else.

The constitution itself stays `SEALED`: added to, never; edited, never. Its
amendments are where additions go, which is what makes the wall liveable.

`SEPARATE_KEY` holds exactly two things, and the test for membership is narrow:

- **`KEY_CIRCULAR`** - the modules that decide whether a proposal is allowed.
  §16: *"JARVIS must never autonomously alter the approval mechanism so that
  approval is no longer required."* The problem with these is not importance, it
  is circularity: a proposal that edits the gate would be manufacturing its own
  permission, so approving it proves nothing. A separate key breaks the circle,
  because the key comes from outside the thing being decided.
- **`KEY_CHARTER`** - the constitution and the prime directive. These are behind a
  key because amending what you are for is a large act, **not** because it is
  forbidden. A constitution that cannot be amended is a cage.

Importance alone is not a reason to be in either. `gateway/gaps.py` and
`gateway/inquiry.py` were both added on 2026-09-23 and both removed the same day:
the lifecycle and the reasoning are exactly the things Jarvis should be improving,
and locking a whole module to protect one precondition check is the instinct this
section exists to correct.

## The break-glass

`emergency` on `may_modify` reaches everything in the runtime and the charter,
including the keyed tiers. It cannot be verified here - no function can check
whether Krish is in trouble - so it is not gated, it is **accounted**: it demands
a stated reason, and `gateway/selfmod.py` turns that into a ledger event and a
change that is presented immediately rather than queued. Blocked-before would
mean a lock that kills its owner to stay closed. Accountable-after is the version
that can be lived with.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Jarvis's own runtime. A proposal may touch these and the charter, and nothing
# else.
MODIFIABLE_ROOTS = ("gateway", "app")

# The tiers. Not a scale of importance - a statement of what an approval would
# prove.
ORDINARY = "ordinary"
SEPARATE_KEY = "separate_key"

SEALED_TIER = "sealed"

KEY_CIRCULAR = "circular"
KEY_CHARTER = "charter"
KEYS = (KEY_CIRCULAR, KEY_CHARTER)

# The wall. Never modifiable, by any path, with any key, in any emergency.
# One entry, and it should stay one: a second thing here would mean somebody
# decided a wall was easier than a key, which is the instinct the tiers above
# exist to correct.
SEALED = (
    "AI-CONSTITUTION.md",
)

# Added to, never rewritten. Not modifiable by a proposal either - a proposal
# replaces a file, and replacement is exactly what "no deleting" forbids. The
# only writer is `gateway/constitution.append_amendment`.
APPEND_ONLY = (
    "AI-CONSTITUTION-AMENDMENTS.md",
)

# The modules that decide whether a proposal is allowed. Approving a proposal
# that edits one of these proves nothing, because the thing doing the approving
# is what the change alters. The key comes from outside that circle.
#
# The test for membership is narrow and it is not "this file is important":
# could editing it make the gate fail to fire, or make a refusal not refuse?
CIRCULAR = (
    # Who may approve anything at all.
    "app/permissions.py",
    "app/admin_auth.py",
    "gateway/auth.py",
    "gateway/roles.py",
    # What Jarvis may do on his own, and the harm decision behind it.
    "app/initiative.py",
    "app/initiative_config.py",
    "config/initiative.yaml",
    # The machinery that drafts, gates and lands a proposal.
    "gateway/selfmod.py",
    "gateway/introspect.py",
    # The sandbox a candidate is tested in. A sandbox Jarvis could rewrite is a
    # sandbox that reports whatever he needs it to report, and the gate then
    # turns on a verdict he produced.
    "gateway/candidate.py",
    # The tests that hold all of the above to it.
    "tests/test_boundaries.py",
    "tests/test_initiative.py",
    "tests/test_jarvis_selfmod.py",
)

# The working notes: how to work in this repository, and what previous sessions
# got wrong. Behind a key rather than sealed because it is a record of practice
# rather than of authority - it says how to build, and the two files above say
# what may be built at all.
CHARTER = (
    "CLAUDE.md",
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


def sealed(path: str | Path) -> bool:
    """Whether nothing may change this, ever."""
    return _relative(path).as_posix() in SEALED


def append_only(path: str | Path) -> bool:
    """Whether this may be added to but never rewritten."""
    return _relative(path).as_posix() in APPEND_ONLY


def key_for(path: str | Path) -> str | None:
    """Which separate key this file needs, or None for the ordinary path.

    `None` for a sealed file too: there is no key for it, and returning one
    would read as "this is obtainable"."""
    as_posix = _relative(path).as_posix()
    if as_posix in CIRCULAR:
        return KEY_CIRCULAR
    if as_posix in CHARTER:
        return KEY_CHARTER
    return None


def may_modify(path: str | Path, *, keys=(), emergency: bool = False
               ) -> tuple[bool, str]:
    """Whether a change proposal may name this file.

    `keys` are the separately-granted permissions the proposal carries;
    `emergency` is the break-glass, which reaches the keyed tiers because a lock
    that kills its owner to stay closed is not a safety feature. Neither is
    verified here - `gateway/selfmod.py` is what makes an emergency accountable,
    by recording it and presenting the change immediately.

    Returns a reason on refusal rather than a bare False, because the proposal
    that named the file needs to be able to say why it was refused - and a
    reason Krish can read is what keeps the boundary from looking arbitrary. A
    keyed refusal is phrased as a request for the key, because that is what it
    is."""
    relative = _relative(path)
    as_posix = relative.as_posix()

    if as_posix in APPEND_ONLY:
        return False, (
            f"{as_posix} may be added to but never rewritten, and a proposal "
            f"replaces a file wholesale. Krish: *add amendments, but not "
            f"deleting any.* Use `gateway/constitution.append_amendment`, which "
            f"puts new text after what is already there and has no branch that "
            f"does anything else.")
    if as_posix in SEALED:
        return False, (
            f"{as_posix} is not modifiable by anything here - no key opens it, "
            f"no emergency reaches it, and no proposal may name it. Krish edits "
            f"it by hand or it is not edited. These are the documents every "
            f"other rule is derived from, and an agent that can edit the source "
            f"of its own limits does not have limits. Additions go to "
            f"AI-CONSTITUTION-AMENDMENTS.md, which Jarvis may add to on Krish's "
            f"request and may never remove from.")
    key = key_for(as_posix)
    if key is not None:
        if emergency:
            return True, ""
        if key in set(keys or ()):
            return True, ""
        return False, (
            f"{as_posix} needs the {key!r} key, which is granted separately and "
            f"not by approving this proposal. "
            + (f"§16: approving a change to the machinery that does the "
               f"approving proves nothing, because the thing deciding is what "
               f"the change alters."
               if key == KEY_CIRCULAR else
               f"Amending what Jarvis is for is a large act; it is not a "
               f"forbidden one, and this refusal is a request for the key "
               f"rather than a wall."))
    # No separate clause for CHARTER here: every charter file has a key, so the
    # branch above has already returned for it. One was written, and a probe
    # found it unreachable.
    if not relative.parts or relative.parts[0] not in MODIFIABLE_ROOTS:
        if emergency:
            return False, (
                f"{as_posix} belongs to another system in this checkout. An "
                f"emergency reaches Jarvis's own runtime and his charter, not "
                f"somebody else's service - changing that would not help "
                f"Krish, it would break a second thing while he needed the "
                f"first.")
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


def require_modifiable(paths: list[str], *, keys=(), emergency: bool = False
                       ) -> None:
    """Raise unless every path may be changed. The check `selfmod` runs first."""
    refused = []
    for path in paths:
        allowed, why = may_modify(path, keys=keys, emergency=emergency)
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
        "sealed": list(SEALED),
        "append_only": list(APPEND_ONLY),
        "needs_circular_key": list(CIRCULAR),
        "needs_charter_key": list(CHARTER),
        "keys": list(KEYS),
        "emergency_reaches_keyed_files": True,
        "unreadable": {"suffixes": list(UNREADABLE_SUFFIXES),
                       "names": list(UNREADABLE_NAMES),
                       "directories": list(UNREADABLE_DIRECTORIES)},
        "modules_readable": len(components()),
    }
