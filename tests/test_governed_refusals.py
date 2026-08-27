"""Refusals by an instrument in force are written down (TQ-90;
docs/SPEC_RECONCILIATION.md §130).

Until this existed a refusal was said on stdout and kept nowhere. The single
refusal was never the problem. **A badly drafted instrument that refuses
everything looks exactly like a quiet market** — discovery goes silent, the queue
stays empty, every property about crashes and orphans passes, and the
organization reports excellent health while producing nothing because it forbade
itself.

Two numbers tell that apart from calm and one cannot: what was filed, and what
was refused.
"""

from __future__ import annotations

import inspect

import pytest

from agents import speaker
from backend import (fi_db, governed_knowledge as governed,
                     operating_context as context, parliament, portfolios, register)
from simulation import metrics

OWNER = portfolios.for_superuser("krish")
ROLL = {"broad": ["coo", "explorer", "speculator", "analysis", "speaker"],
        "representative": ["coo", "analysis"]}


@pytest.fixture
def governed_conn(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    return conn


def _enact(conn, level="organization_policy", title="A resolution") -> int:
    resolution = parliament.propose(conn, title=title, rationale="r",
                                    proposed_by="coo", affects=level)
    tier = parliament.get_resolution(conn, resolution)["tier"]
    for voter in ROLL["representative" if tier == parliament.TIER_REPRESENTATIVE else "broad"]:
        parliament.cast_vote(conn, resolution, voter=voter, value="for")
    parliament.close(conn, resolution)
    return resolution


def _instrument(conn, *, fields=("summary",), subject=None) -> int:
    return governed.adopt(
        conn, subject=subject or fi_db.REPORT_SUBJECT, level="organization_policy",
        text="A rule.", adopted_by="coo", resolution_id=_enact(conn, title=f"r{fields}"),
        binds="*", requires={"kind": "required_fields", "fields": list(fields)})


# --- the record ---------------------------------------------------------------------

def test_a_refusal_is_written_down_with_who_what_and_which_rule(governed_conn):
    item = _instrument(governed_conn)
    context.check(governed_conn, "speculator", fi_db.REPORT_SUBJECT, {})

    recorded = context.refusals(governed_conn)
    assert len(recorded) == 1
    assert recorded[0]["role"] == "speculator"
    assert recorded[0]["subject"] == fi_db.REPORT_SUBJECT
    assert recorded[0]["instrument_id"] == item
    assert recorded[0]["unmet"] == ["summary"]


def test_a_submission_that_complies_records_nothing(governed_conn):
    """A refusal table that filled up with successes would be a log, and nobody
    would read it for the thing it exists to show."""
    _instrument(governed_conn)
    context.check(governed_conn, "speculator", fi_db.REPORT_SUBJECT, {"summary": "a lead"})
    assert context.refusals(governed_conn) == []


def test_the_record_carries_field_names_and_never_their_values(governed_conn):
    """A submission's field NAMES are the organization's own vocabulary. Its
    field CONTENTS are whatever somebody was filing, and a register entry can
    carry anything. Recording names lets the organization diagnose its refusals;
    recording values would put arbitrary content in a table nobody would think to
    look in for it."""
    _instrument(governed_conn, fields=("provenance",))
    context.check(governed_conn, "explorer", fi_db.REPORT_SUBJECT,
                  {"summary": "SECRET-CONTENT-12345", "security": "SYN9"})

    stored = governed_conn.fetchall("SELECT * FROM governed_refusals")
    written = " ".join(str(value) for row in stored for value in row.values())
    assert "provenance" in written
    assert "SECRET-CONTENT-12345" not in written
    assert "SYN9" not in written


def test_refusals_are_attributed_to_the_instrument_that_caused_them(governed_conn):
    """The shape a reader needs. A single instrument accounting for every refusal
    in the organization is a rule that forbids its own subject, not a workforce
    behaving badly."""
    strict = _instrument(governed_conn, fields=("provenance",))
    _instrument(governed_conn, fields=("note",), subject=register.SUBMISSION_SUBJECT)

    for _ in range(3):
        context.check(governed_conn, "explorer", fi_db.REPORT_SUBJECT, {})
    context.check(governed_conn, "coo", register.SUBMISSION_SUBJECT, {})

    by_instrument = context.refusals_by_instrument(governed_conn)
    assert by_instrument[strict] == 3
    assert sum(by_instrument.values()) == 4


def test_the_check_records_rather_than_its_callers(governed_conn):
    """Impure on purpose. A check that noticed a breach and left writing it down
    to whoever called it is how an organization ends up unable to count its own
    refusals — and a new call site would inherit the enforcement and not the
    record."""
    source = inspect.getsource(context.check)
    assert "record_refusal(" in source
    for caller in (inspect.getsource(fi_db.enqueue_report),
                   inspect.getsource(register.file_entry)):
        assert "record_refusal" not in caller


def test_a_real_filing_refused_by_a_real_rule_leaves_a_record(governed_conn):
    """End to end through the path an agent actually uses."""
    _instrument(governed_conn, fields=("provenance",))
    with pytest.raises(fi_db.GovernedRefusal):
        fi_db.enqueue_report(governed_conn, "speculator-1", "2026-01-01T00:00:00+00:00",
                             "speculator", "SYN1", summary="A lead.",
                             evidence_ids=[1], filed_by="speculator")
    assert len(context.refusals(governed_conn)) == 1


# --- and it is visible ---------------------------------------------------------------

def test_the_metric_counts_refusals_and_names_the_instrument(governed_conn):
    item = _instrument(governed_conn, fields=("provenance",))
    for _ in range(2):
        context.check(governed_conn, "explorer", fi_db.REPORT_SUBJECT, {})

    governance = metrics.collect_from(governed_conn)["governance"]
    assert governance["refusals"] == 2
    assert governance["refusals_by_instrument"] == {item: 2}


def test_zero_filed_and_zero_refused_is_a_different_state_from_zero_filed_and_many(governed_conn):
    """The whole point, as one assertion. One number cannot tell a quiet market
    from a rule that forbids its own subject, and two can."""
    quiet = metrics.collect_from(governed_conn)["governance"]
    assert quiet["work_governed"] == 0 and quiet["refusals"] == 0

    _instrument(governed_conn, fields=("provenance",))
    for _ in range(3):
        context.check(governed_conn, "explorer", fi_db.REPORT_SUBJECT, {})

    forbidden = metrics.collect_from(governed_conn)["governance"]
    assert forbidden["work_governed"] == 0 and forbidden["refusals"] == 3


def test_the_speaker_reports_what_the_rules_have_refused(governed_conn):
    """Governance in action rather than governance on paper, and the Speaker is
    where governance speaks (§124). Refusals counted and never mentioned would be
    half a fix."""
    item = _instrument(governed_conn, fields=("provenance",))
    for _ in range(2):
        context.check(governed_conn, "explorer", fi_db.REPORT_SUBJECT, {})

    report = speaker.compose_report(governed_conn)
    assert report["refusals_by_instrument"] == {item: 2}
    assert "refused 2 submission(s)" in report["says"]
    assert f"instrument {item}" in report["says"]


def test_the_speaker_invents_no_threshold_for_too_many(governed_conn):
    """What counts as too many refusals depends on what the instrument is for. A
    number nobody measured would be a policy wearing a measurement's clothes —
    the discipline `TIMING_CONSTANTS.md` keeps for every other rate."""
    source = inspect.getsource(speaker._say)
    for invented in ("> 10", ">= 10", "> 5", ">= 5", "0.5", "too many"):
        assert invented not in source


def test_governance_coverage_survives_a_report_being_judged(governed_conn):
    """A judged report leaves `discovery_reports` for the archive.

    Counting only the pending table made governance coverage FALL as work
    completed: a run with eight governed reports read 8 while they waited and 0
    once they were judged (§132). §128 fixed the archive trigger to carry
    `governed_by` precisely so the question would survive completion, and left
    the metric reading half the evidence — the same defect one step along."""
    _instrument(governed_conn)
    report = fi_db.enqueue_report(
        governed_conn, "speculator-1", "2026-01-01T00:00:00+00:00", "speculator", "SYN1",
        summary="A lead.", evidence_ids=[1], filed_by="speculator")

    before = metrics.collect_from(governed_conn)["governance"]
    assert before["work_governed"] == 1 and before["work_ungoverned"] == 0

    governed_conn.execute(
        "UPDATE discovery_reports SET status = 'analyzed' WHERE id = ?", (report,))

    after = metrics.collect_from(governed_conn)["governance"]
    assert after["work_governed"] == 1, "judging a report did not make it ungoverned"
    assert after["work_ungoverned"] == 0
