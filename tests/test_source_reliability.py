"""Tests for source reliability (constitution §3, Axiom 3: "no authority is
automatically correct").

Two properties carry the design, and both are about what the model refuses to
do: it never assigns a standing a source has not earned, and it never lets a
poor standing suppress the evidence that would let the source change it.
"""

import json

import pytest

from backend import fi_db


def _graded_evidence(conn, source, evidence_quality, overall=0.5, security="SYN1"):
    """One evidence item from `source`, escalated into a report and graded."""
    evidence_id = fi_db.record_evidence_item(
        conn, "speculator-1", "T", "social", security, source=source, content="x", confidence=0.8,
    )
    report_id = fi_db.enqueue_report(
        conn, "speculator-1", "T", "speculator", security, evidence_ids=[evidence_id],
    )
    fi_db.complete_report(conn, report_id, "analyzed",
                          handled_by_identity="analysis-1", handled_by_spawned_at="T")
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "T", report_id, security,
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    fi_db.record_grade(
        conn, "analysis-1", "T", report_id, result_id,
        relevance_score=overall, novelty_score=overall,
        evidence_quality_score=evidence_quality, worth_the_compute=overall > 0.5,
        overall_score=overall, rationale="r",
    )
    return evidence_id


def test_no_source_starts_with_a_standing(conn):
    """Seeding "filings are trustworthy, forums are not" would assert exactly
    the authority Axiom 3 denies - and would make the model untestable, since
    it would then be reporting its own seed back."""
    assert fi_db.list_source_reliability(conn) == []
    assert fi_db.source_standing(conn, "filing_feed") is None


def test_reliability_is_earned_from_how_reports_were_graded(conn):
    for _ in range(6):
        _graded_evidence(conn, "filing_feed", evidence_quality=0.9)
        _graded_evidence(conn, "pump_channel", evidence_quality=0.1)

    fi_db.recompute_source_reliability(conn)

    standings = {s["source"]: s for s in fi_db.list_source_reliability(conn)}
    assert standings["filing_feed"]["mean_evidence_quality"] == pytest.approx(0.9)
    assert standings["pump_channel"]["mean_evidence_quality"] == pytest.approx(0.1)
    assert standings["filing_feed"]["stated"] and standings["pump_channel"]["stated"]


def test_a_source_below_the_evidence_threshold_has_no_stated_standing(conn):
    """"We do not know yet" is a different answer from "this source is
    unreliable". A confident number computed from two samples would be worse
    than no number, because it would be believed."""
    for _ in range(fi_db.MIN_GRADED_CONTRIBUTIONS - 1):
        _graded_evidence(conn, "reddit", evidence_quality=0.2)

    fi_db.recompute_source_reliability(conn)

    standing = fi_db.source_standing(conn, "reddit")
    assert standing["stated"] is False
    assert standing["graded_contributions"] == fi_db.MIN_GRADED_CONTRIBUTIONS - 1


def test_an_unstated_source_is_listed_rather_than_hidden(conn):
    """Hiding it would make "not yet judged" indistinguishable from "no such
    source", and an operator could not tell the model was still learning."""
    _graded_evidence(conn, "reddit", evidence_quality=0.2)
    fi_db.recompute_source_reliability(conn)
    assert [s["source"] for s in fi_db.list_source_reliability(conn)] == ["reddit"]


def test_a_standing_changes_when_the_record_changes(conn):
    """Reliability is "represented probabilistically and changing over time"
    (constitution §3) - a source that improves must be able to recover."""
    for _ in range(6):
        _graded_evidence(conn, "reddit", evidence_quality=0.1)
    fi_db.recompute_source_reliability(conn)
    assert fi_db.source_standing(conn, "reddit")["mean_evidence_quality"] == pytest.approx(0.1)

    for _ in range(18):
        _graded_evidence(conn, "reddit", evidence_quality=0.9)
    fi_db.recompute_source_reliability(conn)

    assert fi_db.source_standing(conn, "reddit")["mean_evidence_quality"] > 0.6


def test_recomputing_is_idempotent(conn):
    """The standing is a claim about a source's whole record, so computing it
    twice from the same record must give the same answer - that is what
    recomputing buys over folding updates in incrementally."""
    for _ in range(6):
        _graded_evidence(conn, "filing_feed", evidence_quality=0.8)

    fi_db.recompute_source_reliability(conn)
    first = fi_db.source_standing(conn, "filing_feed")
    fi_db.recompute_source_reliability(conn)
    second = fi_db.source_standing(conn, "filing_feed")

    # updated_at is excluded deliberately: it records when the standing was last
    # recomputed, not what was computed, and it *should* move on every pass.
    judged = ("graded_contributions", "mean_evidence_quality", "mean_overall_score")
    assert {k: first[k] for k in judged} == {k: second[k] for k in judged}
    assert second["updated_at"] >= first["updated_at"]


def test_a_report_drawing_on_two_sources_credits_both(conn):
    """No finer attribution is available without asking the grader which item
    persuaded it, so both sources take the grade the thing they jointly
    produced received."""
    good = fi_db.record_evidence_item(conn, "speculator-1", "T", "social", "SYN1",
                                      source="filing_feed", content="a", confidence=0.9)
    bad = fi_db.record_evidence_item(conn, "speculator-1", "T", "social", "SYN1",
                                     source="pump_channel", content="b", confidence=0.9)
    report_id = fi_db.enqueue_report(conn, "speculator-1", "T", "speculator", "SYN1",
                                     evidence_ids=[good, bad])
    fi_db.complete_report(conn, report_id, "analyzed",
                          handled_by_identity="analysis-1", handled_by_spawned_at="T")
    result_id = fi_db.record_analysis_result(conn, "analysis-1", "T", report_id, "SYN1",
                                             thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u")
    fi_db.record_grade(conn, "analysis-1", "T", report_id, result_id,
                       relevance_score=0.6, novelty_score=0.6, evidence_quality_score=0.6,
                       worth_the_compute=True, overall_score=0.6, rationale="r")

    fi_db.recompute_source_reliability(conn)

    assert {s["source"] for s in fi_db.list_source_reliability(conn)} == {"filing_feed", "pump_channel"}


def test_ungraded_evidence_contributes_nothing(conn):
    """A source only earns a standing from reports that were actually judged.
    Evidence that never reached a grade says nothing about quality."""
    fi_db.record_evidence_item(conn, "speculator-1", "T", "social", "SYN1",
                               source="filing_feed", content="x", confidence=0.9)
    assert fi_db.recompute_source_reliability(conn) == 0
    assert fi_db.source_standing(conn, "filing_feed") is None


def test_reliability_never_suppresses_collection(conn):
    """The property the whole design turns on. A source rated badly must keep
    contributing evidence - a model that gated collection could never learn it
    was wrong, because the record it judged on would stop growing."""
    for _ in range(6):
        _graded_evidence(conn, "pump_channel", evidence_quality=0.05)
    fi_db.recompute_source_reliability(conn)
    assert fi_db.source_standing(conn, "pump_channel")["mean_evidence_quality"] < 0.1

    # nothing in the evidence path consults the standing
    evidence_id = _graded_evidence(conn, "pump_channel", evidence_quality=0.9)
    assert fi_db.list_evidence_items(conn, [evidence_id])[0]["source"] == "pump_channel"

    fi_db.recompute_source_reliability(conn)
    assert fi_db.source_standing(conn, "pump_channel")["graded_contributions"] == 7


def test_analysis_is_told_the_standing_but_told_not_to_filter_on_it(conn):
    """Analysis weighs the standing; it is explicitly warned off treating a low
    one as grounds to ignore evidence."""
    from agents.analysis import _assemble_context

    for _ in range(6):
        _graded_evidence(conn, "pump_channel", evidence_quality=0.05)
    fi_db.recompute_source_reliability(conn)

    evidence_id = fi_db.record_evidence_item(conn, "speculator-1", "T", "social", "SYN1",
                                             source="pump_channel", content="to the moon", confidence=0.9)
    report_id = fi_db.enqueue_report(conn, "speculator-1", "T", "speculator", "SYN1",
                                     summary="s", evidence_ids=[evidence_id])
    context = _assemble_context(conn, fi_db.fetch_next_pending_report(conn))

    assert "source pump_channel" in context
    assert "mean evidence quality 0.05" in context
    assert "do not treat a low standing as grounds to ignore" in context


def test_an_unearned_standing_is_labelled_as_such_in_context(conn):
    """Rendering "not yet known" as a middling number would read as a judgment
    that has not been made."""
    from agents.analysis import _assemble_context

    evidence_id = fi_db.record_evidence_item(conn, "speculator-1", "T", "social", "SYN1",
                                             source="filing_feed", content="8-K filed", confidence=0.7)
    fi_db.enqueue_report(conn, "speculator-1", "T", "speculator", "SYN1",
                         summary="s", evidence_ids=[evidence_id])
    context = _assemble_context(conn, fi_db.fetch_next_pending_report(conn))

    assert "standing not yet earned" in context


def test_the_provider_gives_sources_genuinely_different_content(conn):
    """Prerequisite for any of this. With one source - or several saying the
    same things - reliability would be a scorer with nothing to discriminate
    between, which is the trap this project keeps having to check for."""
    from providers.social_data import SOURCE_CONTENT

    assert len(SOURCE_CONTENT) > 1
    texts = {source: {t for t, _ in templates} for source, templates in SOURCE_CONTENT.items()}
    for source, own in texts.items():
        for other_source, other in texts.items():
            if source != other_source:
                assert not (own & other), f"{source} and {other_source} share content"
