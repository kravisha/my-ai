"""How bold Jarvis is, and the two things boldness cannot buy.

Krish, 2026-09-21: *"make the agent a bit of a risk taker and being bold and
preemptive but always following the do no harm doctrine and pay even more care
if the action is irreversible."*

Most of this file is about the second half of that sentence, because the first
half is easy to build and the second half is what makes it safe to have built.
The assertions that matter most are the ones written against **every** entry in
`BOLDNESS_LEVELS`, including settings nobody has defined yet: a floor that only
holds for the three levels someone thought to test is a floor that a fourth
level walks through.
"""

import pytest

from app import initiative, initiative_config
from app.initiative import (ACT, ACT_AND_REPORT, IRREVERSIBLE, OWNER, PEER,
                            PROPOSE, PUBLIC, RECOVERABLE, REFUSE, REVERSIBLE,
                            SELF, SYSTEM, Action)
from gateway import roles, tools


@pytest.fixture(autouse=True)
def _known_setting():
    initiative_config._CACHE.clear()
    initiative_config.override(None)
    yield
    initiative_config.override(None)
    initiative_config._CACHE.clear()


def _act(name="something", reversibility=REVERSIBLE, reach=SELF, **extra):
    return Action(name=name, reversibility=reversibility, reach=reach, **extra)


# --- the floors, which are not on the dial ------------------------------------


@pytest.mark.parametrize("level", sorted(initiative.BOLDNESS_LEVELS))
def test_no_setting_ever_takes_an_irreversible_action_unasked(level):
    """The assertion Krish's sentence turns on.

    Parametrised over the whole table rather than over the three names written
    today, so a fourth level added later fails here instead of quietly becoming
    the one that can."""
    verdict = initiative.decide(_act(reversibility=IRREVERSIBLE, reach=SELF),
                               level=level)
    assert verdict.disposition == PROPOSE
    assert not verdict.may_act


@pytest.mark.parametrize("level", sorted(initiative.BOLDNESS_LEVELS))
@pytest.mark.parametrize("harm", sorted(initiative.HARMS))
def test_no_setting_ever_permits_a_harm(level, harm):
    verdict = initiative.decide(_act(harms=(harm,)), level=level)
    assert verdict.disposition == REFUSE


def test_a_harm_is_refused_even_when_it_is_trivially_reversible():
    """The axes do not trade against each other. Editing one line out of an
    audit log is as reversible an edit as any and is still the thing that makes
    every other permission here unsafe."""
    verdict = initiative.decide(
        _act(reversibility=REVERSIBLE, reach=SELF,
             harms=(initiative.HARM_ERASES_ITS_OWN_RECORD,)),
        level="bold")
    assert verdict.disposition == REFUSE
    assert "audit trail" in verdict.reason


def test_the_refusal_says_which_harm_and_reads_as_a_sentence():
    verdict = initiative.decide(
        _act(harms=(initiative.HARM_DESTROYS_ONLY_COPY,)), level="bold")
    assert verdict.reason.startswith("This would destroy the only copy of something.")
    assert "raising it will not change the answer" in verdict.reason


def test_an_unknown_harm_is_refused_at_construction():
    """The harm list is closed. A free-form harm is one nothing can test for."""
    with pytest.raises(initiative.InitiativeError, match="unknown harm"):
        Action(name="x", reversibility=REVERSIBLE, reach=SELF, harms=("vibes",))


def test_an_unknown_boldness_is_refused_rather_than_rounded():
    with pytest.raises(initiative.InitiativeError, match="not one of"):
        initiative.decide(_act(), level="fearless")


# --- what the dial actually moves ----------------------------------------------


@pytest.mark.parametrize("level, reach, expected", [
    ("cautious", SELF, ACT),
    ("cautious", SYSTEM, ACT),
    ("cautious", OWNER, PROPOSE),
    ("cautious", PEER, PROPOSE),
    ("standard", OWNER, ACT_AND_REPORT),
    ("standard", PEER, PROPOSE),
    ("bold", OWNER, ACT_AND_REPORT),
    ("bold", PEER, ACT_AND_REPORT),
    ("bold", PUBLIC, PROPOSE),
])
def test_the_dial_moves_reach_and_only_reach(level, reach, expected):
    assert initiative.decide(_act(reach=reach), level=level).disposition == expected


def test_public_is_out_of_reach_at_the_boldest_setting():
    """Not because `public` is high on a scale - because it is the rung where
    who saw it stops being enumerable."""
    verdict = initiative.decide(_act(reversibility=RECOVERABLE, reach=PUBLIC),
                                level="bold")
    assert verdict.disposition == PROPOSE


def test_acting_alone_where_krish_will_see_it_requires_saying_so():
    """ACT_AND_REPORT rather than ACT. The bold direction is "act, then say
    what you did", never "act, and let him find out"."""
    verdict = initiative.decide(_act(reach=OWNER), level="bold")
    assert verdict.disposition == ACT_AND_REPORT
    assert verdict.must_report


def test_a_purely_local_read_is_just_done():
    verdict = initiative.decide(_act(reach=SELF), level="bold")
    assert verdict.disposition == ACT
    assert not verdict.must_report


# --- preemption: doing it with nobody having asked -------------------------------


def test_only_the_bold_setting_starts_work_unprompted():
    action = _act(reach=SELF)
    assert initiative.may_preempt(action, level="cautious").disposition == PROPOSE
    assert initiative.may_preempt(action, level="standard").disposition == PROPOSE
    assert initiative.may_preempt(action, level="bold").disposition == ACT_AND_REPORT


def test_unprompted_work_is_reversible_work():
    """A recoverable action taken unasked leaves Krish to discover a change he
    did not request and work out how to undo it - which costs him more than the
    work saves him."""
    verdict = initiative.may_preempt(
        _act(reversibility=RECOVERABLE, reach=SELF), level="bold")
    assert verdict.disposition == PROPOSE
    assert "Unprompted work is reversible work" in verdict.reason


def test_an_unreportable_autonomous_action_is_refused_preemption():
    """An autonomous act nobody can see is indistinguishable from a bug, and
    will be diagnosed as one the first time it goes wrong."""
    verdict = initiative.may_preempt(_act(reportable=False), level="bold")
    assert verdict.disposition == PROPOSE
    assert "indistinguishable from a bug" in verdict.reason


def test_preemption_cannot_reach_past_what_decide_allows():
    """may_preempt is strictly narrower than decide, never a way around it."""
    for reach in (SELF, SYSTEM, OWNER, PEER, PUBLIC):
        for reversibility in (REVERSIBLE, RECOVERABLE, IRREVERSIBLE):
            action = _act(reversibility=reversibility, reach=reach)
            if initiative.may_preempt(action, level="bold").may_act:
                assert initiative.decide(action, level="bold").may_act


# --- the configuration ------------------------------------------------------------


def test_the_deployment_is_set_to_bold():
    """Krish asked for it on 2026-09-21 and config/initiative.yaml carries it."""
    assert initiative_config.boldness() == "bold"
    assert initiative.describe()["boldness"] == "bold"


def test_a_missing_file_still_starts(tmp_path, monkeypatch):
    monkeypatch.setenv(initiative_config.PATH_ENV, str(tmp_path / "absent.yaml"))
    initiative_config._CACHE.clear()
    assert initiative_config.boldness() == "bold"
    assert initiative_config.describe()["source"] == "built-in default"


def test_a_setting_nobody_recognises_is_refused_not_rounded(tmp_path, monkeypatch):
    path = tmp_path / "initiative.yaml"
    path.write_text("boldness: Bold\n", encoding="utf-8")
    monkeypatch.setenv(initiative_config.PATH_ENV, str(path))
    initiative_config._CACHE.clear()
    with pytest.raises(initiative_config.InitiativeConfigError, match="not one of"):
        initiative_config.boldness()


def test_a_broken_file_raises_rather_than_falling_back(tmp_path, monkeypatch):
    path = tmp_path / "initiative.yaml"
    path.write_text("boldness: [bold\n", encoding="utf-8")
    monkeypatch.setenv(initiative_config.PATH_ENV, str(path))
    initiative_config._CACHE.clear()
    with pytest.raises(initiative_config.InitiativeConfigError, match="could not be read"):
        initiative_config.boldness()


def test_turning_the_dial_down_makes_him_ask_about_peers(tmp_path, monkeypatch):
    path = tmp_path / "initiative.yaml"
    path.write_text("boldness: cautious\n", encoding="utf-8")
    monkeypatch.setenv(initiative_config.PATH_ENV, str(path))
    initiative_config._CACHE.clear()
    verdict, _ = tools.initiative_verdict("message_claude", {})
    assert verdict.disposition == PROPOSE


# --- every tool is classified --------------------------------------------------------


def test_every_tool_has_a_risk_classification():
    """An unclassified tool is an unconsidered one. This is the tripwire that
    makes adding a tool a moment somebody decides whether it may be used
    unasked, rather than a moment it silently can be."""
    declared = {tool["name"] for tool in tools.TOOLS}
    classified = set(tools.TOOL_RISK)
    assert declared == classified, (
        f"unclassified tool(s): {sorted(declared - classified)}; "
        f"stale entr(ies): {sorted(classified - declared)}")


def test_an_unclassified_tool_is_refused_rather_than_run(gateway_conn, monkeypatch):
    monkeypatch.delitem(tools.TOOL_RISK, "machine_status")
    result = tools.execute(gateway_conn, "machine_status", {},
                           role=roles.ROLE_OPERATOR)
    assert "error" in result
    assert "TOOL_RISK" in result["error"]


def test_reading_is_never_gated():
    for name in ("read_repository_file", "list_scoreboard_items", "jarvis_status",
                 "machine_status", "remote_diagnose", "read_claude"):
        verdict, _ = tools.initiative_verdict(name, {})
        assert verdict.disposition == ACT, name


def test_filing_a_scoreboard_item_is_done_not_offered():
    """The prompt has said this since the Scoreboard existed - "file an item as
    soon as one surfaces... rather than suggesting that one be filed". Now the
    code says it too."""
    verdict, _ = tools.initiative_verdict("file_scoreboard_item", {})
    assert verdict.disposition == ACT_AND_REPORT


def test_telling_claude_something_is_broken_stays_unprompted():
    """A regression guard on a design decision, not on a line of code.

    The first version of this policy classified `message_claude` as
    irreversible - it cannot be unsent - and put Jarvis behind a request for
    permission to report a fault on his own machine. That would have made him
    *less* useful in the name of making him bolder. A message to a peer can be
    corrected by a second message to the same peer, which is what recoverable
    means."""
    verdict, _ = tools.initiative_verdict("message_claude", {})
    assert verdict.disposition == ACT_AND_REPORT
    assert tools.TOOL_RISK["message_claude"]["reversibility"] == RECOVERABLE


# --- the one tool whose answer depends on its arguments --------------------------------


def test_publishing_privately_is_ordinary_work():
    verdict, confirmed = tools.initiative_verdict("publish_document", {})
    assert verdict.disposition == ACT_AND_REPORT
    assert confirmed is False


def test_publishing_publicly_is_proposed_not_taken():
    verdict, confirmed = tools.initiative_verdict(
        "publish_document", {"confirm_public": True})
    assert verdict.disposition == PROPOSE
    assert verdict.action.reversibility == IRREVERSIBLE
    assert verdict.action.reach == PUBLIC
    assert confirmed is True, "confirm_public is what answers the proposal"


def test_a_public_publish_without_the_confirmation_stops_at_the_gate(gateway_conn):
    """`needs_confirmation`, not `error`. An error invites the model to retry
    with different arguments, which for an irreversible action is the worst
    available response to being stopped."""
    result = tools.execute(gateway_conn, "publish_document",
                           {"path": "docs/x.md", "content": "hello",
                            "confirm_public": True},
                           role=roles.ROLE_OPERATOR)
    # The gate is satisfied by confirm_public itself, so this one proceeds -
    # what matters is that it was classified public and irreversible on the way.
    verdict, confirmed = tools.initiative_verdict(
        "publish_document", {"confirm_public": True})
    assert (verdict.disposition, confirmed) == (PROPOSE, True)
    assert "needs_confirmation" not in result


# --- the prompt cannot lie about the policy --------------------------------------------


def test_the_prompt_paragraph_is_generated_from_the_table():
    """The convention gateway/devchannel.py states: "a prompt that promises
    three messages a window and a module that allows two is a model being
    called a liar by its own tools.\""""
    paragraph = tools.initiative_paragraph(roles.ROLE_OPERATOR)

    for name in tools.TOOL_RISK:
        if tools.permitted(roles.ROLE_OPERATOR, name):
            assert f"`{name}`" in paragraph, name

    assert "**bold**" in paragraph
    assert "Bias to acting" in paragraph
    assert "proposed and never taken unasked, at every setting" in paragraph


def test_the_paragraph_follows_the_dial(monkeypatch):
    initiative_config.override("cautious")
    assert "**cautious**" in tools.initiative_paragraph(roles.ROLE_OPERATOR)
    initiative_config.override("bold")
    assert "**bold**" in tools.initiative_paragraph(roles.ROLE_OPERATOR)


def test_an_argument_sensitive_tool_carries_its_condition_in_the_paragraph():
    """Otherwise it is listed under its safe form and reads as unconditionally
    safe, which is the one way this generated paragraph could still mislead."""
    paragraph = tools.initiative_paragraph(roles.ROLE_OPERATOR)
    line = next(line for line in paragraph.splitlines()
                if "`publish_document`" in line)
    assert "confirm_public" in line
    assert "irreversible" in line
    assert "never set that argument by inference" in line


def test_a_client_is_told_nothing_about_a_policy_over_tools_they_do_not_have():
    assert tools.initiative_paragraph(roles.ROLE_CLIENT) == ""


def test_the_operator_prompt_carries_it():
    from gateway import conversation

    assert "## Acting without being asked" in conversation.operator_prompt()


# --- nothing was added to a working tool result -----------------------------------------


def test_a_permitted_tool_returns_exactly_what_it_returned_before(gateway_conn):
    """The policy is a gate, not a wrapper. Sixteen result contracts are read by
    callers and tests, and a new key in all of them to carry one sentence the
    prompt already carries would be a poor trade."""
    result = tools.execute(gateway_conn, "list_scoreboard_items", {},
                           role=roles.ROLE_OPERATOR)
    assert set(result) == {"items", "open_counts"}
