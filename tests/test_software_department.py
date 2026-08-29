"""The Software Department's issue record and its gates (TQ-106;
addendum 53 §1, §2, §5.2, §5.3, §6, §12; docs/SPEC_RECONCILIATION.md §150, §151).

Addendum 53 §1: the department *"is not merely a repair service. Its
responsibility is to make the system progressively harder to break in the same way
twice."*

A department that recorded issues and closed them would be a ticket queue. What
makes it §1's thing is **what it refuses to let you close**, so almost every test
here is a refusal — and each refusal corresponds to a defect this project has
actually shipped.

The one to read first is
`test_a_root_cause_needs_three_perspectives_from_three_identities`: §149 §4 found
three defects that survived because the implementation and the tests came from one
belief, and the third perspective — *why did the tests not catch it* — is the one
nobody was asking.
"""

from __future__ import annotations

import pytest

from agents import dba
from backend import compliance, fi_db, parliament, software_department as dept

RUNS_MISSING = __import__("pathlib").Path("no-such-runs-directory")

DBA = "dba-1"
ENGINEER = "software_engineer-1"
QA = "qa_engineer-1"


def _issue(conn, *, severity=dept.SEVERITY_HIGH, signature="vocabulary:x.py:1") -> int:
    return dept.open_issue(
        conn, observed="A query filters on a value the column never holds.",
        evidence="backend/x.py:1 status = 'open'", component="backend/x.py",
        expected="one of pending, resolved, consumed", signature=signature,
        classification="database_schema", severity=severity, opened_by=DBA)


def _reviewed(conn, issue):
    for perspective, reviewer in ((dept.PERSPECTIVE_DATA, DBA),
                                  (dept.PERSPECTIVE_IMPLEMENTATION, ENGINEER),
                                  (dept.PERSPECTIVE_VERIFICATION, QA)):
        dept.review(conn, issue, perspective=perspective, reviewer=reviewer,
                    finding=f"{perspective} finding")
    dept.record_root_cause(conn, issue, root_cause="A literal with no canonical constant.")


def _corrected(conn, issue, by=ENGINEER):
    dept.record_correction(
        conn, issue, correction="Use the constant.",
        prevention="Vocabulary contract audit.", corrected_by=by)


# --- intake (§6 step 1) -------------------------------------------------------------------

def test_an_intake_needs_all_four_facts(conn):
    """*"It is broken"* is not an intake. Without the expected behaviour there is
    nothing to compare against; without the evidence nobody can re-examine the
    judgement later."""
    for missing in ("observed", "evidence", "component", "expected"):
        kwargs = dict(observed="o", evidence="e", component="c", expected="x",
                      signature="s", classification="database_schema",
                      severity=dept.SEVERITY_NORMAL, opened_by=DBA)
        kwargs[missing] = "   "
        with pytest.raises(dept.IssueRefused):
            dept.open_issue(conn, **kwargs)


def test_an_unknown_classification_or_severity_is_refused(conn):
    for field, bad in (("classification", "vibes"), ("severity", "catastrophic")):
        kwargs = dict(observed="o", evidence="e", component="c", expected="x",
                      signature="s", classification="database_schema",
                      severity=dept.SEVERITY_NORMAL, opened_by=DBA)
        kwargs[field] = bad
        with pytest.raises(dept.IssueRefused) as refusal:
            dept.open_issue(conn, **kwargs)
        assert "known are" in str(refusal.value)


def test_the_same_finding_twice_is_one_issue(conn):
    """A scheduled check runs every cycle and would otherwise file the same defect
    forever. It **returns** rather than raising, because a caller that had to
    catch an exception to make progress would eventually have that exception
    widened — and then a real refusal would be swallowed too."""
    first = _issue(conn)
    assert _issue(conn) == first
    assert len(dept.open_issues(conn)) == 1


def test_a_closed_issue_does_not_block_the_same_finding_recurring(conn):
    """The uniqueness is over *open* issues. A defect that comes back is a new
    issue, and one that could never be reopened would hide a regression."""
    first = _issue(conn)
    _reviewed(conn, first)
    _corrected(conn, first)
    dept.close(conn, first, proof_test="tests/test_x.py::test_y", verified_by=QA,
               lesson="Use constants.")
    assert _issue(conn) != first


# --- the gate that matters (§6 step 3, §2) ------------------------------------------------

def test_a_root_cause_needs_three_perspectives_from_three_identities(conn):
    """**The gate this department exists for.**

    §2 forbids the triad working as silos, and the three questions are different
    in kind. §149 §4 found three defects where the answer to the third — *why did
    the tests not catch it* — was *because they were built from the same
    misreading*, and nobody was asking it."""
    issue = _issue(conn)

    with pytest.raises(dept.IssueRefused) as refusal:
        dept.record_root_cause(conn, issue, root_cause="because")
    assert "three perspectives" in str(refusal.value)

    # All three, but from one agent: one belief wearing three hats.
    for perspective in dept.PERSPECTIVES:
        dept.review(conn, issue, perspective=perspective, reviewer=DBA, finding="f")
    with pytest.raises(dept.IssueRefused) as refusal:
        dept.record_root_cause(conn, issue, root_cause="because")
    assert "one belief wearing three hats" in str(refusal.value)

    dept.review(conn, issue, perspective=dept.PERSPECTIVE_IMPLEMENTATION,
                reviewer=ENGINEER, finding="f")
    dept.review(conn, issue, perspective=dept.PERSPECTIVE_VERIFICATION,
                reviewer=QA, finding="f")
    dept.record_root_cause(conn, issue, root_cause="A literal with no constant.")
    assert dept.require(conn, issue)["status"] == dept.STATUS_REVIEWED


def test_a_reviewer_cannot_file_the_same_perspective_twice_to_look_like_two(conn):
    issue = _issue(conn)
    dept.review(conn, issue, perspective=dept.PERSPECTIVE_DATA, reviewer=DBA, finding="one")
    dept.review(conn, issue, perspective=dept.PERSPECTIVE_DATA, reviewer=DBA, finding="two")
    assert len(dept.reviews(conn, issue)) == 1


def test_an_empty_review_is_a_reviewer_assigned_rather_than_one_that_looked(conn):
    issue = _issue(conn)
    with pytest.raises(dept.IssueRefused) as refusal:
        dept.review(conn, issue, perspective=dept.PERSPECTIVE_DATA, reviewer=DBA, finding="  ")
    assert "having looked" in str(refusal.value)


# --- correction and prevention are one step (§6 steps 5-6, §1) ----------------------------

def test_a_correction_needs_a_prevention(conn):
    """*"A fix without a safeguard leaves the same defect available tomorrow."*
    §1's *harder to break in the same way twice*, made mechanical — and one call
    rather than two, because separating them makes the second optional in
    practice."""
    issue = _issue(conn)
    _reviewed(conn, issue)
    with pytest.raises(dept.IssueRefused) as refusal:
        dept.record_correction(conn, issue, correction="Use the constant.",
                               prevention="   ", corrected_by=ENGINEER)
    assert "available tomorrow" in str(refusal.value)


def test_a_correction_before_a_root_cause_is_refused(conn):
    """§6 step 4 comes before step 5, because a correction written first fixes
    where the defect appeared rather than why it was possible."""
    issue = _issue(conn)
    with pytest.raises(dept.IssueRefused) as refusal:
        _corrected(conn, issue)
    assert "no root cause yet" in str(refusal.value)


# --- closing (§6 step 7, §5.2, §5.3) -------------------------------------------------------

def test_closing_needs_the_name_of_a_test_observed_failing(conn):
    """§5.3's third question: *has the tripwire actually been observed failing
    under that condition?* A boolean cannot answer it; the name of a thing
    somebody else can run does."""
    issue = _issue(conn)
    _reviewed(conn, issue)
    _corrected(conn, issue)
    with pytest.raises(dept.IssueRefused) as refusal:
        dept.close(conn, issue, proof_test="  ", verified_by=QA, lesson="l")
    assert "observed failing" in str(refusal.value)


def test_the_verifier_is_not_the_corrector(conn):
    """**§5.2, and the fifth instance of a rule this system already applies four
    times.** One agent doing both derives the fix and the expected values from a
    single assumption, which is exactly how three defects passed every test."""
    issue = _issue(conn)
    _reviewed(conn, issue)
    _corrected(conn, issue, by=ENGINEER)

    with pytest.raises(dept.IssueRefused) as refusal:
        dept.close(conn, issue, proof_test="tests/test_x.py::test_y",
                   verified_by=ENGINEER, lesson="l")
    assert "§5.2" in str(refusal.value)

    dept.close(conn, issue, proof_test="tests/test_x.py::test_y", verified_by=QA,
               lesson="Never hand-write a domain literal.")
    closed = dept.require(conn, issue)
    assert closed["status"] == dept.STATUS_CLOSED
    assert closed["verified_by"] == QA and closed["proof_test"] == "tests/test_x.py::test_y"


def test_an_uncorrected_issue_cannot_be_closed(conn):
    issue = _issue(conn)
    _reviewed(conn, issue)
    with pytest.raises(dept.IssueRefused) as refusal:
        dept.close(conn, issue, proof_test="t", verified_by=QA, lesson="l")
    assert "no correction to verify" in str(refusal.value)


# --- severity (§12) -------------------------------------------------------------------------

def test_a_critical_issue_escalates_through_the_queue_that_already_exists(conn):
    """§12 escalates a severity-1 issue to a CEO. **There is no CEO** (§150 §2),
    and a second escalation queue would be two places where a matter waits for a
    person. `parliament.escalate`'s contract is already exactly right: nothing in
    the system can answer it, and there is no resolve, dismiss or expiry."""
    before = len(parliament.outstanding_escalations(conn))
    issue = _issue(conn, severity=dept.SEVERITY_CRITICAL, signature="corruption:1")

    after = parliament.outstanding_escalations(conn)
    assert len(after) == before + 1
    assert f"Severity-1 software issue {issue}" in after[-1]["summary"]
    assert dept.require(conn, issue)["escalation_id"] == after[-1]["id"]


def test_an_ordinary_issue_does_not_escalate(conn):
    """Otherwise the owner's queue fills with technical debt and the one thing
    that needed a person is buried in it."""
    before = len(parliament.outstanding_escalations(conn))
    _issue(conn, severity=dept.SEVERITY_NORMAL)
    assert len(parliament.outstanding_escalations(conn)) == before


# --- the summary says what is waiting, and what the department does not do -----------------

def test_the_summary_names_which_step_each_issue_is_waiting_on(conn):
    """Two numbers where one would hide the difference (§130): an organization
    with no issues and one whose issues are all stuck at step 3 both look quiet
    from a single count."""
    issue = _issue(conn)
    # Which perspective is missing, not merely "review". An issue waiting on the
    # implementation view and one waiting on all three are different situations.
    assert dept.summary(conn)["open"][0]["waiting_on"] == (
        "review: database, implementation, verification")

    dept.review(conn, issue, perspective=dept.PERSPECTIVE_DATA, reviewer=DBA, finding="f")
    assert dept.summary(conn)["open"][0]["waiting_on"] == (
        "review: implementation, verification")

    _reviewed(conn, issue)
    assert dept.summary(conn)["open"][0]["waiting_on"] == "correction and prevention"

    _corrected(conn, issue)
    assert dept.summary(conn)["open"][0]["waiting_on"] == "adversarial verification"


def test_the_summary_says_what_the_department_does_not_do(conn):
    summary = dept.summary(conn)
    assert any("librarian" in line for line in summary["not_done"])
    assert any("release" in line for line in summary["not_done"])


def test_a_lesson_survives_closing(conn):
    """§6 step 10. Kept here rather than written into `knowledge_records`, whose
    declared gap 2 is that nothing reads it back."""
    issue = _issue(conn)
    _reviewed(conn, issue)
    _corrected(conn, issue)
    dept.close(conn, issue, proof_test="tests/test_x.py::test_y", verified_by=QA,
               lesson="Never hand-write a domain literal when a constant exists.")
    assert [row["lesson"] for row in dept.lessons(conn)] == [
        "Never hand-write a domain literal when a constant exists."]


# --- the DBA loop: a failing check becomes an issue ------------------------------------------

def test_a_failing_check_opens_an_issue_rather_than_reporting_into_nothing(conn):
    """**The loop that makes the health checks real.** Before this, nothing ran
    them on a schedule and nothing read the answer — which is why
    `compliance.self_evaluated` flagged every grade for months unread (§147)."""
    fi_db.register_agent(conn, "explorer-1", "explorer", pid=1)
    report = fi_db.enqueue_report(conn, "explorer-1", "t0", "lead", "SYN1",
                                  summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(conn, "analysis-1", "t0", report, "SYN1",
                                          "thesis", "e", 0.5, "u")
    # A report graded by the agent that filed it: the real condition the duty names.
    fi_db.record_grade(conn, "explorer-1", "t0", report, result, .2, .2, .2, False, .2, "thin")
    assert compliance.self_evaluated(conn), "the fixture did not create the bad state"

    dba._dba_work(conn, DBA)

    issues = dept.open_issues(conn)
    assert len(issues) == 1
    assert issues[0]["classification"] == "software_logic"
    assert issues[0]["severity"] == dept.SEVERITY_HIGH
    assert "graded by" in issues[0]["observed"]


def test_a_healthy_database_opens_nothing(conn):
    """The other half. A DBA that always found something would be a check nobody
    could act on, which is the failure opposite to a check nobody reads."""
    fi_db.register_agent(conn, "explorer-1", "explorer", pid=1)
    dba._dba_work(conn, DBA)
    assert dept.open_issues(conn) == []


def test_the_dba_files_one_issue_however_many_cycles_it_runs(conn):
    """It runs every cycle. Without a stable signature the queue would fill with
    one defect."""
    fi_db.register_agent(conn, "explorer-1", "explorer", pid=1)
    report = fi_db.enqueue_report(conn, "explorer-1", "t0", "lead", "SYN1",
                                  summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(conn, "analysis-1", "t0", report, "SYN1",
                                          "thesis", "e", 0.5, "u")
    fi_db.record_grade(conn, "explorer-1", "t0", report, result, .2, .2, .2, False, .2, "thin")

    for _ in range(5):
        dba._dba_work(conn, DBA)
    assert len(dept.open_issues(conn)) == 1


def test_the_dba_cannot_close_what_it_opened(conn):
    """A DBA that opened and closed its own issues would be the silo §2 forbids,
    and it is refused by the same gate that refuses everything else — not by a
    check written specially for it."""
    issue = _issue(conn)
    for perspective in dept.PERSPECTIVES:
        dept.review(conn, issue, perspective=perspective, reviewer=DBA, finding="f")
    with pytest.raises(dept.IssueRefused):
        dept.record_root_cause(conn, issue, root_cause="mine")


# --- QA: which safeguards have ever been seen to fail (§5.3 question 3) --------------------

def test_the_history_answers_whether_a_property_has_been_seen_to_fail(tmp_path):
    """**§5.3 question 3, answered from evidence rather than by survey.** Every
    scenario run has been writing `property_results` all along; nothing read them
    for this until now."""
    from simulation import property_history
    import json

    for i, (passed, observed) in enumerate([(True, 0), (True, 0), (False, 3)]):
        run = tmp_path / f"run-{i}"
        run.mkdir()
        (run / "summary.json").write_text(json.dumps({
            "scenario_id": "s",
            "property_results": [
                {"name": "never fails", "metric": "a.b", "expected": 0,
                 "observed": 0, "passed": True},
                {"name": "has failed", "metric": "c.d", "expected": 0,
                 "observed": observed, "passed": passed},
            ]}), encoding="utf-8")

    history = property_history.observed_failures(tmp_path)
    assert history["runs_read"] == 3
    assert [r["property"] for r in history["proven"]] == ["has failed"]
    assert [r["property"] for r in history["unproven"]] == ["never fails"]
    assert history["unproven"][0]["passes"] == 3


def test_the_worklist_would_have_flagged_the_defect_that_shipped():
    """**The observation §5.3 question 3 asks for, over the real history.**

    `no cross-check was left open` passed in every recorded run because its query
    filtered on a status that does not exist (§149 §3). It is on the worklist,
    with the count of runs that passed it — which is what makes *"not accepted
    merely because it has historically passed"* checkable."""
    from simulation import property_history

    work = property_history.worklist()
    if not work["runs_read"]:
        pytest.skip("no recorded runs on this machine to read")

    flagged = [r for r in work["never_varied"] if "left open" in (r["property"] or "")]
    assert flagged, "the property whose query could never match is not on the worklist"
    assert flagged[0]["passes"] > 1
    assert flagged[0]["observed_values"] == ["0"]


def test_the_worklist_says_unproven_is_not_a_defect():
    """A reader taking `unproven` for a findings list would re-derive the mistake
    §150 §6 records — 37 findings, none of them real, and a tripwire that fires on
    everything is turned off within a week."""
    from simulation import property_history

    work = property_history.worklist(RUNS_MISSING)
    assert "not a defect" in work["caveat"]
    assert "forced-failure proof" in work["caveat"]


def test_a_missing_run_directory_reads_as_no_evidence_rather_than_as_health():
    """Absence is `unknown`, never a plausible default (§100, §104, §118). Zero
    runs read must not look like zero unproven properties."""
    from simulation import property_history

    history = property_history.observed_failures(RUNS_MISSING)
    assert history == {"proven": [], "unproven": [], "runs_read": 0}


def test_qa_surfaces_what_awaits_verification_and_does_not_verify_it(conn, capsys):
    """§6 step 7 requires somebody to construct the bad state and observe the
    failure. An agent that marked a safeguard proven because a scan completed
    would be manufacturing the evidence the scan looks for."""
    from agents import qa_engineer

    issue = _issue(conn)
    _reviewed(conn, issue)
    _corrected(conn, issue)

    qa_engineer._qa_work(conn, QA)

    assert "awaits adversarial verification" in capsys.readouterr().out
    assert dept.require(conn, issue)["status"] == dept.STATUS_CORRECTED, (
        "QA closed an issue it only looked at")


# --- staffing the loop (TQ-107; addendum 53 §11, addendum 46 §10) --------------------------

def test_an_issue_names_the_roles_it_is_waiting_on(conn):
    """The same signal `appeal.roles_awaiting_a_peer` gives one department along.
    An issue nobody can review is an appeal nobody can hear: the machinery is
    right and the workforce is one agent short."""
    assert dept.roles_needed(conn) == []
    issue = _issue(conn)
    # In §2's perspective order - database, implementation, verification - not
    # alphabetical, because the order a reader wants is the order they are asked
    # for rather than the order they are spelled.
    assert dept.roles_needed(conn) == ["dba", "software_engineer", "qa_engineer"]

    dept.review(conn, issue, perspective=dept.PERSPECTIVE_DATA, reviewer=DBA, finding="f")
    assert dept.roles_needed(conn) == ["software_engineer", "qa_engineer"]


def test_many_issues_ask_for_one_of_each_role(conn):
    """One reviewer files one perspective on every open issue. A role per issue
    would ask for five agents to do one agent's work (46 §9)."""
    for n in range(4):
        _issue(conn, signature=f"vocabulary:x.py:{n}")
    assert dept.roles_needed(conn) == ["dba", "software_engineer", "qa_engineer"]


def test_an_issue_awaiting_verification_asks_for_qa_not_the_engineer(conn):
    """The verifier may not be the corrector, so step 7 is QA's whether or not an
    engineer is already staffed."""
    issue = _issue(conn)
    _reviewed(conn, issue)
    _corrected(conn, issue)
    assert dept.roles_needed(conn) == ["qa_engineer"]


def test_the_coo_staffs_the_reviewer_the_three_way_review_needs(conn):
    """Read from what the COO actually enqueues. On-demand roles have a baseline
    target of zero, so this is what brings them into existence at all."""
    from agents import coo

    _issue(conn)
    coo._ensure_baseline_population(conn)

    reasons = {row["target_role"]: (row["reason"] or "") for row in conn.fetchall(
        "SELECT target_role, reason FROM coo_directives")}
    assert "qa_engineer" in reasons, f"QA was not staffed; directives: {list(reasons)}"
    assert "waiting on its perspective" in reasons["qa_engineer"]


def test_the_coo_staffs_nobody_extra_when_the_department_is_quiet(conn):
    """Otherwise on-demand becomes a standing population that happens to idle,
    which is what 46 §10 is written against."""
    from agents import coo

    coo._ensure_baseline_population(conn)
    staffed = {row["target_role"] for row in conn.fetchall(
        "SELECT target_role FROM coo_directives")}
    assert "qa_engineer" not in staffed and "software_engineer" not in staffed


# --- the two perspectives that are facts, and the one that is not -------------------------

def test_the_dba_files_the_database_perspective_on_its_own_findings(conn):
    """Transcription, not judgement: the check already established the database
    fact, and the perspective is that fact stated for the other two reviewers."""
    fi_db.register_agent(conn, "explorer-1", "explorer", pid=1)
    report = fi_db.enqueue_report(conn, "explorer-1", "t0", "lead", "SYN1",
                                  summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(conn, "analysis-1", "t0", report, "SYN1",
                                          "thesis", "e", 0.5, "u")
    fi_db.record_grade(conn, "explorer-1", "t0", report, result, .2, .2, .2, False, .2, "thin")

    dba._dba_work(conn, DBA)
    issue = dept.open_issues(conn)[0]

    filed = {row["perspective"]: row for row in dept.reviews(conn, issue["id"])}
    assert set(filed) == {dept.PERSPECTIVE_DATA}
    assert filed[dept.PERSPECTIVE_DATA]["reviewer"] == DBA
    assert "graded by" in filed[dept.PERSPECTIVE_DATA]["finding"]


def test_the_dba_does_not_review_somebody_elses_finding(conn):
    """A database opinion about work this agent has not examined is the same error
    one column along."""
    _issue(conn)  # opened by DBA in the fixture
    conn.execute("UPDATE software_issues SET opened_by = 'somebody-else'")
    dba._review_own_findings(conn, DBA)
    assert dept.reviews(conn, 1) == []


def test_qa_files_the_verification_perspective_and_never_the_implementation(conn):
    """**The wall.** QA answers *why did the tests not catch it* from what the
    backend can establish. It does not supply the implementation view and does not
    correct — an agent that did both would derive the fix and the expected values
    from one assumption (§5.2)."""
    from agents import qa_engineer

    issue = _issue(conn)
    qa_engineer._qa_work(conn, QA)

    filed = {row["perspective"] for row in dept.reviews(conn, issue)}
    assert filed == {dept.PERSPECTIVE_VERIFICATION}
    assert dept.PERSPECTIVE_IMPLEMENTATION in dept.missing_perspectives(conn, issue)


def test_the_loop_stops_at_the_implementation_perspective(conn):
    """**The honest wall, and the point of this increment.** An issue now reaches
    two of three perspectives by itself instead of sitting at step 1 forever — and
    stops, because the third needs an agent that can read code and this system has
    none (TQ-83: the engineer writes no code).

    A fabricated implementation perspective would satisfy the gate that exists to
    make somebody look."""
    from agents import qa_engineer

    fi_db.register_agent(conn, "explorer-1", "explorer", pid=1)
    report = fi_db.enqueue_report(conn, "explorer-1", "t0", "lead", "SYN1",
                                  summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(conn, "analysis-1", "t0", report, "SYN1",
                                          "thesis", "e", 0.5, "u")
    fi_db.record_grade(conn, "explorer-1", "t0", report, result, .2, .2, .2, False, .2, "thin")

    for _ in range(3):
        dba._dba_work(conn, DBA)
        qa_engineer._qa_work(conn, QA)

    issue = dept.open_issues(conn)[0]
    assert dept.missing_perspectives(conn, issue["id"]) == [dept.PERSPECTIVE_IMPLEMENTATION]
    assert issue["root_cause"] is None, "an issue advanced without all three perspectives"
    assert dept.summary(conn)["open"][0]["waiting_on"] == "review: implementation"


def test_qa_says_the_question_is_open_rather_than_inventing_a_reason(conn):
    """A fabricated verification perspective is worse than a missing one: it
    satisfies the gate that exists to make somebody look."""
    from agents import qa_engineer

    issue = dept.open_issue(
        conn, observed="o", evidence="nothing recognisable", component="app/unknown.py",
        expected="x", signature="odd:1", classification="observability",
        severity=dept.SEVERITY_NORMAL, opened_by=DBA)
    qa_engineer._qa_work(conn, QA)

    finding = dept.reviews(conn, issue)[0]["finding"]
    assert "open and needs somebody to look" in finding
    assert "does not guess" in finding
