"""The right to appeal an unfavourable ruling
(TQ-102; owner direction 2026-08-28; addendum 46 §11;
docs/SPEC_RECONCILIATION.md §144 §4, §145).

The owner named this one of two examples of the *"undeniable and inalienable"*
kind of rule that belongs in the Constitution. `backend/charter.py` has declared
it **owed and unenforced** since it was written.

The tests that matter are the ones about what an appeal cannot become, because
every way this goes wrong produces something that still looks like an appeal:

- one heard by the agent that made the ruling;
- one filed on somebody else's behalf;
- one that lapses, which is a denial nobody had to make;
- one an agent can refile until it wins;
- one an ordinary instrument can switch off.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend import appeal, charter, fi_db

ROOT = Path(__file__).resolve().parent.parent

PRODUCER = "analysis-1"
GRADER = "analysis-2"
PEER = "analysis-3"
OUTSIDER = "explorer-1"


def _register(conn, identity, role):
    fi_db.register_agent(conn, identity, role, pid=1000 + len(identity))


def _graded(conn, *, producer=PRODUCER, grader=GRADER, score=0.2) -> int:
    """A ruling: an analysis by `producer`, graded by `grader`.

    Built through the production API rather than by inserting rows, on §128's
    rule - a fixture able to construct states the organization cannot reach
    measures the fixture."""
    report = fi_db.enqueue_report(
        conn, producer, "t0", "lead", "SYN1", summary="something", evidence_ids=[])
    analysis = fi_db.record_analysis_result(
        conn, producer, "t0", report, "SYN1", "a thesis", "e", 0.5, "some")
    return fi_db.record_grade(
        conn, grader, "t0", report, analysis, score, score, score, False, score, "thin")


@pytest.fixture
def graded(conn):
    for identity, role in ((PRODUCER, "analysis"), (GRADER, "analysis"),
                           (OUTSIDER, "explorer")):
        _register(conn, identity, role)
    return conn, _graded(conn)


# --- the prerequisite: you cannot appeal what you were never told ----------------------

def test_an_agent_can_learn_how_its_own_work_was_judged(graded):
    """The charter's *"an agent is told what is found about it"*, and the
    organization model's declared gap 1. **The prerequisite, not a neighbour** -
    an appeal over rulings nobody can see is a right nobody can exercise."""
    conn, grade_id = graded
    rulings = appeal.rulings_about(conn, PRODUCER)
    assert [r["id"] for r in rulings] == [grade_id]
    assert rulings[0]["author"] == GRADER
    assert rulings[0]["rationale"] == "thin"
    assert rulings[0]["appealed"] is False


def test_rulings_are_derived_and_not_delivered(graded):
    """No notification table, so no write anybody has to remember to make. A
    sweeper that stopped would look exactly like an organization with nothing to
    report."""
    conn, _ = graded
    assert "notifications" not in {
        row["name"] for row in conn.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    # A second grade appears in the listing with no write of any kind.
    before = len(appeal.rulings_about(conn, PRODUCER))
    _graded(conn)
    assert len(appeal.rulings_about(conn, PRODUCER)) == before + 1


def test_an_agent_sees_only_rulings_about_itself(graded):
    conn, _ = graded
    assert appeal.rulings_about(conn, GRADER) == []
    assert appeal.rulings_about(conn, OUTSIDER) == []
    assert appeal.rulings_about(conn, "") == []


# --- filing ---------------------------------------------------------------------------

def test_the_subject_may_appeal(graded):
    conn, grade_id = graded
    appeal_id = appeal.file_appeal(
        conn, ruling_kind="grade", ruling_id=grade_id, appellant=PRODUCER,
        grounds="The evidence was cited and not read.")
    row = appeal.require(conn, appeal_id)
    assert row["appellant"] == PRODUCER
    assert row["author"] == GRADER
    assert row["heard_at"] is None
    assert appeal.rulings_about(conn, PRODUCER)[0]["appealed"] is True


def test_nobody_else_may_appeal_on_an_agents_behalf(graded):
    """An appeal filed by somebody else is an opinion, and this is the only place
    the distinction can be enforced."""
    conn, grade_id = graded
    for impostor in (GRADER, OUTSIDER, "analysis-9"):
        with pytest.raises(appeal.AppealRefused) as refusal:
            appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                               appellant=impostor, grounds="I disagree")
        assert "on another agent's behalf is an opinion" in str(refusal.value)


def test_an_appeal_states_why_the_ruling_is_wrong(graded):
    """A review of nothing would uphold everything."""
    conn, grade_id = graded
    with pytest.raises(appeal.AppealRefused) as refusal:
        appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                           appellant=PRODUCER, grounds="   ")
    assert "nothing for an adjudicator to review" in str(refusal.value)


def test_filing_does_not_depend_on_an_adjudicator_existing(graded):
    """**The property that makes this a right rather than a permission.** With
    one Analysis agent besides the grader there is nobody eligible, and the
    appeal is filed anyway."""
    conn, grade_id = graded
    assert appeal.eligible_adjudicators(
        conn, appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                 appellant=PRODUCER, grounds="wrong")) == []
    assert appeal.summary(conn)["filed"] == 1


def test_one_appeal_per_ruling(graded):
    """There is no appeal of an appeal - a second review needs a hierarchy this
    organization does not have - and an agent that could refile until it won
    would be relitigating."""
    conn, grade_id = graded
    appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                       appellant=PRODUCER, grounds="wrong")
    with pytest.raises(appeal.AppealRefused) as refusal:
        appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                           appellant=PRODUCER, grounds="still wrong")
    assert "relitigating" in str(refusal.value)


def test_an_unknown_ruling_kind_is_refused(graded):
    """A closed list. A kind nothing produces would be a right over rulings that
    do not exist."""
    conn, grade_id = graded
    with pytest.raises(appeal.AppealRefused):
        appeal.file_appeal(conn, ruling_kind="verdict", ruling_id=grade_id,
                           appellant=PRODUCER, grounds="wrong")


# --- who may hear it ------------------------------------------------------------------

def test_the_author_may_never_hear_their_own_ruling(graded):
    """**The charter's entire requirement**, enforced structurally rather than
    by convention: *reviewed by someone other than whoever made it*."""
    conn, grade_id = graded
    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    with pytest.raises(appeal.AppealRefused) as refusal:
        appeal.hear(conn, appeal_id, adjudicator=GRADER,
                    outcome=appeal.OUTCOME_UPHELD, rationale="I was right")
    assert "cannot review it" in str(refusal.value)
    assert GRADER not in appeal.eligible_adjudicators(conn, appeal_id)


def test_the_appellant_may_not_decide_their_own_appeal(graded):
    conn, grade_id = graded
    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    with pytest.raises(appeal.AppealRefused) as refusal:
        appeal.hear(conn, appeal_id, adjudicator=PRODUCER,
                    outcome=appeal.OUTCOME_OVERTURNED, rationale="I was right")
    assert "cannot also decide it" in str(refusal.value)
    assert PRODUCER not in appeal.eligible_adjudicators(conn, appeal_id)


def test_a_peer_of_the_author_hears_it(graded):
    """A peer, not a court. Nothing is appointed, so nothing can be removed -
    which is why this shape was chosen over a standing adjudicator."""
    conn, grade_id = graded
    _register(conn, PEER, "analysis")
    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    assert appeal.eligible_adjudicators(conn, appeal_id) == [PEER]

    appeal.hear(conn, appeal_id, adjudicator=PEER, outcome=appeal.OUTCOME_OVERTURNED,
                rationale="The evidence supports a higher score.")
    row = appeal.require(conn, appeal_id)
    assert row["heard_by"] == PEER
    assert row["outcome"] == appeal.OUTCOME_OVERTURNED


def test_an_agent_of_another_role_is_not_a_peer(graded):
    """Someone who cannot make this kind of ruling has no standing to review it."""
    conn, grade_id = graded
    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    assert OUTSIDER not in appeal.eligible_adjudicators(conn, appeal_id)


def test_an_unregistered_author_has_no_peers_rather_than_a_guessed_one(conn):
    """A retired or unknown identity. Guessing a role would be inventing the
    adjudicator's standing, which is worse than having none."""
    _register(conn, PRODUCER, "analysis")
    grade_id = _graded(conn, grader="ghost-1")
    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    assert appeal.eligible_adjudicators(conn, appeal_id) == []


def test_a_hearing_states_its_reasoning(graded):
    """`record_disposition`'s rule. An appeal upheld without one is
    indistinguishable from an appeal ignored."""
    conn, grade_id = graded
    _register(conn, PEER, "analysis")
    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    with pytest.raises(appeal.AppealRefused) as refusal:
        appeal.hear(conn, appeal_id, adjudicator=PEER,
                    outcome=appeal.OUTCOME_UPHELD, rationale="  ")
    assert "indistinguishable from an appeal ignored" in str(refusal.value)


def test_an_appeal_is_heard_once(graded):
    conn, grade_id = graded
    _register(conn, PEER, "analysis")
    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    appeal.hear(conn, appeal_id, adjudicator=PEER, outcome=appeal.OUTCOME_UPHELD,
                rationale="The grade stands.")
    with pytest.raises(appeal.AppealRefused) as refusal:
        appeal.hear(conn, appeal_id, adjudicator=PEER,
                    outcome=appeal.OUTCOME_OVERTURNED, rationale="changed my mind")
    assert "second instance" in str(refusal.value)


# --- what an appeal must never become --------------------------------------------------

def test_nothing_can_deny_expire_or_dismiss_an_appeal():
    """**The one that matters most, and it is an absence.**

    An appeal that lapses is a denial nobody had to make, and it would be
    indistinguishable from one that was heard and refused. So there is no
    `dismiss`, no `deny`, no `expire` and no timeout — the same construction
    `parliament.escalate` uses for owner escalations.

    Asserted over the parsed module because the property is the absence of a
    capability, which no single call can demonstrate the lack of."""
    tree = ast.parse((ROOT / "backend" / "appeal.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef)}
    for forbidden in ("dismiss", "deny", "expire", "close", "reject", "withdraw",
                      "purge", "sweep"):
        assert forbidden not in defined, (
            f"backend/appeal.py defines {forbidden}(); an appeal has exactly one way to "
            f"stop being open, and that is being heard.")

    source = (ROOT / "backend" / "appeal.py").read_text(encoding="utf-8")
    assert "DELETE FROM appeals" not in source, (
        "an appeal is removable; a deleted appeal is a denial with no record of who made it")


def test_no_ordinary_instrument_can_switch_the_right_off():
    """The owner placed this right in the Constitution, where changing it needs
    two-thirds. So this module reads **no governed data at all** — there is no
    instrument that can disable an appeal and no obligation kind that gates one.

    What an ordinary law may eventually govern is *procedure*. That distinction
    is the owner's own: durable rules in the Constitution, situational ones in
    ordinary law (§144)."""
    tree = ast.parse((ROOT / "backend" / "appeal.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[-1])
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
    for gate in ("governed_knowledge", "operating_context", "parliament"):
        assert gate not in imported, (
            f"backend/appeal.py imports {gate}; a right an ordinary instrument can gate is "
            f"a permission, and the owner placed this one in the Constitution (§144)."
        )


def test_overturning_a_ruling_erases_nothing(graded):
    """Addendum 46 §18's rule about rollback, applied to a reversed judgement for
    the same reason: a reversed decision stays part of organizational memory."""
    conn, grade_id = graded
    _register(conn, PEER, "analysis")
    before = conn.fetchone("SELECT * FROM grades WHERE id = ?", (grade_id,))
    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    appeal.hear(conn, appeal_id, adjudicator=PEER, outcome=appeal.OUTCOME_OVERTURNED,
                rationale="The evidence was not read.")

    after = conn.fetchone("SELECT * FROM grades WHERE id = ?", (grade_id,))
    assert after == before, "overturning edited the ruling instead of recording a review of it"
    assert appeal.require(conn, appeal_id)["rationale"] == "The evidence was not read."


# --- two numbers, not one ---------------------------------------------------------------

def test_an_unexercised_right_and_a_denied_one_are_distinguishable(graded):
    """§130's lesson where the failure would be least visible. Zero appeals filed
    is an organization nobody disagrees with; zero heard against many filed is a
    right that exists on paper. **Both look like silence in one number.**"""
    conn, grade_id = graded
    quiet = appeal.summary(conn)
    assert quiet["filed"] == 0 and quiet["heard"] == 0 and quiet["unheard"] == []

    appeal_id = appeal.file_appeal(conn, ruling_kind="grade", ruling_id=grade_id,
                                   appellant=PRODUCER, grounds="wrong")
    stuck = appeal.summary(conn)
    assert stuck["filed"] == 1 and stuck["heard"] == 0
    assert stuck["unheard"] == [appeal_id], "the waiting appeal is not named"
    assert [row["id"] for row in appeal.unheard(conn)] == [appeal_id]

    _register(conn, PEER, "analysis")
    appeal.hear(conn, appeal_id, adjudicator=PEER, outcome=appeal.OUTCOME_UPHELD,
                rationale="The grade stands.")
    done = appeal.summary(conn)
    assert done == {**done, "filed": 1, "heard": 1, "unheard": [], "upheld": 1,
                    "overturned": 0}


def test_the_summary_says_why_waiting_is_ordinary(graded):
    """This organization runs one of each role, so an appeal usually has no
    eligible peer. Stated every time rather than left for a reader to infer
    neglect from a number."""
    conn, _ = graded
    assert "never denied, expired" in appeal.summary(conn)["note"]


# --- the charter entry this discharges ----------------------------------------------------

def test_the_charter_still_names_appeal_and_says_what_changed():
    """The protection stays listed either way. What this increment must not do is
    quietly delete the entry — a charter that shed a promise on delivering it
    would lose the record that it was ever owed."""
    named = [p for p in charter.PROTECTIONS if "appealed" in p.name]
    assert len(named) == 1, "the charter stopped naming the right to appeal"
    assert "fundamental right" in named[0].statement
