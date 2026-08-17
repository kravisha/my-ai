"""Questions about the personnel rules that one trial cannot answer.

"Does a strong agent qualify" needs a single run. "How often does a weak one
qualify anyway", "how far into a decline is it noticed", "does ranking find an
order where none exists" are rates, and a rate needs a population.

These are requirements, not recordings. Each states what the rules must achieve
and measures whether they do; a test that simply asserted whatever number came
out would pass forever and mean nothing. Where a measurement failed to meet the
requirement, the rule changed rather than the assertion.

Runtime is about a second in total, so these are part of the default suite. They
skip the database on purpose - `personnel.sample_grades` is the same sampler the
database path writes rows from, and the equivalence is asserted below rather
than assumed.
"""

import random

import pytest

from backend import competency, fi_db
from simulation import experiment, personnel

TRIALS = 300


# -- the fast path is the same path -------------------------------------------

def test_the_sampler_and_the_database_produce_the_same_evidence(conn):
    """What licenses every other test in this file to skip the database.

    If these diverged, the distributional results would describe a fixture
    nothing else uses."""
    fi_db.init_schema(conn)
    population = personnel.generate(conn, [("analysis", "steady_strong")], items_per_agent=40, seed=99)
    from_database = [
        row["overall_score"] for row in fi_db.competency_evidence(conn, population.agents[0].name)["grades"]
    ]
    from_sampler = [
        row["overall_score"] for row in personnel.sample_grades("steady_strong", 40, random.Random(99))
    ]
    assert sorted(from_database) == sorted(from_sampler)


# -- false promotion ----------------------------------------------------------

def test_a_persistently_weak_agent_essentially_never_qualifies():
    """The false-promotion requirement: noise alone must not promote anybody."""
    for row in experiment.evidence_floor_sweep("steady_weak", trials=TRIALS):
        assert row["rate"] < 0.01, (
            f"a weak agent qualified in {row['rate']:.1%} of trials at an evidence floor of "
            f"{row['min_samples']}"
        )


def test_a_capable_agent_is_not_held_back():
    """The other side of the same threshold.

    A bar high enough to stop every false promotion also stops every true one,
    so both directions have to be measured or only one gets tuned."""
    for row in experiment.evidence_floor_sweep("steady_strong", trials=TRIALS):
        assert row["rate"] > 0.95, (
            f"a capable agent qualified in only {row['rate']:.1%} of trials at floor "
            f"{row['min_samples']}"
        )


def test_a_good_opening_followed_by_decline_is_not_a_false_promotion(conn):
    """Correcting the premise this archetype was built on.

    `lucky_streak` was designed to measure false promotion, and it does not.
    While the streak is running the agent's true competence really is 0.8, so
    qualifying then is correct rather than mistaken - it is a *fast decline*,
    and what matters is how quickly the qualification is withdrawn afterwards.
    That is the detection-lag question below.

    False promotion from noise alone is covered by `steady_weak`, and measures
    zero at every floor."""
    early = experiment.qualification_rate("lucky_streak", evaluate_after=10, trials=TRIALS)
    assert early["true_competence_at_evaluation"] > 0.7, (
        "the archetype is genuinely strong at this point, so qualifying is not an error"
    )
    assert early["rate"] > 0.9


# -- detection lag, and why recency is mandatory ------------------------------

def test_a_lifetime_average_cannot_detect_decline():
    """The finding that decides how qualification must be evaluated.

    An agent falling from 0.75 to 0.25 across its life is, on a lifetime
    average, either noticed at the very end or not at all - because the good
    early record keeps propping the mean up. This is the recorded justification
    for requiring a recency window, and it is measured rather than argued."""
    result = experiment.detection_lag(window=None, trials=TRIALS)

    assert result["never_detected"] / TRIALS > 0.1, (
        "if a lifetime average now detects decline reliably, this justification is stale and the "
        "requirement for a window should be re-examined rather than assumed"
    )
    assert result["median_lag_fraction"] > 0.9


@pytest.mark.parametrize("window,ceiling", [(40, 0.85), (20, 0.7), (10, 0.6)])
def test_a_recent_window_detects_decline_before_it_is_over(window, ceiling):
    """The requirement a window has to meet, tightening as it narrows.

    The archetype crosses the qualification threshold at the halfway point of
    its life, so 0.5 is the best any rule could do and a window of ten lands at
    0.525."""
    result = experiment.detection_lag(window=window, trials=TRIALS)

    assert result["never_detected"] == 0, f"a window of {window} missed the decline entirely"
    assert result["median_lag_fraction"] < ceiling, (
        f"a window of {window} noticed the decline only {result['median_lag_fraction']:.0%} of the "
        "way through it"
    )


def test_narrower_windows_notice_sooner():
    """Monotonic, or the window is not doing what it is being relied on to do."""
    lags = [experiment.detection_lag(window=w, trials=TRIALS)["median_lag_fraction"] for w in (40, 20, 10)]
    assert lags == sorted(lags, reverse=True), f"detection lag did not shorten with the window: {lags}"


# -- ranking among equals -----------------------------------------------------

def test_ranking_finds_no_stable_order_among_equal_agents():
    """Three archetypes averaging 0.5 by construction. Any consistent winner
    would mean the ranking was reading something that is not there."""
    result = experiment.rank_stability(trials=TRIALS)
    shares = result["top_position_share"]

    assert max(shares.values()) < 0.55, (
        f"one agent took the top position in {max(shares.values()):.0%} of trials despite all three "
        f"having identical true competence: {shares}"
    )


def test_ranking_on_a_mean_favours_the_least_consistent_agent():
    """A documented bias, not a requirement.

    Among agents of equal average competence, the noisiest one produces the
    highest single score most often, so ranking on a mean quietly rewards
    inconsistency. It is recorded here because it is real and cannot be removed
    by tuning - what makes it harmless is the separation check below, which
    stops the ordering being acted on."""
    result = experiment.rank_stability(trials=TRIALS)
    shares = result["top_position_share"]
    erratic_share = shares["agent_2"]      # the erratic archetype, by construction

    assert erratic_share == max(shares.values()), (
        "the inconsistency bias has disappeared; if that is a real improvement the separation rule "
        "may be doing more work than it needs to"
    )


def test_the_separation_rule_almost_never_claims_a_false_difference():
    """The safety property that makes the bias above tolerable.

    Two agents of identical true competence must almost never be reported as
    separated. A two-sigma rule budgets roughly five percent; the measured rate
    is an order of magnitude below it, which is the right side to err on for a
    signal that would be used to promote somebody."""
    result = experiment.rank_stability(trials=TRIALS)

    assert result["comparisons"] > 100, "too few comparisons for the rate to mean anything"
    assert result["false_separation_rate"] < 0.05, (
        f"equal agents were reported as separated in {result['false_separation_rate']:.1%} of "
        "comparisons"
    )


def test_a_real_difference_is_still_reported_as_separated():
    """A separation flag that is never True would satisfy the test above and be useless."""
    separated = 0
    for trial in range(100):
        rng = random.Random(4200 + trial)
        profiles = {
            "strong": competency.profile({"grades": personnel.sample_grades("steady_strong", 60, rng)}),
            "weak": competency.profile({"grades": personnel.sample_grades("steady_weak", 60, rng)}),
        }
        ranked = [row for row in competency.rank(profiles, "analytical_quality") if row["rank"]]
        separated += bool(ranked[0]["separated"])

    assert separated == 100, f"a genuine gap was reported as separated in only {separated}/100 trials"
