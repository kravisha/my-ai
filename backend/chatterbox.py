"""The Chatterbox: a living map of who is talking to whom (owner request
2026-08-25; TASK_QUEUE TQ-27, docs/SPEC_RECONCILIATION.md §77).

Collaboration is the organization's highest-priority competency — addenda 34
§16, 36 §8 and 37 §8 all say so, and 34 §18 makes it a hard leadership gate.
This module is the window onto whether it is actually happening.

## Real conversations, not a metaphor

The organization already holds two kinds of agent-to-agent conversation, and
this reads both rather than inventing a third:

- **Cross-checks** (`cross_check_requests`, addendum 12 §14): Explorer asks
  Speculator what the crowd is saying about a security it has a finding on, or
  the reverse. The requester records its own finding *before* asking, so the
  two views stay independent — that is the shape §14 requires, and it is why
  these are genuine collaboration rather than delegation.
- **UQI questions** (`uqi_requests`, addendum 14 §7): a question put to a
  specific agent about its own work, from an operator or another component.

## What the colours mean, and why silence has its own

Four states, because collapsing them would hide the one that matters:

- `active` — asked, and the responder is inside its answering window.
- `waiting` — asked, still unanswered, and aging toward the timeout. This is
  the state worth watching: it is collaboration slowing down before it fails.
- `completed` — answered. `no_evidence` counts as answered, deliberately: a
  responder that looked and found nothing has said something informative
  (`fi_db`'s own words), and scoring it as failure would teach agents to stay
  quiet rather than report an empty hand.
- `silent` — the timeout expired with no reply. Its own colour because it is
  the actual collaboration failure, and a map that showed it as merely
  "not completed" would bury the finding.

## Health is measured, not asserted

The per-desk responsiveness rates come from `backend/competency.py`'s
collaboration dimensions (TQ-17/§65), which follow that module's rules —
absent is not zero, and a desk nobody has asked anything is *unstated* rather
than scored badly.
"""

from __future__ import annotations

from backend import competency, fi_db
from backend.db import Database, parse_timestamp

STATE_ACTIVE = "active"
STATE_WAITING = "waiting"
STATE_COMPLETED = "completed"
STATE_SILENT = "silent"

# Fraction of the timeout after which a still-unanswered conversation stops
# reading as "in flight" and starts reading as "waiting". A disclosed
# convention (TIMING_CONSTANTS.md's discipline), not a measured threshold:
# it exists to make the map show trouble building before the timeout fires.
WAITING_AFTER = 0.5


def _age_state(created_at: str, timeout_seconds: float, now) -> str:
    try:
        age = (now - parse_timestamp(created_at)).total_seconds()
    except Exception:  # noqa: BLE001 - an unparseable timestamp is not a verdict
        return STATE_ACTIVE
    return STATE_WAITING if age >= timeout_seconds * WAITING_AFTER else STATE_ACTIVE


def _cross_checks(conn: Database, now, limit: int) -> list[dict]:
    rows = conn.fetchall(
        "SELECT id, created_at, requester_identity, requester_role, responder_role, "
        "responder_identity, security, question, status, outcome, answered_at "
        "FROM cross_check_requests ORDER BY id DESC LIMIT ?", (limit,)
    )
    out = []
    for row in rows:
        if row["outcome"] == fi_db.CROSS_CHECK_UNANSWERED:
            state = STATE_SILENT
        elif row["status"] == fi_db.CROSS_CHECK_PENDING:
            state = _age_state(row["created_at"], fi_db.CROSS_CHECK_TIMEOUT_SECONDS, now)
        else:
            state = STATE_COMPLETED
        out.append({
            "kind": "cross_check",
            "id": row["id"],
            "from": row["requester_identity"],
            "from_role": row["requester_role"],
            "to": row["responder_identity"] or f"{row['responder_role']} (whoever is on duty)",
            "to_role": row["responder_role"],
            "about": row["security"],
            "question": row["question"],
            "state": state,
            "outcome": row["outcome"],
            "asked_at": row["created_at"],
            "answered_at": row["answered_at"],
        })
    return out


def _uqi(conn: Database, now, limit: int) -> list[dict]:
    rows = conn.fetchall(
        "SELECT id, created_at, asked_by, target_identity, question, status, answered_at "
        "FROM uqi_requests ORDER BY id DESC LIMIT ?", (limit,)
    )
    out = []
    for row in rows:
        if row["status"] == fi_db.UQI_UNANSWERED:
            state = STATE_SILENT
        elif row["status"] == fi_db.UQI_PENDING:
            state = _age_state(row["created_at"], fi_db.UQI_TIMEOUT_SECONDS, now)
        else:
            state = STATE_COMPLETED
        out.append({
            "kind": "question",
            "id": row["id"],
            "from": row["asked_by"],
            "from_role": None,
            "to": row["target_identity"],
            "to_role": None,
            "about": None,
            "question": row["question"],
            "state": state,
            "outcome": row["status"],
            "asked_at": row["created_at"],
            "answered_at": row["answered_at"],
        })
    return out


def _health(conn: Database) -> list[dict]:
    """Per-desk collaboration standing, from the measured dimensions (§65).

    `competency`'s rules carry over untouched: a desk nobody has asked
    anything is *unstated*, never scored badly, so a new arrival does not
    appear on this map as a poor collaborator."""
    health = []
    for row in conn.fetchall("SELECT name FROM agent_names WHERE assigned_to_identity IS NOT NULL"):
        name = row["name"]
        try:
            profile = fi_db.competency_profile(conn, name)
        except Exception:  # noqa: BLE001 - one unreadable profile is not the map's problem
            continue
        entry = {"name": name}
        for key in ("collaboration_responsiveness", "uqi_responsiveness"):
            dimension = profile["dimensions"].get(key, {})
            entry[key] = {
                "stated": dimension.get("stated", False),
                "score": dimension.get("score"),
                "samples": dimension.get("samples", 0),
                "reason": dimension.get("reason"),
            }
        health.append(entry)
    return sorted(health, key=lambda h: h["name"])


def living_map(conn: Database, *, limit: int = 60, now=None) -> dict:
    """Every conversation the organization is holding, newest first, plus the
    measured health of the desks holding them.

    Reports emptiness as a fact: an organization whose agents have never
    spoken to each other is a finding about collaboration, not a blank
    table."""
    from datetime import datetime, timezone

    now = now or datetime.now(timezone.utc)
    conversations = _cross_checks(conn, now, limit) + _uqi(conn, now, limit)
    conversations.sort(key=lambda c: c["asked_at"], reverse=True)
    conversations = conversations[:limit]

    counts = {state: 0 for state in (STATE_ACTIVE, STATE_WAITING, STATE_COMPLETED, STATE_SILENT)}
    for conversation in conversations:
        counts[conversation["state"]] = counts.get(conversation["state"], 0) + 1

    # Who talks to whom, as edges - the map behind the list.
    edges: dict[tuple[str, str], dict] = {}
    for conversation in conversations:
        key = (conversation["from"], conversation["to"])
        edge = edges.setdefault(key, {"from": key[0], "to": key[1], "total": 0, **{s: 0 for s in counts}})
        edge["total"] += 1
        edge[conversation["state"]] += 1

    return {
        "conversations": conversations,
        "counts": counts,
        "edges": sorted(edges.values(), key=lambda e: e["total"], reverse=True),
        "health": _health(conn),
        "quiet": not conversations,
        "quiet_note": (
            "No agent has spoken to another yet. Cross-checks are filed when Explorer or "
            "Speculator has a finding worth a second opinion, so silence here means either "
            "a young organization or one that is not finding anything — both are findings, "
            "not blanks."
        ),
        "note": "Collaboration is this organization's highest-priority competency "
                "(addenda 34 §16, 36 §8, 37 §8). 'Silent' is its own state because a "
                "question that timed out is the actual failure, and burying it in "
                "'not completed' would hide it.",
    }
