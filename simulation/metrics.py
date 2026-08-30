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

Eight families, chosen because each one is the direct observable of a defect class
this project has actually suffered:

    pipeline      work reached each stage at all
    queue         arrival against drain - a wrong timing constant shows here
    cross_check   the `unanswered` rate, which caught a timeout set too low
    population    respawns and survivors - duplicate and orphaned processes
    intelligence  lens bindings and staleness, with the stated reason
    resource      what the run consumed, honestly labelled as inferred
    incidents     whether the organization noticed its own failures
    governance    what bound this run, and whether the work carried its authority

Internal rationale: INT-PHIL-0018
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from backend import fi_db, status_events, strategy

FAMILIES = (
    "pipeline", "queue", "cross_check", "population", "intelligence", "resource", "incidents",
    # Added in §128. A family missing from this tuple is one a scenario cannot
    # discover and a test will not check the shape of - which is why the omission
    # failed the suite rather than passing quietly.
    "governance",
    # Added in §160. The station is a capability of the organization, so what it
    # did is read the same way everything else is - out of the run's own database.
    "broadcast",
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
        "population": {**_population(conn, since), **_slow_episodes(conn, since)},
        "intelligence": _intelligence(conn),
        "resource": _resource(conn, since),
        "incidents": _incidents(conn, since),
        "governance": _governance(conn, since),
        "broadcast": _broadcast(conn, since),
    }


def _one(conn, sql: str) -> int:
    """One COUNT, or zero. Used where the query is its own explanation and a
    named helper for each would be four lines of ceremony per number."""
    row = conn.fetchone(sql)
    return (row or {}).get("n", 0)


def _governance(conn, since: str | None = None) -> dict:
    """What governed this run, and whether anybody could tell.

    State rather than flow for the instruments themselves - an inherited
    instrument is genuinely part of the organization's present, the same
    reasoning `_intelligence` is unscoped for.

    **`work_ungoverned` is the number that matters here.** A run can have
    Articles, an instrument in force and a Speaker reporting cheerfully while
    every report is filed by a caller that named no filer - governed on paper and
    ungoverned in fact. Counting the work that carried no authority is the only
    way that shows up.
    """
    articles = conn.fetchone("SELECT MAX(version) AS v FROM articles")
    instruments = conn.fetchone(
        "SELECT COUNT(*) AS n FROM governed_items WHERE superseded_at IS NULL")
    escalations = conn.fetchone(
        "SELECT COUNT(*) AS n FROM owner_escalations WHERE decided_at IS NULL")
    speaker = conn.fetchall(
        "SELECT filed_at FROM speaker_reports ORDER BY id DESC LIMIT 1")
    speaker_count = _scoped_rows(
        conn, "SELECT COUNT(*) AS n FROM speaker_reports WHERE {bound}", "filed_at", since)
    looks = conn.fetchone(
        "SELECT COALESCE(SUM(reaffirmations), 0) + COUNT(*) AS n FROM speaker_reports")

    refused = _scoped_rows(
        conn, "SELECT COUNT(*) AS n FROM governed_refusals WHERE {bound}", "refused_at", since)
    refusing = conn.fetchall(
        "SELECT instrument_id, COUNT(*) AS n FROM governed_refusals"
        " GROUP BY instrument_id ORDER BY n DESC")

    # **Both tables.** A judged report leaves `discovery_reports` for the archive,
    # and counting only the pending one made governance coverage fall as work
    # completed: a run with eight governed reports read 8 while they waited and 0
    # once they were judged (§132).
    #
    # The archive carries `governed_by` precisely so this question survives
    # completion - §128 fixed the trigger to carry it and left this reading only
    # half the evidence, which is the same defect one step along.
    _BOTH = ("SELECT created_at, governed_by FROM ("
             " SELECT created_at, governed_by FROM discovery_reports"
             " UNION ALL"
             " SELECT created_at, governed_by FROM discovery_reports_completed"
             ") WHERE {bound}")
    governed_reports = _scoped_rows(
        conn, _BOTH + " AND governed_by IS NOT NULL", "created_at", since)
    all_reports = _scoped_rows(conn, _BOTH, "created_at", since)

    filed = len(all_reports)
    carried = len(governed_reports)
    return {
        "articles_version": (articles or {}).get("v"),
        "instruments_in_force": (instruments or {}).get("n", 0),
        "outstanding_owner_escalations": (escalations or {}).get("n", 0),
        "speaker_reports": speaker_count[0]["n"] if speaker_count else 0,
        "speaker_last_report_at": speaker[0]["filed_at"] if speaker else None,
        # How many times the Speaker looked, which is not how many rows it wrote.
        # An unchanged report is reaffirmed in place (§128), so rows count what
        # changed and this counts whether anybody is watching at all.
        "speaker_observations": (looks or {}).get("n", 0),
        "work_governed": carried,
        # Reports filed under no authority at all. Zero is the only good answer
        # once an instrument binds the producer; before that it is simply the
        # count of everything.
        "work_ungoverned": filed - carried,
        # Refusals by an instrument in force (TQ-90). Zero is the ordinary answer
        # and is not the interesting one - **a single instrument accounting for
        # every refusal is a rule that forbids its own subject**, which without
        # this number looks exactly like a quiet market.
        # Releases, so a run can assert that one actually applied and reversed
        # (TQ-96, §139). Counted from the release record rather than inferred
        # from instrument rows: an instrument reactivated by a rollback is
        # indistinguishable from one that was never displaced unless the release
        # that displaced it says so.
        "releases_applied": _one(
            conn, "SELECT COUNT(*) AS n FROM releases WHERE applied_at IS NOT NULL"),
        "releases_rolled_back": _one(
            conn, "SELECT COUNT(*) AS n FROM releases WHERE rolled_back_at IS NOT NULL"),
        # A release in force that nobody judged. Not a failure and not a pass -
        # the value this project writes where a plausible default would go.
        "releases_unjudged_in_force": _one(
            conn, "SELECT COUNT(*) AS n FROM releases WHERE status = 'released'"
                  " AND health = 'unknown'"),
        # Instruments a rollback took back out of force, kept rather than deleted
        # (addendum 46 §18). A rollback that reversed nothing would leave this at
        # zero while the release record claimed success.
        "instruments_reversed": _one(
            conn, "SELECT COUNT(*) AS n FROM release_changes WHERE reversed_at IS NOT NULL"),
        "refusals": refused[0]["n"] if refused else 0,
        "refusals_by_instrument": {row["instrument_id"]: row["n"] for row in refusing},
    }


def _slow_episodes(conn, since: str | None = None) -> dict:
    """Agents reported alive-but-not-advancing, and reported advancing again.

    Counted from `status_events` because that is where COO says it (§134), and
    exposed as a metric because **a scenario cannot assert on a condition it
    cannot see**. The first fully green verification passed `no agent was
    respawned` without the condition ever arising (§135), which is consistent
    with the fix working and with nothing having happened.

    These two numbers are what tell those apart."""
    reported = _scoped_rows(
        conn,
        "SELECT COUNT(*) AS n FROM status_events WHERE event_type = 'agent_slow'"
        " AND severity = ? AND {bound}", "timestamp", since,
        (status_events.SEVERITY_WARNING,))
    recovered = _scoped_rows(
        conn,
        "SELECT COUNT(*) AS n FROM status_events WHERE event_type = 'agent_slow'"
        " AND severity = ? AND {bound}", "timestamp", since,
        (status_events.SEVERITY_INFO,))
    return {
        "slow_reported": reported[0]["n"] if reported else 0,
        "slow_recovered": recovered[0]["n"] if recovered else 0,
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
    # Retired means JUDGED, not merely removed from the queue.
    #
    # A report that ends `failed` has left the queue and been analysed by nobody.
    # Counting it retired made `retirement_ratio` read 1.0 - perfect health -
    # during a run in which the model budget was exhausted and every single
    # report failed instantly (§132). The metric added at §128 to replace a
    # number that was anti-correlated with health was itself fooled by the first
    # real failure it met.
    #
    # `outcome` is the archived report's status: 'analyzed' or 'failed'.
    completions = [
        row["completed_at"]
        for row in _scoped_rows(
            conn,
            "SELECT completed_at FROM discovery_reports_completed"
            " WHERE outcome = 'analyzed' AND {bound}",
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
            "pressure_ratio": None, "retirement_ratio": None,
            "oldest_pending_age_seconds": None,
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
        # **Not the number it was believed to be, and kept only as a reading.**
        #
        # It was documented as "above 1.0 the queue grows without bound; the
        # single number that says whether the organization can keep up with
        # itself". A survey of every scenario showed it is anti-correlated with
        # the health it claims to measure (§128):
        #
        #     baseline_steady_state  90s   8 of 10 left pending   pressure 22.01
        #     developing_story      300s   2 of 10 left pending   pressure 34.08
        #
        # The healthier run reads worse. Both halves of the ratio move for
        # reasons unrelated to capacity: `has_pending_report` caps the backlog at
        # one report per producer per security, so arrivals come as a burst and
        # then stop, while a longer run lets completions spread out and raises
        # the drain interval.
        #
        # `retirement_ratio` below answers the question this was asked to answer.
        # Nothing asserts on this one any more, and `saturation.yaml`'s reasoning
        # about saturation-versus-growth is why: it cannot tell those apart.
        "pressure_ratio": (
            round(drain_interval / arrival_interval, 2)
            if arrival_interval and drain_interval else None
        ),
        # How much of what arrived was retired. Burst-insensitive, monotonic in
        # the thing actually worried about, and comparable between runs of the
        # same length: 0.2 over ninety seconds, 0.8 over three hundred.
        #
        # Below 1.0 the queue grew during the run. That is not by itself a fault
        # - a run that ends mid-cycle leaves work in flight - which is why the
        # scenarios assert a floor rather than 1.0.
        "retirement_ratio": (
            round(len(completions) / len(arrivals), 2) if arrivals else None
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
    # RE-AIMED at TQ-92 (§149). This read `status = 'open'`, and the cross-check
    # status vocabulary is `pending` | `resolved` | `consumed` - `'open'` has never
    # been one of them. So `open_at_end` was **structurally always zero**, and
    # `baseline_steady_state`'s property *"no cross-check was left open: 0 == 0"*
    # has been asserting a tautology.
    #
    # Second instance in two days of the same shape (§147 was the first): not a
    # tripwire aimed where the risk used to be, but one aimed where the answer
    # cannot be anything else. A literal spelled into a query has no compiler to
    # catch it, which is why the constant is used here.
    open_requests = conn.fetchone(
        "SELECT COUNT(*) AS n FROM cross_check_requests WHERE status = ?",
        (fi_db.CROSS_CHECK_PENDING,),
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
        # Per role, because the total cannot answer a question about one role.
        # `saturation_two_judges` asserted "two judgment agents were staffed" as
        # `registered at_least 7` - true of the baseline population without any
        # judgment agent at all once the Speaker and the DBA joined it, so the
        # property passed with zero and could no longer fail (§157).
        #
        # **Zero-filled across every known role**, which is not the plausible
        # default §100 forbids: the registry is the complete list of registered
        # agents, so a role absent from it genuinely has none. Leaving it absent
        # would make a property about that role fail with "no metric at ..."
        # rather than "0 >= 2" - still a failure, and one that reads as a broken
        # scenario instead of the staffing failure it is.
        "registered_by_role": {
            role: 0 for role in fi_db.ROLE_CHARTERS
        } | dict(Counter(row["role"] for row in rows)),
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


def _broadcast(conn, since: str | None = None) -> dict:
    """What the television station did.

    Stage 2's question is *did every expected kind of action happen* - not
    whether it happened well - so these count kinds of occurrence rather than
    scoring anything. A `dropped` segment and a `substituted` guest are counted
    beside the ones that went to plan, because philosophy §11 is explicit that a
    fallback firing may show the system is *more* complete, and a metric that
    hid them would make the fallback paths unobservable."""
    segments = _rows_or_empty(conn, "SELECT kind, status FROM run_of_show")
    appearances = _rows_or_empty(
        conn, "SELECT outcome, substitute_for FROM appearances")
    stories = _rows_or_empty(conn, "SELECT kind, urgency, status FROM stories")
    scripts = _rows_or_empty(conn, "SELECT provisional FROM scripts")
    ads = _rows_or_empty(conn, "SELECT status FROM ad_slots")
    days = _rows_or_empty(conn, "SELECT status, anchor_identity FROM broadcast_days")
    presenters = {d["anchor_identity"] for d in days if d["anchor_identity"]}
    enquiries = _rows_or_empty(
        conn, "SELECT id FROM uqi_requests WHERE asked_by LIKE 'anchor-%'")
    resumed = _rows_or_empty(
        conn, "SELECT id FROM run_of_show WHERE resumed_at IS NOT NULL")

    def count(rows, field, value):
        return sum(1 for r in rows if r[field] == value)

    aired = [r for r in segments if r["status"] == "aired"]
    return {
        "days_opened": len(days),
        "days_closed": count(days, "status", "closed"),
        "segments_aired": len(aired),
        "programmes_aired": sum(1 for r in aired if r["kind"] == "programme"),
        "news_flashes_aired": sum(1 for r in aired if r["kind"] == "news_flash"),
        "ad_breaks_aired": sum(1 for r in aired if r["kind"] == "ad_break"),
        "signed_off": sum(1 for r in aired if r["kind"] == "sign_off"),
        # Fallbacks, counted as first-class outcomes rather than as errors.
        "segments_dropped": count(segments, "status", "dropped"),
        "segments_interrupted": count(segments, "status", "interrupted"),
        "segments_resumed": len(resumed),
        "scripts_prepared": len(scripts),
        "guests_appeared": count(appearances, "outcome", "appeared"),
        "guests_substituted": count(appearances, "outcome", "substituted"),
        "guests_unavailable": count(appearances, "outcome", "unavailable"),
        "stories_filed": len(stories),
        "stories_aired": count(stories, "status", "aired"),
        "story_kinds": sorted({r["kind"] for r in stories}),
        "breaking_stories": count(stories, "urgency", "breaking"),
        "ad_slots": len(ads),
        "ad_slots_unsold": count(ads, "status", "unsold"),
        # The separation the Dedicated Anchor specification exists for. A day
        # presented by the COO is the fallback working; a day presented *only* by
        # the COO across every run would be the coupling back again, which is why
        # this reports who rather than how many.
        "presenters": sorted(presenters),
        "presented_by_anchor": sorted(p for p in presenters if p.startswith("anchor-")),
        "presented_by_fallback": sorted(p for p in presenters if not p.startswith("anchor-")),
        # §10.8: the Anchor could ask for more when the brief was not enough.
        "anchor_enquiries": len(enquiries),
    }


def _rows_or_empty(conn, sql: str, params: tuple = ()) -> list[dict]:
    """A database written before the station existed has none of its tables, and
    reporting nothing about a subsystem that is not there is the correct answer
    rather than a collection failure."""
    try:
        return conn.fetchall(sql, params)
    except Exception:  # noqa: BLE001
        return []


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
        "strategies_active": conn.fetchone(
            "SELECT COUNT(*) AS n FROM strategies WHERE status = 'active'"
        )["n"],
        # The unhealthy join (active strategy, inactive knowledge) is logic
        # that must not be duplicated here in raw SQL - strategy.unhealthy is
        # the one place it lives. metrics.py is simulation-side, above
        # backend/, and already imports fi_db for the same reason this file's
        # raw-SQL style exists (deriving numbers from tables the organization
        # already writes) - importing strategy for the one query that is not
        # "raw SQL by design" is the same kind of import, not a new layer.
        "strategies_unhealthy": len(strategy.unhealthy(conn)),
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
