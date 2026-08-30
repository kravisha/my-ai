"""What the station has to report, read out of the organization's own record
(docs/SPEC_RECONCILIATION.md §160).

The newsroom does not generate news. It reads the tables the organization already
writes during ordinary operation and turns rows into stories, each carrying the
table and row id it came from. That provenance is required by the schema, and the
reason is the one rule a newsroom cannot bend: **a story with no source is
something somebody made up.**

## The universe of events

The owner asked for a run covering *every event that could possibly happen in our
universe*. That universe is not a list somebody maintains - it is whatever the
organization records, so the catalogue below is one reader per event-producing
table. When the organization learns to do something new, it gets a reader here
and the station covers it; until then the station honestly has nothing to say
about it.

Ten kinds today:

    detection     something was noticed in the market
    discovery     a report was filed about it
    cross_check   one agent asked another and got an answer
    judgment      a report was graded
    incident      an agent failed and was recovered
    governance    an instrument was adopted, or a vote carried
    refusal       a rule refused work, attributed to the rule
    staffing      the organization changed its own population
    software      a database check opened an issue
    release       a governed change was applied or reversed

## Urgency is derived, never decided

`breaking` is not an editorial judgement here - it is what the record already
says is serious. An open incident is breaking because an agent is down; a
recovered one is notable because it is over. Deriving it means the newsroom cannot
manufacture drama, which is the failure mode a station reporting on its own
employer would have.
"""

from __future__ import annotations

from backend import broadcast, departments, sectors, trading
from backend.db import Database

KIND_DETECTION = "detection"
KIND_DISCOVERY = "discovery"
KIND_CROSS_CHECK = "cross_check"
KIND_JUDGMENT = "judgment"
KIND_INCIDENT = "incident"
KIND_GOVERNANCE = "governance"
KIND_REFUSAL = "refusal"
KIND_STAFFING = "staffing"
KIND_SOFTWARE = "software"
KIND_RELEASE = "release"
KIND_CURRICULUM = "curriculum"
KIND_STRATEGY = "strategy"
KIND_PERSONNEL = "personnel"
KIND_TRADE = "trade"
KIND_SECTOR = "sector"

# Which programme remit each kind feeds. A kind with no remit would be a story
# the schedule has nowhere to put, so the mapping is total by construction and a
# test asserts it.
REMIT_OF_KIND = {
    KIND_DETECTION: "detection",
    KIND_DISCOVERY: "discovery",
    KIND_CROSS_CHECK: "discovery",
    KIND_JUDGMENT: "judgment",
    KIND_GOVERNANCE: "governance",
    KIND_REFUSAL: "governance",
    KIND_INCIDENT: "operations",
    KIND_STAFFING: "operations",
    KIND_SOFTWARE: "operations",
    KIND_RELEASE: "governance",
    KIND_CURRICULUM: "curriculum",
    KIND_STRATEGY: "strategy",
    KIND_PERSONNEL: "personnel",
    KIND_TRADE: "trading",
    KIND_SECTOR: "sectors",
}

STORY_KINDS = tuple(REMIT_OF_KIND)


def _rows(conn: Database, sql: str, params: tuple = ()) -> list[dict]:
    """Read a table the station reports on, tolerating its absence.

    A database that predates a subsystem has no rows and no table for it, and the
    newsroom having nothing to say about a thing that does not exist here is the
    correct outcome rather than a crash mid-broadcast."""
    try:
        return conn.fetchall(sql, params)
    except Exception:  # noqa: BLE001 - an absent table is not a broadcast failure
        return []


def gather(conn: Database, day_id: str, *, limit_per_kind: int = 3) -> list[int]:
    """Read the organization and file what is worth reporting.

    Returns the ids of stories newly filed. Idempotent per source row, so running
    every cycle adds what is new rather than re-filing the day."""
    filed: list[int] = []

    def file(kind, headline, summary, table, source_id, urgency, subject=None):
        story = broadcast.file_story(
            conn, day_id=day_id, kind=kind, headline=headline, summary=summary,
            source_table=table, source_id=str(source_id), urgency=urgency,
            subject_identity=subject)
        if story is not None:
            filed.append(story)

    # -- detection ---------------------------------------------------------------
    for row in _rows(conn, "SELECT id, security, ratio, detector_type, producer_identity"
                           " FROM detector_events ORDER BY id DESC LIMIT ?", (limit_per_kind,)):
        file(KIND_DETECTION,
             f"Movement flagged in {row['security']}",
             f"The {row['detector_type']} detector recorded {row['security']} at a ratio of "
             f"{row['ratio']}. Raised by {row['producer_identity']}.",
             "detector_events", row["id"], broadcast.URGENCY_ROUTINE, row["producer_identity"])

    # -- discovery ---------------------------------------------------------------
    for row in _rows(conn, "SELECT id, security, producer_identity, report_type, summary"
                           " FROM discovery_reports_completed ORDER BY id DESC LIMIT ?",
                     (limit_per_kind,)):
        file(KIND_DISCOVERY,
             f"{row['producer_identity']} files on {row['security']}",
             (row["summary"] or f"A {row['report_type']} report on {row['security']}.").strip(),
             "discovery_reports_completed", row["id"], broadcast.URGENCY_ROUTINE,
             row["producer_identity"])

    # -- cross-check -------------------------------------------------------------
    for row in _rows(conn, "SELECT id, requester_identity, responder_role, security, outcome"
                           " FROM cross_check_requests WHERE outcome IS NOT NULL"
                           " ORDER BY id DESC LIMIT ?", (limit_per_kind,)):
        file(KIND_CROSS_CHECK,
             f"{row['requester_identity']} asks {row['responder_role']} on {row['security']}",
             f"The cross-check came back {row['outcome']}. The asker's own finding was "
             "on the record before the question was put.",
             "cross_check_requests", row["id"], broadcast.URGENCY_ROUTINE,
             row["requester_identity"])

    # -- judgment ----------------------------------------------------------------
    for row in _rows(conn, "SELECT id, grader_identity, overall_score, rationale"
                           " FROM grades ORDER BY id DESC LIMIT ?", (limit_per_kind,)):
        file(KIND_JUDGMENT,
             f"Report graded {row['overall_score']}",
             (row["rationale"] or "").strip()[:400] or "The grade carries its reasoning.",
             "grades", row["id"], broadcast.URGENCY_ROUTINE, row["grader_identity"])

    # -- incidents ---------------------------------------------------------------
    #
    # The only kind that reaches `breaking`, and it is breaking **on first
    # sight** rather than only while the incident is still open.
    #
    # Deriving it from the current status made the interruption a race: an agent
    # that went down and was recovered between two newsroom passes filed as
    # `notable` and never interrupted anything, so whether a failure was breaking
    # news depended on when the newsroom happened to look. An agent failing is
    # news when you first learn of it, and whether it has since recovered belongs
    # in the story rather than in the decision to run it.
    #
    # `file` refuses a second story from the same row, so this cannot re-break
    # the same incident on a later pass.
    for row in _rows(conn, "SELECT id, subject_identity, symptom, status, action"
                           " FROM incidents ORDER BY id DESC LIMIT ?", (limit_per_kind,)):
        still_down = row["status"] == "open"
        file(KIND_INCIDENT,
             f"{row['subject_identity']} went down",
             f"{row['symptom']}. " + (row["action"] or "") + (
                 " The Controller is acting on it." if still_down
                 else " Service has since been restored."),
             "incidents", row["id"], broadcast.URGENCY_BREAKING,
             row["subject_identity"])

    # -- governance --------------------------------------------------------------
    for row in _rows(conn, "SELECT id, subject, level, text FROM governed_items"
                           " WHERE superseded_at IS NULL ORDER BY id DESC LIMIT ?",
                     (limit_per_kind,)):
        file(KIND_GOVERNANCE,
             f"In force: {row['subject']}",
             f"A {row['level'].replace('_', ' ')} binding the organization. "
             + (row["text"] or "").strip()[:300],
             "governed_items", row["id"], broadcast.URGENCY_NOTABLE)

    for row in _rows(conn, "SELECT id, title, status FROM resolutions"
                           " ORDER BY id DESC LIMIT ?", (limit_per_kind,)):
        file(KIND_GOVERNANCE,
             f"Parliament: {row['title']}",
             f"The resolution stands {row['status']}.",
             "resolutions", row["id"], broadcast.URGENCY_NOTABLE)

    # -- refusals ----------------------------------------------------------------
    #
    # Counted and attributed to the instrument that caused them (§128). Zero filed
    # and ninety refused is a rule forbidding its own subject, and the station
    # reporting it is how that stops looking like a quiet market.
    for row in _rows(conn, "SELECT instrument_id, COUNT(*) AS n FROM governed_refusals"
                           " GROUP BY instrument_id ORDER BY n DESC LIMIT ?",
                     (limit_per_kind,)):
        file(KIND_REFUSAL,
             f"Instrument {row['instrument_id']} refused {row['n']} submissions",
             "A rule in force is turning work away. Refusals are attributed to the "
             "instrument that caused them, so a rule that forbids its own subject is "
             "distinguishable from a quiet day.",
             "governed_refusals", row["instrument_id"], broadcast.URGENCY_NOTABLE)

    # -- staffing ----------------------------------------------------------------
    for row in _rows(conn, "SELECT id, target_role, outcome, reason FROM coo_directives_completed"
                           " WHERE directive_type = 'spawn' ORDER BY id DESC LIMIT ?",
                     (limit_per_kind,)):
        file(KIND_STAFFING,
             f"The organization staffs {row['target_role']}",
             f"{(row['reason'] or 'A staffing decision').strip()} - {row['outcome']}.",
             "coo_directives_completed", row["id"], broadcast.URGENCY_ROUTINE)

    # -- software ----------------------------------------------------------------
    for row in _rows(conn, "SELECT id, component, observed, severity, status"
                           " FROM software_issues ORDER BY id DESC LIMIT ?", (limit_per_kind,)):
        file(KIND_SOFTWARE,
             f"Issue opened against {row['component']}",
             f"{row['observed']} Severity {row['severity']}; currently {row['status']}.",
             "software_issues", row["id"],
             broadcast.URGENCY_NOTABLE if row["severity"] in ("material", "critical")
             else broadcast.URGENCY_ROUTINE)

    # -- releases ----------------------------------------------------------------
    for row in _rows(conn, "SELECT id, name, status FROM releases ORDER BY id DESC LIMIT ?",
                     (limit_per_kind,)):
        file(KIND_RELEASE,
             f"Release '{row['name']}' is {row['status']}",
             "A named set of governed changes that stand or fall together, whose way "
             "back was authorized before the way forward was taken.",
             "releases", row["id"], broadcast.URGENCY_NOTABLE)

    # -- the departments ---------------------------------------------------------
    #
    # Read through each head's own summariser rather than by querying its tables
    # here, so the programme reports what the department would say about itself
    # and the two cannot drift into different accounts of the same records.
    for slug, kind in ((departments.EDUCATION, KIND_CURRICULUM),
                       (departments.STRATEGY, KIND_STRATEGY),
                       (departments.PERSONNEL, KIND_PERSONNEL)):
        for item in departments.summarise(conn, slug)[:limit_per_kind]:
            file(kind, item["headline"], item["summary"],
                 item["source_table"], item["source_id"], broadcast.URGENCY_ROUTINE)

    # -- the desk ------------------------------------------------------------------
    #
    # A trade the organization actually placed, and the attribution somebody
    # other than the trader recorded. Reported with the verdict rather than the
    # profit alone, because the specification asks the demo to expose the
    # evaluator's attribution and not merely the final number - a losing trade
    # attributed to a bad idea says something different about the desk than one
    # attributed to bad timing.
    for row in _rows(conn, "SELECT a.order_id, a.verdict, a.detail, a.pnl_vol_points,"
                           " o.security, o.side, o.placed_by FROM trader_attributions a"
                           " JOIN trader_orders o ON o.id = a.order_id"
                           " ORDER BY a.id DESC LIMIT ?", (limit_per_kind,)):
        file(KIND_TRADE,
             f"{row['security']}: {row['side']} closed {row['pnl_vol_points']:+.4f} vol points",
             f"{row['detail']} Verdict: {row['verdict'].replace('_', ' ')}. "
             "Vol points against a generated surface - a measure of the process, not money.",
             "trader_attributions", row["order_id"], broadcast.URGENCY_ROUTINE,
             row["placed_by"])

    for row in _rows(conn, "SELECT id, security, side, size, thesis, placed_by"
                           " FROM trader_orders WHERE status = 'open' ORDER BY id DESC LIMIT ?",
                     (limit_per_kind,)):
        file(KIND_TRADE,
             f"The desk is {row['side'].replace('_', ' ')} {row['size']} on {row['security']}",
             (row["thesis"] or "").strip()[:300] or "No thesis was recorded.",
             "trader_orders", row["id"], broadcast.URGENCY_ROUTINE, row["placed_by"])

    # -- overlooked sectors ---------------------------------------------------------
    #
    # The only programme that reports on a subject rather than on the
    # organization's own record, so the catalogue is what keeps it sourced: each
    # item is a row, and the standing of that row goes on air with it. These are
    # premises worth investigating and the summary says so, because a confident
    # sentence about an unexamined idea is how a station starts making claims its
    # organization cannot support.
    for row in _rows(conn, "SELECT id, name, field, premise, benefit, why_overlooked,"
                           " evidence_note FROM emerging_sectors ORDER BY id"):
        file(KIND_SECTOR,
             f"{row['name']} - {row['field']}",
             f"{row['premise']} {row['benefit']} Overlooked because: "
             f"{row['why_overlooked']} Standing: {row['evidence_note']} - this "
             "organization has not investigated it.",
             "emerging_sectors", row["id"], broadcast.URGENCY_ROUTINE)

    return filed


def breaking_stories(conn: Database, day_id: str) -> list[dict]:
    return broadcast.stories_for(conn, day_id, urgency=broadcast.URGENCY_BREAKING)


# A programme whose remit no story kind feeds can never air. `summary` is that
# case by design rather than by omission - Closing Bell recaps the day, so it is
# fed by what already went out instead of by a kind of its own.
REMIT_SUMMARY = "summary"


def stories_for_remit(conn: Database, day_id: str, remit: str) -> list[dict]:
    """Everything filed today that this programme's remit covers."""
    if remit == REMIT_SUMMARY:
        # The wrap: what actually aired today, in the order it aired. Reading
        # `aired` rather than `filed` is what makes this a recap instead of a
        # second first-run of stories nobody has heard yet.
        return broadcast.stories_for(conn, day_id, status=broadcast.STORY_AIRED)
    kinds = [kind for kind, mapped in REMIT_OF_KIND.items() if mapped == remit]
    out: list[dict] = []
    for kind in kinds:
        # Breaking stories are excluded: they belong to a news flash, and a
        # programme that also carried one would report the same event twice -
        # once as an interruption and once as a calm item in a later show.
        out.extend(s for s in broadcast.stories_for(conn, day_id, kind=kind)
                   if s["urgency"] != broadcast.URGENCY_BREAKING)
    return sorted(out, key=lambda s: s["id"])
