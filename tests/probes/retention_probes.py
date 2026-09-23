"""Mutations that `tests/test_retention.py` must notice.

Krish, 2026-09-23: *"all deadweight unreferenced information should be eventually
garbage collected as well"* - and, in the same breath, the March Acme fact must
survive. A collector has two ways to be useless and they are opposites: collect
nothing, or collect the seasonal fact. Most of these probes push it one way or
the other and check that a test objects.

The module is pure, so every probe here runs in well under a second. That is the
argument for the decision/effect split stated as a cost: a policy that read a
clock or a store could not be mutated forty times in a few seconds, so it would
not be mutated at all.

Run it directly:

    python tests/probes/retention_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

RETENTION = "app/learning/retention.py"
SUITES = {RETENTION: TESTS / "test_retention.py"}

PROBES: list[harness.Probe] = [
    # --- the grace period -----------------------------------------------------
    (
        RETENTION,
        "there is no grace period, so a new fact can be collected",
        "    if bet.age_days < GRACE_DAYS:",
        "    if False:",
        ("test_nothing_is_collected_inside_the_grace_period",),
    ),
    (
        RETENTION,
        "the grace period never ends",
        "    if bet.age_days < GRACE_DAYS:",
        "    if True:",
        ("test_the_grace_period_ends", "test_deadweight_is_collected",
         "test_every_verdict_is_declared_and_explained"),
    ),
    # --- silence is only evidence when something asked ------------------------
    (
        RETENTION,
        "a fact nothing ever asked about is collected for its silence",
        "        if bet.times_offered < MIN_OFFERS_TO_JUDGE:",
        "        if False:",
        ("test_a_fact_nothing_ever_asked_about_is_not_collected",
         "test_being_passed_over_a_few_times_is_not_enough_to_judge"),
    ),
    (
        RETENTION,
        "one offer is enough to judge a fact by",
        "MIN_OFFERS_TO_JUDGE = 12",
        "MIN_OFFERS_TO_JUDGE = 1",
        ("test_being_passed_over_a_few_times_is_not_enough_to_judge",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        RETENTION,
        "a seasonal fact is collected before its season comes round",
        "        if bet.age_days <= bet.cycle():",
        "        if False:",
        ("test_a_seasonal_fact_is_not_collected_before_its_season_comes_round",),
    ),
    (
        RETENTION,
        "a fact passed over across a full cycle is kept anyway",
        "        return Verdict(DISCARD, f\"cost {bet.cost:g} to acquire, was a candidate \"",
        "        return Verdict(KEEP, f\"cost {bet.cost:g} to acquire, was a candidate \"",
        ("test_deadweight_is_collected",
         "test_once_a_full_cycle_has_passed_unchosen_it_goes",
         "test_the_two_are_told_apart_by_being_chosen_not_by_being_quiet"),
    ),
    # --- the cycle a fact is judged on ----------------------------------------
    (
        RETENTION,
        "an unstated cycle is read as no cycle at all",
        "        if stated is None or stated <= 0:\n            return DEFAULT_INTERVAL_DAYS",
        "        if stated is None:\n            return 0.0",
        ("test_an_unstated_cycle_is_conservative_rather_than_short",
         "test_the_march_acme_fact_survives_a_quiet_summer"),
    ),
    (
        RETENTION,
        "a nonsense cycle of zero is taken literally",
        "        if stated is None or stated <= 0:",
        "        if stated is None:",
        ("test_a_nonsense_cycle_falls_back_rather_than_collecting_instantly",),
    ),
    (
        RETENTION,
        "an unstated cycle defaults to something short",
        "DEFAULT_INTERVAL_DAYS = 365.0",
        "DEFAULT_INTERVAL_DAYS = 30.0",
        ("test_an_unstated_cycle_is_conservative_rather_than_short",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        RETENTION,
        "every fact is judged on the default cycle, not its own",
        "        return float(stated)",
        "        return DEFAULT_INTERVAL_DAYS",
        ("test_a_fact_with_a_short_cycle_is_judged_on_the_short_one",),
    ),
    (
        RETENTION,
        "one missed cycle is enough to call a fact cold",
        "CYCLES_BEFORE_COLD = 2.25",
        "CYCLES_BEFORE_COLD = 0.5",
        ("test_a_yearly_fact_survives_a_quiet_summer_even_before_it_has_paid_off",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    # --- what a payoff buys ---------------------------------------------------
    (
        RETENTION,
        "paying off buys nothing",
        "        if self.times_paid_off:\n            cold *= EARNED_MULTIPLE",
        "        if False:\n            cold *= EARNED_MULTIPLE",
        ("test_paying_off_buys_a_longer_clock_but_not_an_infinite_one",),
    ),
    (
        RETENTION,
        "paying off buys an infinite clock",
        "    if bet.times_paid_off:\n        return Verdict(DISCARD, f\"paid off",
        "    if False:\n        return Verdict(DISCARD, f\"paid off",
        ("test_paying_off_buys_a_longer_clock_but_not_an_infinite_one",
         "test_every_verdict_is_declared_and_explained"),
    ),
    # --- probation ------------------------------------------------------------
    (
        RETENTION,
        "a fact that was used and never useful is collected without demotion",
        "    return Verdict(PROBATION, f\"referenced {bet.times_referenced} time(s) and never \"",
        "    return Verdict(DISCARD, f\"referenced {bet.times_referenced} time(s) and never \"",
        ("test_a_fact_used_and_never_once_useful_stops_being_offered_first",
         "test_every_verdict_is_declared_and_explained"),
    ),
    (
        RETENTION,
        "probation never ends, so a failed fact lives for ever",
        "    if quiet > PROBATION_MULTIPLE * cold_after:",
        "    if False:",
        ("test_probation_ends_in_collection",),
    ),
    # --- the clock a never-referenced fact is on ------------------------------
    (
        RETENTION,
        "a fact never referenced is treated as referenced today",
        "        if self.days_since_reference is None:\n            return self.age_days",
        "        if self.days_since_reference is None:\n            return 0.0",
        ("test_never_referenced_is_not_the_same_as_referenced_today",),
    ),
    (
        RETENTION,
        "a fact used recently is judged on its whole age",
        "        return float(self.days_since_reference)",
        "        return self.age_days",
        ("test_never_referenced_is_not_the_same_as_referenced_today",),
    ),
    # --- the verdict is explained --------------------------------------------
    (
        RETENTION,
        "a verdict carries no numbers to argue with",
        '    detail = {"quiet_days": round(quiet, 1),\n'
        '              "cold_after_days": round(cold_after, 1)}',
        '    detail = {}',
        ("test_a_verdict_carries_the_numbers_it_was_made_from",),
    ),
    (
        RETENTION,
        "a bet can be edited into a different fate",
        "@dataclass(frozen=True)\nclass Bet:",
        "@dataclass\nclass Bet:",
        ("test_a_bet_cannot_be_edited_into_a_different_fate",),
    ),
    # --- learning which kinds are worth the cost ------------------------------
    (
        RETENTION,
        "a kind nobody has tried is judged anyway",
        "        if self.recorded < MIN_SAMPLE_FOR_KIND:\n            return None\n"
        "        return self.paid_off / self.recorded",
        "        return self.paid_off / max(1, self.recorded)",
        ("test_a_kind_nobody_has_tried_is_recorded", "test_a_small_sample_says_nothing"),
    ),
    (
        RETENTION,
        "a kind is discredited on a sample of one",
        "MIN_SAMPLE_FOR_KIND = 8",
        "MIN_SAMPLE_FOR_KIND = 1",
        ("test_a_small_sample_says_nothing",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        RETENTION,
        "an unknown kind fails closed instead of open",
        "    if rate is None:\n        return True, (",
        "    if rate is None:\n        return False, (",
        ("test_a_kind_nobody_has_tried_is_recorded", "test_a_small_sample_says_nothing"),
    ),
    (
        RETENTION,
        "a kind that has paid off is stopped anyway",
        "    if rate > 0:\n        return True, (",
        "    if rate > 0:\n        return False, (",
        ("test_one_payoff_is_enough_to_keep_recording_a_kind",),
    ),
    (
        RETENTION,
        "a kind that never pays off is recorded regardless",
        "    return False, (f\"none of {history.recorded} of this kind ever paid off and \"",
        "    return True, (f\"none of {history.recorded} of this kind ever paid off and \"",
        ("test_a_kind_that_never_once_paid_off_stops_being_recorded",),
    ),
    (
        RETENTION,
        "a discredited kind is closed for ever, with no way back",
        "    if history.recorded % REPRIEVE_EVERY == 0:",
        "    if False:",
        ("test_a_discredited_kind_keeps_a_door_ajar",),
    ),
    (
        RETENTION,
        "the reprieve fires so often the policy does nothing",
        "REPRIEVE_EVERY = 10",
        "REPRIEVE_EVERY = 1",
        ("test_a_discredited_kind_keeps_a_door_ajar",
         "test_a_kind_that_never_once_paid_off_stops_being_recorded",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        RETENTION,
        "the reference rate is the payoff rate under another name",
        "        return self.referenced / self.recorded",
        "        return self.paid_off / self.recorded",
        ("test_the_payoff_rate_is_a_fraction_of_what_was_recorded",),
    ),
    # --- the decision/effect split -------------------------------------------
    (
        RETENTION,
        "the policy reads the clock itself, so no test can choose the date",
        "from dataclasses import dataclass",
        "from dataclasses import dataclass\nfrom datetime import datetime",
        ("test_retention_cannot_touch_a_store_a_clock_or_a_network",),
    ),
    (
        RETENTION,
        "the earned multiple is raised so a paid-off fact is never collected",
        "EARNED_MULTIPLE = 2.0",
        "EARNED_MULTIPLE = 1000.0",
        ("test_paying_off_buys_a_longer_clock_but_not_an_infinite_one",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        RETENTION,
        "the grace period is stretched to cover most facts",
        "GRACE_DAYS = 30.0",
        "GRACE_DAYS = 3000.0",
        ("test_the_grace_period_ends", "test_deadweight_is_collected",
         "test_the_policy_numbers_are_what_they_are"),
    ),
    (
        RETENTION,
        "`describe` reports a constant the code does not use",
        '        "grace_days": GRACE_DAYS,',
        '        "grace_days": 90.0,',
        ("test_describe_reports_the_constants_the_code_uses",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
