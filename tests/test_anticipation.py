"""Guessing what Krish wants before he asks, and being scored on it.

Krish, 2026-09-23: *"trust means anticipating correctly what i need and correctly
executing it to perfection... at some point I know that he would execute to
perfection and would give him a free hand to complete things as per his
discretion and just present me the final result which is the point called the
full stop."* And: *"the anticipating ability or predictive abilities are what is
characterized as being preemptive in being helpful like humans holding the door."*

Two objectives that turned out to be one capability seen twice.

Probed by `tests/probes/anticipation_probes.py`.
"""

from datetime import datetime, timedelta, timezone

import pytest

from gateway import anticipation
from gateway.anticipation import (ACCURACY_TO_CLIMB, ACT_AND_REPORT, FAILED,
                                  FLAWED, FULL_STOP, MENTION, MIN_SETTLED,
                                  NOT_NOW, NotYet, OBSERVE, PERFECT, PREPARE,
                                  RUNGS, WANTED, WRONG, Guess, may, settle,
                                  standing)

AGENT = "jarvis"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def guess(domain="expenses", what="the quarterly statement",
          because="the quarter closed and he asked on the 3rd last year",
          **kwargs):
    kwargs.setdefault("made_at", NOW)
    return Guess(domain=domain, what=what, because=because, **kwargs)


def run_of(count, *, outcome=WANTED, quality=PERFECT, domain="expenses"):
    made = []
    for index in range(count):
        one = guess(domain=domain)
        settle(one, outcome=outcome, by="krish", agent=AGENT, quality=quality,
               now=NOW + timedelta(minutes=index))
        made.append(one)
    return made


# --- a guess is only a guess if it was written down first ----------------------

def test_a_guess_needs_a_reason_it_was_made():
    """A guess with no stated trigger cannot be argued with and teaches nothing
    when it turns out wrong."""
    with pytest.raises(NotYet, match="needs a because"):
        Guess(domain="expenses", what="something", because="  ")


@pytest.mark.parametrize("missing", ["domain", "what"])
def test_a_guess_needs_a_domain_and_a_subject(missing):
    fields = {"domain": "expenses", "what": "something", "because": "a reason"}
    fields[missing] = ""
    with pytest.raises(NotYet, match=f"needs a {missing}"):
        Guess(**fields)


def test_a_guess_cannot_be_settled_before_it_was_made():
    """Recorded afterwards it is hindsight, and hindsight scores perfectly."""
    one = guess()
    with pytest.raises(NotYet, match="hindsight"):
        settle(one, outcome=WANTED, by="krish", agent=AGENT,
               now=NOW - timedelta(minutes=1))


def test_a_settled_guess_cannot_be_rescored():
    """Otherwise a bad week is tidied up later."""
    one = run_of(1)[0]
    with pytest.raises(NotYet, match="already settled"):
        settle(one, outcome=WRONG, by="krish", agent=AGENT, now=NOW)


# --- nothing here grades itself -------------------------------------------------

def test_jarvis_cannot_score_his_own_guess():
    """*A prediction graded by the predictor reads a hundred per cent for ever.*"""
    with pytest.raises(NotYet, match="cannot score its own"):
        settle(guess(), outcome=WANTED, by=AGENT, agent=AGENT, now=NOW)


def test_the_check_is_not_fooled_by_case_or_spacing():
    with pytest.raises(NotYet, match="cannot score its own"):
        settle(guess(), outcome=WANTED, by="  JARVIS ", agent="jarvis", now=NOW)


def test_a_settled_guess_must_say_who_settled_it():
    with pytest.raises(NotYet, match="who settled it"):
        settle(guess(), outcome=WANTED, by="   ", agent=AGENT, now=NOW)


def test_the_module_cannot_work_out_an_outcome_for_itself():
    """`settle` takes the outcome; there is no function that derives one."""
    import inspect
    assert "outcome" in inspect.signature(settle).parameters
    exported = {name for name in dir(anticipation) if not name.startswith("_")}
    assert not {"judge", "evaluate", "score", "grade"} & exported
    assert anticipation.describe()["grades_itself"] is False


@pytest.mark.parametrize("outcome", ["probably", "", None, "right"])
def test_outcomes_are_a_closed_set(outcome):
    with pytest.raises(NotYet, match="outcome must be one of"):
        settle(guess(), outcome=outcome, by="krish", agent=AGENT, now=NOW)


# --- three outcomes, because two would hide the interesting one ----------------

def test_right_at_the_wrong_moment_is_not_the_same_as_wrong():
    """Holding a door for somebody who wanted to walk past is a different
    mistake from holding a door that is not there. Collapsing them teaches
    *stop noticing* rather than *notice and wait*."""
    held = run_of(MIN_SETTLED, outcome=NOT_NOW)
    wrong = run_of(MIN_SETTLED, outcome=WRONG, domain="email")

    assert standing("expenses", held, now=NOW).not_now == MIN_SETTLED
    assert standing("expenses", held, now=NOW).wrong == 0
    assert standing("email", wrong, now=NOW).wrong == MIN_SETTLED


def test_a_right_but_ill_timed_guess_holds_the_ladder_at_mention():
    """The record saying: notice, and let him choose the moment."""
    made = run_of(9) + run_of(1, outcome=NOT_NOW)
    earned = standing("expenses", made, now=NOW)
    assert earned.rung == MENTION
    assert "let Krish choose the moment" in earned.because


# --- a deadline that passes is an answer ---------------------------------------

def test_an_unanswered_deadline_counts_against_the_record():
    """Otherwise an assistant climbs by guessing often and settling only the
    hits."""
    made = run_of(MIN_SETTLED)
    made.append(guess(by_when=NOW + timedelta(days=1)))
    earned = standing("expenses", made, now=NOW + timedelta(days=2))
    assert earned.wrong == 1
    assert earned.settled == MIN_SETTLED + 1


def test_a_guess_still_within_its_deadline_counts_neither_way():
    made = run_of(MIN_SETTLED)
    made.append(guess(by_when=NOW + timedelta(days=1)))
    assert standing("expenses", made, now=NOW).settled == MIN_SETTLED


def test_a_guess_with_no_deadline_never_goes_overdue():
    """Not every anticipation has a moment it stops being useful, and inventing
    one would make silence look like a wrong guess."""
    assert guess().overdue(now=NOW + timedelta(days=3650)) is False


# --- the ladder, slow up ---------------------------------------------------------

def test_a_domain_with_no_history_watches_and_says_nothing():
    earned = standing("email", [], now=NOW)
    assert earned.rung == OBSERVE
    assert earned.accuracy is None
    assert "below the 5" in earned.because


def test_a_small_sample_says_nothing_whatever_its_hit_rate():
    made = run_of(MIN_SETTLED - 1)
    assert standing("expenses", made, now=NOW).rung == OBSERVE


def test_guessing_badly_keeps_it_watching():
    made = run_of(5) + run_of(5, outcome=WRONG)
    earned = standing("expenses", made, now=NOW)
    assert earned.rung == OBSERVE
    assert "More noticing, less suggesting" in earned.because


def test_the_rungs_are_climbed_one_run_at_a_time():
    """Each rung needs a longer unbroken run of faultless work than the last."""
    reached = {}
    for count in (5, 9, 12):
        reached[count] = standing("expenses", run_of(count), now=NOW).rung
    assert reached == {5: ACT_AND_REPORT, 9: ACT_AND_REPORT, 12: FULL_STOP}


def test_prepare_is_where_a_domain_sits_while_it_is_recovering():
    """The rung is reachable, and this is the shape that reaches it: enough
    settled guesses to be judged at all, and a faultless run that is long enough
    to be trusted with the reversible part but not with acting alone.

    Written because the first version of the test above expected five perfect
    executions to land here, and they do not - five in a row is already enough
    for `act_and_report`. A rung nothing can reach would be a lie in the
    ladder, so this is what reaching it looks like."""
    made = run_of(5)
    stumble = guess()
    settle(stumble, outcome=WANTED, by="krish", agent=AGENT, quality=FAILED,
           now=NOW + timedelta(hours=1))
    made.append(stumble)
    for index in range(4):
        recovered = guess()
        settle(recovered, outcome=WANTED, by="krish", agent=AGENT,
               quality=PERFECT, now=NOW + timedelta(hours=2, minutes=index))
        made.append(recovered)

    earned = standing("expenses", made, now=NOW)
    assert earned.perfect_run == 4
    assert earned.rung == PREPARE


def test_the_free_hand_is_the_top_of_the_ladder():
    """*"the point called the full stop"* - does it, and presents the result."""
    earned = standing("expenses", run_of(12), now=NOW)
    assert earned.rung == FULL_STOP
    assert "free hand" in earned.because
    assert RUNGS[-1] == FULL_STOP


# --- and fast down ---------------------------------------------------------------

def test_one_botched_execution_drops_the_rung_immediately():
    """Slow up, fast down - which is how it works with people."""
    made = run_of(12)
    assert standing("expenses", made, now=NOW).rung == FULL_STOP

    botched = guess()
    settle(botched, outcome=WANTED, by="krish", agent=AGENT, quality=FAILED,
           now=NOW + timedelta(hours=1))
    made.append(botched)
    assert standing("expenses", made, now=NOW).rung == MENTION


def test_merely_flawed_work_also_breaks_the_run():
    """*"executing it to perfection"* - so the run counts perfect, not passable."""
    made = run_of(12)
    flawed = guess()
    settle(flawed, outcome=WANTED, by="krish", agent=AGENT, quality=FLAWED,
           now=NOW + timedelta(hours=1))
    made.append(flawed)
    assert standing("expenses", made, now=NOW).perfect_run == 0


def test_a_long_good_history_does_not_dilute_a_recent_failure():
    """A run, not a rate. A rate lets an old failure be washed out by volume.

    The failure is settled *after* everything else on purpose: "recent" is by
    settled time, and the first version of this test timestamped it in the
    middle of the run, where it correctly counted for nothing."""
    made = run_of(200)
    botched = guess()
    settle(botched, outcome=WANTED, by="krish", agent=AGENT, quality=FAILED,
           now=NOW + timedelta(days=1))
    made.append(botched)
    assert standing("expenses", made, now=NOW).perfect_run == 0
    assert standing("expenses", made, now=NOW).rung == MENTION


def test_climbing_back_costs_the_same_as_climbing_the_first_time():
    made = run_of(12)
    botched = guess()
    settle(botched, outcome=WANTED, by="krish", agent=AGENT, quality=FAILED,
           now=NOW + timedelta(hours=1))
    made.append(botched)
    for index in range(10):
        recovered = guess()
        settle(recovered, outcome=WANTED, by="krish", agent=AGENT,
               quality=PERFECT, now=NOW + timedelta(hours=2, minutes=index))
        made.append(recovered)
    assert standing("expenses", made, now=NOW).rung == FULL_STOP


# --- per domain, never global ----------------------------------------------------

def test_a_free_hand_in_one_domain_is_not_a_free_hand_in_another():
    """*"You might give him a free hand on expense statements and none on
    email."* One mistake in the second must not cost the first."""
    made = run_of(12, domain="expenses") + run_of(5, outcome=WRONG,
                                                  domain="email")
    assert standing("expenses", made, now=NOW).rung == FULL_STOP
    assert standing("email", made, now=NOW).rung == OBSERVE


def test_may_answers_for_one_domain_and_says_why():
    made = run_of(12, domain="expenses")
    allowed, why = may("expenses", made, at_least=ACT_AND_REPORT, now=NOW)
    assert allowed is True and why

    refused, why = may("email", made, at_least=MENTION, now=NOW)
    assert refused is False
    assert "below the 5" in why


def test_may_refuses_a_rung_nobody_declared():
    with pytest.raises(NotYet, match="rung must be one of"):
        may("expenses", [], at_least="do_whatever", now=NOW)


# --- the numbers are policy, so they are written out -----------------------------

def test_the_policy_numbers_are_what_they_are():
    """Literals, with the reason each has its value - the rule CLAUDE.md carries
    after a probe found this class three times in one day."""
    # Small: the lowest rungs cost little to be wrong about, and the execution
    # run below is what guards the top.
    assert MIN_SETTLED == 5
    # Not a hundred per cent: an assistant that never guesses wrong is one that
    # never guesses.
    assert ACCURACY_TO_CLIMB == 0.8
    # Each rung costs more than the last, and the free hand costs ten.
    assert anticipation.RUN_TO_CLIMB == {PREPARE: 3, ACT_AND_REPORT: 5,
                                         FULL_STOP: 10}
    assert RUNGS == (OBSERVE, MENTION, PREPARE, ACT_AND_REPORT, FULL_STOP)


def test_every_rung_says_what_it_means_in_plain_words():
    described = anticipation.describe()
    assert set(described["rung_meaning"]) == set(RUNGS)
    assert "free hand" in described["rung_meaning"][FULL_STOP]
    assert described["per_domain"] is True


# =============================================================================
# Where the guesses actually come from
# =============================================================================
#
# A record nothing writes to is this repository's commonest failure. Unprompted
# read-backs are the producer: Jarvis raising something Krish did not ask for is
# a guess about what he wants, and Krish's answer - or his silence - is the grade.


def _register(clock):
    from app import initiative
    from gateway import readback

    action = initiative.Action(
        name="draft_expenses", reversibility=initiative.IRREVERSIBLE,
        reach=initiative.PEER, summary="draft the Q3 expense statement")
    understanding = readback.Understanding(
        action=action,
        particulars=(readback.Particular("quarter", "Q3", readback.INFERRED),))
    return readback.Register(now=clock), understanding


def test_an_unprompted_offer_is_recorded_as_a_guess():
    register, understanding = _register(lambda: NOW)
    register.offer(understanding, prompted=False,
                   because="the quarter closed yesterday")
    assert [one.domain for one in register.guesses] == ["draft_expenses"]
    assert register.guesses[0].because.startswith("the quarter closed")


def test_a_read_back_for_something_krish_asked_for_is_not_a_guess():
    """The load-bearing default. Counting it would fill the record with things
    nobody anticipated and score them all correct."""
    register, understanding = _register(lambda: NOW)
    register.offer(understanding)
    assert register.guesses == []


def test_an_unprompted_offer_must_say_what_prompted_it():
    from gateway.readback import NotStated as Refused
    register, understanding = _register(lambda: NOW)
    with pytest.raises(Refused, match="what made Jarvis think of it"):
        register.offer(understanding, prompted=False)
    assert register.guesses == []


def test_krish_saying_yes_is_the_grade():
    """And a grade Jarvis did not author, which is what `settle` requires."""
    register, understanding = _register(lambda: NOW)
    register.offer(understanding, prompted=False, because="the quarter closed")
    register.answer(confirmed_by="krish", agent=AGENT)

    scored = register.guesses[0]
    assert scored.outcome == WANTED
    assert scored.settled_by == "krish"


def test_silence_is_recorded_as_a_bad_moment_not_a_bad_guess():
    """Krish may well have needed the thing and not wanted it done then.
    Recording that as wrong teaches Jarvis to stop noticing, when the lesson
    available is to wait."""
    clock = [NOW]
    register, understanding = _register(lambda: clock[0])
    register.offer(understanding, prompted=False, because="the quarter closed")

    clock[0] = NOW + timedelta(hours=1)
    assert register.lapse_guesses(agent=AGENT) == 1
    assert register.guesses[0].outcome == NOT_NOW
    assert register.guesses[0].settled_by == "the clock"


def test_a_guess_still_inside_its_window_is_left_alone():
    clock = [NOW]
    register, understanding = _register(lambda: clock[0])
    register.offer(understanding, prompted=False, because="the quarter closed")
    clock[0] = NOW + timedelta(minutes=1)
    assert register.lapse_guesses(agent=AGENT) == 0
    assert register.guesses[0].settled is False


def test_an_answered_guess_is_not_lapsed_as_well():
    clock = [NOW]
    register, understanding = _register(lambda: clock[0])
    register.offer(understanding, prompted=False, because="the quarter closed")
    register.answer(confirmed_by="krish", agent=AGENT)

    clock[0] = NOW + timedelta(hours=1)
    assert register.lapse_guesses(agent=AGENT) == 0
    assert register.guesses[0].outcome == WANTED


def test_the_record_outlives_any_one_register():
    """Handed in rather than owned, so a restart of the conversation does not
    reset what Jarvis has earned."""
    from gateway import readback
    kept = []
    register = readback.Register(now=lambda: NOW, guesses=kept)
    _, understanding = _register(lambda: NOW)
    register.offer(understanding, prompted=False, because="the quarter closed")
    assert len(kept) == 1
