"""The clock archetypes, and which one each class of market data keeps.

Split out from `simulation/clock.py` because the clock is a mechanism and this is
a taxonomy: the mechanism changes rarely, the taxonomy grows every time the
organization learns to consume something new.

**Archetype-first, deliberately.** Roughly a hundred and fifty data types reduce
to seventeen arrival patterns, so a new data type costs one entry here rather
than a design conversation. Grouping by asset class instead - the obvious
choice - puts an ETF and a mutual fund together, which hold identical assets and
keep completely different clocks, and hides the only distinction that changes how
the system must treat them.

See docs/MARKET_DATA_TAXONOMY.md for the full inventory and the traps.

Internal rationale: INT-PHIL-0022
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

# --- archetypes -------------------------------------------------------------

CONTINUOUS = "continuous"                    # constant while its session is open
CONTINUOUS_247 = "continuous_247"            # breaks briefly or not at all
WINDOWED = "windowed"                        # only inside a narrow daily window
DAILY_CLOSE = "daily_close"                  # one value, struck at the close
DAILY_LAGGED = "daily_lagged"                # one per day, next morning
WEEKLY = "weekly"                            # same weekday, same time
WEEKLY_AS_OF = "weekly_as_of"                # weekly, describing an earlier date
SEMI_MONTHLY = "semi_monthly"                # twice a month, published later
PERIODIC = "periodic"                        # monthly or quarterly on a calendar
TWO_VINTAGE = "two_vintage"                  # preliminary then final, both acted on
REVISED = "revised"                          # successive estimates of one period
EVENT_FILED = "event_filed"                  # unpredictable, filed to a deadline
ANNOUNCED_EFFECTIVE = "announced_effective"  # two dates, and the gap is tradeable
SPORADIC = "sporadic"                        # irregular; absence is information
IRREGULAR = "irregular"                      # no calendar at all
SCHEDULED = "scheduled"                      # a known list of dates
STATIC = "static"                            # seldom, and each change matters
APPRAISAL = "appraisal"                      # estimated, not transacted

ARCHETYPES = (
    CONTINUOUS, CONTINUOUS_247, WINDOWED, DAILY_CLOSE, DAILY_LAGGED, WEEKLY,
    WEEKLY_AS_OF, SEMI_MONTHLY, PERIODIC, TWO_VINTAGE, REVISED, EVENT_FILED,
    ANNOUNCED_EFFECTIVE, SPORADIC, IRREGULAR, SCHEDULED, STATIC, APPRAISAL,
)

# Values that are estimates rather than transactions. Measured volatility
# understates the real thing and correlations against continuously priced assets
# are biased toward zero, so a consumer has to be able to ask rather than
# discovering it in a risk number that looked reassuring.
SMOOTHED = frozenset({APPRAISAL, SPORADIC})

# Where a missing value is a finding rather than a gap in the feed. A bond that
# did not trade, a filing that is late, an expected release that never appeared -
# each is informative, and each looks identical to a broken pipe unless the
# system can tell them apart.
ABSENCE_IS_DATA = frozenset({SPORADIC, EVENT_FILED, SCHEDULED, WINDOWED})


@dataclass(frozen=True)
class Cadence:
    """How one class of market data arrives.

    `publication_lag` is the gap between what a datum describes and when the
    world could know it. Zero for anything traded, substantial for anything
    measured - a home price index describes a month that ended two months
    earlier. Modelling it is the difference between a simulation that teaches the
    organization to wait for confirmation and one that quietly hands it the
    future.

    `revisions` is how often a figure is restated. A series is therefore a value
    per *(date, vintage)* rather than per date: a decision taken on the first GDP
    print was taken without the other two, and grading it against the final
    revision judges it on information it could not have had."""

    name: str
    kind: str
    session: str
    interval: timedelta | None = None
    publication_lag: timedelta = timedelta(0)
    revisions: int = 0
    note: str = ""

    @property
    def is_smoothed(self) -> bool:
        return self.kind in SMOOTHED

    @property
    def absence_is_data(self) -> bool:
        return self.kind in ABSENCE_IS_DATA


D = timedelta(days=1)


def _c(name: str, kind: str, session: str, **kwargs) -> Cadence:
    return Cadence(name, kind, session, **kwargs)


CADENCES: dict[str, Cadence] = {
    # --- traded, continuous -------------------------------------------------
    "equity_price": _c("equity_price", CONTINUOUS, "equity"),
    "option_surface": _c("option_surface", CONTINUOUS, "equity"),
    "etf_price": _c("etf_price", CONTINUOUS, "equity"),
    "index_price": _c("index_price", CONTINUOUS, "equity"),
    "government_yield": _c("government_yield", CONTINUOUS, "bond"),
    "commodity_price": _c("commodity_price", CONTINUOUS, "futures"),
    "futures_price": _c("futures_price", CONTINUOUS, "futures"),
    "fx_rate": _c("fx_rate", CONTINUOUS, "fx"),
    "crypto_price": _c("crypto_price", CONTINUOUS_247, "always"),
    "volatility_index": _c("volatility_index", CONTINUOUS, "equity"),

    # --- microstructure -----------------------------------------------------
    "quote_nbbo": _c("quote_nbbo", CONTINUOUS, "equity"),
    "order_book_depth": _c("order_book_depth", CONTINUOUS, "equity"),
    "trade_print": _c("trade_print", CONTINUOUS, "equity"),
    "auction_imbalance": _c("auction_imbalance", WINDOWED, "equity",
                            note="published only in the minutes before the open and close"),

    # --- traded, thin -------------------------------------------------------
    "corporate_bond_price": _c("corporate_bond_price", SPORADIC, "bond",
                               note="may not print for days; staleness is information"),
    "municipal_bond_price": _c("municipal_bond_price", SPORADIC, "bond"),
    "cds_spread": _c("cds_spread", SPORADIC, "bond"),

    # --- struck once a day --------------------------------------------------
    "mutual_fund_nav": _c("mutual_fund_nav", DAILY_CLOSE, "equity",
                          note="no intraday value exists to quote"),
    "index_fund_nav": _c("index_fund_nav", DAILY_CLOSE, "equity"),
    "settlement_price": _c("settlement_price", DAILY_CLOSE, "futures"),
    "credit_spread": _c("credit_spread", DAILY_CLOSE, "bond"),

    # --- daily, available the next morning ----------------------------------
    "overnight_rate": _c("overnight_rate", DAILY_LAGGED, "none", publication_lag=1 * D,
                         note="SOFR and EFFR publish the following business morning"),
    "options_open_interest": _c("options_open_interest", DAILY_LAGGED, "none", publication_lag=1 * D),
    "borrow_rate": _c("borrow_rate", DAILY_LAGGED, "none", publication_lag=1 * D),
    "etf_creation_redemption": _c("etf_creation_redemption", DAILY_LAGGED, "none", publication_lag=1 * D),

    # --- weekly -------------------------------------------------------------
    "jobless_claims": _c("jobless_claims", WEEKLY, "none", interval=7 * D, publication_lag=5 * D),
    "energy_inventories": _c("energy_inventories", WEEKLY, "none", interval=7 * D, publication_lag=4 * D),
    "mortgage_rate_survey": _c("mortgage_rate_survey", WEEKLY, "none", interval=7 * D),
    "central_bank_balance_sheet": _c("central_bank_balance_sheet", WEEKLY, "none", interval=7 * D),
    "commitments_of_traders": _c("commitments_of_traders", WEEKLY_AS_OF, "none",
                                 interval=7 * D, publication_lag=3 * D,
                                 note="reported Friday, as of the preceding Tuesday"),

    # --- semi-monthly -------------------------------------------------------
    "short_interest": _c("short_interest", SEMI_MONTHLY, "none", interval=15 * D, publication_lag=8 * D),
    "fails_to_deliver": _c("fails_to_deliver", SEMI_MONTHLY, "none", interval=15 * D, publication_lag=15 * D),

    # --- monthly and quarterly ---------------------------------------------
    "employment": _c("employment", PERIODIC, "none", interval=30 * D, publication_lag=7 * D, revisions=2,
                     note="revised in each of the two following months"),
    "cpi": _c("cpi", PERIODIC, "none", interval=30 * D, publication_lag=14 * D),
    "ppi": _c("ppi", PERIODIC, "none", interval=30 * D, publication_lag=14 * D),
    "pce": _c("pce", PERIODIC, "none", interval=30 * D, publication_lag=30 * D),
    "retail_sales": _c("retail_sales", PERIODIC, "none", interval=30 * D, publication_lag=16 * D),
    "industrial_production": _c("industrial_production", PERIODIC, "none", interval=30 * D, publication_lag=16 * D),
    "housing_starts": _c("housing_starts", PERIODIC, "none", interval=30 * D, publication_lag=18 * D),
    "purchasing_managers_index": _c("purchasing_managers_index", PERIODIC, "none",
                                    interval=30 * D, publication_lag=1 * D),
    "margin_debt": _c("margin_debt", PERIODIC, "none", interval=30 * D, publication_lag=21 * D),
    "home_price_index": _c("home_price_index", PERIODIC, "none", interval=30 * D, publication_lag=60 * D,
                           note="describes a month that ended two months earlier"),
    "consumer_sentiment": _c("consumer_sentiment", TWO_VINTAGE, "none",
                             interval=30 * D, publication_lag=10 * D, revisions=1,
                             note="preliminary mid-month, final at month end; both acted on"),
    "gdp": _c("gdp", REVISED, "none", interval=91 * D, publication_lag=28 * D, revisions=2,
              note="advance, second and third estimates"),
    "earnings": _c("earnings", PERIODIC, "none", interval=91 * D, publication_lag=21 * D),
    "financial_statement": _c("financial_statement", PERIODIC, "none",
                              interval=91 * D, publication_lag=40 * D, revisions=1,
                              note="restatements re-report a period already published"),
    "institutional_holdings": _c("institutional_holdings", PERIODIC, "none",
                                 interval=91 * D, publication_lag=45 * D,
                                 note="13F; may describe positions closed months earlier"),
    "private_asset_mark": _c("private_asset_mark", APPRAISAL, "none",
                             interval=91 * D, publication_lag=45 * D,
                             note="appraised rather than traded; understates volatility"),

    # --- events -------------------------------------------------------------
    "insider_transaction": _c("insider_transaction", EVENT_FILED, "none", publication_lag=2 * D),
    "activist_stake": _c("activist_stake", EVENT_FILED, "none", publication_lag=10 * D),
    "policy_rate": _c("policy_rate", SCHEDULED, "none", interval=45 * D),
    "policy_minutes": _c("policy_minutes", SCHEDULED, "none", interval=45 * D, publication_lag=21 * D),
    "treasury_auction": _c("treasury_auction", SCHEDULED, "none", interval=7 * D),
    "index_membership_change": _c("index_membership_change", ANNOUNCED_EFFECTIVE, "none",
                                  note="announced, effective later; the gap is heavily traded"),
    "dividend": _c("dividend", ANNOUNCED_EFFECTIVE, "none",
                   note="declaration, ex, record and payment are four distinct dates"),
    "corporate_action": _c("corporate_action", ANNOUNCED_EFFECTIVE, "none"),
    "merger_event": _c("merger_event", ANNOUNCED_EFFECTIVE, "none"),
    "rating_action": _c("rating_action", IRREGULAR, "none"),
    "news_item": _c("news_item", IRREGULAR, "always"),
    "social_post": _c("social_post", IRREGULAR, "always"),
    "analyst_revision": _c("analyst_revision", IRREGULAR, "none"),
    "central_bank_speech": _c("central_bank_speech", IRREGULAR, "none"),
    "weather_observation": _c("weather_observation", CONTINUOUS_247, "always"),

    # --- reference ----------------------------------------------------------
    # Boring until it is wrong, and then it is wrong everywhere at once.
    "security_master": _c("security_master", STATIC, "none"),
    "sector_classification": _c("sector_classification", STATIC, "none"),
    "trading_calendar": _c("trading_calendar", STATIC, "none"),
    "shares_outstanding": _c("shares_outstanding", STATIC, "none"),
}


def by_archetype(kind: str) -> list[str]:
    return sorted(name for name, cadence in CADENCES.items() if cadence.kind == kind)


def lagged() -> list[str]:
    """Data classes where effective and knowable dates differ.

    The set that exercises the lookahead guard, and the set most likely to be
    used wrongly."""
    return sorted(name for name, cadence in CADENCES.items() if cadence.publication_lag > timedelta(0))
