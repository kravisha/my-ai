"""Simulated time, and the fact that market data does not share one clock.

The organization has run entirely on wall-clock time. Market hours, day rollover,
event calendars and a recommendation's declared horizon all need a clock the
whole organization shares, and every one of them built against wall-clock time
would need rebuilding.

The tests that matter most are the lookahead ones. Using a figure before it was
publishable inflates every result it touches and is invisible in the output - a
backtest built on it looks excellent and means nothing - so the guard belongs in
the clock rather than in each independently written consumer.
"""

from datetime import datetime, timedelta, timezone

import pytest

from simulation import clock


def wall(seconds: float) -> datetime:
    return datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


@pytest.fixture
def sim():
    return clock.SimulationClock(scale=288, started_at=wall(0))


# -- scale --------------------------------------------------------------------

def test_simulated_time_advances_at_the_configured_multiple(sim):
    assert sim.now(wall(0)) == clock.DEFAULT_EPOCH
    assert sim.now(wall(1)) == clock.DEFAULT_EPOCH + timedelta(seconds=288)


def test_a_simulated_day_takes_five_wall_minutes_at_the_default_scale(sim):
    assert sim.wall_seconds_per_simulated_day() == pytest.approx(300)


def test_the_default_scale_keeps_an_agent_poll_at_a_plausible_analyst_cadence():
    """The trade-off the scale makes, asserted so it cannot drift unnoticed.

    Too slow and a run never reaches a day rollover; too fast and a one-second
    poll steps over hours of simulated market and an agent watching for a
    dislocation walks straight past it.

    The band widened at the bottom when the rate became 24x. It previously
    started at one simulated minute, which was reasoning from a 288x world where
    a poll covered nearly five - at 24x a poll covers 24 simulated seconds, which
    is a finer view of the market rather than a worse one. What the lower bound
    actually guards is sampling so fine that agents are watching ticks instead of
    forming a view, and seconds-per-poll is comfortably clear of that."""
    poll_seconds = 1.0
    simulated = timedelta(seconds=poll_seconds * clock.DEFAULT_SCALE)
    assert timedelta(seconds=10) <= simulated <= timedelta(minutes=30)


def test_the_epoch_starts_on_a_trading_day():
    """Otherwise the first simulated day opens with every market shut, and a
    short run would conclude the organization does nothing."""
    assert clock.DEFAULT_EPOCH.weekday() < 5


# -- sessions differ by asset class ------------------------------------------

def at(moment: datetime) -> clock.SimulationClock:
    return clock.SimulationClock(epoch=moment, scale=1, started_at=wall(0))


def test_equities_and_futures_do_not_close_together():
    """The reason there is a session registry rather than one calendar.

    Modelling every asset on one session would teach the organization that when
    one market is quiet they all are, which is false and would be learned."""
    overnight = at(datetime(2026, 1, 6, 3, 0, tzinfo=timezone.utc))

    assert overnight.is_open("equity_price", wall(0)) is False
    assert overnight.is_open("commodity_price", wall(0)) is True


def test_the_equity_session_is_open_mid_afternoon_utc():
    midday = at(datetime(2026, 1, 6, 16, 0, tzinfo=timezone.utc))
    assert midday.is_open("equity_price", wall(0)) is True
    assert midday.is_open("option_surface", wall(0)) is True


def test_nothing_that_trades_on_weekdays_is_open_at_the_weekend():
    saturday = at(datetime(2026, 1, 10, 16, 0, tzinfo=timezone.utc))
    for data_class in ("equity_price", "option_surface", "government_yield", "fx_rate"):
        assert saturday.is_open(data_class, wall(0)) is False, data_class


def test_open_data_classes_is_a_list_because_markets_do_not_close_together():
    overnight = at(datetime(2026, 1, 6, 3, 0, tzinfo=timezone.utc))
    names = overnight.open_data_classes(wall(0))

    assert "commodity_price" in names
    assert "equity_price" not in names


def test_an_etf_and_a_mutual_fund_keep_different_clocks():
    """They hold nearly the same assets and are priced completely differently.

    The pair is the clearest case for cadence being a property of the instrument
    rather than of what it owns: one trades all day, the other is struck once at
    the close and has no intraday value to quote."""
    assert clock.CADENCES["etf_price"].kind == clock.CONTINUOUS
    assert clock.CADENCES["mutual_fund_nav"].kind == clock.DAILY_CLOSE


def test_a_corporate_bond_is_sporadic_rather_than_continuous():
    """A given bond may not trade for days, and its last price going stale is
    information rather than a missing value to be filled in."""
    assert clock.CADENCES["corporate_bond_price"].kind == clock.SPORADIC
    assert clock.CADENCES["government_yield"].kind == clock.CONTINUOUS


def test_every_cadence_names_a_session_that_exists():
    for name, cadence in clock.CADENCES.items():
        assert cadence.session in clock.SESSIONS, f"{name} names unknown session {cadence.session!r}"


def test_published_statistics_carry_a_lag_and_traded_prices_do_not():
    """The distinction the whole two-timestamp model rests on."""
    for name in ("equity_price", "option_surface", "fx_rate", "commodity_price"):
        assert clock.CADENCES[name].publication_lag == timedelta(0), name
    for name in ("cpi", "gdp", "home_price_index", "employment"):
        assert clock.CADENCES[name].publication_lag > timedelta(0), name


def test_gdp_is_revised_and_a_price_is_not():
    """A decision made on the first print was made without the revisions, which
    is a thing worth being able to test."""
    assert clock.CADENCES["gdp"].revisions == 2
    assert clock.CADENCES["equity_price"].revisions == 0


# -- lookahead ---------------------------------------------------------------

def test_a_published_figure_is_not_knowable_on_the_day_it_describes():
    """CPI for a month is not available during that month.

    An organization shown it then would appear to predict inflation, and would
    have been handed it."""
    cadence = clock.CADENCES["cpi"]
    effective = datetime(2026, 3, 31, tzinfo=timezone.utc)

    assert clock.is_knowable(cadence, effective, effective) is False
    assert clock.is_knowable(cadence, effective, effective + timedelta(days=15)) is True


def test_a_traded_price_is_knowable_immediately():
    cadence = clock.CADENCES["equity_price"]
    moment = datetime(2026, 3, 31, tzinfo=timezone.utc)
    assert clock.is_knowable(cadence, moment, moment) is True


def test_home_prices_lag_by_months_not_days():
    """The longest lag in the set, and the easiest to get wrong by assuming all
    published data behaves like CPI."""
    cadence = clock.CADENCES["home_price_index"]
    effective = datetime(2026, 3, 31, tzinfo=timezone.utc)

    assert clock.is_knowable(cadence, effective, effective + timedelta(days=30)) is False
    assert clock.is_knowable(cadence, effective, effective + timedelta(days=70)) is True


def test_visible_hides_records_that_had_not_been_published(sim):
    now = datetime(2026, 4, 5, tzinfo=timezone.utc)
    records = [
        {"effective_at": datetime(2026, 2, 28, tzinfo=timezone.utc), "value": "february"},
        {"effective_at": datetime(2026, 3, 31, tzinfo=timezone.utc), "value": "march"},
    ]

    shown = clock.visible("cpi", records, now)

    assert [r["value"] for r in shown] == ["february"], (
        "March CPI was shown five days after the month ended, two weeks before it exists"
    )


def test_visible_accepts_an_iso_string_as_well_as_a_datetime():
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    records = [{"effective_at": "2026-03-31T00:00:00+00:00", "value": "march"}]
    assert len(clock.visible("cpi", records, now)) == 1


def test_a_record_with_no_effective_date_is_dropped_not_assumed_current():
    """Guessing in the permissive direction is the error this exists to prevent.

    A datum whose date is unknown cannot be shown to be knowable, and treating it
    as current is how lookahead gets in through the back door."""
    now = datetime(2026, 12, 31, tzinfo=timezone.utc)
    assert clock.visible("cpi", [{"value": "undated"}], now) == []


# -- the taxonomy ------------------------------------------------------------

def test_every_data_class_names_a_known_archetype():
    from simulation import cadences

    for name, cadence in clock.CADENCES.items():
        assert cadence.kind in cadences.ARCHETYPES, f"{name} has unknown archetype {cadence.kind!r}"


def test_the_registry_covers_the_archetypes_it_declares():
    """An archetype nobody uses is a pattern that was imagined rather than found.

    Not every archetype needs many members - windowed has one - but one with
    none means the taxonomy drifted from the inventory it was drawn from."""
    from simulation import cadences

    unused = [kind for kind in cadences.ARCHETYPES if not cadences.by_archetype(kind)]
    assert not unused, f"archetypes with no data class: {unused}"


def test_traded_prices_carry_no_lag_and_published_statistics_do():
    """The distinction the whole two-timestamp model rests on."""
    from simulation import cadences

    for name in cadences.by_archetype(cadences.CONTINUOUS):
        assert clock.CADENCES[name].publication_lag == timedelta(0), name
    for name in ("cpi", "gdp", "home_price_index", "employment", "institutional_holdings"):
        assert clock.CADENCES[name].publication_lag > timedelta(0), name


def test_the_worst_lag_is_measured_in_months_not_days():
    """13F may describe a position closed four months before anyone can read it,
    and treating it as current holdings is not a small error."""
    assert clock.CADENCES["institutional_holdings"].publication_lag >= timedelta(days=45)
    assert clock.CADENCES["home_price_index"].publication_lag >= timedelta(days=60)


def test_smoothed_data_classes_can_be_asked_whether_they_are_smoothed():
    """An appraised or rarely-traded value shows low measured volatility because
    it is not being repriced, not because it is not risky. A consumer has to be
    able to ask, rather than discovering it in a risk number that looked calm."""
    assert clock.CADENCES["private_asset_mark"].is_smoothed is True
    assert clock.CADENCES["corporate_bond_price"].is_smoothed is True
    assert clock.CADENCES["equity_price"].is_smoothed is False


def test_classes_where_absence_is_a_finding_are_marked():
    """A bond that did not trade and a broken feed look identical otherwise."""
    assert clock.CADENCES["corporate_bond_price"].absence_is_data is True
    assert clock.CADENCES["auction_imbalance"].absence_is_data is True
    assert clock.CADENCES["equity_price"].absence_is_data is False


def test_series_that_get_restated_declare_their_revisions():
    """A series is a value per (date, vintage), not per date. A decision taken on
    the first print was taken without the later ones."""
    assert clock.CADENCES["gdp"].revisions == 2
    assert clock.CADENCES["employment"].revisions == 2
    assert clock.CADENCES["consumer_sentiment"].revisions == 1
    assert clock.CADENCES["equity_price"].revisions == 0


def test_the_etf_and_mutual_fund_pair_still_disagrees():
    """The clearest case for cadence being a property of the instrument rather
    than of what it holds, and the reason the registry is not grouped by asset."""
    assert clock.CADENCES["etf_price"].kind == clock.CONTINUOUS
    assert clock.CADENCES["mutual_fund_nav"].kind == clock.DAILY_CLOSE


def test_the_same_underlying_can_be_priced_on_two_clocks():
    """REIT prices and private real-estate marks describe the same buildings."""
    assert clock.CADENCES["private_asset_mark"].kind == clock.APPRAISAL
    assert clock.CADENCES["equity_price"].kind == clock.CONTINUOUS


def test_lagged_lists_exactly_the_classes_with_a_gap():
    from simulation import cadences

    listed = set(cadences.lagged())
    computed = {n for n, c in clock.CADENCES.items() if c.publication_lag > timedelta(0)}
    assert listed == computed
    assert len(listed) > 20, "the lookahead guard should have plenty to guard"
