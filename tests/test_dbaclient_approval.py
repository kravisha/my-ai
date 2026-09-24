"""RevA: gateway/dbaclient approval methods against the REAL DBA app.

The transport is a TestClient over dba.main (no lifespan, temp DB), so these
assert the live interface rather than this client's belief about it - the
reason `DBAClient` takes a transport at all.
"""

from __future__ import annotations

import json

import pytest

from backend.db import Database
from dba import approval, store
from gateway import dbaclient

TREE = "git-tree:" + "a" * 40 + "@base:" + "b" * 40
TOKENS = {"JARVIS": "tok-jarvis", "operator_console": "tok-operator"}


@pytest.fixture
def service(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from dba.main import app
    path = tmp_path / "dba.db"
    monkeypatch.setenv(store.PATH_ENV, str(path))
    for agent, token in TOKENS.items():
        monkeypatch.setenv(f"DBA_TOKEN_{agent.upper()}", token)
    conn = Database(path)
    store.init_schema(conn)
    approval.init_schema(conn)
    conn.execute(
        "INSERT INTO entities (id, entity_type, name, status, data_json, created_at, "
        "updated_at) VALUES ('ent-p1', 'change_proposal', 'p', 'approved', ?, "
        "'2026-09-24T00:00:00Z', '2026-09-24T00:00:00Z')",
        (json.dumps({"reason": "r", "scope": "s"}),))
    conn.close()
    return TestClient(app), path


def _client(service, agent, token=None):
    http = service[0]

    def transport(method, path, payload):
        r = http.request(method, path, json=payload if method != "GET" else None,
                         headers={"X-DBA-Agent": agent,
                                  "X-DBA-Token": token or TOKENS[agent]})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    return dbaclient.DBAClient(transport=transport, requested_by=agent)


def _status(path):
    conn = Database(path)
    row = conn.fetchone("SELECT status FROM entities WHERE id = 'ent-p1'")
    conn.close()
    return row["status"]


def test_jarvis_freezes_through_the_typed_method(service):
    out = _client(service, "JARVIS").freeze_candidate(
        request_id="rq-f", proposal_id="ent-p1", candidate_artifact=TREE)
    assert out["replayed"] is False
    assert out["data"]["content_digest"].startswith("digest_v1:")
    assert _status(service[1]) == "awaiting_execution_approval"
    again = _client(service, "JARVIS").freeze_candidate(
        request_id="rq-f", proposal_id="ent-p1", candidate_artifact=TREE)
    assert again["replayed"] is True


def test_the_jarvis_client_has_no_approve_method():
    """Least privilege in the client's shape too (Arya 5818448805)."""
    assert not hasattr(dbaclient.DBAClient, "approve_change")


def test_jarvis_cannot_approve_even_through_the_generic_call(service):
    jarvis = _client(service, "JARVIS")
    digest = jarvis.freeze_candidate(request_id="rq-f", proposal_id="ent-p1",
                                     candidate_artifact=TREE)["data"]["content_digest"]
    with pytest.raises(dbaclient.Refused) as refused:
        jarvis.approval("approve_change", request_id="rq-a", proposal_id="ent-p1",
                        confirmed_digest=digest, decision="approve")
    assert refused.value.code == approval.PERMISSION_DENIED
    assert _status(service[1]) == "awaiting_execution_approval"


def test_the_operator_can_approve_through_the_generic_call(service):
    digest = _client(service, "JARVIS").freeze_candidate(
        request_id="rq-f", proposal_id="ent-p1", candidate_artifact=TREE)["data"]["content_digest"]
    out = _client(service, "operator_console").approval(
        "approve_change", request_id="rq-a", proposal_id="ent-p1",
        confirmed_digest=digest, decision="approve")
    assert out["data"]["decision_id"].startswith("dec-")
    assert _status(service[1]) == "approved_for_execution"


def test_a_state_refusal_is_refused_with_its_code(service):
    jarvis = _client(service, "JARVIS")
    jarvis.freeze_candidate(request_id="rq-f", proposal_id="ent-p1", candidate_artifact=TREE)
    with pytest.raises(dbaclient.Refused) as refused:
        jarvis.freeze_candidate(request_id="rq-f2", proposal_id="ent-p1",
                                candidate_artifact=TREE)
    assert refused.value.code == approval.WRONG_STATE


def test_bad_credentials_are_unavailable_not_refused(service):
    with pytest.raises(dbaclient.Unavailable):
        _client(service, "JARVIS", token="wrong").freeze_candidate(
            request_id="rq", proposal_id="ent-p1", candidate_artifact=TREE)
    assert _status(service[1]) == "approved"


def test_a_server_fault_is_unavailable_with_unknown_outcome_not_a_refusal(service, monkeypatch):
    """Arya 5818622167: keep HTTP 500 distinct from a structured refusal."""
    from fastapi.testclient import TestClient

    from dba.main import app

    def boom(*a, **k):
        raise RuntimeError("injected fault")
    monkeypatch.setattr(approval, "freeze_candidate", boom)
    monkeypatch.setitem(approval.OPERATIONS, "freeze_candidate",
                        (boom,) + approval.OPERATIONS["freeze_candidate"][1:])
    http = TestClient(app, raise_server_exceptions=False)

    def transport(method, path, payload):
        r = http.request(method, path, json=payload,
                         headers={"X-DBA-Agent": "JARVIS", "X-DBA-Token": TOKENS["JARVIS"]})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    with pytest.raises(dbaclient.Unavailable) as err:
        dbaclient.DBAClient(transport=transport).freeze_candidate(
            request_id="rq", proposal_id="ent-p1", candidate_artifact=TREE)
    assert "outcome is unknown" in str(err.value)
    assert _status(service[1]) == "approved"


PID = "change_proposal-0123456789abcdef"      # the Gateway parses the type from the id


def _add_proposal(path, **data):
    conn = Database(path)
    conn.execute(
        "INSERT INTO entities (id, entity_type, name, status, data_json, created_at, "
        "updated_at) VALUES (?, 'change_proposal', 'p', 'approved', ?, "
        "'2026-09-24T00:00:00Z', '2026-09-24T00:00:00Z')",
        (PID, json.dumps({"reason": "r", "scope": "s", "agent": "jarvis", **data})))
    conn.close()


def _decisions_for(path, pid):
    conn = Database(path)
    n = conn.fetchone("SELECT COUNT(*) AS n FROM entities WHERE entity_type = "
                      "'approval_decision' AND json_extract(data_json, '$.proposal_id') = ?",
                      (pid,))["n"]
    conn.close()
    return n


def test_decide_refuses_a_frozen_proposal_before_writing_anything(service):
    """RevA wiring: the old two-call decide() must not run on a proposal the
    atomic path owns, and must refuse BEFORE its first write - otherwise the
    decision record is created and then the proposal update is refused,
    leaving an orphan."""
    from gateway import selfmod
    _add_proposal(service[1])
    jarvis = _client(service, "JARVIS")
    jarvis.freeze_candidate(request_id="rq-f", proposal_id=PID, candidate_artifact=TREE)
    stale_copy = {"id": PID, "name": "p", "status": "approved"}     # caller's old dict
    with pytest.raises(selfmod.ExecutionManaged):
        selfmod.decide(jarvis, stale_copy, decision=selfmod.APPROVE, decided_by="krish")
    assert _decisions_for(service[1], PID) == 0
    conn = Database(service[1])
    assert conn.fetchone("SELECT status FROM entities WHERE id = ?", (PID,))["status"] \
        == "awaiting_execution_approval"
    conn.close()


def test_a_freeze_between_the_reread_and_the_writes_never_reports_success(service, monkeypatch):
    """The residual race, reproduced deterministically (Arya 5818781191): the
    re-read says unfrozen, then a freeze lands before decide() writes. The
    planning-decision record may be left as history - that is the stated
    limitation - but decide() must RAISE, never return a successful outcome,
    and the execution state must be untouched."""
    from gateway import selfmod
    _add_proposal(service[1])
    jarvis = _client(service, "JARVIS")
    unfrozen = jarvis.get(PID)
    jarvis.freeze_candidate(request_id="rq-f", proposal_id=PID, candidate_artifact=TREE)
    monkeypatch.setattr(jarvis, "get", lambda *a, **k: unfrozen)   # the interleaving
    with pytest.raises(dbaclient.Refused):
        selfmod.decide(jarvis, {"id": PID, "name": "p"}, decision=selfmod.APPROVE,
                       decided_by="krish")
    conn = Database(service[1])
    row = conn.fetchone("SELECT status, data_json FROM entities WHERE id = ?", (PID,))
    conn.close()
    assert row["status"] == "awaiting_execution_approval"
    assert "approved_decision_id" not in json.loads(row["data_json"])
    assert _decisions_for(service[1], PID) <= 1      # residue allowed, and bounded


def test_decide_still_records_on_an_unfrozen_proposal(service):
    from gateway import selfmod
    _add_proposal(service[1])
    jarvis = _client(service, "JARVIS")
    out = selfmod.decide(jarvis, {"id": PID, "name": "p"}, decision=selfmod.REJECT,
                         decided_by="krish")
    assert out["status"] == selfmod.DENIED
    assert _decisions_for(service[1], PID) == 1


def test_an_unconfigured_launcher_is_unavailable(service):
    """No token for the launcher exists: the live blocker, surfaced as such."""
    with pytest.raises(dbaclient.Unavailable):
        _client(service, "launcher", token="anything").approval(
            "claim_attempt", request_id="rq")
