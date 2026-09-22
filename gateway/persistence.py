"""Jarvis's durable state: the things he must still know after being restarted.

§4.1 lists what has to survive - identity, configuration, policies, knowledge,
skills, goals, commitments, tasks, the current step, provenance, confidence,
schema versions. All of it lives in the DBA's `agent_state` records, reached
over the published interface in `gateway/dbaclient.py`. Nothing here writes to
a file and nothing here opens a database.

## State is revised, never overwritten

Writing a new value as an *update* would make §8's checkpoints unimplementable
and §22's rollback a promise with nothing behind it: once the old value is gone,
"restore the previous known-good state" has nothing to restore. So every write
appends a new revision and marks the one it replaces `superseded`. Reading the
state as it was at some earlier moment is then just a filter on
`effective_from`, which is how `gateway/checkpoint.py` restores without needing
a manifest of what to put back.

That is a real cost - the table grows with every correction - and it is the
right one. The alternative buys disk space with the ability to answer §25's
questions, and those questions are the point of the whole specification.

## Two `current` rows is a state, not a crash

Nothing serialises writers, so two processes can both append revision 4. Rather
than pretend that cannot happen, `current()` resolves it the same way every
time - highest revision wins - and `reconcile()` tidies the loser. A reader that
picked arbitrarily would give two callers different answers about the same fact,
which is the one failure this module exists to prevent.

## §9's layers

`TIER` is a declaration, not a schedule. It says which kinds of state are
written the moment they change and which may wait for the periodic flush,
because §9's instruction - *"do not serialize the entire system after every
message"* - is a policy about importance, and importance is the sort of thing
that should be legible in one place rather than spread across the call sites
that happen to decide it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from gateway import dbaclient, identity

ENTITY_TYPE = "agent_state"

CURRENT = "current"
SUPERSEDED = "superseded"

# --- §4.1's list, as the `kind` of a state item -------------------------------

IDENTITY = "identity"
CONFIGURATION = "configuration"
POLICY = "policy"
KNOWLEDGE = "knowledge"
SKILL = "skill"
LEARNING = "learning"
CORRECTION = "correction"
PREFERENCE = "preference"
GOAL = "goal"
COMMITMENT = "commitment"
TASK = "task"
WORKFLOW = "workflow"
CURRENT_STEP = "current_step"
INTERMEDIATE_RESULT = "intermediate_result"
TOOL_CONFIG = "tool_config"
CAPABILITY = "capability"
LIMITATION = "limitation"
SELF_ASSESSMENT = "self_assessment"

KINDS = (IDENTITY, CONFIGURATION, POLICY, KNOWLEDGE, SKILL, LEARNING,
         CORRECTION, PREFERENCE, GOAL, COMMITMENT, TASK, WORKFLOW,
         CURRENT_STEP, INTERMEDIATE_RESULT, TOOL_CONFIG, CAPABILITY,
         LIMITATION, SELF_ASSESSMENT)

# --- §9's layered persistence -------------------------------------------------

IMMEDIATE = "immediate"
PERIODIC = "periodic"

# §9 names the immediate list outright: a critical correction, a commitment, an
# approval, a denial, an identity change, confirmed learning, an important
# irreversible state change. Everything else may wait.
TIER: dict[str, str] = {
    IDENTITY: IMMEDIATE,
    POLICY: IMMEDIATE,
    CORRECTION: IMMEDIATE,
    COMMITMENT: IMMEDIATE,
    PREFERENCE: IMMEDIATE,
    LIMITATION: IMMEDIATE,
    CONFIGURATION: PERIODIC,
    KNOWLEDGE: PERIODIC,
    SKILL: PERIODIC,
    LEARNING: PERIODIC,
    GOAL: PERIODIC,
    TASK: PERIODIC,
    WORKFLOW: PERIODIC,
    CURRENT_STEP: PERIODIC,
    INTERMEDIATE_RESULT: PERIODIC,
    TOOL_CONFIG: PERIODIC,
    CAPABILITY: PERIODIC,
    SELF_ASSESSMENT: PERIODIC,
}

# §10's vocabulary. A restored item says which of these it is, and
# `gateway/rehydrate.py` refuses to let Jarvis state a `RECONSTRUCTED` item as
# though it were a `RESTORED` one.
RESTORED = "restored"
RECONSTRUCTED = "reconstructed"
INFERRED = "inferred"
RE_VERIFIED = "re_verified"
UNAVAILABLE = "unavailable"
MEMORY_STATES = (RESTORED, RECONSTRUCTED, INFERRED, RE_VERIFIED, UNAVAILABLE)


class UnknownKind(ValueError):
    """A kind of state nobody declared.

    Refused rather than accepted, because §4.1's list is what rehydration walks
    and an item filed under an undeclared kind is one that never comes back."""


def _now() -> str:
    """Microseconds, not seconds.

    Seconds was the first version and it was wrong: two revisions written in
    the same second were indistinguishable to `as_of`, so a checkpoint taken
    between them restored the one that *replaced* the value it meant to keep.
    The precision is not decoration - it is what makes "the state as it stood
    at that moment" a well-defined question."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def decode(record: dict) -> Any:
    """The stored value, or the raw text if it was not written by this module.

    Raw text rather than a raise: a state item somebody wrote by hand is still
    worth restoring, and losing it because it is not JSON would be the module
    deciding that only its own writes count as memory."""
    raw = record.get("value")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise UnknownKind(
            f"{kind!r} is not a declared kind of durable state. Declared: "
            f"{', '.join(KINDS)}.")
    return kind


def tier(kind: str) -> str:
    """Whether this kind is written immediately or may wait (§9)."""
    return TIER.get(_check_kind(kind), PERIODIC)


# --- reading ------------------------------------------------------------------


def current(client: dbaclient.DBAClient, *, kind: str | None = None,
            name: str | None = None, agent: str = identity.AGENT_ID,
            limit: int = 200) -> list[dict]:
    """Every live state item, newest revision per name.

    The de-duplication is here rather than left to the caller because two
    processes appending the same revision is a thing that happens, and a reader
    that returned both would let two callers disagree about one fact."""
    criteria: dict[str, Any] = {"agent": agent, "status": CURRENT}
    if kind is not None:
        criteria["kind"] = _check_kind(kind)
    if name is not None:
        criteria["name"] = name
    rows = client.find(ENTITY_TYPE, criteria, limit=limit)
    return _newest_per_item(rows)


def _newest_per_item(rows: list[dict]) -> list[dict]:
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.get("kind") or "", row.get("name") or "")
        held = best.get(key)
        if held is None or int(row.get("revision") or 0) > int(held.get("revision") or 0):
            best[key] = row
    return [best[key] for key in sorted(best)]


def get(client: dbaclient.DBAClient, kind: str, name: str, *,
        agent: str = identity.AGENT_ID) -> Any:
    """One state item's value, or `None` if it was never written."""
    found = current(client, kind=kind, name=name, agent=agent, limit=20)
    return decode(found[0]) if found else None


def as_of(client: dbaclient.DBAClient, when: str, *,
          agent: str = identity.AGENT_ID, limit: int = 500) -> list[dict]:
    """State as it stood at a moment - what `checkpoint.restore` reads.

    Every revision is fetched, not only the live ones, and the newest revision
    whose `effective_from` is at or before `when` wins. A revision written
    *after* the checkpoint is not part of it, which is the whole point."""
    rows = client.find(ENTITY_TYPE, {"agent": agent}, limit=limit)
    eligible = [row for row in rows
                if (row.get("effective_from") or "") <= when]
    return _newest_per_item(eligible)


def history(client: dbaclient.DBAClient, kind: str, name: str, *,
            agent: str = identity.AGENT_ID, limit: int = 100) -> list[dict]:
    """Every revision of one item, oldest first. §25's "what did I think then"."""
    rows = client.find(ENTITY_TYPE,
                       {"agent": agent, "kind": _check_kind(kind), "name": name},
                       limit=limit)
    return sorted(rows, key=lambda row: int(row.get("revision") or 0))


# --- writing ------------------------------------------------------------------


def put(client: dbaclient.DBAClient, kind: str, name: str, value: Any, *,
        agent: str = identity.AGENT_ID, reason: str | None = None) -> dict:
    """Append a new revision of one state item and retire the one it replaces.

    Returns the stored record. The retirement of the previous revision is
    deliberately *after* the new one is written: interrupted between the two,
    the reader sees two `current` rows and resolves to the newer, which is
    recoverable. Interrupted the other way round it would see none, and a
    remembered fact would have disappeared because the process died."""
    _check_kind(kind)
    if not (name or "").strip():
        raise ValueError("a state item needs a name; it is how it comes back.")

    existing = current(client, kind=kind, name=name, agent=agent, limit=20)
    revision = max((int(row.get("revision") or 0) for row in existing), default=0) + 1

    data = {
        "name": name, "agent": agent, "kind": kind,
        "value": _encode(value), "status": CURRENT,
        "revision": revision, "effective_from": _now(),
    }
    entity_id = client.create(
        ENTITY_TYPE, data,
        reason=reason or f"{kind} state {name!r} revision {revision}")

    for row in existing:
        _retire(client, row)
    return {**data, "id": entity_id}


def _retire(client: dbaclient.DBAClient, row: dict) -> None:
    """Mark one revision superseded, tolerating a race that already did it.

    A failure here is not raised: the new revision is already written and is
    what every reader resolves to. Turning a tidy-up failure into a write
    failure would mean reporting that a fact was not remembered when it was."""
    try:
        client.update(row["id"], {"status": SUPERSEDED},
                      reason="superseded by a newer revision")
    except (dbaclient.Refused, dbaclient.Unavailable, KeyError):
        pass


def reconcile(client: dbaclient.DBAClient, *,
              agent: str = identity.AGENT_ID) -> list[dict]:
    """Retire any duplicate `current` rows, keeping the highest revision.

    Returns what it retired, so that a caller can say so rather than tidying
    silently. Called on rehydration, where a crash mid-`put` is likeliest to
    have left one behind."""
    rows = client.find(ENTITY_TYPE, {"agent": agent, "status": CURRENT}, limit=500)
    keep = {row["id"] for row in _newest_per_item(rows)}
    retired = []
    for row in rows:
        if row.get("id") not in keep:
            _retire(client, row)
            retired.append(row)
    return retired


# --- integrity ----------------------------------------------------------------


def fingerprint(items: list[dict]) -> str:
    """A hash of a set of state items, for a checkpoint to verify itself against.

    Over (kind, name, revision, value) and nothing else: the record id and its
    timestamps are the database's facts about the row, and including them would
    make a checkpoint fail validation after an untouched record was merely
    re-read."""
    digest = hashlib.sha256()
    for row in sorted(items, key=lambda item: (item.get("kind") or "",
                                               item.get("name") or "")):
        digest.update(_encode([row.get("kind"), row.get("name"),
                               int(row.get("revision") or 0),
                               row.get("value")]).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def counts(items: list[dict]) -> dict[str, int]:
    """How many items of each kind, for a checkpoint's `item_counts`."""
    out: dict[str, int] = {}
    for row in items:
        kind = row.get("kind") or "unknown"
        out[kind] = out.get(kind, 0) + 1
    return out
