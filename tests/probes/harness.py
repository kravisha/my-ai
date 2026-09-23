"""The runner behind every `*_probes.py` file here.

Krish, 2026-09-23: *"Tests working fine initially is not good testing at all."*

A probe file names mutations - an exact snippet of a module, what to replace it
with, and which tests must go red as a result - and this runs them. It exists as
its own module because the second probe file would otherwise have copied it, and
a copied harness drifts: one copy gets the fix that makes a stale probe a hard
failure and the other quietly keeps reporting success.

Two rules it enforces, both learned the hard way in this repository:

- **A probe whose snippet no longer appears exactly once is a failure, not a
  skip.** A probe that silently stopped applying reports success, which is worse
  than not having it.
- **A mutation no test noticed is a failure**, and it is named in the output
  along with the tests that should have caught it. That is the whole output that
  matters; the per-probe lines are progress, not the finding.

Every file is restored immediately after its own probe and again in an outer
`finally`, and the restoration is verified by hash before exit. A run that
reports DIRTY means `git checkout` the modules it lists.

Probe files are deliberately not named `test_*`: they edit source files and run
pytest inside themselves, so pytest must never collect them.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (module, what it breaks, snippet, replacement, tests that must fail). A probe
# with an empty test tuple is *recorded, not asserted* - the honest way to say
# "this code is defensive and no test can reach it through the public API"
# without writing a test that pretends to cover it.
Probe = tuple[str, str, str, str, "tuple[str, ...]"]


def _run(suite: Path, tests: tuple[str, ...]) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(suite), "-q",
         "-p", "no:cacheprovider", "-k", " or ".join(tests)],
        capture_output=True, text=True, cwd=ROOT)
    return result.returncode


def run_probes(probes: list[Probe], suites: dict[str, Path]) -> int:
    """Apply every probe, report what no test caught, and restore everything."""
    unknown = {module for module, *_ in probes} - set(suites)
    if unknown:
        print(f"probe files name modules with no suite: {sorted(unknown)}")
        return 1

    sources = {name: (ROOT / name).read_text() for name in suites}
    before = {name: hashlib.sha256(text.encode()).hexdigest()
              for name, text in sources.items()}
    checked = 0
    stale: list[str] = []
    survived: list[str] = []

    try:
        for module, label, snippet, replacement, tests in probes:
            original = sources[module]
            if original.count(snippet) != 1:
                stale.append(f"{module} / {label}: snippet appears "
                             f"{original.count(snippet)} times, expected 1")
                continue
            if not tests:
                continue
            checked += 1
            (ROOT / module).write_text(original.replace(snippet, replacement))
            try:
                code = _run(suites[module], tests)
            finally:
                (ROOT / module).write_text(original)
            if code == 0:
                survived.append(f"{label}\n    tests that should have caught it: "
                                f"{', '.join(tests)}")
            print(f"{'caught  ' if code else 'MISSED  '} {label}")
    finally:
        for name, text in sources.items():
            (ROOT / name).write_text(text)

    after = {name: hashlib.sha256((ROOT / name).read_text().encode()).hexdigest()
             for name in suites}
    print()
    print(f"{checked} mutation(s) applied; {len(survived)} went unnoticed")
    print(f"restored: {'clean' if before == after else 'DIRTY - git checkout them'}")
    if stale:
        print("\nSTALE PROBES (the code moved and these no longer apply):")
        for line in stale:
            print(f"  - {line}")
    if survived:
        print("\nMUTATIONS NO TEST CAUGHT:")
        for line in survived:
            print(f"  - {line}")
    return 1 if (stale or survived or before != after) else 0
