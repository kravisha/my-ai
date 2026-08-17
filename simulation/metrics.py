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
from datetime import datetime
from pathlib import Path

from backend import fi_db

FAMILIES = ("pipeline", "queue", "cross_check", "population", "intelligence", "resource")


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


def collect(db_path: str | Path) -> dict:
    conn = fi_db.get_connection(db_path)
    try:
        return collect_from(conn)
    finally:
        conn.close()


def collect_from(conn) -> dict:
    """Split out from `collect` so the derivations can be exercised against a
    constructed database rather than only against a completed run."""
    return {
        "pipeline": _pipeline(conn),
        "queue": _queue(conn),
        "cross_check": _cross_check(conn),
        "population": _population(conn),
        "intelligence": _intelligence(conn),
        "resource": _resource(conn),
    }


def _count(conn, table: str) -> int:
    return conn.fetchone(f"SELECT COUNT(*) AS n FROM {table}")["n"]


def _pipeline(conn) -> dict:
    reports_pending = _count(conn, "discovery_reports")
    reports_done = _count(conn, "discovery_reports_completed")

    by_producer = {
        row["producer_identity"]: row["n"]
        for row in conn.fetchall(
            "SELECT producer_identity, COUNT(*) AS n FROM ("
            "  SELECT producer_identity FROM discovery_reports"
            "  UNION ALL SELECT producer_identity FROM discovery_reports_completed"
            ") GROUP BY producer_identity"
        )
    }

    latencies = [
        _seconds(row["created_at"], row["completed_at"])
        for row in conn.fetchall("SELECT created_at, completed_at FROM discovery_reports_completed")
    ]

    return {
        "detector_events": _count(conn, "detector_events"),
        "evidence_items": _count(conn, "evidence_items"),
        "reports_filed": reports_pending + reports_done,
        "reports_completed": reports_done,
        "reports_by_producer": by_producer,
        "analyses": _count(conn, "analysis_results"),
        "grades": _count(conn, "grades"),
        # Every completed report should produce exactly one analysis and one
        # grade. A shortfall means work was consumed without being judged, which
        # no test would notice because each stage passes on its own.
        "unanalysed_completed_reports": reports_done - _count(conn, "analysis_results"),
        "ungraded_analyses": _count(conn, "analysis_results") - _count(conn, "grades"),
        "handling_latency_seconds": {
            "count": len(latencies),
            "p50": _percentile(latencies, 0.5),
            "p90": _percentile(latencies, 0.9),
            "max": round(max(latencies), 2) if latencies else None,
        },
    }


def _queue(conn) -> dict:
    """Arrival against drain, and the depth curve implied by the two."""
    arrivals = [
        row["created_at"]
        for row in conn.fetchall(
            "SELECT created_at FROM discovery_reports "
            "UNION ALL SELECT created_at FROM discovery_reports_completed"
        )
    ]
    completions = [
        row["completed_at"]
        for row in conn.fetchall("SELECT completed_at FROM discovery_reports_completed")
    ]

    if not arrivals:
        return {
            "arrivals": 0, "completions": 0, "final_depth": 0, "max_depth": 0,
            "drained": True, "arrival_interval_seconds": None,
            "drain_interval_seconds": None, "pressure_ratio": None,
            "oldest_pending_age_seconds": None,
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
        "final_depth": depth,
        "max_depth": max_depth,
        "drained": depth == 0,
        "arrival_interval_seconds": arrival_interval,
        "drain_interval_seconds": drain_interval,
        # Above 1.0 the queue grows without bound. This is the single number that
        # says whether the organization can keep up with itself.
        "pressure_ratio": (
            round(drain_interval / arrival_interval, 2)
            if arrival_interval and drain_interval else None
        ),
        "oldest_pending_age_seconds": oldest_pending_age,
    }


def _cross_check(conn) -> dict:
    outcomes = {
        str(row["outcome"]): row["n"]
        for row in conn.fetchall(
            "SELECT outcome, COUNT(*) AS n FROM cross_check_requests GROUP BY outcome"
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


def _population(conn) -> dict:
    rows = conn.fetchall(
        "SELECT identity, role, process_state, lifecycle_state FROM agent_registry"
    )
    spawns = {
        row["target_role"]: row["n"]
        for row in conn.fetchall(
            "SELECT target_role, COUNT(*) AS n FROM coo_directives_completed "
            "WHERE directive_type = 'spawn' GROUP BY target_role"
        )
    }
    return {
        "registered": len(rows),
        "roles": sorted({row["role"] for row in rows}),
        "running_at_end": sorted(r["identity"] for r in rows if r["process_state"] == "running"),
        "crashed": sorted(r["identity"] for r in rows if r["process_state"] == "crashed"),
        "dormant": sorted(r["identity"] for r in rows if r["lifecycle_state"] == "dormant"),
        "spawn_directives": spawns,
        # A role spawned more than once in a single run was either respawned
        # after a crash or - the defect that produced three concurrent processes
        # under one identity - respawned while still alive. Either way the
        # control run should show none.
        "respawns": sum(max(0, n - 1) for n in spawns.values()),
        "failed_directives": conn.fetchone(
            "SELECT COUNT(*) AS n FROM coo_directives_completed WHERE outcome = 'failure'"
        )["n"],
        "heartbeats": conn.fetchone(
            "SELECT COUNT(*) AS n FROM health_metrics WHERE metric = 'heartbeat'"
        )["n"],
    }


def _intelligence(conn) -> dict:
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
        "knowledge_records": _count(conn, "knowledge_records"),
    }


def _resource(conn) -> dict:
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
        "inferred_reasoning_calls": _count(conn, "analysis_results"),
        "inferred_uqi_calls": conn.fetchone(
            "SELECT COUNT(*) AS n FROM uqi_requests WHERE status = 'answered'"
        )["n"],
        "evidence_items_collected": _count(conn, "evidence_items"),
        "rows_written": sum(
            _count(conn, table)
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
