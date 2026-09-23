"""What is worth remembering, and what gets collected.

Krish, 2026-09-23, answering whether *"the March invoice from Acme always
arrives late"* is a lesson or a context:

> *"It's a fact that Claude may choose to remember and this cost may or may not
> be rewarded by a cost saving use in the future - that's how Jarvis learns how
> to guess correctly what to remember and what to discard - all deadweight
> unreferenced information should be eventually garbage collected as well"*

Two things have to be true at once and they pull against each other: deadweight
gets collected, and the March Acme fact - relevant one week a year - survives.
The test named after it is the one that matters; the first version of
`app/learning/retention.py` passed it and collected nothing else, which is the
same as having no collector.

Probed by `tests/probes/retention_probes.py`, to his rule that a test passing on
its first run has proved nothing.
"""

import ast
from pathlib import Path

import pytest

from app.learning import retention
from app.learning.retention import (
    DEFAULT_INTERVAL_DAYS, DISCARD, EARNED_MULTIPLE, GRACE_DAYS, KEEP,
    MIN_OFFERS_TO_JUDGE, MIN_SAMPLE_FOR_KIND, PROBATION, PROBATION_MULTIPLE,
    REPRIEVE_EVERY, VERDICTS, Bet, KindHistory, verdict, worth_recording)


def acme() -> Bet:
    """*"The March invoice from Acme always arrives late."*

    Learned two years ago, used each March, and silent for the eight months
    since. Every naive collector deletes this in June."""
    return Bet(kind="owner_fact", cost=3.0, age_days=760,
               times_referenced=2, times_offered=44,
               days_since_reference=240, times_paid_off=2,
               expected_interval_days=365)


def deadweight() -> Bet:
    """Twelve model calls spent, a candidate two hundred times across more than
    a year, never once chosen. This is what he asked to have collected."""
    return Bet(kind="source_value", cost=12.0, age_days=500, times_offered=200)


# --- the two cases the whole module exists to tell apart -----------------------

def test_the_march_acme_fact_survives_a_quiet_summer():
    decided = verdict(acme())
    assert decided.outcome == KEEP
    assert "365-day cycle" in decided.because


def test_a_yearly_fact_survives_a_quiet_summer_even_before_it_has_paid_off():
    """The same shape as Acme without the payoff bonus carrying it.

    Acme alone did not hold the line: it has paid off, which doubles its cold
    period, so halving the cycles-before-cold left it comfortably inside. This
    is the case that fails the moment one missed cycle counts as cold - which is
    every June, for a fact whose season is March."""
    yearly = Bet(kind="owner_fact", cost=3.0, age_days=400, times_referenced=1,
                 times_offered=40, days_since_reference=240,
                 expected_interval_days=365)
    assert verdict(yearly).outcome == KEEP


def test_deadweight_is_collected():
    decided = verdict(deadweight())
    assert decided.outcome == DISCARD
    assert "never once chosen" in decided.because


def test_the_two_are_told_apart_by_being_chosen_not_by_being_quiet():
    """Both are old, both have been quiet, both have a yearly cycle. The only
    difference the module is allowed to use is whether anything ever took them."""
    kept, collected = acme(), deadweight()
    assert kept.quiet_days() >= 200 and collected.quiet_days() >= 200
    assert kept.cycle() == collected.cycle() == DEFAULT_INTERVAL_DAYS
    assert verdict(kept).outcome != verdict(collected).outcome


# --- the grace period ----------------------------------------------------------

def test_nothing_is_collected_inside_the_grace_period():
    """A fact acquired last week has not failed to be useful; it has not had the
    chance. Offers do not shorten this, or a busy week would collect it."""
    young = Bet(kind="source_value", cost=9.0, age_days=GRACE_DAYS - 1,
                times_offered=500, expected_interval_days=1)
    decided = verdict(young)
    assert decided.outcome == KEEP
    assert "grace period" in decided.because


def test_the_grace_period_ends():
    older = Bet(kind="source_value", cost=9.0, age_days=GRACE_DAYS + 1,
                times_offered=500, expected_interval_days=1)
    assert verdict(older).outcome == DISCARD


# --- silence is only evidence when something asked ----------------------------

def test_a_fact_nothing_ever_asked_about_is_not_collected():
    """Its silence is evidence about the thing that never asked. Collecting it
    would destroy the only record of a question nobody puts."""
    unasked = Bet(kind="technique", cost=12.0, age_days=5000, times_offered=0)
    decided = verdict(unasked)
    assert decided.outcome == KEEP
    assert "not about this" in decided.because


def test_being_passed_over_a_few_times_is_not_enough_to_judge():
    """Stated in whole numbers rather than in terms of the constant.

    The first version of this test used `MIN_OFFERS_TO_JUDGE - 1` and
    `MIN_OFFERS_TO_JUDGE`, so it passed at *any* value of the constant -
    including 1, which would collect a fact the first time it was not chosen.
    A test written in terms of a policy number cannot detect a wrong policy
    number. `tests/probes/retention_probes.py` found this by setting it to 1."""
    three = Bet(kind="technique", cost=12.0, age_days=5000, times_offered=3)
    assert verdict(three).outcome == KEEP
    forty = Bet(kind="technique", cost=12.0, age_days=5000, times_offered=40)
    assert verdict(forty).outcome == DISCARD


def test_a_seasonal_fact_is_not_collected_before_its_season_comes_round():
    """Acquired in April, never yet used, offered at every monthly planning read.
    Collecting it in October is how the yearly fact is re-learned every year."""
    april = Bet(kind="owner_fact", cost=3.0, age_days=200, times_offered=20,
                expected_interval_days=365)
    decided = verdict(april)
    assert decided.outcome == KEEP
    assert "season may simply not have come round" in decided.because


def test_once_a_full_cycle_has_passed_unchosen_it_goes():
    past = Bet(kind="owner_fact", cost=3.0, age_days=366, times_offered=20,
               expected_interval_days=365)
    assert verdict(past).outcome == DISCARD


# --- the cycle a fact is judged on --------------------------------------------

def test_an_unstated_cycle_is_conservative_rather_than_short():
    """The expensive mistake is collecting a seasonal fact; the cheap one is
    keeping a dead fact slightly too long.

    The consequence is asserted at a whole number of days, not against the
    constant: a fact with no stated cycle, passed over forty times in its first
    two hundred days, is still inside *some* plausible season and is kept. A
    short default would collect it, and a test comparing the constant to itself
    would not notice."""
    assert Bet(kind="k").cycle() == DEFAULT_INTERVAL_DAYS
    assert Bet(kind="k", expected_interval_days=None).cycle() == DEFAULT_INTERVAL_DAYS
    unstated = Bet(kind="k", cost=4.0, age_days=200, times_offered=40)
    assert verdict(unstated).outcome == KEEP


@pytest.mark.parametrize("stated", [0, 0.0, -1, -365])
def test_a_nonsense_cycle_falls_back_rather_than_collecting_instantly(stated):
    """A zero cycle read literally makes everything cold immediately, which is
    the one bug in here that would be silent and total."""
    assert Bet(kind="k", expected_interval_days=stated).cycle() == \
        DEFAULT_INTERVAL_DAYS
    weekly = Bet(kind="k", cost=1.0, age_days=100, times_referenced=1,
                 times_offered=50, days_since_reference=90,
                 expected_interval_days=stated)
    assert verdict(weekly).outcome == KEEP


def test_a_fact_with_a_short_cycle_is_judged_on_the_short_one():
    """A fact about a daily standup that has not been wanted in a year is dead,
    and should not inherit a yearly fact's protection."""
    daily = Bet(kind="cost", cost=1.0, age_days=500, times_referenced=3,
                times_offered=400, days_since_reference=400, times_paid_off=1,
                expected_interval_days=1)
    assert verdict(daily).outcome == DISCARD


# --- what a payoff buys --------------------------------------------------------

def test_paying_off_buys_a_longer_clock_but_not_an_infinite_one():
    earned = Bet(kind="owner_fact", cost=3.0, age_days=3000,
                 times_referenced=2, times_offered=44,
                 days_since_reference=240, times_paid_off=2,
                 expected_interval_days=365)
    unearned = Bet(kind="owner_fact", cost=3.0, age_days=3000,
                   times_referenced=2, times_offered=44,
                   days_since_reference=240, expected_interval_days=365)
    assert earned.cold_after_days() == unearned.cold_after_days() * EARNED_MULTIPLE
    assert verdict(earned).outcome == KEEP

    ancient = Bet(kind="owner_fact", cost=3.0, age_days=6000,
                  times_referenced=2, times_offered=44,
                  days_since_reference=5000, times_paid_off=2,
                  expected_interval_days=365)
    decided = verdict(ancient)
    assert decided.outcome == DISCARD
    assert "history, not" in decided.because


# --- probation is a window, not a place to live --------------------------------

def test_a_fact_used_and_never_once_useful_stops_being_offered_first():
    """Demoting before collecting means a wrong call here costs a missed hint
    rather than the fact."""
    used = Bet(kind="cost", cost=2.0, age_days=900, times_referenced=5,
               times_offered=60, days_since_reference=850)
    decided = verdict(used)
    assert decided.outcome == PROBATION
    assert "before collecting it" in decided.because


def test_probation_ends_in_collection():
    """Otherwise a fact that fails every test lives for ever in a state nothing
    ever leaves, which is a leak wearing a policy's clothes."""
    stale = Bet(kind="cost", cost=2.0, age_days=4000, times_referenced=5,
                times_offered=60,
                days_since_reference=PROBATION_MULTIPLE * 2.25 * 365 + 1)
    decided = verdict(stale)
    assert decided.outcome == DISCARD
    assert "probation lasts" in decided.because


# --- the silence of a fact never referenced dates from its acquisition ---------

def test_never_referenced_is_not_the_same_as_referenced_today():
    """`days_since_reference=None` means never. Read as 0 it would make every
    unreferenced fact look fresh for ever, which is the more dangerous of the
    two mistakes and the reason the field is not an int."""
    never = Bet(kind="k", age_days=400, times_offered=99)
    assert never.days_since_reference is None
    assert never.quiet_days() == 400
    today = Bet(kind="k", age_days=400, times_offered=99, times_referenced=1,
                days_since_reference=0)
    assert today.quiet_days() == 0
    assert verdict(never).outcome != verdict(today).outcome


# --- properties of every verdict ----------------------------------------------

def test_every_verdict_is_declared_and_explained():
    cases = [acme(), deadweight(),
             Bet(kind="k", age_days=1),
             Bet(kind="k", age_days=5000, times_offered=0),
             Bet(kind="k", age_days=200, times_offered=50,
                 expected_interval_days=365),
             Bet(kind="k", age_days=900, times_referenced=5, times_offered=60,
                 days_since_reference=850),
             Bet(kind="k", age_days=6000, times_referenced=5, times_offered=60,
                 days_since_reference=5000, times_paid_off=1)]
    seen = set()
    for bet in cases:
        decided = verdict(bet)
        assert decided.outcome in VERDICTS
        assert len(decided.because) > 20, decided
        seen.add(decided.outcome)
    assert seen == set(VERDICTS), f"no case reaches {set(VERDICTS) - seen}"


def test_a_verdict_carries_the_numbers_it_was_made_from():
    """So a surprising verdict can be argued with rather than merely
    overridden."""
    decided = verdict(acme())
    assert decided.quiet_days == 240
    assert decided.cold_after_days == round(acme().cold_after_days(), 1)


def test_a_bet_cannot_be_edited_into_a_different_fate():
    with pytest.raises(Exception):
        acme().times_paid_off = 99


# --- learning which kinds are worth the cost ----------------------------------

def test_a_kind_nobody_has_tried_is_recorded():
    """"We have never tried" and "we tried and it never helped" are different
    findings, and only the second justifies stopping."""
    allowed, why = worth_recording(KindHistory(kind="new"))
    assert allowed is True
    assert "not knowing is not a reason to stop" in why


def test_a_small_sample_says_nothing():
    """Three facts of a kind, none of which ever helped, is not a finding about
    the kind. Written as three rather than as `MIN_SAMPLE_FOR_KIND - 1`, which
    would hold at a sample size of one."""
    small = KindHistory(kind="k", recorded=3, paid_off=0, cost_sunk=40)
    assert small.payoff_rate() is None
    assert small.reference_rate() is None
    assert worth_recording(small)[0] is True


def test_one_payoff_is_enough_to_keep_recording_a_kind():
    some = KindHistory(kind="k", recorded=100, referenced=3, paid_off=1)
    assert worth_recording(some)[0] is True


def test_a_kind_that_never_once_paid_off_stops_being_recorded():
    useless = KindHistory(kind="k", recorded=MIN_SAMPLE_FOR_KIND + 1,
                          referenced=4, paid_off=0, cost_sunk=90)
    allowed, why = worth_recording(useless)
    assert allowed is False
    assert "ever paid off" in why
    assert "next reprieve" in why


def test_a_discredited_kind_keeps_a_door_ajar():
    """A policy that closed a kind for ever could never find out the kind had
    become useful, and would be indistinguishable from a bug that lost those
    facts. The reprieve is counter-driven so a test can name which one gets
    through."""
    reprieved = [n for n in range(MIN_SAMPLE_FOR_KIND, MIN_SAMPLE_FOR_KIND + 60)
                 if worth_recording(KindHistory(kind="k", recorded=n,
                                                paid_off=0, cost_sunk=10))[0]]
    assert reprieved, "a discredited kind can never recover"
    assert all(n % REPRIEVE_EVERY == 0 for n in reprieved)
    assert len(reprieved) == 6


def test_the_payoff_rate_is_a_fraction_of_what_was_recorded():
    history = KindHistory(kind="k", recorded=20, referenced=10, paid_off=5)
    assert history.payoff_rate() == 0.25
    assert history.reference_rate() == 0.5


# --- the module decides, and does nothing ------------------------------------

def test_retention_cannot_touch_a_store_a_clock_or_a_network():
    """The repository's split: if it can be decided, decide it in tested code.

    Asserted over the parsed module rather than its text, because a docstring
    saying so is what this repository has been caught believing before. A clock
    is on the list for a reason - a policy that read `now()` itself could not be
    tested at a chosen date, and every rule here is about elapsed time."""
    tree = ast.parse(Path(retention.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "dataclasses"}, imported

    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for forbidden in ("open", "print", "input", "eval", "exec"):
        assert forbidden not in called


def test_the_policy_numbers_are_what_they_are():
    """Asserted as literals, on purpose.

    These are not implementation details that a refactor may move - they are the
    policy, and the difference between keeping the March Acme fact and
    re-learning it every year is in them. Comparing a constant to itself proves
    nothing, so the values are written out here with the reason each one has the
    value it does. Changing one should mean changing this test, deliberately."""
    # Nothing young is deadweight. A month is long enough to have been used once
    # by anything that was going to.
    assert GRACE_DAYS == 30.0
    # One missed season is an ordinary quiet year; two is a pattern.
    assert retention.CYCLES_BEFORE_COLD == 2.25
    # An unknown period is a reason to wait longer, not a licence to collect.
    assert DEFAULT_INTERVAL_DAYS == 365.0
    # A monthly planning read gives a yearly fact a full year of chances before
    # anything is concluded from its silence.
    assert MIN_OFFERS_TO_JUDGE == 12
    # A fact that earned its cost is not judged on the same clock as one that
    # never did - but it is judged eventually.
    assert EARNED_MULTIPLE == 2.0
    assert PROBATION_MULTIPLE == 2.0
    # §26's own floor: fewer is one anecdote with a percentage sign on it.
    assert MIN_SAMPLE_FOR_KIND == 8
    assert REPRIEVE_EVERY == 10
    # One in ten: a collector that never regrets anything is keeping everything,
    # and one regretting a third of its decisions pays re-acquisition costs to
    # save space nobody needed.
    assert retention.REGRET_RATE_TOO_HIGH == 0.1
    # Past three default cycles, learning a fact again is a new fact rather than
    # evidence that throwing the old one away was a mistake.
    assert retention.TOMBSTONE_HORIZON_DAYS == 3 * 365.0


def test_describe_reports_the_constants_the_code_uses():
    described = retention.describe()
    assert described["grace_days"] == GRACE_DAYS
    assert described["min_offers_to_judge"] == MIN_OFFERS_TO_JUDGE
    assert described["probation_multiple"] == PROBATION_MULTIPLE
    assert described["reprieve_every"] == REPRIEVE_EVERY
    assert described["verdicts"] == list(VERDICTS)
    assert described["regret_rate_too_high"] == retention.REGRET_RATE_TOO_HIGH
    assert described["numbers_are_ratified_not_tuned"] is True


# --- the numbers are thought, and then ratified --------------------------------

def test_an_untested_policy_says_so_rather_than_reporting_a_clean_record():
    """Krish, 2026-09-23: *"Deciding what to retain and what to forget shouldn't
    be a guessing game. It should be based on deep thought and then ratified by
    real life experiences."* Nothing collected yet means nothing ratified, and a
    100%-correct record from zero decisions is the guessing game wearing a
    number."""
    verdict = retention.ratification([])
    assert verdict.holding is True
    assert "not been tested" in verdict.because
    assert "reasoning, not evidence" in verdict.because
    assert verdict.regret_rate is None


def test_too_many_regrets_fails_the_policy_and_names_the_remedy():
    verdict = retention.ratification(
        [KindHistory(kind="k", discarded_unreferenced=10, regretted=3)])
    assert verdict.holding is False
    assert verdict.regret_rate == 0.3
    assert "too aggressive" in verdict.because
    assert "CYCLES_BEFORE_COLD" in verdict.because


def test_a_few_regrets_are_the_price_of_collecting_anything():
    """A collector that never regrets anything is keeping everything."""
    verdict = retention.ratification(
        [KindHistory(kind="k", discarded_unreferenced=100, regretted=5)])
    assert verdict.holding is True
    assert verdict.regret_rate == 0.05


def test_regrets_are_counted_across_every_kind():
    verdict = retention.ratification([
        KindHistory(kind="a", discarded_unreferenced=10, regretted=1),
        KindHistory(kind="b", discarded_unreferenced=10, regretted=1)])
    assert verdict.collections == 20 and verdict.regrets == 2


def test_the_policy_reports_its_own_failure_and_never_retunes_itself():
    """A collector that changed its own thresholds from its own regrets would be
    the one thing nobody could audit: the numbers would drift, each drift
    justified by the one before, and the reasoning written beside each constant
    would quietly stop being true.

    Asserted over the parsed module: nothing assigns to a module-level constant
    anywhere, so `ratification` cannot be the exception."""
    tree = ast.parse(Path(retention.__file__).read_text(encoding="utf-8"))
    policy = {"GRACE_DAYS", "CYCLES_BEFORE_COLD", "DEFAULT_INTERVAL_DAYS",
              "EARNED_MULTIPLE", "MIN_OFFERS_TO_JUDGE", "PROBATION_MULTIPLE",
              "MIN_SAMPLE_FOR_KIND", "REPRIEVE_EVERY", "REGRET_RATE_TOO_HIGH"}
    assigned_inside = {
        target.id
        for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        for statement in ast.walk(node) if isinstance(statement, ast.Assign)
        for target in statement.targets if isinstance(target, ast.Name)}
    assert not (assigned_inside & policy)
    assert "global" not in Path(retention.__file__).read_text(encoding="utf-8")
