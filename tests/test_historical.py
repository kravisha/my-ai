"""The Historical Market Data Engine and the Data Store beneath it.

The engine's obligations, in the order they matter: real rows become canonical
observations that cannot lie about their origin; re-ingest converges instead of
duplicating; replay respects what was knowable when; and a symbol is resolved as
of the row's own date, not today's.
"""

import pytest

from backend import fi_db, identifiers, observations
from backend.canonical import ContractError, Observation, Provenance
from providers import historical

GOOD_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2024-01-02,185.0,186.5,184.2,186.0,50000000\n"
    "2024-01-03,186.0,187.0,185.1,185.5,42000000\n"
    "2024-01-04,185.5,186.2,183.9,184.0,47000000\n"
)


@pytest.fixture
def conn():
    connection = fi_db.get_connection(":memory:")
    fi_db.init_schema(connection)
    yield connection
    connection.close()


# --- Parsing: someone else's export, held to account ---------------------


def test_a_clean_file_parses_completely():
    bars, problems = historical.parse_daily_csv(GOOD_CSV, "AAPL", "file:t.csv")

    assert len(bars) == 3
    assert problems == []
    assert bars[0] == {
        "date": "2024-01-02", "open": 185.0, "high": 186.5, "low": 184.2,
        "close": 186.0, "volume": 50000000.0, "interval": "1d",
        "symbol_as_recorded": "AAPL",
    }


def test_bad_rows_are_counted_not_fatal():
    """One malformed row must not abandon an ingest, and the report has to name
    the line - an ingest that cannot account for its skips cannot be trusted
    about its keeps."""
    text = GOOD_CSV + "not-a-date,1,2,0.5,1.5,10\n2024-01-05,190.0,189.0,191.0,190.5,10\n"

    bars, problems = historical.parse_daily_csv(text, "AAPL", "file:t.csv")

    assert len(bars) == 3
    assert len(problems) == 2
    assert "line 5" in problems[0]
    assert "impossible bar" in problems[1], "high below low is data corruption, not a price"


def test_a_missing_volume_is_none_not_zero():
    """Zero volume is a fact (a halt); an empty field is an absence. Conflating
    them manufactures a fact."""
    text = "Date,Open,High,Low,Close,Volume\n2024-01-02,10,11,9,10.5,\n"

    bars, problems = historical.parse_daily_csv(text, "X", "file:t.csv")

    assert problems == []
    assert bars[0]["volume"] is None


def test_a_wrong_shaped_file_is_refused_with_the_expected_shape():
    with pytest.raises(historical.HistoricalError, match="Stooq daily shape"):
        historical.parse_daily_csv("Timestamp,Price\n1,2\n", "X", "file:t.csv")
    with pytest.raises(historical.HistoricalError, match="empty file"):
        historical.parse_daily_csv("", "X", "file:t.csv")


# --- Ingest: canonical, historical, idempotent ---------------------------


def test_ingest_produces_historical_observations_against_a_real_entity(conn):
    report = historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:t.csv")

    assert report.kept == 3 and report.skipped == 0
    assert identifiers.resolve(conn, "symbol", "AAPL") == report.entity_id

    [first, *_] = observations.replay(conn, report.entity_id, "equity_price")
    assert first.provenance.origin == "historical"
    assert first.provenance.source == "file:t.csv"
    assert first.observed_at == "2024-01-02T21:00:00+00:00"


def test_the_origin_cannot_be_overridden():
    """The same structural §15 stance the synthetic provider takes, pointing the
    other way: no parameter exists through which this engine's output could claim
    to be anything but historical."""
    import inspect

    for fn in (historical.ingest_daily_bars, historical.ingest_file):
        assert "origin" not in inspect.signature(fn).parameters
    assert 'origin="historical"' in inspect.getsource(historical.ingest_daily_bars)


def test_re_ingest_converges(conn):
    """A re-run after a crash, a refreshed download, an overlapping range - the
    normal cases. They must converge, not duplicate."""
    first = historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:t.csv")
    second = historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:t.csv")

    assert first.kept == 3
    assert (second.kept, second.already_held) == (0, 3)
    assert len(observations.replay(conn, first.entity_id, "equity_price")) == 3


def test_two_sources_for_the_same_fact_are_both_kept(conn):
    """Two vendors disagreeing about a close is information. Collapsing them
    would destroy the disagreement before anything could learn from it."""
    historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:vendor_a.csv")
    entity = identifiers.resolve(conn, "symbol", "AAPL")
    other = GOOD_CSV.replace("186.0,5", "186.1,5")
    historical.ingest_daily_bars(conn, other, "AAPL", source="file:vendor_b.csv")

    bars = observations.replay(conn, entity, "equity_price")
    assert len(bars) == 6
    assert {bar.provenance.source for bar in bars} == {"file:vendor_a.csv", "file:vendor_b.csv"}


def test_a_row_is_attributed_to_whoever_held_the_symbol_on_its_date(conn):
    """The reassigned-ticker case, at the ingest boundary - the reason
    identifiers.resolve takes a date at all. A 2019 row for a ticker that changed
    hands must not land on today's holder."""
    old_holder = identifiers.create_entity(conn, "security", display_name="Old Corp")
    identifiers.add_identifier(conn, old_holder, "symbol", "ACME", source="test",
                               valid_from="2019-01-01T00:00:00+00:00")
    identifiers.retire_identifier(conn, "symbol", "ACME", valid_to="2022-01-01T00:00:00+00:00")
    new_holder = identifiers.create_entity(conn, "security", display_name="New Corp")
    identifiers.add_identifier(conn, new_holder, "symbol", "ACME", source="test",
                               valid_from="2023-01-01T00:00:00+00:00")

    text = ("Date,Open,High,Low,Close,Volume\n"
            "2019-06-03,10,11,9,10.5,1000\n"       # Old Corp's era
            "2024-06-03,50,51,49,50.5,2000\n")     # New Corp's era
    historical.ingest_daily_bars(conn, text, "ACME", source="file:t.csv")

    assert len(observations.replay(conn, old_holder, "equity_price")) == 1
    assert observations.replay(conn, old_holder, "equity_price")[0].payload["close"] == 10.5
    assert len(observations.replay(conn, new_holder, "equity_price")) == 1


# --- Replay: bounded, clocked, origin-scoped -----------------------------


def test_replay_is_ordered_and_bounded(conn):
    report = historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:t.csv")

    bars = observations.replay(conn, report.entity_id, "equity_price",
                               start="2024-01-03T00:00:00+00:00")
    assert [bar.payload["date"] for bar in bars] == ["2024-01-03", "2024-01-04"]

    bars = observations.replay(conn, report.entity_id, "equity_price",
                               end="2024-01-03T23:59:59+00:00")
    assert [bar.payload["date"] for bar in bars] == ["2024-01-02", "2024-01-03"]


def test_replay_respects_the_clock_it_is_asked_at(conn):
    """The lookahead guard as a WHERE clause: training pretending to stand at
    Jan 3 midday must not see Jan 3's close."""
    report = historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:t.csv")

    seen = observations.replay(conn, report.entity_id, "equity_price",
                               as_knowable_by="2024-01-03T12:00:00+00:00")

    assert [bar.payload["date"] for bar in seen] == ["2024-01-02"]


def test_replay_can_refuse_synthetic_rows_sharing_the_table(conn):
    """The deliberate-mixing rule at the query: a historical consumer asks for
    ('historical',) and cannot silently pick up fixture data."""
    report = historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:t.csv")
    observations.store(conn, Observation(
        entity_id=report.entity_id, data_class="equity_price",
        observed_at="2024-01-05T21:00:00+00:00", payload={"close": 1.0},
        provenance=Provenance(origin="synthetic", source="fixture", run_id="r1"),
    ))

    assert len(observations.replay(conn, report.entity_id, "equity_price")) == 4
    only_real = observations.replay(conn, report.entity_id, "equity_price",
                                    origins=("historical",))
    assert len(only_real) == 3
    assert all(bar.provenance.origin == "historical" for bar in only_real)


def test_the_store_refuses_an_origin_the_contract_does_not_admit(conn):
    """§15 held by the table itself, because the table outlives every process
    that promised to behave."""
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO observations (entity_id, data_class, observed_at, knowable_at, "
            "payload, origin, source, captured_at) VALUES ('JE-000001', 'equity_price', "
            "'2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00', '{}', 'unknown', 's', 'now')"
        )


def test_a_replayed_observation_is_the_contract_type_with_its_guarantees(conn):
    report = historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:t.csv")

    [bar, *_] = observations.replay(conn, report.entity_id, "equity_price")

    assert isinstance(bar, Observation)
    assert bar.known_by("2024-01-02T21:00:00+00:00") is True
    assert bar.known_by("2024-01-02T20:59:59+00:00") is False
    with pytest.raises(Exception):
        bar.provenance.origin = "live"


def test_coverage_answers_what_is_held(conn):
    report = historical.ingest_daily_bars(conn, GOOD_CSV, "AAPL", source="file:t.csv")

    held = observations.coverage(conn, report.entity_id, "equity_price")

    assert held["historical"]["count"] == 3
    assert held["historical"]["first"].startswith("2024-01-02")
    assert held["historical"]["last"].startswith("2024-01-04")
    assert observations.coverage(conn, "JE-999999", "equity_price") is None


# --- The fetch adapter, without a network --------------------------------


def test_the_stooq_url_is_built_correctly():
    assert historical.stooq_url("AAPL") == "https://stooq.com/q/d/l/?s=aapl.us&i=d"
    assert historical.stooq_url("spy", "us") == "https://stooq.com/q/d/l/?s=spy.us&i=d"
    with pytest.raises(historical.HistoricalError):
        historical.stooq_url("  ")


# --- The FRED shape, without a network -----------------------------------


FRED_CSV = (
    "observation_date,DGS10\n"
    "2008-09-12,3.74\n"
    "2008-09-15,3.47\n"
    "2008-09-16,3.44\n"
    "2008-09-17,3.42\n"
)


def test_fred_series_parse_and_missing_markers_are_not_problems():
    """FRED marks holidays with "." - an explicit missing-value marker. Three
    thousand "problems" that are all Christmases would bury the one real
    corruption."""
    text = FRED_CSV + "2008-09-18,.\n2008-09-19,3.81\n"

    points, problems, empty = historical.parse_fred_csv(text, "DGS10", "fred:DGS10")

    assert len(points) == 5
    assert problems == []
    assert empty == 1
    assert points[0] == {"date": "2008-09-12", "value": 3.74, "series": "DGS10"}


def test_fred_ingest_lands_in_the_series_own_data_class(conn):
    """A treasury yield is not an equity price. The mapping is per series
    because one enumeration would flatten a distinction the taxonomy keeps."""
    report = historical.ingest_fred_series(conn, FRED_CSV, "DGS10", source="fred:DGS10")

    assert report.kept == 4
    held = observations.coverage(conn, report.entity_id, "government_yield")
    assert held["historical"]["count"] == 4
    assert observations.coverage(conn, report.entity_id, "equity_price") is None


def test_an_unknown_fred_series_is_refused_with_the_known_ones(conn):
    with pytest.raises(historical.HistoricalError, match="SP500"):
        historical.ingest_fred_series(conn, FRED_CSV, "MYSTERY", source="fred:MYSTERY")


def test_fred_urls_are_built_correctly():
    assert historical.fred_url("sp500") == "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"
    with pytest.raises(historical.HistoricalError):
        historical.fred_url("")
