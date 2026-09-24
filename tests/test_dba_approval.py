"""Rev A: atomic execution approval (contract claude-dev/REVA-DBA-CONTRACT-v1.md, §0-§4b).

Every assertion is on DURABLE DATABASE STATE read back through a second
connection, never on the returned message alone: a function that says "denied"
while having written an approval is exactly the defect this module exists for.

Two real SQLite connections on one file stand in for two processes. Threads
give the race; WAL plus BEGIN IMMEDIATE decide it.
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from backend.db import Database
from dba import approval, store

TREE = "git-tree:" + "a" * 40 + "@base:" + "b" * 40
OTHER_TREE = "git-tree:" + "c" * 40 + "@base:" + "b" * 40
KRISH = "operator:krish"
# The generic path's most privileged writer: the guard must hold even for it,
# or a test with a weaker principal only proves the permission check.
OPERATOR = "operator_console"
# What the launcher OBSERVED when it started the process, recorded at launch.
# Validation evidence must match it; an echoed attempt_id alone is not provenance.
LAUNCH = {"pid": 4242, "start_ticks": 639258398492693262, "launched_artifact": TREE,
          "launcher": "supervisor:deploy-pc"}


# --- fixtures -------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "dba.db"
    conn = Database(path)
    store.init_schema(conn)
    approval.init_schema(conn)
    conn.close()
    return path


def _conn(path) -> Database:
    return Database(path)


def _proposal(path, *, status="approved", **data) -> str:
    """A planning-approved change_proposal, written directly: the fixture is
    state, not the code under test."""
    body = {"gap_id": "gap-1", "proposal_version": 1, "reason": "fix it",
            "scope": "dba only", "affected_components": "dba",
            "affected_files": ["dba/store.py"], "risk": "low",
            "expected_benefit": "atomic", "test_plan": "pytest",
            "rollback_plan": "revert", "baseline_version": "e6e228a",
            "target_branch": "jarvis/change-1", "approval_state": "approve"}
    body.update(data)
    pid = "ent-" + str(abs(hash(json.dumps(body, sort_keys=True))))[:12]
    conn = _conn(path)
    conn.execute(
        "INSERT INTO entities (id, entity_type, name, status, data_json, "
        "created_at, updated_at) VALUES (?, 'change_proposal', 'p', ?, ?, "
        "'2026-09-24T00:00:00Z', '2026-09-24T00:00:00Z')",
        (pid, status, json.dumps(body)))
    conn.close()
    return pid


def _row(path, pid) -> dict:
    conn = _conn(path)
    row = conn.fetchone("SELECT status, data_json FROM entities WHERE id = ?", (pid,))
    conn.close()
    return {"status": row["status"], **json.loads(row["data_json"])}


def _count(path, sql, params=()) -> int:
    conn = _conn(path)
    n = conn.fetchone(sql, params)["n"]
    conn.close()
    return n


def _decisions(path, pid) -> int:
    return _count(path, "SELECT COUNT(*) AS n FROM entities WHERE entity_type = "
                  "'approval_decision' AND json_extract(data_json, '$.proposal_id') = ?",
                  (pid,))


def _attempts(path, pid) -> int:
    return _count(path, "SELECT COUNT(*) AS n FROM change_attempts WHERE proposal_id = ?",
                  (pid,))


def _frozen(path, pid=None, *, artifact=TREE):
    pid = pid or _proposal(path)
    conn = _conn(path)
    r = approval.freeze_candidate(conn, principal=KRISH, request_id="rq-freeze-" + pid,
                                  proposal_id=pid, candidate_artifact=artifact)
    conn.close()
    assert r.ok, r
    return pid, r.data["content_digest"]


def _approved(path):
    pid, digest = _frozen(path)
    conn = _conn(path)
    r = approval.approve_change(conn, principal=KRISH, request_id="rq-appr-" + pid,
                                proposal_id=pid, confirmed_digest=digest,
                                decision="approve")
    conn.close()
    assert r.ok, r
    return pid, digest, r.data["decision_id"]


def _launched(path):
    pid, digest, dec = _approved(path)
    conn = _conn(path)
    c = approval.claim_attempt(conn, principal=KRISH, request_id="rq-claim-" + pid,
                               proposal_id=pid, decision_id=dec, candidate_artifact=TREE)
    assert c.ok, c
    att = c.data["attempt_id"]
    f = approval.finish_attempt(conn, principal=KRISH, request_id="rq-launch-" + pid,
                                attempt_id=att, to_state="launched",
                                launch_observation=LAUNCH)
    conn.close()
    assert f.ok, f
    return pid, digest, dec, att


def _evidence(att, *, tree=TREE, clean=True, provenance=True, start_ticks=None,
              env="UNVERIFIED", untracked="UNVERIFIED"):
    prov = {"attempt_id": att, **{k: v for k, v in LAUNCH.items() if k != "launcher"}}
    if start_ticks is not None:
        prov["start_ticks"] = start_ticks
    return {"repo_tree": tree, "repo_tracked_clean": clean,
            "launch_provenance": prov if provenance else None,
            "environment_fingerprint": env, "untracked_executables": untracked}


# --- §5 the digest ----------------------------------------------------------------


def test_digest_is_canonical_order_independent_and_covers_the_artifact():
    a = {"scope": "x", "reason": "y", "affected_files": ["b", "a"], "candidate_artifact": TREE}
    b = {"candidate_artifact": TREE, "affected_files": ["a", "b"], "reason": "y", "scope": "x"}
    assert approval.content_digest(a) == approval.content_digest(b)
    assert approval.content_digest(a).startswith("digest_v1:")
    assert approval.content_digest(a) != approval.content_digest({**a, "candidate_artifact": OTHER_TREE})
    assert approval.content_digest(a) != approval.content_digest({**a, "scope": "x2"})


@pytest.mark.parametrize("bad", [1.5, {"k": "v"}, True, [1, 2]])
def test_digest_refuses_values_it_would_have_to_coerce(bad):
    with pytest.raises(approval.ApprovalError) as err:
        approval.content_digest({"scope": bad})
    assert err.value.code == approval.VALIDATION_ERROR


# --- §1 freeze ---------------------------------------------------------------------


def test_freeze_records_artifact_once_and_moves_to_awaiting_execution(db_path):
    pid, digest = _frozen(db_path)
    row = _row(db_path, pid)
    assert row["status"] == "awaiting_execution_approval"
    assert row["candidate_artifact"] == TREE
    conn = _conn(db_path)
    again = approval.freeze_candidate(conn, principal=KRISH, request_id="rq-freeze-2",
                                      proposal_id=pid, candidate_artifact=OTHER_TREE)
    conn.close()
    assert not again.ok and again.code == approval.WRONG_STATE
    assert _row(db_path, pid)["candidate_artifact"] == TREE      # never rewritten


def test_freeze_refuses_a_proposal_that_was_never_planning_approved(db_path):
    pid = _proposal(db_path, status="awaiting_approval")
    conn = _conn(db_path)
    r = approval.freeze_candidate(conn, principal=KRISH, request_id="rq-f",
                                  proposal_id=pid, candidate_artifact=TREE)
    conn.close()
    assert not r.ok and r.code == approval.WRONG_STATE
    assert "candidate_artifact" not in _row(db_path, pid)


# --- §2 approve_change ---------------------------------------------------------------


def test_approve_writes_decision_and_binds_digest_and_decision(db_path):
    pid, digest, dec = _approved(db_path)
    row = _row(db_path, pid)
    assert row["status"] == "approved_for_execution"
    assert row["approved_digest"] == digest
    assert row["approved_decision_id"] == dec and dec.startswith("dec-")
    assert _decisions(db_path, pid) == 1


def test_authoritative_read_happens_inside_the_write_transaction(db_path):
    """The proposal must be read after BEGIN IMMEDIATE, never before: a read
    outside the lock is a check another writer can invalidate before the use."""
    pid, digest = _frozen(db_path)
    seen = []

    class Spy(Database):
        def fetchone(self, sql, params=()):
            if "FROM entities" in sql:
                seen.append(self._conn.in_transaction)
            return super().fetchone(sql, params)

    conn = Spy(db_path)
    r = approval.approve_change(conn, principal=KRISH, request_id="rq-spy",
                                proposal_id=pid, confirmed_digest=digest, decision="approve")
    conn.close()
    assert r.ok, r
    assert seen and all(seen), f"entity reads outside a transaction: {seen}"


def test_content_changed_after_confirmation_is_digest_mismatch_and_writes_nothing(db_path):
    pid, digest = _frozen(db_path)
    other = _conn(db_path)                    # a second writer changes scope
    other.execute("UPDATE entities SET data_json = json_set(data_json, '$.scope', 'everything') "
                  "WHERE id = ?", (pid,))
    other.close()
    conn = _conn(db_path)
    r = approval.approve_change(conn, principal=KRISH, request_id="rq-a",
                                proposal_id=pid, confirmed_digest=digest, decision="approve")
    conn.close()
    assert not r.ok and r.code == approval.DIGEST_MISMATCH
    assert _row(db_path, pid)["status"] == "awaiting_execution_approval"
    assert "approved_digest" not in _row(db_path, pid)
    assert _decisions(db_path, pid) == 0


def test_writer_holding_the_lock_gives_contended_and_nothing_is_written(db_path):
    pid, digest = _frozen(db_path)
    holder = sqlite3.connect(db_path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        conn = _conn(db_path)
        conn._conn.execute("PRAGMA busy_timeout=100")
        r = approval.approve_change(conn, principal=KRISH, request_id="rq-c",
                                    proposal_id=pid, confirmed_digest=digest, decision="approve")
        conn.close()
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert not r.ok and r.code == approval.CONTENDED
    assert _row(db_path, pid)["status"] == "awaiting_execution_approval"
    assert _decisions(db_path, pid) == 0


def test_second_approval_of_the_same_proposal_is_wrong_state(db_path):
    pid, digest, dec = _approved(db_path)
    conn = _conn(db_path)
    r = approval.approve_change(conn, principal=KRISH, request_id="rq-second",
                                proposal_id=pid, confirmed_digest=digest, decision="approve")
    conn.close()
    assert not r.ok and r.code == approval.WRONG_STATE
    assert _decisions(db_path, pid) == 1
    assert _row(db_path, pid)["approved_decision_id"] == dec


def test_reject_is_recorded_and_denies(db_path):
    pid, digest = _frozen(db_path)
    conn = _conn(db_path)
    r = approval.approve_change(conn, principal=KRISH, request_id="rq-rej",
                                proposal_id=pid, confirmed_digest=digest, decision="reject")
    conn.close()
    assert r.ok and r.data["outcome"] == "denied"
    row = _row(db_path, pid)
    assert row["status"] == "denied" and "approved_digest" not in row
    assert _decisions(db_path, pid) == 1


# --- §4b.3 replay ------------------------------------------------------------------


def test_replay_same_request_returns_original_and_writes_nothing_new(db_path):
    pid, digest = _frozen(db_path)
    kw = dict(principal=KRISH, request_id="rq-r", proposal_id=pid,
              confirmed_digest=digest, decision="approve")
    conn = _conn(db_path)
    first = approval.approve_change(conn, **kw)
    second = approval.approve_change(conn, **kw)
    conn.close()
    assert first.ok and second.ok
    assert second.data["decision_id"] == first.data["decision_id"]
    assert second.replayed is True
    assert _decisions(db_path, pid) == 1


@pytest.mark.parametrize("change", [{"principal": "operator:someone-else"},
                                    {"decision": "reject"}, {"note": "different"}])
def test_replay_with_different_principal_or_payload_is_replay_conflict(db_path, change):
    pid, digest = _frozen(db_path)
    kw = dict(principal=KRISH, request_id="rq-r", proposal_id=pid,
              confirmed_digest=digest, decision="approve", note="")
    conn = _conn(db_path)
    assert approval.approve_change(conn, **kw).ok
    r = approval.approve_change(conn, **{**kw, **change})
    conn.close()
    assert not r.ok and r.code == approval.REPLAY_CONFLICT
    assert _decisions(db_path, pid) == 1


# --- §3 claim_attempt --------------------------------------------------------------


def test_concurrent_claims_give_exactly_one_attempt(db_path):
    pid, digest, dec = _approved(db_path)
    results, barrier = [], threading.Barrier(4)

    def claim(i):
        conn = _conn(db_path)
        barrier.wait()
        results.append(approval.claim_attempt(
            conn, principal=KRISH, request_id=f"rq-claim-{i}", proposal_id=pid,
            decision_id=dec, candidate_artifact=TREE))
        conn.close()

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r.ok for r in results) == 1, results
    assert all(r.code in (approval.ATTEMPT_EXISTS, approval.CONTENDED)
               for r in results if not r.ok)
    assert _attempts(db_path, pid) == 1


def test_claim_with_the_wrong_artifact_is_refused(db_path):
    pid, digest, dec = _approved(db_path)
    conn = _conn(db_path)
    r = approval.claim_attempt(conn, principal=KRISH, request_id="rq-x", proposal_id=pid,
                               decision_id=dec, candidate_artifact=OTHER_TREE)
    conn.close()
    assert not r.ok and r.code == approval.ARTIFACT_MISMATCH
    assert _attempts(db_path, pid) == 0


def test_generic_write_to_a_digest_field_after_approval_stops_the_claim(db_path):
    pid, digest, dec = _approved(db_path)
    other = _conn(db_path)
    other.execute("UPDATE entities SET data_json = json_set(data_json, '$.rollback_plan', 'none') "
                  "WHERE id = ?", (pid,))
    other.close()
    conn = _conn(db_path)
    r = approval.claim_attempt(conn, principal=KRISH, request_id="rq-x", proposal_id=pid,
                               decision_id=dec, candidate_artifact=TREE)
    conn.close()
    assert not r.ok and r.code == approval.DIGEST_MISMATCH
    assert _attempts(db_path, pid) == 0


def test_uncertain_attempt_is_never_relaunched(db_path):
    pid, digest, dec, att = _launched(db_path)
    conn = _conn(db_path)
    assert approval.finish_attempt(conn, principal=KRISH, request_id="rq-unc",
                                   attempt_id=att, to_state="uncertain").ok
    again = approval.claim_attempt(conn, principal=KRISH, request_id="rq-again",
                                   proposal_id=pid, decision_id=dec, candidate_artifact=TREE)
    conn.close()
    assert not again.ok and again.code == approval.ATTEMPT_EXISTS
    assert again.data["existing_state"] == "uncertain"
    assert _attempts(db_path, pid) == 1


@pytest.mark.parametrize("to_state", ["completed", "claimed", "bogus"])
def test_launcher_cannot_set_states_it_does_not_own(db_path, to_state):
    pid, digest, dec, att = _launched(db_path)
    conn = _conn(db_path)
    r = approval.finish_attempt(conn, principal=KRISH, request_id="rq-own",
                                attempt_id=att, to_state=to_state)
    conn.close()
    assert not r.ok and r.code in (approval.WRONG_STATE, approval.VALIDATION_ERROR)
    assert _count(db_path, "SELECT COUNT(*) AS n FROM change_attempts WHERE "
                  "attempt_id = ? AND state = 'launched'", (att,)) == 1


# --- §4 / §4b validate_attempt ------------------------------------------------------


def _validate(path, pid, digest, dec, att, *, request_id="rq-val", result="accepted", **ev):
    conn = _conn(path)
    r = approval.validate_attempt(conn, principal=KRISH, request_id=request_id,
                                  proposal_id=pid, attempt_id=att, decision_id=dec,
                                  approved_digest=digest, candidate_artifact=TREE,
                                  runtime_evidence=_evidence(att, **ev), result=result)
    conn.close()
    return r


def test_validate_accepts_only_with_matching_tree_clean_repo_and_launch_provenance(db_path):
    pid, digest, dec, att = _launched(db_path)
    r = _validate(db_path, pid, digest, dec, att)
    assert r.ok and r.data["artifact_verdict"] == "accepted"
    # environment and untracked inputs were UNVERIFIED: never an unqualified pass
    assert r.data["runtime_confidence"] == "partial"
    # who reported the launch is recorded, and labelled as correlation only
    assert r.data["launch_source"] == {"reported_by": KRISH, "launcher": "supervisor:deploy-pc",
                                       "assurance_basis": "correlation, not proof of origin"}
    assert _row(db_path, pid)["post_validation_state"] == "accepted"
    assert _count(db_path, "SELECT COUNT(*) AS n FROM change_attempts WHERE "
                  "attempt_id = ? AND state = 'completed'", (att,)) == 1


@pytest.mark.parametrize("ev,code", [
    ({"tree": OTHER_TREE}, "STALE_VALIDATION"),
    ({"clean": False}, "DIRTY_DEPLOYMENT"),
    ({"provenance": False}, "UNVERIFIED_RUNTIME"),
    # same attempt id, different process start: PID reuse, not our process
    ({"start_ticks": 639258398492693263}, "UNVERIFIED_RUNTIME"),
])
def test_validate_refusals_change_no_state_and_are_not_failed(db_path, ev, code):
    pid, digest, dec, att = _launched(db_path)
    r = _validate(db_path, pid, digest, dec, att, **ev)
    assert not r.ok and r.code == getattr(approval, code)
    assert r.data["verdict"] == "BLOCKED"                        # never FAILED
    row = _row(db_path, pid)
    assert "post_validation_state" not in row and row["status"] == "approved_for_execution"
    assert _count(db_path, "SELECT COUNT(*) AS n FROM change_attempts WHERE "
                  "attempt_id = ? AND state = 'launched'", (att,)) == 1


def test_stale_validation_leaves_one_diagnostic_audit_row(db_path):
    pid, digest, dec, att = _launched(db_path)
    _validate(db_path, pid, digest, dec, att, tree=OTHER_TREE)
    # audit's result vocabulary is closed; the label lives in the reason
    assert _count(db_path, "SELECT COUNT(*) AS n FROM audit_events WHERE entity_id = ? "
                  "AND result = 'refused' AND succeeded = 0 AND reason LIKE 'stale:%'",
                  (pid,)) == 1


def test_runtime_confidence_is_verified_only_when_every_input_is_known(db_path):
    pid, digest, dec = _approved(db_path)
    conn = _conn(db_path)
    c = approval.claim_attempt(conn, principal=KRISH, request_id="rq-c", proposal_id=pid,
                               decision_id=dec, candidate_artifact=TREE,
                               environment_fingerprint="sha256:" + "e" * 64)
    att = c.data["attempt_id"]
    assert approval.finish_attempt(conn, principal=KRISH, request_id="rq-l", attempt_id=att,
                                   to_state="launched", launch_observation=LAUNCH).ok
    conn.close()
    r = _validate(db_path, pid, digest, dec, att, env="sha256:" + "e" * 64, untracked=[])
    assert r.ok and r.data["runtime_confidence"] == "verified"


def test_known_environment_with_unverified_untracked_files_is_still_partial(db_path):
    """Isolates the untracked term: the environment matches, so only the
    untracked dimension can keep this from 'verified'. Found missing by a
    mutation that dropped the term and passed every other test."""
    pid, digest, dec = _approved(db_path)
    conn = _conn(db_path)
    c = approval.claim_attempt(conn, principal=KRISH, request_id="rq-c", proposal_id=pid,
                               decision_id=dec, candidate_artifact=TREE,
                               environment_fingerprint="sha256:" + "e" * 64)
    att = c.data["attempt_id"]
    assert approval.finish_attempt(conn, principal=KRISH, request_id="rq-l", attempt_id=att,
                                   to_state="launched", launch_observation=LAUNCH).ok
    conn.close()
    r = _validate(db_path, pid, digest, dec, att, env="sha256:" + "e" * 64,
                  untracked="UNVERIFIED")
    assert r.ok and r.data["runtime_confidence"] == "partial"


def test_replayed_stale_validation_does_not_append_a_second_diagnostic(db_path):
    pid, digest, dec, att = _launched(db_path)
    _validate(db_path, pid, digest, dec, att, tree=OTHER_TREE)
    _validate(db_path, pid, digest, dec, att, tree=OTHER_TREE)
    assert _count(db_path, "SELECT COUNT(*) AS n FROM audit_events WHERE entity_id = ? "
                  "AND reason LIKE 'stale:%'", (pid,)) == 1


def test_digest_changed_after_launch_is_stale(db_path):
    pid, digest, dec, att = _launched(db_path)
    other = _conn(db_path)
    other.execute("UPDATE entities SET data_json = json_set(data_json, '$.scope', 'more') "
                  "WHERE id = ?", (pid,))
    other.close()
    r = _validate(db_path, pid, digest, dec, att)
    assert not r.ok and r.code == approval.STALE_VALIDATION
    assert "post_validation_state" not in _row(db_path, pid)


def test_rolled_back_proposal_refuses_validation_of_a_launched_attempt(db_path):
    pid, digest, dec, att = _launched(db_path)
    other = _conn(db_path)
    other.execute("UPDATE entities SET status = 'rolled_back' WHERE id = ?", (pid,))
    other.close()
    r = _validate(db_path, pid, digest, dec, att)
    assert not r.ok and r.code == approval.STALE_VALIDATION
    assert _row(db_path, pid)["status"] == "rolled_back"


def test_validate_refuses_result_values_outside_the_vocabulary(db_path):
    pid, digest, dec, att = _launched(db_path)
    r = _validate(db_path, pid, digest, dec, att, result="great")
    assert not r.ok and r.code == approval.VALIDATION_ERROR


# --- §4b.5 typed ids ---------------------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("candidate_artifact", "abc"), ("candidate_artifact", None),
    ("candidate_artifact", True), ("request_id", None), ("request_id", ""),
    ("proposal_id", 7),
])
def test_malformed_ids_are_validation_errors(db_path, field, value):
    pid = _proposal(db_path)
    kw = dict(principal=KRISH, request_id="rq-m", proposal_id=pid, candidate_artifact=TREE)
    kw[field] = value
    conn = _conn(db_path)
    r = approval.freeze_candidate(conn, **kw)
    conn.close()
    assert not r.ok and r.code == approval.VALIDATION_ERROR
    assert "candidate_artifact" not in _row(db_path, pid)


def test_decision_id_must_be_typed(db_path):
    pid, digest, dec = _approved(db_path)
    conn = _conn(db_path)
    r = approval.claim_attempt(conn, principal=KRISH, request_id="rq-t", proposal_id=pid,
                               decision_id="not-a-dec", candidate_artifact=TREE)
    conn.close()
    assert not r.ok and r.code == approval.VALIDATION_ERROR


# --- §6 protected fields through the generic DBA path --------------------------------


@pytest.mark.parametrize("field", ["candidate_artifact", "approved_digest",
                                   "approved_decision_id"])
def test_generic_update_cannot_write_protected_fields(db_path, monkeypatch, field):
    from dba import agent as agent_module, contract
    monkeypatch.setenv(store.PATH_ENV, str(db_path))
    pid, digest, dec = _approved(db_path)
    before = _row(db_path, pid)
    resp = agent_module.DBAgent().handle(contract.Request(
        action=contract.UPDATE, requested_by=OPERATOR, entity_type="change_proposal",
        entity_id=pid, data={field: "forged"}, request_id="rq-gen-" + field))
    assert not resp.ok
    assert resp.error["error_code"] == contract.PROTECTED_FIELD
    assert _row(db_path, pid) == before


@pytest.mark.parametrize("data", [{"post_validation_state": "accepted"},
                                  {"status": "accepted"}, {"status": "failed"}])
def test_generic_write_cannot_overwrite_a_managed_proposals_result(db_path, monkeypatch, data):
    """Arya 5818046448: the legacy path may write post_validation_state and
    status, but not on a proposal RevA manages - there a generic write could
    fake or erase a validated verdict."""
    from dba import agent as agent_module, contract
    monkeypatch.setenv(store.PATH_ENV, str(db_path))
    pid, digest, dec, att = _launched(db_path)
    assert _validate(db_path, pid, digest, dec, att, result="failed").ok
    before = _row(db_path, pid)
    resp = agent_module.DBAgent().handle(contract.Request(
        action=contract.UPDATE, requested_by=OPERATOR, entity_type="change_proposal",
        entity_id=pid, data=data, request_id="rq-gen-managed"))
    assert not resp.ok and resp.error["error_code"] == contract.PROTECTED_FIELD
    assert _row(db_path, pid) == before


def test_legacy_proposal_keeps_its_generic_writes(db_path, monkeypatch):
    """The other half: an unfrozen proposal is untouched by RevA, so the
    existing selfmod path still records its validation result."""
    from dba import agent as agent_module, contract
    monkeypatch.setenv(store.PATH_ENV, str(db_path))
    pid = _proposal(db_path)
    resp = agent_module.DBAgent().handle(contract.Request(
        action=contract.UPDATE, requested_by=OPERATOR, entity_type="change_proposal",
        entity_id=pid, data={"post_validation_state": "failed", "status": "failed"},
        request_id="rq-gen-legacy"))
    assert resp.ok, resp.error
    row = _row(db_path, pid)
    assert row["post_validation_state"] == "failed" and row["status"] == "failed"


def test_generic_update_cannot_move_status_into_the_execution_lifecycle(db_path, monkeypatch):
    from dba import agent as agent_module, contract
    monkeypatch.setenv(store.PATH_ENV, str(db_path))
    pid, digest = _frozen(db_path)
    resp = agent_module.DBAgent().handle(contract.Request(
        action=contract.UPDATE, requested_by=OPERATOR, entity_type="change_proposal",
        entity_id=pid, data={"status": "approved_for_execution"}, request_id="rq-gen-st"))
    assert not resp.ok and resp.error["error_code"] == contract.PROTECTED_FIELD
    assert _row(db_path, pid)["status"] == "awaiting_execution_approval"


# --- §4b.4 revisions (Arya 5817725747: confirmed model) ------------------------------


def _revise(path, pid, request_id="rq-rev", **changes):
    conn = _conn(path)
    r = approval.revise_proposal(conn, principal=KRISH, request_id=request_id,
                                 proposal_id=pid, changes=changes or {"scope": "narrower"})
    conn.close()
    return r


def test_revision_is_a_new_proposal_in_the_same_change_family(db_path):
    pid, digest, dec = _approved(db_path)
    r = _revise(db_path, pid)
    assert r.ok, r
    new = r.data["proposal_id"]
    assert new != pid
    old_row, new_row = _row(db_path, pid), _row(db_path, new)
    assert old_row["status"] == "superseded"
    assert old_row["approved_decision_id"] == dec           # history preserved
    assert old_row["scope"] == "dba only"                    # old content immutable
    assert new_row["supersedes"] == pid and new_row["scope"] == "narrower"
    assert new_row["change_id"] == old_row.get("change_id", pid)
    assert "candidate_artifact" not in new_row and "approved_digest" not in new_row
    assert _decisions(db_path, pid) == 1 and _decisions(db_path, new) == 0


def test_superseded_approval_cannot_be_used_to_claim(db_path):
    pid, digest, dec = _approved(db_path)
    assert _revise(db_path, pid).ok
    conn = _conn(db_path)
    r = approval.claim_attempt(conn, principal=KRISH, request_id="rq-old", proposal_id=pid,
                               decision_id=dec, candidate_artifact=TREE)
    conn.close()
    assert not r.ok and r.code == approval.WRONG_STATE
    assert _attempts(db_path, pid) == 0


def test_new_revision_cannot_claim_while_the_family_has_an_unresolved_attempt(db_path):
    pid, digest, dec, att = _launched(db_path)
    rev = _revise(db_path, pid)
    assert rev.ok
    new = rev.data["proposal_id"]
    # the old attempt is NOT implied cancelled by the proposal's status change
    assert _count(db_path, "SELECT COUNT(*) AS n FROM change_attempts WHERE "
                  "attempt_id = ? AND state = 'launched'", (att,)) == 1
    conn = _conn(db_path)
    f = approval.freeze_candidate(conn, principal=KRISH, request_id="rq-f2",
                                  proposal_id=new, candidate_artifact=OTHER_TREE)
    assert f.ok, f
    a = approval.approve_change(conn, principal=KRISH, request_id="rq-a2", proposal_id=new,
                                confirmed_digest=f.data["content_digest"], decision="approve")
    assert a.ok, a
    c = approval.claim_attempt(conn, principal=KRISH, request_id="rq-c2", proposal_id=new,
                               decision_id=a.data["decision_id"], candidate_artifact=OTHER_TREE)
    conn.close()
    assert not c.ok and c.code == approval.ATTEMPT_EXISTS
    assert c.data["existing_attempt_id"] == att
    assert _attempts(db_path, new) == 0


def test_revising_twice_from_the_same_revision_is_refused(db_path):
    pid, digest = _frozen(db_path)
    assert _revise(db_path, pid, request_id="rq-r1").ok
    r = _revise(db_path, pid, request_id="rq-r2", scope="other")
    assert not r.ok and r.code == approval.WRONG_STATE
