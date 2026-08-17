"""A corpus of past observations, readable as of a moment.

**A historical dataset is not a run.** A run is a bounded episode with its own
database and its own provenance in a manifest; a corpus is a body of data
accumulated from many sources over years, where the same fact is recorded
repeatedly and revised. The two want opposite things from their storage, which is
why this is a separate store rather than another table in the organization's
database.

Three domains, because an analysis that silently mixes them is worthless and the
mixing is invisible after the fact:

    real          observed from the actual market, as it arrived
    historical    observed from the actual market, ingested afterwards as a corpus
    simulated     produced by a generator, about no real world at all

`real` and `historical` are both about the world and differ in how they arrived -
which matters, because an ingested corpus carries **vintages** and a live stream
does not. `simulated` is a different kind of claim entirely. So **every query
names its domains**; there is no default and no "all", because the failure this
guards against is a backtest that quietly proved something about generated data.

## Vintages, which are the reason this is not a table

Published statistics are revised. GDP for a quarter is published, revised a month
later, and revised again a month after that - three rows describing **the same
quarter**, knowable at three different times, with three different values.

A backtest running in May must see May's number. Using the final revised figure
is lookahead of the most seductive kind: every result improves, nothing errors,
and the mistake is invisible in the output. So the same `(data_class, subject,
effective_at)` may hold many rows, and `as_of` returns the latest one *knowable*
by the moment asked about - never the latest one recorded.

The two timestamps are the same pair the generators already stamp. What this adds
is that they survive, and that reading without a moment is not possible.

Internal rationale: INT-PHIL-0033
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from backend.db import Database

REAL = "real"
HISTORICAL = "historical"
SIMULATED = "simulated"
DOMAINS = (REAL, HISTORICAL, SIMULATED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    data_class TEXT NOT NULL,
    subject TEXT NOT NULL,
    -- What the datum describes.
    effective_at TEXT NOT NULL,
    -- When it could first have been known. The guard against lookahead, and the
    -- only timestamp any query is allowed to filter on.
    knowable_at TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    -- Which revision this is for that (subject, effective_at). 1 is the original
    -- publication; later integers are revisions.
    vintage INTEGER NOT NULL DEFAULT 1,
    ingested_at TEXT NOT NULL
);

-- The index the as-of query actually uses. Ordered to match its WHERE and
-- ORDER BY, since a corpus is read far more than it is written.
CREATE INDEX IF NOT EXISTS idx_observations_asof
    ON observations (domain, data_class, subject, knowable_at, effective_at);
"""


def open_store(path: str | Path) -> Database:
    """Open (creating if needed) a corpus at `path`.

    A file of its own, never the organization's operational database. Keeping
    them separate is what makes "combining domains must be explicit" structural
    rather than a rule every reader has to remember."""
    conn = Database(path)
    conn.executescript(SCHEMA)
    return conn


def _check_domain(domain: str) -> str:
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain {domain!r}; allowed: {list(DOMAINS)}")
    return domain


def record(
    conn: Database,
    domain: str,
    data_class: str,
    subject: str,
    effective_at: datetime,
    knowable_at: datetime,
    value: dict,
    source: str,
    vintage: int = 1,
) -> int:
    """Add one observation to the corpus.

    `knowable_at` is required and not derived. The orchestrator computes it from
    a cadence for generated data; a real corpus takes it from the publication
    record. Deriving it here would mean inventing a publication lag for data
    whose actual lag is known, which is the one place this store must not
    guess."""
    _check_domain(domain)
    if knowable_at < effective_at:
        raise ValueError(
            f"knowable_at {knowable_at.isoformat()} precedes effective_at "
            f"{effective_at.isoformat()}: a datum cannot be known before the moment it describes"
        )
    return conn.execute_returning_id(
        "INSERT INTO observations (domain, data_class, subject, effective_at, knowable_at, "
        "value, source, vintage, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (domain, data_class, subject, effective_at.isoformat(), knowable_at.isoformat(),
         json.dumps(value), source, vintage, datetime.now().astimezone().isoformat()),
    )


def ingest_observations(conn: Database, observations, domain: str, source: str) -> int:
    """Store what a world produced, as a corpus.

    The bridge from `simulation.world`: observations already carry both
    timestamps, so nothing is derived and nothing is guessed. Recorded under the
    domain the caller names, which will be `simulated` for a generated world -
    stated at the call site rather than inferred, because a corpus that guessed
    its own provenance would be exactly the thing the domains exist to prevent."""
    _check_domain(domain)
    count = 0
    for observation in observations:
        record(
            conn, domain=domain, data_class=observation.data_class,
            subject=observation.subject, effective_at=observation.effective_at,
            knowable_at=observation.knowable_at, value=observation.value,
            source=source or observation.generator,
        )
        count += 1
    return count


def as_of(
    conn: Database,
    moment: datetime,
    domains,
    data_class: str | None = None,
    subject: str | None = None,
    since: datetime | None = None,
) -> list[dict]:
    """Everything knowable by `moment`, in the named domains.

    `moment` and `domains` are both required and neither has a default. A query
    without a moment is a lookahead waiting to happen, and a query without
    domains is one that would silently blend a real corpus with generated data -
    both are mistakes that produce better-looking results and no error."""
    if not domains:
        raise ValueError(
            "a query must name its domains. There is no 'all': mixing a real corpus with generated "
            "data is the failure this store exists to make impossible to do by accident."
        )
    named = [_check_domain(d) for d in domains]

    clauses = ["knowable_at <= ?", f"domain IN ({','.join('?' * len(named))})"]
    params: list = [moment.isoformat(), *named]
    if data_class:
        clauses.append("data_class = ?")
        params.append(data_class)
    if subject:
        clauses.append("subject = ?")
        params.append(subject)
    if since:
        clauses.append("effective_at >= ?")
        params.append(since.isoformat())

    rows = conn.fetchall(
        f"SELECT * FROM observations WHERE {' AND '.join(clauses)} "
        "ORDER BY effective_at, vintage",
        tuple(params),
    )
    return [_row(row) for row in rows]


def latest_vintage_as_of(
    conn: Database,
    moment: datetime,
    domains,
    data_class: str,
    subject: str,
) -> list[dict]:
    """One row per described moment: the newest revision knowable by `moment`.

    What a backtest actually wants. Reading the corpus raw gives every revision
    of every figure, and taking the last of them gives the *final* revision -
    which is the number nobody had at the time.

    Ordered by vintage rather than by `knowable_at` so two revisions published in
    the same instant still resolve deterministically."""
    observations = as_of(conn, moment, domains, data_class=data_class, subject=subject)
    newest: dict = {}
    for observation in observations:
        key = observation["effective_at"]
        current = newest.get(key)
        if current is None or observation["vintage"] >= current["vintage"]:
            newest[key] = observation
    return [newest[key] for key in sorted(newest)]


def revisions(conn: Database, data_class: str, subject: str, effective_at: datetime) -> list[dict]:
    """Every vintage of one figure, oldest first.

    Not an as-of query, and deliberately named so it cannot be mistaken for one:
    this is for studying how a number was revised, which is a question about the
    corpus rather than a question the organization could have asked at the time."""
    rows = conn.fetchall(
        "SELECT * FROM observations WHERE data_class = ? AND subject = ? AND effective_at = ? "
        "ORDER BY vintage",
        (data_class, subject, effective_at.isoformat()),
    )
    return [_row(row) for row in rows]


def summary(conn: Database) -> dict:
    rows = conn.fetchall(
        "SELECT domain, COUNT(*) AS n, MIN(effective_at) AS earliest, MAX(effective_at) AS latest "
        "FROM observations GROUP BY domain"
    )
    return {
        row["domain"]: {
            "observations": row["n"], "earliest": row["earliest"], "latest": row["latest"],
        }
        for row in rows
    }


def _row(row) -> dict:
    record = dict(row)
    record["value"] = json.loads(record["value"])
    return record
