"""Tests for panel/render.py - the control panel's formatting decisions.

Pure functions, no Tk window and no HTTP. The behaviours worth protecting here
are the ones where a display choice could quietly misrepresent the system:
showing a dormant agent as faulty, hiding an expired lens, or resolving a
disagreement the architecture deliberately left open.
"""

from panel import render


def _agent(**overrides):
    base = {
        "identity": "explorer-1",
        "role": "explorer",
        "lifecycle_state": "active",
        "process_state": "running",
        "heartbeat_age_seconds": 0.9,
    }
    return {**base, **overrides}


def test_roster_row_shows_both_axes_as_separate_columns():
    row = render.agent_row(_agent(lifecycle_state="dormant", process_state="stopped"))
    assert "dormant" in row and "stopped" in row


def test_a_never_heartbeated_agent_shows_a_dash_not_zero():
    """Zero would read as "just reported", which is the opposite of the truth."""
    assert "-" in render.agent_row(_agent(heartbeat_age_seconds=None))


def test_dormant_agent_is_not_shown_as_unhealthy():
    """A stood-down agent has no running process to be healthy about. Showing
    it as UNHEALTHY would display a fault where there was a decision."""
    text = render.format_agent_detail(_detail(lifecycle_state="dormant", healthy=None, working=None))
    assert "UNHEALTHY" not in text
    assert "n/a (dormant)" in text


def test_an_unhealthy_agent_is_shouted_not_whispered():
    text = render.format_agent_detail(_detail(healthy=False))
    assert "UNHEALTHY" in text


def _detail(**overrides):
    base = {
        "answered_by": "organizational_record",
        "identity": "explorer-1",
        "agent_name": "Anand",
        "role": "explorer",
        "agent_type": "discovery",
        "description": "Quantitative discovery.",
        "responsibilities": ["Scan surfaces"],
        "allowed": ["File reports"],
        "not_allowed": ["Perform deep reasoning"],
        "competencies": ["IV surface analysis"],
        "work_mechanism": "market provider",
        "lifecycle_state": "active",
        "process_state": "running",
        "healthy": True,
        "working": True,
        "current_task": None,
        "pid": 4242,
        "last_heartbeat_at": "2026-08-16T21:00:00+00:00",
        "heartbeat_age_seconds": 0.9,
        "retire_requested": False,
    }
    return {**base, **overrides}


def test_detail_states_who_answered():
    """A database read presented as the agent's own reply is a small lie that
    becomes load-bearing the moment the UQI makes both possible."""
    assert "[answered by: organizational_record]" in render.format_agent_detail(_detail())


def test_detail_explains_why_there_is_no_current_task():
    """Blank would look like a gap. The reason is that the system records
    heartbeats, not task spans."""
    text = render.format_agent_detail(_detail())
    assert "not recorded" in text and "task spans" in text


def test_detail_lists_prohibitions_explicitly():
    assert "NOT allowed" in render.format_agent_detail(_detail())


def _artifact(**overrides):
    base = {
        "name": "iv_ratio_threshold",
        "version": 1,
        "value": 2.0,
        "status": "active",
        "rationale": "from the spec",
        "staleness_reason": None,
        "observed_under_regime": None,
        "regime_bound_at": None,
        "performance": {"graded_reports": 0, "mean_overall_score": None, "worth_the_compute_rate": None},
    }
    return {**base, **overrides}


def test_stale_lenses_are_shown_with_their_reason():
    """The most informative row in the table is the one that expired - it is
    the system having noticed something."""
    text = render.format_intelligence([_artifact(status="stale", staleness_reason="mean IV moved 0.0803")])
    assert "[STALE]" in text
    assert "mean IV moved 0.0803" in text


def test_an_unbound_lens_says_so_rather_than_showing_blank():
    assert "not yet" in render.format_intelligence([_artifact()])


def test_a_bound_lens_shows_the_conditions_it_earned():
    text = render.format_intelligence([_artifact(
        observed_under_regime={"mean_iv": 0.2999, "iv_dispersion": 0.0618},
        regime_bound_at="2026-08-16T14:25:55+00:00",
    )])
    assert "0.2999" in text and "0.0618" in text


def test_ungraded_lens_shows_dashes_not_zeroes():
    """Zero mean score would read as "scored terribly" rather than "not yet
    judged" - the thin-evidence distinction the whole health check rests on."""
    text = render.format_intelligence([_artifact()])
    assert "mean -" in text


def _cross_check(**overrides):
    base = {
        "id": 5,
        "security": "SYN2",
        "requester_role": "explorer",
        "responder_role": "speculator",
        "question": "Is there contextual evidence?",
        "requester_finding": {"ratio": 2.14},
        "responder_finding": {"distinct_authors": 3, "stance": "unclear"},
        "status": "consumed",
        "outcome": "evidence",
    }
    return {**base, **overrides}


def test_both_findings_are_shown_and_neither_is_resolved():
    """Adding a computed AGREES/DISAGREES banner would settle in a display
    layer the exact question addendum 12 §14 reserves for Analysis."""
    text = render.format_cross_checks([_cross_check()])
    assert "ratio=2.14" in text
    assert "distinct_authors=3" in text
    assert "AGREE" not in text.upper().replace("DISAGREEMENT", "")


def test_an_unanswered_cross_check_says_uncorroborated_not_contradicted():
    """Silence is not evidence against a lead. Conflating them would let a
    dormant agent quietly veto every finding."""
    text = render.format_cross_checks([_cross_check(outcome="unanswered", responder_finding=None)])
    assert "uncorroborated" in text
    assert "not the same as contradicted" in text


def test_no_evidence_reads_as_a_finding_rather_than_a_failure():
    text = render.format_cross_checks([_cross_check(outcome="no_evidence", responder_finding={"posts": 0})])
    assert "looked and found nothing" in text


def test_a_pending_cross_check_shows_no_answer_yet():
    text = render.format_cross_checks([_cross_check(status="pending", outcome=None, responder_finding=None)])
    assert "(no answer yet)" in text


def test_empty_collections_render_a_message_not_a_blank_pane():
    assert "(no cross-checks yet)" in render.format_cross_checks([])
    assert "(no intelligence artifacts)" in render.format_intelligence([])
    assert "(no market observations yet)" in render.format_regime({"market_wide": {"observation_count": 0}})


def test_regime_says_the_estimate_was_inferred_not_supplied():
    """The system is never told the regime. A panel implying otherwise would
    misrepresent the one property that makes regime detection meaningful."""
    text = render.format_regime({
        "market_wide": {"mean_iv": 0.29, "iv_dispersion": 0.036, "observation_count": 20, "securities": 4},
        "securities": [{"security": "SYN1", "mean_iv": 0.29, "iv_dispersion": 0.036, "observation_count": 5}],
    })
    assert "never told" in text
    assert "SYN1" in text


def test_discovery_marks_reports_that_had_no_cross_check():
    text = render.format_discovery({
        "pending_reports": [
            {"id": 1, "security": "SYN1", "producer_identity": "explorer-1", "summary": "anomaly", "cross_check_id": 7},
            {"id": 2, "security": "SYN2", "producer_identity": "explorer-1", "summary": "anomaly", "cross_check_id": None},
        ],
        "recent_analyses": [],
    })
    assert "xcheck#7" in text
    assert "no cross-check" in text


def _exchange(**overrides):
    base = {
        "asked_by": "panel",
        "target_identity": "explorer-1",
        "question": "Who are you?",
        "status": "answered",
        "answer": "I am Anand, an explorer agent.",
        "answered_by_pid": 22892,
    }
    return {**base, **overrides}


def test_a_uqi_answer_names_the_agent_and_the_process_that_replied():
    """Once a live agent reply and a database read are both on screen, the
    operator must be able to tell which they are looking at."""
    text = render.format_uqi_exchange(_exchange())
    assert "answered by: agent" in text
    assert "pid 22892" in text


def test_a_pending_question_says_it_is_waiting_on_the_agents_cycle():
    text = render.format_uqi_exchange(_exchange(status="pending", answer=None, answered_by_pid=None))
    assert "waiting" in text
    assert "answered by" not in text


def test_an_unanswered_question_is_framed_as_a_diagnostic_not_a_bug():
    """A dormant or crashed agent cannot answer. That is the result, not a
    failure of the interface - and the panel should say which."""
    text = render.format_uqi_exchange(_exchange(status="unanswered", answer=None, answered_by_pid=None))
    assert "diagnostic result" in text
    assert "dormant or crashed" in text


def test_lifecycle_log_shows_who_asked_for_each_action():
    """Requester is the interesting column: panel, COO and any future requester
    file into the same queue and the Controller executes all of them."""
    text = render.format_directives({
        "pending": [],
        "completed": [
            {"id": 6, "directive_type": "resume", "target_identity": "explorer-1", "target_role": "explorer",
             "requested_by": "panel", "outcome": "success", "reason": "operator resume via control panel"},
            {"id": 7, "directive_type": "spawn", "target_identity": None, "target_role": "explorer",
             "requested_by": "coo", "outcome": "success", "reason": "baseline role has zero active agents"},
        ],
    })
    assert "by panel" in text and "by coo" in text
    assert "(none)" in text  # the empty pending queue says so rather than rendering blank
