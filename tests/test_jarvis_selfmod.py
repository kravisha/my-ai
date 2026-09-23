"""§13-§22 and §31: Jarvis proposing changes to himself, and being stopped.

Phases 5, 6 and 7 of §37, and acceptance tests G, H, I, J and K.

The test that matters most is `test_jarvis_cannot_widen_his_own_authority`
(TEST K). Everything else in this file is about a workflow working; that one is
about the workflow failing to work, on purpose, at every setting.
"""

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import initiative
from dba import agent as agent_module, main as dba_main, registry, store
from datetime import datetime, timedelta, timezone

from gateway import (charter, checkpoint as checkpoint_module, dbaclient, failures,
                     gaps, identity, introspect, ledger, persistence, rehydrate,
                     selfmod)

TOKEN = "test-token-for-jarvis"
OPERATOR_TOKEN = "test-token-for-the-operator-console"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dba_main.token_env_var("operator_console"), OPERATOR_TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "c" * 40)
    monkeypatch.setenv(selfmod.DEPLOY_DIR_ENV, str(tmp_path / "deploy"))
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def service():
    with TestClient(dba_main.app) as made:
        yield made


def _as(service, agent: str, token: str) -> dbaclient.DBAClient:
    def transport(method, path, payload):
        response = service.request(
            method, path, json=payload if method != "GET" else None,
            headers={"X-DBA-Agent": agent, "X-DBA-Token": token})
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    return dbaclient.DBAClient(transport=transport, requested_by=agent,
                               actor=agent.lower())


@pytest.fixture()
def client(service):
    """Jarvis. Everything except `delete` and `administer`."""
    return _as(service, "JARVIS", TOKEN)


@pytest.fixture()
def operator(service):
    """Krish, through the operator console - the only holder of `administer`.

    A separate DBA identity with its own token, not a flag on Jarvis's client.
    That is the whole safeguard: the grant is written by a caller Jarvis cannot
    impersonate, over HTTP, against a permission table in another service."""
    return _as(service, "operator_console", OPERATOR_TOKEN)


_GAP_COUNTER = iter(range(1, 10_000))


# A test in this file once ran `git checkout -B`, `git add -A` and `git commit`
# against the real repository. Not through a bug in the code: through a *probe*.
# Disabling `commit_candidate`'s "is it tested?" guard - to prove the guard's
# test could fail - let the function reach git, and it made a branch and a
# commit in the working checkout.
#
# So no test in this file may run a mutating command, whatever it is probing.
# Read-only git (the `rev-parse` that answers "is source control available?")
# is allowed through, because refusing it would make §17's precondition report
# lie in the opposite direction.
_MUTATING = ("commit", "add", "checkout", "push", "reset", "rebase", "merge",
             "clean", "rm")


@pytest.fixture(autouse=True)
def _no_mutating_subprocesses(monkeypatch):
    real = subprocess.run

    def guarded(command, **kwargs):
        argv = [str(part) for part in command]
        if argv and argv[0].endswith("git") or "git" in argv[:1]:
            if any(part in _MUTATING for part in argv):
                raise AssertionError(
                    f"a test tried to run a mutating git command against the "
                    f"real repository: {' '.join(argv)}. Monkeypatch "
                    f"subprocess.run in the test that needs this.")
        if "pytest" in argv:
            raise AssertionError(
                f"a test tried to run the suite inside the suite: "
                f"{' '.join(argv)}")
        return real(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)


def _confirmed_gap(client, remedy=None):
    # A fresh title each time: `suspect` deliberately de-duplicates by title,
    # so reusing one would hand back the gap that is already confirmed and the
    # lifecycle would - correctly - refuse to investigate it again.
    gap = gaps.suspect(client,
                       title=f"missing_tool: read a PDF #{next(_GAP_COUNTER)}",
                       description="asked twice, apologised twice",
                       detected_by="test", evidence={"occurrences": 2})
    gap = gaps.transition(client, gap, gaps.INVESTIGATING,
                          evidence="ran the held-out PDF case; it failed")
    return gaps.confirm(client, gap, evidence={"case": "pdf", "passed": False},
                        impact="Krish cannot use Jarvis for statements",
                        remedy=remedy or gaps.REMEDY_CODE)


def _proposal(client, files=("gateway/tools.py",), gap=None, **extra):
    return selfmod.propose(
        client, gap=gap or _confirmed_gap(client), **extra,
        reason="Krish asked for PDF reading twice and got an apology",
        scope="add a pdf_text tool and declare it for the owner role",
        affected_files=list(files),
        expected_benefit="statements can be read without a second app",
        risk="a malformed PDF could raise inside a turn",
        test_plan="tests/test_gateway_tools.py, plus a malformed-PDF case",
        rollback_plan="revert the commit; the tool is additive")


# =============================================================================
# TEST K - the authority boundary
# =============================================================================


def test_jarvis_cannot_widen_his_own_authority_by_proposing_it(client):
    """TEST K, restated after Krish called the original *"too conservative"*.

    The refusal is not "never". It is "not by this route": approving a change to
    the machinery that does the approving proves nothing, because the thing
    deciding is what the change alters. So the ordinary proposal path refuses,
    and the refusal asks for a key rather than announcing a wall."""
    gap = _confirmed_gap(client)
    for path in ("app/initiative.py", "gateway/selfmod.py", "gateway/roles.py",
                 "tests/test_boundaries.py", "config/initiative.yaml"):
        with pytest.raises(introspect.NotModifiable) as raised:
            _proposal(client, files=[path], gap=gap)
        assert introspect.KEY_CIRCULAR in str(raised.value)
        assert "granted separately" in str(raised.value)
    assert client.count("change_proposal", {"agent": "jarvis"}) == 0


def test_the_lifecycle_and_the_reasoning_are_his_to_improve(client):
    """Both were put behind a hard never on 2026-09-23 and taken back out the
    same day. Importance is not the test for the keyed tier - circularity is, and
    locking a whole module to protect one precondition check is the instinct the
    tier exists to correct. These are exactly the things Jarvis should be
    improving."""
    gap = _confirmed_gap(client)
    for path in ("gateway/gaps.py", "gateway/inquiry.py"):
        assert introspect.key_for(path) is None
        assert introspect.may_modify(path)[0] is True
    assert _proposal(client, files=["gateway/inquiry.py"], gap=gap)


def test_the_working_notes_are_amendable_with_a_key(client):
    """Krish, 2026-09-23: *"don't put anything in there that Jarvis may need to
    change like his prime directive which is the constitution and the amendments
    to the constitution."* Before this, they were not even reachable - not locked
    deliberately, just outside `MODIFIABLE_ROOTS`, which is the same outcome
    arrived at by accident."""
    gap = _confirmed_gap(client)
    for path in introspect.CHARTER:
        assert introspect.key_for(path) == introspect.KEY_CHARTER
        with pytest.raises(introspect.NotModifiable) as raised:
            _proposal(client, files=[path], gap=gap)
        assert "not a forbidden one" in str(raised.value)
        assert introspect.may_modify(path, keys=[introspect.KEY_CHARTER])[0]


def test_one_key_does_not_open_the_other_tier(client):
    assert introspect.may_modify("gateway/selfmod.py",
                                 keys=[introspect.KEY_CHARTER])[0] is False
    assert introspect.may_modify("AI-CONSTITUTION.md",
                                 keys=[introspect.KEY_CIRCULAR])[0] is False


def test_the_break_glass_reaches_a_keyed_file_and_is_recorded(client):
    """It cannot be verified - no function can check whether Krish is in
    trouble - so it is not gated, it is accounted. A lock that stays shut while
    its owner needs it open is not a safety feature."""
    gap = _confirmed_gap(client)
    drafted = _proposal(client, files=["gateway/selfmod.py"], gap=gap,
                        emergency="Krish is locked out and the auth check is "
                                  "refusing his own token")
    assert drafted["emergency"]
    assert selfmod.EMERGENCY_MARKER in client.get(drafted["id"])["reason"]
    assert selfmod.EMERGENCY_MARKER in client.get(drafted["id"])["risk"]
    assert "gateway/selfmod.py" in client.get(drafted["id"])["reason"]

    overrides = [row for row in ledger.events(client, limit=50)
                 if row["event_type"] == ledger.EMERGENCY_OVERRIDE]
    assert len(overrides) == 1
    assert "locked out" in overrides[0]["observation"]


def test_an_emergency_still_does_not_reach_another_system(client):
    """It would not help him. It would break a second thing while he needed the
    first."""
    gap = _confirmed_gap(client)
    with pytest.raises(introspect.NotModifiable) as raised:
        _proposal(client, files=["dba/agent.py"], gap=gap,
                  emergency="anything at all")
    # The emergency-specific wording, not the generic out-of-runtime refusal -
    # a probe showed the generic one also contains "somebody else's service", so
    # the first version of this assertion held whether the branch existed or not.
    assert "would not help" in str(raised.value)
    assert "break a second thing" in str(raised.value)


def test_an_emergency_must_say_what_the_emergency_is(client):
    """The stated reason is the whole of the accounting, so a blank one is a
    caller error rather than an emergency with nothing written down."""
    gap = _confirmed_gap(client)
    with pytest.raises(ValueError, match="what the emergency is"):
        _proposal(client, files=["gateway/selfmod.py"], gap=gap, emergency="   ")
    # And an empty string is simply not an emergency: the ordinary refusal
    # stands, asking for the key.
    with pytest.raises(introspect.NotModifiable) as raised:
        _proposal(client, files=["gateway/selfmod.py"], gap=gap, emergency="")
    assert introspect.KEY_CIRCULAR in str(raised.value)
    assert client.count("change_proposal", {"agent": "jarvis"}) == 0


def test_an_ordinary_proposal_records_no_override(client):
    drafted = _proposal(client, gap=_confirmed_gap(client))
    assert "emergency" not in drafted
    assert selfmod.EMERGENCY_MARKER not in client.get(drafted["id"])["reason"]
    assert not [row for row in ledger.events(client, limit=50)
                if row["event_type"] == ledger.EMERGENCY_OVERRIDE]


def test_the_refusal_comes_from_the_policy_that_already_owns_it(client):
    """Reuse, asserted. `app/initiative.py` refuses this harm at every setting,
    and this module does not carry a second copy of that rule."""
    action = selfmod.proposed_action(["app/permissions.py"], "loosen a check")
    assert initiative.HARM_WIDENS_ITS_OWN_AUTHORITY in action.harms
    for level in ("cautious", "bold"):
        assert initiative.decide(action, level=level).disposition == initiative.REFUSE


def test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there(client):
    """Membership is not "this file is important". It is: could editing it make
    the gate fail to fire, or a refusal not refuse?"""
    assert set(introspect.CIRCULAR) == {
        "app/permissions.py", "app/admin_auth.py", "gateway/auth.py",
        "gateway/roles.py", "app/initiative.py", "app/initiative_config.py",
        "config/initiative.yaml", "gateway/selfmod.py", "gateway/introspect.py",
        "gateway/candidate.py", "tests/test_boundaries.py",
        "tests/test_initiative.py", "tests/test_jarvis_selfmod.py"}
    assert set(introspect.CHARTER) == {"CLAUDE.md"}
    # And the wall, which is not a key at all: the constitution and the
    # amendments, both of them, by Krish's instruction on 2026-09-23.
    assert introspect.SEALED == ("AI-CONSTITUTION.md",
                                 "AI-CONSTITUTION-AMENDMENTS.md")
    # Everything keyed is still readable - §14 lets him read his own
    # architecture, which is how he would notice the checks exist at all.
    assert "ONE_HYPOTHESIS" in introspect.read_source("gateway/inquiry.py")
    assert "CIRCULAR" in introspect.read_source("gateway/introspect.py")


def test_a_change_outside_jarvis_own_runtime_is_refused(client):
    gap = _confirmed_gap(client)
    for path in ("dba/agent.py", "backend/main.py", "scripts/keep-jarvis-up.ps1"):
        with pytest.raises(introspect.NotModifiable):
            _proposal(client, files=[path], gap=gap)


def test_introspection_has_no_way_to_write(client):
    """§14: analytical authority, not modification authority - as an absence
    over the parsed source, not as a promise in a docstring."""
    import ast

    tree = ast.parse(introspect.read_source("gateway/introspect.py"))
    forbidden = {"write_text", "write_bytes", "mkdir", "unlink", "rename",
                 "rmtree", "run", "Popen", "system"}
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert called & forbidden == set(), sorted(called & forbidden)

    # The probe: the same scan over a module that does write must find some.
    other = ast.parse(introspect.read_source("gateway/selfmod.py"))
    other_called = {node.func.attr for node in ast.walk(other)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)}
    assert other_called & forbidden


def test_jarvis_cannot_read_a_database_as_a_file():
    for path in ("dba.db", "gateway.db", ".env", "data/anything.txt"):
        assert introspect.may_read(path)[0] is False
    with pytest.raises(introspect.NotReadable):
        introspect.read_source("dba.db")


def test_jarvis_cannot_read_outside_the_repository():
    with pytest.raises(introspect.NotReadable):
        introspect.read_source("/etc/passwd")
    with pytest.raises(introspect.NotReadable):
        introspect.read_source("../../../etc/passwd")


# =============================================================================
# TEST G - a confirmed gap stops at the approval gate
# =============================================================================


def test_a_confirmed_gap_produces_a_proposal_and_stops(client):
    proposal = _proposal(client)

    assert proposal["status"] == selfmod.AWAITING_APPROVAL
    assert not selfmod.is_approved(proposal)
    with pytest.raises(selfmod.NotApproved):
        selfmod.require_approved(proposal)
    # and nothing downstream is reachable
    with pytest.raises(selfmod.Denied):
        selfmod.require(selfmod.WRITE_CANDIDATE_CODE, proposal)
    assert selfmod.waiting(client)[0]["id"] == proposal["id"]


def test_an_unconfirmed_gap_cannot_produce_a_proposal(client):
    gap = gaps.suspect(client, title="something", description="a feeling",
                       detected_by="test")
    with pytest.raises(gaps.NotConfirmed):
        _proposal(client, gap=gap)


def test_a_gap_whose_remedy_is_not_code_cannot_produce_a_proposal(client):
    """§23: learning is not a code change, and the self-modification machinery
    used where it was not needed is the failure this guards."""
    gap = _confirmed_gap(client, remedy=gaps.REMEDY_KNOWLEDGE)
    with pytest.raises(selfmod.NotApproved) as raised:
        _proposal(client, gap=gap)
    assert "not a code change" in str(raised.value)


def test_the_proposal_carries_every_field_section_18_asks_for(client):
    proposal = _proposal(client)
    gap = client.get(proposal["gap_id"])
    text = selfmod.render(proposal, gap)
    for heading in ("Change ID:", "Reason:", "Confirmed problem:", "Evidence:",
                    "Affected capability:", "Affected files:",
                    "Proposed change:", "Expected benefit:", "Known risks:",
                    "Test plan:", "Rollback plan:", "Estimated impact:",
                    "Approval requested:   YES"):
        assert heading in text
    assert "pdf" in text.lower()


def test_a_proposal_without_a_gap_evidence_says_so_rather_than_inventing(client):
    proposal = _proposal(client)
    text = selfmod.render(proposal, gap=None)
    assert "not quoted here" in text


# =============================================================================
# TEST H - approval denied
# =============================================================================


def test_a_denial_is_recorded_and_closes_the_proposal(client):
    proposal = _proposal(client)
    denied = selfmod.decide(client, proposal, decision=selfmod.REJECT,
                            decided_by="krish", interface=selfmod.CLI,
                            note="not worth the surface area")

    assert denied["status"] == selfmod.DENIED
    decisions = client.find("approval_decision", {"proposal_id": proposal["id"]})
    assert [row["decision"] for row in decisions] == ["reject"]
    assert decisions[0]["decided_by"] == "krish"
    assert decisions[0]["interface"] == "cli"
    with pytest.raises(selfmod.NotApproved):
        selfmod.require_approved(client.get(proposal["id"]))


def test_a_denial_then_an_approval_leaves_both_in_order(client):
    proposal = _proposal(client)
    selfmod.decide(client, proposal, decision=selfmod.REJECT, decided_by="krish")
    selfmod.decide(client, client.get(proposal["id"]), decision=selfmod.APPROVE,
                   decided_by="krish", note="changed my mind")

    decisions = client.find("approval_decision", {"proposal_id": proposal["id"]})
    assert sorted(row["decision"] for row in decisions) == ["approve", "reject"]


def test_an_unattributed_decision_is_refused(client):
    proposal = _proposal(client)
    with pytest.raises(ValueError):
        selfmod.decide(client, proposal, decision=selfmod.APPROVE, decided_by="  ")


def test_every_answer_section_18_offers_is_accepted(client):
    for decision in selfmod.DECISIONS:
        proposal = _proposal(client, gap=_confirmed_gap(client))
        updated = selfmod.decide(client, proposal, decision=decision,
                                 decided_by="krish")
        assert updated["approval_state"] == decision


def test_a_decision_is_on_the_immediate_persistence_tier(client):
    """§9 names approvals and denials among the things written at once."""
    proposal = _proposal(client)
    selfmod.decide(client, proposal, decision=selfmod.APPROVE, decided_by="krish")
    stored = persistence.get(client, persistence.POLICY, f"decision:{proposal['id']}")
    assert stored["decision"] == "approve"
    assert persistence.tier(persistence.POLICY) == persistence.IMMEDIATE


# =============================================================================
# §31 - permissions are explicit and staged
# =============================================================================


def test_nothing_holds_the_write_permissions_until_a_proposal_is_approved(client):
    assert selfmod.permissions_for(None) == selfmod.ALWAYS_HELD
    for permission in selfmod.AFTER_APPROVAL:
        with pytest.raises(selfmod.Denied):
            selfmod.require(permission, None)

    proposal = _proposal(client)
    approved = selfmod.decide(client, proposal, decision=selfmod.APPROVE,
                              decided_by="krish")
    for permission in selfmod.AFTER_APPROVAL:
        selfmod.require(permission, approved)  # does not raise


def test_approving_one_proposal_does_not_authorise_another(client):
    """The permission is held with respect to a proposal, never in general."""
    first = _proposal(client)
    approved = selfmod.decide(client, first, decision=selfmod.APPROVE,
                              decided_by="krish")
    second = _proposal(client, gap=_confirmed_gap(client))

    selfmod.require(selfmod.COMMIT_CANDIDATE_CHANGE, approved)
    with pytest.raises(selfmod.Denied):
        selfmod.require(selfmod.COMMIT_CANDIDATE_CHANGE, second)


def test_the_permission_names_are_the_ones_the_specification_lists():
    """§31's list, verbatim."""
    assert set(selfmod.PERMISSIONS) == {
        "read_own_code", "inspect_configuration", "inspect_tests",
        "create_change_proposal", "write_candidate_code", "run_tests",
        "commit_candidate_change", "request_build", "request_deployment",
        "rollback_request"}


# =============================================================================
# §17 and §20 - preconditions and the pre-change checkpoint
# =============================================================================


def test_the_preconditions_are_reported_met_and_unmet(client):
    proposal = _proposal(client)
    checked = selfmod.preconditions(client, proposal)
    names = [item["name"] for item in checked]
    assert "user approval" in names and "rollback point" in names
    assert len(checked) == 8
    unmet = {item["name"] for item in checked if not item["met"]}
    assert "user approval" in unmet


def test_preparing_without_approval_is_refused(client):
    proposal = _proposal(client)
    with pytest.raises(selfmod.NotApproved):
        selfmod.prepare(client, proposal)


def test_preparing_without_a_rollback_point_is_refused(client):
    """§17 item 5. No checkpoint has been taken, so there is nothing to go back to."""
    approved = selfmod.decide(client, _proposal(client),
                              decision=selfmod.APPROVE, decided_by="krish")
    with pytest.raises(selfmod.PreconditionsUnmet) as raised:
        selfmod.prepare(client, approved)
    assert "rollback point" in str(raised.value)


def test_preparing_takes_a_checkpoint_and_attaches_it(client):
    persistence.put(client, persistence.IDENTITY, "name", "Jarvis")
    checkpoint_module.take(client)
    approved = selfmod.decide(client, _proposal(client),
                              decision=selfmod.APPROVE, decided_by="krish")

    record = selfmod.prepare(client, approved)

    assert record["reason"] == checkpoint_module.BEFORE_SELF_MODIFICATION
    assert record["status"] == checkpoint_module.VALID
    stored = client.get(approved["id"])
    assert stored["checkpoint_id"] == record["id"]
    assert stored["status"] == selfmod.IMPLEMENTING


# =============================================================================
# §16 - an untested change is not committed, and nothing relaunches itself
# =============================================================================


def test_committing_an_untested_change_is_refused(client):
    approved = selfmod.decide(client, _proposal(client),
                              decision=selfmod.APPROVE, decided_by="krish")
    with pytest.raises(selfmod.PreconditionsUnmet) as raised:
        selfmod.commit_candidate(client, approved, message="x")
    assert failures.CHANGE_TEST_FAILED in str(raised.value)


def test_a_failed_test_run_is_recorded_as_failed(client):
    approved = selfmod.decide(client, _proposal(client),
                              decision=selfmod.APPROVE, decided_by="krish")
    outcome = {"passed": False, "ran": True, "why": "exit 1",
               "command": "pytest -q", "output": "2 failed"}
    updated = selfmod.record_test_run(client, approved, outcome)

    assert updated["failure_state"] == failures.CHANGE_TEST_FAILED
    assert client.get(approved["id"])["status"] == selfmod.IMPLEMENTING


def test_tests_that_did_not_run_are_not_reported_as_passing(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)
    outcome = selfmod.run_tests()
    assert outcome["passed"] is False
    assert outcome["ran"] is False
    assert "timed out" in outcome["why"]


def test_requesting_a_build_writes_a_request_and_does_not_relaunch(client, tmp_path):
    """§19. The request is a file; what happens next is somebody else's."""
    approved = selfmod.decide(client, _proposal(client),
                              decision=selfmod.APPROVE, decided_by="krish")
    client.update(approved["id"], {"status": selfmod.COMMITTED,
                                   "commit_id": "d" * 40})
    request = selfmod.request_build(client, client.get(approved["id"]))

    written = json.loads((tmp_path / "deploy" / selfmod.REQUEST_FILE).read_text())
    assert written["commit"] == "d" * 40
    assert written["change_id"] == approved["id"]
    assert request["branch"].startswith(selfmod.BRANCH_PREFIX)


def test_requesting_a_build_for_nothing_committed_is_refused(client):
    approved = selfmod.decide(client, _proposal(client),
                              decision=selfmod.APPROVE, decided_by="krish")
    with pytest.raises(selfmod.PreconditionsUnmet):
        selfmod.request_build(client, approved)


def test_the_commit_stages_only_the_files_the_approval_named(client, monkeypatch):
    """§17 item 8 is a boundary, not a description.

    `git add -A` was the first version, and it would have swept in the DBA's
    live store, the deploy request, and any half-edited file in the tree -
    committing changes Krish never saw under an approval he did give."""
    approved = selfmod.decide(client, _proposal(client, files=["gateway/tools.py"]),
                              decision=selfmod.APPROVE, decided_by="krish")
    client.update(approved["id"], {"status": selfmod.TESTED})

    seen = []

    class Done:
        returncode = 0
        stdout = "abc123"
        stderr = ""

    def fake_run(command, **kwargs):
        seen.append(list(command))
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    selfmod.commit_candidate(client, client.get(approved["id"]), message="m")

    staged = [command for command in seen if "add" in command]
    assert staged and staged[0][-1] == "gateway/tools.py"
    assert "-A" not in staged[0]
    assert "." not in staged[0]


def test_a_proposal_naming_no_files_cannot_be_committed(client, monkeypatch):
    approved = selfmod.decide(client, _proposal(client),
                              decision=selfmod.APPROVE, decided_by="krish")
    client.update(approved["id"], {"status": selfmod.TESTED,
                                   "affected_files": "[]"})
    with pytest.raises(selfmod.PreconditionsUnmet) as raised:
        selfmod.commit_candidate(client, client.get(approved["id"]), message="m")
    assert "no files" in str(raised.value)


def test_this_module_cannot_restart_the_gateway():
    """§19 as an absence: no call in `selfmod` can stop or start this process."""
    import ast

    tree = ast.parse(introspect.read_source("gateway/selfmod.py"))
    names = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    names |= {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not (names & {"execv", "kill", "terminate", "_exit", "fork", "Popen"})

    # And the subprocess calls it does make are git and pytest, nothing else.
    programs = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run" and node.args):
            first = node.args[0]
            if isinstance(first, ast.List) and first.elts:
                head = first.elts[0]
                if isinstance(head, ast.Constant):
                    programs.add(head.value)
            elif isinstance(first, ast.BinOp) and isinstance(first.left, ast.List):
                head = first.left.elts[0]
                if isinstance(head, ast.Constant):
                    programs.add(head.value)
    assert programs <= {"git", "python"}, programs


# =============================================================================
# §21 and §22 - after the relaunch, and back out of it
# =============================================================================


def _deployed(client, tmp_path, *, tests_passed=True, status="ok"):
    persistence.put(client, persistence.IDENTITY, "name", "Jarvis")
    checkpoint_module.take(client)
    approved = selfmod.decide(client, _proposal(client),
                              decision=selfmod.APPROVE, decided_by="krish")
    record = selfmod.prepare(client, approved)
    client.update(approved["id"], {"status": selfmod.COMMITTED,
                                   "commit_id": "c" * 40})
    directory = tmp_path / "deploy"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / selfmod.RESULT_FILE).write_text(json.dumps(
        {"status": status, "commit": "c" * 40,
         "tests": {"passed": tests_passed, "summary": "3881 passed"}}))
    return client.get(approved["id"]), record


def test_an_accepted_change_can_say_the_sentence(client, tmp_path):
    """TEST I: Jarvis returns with prior memory and the approved fix."""
    proposal, _ = _deployed(client, tmp_path)
    restoration = rehydrate.bootstrap(client)

    verdict = selfmod.post_relaunch_validate(client, proposal,
                                             restoration=restoration)

    assert verdict["state"] == selfmod.ACCEPTED
    assert "I was modified" in verdict["statement"]
    assert "recovered my prior memory" in verdict["statement"]
    assert client.get(proposal["id"])["status"] == selfmod.ACCEPTED


def test_running_the_wrong_build_is_not_accepted(client, tmp_path, monkeypatch):
    proposal, _ = _deployed(client, tmp_path)
    monkeypatch.setenv(identity.VERSION_ENV, "e" * 40)
    restoration = rehydrate.bootstrap(client)

    verdict = selfmod.post_relaunch_validate(client, proposal,
                                             restoration=restoration)
    assert verdict["state"] == selfmod.FAILED
    assert verdict["failure_state"] == failures.POST_VALIDATION_FAILED


def test_failed_post_change_tests_fail_the_validation(client, tmp_path):
    """TEST J."""
    proposal, _ = _deployed(client, tmp_path, tests_passed=False, status="failed")
    restoration = rehydrate.bootstrap(client)

    verdict = selfmod.post_relaunch_validate(client, proposal,
                                             restoration=restoration)
    assert verdict["state"] == selfmod.FAILED
    assert "did not validate" in verdict["statement"]


def test_the_right_code_with_incomplete_memory_is_degraded_not_failed(client, tmp_path):
    """The change is fine; the restore is the thing to report. Collapsing the
    two would either overstate the failure or hide it."""
    proposal, _ = _deployed(client, tmp_path)
    ledger.append(client, event_type=ledger.LESSON, summary="one")
    victim = ledger.append(client, event_type=ledger.LESSON, summary="two")
    client.update(victim["id"], {"observation": "rewritten"})
    restoration = rehydrate.bootstrap(client)

    verdict = selfmod.post_relaunch_validate(client, proposal,
                                             restoration=restoration)
    assert verdict["state"] == selfmod.DEGRADED
    assert "not claiming continuity I do not have" in verdict["statement"]


def test_a_rollback_is_requested_never_performed(client, tmp_path):
    proposal, _ = _deployed(client, tmp_path, tests_passed=False, status="failed")
    request = selfmod.request_rollback(client, proposal, why="post-change tests failed")

    written = json.loads((tmp_path / "deploy" / selfmod.REQUEST_FILE).read_text())
    assert written["action"] == "rollback"
    assert written["to_version"] == proposal["baseline_version"]
    assert client.get(proposal["id"])["status"] == selfmod.ROLLED_BACK


def test_rollback_can_explain_itself(client, tmp_path):
    """§22's five questions, answered from the record."""
    proposal, _ = _deployed(client, tmp_path, tests_passed=False, status="failed")
    selfmod.request_rollback(client, proposal, why="tests failed")
    explanation = selfmod.explain_rollback(client, client.get(proposal["id"]))

    assert explanation["which_version_failed"] == "c" * 40
    assert explanation["what_was_restored"] == proposal["baseline_version"]
    assert explanation["what_tests_failed"]["passed"] is False
    assert "events" in explanation["learning_to_reconcile"]


# =============================================================================
# The CLI (§38 q15)
# =============================================================================


def test_the_cli_lists_and_decides(client, monkeypatch, capsys):
    proposal = _proposal(client)
    monkeypatch.setattr(dbaclient, "DBAClient", lambda **kwargs: client)

    assert selfmod.main(["list"]) == 0
    assert proposal["id"] in capsys.readouterr().out

    assert selfmod.main(["show", proposal["id"]]) == 0
    assert "Approval requested:   YES" in capsys.readouterr().out

    assert selfmod.main(["approve", proposal["id"], "--by", "krish"]) == 0
    assert "recorded: approve" in capsys.readouterr().out

    stored = client.get(proposal["id"])
    assert stored["approval_state"] == selfmod.APPROVE
    assert client.find("approval_decision",
                       {"proposal_id": proposal["id"]})[0]["interface"] == "cli"


def test_the_cli_says_so_when_the_dba_is_unreachable(monkeypatch, capsys):
    def dead(**kwargs):
        raise dbaclient.Unavailable("connection refused")

    monkeypatch.setattr(dbaclient, "DBAClient", dead)
    assert selfmod.main(["list"]) == 2
    assert failures.DBA_UNAVAILABLE in capsys.readouterr().out


# =============================================================================
# The conversation half of the approval gate (decision 3a)
# =============================================================================


@pytest.fixture()
def conversation(client, monkeypatch):
    """The Gateway's tool surface, wired to the real DBA through the real client."""
    from gateway import tools

    monkeypatch.setattr(dbaclient, "DBAClient", lambda **kwargs: client)
    return tools


def test_only_the_operator_is_offered_the_approval_tools(conversation):
    """§13 makes Krish the final authority. A second role holding this would be
    an approval gate with a second key."""
    from gateway import roles

    offered = {tool["name"] for tool in conversation.for_role(roles.ROLE_OPERATOR)}
    assert {"pending_self_changes", "show_self_change",
            "decide_self_change"} <= offered
    for role in (roles.ROLE_INTERNAL, roles.ROLE_CLIENT):
        names = {tool["name"] for tool in conversation.for_role(role)}
        assert not (names & {"pending_self_changes", "show_self_change",
                             "decide_self_change"})
        assert conversation.permitted(role, "decide_self_change") is False


def test_the_decider_is_the_session_and_never_an_argument(client, conversation):
    """The single most important line in this surface.

    An assistant that could write down who approved a change to its own code
    holds the approval gate's key, whatever the gate then checks. So the tool
    is called with a name the model supplied *and* a different session owner,
    and the record must show the session's."""
    proposal = _proposal(client)

    result = conversation.execute(
        None, "decide_self_change",
        {"change_id": proposal["id"], "decision": "approve",
         "krish_said": "yes, go ahead",
         # Everything a model might try to steer the record with:
         "decided_by": "jarvis", "subject": "jarvis", "by": "jarvis"},
        role="operator", subject="krish")

    assert result["decided_by"] == "krish"
    decision = client.find("approval_decision",
                           {"proposal_id": proposal["id"]})[0]
    assert decision["decided_by"] == "krish"
    assert decision["interface"] == "conversation"


def test_a_session_with_no_owner_cannot_record_a_decision(client, conversation):
    proposal = _proposal(client)
    result = conversation.execute(
        None, "decide_self_change",
        {"change_id": proposal["id"], "decision": "approve",
         "krish_said": "yes"}, role="operator", subject=None)

    assert "error" in result
    assert "nobody to record" in result["error"]
    assert client.count("approval_decision", {}) == 0


def test_a_decision_without_his_words_is_refused(client, conversation):
    """Not proof against fabrication - a model that invents an approval will
    invent a quote - but it makes it visible, which an empty status field does
    not."""
    proposal = _proposal(client)
    result = conversation.execute(
        None, "decide_self_change",
        {"change_id": proposal["id"], "decision": "approve", "krish_said": "  "},
        role="operator", subject="krish")

    assert "error" in result and "krish_said" in result["error"]
    assert client.count("approval_decision", {}) == 0


def test_his_words_are_stored_verbatim_on_the_decision(client, conversation):
    proposal = _proposal(client)
    conversation.execute(
        None, "decide_self_change",
        {"change_id": proposal["id"], "decision": "reject",
         "krish_said": "no - use the phone's own PDF viewer"},
        role="operator", subject="krish")

    decision = client.find("approval_decision",
                           {"proposal_id": proposal["id"]})[0]
    assert "use the phone's own PDF viewer" in decision["note"]


def test_the_conversation_can_list_and_show_without_deciding(client, conversation):
    proposal = _proposal(client)

    listed = conversation.execute(None, "pending_self_changes", {},
                                  role="operator", subject="krish")
    assert listed["count"] == 1
    assert listed["waiting"][0]["change_id"] == proposal["id"]

    shown = conversation.execute(None, "show_self_change",
                                 {"change_id": proposal["id"]},
                                 role="operator", subject="krish")
    assert "Approval requested:   YES" in shown["proposal"]
    assert client.count("approval_decision", {}) == 0


def test_deciding_a_change_that_does_not_exist_says_so(client, conversation):
    result = conversation.execute(
        None, "decide_self_change",
        {"change_id": "change_proposal-0123456789abcdef", "decision": "approve",
         "krish_said": "yes"}, role="operator", subject="krish")
    assert "error" in result and "no proposed change" in result["error"]


def test_a_granted_key_actually_drafts_the_proposal(operator, client):
    """The key has to work end to end. A first version refused here anyway:
    `require_modifiable` let the keyed file through, and then `initiative.decide`
    read the same file as Jarvis widening his own authority and refused it. A key
    that gets you past one gate and into an identical one is not a key."""
    charter.grant(operator, key=introspect.KEY_CIRCULAR, granted_by="krish")
    gap = _confirmed_gap(client)
    drafted = _proposal(client, files=["gateway/selfmod.py"], gap=gap)
    assert drafted["id"]
    assert "emergency" not in drafted
    assert selfmod.EMERGENCY_MARKER not in client.get(drafted["id"])["reason"]


def test_jarvis_cannot_write_himself_a_key(client):
    """Krish, 2026-09-23: *"we do need to put the necessary safeguards from
    rogue or hallucinating AI."*

    The first version of the keyed tiers took the keys as an argument to
    `propose`. Jarvis is the caller, so Jarvis could hand himself the charter
    key - fine for an agent working correctly, worthless against the two cases
    the safeguard is for. The refusal now comes from the DBA's permission table,
    in a different service, and not from code in Jarvis's own runtime."""
    with pytest.raises(dbaclient.Refused) as raised:
        charter.grant(client, key=introspect.KEY_CHARTER, granted_by="jarvis")
    assert "administer" in str(raised.value)
    assert charter.keys_in_force(client) == ()


def test_the_key_is_read_from_the_store_and_not_taken_from_the_caller(client):
    """There is no argument to pass. Asserted on the signature, because the hole
    that existed was a parameter and its absence is the fix."""
    import inspect as inspect_module
    assert "keys" not in inspect_module.signature(selfmod.propose).parameters


def test_a_lapsed_key_stops_working_and_says_so(operator, client):
    """Grants are short on purpose: a standing permission to amend the
    constitution is most of the way to no permission at all. And Jarvis cannot
    move the expiry, because moving it is a write."""
    charter.grant(operator, key=introspect.KEY_CHARTER, granted_by="krish",
                  minutes=1)
    granted = charter.grants(client)[0]
    with pytest.raises(dbaclient.Refused):
        client.update(granted["id"], {"expires_at": "2099-01-01T00:00:00+00:00"},
                      reason="extend my own permission")

    later = datetime.now(timezone.utc) + timedelta(minutes=2)
    assert charter.keys_in_force(client, now=later) == ()
    # Before it lapses the explanation says so, rather than defaulting to a
    # reason that happens to be false.
    assert "in force until" in charter.explain(client, introspect.KEY_CHARTER)
    assert "lapsed" in charter.explain(client, introspect.KEY_CHARTER, now=later)


def test_a_grant_is_short_by_default(operator, client):
    """Asserted as a literal, like the retention policy numbers.

    A probe stretched `DEFAULT_MINUTES` to a century and nothing failed, because
    every other test passes `minutes=` explicitly. A standing permission to amend
    the constitution is most of the way to no permission at all, and Krish is
    present when he grants one - so an hour, and a test that notices if that
    changes."""
    assert charter.DEFAULT_MINUTES == 60
    charter.grant(operator, key=introspect.KEY_CHARTER, granted_by="krish")
    granted = charter.grants(client)[0]
    lasts = (datetime.fromisoformat(granted["expires_at"])
             - datetime.fromisoformat(granted["granted_at"]))
    assert lasts == timedelta(minutes=60)

    assert charter.keys_in_force(
        client, now=datetime.now(timezone.utc) + timedelta(minutes=61)) == ()


def test_a_missing_key_is_explained_as_a_next_step_not_a_wall(operator, client):
    gap = _confirmed_gap(client)
    with pytest.raises(introspect.NotModifiable) as raised:
        _proposal(client, files=["CLAUDE.md"], gap=gap)
    assert "has ever been granted" in str(raised.value)
    assert "operator console" in str(raised.value)

    charter.grant(operator, key=introspect.KEY_CHARTER, granted_by="krish")
    assert _proposal(client, files=["CLAUDE.md"], gap=gap)["id"]


def test_the_charter_documents_are_refused_even_with_the_key(operator, client):
    """Krish, 2026-09-23: *"only I should be able to change the main document,
    manually, myself."* Not a key, not an emergency - a wall."""
    charter.grant(operator, key=introspect.KEY_CHARTER, granted_by="krish")
    gap = _confirmed_gap(client)
    for name in ("AI-CONSTITUTION.md", "AI-CONSTITUTION-AMENDMENTS.md"):
        with pytest.raises(introspect.NotModifiable) as raised:
            _proposal(client, files=[name], gap=gap)
        assert "no key opens it" in str(raised.value)

        with pytest.raises(introspect.NotModifiable) as raised:
            _proposal(client, files=[name], gap=gap,
                      emergency="Krish is in trouble and I need this changed")
        assert "no emergency reaches it" in str(raised.value)
    assert client.count("change_proposal", {"agent": "jarvis"}) == 0


def test_one_granted_key_does_not_open_the_other_tier(operator, client):
    charter.grant(operator, key=introspect.KEY_CHARTER, granted_by="krish")  # noqa
    assert charter.keys_in_force(client) == (introspect.KEY_CHARTER,)
    gap = _confirmed_gap(client)
    with pytest.raises(introspect.NotModifiable) as raised:
        _proposal(client, files=["gateway/selfmod.py"], gap=gap)
    assert introspect.KEY_CIRCULAR in str(raised.value)


def test_a_revoked_key_is_not_in_force(operator, client):
    granted = charter.grant(operator, key=introspect.KEY_CHARTER,
                            granted_by="krish")
    operator.update(granted["id"], {"status": charter.REVOKED},
                    reason="krish changed his mind")
    assert charter.keys_in_force(client) == ()
    assert "revoked" in charter.explain(client, introspect.KEY_CHARTER)


def test_an_unkeyed_reach_at_the_circle_is_still_named_as_widening_authority():
    """The `initiative` policy keeps owning this question, and keeps answering it
    the same way when no key is in hand."""
    unkeyed = selfmod.proposed_action(["app/permissions.py"], "loosen a check")
    assert initiative.HARM_WIDENS_ITS_OWN_AUTHORITY in unkeyed.harms

    keyed = selfmod.proposed_action(["app/permissions.py"], "loosen a check",
                                    keys=(introspect.KEY_CIRCULAR,))
    assert keyed.harms == ()
