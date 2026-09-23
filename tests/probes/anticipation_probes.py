"""Mutations that `tests/test_anticipation.py` must notice.

A trust ladder fails quietly in both directions. Too generous and Jarvis acts
alone on a record that never earned it; too mean and he never climbs, and the
whole thing is decoration. The single worst failure is silent: a record that
grades itself reads a hundred per cent for ever and looks like excellent work.

Run it directly:

    python tests/probes/anticipation_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

ANTICIPATION = "gateway/anticipation.py"
READBACK = "gateway/readback.py"
SUITES = {ANTICIPATION: TESTS / "test_anticipation.py",
          READBACK: TESTS / "test_anticipation.py"}

PROBES: list[harness.Probe] = [
    # --- nothing grades itself ------------------------------------------------
    (
        ANTICIPATION,
        "Jarvis can score his own guess",
        '    if by.strip().lower() == (agent or "").strip().lower():\n'
        "        raise NotYet(\n"
        '            f"{agent!r} cannot score its own guess. A prediction graded by the "',
        "    if False:\n"
        "        raise NotYet(\n"
        '            f"{agent!r} cannot score its own guess. A prediction graded by the "',
        ("test_jarvis_cannot_score_his_own_guess",
         "test_the_check_is_not_fooled_by_case_or_spacing"),
    ),
    (
        ANTICIPATION,
        "the self-scoring check is fooled by case and spacing",
        '    if by.strip().lower() == (agent or "").strip().lower():\n'
        "        raise NotYet(\n"
        '            f"{agent!r} cannot score its own guess.',
        "    if by == agent:\n"
        "        raise NotYet(\n"
        '            f"{agent!r} cannot score its own guess.',
        ("test_the_check_is_not_fooled_by_case_or_spacing",),
    ),
    (
        ANTICIPATION,
        "a score need not say who gave it",
        '    if not (by or "").strip():\n'
        '        raise NotYet("a settled guess must say who settled it")',
        '    if False:\n'
        '        raise NotYet("a settled guess must say who settled it")',
        ("test_a_settled_guess_must_say_who_settled_it",),
    ),
    # --- a guess must precede its outcome -------------------------------------
    (
        ANTICIPATION,
        "a guess can be recorded after the fact, which scores perfectly",
        "    if when < guess.made_at:",
        "    if False:",
        ("test_a_guess_cannot_be_settled_before_it_was_made",),
    ),
    (
        ANTICIPATION,
        "a bad week can be tidied up by rescoring",
        "    if guess.settled:\n        raise NotYet(",
        "    if False:\n        raise NotYet(",
        ("test_a_settled_guess_cannot_be_rescored",),
    ),
    (
        ANTICIPATION,
        "a guess needs no stated trigger",
        '            if not (value or "").strip():',
        "            if False:",
        ("test_a_guess_needs_a_reason_it_was_made",
         "test_a_guess_needs_a_domain_and_a_subject"),
    ),
    (
        ANTICIPATION,
        "outcomes are open",
        "    if outcome not in OUTCOMES:",
        "    if False:",
        ("test_outcomes_are_a_closed_set",),
    ),
    # --- three outcomes, not two ----------------------------------------------
    (
        ANTICIPATION,
        "right at the wrong moment is counted as simply wrong",
        "    wrong = sum(1 for guess in settled if guess.outcome == WRONG) + len(overdue)",
        "    wrong = sum(1 for guess in settled\n"
        "                if guess.outcome in (WRONG, NOT_NOW)) + len(overdue)",
        ("test_right_at_the_wrong_moment_is_not_the_same_as_wrong",),
    ),
    (
        ANTICIPATION,
        "a badly timed guess costs nothing, so the ladder climbs anyway",
        "    if not_now:\n        return MENTION, (",
        "    if False:\n        return MENTION, (",
        ("test_a_right_but_ill_timed_guess_holds_the_ladder_at_mention",),
    ),
    # --- a passed deadline is an answer ---------------------------------------
    (
        ANTICIPATION,
        "guesses nobody answered are simply not counted",
        "    overdue = [guess for guess in guesses\n"
        "               if guess.domain == domain and guess.overdue(now=now)]",
        "    overdue = []",
        ("test_an_unanswered_deadline_counts_against_the_record",),
    ),
    (
        ANTICIPATION,
        "a guess goes overdue before its deadline",
        "        return (now or _now()) > self.by_when",
        "        return True",
        ("test_a_guess_still_within_its_deadline_counts_neither_way",
         "test_the_rungs_are_climbed_one_run_at_a_time"),
    ),
    (
        ANTICIPATION,
        "a guess with no deadline is treated as overdue",
        "        if self.settled or self.by_when is None:\n            return False",
        "        if self.settled:\n            return False",
        ("test_a_guess_with_no_deadline_never_goes_overdue",),
    ),
    # --- outcome and quality are two moments ----------------------------------
    (
        ANTICIPATION,
        "the quality is taken when Krish says yes, before the work is done",
        "def settle(guess: Guess, *, outcome: str, by: str, agent: str,\n"
        "           now: datetime | None = None) -> Guess:",
        "def settle(guess: Guess, *, outcome: str, by: str, agent: str,\n"
        "           quality: str | None = None, now: datetime | None = None) -> Guess:",
        ("test_the_ladder_could_not_climb_before_these_were_separated",),
    ),
    (
        ANTICIPATION,
        "Jarvis can rate his own work",
        '    if by.strip().lower() == (agent or "").strip().lower():\n'
        "        raise NotYet(\n"
        '            f"{agent!r} cannot rate its own work.',
        "    if False:\n"
        "        raise NotYet(\n"
        '            f"{agent!r} cannot rate its own work.',
        ("test_jarvis_cannot_rate_his_own_work",),
    ),
    (
        ANTICIPATION,
        "a rating need not say who gave it",
        '    if not (by or "").strip():\n        raise NotYet("a rating must say who gave it")',
        "    if False:\n        raise NotYet(\"a rating must say who gave it\")",
        ("test_a_rating_must_say_who_gave_it",),
    ),
    (
        ANTICIPATION,
        "work can be rated before Krish has said he wanted it",
        "    if not guess.settled:\n        raise NotYet(",
        "    if False:\n        raise NotYet(",
        ("test_a_guess_cannot_be_rated_before_krish_has_said_he_wanted_it",),
    ),
    (
        ANTICIPATION,
        "a bad Tuesday can be revised on Wednesday",
        "    if guess.rated:\n        raise NotYet(",
        "    if False:\n        raise NotYet(",
        ("test_work_cannot_be_rated_twice",),
    ),
    (
        ANTICIPATION,
        "qualities are open",
        "    if quality not in QUALITIES:",
        "    if False:",
        ("test_qualities_are_a_closed_set",),
    ),
    (
        ANTICIPATION,
        "the run is ordered by when the guess settled, not when work was judged",
        "                        key=lambda guess: guess.rated_at, reverse=True):",
        "                        key=lambda guess: guess.settled_at, reverse=True):",
        ("test_the_run_is_ordered_by_when_the_work_was_rated",),
    ),
    (
        READBACK,
        "a verdict lands on work that was already judged",
        "            if guess.domain == domain and guess.settled and not guess.rated:",
        "            if guess.domain == domain and guess.settled:",
        ("test_a_second_verdict_finds_nothing_rather_than_raising",),
    ),
    (
        READBACK,
        "praise for something nobody guessed at is recorded anyway",
        "        return False\n\n    def awaiting_a_verdict(self) -> list:",
        "        return True\n\n    def awaiting_a_verdict(self) -> list:",
        ("test_praise_for_something_nobody_guessed_at_is_not_a_record",),
    ),
    (
        READBACK,
        "unsettled guesses are offered up for a verdict",
        "        return [guess for guess in self.guesses\n"
        "                if guess.settled and not guess.rated]",
        "        return list(self.guesses)",
        ("test_an_unsettled_guess_is_not_waiting_for_a_verdict",),
    ),
    # --- the ladder, slow up --------------------------------------------------
    (
        ANTICIPATION,
        "a domain is judged on one guess",
        "    if settled < MIN_SETTLED:",
        "    if False:",
        ("test_a_domain_with_no_history_watches_and_says_nothing",
         "test_a_small_sample_says_nothing_whatever_its_hit_rate"),
    ),
    (
        ANTICIPATION,
        "the sample floor is one",
        "MIN_SETTLED = 5",
        "MIN_SETTLED = 1",
        ("test_the_policy_numbers_are_what_they_are",
         "test_a_small_sample_says_nothing_whatever_its_hit_rate"),
    ),
    (
        ANTICIPATION,
        "a bad hit rate climbs anyway",
        "    if accuracy < ACCURACY_TO_CLIMB:",
        "    if False:",
        ("test_guessing_badly_keeps_it_watching",),
    ),
    (
        ANTICIPATION,
        "the hit rate needed to climb is anything at all",
        "ACCURACY_TO_CLIMB = 0.8",
        "ACCURACY_TO_CLIMB = 0.0",
        ("test_the_policy_numbers_are_what_they_are",
         "test_guessing_badly_keeps_it_watching"),
    ),
    (
        ANTICIPATION,
        "every rung costs the same, so the free hand is as cheap as the first",
        "RUN_TO_CLIMB = {PREPARE: 3, ACT_AND_REPORT: 5, FULL_STOP: 10}",
        "RUN_TO_CLIMB = {PREPARE: 1, ACT_AND_REPORT: 1, FULL_STOP: 1}",
        ("test_the_policy_numbers_are_what_they_are",
         "test_the_rungs_are_climbed_one_run_at_a_time"),
    ),
    # --- and fast down --------------------------------------------------------
    (
        ANTICIPATION,
        "a botched execution does not break the run",
        "        if guess.quality == PERFECT:\n            run += 1\n        else:\n            break",
        "        if guess.quality == PERFECT:\n            run += 1\n        else:\n            continue",
        ("test_one_botched_execution_drops_the_rung_immediately",
         "test_a_long_good_history_does_not_dilute_a_recent_failure"),
    ),
    (
        ANTICIPATION,
        "merely flawed work counts as perfect",
        "        if guess.quality == PERFECT:",
        "        if guess.quality != FAILED:",
        ("test_merely_flawed_work_also_breaks_the_run",),
    ),
    (
        ANTICIPATION,
        "the run is read oldest first, so a recent failure is invisible",
        "                        key=lambda guess: guess.rated_at, reverse=True):",
        "                        key=lambda guess: guess.rated_at):",
        ("test_a_long_good_history_does_not_dilute_a_recent_failure",
         "test_one_botched_execution_drops_the_rung_immediately"),
    ),
    (
        ANTICIPATION,
        "the run is a rate, so volume washes a failure out",
        "    run = 0\n"
        "    for guess in sorted((guess for guess in settled if guess.rated),\n"
        "                        key=lambda guess: guess.rated_at, reverse=True):\n"
        "        if guess.quality == PERFECT:\n"
        "            run += 1\n"
        "        else:\n"
        "            break",
        "    scored = [guess for guess in settled if guess.rated]\n"
        "    run = sum(1 for guess in scored if guess.quality == PERFECT)",
        ("test_a_long_good_history_does_not_dilute_a_recent_failure",),
    ),
    # --- per domain -----------------------------------------------------------
    (
        ANTICIPATION,
        "the record is global, so one bad domain costs every other",
        "    settled = [guess for guess in guesses\n"
        "               if guess.domain == domain and guess.settled]",
        "    settled = [guess for guess in guesses if guess.settled]",
        ("test_a_free_hand_in_one_domain_is_not_a_free_hand_in_another",),
    ),
    (
        ANTICIPATION,
        "`may` allows a rung the record has not earned",
        "    allowed = RUNGS.index(earned.rung) >= RUNGS.index(at_least)",
        "    allowed = True",
        ("test_may_answers_for_one_domain_and_says_why",),
    ),
    (
        ANTICIPATION,
        "`may` accepts a rung nobody declared",
        "    if at_least not in RUNGS:",
        "    if False:",
        ("test_may_refuses_a_rung_nobody_declared",),
    ),
    (
        ANTICIPATION,
        "the refusal names the last gate checked rather than the missing one",
        "    for rung in (PREPARE, ACT_AND_REPORT, FULL_STOP):\n"
        "        if run < RUN_TO_CLIMB[rung]:\n"
        "            below = RUNGS[RUNGS.index(rung) - 1]",
        "    for rung in (FULL_STOP, ACT_AND_REPORT, PREPARE):\n"
        "        if run < RUN_TO_CLIMB[rung]:\n"
        "            below = RUNGS[RUNGS.index(rung) - 1]",
        ("test_the_rungs_are_climbed_one_run_at_a_time",
         "test_prepare_is_where_a_domain_sits_while_it_is_recovering"),
    ),
    # --- where the guesses come from ------------------------------------------
    (
        READBACK,
        "a read-back Krish asked for is counted as a guess Jarvis made",
        "        if not prompted:",
        "        if True:",
        ("test_a_read_back_for_something_krish_asked_for_is_not_a_guess",),
    ),
    (
        READBACK,
        "nothing is ever recorded as a guess",
        "            self.guesses.append(anticipation.Guess(",
        "            [].append(anticipation.Guess(",
        ("test_an_unprompted_offer_is_recorded_as_a_guess",
         "test_krish_saying_yes_is_the_grade"),
    ),
    (
        READBACK,
        "an unprompted offer needs no trigger",
        '            if not (because or "").strip():',
        "            if False:",
        ("test_an_unprompted_offer_must_say_what_prompted_it",),
    ),
    (
        READBACK,
        "Krish's yes does not reach the guess",
        "        self._settle_guess(held.understanding.action.name, "
        "outcome=anticipation.WANTED,\n"
        "                           by=confirmed_by)",
        "        pass",
        ("test_krish_saying_yes_is_the_grade",),
    ),
    (
        READBACK,
        "silence is recorded as a wrong guess rather than a bad moment",
        "                anticipation.settle(guess, outcome=anticipation.NOT_NOW,",
        "                anticipation.settle(guess, outcome=anticipation.WRONG,",
        ("test_silence_is_recorded_as_a_bad_moment_not_a_bad_guess",),
    ),
    (
        READBACK,
        "a guess is lapsed before its window is up",
        "            if guess.overdue(now=now):",
        "            if True:",
        ("test_a_guess_still_inside_its_window_is_left_alone",),
    ),
    (
        ANTICIPATION,
        "a settled guess is lapsed a second time",
        "        if self.settled or self.by_when is None:\n            return False",
        "        if self.by_when is None:\n            return False",
        ("test_an_answered_guess_is_not_lapsed_as_well",),
    ),
    (
        READBACK,
        "the record is owned by the register, so it resets with the conversation",
        "        self.guesses: list = guesses if guesses is not None else []",
        "        self.guesses: list = []",
        ("test_the_record_outlives_any_one_register",),
    ),
    (
        ANTICIPATION,
        "`describe` claims the record does not grade itself when it does",
        '        "grades_itself": False,',
        '        "grades_itself": True,',
        ("test_the_module_cannot_work_out_an_outcome_for_itself",),
    ),
    (
        ANTICIPATION,
        "a rung has no plain-words meaning",
        "    FULL_STOP: (\"does it and presents the result - the free hand, and the point \"\n"
        "                \"Krish called the full stop\"),",
        "    FULL_STOP: \"\",",
        ("test_every_rung_says_what_it_means_in_plain_words",
         "test_the_free_hand_is_the_top_of_the_ladder"),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
