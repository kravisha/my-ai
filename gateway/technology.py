"""The Technology and Architecture function (addendum 17 §7-§9).

§7 asks for "a lightweight Technology and Architecture function" that
"periodically review[s] the health and suitability of the Project Jarvis
technical ecosystem" - and says twice what it is not: *"not intended to be a
high-frequency or heavyweight monitoring department"*, and *"the monitoring
function does NOT independently perform the migration"* (§9). It reviews, and it
raises structured recommendations. Somebody else decides, and somebody else
builds.

## Every check measures something that exists

The temptation in a function like this is to invent metrics - to produce a
dashboard of numbers that look like evidence because they are numbers. Each check
below reads something real off this machine or out of the running system, and a
check with nothing to read says so (`no_evidence`) rather than guessing.

That matters most for the case §9 uses as its worked example. SQLite versus
PostgreSQL is exactly the question a monitoring function is expected to answer
enthusiastically and wrongly. What this one does instead: report the concurrency
the substrate is actually carrying, report that **nothing in this system counts
SQLITE_BUSY**, and say plainly that suitability is asserted on the evidence
available rather than proven. The honest recommendation today is not to migrate,
and to instrument first if anybody wants a better answer than that.

## A verdict is not a severity

- `suitable` - the evidence says this component is doing its job.
- `watch` - something is trending, or a maintenance risk exists. Worth a decision
  eventually; not worth interrupting anybody.
- `unsuitable` - the evidence says this component is failing at its job.
- `no_evidence` - the question cannot be answered from what is recorded. Reported
  as loudly as any other verdict, because "we do not measure this" is the finding.

Only `watch` and `unsuitable` reach the Scoreboard. A board that filed an item
every time something was *fine* would bury the ones that are not.

## What it files, and why it cannot repeat itself

A finding that reaches the board carries §9's required shape: evidence, expected
future risk, candidate replacement, benefits, costs and tradeoffs, migration
implications, suggested priority. It also carries a stable `signature`, and an
open item with the same signature stops a second one being filed. A periodic
producer without that would repeat itself every interval until the board was
useless.

Resolved items do not suppress: a finding that was dealt with and has come back is
news again.
"""

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.db import Database
from gateway import jarvis, scoreboard, store

SOURCE = "technology-and-architecture"

REVIEW_INTERVAL_ENV = "GATEWAY_TECH_REVIEW_HOURS"
DEFAULT_REVIEW_INTERVAL_HOURS = 6

# A WAL this size means checkpointing is not keeping up with writes - the first
# real symptom of a SQLite deployment under more concurrent write pressure than it
# is being given room to absorb. Below it, WAL size says nothing.
WAL_WATCH_BYTES = 64 * 1024 * 1024

# SQLite itself is comfortable into the terabytes; this threshold is about
# operational handling - backup time, copy time, the size at which "just copy the
# file" stops being the recovery plan.
DATABASE_WATCH_BYTES = 2 * 1024 * 1024 * 1024

DISK_WATCH_FRACTION = 0.10

# Below this, a Python release is out of security support and the runtime becomes
# a maintenance risk rather than a preference.
MINIMUM_SUPPORTED_PYTHON = (3, 11)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def review_interval_hours() -> float:
    """How often the periodic review runs. Zero disables it entirely - §7's
    "not high-frequency" taken seriously enough to be switchable off."""
    raw = os.environ.get(REVIEW_INTERVAL_ENV, "").strip()
    if not raw:
        return DEFAULT_REVIEW_INTERVAL_HOURS
    try:
        hours = float(raw)
    except ValueError:
        return DEFAULT_REVIEW_INTERVAL_HOURS
    return max(hours, 0.0)


def _finding(
    key: str,
    component: str,
    verdict: str,
    summary: str,
    evidence: dict,
    recommendation: dict | None = None,
    importance: str = "informational",
) -> dict:
    return {
        "key": key,
        "component": component,
        "verdict": verdict,
        "summary": summary,
        "evidence": evidence,
        "recommendation": recommendation,
        "importance": importance,
    }


# --- The checks ---


def check_sqlite_concurrency(status: dict) -> dict:
    """§9's worked example, answered from what is actually recorded.

    The concurrency the substrate carries is observable - agent processes are
    registered and heartbeat. Contention is not: nothing in this system counts
    SQLITE_BUSY or times a blocked write. So the verdict rests on the first and
    says so about the second."""
    if not status.get("available"):
        return _finding(
            "sqlite_concurrency",
            "backend/fi_db.py (SQLite)",
            "no_evidence",
            "The backend is not reachable, so the coordination substrate cannot be reviewed.",
            {"backend": status.get("reason", "unavailable")},
        )

    agents = status.get("agents", [])
    running = [a for a in agents if a.get("process_state") == "running"]
    stale = [
        a["identity"]
        for a in running
        if (a.get("heartbeat_age_seconds") or 0) > 45  # HEALTH_STALE_THRESHOLD_SECONDS
    ]

    evidence = {
        "processes_sharing_the_database": len(running),
        "agents_with_a_stale_heartbeat": stale,
        "recorded_sqlite_busy_errors": None,
        "measurement_limit": (
            "Nothing in this system counts SQLITE_BUSY or times a blocked write, so the "
            "absence of contention is unmeasured rather than observed."
        ),
    }

    if stale:
        return _finding(
            "sqlite_concurrency",
            "backend/fi_db.py (SQLite)",
            "watch",
            f"{len(stale)} running agent(s) have a heartbeat older than the staleness threshold, "
            "which is consistent with - though not proof of - write pressure on the substrate.",
            evidence,
            recommendation={
                "candidate_replacement": "PostgreSQL, per addendum 17 §9",
                "benefits": "Concurrent writers without a single-writer lock.",
                "costs_and_tradeoffs": (
                    "A second service to run and back up, and every SQLite-specific "
                    "behaviour in backend/fi_db.py to re-verify - the archive trigger in "
                    "particular."
                ),
                "migration_implications": (
                    "backend/db.py exists precisely so a second Database implementation is "
                    "possible without touching call sites. That is the cheap part; the "
                    "trigger and the WAL-visibility assumptions are not."
                ),
                "expected_future_risk": "Stale heartbeats under load look like crashes to COO, "
                "which respawns - the duplicate-process failure this project has already met once.",
                "suggested_priority": "Investigate before migrating: instrument SQLITE_BUSY first.",
            },
            importance="important",
        )

    return _finding(
        "sqlite_concurrency",
        "backend/fi_db.py (SQLite)",
        "suitable",
        f"SQLite is carrying {len(running)} concurrent process(es) with no stale heartbeats. "
        "On the available evidence it remains suitable, and migrating would be a decision "
        "without a measurement behind it.",
        evidence,
        recommendation={
            "candidate_replacement": "None recommended.",
            "benefits": "n/a",
            "costs_and_tradeoffs": (
                "Migrating now would spend the cost of a second service and a re-verification "
                "of every SQLite-specific behaviour, to solve a problem nothing has observed."
            ),
            "migration_implications": "n/a",
            "expected_future_risk": (
                "The answer is only as good as the instrumentation. If this question matters, "
                "count SQLITE_BUSY and time blocked writes first - then the next review can "
                "answer it from evidence rather than from absence of evidence."
            ),
            "suggested_priority": "None. Revisit if instrumentation exists or agent count grows.",
        },
    )


def check_database_growth() -> dict:
    """Sizes and WAL health for both databases this system owns."""
    measurements = {}
    concerns = []
    for label, path in (
        ("financial_intelligence.db", PROJECT_ROOT / "financial_intelligence.db"),
        ("gateway.db", store.DB_PATH),
    ):
        wal = Path(str(path) + "-wal")
        size = path.stat().st_size if path.exists() else None
        wal_size = wal.stat().st_size if wal.exists() else None
        measurements[label] = {"bytes": size, "wal_bytes": wal_size}
        if size is not None and size > DATABASE_WATCH_BYTES:
            concerns.append(f"{label} is {size / 1e9:.1f} GB")
        if wal_size is not None and wal_size > WAL_WATCH_BYTES:
            concerns.append(f"{label}'s WAL is {wal_size / 1e6:.0f} MB, so checkpointing is behind")

    if concerns:
        return _finding(
            "database_growth",
            "SQLite databases",
            "watch",
            "; ".join(concerns) + ".",
            measurements,
            recommendation={
                "candidate_replacement": "None yet - size alone is not a reason to migrate.",
                "benefits": "n/a",
                "costs_and_tradeoffs": "n/a",
                "migration_implications": "n/a",
                "expected_future_risk": (
                    "A large WAL means readers hold checkpoints open; a large database means "
                    "copy-the-file recovery stops being practical."
                ),
                "suggested_priority": "Check backup and checkpoint behaviour before capacity.",
            },
        )

    return _finding(
        "database_growth",
        "SQLite databases",
        "suitable",
        "Both databases are within operational size, and neither WAL suggests checkpointing "
        "is behind.",
        measurements,
    )


def check_dependency_pinning() -> dict:
    """§8's "maintenance burden", measured rather than asserted: an unpinned
    requirement means the next clean install may not be the tested one."""
    requirements = PROJECT_ROOT / "requirements.txt"
    if not requirements.exists():
        return _finding(
            "dependency_pinning",
            "requirements.txt",
            "no_evidence",
            "No requirements.txt to review.",
            {},
        )

    declared = [
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    unpinned = [line for line in declared if not any(op in line for op in ("==", ">=", "<=", "~="))]

    evidence = {
        "declared": len(declared),
        "unpinned": unpinned,
        "python": sys.version.split()[0],
    }

    if not unpinned:
        return _finding(
            "dependency_pinning",
            "requirements.txt",
            "suitable",
            "Every declared dependency carries a version constraint.",
            evidence,
        )

    return _finding(
        "dependency_pinning",
        "requirements.txt",
        "watch",
        f"{len(unpinned)} of {len(declared)} dependencies are unpinned "
        f"({', '.join(unpinned)}), so a clean install is not guaranteed to reproduce the "
        "environment the test suite passed against.",
        evidence,
        recommendation={
            "candidate_replacement": "Version constraints in requirements.txt, or a lock file.",
            "benefits": (
                "A reproducible environment, and a dependency upgrade that arrives as a "
                "deliberate change with its own test run rather than as a surprise."
            ),
            "costs_and_tradeoffs": (
                "Pinned versions have to be raised deliberately, and stale pins are their own "
                "risk - the cost is a recurring upgrade task rather than a one-off."
            ),
            "migration_implications": (
                "Record the versions currently installed and passing, rather than the newest "
                "available: the point is to pin what was tested."
            ),
            "expected_future_risk": (
                "A breaking release lands on the next clean install - typically on a new "
                "machine, or in CI, where the cause is least obvious."
            ),
            "suggested_priority": "Low, and cheap. It costs one commit and removes a class of "
            "surprise entirely.",
        },
    )


def check_python_runtime() -> dict:
    version = sys.version_info
    evidence = {
        "python": f"{version.major}.{version.minor}.{version.micro}",
        "minimum_supported": ".".join(str(part) for part in MINIMUM_SUPPORTED_PYTHON),
    }
    if (version.major, version.minor) < MINIMUM_SUPPORTED_PYTHON:
        return _finding(
            "python_runtime",
            "Python runtime",
            "unsuitable",
            f"Python {evidence['python']} is below the supported minimum "
            f"{evidence['minimum_supported']} and no longer receives security fixes.",
            evidence,
            recommendation={
                "candidate_replacement": "A supported Python release.",
                "benefits": "Security fixes, and the language features the codebase already uses.",
                "costs_and_tradeoffs": "A re-created virtual environment and a full test run.",
                "migration_implications": "No code change expected; the suite is the check.",
                "expected_future_risk": "Unpatched runtime vulnerabilities.",
                "suggested_priority": "High.",
            },
            importance="important",
        )
    return _finding(
        "python_runtime",
        "Python runtime",
        "suitable",
        f"Python {evidence['python']} is supported.",
        evidence,
    )


def check_disk_headroom() -> dict:
    """§7's "capacity constraints", for the volume the databases live on."""
    usage = shutil.disk_usage(PROJECT_ROOT)
    free_fraction = usage.free / usage.total if usage.total else 0
    evidence = {
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "free_fraction": round(free_fraction, 4),
    }
    if free_fraction < DISK_WATCH_FRACTION:
        return _finding(
            "disk_headroom",
            "host volume",
            "watch",
            f"{free_fraction:.1%} of the volume holding the databases is free.",
            evidence,
            recommendation={
                "candidate_replacement": "None - this is capacity, not architecture.",
                "benefits": "n/a",
                "costs_and_tradeoffs": "n/a",
                "migration_implications": "n/a",
                "expected_future_risk": (
                    "SQLite fails writes when the volume fills, and an agent organization that "
                    "cannot write is an organization that cannot coordinate."
                ),
                "suggested_priority": "Free space or move the databases.",
            },
            importance="important",
        )
    return _finding(
        "disk_headroom",
        "host volume",
        "suitable",
        f"{free_fraction:.1%} of the volume is free.",
        evidence,
    )


def check_git_available() -> dict:
    """The Gateway's artifact exchange depends on a git binary being present -
    an external dependency §7 explicitly lists, and one that is invisible until
    a publish fails."""
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip() or result.stderr.strip()
        available = result.returncode == 0
    except (OSError, subprocess.SubprocessError) as missing:
        version = str(missing)
        available = False

    if available:
        return _finding("git_available", "git", "suitable", version, {"version": version})
    return _finding(
        "git_available",
        "git",
        "unsuitable",
        "No usable git binary, so the Gateway cannot read or publish project artifacts.",
        {"error": version},
        recommendation={
            "candidate_replacement": "Install git, or configure the Gateway without repositories.",
            "benefits": "Restores addendum 16 §14's artifact exchange.",
            "costs_and_tradeoffs": "None.",
            "migration_implications": "None.",
            "expected_future_risk": "Every publish fails at the moment it is needed.",
            "suggested_priority": "High - the capability is simply absent until fixed.",
        },
        importance="urgent",
    )


def review(status: dict | None = None) -> dict:
    """One full review. Read-only, and safe to run at any time."""
    if status is None:
        status = jarvis.JarvisClient().status()

    findings = [
        check_sqlite_concurrency(status),
        check_database_growth(),
        check_dependency_pinning(),
        check_python_runtime(),
        check_disk_headroom(),
        check_git_available(),
    ]
    return {
        "reviewed_at": _now(),
        "findings": findings,
        "counts": {
            verdict: sum(1 for f in findings if f["verdict"] == verdict)
            for verdict in ("suitable", "watch", "unsuitable", "no_evidence")
        },
    }


def _as_question(finding: dict) -> str:
    """A Scoreboard item's text: the finding, then §9's required fields, in the
    order §9 lists them. Written for a person to read six weeks later."""
    lines = [f"[{finding['component']}] {finding['summary']}", ""]
    lines.append("Evidence:")
    for key, value in finding["evidence"].items():
        lines.append(f"  - {key}: {value}")
    recommendation = finding.get("recommendation") or {}
    if recommendation:
        lines.append("")
        for label in (
            "expected_future_risk",
            "candidate_replacement",
            "benefits",
            "costs_and_tradeoffs",
            "migration_implications",
            "suggested_priority",
        ):
            if recommendation.get(label):
                lines.append(f"{label.replace('_', ' ').capitalize()}: {recommendation[label]}")
    lines.append("")
    lines.append(
        "Raised by the Technology and Architecture function (addendum 17 §7-§9), which "
        "reviews and recommends. It does not act."
    )
    return "\n".join(lines)


def review_and_file(db_path) -> tuple[dict, list[dict]]:
    """One periodic pass, entirely on the caller's thread.

    Takes a path rather than a connection for the reason `gateway/conversation.py`
    takes one: this runs in a worker thread, and sqlite3 connections belong to the
    thread that opened them. The first version of the periodic loop opened the
    connection on the event loop and handed it across, which raised
    `SQLite objects created in a thread can only be used in that same thread` on
    every pass - survivably, because the loop catches everything, and therefore
    invisibly. The whole function now crosses the thread boundary as one call."""
    report = review()
    conn = store.get_connection(db_path)
    try:
        return report, file_findings(conn, report)
    finally:
        conn.close()


def file_findings(conn: Database, report: dict) -> list[dict]:
    """File what needs a decision, and nothing else.

    Returns one record per filed item. A finding whose signature already has an
    open item is skipped - stated in the return value rather than silently, so a
    caller can tell "nothing wrong" from "already knew"."""
    filed = []
    for finding in report["findings"]:
        if finding["verdict"] not in ("watch", "unsuitable"):
            continue
        signature = f"tech:{finding['key']}"
        existing = scoreboard.open_item_with_signature(conn, signature)
        if existing is not None:
            filed.append({"key": finding["key"], "skipped": "already open", "item_id": existing["id"]})
            continue
        item_id = scoreboard.file_item(
            conn,
            source=SOURCE,
            question=_as_question(finding),
            importance=finding["importance"],
            blocking=False,
            related_spec="addendum 17 §7-§9",
            related_component=finding["component"],
            signature=signature,
        )
        filed.append({"key": finding["key"], "item_id": item_id})
    return filed
