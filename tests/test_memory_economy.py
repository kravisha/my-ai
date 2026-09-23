"""A remembered fact is a bet, and this is the loop that places and settles one.

Krish, 2026-09-23, asked whether *"the March invoice from Acme always arrives
late"* is a lesson or a context, and answered it himself:

> *"It's a fact that Claude may choose to remember and this cost may or may not
> be rewarded by a cost saving use in the future - that's how Jarvis learns how
> to guess correctly what to remember and what to discard - all deadweight
> unreferenced information should be eventually garbage collected as well"*

`tests/test_retention.py` covers the judgement, which is pure. This covers the
machinery around it, which is the half that can silently not happen:

- `advice_for` is the **only** thing that marks a lesson used. A copy of that
  loop that read lessons without marking them would make every fact it used look
  like deadweight, and the collector would delete exactly the lessons that were
  working.
- `engine.accept` is the **only** thing that credits a payoff.
- `upkeep.run_once` is the only thing that ever collects.

Each of those is one call site, and a missing call site is invisible - which is
why each has a test here rather than a comment saying it matters.

Probed by `tests/probes/memory_economy_probes.py`.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.learning import memory, retention, store


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "learning.db"))
    yield tmp_path


def a_lesson(kind=memory.SOURCE_VALUE, pattern="web_search", cost=5.0,
             interval=None):
    return store.record_lesson(kind=kind, pattern=pattern, lesson="something",
                               cost=cost, expected_interval_days=interval)


# --- placing the bet ----------------------------------------------------------

def test_recording_a_lesson_counts_it_against_its_kind():
    a_lesson(cost=5.0)
    history = store.kind_history(memory.SOURCE_VALUE)
    assert history["recorded"] == 1
    assert history["cost_sunk"] == 5.0
    assert history["referenced"] == 0 and history["paid_off"] == 0


def test_seeing_the_same_lesson_again_is_not_a_second_bet():
    """`recorded` is the denominator of every payoff rate here. Counting an
    upsert would make one lesson seen fifty times look like fifty bets, and a
    single unhelpful lesson would discredit its whole kind."""
    for _ in range(5):
        a_lesson(cost=2.0)
    history = store.kind_history(memory.SOURCE_VALUE)
    assert history["recorded"] == 1
    # The cost still accumulates: learning the same thing five times cost five
    # times as much, and that total is what makes never using it worth saying.
    assert history["cost_sunk"] == 10.0
    assert store.lessons()[0]["times_seen"] == 5
    assert store.lessons()[0]["cost"] == 10.0


def test_a_kind_nothing_has_recorded_reports_zeroes_not_nothing():
    """`retention.worth_recording` has to be able to say "nobody has tried
    this", and a missing row is that answer rather than an error."""
    history = store.kind_history("never_seen")
    assert history == {"kind": "never_seen", "recorded": 0, "referenced": 0,
                       "paid_off": 0, "discarded_unreferenced": 0,
                       "cost_sunk": 0.0}
    assert retention.worth_recording(retention.KindHistory(**history))[0] is True


def test_a_kind_that_never_pays_off_stops_being_recorded_by_the_producer():
    """The learning half, at the one place lessons are written."""
    for index in range(retention.MIN_SAMPLE_FOR_KIND + 1):
        a_lesson(pattern=f"source-{index}", cost=3.0)
    allowed, why = retention.worth_recording(
        retention.KindHistory(**store.kind_history(memory.SOURCE_VALUE)))
    assert allowed is False
    assert "ever paid off" in why


# --- settling it: advice_for is the measurement -------------------------------

def test_giving_advice_is_what_marks_a_lesson_used():
    lesson = a_lesson()
    assert store.lessons()[0]["times_referenced"] == 0

    said = memory.advice_for(None, episode_slug="ep1")
    assert said, "the lesson was not offered at all"
    row = store.lessons()[0]
    assert row["times_referenced"] == 1
    assert row["times_offered"] == 1
    assert row["last_referenced_at"]
    assert [ref["episode_slug"] for ref in store.lesson_references(lesson)] == ["ep1"]


def test_a_lesson_looked_at_and_not_used_is_offered_not_referenced():
    """The distinction the whole collector turns on. A lesson passed over is
    evidence against it; a lesson nothing ever looked at is not."""
    for index in range(5):
        a_lesson(pattern=f"source-{index}")
    memory.advice_for(None)

    rows = store.lessons(memory.SOURCE_VALUE)
    assert all(row["times_offered"] == 1 for row in rows)
    referenced = [row for row in rows if row["times_referenced"]]
    assert len(referenced) == 3, "advice_for hands over the top three"
    assert len(rows) == 5, "but it looked at all five"


def test_a_failure_pattern_below_the_trend_floor_is_offered_and_not_used():
    a_lesson(kind=memory.FAILURE_PATTERN, pattern="seen_once")
    assert memory.advice_for(None) == []
    row = store.lessons(memory.FAILURE_PATTERN)[0]
    assert row["times_offered"] == 1
    assert row["times_referenced"] == 0


def test_advice_given_without_a_slug_can_be_used_but_never_credited():
    """The honest consequence of not saying who the advice was for."""
    a_lesson()
    memory.advice_for(None)
    assert store.lessons()[0]["times_referenced"] == 1
    assert store.credit_episode("ep1") == []
    assert store.lessons()[0]["times_paid_off"] == 0


# --- settling it: a payoff --------------------------------------------------

def test_crediting_an_episode_pays_off_the_lessons_it_was_given():
    a_lesson()
    memory.advice_for(None, episode_slug="ep1")
    assert store.credit_episode("ep1")
    row = store.lessons()[0]
    assert row["times_paid_off"] == 1
    assert store.kind_history(memory.SOURCE_VALUE)["paid_off"] == 1


def test_crediting_twice_does_not_pay_twice():
    """Idempotent, because acceptance can be called again and a payoff rate that
    grows on repeat calls measures retries."""
    a_lesson()
    memory.advice_for(None, episode_slug="ep1")
    assert store.credit_episode("ep1")
    assert store.credit_episode("ep1") == []
    assert store.lessons()[0]["times_paid_off"] == 1


def test_a_kinds_payoff_count_is_lessons_not_uses():
    """One popular lesson must not make its whole kind look valuable."""
    a_lesson()
    for slug in ("ep1", "ep2", "ep3"):
        memory.advice_for(None, episode_slug=slug)
        store.credit_episode(slug)
    assert store.lessons()[0]["times_paid_off"] == 3
    history = store.kind_history(memory.SOURCE_VALUE)
    assert history["paid_off"] == 1, "one lesson of this kind has ever paid off"
    assert history["referenced"] == 1


# --- collecting -------------------------------------------------------------

def _years(count):
    return datetime.now(timezone.utc) + timedelta(days=365 * count)


def test_the_march_acme_fact_survives_the_sweep():
    """The case the whole design is bent around, run through the real store."""
    a_lesson(kind=memory.FAILURE_PATTERN, pattern="acme_march_invoice_late",
             cost=3.0, interval=365)
    memory.advice_for(None, episode_slug="march")
    store.record_lesson(kind=memory.FAILURE_PATTERN,
                        pattern="acme_march_invoice_late", lesson="again")
    memory.advice_for(None, episode_slug="march")
    store.credit_episode("march")

    report = memory.collect_garbage(now=_years(1.5))
    assert report["discarded"] == []
    assert [row["pattern"] for row in store.lessons()] == \
        ["acme_march_invoice_late"]


def test_deadweight_is_collected_by_the_sweep():
    lesson = a_lesson(cost=12.0)
    # Offered at every planning read for two years, never chosen: this lesson is
    # ranked below three others every single time.
    for index in range(3):
        a_lesson(pattern=f"better-{index}")
    for _ in range(retention.MIN_OFFERS_TO_JUDGE + 2):
        memory.advice_for(None)
    assert store.lessons(memory.SOURCE_VALUE)
    before = len(store.lessons())

    report = memory.collect_garbage(now=_years(2))
    assert lesson in [row["id"] for row in report["discarded"]]
    assert len(store.lessons()) < before


def test_what_a_collection_leaves_behind_is_the_lesson_about_the_kind():
    """The row goes - that is what was asked for - and the finding survives it."""
    a_lesson(cost=12.0)
    for index in range(3):
        a_lesson(pattern=f"better-{index}", cost=1.0)
    for _ in range(retention.MIN_OFFERS_TO_JUDGE + 2):
        memory.advice_for(None)
    memory.collect_garbage(now=_years(2))

    history = store.kind_history(memory.SOURCE_VALUE)
    assert history["discarded_unreferenced"] >= 1
    assert history["cost_sunk"] == 15.0
    assert history["recorded"] == 4, "what was bet on outlives what was kept"


def test_a_collected_lesson_takes_its_references_with_it():
    lesson = a_lesson()
    memory.advice_for(None, episode_slug="ep1")
    assert store.lesson_references(lesson)
    store.discard_lesson(lesson)
    assert store.lesson_references(lesson) == []


def test_a_dry_run_reports_and_deletes_nothing():
    """The first honest thing to do with a collector is watch it for a while."""
    a_lesson(cost=12.0)
    for index in range(3):
        a_lesson(pattern=f"better-{index}")
    for _ in range(retention.MIN_OFFERS_TO_JUDGE + 2):
        memory.advice_for(None)
    before = [row["id"] for row in store.lessons()]

    report = memory.collect_garbage(now=_years(2), dry_run=True)
    assert report["dry_run"] is True
    assert report["discarded"], "nothing was even reported"
    assert [row["id"] for row in store.lessons()] == before


def test_every_collection_says_why_in_words():
    a_lesson(cost=12.0)
    for index in range(3):
        a_lesson(pattern=f"better-{index}")
    for _ in range(retention.MIN_OFFERS_TO_JUDGE + 2):
        memory.advice_for(None)
    report = memory.collect_garbage(now=_years(2), dry_run=True)
    for entry in report["discarded"]:
        assert len(entry["because"]) > 20
        assert entry["pattern"] and entry["kind"]


# --- probation is a door that opens both ways --------------------------------

def test_a_lesson_on_probation_stops_being_offered():
    lesson = a_lesson(kind=memory.COST, pattern="attempts_per_case")
    assert memory.advice_for(None), "it should be offered while healthy"
    store.demote_lesson(lesson)
    assert memory.advice_for(None) == []
    assert store.lessons() == []
    assert store.lessons(include_demoted=True)


def test_a_demoted_lesson_is_restored_when_its_verdict_comes_back_to_keep():
    """Otherwise probation is a one-way door, and a lesson demoted during a
    quiet spell never recovers - which is a deletion with extra steps."""
    lesson = a_lesson(kind=memory.COST, pattern="attempts_per_case")
    store.demote_lesson(lesson)
    assert store.lessons() == []

    report = memory.collect_garbage(now=datetime.now(timezone.utc))
    assert [row["id"] for row in report["restored"]] == [lesson]
    assert [row["id"] for row in store.lessons()] == [lesson]


def test_a_demoted_lesson_is_still_in_the_report():
    """A report that hid it would disagree with the database."""
    lesson = a_lesson()
    store.demote_lesson(lesson)
    store.record_lesson(kind=memory.SOURCE_VALUE, pattern="other", lesson="x")
    reported = memory.meta_report()
    assert lesson in [row["id"] for row in reported["lessons"]]


# --- a clock problem must not become a deletion -------------------------------

def test_an_unparseable_timestamp_keeps_a_lesson_rather_than_collecting_it():
    """The direction of the failure is the whole point. A lesson that looks
    brand new survives; one that looks ancient is deleted, and a clock bug that
    deletes memory is the worst outcome available here."""
    lesson = a_lesson(cost=12.0)
    with store.connect() as db:
        db.execute("UPDATE lessons SET at = ? WHERE id = ?",
                   ("not a timestamp", lesson))
    for _ in range(retention.MIN_OFFERS_TO_JUDGE + 2):
        memory.advice_for(None)
    report = memory.collect_garbage(now=_years(5))
    assert report["discarded"] == []


def test_the_bet_a_row_becomes_is_derived_only_from_the_row():
    lesson = a_lesson(cost=7.0, interval=30)
    memory.advice_for(None, episode_slug="ep1")
    row = next(item for item in store.lessons() if item["id"] == lesson)
    bet = memory.as_bet(row, now=datetime.now(timezone.utc))
    assert bet.kind == memory.SOURCE_VALUE
    assert bet.cost == 7.0
    assert bet.expected_interval_days == 30
    assert bet.times_referenced == 1
    assert bet.times_offered == 1
    assert bet.days_since_reference is not None


def test_a_lesson_never_referenced_reports_no_reference_rather_than_a_recent_one():
    lesson = a_lesson()
    row = next(item for item in store.lessons() if item["id"] == lesson)
    assert memory.as_bet(row, now=datetime.now(timezone.utc)).days_since_reference \
        is None


# --- the one periodic caller -------------------------------------------------

def test_upkeep_is_what_ever_collects_anything():
    """Named here because a sweep nothing calls is the repository's commonest
    failure: a complete mechanism with no producer."""
    from gateway import upkeep
    assert upkeep.COLLECT_MEMORY_EVERY_HOURS == 24 * 7
    assert "collect_memory_every_hours" in upkeep.describe()
    assert upkeep.collection_is_dry() is False


def test_the_sweep_can_be_switched_to_reporting_only(monkeypatch):
    from gateway import upkeep
    monkeypatch.setenv(upkeep.COLLECTION_DRY_RUN_ENV, "1")
    assert upkeep.collection_is_dry() is True
    monkeypatch.setenv(upkeep.COLLECTION_DRY_RUN_ENV, "0")
    assert upkeep.collection_is_dry() is False


def test_the_producer_honours_the_refusal_to_record_a_worthless_kind(monkeypatch):
    """`learn_from_episode` asks before writing, and the answer changes what is
    in the database - not just what is returned."""
    episode_id = store.create_episode("slug-a", {"slug": "slug-a"}, "user")
    for name in ("one", "two"):
        store.record_attempt(episode_id, kind=store.KIND_DEVELOPMENT,
                             passed=True, case_name=name)

    monkeypatch.setattr(retention, "worth_recording",
                        lambda history: (False, "nothing of this kind ever paid off"))
    written = memory.learn_from_episode("slug-a")
    assert written == []
    assert store.lessons(include_demoted=True) == []

    monkeypatch.setattr(retention, "worth_recording", lambda history: (True, "ok"))
    assert memory.learn_from_episode("slug-a")
    assert store.lessons(include_demoted=True)


def test_a_withheld_lesson_is_logged_rather_than_silently_dropped(monkeypatch, caplog):
    """"We deliberately did not write this down" is exactly the thing that looks
    like a bug six months later."""
    episode_id = store.create_episode("slug-b", {"slug": "slug-b"}, "user")
    store.record_attempt(episode_id, kind=store.KIND_DEVELOPMENT,
                         passed=True, case_name="one")
    monkeypatch.setattr(retention, "worth_recording",
                        lambda history: (False, "never paid off"))
    with caplog.at_level("INFO", logger="app.learning.memory"):
        memory.learn_from_episode("slug-b")
    assert any("not recording" in record.message for record in caplog.records)


def test_both_settling_call_sites_exist_in_the_engine():
    """There are exactly two, and a deleted one is invisible.

    Asserted over the parsed engine rather than by running an episode to
    acceptance, which `tests/test_learning.py` already does at length. That makes
    this weaker than an end-to-end check and it is here anyway: this repository
    has already shipped an escape hatch with twenty-three passing tests that
    nothing proved was connected, and one AST assertion would have caught it."""
    import ast
    from pathlib import Path

    from app.learning import engine
    tree = ast.parse(Path(engine.__file__).read_text(encoding="utf-8"))
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}

    def calls(name, attribute):
        return any(isinstance(node.func, ast.Attribute)
                   and node.func.attr == attribute
                   for node in ast.walk(functions[name])
                   if isinstance(node, ast.Call))

    assert calls("accept", "credit_episode"), \
        "nothing credits a payoff, so every lesson looks like a bet that never paid"
    assert calls("plan", "advice_for")
    # And the slug goes with it, or the references can never be credited.
    advice = next(node for node in ast.walk(functions["plan"])
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "advice_for")
    assert "episode_slug" in [keyword.arg for keyword in advice.keywords]


# --- ratified by real life experience ----------------------------------------
#
# Krish, 2026-09-23: *"Deciding what to retain and what to forget shouldn't be a
# guessing game. It should be based on deep thought and then ratified by real life
# experiences."* The thought is the constants in `retention`. The ratification is
# here: a fact collected and then learned again is the only observable in the
# system that says a retention decision was wrong.


def _collectable(cost=12.0, pattern="never_chosen", interval=None):
    """One fact that will be collected, and three that will always outrank it."""
    doomed = store.record_lesson(kind=memory.SOURCE_VALUE, pattern=pattern,
                                 lesson="x", cost=cost,
                                 expected_interval_days=interval)
    for index in range(3):
        store.record_lesson(kind=memory.SOURCE_VALUE, pattern=f"better-{index}",
                            lesson="y", cost=1.0)
    for _ in range(retention.MIN_OFFERS_TO_JUDGE + 2):
        memory.advice_for(None)
    with store.connect() as db:
        db.execute("UPDATE lessons SET at = '2019-01-01T00:00:00+00:00'")
    return doomed


def test_collecting_a_fact_leaves_a_tombstone_of_what_it_was():
    _collectable(cost=12.0)
    memory.collect_garbage(now=datetime.now(timezone.utc))

    tombstones = store.regretted_patterns()
    assert [item["pattern"] for item in tombstones] == ["never_chosen"]
    assert tombstones[0]["cost_at_discard"] == 12.0
    assert tombstones[0]["quiet_days_at_discard"] > 365
    assert tombstones[0]["because"]


def test_learning_a_collected_fact_again_is_counted_as_a_regret():
    _collectable()
    memory.collect_garbage(now=datetime.now(timezone.utc))
    assert store.kind_history(memory.SOURCE_VALUE)["regretted"] == 0

    store.record_lesson(kind=memory.SOURCE_VALUE, pattern="never_chosen",
                        lesson="turns out we needed it", cost=12.0)
    assert store.kind_history(memory.SOURCE_VALUE)["regretted"] == 1
    assert store.regretted_patterns() == [], "the tombstone is spent"


def test_learning_it_again_teaches_the_fact_its_real_cycle():
    """The loop closing. The world has just said how long this fact's period is,
    and that beats whatever the default assumed."""
    _collectable()
    memory.collect_garbage(now=datetime.now(timezone.utc))
    quiet = store.regretted_patterns()[0]["quiet_days_at_discard"]

    back = store.record_lesson(kind=memory.SOURCE_VALUE, pattern="never_chosen",
                               lesson="needed after all", cost=12.0)
    row = next(item for item in store.lessons() if item["id"] == back)
    assert row["expected_interval_days"] >= quiet


def test_a_fact_wrongly_collected_once_is_not_collected_wrongly_twice():
    """The whole point of ratifying rather than guessing. Before the regret this
    fact had the default year and was collected at 380 days; after it, the cycle
    it actually demonstrated keeps it."""
    _collectable(pattern="acme_march")
    memory.collect_garbage(now=datetime.now(timezone.utc))
    assert store.lessons(memory.SOURCE_VALUE)

    back = store.record_lesson(kind=memory.SOURCE_VALUE, pattern="acme_march",
                               lesson="late again", cost=3.0)
    learned = next(item for item in store.lessons()
                   if item["id"] == back)["expected_interval_days"]
    assert learned > 365, "nothing was learned from the mistake"

    # Offer it repeatedly and let a year pass: the default would collect it here.
    for _ in range(retention.MIN_OFFERS_TO_JUDGE + 2):
        memory.advice_for(None)
    report = memory.collect_garbage(now=datetime.now(timezone.utc)
                                    + timedelta(days=380))
    assert "acme_march" not in [item["pattern"] for item in report["discarded"]]


def test_a_stated_cycle_is_never_lowered_by_what_was_learned():
    """Experience raises the floor; it does not overwrite a longer claim.

    The first version of this test gave the fact a 10,000-day cycle *before*
    collection, so it was never collected, nothing was re-learned, and the
    assertion held for no reason. `tests/probes/memory_economy_probes.py` found
    that by replacing the `max` with the learned value and watching nothing
    fail."""
    _collectable(pattern="rare_thing")
    memory.collect_garbage(now=datetime.now(timezone.utc))
    learned = store.regretted_patterns()[0]["quiet_days_at_discard"]
    assert 0 < learned < 10_000

    back = store.record_lesson(kind=memory.SOURCE_VALUE, pattern="rare_thing",
                               lesson="again", cost=1.0,
                               expected_interval_days=10_000)
    row = next(item for item in store.lessons() if item["id"] == back)
    assert row["expected_interval_days"] == 10_000


def test_a_dry_run_leaves_no_tombstone_either():
    _collectable()
    memory.collect_garbage(now=datetime.now(timezone.utc), dry_run=True)
    assert store.regretted_patterns() == []


def test_a_tombstone_past_the_horizon_is_pruned_and_stops_being_a_regret():
    """Beyond three default cycles, learning a fact again is a new fact - and a
    tombstone table that grew for ever would be the deadweight the collector
    exists to prevent."""
    _collectable()
    memory.collect_garbage(now=datetime.now(timezone.utc))
    assert store.regretted_patterns()

    with store.connect() as db:
        db.execute("UPDATE collected_patterns SET discarded_at = '2015-01-01T00:00:00+00:00'")
    assert store.prune_tombstones(
        older_than_days=retention.TOMBSTONE_HORIZON_DAYS) == 1

    store.record_lesson(kind=memory.SOURCE_VALUE, pattern="never_chosen",
                        lesson="unrelated, years later", cost=1.0)
    assert store.kind_history(memory.SOURCE_VALUE)["regretted"] == 0


def test_the_sweep_prunes_as_it_goes():
    _collectable()
    memory.collect_garbage(now=datetime.now(timezone.utc))
    with store.connect() as db:
        db.execute("UPDATE collected_patterns SET discarded_at = '2015-01-01T00:00:00+00:00'")
    assert memory.collect_garbage(now=datetime.now(timezone.utc))["pruned"] == 1


def test_the_policy_is_judged_by_its_regrets_not_by_its_reasoning():
    _collectable()
    memory.collect_garbage(now=datetime.now(timezone.utc))
    assert memory.ratification()["holding"] is True

    store.record_lesson(kind=memory.SOURCE_VALUE, pattern="never_chosen",
                        lesson="needed it", cost=12.0)
    judged = memory.ratification()
    assert judged["holding"] is False
    assert judged["regrets"] == 1 and judged["collections"] == 1
    assert "too aggressive" in judged["because"]


def test_the_report_says_whether_the_forgetting_was_right():
    """A claim about how this system learns that said nothing about whether its
    forgetting was right would be the guessing game."""
    _collectable()
    memory.collect_garbage(now=datetime.now(timezone.utc))
    reported = memory.meta_report()
    assert reported["ratification"]["collections"] == 1
    # Its own key, not folded into `claims`: `claims` means cross-episode claims
    # about how this system *learns*, and a verdict on the forgetting policy is
    # true from the first collection rather than being a trend. Mixing them would
    # make "no claims yet" unsayable.
    assert reported["claims"] == []


def test_what_is_still_collected_is_readable_so_a_person_can_judge():
    """The evidence behind the verdict, not just the number - a person deciding
    whether the policy is too aggressive needs to see *what* it threw away."""
    _collectable(cost=12.0)
    memory.collect_garbage(now=datetime.now(timezone.utc))
    still = memory.ratification()["still_collected"]
    assert [item["pattern"] for item in still] == ["never_chosen"]
    assert still[0]["cost_at_discard"] == 12.0
