"""Noticing that Krish will want something, before he asks.

Krish, 2026-09-23: *"the anticipating ability or predictive abilities are what is
characterized as being preemptive in being helpful like humans holding the door
and being thoughtful like a caring parent."*

The trust ladder had nothing on it until this: `anticipation` scores guesses and
`readback` offers them, and nothing made one. The two behaviours worth reading
these tests for are the split between noticing and saying - everything noticed is
recorded, little of it is spoken - and the rung finally changing behaviour rather
than describing it.

Probed by `tests/probes/noticing_probes.py`.
"""

from datetime import datetime, timedelta, timezone

import pytest

from gateway import anticipation, noticing
from gateway.anticipation import (FULL_STOP, MENTION, NOT_NOW, OBSERVE, PERFECT,
                                  WANTED, Guess)
from gateway.noticing import (COMMITMENT_DUE, COMMITMENT_OVERDUE,
                              MOST_PER_SWEEP, QUIET_DAYS, REPEATED_REQUEST,
                              Prompting, notice, recently_declined,
                              worth_saying)

AGENT = "jarvis"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def commitment(promise="send Krish the Q3 statement", days=1, status="open"):
    return {"status": status, "promise": promise,
            "due_on": (NOW + timedelta(days=days)).isoformat()}


def request(count=4, needed="read a PDF", kind="missing_tool"):
    return {"count": count, "what_was_needed": needed, "gap_type": kind,
            "last_seen": NOW.isoformat()}


def earned(rung, domain="commitments"):
    """A record good enough for `domain` to sit at `rung`."""
    made = []
    if rung == OBSERVE:
        return made
    count = {MENTION: 5, FULL_STOP: 12}[rung]
    for index in range(count):
        one = Guess(domain=domain, what="something", because="a reason",
                    made_at=NOW)
        anticipation.settle(one, outcome=WANTED, by="krish", agent=AGENT,
                            now=NOW + timedelta(minutes=index))
        if rung == FULL_STOP:
            anticipation.rate(one, quality=PERFECT, by="krish", agent=AGENT,
                              now=NOW + timedelta(minutes=index, seconds=30))
        made.append(one)
    return made


# --- noticing reads what is already recorded ------------------------------------

def test_a_promise_coming_due_is_noticed():
    found = notice(commitments=[commitment(days=1)], now=NOW)
    assert [one.source for one in found] == [COMMITMENT_DUE]
    assert "due on 24 September" in found[0].because


def test_a_promise_already_missed_is_noticed_and_ranked_first():
    found = notice(commitments=[commitment(days=1),
                                commitment("reply to the accountant", days=-3)],
                   now=NOW)
    assert [one.source for one in found] == [COMMITMENT_OVERDUE, COMMITMENT_DUE]
    assert "has not been settled" in found[0].because


def test_a_promise_three_weeks_away_is_not_noise_yet():
    assert notice(commitments=[commitment(days=21)], now=NOW) == []


def test_a_promise_already_kept_is_left_alone():
    assert notice(commitments=[commitment(status="kept")], now=NOW) == []
    assert notice(commitments=[commitment(status="released")], now=NOW) == []


def test_a_promise_with_no_date_is_not_guessed_at():
    """Inventing a deadline would make silence look like a missed one."""
    assert notice(commitments=[{"status": "open", "promise": "something"}],
                  now=NOW) == []


def test_a_promise_with_no_text_is_not_noticed():
    assert notice(commitments=[{"status": "open", "due_on": NOW.isoformat()}],
                  now=NOW) == []


def test_something_asked_for_often_enough_becomes_a_pattern():
    found = notice(requests=[request(count=4)], now=NOW)
    assert [one.source for one in found] == [REPEATED_REQUEST]
    assert "asked for this 4 times" in found[0].because


def test_asking_twice_is_a_coincidence():
    assert notice(requests=[request(count=2)], now=NOW) == []


def test_every_noticing_carries_the_record_it_came_from():
    """*"Why did you think that?"* has an answer that is not a feeling."""
    for one in notice(commitments=[commitment(days=-1)],
                      requests=[request()], now=NOW):
        assert one.because and one.source in noticing.SOURCES


def test_noticing_observes_nothing_itself():
    """It reads rows this system already keeps. Asserted over the imports,
    because the difference between anticipation and invention is exactly that
    every prompting traces to a record."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(noticing.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "dataclasses", "datetime", "gateway"}
    assert noticing.describe()["observes_the_world"] is False


def test_a_prompting_becomes_a_guess_with_its_trigger_intact():
    one = notice(commitments=[commitment(days=1)], now=NOW)[0]
    guess = one.as_guess(now=NOW)
    assert guess.domain == "commitments"
    assert guess.because == one.because
    assert guess.by_when == one.by_when


# --- saying is a separate decision, and the rung makes it -------------------------

def test_at_the_bottom_rung_everything_is_recorded_and_nothing_is_said():
    """The first place in this system where the rung changes behaviour rather
    than describing it."""
    found = notice(commitments=[commitment(days=1)], now=NOW)
    say, quiet = worth_saying(found, earned(OBSERVE), now=NOW)
    assert say == []
    assert quiet == found


def test_once_the_rung_allows_it_the_same_noticing_is_said():
    found = notice(commitments=[commitment(days=1)], now=NOW)
    say, quiet = worth_saying(found, earned(MENTION), now=NOW)
    assert say == found and quiet == []


def test_a_domain_that_has_earned_nothing_stays_quiet_while_another_speaks():
    """Per domain, so one bad area does not silence a good one."""
    found = notice(commitments=[commitment(days=1)], requests=[request()],
                   now=NOW)
    say, quiet = worth_saying(found, earned(MENTION, domain="commitments"),
                              now=NOW)
    assert [one.domain for one in say] == ["commitments"]
    assert [one.domain for one in quiet] == ["missing_tool"]


def test_everything_noticed_is_recorded_even_when_nothing_is_said():
    """An assistant that only writes down what it is allowed to say can never
    demonstrate it was right, so it can never climb. That makes the bottom rung
    a starting point rather than a trap."""
    found = notice(commitments=[commitment(days=1)], requests=[request()],
                   now=NOW)
    say, quiet = worth_saying(found, earned(OBSERVE), now=NOW)
    assert len(say) + len(quiet) == len(found)


def test_holding_forty_doors_is_not_helpfulness():
    found = [Prompting(domain="commitments", what=f"thing {index}",
                       because="a reason", source=COMMITMENT_DUE, urgency=index)
             for index in range(20)]
    say, quiet = worth_saying(found, earned(MENTION), now=NOW)
    assert len(say) == MOST_PER_SWEEP
    assert len(quiet) == 20 - MOST_PER_SWEEP


def test_the_cap_is_on_what_is_said_and_never_on_what_is_noticed():
    many = [commitment(f"promise {index}", days=1) for index in range(20)]
    assert len(notice(commitments=many, now=NOW)) == 20


def test_the_most_pressing_things_are_the_ones_that_get_said():
    found = notice(
        commitments=[commitment("due soon", days=1),
                     commitment("badly overdue", days=-30),
                     commitment("just overdue", days=-1)],
        now=NOW)
    say, _ = worth_saying(found, earned(MENTION), now=NOW, most=1)
    assert say[0].what == "badly overdue"


# --- not now means not now --------------------------------------------------------

def test_a_recent_not_now_holds_the_same_ground_back():
    """He answered. Asking again that afternoon is how a person learns to stop
    reading what they are asked."""
    made = earned(MENTION)
    declined = Guess(domain="commitments", what="x", because="y", made_at=NOW)
    anticipation.settle(declined, outcome=NOT_NOW, by="krish", agent=AGENT,
                        now=NOW)
    made.append(declined)

    found = notice(commitments=[commitment(days=1)], now=NOW)
    say, quiet = worth_saying(found, made, now=NOW + timedelta(days=1))
    assert say == [] and quiet == found


def test_the_quiet_period_ends():
    made = earned(MENTION)
    declined = Guess(domain="commitments", what="x", because="y", made_at=NOW)
    anticipation.settle(declined, outcome=NOT_NOW, by="krish", agent=AGENT,
                        now=NOW)
    made.append(declined)

    later = NOW + timedelta(days=QUIET_DAYS + 1)
    found = notice(commitments=[commitment(days=1)], now=NOW)
    say, _ = worth_saying(found, made, now=later)
    assert say == found


def test_a_not_now_in_one_area_does_not_silence_another():
    made = earned(MENTION, domain="commitments") + \
        earned(MENTION, domain="missing_tool")
    declined = Guess(domain="commitments", what="x", because="y", made_at=NOW)
    anticipation.settle(declined, outcome=NOT_NOW, by="krish", agent=AGENT,
                        now=NOW)
    made.append(declined)

    found = notice(commitments=[commitment(days=1)], requests=[request()],
                   now=NOW)
    say, _ = worth_saying(found, made, now=NOW + timedelta(days=1))
    assert [one.domain for one in say] == ["missing_tool"]


def test_a_wanted_guess_does_not_hold_anything_back():
    """Only *not at the moment* buys quiet. Being right is not a reason to stop."""
    assert recently_declined("commitments", earned(MENTION),
                             now=NOW + timedelta(days=1)) is False


# --- the numbers are policy ---------------------------------------------------------

def test_the_policy_numbers_are_what_they_are():
    """Literals, with the reason each has its value."""
    # Long enough to do something about it, short enough not to be noise about
    # a thing three weeks away.
    assert noticing.DUE_WITHIN_DAYS == 2
    # Twice is a coincidence.
    assert noticing.TIMES_BEFORE_A_PATTERN == 3
    # Six things you might want is help; sixty is a cost.
    assert MOST_PER_SWEEP == 3
    # A week, so a "not now" is respected without becoming forgetting.
    assert QUIET_DAYS == 7


def test_describe_says_it_records_more_than_it_says():
    assert noticing.describe()["records_everything_it_notices"] is True
    assert set(noticing.describe()["sources"]) == set(noticing.SOURCES)
