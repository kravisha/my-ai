"""Natural language as a control surface (backend/view_intents.py;
addendum 40 §10, §11; TQ-32, SPEC_RECONCILIATION §84).

Two things this suite holds, and the second matters more than the first.

**Commands are recognised** — §11's own examples ("show that tab", "go back",
"open the agent conversation") act instantly, with no model call.

**Questions are not.** Everything this layer accepts moves the operator's
screen, so certainty is the bar: an ambiguous phrase must fall through to the
model rather than guess. A control surface that acts on a maybe teaches an
operator to distrust it, and the failure is worse than the miss — a wrong jump
mid-sentence loses their place, while a fall-through merely costs a model
call.
"""

import pytest

from backend import view_intents as vi
from backend.view_intents import (
    ACTION_BACK, ACTION_CLEAR_FILTERS, ACTION_FILTER_ATTENTION,
    ACTION_FOLLOW, ACTION_PAUSE, ACTION_SHOW_VIEW,
)


# --- §11's control examples act -----------------------------------------------


@pytest.mark.parametrize("phrase,view", [
    ("show me the chatterbox", "chatterbox"),
    ("open the agent conversations", "chatterbox"),
    ("show that finance tab", "finance"),
    ("take me to alerts", "alerts"),
    ("switch to the organization view", "organization"),
    ("go to simulation", "simulation"),
    ("pull up the strategy register", "strategy"),
    ("let's see parliament", "parliament"),
    ("bring up the newsroom", "newsroom"),
])
def test_show_commands_name_a_view(phrase, view):
    directive = vi.interpret(phrase)
    assert directive is not None, f"{phrase!r} should be recognised as a command"
    assert directive["action"] == ACTION_SHOW_VIEW
    assert directive["view"] == view
    assert directive["say"], "a command should say what it did"


@pytest.mark.parametrize("phrase", ["chatterbox", "finance", "alerts", "the markets"])
def test_a_bare_view_name_is_a_command(phrase):
    """An operator who says "chatterbox" at the console means show it."""
    assert vi.interpret(phrase)["action"] == ACTION_SHOW_VIEW


def test_aliases_follow_the_operator_not_the_tab_label(phrase="show me collaboration"):
    """"conversations", "collaboration" and "chatterbox" are the same desk.
    Refusing a synonym would be the interface insisting on its own
    vocabulary."""
    assert vi.interpret(phrase)["view"] == "chatterbox"
    assert vi.interpret("show me the markets")["view"] == "finance"
    assert vi.interpret("show me who is running")["view"] == "organization"


def test_the_other_controls():
    assert vi.interpret("go back")["action"] == ACTION_BACK
    assert vi.interpret("back to the previous view")["action"] == ACTION_BACK
    assert vi.interpret("just show me errors")["action"] == ACTION_FILTER_ATTENTION
    assert vi.interpret("only warnings please")["action"] == ACTION_FILTER_ATTENTION
    assert vi.interpret("clear the filters")["action"] == ACTION_CLEAR_FILTERS
    assert vi.interpret("pause the feed")["action"] == ACTION_PAUSE
    assert vi.interpret("resume the feed")["action"] == ACTION_FOLLOW


# --- questions must fall through ----------------------------------------------


@pytest.mark.parametrize("question", [
    "what is happening between Explorer and Analyst?",
    "why is the simulation engine idle?",
    "how many agents are running?",
    "what failed during startup?",
    "what stage are we in?",
    "is the finance desk showing real prices?",
    "which departments are idle?",
    "what changed while I was away?",
    "tell me about the alerts we had yesterday and whether the market moved",
])
def test_questions_are_left_to_the_model(question):
    """A question is not a command. Swallowing one would replace an answer
    with a tab change - the worst possible trade."""
    assert vi.interpret(question) is None


def test_ambiguity_falls_through_rather_than_guessing():
    """Two desks named at once is not certainty, and certainty is the bar."""
    assert vi.interpret("show me finance and alerts") is None
    assert vi.interpret("compare the simulation and the organization") is None


def test_empty_and_noise_are_safe():
    for text in ("", "   ", "?", "hmm", None):
        assert vi.interpret(text) is None


def test_a_sentence_about_a_desk_is_not_a_jump_to_it():
    """The bare-name shortcut is bounded to short utterances precisely so a
    sentence *about* a desk is not hijacked into opening it."""
    assert vi.interpret("the chatterbox showed a silent conversation earlier today") is None


# --- the softer focus hint ------------------------------------------------------


def test_focus_hint_is_looser_than_a_command():
    """§10 wants both halves: change the focus *and* answer. The hint never
    suppresses the model, so it can afford to be less certain - a wrong hint
    costs a tab change during an answer that still arrives."""
    assert vi.followed_by_view("what is happening in the chatterbox?") == "chatterbox"
    assert vi.followed_by_view("are there any alerts?") == "alerts"
    # Still refuses ambiguity - a hint that flails is worse than none.
    assert vi.followed_by_view("compare finance and simulation") is None
    assert vi.followed_by_view("how are things?") is None


# --- the vocabulary is the console's -------------------------------------------


def test_every_view_the_console_renders_is_steerable():
    """A desk the COO cannot open is a desk the operator has to reach with a
    mouse, which §11 says should never be required."""
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "backend" / "console" / "index.html").read_text(
        encoding="utf-8")
    rendered = set(__import__("re").findall(r'data-tab="([a-z_]+)"', html))
    assert rendered, "no tabs found in the console"
    assert rendered <= set(vi.VIEWS), (
        f"the console renders {sorted(rendered - set(vi.VIEWS))} which the COO cannot open"
    )


def test_no_directive_writes_anything():
    """Every action here changes what is displayed and nothing else, which is
    why none of them need a confirmation step (§11's confirmation rule applies
    to consequential actions, and looking at a tab is not one)."""
    actions = {vi.interpret(p)["action"] for p in
               ("show me finance", "go back", "just show me errors",
                "clear filters", "pause the feed", "resume the feed")}
    assert actions <= {ACTION_SHOW_VIEW, ACTION_BACK, ACTION_FILTER_ATTENTION,
                       ACTION_CLEAR_FILTERS, ACTION_PAUSE, ACTION_FOLLOW}
