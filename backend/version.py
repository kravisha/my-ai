"""The one answer to "which code is this?" — addendum 30 §26 (Directive E17).

Extracted from simulation/harness.py, which needed it first (a run whose code
version is unrecorded cannot be replayed); the agent registry needs the same
fact for the same reason (an agent whose behavior version is unrecorded cannot
be targeted for retraining or trusted in mixed-version operation), and two
implementations of "what version am I" would eventually disagree about it.

The answer never guesses: a commit sha, sha-dirty when the working tree has
uncommitted changes (an agent running edited code is *not* running the
commit), or the honest marker 'unknown' when git is unavailable — a usable
answer, where a fabricated one is not.
"""

import functools
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_SHA = re.compile(r"[0-9a-f]{40}")


@functools.lru_cache(maxsize=1)
def code_version() -> str:
    """Cached per process: a process runs exactly one code version for its
    whole life, so asking git once is both sufficient and what keeps this
    cheap enough to sit on every agent registration.

    The except clause is deliberately broad and the sha is validated before
    being trusted: this function's contract is "a true answer or 'unknown'",
    and *any* failure mode — git missing, a test environment with a faked
    subprocess layer, garbage on stdout — must resolve to 'unknown' rather
    than to an exception in registration or a fabricated version on record."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return "unknown"
        sha = result.stdout.strip()
        if not _SHA.fullmatch(sha):
            return "unknown"
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except Exception:
        return "unknown"
