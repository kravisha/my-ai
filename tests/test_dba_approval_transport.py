"""RevA transport: POST /approval/{operation} on the real DBA app (Arya 5818448805).

TestClient without `with`, so the app's lifespan - and with it the backup
scheduler - never starts. Every refusal is checked against the durable row,
not only the status code.
"""

from __future__ import annotations

import json

import pytest

from backend.db import Database
from dba import approval, store

TREE = "git-tree:" + "a" * 40 + "@base:" + "b" * 40
TOKENS = {"JARVIS": "tok-jarvis", "operator_console": "tok-operator",
          "launcher": "tok-launcher", "coo": "tok-coo"}
LAUNCH = {"pid": 4242, "start_ticks": 639258398492693262, "launched_artifact": TREE,
          "launcher": "supervisor:test"}


@pytest.fixture
def db_path(tmp_path, monkeypatch):
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
        (json.dumps({"reason": "r", "scope": "s", "affected_files": ["a.py"]}),))
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    from fastapi.testclient import TestClient

    from dba.main import app
    return TestClient(app)          # no `with`: lifespan (backup scheduler) not started


def _as(agent):
    return {"X-DBA-Agent": agent, "X-DBA-Token": TOKENS[agent]}


def _row(path):
    conn = Database(path)
    row = conn.fetchone("SELECT status, data_json FROM entities WHERE id = 'ent-p1'")
    conn.close()
    return {"status": row["status"], **json.loads(row["data_json"])}


def _count(path, sql):
    conn = Database(path)
    n = conn.fetchone(sql)["n"]
    conn.close()
    return n


def _freeze(client):
    r = client.post("/approval/freeze_candidate", headers=_as("JARVIS"),
                    json={"request_id": "rq-f", "proposal_id": "ent-p1",
                          "candidate_artifact": TREE})
    assert r.status_code == 200, r.json()
    return r.json()["data"]["content_digest"]


def _approve(client, digest):
    r = client.post("/approval/approve_change", headers=_as("operator_console"),
                    json={"request_id": "rq-a", "proposal_id": "ent-p1",
                          "confirmed_digest": digest, "decision": "approve"})
    assert r.status_code == 200, r.json()
    return r.json()["data"]["decision_id"]


# --- the whole path, through the real route -----------------------------------------


def test_the_full_lifecycle_through_http_with_each_role(client, db_path):
    digest = _freeze(client)
    dec = _approve(client, digest)
    c = client.post("/approval/claim_attempt", headers=_as("launcher"),
                    json={"request_id": "rq-c", "proposal_id": "ent-p1", "decision_id": dec,
                          "candidate_artifact": TREE})
    assert c.status_code == 200, c.json()
    att = c.json()["data"]["attempt_id"]
    f = client.post("/approval/finish_attempt", headers=_as("launcher"),
                    json={"request_id": "rq-l", "attempt_id": att, "to_state": "launched",
                          "launch_observation": LAUNCH})
    assert f.status_code == 200, f.json()
    prov = {"attempt_id": att, **{k: v for k, v in LAUNCH.items() if k != "launcher"}}
    v = client.post("/approval/validate_attempt", headers=_as("JARVIS"),
                    json={"request_id": "rq-v", "proposal_id": "ent-p1", "attempt_id": att,
                          "decision_id": dec, "approved_digest": digest,
                          "candidate_artifact": TREE, "result": "accepted",
                          "runtime_evidence": {"repo_tree": TREE, "repo_tracked_clean": True,
                                               "launch_provenance": prov,
                                               "environment_fingerprint": "UNVERIFIED",
                                               "untracked_executables": "UNVERIFIED"}})
    assert v.status_code == 200, v.json()
    row = _row(db_path)
    assert row["post_validation_state"] == "accepted"
    assert row["approved_decision_id"] == dec
    # the decision records the AUTHENTICATED principal
    assert _count(db_path, "SELECT COUNT(*) AS n FROM entities WHERE entity_type = "
                  "'approval_decision' AND json_extract(data_json, '$.decided_by') = "
                  "'operator_console'") == 1


# --- authentication ------------------------------------------------------------------


def test_missing_token_is_401_and_changes_nothing(client, db_path):
    before = _row(db_path)
    r = client.post("/approval/freeze_candidate",
                    json={"request_id": "rq", "proposal_id": "ent-p1", "candidate_artifact": TREE})
    assert r.status_code == 401
    assert _row(db_path) == before


def test_wrong_token_is_403_and_changes_nothing(client, db_path):
    before = _row(db_path)
    r = client.post("/approval/freeze_candidate",
                    headers={"X-DBA-Agent": "JARVIS", "X-DBA-Token": "wrong"},
                    json={"request_id": "rq", "proposal_id": "ent-p1", "candidate_artifact": TREE})
    assert r.status_code == 403
    assert _row(db_path) == before


# --- least privilege per operation ----------------------------------------------------


@pytest.mark.parametrize("operation,agent", [
    ("approve_change", "JARVIS"),          # Jarvis cannot approve a change to itself
    ("approve_change", "launcher"),
    ("freeze_candidate", "launcher"),
    ("freeze_candidate", "coo"),
    ("claim_attempt", "JARVIS"),
    ("claim_attempt", "operator_console"),  # not even the operator: the launcher claims
    ("finish_attempt", "JARVIS"),
    ("validate_attempt", "launcher"),
])
def test_each_operation_refuses_every_role_not_granted_it(client, db_path, operation, agent):
    before = _row(db_path)
    r = client.post(f"/approval/{operation}", headers=_as(agent), json={"request_id": "rq"})
    assert r.status_code == 403 and r.json()["code"] == approval.PERMISSION_DENIED
    assert _row(db_path) == before


def test_the_role_table_is_exactly_this(client):
    """Literals, not the constant: a widened grant must fail here."""
    assert {op: sorted(roles) for op, roles in approval._roles().items()} == {
        "approve_change": ["operator_console"],
        "freeze_candidate": ["JARVIS", "operator_console"],
        "revise_proposal": ["JARVIS", "operator_console"],
        "claim_attempt": ["launcher"],
        "finish_attempt": ["launcher"],
        "validate_attempt": ["JARVIS"],
    }


def test_the_launcher_holds_nothing_in_the_generic_path(client, db_path):
    r = client.post("/request", headers=_as("launcher"),
                    json={"action": "get", "requested_by": "launcher",
                          "entity_type": "change_proposal", "entity_id": "ent-p1"})
    assert r.status_code == 403


# --- identity in the body, unknown operations, malformed bodies --------------------------


@pytest.mark.parametrize("field", ["principal", "requested_by", "actor", "decided_by"])
def test_a_body_that_names_an_identity_is_refused(client, db_path, field):
    digest = _freeze(client)
    before = _row(db_path)
    r = client.post("/approval/approve_change", headers=_as("operator_console"),
                    json={"request_id": "rq-x", "proposal_id": "ent-p1",
                          "confirmed_digest": digest, "decision": "approve",
                          field: "operator:krish"})
    assert r.status_code == 400 and r.json()["code"] == approval.VALIDATION_ERROR
    # The refusal must SAY it was an identity claim. A generic "unexpected
    # field" would also refuse it, and a mutation that removed the identity
    # check survived until this line existed.
    assert "identity comes from authentication" in r.json()["message"]
    assert field in r.json()["message"]
    assert _row(db_path) == before


def test_an_unknown_operation_is_404_after_authentication(client, db_path):
    assert client.post("/approval/init_schema", headers=_as("JARVIS"), json={}).status_code == 404
    assert client.post("/approval/init_schema", json={}).status_code == 401


@pytest.mark.parametrize("body", [{"request_id": "rq"},
                                  {"request_id": "rq", "proposal_id": "ent-p1",
                                   "candidate_artifact": TREE, "extra": 1}])
def test_missing_or_unexpected_fields_are_refused(client, db_path, body):
    before = _row(db_path)
    r = client.post("/approval/freeze_candidate", headers=_as("JARVIS"), json=body)
    assert r.status_code == 400
    assert _row(db_path) == before


# --- replay through the route ----------------------------------------------------------


def test_replay_through_http_returns_the_original_and_conflicts_across_principals(client, db_path):
    digest = _freeze(client)
    body = {"request_id": "rq-a", "proposal_id": "ent-p1", "confirmed_digest": digest,
            "decision": "approve"}
    first = client.post("/approval/approve_change", headers=_as("operator_console"), json=body)
    again = client.post("/approval/approve_change", headers=_as("operator_console"), json=body)
    assert first.status_code == again.status_code == 200
    assert again.json()["replayed"] is True
    assert again.json()["data"]["decision_id"] == first.json()["data"]["decision_id"]
    other = client.post("/approval/approve_change", headers=_as("operator_console"),
                        json={**body, "decision": "reject"})
    assert other.status_code == 409 and other.json()["code"] == approval.REPLAY_CONFLICT
    assert _count(db_path, "SELECT COUNT(*) AS n FROM entities WHERE entity_type = "
                  "'approval_decision'") == 1


def test_a_state_refusal_is_409_and_changes_nothing(client, db_path):
    digest = _freeze(client)
    _approve(client, digest)
    before = _row(db_path)
    r = client.post("/approval/approve_change", headers=_as("operator_console"),
                    json={"request_id": "rq-2", "proposal_id": "ent-p1",
                          "confirmed_digest": digest, "decision": "approve"})
    assert r.status_code == 409 and r.json()["code"] == approval.WRONG_STATE
    assert _row(db_path) == before
