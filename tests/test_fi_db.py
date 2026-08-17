"""Unit tests for backend/fi_db.py - the SQLite coordination substrate for
the Financial Intelligence system. Pure DB logic, fully hermetic (in-memory
SQLite, no real processes) - the real-subprocess integration test lives
separately in tests/test_controller.py, per the plan's deliberate testing
split.
"""

import json

import pytest

from backend import fi_db


def test_init_schema_is_idempotent(conn):
    fi_db.init_schema(conn)  # calling again should not raise
    fi_db.init_schema(conn)


def test_register_agent_appears_in_list(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    agents = fi_db.list_agents(conn)
    assert len(agents) == 1
    assert agents[0]["identity"] == "dummy-1"
    assert agents[0]["role"] == "dummy"
    assert agents[0]["pid"] == 111
    assert agents[0]["status"] == "active"


def test_register_agent_upserts_rather_than_duplicating(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.register_agent(conn, "dummy-1", "dummy", 222)  # re-spawned with a new pid
    agents = fi_db.list_agents(conn)
    assert len(agents) == 1
    assert agents[0]["pid"] == 222
    assert agents[0]["status"] == "active"


def test_register_agent_resets_last_heartbeat_on_reregistration(conn):
    """Identity is now a permanent role-slot, so re-registration (a real
    respawn wearing the same identity, not a rare edge case) must not let a
    fresh life inherit its previous life's last_heartbeat_at - that stale
    timestamp could already be past agents/coo.py's staleness threshold and
    get the freshly-registered agent marked 'crashed' immediately."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"] is not None

    fi_db.register_agent(conn, "dummy-1", "dummy", 222)  # respawned under the same permanent identity
    assert fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"] is None


def test_get_agent_returns_none_for_unknown_identity(conn):
    assert fi_db.get_agent(conn, "nobody") is None


def test_get_agent_returns_registered_agent(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["identity"] == "dummy-1"


def test_record_heartbeat_updates_last_heartbeat_and_logs_metric(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    assert fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"] is None

    fi_db.record_heartbeat(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"] is not None

    card = fi_db.get_performance_card(conn)
    assert card[0]["heartbeat_count"] == 1


def test_is_retirement_requested_false_by_default(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    assert fi_db.is_retirement_requested(conn, "dummy-1") is False


def test_request_retirement_sets_flag_agent_can_poll(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")
    assert fi_db.is_retirement_requested(conn, "dummy-1") is True


def test_is_retirement_requested_false_for_unknown_identity(conn):
    assert fi_db.is_retirement_requested(conn, "nobody") is False


def test_reregistering_agent_resets_retire_flag(conn):
    """A fresh spawn under the same identity should not inherit a stale
    retire request from a previous incarnation."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 222)
    assert fi_db.is_retirement_requested(conn, "dummy-1") is False


def test_mark_process_stopped_leaves_lifecycle_untouched(conn):
    """A process stopping says nothing about organizational standing: the
    agent is still in service, it just has no process right now (which is
    what COO refills)."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_stopped(conn, "dummy-1")

    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["process_state"] == fi_db.PROCESS_STOPPED
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_ACTIVE
    assert agent["status"] == "gone"  # derived legacy value


def test_enqueue_and_fetch_next_pending_directive(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["id"] == directive_id
    assert pending["directive_type"] == "spawn"
    assert pending["target_role"] == "dummy"
    assert pending["status"] == "pending"
    assert json.loads(pending["params"]) == {}


def test_fetch_next_pending_directive_returns_none_when_empty(conn):
    assert fi_db.fetch_next_pending_directive(conn) is None


def test_directives_are_fetched_fifo_by_timestamp(conn):
    first_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    second_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")

    first_pending = fi_db.fetch_next_pending_directive(conn)
    assert first_pending["id"] == first_id

    fi_db.complete_directive(conn, first_id, "success")
    second_pending = fi_db.fetch_next_pending_directive(conn)
    assert second_pending["id"] == second_id


def test_complete_directive_moves_row_to_completed_table(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")

    fi_db.complete_directive(conn, directive_id, "success", detail="spawned dummy-1")

    assert fi_db.fetch_next_pending_directive(conn) is None
    completed = fi_db.list_completed_directives(conn)
    assert len(completed) == 1
    assert completed[0]["id"] == directive_id
    assert completed[0]["outcome"] == "success"
    assert completed[0]["detail"] == "spawned dummy-1"


def test_complete_directive_with_failure_outcome(conn):
    directive_id = fi_db.enqueue_directive(conn, "retire", "coo", target_identity="dummy-1")
    fi_db.complete_directive(conn, directive_id, "failure", detail="process not found")

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["outcome"] == "failure"
    assert completed[0]["detail"] == "process not found"


def test_enqueue_directive_reason_is_optional(conn):
    """Backward compatibility: existing callers that don't pass reason keep
    working, and get a null reason rather than an error."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["id"] == directive_id
    assert pending["reason"] is None


def test_schema_version_is_stamped_on_agent_registry_and_health_metrics(conn):
    """Gap 1 (project brief): every message/record carries a schema
    version, addressed alongside (not instead of) the additive-only-
    columns rule - see the module docstring in fi_db.py for why both."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["schema_version"] == fi_db.SCHEMA_VERSION

    fi_db.record_heartbeat(conn, "dummy-1")
    metric_row = conn.fetchone("SELECT schema_version FROM health_metrics WHERE identity = 'dummy-1'")
    assert metric_row["schema_version"] == fi_db.SCHEMA_VERSION


def test_schema_version_is_stamped_on_directives_and_survives_archival(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["schema_version"] == fi_db.SCHEMA_VERSION

    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["schema_version"] == fi_db.SCHEMA_VERSION


def test_enqueue_directive_reason_is_captured_and_survives_archival(conn):
    """Gap 2 (project brief): COO decisions should be logged with a reason.
    This checks the reason is stored on the pending row and carried through
    to the completed table by the archive trigger, not dropped along the way."""
    directive_id = fi_db.enqueue_directive(
        conn, "spawn", "coo", target_role="dummy",
        reason="baseline role 'dummy' has zero active agents - respawning to maintain baseline",
    )
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["reason"] == "baseline role 'dummy' has zero active agents - respawning to maintain baseline"

    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["reason"] == "baseline role 'dummy' has zero active agents - respawning to maintain baseline"


def test_directives_needing_observation_excludes_non_spawn_and_failures(conn):
    spawn_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, spawn_id, "success", detail="dummy-1")

    failed_spawn_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, failed_spawn_id, "failure", detail="boom")

    retire_id = fi_db.enqueue_directive(conn, "retire", "coo", target_identity="dummy-1")
    fi_db.complete_directive(conn, retire_id, "success", detail="retirement requested for dummy-1")

    ready = fi_db.list_directives_needing_observation(conn, grace_seconds=0)
    assert [r["id"] for r in ready] == [spawn_id]


def test_directives_needing_observation_respects_grace_period(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")

    assert fi_db.list_directives_needing_observation(conn, grace_seconds=999) == []
    assert [r["id"] for r in fi_db.list_directives_needing_observation(conn, grace_seconds=0)] == [directive_id]


def test_directives_needing_observation_excludes_already_observed(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.record_observed_result(conn, directive_id, "established")

    assert fi_db.list_directives_needing_observation(conn, grace_seconds=0) == []


def test_record_observed_result_is_visible_on_completed_directive(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")

    fi_db.record_observed_result(conn, directive_id, "established")

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "established"
    assert completed[0]["observed_at"] is not None


def test_has_pending_spawn_directive_true_while_unprocessed(conn):
    fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    assert fi_db.has_pending_spawn_directive(conn, "dummy") is True


def test_has_pending_spawn_directive_false_once_completed(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    assert fi_db.has_pending_spawn_directive(conn, "dummy") is False


def test_has_pending_spawn_directive_false_for_different_role(conn):
    fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    assert fi_db.has_pending_spawn_directive(conn, "explorer") is False


def test_mark_process_crashed_is_distinct_from_stopped(conn):
    """Gap 3 (project brief): restart-vs-crash distinction - 'crashed'
    (observed by COO's health evaluation) must stay distinct from 'stopped'
    (the agent's own clean exit), not collapsed into one value. Like a clean
    stop, it records process liveness only and never retires the agent."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_crashed(conn, "dummy-1")

    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["process_state"] == fi_db.PROCESS_CRASHED
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_ACTIVE
    assert agent["status"] == "crashed"  # derived legacy value


def test_list_stale_active_agents_excludes_fresh_heartbeat(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")
    assert fi_db.list_stale_active_agents(conn, stale_seconds=999) == []


def test_list_stale_active_agents_includes_agent_past_threshold(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")
    stale = fi_db.list_stale_active_agents(conn, stale_seconds=0)
    assert [a["identity"] for a in stale] == ["dummy-1"]


def test_list_stale_active_agents_uses_spawn_time_when_no_heartbeat_yet(conn):
    """An agent that registered but crashed before its first heartbeat has
    no last_heartbeat_at to check - fall back to spawned_at rather than
    treating a null heartbeat as 'never stale'."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    stale = fi_db.list_stale_active_agents(conn, stale_seconds=0)
    assert [a["identity"] for a in stale] == ["dummy-1"]


def test_list_stale_active_agents_excludes_already_stopped_processes(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_stopped(conn, "dummy-1")
    assert fi_db.list_stale_active_agents(conn, stale_seconds=0) == []


def test_list_stale_active_agents_excludes_dormant_agents(conn):
    """A dormant agent whose process already stopped is retired, not stale -
    flagging it as crashed would be plainly wrong."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.mark_process_stopped(conn, "dummy-1")

    assert fi_db.list_stale_active_agents(conn, stale_seconds=0) == []


def test_performance_card_reflects_multiple_agents(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.register_agent(conn, "coo-1", "coo", 222)
    fi_db.record_heartbeat(conn, "dummy-1")
    fi_db.record_heartbeat(conn, "dummy-1")

    card = fi_db.get_performance_card(conn)
    by_identity = {row["identity"]: row for row in card}
    assert by_identity["dummy-1"]["heartbeat_count"] == 2
    assert by_identity["coo-1"]["heartbeat_count"] == 0


def test_performance_card_empty_when_no_agents(conn):
    assert fi_db.get_performance_card(conn) == []


# --- Phase C: detector events, evidence, discovery report queue, analysis, grading ---


def test_record_detector_event_and_get(conn):
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0, neighborhood_desc="strike idx ±1, expiry idx ±1", surface_seed="42",
    )
    event = fi_db.get_detector_event(conn, event_id)
    assert event["security"] == "SYN1"
    assert event["ratio"] == 2.4
    assert event["scope"] == "individual"
    assert event["judgment_passed"] is None


def test_record_detector_event_with_peer_fields(conn):
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0, scope="peer", peer_group_name="synthetic_peer_group_v1",
        peer_group_version=1, peer_context='{"co_triggering": ["SYN2"]}',
    )
    event = fi_db.get_detector_event(conn, event_id)
    assert event["scope"] == "peer"
    assert event["peer_group_name"] == "synthetic_peer_group_v1"
    assert event["peer_group_version"] == 1
    assert event["peer_context"] == '{"co_triggering": ["SYN2"]}'


def test_record_detector_judgment_updates_event(conn):
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0,
    )
    fi_db.record_detector_judgment(conn, event_id, True, "coherent enough")
    event = fi_db.get_detector_event(conn, event_id)
    assert event["judgment_passed"] == 1
    assert event["judgment_note"] == "coherent enough"


def test_record_and_list_evidence_items(conn):
    id1 = fi_db.record_evidence_item(
        conn, "speculator-1", "2026-01-01T00:00:00+00:00", "social", "SYN1",
        source="reddit", content="something interesting", confidence=0.7, raw_ref="reddit:u1:t1",
    )
    id2 = fi_db.record_evidence_item(
        conn, "speculator-1", "2026-01-01T00:00:00+00:00", "social", "SYN1",
        source="reddit", content="something else", confidence=0.4, raw_ref="reddit:u2:t2",
    )
    items = fi_db.list_evidence_items(conn, [id1, id2])
    assert {item["id"] for item in items} == {id1, id2}
    assert fi_db.list_evidence_items(conn, []) == []


def test_enqueue_report_and_fetch_next_pending(conn):
    report_id = fi_db.enqueue_report(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        summary="anomaly found", detector_event_id=1, evidence_ids=[], judgment_confidence=None,
    )
    pending = fi_db.fetch_next_pending_report(conn)
    assert pending["id"] == report_id
    assert pending["status"] == "pending"
    assert json.loads(pending["evidence_ids"]) == []


def test_fetch_next_pending_report_none_when_empty(conn):
    assert fi_db.fetch_next_pending_report(conn) is None


def test_has_pending_report_true_while_unconsumed(conn):
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    assert fi_db.has_pending_report(conn, "explorer-1", "SYN1") is True


def test_has_pending_report_false_for_different_producer_or_security(conn):
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    assert fi_db.has_pending_report(conn, "speculator-1", "SYN1") is False
    assert fi_db.has_pending_report(conn, "explorer-1", "SYN2") is False


def test_complete_report_moves_to_completed_table_via_trigger(conn):
    report_id = fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    fi_db.complete_report(
        conn, report_id, "analyzed",
        handled_by_identity="analysis-1", handled_by_spawned_at="2026-01-01T00:01:00+00:00",
    )

    assert fi_db.fetch_next_pending_report(conn) is None
    assert fi_db.has_pending_report(conn, "explorer-1", "SYN1") is False

    completed = fi_db.list_completed_reports(conn)
    assert completed[0]["id"] == report_id
    assert completed[0]["outcome"] == "analyzed"
    assert completed[0]["handled_by_identity"] == "analysis-1"
    assert completed[0]["producer_identity"] == "explorer-1"


def test_complete_report_with_failed_outcome(conn):
    report_id = fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    fi_db.complete_report(conn, report_id, "failed", detail="boom")

    completed = fi_db.list_completed_reports(conn)
    assert completed[0]["outcome"] == "failed"
    assert completed[0]["detail"] == "boom"
    assert completed[0]["handled_by_identity"] is None


def test_record_analysis_result(conn):
    report_id = fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, "SYN1",
        thesis="vol looks overpriced here", evidence_summary="peak ratio 2.4",
        confidence=0.6, uncertainty="could be earnings-driven noise",
    )
    assert result_id is not None


def test_record_analysis_result_with_peer_classification(conn):
    report_id = fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, "SYN1",
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
        peer_classification="common_factor",
    )
    results = fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)
    assert next(r for r in results if r["id"] == result_id)["peer_classification"] == "common_factor"


def test_list_recent_analysis_results_respects_window(conn):
    report_id = fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, "SYN1",
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    assert len(fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)) == 1
    assert fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=0) == []
    assert fi_db.list_recent_analysis_results(conn, "SYN2", since_seconds=999) == []


def test_record_grade_and_list_for_identity(conn):
    report_id = fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    fi_db.complete_report(conn, report_id, "analyzed", handled_by_identity="analysis-1", handled_by_spawned_at="2026-01-01T00:01:00+00:00")
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, "SYN1",
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    fi_db.record_grade(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, result_id,
        relevance_score=0.8, novelty_score=0.6, evidence_quality_score=0.7,
        worth_the_compute=True, overall_score=0.7, rationale="solid quantitative signal",
    )

    grades = fi_db.list_grades_for_identity(conn, "explorer-1")
    assert len(grades) == 1
    assert grades[0]["report_id"] == report_id
    assert grades[0]["analysis_result_id"] == result_id
    assert grades[0]["worth_the_compute"] == 1


def test_list_grades_for_identity_attributes_to_producer_not_grader(conn):
    """Grades are attributable to whoever produced the report (Explorer/
    Speculator), not to Analysis (the grader) - querying by the grader's
    own identity should find nothing."""
    report_id = fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")
    fi_db.complete_report(conn, report_id, "analyzed", handled_by_identity="analysis-1", handled_by_spawned_at="2026-01-01T00:01:00+00:00")
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, "SYN1",
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    fi_db.record_grade(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, result_id,
        relevance_score=0.8, novelty_score=0.6, evidence_quality_score=0.7,
        worth_the_compute=True, overall_score=0.7, rationale="r",
    )

    assert fi_db.list_grades_for_identity(conn, "explorer-1") != []
    assert fi_db.list_grades_for_identity(conn, "analysis-1") == []


# --- Pre-Alpha static metadata: Agent Name Repository (Consolidated §10/§21) ---


def test_register_agent_assigns_a_name_automatically(conn):
    """Agents get named without any agent-side code doing anything - the
    hook lives in register_agent, which every agent already calls."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    assert fi_db.get_agent_name(conn, "dummy-1") is not None


def test_agent_keeps_the_same_name_across_respawns(conn):
    """The point of tying names to the permanent role-slot identity: a name
    is a durable organizational record, not a per-process label."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    original = fi_db.get_agent_name(conn, "dummy-1")

    fi_db.register_agent(conn, "dummy-1", "dummy", 222)  # respawn, same identity

    assert fi_db.get_agent_name(conn, "dummy-1") == original


def test_two_identities_never_share_a_name(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.register_agent(conn, "explorer-1", "explorer", 222)
    assert fi_db.get_agent_name(conn, "dummy-1") != fi_db.get_agent_name(conn, "explorer-1")


def test_assign_agent_name_is_idempotent(conn):
    first = fi_db.assign_agent_name(conn, "dummy-1")
    second = fi_db.assign_agent_name(conn, "dummy-1")
    assert first == second


def test_reserved_ceo_name_is_never_auto_assigned(conn):
    """FI_CEO_DISPLAY_NAME (default "Bob") is seeded reserved so no ordinary
    agent can be handed it - the whole of the "Bob must not be hard-coded"
    requirement is this one setting plus this one reserved row."""
    for i in range(len(fi_db.AGENT_NAME_POOL) + 5):
        fi_db.assign_agent_name(conn, f"agent-{i}")

    reserved = conn.fetchone("SELECT * FROM agent_names WHERE name = ?", (fi_db.CEO_DISPLAY_NAME,))
    assert reserved["reserved"] == 1
    assert reserved["assigned_to_identity"] is None


def test_assign_agent_name_returns_none_when_pool_exhausted_without_raising(conn):
    """A name is a display concern - an empty pool must never be able to stop
    an agent from registering and doing real work."""
    # drain the pool down to a single remaining name (each row needs its own
    # identity - assigned_to_identity is UNIQUE, which is itself correct)
    for i, row in enumerate(fi_db.list_agent_names(conn)):
        if row["reserved"] == 0 and row["name"] != "Amara":
            conn.execute(
                "UPDATE agent_names SET assigned_to_identity = ? WHERE name = ?",
                (f"filler-{i}", row["name"]),
            )

    assert fi_db.assign_agent_name(conn, "first-1") == "Amara"
    assert fi_db.assign_agent_name(conn, "second-1") is None
    # and registering still works fine despite no name being available
    fi_db.register_agent(conn, "second-1", "dummy", 111)
    assert fi_db.get_agent(conn, "second-1")["status"] == "active"


def test_list_agent_names_assigned_only_filter(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    assigned = fi_db.list_agent_names(conn, assigned_only=True)
    assert [n["assigned_to_identity"] for n in assigned] == ["dummy-1"]
    assert len(fi_db.list_agent_names(conn)) == len(fi_db.AGENT_NAME_POOL) + 1  # + reserved CEO name


# --- Pre-Alpha static metadata: Security Universe (Consolidated §10/§21) ---


def test_security_universe_is_seeded(conn):
    symbols = [s["symbol"] for s in fi_db.list_security_universe(conn)]
    assert symbols == sorted(fi_db.SECURITY_UNIVERSE_SEED)


def test_security_universe_rows_are_versioned(conn):
    row = fi_db.list_security_universe(conn)[0]
    assert row["universe_version"] == fi_db.SECURITY_UNIVERSE_VERSION


def test_add_security_expands_the_universe(conn):
    fi_db.add_security(conn, "NEWCO", note="added at runtime")
    symbols = [s["symbol"] for s in fi_db.list_security_universe(conn)]
    assert "NEWCO" in symbols


def test_deactivate_security_is_non_destructive(conn):
    """Deactivation removes a symbol from active monitoring without deleting
    its row - matches this project's additive-only conventions."""
    target = fi_db.SECURITY_UNIVERSE_SEED[0]
    fi_db.deactivate_security(conn, target)

    assert target not in [s["symbol"] for s in fi_db.list_security_universe(conn)]
    all_rows = {s["symbol"]: s for s in fi_db.list_security_universe(conn, active_only=False)}
    assert all_rows[target]["active"] == 0


def test_re_adding_a_deactivated_security_reactivates_it(conn):
    target = fi_db.SECURITY_UNIVERSE_SEED[0]
    fi_db.deactivate_security(conn, target)
    fi_db.add_security(conn, target, note="back under monitoring")

    assert target in [s["symbol"] for s in fi_db.list_security_universe(conn)]


def test_seeding_is_idempotent_across_repeated_init(conn):
    """init_schema runs in every agent process, not just the server, so
    re-seeding must never duplicate rows or disturb existing assignments."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    name_before = fi_db.get_agent_name(conn, "dummy-1")

    fi_db.init_schema(conn)
    fi_db.init_schema(conn)

    assert fi_db.get_agent_name(conn, "dummy-1") == name_before
    assert len(fi_db.list_agent_names(conn)) == len(fi_db.AGENT_NAME_POOL) + 1
    assert len(fi_db.list_security_universe(conn)) == len(fi_db.SECURITY_UNIVERSE_SEED)


# --- Dormancy: retirement is non-destructive and reversible (addendum 11 §9) ---


def test_retirement_makes_agent_dormant_without_deleting_it(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")

    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent is not None, "retirement must never delete the agent row"
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT
    assert fi_db.is_retirement_requested(conn, "dummy-1") is True


def test_retirement_preserves_identity_name_and_history(conn):
    """The substance of "non-destructive": everything that makes the agent a
    durable organizational record survives retirement untouched."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")
    fi_db.record_heartbeat(conn, "dummy-1")
    name_before = fi_db.get_agent_name(conn, "dummy-1")
    spawned_before = fi_db.get_agent(conn, "dummy-1")["spawned_at"]

    fi_db.request_retirement(conn, "dummy-1")
    fi_db.mark_process_stopped(conn, "dummy-1")

    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["identity"] == "dummy-1"
    assert agent["role"] == "dummy"
    assert agent["spawned_at"] == spawned_before
    assert fi_db.get_agent_name(conn, "dummy-1") == name_before
    # health history is untouched
    card = {row["identity"]: row for row in fi_db.get_performance_card(conn)}
    assert card["dummy-1"]["heartbeat_count"] == 2


def test_resume_restores_an_agent_to_active_service(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.mark_process_stopped(conn, "dummy-1")

    fi_db.resume_agent(conn, "dummy-1")

    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_ACTIVE
    # resume clears the retire flag, or the next spawned process would
    # immediately wind itself back down
    assert fi_db.is_retirement_requested(conn, "dummy-1") is False
    # resume restores standing only - it does not start a process
    assert agent["process_state"] == fi_db.PROCESS_STOPPED


def test_resumed_agent_keeps_its_original_name_and_identity(conn):
    """Resume is a genuine restoration, not a fresh agent wearing the same
    slot - which is the difference between reversible dormancy and deletion
    plus recreation."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    name_before = fi_db.get_agent_name(conn, "dummy-1")
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.mark_process_stopped(conn, "dummy-1")

    fi_db.resume_agent(conn, "dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 222)  # the resumed process comes up

    assert fi_db.get_agent_name(conn, "dummy-1") == name_before
    assert fi_db.get_agent(conn, "dummy-1")["lifecycle_state"] == fi_db.LIFECYCLE_ACTIVE


def test_register_agent_does_not_silently_un_retire_a_dormant_agent(conn):
    """Registration reports process liveness; it is not a lifecycle decision.
    A dormant agent whose process somehow starts must stay dormant - only the
    Controller (resume_agent) can put it back in service."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.mark_process_stopped(conn, "dummy-1")

    fi_db.register_agent(conn, "dummy-1", "dummy", 222)

    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT
    assert agent["process_state"] == fi_db.PROCESS_RUNNING


def test_derived_status_stays_coherent_with_both_axes(conn):
    """`status` is legacy and derived - it must never drift from the two
    real axes, whichever path wrote the row."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    assert fi_db.get_agent(conn, "dummy-1")["status"] == "active"

    fi_db.mark_process_crashed(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["status"] == "crashed"

    fi_db.request_retirement(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["status"] == "dormant"

    fi_db.resume_agent(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["status"] == "gone"  # active but no process


# --- Intelligence artifacts: lenses that can be attributed and can expire ---
# (JARVIS Constitution §3/§7; gap analysis §4.11)


def _graded_report(conn, lens_artifact_id, overall_score, worth_the_compute,
                   producer="explorer-1", detector_event_id=None):
    """A report produced by a lens, consumed and graded - the full chain the
    attribution query has to traverse."""
    report_id = fi_db.enqueue_report(
        conn, producer, "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        detector_event_id=detector_event_id, lens_artifact_id=lens_artifact_id,
    )
    fi_db.complete_report(conn, report_id, "analyzed",
                          handled_by_identity="analysis-1", handled_by_spawned_at="2026-01-01T00:01:00+00:00")
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, "SYN1",
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    fi_db.record_grade(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, result_id,
        relevance_score=overall_score, novelty_score=overall_score,
        evidence_quality_score=overall_score, worth_the_compute=worth_the_compute,
        overall_score=overall_score, rationale="r",
    )
    return report_id


def test_both_lenses_are_seeded_active(conn):
    lenses = fi_db.list_intelligence_artifacts(conn, artifact_kind=fi_db.LENS_KIND)
    names = {a["name"]: a for a in lenses}
    assert set(names) == {fi_db.LENS_IV_RATIO_NAME, fi_db.LENS_SPECULATOR_CONFIDENCE_NAME}
    assert all(a["status"] == "active" for a in lenses)


def test_seeded_lens_carries_rationale_and_validity_conditions(conn):
    """A lens is intelligence, not configuration - it has to say where it came
    from and what would invalidate it (Constitution §7)."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    assert lens["rationale"]
    conditions = json.loads(lens["validity_conditions"])
    assert conditions["min_graded_reports"] > 0
    # the unbuilt half of "intelligence expires" is recorded, not omitted
    assert "regime" in conditions


def test_get_active_artifact_value_decodes_the_seed(conn):
    assert fi_db.get_active_artifact_value(conn, fi_db.LENS_IV_RATIO_NAME) == fi_db.LENS_IV_RATIO_SEED


def test_get_active_artifact_returns_none_for_unknown_name(conn):
    assert fi_db.get_active_artifact(conn, "no-such-lens") is None
    assert fi_db.get_active_artifact_value(conn, "no-such-lens", default=1.5) == 1.5


def test_artifact_seeding_is_idempotent_and_non_destructive(conn):
    """init_schema runs in every agent process. Re-seeding must never
    resurrect or overwrite a lens that has since been marked stale."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.mark_artifact_stale(conn, lens["id"], "test")

    fi_db.init_schema(conn)
    fi_db.init_schema(conn)

    assert len(fi_db.list_intelligence_artifacts(conn, artifact_kind=fi_db.LENS_KIND)) == 2
    assert fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME) is None  # stayed stale


def test_mark_artifact_stale_records_evidence_without_changing_the_value(conn):
    """The central constraint: flagging is evidence-gathering, not
    self-modification (addendum 13 §14)."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    original_value = lens["value"]

    fi_db.mark_artifact_stale(conn, lens["id"], "grades say otherwise")

    row = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (lens["id"],))
    assert row["status"] == "stale"
    assert row["staleness_reason"] == "grades say otherwise"
    assert row["stale_at"] is not None
    assert row["value"] == original_value


def test_supersede_artifact_links_forward_without_deleting(conn):
    """"Track intellectual evolution" (§8) is impossible if superseded
    intelligence is thrown away."""
    old = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    new_id = fi_db.record_intelligence_artifact(
        conn, fi_db.LENS_KIND, fi_db.LENS_IV_RATIO_NAME, 2.5,
        rationale="revised after evidence", version=2,
    )
    fi_db.supersede_artifact(conn, old["id"], new_id)

    old_row = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (old["id"],))
    assert old_row is not None, "superseded intelligence must never be deleted"
    assert old_row["status"] == "superseded"
    assert old_row["superseded_by"] == new_id
    assert fi_db.get_active_artifact_value(conn, fi_db.LENS_IV_RATIO_NAME) == 2.5


def test_lens_performance_reports_zero_evidence_cleanly(conn):
    """"No evidence" must be distinguishable from "bad evidence" - COO relies
    on this to refuse judging a lens on thin data."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    performance = fi_db.lens_performance(conn, lens["id"])
    assert performance["graded_reports"] == 0
    assert performance["mean_overall_score"] is None


def test_lens_performance_attributes_grades_back_to_the_lens(conn):
    """The join that closes the previously-severed loop."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    _graded_report(conn, lens["id"], 0.8, True)
    _graded_report(conn, lens["id"], 0.4, False)

    performance = fi_db.lens_performance(conn, lens["id"])
    assert performance["graded_reports"] == 2
    assert performance["mean_overall_score"] == pytest.approx(0.6)
    assert performance["worth_the_compute_rate"] == pytest.approx(0.5)


def test_lens_performance_works_for_speculator_reports_with_no_detector_event(conn):
    """The case that decided where lens_artifact_id lives: Speculator reports
    carry no detector event, so attribution had to hang off the report itself
    or it would need two different paths."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_SPECULATOR_CONFIDENCE_NAME)
    report_id = fi_db.enqueue_report(
        conn, "speculator-1", "2026-01-01T00:00:00+00:00", "speculator", "SYN1",
        detector_event_id=None, evidence_ids=[1], lens_artifact_id=lens["id"],
    )
    fi_db.complete_report(conn, report_id, "analyzed",
                          handled_by_identity="analysis-1", handled_by_spawned_at="2026-01-01T00:01:00+00:00")
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, "SYN1",
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    fi_db.record_grade(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, result_id,
        relevance_score=0.7, novelty_score=0.7, evidence_quality_score=0.7,
        worth_the_compute=True, overall_score=0.7, rationale="r",
    )

    performance = fi_db.lens_performance(conn, lens["id"])
    assert performance["graded_reports"] == 1
    assert performance["mean_overall_score"] == pytest.approx(0.7)


def test_lens_artifact_id_survives_report_archival(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    _graded_report(conn, lens["id"], 0.6, True)
    completed = fi_db.list_completed_reports(conn)
    assert completed[0]["lens_artifact_id"] == lens["id"]


def test_detector_event_records_the_lens_that_produced_it(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0, lens_artifact_id=lens["id"],
    )
    assert fi_db.get_detector_event(conn, event_id)["lens_artifact_id"] == lens["id"]


# --- market regime: a current-state estimate, not a log ---


def test_first_regime_observation_seeds_rather_than_blending(conn):
    """Blending the first observation against a zero that was never observed
    would start the estimate wrong and take dozens of cycles to recover -
    and any early drift check would be measuring the seeding artifact."""
    fi_db.update_market_regime(conn, "SYN1", 0.2855, 0.0116)
    row = fi_db.get_market_regime(conn, "SYN1")
    assert row["mean_iv"] == pytest.approx(0.2855)
    assert row["iv_dispersion"] == pytest.approx(0.0116)
    assert row["observation_count"] == 1


def test_regime_observations_blend_and_never_add_rows(conn):
    for _ in range(50):
        fi_db.update_market_regime(conn, "SYN1", 0.30, 0.01)
    assert len(fi_db.list_market_regime(conn)) == 1  # bounded: one row per security
    assert fi_db.get_market_regime(conn, "SYN1")["observation_count"] == 50


def test_regime_ewma_migrates_toward_a_sustained_shift_without_jumping(conn):
    fi_db.update_market_regime(conn, "SYN1", 0.2855, 0.0116)
    fi_db.update_market_regime(conn, "SYN1", 0.4850, 0.0263)
    after_one = fi_db.get_market_regime(conn, "SYN1")["mean_iv"]
    assert after_one < 0.31  # one high reading barely moves it

    for _ in range(40):
        fi_db.update_market_regime(conn, "SYN1", 0.4850, 0.0263)
    after_many = fi_db.get_market_regime(conn, "SYN1")["mean_iv"]
    assert after_many > 0.44  # a sustained shift does move it


def test_current_market_characterization_averages_across_securities(conn):
    fi_db.update_market_regime(conn, "SYN1", 0.20, 0.010)
    fi_db.update_market_regime(conn, "SYN2", 0.40, 0.030)
    characterization = fi_db.current_market_characterization(conn)
    assert characterization["mean_iv"] == pytest.approx(0.30)
    assert characterization["iv_dispersion"] == pytest.approx(0.020)
    # total evidence, so the thin-data guard reflects everything gathered
    assert characterization["observation_count"] == 2
    assert characterization["securities"] == 2


def test_current_market_characterization_can_be_scoped_to_securities(conn):
    fi_db.update_market_regime(conn, "SYN1", 0.20, 0.010)
    fi_db.update_market_regime(conn, "SYN2", 0.40, 0.030)
    scoped = fi_db.current_market_characterization(conn, ["SYN1"])
    assert scoped["mean_iv"] == pytest.approx(0.20)
    assert scoped["securities"] == 1


def test_current_market_characterization_with_no_observations(conn):
    characterization = fi_db.current_market_characterization(conn)
    assert characterization["mean_iv"] is None
    assert characterization["observation_count"] == 0


def test_bind_lens_to_regime_records_conditions_and_when(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    assert json.loads(lens["validity_conditions"])["regime"]["observed_under"] is None

    fi_db.update_market_regime(conn, "SYN1", 0.2855, 0.0116)
    fi_db.bind_lens_to_regime(conn, lens["id"], fi_db.current_market_characterization(conn))

    regime = json.loads(fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)["validity_conditions"])["regime"]
    assert regime["observed_under"]["mean_iv"] == pytest.approx(0.2855)
    assert regime["observed_under"]["iv_dispersion"] == pytest.approx(0.0116)
    assert regime["bound_at"] is not None
    # binding must not disturb the tolerances it will later be judged against
    assert regime["max_mean_iv_drift"] == fi_db.DEFAULT_MARKET_REGIME_CONDITIONS["max_mean_iv_drift"]


def test_bind_lens_to_regime_leaves_performance_conditions_intact(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.update_market_regime(conn, "SYN1", 0.2855, 0.0116)
    fi_db.bind_lens_to_regime(conn, lens["id"], fi_db.current_market_characterization(conn))

    conditions = json.loads(fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)["validity_conditions"])
    assert conditions["min_graded_reports"] == fi_db.DEFAULT_LENS_VALIDITY_CONDITIONS["min_graded_reports"]


def test_only_the_market_lens_carries_regime_conditions(conn):
    """The speculator's bar looks at social confidence, and nothing here
    characterizes a social regime - attaching market conditions to it would
    let market volatility invalidate a social lens on no evidence."""
    market = json.loads(fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)["validity_conditions"])
    social = json.loads(fi_db.get_active_artifact(conn, fi_db.LENS_SPECULATOR_CONFIDENCE_NAME)["validity_conditions"])
    assert "regime" in market
    assert "regime" not in social


# --- Explorer<->Speculator cross-checks (addendum 12 section 14) ---


def _open(conn, security="SYN1", requester="explorer-1", finding=None):
    return fi_db.open_cross_check(
        conn, requester, "2026-01-01T00:00:00+00:00", "explorer", "speculator", security,
        question=f"Does social evidence corroborate an IV dislocation on {security}?",
        requester_finding=finding or {"ratio": 2.21}, requester_confidence=0.8,
    )


def test_cross_check_records_the_requesters_own_finding_before_asking(conn):
    """"Investigate independently first, then cross-check." The finding is
    captured at open time - if it were recorded after the answer arrived the
    two views would no longer be independent."""
    request_id = _open(conn, finding={"ratio": 2.21, "peak_iv": 0.688})
    row = fi_db.get_cross_check(conn, request_id)
    assert json.loads(row["requester_finding"])["ratio"] == 2.21
    assert row["responder_finding"] is None  # nothing from the other side yet


def test_cross_check_is_routed_by_responder_role(conn):
    _open(conn)
    assert fi_db.fetch_next_pending_cross_check(conn, "speculator") is not None
    assert fi_db.fetch_next_pending_cross_check(conn, "explorer") is None


def test_open_cross_check_blocks_re_asking_the_same_security(conn):
    _open(conn, security="SYN1")
    assert fi_db.has_open_cross_check(conn, "explorer-1", "SYN1")
    assert not fi_db.has_open_cross_check(conn, "explorer-1", "SYN2")


def test_consuming_an_answer_makes_the_security_askable_again(conn):
    request_id = _open(conn)
    fi_db.answer_cross_check(conn, request_id, "speculator-1", "T1",
                             fi_db.CROSS_CHECK_EVIDENCE, {"posts": 6})
    assert fi_db.has_open_cross_check(conn, "explorer-1", "SYN1")  # answered but unacted
    fi_db.consume_cross_check(conn, request_id)
    assert not fi_db.has_open_cross_check(conn, "explorer-1", "SYN1")


def test_answered_request_carries_both_findings_unreconciled(conn):
    """Disagreement is preserved rather than erased - both sides survive as
    stated, and nothing collapses them into a verdict."""
    request_id = _open(conn, finding={"ratio": 2.21})
    fi_db.answer_cross_check(conn, request_id, "speculator-1", "T1",
                             fi_db.CROSS_CHECK_EVIDENCE,
                             {"posts": 26, "authors": 25, "reads_as": "explains the move away"}, 0.8)
    row = fi_db.get_cross_check(conn, request_id)
    assert json.loads(row["requester_finding"])["ratio"] == 2.21
    assert json.loads(row["responder_finding"])["reads_as"] == "explains the move away"
    # the responder reports what it saw; it does not declare agreement
    assert row["outcome"] == fi_db.CROSS_CHECK_EVIDENCE


def test_no_evidence_is_a_real_answer_not_a_failure(conn):
    """A responder that looked and found nothing has said something
    informative, and it is a different finding from disagreement."""
    request_id = _open(conn)
    fi_db.answer_cross_check(conn, request_id, "speculator-1", "T1",
                             fi_db.CROSS_CHECK_NO_EVIDENCE, {"posts": 0})
    row = fi_db.get_cross_check(conn, request_id)
    assert row["outcome"] == fi_db.CROSS_CHECK_NO_EVIDENCE
    assert row["status"] == fi_db.CROSS_CHECK_RESOLVED  # resolved, not left pending


def test_unanswered_request_expires_so_the_requester_is_never_stalled(conn):
    """A dormant or crashed responder must not silently halt the other agent's
    pipeline - the same class of defect as a retirement that quietly does
    nothing."""
    request_id = _open(conn)
    assert fi_db.expire_stale_cross_checks(conn, timeout_seconds=0) == 1
    row = fi_db.get_cross_check(conn, request_id)
    assert row["outcome"] == fi_db.CROSS_CHECK_UNANSWERED
    assert row["status"] == fi_db.CROSS_CHECK_RESOLVED


def test_expiry_leaves_fresh_requests_alone(conn):
    _open(conn)
    assert fi_db.expire_stale_cross_checks(conn, timeout_seconds=3600) == 0
    assert fi_db.fetch_next_pending_cross_check(conn, "speculator") is not None


def test_answering_an_already_resolved_request_is_a_noop(conn):
    """Two responder processes racing on the same question must not overwrite
    each other - the guard is the status check in the UPDATE."""
    request_id = _open(conn)
    fi_db.answer_cross_check(conn, request_id, "speculator-1", "T1",
                             fi_db.CROSS_CHECK_EVIDENCE, {"posts": 6})
    fi_db.answer_cross_check(conn, request_id, "speculator-2", "T2",
                             fi_db.CROSS_CHECK_NO_EVIDENCE, {"posts": 0})
    row = fi_db.get_cross_check(conn, request_id)
    assert row["responder_identity"] == "speculator-1"
    assert row["outcome"] == fi_db.CROSS_CHECK_EVIDENCE


def test_pending_cross_checks_are_served_oldest_first_by_id(conn):
    """Ordered by id, not created_at - millisecond ties caused a real bug in
    the spawn-directive path."""
    first = _open(conn, security="SYN1")
    _open(conn, security="SYN2")
    assert fi_db.fetch_next_pending_cross_check(conn, "speculator")["id"] == first


# --- prioritised report queue (gap analysis section 4.3b) ---


def _answered_cross_check(conn, security, outcome=None):
    request_id = fi_db.open_cross_check(
        conn, "explorer-1", "T", "explorer", "speculator", security,
        question="q", requester_finding={"ratio": 2.2},
    )
    if outcome == "timeout":
        fi_db.expire_stale_cross_checks(conn, timeout_seconds=0)
    elif outcome is not None:
        fi_db.answer_cross_check(conn, request_id, "speculator-1", "T", outcome, {"posts": 3})
    return request_id


def test_prioritised_queue_puts_the_best_evidenced_lead_first(conn):
    answered = _answered_cross_check(conn, "SYN1", fi_db.CROSS_CHECK_EVIDENCE)
    timed_out = _answered_cross_check(conn, "SYN2", "timeout")
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN2", cross_check_id=timed_out)
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1", cross_check_id=answered)

    queue = fi_db.prioritised_pending_reports(conn)

    assert [r["security"] for r in queue] == ["SYN1", "SYN2"]
    assert fi_db.fetch_prioritised_report(conn)["security"] == "SYN1"


def test_every_queued_report_carries_its_triage_reason_and_age(conn):
    """The first report for a security the system has never seen is genuinely
    unprecedented, so novelty - which outranks evidence completeness - is the
    honest reason it sits where it does."""
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1")
    row = fi_db.prioritised_pending_reports(conn)[0]
    assert "unprecedented" in row["triage_reason"]
    assert row["novelty"]["is_novel"] is True
    assert row["waiting_seconds"] >= 0


def test_a_familiar_lead_falls_back_to_the_evidence_reason(conn):
    """Once a security has history, novelty stops firing and the ranking is
    decided by how well-evidenced the lead is - so the two inputs are visibly
    distinct rather than one always masking the other."""
    fi_db.record_detector_event(conn, "explorer-1", "T", "SYN1", "iv_surface_peak_ratio",
                                0.6, 0.3, 2.2, 2.0)
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1")

    row = fi_db.prioritised_pending_reports(conn)[0]

    assert row["novelty"]["is_novel"] is False
    assert row["triage_reason"] == "no cross-check on this lead"


def test_prioritisation_never_drops_a_report(conn):
    """Reordering must be exactly that. A ranking that silently omitted rows
    would look like prioritisation and behave like data loss."""
    for i in range(5):
        fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", f"SYN{i}")
    assert len(fi_db.prioritised_pending_reports(conn)) == 5


def test_the_starvation_guard_reaches_reports_the_ranking_would_bury(conn):
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN9")  # no cross-check, ranks last
    answered = _answered_cross_check(conn, "SYN1", fi_db.CROSS_CHECK_EVIDENCE)
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1", cross_check_id=answered)

    assert fi_db.fetch_prioritised_report(conn)["security"] == "SYN1"
    # with a zero-second guard everything counts as starving, oldest first
    assert fi_db.fetch_prioritised_report(conn, starvation_seconds=0)["security"] == "SYN9"


def test_an_empty_queue_returns_nothing_rather_than_raising(conn):
    assert fi_db.prioritised_pending_reports(conn) == []
    assert fi_db.fetch_prioritised_report(conn) is None
