"""The Model Performance Registry (app/model_performance.py; TQ-54,
docs/SPEC_RECONCILIATION.md §105).

Nothing here calls a model. These tests are about whether the *competition* is
real: whether a seeded ordering can be overturned by evidence, whether failing at
one task costs a model rank at another, and whether the hand-authored guess stays
separable from the measurement forever.

The three that carry the increment:

- `test_a_challenger_can_overtake_the_seeded_leader` — §13. If this ever fails,
  the system is trapped by the original human guess, which is the specific
  failure §12 and §13 exist to prevent.
- `test_failing_one_category_does_not_touch_another` — §11, and it is structural
  rather than policy: there is no code path between two categories' rows.
- `test_the_seed_and_the_evidence_stay_decomposable` — §12. A blended score
  cannot let empirical data dominate later, because nobody could take it apart.
"""

import conftest
import pytest

from app import model_performance as mp
from app.task_signature import (CATEGORY_CODING, CATEGORY_FINANCIAL,
                                CATEGORY_LONG_CONTEXT, TASK_CATEGORIES,
                                UnknownVocabulary)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """A fresh database per test, redirected the way model_budget's ledger is -
    by environment, resolved at call time, so no import-order games."""
    monkeypatch.setenv(mp.PATH_ENV, str(tmp_path / "model_performance.db"))
    yield


def _win(**kw):
    return mp.Outcome(succeeded=True, quality=kw.pop("quality", 0.9), **kw)


def _loss(**kw):
    return mp.Outcome(succeeded=False, failure_type=kw.pop("failure_type", "wrong_answer"),
                      **kw)


# --- seeding (§12) ------------------------------------------------------------------


def test_a_single_seeded_model_sits_at_exact_neutral():
    """Being the only candidate is not evidence of being a good one. A lone
    seeded model expresses no information, and the number says so."""
    mp.seed_leaderboard(CATEGORY_CODING, ["only-model"])

    entry = mp.entry("only-model", CATEGORY_CODING)
    assert entry["seed_score"] == mp.SEED_NEUTRAL
    assert entry["score"] == mp.SEED_NEUTRAL
    assert entry["status"] == mp.STATUS_SEEDED
    assert entry["sample_count"] == 0
    assert entry["confidence"] == 0.0


def test_a_seeded_ordering_is_spread_narrowly_around_neutral():
    """§13 says the initial ranking may well be wrong, so the seed expresses an
    ordering without asserting a gulf that real results have to climb out of."""
    mp.seed_leaderboard(CATEGORY_CODING, ["first", "second", "third"])
    scores = [e["seed_score"] for e in mp.ranking(CATEGORY_CODING)]

    assert scores == sorted(scores, reverse=True)
    assert max(scores) - min(scores) == pytest.approx(2 * mp.SEED_SPREAD)
    assert all(0 < s < 1 for s in scores)


def test_every_seeded_entry_is_provisional():
    """§12: initial scores are explicitly provisional, and stay so until enough
    evidence exists that the seed is no longer most of the number."""
    mp.seed_all_categories(["alpha", "beta"])
    for category in TASK_CATEGORIES:
        for entry in mp.ranking(category):
            assert entry["status"] == mp.STATUS_SEEDED
            assert entry["provisional"] is True


def test_seeding_all_eight_categories_covers_all_eight():
    mp.seed_all_categories(["alpha"])
    assert set(mp.leaderboards()) == set(TASK_CATEGORIES)
    assert mp.summary()["seeded_categories"] == 8


def test_reseeding_never_discards_accumulated_evidence():
    """The one thing a seed must never do to a measurement. Re-seeding is
    idempotent by refusal rather than by overwrite."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha", "beta"])
    for _ in range(6):
        mp.record_outcome("beta", CATEGORY_CODING, _win())
    before = mp.entry("beta", CATEGORY_CODING)

    mp.seed_leaderboard(CATEGORY_CODING, ["alpha", "beta"])

    after = mp.entry("beta", CATEGORY_CODING)
    assert after["sample_count"] == before["sample_count"] == 6
    assert after["seed_score"] == before["seed_score"]


def test_an_unseeded_model_cannot_take_an_outcome():
    """A score with no provisional starting point cannot be decomposed into seed
    and evidence, so there is nowhere to put the result."""
    with pytest.raises(LookupError):
        mp.record_outcome("never-seeded", CATEGORY_CODING, _win())


def test_an_unknown_category_is_refused():
    with pytest.raises(UnknownVocabulary):
        mp.seed_leaderboard("PORTFOLIO_ANALYSIS", ["alpha"])


def test_a_duplicate_in_the_seed_ordering_is_refused():
    with pytest.raises(ValueError):
        mp.seed_leaderboard(CATEGORY_CODING, ["alpha", "alpha"])


# --- the competition (§10, §11, §13) ------------------------------------------------


def test_a_challenger_can_overtake_the_seeded_leader():
    """§13, and the reason the whole lineage exists.

    "No model has a permanent privileged position." The model seeded *last*
    performs well, the model seeded *first* performs badly, and the ordering
    changes - without anybody editing a seed, because the seed decays against
    evidence by arithmetic rather than by decision."""
    mp.seed_leaderboard(CATEGORY_CODING, ["favourite", "underdog"])
    assert mp.front_runner(CATEGORY_CODING)["model_id"] == "favourite"

    for _ in range(10):
        mp.record_outcome("underdog", CATEGORY_CODING, _win(quality=0.95))
        mp.record_outcome("favourite", CATEGORY_CODING, _loss())

    assert mp.front_runner(CATEGORY_CODING)["model_id"] == "underdog"
    ranked = mp.ranking(CATEGORY_CODING)
    assert [e["model_id"] for e in ranked] == ["underdog", "favourite"]
    assert ranked[0]["seed_rank"] == 2, "the winner is the one seeded second"


def test_failing_one_category_does_not_touch_another():
    """§11: "A model failing at one type of task should not necessarily lose
    rank everywhere."

    Structural rather than policy - `record_outcome` writes a row keyed by
    (model, category) and there is no statement in it that reaches another."""
    mp.seed_all_categories(["alpha", "beta"])
    for _ in range(10):
        mp.record_outcome("alpha", CATEGORY_LONG_CONTEXT, _loss())

    assert mp.front_runner(CATEGORY_LONG_CONTEXT)["model_id"] == "beta"
    assert mp.front_runner(CATEGORY_CODING)["model_id"] == "alpha"
    assert mp.entry("alpha", CATEGORY_CODING)["sample_count"] == 0
    assert mp.entry("alpha", CATEGORY_FINANCIAL)["status"] == mp.STATUS_SEEDED


def test_the_seed_and_the_evidence_stay_decomposable():
    """§12: "empirical data should dominate the initial seed" is impossible if
    the two were averaged into a number nobody can take apart later.

    So a caller can always ask what was guessed, what was measured, and how much
    of the composite is each."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha", "beta"])
    for _ in range(15):
        mp.record_outcome("beta", CATEGORY_CODING, _win(quality=0.8))

    entry = mp.entry("beta", CATEGORY_CODING)
    assert entry["seed_score"] == 0.35, "the guess is untouched by the evidence"
    assert entry["quality_score"] == pytest.approx(0.8), "the measurement is its own field"
    assert entry["seed_score"] < entry["score"] < entry["quality_score"], (
        "the composite sits between them, moving toward the evidence")


def test_the_seed_decays_as_evidence_arrives_without_anybody_deciding():
    """Confidence is the seed decay read from the other side: how much of the
    score is measurement rather than guess. Nobody flips a switch when evidence
    takes over."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    assert mp.entry("alpha", CATEGORY_CODING)["confidence"] == 0.0

    seen = []
    for _ in range(20):
        mp.record_outcome("alpha", CATEGORY_CODING, _win())
        seen.append(mp.entry("alpha", CATEGORY_CODING)["confidence"])

    assert seen == sorted(seen), "confidence only ever rises with evidence"
    assert seen[-1] > 0.75
    assert seen[-1] < 1.0, "the seed never quite vanishes, and never has to be deleted"


def test_a_model_stops_being_provisional_once_evidence_outweighs_the_seed():
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    assert mp.entry("alpha", CATEGORY_CODING)["provisional"] is True

    for _ in range(mp.SEED_PRIOR_SAMPLES):
        mp.record_outcome("alpha", CATEGORY_CODING, _win())

    assert mp.entry("alpha", CATEGORY_CODING)["provisional"] is False


@pytest.mark.parametrize("failure", sorted(mp.FAILURE_PENALTIES))
def test_every_failure_type_carries_its_own_weight(failure):
    """§10's penalties are tunable apart. "Wrong answer" and "excessive latency"
    are both bad, and a scoring system that could not tell them apart would have
    nothing to tune."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    mp.record_outcome("alpha", CATEGORY_CODING,
                      mp.Outcome(succeeded=False, failure_type=failure))

    entry = mp.entry("alpha", CATEGORY_CODING)
    assert entry["penalty_score"] == pytest.approx(mp.FAILURE_PENALTIES[failure])
    assert entry["failure_rate"] == 1.0
    assert entry["reliability_score"] == 0.0


def test_a_heavier_failure_costs_more_than_a_lighter_one():
    mp.seed_leaderboard(CATEGORY_CODING, ["heavy", "light"])
    for _ in range(5):
        mp.record_outcome("heavy", CATEGORY_CODING,
                          mp.Outcome(succeeded=False, failure_type="wrong_answer"))
        mp.record_outcome("light", CATEGORY_CODING,
                          mp.Outcome(succeeded=False, failure_type="excessive_latency"))

    assert (mp.entry("light", CATEGORY_CODING)["score"]
            > mp.entry("heavy", CATEGORY_CODING)["score"])


def test_an_unknown_failure_type_is_refused_rather_than_scored_as_zero():
    """Fail closed. A penalty this build cannot weigh must not silently become
    no penalty at all."""
    with pytest.raises(mp.UnknownFailure):
        mp.Outcome(succeeded=False, failure_type="vibes")


def test_a_success_cannot_carry_a_failure_type():
    with pytest.raises(ValueError):
        mp.Outcome(succeeded=True, failure_type="timeout")


def test_an_unscored_success_counts_as_neutral_rather_than_a_win():
    """§38: validate before penalising - and equally, before rewarding. Nobody
    looked at this result, so it earns nothing."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    for _ in range(10):
        mp.record_outcome("alpha", CATEGORY_CODING, mp.Outcome(succeeded=True))

    assert mp.entry("alpha", CATEGORY_CODING)["quality_score"] == pytest.approx(
        mp.SEED_NEUTRAL)


def test_quality_outside_zero_to_one_is_refused():
    for impossible in (-0.1, 1.1):
        with pytest.raises(ValueError):
            mp.Outcome(succeeded=True, quality=impossible)


def test_ties_break_on_the_seeded_order():
    """An ordering somebody chose deliberately survives until evidence
    separates the models - it does not get shuffled by dictionary order."""
    mp.seed_leaderboard(CATEGORY_CODING, ["zulu", "alpha"])
    assert [e["model_id"] for e in mp.ranking(CATEGORY_CODING)] == ["zulu", "alpha"]


def test_rank_is_derived_rather_than_stored():
    """A stored rank is a second copy of what the scores already say, and the
    copy is what goes stale."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha", "beta"])
    for _ in range(10):
        mp.record_outcome("beta", CATEGORY_CODING, _win(quality=1.0))

    ranked = mp.ranking(CATEGORY_CODING)
    assert [e["rank"] for e in ranked] == [1, 2]
    assert ranked[0]["model_id"] == "beta"
    assert ranked[0]["seed_rank"] == 2, "the seeded rank is remembered, not rewritten"


# --- trend, and the agent-specific view (§8) ----------------------------------------


def test_trend_is_unknown_until_there_is_something_to_compare():
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    assert mp.entry("alpha", CATEGORY_CODING)["trend"] == mp.TREND_UNKNOWN
    mp.record_outcome("alpha", CATEGORY_CODING, _win())
    assert mp.entry("alpha", CATEGORY_CODING)["trend"] == mp.TREND_UNKNOWN


def test_a_model_getting_better_reads_as_rising():
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    for _ in range(10):
        mp.record_outcome("alpha", CATEGORY_CODING, _win(quality=0.2))
    for _ in range(6):
        mp.record_outcome("alpha", CATEGORY_CODING, _win(quality=1.0))

    assert mp.entry("alpha", CATEGORY_CODING)["trend"] == mp.TREND_RISING


def test_a_model_getting_worse_reads_as_falling():
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    for _ in range(10):
        mp.record_outcome("alpha", CATEGORY_CODING, _win(quality=1.0))
    for _ in range(6):
        mp.record_outcome("alpha", CATEGORY_CODING, _win(quality=0.1))

    assert mp.entry("alpha", CATEGORY_CODING)["trend"] == mp.TREND_FALLING


def test_agent_specific_performance_sits_beside_the_global_row():
    """§8 wants both. The global row stays the authority; the per-agent rows are
    an extra view, exactly as model_budget's spend_by_caller is."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    mp.record_outcome("alpha", CATEGORY_CODING, _win(agent_role="analysis"))
    mp.record_outcome("alpha", CATEGORY_CODING, _loss(agent_role="explorer"))

    assert mp.entry("alpha", CATEGORY_CODING)["sample_count"] == 2
    assert mp.agent_view("alpha", CATEGORY_CODING, "analysis")["failure_rate"] == 0.0
    assert mp.agent_view("alpha", CATEGORY_CODING, "explorer")["failure_rate"] == 1.0


def test_an_agent_that_never_used_this_model_has_no_row_rather_than_a_zero():
    """"Never used it" and "used it and got nothing right" are different facts,
    and a zero would collapse them."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    assert mp.agent_view("alpha", CATEGORY_CODING, "analysis") is None


def test_work_with_no_declared_role_is_bucketed_honestly():
    """model_budget's word, for its reason: an honest bucket beats a clever
    wrong label, and a growing `unattributed` row is itself the finding."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    mp.record_outcome("alpha", CATEGORY_CODING, _win())

    assert mp.agent_view("alpha", CATEGORY_CODING, mp.UNATTRIBUTED)["sample_count"] == 1


# --- seeding from the committed registry --------------------------------------------


def test_seeding_from_the_registry_covers_every_configured_model():
    """The one point where the two registries touch, and it is directional: the
    performance registry learns which models exist from the committed file and
    tells it nothing back."""
    yaml = pytest.importorskip("yaml")

    mp.seed_from_registry()
    registry = yaml.safe_load(mp.REGISTRY_PATH.read_text(encoding="utf-8"))
    configured = {m["id"] for m in registry["models"] if m["status"] == "configured"}

    for category in TASK_CATEGORIES:
        seeded = {e["model_id"] for e in mp.ranking(category)}
        assert configured <= seeded, f"{category} cannot reach {configured - seeded}"


def test_seeding_from_a_registry_with_no_ordering_refuses_rather_than_inventing_one(
        tmp_path):
    pytest.importorskip("yaml")
    empty = tmp_path / "registry.yaml"
    empty.write_text("version: 1\nmodels: []\n", encoding="utf-8")

    with pytest.raises(LookupError, match="seed_ordering"):
        mp.seed_from_registry(empty)


# --- what this module deliberately does not do --------------------------------------


def test_nothing_here_selects_a_model():
    """TQ-54's scope, asserted rather than trusted.

    A leaderboard that quietly became a router would be one that ignores §36's
    privacy rule and §35's hardware rule, because it has neither in front of it.
    `front_runner` answers "who is ahead"; TQ-60 answers "what should run this",
    and the difference is the whole reason those are separate entries."""
    body = conftest.executable_source(mp.__file__)

    for leaked in ("privacy", "vram", "gpu", "select_model", "route("):
        assert leaked not in body, (
            f"{leaked!r} appears in model_performance's code: this module ranks, "
            "it does not choose")


def test_cost_and_resource_scores_are_absent_rather_than_zero():
    """§8 lists them and nothing produces either yet - local cost needs TQ-57's
    hardware monitoring, external cost needs TQ-65's cost model. A column that
    is always NULL is machinery with no user; a zero would be a measurement
    nobody made."""
    mp.seed_leaderboard(CATEGORY_CODING, ["alpha"])
    entry = mp.entry("alpha", CATEGORY_CODING)

    for absent in ("cost_score", "resource_efficiency_score"):
        assert absent not in entry
