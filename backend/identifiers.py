"""Jarvis-owned identity for the things the world names inconsistently.

Addendum 20 §3: "Reference entities should use Jarvis-owned internal IDs mapped to
external identifiers." §2D wants the same for issuers, exchanges and option
contracts. This module is that mapping, and the reason it exists is one sentence:

**A symbol is not an identity.**

Tickers are reassigned. `FB` became `META` and the entity did not change; a
delisted ticker can be issued to an unrelated company years later and the entity
did change. An organization that keys observations on the symbol will, sooner or
later, join two companies' histories into one series and never notice - and the
join will look like a discovery, because it will show a break in behaviour exactly
where the reassignment happened.

This is the same argument the organization already accepted for its agents:
`agents/base.py` keeps a permanent role-slot identity precisely so a process
restart does not start a new career. The reasoning transfers exactly - an entity
outlives its names, and the names are attributes of it rather than the other way
round.

## What an identifier row means

`(scheme, value)` resolves to one entity **as of a moment**. `valid_from` and
`valid_to` are what make that a question with a date in it, so a resolution of
`symbol=FB` in 2019 and in 2026 can honestly give different answers - or the same
entity under a name it has since dropped.

The uniqueness rule is deliberately narrow: **at most one live holder of a
(scheme, value) pair at a time**, enforced by a partial index rather than by
whichever caller remembers. History is unconstrained, because history is the
point.

## What is not here

No issuers, exchanges, sectors, calendars or option contract specifications yet -
§2D's full list. `entity_type` exists so they arrive as rows rather than as tables,
but nothing produces them, and a column nobody fills is the empty schema this
project keeps refusing. The first real consumer is the security universe.
"""

from __future__ import annotations

from backend.db import Database, now_iso, parse_timestamp

# What an entity can be. Deliberately short: these are the kinds something in the
# system actually refers to today, and §2D's remaining kinds join the list when
# something produces them.
ENTITY_TYPES = ("security", "issuer", "exchange")

# Identifier schemes this organization understands. `symbol` is the one in use;
# the rest are named because the mapping table is worthless if the vocabulary has
# to be invented at each call site, and a typo'd scheme silently creates a second
# namespace.
SCHEMES = ("symbol", "isin", "cusip", "figi", "internal_legacy")

SCHEMA = """
-- The thing itself, independent of whatever the world is currently calling it.
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('security', 'issuer', 'exchange')),
    display_name TEXT,
    created_at TEXT NOT NULL,
    note TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- What the world calls it, when, and who said so.
CREATE TABLE IF NOT EXISTS entity_identifiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
);

-- One live holder of a (scheme, value) at a time. Closed rows are unconstrained,
-- because a ticker having belonged to something else is history rather than a
-- conflict - and history is the reason this table exists.
CREATE UNIQUE INDEX IF NOT EXISTS entity_identifiers_one_live_holder
    ON entity_identifiers (scheme, value) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS entity_identifiers_by_entity ON entity_identifiers (entity_id, scheme);
CREATE INDEX IF NOT EXISTS entity_identifiers_by_value ON entity_identifiers (scheme, value, valid_from);
"""


class IdentifierError(ValueError):
    """A refusal, phrased for whoever asked."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def _next_entity_id(conn: Database) -> str:
    """A readable, sortable, opaque-enough identity.

    Readable because a human reads these in a log; opaque because it must carry no
    meaning that could later be wrong. `JE-000007` says only "the seventh entity
    this organization created", which cannot become false."""
    row = conn.fetchone("SELECT COUNT(*) AS n FROM entities")
    return f"JE-{(row['n'] if row else 0) + 1:06d}"


def create_entity(
    conn: Database,
    entity_type: str = "security",
    display_name: str | None = None,
    note: str | None = None,
) -> str:
    if entity_type not in ENTITY_TYPES:
        raise IdentifierError(
            f"entity_type must be one of {', '.join(ENTITY_TYPES)}; got {entity_type!r}"
        )
    entity_id = _next_entity_id(conn)
    conn.execute(
        "INSERT INTO entities (entity_id, entity_type, display_name, created_at, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (entity_id, entity_type, display_name, now_iso(), note),
    )
    return entity_id


def add_identifier(
    conn: Database,
    entity_id: str,
    scheme: str,
    value: str,
    source: str,
    valid_from: str | None = None,
) -> int:
    """Attach a name to an entity.

    Refuses a scheme it does not know, because a typo would silently create a
    second namespace that resolves nothing and conflicts with nothing."""
    if scheme not in SCHEMES:
        raise IdentifierError(f"unknown scheme {scheme!r}; this organization understands {', '.join(SCHEMES)}")
    if not (value or "").strip():
        raise IdentifierError("an identifier needs a value")
    if conn.fetchone("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)) is None:
        raise IdentifierError(f"no entity {entity_id!r} to attach {scheme}={value!r} to")

    live = conn.fetchone(
        "SELECT entity_id FROM entity_identifiers WHERE scheme = ? AND value = ? AND valid_to IS NULL",
        (scheme, value),
    )
    if live is not None:
        if live["entity_id"] == entity_id:
            raise IdentifierError(f"{scheme}={value!r} is already live for {entity_id}")
        raise IdentifierError(
            f"{scheme}={value!r} is live for {live['entity_id']}. Retire it there first - a "
            f"reassignment is a sequence of two facts, not one, and recording only the second "
            f"loses the moment the meaning changed."
        )

    return conn.execute_returning_id(
        "INSERT INTO entity_identifiers (entity_id, scheme, value, source, valid_from) "
        "VALUES (?, ?, ?, ?, ?)",
        (entity_id, scheme, value, source, valid_from or now_iso()),
    )


def retire_identifier(conn: Database, scheme: str, value: str, valid_to: str | None = None) -> bool:
    """Stop a name pointing at an entity, without deleting that it once did."""
    changed = conn.execute_returning_rowcount(
        "UPDATE entity_identifiers SET valid_to = ? WHERE scheme = ? AND value = ? AND valid_to IS NULL",
        (valid_to or now_iso(), scheme, value),
    )
    return bool(changed)


def resolve(conn: Database, scheme: str, value: str, as_of: str | None = None) -> str | None:
    """Which entity this name meant at that moment. None if nothing.

    `as_of` defaults to now, which is the common case and the dangerous one: a
    caller resolving a historical observation with today's mapping will attribute
    it to whoever holds the ticker *now*. Historical ingest must pass the
    observation's own date - that is the whole reason the columns are dated."""
    if as_of is None:
        row = conn.fetchone(
            "SELECT entity_id FROM entity_identifiers "
            "WHERE scheme = ? AND value = ? AND valid_to IS NULL",
            (scheme, value),
        )
        return row["entity_id"] if row else None

    moment = parse_timestamp(as_of)
    for row in conn.fetchall(
        "SELECT entity_id, valid_from, valid_to FROM entity_identifiers "
        "WHERE scheme = ? AND value = ? ORDER BY valid_from DESC",
        (scheme, value),
    ):
        if parse_timestamp(row["valid_from"]) <= moment and (
            row["valid_to"] is None or moment < parse_timestamp(row["valid_to"])
        ):
            return row["entity_id"]
    return None


def identifiers_for(conn: Database, entity_id: str, include_retired: bool = False) -> list[dict]:
    sql = "SELECT * FROM entity_identifiers WHERE entity_id = ?"
    if not include_retired:
        sql += " AND valid_to IS NULL"
    return conn.fetchall(sql + " ORDER BY scheme, valid_from", (entity_id,))


def get_entity(conn: Database, entity_id: str) -> dict | None:
    row = conn.fetchone("SELECT * FROM entities WHERE entity_id = ?", (entity_id,))
    return dict(row) if row else None


def ensure_security(conn: Database, symbol: str, source: str = "security_universe") -> str:
    """The bridge from the symbol-keyed world to the entity-keyed one.

    `security_universe` is a list of symbols, and every existing detector event,
    report and analysis names a security by symbol. Rewriting all of that at once
    would be a migration with no consumer asking for it; this gives each symbol an
    entity the moment anything needs one, so the two schemes can coexist while
    the entity-keyed side grows."""
    existing = resolve(conn, "symbol", symbol)
    if existing is not None:
        return existing
    entity_id = create_entity(conn, "security", display_name=symbol)
    add_identifier(conn, entity_id, "symbol", symbol, source=source)
    return entity_id
