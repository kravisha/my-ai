"""Tests for backend/triage.py - which queued lead Analysis takes next.

Split from the database tests because the ordering is the substance, and it
should be examinable without a database or a model call. The behaviours worth
protecting are the two the design turns on: rank on evidence *quantity* and
never on its direction, and never let ranking become starvation.
"""

from backend import triage


def _report(report_id, cross_check_id=None):
    return {"id": report_id, "security": f"SYN{report_id}", "cross_check_id": cross_check_id}


def _order(reports, cross_checks=None, ages=None, starvation=120.0, novelty_scores=None):
    ranked = triage.prioritise(reports, cross_checks or {}, ages or {}, starvation, novelty_scores)
    return [r["id"] for r in ranked]


def test_an_answered_cross_check_outranks_an_unanswered_one():
    """A lead whose partner replied has two independent findings for Analysis to
    weigh; one that timed out has one."""
    reports = [_report(1, cross_check_id=10), _report(2, cross_check_id=20)]
    cross_checks = {10: {"outcome": "unanswered"}, 20: {"outcome": "evidence"}}
    assert _order(reports, cross_checks) == [2, 1]


def test_no_evidence_outranks_unanswered():
    """"The second frame looked and found nothing" is a real finding. "Nobody
    answered" is an absence. The first is more to reason about."""
    reports = [_report(1, cross_check_id=10), _report(2, cross_check_id=20)]
    cross_checks = {10: {"outcome": "unanswered"}, 20: {"outcome": "no_evidence"}}
    assert _order(reports, cross_checks) == [2, 1]


def test_a_lead_with_no_cross_check_at_all_ranks_last():
    reports = [_report(1), _report(2, cross_check_id=20)]
    cross_checks = {20: {"outcome": "unanswered"}}
    assert _order(reports, cross_checks) == [2, 1]


def test_ranking_ignores_which_way_the_evidence_points():
    """The direction of the second frame's finding is deliberately not consulted.
    Ranking on whether Speculator *supported* the lead would settle in a queue
    the question addendum 12 §14 reserves for Analysis - and the queue has no
    business forming that view."""
    supporting = {"outcome": "evidence", "responder_finding": '{"stance": "supports"}'}
    undercutting = {"outcome": "evidence", "responder_finding": '{"stance": "undercuts"}'}
    reports = [_report(1, cross_check_id=10), _report(2, cross_check_id=20)]

    # whichever way round the stances are, arrival order decides - not stance
    assert _order(reports, {10: supporting, 20: undercutting}) == [1, 2]
    assert _order(reports, {10: undercutting, 20: supporting}) == [1, 2]


def test_equally_evidenced_leads_stay_in_arrival_order():
    """Prioritisation refines FIFO rather than replacing it - among ties the old
    behaviour is exactly preserved."""
    cross_checks = {10: {"outcome": "evidence"}, 20: {"outcome": "evidence"}}
    reports = [_report(2, cross_check_id=20), _report(1, cross_check_id=10)]
    assert _order(reports, cross_checks) == [1, 2]


def test_a_starving_lead_jumps_the_whole_ranking():
    """Without this, a security whose cross-checks keep timing out would sit at
    the back forever and prioritisation would quietly become suppression."""
    reports = [_report(1), _report(2, cross_check_id=20)]
    cross_checks = {20: {"outcome": "evidence"}}
    ages = {1: 500.0, 2: 1.0}
    assert _order(reports, cross_checks, ages, starvation=120.0) == [1, 2]


def test_among_starving_leads_the_oldest_goes_first():
    """Once something has waited too long, waiting longer is the only thing that
    matters - being better evidenced must not promote one starving lead over
    another that has waited even longer."""
    reports = [_report(1, cross_check_id=10), _report(2)]
    cross_checks = {10: {"outcome": "evidence"}}
    ages = {1: 200.0, 2: 900.0}
    assert _order(reports, cross_checks, ages, starvation=120.0) == [2, 1]


def test_nothing_starves_below_the_threshold():
    reports = [_report(1), _report(2, cross_check_id=20)]
    cross_checks = {20: {"outcome": "evidence"}}
    ages = {1: 119.0, 2: 1.0}
    assert _order(reports, cross_checks, ages, starvation=120.0) == [2, 1]


def test_an_empty_queue_is_not_an_error():
    assert triage.prioritise([], {}, {}) == []


def test_explanations_name_the_actual_reason():
    """An unexplained ordering is not auditable, which is the same standard
    every other decision in this system is held to."""
    cross_checks = {10: {"outcome": "evidence"}, 20: {"outcome": "unanswered"}}
    assert "evidence from the second frame" in triage.explain(_report(1, 10), cross_checks, {})
    assert "timed out" in triage.explain(_report(2, 20), cross_checks, {})
    assert "no cross-check" in triage.explain(_report(3), cross_checks, {})
    assert "starvation guard" in triage.explain(_report(4), cross_checks, {4: 900.0}, 120.0)


def test_a_dangling_cross_check_reference_does_not_crash_the_queue():
    """A report pointing at a cross-check row that is missing must rank last,
    not raise - one bad row cannot be allowed to stall the whole pipeline."""
    reports = [_report(1, cross_check_id=999), _report(2, cross_check_id=20)]
    cross_checks = {20: {"outcome": "unanswered"}}
    assert _order(reports, cross_checks) == [2, 1]


def test_the_starvation_guard_exceeds_a_realistic_queue_drain_time():
    """The guard must sit above how long the queue actually takes to drain, or
    it fires for every report and prioritisation silently becomes FIFO.

    Measured against a real ten-security backend: Analysis completes 0.05
    reports/sec and the queue runs 13-20 deep, so a full drain is 260-400s. The
    first value tried was 120s - below that, which would have made the ranking
    apply to nothing. This test encodes the measurement so the constant cannot
    drift back under it unnoticed."""
    worst_observed_drain_seconds = 20 / 0.05  # depth / throughput
    assert triage.STARVATION_SECONDS > worst_observed_drain_seconds * 2


def test_the_guard_is_configurable_for_a_faster_or_slower_pipeline():
    """Throughput will change - more Analysis instances, a cheaper model, a
    deeper queue. The constant is a measurement of today, not a law."""
    reports = [_report(1), _report(2, cross_check_id=20)]
    cross_checks = {20: {"outcome": "evidence"}}
    ages = {1: 300.0, 2: 1.0}
    assert _order(reports, cross_checks, ages, starvation=200.0) == [1, 2]   # 1 starves
    assert _order(reports, cross_checks, ages, starvation=9999.0) == [2, 1]  # nothing starves


# --- novelty as a ranking input (constitution section 8: transformation, not filing) ---


def _novel(score=1.0, summary="first observation ever recorded"):
    return {"score": score, "is_novel": score >= triage.NOVEL_THRESHOLD,
            "reasons": [summary], "summary": summary}


def test_an_unprecedented_lead_outranks_a_well_evidenced_familiar_one():
    """The whole point. A lead the system has no precedent for is worth the
    scarce deep-reasoning call more than the twentieth instance of a known
    pattern - even one with a complete cross-check."""
    reports = [_report(1, cross_check_id=10), _report(2, cross_check_id=20)]
    cross_checks = {10: {"outcome": "evidence"}, 20: {"outcome": "unanswered"}}
    novelty_scores = {2: _novel()}

    assert _order(reports, cross_checks, novelty_scores=novelty_scores) == [2, 1]


def test_among_novel_leads_evidence_still_decides():
    """Novelty promotes a lead into the front group; within it the ordering is
    still the evidence ranking, so the two inputs compose rather than one
    erasing the other."""
    reports = [_report(1, cross_check_id=10), _report(2, cross_check_id=20)]
    cross_checks = {10: {"outcome": "unanswered"}, 20: {"outcome": "evidence"}}
    novelty_scores = {1: _novel(), 2: _novel()}

    assert _order(reports, cross_checks, novelty_scores=novelty_scores) == [2, 1]


def test_starvation_still_beats_novelty():
    """A lead that has waited too long outranks everything, novel or not -
    otherwise a steady stream of unprecedented leads would starve the queue and
    prioritisation would become the suppression it exists to avoid."""
    reports = [_report(1), _report(2)]
    novelty_scores = {2: _novel()}
    ages = {1: 5000.0, 2: 1.0}

    assert _order(reports, {}, ages, starvation=900.0, novelty_scores=novelty_scores) == [1, 2]


def test_a_below_threshold_score_does_not_promote():
    reports = [_report(1, cross_check_id=10), _report(2)]
    cross_checks = {10: {"outcome": "evidence"}}
    novelty_scores = {2: _novel(score=0.3)}  # under NOVEL_THRESHOLD

    assert _order(reports, cross_checks, novelty_scores=novelty_scores) == [1, 2]


def test_the_reason_says_what_was_unprecedented():
    """A novelty verdict nobody can interrogate is the unfalsifiable assessment
    this whole approach exists to avoid."""
    reason = triage.explain(_report(1), {}, {},
                            novelty_scores={1: _novel(summary="ratio 9.90 exceeds anything seen")})
    assert "unprecedented" in reason
    assert "ratio 9.90 exceeds anything seen" in reason


def test_ranking_without_novelty_scores_is_unchanged():
    """Novelty is additive. Callers that do not supply scores must get exactly
    the previous ordering."""
    reports = [_report(1, cross_check_id=10), _report(2, cross_check_id=20)]
    cross_checks = {10: {"outcome": "unanswered"}, 20: {"outcome": "evidence"}}
    assert _order(reports, cross_checks) == [2, 1]
