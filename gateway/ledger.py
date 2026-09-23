"""The life ledger: what happened to Jarvis, in order, and provably unedited.

§4.3 asks for *"an append-oriented chronological record of JARVIS's
experience"*, and §39's second principle says why: if only the final conclusion
survives, part of the learning history has been lost. The ledger is not a log
of tokens (§5 says so outright). It holds the transactions that meant
something - a correction, a decision, a failure, an approval - with enough
context that Jarvis can come back later and reason about the event again (§6).

## Append-only is enforced by shape, not by good intentions

There is no update and no delete in this module, and `tests/test_jarvis_life.py`
asserts that as an absence. A correction to an earlier event is a *later* event
carrying `supersedes_event_id`. The original stays exactly as written, because
§6's whole point is that "what did I believe then?" must remain answerable
after Jarvis has changed his mind.

That is also why the `ledger_event` type declares one status and only one.
Marking the original "superseded" would be an edit to history, performed by the
very mechanism that exists to prevent edits to history.

## The chain

Each event stores the hash of its own content and the hash of the event before
it:

    integrity_hash = sha256(previous_event_hash + "\\n" + canonical(content))

`replay()` recomputes the whole chain and reports the first link that does not
match. That catches an event edited in place, an event removed, and two events
transposed - none of which the DBA's own audit trail would notice, because from
its side each of those is a legal row.

## Sequence numbers, and the race

The sequence number lives in `external_id` as `"<agent>:<12 digits>"`, and that
field is `identifying` on the type. So two appends that both believe they are
event 41 do not both become event 41: the DBA refuses the second with
`duplicate_detected`, and `append` re-reads the tip and tries again. The
alternative - trusting a cached tip - is a chain with a fork in it, discovered
months later by a replay.

The tip is found by counting and then fetching by exact key rather than by
"the newest row", because "newest" is a clock question and a clock that steps
backwards would hand out a sequence number twice.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from gateway import dbaclient, identity

ENTITY_TYPE = "ledger_event"

SCHEMA_VERSION = 1

SEQUENCE_WIDTH = 12

# The hash a first event chains from. A constant rather than "" so that an
# event whose `previous_event_hash` was lost cannot be mistaken for the
# genesis event.
GENESIS_HASH = "genesis"

# §5's list of what belongs in here. Declared so that a caller cannot invent a
# category nobody can later query for.
USER_REQUEST = "user_request"
USER_CORRECTION = "user_correction"
OBSERVATION = "observation"
DECISION = "decision"
CONFLICT_DISCOVERED = "conflict_discovered"
ACTION_FAILED = "action_failed"
ACTION_SUCCEEDED = "action_succeeded"
EVALUATION_RESULT = "evaluation_result"
GAP_SUSPECTED = "gap_suspected"
GAP_REJECTED = "gap_rejected"
GAP_CONFIRMED = "gap_confirmed"
APPROVAL_GRANTED = "approval_granted"
APPROVAL_DENIED = "approval_denied"
CHANGE_PROPOSED = "change_proposed"
TEST_RESULT = "test_result"
ROLLBACK = "rollback"
LESSON = "lesson"
STATE_TRANSITION = "state_transition"
REINTERPRETATION = "reinterpretation"
RESTORE_REPORT = "restore_report"
# The break-glass: a change made to a file behind a separate key, without the
# key, because Krish needed it now. Its own type rather than a flavour of
# `change_proposed`, because "show me every time you overrode your own limits"
# has to be one query and not a text search.
EMERGENCY_OVERRIDE = "emergency_override"

EVENT_TYPES = (
    USER_REQUEST, USER_CORRECTION, OBSERVATION, DECISION, CONFLICT_DISCOVERED,
    ACTION_FAILED, ACTION_SUCCEEDED, EVALUATION_RESULT, GAP_SUSPECTED,
    GAP_REJECTED, GAP_CONFIRMED, APPROVAL_GRANTED, APPROVAL_DENIED,
    CHANGE_PROPOSED, TEST_RESULT, ROLLBACK, LESSON, STATE_TRANSITION,
    REINTERPRETATION, RESTORE_REPORT, EMERGENCY_OVERRIDE,
)

# §7's structured metadata. Stored because §6 asks Jarvis to be able to say what
# he believed *and how firmly* at the time; "inferred" and "verified" reaching
# the same conclusion are not the same event.
INFERRED = "inferred"
VERIFIED = "verified"
ASSERTED_BY_USER = "asserted_by_user"
UNVERIFIED = "unverified"
CONTRADICTED = "contradicted"
VERIFICATION_STATES = (INFERRED, VERIFIED, ASSERTED_BY_USER, UNVERIFIED,
                       CONTRADICTED)

# The fields that go into the hash, in the order they are declared. Everything
# the DBA assigns - the record id, its timestamps, its classification - is left
# out, because those are the database's facts about the row and not the event.
HASHED_FIELDS = (
    "agent", "sequence_number", "occurred_at", "session_id", "event_type",
    "actor", "origin", "origin_id", "input_reference", "observation",
    "assessment", "confidence", "verification_state", "risk_level",
    "related_event_ids", "supersedes_event_id", "checkpoint_id",
    "code_version", "ledger_schema_version", "name",
)

# How many times `append` will re-read the tip and try again after losing a
# sequence-number race. Bounded: an unbounded retry against a DBA that refuses
# every write for some other reason is a spin, not a recovery.
APPEND_ATTEMPTS = 5


class LedgerWriteFailed(RuntimeError):
    """§34's `LEDGER_WRITE_FAILED`, said as such.

    Raised rather than logged. An event that mattered enough to record and was
    not recorded must not leave the caller believing it was."""


class ChainBroken(RuntimeError):
    """A replay found a link that does not verify."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sequence_key(agent: str, sequence_number: int) -> str:
    return f"{agent}:{sequence_number:0{SEQUENCE_WIDTH}d}"


def canonical(content: dict) -> str:
    """The bytes that get hashed.

    Sorted keys and no insignificant whitespace, so that the same event hashes
    the same way on any Python and after any round trip through JSON."""
    return json.dumps({name: content.get(name) for name in HASHED_FIELDS},
                      sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def content_hash(content: dict) -> str:
    return hashlib.sha256(canonical(content).encode("utf-8")).hexdigest()


def chain_hash(previous_hash: str, content: dict) -> str:
    return hashlib.sha256(
        f"{previous_hash}\n{canonical(content)}".encode("utf-8")).hexdigest()


# --- reading ------------------------------------------------------------------


def length(client: dbaclient.DBAClient, agent: str = identity.AGENT_ID) -> int:
    """How many events this agent has. The authoritative sequence position."""
    return client.count(ENTITY_TYPE, {"agent": agent})


def at(client: dbaclient.DBAClient, sequence_number: int,
       agent: str = identity.AGENT_ID) -> dict | None:
    """One event by its sequence number, looked up on the promoted column."""
    if sequence_number < 1:
        return None
    found = client.find(
        ENTITY_TYPE, {"external_id": sequence_key(agent, sequence_number)},
        limit=2)
    if len(found) > 1:
        # Impossible while `external_id` is identifying, and worth saying out
        # loud if it ever becomes possible: two events at one position is a
        # forked chain, and picking one would hide it.
        raise ChainBroken(
            f"two events claim sequence {sequence_number} for {agent}: "
            f"{[record.get('id') for record in found]}")
    return found[0] if found else None


def tip(client: dbaclient.DBAClient,
        agent: str = identity.AGENT_ID) -> dict | None:
    """The last event, or `None` for an agent that has never written one."""
    return at(client, length(client, agent), agent)


def events(client: dbaclient.DBAClient, *, agent: str = identity.AGENT_ID,
           first: int = 1, limit: int = 50) -> list[dict]:
    """A window of the chain, in order, by sequence number.

    Walked by key rather than fetched as a page, so the order is the chain's
    own and not the database's opinion about `created_at`."""
    limit = max(1, min(int(limit), 500))
    out = []
    for number in range(max(1, first), max(1, first) + limit):
        record = at(client, number, agent)
        if record is None:
            break
        out.append(record)
    return out


# --- writing ------------------------------------------------------------------


def append(client: dbaclient.DBAClient, *, event_type: str, summary: str,
           observation: str | None = None, session_id: str | None = None,
           actor: str = "jarvis", origin: str | None = None,
           origin_id: str | None = None, input_reference: str | None = None,
           assessment: str | None = None, confidence: float | None = None,
           verification_state: str | None = None, risk_level: str | None = None,
           related_event_ids: list[str] | None = None,
           supersedes_event_id: str | None = None,
           checkpoint_id: str | None = None,
           agent: str = identity.AGENT_ID) -> dict:
    """Record one event and return it as stored.

    Raises `LedgerWriteFailed` if it could not be written, and never returns a
    record the DBA did not confirm."""
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"{event_type!r} is not a declared ledger event type. Declared: "
            f"{', '.join(EVENT_TYPES)}. Refusing rather than accepting it, "
            f"because an undeclared type is an event nobody can query for.")
    if verification_state is not None and verification_state not in VERIFICATION_STATES:
        raise ValueError(
            f"{verification_state!r} is not one of {VERIFICATION_STATES}")
    if not (summary or "").strip():
        raise ValueError("a ledger event needs a summary: it is the line that "
                         "answers 'what was this?' in a replay.")

    last_refusal: Exception | None = None
    for _ in range(APPEND_ATTEMPTS):
        # Inside the try as well as the write: reading the tip talks to the
        # same service, and an outage there is still "this event was not
        # recorded", not an unrelated exception escaping to the caller.
        try:
            previous = tip(client, agent)
        except dbaclient.Unavailable as exc:
            raise LedgerWriteFailed(
                f"the DBA is unavailable, so the {event_type} event was not "
                f"recorded: {exc}") from exc
        number = int(previous.get("sequence_number") or 0) + 1 if previous else 1
        previous_hash = (previous.get("integrity_hash") or "") if previous else GENESIS_HASH
        if previous is not None and not previous_hash:
            raise ChainBroken(
                f"event {number - 1} for {agent} has no integrity hash, so "
                f"nothing can be chained to it. Replay the ledger before "
                f"appending.")

        content = {
            "name": summary.strip()[:200],
            "agent": agent,
            "sequence_number": number,
            "occurred_at": _now(),
            "session_id": session_id,
            "event_type": event_type,
            "actor": actor,
            "origin": origin,
            "origin_id": origin_id,
            "input_reference": input_reference,
            "observation": observation,
            "assessment": assessment,
            "confidence": confidence,
            "verification_state": verification_state,
            "risk_level": risk_level,
            "related_event_ids": ",".join(related_event_ids or []) or None,
            "supersedes_event_id": supersedes_event_id,
            "checkpoint_id": checkpoint_id,
            "code_version": identity.code_version(),
            "ledger_schema_version": SCHEMA_VERSION,
        }
        data = {name: value for name, value in content.items() if value is not None}
        data["external_id"] = sequence_key(agent, number)
        data["status"] = "recorded"
        data["previous_event_hash"] = previous_hash
        data["integrity_hash"] = chain_hash(previous_hash, content)

        try:
            entity_id = client.create(
                ENTITY_TYPE, data,
                reason=f"life ledger event {number}: {event_type}")
        except dbaclient.Refused as exc:
            if exc.code != dbaclient.DUPLICATE_DETECTED:
                raise LedgerWriteFailed(
                    f"the DBA refused ledger event {number}: {exc}") from exc
            # Somebody else took this sequence number between the read and the
            # write. Re-read the tip and build the event again - including its
            # hash, which chains to a different predecessor now.
            last_refusal = exc
            continue
        except dbaclient.Unavailable as exc:
            raise LedgerWriteFailed(
                f"the DBA is unavailable, so ledger event {number} "
                f"({event_type}) was not recorded: {exc}") from exc

        stored = {**data, "id": entity_id}
        return stored

    raise LedgerWriteFailed(
        f"could not claim a sequence number for {agent} in {APPEND_ATTEMPTS} "
        f"attempts; the last refusal was: {last_refusal}")


def reinterpret(client: dbaclient.DBAClient, *, original_event_id: str,
                lesson: str, why_changed: str,
                confidence: float | None = None,
                session_id: str | None = None,
                agent: str = identity.AGENT_ID) -> dict:
    """Record a new understanding of an earlier event, leaving it intact (§6).

    The original is read first, and the reinterpretation refuses if it is not
    there - a reinterpretation of nothing is a claim about a past that cannot
    be checked."""
    original = client.get(original_event_id)
    if original is None:
        raise ValueError(
            f"{original_event_id} is not an event in the ledger, so there is "
            f"nothing to reinterpret. Refusing rather than recording a lesson "
            f"about an event that may never have happened.")
    return append(
        client, event_type=REINTERPRETATION,
        summary=lesson,
        observation=why_changed,
        assessment=(f"supersedes the earlier reading of "
                    f"{original.get('name') or original_event_id}"),
        confidence=confidence,
        verification_state=INFERRED,
        supersedes_event_id=original_event_id,
        related_event_ids=[original_event_id],
        session_id=session_id, agent=agent)


# --- verifying ----------------------------------------------------------------


def replay(client: dbaclient.DBAClient, *, agent: str = identity.AGENT_ID,
           stop_at_first_break: bool = True) -> dict:
    """Walk the chain from the beginning and check every link.

    Returns a report rather than raising, because "the ledger is damaged from
    event 412 onwards" is something Jarvis must be able to *say* (§34), and an
    exception at the point of damage would lose the part that is still good."""
    total = length(client, agent)
    breaks: list[dict] = []
    previous_hash = GENESIS_HASH
    checked = 0

    for number in range(1, total + 1):
        record = at(client, number, agent)
        if record is None:
            breaks.append({"sequence_number": number, "problem": "missing",
                           "detail": f"event {number} of {total} is not there"})
            if stop_at_first_break:
                break
            continue

        stated_previous = record.get("previous_event_hash") or ""
        if stated_previous != previous_hash:
            breaks.append({
                "sequence_number": number, "problem": "previous_hash_mismatch",
                "detail": (f"event {number} chains from {stated_previous!r}, "
                           f"but event {number - 1} hashes to {previous_hash!r}")})
            if stop_at_first_break:
                break

        recomputed = chain_hash(stated_previous, record)
        stated = record.get("integrity_hash") or ""
        if recomputed != stated:
            breaks.append({
                "sequence_number": number, "problem": "content_changed",
                "detail": (f"event {number} hashes to {recomputed}, but the "
                           f"record says {stated}. Its content was changed "
                           f"after it was written.")})
            if stop_at_first_break:
                break

        previous_hash = stated
        checked += 1

    return {
        "agent": agent,
        "events": total,
        "verified_through": checked,
        "intact": not breaks,
        "breaks": breaks,
        "tip_hash": previous_hash if checked else None,
    }


def history_of(client: dbaclient.DBAClient, *, subject: str,
               agent: str = identity.AGENT_ID, limit: int = 20) -> list[dict]:
    """Events mentioning a subject, oldest first, with supersession noted.

    §25's questions - what did I think, what changed my mind, did I later
    reinterpret it - are answered by reading these in order, which is why they
    are returned in order and not by relevance."""
    found = client.request(
        dbaclient.SEARCH, entity_type=ENTITY_TYPE,
        criteria={"text": subject, "limit": limit})
    matches = (found.get("result") or {}).get("matches") or []
    mine = [record for record in matches if record.get("agent") == agent]
    return sorted(mine, key=lambda record: int(record.get("sequence_number") or 0))
