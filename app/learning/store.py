"""Where learning is kept, so that the next attempt can read the last one.

SQLite rather than JSONL, which is the opposite of the choice `app/model_calls.py`
made two days earlier, and for a reason worth stating: a call log is append-only
telemetry read in bulk, while a learning episode is a *record with a current
state* that is read back, joined against, and updated as attempts accumulate.
Document 1 §25's learning memory and §26's meta-learning are both queries across
episodes, and answering "which sources have paid off" over JSONL means
re-implementing GROUP BY by hand.

Standalone `sqlite3` rather than `backend/db.py`, following
`app/model_performance.py`: the Gateway must not need the backend running to
learn anything, and the two services share no database today.

## Eight tables, and the boundaries between them

- `episodes` — one per capability being learned. Holds the objective, the plan
  and the commitment, and **not** the state: the state is computed from evidence
  by `mastery.state_of` and storing it would create a second answer that could
  disagree with the first.
- `attempts` — every practice, test, trial and demonstration. Append-only. This
  is the learning history Document 1 §14 asks for, and it is never rewritten,
  because an attempt that was wrong is the evidence.
- `knowledge` — what was learned and where from, with a trust tier (§10) and
  whether a test later confirmed it (§11). Provenance is a column, not a note.
- `recipes` — every version, superseded rather than replaced, so §24's revert is
  a SELECT rather than a mechanism.
- `feedback` — Krish's verdicts, and whether each was acted on.
- `lessons` — §25/§26's memory: what generalises beyond one episode.
- `lesson_references` — every time a lesson was actually handed to a decision,
  and whether that decision then went well. The other half of the bet.
- `lesson_kinds` — one row per kind, and the only thing that survives a
  collection: what this kind of fact has cost and returned, in total.

## A lesson is a bet, and both halves are kept

Krish, 2026-09-23, on whether *"the March invoice from Acme always arrives late"*
is a lesson or a context: *"it's a fact that Claude may choose to remember and
this cost may or may not be rewarded by a cost saving use in the future... all
deadweight unreferenced information should be eventually garbage collected."*

`times_seen` was the only number here and it is the acquisition side: how often
the world produced the pattern. It said nothing about whether the lesson was ever
read back, which is the half that decides whether keeping it was worth anything.
So `lessons` now also carries `times_offered` (it was a candidate),
`times_referenced` (it was handed over) and `times_paid_off` (what it was handed
to then went well). `app/learning/retention.py` decides fates from those and
touches no database; this module is where the numbers live and the deletions
happen.

**Why `lesson_kinds` is an aggregate and not a tombstone per lesson.** A discard
deletes the row, because that is what was asked for - but *"facts of this kind
cost us this much and were never once used"* is the training signal for guessing
better next time and has to outlive the rows. One row per kind means the record
of what was thrown away is bounded by the number of kinds, and so can never
itself become the deadweight it exists to prevent.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

SCHEMA_VERSION = 1
PATH_ENV = "LEARNING_DB_PATH"

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    origin          TEXT NOT NULL,
    objective_json  TEXT NOT NULL,
    plan_json       TEXT,
    commitment_json TEXT,
    accepted_by_user INTEGER NOT NULL DEFAULT 0,
    schema_version  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    INTEGER NOT NULL,
    at            TEXT NOT NULL,
    kind          TEXT NOT NULL,
    case_name     TEXT,
    recipe_version INTEGER,
    passed        INTEGER,
    expected      TEXT,
    observed      TEXT,
    diagnosis_json TEXT,
    cost_json     TEXT,
    trace_json    TEXT,
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);
CREATE TABLE IF NOT EXISTS knowledge (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id   INTEGER NOT NULL,
    at           TEXT NOT NULL,
    question     TEXT NOT NULL,
    answer       TEXT NOT NULL,
    source_kind  TEXT NOT NULL,
    source_ref   TEXT,
    trust_tier   INTEGER NOT NULL,
    confirmed_by_test INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);
CREATE TABLE IF NOT EXISTS recipes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    INTEGER NOT NULL,
    version       INTEGER NOT NULL,
    at            TEXT NOT NULL,
    spec_json     TEXT NOT NULL,
    why           TEXT,
    superseded_by INTEGER,
    UNIQUE (episode_id, version),
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id  INTEGER NOT NULL,
    at          TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    note        TEXT,
    acted_on    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);
CREATE TABLE IF NOT EXISTS lessons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    pattern    TEXT NOT NULL,
    lesson     TEXT NOT NULL,
    episodes   TEXT,
    times_seen INTEGER NOT NULL DEFAULT 1,
    UNIQUE (kind, pattern)
);
CREATE TABLE IF NOT EXISTS lesson_references (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id   INTEGER NOT NULL,
    episode_slug TEXT,
    at          TEXT NOT NULL,
    credited    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (lesson_id) REFERENCES lessons(id)
);
CREATE TABLE IF NOT EXISTS lesson_kinds (
    kind                   TEXT PRIMARY KEY,
    recorded               INTEGER NOT NULL DEFAULT 0,
    referenced             INTEGER NOT NULL DEFAULT 0,
    paid_off               INTEGER NOT NULL DEFAULT 0,
    discarded_unreferenced INTEGER NOT NULL DEFAULT 0,
    cost_sunk              REAL NOT NULL DEFAULT 0,
    regretted              INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS collected_patterns (
    kind                  TEXT NOT NULL,
    pattern               TEXT NOT NULL,
    discarded_at          TEXT NOT NULL,
    quiet_days_at_discard REAL NOT NULL DEFAULT 0,
    cost_at_discard       REAL NOT NULL DEFAULT 0,
    because               TEXT,
    PRIMARY KEY (kind, pattern)
);
CREATE INDEX IF NOT EXISTS idx_attempts_episode ON attempts(episode_id, at);
CREATE INDEX IF NOT EXISTS idx_knowledge_episode ON knowledge(episode_id);
CREATE INDEX IF NOT EXISTS idx_refs_lesson ON lesson_references(lesson_id);
CREATE INDEX IF NOT EXISTS idx_refs_episode ON lesson_references(episode_slug, credited);
"""

# Columns added to `lessons` after it had rows in it. Additive, in the shape
# `backend/migrations.py` uses: a new column with a default is a migration a
# running system survives, and every one of these has a default because the
# alternative is a NOT NULL against existing rows, which fails.
LESSON_COLUMNS = (
    ("cost", "REAL NOT NULL DEFAULT 0"),
    ("times_offered", "INTEGER NOT NULL DEFAULT 0"),
    ("times_referenced", "INTEGER NOT NULL DEFAULT 0"),
    ("last_referenced_at", "TEXT"),
    ("times_paid_off", "INTEGER NOT NULL DEFAULT 0"),
    ("expected_interval_days", "REAL"),
    # Set when retention puts a lesson on probation: kept, and no longer offered.
    ("demoted_at", "TEXT"),
)

KIND_COLUMNS = (
    ("regretted", "INTEGER NOT NULL DEFAULT 0"),
)

# Attempt kinds. The distinction between `development` and `heldout` is the one
# `mastery.py` depends on: mixing them would make fitting indistinguishable
# from learning.
KIND_PRACTICE = "practice"
KIND_DEVELOPMENT = "development"
KIND_HELDOUT = "heldout"
KIND_TRIAL = "real_world_trial"
KIND_DEMONSTRATION = "demonstration"
KIND_OPERATIONAL = "operational"
KINDS = (KIND_PRACTICE, KIND_DEVELOPMENT, KIND_HELDOUT, KIND_TRIAL,
         KIND_DEMONSTRATION, KIND_OPERATIONAL)


def database_path() -> Path:
    configured = (os.environ.get(PATH_ENV, "") or "").strip()
    return Path(configured) if configured else PROJECT_ROOT / "learning.db"


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    _migrate(connection)
    return connection


def _migrate(db: sqlite3.Connection) -> None:
    """Add columns that `CREATE TABLE IF NOT EXISTS` cannot add.

    `connect` re-runs the schema on every call, which creates missing *tables*
    and silently does nothing for a missing *column* on a table that already
    exists. A developer with a learning.db from last week would otherwise get
    `no such column: times_offered` at the first read, which is the failure this
    loop exists to prevent."""
    for table, columns in (("lessons", LESSON_COLUMNS),
                           ("lesson_kinds", KIND_COLUMNS)):
        have = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for column, declaration in columns:
            if column not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row) -> dict:
    return dict(row) if row is not None else {}


# --- episodes -----------------------------------------------------------------


def create_episode(slug: str, objective: dict, origin: str) -> int:
    with connect() as db:
        existing = db.execute("SELECT id FROM episodes WHERE slug = ?",
                              (slug,)).fetchone()
        if existing is not None:
            db.execute("UPDATE episodes SET objective_json = ?, updated_at = ? "
                       "WHERE id = ?",
                       (json.dumps(objective), _now(), existing["id"]))
            return int(existing["id"])
        cursor = db.execute(
            "INSERT INTO episodes (slug, created_at, updated_at, origin, "
            "objective_json, schema_version) VALUES (?, ?, ?, ?, ?, ?)",
            (slug, _now(), _now(), origin, json.dumps(objective), SCHEMA_VERSION))
        return int(cursor.lastrowid)


def set_plan(episode_id: int, plan: dict, commitment: dict | None = None) -> None:
    with connect() as db:
        db.execute("UPDATE episodes SET plan_json = ?, commitment_json = ?, "
                   "updated_at = ? WHERE id = ?",
                   (json.dumps(plan),
                    json.dumps(commitment) if commitment is not None else None,
                    _now(), episode_id))


def accept_episode(episode_id: int) -> None:
    """Krish's acceptance. The only field a human writes; see `mastery.py`."""
    with connect() as db:
        db.execute("UPDATE episodes SET accepted_by_user = 1, updated_at = ? "
                   "WHERE id = ?", (_now(), episode_id))


def get_episode(slug_or_id) -> dict:
    with connect() as db:
        column = "id" if isinstance(slug_or_id, int) else "slug"
        row = db.execute(f"SELECT * FROM episodes WHERE {column} = ?",
                         (slug_or_id,)).fetchone()
    episode = _row(row)
    if not episode:
        return {}
    episode["objective"] = json.loads(episode.pop("objective_json") or "{}")
    episode["plan"] = json.loads(episode.pop("plan_json") or "null")
    episode["commitment"] = json.loads(episode.pop("commitment_json") or "null")
    episode["accepted_by_user"] = bool(episode["accepted_by_user"])
    return episode


def list_episodes() -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT slug FROM episodes ORDER BY updated_at DESC").fetchall()
    return [get_episode(row["slug"]) for row in rows]


# --- attempts -----------------------------------------------------------------


def record_attempt(episode_id: int, *, kind: str, passed: bool | None,
                   case_name: str | None = None, recipe_version: int | None = None,
                   expected: str | None = None, observed: str | None = None,
                   diagnosis: dict | None = None, cost: dict | None = None,
                   trace: list | None = None) -> int:
    if kind not in KINDS:
        raise ValueError(f"attempt kind={kind!r} is not one of {KINDS}")
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO attempts (episode_id, at, kind, case_name, recipe_version, "
            "passed, expected, observed, diagnosis_json, cost_json, trace_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (episode_id, _now(), kind, case_name, recipe_version,
             None if passed is None else int(passed), expected, observed,
             json.dumps(diagnosis) if diagnosis else None,
             json.dumps(cost) if cost else None,
             json.dumps(trace) if trace else None))
        db.execute("UPDATE episodes SET updated_at = ? WHERE id = ?",
                   (_now(), episode_id))
        return int(cursor.lastrowid)


def attempts(episode_id: int, kind: str | None = None) -> list[dict]:
    query = "SELECT * FROM attempts WHERE episode_id = ?"
    params: list = [episode_id]
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    with connect() as db:
        rows = db.execute(query + " ORDER BY id", params).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["passed"] = None if item["passed"] is None else bool(item["passed"])
        item["diagnosis"] = json.loads(item.pop("diagnosis_json") or "null")
        item["cost"] = json.loads(item.pop("cost_json") or "null")
        item["trace"] = json.loads(item.pop("trace_json") or "null")
        out.append(item)
    return out


def latest_case_results(episode_id: int, kind: str) -> dict[str, bool]:
    """The most recent verdict per case, not every verdict.

    A case that failed twice and then passed has been learned, and counting all
    three rows would report it as one-of-three. The evidence
    `mastery.state_of` reads is *current* per case, which is why this collapses
    by case name in arrival order."""
    latest: dict[str, bool] = {}
    for attempt in attempts(episode_id, kind):
        if attempt["case_name"] and attempt["passed"] is not None:
            latest[attempt["case_name"]] = attempt["passed"]
    return latest


# --- knowledge, recipes, feedback, lessons ------------------------------------


def record_knowledge(episode_id: int, *, question: str, answer: str,
                     source_kind: str, trust_tier: int,
                     source_ref: str | None = None,
                     confirmed_by_test: bool = False) -> int:
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO knowledge (episode_id, at, question, answer, source_kind, "
            "source_ref, trust_tier, confirmed_by_test) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (episode_id, _now(), question, answer, source_kind, source_ref,
             int(trust_tier), int(confirmed_by_test)))
        return int(cursor.lastrowid)


def confirm_knowledge(knowledge_id: int) -> None:
    with connect() as db:
        db.execute("UPDATE knowledge SET confirmed_by_test = 1 WHERE id = ?",
                   (knowledge_id,))


def knowledge(episode_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM knowledge WHERE episode_id = ? ORDER BY id",
                          (episode_id,)).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["confirmed_by_test"] = bool(item["confirmed_by_test"])
        out.append(item)
    return out


def save_recipe(episode_id: int, spec: dict, why: str = "") -> int:
    """Store a new version, superseding the previous one rather than replacing it.

    §24: *"The old working version must not simply disappear."* Revert is
    therefore `recipe_version(episode, n)` and needs no mechanism of its own."""
    with connect() as db:
        previous = db.execute(
            "SELECT id, version FROM recipes WHERE episode_id = ? "
            "ORDER BY version DESC LIMIT 1", (episode_id,)).fetchone()
        version = int(spec.get("version") or 0) or (
            (int(previous["version"]) + 1) if previous else 1)
        db.execute("DELETE FROM recipes WHERE episode_id = ? AND version = ?",
                   (episode_id, version))
        cursor = db.execute(
            "INSERT INTO recipes (episode_id, version, at, spec_json, why) "
            "VALUES (?, ?, ?, ?, ?)",
            (episode_id, version, _now(), json.dumps({**spec, "version": version}), why))
        if previous is not None and int(previous["version"]) != version:
            db.execute("UPDATE recipes SET superseded_by = ? WHERE id = ?",
                       (cursor.lastrowid, previous["id"]))
        return version


def recipe_versions(episode_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM recipes WHERE episode_id = ? ORDER BY version",
                          (episode_id,)).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["spec"] = json.loads(item.pop("spec_json"))
        out.append(item)
    return out


def latest_recipe(episode_id: int) -> dict | None:
    versions = recipe_versions(episode_id)
    return versions[-1] if versions else None


def record_feedback(episode_id: int, *, verdict: str, note: str | None = None) -> int:
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO feedback (episode_id, at, verdict, note) VALUES (?, ?, ?, ?)",
            (episode_id, _now(), verdict, note))
        db.execute("UPDATE episodes SET updated_at = ? WHERE id = ?",
                   (_now(), episode_id))
        return int(cursor.lastrowid)


def mark_feedback_acted_on(feedback_id: int) -> None:
    with connect() as db:
        db.execute("UPDATE feedback SET acted_on = 1 WHERE id = ?", (feedback_id,))


def feedback(episode_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM feedback WHERE episode_id = ? ORDER BY id",
                          (episode_id,)).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["acted_on"] = bool(item["acted_on"])
        out.append(item)
    return out


def _bump_kind(db: sqlite3.Connection, kind: str, **deltas) -> None:
    """Add to a kind's tally, creating the row if this is its first fact.

    Separate from the lesson row on purpose: this is the part that outlives a
    collection, so it must never be a column on the thing being collected."""
    db.execute("INSERT OR IGNORE INTO lesson_kinds (kind) VALUES (?)", (kind,))
    if not deltas:
        return
    sets = ", ".join(f"{column} = {column} + ?" for column in deltas)
    db.execute(f"UPDATE lesson_kinds SET {sets} WHERE kind = ?",
               (*deltas.values(), kind))


def record_lesson(*, kind: str, pattern: str, lesson: str,
                  episode_slug: str | None = None, cost: float = 0.0,
                  expected_interval_days: float | None = None) -> int:
    """A lesson, or one more sighting of one already recorded.

    Upserted on `(kind, pattern)` and counted, because §26's value is entirely in
    the count: *"I repeatedly waste time researching this source"* is a claim
    about frequency, and a hundred separate rows saying the same thing is the
    shape that makes it invisible.

    `cost` is what acquiring it cost, and it **accumulates across sightings**
    rather than being overwritten: learning the same thing four times cost four
    times as much, and that total is the number that makes a never-referenced
    lesson worth complaining about. `expected_interval_days` is how often the
    fact is expected to be *relevant* - a yearly invoice is 365 - and is left
    None when nothing knows, which `retention` reads as a reason to wait longer
    rather than a licence to collect sooner.

    A re-sighting does not count as a new fact of its kind. `lesson_kinds.recorded`
    is how many facts of this kind were bet on, and counting an upsert would make
    one lesson seen fifty times look like fifty independent bets, which is the
    denominator of every payoff rate here."""
    with connect() as db:
        existing = db.execute(
            "SELECT id, episodes, times_seen FROM lessons WHERE kind = ? AND pattern = ?",
            (kind, pattern)).fetchone()
        if existing is not None:
            seen = json.loads(existing["episodes"] or "[]")
            if episode_slug and episode_slug not in seen:
                seen.append(episode_slug)
            db.execute("UPDATE lessons SET times_seen = times_seen + 1, "
                       "episodes = ?, at = ?, lesson = ?, cost = cost + ?, "
                       "expected_interval_days = COALESCE(?, expected_interval_days) "
                       "WHERE id = ?",
                       (json.dumps(seen), _now(), lesson, float(cost),
                        expected_interval_days, existing["id"]))
            _bump_kind(db, kind, cost_sunk=float(cost))
            return int(existing["id"])
        # Ratification. A pattern we collected and are now learning again is the
        # one observable that says a retention decision was wrong, so it is
        # counted - and the fact is told what its real cycle is, which is the
        # whole of "ratified by real life experiences". A yearly fact collected
        # wrongly once cannot be collected wrongly twice.
        regret = db.execute(
            "SELECT * FROM collected_patterns WHERE kind = ? AND pattern = ?",
            (kind, pattern)).fetchone()
        if regret is not None:
            learned = _relearned_interval(regret)
            expected_interval_days = max(expected_interval_days or 0.0, learned)
            db.execute("DELETE FROM collected_patterns WHERE kind = ? AND pattern = ?",
                       (kind, pattern))
        cursor = db.execute(
            "INSERT INTO lessons (at, kind, pattern, lesson, episodes, cost, "
            "expected_interval_days) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_now(), kind, pattern, lesson,
             json.dumps([episode_slug] if episode_slug else []),
             float(cost), expected_interval_days))
        _bump_kind(db, kind, recorded=1, cost_sunk=float(cost),
                   **({"regretted": 1} if regret is not None else {}))
        return int(cursor.lastrowid)


def _relearned_interval(tombstone) -> float:
    """The cycle a wrongly-collected fact has just demonstrated.

    It was quiet for `quiet_days_at_discard` when we threw it away, then stayed
    thrown away until now. Its true period is at least the sum: that is what the
    world just said, rather than what the default assumed."""
    away = 0.0
    try:
        gone = datetime.fromisoformat(tombstone["discarded_at"])
        if gone.tzinfo is None:
            gone = gone.replace(tzinfo=timezone.utc)
        away = max(0.0, (datetime.now(timezone.utc) - gone).total_seconds() / 86400.0)
    except (ValueError, TypeError):
        away = 0.0
    return float(tombstone["quiet_days_at_discard"] or 0.0) + away


def regretted_patterns() -> list[dict]:
    """What has been collected and not (yet) learned again.

    The evidence `retention.ratification` is a verdict on. Readable so that a
    person judging whether the policy is too aggressive can see *what* it threw
    away, not only how much."""
    with connect() as db:
        return [_row(row) for row in db.execute(
            "SELECT * FROM collected_patterns ORDER BY discarded_at DESC")]


def prune_tombstones(*, older_than_days: float) -> int:
    """Forget that something was collected.

    Past the horizon, learning a fact again is a new fact rather than evidence
    that throwing the old one away was wrong - and a tombstone table that grew
    for ever would be the deadweight the collector exists to prevent."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=float(older_than_days))).isoformat()
    with connect() as db:
        cursor = db.execute("DELETE FROM collected_patterns WHERE discarded_at < ?",
                            (cutoff,))
        return int(cursor.rowcount or 0)


def note_offered(lesson_ids) -> int:
    """Record that these lessons were candidates, whether or not they were used.

    This is the number that tells a dormant seasonal fact from deadweight. Being
    unused means nothing on its own; being unused *while repeatedly on the table*
    is the finding. Called by whatever reads lessons to make a decision, and
    called for every lesson it looked at rather than every lesson it liked."""
    ids = [int(one) for one in lesson_ids]
    if not ids:
        return 0
    with connect() as db:
        marks = ",".join("?" for _ in ids)
        db.execute(f"UPDATE lessons SET times_offered = times_offered + 1 "
                   f"WHERE id IN ({marks})", ids)
    return len(ids)


def note_referenced(lesson_id: int, *, episode_slug: str | None = None) -> None:
    """Record that a lesson was actually handed to a decision.

    `lesson_kinds.referenced` counts *lessons of this kind that were ever used*,
    not uses, so it only moves on a lesson's first reference. The two are very
    different denominators and mixing them would let one popular lesson make its
    whole kind look valuable."""
    with connect() as db:
        row = db.execute("SELECT kind, times_referenced FROM lessons WHERE id = ?",
                         (lesson_id,)).fetchone()
        if row is None:
            return
        db.execute("UPDATE lessons SET times_referenced = times_referenced + 1, "
                   "last_referenced_at = ? WHERE id = ?", (_now(), lesson_id))
        db.execute("INSERT INTO lesson_references (lesson_id, episode_slug, at) "
                   "VALUES (?, ?, ?)", (lesson_id, episode_slug, _now()))
        first = int(row["times_referenced"] or 0) == 0
        _bump_kind(db, row["kind"], **({"referenced": 1} if first else {}))


def credit_episode(episode_slug: str) -> list[int]:
    """Credit every lesson this episode was given, now that it went well.

    Called when an episode reaches a *good* terminal state. Payoff is deliberately
    attributed to the reference rather than to the lesson in general: a lesson
    handed to four episodes of which one succeeded has paid off once, and
    crediting it on every later success would let one hit pay for every miss.

    Returns the lesson ids credited. Idempotent: `credited` stops a second call
    for the same episode paying twice."""
    with connect() as db:
        rows = db.execute(
            "SELECT id, lesson_id FROM lesson_references "
            "WHERE episode_slug = ? AND credited = 0", (episode_slug,)).fetchall()
        credited = []
        for row in rows:
            lesson = db.execute(
                "SELECT kind, times_paid_off FROM lessons WHERE id = ?",
                (row["lesson_id"],)).fetchone()
            db.execute("UPDATE lesson_references SET credited = 1 WHERE id = ?",
                       (row["id"],))
            if lesson is None:
                continue
            db.execute("UPDATE lessons SET times_paid_off = times_paid_off + 1 "
                       "WHERE id = ?", (row["lesson_id"],))
            first = int(lesson["times_paid_off"] or 0) == 0
            _bump_kind(db, lesson["kind"], **({"paid_off": 1} if first else {}))
            credited.append(int(row["lesson_id"]))
        return credited


def kind_history(kind: str) -> dict:
    """What this kind of fact has cost and returned, across everything ever kept.

    Returns zeroes for a kind nothing has recorded, rather than None, because
    `retention.worth_recording` must be able to say "nobody has tried this" and
    a missing row is that answer rather than an error."""
    with connect() as db:
        row = db.execute("SELECT * FROM lesson_kinds WHERE kind = ?",
                         (kind,)).fetchone()
    if row is None:
        return {"kind": kind, "recorded": 0, "referenced": 0, "paid_off": 0,
                "discarded_unreferenced": 0, "cost_sunk": 0.0}
    return _row(row)


def kind_histories() -> list[dict]:
    with connect() as db:
        return [_row(row) for row in db.execute(
            "SELECT * FROM lesson_kinds ORDER BY recorded DESC, kind")]


def demote_lesson(lesson_id: int) -> None:
    """Stop offering a lesson without deleting it.

    Probation. A wrong call here costs a missed hint; a wrong deletion costs the
    fact, and those are not the same mistake."""
    with connect() as db:
        db.execute("UPDATE lessons SET demoted_at = ? WHERE id = ? "
                   "AND demoted_at IS NULL", (_now(), lesson_id))


def restore_lesson(lesson_id: int) -> None:
    """Offer it again. The way back off probation, so demotion is not a deletion
    with extra steps."""
    with connect() as db:
        db.execute("UPDATE lessons SET demoted_at = NULL WHERE id = ?",
                   (lesson_id,))


def discard_lesson(lesson_id: int, *, quiet_days: float = 0.0,
                   because: str = "") -> dict:
    """Collect a lesson, leaving its kind's tally behind.

    The row goes and its references go with it. What stays is one increment on
    `lesson_kinds`, which is how *"we spent this and never used any of it"*
    outlives the rows it is about. Returns what was discarded, so a caller can
    report it before it is gone for good."""
    with connect() as db:
        row = db.execute("SELECT * FROM lessons WHERE id = ?",
                         (lesson_id,)).fetchone()
        if row is None:
            return {}
        gone = _row(row)
        never_used = int(gone.get("times_referenced") or 0) == 0
        _bump_kind(db, gone["kind"],
                   **({"discarded_unreferenced": 1} if never_used else {}))
        # The tombstone, so that learning this again is recognisable as a regret.
        # `REPLACE` because the same pattern may be collected more than once, and
        # the most recent discard is the one a re-learning argues with.
        db.execute(
            "INSERT OR REPLACE INTO collected_patterns "
            "(kind, pattern, discarded_at, quiet_days_at_discard, cost_at_discard, "
            "because) VALUES (?, ?, ?, ?, ?, ?)",
            (gone["kind"], gone["pattern"], _now(), float(quiet_days),
             float(gone.get("cost") or 0.0), because))
        db.execute("DELETE FROM lesson_references WHERE lesson_id = ?", (lesson_id,))
        db.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
        gone["episodes"] = json.loads(gone.get("episodes") or "[]")
        return gone


def lesson_references(lesson_id: int) -> list[dict]:
    with connect() as db:
        return [_row(row) for row in db.execute(
            "SELECT * FROM lesson_references WHERE lesson_id = ? ORDER BY at",
            (lesson_id,))]


def lessons(kind: str | None = None, *, include_demoted: bool = False) -> list[dict]:
    """Lessons, newest and most-seen first.

    Demoted lessons are **excluded by default**, because the commonest caller is
    something about to offer advice and probation means "stop offering this".
    A reporting caller passes `include_demoted=True`: a demoted lesson is still
    part of the record of what was learned, and hiding it from `meta_report`
    would make the report disagree with the database."""
    query = "SELECT * FROM lessons"
    where = []
    params: list = []
    if kind is not None:
        where.append("kind = ?")
        params.append(kind)
    if not include_demoted:
        where.append("demoted_at IS NULL")
    if where:
        query += " WHERE " + " AND ".join(where)
    with connect() as db:
        rows = db.execute(query + " ORDER BY times_seen DESC, at DESC", params).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["episodes"] = json.loads(item["episodes"] or "[]")
        out.append(item)
    return out
