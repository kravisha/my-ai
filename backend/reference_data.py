"""The Reference Data Engine (addendum 24, with addendum 26 subordinate -
docs/SPEC_RECONCILIATION.md §39): the canonical description of every asset
this organization knows about, built and certified before any operational
agent begins work.

**An engine, not an agent** (addendum 24 §1: "an engine, not an autonomous
organizational authority"). It is pure functions over the database, called
from backend/main.py's startup orchestration the same way §35's Risk Engine
runs inside the COO cycle rather than as a spawned role - no charter, no
watcher, no organization.yaml entry. See docs/organization.yaml's own
comment: that file records agent roles checked against fi_db.ROLE_CHARTERS
and agents/coo.py's BASELINE_ROLES, neither of which this module touches.

## Three registries, one table

Asset Universe, Capability Set and Current Focus (addendum 24 §4) are not
three tables - they are three flags on one row per asset class
(`asset_classes.in_universe/in_capability/in_focus`), because they are
questions about the same eleven classes, not different populations. The
Pre-Alpha parity mission's scope (docs/SPEC_RECONCILIATION.md §39, addendum
25 §1) is `stock` and `stock_option`; every other class is seeded present in
the Universe and absent from Capability and Focus, so widening the mission
later is a flag flip, not a schema change.

## Why this sits below fi_db

fi_db.init_schema creates this module's tables (the same reason risk.py and
strategy.py give, now a fourth instance), so this module must not import
fi_db - that would close an import cycle. Table names like `security_universe`
that fi_db owns are queried here with plain SQL (see SeedUniverseAdapter),
not imported.

## The one adapter Day Zero ships

addendum 24 §11 lists free/public sources (EDGAR, OpenFIGI, exchange
directories); none ship here. The synthetic seed universe is the Pre-Alpha
Current Focus, and a network fetch cannot improve coverage of a universe that
does not exist outside this database - an ingest nothing consumes is the
empty machinery this project refuses (docs/SPEC_RECONCILIATION.md §39). The
adapter interface is real and the seed universe flows through it as the
first (and, for now, only) adapter; EDGAR/OpenFIGI arrive with the Alpha
focus universe, behind this same interface.

## The market as a source (TQ-15, SPEC_RECONCILIATION §62)

Validation grew its first cross-check against something other than this
database's own consistency: for every focus asset with a stored option-chain
observation, the ARB-015/016 diagnostics (backend/arbitrage.py's
diagnose_chain) test the declared carry inputs - pv_div per expiry, r -
against the executable band the market's own quotes imply. A declaration
outside the band is recorded in reference_conflicts as a disagreement
between the declaring source and 'market_implied' (a registered source,
ranked below every declaring one). It is data, never a readiness blocker,
and never a validity verdict: "difference alone is not arbitrage" cuts both
ways - it is not proof the declaration is wrong either. The check activates
on data presence (no stored chains, nothing to cross-check), the same
discipline providers/stored_data.py states for its own adapter.

## Fail-closed, always

`certify_readiness` never claims READY on a check that failed (addendum 24
§21, addendum 26 §17), and every run - including reruns against unchanged
data - re-certifies rather than trusting a prior result. Conflicts are
recorded, never hidden or silently resolved (addendum 24 §13: "a
disagreement is data, not something to hide") - `unresolved_conflicts`
always reports ok=True precisely because a conflict is not, by itself, a
readiness failure.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, Protocol

from backend import identifiers
from backend.db import Database, now_iso

SCHEMA_VERSION = 1

# A convention, unmeasured, mirroring risk.py's own disclosure discipline.
# Four is the size of the "synthetic_alpha" peer group
# (agents/discovery_config.py PEER_GROUPS) that discovery actually scans -
# not a measured minimum viable coverage, just the smallest population this
# organization has ever called a peer group. Overridable because a different
# mission will have a different honest answer.
MIN_FOCUS_ASSETS = int(os.environ.get("FI_MIN_FOCUS_ASSETS", "4"))

# --- Asset-class registry: granularity at which capability differs (addendum
# 24 §5). display_name is the only thing a human reads; the code is the join
# key everywhere else.
ASSET_CLASSES = [
    ("stock", "Stocks"),
    ("stock_option", "Stock Options"),
    ("etf", "ETFs"),
    ("etf_option", "ETF Options"),
    ("future", "Futures"),
    ("future_option", "Futures Options"),
    ("commodity", "Commodities"),
    ("commodity_option", "Commodity Options"),
    ("fx", "Currencies / FX"),
    ("fixed_income", "Fixed Income"),
    ("digital_asset", "Digital Assets"),
]

# The Pre-Alpha parity mission's scope (addendum 25 §1): the only classes the
# software can currently process, and the only ones currently selected for
# work. Every other class is Universe-only until something builds the
# capability and a mission selects it.
CAPABILITY_FOCUS_CLASSES = {"stock", "stock_option"}

# Identifier requirements per class (addendum 24 §7). Schemes must come from
# identifiers.SCHEMES - validated in _seed_identifier_rules rather than left
# to whoever edits this list next.
IDENTIFIER_RULE_SEED = [
    ("stock", "symbol", "required", None),
    ("stock", "isin", "optional", None),
    ("stock", "cusip", "optional", None),
    ("stock", "figi", "optional", None),
    ("stock_option", "symbol", "required", None),
]

IDENTIFIER_REQUIREMENTS = ("required", "optional")

# The source registry's opening entries (addendum 24 §13). security_universe
# is the seed adapter's authority; fred is named for when providers/
# historical.py's ingest is wired through this engine rather than only
# through observations.py directly - not wired yet, named so the authority
# comparison in `ingest` has a real number to read the day it is.
REFERENCE_SOURCE_SEED = [
    ("security_universe", "seed", 100, "the seeded synthetic universe"),
    ("fred", "public_api", 80, "FRED public series - see providers/historical.py"),
    # The market itself, as a source (TQ-15, SPEC_RECONCILIATION §62): what
    # executable option quotes imply about dividends and financing, via
    # backend/arbitrage.py's ARB-015/016 diagnostics. Ranked below every
    # declaring source on purpose - a diagnostic can mean the declaration is
    # wrong OR the market is mispriced, and the spec's own words ("difference
    # alone is not arbitrage") cut both ways: difference alone is not proof
    # the declaration is wrong either. It never overwrites; it only disagrees.
    ("market_implied", "derived", 10, "executable-band cross-check via ARB-015/016 (diagnose_chain)"),
]

# The reference_conflicts.offering_source value the market-implied cross-check
# records under, and the field each diagnostic contests.
MARKET_IMPLIED_SOURCE = "market_implied"
_MARKET_FIELD_BY_DETECTOR = {"ARB-015": "pv_div", "ARB-016": "r"}

# Fields ingest() will fill when NULL and flag as a conflict when an offered
# value disagrees with an already-held one. Deliberately excludes
# underlying_entity_id and attributes: addendum 24 §8 lists them as part of
# the master record but the conflict/fill contract this module implements is
# scoped to the five scalar descriptive fields the spec calls out by name.
_CONFLICT_FIELDS = ("name", "exchange", "currency", "country", "asset_class")

SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_classes (
    asset_class TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    in_universe INTEGER NOT NULL DEFAULT 1,
    in_capability INTEGER NOT NULL DEFAULT 0,
    in_focus INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS identifier_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_class TEXT NOT NULL,
    scheme TEXT NOT NULL,
    requirement TEXT NOT NULL,
    note TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(asset_class, scheme)
);

-- One row per entity (addendum 24 §8): the canonical instrument record over
-- the entity layer identifiers.py owns. entity_id is not AUTOINCREMENT
-- because it is not this table's identity to mint - identifiers.py already
-- minted it, and a security_master row without an entities row would be
-- reference data about nothing.
CREATE TABLE IF NOT EXISTS security_master (
    entity_id TEXT PRIMARY KEY REFERENCES entities(entity_id),
    asset_class TEXT NOT NULL,
    name TEXT,
    exchange TEXT,
    currency TEXT,
    country TEXT,
    underlying_entity_id TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    attributes TEXT,
    source TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'unvalidated',
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS security_master_by_asset_class ON security_master (asset_class, active);

CREATE TABLE IF NOT EXISTS reference_sources (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    authority_rank INTEGER NOT NULL,
    note TEXT,
    added_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- Append-only by design (addendum 24 §13: "a disagreement is data, not
-- something to hide"). Nothing in this module ever deletes or updates a row
-- here - a resolved conflict is still a fact about a moment this source and
-- that source disagreed.
CREATE TABLE IF NOT EXISTS reference_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    field TEXT NOT NULL,
    held_value TEXT,
    held_source TEXT,
    offered_value TEXT,
    offering_source TEXT,
    detected_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS reference_conflicts_by_entity ON reference_conflicts (entity_id, detected_at);

-- Append-only certification record (addendum 24 §17/§18). Every
-- run_reference_engine call adds a row rather than updating the last one, so
-- the readiness history - not just the current answer - survives restart.
CREATE TABLE IF NOT EXISTS reference_readiness (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    certified_at TEXT NOT NULL,
    status TEXT NOT NULL,
    checks TEXT NOT NULL,
    focus_asset_count INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- Addendum 24 §9's Assets table, as a view rather than a maintained copy -
-- the same house precedent as fi_db's performance_card - so it cannot drift
-- from security_master by anyone forgetting to update a second place.
CREATE VIEW IF NOT EXISTS assets AS
SELECT
    sm.entity_id AS entity_id,
    sm.asset_class AS asset_class,
    (SELECT ei.value FROM entity_identifiers ei
     WHERE ei.entity_id = sm.entity_id AND ei.scheme = 'symbol' AND ei.valid_to IS NULL
     ORDER BY ei.valid_from, ei.id LIMIT 1) AS primary_identifier,
    sm.active AS active,
    ac.in_focus AS in_focus
FROM security_master sm
JOIN asset_classes ac ON ac.asset_class = sm.asset_class;
"""

_VIEW_PATTERN = re.compile(
    r"CREATE VIEW IF NOT EXISTS\s+(\w+)\s+AS.*?;", re.DOTALL | re.IGNORECASE
)


def _normalise(sql: str) -> str:
    """Mirrors fi_db._normalise exactly (collapse whitespace, lowercase,
    strip IF NOT EXISTS), so a purely cosmetic edit to the view's SQL never
    reads as drift."""
    return " ".join(sql.replace("IF NOT EXISTS", "").split()).lower()


def _reconcile_view(conn: Database) -> None:
    """CREATE VIEW IF NOT EXISTS has the same trap fi_db._reconcile_triggers
    documents for CREATE TRIGGER IF NOT EXISTS: on a database where `assets`
    already exists under an older definition, the statement above silently
    does nothing and the stale view keeps answering forever - no PRAGMA, no
    failing query, nothing that reveals it. A view holds no data, so
    replacing it loses nothing, which is what lets this be automatic the way
    _reconcile_triggers is."""
    match = _VIEW_PATTERN.search(SCHEMA)
    if match is None:
        return
    name = match.group(1)
    declared = match.group(0).rstrip(";")
    row = conn.fetchone(
        "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = ?", (name,)
    )
    if row is None or _normalise(row["sql"]) == _normalise(declared):
        return
    conn.execute(f"DROP VIEW {name}")
    conn.execute(declared)


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)
    _reconcile_view(conn)
    _seed_asset_classes(conn)
    _seed_identifier_rules(conn)
    _seed_reference_sources(conn)


def _seed_asset_classes(conn: Database) -> None:
    for asset_class, display_name in ASSET_CLASSES:
        in_capability = 1 if asset_class in CAPABILITY_FOCUS_CLASSES else 0
        conn.execute(
            "INSERT OR IGNORE INTO asset_classes "
            "(asset_class, display_name, in_universe, in_capability, in_focus, updated_at, schema_version) "
            "VALUES (?, ?, 1, ?, ?, ?, ?)",
            (asset_class, display_name, in_capability, in_capability, now_iso(), SCHEMA_VERSION),
        )


def _seed_identifier_rules(conn: Database) -> None:
    for asset_class, scheme, requirement, note in IDENTIFIER_RULE_SEED:
        if scheme not in identifiers.SCHEMES:
            raise ValueError(f"identifier rule seed names unknown scheme {scheme!r}")
        if requirement not in IDENTIFIER_REQUIREMENTS:
            raise ValueError(f"identifier rule seed names unknown requirement {requirement!r}")
        conn.execute(
            "INSERT OR IGNORE INTO identifier_rules (asset_class, scheme, requirement, note, schema_version) "
            "VALUES (?, ?, ?, ?, ?)",
            (asset_class, scheme, requirement, note, SCHEMA_VERSION),
        )


def _seed_reference_sources(conn: Database) -> None:
    for name, kind, authority_rank, note in REFERENCE_SOURCE_SEED:
        conn.execute(
            "INSERT OR IGNORE INTO reference_sources (name, kind, authority_rank, note, added_at, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, kind, authority_rank, note, now_iso(), SCHEMA_VERSION),
        )


def _require_known_class(conn: Database, asset_class: str) -> None:
    if conn.fetchone("SELECT 1 FROM asset_classes WHERE asset_class = ?", (asset_class,)) is None:
        raise ValueError(f"unknown asset class {asset_class!r}")


def set_capability(conn: Database, asset_class: str, flag: bool) -> None:
    _require_known_class(conn, asset_class)
    conn.execute(
        "UPDATE asset_classes SET in_capability = ?, updated_at = ? WHERE asset_class = ?",
        (int(bool(flag)), now_iso(), asset_class),
    )


def set_focus(conn: Database, asset_class: str, flag: bool) -> None:
    _require_known_class(conn, asset_class)
    conn.execute(
        "UPDATE asset_classes SET in_focus = ?, updated_at = ? WHERE asset_class = ?",
        (int(bool(flag)), now_iso(), asset_class),
    )


# --- Ingestion pipeline (addendum 24 §11/§12) -------------------------------


@dataclass
class SourceRecord:
    """One instrument as one adapter sees it. `underlying`, when given, is a
    (scheme, value) pair - the underlying is itself identified the same way
    any other instrument is, not by a canonical id the adapter cannot know
    yet."""

    scheme: str
    value: str
    asset_class: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    country: str | None = None
    underlying: tuple[str, str] | None = None
    attributes: dict | None = None


class SourceAdapter(Protocol):
    name: str

    def records(self, conn: Database) -> Iterable[SourceRecord]: ...


class SeedUniverseAdapter:
    """The only adapter Day Zero ships - see the module docstring for why a
    network source is declined rather than merely deferred. Every active
    security_universe symbol becomes a `stock` SourceRecord; the table's own
    active flag is what "seen" means for this source."""

    name = "security_universe"

    def records(self, conn: Database) -> Iterable[SourceRecord]:
        for row in conn.fetchall("SELECT symbol FROM security_universe WHERE active = 1"):
            yield SourceRecord(scheme="symbol", value=row["symbol"], asset_class="stock")


def _authority(conn: Database, source_name: str) -> int:
    """0 for a source with no reference_sources row - an unregistered source
    can create instruments but can never outrank one, since there is nothing
    on record to compare it against."""
    row = conn.fetchone("SELECT authority_rank FROM reference_sources WHERE name = ?", (source_name,))
    return row["authority_rank"] if row else 0


def ingest(conn: Database, adapter: SourceAdapter) -> dict:
    """Acquire -> Normalize -> Validate -> Resolve Identity -> Reconcile ->
    Merge -> Record Provenance (addendum 24 §12), one adapter at a time.

    Idempotent by construction: re-running the same adapter against
    unchanged source data offers the same values it already holds for every
    field, so no UPDATE ever fires and no conflict is ever recorded - "same
    value" is not a disagreement."""
    report: dict = {"source": adapter.name, "seen": 0, "created": 0, "updated": 0, "conflicts": 0, "rejected": []}
    source_authority = _authority(conn, adapter.name)

    for record in adapter.records(conn):
        report["seen"] += 1
        class_row = conn.fetchone(
            "SELECT in_capability FROM asset_classes WHERE asset_class = ?", (record.asset_class,)
        )
        if class_row is None:
            report["rejected"].append(f"{record.scheme}={record.value}: unknown asset class {record.asset_class!r}")
            continue
        if not class_row["in_capability"]:
            report["rejected"].append(
                f"{record.scheme}={record.value}: asset class {record.asset_class!r} is not in the Capability Set"
            )
            continue

        entity_id = identifiers.ensure_entity(
            conn, record.scheme, record.value, entity_type="security", source=adapter.name
        )
        existing = conn.fetchone("SELECT * FROM security_master WHERE entity_id = ?", (entity_id,))
        attributes_json = json.dumps(record.attributes) if record.attributes else None

        if existing is None:
            underlying_entity_id = None
            if record.underlying is not None:
                underlying_entity_id = identifiers.resolve(conn, *record.underlying)
            now = now_iso()
            conn.execute(
                "INSERT INTO security_master "
                "(entity_id, asset_class, name, exchange, currency, country, underlying_entity_id, "
                "active, attributes, source, validation_status, first_seen_at, updated_at, schema_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'unvalidated', ?, ?, ?)",
                (
                    entity_id, record.asset_class, record.name, record.exchange, record.currency,
                    record.country, underlying_entity_id, attributes_json, adapter.name, now, now,
                    SCHEMA_VERSION,
                ),
            )
            report["created"] += 1
            continue

        held_source = existing["source"]
        held_authority = _authority(conn, held_source)
        may_overwrite = source_authority > held_authority

        updates: dict[str, object] = {}
        offered_by_field = dict(zip(_CONFLICT_FIELDS, (
            record.name, record.exchange, record.currency, record.country, record.asset_class,
        )))
        for field_name, offered in offered_by_field.items():
            if offered is None:
                continue
            held = existing[field_name]
            if held is None:
                updates[field_name] = offered
                continue
            if held == offered:
                continue
            # A held, non-null value disagrees with what this source offers.
            # Recorded regardless of whether the higher-authority source is
            # about to overwrite it - the prior value is precisely what an
            # audit trail needs when it did (addendum 24 §14). Recorded once
            # per distinct disagreement, not once per run: the pipeline runs
            # on every startup, and re-inserting the identical open
            # disagreement each time would grow this table without adding a
            # fact - the row already says these two sources disagree.
            already = conn.fetchone(
                "SELECT 1 FROM reference_conflicts WHERE entity_id = ? AND field = ? "
                "AND held_value = ? AND offered_value = ? AND offering_source = ?",
                (entity_id, field_name, str(held), str(offered), adapter.name),
            )
            if already is None:
                conn.execute(
                    "INSERT INTO reference_conflicts "
                    "(entity_id, field, held_value, held_source, offered_value, offering_source, detected_at, schema_version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (entity_id, field_name, str(held), held_source, str(offered), adapter.name, now_iso(), SCHEMA_VERSION),
                )
                report["conflicts"] += 1
            if may_overwrite:
                updates[field_name] = offered

        if existing["attributes"] is None and attributes_json is not None:
            updates["attributes"] = attributes_json

        if updates:
            set_clause = ", ".join(f"{name} = ?" for name in updates)
            conn.execute(
                f"UPDATE security_master SET {set_clause}, updated_at = ? WHERE entity_id = ?",
                (*updates.values(), now_iso(), entity_id),
            )
            report["updated"] += 1

    return report


# --- Validation and readiness (addendum 24 §16/§17) -------------------------


def _required_identifier_gaps(conn: Database) -> dict[str, list[str]]:
    """entity_id -> missing required schemes, for every ACTIVE security_master
    row whose class is in_focus. Shared between `validate`'s
    required_identifiers check and `certify_readiness`'s validation_status
    stamping so the two can never name a different set of failing rows."""
    gaps: dict[str, list[str]] = {}
    focus_rows = conn.fetchall(
        "SELECT entity_id, asset_class FROM security_master WHERE active = 1 AND asset_class IN "
        "(SELECT asset_class FROM asset_classes WHERE in_focus = 1)"
    )
    for row in focus_rows:
        required = conn.fetchall(
            "SELECT scheme FROM identifier_rules WHERE asset_class = ? AND requirement = 'required'",
            (row["asset_class"],),
        )
        missing = [
            rule["scheme"] for rule in required
            if conn.fetchone(
                "SELECT 1 FROM entity_identifiers WHERE entity_id = ? AND scheme = ? AND valid_to IS NULL",
                (row["entity_id"], rule["scheme"]),
            ) is None
        ]
        if missing:
            gaps[row["entity_id"]] = missing
    return gaps


def _focus_asset_count(conn: Database) -> int:
    row = conn.fetchone(
        "SELECT COUNT(*) AS n FROM security_master WHERE active = 1 AND asset_class IN "
        "(SELECT asset_class FROM asset_classes WHERE in_focus = 1)"
    )
    return row["n"] if row else 0


def _market_implied_diagnostics(conn: Database) -> dict:
    """The market-implied cross-check (TQ-15, SPEC_RECONCILIATION §62; the
    consumer §55 named for the ARB-015/016 diagnostics): for every focus
    asset with a stored option-chain observation, run diagnose_chain over
    the chains the observation reconstructs to and report every declared
    carry input (pv_div per expiry, r) that lies outside the executable
    band the market's own quotes imply.

    Aggregated per (asset, field, expiry) rather than per strike: the
    *declaration* is per expiry, and twenty strikes flagging the same
    declared pv_div are one disagreement with twenty witnesses, not twenty
    disagreements - the max-gap strike represents it, with the witness
    count carried. Read-only, like everything validate() calls; recording
    is certify_readiness's job (_record_market_findings below).

    A missing observations table (a database fi_db has never initialized)
    and assets with no stored chain are both "nothing to cross-check yet",
    not failures - the check activates on data presence, the
    providers/stored_data.py discipline."""
    summary = {"assets_checked": 0, "assets_without_observations": 0, "findings": [], "errors": []}
    if conn.fetchone(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'observations'"
    ) is None:
        return summary

    # Lazy, the parity_world-imports-harness idiom: providers/stored_data is
    # the one translation from stored payload to ChainSnapshot (drift-free by
    # being shared with Explorer), and importing it at module scope would
    # invert the layering for every reference_data importer that never
    # cross-checks.
    from backend.arbitrage import diagnose_chain
    from providers.stored_data import StoredChainProvider, chain_snapshots

    provider = StoredChainProvider(conn)
    for asset in list_focus_assets(conn):
        entity_id, symbol = asset["entity_id"], asset["primary_identifier"]
        try:
            observation = provider.latest_chain(entity_id)
            if observation is None:
                summary["assets_without_observations"] += 1
                continue
            summary["assets_checked"] += 1
            grouped: dict[tuple[str, int], dict] = {}
            for chain in chain_snapshots(observation):
                for diagnostic in diagnose_chain(chain):
                    field_name = _MARKET_FIELD_BY_DETECTOR[diagnostic.detector_id]
                    expiry_days = diagnostic.inputs["expiry_days"]
                    key = (field_name, expiry_days)
                    held = grouped.get(key)
                    if held is None or diagnostic.gap > held["gap"]:
                        grouped[key] = {
                            "entity_id": entity_id, "symbol": symbol,
                            "field": field_name, "expiry_days": expiry_days,
                            "detector_id": diagnostic.detector_id,
                            "declared": diagnostic.declared,
                            "implied_low": diagnostic.implied_low,
                            "implied_high": diagnostic.implied_high,
                            "gap": diagnostic.gap, "strike": diagnostic.strike,
                            "n_strikes": (held["n_strikes"] + 1) if held else 1,
                            "held_source": observation.provenance.source,
                        }
                    else:
                        held["n_strikes"] += 1
            summary["findings"].extend(
                grouped[key] for key in sorted(grouped)
            )
        except Exception as exc:  # noqa: BLE001 - an undiagnosable asset is reported, not fatal
            # A cross-check that cannot run on one asset must neither crash
            # certification nor silently vanish - it is named in the check
            # detail so a broken feed is visible.
            summary["errors"].append(f"{entity_id}: {exc.__class__.__name__}: {exc}")
    return summary


def _record_market_findings(conn: Database, findings: list[dict]) -> int:
    """Each finding into reference_conflicts, the same append-only shape and
    the same once-per-distinct-disagreement dedup ingest() applies: the
    pipeline runs on every startup, and re-inserting the identical open
    disagreement each time would grow the table without adding a fact. A
    *changed* band (a new observation moved the market) is a new fact and
    gets a new row. Returns how many rows were actually added."""
    added = 0
    for finding in findings:
        held_value = str(finding["declared"])
        offered_value = json.dumps(
            {k: finding[k] for k in
             ("detector_id", "expiry_days", "implied_low", "implied_high", "gap", "strike", "n_strikes")},
            sort_keys=True,
        )
        already = conn.fetchone(
            "SELECT 1 FROM reference_conflicts WHERE entity_id = ? AND field = ? "
            "AND held_value = ? AND offered_value = ? AND offering_source = ?",
            (finding["entity_id"], finding["field"], held_value, offered_value, MARKET_IMPLIED_SOURCE),
        )
        if already is None:
            conn.execute(
                "INSERT INTO reference_conflicts "
                "(entity_id, field, held_value, held_source, offered_value, offering_source, detected_at, schema_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (finding["entity_id"], finding["field"], held_value, finding["held_source"],
                 offered_value, MARKET_IMPLIED_SOURCE, now_iso(), SCHEMA_VERSION),
            )
            added += 1
    return added


def market_implied_conflicts(conn: Database, entity_id: str | None = None) -> list[dict]:
    """The recorded market-implied disagreements, offered_value parsed - the
    read side for whatever consumes the cross-check next (an admin surface,
    a remediation pass). Newest first."""
    if entity_id is None:
        rows = conn.fetchall(
            "SELECT * FROM reference_conflicts WHERE offering_source = ? ORDER BY id DESC",
            (MARKET_IMPLIED_SOURCE,),
        )
    else:
        rows = conn.fetchall(
            "SELECT * FROM reference_conflicts WHERE offering_source = ? AND entity_id = ? ORDER BY id DESC",
            (MARKET_IMPLIED_SOURCE, entity_id),
        )
    parsed = []
    for row in rows:
        row = dict(row)
        row["offered_value"] = json.loads(row["offered_value"])
        parsed.append(row)
    return parsed


def validate(conn: Database) -> list[dict]:
    """Every automated check addendum 24 §16/26 §14 asks for that this
    schema can actually evaluate. Returns the list itself - certify_readiness
    is what decides READY/FAILED and writes the record; this function is
    honest without deciding anything."""
    checks = []

    bad = []
    for row in conn.fetchall("SELECT * FROM asset_classes"):
        if row["in_focus"] and not row["in_capability"]:
            bad.append(f"{row['asset_class']}: in_focus but not in_capability")
        if row["in_capability"] and not row["in_universe"]:
            bad.append(f"{row['asset_class']}: in_capability but not in_universe")
    checks.append({
        "check": "registry_invariants",
        "ok": not bad,
        "detail": "; ".join(bad) if bad else "in_focus subseteq in_capability subseteq in_universe for every class",
    })

    focus_classes = [r["asset_class"] for r in conn.fetchall("SELECT asset_class FROM asset_classes WHERE in_focus = 1")]
    checks.append({
        "check": "focus_nonempty",
        "ok": bool(focus_classes),
        "detail": f"{len(focus_classes)} class(es) in focus: {', '.join(focus_classes)}" if focus_classes
        else "no asset class is in focus",
    })

    bad = []
    for row in conn.fetchall("SELECT * FROM security_master"):
        if conn.fetchone("SELECT 1 FROM asset_classes WHERE asset_class = ?", (row["asset_class"],)) is None:
            bad.append(f"{row['entity_id']}: unknown asset class {row['asset_class']!r}")
        if conn.fetchone("SELECT 1 FROM entities WHERE entity_id = ?", (row["entity_id"],)) is None:
            bad.append(f"{row['entity_id']}: no matching entities row")
        if not (row["source"] or "").strip():
            bad.append(f"{row['entity_id']}: empty source")
    checks.append({
        "check": "master_integrity",
        "ok": not bad,
        "detail": "; ".join(bad) if bad else "every security_master row names a known class, entity, and source",
    })

    gaps = _required_identifier_gaps(conn)
    checks.append({
        "check": "required_identifiers",
        "ok": not gaps,
        "detail": "; ".join(f"{eid}: missing {', '.join(schemes)}" for eid, schemes in gaps.items()) if gaps
        else "every active focus-class instrument carries its required identifiers",
    })

    focus_count = _focus_asset_count(conn)
    checks.append({
        "check": "focus_coverage",
        "ok": focus_count >= MIN_FOCUS_ASSETS,
        "detail": f"{focus_count} active focus-class instrument(s), minimum {MIN_FOCUS_ASSETS} "
                  "(convention, not measurement)",
    })

    dupes = conn.fetchall(
        "SELECT scheme, value, COUNT(*) AS n FROM entity_identifiers WHERE valid_to IS NULL "
        "GROUP BY scheme, value HAVING COUNT(*) > 1"
    )
    checks.append({
        "check": "duplicate_live_identifiers",
        "ok": not dupes,
        "detail": "; ".join(f"{d['scheme']}={d['value']} has {d['n']} live holders" for d in dupes) if dupes
        else "no (scheme, value) has two live holders - the partial index should make this impossible",
    })

    market = _market_implied_diagnostics(conn)
    finding_bits = [
        f"{f['symbol']} {f['field']}@{f['expiry_days']}d declared {f['declared']:.4g} vs "
        f"[{f['implied_low']:.4g}, {f['implied_high']:.4g}] ({f['n_strikes']} strike(s))"
        for f in market["findings"]
    ]
    error_bits = [f"cross-check error {e}" for e in market["errors"]]
    checks.append({
        "check": "market_implied_consistency",
        # ok=True always, the unresolved_conflicts discipline: a diagnostic
        # means the declaration and the market disagree, and the spec's own
        # words cut both ways - it is not proof the declaration is wrong, so
        # it is recorded (certify_readiness), never a readiness blocker.
        # Errors in the cross-check itself are also data here: an asset that
        # cannot be diagnosed is named, and blocking the whole organization
        # on it would let one malformed observation take down startup.
        "ok": True,
        "detail": (
            f"{market['assets_checked']} asset(s) cross-checked against executable bands, "
            f"{market['assets_without_observations']} with no stored chain"
            + (f"; disagreements: {'; '.join(finding_bits)}" if finding_bits else "; no disagreements")
            + (f"; {'; '.join(error_bits)}" if error_bits else "")
        ),
    })

    conflict_count = conn.fetchone("SELECT COUNT(*) AS n FROM reference_conflicts")["n"]
    checks.append({
        "check": "unresolved_conflicts",
        "ok": True,
        "detail": f"{conflict_count} recorded conflict(s) - a disagreement is data, not a blocker",
    })

    return checks


def certify_readiness(conn: Database) -> dict:
    """Runs validate(), decides READY/FAILED, stamps validation_status on
    every focus-class master row, and appends the record - always, even on
    FAILED, since a failed certification is itself part of the audit trail
    addendum 24 §17 asks for (fail closed, not fail silent).

    The market-implied cross-check's findings are recorded FIRST (this is
    the writing half validate() deliberately does not do - validate stays
    read-only), so the unresolved_conflicts count validate() then reports
    already includes this certification's own discoveries. validation_status
    stamping is deliberately untouched by market findings: 'invalid' means
    the record is structurally broken (missing required identifiers), and a
    market disagreement is a conflict about a healthy record, not a broken
    one."""
    _record_market_findings(conn, _market_implied_diagnostics(conn)["findings"])
    checks = validate(conn)
    status = "READY" if all(c["ok"] for c in checks) else "FAILED"

    gaps = _required_identifier_gaps(conn)
    now = now_iso()
    for row in conn.fetchall(
        "SELECT entity_id FROM security_master WHERE asset_class IN "
        "(SELECT asset_class FROM asset_classes WHERE in_focus = 1)"
    ):
        new_status = "invalid" if row["entity_id"] in gaps else "valid"
        conn.execute(
            "UPDATE security_master SET validation_status = ?, updated_at = ? WHERE entity_id = ?",
            (new_status, now, row["entity_id"]),
        )

    focus_count = _focus_asset_count(conn)
    certified_at = now_iso()
    conn.execute(
        "INSERT INTO reference_readiness (certified_at, status, checks, focus_asset_count, schema_version) "
        "VALUES (?, ?, ?, ?, ?)",
        (certified_at, status, json.dumps(checks), focus_count, SCHEMA_VERSION),
    )
    return {"status": status, "checks": checks, "focus_asset_count": focus_count, "certified_at": certified_at}


def run_reference_engine(conn: Database, adapters: list[SourceAdapter] | None = None) -> dict:
    """The engine's entry point (addendum 24 §2's "Reference Data Engine"
    step) - called from backend/main.py's lifespan on every startup, before
    the COO wakes any operational agent (the Day Zero rule, addendum 26 §3).
    Idempotent: a second call against unchanged sources ingests nothing new
    and re-certifies against the same data."""
    if adapters is None:
        adapters = [SeedUniverseAdapter()]
    ingest_reports = [ingest(conn, adapter) for adapter in adapters]
    readiness = certify_readiness(conn)
    return {"ingest": ingest_reports, "readiness": readiness}


def latest_readiness(conn: Database) -> dict | None:
    row = conn.fetchone("SELECT * FROM reference_readiness ORDER BY id DESC LIMIT 1")
    if row is None:
        return None
    row = dict(row)
    row["checks"] = json.loads(row["checks"])
    return row


def is_ready(conn: Database) -> bool:
    """False on a fresh database - no certification has ever run, which is a
    different fact from "certification failed" but neither one is ready."""
    latest = latest_readiness(conn)
    return latest is not None and latest["status"] == "READY"


# --- Stable consumer interface (addendum 24 §20) ----------------------------


def get_asset(conn: Database, entity_id: str) -> dict | None:
    row = conn.fetchone("SELECT * FROM security_master WHERE entity_id = ?", (entity_id,))
    if row is None:
        return None
    asset = dict(row)
    asset["attributes"] = json.loads(asset["attributes"]) if asset["attributes"] else None
    asset["identifiers"] = identifiers.identifiers_for(conn, entity_id)
    return asset


def list_assets(conn: Database, asset_class: str | None = None, active_only: bool = True) -> list[dict]:
    conditions = []
    params: list = []
    if asset_class is not None:
        conditions.append("asset_class = ?")
        params.append(asset_class)
    if active_only:
        conditions.append("active = 1")
    sql = "SELECT * FROM assets"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY entity_id"
    return conn.fetchall(sql, tuple(params))


def list_focus_assets(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM assets WHERE in_focus = 1 AND active = 1 ORDER BY entity_id")


def get_validation_status(conn: Database, entity_id: str) -> str | None:
    row = conn.fetchone("SELECT validation_status FROM security_master WHERE entity_id = ?", (entity_id,))
    return row["validation_status"] if row else None


def status(conn: Database) -> dict:
    """The dashboard's shape (addendum 24 §19): enough to show progress
    without anyone reading terminal output."""
    total = conn.fetchone("SELECT COUNT(*) AS n FROM security_master")["n"]
    conflicts = conn.fetchone("SELECT COUNT(*) AS n FROM reference_conflicts")["n"]
    focus_classes = [
        r["asset_class"] for r in
        conn.fetchall("SELECT asset_class FROM asset_classes WHERE in_focus = 1 ORDER BY asset_class")
    ]
    return {
        "ready": is_ready(conn),
        "latest": latest_readiness(conn),
        "assets": total,
        "focus_assets": _focus_asset_count(conn),
        "conflicts": conflicts,
        "focus_classes": focus_classes,
    }
