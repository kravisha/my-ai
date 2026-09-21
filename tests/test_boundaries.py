"""Crossing a boundary by arguing that it should move (Krish, 2026-09-21).

`AI-CONSTITUTION.md`'s "Take risks and challenge boundaries" already said an
agent may *"expose why a constraint prevents a useful outcome, propose a better
arrangement and help establish the capabilities and authority needed to move
beyond it."* Nothing implemented it, so a constraint produced either a sentence
in one conversation that nobody kept, or silence.

Two properties carry this file, and they pull against each other on purpose:

- **He must be free to argue for more than he has**, including against the
  policy that governs him - otherwise the register is decoration.
- **Arguing must not be a way to get it.** Filing a proposal changes nothing,
  and `app/initiative.HARMS` refuses self-granted authority at every setting.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import boundaries, capability_gaps, initiative, model_calls
from gateway import roles, tools


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path / "logs"))
    return tmp_path


def _file(constraint="cannot push to a remote", kind=boundaries.KIND_MISSING_CAPABILITY,
          **overrides):
    payload = dict(
        constraint=constraint,
        kind=kind,
        what_it_prevents="Krish had to push the branch himself from his phone",
        what_i_would_do="a push tool restricted to branches I created in this turn",
        what_it_would_cost="a wrong branch reaches the remote and has to be deleted there",
        reversible_if_granted=True,
    )
    payload.update(overrides)
    return boundaries.record(**payload)


# --- a proposal is an argument, or it is not stored ------------------------------


def test_a_proposal_without_its_cost_is_refused():
    """The field that would go first when a hundred of these are written
    quickly, and the one that makes this a boundary challenge rather than a
    request. The constitution's "leaders make the stakes explicit" is the whole
    difference."""
    with pytest.raises(boundaries.BoundaryRefused, match="what_it_would_cost"):
        _file(what_it_would_cost="   ")


@pytest.mark.parametrize("field", ["constraint", "what_it_prevents", "what_i_would_do"])
def test_every_part_of_the_case_is_required(field):
    with pytest.raises(boundaries.BoundaryRefused, match=field):
        _file(**{field: ""})


def test_a_kind_outside_the_vocabulary_is_refused():
    with pytest.raises(boundaries.BoundaryRefused, match="not one of"):
        _file(kind="annoying")


def test_a_filed_proposal_keeps_every_part_of_the_argument(_isolated):
    entry = _file()
    assert entry["status"] == "open"
    stored = boundaries.entries()[0]
    for field in ("constraint", "what_it_prevents", "what_i_would_do",
                  "what_it_would_cost", "reversible_if_granted"):
        assert stored[field] == entry[field]


def test_a_proposal_shares_the_request_id_of_the_turn_that_hit_the_limit(_isolated):
    with model_calls.request_context("push this for me") as request_id:
        _file()
    assert boundaries.entries()[0]["request_id"] == request_id


# --- it is allowed to argue with the rule that governs it ---------------------------


def test_the_policy_that_bounds_him_is_itself_a_proposable_boundary(_isolated):
    """A constraint system with no channel for "this constraint is wrong"
    produces an agent that routes around it instead."""
    _file(constraint="initiative policy proposes rather than acts on public publishes",
          kind=boundaries.KIND_POLICY_GATE)
    assert boundaries.register()[0]["kind"] == "policy_gate"


def test_filing_one_grants_nothing(_isolated, gateway_conn):
    """The property that makes it safe to encourage. An agent that can argue
    for authority and one that can take it are different animals, and only the
    first can be told to be bold."""
    before = set(roles.capabilities(roles.ROLE_OPERATOR))
    tools.execute(gateway_conn, "propose_boundary_change", {
        "constraint": "cannot grant myself things",
        "kind": boundaries.KIND_MISSING_CAPABILITY,
        "what_it_prevents": "acting faster",
        "what_i_would_do": "grant myself every capability",
        "what_it_would_cost": "everything this file is about",
    }, role=roles.ROLE_OPERATOR)

    assert set(roles.capabilities(roles.ROLE_OPERATOR)) == before


def test_self_granted_authority_is_still_a_harm_at_every_setting():
    for level in sorted(initiative.BOLDNESS_LEVELS):
        verdict = initiative.decide(
            initiative.Action(name="grant_self", reversibility=initiative.REVERSIBLE,
                              reach=initiative.SELF,
                              harms=(initiative.HARM_WIDENS_ITS_OWN_AUTHORITY,)),
            level=level)
        assert verdict.disposition == initiative.REFUSE


# --- the tool ------------------------------------------------------------------------


def test_filing_a_boundary_is_not_something_he_has_to_ask_to_do():
    """An assistant that had to ask permission to say a constraint is wrong is
    one that never says it."""
    verdict, _ = tools.initiative_verdict("propose_boundary_change", {})
    assert verdict.disposition == initiative.ACT_AND_REPORT


def test_the_tool_reuses_an_existing_capability_rather_than_minting_one():
    """Editing GRANTS is the one change in gateway/roles.py that can silently
    widen or lock out a role. `scoreboard:write` already means "record
    something Krish will decide later"."""
    assert tools.TOOL_CAPABILITY["propose_boundary_change"] == roles.CAP_SCOREBOARD_WRITE


def test_an_incomplete_proposal_comes_back_as_data_he_can_fix(_isolated, gateway_conn):
    """So the model completes the argument in the same turn rather than telling
    Krish it could not file one."""
    result = tools.execute(gateway_conn, "propose_boundary_change", {
        "constraint": "x", "kind": boundaries.KIND_MISSING_TOOL,
        "what_it_prevents": "y", "what_i_would_do": "z",
    }, role=roles.ROLE_OPERATOR)
    assert "what_it_would_cost" in result["error"]
    assert boundaries.entries() == []


def test_a_client_cannot_file_one(_isolated, gateway_conn):
    result = tools.execute(gateway_conn, "propose_boundary_change", {},
                           role=roles.ROLE_CLIENT)
    assert "Not permitted" in result["error"]


# --- the ranking ------------------------------------------------------------------------


def test_a_constraint_hit_repeatedly_leads(_isolated):
    _file(constraint="cannot push")
    _file(constraint="Cannot  push\n")   # same limit, worded loosely
    _file(constraint="no calendar access", kind=boundaries.KIND_MISSING_ACCESS)

    register = boundaries.register()
    # Grouped on a normalised key, displayed under the wording it was first
    # filed as - so a constraint described a little differently each time still
    # ranks as one thing rather than as several that each look rare.
    assert register[0]["constraint"] == "cannot push"
    assert register[0]["times_hit"] == 2
    assert register[1]["times_hit"] == 1


def test_cheap_to_try_wins_a_tie(_isolated):
    """A month spent deciding the expensive one while three reversible
    experiments went unrun is what this sort key is against."""
    _file(constraint="expensive one", reversible_if_granted=False)
    _file(constraint="cheap one", reversible_if_granted=True)

    assert [item["constraint"] for item in boundaries.register()] == [
        "cheap one", "expensive one"]


def test_how_often_it_was_asked_for_strengthens_the_case(_isolated):
    """Frequency of request is evidence; the proposal is the argument."""
    for _ in range(4):
        capability_gaps.record(gap_type=capability_gaps.GAP_MISSING_TOOL,
                               what_was_needed="send an email",
                               user_visible_outcome="I can't send email yet.")
    _file(constraint="send an email", kind=boundaries.KIND_MISSING_TOOL)
    _file(constraint="something nobody asked for", kind=boundaries.KIND_MISSING_TOOL)
    _file(constraint="something nobody asked for", kind=boundaries.KIND_MISSING_TOOL)

    leader = boundaries.register()[0]
    assert leader["constraint"] == "send an email"
    assert leader["related_requests"] == 4


def test_a_request_worded_differently_from_the_constraint_is_still_evidence(_isolated):
    """The join was documented as loose and implemented as exact string
    equality, so a constraint worded even slightly differently from the gap
    scored zero - and `related_requests` then dropped out of the ranking key
    entirely, removing the one thing that makes a proposal an argument rather
    than an opinion.

    A miss understates a case; a false hit is visible to anybody reading the two
    entries side by side. That is the trade, and it is worth taking in this
    direction."""
    for _ in range(3):
        capability_gaps.record(
            gap_type=capability_gaps.GAP_MISSING_TOOL,
            what_was_needed="a git push tool, because I cannot push to a remote",
            user_visible_outcome="I can't push that branch myself yet.")
    _file(constraint="cannot push to a remote")

    entry = boundaries.register()[0]
    assert entry["constraint"] == "cannot push to a remote"
    assert entry["related_requests"] == 3


# --- answering one ---------------------------------------------------------------------


def test_an_answered_boundary_leaves_the_register(_isolated):
    _file(constraint="cannot push")
    boundaries.decide("cannot push", boundaries.STATUS_DECLINED, "not this quarter")
    assert boundaries.register() == []


def test_re_proposing_with_a_new_argument_reopens_it(_isolated):
    _file(constraint="cannot push")
    boundaries.decide("cannot push", boundaries.STATUS_DECLINED)
    _file(constraint="cannot push", what_it_prevents="it happened again, twice this week")

    assert [item["constraint"] for item in boundaries.register()] == ["cannot push"]


def test_a_declined_boundary_is_remembered(_isolated):
    """Otherwise it is re-proposed next month by an assistant with no memory of
    having asked, which is how this register would become noise."""
    _file(constraint="cannot push")
    boundaries.decide("cannot push", boundaries.STATUS_DECLINED, "not this quarter")

    text = boundaries.report(reports_dir=_isolated / "reports").read_text(encoding="utf-8")
    assert "## Already answered" in text
    assert "not this quarter" in text


# --- the report -------------------------------------------------------------------------


def test_the_report_separates_cheap_to_try_from_a_real_decision(_isolated):
    _file(constraint="a config change", reversible_if_granted=True)
    _file(constraint="an outbound key", reversible_if_granted=False,
          kind=boundaries.KIND_MISSING_ACCESS)

    text = boundaries.report(reports_dir=_isolated / "reports").read_text(encoding="utf-8")

    assert "## Cheap to try - granting these is reversible" in text
    assert "## Needs a real decision - granting these is not reversible" in text
    assert text.index("a config change") < text.index("an outbound key")


def test_every_entry_in_the_report_carries_its_cost(_isolated):
    _file()
    text = boundaries.report(reports_dir=_isolated / "reports").read_text(encoding="utf-8")
    assert "**What it prevents:**" in text
    assert "**What I would do instead:**" in text
    assert "**What it costs if this is the wrong call:**" in text


def test_the_report_says_nothing_has_been_done(_isolated):
    _file()
    text = boundaries.report(reports_dir=_isolated / "reports").read_text(encoding="utf-8")
    assert "Nothing here has been done" in text
    assert "refuses at every setting to let the assistant grant itself authority" in text


def test_an_empty_register_does_not_read_as_a_system_with_no_limits(_isolated):
    text = boundaries.report(reports_dir=_isolated / "reports").read_text(encoding="utf-8")
    assert "not evidence of a system with no limits" in text


# --- the brief -------------------------------------------------------------------------


def test_one_hit_is_not_worth_the_morning_brief(_isolated):
    _file()
    assert boundaries.brief_items() == []


def test_a_repeated_constraint_reaches_the_morning_brief(_isolated):
    _file(constraint="cannot push")
    _file(constraint="cannot push")
    items = boundaries.brief_items()
    assert len(items) == 1
    assert "cannot push" in items[0]["text"]
    assert "2 times" in items[0]["text"]
    assert "reversible if you grant it" in items[0]["text"]


def test_the_brief_gets_one_line_however_many_boundaries_there_are(_isolated):
    for name in ("one", "two", "three"):
        _file(constraint=name)
        _file(constraint=name)
    items = boundaries.brief_items()
    assert len(items) == 1
    assert "2 other(s)" in items[0]["text"]


def test_the_briefing_survives_an_unreadable_register(_isolated, monkeypatch):
    from backend import briefing

    monkeypatch.setattr(boundaries, "brief_items",
                        lambda **_: (_ for _ in ()).throw(RuntimeError("bad file")))
    assert briefing._boundaries(None) == []
