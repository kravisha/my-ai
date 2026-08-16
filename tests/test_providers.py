"""Unit tests for providers/market_data.py and providers/social_data.py -
pure logic, no DB or network involved."""

import statistics

import pytest

from providers.market_data import (
    BASE_LEVEL,
    EXPIRIES_DAYS,
    NOISE_AMPLITUDE,
    STRIKES,
    SyntheticMarketDataProvider,
)
from providers.social_data import SyntheticSocialDataProvider


# --- market data ---


def test_same_seed_same_security_is_deterministic():
    p1 = SyntheticMarketDataProvider(seed=42)
    p2 = SyntheticMarketDataProvider(seed=42)
    assert p1.get_option_surface("SYN1").points == p2.get_option_surface("SYN1").points


def test_same_provider_repeated_calls_are_static():
    p = SyntheticMarketDataProvider(seed=42)
    first = p.get_option_surface("SYN1")
    second = p.get_option_surface("SYN1")
    assert first.points == second.points


def test_different_seed_diverges():
    p1 = SyntheticMarketDataProvider(seed=42)
    p2 = SyntheticMarketDataProvider(seed=99)
    assert p1.get_option_surface("SYN1").points != p2.get_option_surface("SYN1").points


def test_different_security_diverges_within_same_provider():
    p = SyntheticMarketDataProvider(seed=42)
    assert p.get_option_surface("SYN1").points != p.get_option_surface("SYN2").points


def test_no_anomalies_stays_flat():
    """With no security named in `anomalies`, no cell should be anywhere
    close to a 2x ratio against its own local neighborhood - otherwise
    Explorer's detector would false-positive on ordinary noise."""
    p = SyntheticMarketDataProvider(seed=42)
    surface = p.get_option_surface("SYN1")
    grid = {(STRIKES.index(pt.strike), EXPIRIES_DAYS.index(pt.expiry_days)): pt.iv for pt in surface.points}
    max_ratio = 0.0
    for (si, ei), iv in grid.items():
        neighbors = [
            v for (nsi, nei), v in grid.items()
            if (nsi, nei) != (si, ei) and abs(nsi - si) <= 1 and abs(nei - ei) <= 1
        ]
        if neighbors:
            max_ratio = max(max_ratio, iv / (sum(neighbors) / len(neighbors)))
    assert max_ratio < 1.5


def test_forced_anomaly_produces_elevated_peak_cell():
    p = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})
    surface = p.get_option_surface("SYN1")
    peak = max(pt.iv for pt in surface.points)
    baseline_no_anomaly = SyntheticMarketDataProvider(seed=42).get_option_surface("SYN1")
    baseline_avg = sum(pt.iv for pt in baseline_no_anomaly.points) / len(baseline_no_anomaly.points)
    assert peak > baseline_avg * 2


def test_anomaly_is_targeted_per_security_not_global():
    """A security not named in `anomalies` stays flat even when another
    security in the same provider instance is forced - addendum_7 §5's
    isolated-anomaly scenario depends on this."""
    p = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})
    syn2_forced = p.get_option_surface("SYN2")
    syn2_natural = SyntheticMarketDataProvider(seed=42).get_option_surface("SYN2")
    assert syn2_forced.points == syn2_natural.points


def test_co_movement_scenario_bumps_both_securities_at_same_cell():
    """Two securities both given an empty anomaly override bump at the same
    default grid cell - a genuine "same shape/spike" fixture for the
    addendum_7 §5 peer/co-movement scenario, not two unrelated anomalies
    that happen to coexist."""
    p = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}, "SYN2": {}})
    natural = SyntheticMarketDataProvider(seed=42).get_option_surface("SYN1").points
    baseline_avg = sum(pt.iv for pt in natural) / len(natural)
    peak1 = max(pt.iv for pt in p.get_option_surface("SYN1").points)
    peak2 = max(pt.iv for pt in p.get_option_surface("SYN2").points)
    assert peak1 > baseline_avg * 2
    assert peak2 > baseline_avg * 2


# --- social data ---


def test_social_same_seed_is_reproducible():
    p1 = SyntheticSocialDataProvider(seed=7)
    p2 = SyntheticSocialDataProvider(seed=7)
    posts1 = p1.fetch_recent("SYN1")
    posts2 = p2.fetch_recent("SYN1")
    assert [p.text for p in posts1] == [p.text for p in posts2]
    assert [p.posted_at for p in posts1] == [p.posted_at for p in posts2]


def test_social_since_filter_excludes_already_seen_posts():
    p = SyntheticSocialDataProvider(seed=7)
    first_batch = p.fetch_recent("SYN1")
    if not first_batch:
        # seed=7's first call happened to generate zero posts - force a
        # second call so there's something to filter against.
        first_batch = p.fetch_recent("SYN1")
    cursor = first_batch[-1].posted_at
    second_batch = p.fetch_recent("SYN1", since=cursor)
    assert all(post.posted_at > cursor for post in second_batch)
    assert not set(post.posted_at for post in second_batch) & set(post.posted_at for post in first_batch)


def test_social_posts_scoped_to_requested_security():
    p = SyntheticSocialDataProvider(seed=7)
    posts = p.fetch_recent("SYN1")
    assert all(post.security == "SYN1" for post in posts)


# --- market regime: the provider must be able to change conditions at all ---


def test_market_provider_honours_a_regime_override():
    """Without this the whole regime-detection feature would be a detector for
    a phenomenon that cannot occur - BASE_LEVEL/NOISE_AMPLITUDE were module
    constants and surfaces are cached permanently."""
    default = SyntheticMarketDataProvider(seed=42)
    shifted = SyntheticMarketDataProvider(seed=42, regime={"base_level": 0.45})
    default_mean = statistics.mean(p.iv for p in default.get_option_surface("SYN1").points)
    shifted_mean = statistics.mean(p.iv for p in shifted.get_option_surface("SYN1").points)
    assert shifted_mean - default_mean == pytest.approx(0.20, abs=0.01)


def test_market_provider_regime_changes_dispersion_independently_of_level():
    calm = SyntheticMarketDataProvider(seed=42, regime={"noise_amplitude": 0.005})
    choppy = SyntheticMarketDataProvider(seed=42, regime={"noise_amplitude": 0.08})
    calm_points = [p.iv for p in calm.get_option_surface("SYN1").points]
    choppy_points = [p.iv for p in choppy.get_option_surface("SYN1").points]
    assert statistics.stdev(choppy_points) > statistics.stdev(calm_points)
    # level is essentially untouched - the two statistics move independently,
    # which is what lets a drift check say *which* condition changed
    assert statistics.mean(choppy_points) == pytest.approx(statistics.mean(calm_points), abs=0.02)


def test_market_provider_defaults_match_the_module_constants():
    """An omitted regime must be exactly the old behaviour - every existing
    test and calibrated tolerance depends on it."""
    explicit = SyntheticMarketDataProvider(seed=42, regime={"base_level": BASE_LEVEL, "noise_amplitude": NOISE_AMPLITUDE})
    implicit = SyntheticMarketDataProvider(seed=42)
    assert [p.iv for p in explicit.get_option_surface("SYN1").points] == [
        p.iv for p in implicit.get_option_surface("SYN1").points
    ]


# --- social narratives: the fixture must be able to produce disagreement ---


def _drain(provider, security, cycles=10):
    """Collect posts the way Speculator does - advancing a `since` cursor.
    Calling fetch_recent without one returns everything accumulated so far,
    which double-counts."""
    posts, cursor = [], None
    for _ in range(cycles):
        new = provider.fetch_recent(security, since=cursor)
        if new:
            posts += new
            cursor = new[-1].posted_at
    return posts


def test_silent_narrative_produces_no_posts_at_all():
    """'No evidence available' is a distinct cross-check finding from
    disagreement, so it has to be constructible rather than approximated by a
    low post count."""
    p = SyntheticSocialDataProvider(seed=7, narratives={"SYN1": "silent"})
    assert _drain(p, "SYN1") == []


def test_coordinated_narrative_is_high_volume_from_few_authors():
    """The case that earns source dispersion its keep: the text reads as
    enthusiastic agreement, but it comes from a handful of accounts."""
    p = SyntheticSocialDataProvider(seed=7, narratives={"SYN1": "coordinated"})
    posts = _drain(p, "SYN1")
    assert len(posts) > 20
    assert len(set(post.author for post in posts)) <= 3


def test_broad_narratives_have_near_unique_authorship():
    p = SyntheticSocialDataProvider(seed=7, narratives={"SYN1": "corroborating", "SYN2": "contradicting"})
    for security in ("SYN1", "SYN2"):
        posts = _drain(p, security)
        assert posts
        # a genuine crowd, not three accounts
        assert len(set(post.author for post in posts)) / len(posts) > 0.8


def test_volume_alone_ranks_the_securities_backwards():
    """The fixture's central property. If loudest meant most credible, this
    increment would have nothing to prove - so the corroborating stream is
    deliberately the quietest of the three."""
    p = SyntheticSocialDataProvider(seed=7, narratives={
        "SYN1": "corroborating", "SYN2": "contradicting", "SYN3": "coordinated",
    })
    volumes = {s: len(_drain(p, s)) for s in ("SYN1", "SYN2", "SYN3")}
    assert volumes["SYN3"] > volumes["SYN2"] > volumes["SYN1"]


def test_unknown_narrative_is_rejected_loudly():
    p = SyntheticSocialDataProvider(seed=7, narratives={"SYN1": "bullish"})
    with pytest.raises(ValueError, match="unknown narrative"):
        p.fetch_recent("SYN1")


def test_securities_without_a_narrative_keep_the_default_stream():
    p = SyntheticSocialDataProvider(seed=7, narratives={"SYN1": "silent"})
    assert _drain(p, "SYN2")  # unassigned security still produces chatter


def test_engagement_score_never_exceeds_one():
    """Several narrative templates sit at 0.9+, and unclamped jitter produced
    1.017 in a real run - which would flow into a report's
    judgment_confidence as a confidence above certainty."""
    p = SyntheticSocialDataProvider(seed=7, narratives={"SYN1": "coordinated"})
    posts = _drain(p, "SYN1", cycles=30)
    assert posts
    assert all(0.0 <= post.engagement_score <= 1.0 for post in posts)
