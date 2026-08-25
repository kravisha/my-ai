"""The personal agent a client meets (addendum 43 §16, addendum 41 §24;
TASK_QUEUE TQ-39, docs/SPEC_RECONCILIATION.md §93).

Addendum 43 §16 asks for a persistent personal agent with a name, a face, a
voice, an identity, scoped memory, authorized access and relationship
continuity, so that "the client should feel as though they are speaking with a
familiar representative of the organization."

Familiar is the whole requirement. An assistant that introduces itself afresh
every session is a search box with manners; what makes a representative feel
like one is that they were the same person last time.

## The same shape as Kumbhakarnan, one per client

`backend/coo_identity.py` (§88) already answers "who is the COO" as persisted
state that outlives the code. This is that pattern applied per client rather
than per organization, and the reasoning carries over unchanged: identity is
created once, a new build inherits it, and a rename is deliberate and recorded.

What differs is the key. The COO belongs to the organization; a client agent
belongs to a **subject** - the account that logged in - because addendum 43 §16's
relationship continuity is with a person, and two clients sharing the `client`
role must not share a representative.

## Why the name comes from here and not from the organization

`fi_db.AGENT_NAME_POOL` is the obvious source and is the wrong one. It lives in
the backend's database, and the Gateway reaches the backend over HTTP - so
drawing a name from it would make meeting your agent for the first time
impossible whenever the backend was down, which addendum 16 §23 explicitly
forbids ("usable when internal components are unavailable"). A representative
who cannot introduce themselves during an outage is not continuity.

So the Gateway keeps its own small pool. The names are drawn deterministically
from the client's own id, then persisted - deterministic so that the same client
gets the same name even in the window before the row is written, persisted
because §16 asks for identity rather than for a hash function.

## Scoped memory is enforced elsewhere, and that is the point

§16's "scoped memory" is not a field on this table - it is `conversations.owner`
in gateway/store.py. Storing a memory *here* would make it something this module
could get wrong; making the conversation itself owned means a client cannot
reach another's transcript even if this module were absent entirely.

That distinction is not academic. Before TQ-39 the Gateway had one conversation
for the whole database, and a client's socket opened onto the operator's
transcript.

## What is deliberately not here

**The face** (43 §16, 41 §24's "stable face"). Nothing renders a face for the
COO either, and §85 recorded why a still image standing in for an animated
presenter fails the specification rather than approximating it. The same holds
one role down. The identity carries the *visual* record so a renderer has
something to read; it does not carry a picture, and it says so.
"""

from __future__ import annotations

import hashlib
import json

from backend.db import Database, now_iso

SCHEMA_VERSION = 1
IDENTITY_VERSION = 1

# The Gateway's own pool - see the module docstring for why it is not the
# organization's. Deliberately small and plain: these are people a client is
# meant to remember, not a namespace.
NAME_POOL = (
    "Ada", "Beatrice", "Caspar", "Delia", "Emil", "Farida", "Gideon", "Halina",
    "Isolde", "Jonah", "Kiran", "Lucia", "Mireille", "Nadim", "Ottilie", "Pavel",
    "Quintus", "Rosalind", "Sabri", "Tomas", "Ursula", "Vikram", "Wilhelmina", "Yusra",
)

DEFAULT_VOICE = {
    "preferred_language": "en",
    "synthesis": "browser-provided; no voice is bundled or assumed",
    "source": "addendum 43 §16 (stable voice)",
}

DEFAULT_VISUAL = {
    "rendered": False,
    "rendered_note": (
        "No face exists yet. Addendum 41 §3 rules out a static portrait standing in for an "
        "animated presenter, and the same reasoning applies one role down (SPEC_RECONCILIATION "
        "§85 disposition 4). This record is what a renderer would read when there is one."
    ),
    "direction": ["approachable", "professional", "consistent across sessions"],
    "source": "addendum 43 §16, addendum 41 §24",
}

SCHEMA = """
-- The persistent representative a client meets (addendum 43 §16). One row per
-- subject, because relationship continuity belongs to a person rather than to
-- a role - two clients sharing the `client` role must not share an agent.
CREATE TABLE IF NOT EXISTS client_agents (
    client_id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    identity_version INTEGER NOT NULL DEFAULT 1,
    voice TEXT NOT NULL,
    visual TEXT NOT NULL,
    -- Relationship continuity, as two facts rather than a feeling: when this
    -- client was last here, and how many times they have been.
    last_seen_at TEXT,
    meetings INTEGER NOT NULL DEFAULT 0
);
"""


class AgentFromTheFuture(ValueError):
    """Stored by a newer build than this one. Refused, never overwritten - the
    same rule §88 applies to the COO, for the same reason: recreating an
    identity because this build could not read it is a silent replacement."""


def _name_for(client_id: str, taken: set[str]) -> str:
    """A stable name, chosen deterministically and then never chosen again.

    Deterministic from the client's own id so the same person gets the same
    name even in the window before the row exists; walked forward on collision
    so two clients are never handed one name. The pool is finite, and when it
    runs out the name is suffixed rather than repeated - a second Ada is worse
    than an Ada 2, because the first is a confusion and the second is only
    plain."""
    digest = int(hashlib.sha256(client_id.encode("utf-8")).hexdigest(), 16)
    start = digest % len(NAME_POOL)
    for offset in range(len(NAME_POOL)):
        candidate = NAME_POOL[(start + offset) % len(NAME_POOL)]
        if candidate not in taken:
            return candidate
    return f"{NAME_POOL[start]} {1 + len(taken) // len(NAME_POOL)}"


def _row_to_agent(row) -> dict:
    if row["schema_version"] > SCHEMA_VERSION:
        raise AgentFromTheFuture(
            f"this client's agent was stored by schema version {row['schema_version']}, newer "
            f"than this build understands ({SCHEMA_VERSION}). Left untouched; upgrade rather "
            "than replacing somebody's representative."
        )
    return {
        "client_id": row["client_id"],
        "name": row["agent_name"],
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
        "identity_version": row["identity_version"],
        "voice": json.loads(row["voice"]),
        "visual": json.loads(row["visual"]),
        "last_seen_at": row["last_seen_at"],
        "meetings": row["meetings"],
    }


def load(conn: Database, client_id: str) -> dict | None:
    row = conn.fetchone("SELECT * FROM client_agents WHERE client_id = ?", (client_id,))
    return None if row is None else _row_to_agent(row)


def ensure(conn: Database, client_id: str) -> dict:
    """This client's agent, created on first meeting and stable thereafter."""
    if not (client_id or "").strip():
        raise ValueError("a client agent needs a client to belong to")
    existing = load(conn, client_id)
    if existing is not None:
        return existing

    taken = {row["agent_name"] for row in conn.fetchall("SELECT agent_name FROM client_agents")}
    conn.execute(
        "INSERT OR IGNORE INTO client_agents (client_id, agent_name, created_at, schema_version, "
        "identity_version, voice, visual, last_seen_at, meetings) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0)",
        (client_id, _name_for(client_id, taken), now_iso(), SCHEMA_VERSION, IDENTITY_VERSION,
         json.dumps(DEFAULT_VOICE), json.dumps(DEFAULT_VISUAL)),
    )
    agent = load(conn, client_id)
    if agent is None:  # pragma: no cover - the INSERT landed or lost to a peer
        raise RuntimeError("client agent could not be created or read back")
    return agent


def greet(conn: Database, client_id: str) -> dict:
    """Record that this client has arrived, and answer with who is meeting them.

    Returns the agent plus a `returning` flag and the previous visit, which is
    what lets the interface say "good to see you again" *truthfully* - and say
    nothing of the kind on a first meeting. §16 asks the client to feel they are
    speaking with a familiar representative; a system that claimed familiarity
    it did not have would be the fastest possible way to lose it."""
    agent = ensure(conn, client_id)
    previous = agent["last_seen_at"]
    conn.execute(
        "UPDATE client_agents SET last_seen_at = ?, meetings = meetings + 1 WHERE client_id = ?",
        (now_iso(), client_id),
    )
    return {
        **agent,
        "returning": agent["meetings"] > 0,
        "last_seen_at": previous,
        "meetings": agent["meetings"] + 1,
    }


def introduction(agent: dict) -> str:
    """What the agent says when the client arrives.

    Grounded in the record, like everything else this system says: a returning
    client is greeted as one because `meetings` says so, and a new client is
    not told they are remembered."""
    name = agent["name"]
    if not agent.get("returning"):
        return (f"Hello — I'm {name}. I'll be your point of contact here. "
                "Ask me anything and I'll tell you what I know, or say plainly when I don't.")
    when = (agent.get("last_seen_at") or "")[:10]
    since = f" We last spoke on {when}." if when else ""
    return f"Good to see you again — {name} here.{since} What can I do for you?"
