"""Same-machine spool: the compatible local adapter under the R2 design.

One append-only UTF-8 file. The cursor is ``{"size": n, "sha256": h}`` of the whole file,
so a put with a stale cursor is a conflict exactly as a stale blob SHA is on GitHub.
A byte-range lock serializes writers on Windows and POSIX. This file is NOT the shared
source; it stands in for it on one machine and under fakes.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import fsatomic, plane as P

try:  # Windows
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None
    import fcntl


class _Lock:
    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.fh = open(self.path, "a+b")
        if msvcrt is not None:
            self.fh.seek(0)
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)  # bounded: LK_LOCK retries ~10 s then raises
        else:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if msvcrt is not None:
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()


class LocalSpoolPlane:
    name = "local-spool"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _snapshot(self) -> tuple[dict, str]:
        if not self.path.exists():
            return {"size": 0, "sha256": hashlib.sha256(b"").hexdigest()}, ""
        data = self.path.read_bytes()
        return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}, data.decode("utf-8")

    def fetch(self, cursor: dict | None) -> P.FetchResult:
        try:
            with _Lock(self.lock_path):
                cur, text = self._snapshot()
        except OSError as e:
            return P.FetchResult(P.FAILED, detail=f"{type(e).__name__}")
        if cursor is not None and cursor == cur:
            return P.FetchResult(P.UNCHANGED, cursor=cur)
        return P.FetchResult(P.CHANGED, cursor=cur, text=text)

    def put(self, expected_cursor: dict | None, new_text: str, message: str = "") -> P.PutResult:
        try:
            with _Lock(self.lock_path):
                cur, _ = self._snapshot()
                if expected_cursor is not None and expected_cursor != cur:
                    return P.PutResult(P.PUT_CONFLICT, cursor=cur, detail="spool changed since read")
                data = new_text.encode("utf-8")
                fsatomic.write_atomic(self.path, data)
                new_cur = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                return P.PutResult(P.PUT_OK, cursor=new_cur, commit=new_cur["sha256"][:12])
        except OSError as e:
            return P.PutResult(P.PUT_UNKNOWN, detail=f"{type(e).__name__}")
