"""Unit tests for providers/market_data.py and providers/social_data.py -
pure logic, no DB or network involved."""

from providers.market_data import EXPIRIES_DAYS, STRIKES, SyntheticMarketDataProvider
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


def test_no_forced_anomaly_stays_flat():
    """Without force_anomaly, no cell should be anywhere close to a 2x
    ratio against its own local neighborhood - otherwise Explorer's
    detector would false-positive on ordinary noise."""
    p = SyntheticMarketDataProvider(seed=42, force_anomaly=False)
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
    p = SyntheticMarketDataProvider(seed=42, force_anomaly=True)
    surface = p.get_option_surface("SYN1")
    peak = max(pt.iv for pt in surface.points)
    baseline_no_anomaly = SyntheticMarketDataProvider(seed=42, force_anomaly=False).get_option_surface("SYN1")
    baseline_avg = sum(pt.iv for pt in baseline_no_anomaly.points) / len(baseline_no_anomaly.points)
    assert peak > baseline_avg * 2


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
