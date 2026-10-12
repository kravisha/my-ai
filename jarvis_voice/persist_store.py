"""JARVIS-PERSIST-01 reference file store, v2 (PROPOSED).

Implements CONTRACT.md (parent directory) as corrected by Arya's review
(hub 5825568616, 5825553772). Standard library only. No database, no network,
no process control, no speech, no send path. Nothing here deletes a file.

v2 changes: R2 `epoch` is the only generation field; checkpoints live in a
checksum envelope and a current file always exists (prev is written first);
an unsupported MAJOR at event level fails closed for every mutation; a file
lock covers read-check-dedup-append, checkpoint replace and recover; a partial
line blocks appends until recover has quarantined the whole original file.
"""
from __future__ import annotations

import hashlib
import json
import os
import errno
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = "1.0"
READER_MAJOR = 1
TERMINAL_STATES = ("completed", "error", "cancelled")
KINDS = ("user", "assistant_local", "assistant_claude", "system")
REQUIRED_EVENT_FIELDS = (
    "schema_version", "event_id", "conversation_id", "turn_id", "request_id",
    "sequence", "epoch", "author", "timestamp", "kind", "terminal_state", "payload",
)
PENDING_FIELDS = ("request_id", "epoch", "state", "turn_sequence")
LOCK_TIMEOUT_S = 10.0
# contention errnos, per platform: msvcrt.locking(LK_NBLCK) raises EACCES on a
# held lock (EDEADLK after LK_LOCK retries); fcntl.flock(LOCK_NB) raises
# EAGAIN/EWOULDBLOCK. Anything else is permanent and is never retried.
_LOCK_CONTENTION_ERRNOS = (
    {errno.EACCES, errno.EDEADLK} if os.name == "nt"
    else {errno.EAGAIN, getattr(errno, "EWOULDBLOCK", errno.EAGAIN)}
)


class ConflictError(Exception):
    """Same event_id, different content."""


class VersionRefused(Exception):
    """File or event MAJOR version is newer than this reader; mutation refused."""


class CorruptionBlocksWrite(Exception):
    """History has a corrupt tail; appends are refused until recover() runs."""


class LockTimeout(TimeoutError):
    """The store lock stayed contended past the deadline; nothing was written.
    A TimeoutError (so an OSError) with the last contention errno as cause."""


class DurabilityUnknown(Exception):
    """os.replace succeeded (new bytes are the file) but a later flush raised:
    committed on disk, durability across power loss unknown. Not a failure,
    not a success; the caller reports it as such."""

    def __init__(self, target: "Path", stage: str):
        super().__init__(f"{target}: committed by replace; {stage} raised")
        self.target = target
        self.stage = stage
        self.committed_on_disk = True
        self.durable = None


def validate_conversation_id(value: Any) -> str:
    """Canonical lowercase UUID only; the id is used to build a path."""
    if not isinstance(value, str):
        raise ValueError("conversation_id must be a string")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise ValueError("conversation_id must be a canonical UUID string")
    return value


# --- canonical hashing (R2 rule) -------------------------------------------

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _major(version: Any) -> int:
    try:
        return int(str(version).split(".")[0])
    except ValueError:
        return -1


# --- lock (byte lock like the owned store's idea; released on process death) --

@contextmanager
def file_lock(path: Path, timeout_s: float = LOCK_TIMEOUT_S):
    """Byte lock on `path`. Contention is retried until `timeout_s`, then
    LockTimeout. Any other OSError is raised at once (permanent error, never
    retried). Released by the OS on process death. Windows path UNRUN."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    with open(path, "a+b") as fh:
        if fh.tell() == 0:
            fh.write(b"0")
            fh.flush()
        fh.seek(0)
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in _LOCK_CONTENTION_ERRNOS:
                        raise
                    if time.monotonic() >= deadline:
                        raise LockTimeout(str(path)) from exc
                    time.sleep(0.02)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in _LOCK_CONTENTION_ERRNOS:
                        raise
                    if time.monotonic() >= deadline:
                        raise LockTimeout(str(path)) from exc
                    time.sleep(0.02)
        try:
            yield
        finally:
            fh.seek(0)
            if os.name == "nt":
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh, fcntl.LOCK_UN)


# --- results ---------------------------------------------------------------

@dataclass
class HistoryResult:
    events: list[dict] = field(default_factory=list)
    gaps: list[int] = field(default_factory=list)
    corruption_detected: dict | None = None
    version_refused: bool = False
    unsupported_event_major: dict | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class CheckpointResult:
    checkpoint: dict | None = None
    checkpoint_available: bool = False
    fallback_used: str | None = None
    version_refused: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class RecoveryReport:
    previous_epoch: str | None = None
    stale_unresolved: list[dict] = field(default_factory=list)
    still_pending: list[dict] = field(default_factory=list)
    stray_tmp_quarantined: list[str] = field(default_factory=list)
    history_repaired: list[dict] = field(default_factory=list)
    history_frozen_unsupported_major: list[str] = field(default_factory=list)
    checkpoint_current_missing_prev_used: list[str] = field(default_factory=list)
    checkpoint_frozen_unsupported_major: list[str] = field(default_factory=list)
    history_high_water: dict[str, int | None] = field(default_factory=dict)
    checkpoint_last_sequence: dict[str, int | None] = field(default_factory=dict)
    pending_max_turn_sequence: dict[str, int | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Scan:
    events: list[dict] = field(default_factory=list)   # {event_id, event, _sha256}
    corruption_detected: dict | None = None
    version_refused: bool = False
    unsupported_event_major: dict | None = None
    warnings: list[str] = field(default_factory=list)
    good_prefix_len: int = 0


# --- store -----------------------------------------------------------------

class FileStore:
    def __init__(self, root: str | os.PathLike,
                 fault: Callable[[str, Path], None] | None = None,
                 lock_timeout_s: float = LOCK_TIMEOUT_S):
        """`fault(boundary, path)` is a test hook called at named write
        boundaries; it may raise to simulate a crash. For a whole-file write
        labelled L (prev, current, manifest) the boundaries are, in order:
        'after_tmp_fsync:L', 'before_replace:L', 'after_replace:L',
        'after_dir_fsync:L'. A raise at or after 'after_replace' surfaces as
        DurabilityUnknown (the replace already happened)."""
        self.root = Path(root)
        self._fault = fault or (lambda boundary, path: None)
        self._lock_timeout_s = lock_timeout_s
        for sub in ("history", "checkpoints", "quarantine"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._lockfile = self.root / "store.lock"
        manifest = self.root / "manifest.json"
        if not manifest.exists():
            with file_lock(self._lockfile, self._lock_timeout_s):
                if not manifest.exists():
                    self._atomic_write(manifest, {
                        "schema_version": SCHEMA_VERSION,
                        "store_id": str(uuid.uuid4()),
                        "created_at": _now(),
                    }, label="manifest")

    # -- paths
    def _history(self, conversation_id: str) -> Path:
        return self.root / "history" / f"{validate_conversation_id(conversation_id)}.jsonl"

    def _checkpoint(self, conversation_id: str) -> Path:
        return self.root / "checkpoints" / f"{validate_conversation_id(conversation_id)}.json"

    def _checkpoint_prev(self, conversation_id: str) -> Path:
        return self.root / "checkpoints" / f"{validate_conversation_id(conversation_id)}.prev.json"

    # -- atomic whole-file write (CONTRACT section 4)
    def _atomic_write(self, target: Path, doc: dict, label: str = "file") -> None:
        tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
        data = (canonical_json(doc) + "\n").encode("utf-8")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        self._fault(f"after_tmp_fsync:{label}", tmp)
        self._fault(f"before_replace:{label}", tmp)
        os.replace(tmp, target)
        # from here the new bytes ARE the file; a raise is DurabilityUnknown
        try:
            self._fault(f"after_replace:{label}", target)
            self._fsync_dir(target.parent)
            self._fault(f"after_dir_fsync:{label}", target)
        except DurabilityUnknown:
            raise
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            raise DurabilityUnknown(target, f"post-replace ({type(exc).__name__}: {exc})") from exc

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _quarantine_copy(self, src: Path, label: str) -> Path:
        dst = self.root / "quarantine" / f"{src.name}.{label}.{_stamp()}"
        with open(src, "rb") as s, open(dst, "wb") as d:
            d.write(s.read())
            d.flush()
            os.fsync(d.fileno())
        self._fsync_dir(dst.parent)
        return dst

    @staticmethod
    def _append_line(path: Path, doc: dict) -> None:
        data = (canonical_json(doc) + "\n").encode("utf-8")
        with open(path, "ab") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())

    # -- validation
    @staticmethod
    def _validate_turn(turn: dict) -> dict:
        missing = [f for f in REQUIRED_EVENT_FIELDS if f not in turn]
        if missing:
            raise ValueError(f"missing fields: {missing}")
        if "generation" in turn or "session_generation" in turn:
            raise ValueError("use R2 'epoch'; no second generation field")
        if turn["terminal_state"] not in TERMINAL_STATES:
            raise ValueError(f"turn is not terminal: {turn['terminal_state']!r}")
        if turn["kind"] not in KINDS:
            raise ValueError(f"unknown kind: {turn['kind']!r}")
        if not isinstance(turn["sequence"], int) or isinstance(turn["sequence"], bool) or turn["sequence"] < 1:
            raise ValueError("sequence must be a positive integer")
        if _major(turn["schema_version"]) != READER_MAJOR:
            raise ValueError(f"event schema_version {turn['schema_version']!r} unsupported")
        if not isinstance(turn["epoch"], str) or not turn["epoch"]:
            raise ValueError("epoch must be a non-empty string")
        validate_conversation_id(turn["conversation_id"])
        return dict(turn)

    # -- scanning a history file (read-only; never mutates)
    def _scan(self, path: Path) -> _Scan:
        sc = _Scan()
        if not path.exists():
            return sc
        with open(path, "rb") as fh:
            raw = fh.read()
        offset = 0
        lineno = 0
        header_seen = False
        while offset < len(raw):
            nl = raw.find(b"\n", offset)
            if nl == -1:
                sc.corruption_detected = {"line": lineno + 1, "byte_offset": offset,
                                          "reason": "unterminated (partial) line"}
                break
            line = raw[offset:nl]
            lineno += 1
            try:
                doc = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                sc.corruption_detected = {"line": lineno, "byte_offset": offset, "reason": "invalid json"}
                break
            if not header_seen:
                if not (isinstance(doc, dict) and doc.get("kind") == "header"):
                    sc.corruption_detected = {"line": lineno, "byte_offset": offset, "reason": "missing header"}
                    break
                header_seen = True
                major = _major(doc.get("schema_version"))
                if major > READER_MAJOR:
                    sc.version_refused = True
                    return sc
                if str(doc.get("schema_version")) != SCHEMA_VERSION:
                    sc.warnings.append(f"file schema_version {doc.get('schema_version')} read by {SCHEMA_VERSION} reader")
            else:
                ev = doc.get("event") if isinstance(doc, dict) else None
                digest = doc.get("sha256") if isinstance(doc, dict) else None
                if not isinstance(ev, dict) or not isinstance(digest, str) or sha256_of(ev) != digest:
                    sc.corruption_detected = {"line": lineno, "byte_offset": offset,
                                              "reason": "hash mismatch or malformed record"}
                    break
                if _major(ev.get("schema_version")) > READER_MAJOR:
                    # fail closed: stop here, keep all bytes, refuse mutations
                    sc.unsupported_event_major = {"line": lineno, "byte_offset": offset,
                                                  "schema_version": ev.get("schema_version")}
                    return sc
                sc.events.append({"event_id": ev.get("event_id"), "event": ev, "_sha256": digest})
            offset = nl + 1
            sc.good_prefix_len = offset
        return sc

    STORAGE = "file"

    def capabilities(self) -> dict:
        return {"durable": True, "storage": self.STORAGE}

    # -- API: save_completed_turn (locked read-check-dedup-append)
    def save_completed_turn(self, turn: dict) -> dict:
        event = self._validate_turn(turn)
        digest = sha256_of(event)
        path = self._history(event["conversation_id"])
        with file_lock(self._lockfile, self._lock_timeout_s):
            sc = self._scan(path)
            if sc.version_refused or sc.unsupported_event_major is not None:
                raise VersionRefused(str(path))
            if sc.corruption_detected is not None:
                raise CorruptionBlocksWrite(canonical_json(sc.corruption_detected))
            for line in sc.events:
                if line["event_id"] == event["event_id"]:
                    if line["_sha256"] == digest:
                        return {"event_id": event["event_id"], "duplicate": True, "persisted": True, "storage": self.STORAGE}
                    self._append_line(self.root / "quarantine" / "conflicts.jsonl", {
                        "recorded_at": _now(), "event": event, "sha256": digest,
                        "existing_sha256": line["_sha256"],
                    })
                    raise ConflictError(event["event_id"])
            if not path.exists():
                self._append_line(path, {
                    "kind": "header", "schema_version": SCHEMA_VERSION,
                    "conversation_id": event["conversation_id"], "created_at": _now(),
                })
            self._append_line(path, {"event": event, "sha256": digest})
            return {"event_id": event["event_id"], "duplicate": False, "persisted": True, "storage": self.STORAGE}

    # -- checkpoints: envelope {"checkpoint": {...}, "sha256": ...}
    @staticmethod
    def _envelope_status(doc: Any, conversation_id: str) -> tuple[str, dict | None]:
        """Returns ('ok', cp) | ('invalid', None) | ('version_refused', None).
        Typed validation of every required field; a future MAJOR is refused,
        never treated as invalid, so its bytes are preserved."""
        if not isinstance(doc, dict) or "checkpoint" not in doc or "sha256" not in doc:
            return "invalid", None
        cp = doc["checkpoint"]
        if not isinstance(cp, dict) or not isinstance(doc["sha256"], str) or sha256_of(cp) != doc["sha256"]:
            return "invalid", None
        if not isinstance(cp.get("schema_version"), str):
            return "invalid", None
        if _major(cp["schema_version"]) > READER_MAJOR:
            return "version_refused", None
        if _major(cp["schema_version"]) != READER_MAJOR:
            return "invalid", None
        if cp.get("conversation_id") != conversation_id:
            return "invalid", None
        if not isinstance(cp.get("checkpoint_seq"), int) or isinstance(cp.get("checkpoint_seq"), bool):
            return "invalid", None
        if not isinstance(cp.get("epoch"), str) or not cp["epoch"]:
            return "invalid", None
        if not isinstance(cp.get("written_at"), str):
            return "invalid", None
        if not isinstance(cp.get("pending"), list) or not isinstance(cp.get("important_state"), dict):
            return "invalid", None
        ls = cp.get("last_sequence")
        if ls is not None and (not isinstance(ls, int) or isinstance(ls, bool)):
            return "invalid", None
        for p in cp["pending"]:
            if not isinstance(p, dict):
                return "invalid", None
            for f in PENDING_FIELDS:
                if f not in p:
                    return "invalid", None
            if not (isinstance(p["request_id"], str) and p["request_id"]) \
                    or not (isinstance(p["epoch"], str) and p["epoch"]) \
                    or not (isinstance(p["state"], str) and p["state"]):
                return "invalid", None
            if not isinstance(p["turn_sequence"], int) or isinstance(p["turn_sequence"], bool) or p["turn_sequence"] < 1:
                return "invalid", None
        return "ok", cp

    def _read_envelope(self, path: Path, conversation_id: str) -> tuple[str, dict | None]:
        try:
            with open(path, "rb") as fh:
                return self._envelope_status(json.loads(fh.read().decode("utf-8")), conversation_id)
        except (OSError, ValueError, UnicodeDecodeError):
            return "invalid", None

    def save_checkpoint(self, conversation_id: str, checkpoint: dict) -> dict:
        """Returns {checkpoint_seq, persisted: True, storage: "file"} (uniform
        with NoopStore, hub 5825719873). Raises on any failure; a raise after
        the replace is DurabilityUnknown (committed, durability unknown)."""
        validate_conversation_id(conversation_id)
        if "generation" in checkpoint or "session_generation" in checkpoint:
            raise ValueError("use R2 'epoch'; no second generation field")
        if not isinstance(checkpoint.get("epoch"), str) or not checkpoint["epoch"]:
            raise ValueError("checkpoint.epoch must be a non-empty string")
        ls = checkpoint.get("last_sequence")
        if ls is not None and (not isinstance(ls, int) or isinstance(ls, bool) or ls < 0):
            raise ValueError("last_sequence must be a non-negative integer or absent")
        for p in checkpoint.get("pending", []):
            if not isinstance(p, dict):
                raise ValueError("pending item must be an object")
            for f in PENDING_FIELDS:
                if f not in p:
                    raise ValueError(f"pending item missing {f}")
            if "generation" in p:
                raise ValueError("pending item must use 'epoch'")
            if not isinstance(p["turn_sequence"], int) or isinstance(p["turn_sequence"], bool) or p["turn_sequence"] < 1:
                raise ValueError("pending.turn_sequence must be a positive integer")
        current = self._checkpoint(conversation_id)
        prev = self._checkpoint_prev(conversation_id)
        with file_lock(self._lockfile, self._lock_timeout_s):
            # v4 (Windows findings 5825817707): inspect BOTH candidates before
            # any write; a future MAJOR anywhere refuses the mutation (F2); the
            # recoverable candidate (current, else prev) drives a monotonic
            # checkpoint_seq (F3); the complete outgoing envelope is validated
            # before any mutation (F1).
            cur_status, cur_doc = ("missing", None)
            if current.exists():
                cur_status, cur_doc = self._read_envelope(current, conversation_id)
            prev_status, prev_doc = ("missing", None)
            if prev.exists():
                prev_status, prev_doc = self._read_envelope(prev, conversation_id)
            if cur_status == "version_refused" or prev_status == "version_refused":
                raise VersionRefused(f"{current if cur_status == 'version_refused' else prev}: "
                                     "future-version checkpoint preserved; mutation refused")
            if cur_doc is not None:
                old, old_from = cur_doc, "current"
            elif prev_doc is not None:
                old, old_from = prev_doc, "prev"
            else:
                old, old_from = None, None
            seq = (int(old["checkpoint_seq"]) + 1) if old else 1
            cp = dict(checkpoint)
            cp.update({"schema_version": SCHEMA_VERSION, "conversation_id": conversation_id,
                       "checkpoint_seq": seq, "written_at": _now()})
            cp.setdefault("pending", [])
            cp.setdefault("important_state", {})
            out_status, _ = self._envelope_status({"checkpoint": cp, "sha256": sha256_of(cp)}, conversation_id)
            if out_status != "ok":
                raise ValueError("outgoing checkpoint fails complete envelope validation; nothing written")
            # evidence of an invalid (not missing) current before it is replaced
            if cur_status == "invalid":
                self._quarantine_copy(current, "invalid-checkpoint-before-replace")
            # 1. preserve the validated candidate as prev FIRST (atomic), so a
            #    valid candidate exists at every boundary. If the candidate
            #    already IS prev (current missing/invalid), prev is left as is.
            if old is not None and old_from == "current":
                self._atomic_write(prev, {"checkpoint": old, "sha256": sha256_of(old)}, label="prev")
            # 2. atomically replace current.
            self._atomic_write(current, {"checkpoint": cp, "sha256": sha256_of(cp)}, label="current")
            return {"checkpoint_seq": seq, "persisted": True, "storage": self.STORAGE}

    def load_checkpoint(self, conversation_id: str) -> dict:
        """Plain dict (asdict of CheckpointResult): all six store functions
        return plain dicts (agreed 5826094561)."""
        return asdict(self._load_checkpoint(conversation_id))

    def _load_checkpoint(self, conversation_id: str) -> CheckpointResult:
        validate_conversation_id(conversation_id)
        res = CheckpointResult()
        for label, path in (("current", self._checkpoint(conversation_id)),
                            ("prev", self._checkpoint_prev(conversation_id))):
            if not path.exists():
                if label == "current":
                    res.warnings.append("current checkpoint missing")
                continue
            status, cp = self._read_envelope(path, conversation_id)
            if status == "version_refused":
                # preserved byte-for-byte; no fallback to older state, no copy
                res.version_refused = True
                res.warnings.append(f"{label} checkpoint has a future MAJOR version; preserved, refused")
                return res
            if status == "invalid":
                self._quarantine_copy(path, "invalid-checkpoint")
                res.warnings.append(f"{label} checkpoint invalid (envelope/checksum/schema/types); quarantined copy")
                continue
            res.checkpoint = cp
            res.checkpoint_available = True
            res.fallback_used = None if label == "current" else label
            return res
        return res

    # -- API: load_history (read-only)
    def load_history(self, conversation_id: str, since_sequence: int = 0) -> dict:
        """Plain dict (asdict of HistoryResult)."""
        return asdict(self._load_history(conversation_id, since_sequence))

    def _load_history(self, conversation_id: str, since_sequence: int = 0) -> HistoryResult:
        validate_conversation_id(conversation_id)
        path = self._history(conversation_id)
        sc = self._scan(path)
        res = HistoryResult(corruption_detected=sc.corruption_detected,
                            version_refused=sc.version_refused,
                            unsupported_event_major=sc.unsupported_event_major,
                            warnings=list(sc.warnings))
        if sc.version_refused:
            return res
        seen: set[str] = set()
        last_seq = 0
        for line in sc.events:
            if line["event_id"] in seen:
                continue
            seen.add(line["event_id"])
            ev = dict(line["event"])
            ev["restored"] = True
            ev["sha256"] = line["_sha256"]
            s = ev["sequence"]
            if s > last_seq + 1:
                res.gaps.extend(range(last_seq + 1, s))
            last_seq = max(last_seq, s)
            if s > since_sequence:
                res.events.append(ev)
        return res

    # -- API: recover (locked; the only place that repairs a history file)
    def recover(self, current_epoch: str) -> dict:
        """Plain dict (asdict of RecoveryReport)."""
        return asdict(self._recover(current_epoch))

    def _recover(self, current_epoch: str) -> RecoveryReport:
        rep = RecoveryReport()
        with file_lock(self._lockfile, self._lock_timeout_s):
            for sub in ("", "checkpoints", "history"):
                for tmp in (self.root / sub).glob("*.tmp-*"):
                    dst = self.root / "quarantine" / f"{tmp.name}.orphan.{_stamp()}"
                    os.replace(tmp, dst)
                    rep.stray_tmp_quarantined.append(str(dst))
            for hist in sorted((self.root / "history").glob("*.jsonl")):
                sc = self._scan(hist)
                conv = hist.stem
                if sc.version_refused or sc.unsupported_event_major is not None:
                    rep.history_frozen_unsupported_major.append(str(hist))
                    rep.history_high_water[conv] = None
                    continue
                seqs = [l["event"]["sequence"] for l in sc.events if isinstance(l["event"].get("sequence"), int)]
                rep.history_high_water[conv] = max(seqs) if seqs else None
                if sc.corruption_detected is not None:
                    original = self._quarantine_copy(hist, "original-before-repair")
                    with open(hist, "r+b") as fh:
                        fh.truncate(sc.good_prefix_len)
                        fh.flush()
                        os.fsync(fh.fileno())
                    rep.history_repaired.append({"file": str(hist), "original_copy": str(original),
                                                 "truncated_to": sc.good_prefix_len,
                                                 "corruption": sc.corruption_detected})
            for cp in sorted((self.root / "checkpoints").glob("*.json")):
                if cp.name.endswith(".prev.json"):
                    continue
                self._collect_pending(cp.stem, current_epoch, rep)
            # a conversation whose current is missing but prev exists
            for prev in sorted((self.root / "checkpoints").glob("*.prev.json")):
                conv = prev.name[: -len(".prev.json")]
                if not self._checkpoint(conv).exists():
                    rep.checkpoint_current_missing_prev_used.append(conv)
                    self._collect_pending(conv, current_epoch, rep)
        return rep

    def _collect_pending(self, conv: str, current_epoch: str, rep: RecoveryReport) -> None:
        res = self._load_checkpoint(conv)
        rep.warnings.extend(res.warnings)
        if res.version_refused:
            rep.checkpoint_frozen_unsupported_major.append(conv)
            rep.checkpoint_last_sequence[conv] = None
            rep.pending_max_turn_sequence[conv] = None
            return
        if not res.checkpoint_available:
            rep.checkpoint_last_sequence[conv] = None
            rep.pending_max_turn_sequence[conv] = None
            return
        doc = res.checkpoint
        if rep.previous_epoch is None:
            rep.previous_epoch = doc.get("epoch")
        rep.checkpoint_last_sequence[conv] = doc.get("last_sequence")
        turn_seqs = []
        for p in doc.get("pending", []):
            item = dict(p, conversation_id=conv)
            turn_seqs.append(p["turn_sequence"])
            if p.get("epoch") != current_epoch:
                item["prior_state"] = p.get("state")   # e.g. cancel_requested survives the restart
                item["state"] = "stale_unresolved"
                rep.stale_unresolved.append(item)
            else:
                rep.still_pending.append(item)
        rep.pending_max_turn_sequence[conv] = max(turn_seqs) if turn_seqs else None


def file_hashes(root: str | os.PathLike) -> dict[str, str]:
    """SHA256 of every file under root, for evidence tables."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class NoopStore:
    """Demo adapter for the first communication demonstration (no persistence).

    Same five functions as FileStore. Every save answers persisted=False and
    storage='noop-demo' so communication can never infer durability from a
    call returning. Loads answer empty; recover answers nothing pending.
    """

    STORAGE = "noop-demo"

    def capabilities(self) -> dict:
        return {"durable": False, "storage": self.STORAGE}

    def save_completed_turn(self, turn: dict) -> dict:
        FileStore._validate_turn(turn)
        return {"event_id": turn["event_id"], "duplicate": False,
                "persisted": False, "storage": self.STORAGE}

    def save_checkpoint(self, conversation_id: str, checkpoint: dict) -> dict:
        validate_conversation_id(conversation_id)
        if not isinstance(checkpoint.get("epoch"), str) or not checkpoint["epoch"]:
            raise ValueError("checkpoint.epoch must be a non-empty string")
        return {"checkpoint_seq": None, "persisted": False, "storage": self.STORAGE}

    def load_history(self, conversation_id: str, since_sequence: int = 0) -> dict:
        return asdict(HistoryResult(warnings=["noop-demo storage: nothing is ever restored"]))

    def load_checkpoint(self, conversation_id: str) -> dict:
        return asdict(CheckpointResult(warnings=["noop-demo storage: no checkpoint exists"]))

    def recover(self, current_epoch: str) -> dict:
        return asdict(RecoveryReport(warnings=["noop-demo storage: nothing to recover"]))
