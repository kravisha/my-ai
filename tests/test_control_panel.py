"""Tests for the Controller control-panel routes (addendum 14 §6-§7).

Read-only observability over the agent organization. Every test drives the real
FastAPI app with panel_db overridden onto a temporary database.
"""

import pytest

from backend import fi_db


def test_agents_route_reports_both_axes_separately(panel_client, panel_conn):
    """The two-axis model is the point. A panel that merged lifecycle and
    process state into one status would reintroduce exactly the confusion that
    separating them exists to remove."""
    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    fi_db.record_heartbeat(panel_conn, "explorer-1")

    agent = panel_client.get("/admin/agents").json()["agents"][0]

    assert agent["lifecycle_state"] == "active"
    assert agent["process_state"] == "running"
    assert agent["heartbeat_age_seconds"] is not None


def test_a_dormant_agent_is_visibly_dormant_not_missing(panel_client, panel_conn):
    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    fi_db.request_retirement(panel_conn, "explorer-1")

    agent = panel_client.get("/admin/agents").json()["agents"][0]

    assert agent["lifecycle_state"] == "dormant"
    assert agent["retire_requested"] is True


def test_self_description_answers_the_alpha_questions(panel_client, panel_conn):
    """Addendum 14 §6 - identity, role, responsibilities, permissions,
    prohibitions, state."""
    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    fi_db.record_heartbeat(panel_conn, "explorer-1")

    body = panel_client.get("/admin/agents/explorer-1").json()

    assert body["identity"] == "explorer-1"
    assert body["role"] == "explorer"
    assert body["agent_type"] == "discovery"
    assert body["responsibilities"] and body["allowed"] and body["not_allowed"]
    assert body["lifecycle_state"] == "active"
    assert body["healthy"] is True


def test_self_description_is_labelled_as_the_record_not_the_agent_speaking(panel_client, panel_conn):
    """The database answering on an agent's behalf is not the agent answering.
    Labelling it is what stops the panel presenting one as the other."""
    fi_db.register_agent(panel_conn, "coo-1", "coo", 1)
    assert panel_client.get("/admin/agents/coo-1").json()["answered_by"] == "organizational_record"


def test_self_description_never_invents_a_current_task(panel_client, panel_conn):
    """The system records heartbeats, not task spans. Claiming to know which
    task is in flight would be a fabrication."""
    fi_db.register_agent(panel_conn, "analysis-1", "analysis", 7)
    fi_db.record_heartbeat(panel_conn, "analysis-1")
    assert panel_client.get("/admin/agents/analysis-1").json()["current_task"] is None


def test_a_stale_heartbeat_reports_unhealthy_despite_an_active_row(panel_client, panel_conn):
    """Health follows the process, not the row. An agent whose registry entry
    still says active but which stopped reporting is not healthy, and saying so
    is the entire value of the field."""
    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    panel_conn.execute(
        "UPDATE agent_registry SET last_heartbeat_at = ? WHERE identity = ?",
        ("2020-01-01T00:00:00+00:00", "explorer-1"),
    )
    assert panel_client.get("/admin/agents/explorer-1").json()["healthy"] is False


def test_a_dormant_agent_reports_neither_healthy_nor_unhealthy(panel_client, panel_conn):
    """Health is a claim about a running process. A deliberately stood-down
    agent has none, and reporting False would read as a fault."""
    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    fi_db.request_retirement(panel_conn, "explorer-1")
    body = panel_client.get("/admin/agents/explorer-1").json()
    assert body["healthy"] is None
    assert body["working"] is None


def test_unknown_agent_is_404_not_an_empty_shell(panel_client):
    assert panel_client.get("/admin/agents/nobody-9").status_code == 404


def test_every_baseline_role_has_a_charter():
    """A role without a charter would answer §6 with empty lists - technically
    a response, substantively a failure."""
    from agents.coo import BASELINE_ROLES

    for role in list(BASELINE_ROLES) + ["coo", "controller"]:
        assert role in fi_db.ROLE_CHARTERS, f"{role} has no charter"
        charter = fi_db.ROLE_CHARTERS[role]
        assert charter["responsibilities"]
        assert charter["not_allowed"]


def test_intelligence_route_includes_stale_lenses(panel_client, panel_conn):
    """A lens that expired is the most informative row in the table - it is the
    system having noticed something. Showing only active ones would leave the
    panel displaying exclusively what still looks fine."""
    lens = fi_db.get_active_artifact(panel_conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.mark_artifact_stale(panel_conn, lens["id"], "regime diverged")

    stale = [a for a in panel_client.get("/admin/intelligence").json()["artifacts"]
             if a["status"] == "stale"]
    assert stale and stale[0]["staleness_reason"] == "regime diverged"


def test_intelligence_route_surfaces_the_bound_regime(panel_client, panel_conn):
    lens = fi_db.get_active_artifact(panel_conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.update_market_regime(panel_conn, "SYN1", 0.2855, 0.0116)
    fi_db.bind_lens_to_regime(panel_conn, lens["id"], fi_db.current_market_characterization(panel_conn))

    artifact = [a for a in panel_client.get("/admin/intelligence").json()["artifacts"]
                if a["name"] == fi_db.LENS_IV_RATIO_NAME][0]
    assert artifact["observed_under_regime"]["mean_iv"] == pytest.approx(0.2855)
    assert artifact["regime_bound_at"] is not None


def test_regime_route_reports_per_security_and_market_wide(panel_client, panel_conn):
    fi_db.update_market_regime(panel_conn, "SYN1", 0.20, 0.010)
    fi_db.update_market_regime(panel_conn, "SYN2", 0.40, 0.030)

    body = panel_client.get("/admin/regime").json()

    assert len(body["securities"]) == 2
    assert body["market_wide"]["mean_iv"] == pytest.approx(0.30)


def test_cross_checks_route_returns_both_findings_and_no_verdict(panel_client, panel_conn):
    """Collapsing two findings into agreed/disagreed here would erase the
    disagreement the table exists to preserve."""
    request_id = fi_db.open_cross_check(
        panel_conn, "explorer-1", "T0", "explorer", "speculator", "SYN3",
        question="Is there contextual evidence?", requester_finding={"ratio": 2.19},
    )
    fi_db.answer_cross_check(panel_conn, request_id, "speculator-1", "T1", fi_db.CROSS_CHECK_EVIDENCE,
                             {"posts": 36, "distinct_authors": 3, "stance": "supports"})

    row = panel_client.get("/admin/cross-checks").json()["cross_checks"][0]

    assert row["requester_finding"]["ratio"] == 2.19
    assert row["responder_finding"]["distinct_authors"] == 3
    assert row["outcome"] == "evidence"
    assert "agreed" not in row and "verdict" not in row


def test_cross_checks_route_parses_json_rather_than_returning_strings(panel_client, panel_conn):
    fi_db.open_cross_check(panel_conn, "explorer-1", "T0", "explorer", "speculator", "SYN1",
                           question="q", requester_finding={"ratio": 2.2})
    row = panel_client.get("/admin/cross-checks").json()["cross_checks"][0]
    assert isinstance(row["requester_finding"], dict)
    assert row["responder_finding"] is None  # unanswered, not an empty dict


def test_discovery_route_shows_the_pending_queue(panel_client, panel_conn):
    fi_db.enqueue_report(panel_conn, "explorer-1", "T0", "explorer", "SYN1", summary="anomaly")
    body = panel_client.get("/admin/discovery").json()
    assert body["pending_reports"][0]["security"] == "SYN1"
    assert "performance_card" in body


def test_panel_routes_are_read_only(panel_client, panel_conn):
    """Lifecycle actions belong to the Controller alone (addendum 11 §15). The
    observability layer must not quietly acquire them."""
    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    before = [dict(a) for a in fi_db.list_agents(panel_conn)]

    for path in ("/admin/agents", "/admin/agents/explorer-1", "/admin/intelligence",
                 "/admin/regime", "/admin/cross-checks", "/admin/discovery"):
        assert panel_client.get(path).status_code == 200

    assert [dict(a) for a in fi_db.list_agents(panel_conn)] == before
