"""The collaboration scoring baseline (backend/competency.py +
fi_db.competency_evidence; TQ-17, SPEC_RECONCILIATION §65).

Addenda 34 §17 / 36 §8 / 37 §8 all make collaboration the highest-priority
competency. This suite covers the half that can be *measured* today from
records the organization already writes: whether a desk answers the
cross-checks addressed to its role and the UQI questions addressed to its
identity, before the timeout machinery gives up on it.

The competency module's four rules apply unchanged and are tested here:
absent is not zero (too little evidence means the dimension is not stated at
all, never a low score), earned rather than assigned, no universal score
(collaboration is its own dimension, never blended into another), and
attribution by tenure - a desk is scored for the duty assigned while it sat
there."""

import pytest

from backend import competency, fi_db


def _seed_desk(conn, identity="explorer-1", role="explorer"):
    """Register an agent the way the organization does - register_agent mints
    the name and opens its assignment span - and return the minted name."""
    fi_db.register_agent(conn, identity, role, 100)
    return fi_db.get_agent_name(conn, identity)


def at(second: int) -> str:
    return f"2026-08-17T00:00:{second:02d}.000000+00:00"


def set_span(conn, span_id: int, started_at: str, ended_at: str | None):
    conn.execute(
        "UPDATE agent_assignments SET started_at = ?, ended_at = ? WHERE id = ?",
        (started_at, ended_at, span_id),
    )


def set_created_at(conn, request_id: int, created_at: str):
    conn.execute("UPDATE cross_check_requests SET created_at = ? WHERE id = ?", (created_at, request_id))


def _cross_check(conn, responder_role="explorer", outcome=fi_db.CROSS_CHECK_EVIDENCE):
    """One terminal cross-check addressed to `responder_role`. Answered
    through the real API where the outcome is an answer; expired through the
    real timeout path where it is silence - so the statuses under test are
    the ones the organization actually writes."""
    request_id = fi_db.open_cross_check(
        conn, requester_identity="speculator-1", requester_spawned_at="2026-01-01T00:00:00+00:00",
        requester_role="speculator", responder_role=responder_role, security="ACME",
        question="what is the chatter saying?", requester_finding={"detector": "arb001_parity"},
    )
    if outcome == fi_db.CROSS_CHECK_UNANSWERED:
        # timeout_seconds=0: every pending request is already stale.
        fi_db.expire_stale_cross_checks(conn, timeout_seconds=0)
    else:
        fi_db.answer_cross_check(
            conn, request_id, responder_identity="explorer-1",
            responder_spawned_at="2026-01-01T00:00:00+00:00", outcome=outcome,
            responder_finding={"note": "looked"},
        )
    return request_id


def _uqi(conn, target_identity="explorer-1", answered=True):
    request_id = fi_db.ask_agent(conn, asked_by="operator", target_identity=target_identity,
                                question="what are you working on?")
    if answered:
        fi_db.answer_uqi_request(conn, request_id, answer="a parity scan", pid=123)
    else:
        fi_db.expire_stale_uqi_requests(conn, timeout_seconds=0)
    return request_id


def _dimension(conn, name, key):
    return fi_db.competency_profile(conn, name)["dimensions"][key]


# --- the dimensions exist and are their own ---------------------------------------


def test_collaboration_dimensions_are_declared_separately():
    """No universal score: collaboration is reported as its own dimension,
    never folded into analytical quality."""
    assert "collaboration_responsiveness" in competency.DIMENSIONS
    assert "uqi_responsiveness" in competency.DIMENSIONS
    for key in ("collaboration_responsiveness", "uqi_responsiveness"):
        assert competency.DIMENSIONS[key]["min_samples"] >= 1


def test_absent_evidence_is_not_a_low_score(conn):
    """The module's first rule, applied to the new dimensions: a desk nobody
    has ever asked anything is not a bad collaborator."""
    name = _seed_desk(conn)
    for key in ("collaboration_responsiveness", "uqi_responsiveness"):
        entry = _dimension(conn, name, key)
        assert entry["stated"] is False
        assert entry["samples"] == 0
        assert entry.get("score") is None
        assert competency.UNSTATED_REASON in entry["reason"]


# --- scoring ----------------------------------------------------------------------


def test_answered_cross_checks_score_and_state(conn):
    name = _seed_desk(conn)
    for _ in range(competency.DIMENSIONS["collaboration_responsiveness"]["min_samples"]):
        _cross_check(conn)
    entry = _dimension(conn, name, "collaboration_responsiveness")
    assert entry["stated"] is True
    assert entry["score"] == pytest.approx(1.0)


def test_no_evidence_counts_as_an_answer(conn):
    """A responder that looked and found nothing has said something
    informative (fi_db's own words on the outcome vocabulary) - silence is
    the collaboration failure, not an honest empty-handed reply."""
    name = _seed_desk(conn)
    for _ in range(5):
        _cross_check(conn, outcome=fi_db.CROSS_CHECK_NO_EVIDENCE)
    entry = _dimension(conn, name, "collaboration_responsiveness")
    assert entry["stated"] is True
    assert entry["score"] == pytest.approx(1.0)


def test_silence_lowers_the_rate(conn):
    """Responsiveness folds latency in: the timeout machinery marks a slow
    answer 'unanswered', so answered-at-all is answered-in-time."""
    name = _seed_desk(conn)
    for _ in range(3):
        _cross_check(conn)
    for _ in range(3):
        _cross_check(conn, outcome=fi_db.CROSS_CHECK_UNANSWERED)
    entry = _dimension(conn, name, "collaboration_responsiveness")
    assert entry["samples"] == 6
    assert entry["score"] == pytest.approx(0.5)


def test_in_flight_requests_are_not_yet_evidence(conn):
    """A pending question says nothing about the desk yet - counting it as
    an unanswered failure would score an agent for work still in progress."""
    name = _seed_desk(conn)
    for _ in range(5):
        _cross_check(conn)
    fi_db.open_cross_check(
        conn, requester_identity="speculator-1", requester_spawned_at="2026-01-01T00:00:00+00:00",
        requester_role="speculator", responder_role="explorer", security="ACME",
        question="still thinking?", requester_finding={},
    )
    entry = _dimension(conn, name, "collaboration_responsiveness")
    assert entry["samples"] == 5
    assert entry["score"] == pytest.approx(1.0)


def test_uqi_responsiveness_scores_on_its_own_traffic(conn):
    name = _seed_desk(conn)
    for _ in range(2):
        _uqi(conn)
    _uqi(conn, answered=False)
    entry = _dimension(conn, name, "uqi_responsiveness")
    assert entry["samples"] == 3
    assert entry["score"] == pytest.approx(2 / 3, abs=1e-3)  # _state rounds
    # And it is genuinely separate traffic: cross-check silence does not
    # touch it.
    assert _dimension(conn, name, "collaboration_responsiveness")["stated"] is False


def test_cross_checks_for_another_role_are_not_this_desks_evidence(conn):
    name = _seed_desk(conn)
    for _ in range(5):
        _cross_check(conn, responder_role="speculator")
    assert _dimension(conn, name, "collaboration_responsiveness")["samples"] == 0


def test_uqi_for_another_identity_is_not_this_desks_evidence(conn):
    name = _seed_desk(conn)
    for _ in range(3):
        _uqi(conn, target_identity="speculator-1")
    assert _dimension(conn, name, "uqi_responsiveness")["samples"] == 0


# --- attribution by tenure --------------------------------------------------------


def test_duty_assigned_before_a_transfer_stays_with_the_desk_that_held_it(conn):
    """The attributed_work rule: a desk is scored for the duty it was on
    call for. Work asked of a role before this agent sat at it belongs to
    whoever did sit there."""
    incumbent = _seed_desk(conn)
    first_span = fi_db.current_assignment(conn, name=incumbent)["id"]
    set_span(conn, first_span, at(0), at(10))

    # Five cross-checks during the incumbent's tenure, one after it ended.
    for _ in range(5):
        set_created_at(conn, _cross_check(conn), at(5))
    fi_db.reassign_agent_name(conn, incumbent, "analysis-1", "transferred to analysis")
    set_span(conn, fi_db.current_assignment(conn, name=incumbent)["id"], at(10), None)
    fi_db.open_assignment(conn, "Blake", "explorer-1", "explorer", "backfilled the vacancy",
                          started_at=at(10))
    set_created_at(conn, _cross_check(conn), at(20))

    assert _dimension(conn, incumbent, "collaboration_responsiveness")["samples"] == 5
    successor = _dimension(conn, "Blake", "collaboration_responsiveness")
    assert successor["samples"] == 1
    assert successor["stated"] is False  # absent is not zero, for the new arrival too


# --- the evidence gatherer's own shape --------------------------------------------


def test_evidence_carries_the_collaboration_records(conn):
    name = _seed_desk(conn)
    _cross_check(conn)
    _uqi(conn, answered=False)
    evidence = fi_db.competency_evidence(conn, name)
    assert evidence["cross_check_responses"] == [{"answered": True}]
    assert evidence["uqi_responses"] == [{"answered": False}]


def test_profile_tolerates_evidence_without_the_new_keys():
    """backend/competency.py is a pure function over a dict, and callers
    predating this increment (or a narrowed test double) must not crash -
    they get unstated dimensions, which is the honest answer."""
    profile = competency.profile({"grades": [], "sessions": 1, "crashes": 0})
    assert profile["dimensions"]["collaboration_responsiveness"]["stated"] is False
    assert "collaboration_responsiveness" not in profile["stated_dimensions"]
