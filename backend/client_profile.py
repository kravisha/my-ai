"""What a client told this system about how to serve them
(TASK_QUEUE TQ-98; addendum 51 §4, §13, §15; owner direction §111;
docs/SPEC_RECONCILIATION.md §140 §5, §143).

Every Providence agent is personal, and a personal agent works within *that
client's* permissions, profile, preferences and goals (51 §4). Nothing here can
be personal until there is a profile to be personal about.

## This is the first client data the *backend* keeps

The first draft of this docstring said *the first client data this system keeps*,
and the tripwire below disproved it before the module ran: `gateway/client_agent.py`
has persisted `client_agents` since addendum 43 §16 - the named representative a
client meets, its voice and visual identity, when they were last here and how many
times. Client-scoped, durable, and older than this increment.

The distinction that survives is worth more than the claim that did not:

- **`client_agents` is the system's record of serving somebody.** The Gateway
  assigns the name; the client never stated it.
- **This module holds the client's own statements.** Nobody derived them, and
  nobody may.

And they sit in different databases for the reason §109 gives: the Gateway
establishes identity, the backend holds business logic. A preference is business
logic.

Until now the backend's rule was simple and absolute: **the database is a
transport, not a store.** A request is deleted when claimed, a report when
collected, a session's rows on disconnect (§117). Owner direction §111: *"the
system... holds no information of the portfolios in the system."*

A profile cannot work that way. A preference discarded at disconnect is not a
preference; it is a question asked again every session. So this store persists,
and the boundary between what persists and what must not has to be **structural
rather than remembered**, because the version of §111 that gets undone is not the
one somebody argues against - it is the one somebody stores next to.

## The boundary, from §140 §5

- **A profile is what the client *told* the system.** Tone, topics, pacing,
  consent. Supplied deliberately, and §111 never spoke about it.
- **A portfolio is what the client *owns*.** Positions, quantities, cost bases.
  Never stored, unchanged, and `holdings` still fetches and discards.
- **A watchlist is the line**, and it is the reason this module exists at all.
  Symbols a client typed are a preference. Symbols derived from a fetched
  portfolio are a portfolio wearing a preference's name, and **the two are
  identical as data.**

## What actually holds that line, and it is not the `source` column

The tempting design is provenance: tag each symbol `client_stated`, refuse
anything else, and call the boundary enforced. That is worth having and it is
**not** the guarantee, because a caller writing a derived symbol can pass
`client_stated` and nothing here would know. A guard whose whole strength is the
honesty of its caller should be described as a convention.

The property this schema really has is smaller, structural, and worth more:

> **A watchlist entry is a symbol and nothing else.**

There is no quantity column, no cost basis, no account, no price, no value, no
as-of. So even a watchlist assembled entirely from a fetched portfolio is *not a
portfolio* - the facts that make positions worth protecting have nowhere to go.
Writing them would take a schema change, and `tests/test_client_profile.py` fails
the suite when a column appears that could hold one.

That is the same argument §120 makes about the safest write path being the one
that does not exist, and it is why the guard was written before the table (§105:
build the table first and re-aim the guard afterwards, and the constraint erodes).

## The vocabulary is closed, so the profile cannot grow a portfolio

Addendum 51 §15's fields and no others. An unknown key is **refused, not stored**
- `PREFERENCES` is the complete list of what this system will remember about a
person, in one place a reader can check against §15.

An open key-value store would have made every guard above decorative: nothing
stops `set_preference(owner, "holdings", ...)` if any key is acceptable.

## Ownership is evidence, never a parameter

Every function takes an `OwnerContext`, built by the Gateway from the session
subject and never from anything a caller sent (addendum 44 §9.2). A `client_id`
string argument would mean any agent could read or rewrite any client's profile
by knowing their name.

Sits below `fi_db`, so it must not import it - and it must not import
`holdings`, `consolidation` or `portfolio_providers` either. A module that could
read positions and write a profile is one import away from deriving a watchlist,
and that import is what the tripwire watches for.
"""

from __future__ import annotations

import json
import re

from backend.db import Database, now_iso
from backend.portfolios import OwnerContext

SCHEMA = """
CREATE TABLE IF NOT EXISTS client_preferences (
    -- One row per client per preference. Keyed by both, so a client has at most
    -- one answer to each question and no merge is ever needed.
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    stated_at TEXT NOT NULL,
    PRIMARY KEY (owner_type, owner_id, key)
);

CREATE TABLE IF NOT EXISTS client_watchlist (
    -- **A symbol and nothing else.** No quantity, no cost basis, no account, no
    -- price, no value, no as-of. A watchlist assembled from a fetched portfolio
    -- would still not be a portfolio, because what makes positions worth
    -- protecting has nowhere to go (owner direction, SPEC_RECONCILIATION 111).
    --
    -- Adding a column here is the change that would undo that, which is why a
    -- test fails the suite when one appears.
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    -- How it got here. Closed vocabulary, and `client_stated` is the only
    -- accepted value - see the module docstring for why this is a convention
    -- rather than the guarantee.
    source TEXT NOT NULL,
    stated_at TEXT NOT NULL,
    PRIMARY KEY (owner_type, owner_id, symbol)
);
"""

SCHEMA_VERSION = 1

# Addendum 51 §15, complete, and nothing else. **This tuple is the entire list of
# what this system will remember about a person**, which is what makes it worth
# keeping in one readable place rather than spread over a schema.
PREFERENCES = (
    "preferred_name",
    "preferred_language",
    "preferred_tone",
    "preferred_pacing",
    "preferred_humor",
    "preferred_visual_style",
    "preferred_persona_archetype",
    "preferred_topics",
    "disliked_topics",
    "explanation_depth",
    "correction_style",
    "interruption_tolerance",
    "conversation_style",
    "entertainment_preferences",
    "consented_reference_material",
    "accessibility_preferences",
)

# Which of them are lists. Declared rather than inferred from what a caller
# passed: a field that silently accepted either shape would be read differently
# by two callers, and neither would be wrong.
LIST_PREFERENCES = frozenset({
    "preferred_topics", "disliked_topics", "entertainment_preferences",
    "consented_reference_material", "accessibility_preferences",
})

# The only way a symbol may enter a watchlist.
SOURCE_CLIENT_STATED = "client_stated"
WATCHLIST_SOURCES = (SOURCE_CLIENT_STATED,)

# What a symbol may look like. Deliberately narrow: this store holds identifiers,
# and a field that accepted arbitrary text is a field somebody will eventually
# put a note in.
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")


class ProfileRefused(ValueError):
    """Something this store will not remember about a person."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def _owner(owner) -> tuple[str, str]:
    """Ownership is evidence, so this refuses anything that is not.

    A `client_id` string is a claim; an `OwnerContext` was built server-side from
    a session subject (addendum 44 §9.2). Accepting the string would let any
    agent read or rewrite any client's profile by knowing their name."""
    if not isinstance(owner, OwnerContext):
        raise ProfileRefused(
            "A profile is read and written under an OwnerContext resolved from the session, "
            "never under a client id somebody passed. A name is a claim, not a proof.")
    return owner.owner_type, owner.owner_id


def set_preference(conn: Database, owner, *, key: str, value) -> None:
    """Remember one thing the client told us.

    **Refuses a key that is not addendum 51 §15's**, which is what keeps this from
    becoming somewhere a portfolio can live. An open store would make every other
    guard here decorative."""
    owner_type, owner_id = _owner(owner)
    if key not in PREFERENCES:
        raise ProfileRefused(
            f"{key!r} is not something this system remembers about a person. "
            f"Known preferences are {list(PREFERENCES)} (addendum 51 §15). "
            f"The list is closed on purpose: an open one is where a portfolio ends up.")
    if key in LIST_PREFERENCES:
        if not isinstance(value, (list, tuple)):
            raise ProfileRefused(f"{key!r} is a list of values.")
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        stored = json.dumps(cleaned)
    else:
        if isinstance(value, (list, tuple, dict)):
            raise ProfileRefused(f"{key!r} is a single value.")
        text = str(value).strip()
        if not text:
            raise ProfileRefused(
                f"{key!r} with no value states nothing. Use `forget_preference` to remove it - "
                f"an empty string and an unstated preference are different facts.")
        stored = text
    conn.execute(
        "INSERT INTO client_preferences (owner_type, owner_id, key, value, stated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (owner_type, owner_id, key) DO UPDATE SET value = ?, stated_at = ?",
        (owner_type, owner_id, key, stored, now_iso(), stored, now_iso()))


def preferences(conn: Database, owner) -> dict:
    """Everything this client has stated, and nothing they have not.

    **A key they never answered is absent, never a default.** §100, §104, §118 and
    §132's rule, and it matters more here than usual: a profile that returned
    `preferred_tone='neutral'` for somebody who never said would have the agent
    acting on a preference the client does not hold, indistinguishably from one
    they do."""
    owner_type, owner_id = _owner(owner)
    stated = {}
    for row in conn.fetchall(
            "SELECT key, value FROM client_preferences WHERE owner_type = ? AND owner_id = ?"
            " ORDER BY key", (owner_type, owner_id)):
        stated[row["key"]] = (json.loads(row["value"]) if row["key"] in LIST_PREFERENCES
                              else row["value"])
    return stated


def unstated(conn: Database, owner) -> list[str]:
    """What this client has not told us, by name.

    The counterpart to `preferences`, and it exists so an agent can *ask* rather
    than assume. Addendum 49's patience rules want an Usher that finds out; a
    system that only exposed what it knew would leave finding out to a guess."""
    return [key for key in PREFERENCES if key not in preferences(conn, owner)]


def forget_preference(conn: Database, owner, *, key: str) -> None:
    """Unstate something. Distinct from setting it empty, which is a statement."""
    owner_type, owner_id = _owner(owner)
    conn.execute(
        "DELETE FROM client_preferences WHERE owner_type = ? AND owner_id = ? AND key = ?",
        (owner_type, owner_id, key))


# --- the watchlist, which is the line -------------------------------------------------

def add_to_watchlist(conn: Database, owner, *, symbol: str,
                     source: str = SOURCE_CLIENT_STATED) -> None:
    """Remember a symbol the client asked to follow.

    **Only `client_stated`.** A symbol derived from a fetched portfolio is a
    holding, and this system does not store holdings (§111). The refusal names
    the reason rather than being identical, because nothing is concealed by it:
    there is one legitimate source and a caller with a derived symbol needs to
    know that carrying it here is the thing being refused.

    Read the module docstring for what this does and does not guarantee. The
    column is a convention; the absence of a quantity column is the guarantee."""
    owner_type, owner_id = _owner(owner)
    if source not in WATCHLIST_SOURCES:
        raise ProfileRefused(
            f"{source!r} is not a way a symbol may enter a watchlist. The only one is "
            f"{SOURCE_CLIENT_STATED!r}: a symbol the client typed is a preference, and a "
            f"symbol derived from a fetched portfolio is a holding, which this system does "
            f"not store (SPEC_RECONCILIATION 111).")
    symbol = (symbol or "").strip().upper()
    if not _SYMBOL.match(symbol):
        raise ProfileRefused(
            f"{symbol!r} is not a symbol. This store holds identifiers, and a field that "
            f"took arbitrary text is a field somebody puts a note in.")
    conn.execute(
        "INSERT INTO client_watchlist (owner_type, owner_id, symbol, source, stated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (owner_type, owner_id, symbol) DO NOTHING",
        (owner_type, owner_id, symbol, source, now_iso()))


def watchlist(conn: Database, owner) -> list[str]:
    """The symbols this client follows. Symbols, and nothing about them."""
    owner_type, owner_id = _owner(owner)
    return [row["symbol"] for row in conn.fetchall(
        "SELECT symbol FROM client_watchlist WHERE owner_type = ? AND owner_id = ?"
        " ORDER BY symbol", (owner_type, owner_id))]


def remove_from_watchlist(conn: Database, owner, *, symbol: str) -> None:
    owner_type, owner_id = _owner(owner)
    conn.execute(
        "DELETE FROM client_watchlist WHERE owner_type = ? AND owner_id = ? AND symbol = ?",
        (owner_type, owner_id, (symbol or "").strip().upper()))


# --- leaving ---------------------------------------------------------------------------

def forget_everything(conn: Database, owner) -> dict:
    """Remove everything this system remembers about a person.

    **Required rather than convenient.** Every other client-scoped store in this
    database disappears on its own - a request when claimed, a report when
    collected, a session's rows on disconnect. This one persists by design, so it
    would otherwise outlive the client's interest in it, and the way out has to be
    a function rather than a database session.

    It does not reach `client_agents`, which is the Gateway's and is reached
    through the Gateway. A backend function that deleted rows from `gateway.db`
    would be the boundary §109 draws, crossed for convenience.

    Returns what it removed, by count. A caller told *"done"* cannot tell a
    successful deletion from a mistyped owner."""
    owner_type, owner_id = _owner(owner)
    removed = {}
    for table in ("client_preferences", "client_watchlist"):
        row = conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table} WHERE owner_type = ? AND owner_id = ?",
            (owner_type, owner_id))
        removed[table] = (row or {}).get("n", 0)
        conn.execute(f"DELETE FROM {table} WHERE owner_type = ? AND owner_id = ?",
                     (owner_type, owner_id))
    return removed


def summary(conn: Database, owner) -> dict:
    """What is known and what is not, for an agent about to serve this client."""
    stated = preferences(conn, owner)
    return {
        "stated": stated,
        # Named, not counted. An agent that knows *which* preferences are missing
        # can ask; one that knows six are missing cannot.
        "unstated": [key for key in PREFERENCES if key not in stated],
        "watchlist": watchlist(conn, owner),
        # Said every time, because this is the one client store that persists and
        # a reader should never have to infer the boundary from what is absent.
        "not_held": [
            "positions, quantities and cost bases - fetched per session and "
            "discarded (SPEC_RECONCILIATION 111)",
            "anything about a watchlist symbol beyond the symbol itself",
        ],
    }
