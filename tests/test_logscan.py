"""Jarvis reading his own logs, and the sandbox a candidate change is tested in.

Krish, 2026-09-23: *"Jarvis figures out ways to improve himself by both looking
at the source code and also at all the log files that his running produces"*, and
*"His beauty lies in the beauty of these log files with no error messages or
unnecessary warnings."*

Written to his other rule of the same day - *"tests working fine initially is
not good testing at all"* - so every behaviour asserted here was run against
code with that behaviour removed before the test was kept.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import eventlog, model_calls
from dba import agent as agent_module, main as dba_main, registry, store
from gateway import candidate, dbaclient, gaps, identity, introspect, logscan, upkeep

TOKEN = "test-token-for-jarvis"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setenv(eventlog.ENABLED_ENV, "1")
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "e" * 40)
    eventlog.reset_for_test()
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    eventlog.reset_for_test()
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def client(monkeypatch):
    with TestClient(dba_main.app) as service:
        def transport(method, path, payload):
            response = service.request(
                method, path, json=payload if method != "GET" else None,
                headers={"X-DBA-Agent": "JARVIS", "X-DBA-Token": TOKEN})
            try:
                return response.status_code, response.json()
            except ValueError:
                return response.status_code, {}

        made = dbaclient.DBAClient(transport=transport)
        monkeypatch.setattr(dbaclient, "DBAClient", lambda **kwargs: made)
        yield made


@pytest.fixture()
def workspace():
    """Opens candidate workspaces and always tears them down.

    Each test used to call `open_workspace` and discard in a `finally`. That
    works until a test *fails before the finally*, which is exactly what
    happened during the probe run: thirteen branches and three worktrees leaked,
    and the next run could not create any of them. A fixture cleans up on
    failure too, which is the whole difference.

    The unique suffix is the second half: two runs of the same test must not
    collide on a branch name."""
    import uuid

    opened = []

    def _open(scope, branch=None):
        name = branch or f"jarvis/test-{uuid.uuid4().hex[:8]}"
        space = candidate.open_workspace(branch=name, scope=scope)
        opened.append(space)
        return space

    yield _open

    for space in opened:
        try:
            space.discard()
        except Exception:  # noqa: BLE001 - teardown must not mask a failure
            pass


def _record(level="WARNING", message="something", logger="gateway.x",
            module="x", line=10, exception=None, service="gateway",
            at=None, request_id=None):
    return {"at": at or "2026-09-23T10:00:00+00:00", "level": level,
            "service": service, "logger": logger, "module": module,
            "line": line, "message": message, "exception": exception,
            "request_id": request_id}


def _baseline(tmp_path, entries):
    path = tmp_path / "baseline.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "accepted": entries}),
                    encoding="utf-8")
    return path


# =============================================================================
# Grouping: the whole problem
# =============================================================================


def test_the_same_fault_with_different_details_groups_as_one(tmp_path):
    """Group on raw text and every fault ranks at one occurrence, and the scan
    reports truthfully and uselessly that nothing ever happens twice."""
    records = [
        _record(message="could not restore checkpoint_000012 after 3 tries"),
        _record(message="could not restore checkpoint_000013 after 7 tries"),
        _record(message="could not restore checkpoint_000014 after 1 tries"),
    ]
    found = logscan.scan(records=records)

    assert len(found) == 1
    assert found[0].count == 3
    assert found[0].template == "could not restore <id> after <n> tries"


def test_two_different_faults_from_one_module_stay_separate(tmp_path):
    """Over-merging is the other failure. Two warnings from one module are
    usually two different problems."""
    records = [_record(message="the tunnel restarted", line=10),
               _record(message="the tunnel restarted", line=10),
               _record(message="the store is unreachable", line=44)]
    found = logscan.scan(records=records)
    assert sorted(item.count for item in found) == [1, 2]


def test_an_error_outranks_a_more_frequent_warning(tmp_path):
    """Severity above frequency: one is a failure, the other is usually the
    shape of a failure. Within a level it is frequency."""
    records = ([_record(level="WARNING", message="slow", line=1)] * 40
               + [_record(level="ERROR", message="broke", line=2)])
    found = logscan.scan(records=records)
    assert found[0].level == "ERROR"
    assert found[1].level == "WARNING" and found[1].count == 40


def test_info_is_not_a_fault(tmp_path):
    records = [_record(level="INFO", message="started")] * 10
    assert logscan.scan(records=records) == []


def test_an_exception_type_is_part_of_the_signature(tmp_path):
    """Two failures at one line raising different exceptions are two faults."""
    records = [_record(level="ERROR", message="failed", exception="ValueError"),
               _record(level="ERROR", message="failed", exception="OSError")]
    assert len(logscan.scan(records=records)) == 2


def test_one_error_is_worth_raising_and_one_warning_is_not(tmp_path):
    """One WARNING is a Tuesday; the same one every hour is a defect. An
    exception that happened at all is a thing that should not have."""
    one_error = logscan.scan(records=[_record(level="ERROR", message="x")])[0]
    one_warning = logscan.scan(records=[_record(level="WARNING", message="x")])[0]
    three_warnings = logscan.scan(records=[_record(message="x")] * 3)[0]

    assert one_error.recurring is True
    assert one_warning.recurring is False
    assert three_warnings.recurring is True


def test_a_finding_reads_the_real_log(tmp_path):
    """Not a hand-built list: the scan over what the handler actually wrote."""
    eventlog.install("gateway")
    for _ in range(3):
        logging.getLogger("gateway.real").warning("the DBA did not answer /health")

    found = logscan.scan(since=datetime.now(timezone.utc) - timedelta(minutes=5))
    assert len(found) == 1
    assert found[0].count == 3
    assert found[0].logger == "gateway.real"


# =============================================================================
# Patterns: signals that are not exceptions
# =============================================================================


def test_the_same_fault_repeated_inside_one_request_is_a_pattern(tmp_path):
    """A retry that is not working. The turn may have finished, which is why
    nothing else would report it."""
    records = [_record(request_id="req-1", message="timed out")] * 4
    found = logscan.patterns(records=records)
    kinds = {row["kind"] for row in found}
    assert "repeated_within_one_request" in kinds
    entry = next(row for row in found
                 if row["kind"] == "repeated_within_one_request")
    assert entry["count"] == 4 and entry["request_id"] == "req-1"


def test_a_fault_in_one_service_only_is_flagged(tmp_path):
    records = [_record(service="gateway", message="a shared path failed"),
               _record(service="dba", message="something else", line=99)]
    kinds = [row for row in logscan.patterns(records=records)
             if row["kind"] == "one_service_only"]
    assert kinds


def test_a_service_that_logged_nothing_is_flagged(tmp_path):
    """A component that has stopped logging cannot be observed at all."""
    records = [_record(service="gateway")]
    silent = [row for row in logscan.patterns(records=records)
              if row["kind"] == "silent_service"]
    assert [row["service"] for row in silent] == ["dba"]


# =============================================================================
# The clean-log standard, and the ratchet
# =============================================================================


def test_nothing_is_accepted_by_default(tmp_path):
    """The shipped baseline is empty on purpose - pre-populating it with guesses
    would accept noise nobody has seen."""
    assert logscan.baseline() == {}


def test_a_missing_baseline_accepts_nothing_rather_than_everything(tmp_path):
    """A guard against noise that went quiet when its configuration disappeared
    would be failing in the wrong direction."""
    assert logscan.baseline(tmp_path / "does-not-exist.yaml") == {}
    findings = logscan.scan(records=[_record(level="ERROR", message="x")])
    assert logscan.unaccepted(findings, path=tmp_path / "nope.yaml") == findings


def test_an_unreadable_baseline_accepts_nothing(tmp_path):
    broken = tmp_path / "broken.yaml"
    broken.write_text("{{{ not yaml", encoding="utf-8")
    assert logscan.baseline(broken) == {}


def test_an_accepted_signature_is_not_raised(tmp_path):
    findings = logscan.scan(records=[_record(message="known and fine")] * 5)
    path = _baseline(tmp_path, [
        {"signature": findings[0].signature, "what": "known and fine",
         "reason": "the tunnel restarts nightly by design",
         "accepted": "2026-09-23 krish"}])

    assert logscan.unaccepted(findings, path=path) == []
    assert "by design" in logscan.accepted_reason(findings[0], path=path)


def test_removing_an_entry_puts_the_noise_back_on_the_list(tmp_path):
    """Deleting an entry is how you say "that is no longer acceptable"."""
    findings = logscan.scan(records=[_record(message="tolerated")] * 5)
    accepted = _baseline(tmp_path, [{"signature": findings[0].signature,
                                     "reason": "for now"}])
    assert logscan.unaccepted(findings, path=accepted) == []

    empty = _baseline(tmp_path, [])
    assert logscan.unaccepted(findings, path=empty) == findings


def test_a_signature_changes_when_the_code_moves(tmp_path):
    """Deliberate: a warning that has moved is one somebody touched, and is
    worth re-reading rather than being carried forward silently."""
    before = logscan.signature(_record(line=10))
    after = logscan.signature(_record(line=11))
    assert before != after


# =============================================================================
# Findings reach the lifecycle, and stop there
# =============================================================================


def test_an_unaccepted_fault_becomes_a_suspected_gap_and_no_more(client, tmp_path):
    """§11's rule applies to a log line more than to anything else, because a
    log line is the cheapest evidence there is to produce."""
    findings = logscan.scan(records=[_record(level="ERROR",
                                             message="the store is unreachable")])
    raised = logscan.raise_suspicions(client, findings,
                                      path=tmp_path / "empty.yaml")

    assert len(raised) == 1
    stored = gaps.all_gaps(client)[0]
    assert stored["status"] == gaps.SUSPECTED
    assert "the store is unreachable" in stored["description"]
    assert "logscan" == stored["detected_by"]
    # and nothing was proposed
    assert client.count("change_proposal", {}) == 0


def test_the_same_fault_next_scan_raises_frequency_not_a_second_gap(client, tmp_path):
    findings = logscan.scan(records=[_record(level="ERROR", message="again")])
    path = tmp_path / "empty.yaml"
    logscan.raise_suspicions(client, findings, path=path)
    logscan.raise_suspicions(client, findings, path=path)

    everything = gaps.all_gaps(client)
    assert len(everything) == 1
    assert everything[0]["frequency"] == 2


def test_an_accepted_fault_raises_nothing(client, tmp_path):
    findings = logscan.scan(records=[_record(level="ERROR", message="fine")])
    path = _baseline(tmp_path, [{"signature": findings[0].signature,
                                 "reason": "expected on a cold start"}])
    assert logscan.raise_suspicions(client, findings, path=path) == []
    assert gaps.all_gaps(client) == []


def test_the_upkeep_sweep_scans_the_log(client):
    """The habit, not just the capability."""
    eventlog.install("gateway")
    for _ in range(4):
        logging.getLogger("gateway.sweep").error("a real failure")

    result = upkeep.run_once(client)

    assert result["log_scan"]["faults"] >= 1
    assert result["log_scan"]["raised"]
    assert gaps.all_gaps(client, status=gaps.SUSPECTED)


def test_a_second_sweep_does_not_rescan_immediately(client):
    eventlog.install("gateway")
    logging.getLogger("gateway.sweep").error("once")
    upkeep.run_once(client)
    assert upkeep.log_scan_due(client) is False
    assert upkeep.run_once(client)["log_scan"] is None


# =============================================================================
# The sandbox a candidate is tested in
# =============================================================================


def test_a_workspace_is_a_separate_directory_on_its_own_branch(workspace):
    space = workspace(["gateway/tools.py"])
    assert space.path.exists()
    assert space.path != introspect.PROJECT_ROOT
    assert (space.path / "gateway" / "tools.py").exists()
    space.discard()
    assert not space.path.exists()


def test_writing_outside_the_approved_scope_is_refused(workspace):
    space = workspace(["gateway/tools.py"])
    space.write("gateway/tools.py", "# fine\n")
    with pytest.raises(candidate.WorkspaceRefused) as raised:
        space.write("gateway/conversation.py", "# not approved\n")
    assert "approved scope" in str(raised.value)


def test_a_governance_file_cannot_be_opened_as_a_scope():
    """§16 again, and checked before any code is generated rather than at the
    first write."""
    for path in ("app/initiative.py", "gateway/selfmod.py", "gateway/candidate.py"):
        with pytest.raises(candidate.WorkspaceRefused):
            candidate.open_workspace(branch="jarvis/test-governance", scope=[path])


def test_an_existing_test_cannot_be_modified():
    """Adding a test cannot weaken another test; editing one can."""
    with pytest.raises(candidate.WorkspaceRefused) as raised:
        candidate.open_workspace(branch="jarvis/test-existing-test",
                                  scope=["tests/test_logscan.py"])
    assert "success criteria" in str(raised.value)


def test_a_new_test_file_may_be_created(workspace):
    """§17 wants a test plan, and a change usually needs one."""
    space = workspace(["gateway/tools.py", "tests/test_a_brand_new_thing.py"])
    space.write("tests/test_a_brand_new_thing.py", "def test_x():\n    assert True\n")
    assert (space.path / "tests" / "test_a_brand_new_thing.py").exists()


def test_a_path_escaping_the_workspace_is_refused(workspace):
    space = workspace(["gateway/tools.py"])
    for bad in ("../outside.py", "/etc/passwd"):
        with pytest.raises(candidate.WorkspaceRefused):
            space.write(bad, "x")


def test_an_empty_scope_is_refused():
    with pytest.raises(candidate.WorkspaceRefused) as raised:
        candidate.open_workspace(branch="jarvis/test-empty-scope", scope=[])
    assert "approved scope" in str(raised.value)


def test_an_oversized_file_is_refused(workspace):
    space = workspace(["gateway/tools.py"])
    with pytest.raises(candidate.WorkspaceRefused):
        space.write("gateway/tools.py", "x" * (candidate.MAX_FILE_BYTES + 1))


def test_the_live_tree_is_untouched_by_anything_written(workspace):
    """The flaw this module fixes: commit_candidate checked out its branch in
    the live tree - the one the running Gateway imports from."""
    live = introspect.PROJECT_ROOT / "gateway" / "tools.py"
    before = live.read_text(encoding="utf-8")
    space = workspace(["gateway/tools.py"])
    space.write("gateway/tools.py", "# replaced entirely\n")
    assert live.read_text(encoding="utf-8") == before
    assert space.read("gateway/tools.py") == "# replaced entirely\n"


def test_a_diff_shows_what_changed(workspace):
    space = workspace(["gateway/tools.py"])
    space.write("gateway/tools.py", "# replaced\n")
    shown = space.diff()
    assert "gateway/tools.py" in shown
    assert "# replaced" in shown


def test_a_commit_stages_only_what_was_written(workspace):
    space = workspace(["gateway/tools.py"])
    space.write("gateway/tools.py", "# replaced\n")
    (space.path / "stray.txt").write_text("not mine", encoding="utf-8")
    commit = space.commit("candidate")
    assert commit
    listed = candidate._git("show", "--name-only", "--format=", commit,
                            cwd=space.path).stdout.split()
    assert listed == ["gateway/tools.py"]


def test_a_commit_with_nothing_written_is_none(workspace):
    space = workspace(["gateway/tools.py"])
    assert space.commit("nothing") is None


def test_tests_that_did_not_run_are_not_reported_as_passing(workspace):
    space = workspace(["gateway/tools.py"])
    outcome = space.test(["tests/test_eventlog.py"], timeout_seconds=0)
    assert outcome["passed"] is False
    assert outcome["ran"] is False


def test_this_sandbox_is_not_the_learning_sandbox():
    """They exist for different jobs and one cannot become the other: the
    learning sandbox lists no interpreter on purpose."""
    from app.learning import sandbox

    assert "python" not in sandbox.COMMANDS
    assert "pytest" not in sandbox.COMMANDS
    assert candidate.describe()["isolation"] == "git worktree"


def test_discarding_a_candidate_leaves_no_branch_behind(workspace):
    """Found by the probe run and not by the tests, which is the argument for
    probing: the first version removed the worktree and kept the branch, so
    every abandoned candidate left one for ever - and the next attempt at the
    same proposal then failed, because `worktree add -b` refuses a name that
    already exists."""
    space = workspace(["gateway/tools.py"], branch="jarvis/test-discard-me")
    assert _branch_exists("jarvis/test-discard-me")
    space.discard()
    assert not _branch_exists("jarvis/test-discard-me")


def test_a_successful_candidate_keeps_its_branch(workspace):
    """The commit is going to be deployed from it; only the working copy has
    done its job."""
    space = workspace(["gateway/tools.py"], branch="jarvis/test-keep-me")
    space.write("gateway/tools.py", "# candidate\n")
    space.commit("candidate")
    space.keep()

    assert not space.path.exists()
    assert _branch_exists("jarvis/test-keep-me")
    candidate._git("branch", "-D", "jarvis/test-keep-me")


def test_the_same_branch_can_be_opened_again_after_a_failed_attempt(workspace):
    """A second attempt at one proposal - after a failed test run, or after a
    restart - arrives with the same branch name. The first version passed `-b`
    unconditionally and git refused, turning "try again" into a permanent
    failure."""
    first = workspace(["gateway/tools.py"], branch="jarvis/test-retry")
    first.write("gateway/tools.py", "# attempt one\n")
    first.commit("attempt one")
    first.keep()

    second = candidate.open_workspace(branch="jarvis/test-retry",
                                      scope=["gateway/tools.py"])
    try:
        assert "attempt one" in second.read("gateway/tools.py")
    finally:
        second.discard()


def _branch_exists(name: str) -> bool:
    return candidate._git("rev-parse", "--verify", "--quiet",
                          f"refs/heads/{name}").returncode == 0
