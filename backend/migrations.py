"""The migration pipeline, and the way out of stale state (addendum 42 §7–§10,
§14, §22, §23; TASK_QUEUE TQ-36, docs/SPEC_RECONCILIATION.md §89).

## Built before it is needed, deliberately

This system's standing rule is that machinery with no user does not get built.
This module is a reasoned exception, and the reasoning is §23's:

    Validate source snapshot. Create backup snapshot. Record source schema.
    Record target schema. Run migration. Validate migrated state. Only then
    mark the new state active.

The whole value of that ordering is being in place *before* the first upgrade,
because the failure it prevents is destroying state during one. A pipeline
written when the first migration is written is a pipeline whose first
production run is also its first run ever, on the day it matters most.

So the engine exists and the registry is honest: both registered stores are at
version 1 and declare **no migration steps**, because neither has changed shape
yet. `status()` says exactly that rather than implying work is pending. The
engine itself is exercised by tests that register real 1→2 and 2→3 steps — the
tests are its users until a store actually changes.

## Sequential steps, never one converter (§9)

§9 is explicit: "Current COO code should not contain one giant converter for
every historical version. Use sequential migrations." So a store declares
`{1: migrate_1_to_2, 2: migrate_2_to_3}` and the runner composes the path. A
missing rung is a hard failure rather than a skip: state at version 5 with no
`5→6` registered must stop, because jumping it would hand version-9 code a
version-5 row while the version column claimed otherwise.

## What "only then mark active" actually means here

The version column is written by the **runner**, after validation, not by the
migration step. A step transforms data; the runner decides the state is now
that version. That is what gives §23 a real activation moment rather than a
figure of speech.

The whole sequence runs inside one transaction (`Database.transaction`, added
for this - see its docstring). A run that fails at step three leaves nothing
applied and the version unchanged, which is the half-migrated state §23 exists
to prevent.

## Failure preserves (§22)

"Do not destroy it. Log the failure. Try the previous valid snapshot. Preserve
corrupted material for diagnosis." So a failed migration rolls the data back,
records the failure in `schema_migrations` with the exception text, leaves the
pre-migration backup in place, and publishes a status event the console shows.
Nothing is deleted, and the operator is told where the backup is.

## The escape hatches are not a nicety (§14)

"Persistence must help development, not trap developers inside stale state."
That became a live risk the moment identity became persistent (§88): before
TQ-35 a developer could delete the database and start over; now that throws away
the COO. All eight of §14's hatches have a real target today, and they are a CLI
because that is how a developer actually reaches for them:

    python -m backend.migrations status      # compare schema versions
    python -m backend.migrations inspect     # read raw persisted state
    python -m backend.migrations migrate     # run the pipeline, or --force it
    python -m backend.migrations snapshots   # what can be gone back to
    python -m backend.migrations restore ID  # load a specific snapshot / roll back
    python -m backend.migrations reset       # start clean

`reset` is gated on the lifecycle stage being PRE_ALPHA or ALPHA, and takes a
backup first. An escape hatch that can be pulled in production is not a
development convenience, it is a loaded gun; and one that destroys the only copy
is the thing §22 forbids, wearing a helpful name.

Disabling persistence temporarily (§14's fourth hatch) is an environment
variable rather than a command, because it has to hold for a whole session:
`MYAI_PERSISTENCE_DISABLED=1` makes workspace checkpointing a no-op that says so.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable

from backend import (agent_identity, analysis_requests, appeal, client_profile,
                     coo_identity, curriculum, demonstration, engineering, governed_knowledge,
                     identifiers, missions, observations, operating_context,
                     parliament, reference_data, release, risk,
                     register as register_store, software_department,
                     status_events, strategy, workspace)
from backend.db import Database, now_iso
from backend.version import code_version

# §14's fourth hatch. Read at call time rather than import, so a test or a shell
# can turn it on without reloading the process.
PERSISTENCE_DISABLED_ENV = "MYAI_PERSISTENCE_DISABLED"

# Which lifecycle stages may pull a destructive hatch. The same reasoning as the
# plaintext-password gate (§74): a convenience that outlives its stage stops
# being a convenience.
DESTRUCTIVE_STAGES = ("PRE_ALPHA", "ALPHA")

OUTCOME_STARTED = "started"
OUTCOME_MIGRATED = "migrated"
OUTCOME_FAILED = "failed"
OUTCOME_VALIDATION_FAILED = "validation_failed"

SCHEMA = """
-- Every migration attempt, successful or not (addendum 42 §15's audit trail,
-- §23's "record source schema, record target schema"). Failures are rows here
-- rather than absences: an audit trail that only records successes cannot
-- answer the question anybody actually asks it after an incident.
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store TEXT NOT NULL,
    from_version INTEGER NOT NULL,
    to_version INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL,
    detail TEXT,
    -- The pre-migration snapshot (§23). Recorded so a rollback does not depend
    -- on somebody remembering which backup came before which attempt.
    backup_id TEXT,
    software_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS schema_migrations_by_store ON schema_migrations (store, id);

-- What shape each store is in *now*. One row per store, written only by the
-- runner after validation (§23's activation moment).
--
-- This exists because the per-row `schema_version` column that most tables
-- carry is **a different thing wearing the same name**, and using it as a store
-- version destroys what it is for. `fi_db.SCHEMA_VERSION` says so in terms:
-- bump it "when the *meaning* of newly-written rows changes in a way a future
-- reader/grader needs to distinguish from older rows". Rows at v2, v3 and v7
-- coexist deliberately - a v3 detector_event records which lens produced it and
-- a v2 one does not, and a grader reading old rows depends on being able to
-- tell. A store version is the opposite: one value for the whole table, rewritten
-- on migration.
--
-- The first two registered stores conflated them, and their writers issue
-- `UPDATE <table> SET schema_version = ?` across every row. On a single-row
-- identity that is harmless. Applied to fi_db's tables it would restamp every
-- historical row with today's number and erase the provenance the column exists
-- to carry - silently, and only visibly wrong to a grader months later (§156).
CREATE TABLE IF NOT EXISTS store_schema_versions (
    store TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    -- How this store's version came to be known: 'backfill' for a database that
    -- predates version tracking, 'migration' for one the runner moved.
    source TEXT NOT NULL
);
"""


class MissingMigration(RuntimeError):
    """A rung is missing from the ladder.

    Hard failure rather than a skip: jumping a version would hand new code an
    old shape while the version column claimed the conversion had happened,
    which is worse than refusing to start."""


class StateFromTheFuture(RuntimeError):
    """Stored state written by a newer build than this one.

    §22's rule applies with full force: this is not corruption and must not be
    reset. The remedy is to upgrade the code, and the state is left untouched."""


class ValidationFailed(RuntimeError):
    """State did not validate, before or after migrating."""


class HatchRefused(RuntimeError):
    """A destructive development hatch was pulled outside a development stage."""


def persistence_disabled() -> bool:
    """§14's fourth hatch, read at call time so a shell can set it per run."""
    return (os.environ.get(PERSISTENCE_DISABLED_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Store:
    """One versioned body of persisted state.

    `migrations` maps a *from* version to the step that produces the next one,
    which is what makes the ladder walkable in one direction without a table of
    pairs. A step takes the connection and transforms data only - it must not
    write the version column, because the runner owns activation (§23)."""

    name: str
    # The table this store lives in. Named rather than inferred so that "this
    # store has never existed in this database" can be distinguished from "this
    # database is broken" - which is not a nicety: a database that predates a
    # store is precisely the upgrade case this module exists for, and reporting
    # it as unreadable would send a developer looking for corruption that is not
    # there.
    table: str
    code_version: int
    read_version: Callable[[Database], int | None]
    write_version: Callable[[Database, int], None]
    validate: Callable[[Database], list[str]]
    inspect: Callable[[Database], list[dict]]
    migrations: dict[int, Callable[[Database], None]] = field(default_factory=dict)
    note: str = ""
    # Every table this store owns, when it owns more than one. `table` stays the
    # representative - the one whose presence answers "has this store ever
    # existed here" - because a module's tables are created together by one
    # executescript, so any of them existing means all of them do.
    tables: tuple[str, ...] = ()


_REGISTRY: dict[str, Store] = {}


def register(store: Store) -> Store:
    _REGISTRY[store.name] = store
    return store


def stores() -> list[Store]:
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def get(name: str) -> Store:
    if name not in _REGISTRY:
        raise KeyError(f"unknown store {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


# --- store versions, kept apart from row stamps -----------------------------------
#
# See `store_schema_versions` in SCHEMA above for why these are two different
# things. Everything registered below reads and writes its version here; nothing
# touches a row's own `schema_version`, ever.

# What a store is assumed to be at when its tables exist and the engine has never
# recorded a version for it. Deliberately a constant rather than the store's
# `code_version`: stamping "whatever the code says" would assert that an unknown
# database is already current, which is the one assumption a migration engine
# must never make.
BACKFILL_VERSION = 1


class AmbiguousVersion(RuntimeError):
    """A store's tables exist, no version was ever recorded, and the code is past
    the backfill version - so the database could be at any version between them.

    Refused rather than guessed, on §23's rule. The remedy is a person deciding
    which version this database is actually at and recording it."""


def _recorded_version(store_name: str, tables: tuple[str, ...]):
    """Read a store's version from `store_schema_versions`.

    Returns None when the store has never existed in this database, which the
    runner reads as "nothing to migrate" rather than as a fault."""

    def read(conn: Database) -> int | None:
        if not any(table_exists(conn, name) for name in tables):
            return None
        row = conn.fetchone(
            "SELECT version FROM store_schema_versions WHERE store = ?", (store_name,))
        return None if row is None else int(row["version"])

    return read


def _record_version(store_name: str, source: str = "migration"):
    def write(conn: Database, version: int) -> None:
        conn.execute(
            "INSERT INTO store_schema_versions (store, version, recorded_at, source) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(store) DO UPDATE SET version = excluded.version, "
            "recorded_at = excluded.recorded_at, source = excluded.source",
            (store_name, version, now_iso(), source))

    return write


def _rows_in(tables: tuple[str, ...]):
    def inspect(conn: Database) -> list[dict]:
        out = []
        for name in tables:
            if table_exists(conn, name):
                out.append({"table": name, "rows": conn.fetchone(
                    f"SELECT COUNT(*) AS n FROM {name}")["n"]})
        return out

    return inspect


def _tables_present(store_name: str, tables: tuple[str, ...]):
    """The honest generic validator: the tables this store declares are there.

    Deliberately shallow. A validator that invented content rules it had not been
    asked for would fail databases that are fine, and `migrate` refuses to
    proceed on a validation failure - so a wrong validator here is an outage, not
    a warning. The two stores with real content invariants keep their own."""

    def validate(conn: Database) -> list[str]:
        missing = [name for name in tables if not table_exists(conn, name)]
        if missing and len(missing) != len(tables):
            return [f"{store_name}: tables created together are not all present: {missing}"]
        return []

    return validate


def backfill_store_versions(conn: Database) -> list[str]:
    """Record `BACKFILL_VERSION` for registered stores whose tables exist and
    whose version was never tracked.

    Run at startup, once per database. Every store registered today is at code
    version 1 with no migration steps, so a database that predates this tracking
    genuinely is at 1 - there has never been a migration for it to have missed.
    That is only true while `code_version` is 1, which is why the alternative is
    refused rather than assumed."""
    recorded = []
    for store in stores():
        names = store.tables or (store.table,)
        if not any(table_exists(conn, name) for name in names):
            continue  # store has never existed here; nothing to backfill
        if conn.fetchone("SELECT 1 FROM store_schema_versions WHERE store = ?", (store.name,)):
            continue
        if store.code_version > BACKFILL_VERSION:
            raise AmbiguousVersion(
                f"{store.name} exists in this database with no recorded schema version, and this "
                f"build is at version {store.code_version}. The database could be at any version "
                f"between {BACKFILL_VERSION} and {store.code_version}, and guessing either way "
                "would hand new code an old shape or skip a conversion. Record the correct "
                "version in store_schema_versions before starting."
            )
        _record_version(store.name, source="backfill")(conn, BACKFILL_VERSION)
        recorded.append(store.name)
    return recorded


# --- the two stores with content invariants ---------------------------------------
#
# Both at version 1 with no steps, because neither has changed shape yet. Said
# in `note` rather than left to be inferred from an empty dict: "no migrations
# registered" and "migrations forgotten" look identical otherwise.
#
# Their `validate` and `inspect` are specific because there is something real to
# check - one COO, parseable payloads. Their version reading is not: it moved to
# `store_schema_versions` with everything else, because the readers they had
# aggregated a per-row column (MAX for one, MIN for the other - already
# inconsistent) and the writers overwrote every row's stamp.


def _workspace_validate(conn: Database) -> list[str]:
    problems = []
    for row in conn.fetchall("SELECT surface, payload FROM workspace_state"):
        try:
            if not isinstance(json.loads(row["payload"]), dict):
                problems.append(f"workspace {row['surface']!r}: payload is not an object")
        except Exception as exc:  # noqa: BLE001 - the report is the point
            problems.append(f"workspace {row['surface']!r}: payload will not parse ({exc})")
    return problems


def _workspace_inspect(conn: Database) -> list[dict]:
    return conn.fetchall(
        "SELECT surface, schema_version, revision, updated_at, payload FROM workspace_state")


def _identity_validate(conn: Database) -> list[str]:
    rows = conn.fetchall("SELECT * FROM coo_identity")
    if not rows:
        return ["no COO identity exists"]
    if len(rows) > 1:
        return [f"{len(rows)} COO identities exist; there must be exactly one"]
    row = rows[0]
    problems = []
    if not (row["name"] or "").strip():
        problems.append("the COO has no name")
    if not row["created_at"]:
        problems.append("the COO has no creation timestamp")
    for column in ("personality", "voice_identity", "visual_identity", "preferences",
                   "relationship_history"):
        try:
            json.loads(row[column])
        except Exception as exc:  # noqa: BLE001
            problems.append(f"coo_identity.{column} will not parse ({exc})")
    return problems


def _identity_inspect(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM coo_identity")


register(Store(
    name="workspace",
    table="workspace_state",
    tables=("workspace_state",),
    code_version=workspace.SCHEMA_VERSION,
    read_version=_recorded_version("workspace", ("workspace_state",)),
    write_version=_record_version("workspace"),
    validate=_workspace_validate,
    inspect=_workspace_inspect,
    migrations={},
    note="No migrations registered: the workspace payload has not changed shape since "
         "version 1. The payload itself is free-form by design (addendum 40 §5.4), so a "
         "new field is not a migration - only a change to what an existing field *means* "
         "would be.",
))

register(Store(
    name="coo_identity",
    table="coo_identity",
    tables=("coo_identity", "coo_identity_history"),
    code_version=coo_identity.SCHEMA_VERSION,
    read_version=_recorded_version("coo_identity", ("coo_identity", "coo_identity_history")),
    write_version=_record_version("coo_identity"),
    validate=_identity_validate,
    inspect=_identity_inspect,
    migrations={},
    note="No migrations registered: Kumbhakarnan's row has not changed shape since it was "
         "created at version 1 (§88).",
))


# --- every other store that owns tables -------------------------------------------
#
# Registered because a store whose first registration happens on the day it
# migrates is a store whose registration is untested - the same argument that put
# this whole module in place before anything needed it, extended one step. Until
# TQ-110 the engine governed two of twenty-three, so `status()` reported a
# complete picture of 8% of the database and nothing said so.
#
# All at code version 1 with no steps. `code_version` here is **not** the module's
# `SCHEMA_VERSION`: that constant is the row stamp (see `store_schema_versions`),
# and fi_db's is at 7 while its tables have never been migrated once. Conflating
# them would make the runner try to walk 1 -> 7 through six rungs that do not
# exist, and correctly refuse to start.


def tables_in(schema: str) -> tuple[str, ...]:
    """The tables a module's DDL creates, in declaration order.

    Derived rather than listed, because a hand-kept list drifts the moment
    somebody adds a table - and drift here is a table the engine does not know it
    is versioning."""
    return tuple(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", schema))


def register_module(name: str, schema: str, *, note: str) -> Store:
    """Register a module's tables as one store.

    One store per module rather than per table, because a module's tables are
    created by one `executescript` and change together; twenty-three stores is a
    registry somebody reads, and sixty-six is a wall."""
    names = tables_in(schema)
    if not names:
        raise ValueError(f"{name} declares no tables; nothing to register")
    return register(Store(
        name=name,
        table=names[0],
        tables=names,
        code_version=1,
        read_version=_recorded_version(name, names),
        write_version=_record_version(name),
        validate=_tables_present(name, names),
        inspect=_rows_in(names),
        migrations={},
        note=note,
    ))


_NEVER_MIGRATED = ("No migrations registered: this store has not changed shape since "
                   "version 1.")

for _name, _schema in (
    ("agent_identity", agent_identity.SCHEMA),
    ("analysis_requests", analysis_requests.SCHEMA),
    ("appeal", appeal.SCHEMA),
    ("client_profile", client_profile.SCHEMA),
    ("curriculum", curriculum.SCHEMA),
    ("demonstration", demonstration.SCHEMA),
    ("engineering", engineering.SCHEMA),
    ("governed_knowledge", governed_knowledge.SCHEMA),
    ("identifiers", identifiers.SCHEMA),
    ("missions", missions.SCHEMA),
    ("observations", observations.SCHEMA),
    ("operating_context", operating_context.SCHEMA),
    ("parliament", parliament.SCHEMA),
    ("reference_data", reference_data.SCHEMA),
    ("register", register_store.SCHEMA),
    ("release", release.SCHEMA),
    ("risk", risk.SCHEMA),
    ("software_department", software_department.SCHEMA),
    ("status_events", status_events.SCHEMA),
    ("strategy", strategy.SCHEMA),
):
    register_module(_name, _schema, note=_NEVER_MIGRATED)

# `fi_db` is registered from fi_db itself: this module sits below it and must not
# import it. `migrations.SCHEMA`'s own two tables are deliberately not a store -
# they are the engine's bookkeeping, and a migration engine that versioned its own
# audit trail would need itself working in order to repair itself.


# --- reading the situation --------------------------------------------------------


def table_exists(conn: Database, table: str) -> bool:
    """Whether a store has ever been created in this database.

    Asked before reading a version, so that a database predating a store reports
    "not created here" rather than an exception dressed up as corruption."""
    return conn.fetchone(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)) is not None


def _has_state(conn: Database, store: Store) -> bool:
    """Whether any of this store's tables holds a row.

    Asked separately from the version since §156 split them. Cheap enough for a
    CLI: one `LIMIT 1` per table, stopping at the first hit."""
    for name in (store.tables or (store.table,)):
        if not table_exists(conn, name):
            continue
        if conn.fetchone(f"SELECT 1 FROM {name} LIMIT 1") is not None:
            return True
    return False


def plan(store: Store, stored: int) -> list[tuple[int, int]]:
    """The sequential steps from `stored` to this build's version (§8, §9).

    Raises rather than skipping a missing rung, and raises rather than reading
    state from the future - the two ways a version gap can silently corrupt."""
    if stored > store.code_version:
        raise StateFromTheFuture(
            f"{store.name} state is at schema version {stored}, newer than this build "
            f"understands ({store.code_version}). Left untouched - upgrade the code rather "
            "than resetting the state."
        )
    steps = []
    for version in range(stored, store.code_version):
        if version not in store.migrations:
            raise MissingMigration(
                f"{store.name} needs {version} -> {version + 1} but no migration is registered "
                f"for it. Refusing to skip: version {store.code_version} code would be handed a "
                f"version {version} shape with the version column claiming otherwise."
            )
        steps.append((version, version + 1))
    return steps


def status(conn: Database) -> list[dict]:
    """Every registered store, its stored version and this build's (§14's
    "compare schema versions").

    Never raises: this is the command a developer runs *because* something is
    wrong, so a store that cannot be read reports why instead of taking the
    report down with it."""
    report = []
    for store in stores():
        entry = {"store": store.name, "code_version": store.code_version, "note": store.note}
        if not table_exists(conn, store.table):
            # Not a fault. A database written before this store existed is the
            # ordinary upgrade case, and calling it unreadable would send a
            # developer hunting for corruption that is not there.
            entry.update({"stored_version": None, "readable": True, "present": False,
                          "created": False, "needs_migration": False, "steps": [],
                          "problems": [],
                          "problem": f"table {store.table!r} does not exist in this database; "
                                     "it is created by fi_db.init_schema on next start"})
            report.append(entry)
            continue
        try:
            stored = store.read_version(conn)
        except Exception as exc:  # noqa: BLE001 - unreadable is an answer here
            entry.update({"stored_version": None, "readable": False, "problem": str(exc)})
            report.append(entry)
            continue

        entry.update({"stored_version": stored, "readable": True})
        # `created` is "the tables are here"; `present` is "there is state in
        # them". They were one question while the version was an aggregate over
        # rows - an empty table had no MAX(schema_version), so "no data" and "no
        # version" were the same answer by accident. With the version in its own
        # table they separate, and both are worth reporting: a store created and
        # empty is the ordinary state of most of this database, and a store whose
        # tables are missing is an upgrade case (§156).
        entry["created"] = True
        entry["present"] = _has_state(conn, store)
        if stored is None:
            entry.update({"needs_migration": False, "steps": [], "problems": []})
        else:
            try:
                steps = plan(store, stored)
                entry.update({"needs_migration": bool(steps), "steps": steps, "problem": None})
            except (MissingMigration, StateFromTheFuture) as exc:
                entry.update({"needs_migration": True, "steps": None, "problem": str(exc)})
            entry["problems"] = store.validate(conn)
        report.append(entry)
    return report


def pending(conn: Database) -> list[str]:
    """Which stores actually need work. The one-line answer `status()` gives at
    length, for a caller that only wants to know whether to act."""
    return [entry["store"] for entry in status(conn) if entry.get("needs_migration")]


# --- running one ------------------------------------------------------------------


def _record(conn: Database, store: str, source: int, target: int, outcome: str,
            *, detail: str | None = None, backup_id: str | None = None,
            started_at: str | None = None) -> None:
    now = now_iso()
    conn.execute(
        "INSERT INTO schema_migrations (store, from_version, to_version, started_at, "
        "finished_at, outcome, detail, backup_id, software_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (store, source, target, started_at or now,
         None if outcome == OUTCOME_STARTED else now,
         outcome, detail, backup_id, code_version()),
    )


def _pre_upgrade_backup() -> tuple[str | None, str | None]:
    """§23's "create backup snapshot", or an honest account of why not.

    Returns (backup_id, problem). A backup that could not be taken is reported
    and the caller decides - refusing to migrate without one is the right
    default, but a developer with `--no-backup` has said they accept that."""
    try:
        from backend import continuity

        destinations = continuity.backup_destinations()
        if not destinations:
            return None, "no backup destination is configured"
        label, provider = destinations[0]
        manifest = continuity.create_backup(provider)
        return manifest["backup_id"], None
    except Exception as exc:  # noqa: BLE001 - the reason travels to the operator
        return None, f"{type(exc).__name__}: {exc}"


def migrate(conn: Database, *, store_name: str | None = None, dry_run: bool = False,
            force: bool = False, backup: bool = True) -> list[dict]:
    """Run the pipeline in §23's order, for one store or all of them.

    validate source -> back up -> record -> migrate -> validate -> activate.

    `force` re-runs the steps even when the versions say there is nothing to do
    (§14's sixth hatch), which is how a developer re-applies a step they have
    just edited. It cannot force a *missing* step or state from the future -
    those refuse regardless, because forcing them would corrupt rather than
    inconvenience."""
    targets = [get(store_name)] if store_name else stores()
    results = []

    for store in targets:
        if not table_exists(conn, store.table):
            results.append({"store": store.name, "action": "skipped",
                            "reason": f"table {store.table!r} does not exist in this database "
                                      "yet; fi_db.init_schema creates it on next start"})
            continue
        stored = store.read_version(conn)
        if stored is None:
            results.append({"store": store.name, "action": "skipped",
                            "reason": "no state exists for this store yet"})
            continue

        try:
            steps = plan(store, stored)
        except (MissingMigration, StateFromTheFuture) as exc:
            # Neither is forceable. Recorded rather than raised so a run across
            # several stores reports on all of them.
            _record(conn, store.name, stored, store.code_version, OUTCOME_FAILED,
                    detail=str(exc))
            results.append({"store": store.name, "action": "refused", "reason": str(exc)})
            continue

        if not steps and not force:
            results.append({"store": store.name, "action": "up_to_date",
                            "version": stored, "note": store.note})
            continue
        if not steps and force:
            # Nothing to replay: forcing an empty ladder is a no-op, and saying
            # so beats reporting a success that did nothing.
            results.append({"store": store.name, "action": "up_to_date",
                            "version": stored, "forced": True,
                            "note": "force had nothing to re-run; no steps are registered"})
            continue

        # 1. Validate the source (§23). A migration is a poor moment to
        #    discover the input was already broken.
        problems = store.validate(conn)
        if problems and not force:
            _record(conn, store.name, stored, store.code_version, OUTCOME_VALIDATION_FAILED,
                    detail=f"source state did not validate: {problems}")
            results.append({"store": store.name, "action": "refused",
                            "reason": f"source state did not validate: {problems}"})
            continue

        if dry_run:
            results.append({"store": store.name, "action": "would_migrate", "steps": steps,
                            "source_problems": problems})
            continue

        # 2. Back up before touching anything (§23).
        backup_id, backup_problem = (None, None) if not backup else _pre_upgrade_backup()
        if backup and backup_id is None:
            _record(conn, store.name, stored, store.code_version, OUTCOME_FAILED,
                    detail=f"refused: no pre-migration backup ({backup_problem})")
            results.append({
                "store": store.name, "action": "refused",
                "reason": f"could not take a pre-migration backup ({backup_problem}); "
                          "pass backup=False only if you accept migrating without one",
            })
            continue

        # 3. Record source and target before running (§23), so an interrupted
        #    run leaves evidence of what it was attempting.
        started_at = now_iso()
        _record(conn, store.name, stored, store.code_version, OUTCOME_STARTED,
                backup_id=backup_id, started_at=started_at)

        # 4-6. Migrate, validate, and only then activate - all inside one
        #      transaction, so a failure at step three leaves nothing applied.
        try:
            with conn.transaction():
                for source_version, _target in steps:
                    store.migrations[source_version](conn)
                after = store.validate(conn)
                if after:
                    raise ValidationFailed(
                        f"migrated state did not validate: {after}")
                store.write_version(conn, store.code_version)
        except Exception as exc:  # noqa: BLE001 - every failure is reported, none is swallowed
            # §22: nothing destroyed, the failure logged, the backup named.
            _record(conn, store.name, stored, store.code_version,
                    OUTCOME_VALIDATION_FAILED if isinstance(exc, ValidationFailed)
                    else OUTCOME_FAILED,
                    detail=f"{type(exc).__name__}: {exc}", backup_id=backup_id,
                    started_at=started_at)
            _alert(conn, store.name, stored, exc, backup_id)
            results.append({"store": store.name, "action": "failed", "reason": str(exc),
                            "backup_id": backup_id,
                            "state": "rolled back; nothing was applied and the version is "
                                     f"still {stored}"})
            continue

        _record(conn, store.name, stored, store.code_version, OUTCOME_MIGRATED,
                detail=f"{len(steps)} step(s)", backup_id=backup_id, started_at=started_at)
        results.append({"store": store.name, "action": "migrated", "from": stored,
                        "to": store.code_version, "steps": steps, "backup_id": backup_id})

    return results


def _alert(conn: Database, store: str, stored: int, exc: Exception, backup_id: str | None) -> None:
    """§22's "alert the operator when appropriate". A failed migration is
    always appropriate: it is the one failure where doing nothing and doing
    something are both potentially destructive."""
    try:
        status_events.publish(
            conn, "migration_failed",
            f"Migration of {store!r} from schema {stored} failed and was rolled back: "
            f"{type(exc).__name__}: {exc}."
            + (f" The pre-migration backup is {backup_id}." if backup_id
               else " No pre-migration backup was taken."),
            severity=status_events.SEVERITY_ERROR,
            status=status_events.STATUS_FAILED, department="server",
        )
    except Exception:  # noqa: BLE001 - never let the alarm mask the failure it reports
        pass


def history(conn: Database, *, store_name: str | None = None, limit: int = 50) -> list[dict]:
    """What has been attempted, newest last. Failures included - see SCHEMA."""
    sql = "SELECT * FROM schema_migrations"
    params: tuple = ()
    if store_name:
        sql += " WHERE store = ?"
        params = (store_name,)
    sql += " ORDER BY id DESC LIMIT ?"
    rows = conn.fetchall(sql, params + (max(1, min(limit, 500)),))
    return list(reversed(rows))


# --- the destructive hatches (§14) -------------------------------------------------


def _require_development_stage() -> str:
    """Refuse a destructive hatch outside a development stage.

    Fails closed on an unreadable boot config: "I could not tell what stage this
    is" must not resolve to "go ahead and wipe it"."""
    from backend import boot_config

    try:
        stage = boot_config.load().lifecycle_stage
    except Exception as exc:  # noqa: BLE001
        raise HatchRefused(
            f"refusing a destructive operation: the boot configuration could not be read "
            f"({exc}), so the lifecycle stage is unknown."
        ) from exc
    if stage not in DESTRUCTIVE_STAGES:
        raise HatchRefused(
            f"refusing a destructive operation at lifecycle stage {stage}. "
            f"§14's hatches are development conveniences; allowed stages are "
            f"{', '.join(DESTRUCTIVE_STAGES)}."
        )
    return stage


def reset(conn: Database, *, store_name: str | None = None, backup: bool = True) -> dict:
    """§14's first two hatches: reset state, start clean.

    Takes a backup first unless told not to, and is gated on the lifecycle
    stage. An escape hatch that destroys the only copy is the thing §22 forbids
    wearing a helpful name."""
    stage = _require_development_stage()
    backup_id, backup_problem = (None, None) if not backup else _pre_upgrade_backup()
    if backup and backup_id is None:
        raise HatchRefused(
            f"refusing to reset without a backup ({backup_problem}); pass backup=False to "
            "accept that deliberately"
        )

    targets = [get(store_name)] if store_name else stores()
    cleared = []
    for store in targets:
        # Rows, not tables: dropping the table would take the schema with it and
        # the next init_schema would recreate it silently, which hides what
        # happened. Emptied state is visible as emptied.
        if not table_exists(conn, store.table):
            continue
        conn.execute(f"DELETE FROM {store.table}")
        cleared.append(store.name)

    status_events.publish(
        conn, "state_reset",
        f"Development reset cleared {', '.join(cleared) or 'nothing'} at stage {stage}."
        + (f" Backup {backup_id} was taken first." if backup_id else " No backup was taken."),
        severity=status_events.SEVERITY_WARNING, status=status_events.STATUS_COMPLETED,
        department="server",
    )
    return {"cleared": cleared, "backup_id": backup_id, "stage": stage}


def inspect(conn: Database, *, store_name: str | None = None) -> dict:
    """§14's sixth hatch: raw persisted state, exactly as stored.

    Raw on purpose - JSON columns come back as their stored text rather than
    parsed. A developer reading this is usually trying to find out why parsing
    failed, and a view that parses for them hides the thing they came to see."""
    targets = [get(store_name)] if store_name else stores()
    return {store.name: store.inspect(conn) for store in targets}


def main(argv: list[str] | None = None) -> int:
    # The CLI loads .env; importing this module does not - the same lesson
    # backend/continuity.py records at length after a real defect (§69).
    from dotenv import load_dotenv

    load_dotenv()

    from backend import fi_db

    parser = argparse.ArgumentParser(
        prog="python -m backend.migrations",
        description="Schema migrations and the development escape hatches (addendum 42 "
                    "§7-§10, §14, §22, §23).",
    )
    parser.add_argument("--db", default=None, help="database path (default: FI_DB_PATH)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="compare stored and code schema versions for every store")
    p_inspect = sub.add_parser("inspect", help="print raw persisted state")
    p_inspect.add_argument("store", nargs="?", default=None)
    p_hist = sub.add_parser("history", help="every migration attempt, successes and failures")
    p_hist.add_argument("store", nargs="?", default=None)

    p_migrate = sub.add_parser("migrate", help="run the pipeline in addendum 42 §23's order")
    p_migrate.add_argument("store", nargs="?", default=None)
    p_migrate.add_argument("--dry-run", action="store_true",
                           help="report what would run, change nothing")
    p_migrate.add_argument("--force", action="store_true",
                           help="re-run steps even when the versions say there is nothing to do")
    p_migrate.add_argument("--no-backup", action="store_true",
                           help="migrate without a pre-migration snapshot (§23 asks for one)")

    sub.add_parser("snapshots", help="backup sets that can be restored or rolled back to")
    p_restore = sub.add_parser("restore", help="load a specific snapshot over live state")
    p_restore.add_argument("backup_id")
    p_restore.add_argument("dest_root", nargs="?", default=".")
    p_restore.add_argument("--overwrite", action="store_true",
                           help="replace existing files; restoring onto live state needs this")

    p_reset = sub.add_parser("reset", help="clear persisted state and start clean")
    p_reset.add_argument("store", nargs="?", default=None)
    p_reset.add_argument("--yes", action="store_true", required=False,
                         help="required: confirm that state should be destroyed")
    p_reset.add_argument("--no-backup", action="store_true")

    args = parser.parse_args(argv)
    conn = fi_db.get_connection(args.db) if args.db else fi_db.get_connection()
    try:
        return _run_command(conn, args)
    finally:
        conn.close()


def _run_command(conn: Database, args) -> int:
    from backend import continuity

    if args.command == "status":
        if persistence_disabled():
            print(f"! {PERSISTENCE_DISABLED_ENV} is set: persistence is disabled this session.\n")
        for entry in status(conn):
            if not entry["readable"]:
                print(f"{entry['store']}: UNREADABLE - {entry['problem']}")
                continue
            if not entry["present"]:
                if not entry.get("created"):
                    print(f"{entry['store']}: not created in this database yet "
                          f"(code is at {entry['code_version']})")
                    print(f"  {entry['problem']}")
                else:
                    print(f"{entry['store']}: no state stored yet (code is at "
                          f"{entry['code_version']})")
                continue
            state = "needs migration" if entry["needs_migration"] else "up to date"
            print(f"{entry['store']}: stored {entry['stored_version']}, "
                  f"code {entry['code_version']} - {state}")
            if entry.get("problem"):
                print(f"  ! {entry['problem']}")
            for problem in entry["problems"]:
                print(f"  ! {problem}")
            if entry["note"]:
                print(f"  {entry['note']}")
        return 0

    if args.command == "inspect":
        for name, rows in inspect(conn, store_name=args.store).items():
            print(f"--- {name} ({len(rows)} row(s)) ---")
            for row in rows:
                print(json.dumps(row, indent=1, default=str))
        return 0

    if args.command == "history":
        entries = history(conn, store_name=args.store)
        if not entries:
            print("no migration has been attempted")
            return 0
        for entry in entries:
            print(f"{entry['started_at']} {entry['store']}: {entry['from_version']} -> "
                  f"{entry['to_version']} {entry['outcome']}"
                  + (f" ({entry['detail']})" if entry["detail"] else "")
                  + (f" [backup {entry['backup_id']}]" if entry["backup_id"] else ""))
        return 0

    if args.command == "migrate":
        results = migrate(conn, store_name=args.store, dry_run=args.dry_run,
                          force=args.force, backup=not args.no_backup)
        failed = False
        for result in results:
            print(f"{result['store']}: {result['action']}"
                  + (f" - {result.get('reason') or result.get('note') or ''}").rstrip(" -"))
            if result.get("steps"):
                print(f"  steps: {result['steps']}")
            if result["action"] in {"failed", "refused"}:
                failed = True
            if result.get("state"):
                print(f"  {result['state']}")
        return 1 if failed else 0

    if args.command == "snapshots":
        destinations = continuity.backup_destinations()
        if not destinations:
            print("no backup destination is configured")
            return 1
        for label, provider in destinations:
            sets = continuity.list_backups(provider)
            print(f"--- {label}: {len(sets)} set(s) ---")
            for entry in sets:
                print(f"  {entry['backup_id']}  {entry.get('created_at', '')}")
        return 0

    if args.command == "restore":
        destinations = continuity.backup_destinations()
        if not destinations:
            print("no backup destination is configured")
            return 1
        _label, provider = destinations[0]
        written = continuity.restore_backup(provider, args.backup_id, args.dest_root,
                                            overwrite=args.overwrite)
        for path in written:
            print(f"restored {path}")
        return 0

    if args.command == "reset":
        if not args.yes:
            print("reset destroys persisted state, including the COO's identity. "
                  "Re-run with --yes if that is what you want.")
            return 1
        try:
            outcome = reset(conn, store_name=args.store, backup=not args.no_backup)
        except HatchRefused as exc:
            print(f"refused: {exc}")
            return 1
        print(f"cleared: {', '.join(outcome['cleared']) or 'nothing'}")
        if outcome["backup_id"]:
            print(f"backup taken first: {outcome['backup_id']}")
        return 0

    raise AssertionError(f"unhandled command {args.command!r}")   # pragma: no cover


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
