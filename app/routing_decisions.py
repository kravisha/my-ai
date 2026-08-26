"""Every routing decision, and what became of it (TASK_QUEUE TQ-55,
docs/SPEC_RECONCILIATION.md §106).

Source: addendum 45 §24 (the decision flow), §25 (task-step routing), §26 (the
record), §32 (the self-improvement loop), §41 (routing error types),
§45 Phase A.

## Written from the first decision, not once there is traffic worth analysing

A log that starts late has a hole in it exactly where the early mistakes are.
This exists before anything routes, so the first routing decision this system
ever makes is recorded like every later one.

## It shares a database with the leaderboards, on purpose

`model_performance.db` holds both. They are two steps of one loop (§32: record
the route → record the result → score it → update the registry), and the
alternative is worse in a specific way: the outcome fields in §26 —
`quality_score`, `failure_type`, `validation_result` — are the *same facts* that
feed `model_performance.record_outcome`. Two databases would mean either writing
them twice, which is two sources of truth for one fact, or joining across files.

So `complete()` is the single write path: it closes the log entry **and** scores
the leaderboard, in that order. There is no way to score an outcome without
logging the decision that produced it, and no way to close a decision without
scoring it. The log is written first and survives a scoring failure, because the
record of what happened matters more than the tally.

## The signature is stored once

§26 lists `task_signature` *and* `task_category`, `complexity`, `risk_level` and
`privacy_level` — four fields the signature already contains. Storing them
alongside it would be four more places to disagree.

They are derived on read instead. `task_category` is the one exception: it is
denormalised into a real column because TQ-66's observability groups by it and
JSON extraction is a poor index. **The caller never supplies it** — it is
extracted from the signature at write time, so there is no path by which the
column and the signature could differ.

`risk_level` is §26's third name for a fact this codebase already calls
`criticality` (`model_registry.yaml`) and `error_cost` (`task_signature`). §104
tied the first two; this reads the third off the signature rather than adding a
column, so there is still one vocabulary.

## One field §26 does not name, and why it is here anyway

`execution_path` — deterministic, local, or external (§2's hierarchy).

§26 has `deterministic_possible` and `local_sufficient`, which record what the
*decision* concluded, and `selected_model`, which records what was chosen. None
of them records which of the three ways the work was actually done, and §41's
error types cannot be computed without it: `UNDER_ESCALATION`,
`OVER_ESCALATION` and `UNNECESSARY_AI` are all statements about the path taken
versus the path that should have been.

## It detects §36 violations; it does not prevent them

The first end-to-end run of this module routed a `LOCAL_ONLY` step to an
external model, and nothing said a word — the log recorded it faithfully and no
reader would ever have looked. So `privacy_violation` is derived on read and
counted in `summary()`, from facts the row already holds.

**Detection, never refusal.** Enforcement is TQ-60's. Once it exists, a
violation can only reach this table through a bug or a bypass — and a log that
refused to record those would hide precisely what it exists to reveal.

## What cannot be answered yet, and is not pretended

`was_escalation_worthwhile` is the field this whole lineage exists to be able to
answer, and **nothing can answer it today**. It requires a counterfactual — what
would have happened had the work stayed local — and the first thing that produces
one is TQ-63's challenger mode, which runs both and compares.

So it is three-valued and defaults to `unknown`, which is a recorded fact rather
than a gap. A boolean defaulting to false would have quietly asserted that every
escalation was wasted.

`estimated_cost`, `actual_cost` and `resource_usage` are nullable and nothing
fills them: §37's cost model is TQ-65's and hardware monitoring is TQ-57's. That
is a different judgement from §105's, where always-NULL *score* columns were left
out entirely — a score participates in arithmetic that changes shape when a
dimension arrives, whereas a log field is inert. And a log is the one artifact
that must not need migrating later, because migrating a log means rewriting
history.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone

from app import model_performance
from app.task_signature import (PRIVACY_LOCAL_ONLY, TaskSignature,
                                UnknownVocabulary)

SCHEMA_VERSION = 1

# --- closed vocabularies ------------------------------------------------------------
#
# Fail-closed on read as well as write, the rule every other vocabulary in this
# codebase works under.

# §2's execution hierarchy: "Use the least expensive and least resource-intensive
# method that can meet the required quality and reliability threshold."
PATH_DETERMINISTIC = "deterministic"
PATH_LOCAL = "local"
PATH_EXTERNAL = "external"
EXECUTION_PATHS = (PATH_DETERMINISTIC, PATH_LOCAL, PATH_EXTERNAL)

# §38: "Before penalizing a model, validate where possible." So "nobody checked"
# is its own answer and never collapses into "passed".
VALIDATION_PASSED = "passed"
VALIDATION_FAILED = "failed"
VALIDATION_NOT_VALIDATED = "not_validated"
VALIDATION_RESULTS = (VALIDATION_PASSED, VALIDATION_FAILED, VALIDATION_NOT_VALIDATED)

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_REFUSED = "refused"
STATUS_ABANDONED = "abandoned"
FINAL_STATUSES = (STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED, STATUS_REFUSED,
                  STATUS_ABANDONED)

# The three-valued answer to §26's `was_escalation_worthwhile`. `unknown` is the
# default and will stay the only honest value until TQ-63 produces a
# counterfactual to compare against.
WORTH_YES = "yes"
WORTH_NO = "no"
WORTH_UNKNOWN = "unknown"
WORTHWHILE = (WORTH_YES, WORTH_NO, WORTH_UNKNOWN)

_FIELDS = (
    "routing_decision_id", "agent_id", "task_id", "task_step_id", "decided_at",
    "task_signature", "task_category", "execution_path", "deterministic_possible",
    "local_sufficient", "selected_model", "selected_provider",
    "leaderboard_rank_at_selection", "reason_for_selection", "confidence",
    "estimated_cost", "actual_cost", "estimated_latency_ms", "actual_latency_ms",
    "resource_usage", "validation_result", "quality_score", "failure_type",
    "was_escalation_worthwhile", "final_status", "completed_at", "schema_version",
)


class DecisionRefused(ValueError):
    """A decision this module will not record, with the reason."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(value, vocabulary: tuple[str, ...], field: str):
    if value not in vocabulary:
        raise UnknownVocabulary(
            f"unknown {field} {value!r}; known are {list(vocabulary)}")
    return value


def _connect() -> sqlite3.Connection:
    """The same file the leaderboards live in - see the module docstring for
    why one database rather than two."""
    conn = sqlite3.connect(model_performance.database_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS routing_decisions ("
        "  routing_decision_id TEXT PRIMARY KEY,"
        "  agent_id TEXT,"
        "  task_id TEXT,"
        "  task_step_id TEXT,"
        "  decided_at TEXT NOT NULL,"
        # The signature as stored JSON, and the source of truth for category,
        # complexity, risk and privacy. Read back through
        # TaskSignature.from_dict, which validates on the way in (§104).
        "  task_signature TEXT NOT NULL,"
        # Denormalised from the signature by this module, never by a caller -
        # TQ-66 groups by it and JSON extraction is a poor index.
        "  task_category TEXT NOT NULL,"
        "  execution_path TEXT NOT NULL,"
        "  deterministic_possible INTEGER,"
        "  local_sufficient INTEGER,"
        "  selected_model TEXT,"
        "  selected_provider TEXT,"
        "  leaderboard_rank_at_selection INTEGER,"
        "  reason_for_selection TEXT NOT NULL,"
        "  confidence REAL,"
        "  estimated_cost REAL,"
        "  actual_cost REAL,"
        "  estimated_latency_ms REAL,"
        "  actual_latency_ms REAL,"
        "  resource_usage TEXT,"
        "  validation_result TEXT,"
        "  quality_score REAL,"
        "  failure_type TEXT,"
        "  was_escalation_worthwhile TEXT NOT NULL DEFAULT 'unknown',"
        "  final_status TEXT NOT NULL DEFAULT 'pending',"
        "  completed_at TEXT,"
        "  schema_version INTEGER NOT NULL DEFAULT 1"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS routing_decisions_by_category "
        "ON routing_decisions (task_category, decided_at)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS routing_decisions_by_task "
        "ON routing_decisions (task_id, task_step_id)")
    return conn


def record_decision(signature: TaskSignature, *, reason: str, execution_path: str,
                    selected_model: str | None = None,
                    selected_provider: str | None = None,
                    leaderboard_rank: int | None = None,
                    agent_id: str | None = None,
                    task_id: str | None = None,
                    task_step_id: str | None = None,
                    deterministic_possible: bool | None = None,
                    local_sufficient: bool | None = None,
                    confidence: float | None = None,
                    estimated_cost: float | None = None,
                    estimated_latency_ms: float | None = None) -> str:
    """Log one routing decision at the moment it is made. Returns its id.

    `reason` is required and must say something: §26 asks for
    `reason_for_selection`, and a decision recorded without one is a row that
    tells a later reader *what* was chosen and nothing about *why* — which is
    the half that makes the log worth keeping when a routing mistake is being
    diagnosed.

    A `task_step_id` records that this decision was made for one step of a
    larger task (§25). The same `task_id` with several step ids is exactly the
    portfolio-analysis example §25 gives: parse deterministically, interpret
    locally, resolve the hard part externally."""
    if not isinstance(signature, TaskSignature):
        raise DecisionRefused(
            "a routing decision is recorded against a TaskSignature, not a dict. "
            "Build one first - it validates the vocabulary (§104).")
    _check(execution_path, EXECUTION_PATHS, "execution path")
    if not (reason or "").strip():
        raise DecisionRefused(
            "a routing decision needs a reason. A row that says what was chosen "
            "and not why is not worth the space when somebody is diagnosing a "
            "routing mistake.")
    if execution_path == PATH_DETERMINISTIC and selected_model:
        raise DecisionRefused(
            f"execution_path is {PATH_DETERMINISTIC!r} but a model was selected "
            f"({selected_model!r}). §19's whole point is that deterministic work "
            "uses no model.")
    if execution_path != PATH_DETERMINISTIC and not selected_model:
        raise DecisionRefused(
            f"execution_path is {execution_path!r} but no model was selected. A "
            "model path with no model is a decision nobody can audit.")

    decision_id = f"rd-{secrets.token_hex(16)}"
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO routing_decisions ("
            " routing_decision_id, agent_id, task_id, task_step_id, decided_at,"
            " task_signature, task_category, execution_path, deterministic_possible,"
            " local_sufficient, selected_model, selected_provider,"
            " leaderboard_rank_at_selection, reason_for_selection, confidence,"
            " estimated_cost, estimated_latency_ms, was_escalation_worthwhile,"
            " final_status, schema_version"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (decision_id, agent_id, task_id, task_step_id, _now(),
             json.dumps(signature.as_dict(), sort_keys=True),
             signature.task_category, execution_path,
             None if deterministic_possible is None else int(deterministic_possible),
             None if local_sufficient is None else int(local_sufficient),
             selected_model, selected_provider, leaderboard_rank,
             reason.strip(), confidence, estimated_cost, estimated_latency_ms,
             WORTH_UNKNOWN, STATUS_PENDING, SCHEMA_VERSION))
        conn.commit()
    finally:
        conn.close()
    return decision_id


def complete(decision_id: str, *, final_status: str,
             validation_result: str = VALIDATION_NOT_VALIDATED,
             quality_score: float | None = None,
             failure_type: str | None = None,
             actual_cost: float | None = None,
             actual_latency_ms: float | None = None,
             resource_usage: dict | None = None,
             was_escalation_worthwhile: str = WORTH_UNKNOWN,
             latency_acceptable: bool | None = None,
             score_leaderboard: bool = True) -> dict:
    """Close a decision with what happened, and score the leaderboard from it.

    **The single write path** for an outcome (§32). The log entry is closed
    first and the leaderboard scored second, so a scoring failure leaves the
    record of what happened intact — the log matters more than the tally, and a
    tally can be rebuilt from a log while the reverse is not true.

    `score_leaderboard=False` exists for one honest case: a decision whose model
    has no leaderboard entry, which happens in tests and would otherwise be a
    hard error. It is not a way to keep an inconvenient result out of the
    rankings, and nothing in production should pass it."""
    _check(final_status, FINAL_STATUSES, "final status")
    _check(validation_result, VALIDATION_RESULTS, "validation result")
    _check(was_escalation_worthwhile, WORTHWHILE, "escalation worthwhile")
    if quality_score is not None and not 0.0 <= quality_score <= 1.0:
        raise DecisionRefused(f"quality_score must be within 0..1, got {quality_score}")

    existing = get(decision_id)
    if existing is None:
        raise LookupError(f"no routing decision {decision_id!r}")
    if existing["final_status"] != STATUS_PENDING:
        raise DecisionRefused(
            f"{decision_id!r} is already {existing['final_status']!r}. A decision is "
            "closed once - re-closing it would rewrite history and double-count the "
            "outcome against the leaderboard.")

    conn = _connect()
    try:
        conn.execute(
            "UPDATE routing_decisions SET"
            "  validation_result = ?, quality_score = ?, failure_type = ?,"
            "  actual_cost = ?, actual_latency_ms = ?, resource_usage = ?,"
            "  was_escalation_worthwhile = ?, final_status = ?, completed_at = ? "
            "WHERE routing_decision_id = ?",
            (validation_result, quality_score, failure_type, actual_cost,
             actual_latency_ms,
             None if resource_usage is None else json.dumps(resource_usage, sort_keys=True),
             was_escalation_worthwhile, final_status, _now(), decision_id))
        conn.commit()
    finally:
        conn.close()

    # Then the tally. §11 holds through here too: the outcome lands on the
    # category this decision was made for and no other.
    if score_leaderboard and existing["selected_model"]:
        model_performance.record_outcome(
            existing["selected_model"], existing["task_category"],
            model_performance.Outcome(
                succeeded=final_status == STATUS_COMPLETED,
                quality=quality_score,
                latency_ms=actual_latency_ms,
                latency_acceptable=latency_acceptable,
                failure_type=failure_type,
                agent_role=existing["signature"].agent_role))
    return get(decision_id)


def _interpret(row) -> dict:
    """One stored decision, with §26's duplicated fields derived from the
    signature rather than read from columns that could disagree with it."""
    signature = TaskSignature.from_dict(json.loads(row["task_signature"]))
    if signature.task_category != row["task_category"]:
        raise UnknownVocabulary(
            f"stored decision {row['routing_decision_id']!r} has task_category "
            f"{row['task_category']!r} but a signature saying "
            f"{signature.task_category!r}. Refusing to guess which is true.")
    _check(row["execution_path"], EXECUTION_PATHS, "execution path")
    _check(row["final_status"], FINAL_STATUSES, "final status")
    _check(row["was_escalation_worthwhile"], WORTHWHILE, "escalation worthwhile")
    if row["validation_result"] is not None:
        _check(row["validation_result"], VALIDATION_RESULTS, "validation result")

    decision = {key: row[key] for key in _FIELDS if key != "task_signature"}
    decision["signature"] = signature
    # §26's four duplicates, derived rather than stored.
    decision["complexity"] = signature.complexity
    decision["privacy_level"] = signature.privacy_level
    decision["risk_level"] = signature.error_cost
    for boolean in ("deterministic_possible", "local_sufficient"):
        decision[boolean] = (None if row[boolean] is None else bool(row[boolean]))
    decision["resource_usage"] = (None if row["resource_usage"] is None
                                  else json.loads(row["resource_usage"]))
    # §41's PRIVACY_MISROUTING, detected from what the row already holds.
    #
    # Found by running this module rather than by reasoning about it: the first
    # end-to-end exercise routed a LOCAL_ONLY step to an external model and
    # nothing said a word (§106). The log recorded it perfectly and no reader
    # would ever have looked.
    #
    # Detection, never refusal. **The log must record reality including its
    # violations** - once TQ-60 enforces privacy, a violation can only reach
    # this table through a bug or a bypass, and a log that refused to record
    # those is a log that hides exactly what it exists to reveal.
    decision["privacy_violation"] = (
        decision["execution_path"] == PATH_EXTERNAL
        and signature.privacy_level == PRIVACY_LOCAL_ONLY)
    return decision


def get(decision_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM routing_decisions WHERE routing_decision_id = ?",
            (decision_id,)).fetchone()
    finally:
        conn.close()
    return _interpret(row) if row else None


def recent(limit: int = 50, task_category: str | None = None) -> list[dict]:
    conn = _connect()
    try:
        if task_category:
            rows = conn.execute(
                "SELECT * FROM routing_decisions WHERE task_category = ? "
                "ORDER BY decided_at DESC, routing_decision_id DESC LIMIT ?",
                (task_category, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM routing_decisions "
                "ORDER BY decided_at DESC, routing_decision_id DESC LIMIT ?",
                (limit,)).fetchall()
    finally:
        conn.close()
    return [_interpret(row) for row in rows]


def for_task(task_id: str) -> list[dict]:
    """Every decision made for one task, oldest first (§25).

    A task routed as a whole has one row; a task routed per step has several,
    which is §25's portfolio-analysis example: parse deterministically,
    interpret locally, resolve the hard part externally, summarize locally."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM routing_decisions WHERE task_id = ? "
            "ORDER BY decided_at, routing_decision_id", (task_id,)).fetchall()
    finally:
        conn.close()
    return [_interpret(row) for row in rows]


def summary() -> dict:
    """Enough to answer "what has this system been doing" without reading the
    log. The shape TQ-66's observability builds on, not that observability
    itself: §40's metrics and §41's error types need a comparison against what
    *should* have happened, and nothing here knows that."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT execution_path, final_status, COUNT(*) AS n "
            "FROM routing_decisions GROUP BY execution_path, final_status").fetchall()
        total = conn.execute("SELECT COUNT(*) AS n FROM routing_decisions").fetchone()["n"]
        unanswered = conn.execute(
            "SELECT COUNT(*) AS n FROM routing_decisions "
            "WHERE was_escalation_worthwhile = ?", (WORTH_UNKNOWN,)).fetchone()["n"]
        # Cheap because both facts are already in the row; surfaced here so a
        # violation is a number somebody sees rather than one they would have to
        # go looking for (§41's PRIVACY_MISROUTING).
        violations = conn.execute(
            "SELECT COUNT(*) AS n FROM routing_decisions "
            "WHERE execution_path = ? AND task_signature LIKE ?",
            (PATH_EXTERNAL, f'%"privacy_level": "{PRIVACY_LOCAL_ONLY}"%')).fetchone()["n"]
    finally:
        conn.close()

    by_path: dict[str, dict[str, int]] = {}
    for row in rows:
        by_path.setdefault(row["execution_path"], {})[row["final_status"]] = row["n"]
    return {
        "decisions": total,
        "by_path": by_path,
        "privacy_violations": violations,
        "privacy_note": (
            "LOCAL_ONLY work that went to an external model (§36, §41's "
            "PRIVACY_MISROUTING). Detected here, not prevented - prevention is "
            "TQ-60's. A non-zero count is a defect, not a statistic."
        ) if violations else None,
        "escalation_worth_unknown": unanswered,
        "note": ("`was_escalation_worthwhile` needs a counterfactual - what would have "
                 "happened locally - and nothing produces one until TQ-63's challenger "
                 "mode. Until then `unknown` is the honest answer, not a gap."),
    }
