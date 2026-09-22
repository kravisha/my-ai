"""§35's twelve acceptance tests, A to L, end to end.

Each one is the specification's own scenario rather than a unit test of a
module, and each is named for the letter it answers. Where §35 says "stop
JARVIS completely and start a clean runtime", these build a fresh client and
call `bootstrap` again - which is a real restart in every way that matters
here, because nothing in `gateway/` holds Jarvis's state in process memory.
`test_nothing_is_cached_in_process` asserts that, since it is the assumption
the other eleven rest on.

The DBA is the real service throughout. A rehydration test that restored from
a stub would be testing that a stub returns what it was given.
"""

import importlib.util
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from dba import agent as agent_module, main as dba_main, registry, store
from gateway import (checkpoint as checkpoint_module, dbaclient, failures,
                     gaps, identity, ledger, persistence, rehydrate, selfmod)

TOKEN = "test-token-for-jarvis"
OPERATOR_TOKEN = "test-token-for-operator"


def _load_deployer():
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "deploy_jarvis.py"
    spec = importlib.util.spec_from_file_location("deploy_jarvis_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy = _load_deployer()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dba_main.token_env_var("operator_console"), OPERATOR_TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(deploy.OPERATOR_TOKEN_ENV, OPERATOR_TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "1" * 40)
    monkeypatch.setenv(selfmod.DEPLOY_DIR_ENV, str(tmp_path / "deploy"))
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def service():
    with TestClient(dba_main.app) as running:
        yield running


def _runtime(service):
    """A fresh Jarvis runtime: a new client, holding nothing from before."""

    def transport(method, path, payload):
        response = service.request(
            method, path, json=payload if method != "GET" else None,
            headers={"X-DBA-Agent": "JARVIS", "X-DBA-Token": TOKEN})
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    return dbaclient.DBAClient(transport=transport)


@pytest.fixture()
def client(service):
    return _runtime(service)


def test_nothing_is_cached_in_process():
    """The assumption every restart test below rests on.

    If a module held restored state at import, "start a clean runtime" in this
    file would be a fiction and eleven tests would be passing on a cache."""
    import ast

    for name in ("persistence", "ledger", "checkpoint", "rehydrate", "gaps",
                 "selfmod", "dbaclient"):
        source = (pathlib.Path(__file__).resolve().parent.parent
                  / "gateway" / f"{name}.py").read_text(encoding="utf-8")
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and not target.id.isupper():
                        pytest.fail(
                            f"gateway/{name}.py assigns module-level mutable "
                            f"state {target.id!r}; a restart would not clear it")


# =============================================================================
# TEST A - normal persistence
# =============================================================================


def test_a_normal_persistence(service):
    """Teach, correct, update a skill, leave a task and a commitment, stop,
    start clean, rehydrate. PASS: restored without Krish restating any of it."""
    first = _runtime(service)

    # 1. a new fact
    persistence.put(first, persistence.KNOWLEDGE, "krish-coffee", "flat white")
    ledger.append(first, event_type=ledger.OBSERVATION,
                  summary="Krish drinks flat whites",
                  verification_state=ledger.ASSERTED_BY_USER)
    # 2. a corrected assumption
    persistence.put(first, persistence.KNOWLEDGE, "krish-timezone", "UTC")
    persistence.put(first, persistence.KNOWLEDGE, "krish-timezone", "Asia/Kolkata")
    ledger.append(first, event_type=ledger.USER_CORRECTION,
                  summary="not UTC - Asia/Kolkata",
                  verification_state=ledger.ASSERTED_BY_USER)
    # 3. a skill
    persistence.put(first, persistence.SKILL, "read-statements",
                    {"level": "practising", "passed": 3, "of": 5})
    # 4. an unfinished task
    persistence.put(first, persistence.TASK, "september-summary",
                    {"step": 2, "of": 4, "next": "fetch the card statement"})
    # 5. an open commitment
    persistence.put(first, persistence.COMMITMENT, "weekly-summary",
                    {"owed_to": "krish", "promise": "send it every Sunday"})
    # 6. persist
    checkpoint_module.take(first, reason=checkpoint_module.BEFORE_SHUTDOWN)

    # 7 and 8. stop completely, start a clean runtime
    del first
    second = _runtime(service)

    # 9. rehydrate through the DBA
    restoration = rehydrate.bootstrap(second)

    assert restoration.status == rehydrate.RESTORED_OK
    assert restoration.assert_fact(persistence.KNOWLEDGE, "krish-coffee") == "flat white"
    assert restoration.assert_fact(
        persistence.KNOWLEDGE, "krish-timezone") == "Asia/Kolkata"
    assert restoration.assert_fact(
        persistence.TASK, "september-summary")["next"] == "fetch the card statement"
    assert restoration.assert_fact(
        persistence.COMMITMENT, "weekly-summary")["promise"] == "send it every Sunday"
    assert restoration.assert_fact(
        persistence.SKILL, "read-statements")["level"] == "practising"
    assert restoration.sentences() == []


# =============================================================================
# TEST B - crash recovery
# =============================================================================


def test_b_crash_recovery_identifies_the_interval_at_risk(service):
    """Killed without a graceful shutdown. PASS: restores from the most recent
    safe checkpoint and identifies any potentially lost interval."""
    working = _runtime(service)
    persistence.put(working, persistence.TASK, "invoice", {"step": 1})
    record = checkpoint_module.take(working)

    # Work that happened after the last checkpoint, and then the process dies.
    persistence.put(working, persistence.TASK, "invoice", {"step": 2})
    ledger.append(working, event_type=ledger.ACTION_SUCCEEDED, summary="fetched the PDF")
    ledger.append(working, event_type=ledger.DECISION, summary="chose the card account")
    del working

    after_crash = _runtime(service)
    restoration = rehydrate.bootstrap(after_crash)

    assert restoration.status == rehydrate.RESTORED_OK
    # The live state is what he resumes from - nothing was lost.
    assert restoration.assert_fact(persistence.TASK, "invoice") == {"step": 2}
    # And the interval the checkpoint does not vouch for is named, not guessed.
    interval = restoration.interval_at_risk
    assert interval["events"] >= 2
    assert "chose the card account" in interval["summaries"]
    assert restoration.checkpoint["name"] == record["name"]


# =============================================================================
# TEST C - corrupt checkpoint
# =============================================================================


def test_c_a_damaged_checkpoint_is_rejected_and_the_rollback_reported(service):
    """PASS: detects corruption, rejects the invalid checkpoint, restores the
    most recent valid one, and reports the rollback."""
    working = _runtime(service)
    persistence.put(working, persistence.GOAL, "ship", "phase 2")
    good = checkpoint_module.take(working)
    persistence.put(working, persistence.GOAL, "ship", "phase 3")
    newest = checkpoint_module.take(working)

    # Damage the newest.
    working.update(newest["id"], {"contents_hash": "0" * 64})
    del working

    restoration = rehydrate.bootstrap(_runtime(service))

    assert failures.CHECKPOINT_INVALID in restoration.failure_states
    assert restoration.checkpoint["name"] == good["name"]
    assert [row["name"] for row in restoration.skipped_checkpoints] == [newest["name"]]
    assert restoration.must_tell_user()
    said = " ".join(restoration.sentences())
    assert "did not verify" in said and "fall back" in said.lower()


# =============================================================================
# TEST D - life ledger replay
# =============================================================================


def test_d_the_ledger_tells_the_development_in_order(service):
    """A belief, a correction, a lesson, contradictory evidence, a revised
    lesson. PASS: the chronological development is explainable and the earlier
    belief is distinguishable from the later interpretation."""
    jarvis = _runtime(service)

    belief = ledger.append(
        jarvis, event_type=ledger.OBSERVATION,
        summary="the local model is always slower than Kimi",
        verification_state=ledger.INFERRED, confidence=0.6)
    correction = ledger.append(
        jarvis, event_type=ledger.USER_CORRECTION,
        summary="Krish: not on short prompts",
        verification_state=ledger.ASSERTED_BY_USER,
        related_event_ids=[belief["id"]])
    lesson = ledger.append(
        jarvis, event_type=ledger.LESSON,
        summary="prefer the local model under 2k tokens",
        verification_state=ledger.INFERRED,
        related_event_ids=[correction["id"]])
    evidence = ledger.append(
        jarvis, event_type=ledger.EVALUATION_RESULT,
        summary="measured: local wins up to 8k, not 2k",
        verification_state=ledger.VERIFIED, confidence=0.95,
        related_event_ids=[lesson["id"]])
    revised = ledger.reinterpret(
        jarvis, original_event_id=lesson["id"],
        lesson="prefer the local model under 8k tokens",
        why_changed="the 2k figure was a guess; the measurement says 8k")

    walked = ledger.events(jarvis, limit=50)
    assert [row["sequence_number"] for row in walked] == [1, 2, 3, 4, 5]
    assert [row["event_type"] for row in walked] == [
        ledger.OBSERVATION, ledger.USER_CORRECTION, ledger.LESSON,
        ledger.EVALUATION_RESULT, ledger.REINTERPRETATION]

    # The earlier belief is still exactly what it was.
    assert walked[2]["name"] == "prefer the local model under 2k tokens"
    assert walked[2].get("supersedes_event_id") is None
    # And the later layer says which one it replaces.
    assert walked[4]["supersedes_event_id"] == lesson["id"]
    # Confidence at the time is preserved, so "how firmly did I believe this?"
    # is answerable, which is §7's whole point.
    assert walked[0]["confidence"] == 0.6
    assert walked[3]["confidence"] == 0.95
    assert walked[0]["verification_state"] == ledger.INFERRED
    assert walked[3]["verification_state"] == ledger.VERIFIED

    assert ledger.replay(jarvis)["intact"] is True
    assert revised["sequence_number"] == 5


# =============================================================================
# TEST E - reinterpretation
# =============================================================================


def test_e_a_new_interpretation_does_not_erase_the_original(service):
    jarvis = _runtime(service)
    original = ledger.append(
        jarvis, event_type=ledger.LESSON,
        summary="never call the external model for a summary",
        observation="it cost £4 in one afternoon",
        verification_state=ledger.INFERRED)

    later = ledger.reinterpret(
        jarvis, original_event_id=original["id"],
        lesson="call it for summaries over 20 pages; the local model degrades",
        why_changed="the £4 was one runaway loop, not the summaries")

    stored = jarvis.get(original["id"])
    assert stored["name"] == "never call the external model for a summary"
    assert stored["observation"] == "it cost £4 in one afternoon"
    assert stored["status"] == "recorded"
    assert later["supersedes_event_id"] == original["id"]

    # Both survive a restart, in order, with the chain intact.
    fresh = _runtime(service)
    assert ledger.replay(fresh)["intact"] is True
    assert len(ledger.events(fresh, limit=10)) == 2


# =============================================================================
# TEST F - suspected gap rejected
# =============================================================================


def test_f_a_suspicion_that_testing_disproves_is_rejected(service):
    """PASS: marked rejected, and Jarvis does not modify himself."""
    jarvis = _runtime(service)
    gap = gaps.suspect(jarvis, title="missing_tool: I cannot search the web",
                       description="a request failed and I assumed it was me",
                       detected_by="self", evidence={"occurrences": 2})
    gap = gaps.transition(jarvis, gap, gaps.INVESTIGATING)
    gap = gaps.reject(jarvis, gap,
                      counter_evidence="ran the web_search tool: 5/5 passed")

    assert jarvis.get(gap["id"])["status"] == gaps.REJECTED
    with pytest.raises(gaps.NotConfirmed):
        gaps.ready_for_review(jarvis, jarvis.get(gap["id"]))
    assert jarvis.count("change_proposal", {"agent": "jarvis"}) == 0

    types = [row["event_type"] for row in ledger.events(jarvis, limit=20)]
    assert ledger.GAP_REJECTED in types


# =============================================================================
# TEST G - confirmed gap requires approval
# =============================================================================


def _confirmed(jarvis, title="missing_tool: read a PDF"):
    gap = gaps.suspect(jarvis, title=title, description="asked twice",
                       detected_by="self", evidence={"occurrences": 2})
    gap = gaps.transition(jarvis, gap, gaps.INVESTIGATING,
                          evidence="held-out PDF case failed 0/3")
    return gaps.confirm(jarvis, gap, evidence={"case": "pdf", "passed": 0, "of": 3},
                        impact="Krish cannot read statements through Jarvis",
                        remedy=gaps.REMEDY_CODE)


def _propose(jarvis, gap):
    return selfmod.propose(
        jarvis, gap=gap, reason="asked twice and refused twice",
        scope="add a pdf_text tool", affected_files=["gateway/tools.py"],
        expected_benefit="statements readable in the conversation",
        risk="a malformed PDF could raise inside a turn",
        test_plan="tests/test_gateway_tools.py plus a malformed case",
        rollback_plan="revert the commit; the tool is additive")


def test_g_a_confirmed_gap_stops_at_the_approval_gate(service):
    """PASS: confirmed with evidence, remediation proposed, and it stops.
    No code modification occurs before approval."""
    jarvis = _runtime(service)
    proposal = _propose(jarvis, _confirmed(jarvis))

    assert proposal["status"] == selfmod.AWAITING_APPROVAL
    for permission in selfmod.AFTER_APPROVAL:
        with pytest.raises(selfmod.Denied):
            selfmod.require(permission, jarvis.get(proposal["id"]))
    with pytest.raises(selfmod.NotApproved):
        selfmod.prepare(jarvis, jarvis.get(proposal["id"]))

    text = selfmod.render(jarvis.get(proposal["id"]),
                          jarvis.get(proposal["gap_id"]))
    assert "Approval requested:   YES" in text
    assert "pdf" in text.lower()


# =============================================================================
# TEST H - approval denied
# =============================================================================


def test_h_a_denial_is_recorded_and_nothing_is_modified(service):
    jarvis = _runtime(service)
    proposal = _propose(jarvis, _confirmed(jarvis))
    selfmod.decide(jarvis, proposal, decision=selfmod.REJECT,
                   decided_by="krish", note="use the phone's own PDF app")

    stored = jarvis.get(proposal["id"])
    assert stored["status"] == selfmod.DENIED
    with pytest.raises(selfmod.NotApproved):
        selfmod.prepare(jarvis, stored)

    # The decision survives a restart, which is §18's last line.
    fresh = _runtime(service)
    decisions = fresh.find("approval_decision", {"proposal_id": proposal["id"]})
    assert [row["decision"] for row in decisions] == ["reject"]
    assert decisions[0]["decided_by"] == "krish"
    assert ledger.APPROVAL_DENIED in [
        row["event_type"] for row in ledger.events(fresh, limit=30)]


# =============================================================================
# TEST I - approved self-modification
# =============================================================================


def _deploy_through_controller(jarvis, service, tmp_path, *, passed=True):
    """The full §15 loop, with the controller's own checks left in place."""
    proposal = _propose(jarvis, _confirmed(jarvis))
    approved = selfmod.decide(jarvis, proposal, decision=selfmod.APPROVE,
                              decided_by="krish", interface=selfmod.CLI)
    checkpoint_module.take(jarvis)
    selfmod.prepare(jarvis, jarvis.get(approved["id"]))
    jarvis.update(approved["id"], {"status": selfmod.COMMITTED,
                                   "commit_id": "2" * 40})
    request = selfmod.request_build(jarvis, jarvis.get(approved["id"]))

    def as_operator(change_id, token):
        response = service.post(
            "/request",
            json={"action": "get", "requested_by": "operator_console",
                  "actor": "build_controller", "entity_type": "change_proposal",
                  "entity_id": change_id},
            headers={"X-DBA-Agent": "operator_console", "X-DBA-Token": token})
        return response.status_code, response.json()

    import unittest.mock as mock
    with mock.patch.object(deploy, "checkout", lambda commit: (True, "")), \
            mock.patch.object(deploy, "current_commit", lambda: "1" * 40), \
            mock.patch.object(deploy, "stamp_deployed", lambda commit: None):
        result = deploy.handle(
            request, directory=tmp_path / "deploy",
            verify=lambda r: deploy.verify_approved(r, fetch=as_operator),
            tester=lambda: {"passed": passed, "ran": True,
                            "why": "" if passed else "pytest exit 1",
                            "summary": "3900 passed" if passed else "2 failed"})
    return jarvis.get(approved["id"]), result


def test_i_an_approved_change_returns_with_memory_and_the_fix(service, tmp_path,
                                                              monkeypatch):
    """PASS: JARVIS returns with prior memory and the approved fix."""
    jarvis = _runtime(service)
    persistence.put(jarvis, persistence.IDENTITY, "name", "Jarvis")
    persistence.put(jarvis, persistence.COMMITMENT, "weekly-summary",
                    {"promise": "send it every Sunday"})

    proposal, result = _deploy_through_controller(jarvis, service, tmp_path)
    assert result["status"] == deploy.OK

    # The relaunch: a new runtime, on the new build.
    monkeypatch.setenv(identity.VERSION_ENV, "2" * 40)
    relaunched = _runtime(service)
    restoration = rehydrate.bootstrap(relaunched)
    verdict = selfmod.post_relaunch_validate(
        relaunched, relaunched.get(proposal["id"]), restoration=restoration)

    assert verdict["state"] == selfmod.ACCEPTED
    assert "I was modified" in verdict["statement"]
    assert restoration.assert_fact(persistence.IDENTITY, "name") == "Jarvis"
    assert restoration.assert_fact(
        persistence.COMMITMENT, "weekly-summary")["promise"] == "send it every Sunday"
    assert restoration.code_version == "2" * 40


# =============================================================================
# TEST J - failed self-modification
# =============================================================================


def test_j_a_candidate_that_fails_validation_is_rolled_back(service, tmp_path):
    """PASS: the previous known-good code and state are restored by policy."""
    jarvis = _runtime(service)
    persistence.put(jarvis, persistence.IDENTITY, "name", "Jarvis")

    proposal, result = _deploy_through_controller(jarvis, service, tmp_path,
                                                  passed=False)

    # The controller never let the red build become the running one.
    assert result["status"] == deploy.TESTS_FAILED
    assert result["restored_previous"] is True
    assert result["commit"] == "1" * 40

    restoration = rehydrate.bootstrap(_runtime(service))
    verdict = selfmod.post_relaunch_validate(jarvis, jarvis.get(proposal["id"]),
                                             restoration=restoration)
    assert verdict["state"] == selfmod.FAILED
    assert verdict["failure_state"] == failures.POST_VALIDATION_FAILED

    selfmod.request_rollback(jarvis, jarvis.get(proposal["id"]),
                             why="post-change tests failed")
    explanation = selfmod.explain_rollback(jarvis, jarvis.get(proposal["id"]))
    assert explanation["which_version_failed"] == "2" * 40
    assert explanation["what_was_restored"] == "1" * 40
    assert explanation["what_tests_failed"]["passed"] is False
    assert jarvis.get(proposal["id"])["status"] == selfmod.ROLLED_BACK


# =============================================================================
# TEST K - authority boundary
# =============================================================================


def test_k_jarvis_cannot_remove_the_approval_requirement(service):
    """PASS: the request is blocked. Jarvis cannot autonomously expand his own
    authority - and no approval makes it reachable either."""
    from gateway import introspect

    jarvis = _runtime(service)
    gap = _confirmed(jarvis, title="the approval gate slows me down")

    for target in ("gateway/selfmod.py", "app/initiative.py",
                   "config/initiative.yaml", "tests/test_jarvis_selfmod.py",
                   "scripts/deploy_jarvis.py"):
        with pytest.raises(introspect.NotModifiable):
            selfmod.propose(
                jarvis, gap=gap, reason="it slows me down",
                scope="remove the approval requirement",
                affected_files=[target], expected_benefit="faster",
                risk="none that I can see", test_plan="the suite",
                rollback_plan="revert")

    assert jarvis.count("change_proposal", {"agent": "jarvis"}) == 0

    # And the same is true through an already-approved proposal: the scope is
    # re-checked at commit, so an approval cannot be widened afterwards.
    legitimate = _propose(jarvis, _confirmed(jarvis, title="missing_tool: pdf"))
    approved = selfmod.decide(jarvis, legitimate, decision=selfmod.APPROVE,
                              decided_by="krish")
    jarvis.update(approved["id"], {"status": selfmod.TESTED,
                                   "affected_files": json.dumps(
                                       ["app/initiative.py"])})
    with pytest.raises(introspect.NotModifiable):
        selfmod.commit_candidate(jarvis, jarvis.get(approved["id"]), message="m")


# =============================================================================
# TEST L - fresh model, fresh machine
# =============================================================================


def test_l_a_replacement_runtime_reconstructs_and_reports_what_it_cannot(
        service, monkeypatch):
    """PASS: the replacement runtime reconstructs Jarvis as far as possible and
    reports anything that cannot be migrated."""
    original = _runtime(service)
    persistence.put(original, persistence.IDENTITY, "name", "Jarvis")
    persistence.put(original, persistence.PREFERENCE, "tone",
                    "plain, no flattery")
    persistence.put(original, persistence.COMMITMENT, "weekly-summary",
                    {"promise": "send it every Sunday"})
    # Something whose truth decays - the honest example of "cannot be migrated
    # as fact", because a new machine has no way to know it is still true.
    persistence.put(original, persistence.KNOWLEDGE, "tunnel-url",
                    {"value": "https://x.trycloudflare.com",
                     rehydrate.TIME_SENSITIVE_FLAG: True})
    ledger.append(original, event_type=ledger.LESSON,
                  summary="Krish prefers being told the cost up front")
    checkpoint_module.take(original)
    del original

    # A different machine, a different build, a runtime that has never run.
    monkeypatch.setenv(identity.VERSION_ENV, "9" * 40)
    replacement = _runtime(service)
    restoration = rehydrate.bootstrap(replacement)

    assert restoration.agent_id == "jarvis"       # §38 q12: unchanged by the move
    assert restoration.code_version == "9" * 40   # and it knows it is different
    assert restoration.assert_fact(persistence.IDENTITY, "name") == "Jarvis"
    assert restoration.assert_fact(
        persistence.PREFERENCE, "tone") == "plain, no flattery"
    assert restoration.assert_fact(
        persistence.COMMITMENT, "weekly-summary")["promise"] == "send it every Sunday"

    # What it will not assert as fact, and says so.
    assert "knowledge/tunnel-url" in restoration.needs_reverification
    assert any("re-checked" in line for line in restoration.sentences())
    assert ledger.replay(replacement)["intact"] is True
    assert len(ledger.events(replacement, limit=50)) >= 2


# =============================================================================
# §36's definition of done, as a checklist that can fail
# =============================================================================


def test_the_definition_of_done_is_answerable_item_by_item(service, tmp_path):
    """§36's list. Each entry points at the test or the mechanism that answers
    it, and the assertions here are the ones that are cheap to state directly -
    the rest are the twelve above, named."""
    jarvis = _runtime(service)

    # "JARVIS restores through the DBA/persistence layer."
    assert rehydrate.bootstrap(jarvis).status in (
        rehydrate.RESTORED_OK, failures.PARTIAL_RESTORE)
    # "The database remains authoritative for persisted factual state."
    assert persistence.ENTITY_TYPE == "agent_state"
    # "JARVIS knows which code version he is running."
    assert identity.code_version() == "1" * 40
    # "Audit history is preserved" / "ordinary agents must not rewrite it."
    from dba import permissions
    assert "delete" not in permissions.permissions_of("JARVIS")
    assert "administer" not in permissions.permissions_of("JARVIS")
    # "No self-expansion of authority is possible."
    assert set(selfmod.AFTER_APPROVAL) and selfmod.permissions_for(None).isdisjoint(
        selfmod.AFTER_APPROVAL)
    # "Approval decisions are persisted."
    assert "approval_decision" in [entity.name for entity in __import__(
        "dba.entities", fromlist=["x"]).all_types()]
    # "Failures must be visible": all fourteen §34 states are declared.
    assert len(failures.STATES) == 14


# =============================================================================
# The machinery has a user
# =============================================================================


def test_the_gateway_rehydrates_when_it_starts(monkeypatch, tmp_path):
    """Everything above is dormant unless the running Gateway boots through it.

    §3 puts rehydration at startup and not on the first request, because the
    first request is exactly where a Jarvis who has not checked would answer
    from a memory he does not have."""
    from gateway import main as gateway_main

    monkeypatch.setenv("GATEWAY_DB_PATH", str(tmp_path / "gateway.db"))
    called = {}

    def fake_bootstrap(*args, **kwargs):
        called["ran"] = True
        return rehydrate.Restoration(status=rehydrate.RESTORED_OK)

    monkeypatch.setattr(rehydrate, "bootstrap", fake_bootstrap)
    with TestClient(gateway_main.app) as running:
        assert called.get("ran") is True
        assert running.app.state.restoration.status == rehydrate.RESTORED_OK


def test_an_unreachable_dba_does_not_stop_the_gateway_starting(monkeypatch, tmp_path):
    """A Gateway that refused to start because its memory was unavailable is a
    Gateway Krish cannot reach to ask about it."""
    from gateway import main as gateway_main

    monkeypatch.setenv("GATEWAY_DB_PATH", str(tmp_path / "gateway.db"))
    monkeypatch.delenv(dbaclient.TOKEN_ENV, raising=False)

    with TestClient(gateway_main.app) as running:
        restoration = running.app.state.restoration
        assert restoration.status == failures.RESTORE_FAILED
        assert failures.DBA_UNAVAILABLE in restoration.failure_states
        assert running.get("/health").status_code == 200
