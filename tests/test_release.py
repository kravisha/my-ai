"""Releases and rollback over governed data (TQ-96; addendum 46 §16, §18;
addendum 30 §26, §27; docs/SPEC_RECONCILIATION.md §139).

§139 settled what a release is here, and every test below is aimed at one of the
three things it says adoption cannot do: a **boundary** around a change, a **way
back that needs no vote**, and a **health verdict**.

Two habits from this project's own defects shape how they are written.

**A test over data does not test the rule that produced the data** (§117, §123,
§129). So the rollback tests do not assert that a row moved - they run the real
governed code path (`register.file_entry`, which refuses submissions an
instrument forbids) before and after, and assert the *behaviour* came back.

**A function tested in isolation is not a function that runs** (§134). So the
department's staging and the Speaker's reporting are exercised through
`engineering` and `speaker.compose_report`, not by calling `release` directly and
trusting the callers exist.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from agents import speaker
from backend import (engineering, fi_db, governed_knowledge as governed,
                     parliament, portfolios, register, release)

OWNER = portfolios.for_superuser("krish")
ROLL = {"broad": ["coo", "analysis"], "representative": ["coo", "analysis"]}

# The instrument the rollback tests move in and out of force. `source_reference`
# is a real field on a register submission, so an instrument requiring it refuses
# a submission without one - which is a behaviour, observable through the
# production path, rather than a row somebody can read.
REQUIRE_SOURCE = {"kind": "required_fields", "fields": ["source_reference"]}


@pytest.fixture
def governed_conn(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    return conn


def _enact(conn, *, affects="organization_policy", title="A resolution") -> int:
    resolution = parliament.propose(conn, title=title, rationale="r",
                                    proposed_by="coo", affects=affects)
    for voter in ROLL["representative"]:
        parliament.cast_vote(conn, resolution, voter=voter, value="for")
    parliament.close(conn, resolution)
    return resolution


def _instrument(*, text, requires=None, level="organization_policy",
                subject=register.SUBMISSION_SUBJECT, replaces=None):
    item = {"subject": subject, "level": level, "text": text, "binds": "explorer"}
    if requires is not None:
        item["requires"] = requires
    if replaces is not None:
        item["replaces"] = replaces
    return item


def _files_ok(conn, title="An entry") -> bool:
    """Whether the governed production path accepts a submission with no
    `source_reference`. This is the behaviour a release changes and a rollback
    restores; asserting it is what makes these tests about the rule rather than
    about a row."""
    try:
        register.file_entry(conn, title=title, category="want", origin="explorer",
                            rationale="r", filed_by="explorer")
        return True
    except ValueError as refusal:
        if "instrument in force" not in str(refusal):
            raise
        return False


# --- the boundary: a set stands or falls together --------------------------------------

def test_a_release_with_nothing_staged_is_refused(governed_conn):
    """Recording a release that changed nothing would put an entry in the
    history that no rollback could mean anything about."""
    rel = release.prepare(governed_conn, name="empty", intent="nothing",
                          resolution_id=_enact(governed_conn), prepared_by="coo")
    with pytest.raises(release.ReleaseRefused) as refusal:
        release.apply(governed_conn, rel, applied_by="analysis")
    assert "changes nothing" in str(refusal.value)


def test_a_release_needs_the_resolution_that_authorises_the_way_back(governed_conn):
    """Addendum 30 §27: rollback is defined before rollout. A release with no
    enacted resolution has nothing to be reversed under, so the way back would
    need a vote at the moment it cannot get one."""
    with pytest.raises(release.ReleaseRefused) as refusal:
        release.prepare(governed_conn, name="r", intent="i", resolution_id=999,
                        prepared_by="coo")
    assert "enacted resolution" in str(refusal.value)


def test_an_open_resolution_authorises_no_release(governed_conn):
    pending = parliament.propose(governed_conn, title="x", rationale="r",
                                 proposed_by="coo", affects="organization_policy")
    with pytest.raises(release.ReleaseRefused):
        release.prepare(governed_conn, name="r", intent="i", resolution_id=pending,
                        prepared_by="coo")


def test_one_refused_instrument_means_none_is_adopted(governed_conn):
    """**The state nobody designed**, refused. Two instruments staged, the second
    unadoptable; without atomicity the first would be in force under a vote that
    authorised the pair, and no reader could tell that from a set somebody
    intended.

    Asserted through the behaviour, not the row count: after the failed apply the
    production path must still accept what it accepted before."""
    resolution = _enact(governed_conn)
    rel = release.prepare(governed_conn, name="pair", intent="two rules",
                          resolution_id=resolution, prepared_by="coo")
    release.stage(governed_conn, rel, staged_by="coo",
                  instrument=_instrument(text="Submissions name a source.",
                                         requires=REQUIRE_SOURCE))
    # A second instrument on the same subject at the same level, naming nothing
    # it replaces: `adopt` refuses two equal authorities on one subject.
    release.stage(governed_conn, rel, staged_by="coo",
                  instrument=_instrument(text="Submissions do something else."))

    assert _files_ok(governed_conn) is True
    with pytest.raises(governed.AdoptionRefused):
        release.apply(governed_conn, rel, applied_by="analysis")

    assert _files_ok(governed_conn, title="After the failed apply") is True, (
        "the first instrument of a refused release reached force")
    assert governed.effective_item(governed_conn, register.SUBMISSION_SUBJECT) is None
    assert release.require(governed_conn, rel)["status"] == release.STATUS_PREPARING


def test_a_staged_change_may_not_carry_its_own_authority(governed_conn):
    """A change with its own resolution is one that could survive the set being
    reversed, which is the boundary dissolving quietly."""
    rel = release.prepare(governed_conn, name="r", intent="i",
                          resolution_id=_enact(governed_conn), prepared_by="coo")
    with pytest.raises(release.ReleaseRefused) as refusal:
        release.stage(governed_conn, rel, staged_by="coo",
                      instrument={**_instrument(text="t"), "resolution_id": 1})
    assert "authorises the whole set" in str(refusal.value)


def test_an_applied_release_is_a_record_and_not_a_candidate(governed_conn):
    rel = release.prepare(governed_conn, name="r", intent="i",
                          resolution_id=_enact(governed_conn), prepared_by="coo")
    release.stage(governed_conn, rel, staged_by="coo", instrument=_instrument(text="t"))
    release.apply(governed_conn, rel, applied_by="analysis")
    with pytest.raises(release.ReleaseRefused):
        release.stage(governed_conn, rel, staged_by="coo", instrument=_instrument(text="u"))
    with pytest.raises(release.ReleaseRefused):
        release.apply(governed_conn, rel, applied_by="analysis")


# --- health: unknown is not passing -----------------------------------------------------

def test_a_released_change_is_unknown_and_never_healthy(governed_conn):
    """§118, unmodified: absence of complaint is not evidence that a release is
    working. A release that came back healthy because nobody objected would be
    the analyst that stopped asking, in a release manager's coat."""
    rel = release.prepare(governed_conn, name="r", intent="i",
                          resolution_id=_enact(governed_conn), prepared_by="coo")
    release.stage(governed_conn, rel, staged_by="coo", instrument=_instrument(text="t"))
    release.apply(governed_conn, rel, applied_by="analysis")
    assert release.require(governed_conn, rel)["health"] == release.HEALTH_UNKNOWN
    assert release.summary(governed_conn)["unjudged_in_force"] == ["r"]


def test_unknown_is_not_a_verdict_anybody_can_record(governed_conn):
    """It is what a release is before anybody looked. A caller able to *set* it
    could clear an unhealthy verdict by declaring ignorance."""
    rel = _released(governed_conn)
    with pytest.raises(release.ReleaseRefused) as refusal:
        release.judge(governed_conn, rel, health=release.HEALTH_UNKNOWN,
                      judged_by="analysis", evidence="e")
    assert "before anybody looked" in str(refusal.value)


def test_the_preparer_cannot_judge_their_own_release(governed_conn):
    """Addendum 46 §11, and §117's reason for keeping ground truth off the
    provider interface: a party able to grade its own work passes by grading."""
    rel = _released(governed_conn, prepared_by="coo")
    with pytest.raises(release.ReleaseRefused) as refusal:
        release.judge(governed_conn, rel, health=release.HEALTH_HEALTHY,
                      judged_by="coo", evidence="looks fine")
    assert "§11" in str(refusal.value)


def test_a_health_verdict_needs_its_evidence(governed_conn):
    rel = _released(governed_conn)
    with pytest.raises(release.ReleaseRefused) as refusal:
        release.judge(governed_conn, rel, health=release.HEALTH_HEALTHY,
                      judged_by="analysis", evidence="  ")
    assert "nobody complained" in str(refusal.value)


def test_nothing_in_force_is_nothing_to_judge(governed_conn):
    rel = release.prepare(governed_conn, name="r", intent="i",
                          resolution_id=_enact(governed_conn), prepared_by="coo")
    with pytest.raises(release.ReleaseRefused):
        release.judge(governed_conn, rel, health=release.HEALTH_HEALTHY,
                      judged_by="analysis", evidence="e")


# --- the way back ------------------------------------------------------------------------

def _released(conn, *, prepared_by="coo", requires=None, text="Submissions name a source."):
    rel = release.prepare(conn, name="r", intent="i", resolution_id=_enact(conn),
                          prepared_by=prepared_by)
    release.stage(conn, rel, staged_by=prepared_by,
                  instrument=_instrument(text=text, requires=requires))
    release.apply(conn, rel, applied_by="analysis")
    return rel


def test_a_rollback_restores_the_behaviour_and_not_merely_the_row(governed_conn):
    """The whole claim, run through the production path.

    Before: submissions without a source are accepted. Released: refused. Rolled
    back: accepted again - by `register.file_entry`, which is the code an agent
    actually calls, rather than by a row somebody read."""
    assert _files_ok(governed_conn, title="Before") is True

    rel = _released(governed_conn, requires=REQUIRE_SOURCE)
    assert _files_ok(governed_conn, title="During") is False, (
        "the release did not change behaviour, so the rollback proves nothing")

    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="Every explorer submission is refused.")
    release.roll_back(governed_conn, rel, rolled_back_by="analysis",
                      reason="Nothing can satisfy it.")

    assert _files_ok(governed_conn, title="After") is True, (
        "the rollback restored the row and not the behaviour")


def test_a_rollback_restores_what_the_release_displaced(governed_conn):
    """Not a withdrawal: an earlier instrument was in force, and the rollback has
    to put *that* back rather than leave the subject ungoverned."""
    resolution = _enact(governed_conn)
    first = governed.adopt(governed_conn, resolution_id=resolution, adopted_by="coo",
                           **_instrument(text="Version N."))

    rel = release.prepare(governed_conn, name="n+1", intent="replace N",
                          resolution_id=resolution, prepared_by="coo")
    release.stage(governed_conn, rel, staged_by="coo",
                  instrument=_instrument(text="Version N+1.", replaces=first))
    release.apply(governed_conn, rel, applied_by="analysis")
    assert governed.effective(governed_conn, register.SUBMISSION_SUBJECT) == "Version N+1."

    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="worse")
    result = release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="worse")

    assert governed.effective(governed_conn, register.SUBMISSION_SUBJECT) == "Version N."
    assert result["restored"] == [first]
    assert result["withdrawn"] == []


def test_a_rollback_of_a_change_that_displaced_nothing_withdraws_it(governed_conn):
    """A real state, and distinct from having put something back. Reported under
    its own name so a caller cannot read one as the other."""
    rel = _released(governed_conn)
    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")
    result = release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")
    assert result["restored"] == []
    assert len(result["withdrawn"]) == 1
    assert governed.effective_item(governed_conn, register.SUBMISSION_SUBJECT) is None


def test_a_rollback_spends_no_new_authority(governed_conn):
    """The point of the module. Addendum 30 §27's guarantee is that the way back
    was granted by the vote that granted the way forward - so a rollback must add
    no resolution, cast no vote, and enact nothing."""
    rel = _released(governed_conn, requires=REQUIRE_SOURCE)
    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")

    before = governed_conn.fetchall("SELECT * FROM resolutions")
    votes_before = governed_conn.fetchall("SELECT * FROM resolution_votes")
    release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")

    assert governed_conn.fetchall("SELECT * FROM resolutions") == before, (
        "the rollback carried a resolution, which is a second change and not a way back")
    assert governed_conn.fetchall("SELECT * FROM resolution_votes") == votes_before


def test_a_rollback_needs_the_release_marked_unhealthy_first(governed_conn):
    """Addendum 46 §18's own step order, made mechanical. A rollback with no
    verdict behind it preserves no failure evidence, which §18 step 6 requires."""
    rel = _released(governed_conn)
    with pytest.raises(release.ReleaseRefused) as refusal:
        release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")
    assert "unhealthy" in str(refusal.value)


def test_a_healthy_release_cannot_be_rolled_back_without_a_new_verdict(governed_conn):
    rel = _released(governed_conn)
    release.judge(governed_conn, rel, health=release.HEALTH_HEALTHY,
                  judged_by="analysis", evidence="Submissions still file.")
    with pytest.raises(release.ReleaseRefused):
        release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")


def test_a_release_that_never_applied_has_nothing_to_reverse(governed_conn):
    rel = release.prepare(governed_conn, name="r", intent="i",
                          resolution_id=_enact(governed_conn), prepared_by="coo")
    with pytest.raises(release.ReleaseRefused):
        release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")


def test_a_multi_instrument_release_reverses_all_of_it(governed_conn):
    """Stands or falls together applies to the way back too. A rollback that
    reversed some of a set would leave the same undesigned state a partial apply
    would."""
    resolution = _enact(governed_conn)
    rel = release.prepare(governed_conn, name="two", intent="two subjects",
                          resolution_id=resolution, prepared_by="coo")
    release.stage(governed_conn, rel, staged_by="coo",
                  instrument=_instrument(text="A.", requires=REQUIRE_SOURCE))
    release.stage(governed_conn, rel, staged_by="coo",
                  instrument=_instrument(text="B.", subject=fi_db.REPORT_SUBJECT))
    release.apply(governed_conn, rel, applied_by="analysis")

    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")
    release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")

    assert governed.effective_item(governed_conn, register.SUBMISSION_SUBJECT) is None
    assert governed.effective_item(governed_conn, fi_db.REPORT_SUBJECT) is None
    assert _files_ok(governed_conn, title="After both") is True


# --- nothing about rollback erases history ------------------------------------------------

def test_the_failed_instrument_is_preserved_and_readable(governed_conn):
    """Addendum 46 §18's closing requirement, and 30 §27's *failure evidence
    SHALL be preserved*. A rolled-back version remains organizational memory."""
    rel = _released(governed_conn, requires=REQUIRE_SOURCE)
    failed = release.changes(governed_conn, rel)[0]["adopted_item_id"]
    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")
    release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")

    item = governed.get_item(governed_conn, failed)
    assert item is not None, "the rollback deleted the instrument"
    assert item["superseded_at"] is not None
    assert item["text"]


def test_a_rollback_is_distinguishable_from_a_change_of_mind(governed_conn):
    """`superseded_by` pointing **backwards in id order**, which no ordinary
    supersession can produce - an ordinary one is always displaced by a row
    inserted after it. A reader of `governed_items` alone can tell which
    happened."""
    resolution = _enact(governed_conn)
    first = governed.adopt(governed_conn, resolution_id=resolution, adopted_by="coo",
                           **_instrument(text="Version N."))
    rel = release.prepare(governed_conn, name="n+1", intent="i",
                          resolution_id=resolution, prepared_by="coo")
    release.stage(governed_conn, rel, staged_by="coo",
                  instrument=_instrument(text="Version N+1.", replaces=first))
    second = release.apply(governed_conn, rel, applied_by="analysis")[0]

    assert governed.get_item(governed_conn, first)["superseded_by"] == second, (
        "an ordinary supersession points forwards")

    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")
    release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")

    reversed_item = governed.get_item(governed_conn, second)
    assert reversed_item["superseded_by"] == first < second, (
        "a reversal is indistinguishable from an ordinary supersession")
    assert governed.get_item(governed_conn, first)["superseded_at"] is None


def test_the_postmortem_is_composed_from_the_record(governed_conn):
    """Addendum 46 §18 step 7. Composed rather than stored: a narrative written
    beside the rows is a second copy that can disagree with them."""
    rel = _released(governed_conn, requires=REQUIRE_SOURCE)
    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="Every submission refused.")
    release.roll_back(governed_conn, rel, rolled_back_by="analysis",
                      reason="Nothing can satisfy it.")

    report = release.postmortem(governed_conn, rel)
    assert report["health"] == release.HEALTH_UNHEALTHY
    assert report["evidence"] == "Every submission refused."
    assert report["rollback_reason"] == "Nothing can satisfy it."
    assert report["judged_by"] == "analysis" != report["prepared_by"]
    assert len(report["failed_instruments_preserved"]) == 1
    # It says what it did not do, every time (§129's rule one level down).
    assert any("lessons" in line for line in report["not_recorded"])
    assert any("acceptance criteria" in line for line in report["not_recorded"])


# --- reversal reaches only what its own release adopted -----------------------------------

def test_reversal_refuses_an_instrument_something_else_already_superseded(governed_conn):
    """Reversing it would undo a change this caller did not make - an unvoted
    repeal with a maintenance name on it."""
    resolution = _enact(governed_conn)
    rel = _released(governed_conn)
    adopted = release.changes(governed_conn, rel)[0]["adopted_item_id"]
    governed.adopt(governed_conn, resolution_id=resolution, adopted_by="coo",
                   **_instrument(text="Somebody else's newer rule.", replaces=adopted))

    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")
    with pytest.raises(governed.AdoptionRefused) as refusal:
        release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")
    assert "did not make" in str(refusal.value)


def test_reversal_refuses_a_restore_target_it_did_not_displace(governed_conn):
    """Without this check, `reverse` would be a way to put any archived
    instrument back in force, and precedence would be settled by whoever called
    it last."""
    resolution = _enact(governed_conn)
    stranger = governed.adopt(governed_conn, resolution_id=resolution, adopted_by="coo",
                              **_instrument(text="Unrelated.", subject=fi_db.REPORT_SUBJECT))
    mine = governed.adopt(governed_conn, resolution_id=resolution, adopted_by="coo",
                          **_instrument(text="Mine."))
    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.reverse(governed_conn, adopted_id=mine, restore_id=stranger)
    assert "did not displace" in str(refusal.value)


# --- the code half, observed and never chosen ---------------------------------------------

def test_the_code_version_is_recorded_at_every_stage(governed_conn):
    """Addendum 30 §26's compatibility checking needs facts to check."""
    rel = _released(governed_conn)
    row = release.require(governed_conn, rel)
    assert row["code_version_prepared"] and row["code_version_applied"]
    assert row["code_version_rolled_back"] is None


def test_a_rollback_under_different_code_says_the_system_is_not_restored(governed_conn):
    """**Restoring the data under a different code version is not a return to the
    last known-good condition**, and this system cannot fix that - it does not
    choose its code version. So it is reported, with the versions named."""
    rel = _released(governed_conn)
    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")
    governed_conn.execute("UPDATE releases SET code_version_applied = ? WHERE id = ?",
                          ("a" * 40, rel))
    result = release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")

    assert result["code_version_matched"] is False
    assert "is not" in result["code_version_note"]
    assert "a" * 40 in result["code_version_note"]


def test_matching_code_versions_are_reported_as_matching(governed_conn):
    rel = _released(governed_conn)
    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")
    result = release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")
    assert result["code_version_matched"] is True
    assert "code_version_note" not in result


def test_nothing_here_deploys_restarts_or_writes_to_the_repository():
    """**Prevention by absence**, the argument §120 makes about the Constitution
    and §122 about the living documentation: the safest write path is one that
    does not exist.

    The organization observes its code version through `backend/version.py` and
    may not choose it. A release module that could run git, spawn a process or
    restart a service would either not work or breach that boundary - and §119 §5
    forbade building a release as a restart script in terms.

    Asserted over the *parsed* module rather than over its text, which matters
    here more than usual: this module's whole docstring is about restarts and
    deployment, and a substring scan would be satisfied by prose and defeated by
    it in turn. What is forbidden is the import and the call, so those are what
    is read."""
    tree = ast.parse(inspect.getsource(release))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names} | {
        node.module.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    for forbidden in ("subprocess", "os", "shutil", "signal", "socket", "multiprocessing"):
        assert forbidden not in imported, (
            f"backend/release.py imports {forbidden!r}; a release here is governed data, "
            f"and code is not this organization's to deploy (§139 §3)")

    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for forbidden in ("run", "Popen", "system", "spawn", "kill", "terminate", "restart",
                      "exec", "open"):
        assert forbidden not in called, (
            f"backend/release.py calls {forbidden!r}, which is not something a governed-data "
            f"release has any business doing (§139 §3)")


# --- the department stages into a candidate, and cannot keep credit for a rollback -------

def _directive(conn, *, resolution, subject=register.SUBMISSION_SUBJECT):
    return engineering.receive(
        conn, title="Name your source", intended_outcome="Submissions name a source.",
        resolution_id=resolution, requirement=REQUIRE_SOURCE, subject=subject,
        binds="explorer")


def _proposed(conn, *, resolution, engineer="engineer-1"):
    directive_id = _directive(conn, resolution=resolution)
    directive = engineering.get_directive(conn, directive_id)
    level, reasoning = engineering.assess(directive)
    work = engineering.record_assessment(conn, directive_id, engineer=engineer,
                                         level=level, reasoning=reasoning)
    engineering.propose_instrument(
        conn, work, instrument=engineering.instrument_for(directive))
    return work


def test_an_approval_into_a_release_changes_nothing_yet(governed_conn):
    """Addendum 46 §16's Version N+1: designed, approved, and not yet in force.
    Calling that delivered would be the department scoring for work the
    organization has not received (§119 §8)."""
    resolution = _enact(governed_conn)
    work = _proposed(governed_conn, resolution=resolution)
    rel = release.prepare(governed_conn, name="n+1", intent="source rule",
                          resolution_id=resolution, prepared_by="engineer-1")

    engineering.stage_for_release(governed_conn, work, release_id=rel, approver="coo")

    assert _files_ok(governed_conn, title="Staged") is True, (
        "a staged change reached force before the release applied")
    outcome = engineering.delivered_outcomes(governed_conn)[0]
    assert outcome["standing"] == engineering.STANDING_STAGED
    assert outcome["instrument_id"] is None


def test_staging_still_refuses_the_engineer_as_the_only_approval(governed_conn):
    """Approving into a release is still approving (addendum 46 §11)."""
    resolution = _enact(governed_conn)
    work = _proposed(governed_conn, resolution=resolution)
    rel = release.prepare(governed_conn, name="n+1", intent="i",
                          resolution_id=resolution, prepared_by="coo")
    with pytest.raises(engineering.EngineeringRefused) as refusal:
        engineering.stage_for_release(governed_conn, work, release_id=rel,
                                      approver="engineer-1")
    assert "§11" in str(refusal.value)


def test_a_release_may_not_contain_a_change_authorised_by_another_resolution(governed_conn):
    """Addendum 30 §27's guarantee is that the way back was granted by the vote
    that granted the way forward. Two resolutions in one set is two different
    answers to *who authorised undoing this*."""
    work = _proposed(governed_conn, resolution=_enact(governed_conn, title="one"))
    rel = release.prepare(governed_conn, name="other", intent="i",
                          resolution_id=_enact(governed_conn, title="two"),
                          prepared_by="coo")
    with pytest.raises(engineering.EngineeringRefused) as refusal:
        engineering.stage_for_release(governed_conn, work, release_id=rel, approver="coo")
    assert "authorised by another" in str(refusal.value)


def test_the_department_cannot_keep_credit_for_a_rolled_back_change(governed_conn):
    """§119 §8's metric trap in the dimension TQ-96 creates.

    The work row says an instrument was adopted and nothing would ever come back
    to say it was reversed - so the standing is **derived on read**, and a
    department scored on it loses the credit the moment the change is undone."""
    resolution = _enact(governed_conn)
    work = _proposed(governed_conn, resolution=resolution)
    rel = release.prepare(governed_conn, name="n+1", intent="i",
                          resolution_id=resolution, prepared_by="coo")
    engineering.stage_for_release(governed_conn, work, release_id=rel, approver="analysis")
    release.apply(governed_conn, rel, applied_by="coo")

    assert engineering.delivered_outcomes(governed_conn)[0]["standing"] == \
        engineering.STANDING_IN_FORCE
    assert _files_ok(governed_conn, title="Released") is False

    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="Every explorer submission is refused.")
    release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="misdrafted")

    assert engineering.delivered_outcomes(governed_conn)[0]["standing"] == \
        engineering.STANDING_REVERSED, (
        "the department kept credit for a change the organization rolled back")
    assert _files_ok(governed_conn, title="Rolled back") is True


def test_a_directly_approved_change_that_is_later_superseded_says_so(governed_conn):
    """The same derivation over the other approval path, so the honest metric
    does not depend on which route the change took."""
    resolution = _enact(governed_conn)
    work = _proposed(governed_conn, resolution=resolution)
    item = engineering.approve(governed_conn, work, approver="coo")
    assert engineering.delivered_outcomes(governed_conn)[0]["standing"] == \
        engineering.STANDING_IN_FORCE

    governed.adopt(governed_conn, resolution_id=resolution, adopted_by="coo",
                   **_instrument(text="A later rule.", replaces=item))
    assert engineering.delivered_outcomes(governed_conn)[0]["standing"] == \
        engineering.STANDING_SUPERSEDED


# --- the Speaker: an unhealthy release cannot be invisible --------------------------------

def test_the_speaker_names_an_unhealthy_release_in_force(governed_conn):
    """§130's problem one level up: a change quietly making the organization
    worse looks exactly like one that is working. A release marked unhealthy that
    nobody surfaces is a rollback nobody performs - and the way back is already
    authorised, so the only missing thing is that somebody knows."""
    rel = _released(governed_conn, requires=REQUIRE_SOURCE)
    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="Every submission refused.")

    report = speaker.compose_report(governed_conn)
    assert report["releases"]["unhealthy_in_force"] == ["r"]
    assert "unhealthy" in report["says"]
    assert "way back" in report["says"]


def test_the_speaker_says_when_a_release_in_force_is_unjudged(governed_conn):
    """Unjudged is not passing (§118). Reported under its own name so a reader
    cannot mistake silence for a clean bill."""
    _released(governed_conn)
    report = speaker.compose_report(governed_conn)
    assert report["releases"]["unjudged_in_force"] == ["r"]
    assert "nobody has judged" in report["says"]


def test_the_speaker_reports_a_rolled_back_release_rather_than_forgetting_it(governed_conn):
    """Addendum 46 §18: a rolled-back version remains organizational memory."""
    rel = _released(governed_conn)
    release.judge(governed_conn, rel, health=release.HEALTH_UNHEALTHY,
                  judged_by="analysis", evidence="e")
    release.roll_back(governed_conn, rel, rolled_back_by="analysis", reason="r")
    report = speaker.compose_report(governed_conn)
    assert report["releases"]["rolled_back"] == ["r"]
    assert "rolled back and are kept" in report["says"]


def test_the_speaker_cannot_perform_a_release(governed_conn):
    """It reports on one. A spokesperson who could also apply and reverse
    releases is not reporting on the organization's changes, it is making them -
    the same argument that keeps it out of `parliament.propose` and `cast_vote`.

    Absence of the capability, so it is read from the parsed module rather than
    demonstrated by one failing call."""
    tree = ast.parse(inspect.getsource(speaker))
    reached = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and getattr(node.func.value, "id", None) == "release"}
    assert reached <= {"summary"}, f"the Speaker reaches release.{reached - {'summary'}}"
