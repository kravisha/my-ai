"""Competency, qualification, ranking and commendation rules.

Pure functions over evidence, so these tests can be honest without a database.
They cover the shape of the rules; whether the *thresholds* are right is a
distributional question that a single fixture cannot answer, and is measured
separately against generated populations.

Four properties matter more than the arithmetic:
absent is never zero; a sole candidate is never ranked first; a commendation is
never an input to a decision; and an unmet requirement is distinguished from an
unknown one.
"""

import pytest

from backend import competency


def grades(n: int, overall=0.7, evidence=0.6, novelty=0.5) -> list[dict]:
    return [
        {"overall_score": overall, "evidence_quality_score": evidence,
         "novelty_score": novelty, "worth_the_compute": 1}
        for _ in range(n)
    ]


def strong(n: int = 40) -> dict:
    return competency.profile({
        "grades": grades(n, 0.8, 0.75, 0.6),
        "calibration": [(0.8, True)] * 30,
        "sessions": 10, "crashes": 0,
    })


def weak(n: int = 40) -> dict:
    return competency.profile({
        "grades": grades(n, 0.25, 0.2, 0.15),
        "calibration": [(0.9, False)] * 30,
        "sessions": 10, "crashes": 4,
    })


# -- absent is not zero -------------------------------------------------------

def test_a_dimension_below_its_evidence_floor_is_not_stated(conn):
    result = competency.profile({"grades": grades(3)})
    entry = result["dimensions"]["analytical_quality"]

    assert entry["stated"] is False
    assert entry["score"] is None, "a thin record must not be reported as a low score"
    assert entry["samples"] == 3 and entry["needs"] == 10


def test_an_empty_record_states_nothing_rather_than_scoring_zero():
    result = competency.profile({})
    assert result["stated_dimensions"] == []
    assert all(entry["score"] is None for entry in result["dimensions"].values())


def test_enough_evidence_states_the_dimension():
    entry = strong()["dimensions"]["analytical_quality"]
    assert entry["stated"] is True
    assert entry["score"] == pytest.approx(0.8)
    assert entry["samples"] == 40


def test_sample_count_travels_with_the_score():
    """0.62 from twelve observations and 0.62 from four hundred are different
    claims, and a consumer that cannot tell them apart will treat them alike."""
    few = competency.profile({"grades": grades(10, 0.62)})["dimensions"]["analytical_quality"]
    many = competency.profile({"grades": grades(400, 0.62)})["dimensions"]["analytical_quality"]
    assert few["score"] == many["score"]
    assert few["samples"] != many["samples"]


# -- calibration --------------------------------------------------------------

def test_confident_and_right_calibrates_well():
    result = competency.profile({"calibration": [(0.95, True)] * 25})
    assert result["dimensions"]["uncertainty_calibration"]["score"] > 0.9


def test_confident_and_wrong_calibrates_badly():
    result = competency.profile({"calibration": [(0.95, False)] * 25})
    assert result["dimensions"]["uncertainty_calibration"]["score"] < 0.1


def test_uniform_confidence_is_penalised_even_when_often_right():
    """An agent that says 0.9 about everything is badly calibrated however often
    it happens to be correct - calibration is not accuracy."""
    always_confident = [(0.9, True)] * 15 + [(0.9, False)] * 10
    discriminating = [(0.9, True)] * 15 + [(0.15, False)] * 10

    a = competency.profile({"calibration": always_confident})["dimensions"]["uncertainty_calibration"]
    b = competency.profile({"calibration": discriminating})["dimensions"]["uncertainty_calibration"]
    assert b["score"] > a["score"]


def test_reliability_counts_crashes_against_sessions():
    result = competency.profile({"sessions": 10, "crashes": 2})
    assert result["dimensions"]["operational_reliability"]["score"] == pytest.approx(0.8)


# -- qualification ------------------------------------------------------------

REQUIREMENT = {"analytical_quality": 0.5, "evidence_discipline": 0.45}


def test_a_strong_agent_qualifies():
    assert competency.evaluate_qualification(strong(), REQUIREMENT)["qualified"] is True


def test_a_weak_agent_does_not_qualify_and_is_blocked_on_performance():
    result = competency.evaluate_qualification(weak(), REQUIREMENT)
    assert result["qualified"] is False
    assert result["blocked_by"] == "performance"
    assert result["failed"]


def test_a_new_agent_is_blocked_on_evidence_not_performance(conn):
    """Remediation is the wrong response to an agent nobody has watched yet."""
    result = competency.evaluate_qualification(competency.profile({"grades": grades(2)}), REQUIREMENT)
    assert result["qualified"] is False
    assert result["blocked_by"] == "evidence"
    assert result["failed"] == []
    assert any("not yet known" in reason for reason in result["unknown"])


def test_an_unmeasured_dimension_is_reported_rather_than_ignored():
    result = competency.evaluate_qualification(strong(), {"charisma": 0.5})
    assert result["qualified"] is False
    assert any("not a dimension" in reason for reason in result["unknown"])


def test_qualification_says_which_requirements_were_met():
    result = competency.evaluate_qualification(strong(), REQUIREMENT)
    assert len(result["met"]) == 2


# -- ranking ------------------------------------------------------------------

def test_a_sole_candidate_is_unranked_not_first():
    """The most important rule here.

    'Ranked #1' among one agent is a true statement that will be read as a false
    one, because everybody consuming a ranking is looking for a comparison."""
    result = competency.rank({"Alex": strong()}, "analytical_quality")
    assert len(result) == 1
    assert result[0]["rank"] is None
    assert "only candidate" in result[0]["reason"]


def test_two_candidates_are_ranked_by_score():
    result = competency.rank({"Alex": strong(), "Blake": weak()}, "analytical_quality")
    ranked = [row for row in result if row["rank"] is not None]
    assert [row["name"] for row in ranked] == ["Alex", "Blake"]
    assert [row["rank"] for row in ranked] == [1, 2]


def test_equal_scores_share_a_rank_and_say_so():
    result = competency.rank({"Alex": strong(), "Blake": strong()}, "analytical_quality")
    assert {row["rank"] for row in result} == {1}
    assert result[0]["tied_with"] == ["Blake"]


def test_ranking_uses_competition_numbering_after_a_tie():
    third = competency.profile({
        "grades": grades(40, 0.4), "calibration": [(0.5, True)] * 30, "sessions": 5, "crashes": 0,
    })
    result = competency.rank(
        {"Alex": strong(), "Blake": strong(), "Cass": third}, "analytical_quality"
    )
    assert sorted(row["rank"] for row in result) == [1, 1, 3]


def test_an_agent_without_the_dimension_is_returned_unranked_not_omitted():
    """An agent missing from a ranking looks like an agent that does not exist."""
    result = competency.rank(
        {"Alex": strong(), "Blake": strong(), "New": competency.profile({"grades": grades(2)})},
        "analytical_quality",
    )
    assert len(result) == 3
    unranked = [row for row in result if row["rank"] is None]
    assert [row["name"] for row in unranked] == ["New"]
    assert unranked[0]["reason"] == competency.UNSTATED_REASON


def test_scores_differing_below_tie_precision_do_not_split_a_rank():
    """A rank that flickers on floating-point noise is one nobody can act on."""
    a = competency.profile({"grades": grades(40, 0.700001)})
    b = competency.profile({"grades": grades(40, 0.700002)})
    result = competency.rank({"A": a, "B": b}, "analytical_quality")
    assert {row["rank"] for row in result} == {1}


# -- commendations ------------------------------------------------------------

def events(kind: str, subject: str, n: int, detail=None, start=0) -> list[dict]:
    return [
        {"event_kind": kind, "subject": subject, "detail": detail,
         "occurred_at": f"2026-08-{start + i + 1:02d}"}
        for i in range(n)
    ]


def test_a_sustained_top_rank_earns_a_commendation():
    history = events("rank_achieved", "analytical_quality", 30, detail="1")
    earned = competency.commendations_earned("Alex", history)
    assert [c["kind"] for c in earned] == ["held_top_rank"]


def test_a_good_week_does_not():
    history = events("rank_achieved", "analytical_quality", 5, detail="1")
    assert competency.commendations_earned("Alex", history) == []


def test_regaining_a_lost_qualification_is_a_commendation():
    history = [
        {"event_kind": "qualification_granted", "subject": "analysis", "occurred_at": "2026-08-01"},
        {"event_kind": "qualification_revoked", "subject": "analysis", "occurred_at": "2026-08-05"},
        {"event_kind": "qualification_granted", "subject": "analysis", "occurred_at": "2026-08-20"},
    ]
    earned = competency.commendations_earned("Alex", history)
    assert any(c["kind"] == "recovery" for c in earned)


def test_no_decision_function_accepts_a_commendation():
    """§6: commendations provide context and never override current standing.

    Enforced in the signatures rather than by convention - neither
    evaluate_qualification nor rank has anywhere to put one."""
    import inspect

    for function in (competency.evaluate_qualification, competency.rank):
        parameters = set(inspect.signature(function).parameters)
        assert not any("commend" in name for name in parameters), (
            f"{function.__name__} accepts a commendation; historical memory must not decide "
            "current standing"
        )


def test_losing_standing_does_not_remove_an_earned_commendation():
    """The achievement happened. Ranking #1 for a period stays true after a fall
    to #3, which is the point of keeping the two layers apart."""
    history = (
        events("rank_achieved", "analytical_quality", 30, detail="1")
        + [{"event_kind": "rank_achieved", "subject": "analytical_quality",
            "detail": "3", "occurred_at": "2026-09-01"}]
    )
    earned = competency.commendations_earned("Alex", history)
    assert any(c["kind"] == "held_top_rank" for c in earned)
