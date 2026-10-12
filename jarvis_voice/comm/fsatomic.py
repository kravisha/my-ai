"""Atomic file publication on Windows and POSIX: write a temp file in the same directory,
flush, fsync, then ``os.replace`` over the target.

Windows finding (observed in this suite on 2026-09-24 22:49 EDT, DEPLOYMENT-PC): ``os.replace``
of a just-written temp file can fail transiently with ``PermissionError`` WinError 32
("being used by another process") while something else, typically an on-access scanner,
holds the new file open. The mitigation is a BOUNDED retry with a short backoff. It is
bounded on purpose: an unbounded loop would hang a synchronous UI call, which is the same
defect Arya flagged in the persistence lock (5825662233). Exhaustion raises the last error
so the caller reports it; the temp file is left where it is as evidence, never deleted.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

REPLACE_ATTEMPTS = 6
REPLACE_BACKOFF_S = (0.01, 0.02, 0.05, 0.1, 0.2)


def replace_bounded(src: Path, dst: Path, *, attempts: int = REPLACE_ATTEMPTS, sleep=time.sleep) -> int:
    """os.replace with a bounded retry on transient sharing violations. Returns the attempt count."""
    for i in range(1, attempts + 1):
        try:
            os.replace(src, dst)
            return i
        except PermissionError:
            if i >= attempts:
                raise
            sleep(REPLACE_BACKOFF_S[min(i - 1, len(REPLACE_BACKOFF_S) - 1)])
    raise AssertionError("unreachable")


def write_atomic(path: Path, data: bytes, *, sleep=time.sleep) -> None:
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    replace_bounded(tmp, path, sleep=sleep)
