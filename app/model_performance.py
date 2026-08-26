"""The Model Performance Registry: which model is good at what, by evidence
(TASK_QUEUE TQ-54, docs/SPEC_RECONCILIATION.md §105).

Source: addendum 45 §8 (the registry), §9 (front-runner), §10 (penalties and
rewards), §11 (task-specific demotion), §12 (seeding), §13 (no permanent
position), §42 (the eight leaderboards), §45 Phase A + C.

## Not `docs/model_registry.yaml`, and the reason is the writer

§103 settled this. `model_registry.yaml` is hand-authored, committed, reviewed
and asserted against the code — *what is configured*. This is machine-written
after every task, at a volume no committed file should carry — *what performs
well at what*. Scores in git would dirty the working tree on every inference and
make those assertions race a moving target.

Storage follows `app/model_budget.py` exactly, and for its reason: the
organization is a population of separate processes, each holding its own
provider, and a per-process table would let them disagree about who is winning.
One SQLite file, path resolved at call time from the environment so tests
redirect without import-order games.

## A seed and a measurement must stay decomposable

The mistake this design exists to avoid: storing one `score` that blends the
hand-authored guess with the measured evidence. §12 requires that *"once enough
real simulation evidence exists, empirical data should dominate the initial
seed"* — impossible if the two were averaged into a number nobody can take apart
later.

So the seed is stored once and never changes, and the composite is derived:

    score = (SEED_PRIOR_SAMPLES * seed_score + n * measured_mean)
            / (SEED_PRIOR_SAMPLES + n)

The seed is worth exactly `SEED_PRIOR_SAMPLES` observations. At n=0 the score is
the seed; by n=50 the seed is 9% of it; it never quite vanishes and never has to
be deleted. **Nobody decides when evidence takes over — arithmetic does**, which
is the property §13 wants when it says the system must not be trapped by the
original human guess.

`confidence` is the same ratio read from the other side: how much of the score is
measurement rather than guess.

## Rankings are per category, and that is structural

§11: *"A model failing at one type of task should not necessarily lose rank
everywhere."* Rows are keyed by `(model_id, task_category)`, so an outcome
recorded against `LONG_CONTEXT_AND_MEMORY` cannot touch `CODING_AND_DEBUGGING` —
not by policy, but because there is no code path from one row to the other.

## What is deliberately not scored yet

§8 lists `cost_score` and `resource_efficiency_score`. **Nothing produces
either.** Local cost needs the hardware monitoring TQ-57 brings; external cost
needs §37's cost model, which is TQ-65's. Columns for them would be columns that
are always NULL — machinery with no user, and the registry's own discipline is
*empirical or absent, never a number nobody measured*.

They are added by the increment that first measures them. A composite that gains
a dimension later simply ranks differently from then on, which is what evidence
is supposed to do.

## Nothing here chooses a model

This answers *"who is ahead at this task?"*. It does not answer *"what should run
this task?"* — that needs privacy, hardware load, availability and budget, and it
is TQ-60's. Keeping the line means a leaderboard cannot quietly become a router
that ignores §36.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.task_signature import TASK_CATEGORIES, UnknownVocabulary

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PATH_ENV = "MODEL_PERFORMANCE_DB_PATH"

SCHEMA_VERSION = 1

# --- the tunable part (§10: "The scoring system must be tunable") -------------------
#
# Every number below is a policy choice with a stated reason, not a measurement.
# They are module constants rather than a config file because nothing has asked
# to change them at runtime yet; when something does, they move to the
# environment the way model_budget's limits already do.

# How many observations the hand-authored seed is worth. Five is small enough
# that a handful of real results moves a ranking, large enough that one unlucky
# outcome does not. §12's "empirical should dominate" made arithmetic.
SEED_PRIOR_SAMPLES = 5

# The band a seeded ordering is spread across. Centred on 0.5 - a single seeded
# model sits exactly at neutral, because "the only model we have" is not
# evidence that it is good.
SEED_NEUTRAL = 0.5
SEED_SPREAD = 0.15

# Exponential moving average weight for the recent window, which is what `trend`
# compares against the long-run mean. Higher = twitchier.
TREND_ALPHA = 0.3
# How far recent and overall must diverge before it is called a trend rather
# than noise.
TREND_EPSILON = 0.02

# §10's penalties and rewards, as score deltas applied to a single outcome's
# quality before it enters the mean. A failure is not merely a low score - it
# carries its own weight, so "wrong answer" and "timed out" can be tuned apart.
FAILURE_PENALTIES = {
    "wrong_answer": 1.0,
    "hallucination": 1.0,
    "failed_structured_output": 0.8,
    "timeout": 0.7,
    "excessive_latency": 0.4,
    "instruction_not_followed": 0.6,
    "incomplete": 0.6,
    "needed_external_rework": 0.5,
}

# A latency this task was happy with earns a small bonus; nothing here converts
# milliseconds into a score, because "fast" is only meaningful against what the
# task needed (§20's latency_sensitivity) and that comparison is TQ-60's.
LATENCY_BONUS = 0.05

STATUS_SEEDED = "SEEDED"
STATUS_MEASURED = "MEASURED"
STATUSES = (STATUS_SEEDED, STATUS_MEASURED)

TREND_RISING = "rising"
TREND_FALLING = "falling"
TREND_STEADY = "steady"
TREND_UNKNOWN = "unknown"

# The agent-specific bucket for work that declared no role. `model_budget` uses
# the same word for the same reason: an honest bucket beats a clever wrong label.
UNATTRIBUTED = "unattributed"


class UnknownFailure(ValueError):
    """A failure type outside the tunable table. Fail closed: a penalty this
    build cannot weigh is not one it may silently score as zero."""


def _path() -> Path:
    return Path(os.environ.get(PATH_ENV) or (PROJECT_ROOT / "model_performance.db"))


def database_path() -> Path:
    """Where this subsystem's machine-written state lives.

    Public because `app/routing_decisions.py` shares the file (TQ-55, §106): the
    decision log and the leaderboards are two steps of one loop, and the outcome
    fields they both hold are the same facts. Sharing the path through an
    accessor makes that explicit rather than having a second module reach into a
    private name or resolve the environment variable a second time."""
    return _path()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")
    # One row per model per task category (§11: rankings are task-specific, and
    # there is deliberately no path from one category's row to another's).
    #
    # `seed_score` is written once at seeding and never updated - it is the
    # hand-authored guess, and a guess that could be edited by an outcome would
    # stop being decomposable from the evidence (§12).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS model_performance ("
        "  model_id TEXT NOT NULL,"
        "  task_category TEXT NOT NULL,"
        "  seed_score REAL NOT NULL,"
        "  seed_rank INTEGER NOT NULL,"
        "  quality_total REAL NOT NULL DEFAULT 0,"
        "  sample_count INTEGER NOT NULL DEFAULT 0,"
        "  failure_count INTEGER NOT NULL DEFAULT 0,"
        "  penalty_total REAL NOT NULL DEFAULT 0,"
        "  bonus_total REAL NOT NULL DEFAULT 0,"
        "  latency_total_ms REAL NOT NULL DEFAULT 0,"
        "  latency_samples INTEGER NOT NULL DEFAULT 0,"
        "  recent_score REAL,"
        "  seeded_at TEXT NOT NULL,"
        "  last_updated TEXT,"
        "  schema_version INTEGER NOT NULL DEFAULT 1,"
        "  PRIMARY KEY (model_id, task_category)"
        ")"
    )
    # §8's "AGENT-SPECIFIC performance", beside the global row rather than
    # instead of it. Follows model_budget's spend_by_caller exactly: the rows
    # start empty, they never become a second authority, and a model with no
    # per-agent history simply has none.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS model_performance_by_agent ("
        "  model_id TEXT NOT NULL,"
        "  task_category TEXT NOT NULL,"
        "  agent_role TEXT NOT NULL,"
        "  quality_total REAL NOT NULL DEFAULT 0,"
        "  sample_count INTEGER NOT NULL DEFAULT 0,"
        "  failure_count INTEGER NOT NULL DEFAULT 0,"
        "  last_updated TEXT,"
        "  PRIMARY KEY (model_id, task_category, agent_role)"
        ")"
    )
    return conn


def _check_category(task_category: str) -> str:
    if task_category not in TASK_CATEGORIES:
        raise UnknownVocabulary(
            f"unknown task category {task_category!r}; known are "
            f"{list(TASK_CATEGORIES)}")
    return task_category


# --- seeding (§12) ------------------------------------------------------------------


def _seed_score(position: int, total: int) -> float:
    """Where a hand-authored ordering puts a model, as a number.

    One model sits at neutral, because being the only candidate is not evidence
    of being a good one. Several are spread evenly across a narrow band around
    neutral - narrow on purpose: §13 says the initial ranking may well be wrong,
    so the seed should express an ordering without asserting a gulf that real
    results then have to climb out of."""
    if total <= 1:
        return SEED_NEUTRAL
    step = (2 * SEED_SPREAD) / (total - 1)
    return round(SEED_NEUTRAL + SEED_SPREAD - position * step, 4)


def seed_leaderboard(task_category: str, ordered_model_ids: list[str]) -> list[dict]:
    """Write a provisional initial ordering for one category (§12).

    Idempotent by refusal rather than by overwrite: a model already seeded here
    keeps the seed it has. Re-seeding a leaderboard that has accumulated evidence
    would silently discard that evidence, which is the one thing a seed must
    never do to a measurement.

    Every row it writes is `SEEDED` until an outcome lands on it."""
    _check_category(task_category)
    if not ordered_model_ids:
        raise ValueError("a leaderboard needs at least one model to seed")
    if len(set(ordered_model_ids)) != len(ordered_model_ids):
        raise ValueError(f"duplicate model in seed ordering: {ordered_model_ids}")

    conn = _connect()
    try:
        total = len(ordered_model_ids)
        for position, model_id in enumerate(ordered_model_ids):
            conn.execute(
                "INSERT OR IGNORE INTO model_performance "
                "(model_id, task_category, seed_score, seed_rank, seeded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (model_id, task_category, _seed_score(position, total),
                 position + 1, _now()))
        conn.commit()
    finally:
        conn.close()
    return ranking(task_category)


def seed_all_categories(ordered_model_ids: list[str]) -> dict:
    """The same provisional ordering across all eight leaderboards (§42).

    A starting point, and an explicitly poor one: §7 exists because *"a model may
    be excellent for coding and mediocre for classification"*, so one ordering
    everywhere is precisely the assumption the leaderboards are built to
    disprove. It is honest as a seed because it claims no distinction it has not
    measured - the distinctions arrive from evidence."""
    return {category: seed_leaderboard(category, ordered_model_ids)
            for category in TASK_CATEGORIES}


REGISTRY_PATH = PROJECT_ROOT / "docs" / "model_registry.yaml"


def seed_from_registry(registry_path: Path | None = None) -> dict:
    """Seed every leaderboard from `docs/model_registry.yaml`'s `seed_ordering`.

    The one point where the two registries touch, and it is directional: the
    performance registry learns *which models exist and in what provisional
    order* from the committed file, and tells it nothing back. Measurements
    never flow into git.

    `yaml` is imported here rather than at module scope because PyYAML is a
    **dev** dependency (`requirements-dev.txt`), not a runtime one - the same
    deferred-import convention `backend/continuity.py` uses for `cryptography`,
    so nothing pays for it until something actually reads the file."""
    import yaml

    path = registry_path or REGISTRY_PATH
    registry = yaml.safe_load(path.read_text(encoding="utf-8"))
    ordering = registry.get("seed_ordering") or {}
    if not ordering:
        raise LookupError(
            f"{path} carries no seed_ordering. The hand-authored initial ordering "
            "lives there (§12, §105); seeding cannot invent one.")
    return {category: seed_leaderboard(category, models)
            for category, models in ordering.items()}


# --- recording outcomes (§10) -------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """What happened when a model did a task.

    `quality` is an evaluator's score in 0..1, or None when nobody scored it —
    absent rather than assumed, so an unscored success does not quietly count as
    a perfect one. §38 is the rule this defers to: validate before penalising,
    and a model must not lose points merely because another disagreed."""

    succeeded: bool
    quality: float | None = None
    latency_ms: float | None = None
    latency_acceptable: bool | None = None
    failure_type: str | None = None
    agent_role: str | None = None

    def __post_init__(self) -> None:
        if self.quality is not None and not 0.0 <= self.quality <= 1.0:
            raise ValueError(f"quality must be within 0..1, got {self.quality}")
        if self.failure_type is not None and self.failure_type not in FAILURE_PENALTIES:
            raise UnknownFailure(
                f"unknown failure type {self.failure_type!r}; known are "
                f"{sorted(FAILURE_PENALTIES)}. A penalty this build cannot weigh "
                "is not one it may score as zero.")
        if self.succeeded and self.failure_type is not None:
            raise ValueError("an outcome that succeeded cannot carry a failure type")


def _scored(outcome: Outcome) -> tuple[float, float, float]:
    """One outcome as (quality, penalty, bonus), all in score units.

    A failed outcome contributes zero quality and its own penalty weight, so
    "wrong answer" and "excessive latency" can be tuned apart rather than both
    meaning "bad"."""
    penalty = FAILURE_PENALTIES[outcome.failure_type] if outcome.failure_type else 0.0
    bonus = LATENCY_BONUS if outcome.latency_acceptable else 0.0

    if not outcome.succeeded:
        return 0.0, penalty, 0.0
    # An unscored success counts as neutral, not as a win. Somebody has to look
    # before a model earns points for looking right (§38).
    quality = SEED_NEUTRAL if outcome.quality is None else outcome.quality
    return quality, penalty, bonus


def record_outcome(model_id: str, task_category: str, outcome: Outcome) -> dict:
    """Apply one result to one leaderboard, and only that one.

    §11 is structural here rather than checked: this writes a row keyed by
    `(model_id, task_category)` and there is no statement in this function that
    reaches another category. A model that fails at long context keeps its
    coding rank because nothing here could take it away."""
    _check_category(task_category)
    quality, penalty, bonus = _scored(outcome)

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT recent_score FROM model_performance "
            "WHERE model_id = ? AND task_category = ?",
            (model_id, task_category)).fetchone()
        if row is None:
            raise LookupError(
                f"{model_id!r} has no seeded entry on {task_category!r}. Seed the "
                "leaderboard first - a score with no provisional starting point "
                "cannot be decomposed into seed and evidence (§12).")

        previous = row["recent_score"]
        recent = quality if previous is None else (
            TREND_ALPHA * quality + (1 - TREND_ALPHA) * previous)

        conn.execute(
            "UPDATE model_performance SET "
            "  quality_total = quality_total + ?,"
            "  sample_count = sample_count + 1,"
            "  failure_count = failure_count + ?,"
            "  penalty_total = penalty_total + ?,"
            "  bonus_total = bonus_total + ?,"
            "  latency_total_ms = latency_total_ms + ?,"
            "  latency_samples = latency_samples + ?,"
            "  recent_score = ?,"
            "  last_updated = ? "
            "WHERE model_id = ? AND task_category = ?",
            (quality, 0 if outcome.succeeded else 1, penalty, bonus,
             outcome.latency_ms or 0.0, 1 if outcome.latency_ms is not None else 0,
             recent, _now(), model_id, task_category))

        role = outcome.agent_role or UNATTRIBUTED
        conn.execute(
            "INSERT INTO model_performance_by_agent "
            "(model_id, task_category, agent_role, quality_total, sample_count, "
            " failure_count, last_updated) VALUES (?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(model_id, task_category, agent_role) DO UPDATE SET "
            "  quality_total = quality_total + excluded.quality_total,"
            "  sample_count = sample_count + 1,"
            "  failure_count = failure_count + excluded.failure_count,"
            "  last_updated = excluded.last_updated",
            (model_id, task_category, role, quality,
             0 if outcome.succeeded else 1, _now()))
        conn.commit()
    finally:
        conn.close()
    return entry(model_id, task_category)


# --- reading the leaderboard (§8, §9) -----------------------------------------------


def _interpret(row) -> dict:
    """One stored row as §8's fields, with everything derived rather than
    stored — so a tuning change takes effect on read instead of needing a
    rewrite of history."""
    n = row["sample_count"]
    measured_mean = (row["quality_total"] / n) if n else None
    penalty_mean = (row["penalty_total"] / n) if n else 0.0
    bonus_mean = (row["bonus_total"] / n) if n else 0.0

    # The seed decays as evidence arrives; it never has to be deleted, and
    # nobody decides when it stops mattering.
    weighted = (SEED_PRIOR_SAMPLES * row["seed_score"]
                + n * ((measured_mean or 0.0) - penalty_mean + bonus_mean))
    score = weighted / (SEED_PRIOR_SAMPLES + n)

    recent = row["recent_score"]
    if n < 2 or recent is None or measured_mean is None:
        trend = TREND_UNKNOWN
    elif recent - measured_mean > TREND_EPSILON:
        trend = TREND_RISING
    elif measured_mean - recent > TREND_EPSILON:
        trend = TREND_FALLING
    else:
        trend = TREND_STEADY

    return {
        "model_id": row["model_id"],
        "task_category": row["task_category"],
        "score": round(score, 4),
        # Kept separate, permanently and on purpose (§12): a caller can always
        # ask what was guessed and what was measured.
        "seed_score": row["seed_score"],
        "seed_rank": row["seed_rank"],
        "quality_score": None if measured_mean is None else round(measured_mean, 4),
        "reliability_score": (None if not n
                              else round(1 - row["failure_count"] / n, 4)),
        "failure_rate": None if not n else round(row["failure_count"] / n, 4),
        "latency_score": (None if not row["latency_samples"]
                          else round(row["latency_total_ms"] / row["latency_samples"], 2)),
        "penalty_score": round(row["penalty_total"], 4),
        "bonus_score": round(row["bonus_total"], 4),
        "sample_count": n,
        # How much of `score` is measurement rather than guess - the seed decay
        # read from the other side.
        "confidence": round(n / (n + SEED_PRIOR_SAMPLES), 4),
        "status": STATUS_SEEDED if n == 0 else STATUS_MEASURED,
        "provisional": n < SEED_PRIOR_SAMPLES,
        "trend": trend,
        "last_updated": row["last_updated"],
        "seeded_at": row["seeded_at"],
    }


def entry(model_id: str, task_category: str) -> dict | None:
    _check_category(task_category)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM model_performance WHERE model_id = ? AND task_category = ?",
            (model_id, task_category)).fetchone()
    finally:
        conn.close()
    return _interpret(row) if row else None


def ranking(task_category: str) -> list[dict]:
    """This category's leaderboard, best first, with `rank` assigned on read.

    Rank is derived rather than stored: a stored rank is a second copy of what
    the scores already say, and the copy is what goes stale. Ties break on the
    seeded order, so an ordering somebody chose deliberately survives until
    evidence separates the models."""
    _check_category(task_category)
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM model_performance WHERE task_category = ?",
            (task_category,)).fetchall()
    finally:
        conn.close()

    entries = sorted((_interpret(row) for row in rows),
                     key=lambda e: (-e["score"], e["seed_rank"], e["model_id"]))
    for position, item in enumerate(entries, start=1):
        item["rank"] = position
    return entries


def front_runner(task_category: str) -> dict | None:
    """The highest-ranked model on this leaderboard (§9), or None if nothing is
    seeded.

    **This is not model selection.** It answers "who is ahead at this task",
    which is one input to the question TQ-60 answers — that one also weighs
    privacy, hardware load, availability and budget, and §36 is explicit that
    sensitive work stays home no matter who is ahead here."""
    entries = ranking(task_category)
    return entries[0] if entries else None


def agent_view(model_id: str, task_category: str, agent_role: str) -> dict | None:
    """§8's agent-specific performance. None when this pairing has no history —
    an absence, never a zero, because "this agent has never used this model" and
    "it used it and got nothing right" are different facts."""
    _check_category(task_category)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM model_performance_by_agent "
            "WHERE model_id = ? AND task_category = ? AND agent_role = ?",
            (model_id, task_category, agent_role)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    n = row["sample_count"]
    return {
        "model_id": row["model_id"],
        "task_category": row["task_category"],
        "agent_role": row["agent_role"],
        "quality_score": round(row["quality_total"] / n, 4) if n else None,
        "failure_rate": round(row["failure_count"] / n, 4) if n else None,
        "sample_count": n,
        "last_updated": row["last_updated"],
    }


def leaderboards() -> dict:
    """Every category's ranking. What an operator reads, and what TQ-66's
    observability will chart."""
    return {category: ranking(category) for category in TASK_CATEGORIES}


def summary() -> dict:
    """Enough to answer "is this registry seeded, and is anything measured yet"
    without reading eight rankings."""
    boards = leaderboards()
    measured = sum(1 for entries in boards.values() for e in entries
                   if e["status"] == STATUS_MEASURED)
    return {
        "categories": len(boards),
        "seeded_categories": sum(1 for entries in boards.values() if entries),
        "models": sorted({e["model_id"] for entries in boards.values()
                          for e in entries}),
        "measured_entries": measured,
        "note": ("Every entry is SEEDED and provisional until outcomes land on it "
                 "(addendum 45 §12)." if measured == 0 else
                 f"{measured} entr(ies) carry measured evidence."),
    }


def export() -> str:
    """The whole registry as JSON, for a human reading it or a test asserting
    against it. Not a storage format — the database is."""
    return json.dumps(leaderboards(), indent=2, sort_keys=True)
