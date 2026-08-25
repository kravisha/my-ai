"""Kumbhakarnan: the COO's identity as persisted state (addendum 42 §3, §4,
§18, §19, §20; TASK_QUEUE TQ-35, docs/SPEC_RECONCILIATION.md §88).

## What this is for

Addendum 42 §19, in one sentence: "Changing implementation versions must not
silently replace the COO's identity."

The principle already lived here in a narrower form. The owner decision of
2026-08-17 made `agent_names` the durable agent and `agent_registry.identity`
the desk it sits at, so a name survives a process, a crash and a respawn. What
did not exist was an identity that survives *the code* — an entity with its own
id, its own creation moment and its own version, which a rewritten COO
implementation inherits rather than replaces.

That distinction is the whole module. An agent identity answers "who is at this
desk". This answers "who is the COO", and the answer must be the same tomorrow
when the implementation behind it is different.

## Three versions, deliberately not one (§4)

§4 is unusually explicit: "Do not assume software version and persistence schema
version are the same." So three fields, never collapsed:

- **Software version** — the implementation, from `backend.version.code_version()`.
  It changes on every commit and means nothing about the identity.
- **Schema version** (`SCHEMA_VERSION`) — the shape of the stored row. It changes
  when this table changes, and it is what TQ-36's migrations will step through.
- **Identity version** (`IDENTITY_VERSION`) — the persona. It changes when
  Kumbhakarnan himself is meant to change, which is an owner decision and not
  something a deployment does.

Collapsing any two would mean a routine deploy could look like a new person, or
a persona change could look like a migration. Both are the failure §19 names.

## Creation happens once, and only once

`ensure()` is idempotent by construction: after the first call, every later call
returns the stored row untouched — same `coo_id`, same `created_at`. It is
called from `fi_db.init_schema`, which runs in *every* agent process, so "once"
has to mean once across processes rather than once per import.

The one thing `ensure()` will update is `software_version_last_seen`, and it
records the change in `coo_identity_history` when it differs. That is the audit
trail §15 asks for, and it is what makes "this identity has survived N software
versions" a fact the system can state rather than a claim.

A rename is possible, but it is `rename()` — explicit, reasoned, and recorded.
There is deliberately no path by which redeploying changes the name.

## Nothing here is fabricated (§11)

The seeded personality, voice and visual identity are not invented: they are the
owner's own specifications, from addendum 41 §4/§12/§13, addendum 42 §20, and
the language preference recorded in §77. `software_version` comes from
`code_version()`, whose contract is "a true answer or 'unknown'" and which never
guesses. `relationship_history` starts as an empty list because no relationship
has been recorded yet — which is accurate, and different from the
`needs_reconstruction` vocabulary §11 reserves for facts that were lost.

## The visual identity is stored, not remembered

§20 constrains how Kumbhakarnan may be drawn: an original interpretation of the
Kumbhakarna tradition, and explicitly not a copy of any film, television, comic,
game or commercial depiction. That constraint is persisted with the identity
rather than left in a specification, so whoever eventually renders the presenter
reads it from the state they are rendering instead of having to know it.
"""

from __future__ import annotations

import json
import uuid

from backend.db import Database, now_iso
from backend.version import code_version

# B: the shape of the stored row. TQ-36 steps migrations through this.
SCHEMA_VERSION = 1

# C: the persona. Bumped when Kumbhakarnan is meant to change, which is an
# owner decision - never by a deployment.
IDENTITY_VERSION = 1

# §3/§19. The default only ever applies at creation; a stored name always wins,
# which is the mechanism behind "must not silently replace".
DEFAULT_NAME = "Kumbhakarnan"
COO_ROLE = "coo"

# One COO per organization (§3: "a long-lived organizational entity"). The id is
# a column rather than an assumption so that "one organization, many windows"
# (addendum 40 §2) does not quietly become one database, many COOs.
DEFAULT_ORGANIZATION_ID = "my-ai"

# Change kinds recorded in the history. A closed vocabulary, and unknown values
# are refused rather than defaulted - the house rule for anything that will be
# read back and reasoned about.
CHANGE_CREATED = "created"
CHANGE_RENAMED = "renamed"
CHANGE_SOFTWARE_VERSION = "software_version_changed"
CHANGE_PERSONA = "identity_version_changed"
CHANGE_KINDS = frozenset(
    {CHANGE_CREATED, CHANGE_RENAMED, CHANGE_SOFTWARE_VERSION, CHANGE_PERSONA})


# --- what Kumbhakarnan is, as specified by the owner ---------------------------
#
# Seeded at creation and stored thereafter. These are quotations of the
# specification, not inventions: addendum 41 §4 and §12/§13 for bearing and
# expression, addendum 42 §20 for the visual direction, and the language
# preference recorded in SPEC_RECONCILIATION §77.

DEFAULT_PERSONALITY = {
    "bearing": ["dignified", "calm", "observant", "approachable", "executive authority",
                "warm human presence"],
    "manner": "Reports from the organization's own state, leads with the answer, and says "
              "plainly when it does not have something.",
    "source": "addendum 41 §4, §12, §13",
}

DEFAULT_VOICE_IDENTITY = {
    # The owner's stated preference (§77): Tamil, and English in a Tamil accent.
    "preferred_language": "en-IN",
    "fallback_language": "en",
    "also_speaks": ["ta", "en"],
    # Which voices actually exist is the browser's answer, not ours - the console
    # says so rather than promising an accent the operating system may not have.
    "synthesis": "browser-provided; no voice is bundled or assumed",
    "source": "SPEC_RECONCILIATION §77",
}

DEFAULT_VISUAL_IDENTITY = {
    "direction": ["regal", "powerful", "calm", "wise", "grounded", "approachable",
                  "executive", "distinctive crown", "traditional royal-inspired attire",
                  "strong physical presence", "original visual interpretation"],
    # Persisted deliberately: this is a constraint on how the presenter may be
    # rendered, and it belongs with the thing being rendered rather than in a
    # document the renderer's author may never open.
    "must_not": "Copy any specific film, television, comic, game or commercial depiction. "
                "The character is an original interpretation inspired by the Kumbhakarna "
                "tradition.",
    "rendered": False,
    "rendered_note": "No animated presenter exists yet. Addendum 41 §3 rules out a static "
                     "portrait standing in for one, so the console shows a nameplate.",
    "source": "addendum 42 §20, addendum 41 §3, §4",
}

DEFAULT_PREFERENCES = {
    "answers_in": "the language the operator writes in",
    "briefing": "lead with what needs attention, then what changed",
}

SCHEMA = """
-- The COO as a long-lived organizational entity (addendum 42 §3). One row per
-- organization: the identity that a rewritten COO implementation inherits
-- rather than replaces.
CREATE TABLE IF NOT EXISTS coo_identity (
    coo_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    -- §4's three version types, kept apart on purpose. Conflating any two would
    -- let a deploy look like a new person, or a persona change look like a
    -- migration.
    identity_version INTEGER NOT NULL DEFAULT 1,
    schema_version INTEGER NOT NULL DEFAULT 1,
    software_version_at_creation TEXT NOT NULL,
    software_version_last_seen TEXT NOT NULL,
    -- JSON, because these are the owner's specifications rather than anything
    -- this system computes or queries across.
    personality TEXT NOT NULL,
    voice_identity TEXT NOT NULL,
    visual_identity TEXT NOT NULL,
    preferences TEXT NOT NULL,
    relationship_history TEXT NOT NULL,
    last_persisted_at TEXT NOT NULL
);

-- Every change to the identity, including its creation (addendum 42 §15's audit
-- trail). This is what lets the system state "this identity has survived N
-- software versions" as a fact rather than a claim.
CREATE TABLE IF NOT EXISTS coo_identity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coo_id TEXT NOT NULL,
    at TEXT NOT NULL,
    change TEXT NOT NULL,
    detail TEXT,
    software_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS coo_identity_history_by_coo ON coo_identity_history (coo_id, id);
"""


class IdentityFromTheFuture(ValueError):
    """Stored identity written by a newer schema than this code understands.

    Its own class because the remedy is an upgrade, not a reset. §22: a snapshot
    that fails validation is preserved for diagnosis, never destroyed - and
    overwriting the COO's identity because this build could not read it would be
    the single worst thing this module could do."""


class UnknownChange(ValueError):
    """A history entry with a change kind outside the vocabulary.

    Fail closed rather than record an unrecognised word: the history is read
    back and reasoned about, and a silently accepted typo is a gap in an audit
    trail that still looks complete."""


def _record(conn: Database, coo_id: str, change: str, detail: str | None) -> None:
    if change not in CHANGE_KINDS:
        raise UnknownChange(
            f"unknown identity change {change!r}; known kinds are {sorted(CHANGE_KINDS)}")
    conn.execute(
        "INSERT INTO coo_identity_history (coo_id, at, change, detail, software_version, "
        "schema_version) VALUES (?, ?, ?, ?, ?, ?)",
        (coo_id, now_iso(), change, detail, code_version(), SCHEMA_VERSION),
    )


def _row_to_identity(row) -> dict:
    if row["schema_version"] > SCHEMA_VERSION:
        raise IdentityFromTheFuture(
            f"the stored COO identity was written by schema version {row['schema_version']}, "
            f"newer than this build understands ({SCHEMA_VERSION}). It has been left untouched; "
            "upgrade rather than replacing Kumbhakarnan."
        )
    return {
        "coo_id": row["coo_id"],
        "organization_id": row["organization_id"],
        "name": row["name"],
        "role": row["role"],
        "created_at": row["created_at"],
        "identity_version": row["identity_version"],
        "schema_version": row["schema_version"],
        "software_version_at_creation": row["software_version_at_creation"],
        "software_version_last_seen": row["software_version_last_seen"],
        "personality": json.loads(row["personality"]),
        "voice_identity": json.loads(row["voice_identity"]),
        "visual_identity": json.loads(row["visual_identity"]),
        "preferences": json.loads(row["preferences"]),
        "relationship_history": json.loads(row["relationship_history"]),
        "last_persisted_at": row["last_persisted_at"],
    }


def load(conn: Database, *, organization_id: str = DEFAULT_ORGANIZATION_ID) -> dict | None:
    """The stored identity, or None if this organization has never had one.

    None rather than a fabricated default: "no COO identity exists yet" is a
    real state with a real answer, and inventing one here would mean callers
    could not tell a fresh database from a restored one."""
    row = conn.fetchone(
        "SELECT * FROM coo_identity WHERE organization_id = ?", (organization_id,))
    return None if row is None else _row_to_identity(row)


def ensure(conn: Database, *, organization_id: str = DEFAULT_ORGANIZATION_ID) -> dict:
    """The organization's COO identity, created if this is the first time.

    Idempotent across processes, not merely across calls: `fi_db.init_schema`
    runs in every agent process, so two agents starting at once must not produce
    two Kumbhakarnans. The INSERT is guarded by the UNIQUE on organization_id
    and a re-read, rather than by a check-then-write that a second process could
    interleave with.

    On an existing identity this updates exactly one field -
    `software_version_last_seen` - and records the change when it differs. The
    name, the id and the creation moment are never touched here, which is the
    mechanical form of §19's "must not silently replace"."""
    existing = load(conn, organization_id=organization_id)
    if existing is not None:
        return _note_software_version(conn, existing)

    now = now_iso()
    version = code_version()
    coo_id = f"coo-{uuid.uuid4().hex[:16]}"
    conn.execute(
        "INSERT OR IGNORE INTO coo_identity ("
        "coo_id, organization_id, name, role, created_at, identity_version, schema_version, "
        "software_version_at_creation, software_version_last_seen, personality, voice_identity, "
        "visual_identity, preferences, relationship_history, last_persisted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (coo_id, organization_id, DEFAULT_NAME, COO_ROLE, now, IDENTITY_VERSION, SCHEMA_VERSION,
         version, version,
         json.dumps(DEFAULT_PERSONALITY), json.dumps(DEFAULT_VOICE_IDENTITY),
         json.dumps(DEFAULT_VISUAL_IDENTITY), json.dumps(DEFAULT_PREFERENCES),
         json.dumps([]), now),
    )
    # Re-read rather than trusting the INSERT: with OR IGNORE, another process
    # winning the race is a normal outcome, and the row that exists is the
    # answer whether or not this call wrote it.
    identity = load(conn, organization_id=organization_id)
    if identity is None:  # pragma: no cover - the INSERT either landed or lost to a peer
        raise RuntimeError("COO identity could not be created or read back")
    if identity["coo_id"] == coo_id:
        _record(conn, coo_id, CHANGE_CREATED,
                f"{DEFAULT_NAME} created for organization {organization_id!r}")
    return identity


def _note_software_version(conn: Database, identity: dict) -> dict:
    """Record that the identity has been carried into a new build.

    Only writes when the version actually changed, which rate-limits this to
    real deploys rather than every process start - and makes each history row
    mean something."""
    version = code_version()
    if version == identity["software_version_last_seen"]:
        return identity

    previous = identity["software_version_last_seen"]
    conn.execute(
        "UPDATE coo_identity SET software_version_last_seen = ?, last_persisted_at = ? "
        "WHERE coo_id = ?",
        (version, now_iso(), identity["coo_id"]),
    )
    _record(conn, identity["coo_id"], CHANGE_SOFTWARE_VERSION,
            f"identity carried from software {previous} to {version}")
    identity["software_version_last_seen"] = version
    return identity


def rename(conn: Database, new_name: str, *, reason: str,
           organization_id: str = DEFAULT_ORGANIZATION_ID) -> dict:
    """Change the COO's name, deliberately and on the record.

    A reason is required rather than optional. This is the only path that can
    change the name, and §19's requirement is not that the name is immutable -
    it is that it never changes *silently*. An unexplained rename in the history
    would satisfy the letter of that and miss the point."""
    name = (new_name or "").strip()
    if not name:
        raise ValueError("the COO's name cannot be blank")
    if not (reason or "").strip():
        raise ValueError("renaming the COO requires a reason; §19 forbids a silent replacement")

    identity = load(conn, organization_id=organization_id)
    if identity is None:
        raise ValueError("there is no COO identity to rename")
    if identity["name"] == name:
        return identity

    conn.execute(
        "UPDATE coo_identity SET name = ?, last_persisted_at = ? WHERE coo_id = ?",
        (name, now_iso(), identity["coo_id"]),
    )
    _record(conn, identity["coo_id"], CHANGE_RENAMED,
            f"{identity['name']} -> {name}: {reason.strip()}")
    identity["name"] = name
    return identity


def versions(conn: Database, *, organization_id: str = DEFAULT_ORGANIZATION_ID) -> dict:
    """§4's three version types, side by side and never collapsed.

    Exists so the distinction is answerable rather than merely documented: this
    is the report TQ-36's migration pipeline reads to decide what, if anything,
    needs stepping - and the one a developer reads to find out why a restored
    COO looks different from the code."""
    identity = load(conn, organization_id=organization_id)
    running = code_version()
    if identity is None:
        return {
            "exists": False,
            "software": {"running": running, "stored": None},
            "schema": {"code": SCHEMA_VERSION, "stored": None},
            "identity": {"code": IDENTITY_VERSION, "stored": None},
            "migration_needed": False,
        }
    return {
        "exists": True,
        "software": {
            "running": running,
            "stored": identity["software_version_last_seen"],
            "at_creation": identity["software_version_at_creation"],
            # Not a problem, and said so explicitly: software drift is the
            # expected case and the one §4 warns against reading as a migration.
            "changed": running != identity["software_version_last_seen"],
        },
        "schema": {"code": SCHEMA_VERSION, "stored": identity["schema_version"]},
        "identity": {"code": IDENTITY_VERSION, "stored": identity["identity_version"]},
        "migration_needed": identity["schema_version"] < SCHEMA_VERSION,
    }


def history(conn: Database, *, organization_id: str = DEFAULT_ORGANIZATION_ID,
            limit: int = 50) -> list[dict]:
    """What has happened to this identity, newest last.

    Chronological rather than newest-first: this is a life story, and the one
    question it answers - has this been the same COO throughout - reads
    forwards."""
    identity = load(conn, organization_id=organization_id)
    if identity is None:
        return []
    rows = conn.fetchall(
        "SELECT at, change, detail, software_version, schema_version "
        "FROM coo_identity_history WHERE coo_id = ? ORDER BY id DESC LIMIT ?",
        (identity["coo_id"], max(1, min(limit, 500))),
    )
    return [dict(row) for row in reversed(rows)]


def summary(conn: Database, *, organization_id: str = DEFAULT_ORGANIZATION_ID) -> dict:
    """What a surface needs to introduce the COO, and nothing more.

    The console renders the name from here rather than hard-coding it. That is
    not decoration: a name written into markup is a name a redeploy can change
    without anybody noticing, which is exactly what §19 forbids."""
    identity = load(conn, organization_id=organization_id)
    if identity is None:
        return {"exists": False, "name": None, "role": COO_ROLE,
                "reason": "no COO identity has been created yet"}
    software_versions_seen = sum(
        1 for entry in history(conn, organization_id=organization_id, limit=500)
        if entry["change"] == CHANGE_SOFTWARE_VERSION)
    return {
        "exists": True,
        "coo_id": identity["coo_id"],
        "name": identity["name"],
        "role": identity["role"],
        "created_at": identity["created_at"],
        "identity_version": identity["identity_version"],
        "voice_identity": identity["voice_identity"],
        "visual_identity": identity["visual_identity"],
        # The claim §19 makes worth making, stated as a count rather than a
        # boast: the identity has outlived this many builds.
        "software_versions_survived": software_versions_seen,
    }
