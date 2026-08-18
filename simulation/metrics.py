"""What a run did, read back out of the run's own database.

Read-only, and adds no instrumentation anywhere. Every number here is derived
from tables the organization already writes during ordinary operation, which is
what keeps a simulated run identical to a real one - an organization that
behaves differently because it is being measured is not the organization.

The queue depth series is reconstructed rather than sampled. Reports carry a
`created_at`, and completed ones carry a `completed_at`, so depth at any instant
is the number created by then minus the number completed by then. Polling for it
would have needed a writer inside the run and would have recorded the depth at
the sampling instants rather than the depth.

Six families, chosen because each one is the direct observable of a defect class
this project has actually suffered:

    pipeline      work reached each stage at all
    queue         arrival against drain - a wrong timing constant shows here
    cross_check   the `unanswered` rate, which caught a timeout set too low
    population    respawns and survivors - duplicate and orphaned processes
    intelligence  lens bindings and staleness, with the stated reason
    resource      what the run consumed, honestly labelled as inferred

Internal rationale: INT-PHIL-0018
"""

from __future__ import annotations

import json
from pathlib import Path

from backend import fi_db

FAMILIES = (
    "pipeline", "queue", "cross_check", "population", "intelligence", "resource", "incidents",
)


def _seconds(earlier: str, later: str) -> float:
    return (fi_db.parse_timestamp(later) - fi_db.parse_timestamp(earlier)).total_seconds()


def _percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank, because these samples are counted in single digits.

    Interpolating between two of four observations would present a number no
    observation supports."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return round(ordered[index], 2)


def collect(db_path: str | Path, since: str | None = None) -> dict:
    conn = fi_db.get_connection(db_path)
    try:
        return collect_from(conn, since)
    finally:
        conn.close()


def collect_from(conn, since: str | None = None) -> dict:
    """Split out from `collect` so the derivations can be exercised against a
    constructed database rather than only against a completed run.

    **`since` is what makes a metric describe a run rather than a lineage.**
    A run that inherits another run's database inherits its rows too, and
    without a boundary every flow measure reports the accumulated history of
    every generation. That is not a subtle distortion: chained runs reported
    four respawns and then eight, when each generation had spawned its baseline
    exactly once and nothing had been respawned at all. Two property failures,
    neither of them real.

    Flow families - what happened - are scoped. State families - what is true
    now, like which lenses are stale or who is registered - are not, because
    inherited state is genuinely part of the organization's present."""
    return {
        "pipeline": _pipeline(conn, since),
        "queue": _queue(conn, since),
        "cross_check": _cross_check(conn, since),
        "population": _population(conn, since),
        "intelligence": _intelligence(conn),
        "resource": _resource(conn, since),
        "incidents": _incidents(conn, since),
    }


def _incidents(conn, since: str | None = None) -> dict:
    """What the organization noticed about its own failures.

    A flow family, scoped like the others: incidents are things that happened
    during a run, and an inherited database's old failures are not this run's.

    This exists because the Fault Tolerance Framework's §15 asks for fault
    simulations whose purpose "is not merely to prove that processes restart" but
    to prove the organization notices, assigns responsibility, recovers and
    learns. None of that is observable unless detection itself is measured -
    `recovered` is the organization fixing itself, and `escalated` is it correctly
    admitting that it cannot."""
    rows = _scoped_rows(
        conn,
        "SELECT status, COUNT(*) AS n FROM incidents WHERE {bound} GROUP BY status",
        "detected_at", since,
    )
    counts = {row["status"]: row["n"] for row in rows}
    return {
        "open": counts.get("open", 0),
        "recovered": counts.get("recovered", 0),
        "escalated": counts.get("escalated", 0),
        "total": sum(counts.values()),
        "subjects": sorted({
            row["subject_identity"]
            for row in _scoped_rows(
                conn,
                "SELECT subject_identity FROM incidents WHERE {bound}",
                "detected_at", since,
            )
        }),
    }


def _scoped_count(conn, table: str, column: str, since: str | None) -> int:
    if since is None:
        return conn.fetchone(f"SELECT COUNT(*) AS n FROM {table}")["n"]
    return conn.fetchone(
        f"SELECT COUNT(*) AS n FROM {table} WHERE {column} >= ?", (since,)
    )["n"]


def _scoped_rows(conn, sql: str, column: str, since: str | None, params: tuple = ()) -> list:
    """Append a time bound to a query, or run it unbounded.

    The caller supplies a query ending in a WHERE clause of its own or none at
    all; `1=1` keeps both shapes valid without two versions of every statement."""
    if since is None:
        return conn.fetchall(sql.replace("{bound}", "1=1"), params)
    return conn.fetchall(sql.replace("{bound}", f"{column} >= ?"), params + (since,))


def _pipeline(conn, since: str | None = None) -> dict:
    """Work filed and retired during this run.

    Arrivals are scoped by when a report was created; completions by when it was
    *completed*, not created. A report inherited from an earlier generation and
    retired during this one is work this run did, and counting it by creation
    would credit it to a run that never touched it."""
    reports_filed = (
        _scoped_count(conn, "discovery_reports", "created_at", since)
        + _scoped_count(conn, "discovery_reports_completed", "created_at", since)
    )
    reports_done = _scoped_count(conn, "discovery_reports_completed", "completed_at", since)
    analyses = _scoped_count(conn, "analysis_results", "created_at", since)
    grades = _scoped_count(conn, "grades", "created_at", since)

    by_producer = {
        row["producer_identity"]: row["n"]
        for row in _scoped_rows(
            conn,
            "SELECT producer_identity, COUNT(*) AS n FROM ("
            "  SELECT producer_identity, created_at FROM discovery_reports"
            "  UNION ALL SELECT producer_identity, created_at FROM discovery_reports_completed"
            ") WHERE {bound} GROUP BY producer_identity",
            "created_at", since,
        )
    }

    latencies = [
        _seconds(row["created_at"], row["completed_at"])
        for row in _scoped_rows(
            conn,
            "SELECT created_at, completed_at FROM discovery_reports_completed WHERE {bound}",
            "completed_at", since,
        )
    ]

    return {
        "detector_events": _scoped_count(conn, "detector_events", "created_at", since),
        "evidence_items": _scoped_count(conn, "evidence_items", "created_at", since),
        "reports_filed": reports_filed,
        "reports_completed": reports_done,
        "reports_by_producer": by_producer,
        "analyses": analyses,
        "grades": grades,
        # Every completed report should produce exactly one analysis and one
        # grade. A shortfall means work was consumed without being judged, which
        # no test would notice because each stage passes on its own.
        "unanalysed_completed_reports": reports_done - analyses,
        "ungraded_analyses": analyses - grades,
        "handling_latency_seconds": {
            "count": len(latencies),
            "p50": _percentile(latencies, 0.5),
            "p90": _percentile(latencies, 0.9),
            "max": round(max(latencies), 2) if latencies else None,
        },
    }


def _queue(conn, since: str | None = None) -> dict:
    """Arrival against drain, and the depth curve implied by the two.

    `inherited_backlog` is reported separately because a run that starts behind
    is a different situation from one that falls behind, and a single depth
    number cannot tell the two apart."""
    arrivals = [
        row["created_at"]
        for row in _scoped_rows(
            conn,
            "SELECT created_at FROM ("
            "  SELECT created_at FROM discovery_reports"
            "  UNION ALL SELECT created_at FROM discovery_reports_completed"
            ") WHERE {bound}",
            "created_at", since,
        )
    ]
    completions = [
        row["completed_at"]
        for row in _scoped_rows(
            conn,
            "SELECT completed_at FROM discovery_reports_completed WHERE {bound}",
            "completed_at", since,
        )
    ]

    inherited = 0
    if since is not None:
        inherited = conn.fetchone(
            "SELECT COUNT(*) AS n FROM discovery_reports WHERE created_at < ?", (since,)
        )["n"]

    pending_now = conn.fetchone("SELECT COUNT(*) AS n FROM discovery_reports")["n"]

    if not arrivals:
        return {
            "arrivals": 0, "completions": len(completions), "net_depth_change": 0,
            "max_depth": 0, "drained": pending_now == 0,
            "arrival_interval_seconds": None, "drain_interval_seconds": None,
            "pressure_ratio": None, "oldest_pending_age_seconds": None,
            "inherited_backlog": inherited, "pending_at_end": pending_now,
        }

    events = [(fi_db.parse_timestamp(t), +1) for t in arrivals]
    events += [(fi_db.parse_timestamp(t), -1) for t in completions]
    # Completions sort before arrivals at an identical instant, so a tie cannot
    # invent a depth of one that never existed. The delta itself is the tie-break
    # because -1 sorts before +1; negating it here reads more natural and is
    # wrong, which is how this was first written.
    events.sort(key=lambda pair: (pair[0], pair[1]))

    depth = 0
    max_depth = 0
    for _, delta in events:
        depth += delta
        max_depth = max(max_depth, depth)

    span = _seconds(min(arrivals), max(arrivals)) or None
    arrival_interval = round(span / (len(arrivals) - 1), 2) if span and len(arrivals) > 1 else None

    drain_span = _seconds(min(completions), max(completions)) if len(completions) > 1 else None
    drain_interval = round(drain_span / (len(completions) - 1), 2) if drain_span else None

    pending = conn.fetchall("SELECT created_at FROM discovery_reports")
    oldest_pending_age = (
        round(_seconds(min(row["created_at"] for row in pending), max(arrivals + completions)), 2)
        if pending else None
    )

    return {
        "arrivals": len(arrivals),
        "completions": len(completions),
        # The NET CHANGE this run made to the queue, not the queue's size. A run
        # that retired exactly as many as it filed nets zero while leaving an
        # inherited backlog untouched, so `drained` is answered from what is
        # actually pending - it read True over ten waiting reports before this
        # was separated.
        "net_depth_change": depth,
        "max_depth": max_depth,
        "drained": pending_now == 0,
        "arrival_interval_seconds": arrival_interval,
        "drain_interval_seconds": drain_interval,
        # Above 1.0 the queue grows without bound. This is the single number that
        # says whether the organization can keep up with itself.
        "pressure_ratio": (
            round(drain_interval / arrival_interval, 2)
            if arrival_interval and drain_interval else None
        ),
        "oldest_pending_age_seconds": oldest_pending_age,
        # Work this run began already owing, and everything still owed at the
        # end regardless of which generation filed it.
        "inherited_backlog": inherited,
        "pending_at_end": pending_now,
    }


def _cross_check(conn, since: str | None = None) -> dict:
    outcomes = {
        str(row["outcome"]): row["n"]
        for row in _scoped_rows(
            conn,
            "SELECT outcome, COUNT(*) AS n FROM cross_check_requests WHERE {bound} GROUP BY outcome",
            "created_at", since,
        )
    }
    total = sum(outcomes.values())
    unanswered = outcomes.get("unanswered", 0)
    open_requests = conn.fetchone(
        "SELECT COUNT(*) AS n FROM cross_check_requests WHERE status = 'open'"
    )["n"]
    return {
        "total": total,
        "outcomes": outcomes,
        "open_at_end": open_requests,
        # The diagnostic that caught a timeout constant set below the real answer
        # time. A rise here without a corresponding rise in load means a
        # threshold has drifted out of step with the system it governs.
        "unanswered_rate": round(unanswered / total, 3) if total else None,
    }


def _population(conn, since: str | None = None) -> dict:
    """Registry state is current and unscoped; spawn activity is this run's.

    Mixing the two is what made a chained run report eight respawns having
    respawned nothing: the registry is rightly cumulative, and the directives
    are rightly not."""
    rows = conn.fetchall(
        "SELECT identity, role, process_state, lifecycle_state FROM agent_registry"
    )
    spawns = {
        row["target_role"]: row["n"]
        for row in _scoped_rows(
            conn,
            "SELECT target_role, COUNT(*) AS n FROM coo_directives_completed "
            "WHERE directive_type = 'spawn' AND {bound} GROUP BY target_role",
            "completed_at", since,
        )
    }
    # Counted per identity, not per role. A role staffed with two agents takes
    # two spawns to establish, and counting spawns-beyond-the-first per *role*
    # reported that as a respawn - which it flagged the moment judgment was
    # first staffed with two agents. A respawn is the same slot being filled
    # twice, which is exactly what a per-identity count says.
    per_identity = _scoped_rows(
        conn,
        "SELECT detail, COUNT(*) AS n FROM coo_directives_completed "
        "WHERE directive_type = 'spawn' AND outcome = 'success' AND detail IS NOT NULL "
        "AND {bound} GROUP BY detail",
        "completed_at", since,
    )
    return {
        "registered": len(rows),
        "roles": sorted({row["role"] for row in rows}),
        "running_at_end": sorted(r["identity"] for r in rows if r["process_state"] == "running"),
        "crashed": sorted(r["identity"] for r in rows if r["process_state"] == "crashed"),
        "dormant": sorted(r["identity"] for r in rows if r["lifecycle_state"] == "dormant"),
        "spawn_directives": spawns,
        # A slot filled more than once *within one run* was either refilled
        # after a crash or - the defect that produced three concurrent processes
        # under one identity - refilled while still alive. Establishing the
        # baseline is normal and must not count here, however many slots it takes.
        "respawns": sum(max(0, row["n"] - 1) for row in per_identity),
        "lifetime_spawns": conn.fetchone(
            "SELECT COUNT(*) AS n FROM coo_directives_completed WHERE directive_type = 'spawn'"
        )["n"],
        "failed_directives": len(_scoped_rows(
            conn,
            "SELECT id FROM coo_directives_completed WHERE outcome = 'failure' AND {bound}",
            "completed_at", since,
        )),
        "heartbeats": _scoped_count(conn, "health_metrics", "timestamp", since),
    }


def _intelligence(conn) -> dict:
    """Current state, never scoped.

    A lens that went stale in an earlier generation is still stale now, and
    scoping this would report a healthy organization by forgetting."""
    artifacts = conn.fetchall(
        "SELECT name, status, staleness_reason, validity_conditions FROM intelligence_artifacts"
    )
    bound = []
    for row in artifacts:
        try:
            conditions = json.loads(row["validity_conditions"] or "{}")
        except json.JSONDecodeError:
            continue
        if (conditions.get("regime") or {}).get("observed_under"):
            bound.append(row["name"])

    regimes = conn.fetchall(
        "SELECT security, mean_iv, iv_dispersion, observation_count FROM market_regime"
    )
    return {
        "artifacts": len(artifacts),
        "active": sum(1 for row in artifacts if row["status"] == "active"),
        "stale": sum(1 for row in artifacts if row["status"] == "stale"),
        "regime_bound": sorted(bound),
        "staleness_reasons": [row["staleness_reason"] for row in artifacts if row["staleness_reason"]],
        "securities_observed": len(regimes),
        "regime_observations": sum(row["observation_count"] for row in regimes),
        "knowledge_records": conn.fetchone("SELECT COUNT(*) AS n FROM knowledge_records")["n"],
    }


def _resource(conn, since: str | None = None) -> dict:
    """What the run consumed.

    **Nothing meters model usage**, so the counts below are inferred from work
    products - one reasoning call per analysis, one per answered operator
    question - and `metered` says so. An inferred number presented as a measured
    one would be worse than none, because it would be budgeted against.

    `unit` is carried per the proposal's requirement not to hard-code tokens as
    the permanent economic unit; when real metering exists it changes the unit,
    not the shape."""
    return {
        "metered": False,
        "unit": "model_call",
        "inferred_reasoning_calls": _scoped_count(conn, "analysis_results", "created_at", since),
        "inferred_uqi_calls": conn.fetchone(
            "SELECT COUNT(*) AS n FROM uqi_requests WHERE status = 'answered' "
            "AND (? IS NULL OR created_at >= ?)", (since, since),
        )["n"],
        "evidence_items_collected": _scoped_count(conn, "evidence_items", "created_at", since),
        "rows_written": sum(
            _scoped_count(conn, table, "created_at", since)
            for table in ("detector_events", "evidence_items", "analysis_results", "grades")
        ),
    }


def lookup(metrics: dict, path: str):
    """Resolve a dotted metric path, raising rather than returning None if absent.

    A scenario naming a metric that does not exist must fail loudly. Returning
    None would let a typo produce a property that quietly asserts nothing while
    still reporting as covered - which is the failure the whole subsystem exists
    to stop repeating."""
    current = metrics
    walked: list[str] = []
    for part in path.split("."):
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            available = sorted(current) if isinstance(current, dict) else []
            raise KeyError(
                f"no metric at {'.'.join(walked)!r}; available at that level: {available}"
            )
        current = current[part]
    return current
