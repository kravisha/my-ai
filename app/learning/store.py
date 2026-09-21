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

## Six tables, and the boundaries between them

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
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
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
CREATE INDEX IF NOT EXISTS idx_attempts_episode ON attempts(episode_id, at);
CREATE INDEX IF NOT EXISTS idx_knowledge_episode ON knowledge(episode_id);
"""

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
    return connection


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


def record_lesson(*, kind: str, pattern: str, lesson: str,
                  episode_slug: str | None = None) -> int:
    """A lesson, or one more sighting of one already recorded.

    Upserted on `(kind, pattern)` and counted, because §26's value is entirely in
    the count: *"I repeatedly waste time researching this source"* is a claim
    about frequency, and a hundred separate rows saying the same thing is the
    shape that makes it invisible."""
    with connect() as db:
        existing = db.execute(
            "SELECT id, episodes, times_seen FROM lessons WHERE kind = ? AND pattern = ?",
            (kind, pattern)).fetchone()
        if existing is not None:
            seen = json.loads(existing["episodes"] or "[]")
            if episode_slug and episode_slug not in seen:
                seen.append(episode_slug)
            db.execute("UPDATE lessons SET times_seen = times_seen + 1, "
                       "episodes = ?, at = ?, lesson = ? WHERE id = ?",
                       (json.dumps(seen), _now(), lesson, existing["id"]))
            return int(existing["id"])
        cursor = db.execute(
            "INSERT INTO lessons (at, kind, pattern, lesson, episodes) "
            "VALUES (?, ?, ?, ?, ?)",
            (_now(), kind, pattern, lesson,
             json.dumps([episode_slug] if episode_slug else [])))
        return int(cursor.lastrowid)


def lessons(kind: str | None = None) -> list[dict]:
    query = "SELECT * FROM lessons"
    params: list = []
    if kind is not None:
        query += " WHERE kind = ?"
        params.append(kind)
    with connect() as db:
        rows = db.execute(query + " ORDER BY times_seen DESC, at DESC", params).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["episodes"] = json.loads(item["episodes"] or "[]")
        out.append(item)
    return out
