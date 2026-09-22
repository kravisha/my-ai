"""§8's checkpoints: validated points Jarvis can be put back to.

    checkpoint_000001
    checkpoint_000002
    checkpoint_000003

A checkpoint here is **not** a copy of the state. It is a validated marker into
state that is already durable and already versioned - see
`gateway/persistence.py`, where every write appends a revision instead of
overwriting one. Restoring to a checkpoint means reading the revision of each
item that was current when the checkpoint was taken, which needs no manifest
and cannot drift from the thing it describes.

That design was forced, and the constraint was the right one. Jarvis does not
hold the DBA's `administer` permission, so he cannot order a database backup -
§16's *"JARVIS must never autonomously grant himself new permissions"* made
structural in `dba/permissions.POLICY`. Rather than widen the permission, the
checkpoint was built out of what Jarvis legitimately has. A snapshot mechanism
that required Jarvis to be able to administer the database would have been the
specification's own boundary traded away for convenience.

## Validated before authoritative, and a write-complete marker

§8 asks for both. A checkpoint is created `writing`, then its contents are
hashed and compared, and only then does it become `valid`. A checkpoint still
marked `writing` is one whose process died mid-write; `latest_valid()` skips it
and `validate()` says why. Nothing falls back to "probably fine".

## What makes a restore honest

`ledger_tip_sequence` records how far the life ledger had got. After a crash,
the events after that point are the interval that may have been lost, and
`interval_at_risk()` names it. §3 step 8 asks Jarvis to identify what failed to
restore; a checkpoint that recorded only state would leave him guessing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from gateway import dbaclient, identity, ledger, persistence

ENTITY_TYPE = "checkpoint"

WRITING = "writing"
VALID = "valid"
INVALID = "invalid"
SUPERSEDED = "superseded"

SEQUENCE_WIDTH = 6

# Why a checkpoint was taken. §9's checkpoint layer names these three; the
# fourth is the one §20 requires before a self-modification.
MILESTONE = "milestone"
BEFORE_SHUTDOWN = "before_shutdown"
AFTER_RELAUNCH = "after_relaunch"
BEFORE_SELF_MODIFICATION = "before_self_modification"
REASONS = (MILESTONE, BEFORE_SHUTDOWN, AFTER_RELAUNCH,
           BEFORE_SELF_MODIFICATION)


class CheckpointInvalid(RuntimeError):
    """§34's `CHECKPOINT_INVALID`, said as such rather than returned as false."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sequence_key(agent: str, number: int) -> str:
    return f"{agent}:ckpt:{number:0{SEQUENCE_WIDTH}d}"


def label(number: int) -> str:
    return f"checkpoint_{number:0{SEQUENCE_WIDTH}d}"


def item_counts(record: dict) -> dict[str, int]:
    """A stored checkpoint's per-kind counts, decoded."""
    raw = record.get("item_counts")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}


# --- reading ------------------------------------------------------------------


def all_checkpoints(client: dbaclient.DBAClient, *,
                    agent: str = identity.AGENT_ID,
                    limit: int = 200) -> list[dict]:
    """Every checkpoint for this agent, oldest first."""
    rows = client.find(ENTITY_TYPE, {"agent": agent}, limit=limit)
    return sorted(rows, key=lambda row: int(row.get("sequence_number") or 0))


def latest_valid(client: dbaclient.DBAClient, *,
                 agent: str = identity.AGENT_ID) -> dict | None:
    """The newest checkpoint marked valid, or `None`.

    §8's *"fallback must use the most recent valid checkpoint"*. A `writing` or
    `invalid` checkpoint is skipped rather than repaired: a checkpoint whose
    validity is in doubt is exactly the thing this is supposed to protect
    against."""
    for record in reversed(all_checkpoints(client, agent=agent)):
        if record.get("status") == VALID:
            return record
    return None


def previous_valid(client: dbaclient.DBAClient, before: dict, *,
                   agent: str = identity.AGENT_ID) -> dict | None:
    """The newest valid checkpoint older than this one (§8's recoverable parent)."""
    position = int(before.get("sequence_number") or 0)
    for record in reversed(all_checkpoints(client, agent=agent)):
        if (record.get("status") == VALID
                and int(record.get("sequence_number") or 0) < position):
            return record
    return None


# --- taking -------------------------------------------------------------------


def take(client: dbaclient.DBAClient, *, reason: str = MILESTONE,
         agent: str = identity.AGENT_ID) -> dict:
    """Take a checkpoint, validate it, and return it.

    Raises `CheckpointInvalid` if it could not be validated, leaving the record
    behind marked `invalid` rather than deleting it. A checkpoint that failed is
    evidence; removing it would make the failure unexplainable afterwards."""
    if reason not in REASONS:
        raise ValueError(f"{reason!r} is not one of {REASONS}")

    existing = all_checkpoints(client, agent=agent)
    number = max((int(row.get("sequence_number") or 0) for row in existing),
                 default=0) + 1
    parent = latest_valid(client, agent=agent)

    # Stamp the moment first, then hash *the state as of that moment* - the
    # same query `validate` will run. Reading the live state and stamping
    # afterwards meant a write landing in between made the checkpoint fail its
    # own validation the instant it was written.
    taken_at = _now()
    items = persistence.as_of(client, taken_at, agent=agent)
    tip = ledger.tip(client, agent)

    data = {
        "name": label(number),
        "external_id": sequence_key(agent, number),
        "status": WRITING,
        "agent": agent,
        "sequence_number": number,
        "taken_at": taken_at,
        "reason": reason,
        "code_version": identity.code_version(),
        "state_schema_version": identity.STATE_SCHEMA_VERSION,
        "ledger_tip_sequence": int(tip.get("sequence_number") or 0) if tip else 0,
        "ledger_tip_hash": (tip.get("integrity_hash") if tip else None),
        "contents_hash": persistence.fingerprint(items),
        # JSON text, because the DBA types this field TEXT and a dict
        # would be refused by its validator rather than silently stored.
        "item_counts": json.dumps(persistence.counts(items), sort_keys=True),
    }
    if parent is not None:
        data["parent_checkpoint_id"] = parent.get("id")
    data = {name: value for name, value in data.items() if value is not None}

    entity_id = client.create(ENTITY_TYPE, data,
                              reason=f"checkpoint {number} ({reason})")
    record = {**data, "id": entity_id}

    verdict = validate(client, record, agent=agent)
    if not verdict["valid"]:
        client.update(entity_id, {"status": INVALID,
                                  "invalid_reason": verdict["why"]},
                      reason="checkpoint failed its own validation")
        raise CheckpointInvalid(
            f"{label(number)} was written but did not validate: {verdict['why']}")

    client.update(entity_id, {"status": VALID, "validated_at": _now()},
                  reason="checkpoint validated")
    record["status"] = VALID
    return record


# --- validating ---------------------------------------------------------------


def validate(client: dbaclient.DBAClient, record: dict, *,
             agent: str = identity.AGENT_ID) -> dict:
    """Check a checkpoint against the state it claims to describe.

    Returns a verdict rather than raising, because §34 wants
    `CHECKPOINT_INVALID` represented and a caller walking backwards through
    checkpoints needs to keep walking."""
    if record.get("status") == WRITING and record.get("validated_at"):
        return {"valid": False,
                "why": "marked as still being written but carries a validation "
                       "time; the record is inconsistent with itself"}

    taken_at = record.get("taken_at")
    if not taken_at:
        return {"valid": False, "why": "no taken_at, so it describes no moment"}

    stated = record.get("contents_hash")
    if not stated:
        return {"valid": False,
                "why": "no contents_hash, so nothing about it can be checked"}

    items = persistence.as_of(client, taken_at, agent=agent)
    recomputed = persistence.fingerprint(items)
    if recomputed != stated:
        return {"valid": False,
                "why": (f"the state as of {taken_at} hashes to {recomputed}, "
                        f"but the checkpoint says {stated}. Either the state "
                        f"was altered behind it or the checkpoint is damaged.")}

    expected_version = int(record.get("state_schema_version") or 0)
    if expected_version > identity.STATE_SCHEMA_VERSION:
        return {"valid": False,
                "why": (f"written by state schema {expected_version}; this "
                        f"runtime understands {identity.STATE_SCHEMA_VERSION}. "
                        f"Refusing to read it optimistically.")}

    return {"valid": True, "why": "", "items": len(items)}


def reject(client: dbaclient.DBAClient, record: dict, why: str) -> dict:
    """Mark a checkpoint invalid, keeping it and the reason.

    §8 says corrupted checkpoints must be rejected. Rejected, not removed: the
    reason a restore fell back is part of what §22 asks the system to be able
    to explain."""
    client.update(record["id"], {"status": INVALID, "invalid_reason": why},
                  reason="checkpoint rejected")
    return {**record, "status": INVALID, "invalid_reason": why}


def newest_usable(client: dbaclient.DBAClient, *,
                  agent: str = identity.AGENT_ID) -> tuple[dict | None, list[dict]]:
    """The newest checkpoint that actually validates, plus the ones it stepped over.

    This is §8's fallback, and the second half of the return value is why it is
    a pair: TEST C asks that Jarvis *report* the rollback, and a function that
    quietly returned the older checkpoint would make that impossible."""
    skipped: list[dict] = []
    for record in reversed(all_checkpoints(client, agent=agent)):
        if record.get("status") == INVALID:
            skipped.append(record)
            continue
        if record.get("status") == WRITING:
            skipped.append(reject(
                client, record,
                "still marked as being written: the process that took it did "
                "not finish, so its contents were never verified."))
            continue
        if record.get("status") != VALID:
            continue
        verdict = validate(client, record, agent=agent)
        if verdict["valid"]:
            return record, skipped
        skipped.append(reject(client, record, verdict["why"]))
    return None, skipped


# --- restoring ----------------------------------------------------------------


def restore(client: dbaclient.DBAClient, record: dict, *,
            agent: str = identity.AGENT_ID) -> dict:
    """The state this checkpoint describes, and what happened after it.

    Reads; it does not write. Putting the old values back as new revisions
    would rewrite the present in order to describe the past - and §6 is
    explicit that the later record is a layer on the earlier one, not a
    replacement for it. What a caller gets is the *view*, plus an honest
    account of the interval that came after."""
    verdict = validate(client, record, agent=agent)
    if not verdict["valid"]:
        raise CheckpointInvalid(
            f"{record.get('name')} will not restore: {verdict['why']}")

    taken_at = record["taken_at"]
    items = persistence.as_of(client, taken_at, agent=agent)
    return {
        "checkpoint": record.get("name"),
        "checkpoint_id": record.get("id"),
        "taken_at": taken_at,
        "code_version": record.get("code_version"),
        "items": items,
        # A dict here: this is a view returned to a caller, not a field being
        # written to a TEXT column.
        "item_counts": persistence.counts(items),
        "ledger_tip_sequence": int(record.get("ledger_tip_sequence") or 0),
        "interval_at_risk": interval_at_risk(client, record, agent=agent),
    }


def interval_at_risk(client: dbaclient.DBAClient, record: dict, *,
                     agent: str = identity.AGENT_ID) -> dict:
    """Ledger events written after this checkpoint - TEST B's "lost interval".

    They are not lost, exactly: they are in the ledger, and that is the point.
    What may be lost is whatever they *would have caused* had the process not
    died, and naming them is how Jarvis says so instead of assuming."""
    from_sequence = int(record.get("ledger_tip_sequence") or 0) + 1
    total = ledger.length(client, agent)
    if total < from_sequence:
        return {"events": 0, "from_sequence": from_sequence, "to_sequence": total,
                "detail": "nothing was written after this checkpoint"}
    after = ledger.events(client, agent=agent, first=from_sequence,
                          limit=min(500, total - from_sequence + 1))
    return {
        "events": len(after),
        "from_sequence": from_sequence,
        "to_sequence": total,
        "detail": (f"{len(after)} ledger event(s) were recorded after this "
                   f"checkpoint and are not described by it"),
        "summaries": [row.get("name") for row in after[:20]],
    }
