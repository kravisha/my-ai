"""Unit tests for backend/fi_db.py - the SQLite coordination substrate for
the Financial Intelligence system. Pure DB logic, fully hermetic (in-memory
SQLite, no real processes) - the real-subprocess integration test lives
separately in tests/test_controller.py, per the plan's deliberate testing
split.
"""

import json

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


def test_mark_agent_gone_updates_status(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_gone(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["status"] == "gone"


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


def test_mark_agent_crashed_is_distinct_from_gone(conn):
    """Gap 3 (project brief): restart-vs-crash distinction - 'crashed'
    (detected by COO's health evaluation) must be a different status from
    'gone' (the agent's own clean exit), not collapsed into the same value."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_crashed(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["status"] == "crashed"


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


def test_list_stale_active_agents_excludes_non_active_status(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_gone(conn, "dummy-1")
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
