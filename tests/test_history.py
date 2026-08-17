"""A corpus readable as of a moment, with vintages.

Two failures shape these tests, and both share a property that makes them
dangerous: **they improve the result and raise no error.**

*Lookahead.* Reading the corpus without a moment returns everything, including
what nobody knew at the time. Every backtest gets better and nothing breaks.

*Vintage collapse.* Published statistics are revised, so the same quarter has
several values knowable at different times. Taking the newest row gives the final
revision, which is the number nobody had.

The guard against both is that the query cannot be written wrongly: `as_of`
requires a moment and requires its domains, with no defaults and no "all".
"""

from datetime import datetime, timedelta, timezone

import pytest

from simulation import history

Q1 = datetime(2026, 3, 31, tzinfo=timezone.utc)
APRIL = datetime(2026, 4, 30, tzinfo=timezone.utc)
MAY = datetime(2026, 5, 30, tzinfo=timezone.utc)
JUNE = datetime(2026, 6, 30, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    conn = history.open_store(tmp_path / "corpus.db")
    yield conn
    conn.close()


def gdp(conn, knowable, value, vintage, domain=history.HISTORICAL):
    return history.record(
        conn, domain=domain, data_class="cpi", subject="US",
        effective_at=Q1, knowable_at=knowable, value={"gdp": value},
        source="statistics office", vintage=vintage,
    )


def three_vintages(conn):
    """The same quarter, published once and revised twice."""
    gdp(conn, APRIL, 2.1, 1)
    gdp(conn, MAY, 2.4, 2)
    gdp(conn, JUNE, 1.9, 3)


# -- vintages ----------------------------------------------------------------

def test_the_same_quarter_can_hold_several_revisions(store):
    three_vintages(store)
    assert len(history.revisions(store, "cpi", "US", Q1)) == 3


def test_a_backtest_in_may_sees_mays_number(store):
    """The failure this store exists to prevent. Using June's revision on a May
    date is lookahead of the most seductive kind: the result improves, nothing
    errors, and the mistake is invisible in the output."""
    three_vintages(store)

    latest = history.latest_vintage_as_of(store, MAY, [history.HISTORICAL], "cpi", "US")

    assert len(latest) == 1
    assert latest[0]["value"]["gdp"] == 2.4
    assert latest[0]["vintage"] == 2


def test_a_backtest_in_april_sees_the_original_publication(store):
    three_vintages(store)
    latest = history.latest_vintage_as_of(store, APRIL, [history.HISTORICAL], "cpi", "US")
    assert latest[0]["value"]["gdp"] == 2.1


def test_before_publication_the_figure_does_not_exist(store):
    """Not zero, not the first revision - absent. A quarter that has ended is not
    a quarter whose statistics have been published."""
    three_vintages(store)
    just_after_the_quarter = Q1 + timedelta(days=1)

    assert history.as_of(store, just_after_the_quarter, [history.HISTORICAL]) == []


def test_the_final_revision_is_only_visible_once_it_is_published(store):
    three_vintages(store)
    assert history.latest_vintage_as_of(
        store, JUNE, [history.HISTORICAL], "cpi", "US"
    )[0]["value"]["gdp"] == 1.9


# -- the as-of guard ---------------------------------------------------------

def test_a_query_must_name_its_domains(store):
    """No 'all'. A query without domains would silently blend a real corpus with
    generated data, and the result would look entirely normal."""
    three_vintages(store)
    with pytest.raises(ValueError, match="must name its domains"):
        history.as_of(store, JUNE, [])


def test_an_unknown_domain_is_refused(store):
    with pytest.raises(ValueError, match="unknown domain"):
        history.as_of(store, JUNE, ["probably_real"])


def test_domains_do_not_leak_into_each_other(store):
    """The whole point of recording provenance. A simulated figure must never
    appear in an answer about the real world."""
    gdp(store, APRIL, 2.1, 1, domain=history.HISTORICAL)
    gdp(store, APRIL, 9.9, 1, domain=history.SIMULATED)

    real_only = history.as_of(store, JUNE, [history.HISTORICAL])

    assert len(real_only) == 1
    assert real_only[0]["value"]["gdp"] == 2.1


def test_combining_domains_is_possible_but_deliberate(store):
    """Explicit is the requirement, not impossible. Naming both is a decision
    somebody made and can be found in the code."""
    gdp(store, APRIL, 2.1, 1, domain=history.HISTORICAL)
    gdp(store, APRIL, 9.9, 1, domain=history.SIMULATED)

    both = history.as_of(store, JUNE, [history.HISTORICAL, history.SIMULATED])

    assert len(both) == 2


def test_recording_a_datum_knowable_before_it_happened_is_refused(store):
    """The corpus refuses to hold an impossibility. Ingesting one would put
    lookahead in the data itself, where no query guard could catch it."""
    with pytest.raises(ValueError, match="cannot be known before"):
        history.record(
            store, domain=history.HISTORICAL, data_class="cpi", subject="US",
            effective_at=JUNE, knowable_at=APRIL, value={}, source="test",
        )


# -- filtering ---------------------------------------------------------------

def test_a_subject_filter_does_not_widen_the_as_of_window(store):
    """A filter that quietly dropped the moment would be the worst version of
    this bug: correct-looking, narrower, and full of the future."""
    three_vintages(store)
    history.record(
        store, domain=history.HISTORICAL, data_class="cpi", subject="EU",
        effective_at=Q1, knowable_at=JUNE, value={"gdp": 0.4}, source="test",
    )

    us = history.as_of(store, MAY, [history.HISTORICAL], subject="US")

    assert {row["subject"] for row in us} == {"US"}
    assert all(row["knowable_at"] <= MAY.isoformat() for row in us)


def test_the_corpus_reports_what_it_holds(store):
    three_vintages(store)
    summary = history.summary(store)

    assert summary[history.HISTORICAL]["observations"] == 3
    assert history.SIMULATED not in summary


# -- the bridge from a world -------------------------------------------------

def test_a_world_can_be_ingested_as_a_corpus(store):
    """The path that makes a continuously advancing world worth more than one
    run: what it produced survives it."""
    from datetime import timezone as tz

    from providers.market_data import SyntheticMarketDataProvider
    from providers.social_data import SyntheticSocialDataProvider
    from simulation.clock import SimulationClock
    from simulation.generators.builtin import MacroGenerator, MarketGenerator, SocialGenerator
    from simulation.generators.orchestrator import Orchestrator
    from simulation.world import ContinuousWorld

    wall = datetime(2026, 6, 1, 12, 0, tzinfo=tz.utc)
    clock = SimulationClock(epoch=datetime(2026, 1, 5, 16, 0, tzinfo=tz.utc), scale=24,
                            started_at=wall)
    world = ContinuousWorld(Orchestrator(
        clock,
        [MarketGenerator(SyntheticMarketDataProvider(seed=42)),
         SocialGenerator(SyntheticSocialDataProvider(seed=7)),
         MacroGenerator(seed=1)],
        subjects=("SYN1", "SYN2"),
    ), clock)

    produced = [obs for tick in world.run_until(wall + timedelta(minutes=10), step_seconds=30)
                for obs in tick.observations]
    stored = history.ingest_observations(store, produced, history.SIMULATED, source="baseline world")

    assert stored == len(produced) > 0
    assert history.summary(store)[history.SIMULATED]["observations"] == stored


def test_an_ingested_world_keeps_both_timestamps(store):
    """The pair survives ingestion, which is the only reason as-of means anything
    afterwards. A corpus that kept one timestamp would be a corpus that could not
    be read as of a moment."""
    history.record(
        store, domain=history.SIMULATED, data_class="cpi", subject="US",
        effective_at=Q1, knowable_at=APRIL, value={"surprise": 0.3}, source="macro",
    )
    row = history.as_of(store, APRIL, [history.SIMULATED])[0]

    assert row["effective_at"] == Q1.isoformat()
    assert row["knowable_at"] == APRIL.isoformat()
    assert row["knowable_at"] > row["effective_at"]


def test_ingestion_names_its_domain_rather_than_inferring_it(store):
    with pytest.raises(ValueError, match="unknown domain"):
        history.ingest_observations(store, [], "generated", source="x")
