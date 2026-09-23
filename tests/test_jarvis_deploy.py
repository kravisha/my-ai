"""The build/relaunch controller: §19, and the request file it does not trust.

`scripts/deploy_jarvis.py` is the half of the supervisor that can be tested on
any platform. The PowerShell around it starts processes; this decides whether
anything should be started at all.

The tests that matter are the refusals. A controller that deploys what it is
asked to deploy is a controller that turns "anything that can write a JSON
file" into "anything that can replace Jarvis".
"""

import importlib.util
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from dba import agent as agent_module, main as dba_main, registry, store
from gateway import dbaclient, gaps, identity, selfmod

TOKEN = "test-token-for-jarvis"
OPERATOR_TOKEN = "test-token-for-operator"


def _load():
    """Imported by path: it lives in `scripts/`, which is not a package, and
    that is deliberate - see its docstring on why it is not in `gateway/`."""
    import pathlib

    path = (pathlib.Path(__file__).resolve().parent.parent
            / "scripts" / "deploy_jarvis.py")
    spec = importlib.util.spec_from_file_location("deploy_jarvis", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy = _load()


# The same guard as tests/test_jarvis_selfmod.py, and for the same reason: a
# probe there once disabled a check and the code underneath reached git, which
# made a branch and a commit in the real checkout. This module's subject runs
# `git checkout --force` and the whole test suite, so it is the one place where
# a disabled guard would do the most damage.
_MUTATING = ("commit", "add", "checkout", "push", "reset", "rebase", "merge",
             "clean", "rm", "fetch")


@pytest.fixture(autouse=True)
def _no_mutating_subprocesses(monkeypatch):
    real = subprocess.run

    def guarded(command, **kwargs):
        argv = [str(part) for part in command]
        if argv and "git" in argv[0] and any(part in _MUTATING for part in argv):
            raise AssertionError(
                f"a test tried to run a mutating git command against the real "
                f"repository: {' '.join(argv)}")
        if any("pytest" in part for part in argv):
            raise AssertionError(
                f"a test tried to run the suite inside the suite: {' '.join(argv)}")
        return real(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dba_main.token_env_var("operator_console"), OPERATOR_TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(deploy.OPERATOR_TOKEN_ENV, OPERATOR_TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "f" * 40)
    monkeypatch.setenv(selfmod.DEPLOY_DIR_ENV, str(tmp_path / "deploy"))
    monkeypatch.setenv(deploy.DEPLOY_DIR_ENV, str(tmp_path / "deploy"))
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def service():
    with TestClient(dba_main.app) as client:
        yield client


@pytest.fixture()
def client(service):
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
def ask_dba(service):
    """The controller's own view of the DBA - as the operator, not as Jarvis."""

    def fetch(change_id, token):
        response = service.post(
            "/request",
            json={"action": "get", "requested_by": "operator_console",
                  "actor": "build_controller", "entity_type": "change_proposal",
                  "entity_id": change_id},
            headers={"X-DBA-Agent": "operator_console", "X-DBA-Token": token})
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    return fetch


def _approved_proposal(client, commit="a" * 40):
    gap = gaps.suspect(client, title="missing_tool: read a PDF",
                       description="asked twice", detected_by="test",
                       evidence={"occurrences": 2})
    gap = gaps.transition(client, gap, gaps.INVESTIGATING, evidence="failed")
    gap = gaps.confirm(client, gap, evidence={"case": "pdf"}, impact="high",
                       remedy=gaps.REMEDY_CODE)
    proposal = selfmod.propose(
        client, gap=gap, reason="asked twice", scope="add a pdf tool",
        affected_files=["gateway/tools.py"], expected_benefit="reads statements",
        risk="malformed input", test_plan="tests/test_gateway_tools.py",
        rollback_plan="revert")
    approved = selfmod.decide(client, proposal, decision=selfmod.APPROVE,
                              decided_by="krish")
    client.update(approved["id"], {"status": selfmod.COMMITTED,
                                   "commit_id": commit})
    return client.get(approved["id"])


# =============================================================================
# The request file is not trusted
# =============================================================================


def test_a_request_for_an_unapproved_change_is_refused(client, ask_dba, tmp_path):
    """The whole reason this check exists: a JSON file is not a decision."""
    gap = gaps.suspect(client, title="x", description="y", detected_by="t",
                       evidence={"occurrences": 2})
    gap = gaps.transition(client, gap, gaps.INVESTIGATING, evidence="e")
    gap = gaps.confirm(client, gap, evidence="e", impact="i",
                       remedy=gaps.REMEDY_CODE)
    proposal = selfmod.propose(
        client, gap=gap, reason="r", scope="s",
        affected_files=["gateway/tools.py"], expected_benefit="b", risk="k",
        test_plan="t", rollback_plan="p")

    ok, why = deploy.verify_approved(
        {"change_id": proposal["id"], "commit": "a" * 40},
        fetch=ask_dba)
    assert ok is False
    assert "not approved" in why


def test_a_request_naming_a_different_commit_is_refused(client, ask_dba):
    proposal = _approved_proposal(client, commit="a" * 40)
    ok, why = deploy.verify_approved(
        {"change_id": proposal["id"], "commit": "b" * 40}, fetch=ask_dba)
    assert ok is False
    assert "disagrees" in why or "records" in why


def test_an_approved_request_for_the_recorded_commit_verifies(client, ask_dba):
    proposal = _approved_proposal(client, commit="a" * 40)
    ok, why = deploy.verify_approved(
        {"change_id": proposal["id"], "commit": "a" * 40}, fetch=ask_dba)
    assert ok is True, why


def test_a_request_for_a_change_that_does_not_exist_is_refused(ask_dba):
    ok, why = deploy.verify_approved(
        {"change_id": "change_proposal-0123456789abcdef", "commit": "a" * 40},
        fetch=ask_dba)
    assert ok is False


def test_a_request_with_no_change_id_is_refused():
    ok, why = deploy.verify_approved({"commit": "a" * 40})
    assert ok is False
    assert "change_id" in why


def test_without_an_operator_token_the_controller_refuses(monkeypatch):
    """It cannot verify, so it does not act. An unverifiable deploy request is
    not a safer one for being urgent."""
    monkeypatch.delenv(deploy.OPERATOR_TOKEN_ENV, raising=False)
    ok, why = deploy.verify_approved({"change_id": "change_proposal-0" * 1})
    assert ok is False
    assert deploy.OPERATOR_TOKEN_ENV in why


def test_a_dba_that_cannot_be_reached_is_a_refusal_not_a_deploy():
    def dead(change_id, token):
        raise OSError("connection refused")

    ok, why = deploy.verify_approved({"change_id": "x", "commit": "y"}, fetch=dead)
    assert ok is False
    assert "could not reach" in why


def test_the_controller_authenticates_as_the_operator_not_as_jarvis():
    """The agent whose code is being replaced is not the agent whose
    credentials authorise replacing it."""
    source = (deploy.PROJECT_ROOT / "scripts" / "deploy_jarvis.py").read_text(encoding="utf-8")
    assert deploy.OPERATOR_TOKEN_ENV == "DBA_TOKEN_OPERATOR_CONSOLE"
    assert "DBA_TOKEN_JARVIS" not in source


# =============================================================================
# A red suite never becomes the running build
# =============================================================================


def test_failing_tests_restore_the_previous_commit_and_say_so(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(deploy, "current_commit", lambda: "old" + "0" * 37)
    monkeypatch.setattr(deploy, "checkout",
                        lambda commit: (seen.append(commit), (True, ""))[1])
    monkeypatch.setattr(deploy, "stamp_deployed",
                        lambda commit: pytest.fail("stamped a red build"))

    result = deploy.handle(
        {"change_id": "c", "commit": "new" + "0" * 37},
        directory=tmp_path / "deploy",
        verify=lambda request: (True, ""),
        tester=lambda: {"passed": False, "ran": True, "why": "pytest exit 1",
                        "summary": "2 failed"})

    assert result["status"] == deploy.TESTS_FAILED
    assert result["restored_previous"] is True
    assert seen == ["new" + "0" * 37, "old" + "0" * 37]
    assert result["commit"] == "old" + "0" * 37


def test_tests_that_did_not_run_are_not_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "current_commit", lambda: "old" + "0" * 37)
    monkeypatch.setattr(deploy, "checkout", lambda commit: (True, ""))
    result = deploy.handle(
        {"change_id": "c", "commit": "new" + "0" * 37},
        directory=tmp_path / "deploy", verify=lambda request: (True, ""),
        tester=lambda: {"passed": False, "ran": False, "why": "timed out"})
    assert result["status"] == deploy.TESTS_FAILED


def test_a_green_suite_is_stamped_and_reported_ok(tmp_path, monkeypatch):
    stamped = []
    monkeypatch.setattr(deploy, "current_commit", lambda: "old" + "0" * 37)
    monkeypatch.setattr(deploy, "checkout", lambda commit: (True, ""))
    monkeypatch.setattr(deploy, "stamp_deployed", stamped.append)

    result = deploy.handle(
        {"change_id": "c", "commit": "new" + "0" * 37},
        directory=tmp_path / "deploy", verify=lambda request: (True, ""),
        tester=lambda: {"passed": True, "ran": True, "why": "",
                        "summary": "3900 passed"})

    assert result["status"] == deploy.OK
    assert stamped == ["new" + "0" * 37]
    written = json.loads((tmp_path / "deploy" / deploy.RESULT_FILE).read_text(encoding="utf-8"))
    assert written["status"] == "ok"


def test_a_failed_checkout_leaves_the_running_build_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "current_commit", lambda: "old" + "0" * 37)
    monkeypatch.setattr(deploy, "checkout",
                        lambda commit: (False, "unknown revision"))
    result = deploy.handle(
        {"change_id": "c", "commit": "nope"}, directory=tmp_path / "deploy",
        verify=lambda request: (True, ""),
        tester=lambda: pytest.fail("tested a tree that was never checked out"))
    assert result["status"] == deploy.BUILD_FAILED
    assert result["commit"] == "old" + "0" * 37


# =============================================================================
# Every path leaves a record, and no path leaves the request behind
# =============================================================================


def test_every_outcome_writes_a_result_jarvis_can_read(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "current_commit", lambda: "old" + "0" * 37)
    for verify, tester, expected in (
            (lambda r: (False, "not approved"), None, deploy.REFUSED),
            (lambda r: (True, ""), lambda: {"passed": False, "ran": True,
                                            "why": "x"}, deploy.TESTS_FAILED),
            (lambda r: (True, ""), lambda: {"passed": True, "ran": True,
                                            "why": ""}, deploy.OK)):
        monkeypatch.setattr(deploy, "checkout", lambda commit: (True, ""))
        monkeypatch.setattr(deploy, "stamp_deployed", lambda commit: None)
        directory = tmp_path / "deploy"
        deploy.handle({"change_id": "c", "commit": "new" + "0" * 37},
                      directory=directory, verify=verify,
                      tester=tester or (lambda: {"passed": True, "ran": True}))
        written = json.loads((directory / deploy.RESULT_FILE).read_text(encoding="utf-8"))
        assert written["status"] == expected
        assert written["handled_at"]


def test_a_handled_request_is_removed_so_it_is_not_replayed(tmp_path, monkeypatch):
    """A request still on disk after being acted on is one a restarted
    supervisor acts on again, and "deployed twice" stops being harmless the
    moment one of the two is a rollback."""
    directory = tmp_path / "deploy"
    directory.mkdir(parents=True)
    (directory / deploy.REQUEST_FILE).write_text(
        json.dumps({"change_id": "c", "commit": "new" + "0" * 37}), encoding="utf-8")

    monkeypatch.setattr(deploy, "current_commit", lambda: "old" + "0" * 37)
    monkeypatch.setattr(deploy, "checkout", lambda commit: (True, ""))
    monkeypatch.setattr(deploy, "stamp_deployed", lambda commit: None)
    deploy.handle(deploy.read_request(directory), directory=directory,
                  verify=lambda request: (True, ""),
                  tester=lambda: {"passed": True, "ran": True})

    assert deploy.read_request(directory) is None


def test_a_rollback_request_moves_to_the_baseline(client, ask_dba, tmp_path,
                                                  monkeypatch):
    proposal = _approved_proposal(client, commit="a" * 40)
    request = selfmod.request_rollback(client, proposal, why="post-change failure")
    assert request["to_version"] == proposal["baseline_version"]

    seen = []
    monkeypatch.setattr(deploy, "current_commit", lambda: "a" * 40)
    monkeypatch.setattr(deploy, "checkout",
                        lambda commit: (seen.append(commit), (True, ""))[1])
    monkeypatch.setattr(deploy, "stamp_deployed", lambda commit: None)
    result = deploy.handle(request, directory=tmp_path / "deploy",
                           verify=lambda r: deploy.verify_approved(r, fetch=ask_dba),
                           tester=lambda: {"passed": True, "ran": True})

    assert result["status"] == deploy.OK
    assert seen == [proposal["baseline_version"]]


# =============================================================================
# Where this file lives is part of the design
# =============================================================================


def test_jarvis_cannot_propose_changing_the_build_controller():
    """§16: a controller Jarvis could rewrite is source control and the
    approval gate bypassed in one approved step."""
    from gateway import introspect

    allowed, why = introspect.may_modify("scripts/deploy_jarvis.py")
    assert allowed is False
    assert "outside Jarvis's own runtime" in why
    # but he may read it: §14 is analysis, and understanding what deploys him
    # is exactly the kind of analysis it grants.
    assert introspect.may_read("scripts/deploy_jarvis.py")[0] is True


def test_the_supervisor_starts_the_dba_before_the_gateway():
    """§3 step 3, and §38 q2 - which the repository answered "no" before this."""
    import pathlib

    script = (pathlib.Path(__file__).resolve().parent.parent
              / "scripts" / "keep-jarvis-up.ps1").read_text(encoding="utf-8")
    body = script[script.index("while ($true)"):]
    assert "DBA-Alive" in body and "Gateway-Alive" in body
    assert body.index("DBA-Alive") < body.index("Gateway-Alive")
    assert "dba.main:app" in script
    assert "Deploy-IfRequested" in body
