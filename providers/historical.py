"""The Historical Market Data Engine: real past data, ingested and replayable.

Addendum 20 §2B, and Scoreboard #4's reasoning for building this engine before
Live: it is replayable, needs no credentials, and proves the canonical contract
against data the synthetic provider did not shape.

## Files are the engine; the network is an errand

The core of this module reads CSV files. That is a design position, not a
shortcut: replay - the engine's defining obligation - requires a corpus that is
*held*, so the durable artifact is the file plus the rows ingested from it, and a
network fetch is merely one way a file comes to exist. It also keeps the engine
whole when the vendor is down, which is the same §23 isolation argument the
Gateway was built under.

Two fetch adapters, and the story of why there are two is the §1 vendor-
independence argument made flesh:

- **Stooq** (https://stooq.com) was chosen first as a keyless CSV source - and on
  first live use turned out to sit behind a JavaScript proof-of-work wall that
  404s programmatic clients. Automating around an anti-bot control is not
  something this project does, so the fetcher stays only as an honest failure:
  it names the wall and points at the file path. A person can download in a
  browser and `ingest_file` the result, which the wall's owners plainly permit.
- **FRED** (https://fred.stlouisfed.org) is the adapter that works unattended:
  genuinely public, keyless CSV, decades deep. It serves series rather than
  equities - S&P 500 level, treasury yields - which map onto cadences the
  taxonomy already carries (`index_price`, `government_yield`).

Alternatives considered and rejected: scraping libraries such as yfinance (a
terms-of-service and breakage surface, and §1 wants thin adapters rather than
vendor coupling), and bundling a dataset in the repository (market-data
redistribution licensing, in a public repo). No fetch adapter is exercised by the
default test suite, because a suite that needs a vendor up fails for reasons that
are not defects.

## Symbols are resolved as of the observation's own date

Every row's symbol goes through backend/identifiers.py with the row's date, not
today's - the exact case the dated mapping was built for. A 2019 row for a ticker
that changed hands in 2023 must attribute to the company that held it in 2019.
Unknown symbols get an entity created (`ensure_security`), because the first
ingest of a new instrument is the ordinary way instruments arrive.

## Bad rows are counted, not fatal

A historical file is someone else's export: rows go missing, headers drift,
half-days produce zero volume. One malformed row must not abandon an ingest, and
an ingest that cannot say "kept 240, skipped 3, and here is the first bad line"
cannot be trusted about the 240 either.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from backend import identifiers, observations
from backend.canonical import Observation, Provenance
from backend.db import Database

# The one data class this engine ingests today. A daily bar is an end-of-day
# sample of a class the taxonomy already has; a parallel "equity_bar_daily"
# cadence would split one instrument's history across two names.
DATA_CLASS = "equity_price"

# Daily bars describe the session; the moment the fact is true is the close.
# US equities close 16:00 America/New_York - stored explicitly in UTC (21:00
# during daylight time is *not* assumed; 21:00 UTC covers EDT, and being an hour
# late in winter is conservative in exactly the safe direction for a lookahead
# guard: never early).
SESSION_CLOSE_UTC = "21:00:00+00:00"

REQUIRED_COLUMNS = ("Date", "Open", "High", "Low", "Close")


class HistoricalError(ValueError):
    pass


@dataclass
class IngestReport:
    """What an ingest actually did, row by accountable row."""

    symbol: str
    entity_id: str
    source: str
    kept: int = 0
    already_held: int = 0
    skipped: int = 0
    problems: list[str] = field(default_factory=list)

    def as_record(self) -> dict:
        return {
            "symbol": self.symbol,
            "entity_id": self.entity_id,
            "source": self.source,
            "kept": self.kept,
            "already_held": self.already_held,
            "skipped": self.skipped,
            "problems": self.problems[:10],
        }


def parse_daily_csv(text: str, symbol: str, source: str) -> tuple[list[dict], list[str]]:
    """Stooq-shaped daily CSV (Date,Open,High,Low,Close,Volume) into raw bar
    dicts. Returns (bars, problems) - parsing is separated from ingest so a file
    can be inspected without a database, and problems are per-row strings a
    report can carry."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HistoricalError(f"{source}: empty file, no header row")
    missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
    if missing:
        raise HistoricalError(
            f"{source}: header lacks {missing}; this reader understands the Stooq daily shape "
            f"(Date,Open,High,Low,Close,Volume)"
        )

    bars: list[dict] = []
    problems: list[str] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            date = (row["Date"] or "").strip()
            if len(date) != 10 or date[4] != "-" or date[7] != "-":
                raise ValueError(f"date {date!r} is not YYYY-MM-DD")
            bar = {
                "date": date,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]) if (row.get("Volume") or "").strip() else None,
                "interval": "1d",
                "symbol_as_recorded": symbol,
            }
            if not (bar["low"] <= bar["open"] <= bar["high"]
                    and bar["low"] <= bar["close"] <= bar["high"]):
                raise ValueError(
                    f"impossible bar: open {bar['open']} / close {bar['close']} outside "
                    f"[{bar['low']}, {bar['high']}]"
                )
            bars.append(bar)
        except (KeyError, TypeError, ValueError) as bad:
            problems.append(f"line {line_number}: {bad}")
    return bars, problems


def ingest_daily_bars(conn: Database, text: str, symbol: str, source: str) -> IngestReport:
    """One file of daily bars into the store, as canonical historical
    observations.

    The provenance origin is fixed at 'historical' with no parameter to override
    it - the same structural §15 stance the synthetic provider takes, pointing the
    other way."""
    bars, problems = parse_daily_csv(text, symbol, source)

    # Resolution is dated per-row below; entity creation, if needed, happens once.
    entity_id = identifiers.ensure_security(conn, symbol, source=source)

    report = IngestReport(symbol=symbol, entity_id=entity_id, source=source,
                          skipped=len(problems), problems=problems)
    for bar in bars:
        observed_at = f"{bar['date']}T{SESSION_CLOSE_UTC}"
        row_entity = identifiers.resolve(conn, "symbol", symbol, as_of=observed_at) or entity_id
        observation = Observation(
            entity_id=row_entity,
            data_class=DATA_CLASS,
            observed_at=observed_at,
            payload=bar,
            provenance=Provenance(origin="historical", source=source),
        )
        if observations.store(conn, observation):
            report.kept += 1
        else:
            report.already_held += 1
    return report


def ingest_file(conn: Database, path: str | Path, symbol: str) -> IngestReport:
    path = Path(path)
    if not path.exists():
        raise HistoricalError(f"no file at {path}")
    return ingest_daily_bars(
        conn, path.read_text(encoding="utf-8"), symbol, source=f"file:{path.name}"
    )


# --- the one fetch adapter ------------------------------------------------


def stooq_url(symbol: str, market_suffix: str = "us") -> str:
    """Stooq's daily-history CSV endpoint for one symbol. Building the URL is
    separated from fetching so the mapping is testable without a network."""
    cleaned = symbol.strip().lower()
    if not cleaned:
        raise HistoricalError("a symbol is required")
    return f"https://stooq.com/q/d/l/?s={cleaned}.{market_suffix}&i=d"


def fetch_stooq(symbol: str, market_suffix: str = "us", timeout: float = 20.0) -> str:
    """Fetch one symbol's daily history from Stooq.

    Known, verified live on 2026-08-18: Stooq gates programmatic clients behind a
    JavaScript proof-of-work check - requests gets a 404, curl gets a challenge
    page. This project does not automate around anti-bot controls, so both
    outcomes raise with the legitimate alternative named rather than a bare HTTP
    error a caller would waste an afternoon on."""
    import requests

    WALL = (
        f"stooq.com gates automated access behind a browser-verification wall (seen as a 404 or "
        f"a JavaScript challenge page). Download the CSV in a browser - {stooq_url(symbol, market_suffix)} "
        f"- and ingest it with ingest_file(), or use the FRED adapter for series data."
    )
    response = requests.get(stooq_url(symbol, market_suffix), timeout=timeout)
    if response.status_code == 404:
        raise HistoricalError(WALL)
    response.raise_for_status()
    text = response.text
    if text.lstrip().lower().startswith("<"):
        raise HistoricalError(WALL)
    return text


def ingest_from_stooq(conn: Database, symbol: str, market_suffix: str = "us") -> IngestReport:
    text = fetch_stooq(symbol, market_suffix)
    return ingest_daily_bars(conn, text, symbol, source=f"stooq:{symbol.lower()}.{market_suffix}")


# --- FRED: the adapter that works unattended ------------------------------

# Which FRED series this engine understands, and what each is in the taxonomy.
# The cadence is looked up per series because an index level and a treasury
# yield are different data classes with their own clocks - one enumeration here
# would flatten a distinction simulation/cadences.py exists to keep.
FRED_SERIES = {
    "SP500": "index_price",
    "DGS10": "government_yield",
    "DGS2": "government_yield",
}


def fred_url(series_id: str) -> str:
    cleaned = series_id.strip().upper()
    if not cleaned:
        raise HistoricalError("a FRED series id is required")
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={cleaned}"


def parse_fred_csv(text: str, series_id: str, source: str) -> tuple[list[dict], list[str], int]:
    """FRED's two-column shape (observation_date,VALUE) into raw points.

    Returns (points, problems, empty). FRED marks a market holiday with "." -
    an explicit missing-value marker, not a malformed row, so those are counted
    separately rather than reported as problems: three thousand "problems" that
    are all Christmases would bury the one real corruption."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HistoricalError(f"{source}: empty file, no header row")
    if "observation_date" not in reader.fieldnames or len(reader.fieldnames) < 2:
        raise HistoricalError(
            f"{source}: header {reader.fieldnames} is not FRED's shape (observation_date,VALUE)"
        )
    value_column = [name for name in reader.fieldnames if name != "observation_date"][0]

    points: list[dict] = []
    problems: list[str] = []
    empty = 0
    for line_number, row in enumerate(reader, start=2):
        raw = (row.get(value_column) or "").strip()
        if raw == "." or raw == "":
            empty += 1
            continue
        try:
            date = (row["observation_date"] or "").strip()
            if len(date) != 10 or date[4] != "-" or date[7] != "-":
                raise ValueError(f"date {date!r} is not YYYY-MM-DD")
            points.append({"date": date, "value": float(raw), "series": series_id})
        except (KeyError, TypeError, ValueError) as bad:
            problems.append(f"line {line_number}: {bad}")
    return points, problems, empty


def ingest_fred_series(conn: Database, text: str, series_id: str, source: str) -> IngestReport:
    """One FRED series into the store, as canonical historical observations.

    The subject entity is the series itself, entity_type 'series' - an index
    level or a yield is observed like a security but is not a tradeable
    instrument. This replaces the earlier admitted misuse that minted these as
    'security'; rows created under the old type in scratch databases keep their
    recorded type, because identity rows record what was done, not what should
    have been."""
    series_id = series_id.strip().upper()
    if series_id not in FRED_SERIES:
        raise HistoricalError(
            f"unknown FRED series {series_id!r}; this engine understands "
            f"{', '.join(sorted(FRED_SERIES))}. Adding one is a mapping entry plus the "
            f"knowledge of which data class it is."
        )
    data_class = FRED_SERIES[series_id]
    points, problems, empty = parse_fred_csv(text, series_id, source)

    entity_id = identifiers.ensure_entity(conn, "symbol", series_id, "series", source=source)
    report = IngestReport(symbol=series_id, entity_id=entity_id, source=source,
                          skipped=len(problems), problems=problems)
    for point in points:
        observed_at = f"{point['date']}T{SESSION_CLOSE_UTC}"
        observation = Observation(
            entity_id=entity_id,
            data_class=data_class,
            observed_at=observed_at,
            payload=point,
            provenance=Provenance(origin="historical", source=source),
        )
        if observations.store(conn, observation):
            report.kept += 1
        else:
            report.already_held += 1
    return report


def fetch_fred(series_id: str, timeout: float = 30.0) -> str:
    """Network - not used by the default test suite."""
    import requests

    response = requests.get(fred_url(series_id), timeout=timeout)
    response.raise_for_status()
    return response.text


def ingest_from_fred(conn: Database, series_id: str) -> IngestReport:
    text = fetch_fred(series_id)
    return ingest_fred_series(conn, text, series_id, source=f"fred:{series_id.strip().upper()}")
