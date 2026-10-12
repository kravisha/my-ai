"""R2 entries: construction, validation, rendering and parsing.

One Markdown heading ``### <message_id>`` followed by one fenced JSON object with exactly
the R2 required fields. Entries append at the physical end of the file; everything
before the first entry is legacy text and is preserved byte for byte. A malformed block
is flagged and retained, never returned as an entry and never executed.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from . import canon

PROTOCOL = "JARVIS-COMMS-R2"
MAX_ENTRY_BYTES = 16 * 1024

REQUIRED: dict[str, tuple] = {
    "protocol": (str,), "message_id": (str,), "conversation_id": (str,), "sequence": (int,),
    "created_at": (str,), "from": (str,), "session_id": (str,), "epoch": (str,), "to": (list,),
    "owner": (str,), "grant_id": (str,), "grant_revision": (int,), "type": (str,),
    "reply_to": (list,), "task_id": (str, type(None)), "body": (str,), "evidence": (list,),
}

TYPES = frozenset({
    "CHECK_IN", "TASK_ASSIGN", "TASK_REQUEST", "QUESTION", "ACK", "ACCEPT", "OBJECTION",
    "PROGRESS", "BLOCKER", "RESULT", "REVIEW", "CANCEL_REQUEST", "CANCEL_ACK", "CORRECTION", "REVOCATION",
    "ERROR",
})

# Never put secrets in the file. These are shapes, not a complete list; the validator is a
# last line, the first line is that no code path ever puts a credential into a body.
SECRET_PATTERNS = [re.compile(p) for p in (
    r"ghp_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}", r"gho_[A-Za-z0-9]{20,}",
    r"sk-[A-Za-z0-9\-_]{20,}", r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}", r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}",
    r"(?i)(password|passwd|secret|token)\s*[:=]\s*\S{8,}",
)]

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$")


def is_uuid(s: object) -> bool:
    return isinstance(s, str) and bool(_UUID.match(s))


def make_entry(*, message_id: str | None = None, conversation_id: str, sequence: int, created_at: str,
               from_: str, session_id: str, epoch: str, to: list[str], owner: str, grant_id: str,
               grant_revision: int, type_: str, body: str, reply_to: list[str] | None = None,
               task_id: str | None = None, evidence: list | None = None) -> dict:
    return {
        "protocol": PROTOCOL, "message_id": message_id or str(uuid.uuid4()), "conversation_id": conversation_id,
        "sequence": sequence, "created_at": created_at, "from": from_, "session_id": session_id, "epoch": epoch,
        "to": list(to), "owner": owner, "grant_id": grant_id, "grant_revision": grant_revision, "type": type_,
        "reply_to": list(reply_to or []), "task_id": task_id, "body": body, "evidence": list(evidence or []),
    }


def validate(entry: object) -> list[str]:
    errs: list[str] = []
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    for k, types in REQUIRED.items():
        if k not in entry:
            errs.append(f"missing required field {k}")
        elif not isinstance(entry[k], types) or (isinstance(entry[k], bool) and bool not in types):
            errs.append(f"field {k} has wrong type {type(entry[k]).__name__}")
    extra = set(entry) - set(REQUIRED)
    if extra:
        errs.append(f"unknown fields {sorted(extra)}")
    if errs:
        return errs
    if entry["protocol"] != PROTOCOL:
        errs.append(f"protocol must be {PROTOCOL}")
    for k in ("message_id", "conversation_id"):
        if not is_uuid(entry[k]):
            errs.append(f"field {k} is not a UUID")
    if entry["task_id"] is not None and not is_uuid(entry["task_id"]):
        errs.append("field task_id is not a UUID")
    if entry["sequence"] < 1:
        errs.append("field sequence must be a positive integer")
    if entry["grant_revision"] < 1:
        errs.append("field grant_revision must be a positive integer")
    if not _RFC3339.match(entry["created_at"]):
        errs.append("field created_at is not RFC3339 with offset")
    if entry["type"] not in TYPES:
        errs.append(f"field type {entry['type']!r} is not an R2 type")
    if not entry["to"] or not all(isinstance(x, str) and x for x in entry["to"]):
        errs.append("field to must be a non-empty list of participant ids")
    if not all(is_uuid(x) for x in entry["reply_to"]):
        errs.append("field reply_to must contain UUIDs")
    for pat in SECRET_PATTERNS:
        if pat.search(entry["body"]) or pat.search(json.dumps(entry["evidence"], ensure_ascii=False)):
            errs.append("body or evidence contains a secret-shaped value; refused")
            break
    try:
        size = len(canon.canonical_bytes(entry))
    except canon.CanonError as e:
        errs.append(f"not canonicalizable: {e}")
        return errs
    if size > MAX_ENTRY_BYTES:
        errs.append(f"entry size {size} bytes exceeds 16 KiB; split with explicit reply references, no truncation")
    return errs


def render(entry: dict) -> str:
    body = json.dumps(entry, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return f"### {entry['message_id']}\n```json\n{body}\n```\n"


@dataclass
class Parsed:
    entry: dict
    sha256: str
    heading_id: str
    start: int
    end: int


@dataclass
class Malformed:
    heading_id: str
    reason: str
    raw: str
    start: int
    end: int


@dataclass
class ParseResult:
    legacy_prefix: str
    entries: list[Parsed] = field(default_factory=list)
    malformed: list[Malformed] = field(default_factory=list)


_HEADING = re.compile(r"^### ([0-9a-fA-F-]{36})[ \t]*\r?$", re.M)


def parse(text: str) -> ParseResult:
    heads = list(_HEADING.finditer(text))
    if not heads:
        return ParseResult(legacy_prefix=text)
    result = ParseResult(legacy_prefix=text[: heads[0].start()])
    for i, h in enumerate(heads):
        start = h.start()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        block = text[start:end]
        hid = h.group(1)
        m = re.search(r"```json\r?\n(.*?)\r?\n```", block, re.S)
        if not m:
            result.malformed.append(Malformed(hid, "no fenced json block", block, start, end))
            continue
        try:
            obj = canon.parse_strict(m.group(1))
        except canon.CanonError as e:
            result.malformed.append(Malformed(hid, f"strict parse failed: {e}", block, start, end))
            continue
        errs = validate(obj)
        if errs:
            result.malformed.append(Malformed(hid, "; ".join(errs), block, start, end))
            continue
        if obj["message_id"] != hid:
            result.malformed.append(Malformed(hid, "heading id does not match message_id", block, start, end))
            continue
        result.entries.append(Parsed(obj, canon.fingerprint(obj), hid, start, end))
    return result
