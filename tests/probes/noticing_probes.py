"""Mutations that `tests/test_noticing.py` must notice.

This module fails in two directions that are both comfortable. Notice too little
and Jarvis is exactly as useless as before, with a record that says everything is
fine; notice too much and he is a person who points out sixty things, which
teaches Krish to stop reading. The quiet failure is the second one wearing the
first one's clothes: recording nothing, so nothing can ever be shown to have been
right, so the ladder never moves.

Run it directly:

    python tests/probes/noticing_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

NOTICING = "gateway/noticing.py"
UPKEEP = "gateway/upkeep.py"
SUITES = {NOTICING: TESTS / "test_noticing.py",
          UPKEEP: TESTS / "test_jarvis_upkeep.py"}

PROBES: list[harness.Probe] = [
    # --- what gets noticed ----------------------------------------------------
    (
        NOTICING,
        "a promise already kept is raised again",
        '        if (row.get("status") or "open") != "open":',
        "        if False:",
        ("test_a_promise_already_kept_is_left_alone",),
    ),
    (
        NOTICING,
        "a promise with no date gets one invented",
        "        if due is None:\n            continue",
        "        if due is None:\n            due = when",
        ("test_a_promise_with_no_date_is_not_guessed_at",),
    ),
    (
        NOTICING,
        "a promise with no text is raised as an empty one",
        "        if not promise:\n            continue",
        "        if False:\n            continue",
        ("test_a_promise_with_no_text_is_not_noticed",),
    ),
    (
        NOTICING,
        "everything on the calendar is raised, however far off",
        "        elif days <= DUE_WITHIN_DAYS:",
        "        else:",
        ("test_a_promise_three_weeks_away_is_not_noise_yet",),
    ),
    (
        NOTICING,
        "a promise three weeks away is as pressing as one due tomorrow",
        "DUE_WITHIN_DAYS = 2",
        "DUE_WITHIN_DAYS = 30",
        ("test_a_promise_three_weeks_away_is_not_noise_yet",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        NOTICING,
        "an overdue promise is not marked as overdue",
        "        if days < 0:",
        "        if False:",
        ("test_a_promise_already_missed_is_noticed_and_ranked_first",),
    ),
    (
        NOTICING,
        "asking twice is treated as a pattern",
        "        if count < TIMES_BEFORE_A_PATTERN:",
        "        if False:",
        ("test_asking_twice_is_a_coincidence",),
    ),
    (
        NOTICING,
        "one request is a pattern",
        "TIMES_BEFORE_A_PATTERN = 3",
        "TIMES_BEFORE_A_PATTERN = 1",
        ("test_asking_twice_is_a_coincidence",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        NOTICING,
        "the most pressing thing is not raised first",
        "    return sorted(found, key=lambda one: (-one.urgency, one.domain, one.what))",
        "    return sorted(found, key=lambda one: (one.urgency, one.domain, one.what))",
        ("test_a_promise_already_missed_is_noticed_and_ranked_first",
         "test_the_most_pressing_things_are_the_ones_that_get_said"),
    ),
    (
        NOTICING,
        "an overdue promise ranks below one merely due",
        "                urgency=100 + min(30, int(-days))))",
        "                urgency=1))",
        ("test_a_promise_already_missed_is_noticed_and_ranked_first",
         "test_the_most_pressing_things_are_the_ones_that_get_said"),
    ),
    (
        NOTICING,
        "a noticing carries no record of where it came from",
        '                         f"not been settled"),',
        '                         f""),',
        ("test_every_noticing_carries_the_record_it_came_from",
         "test_a_promise_already_missed_is_noticed_and_ranked_first"),
    ),
    (
        NOTICING,
        "the trigger is lost on the way to becoming a guess",
        "            domain=self.domain, what=self.what, because=self.because,",
        '            domain=self.domain, what=self.what, because="anticipated",',
        ("test_a_prompting_becomes_a_guess_with_its_trigger_intact",),
    ),
    (
        NOTICING,
        "the module starts observing the world itself",
        "from gateway import anticipation",
        "import subprocess  # noqa: F401\nfrom gateway import anticipation",
        ("test_noticing_observes_nothing_itself",),
    ),
    # --- saying is a separate decision ----------------------------------------
    (
        NOTICING,
        "the rung is ignored, so the bottom rung says everything",
        "        allowed, _ = anticipation.may(one.domain, guesses,\n"
        "                                      at_least=anticipation.MENTION, now=now)",
        "        allowed = True",
        ("test_at_the_bottom_rung_everything_is_recorded_and_nothing_is_said",
         "test_a_domain_that_has_earned_nothing_stays_quiet_while_another_speaks"),
    ),
    (
        NOTICING,
        "nothing is ever said, whatever the rung",
        "        if not allowed:\n            quiet.append(one)",
        "        if True:\n            quiet.append(one)",
        ("test_once_the_rung_allows_it_the_same_noticing_is_said",),
    ),
    (
        NOTICING,
        "the rung is read globally rather than per domain",
        "        allowed, _ = anticipation.may(one.domain, guesses,",
        '        allowed, _ = anticipation.may("commitments", guesses,',
        ("test_a_domain_that_has_earned_nothing_stays_quiet_while_another_speaks",),
    ),
    (
        NOTICING,
        "what is not said is dropped rather than recorded",
        "        else:\n            say.append(one)\n    return say, quiet",
        "        else:\n            say.append(one)\n    return say, []",
        ("test_everything_noticed_is_recorded_even_when_nothing_is_said",
         "test_at_the_bottom_rung_everything_is_recorded_and_nothing_is_said"),
    ),
    (
        NOTICING,
        "there is no cap, so forty doors are held at once",
        "        elif len(say) >= most:",
        "        elif False:",
        ("test_holding_forty_doors_is_not_helpfulness",),
    ),
    (
        NOTICING,
        "the cap is raised until it does nothing",
        "MOST_PER_SWEEP = 3",
        "MOST_PER_SWEEP = 100",
        ("test_holding_forty_doors_is_not_helpfulness",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        NOTICING,
        "the cap applies to noticing as well, so the record is capped too",
        "def notice(*, commitments=(), requests=(), now: datetime | None = None\n"
        "           ) -> list[Prompting]:",
        "def notice(*, commitments=(), requests=(), now: datetime | None = None,\n"
        "           _cap=MOST_PER_SWEEP) -> list[Prompting]:",
        (),  # recorded: the mutation alone changes nothing without also
             # truncating the return, and a two-part mutation is a rewrite
             # rather than a probe. The cap's absence from `notice` is asserted
             # directly by `test_the_cap_is_on_what_is_said_and_never_on_what_is_noticed`.
    ),
    # --- not now means not now ------------------------------------------------
    (
        NOTICING,
        "a recent not-now is ignored and the same ground is raised again",
        "        elif recently_declined(one.domain, guesses, now=now):",
        "        elif False:",
        ("test_a_recent_not_now_holds_the_same_ground_back",),
    ),
    (
        NOTICING,
        "a not-now silences that ground for ever",
        "        if guess.settled_at and (when - guess.settled_at) <= timedelta(\n"
        "                days=QUIET_DAYS):",
        "        if guess.settled_at:",
        ("test_the_quiet_period_ends",),
    ),
    (
        NOTICING,
        "being right also buys quiet, so success stops the noticing",
        "        if guess.domain != domain or guess.outcome != anticipation.NOT_NOW:",
        "        if guess.domain != domain:",
        ("test_a_wanted_guess_does_not_hold_anything_back",),
    ),
    (
        NOTICING,
        "a not-now in one area silences every other",
        "        if guess.domain != domain or guess.outcome != anticipation.NOT_NOW:",
        "        if guess.outcome != anticipation.NOT_NOW:",
        ("test_a_not_now_in_one_area_does_not_silence_another",),
    ),
    (
        NOTICING,
        "the quiet period is a day, which is not a rest",
        "QUIET_DAYS = 7",
        "QUIET_DAYS = 0",
        ("test_a_recent_not_now_holds_the_same_ground_back",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    # --- the sweep that runs it -----------------------------------------------
    (
        UPKEEP,
        "nothing ever notices anything",
        "        if noticing_due(client, agent=agent):",
        "        if False:",
        ("test_the_sweep_notices_a_promise_coming_due",),
    ),
    (
        UPKEEP,
        "only what is said gets recorded, so the ladder can never move",
        "            for one in found:\n"
        "                trustbook.record(client, one.as_guess(),\n"
        "                                 to_say=(one.domain, one.what) in spoken,\n"
        "                                 agent=agent)",
        "            for one in say:\n"
        "                trustbook.record(client, one.as_guess(),\n"
        "                                 to_say=(one.domain, one.what) in spoken,\n"
        "                                 agent=agent)",
        ("test_a_new_domain_records_and_says_nothing",
         "test_the_sweep_notices_a_promise_coming_due"),
    ),
    (
        UPKEEP,
        "the rung is ignored and everything noticed is said",
        "            say, quiet = noticing.worth_saying(found, known)",
        "            say, quiet = found, []",
        ("test_a_new_domain_records_and_says_nothing",),
    ),
    (
        UPKEEP,
        "the sweep never records that it ran, so it notices every time",
        "            persistence.put(client, persistence.SELF_ASSESSMENT, _LAST_NOTICING,",
        "            _ = (client, persistence.SELF_ASSESSMENT, _LAST_NOTICING,",
        ("test_noticing_is_not_repeated_every_sweep",),
    ),
    (
        UPKEEP,
        "noticing runs as often as the log scan",
        "NOTICE_EVERY_HOURS = 4",
        "NOTICE_EVERY_HOURS = 6",
        ("test_the_noticing_cadence_is_what_it_is",),
    ),
    (
        UPKEEP,
        "a broken trust record takes the whole sweep down",
        "    except (dbaclient.Unavailable, dbaclient.Refused, OSError, ValueError) as exc:\n"
        '        result["problems"].append(f"noticing: {exc}")',
        "    except dbaclient.Refused as exc:\n"
        '        result["problems"].append(f"noticing: {exc}")',
        ("test_a_broken_trust_record_does_not_stop_the_rest_of_the_sweep",),
    ),
    (
        UPKEEP,
        "problems loading the record are swallowed",
        '            result["problems"].extend(problems)',
        "            pass",
        (),  # recorded: `trustbook.load` reports a problem only for a verdict
             # with no guess, which needs the operator console to create - and
             # `tests/test_trustbook.py` covers that path directly.
    ),
    (
        NOTICING,
        "`describe` claims it records everything when it does not",
        '        "records_everything_it_notices": True,',
        '        "records_everything_it_notices": False,',
        ("test_describe_says_it_records_more_than_it_says",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
