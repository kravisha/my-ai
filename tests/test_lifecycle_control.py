"""Tests for operator lifecycle control (addendum 11 §15, addendum 14 §7).

The property under test throughout: the panel and its routes never change
lifecycle state. They file a directive and the Controller executes it. A route
that wrote lifecycle_state itself would make the backend a second executor and
quietly end §15's exclusive-executor guarantee.
"""

from backend import fi_db


def _register(conn, identity="explorer-1", role="explorer"):
    fi_db.register_agent(conn, identity, role, 4242)
    return identity


def test_retiring_files_a_directive_rather_than_changing_state(panel_client, panel_conn):
    """The route must not touch lifecycle_state. Nothing changes until the
    Controller acts on the directive."""
    _register(panel_conn)

    body = panel_client.post(
        "/admin/agents/explorer-1/retire", json={"reason": "operator test"}
    ).json()

    assert body["executed_by"] == "controller"
    assert fi_db.get_agent(panel_conn, "explorer-1")["lifecycle_state"] == fi_db.LIFECYCLE_ACTIVE
    directive = fi_db.get_directive(panel_conn, body["directive_id"])
    assert directive["directive_type"] == "retire"
    assert directive["target_identity"] == "explorer-1"
    assert directive["status"] == "pending"


def test_the_directive_records_who_asked_and_why(panel_client, panel_conn):
    """Auditability comes free from routing through the directive queue."""
    _register(panel_conn)

    body = panel_client.post(
        "/admin/agents/explorer-1/retire",
        json={"reason": "suspected drift", "requested_by": "krish"},
    ).json()

    directive = fi_db.get_directive(panel_conn, body["directive_id"])
    assert directive["requested_by"] == "krish"
    assert directive["reason"] == "suspected drift"


def test_the_controller_is_the_one_that_actually_executes(panel_client, panel_conn, tmp_path):
    """End to end through the real executor: file a directive, let the
    Controller process it, and only then does standing change."""
    from backend.controller import Controller

    _register(panel_conn)
    body = panel_client.post("/admin/agents/explorer-1/retire", json={"reason": "test"}).json()

    controller = Controller(db_path=str(tmp_path / "panel.db"))
    try:
        assert controller.process_next_directive() is True
    finally:
        controller.close()

    assert fi_db.get_agent(panel_conn, "explorer-1")["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT
    assert fi_db.get_directive(panel_conn, body["directive_id"]) is None  # archived on completion


def test_the_controller_cannot_be_asked_to_retire_itself(panel_client, panel_conn):
    """controller-1 appears in the roster like any other agent and the panel
    offers the same button for every row - so this footgun is reachable, not
    theoretical. The Controller *is* the server process."""
    _register(panel_conn, "controller-1", "controller")

    response = panel_client.post("/admin/agents/controller-1/retire", json={"reason": "oops"})

    assert response.status_code == 400
    assert "cannot retire itself" in response.json()["detail"]


def test_retiring_an_already_dormant_agent_is_refused(panel_client, panel_conn):
    _register(panel_conn)
    fi_db.request_retirement(panel_conn, "explorer-1")

    response = panel_client.post("/admin/agents/explorer-1/retire", json={"reason": "again"})

    assert response.status_code == 409
    assert "already dormant" in response.json()["detail"]


def test_resuming_an_active_agent_is_refused(panel_client, panel_conn):
    _register(panel_conn)
    response = panel_client.post("/admin/agents/explorer-1/resume", json={"reason": "unnecessary"})
    assert response.status_code == 409


def test_resuming_a_dormant_agent_files_a_resume_directive(panel_client, panel_conn):
    _register(panel_conn)
    fi_db.request_retirement(panel_conn, "explorer-1")

    body = panel_client.post("/admin/agents/explorer-1/resume", json={"reason": "back to work"}).json()

    assert fi_db.get_directive(panel_conn, body["directive_id"])["directive_type"] == "resume"


def test_acting_on_an_unknown_agent_is_404(panel_client):
    assert panel_client.post("/admin/agents/ghost-9/retire", json={"reason": "x"}).status_code == 404
    assert panel_client.post("/admin/agents/ghost-9/resume", json={"reason": "x"}).status_code == 404


def test_directives_route_exposes_pending_and_completed(panel_client, panel_conn):
    _register(panel_conn)
    panel_client.post("/admin/agents/explorer-1/retire", json={"reason": "audit me"})

    body = panel_client.get("/admin/directives").json()

    assert body["pending"][0]["reason"] == "audit me"
    assert "completed" in body


def test_coo_does_not_grade_operator_directives_as_its_own(panel_conn):
    """COO evaluates *its own* decisions. Grading someone else's choice as
    though it were COO's would corrupt the decision history that
    _evaluate_past_decisions exists to build."""
    coo_id = fi_db.enqueue_directive(panel_conn, "spawn", requested_by="coo", target_role="dummy")
    operator_id = fi_db.enqueue_directive(panel_conn, "spawn", requested_by="operator", target_role="dummy")
    for directive_id in (coo_id, operator_id):
        fi_db.complete_directive(panel_conn, directive_id, "success", detail="dummy-1")

    needing = fi_db.list_directives_needing_observation(panel_conn, grace_seconds=0)

    assert [d["requested_by"] for d in needing] == ["coo"]
