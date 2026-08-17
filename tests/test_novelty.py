"""Tests for backend/novelty.py - does this observation fit what the system has
seen before? (Constitution section 8, Axiom 8.)

Structural, not semantic, and that limit is deliberate: novelty measured against
recorded history can be checked against the rows that produced it, whereas an
LLM asked "is this novel?" produces an assessment nothing can contradict.
"""

from backend import novelty


def _history(securities=(), ratios=None, combinations=(), outcomes=()):
    return {
        "securities_seen": set(securities),
        "ratio_range": ratios or {},
        "peer_combinations": set(combinations),
        "cross_check_outcomes": set(outcomes),
    }


def test_a_security_never_seen_before_is_novel():
    result = novelty.assess({"security": "SYN7"}, _history(securities=["SYN1"]))
    assert result["is_novel"]
    assert "first observation" in result["summary"]


def test_a_familiar_security_at_a_familiar_ratio_is_not_novel():
    history = _history(securities=["SYN1"], ratios={"SYN1": (2.0, 2.5)})
    result = novelty.assess({"security": "SYN1", "ratio": 2.2}, history)
    assert not result["is_novel"]
    assert result["score"] == 0.0


def test_a_ratio_above_anything_previously_seen_is_novel():
    history = _history(securities=["SYN1"], ratios={"SYN1": (2.0, 2.5)})
    result = novelty.assess({"security": "SYN1", "ratio": 9.9}, history)
    assert result["is_novel"]
    assert "exceeds anything previously seen" in result["summary"]


def test_a_ratio_below_anything_previously_seen_is_also_novel():
    """Unprecedented in either direction. A collapse is as much a break from
    experience as a spike."""
    history = _history(securities=["SYN1"], ratios={"SYN1": (2.0, 2.5)})
    result = novelty.assess({"security": "SYN1", "ratio": 0.4}, history)
    assert result["is_novel"]
    assert "below anything previously seen" in result["summary"]


def test_an_unseen_peer_combination_is_novel():
    history = _history(securities=["SYN1"], ratios={"SYN1": (2.0, 2.5)},
                       combinations=["SYN2,SYN3"])
    result = novelty.assess(
        {"security": "SYN1", "ratio": 2.2, "co_triggering": ["SYN4", "SYN5"]}, history)
    assert result["is_novel"]
    assert "has not co-triggered as [SYN4,SYN5] before" in result["summary"]


def test_a_peer_combination_is_order_independent():
    """The same set of co-triggering securities is one combination however it
    happened to be ordered when recorded."""
    history = _history(securities=["SYN1"], ratios={"SYN1": (2.0, 2.5)},
                       combinations=["SYN2,SYN3"])
    result = novelty.assess(
        {"security": "SYN1", "ratio": 2.2, "co_triggering": ["SYN3", "SYN2"]}, history)
    assert not result["is_novel"]


def test_reasons_stack_so_the_most_unprecedented_ranks_highest():
    """A first-ever security carrying an unheard-of ratio should outrank one
    that is merely unfamiliar."""
    plain = novelty.assess({"security": "SYN7"}, _history())
    compound = novelty.assess(
        {"security": "SYN7", "co_triggering": ["SYN1"], "cross_check_outcome": "no_evidence"},
        _history())
    assert compound["score"] >= plain["score"]
    assert len(compound["reasons"]) > len(plain["reasons"])


def test_the_score_is_capped():
    result = novelty.assess(
        {"security": "SYN7", "ratio": 99.0, "co_triggering": ["SYN1"],
         "cross_check_outcome": "never_seen"}, _history())
    assert result["score"] == 1.0


def test_fitting_experience_is_stated_rather_than_left_blank():
    """"Nothing about this is unprecedented" is a finding. A blank field reads
    as an absent check rather than a completed one."""
    history = _history(securities=["SYN1"], ratios={"SYN1": (2.0, 2.5)})
    result = novelty.assess({"security": "SYN1", "ratio": 2.2}, history)
    assert result["reasons"] == []
    assert "nothing unprecedented" in result["summary"]


def test_a_lead_with_no_ratio_is_judged_on_what_it_does_have():
    """Speculator-sourced leads carry no detector event. They must still be
    assessable rather than erroring or defaulting to novel."""
    history = _history(securities=["SYN1"])
    assert not novelty.assess({"security": "SYN1"}, history)["is_novel"]
    assert novelty.assess({"security": "SYN9"}, history)["is_novel"]


def test_every_verdict_carries_its_reasons():
    """A novelty verdict nobody can interrogate is the unfalsifiable assessment
    this module exists to avoid producing."""
    result = novelty.assess({"security": "SYN7", "ratio": 5.0}, _history())
    assert result["reasons"]
    assert all(isinstance(r, str) and r for r in result["reasons"])
