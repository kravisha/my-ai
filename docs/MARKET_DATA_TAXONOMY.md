# Market Data Taxonomy

An inventory of the data an analysis organization can obtain from markets, organised by **how it
arrives in time** rather than by asset class.

## Why organised this way

Asset class is the obvious grouping and the wrong one. An ETF and a mutual fund can hold identical
assets and keep completely different clocks — one trades continuously, the other is struck once at the
close and has no intraday value to quote. A REIT and an NCREIF index describe the same commercial
buildings; one reprices every second and the other four times a year, by appraisal. Grouping by what
the data is *about* puts those pairs together and hides the only difference that changes how the
system must handle them.

Grouping by arrival pattern also bounds the work. There are hundreds of data types and roughly
**seventeen arrival patterns**. Once the patterns are modelled, a new data type costs one registry
entry rather than a design conversation.

---

## 1. The clock archetypes

| # | Archetype | Behaviour | Examples |
|---|---|---|---|
| 1 | **Continuous, session-bound** | Updates constantly while its market is open | Equity and ETF prices, listed options, index futures |
| 2 | **Continuous, near-24h** | Breaks briefly or not at all | FX spot, most futures, crypto |
| 3 | **Windowed** | Published only inside a narrow daily window | Opening and closing auction imbalances |
| 4 | **Struck at close** | Exactly one value per day, computed at the close | Mutual fund NAV, official settlement prices |
| 5 | **Daily, published next morning** | One value per day, available the following business day | SOFR, EFFR, most reference rates |
| 6 | **Weekly, scheduled** | Same weekday, same time | Jobless claims, EIA inventories, Freddie Mac mortgage survey |
| 7 | **Weekly, as-of-earlier** | Published weekly, describing an earlier date | CFTC Commitments of Traders |
| 8 | **Semi-monthly, lagged** | Twice a month, published a week or so later | Short interest, fails to deliver |
| 9 | **Monthly, lagged** | Once a month for the prior month | CPI, PPI, employment, PCE, housing starts |
| 10 | **Monthly, two vintages** | Preliminary then final, both actionable | University of Michigan sentiment |
| 11 | **Quarterly, revised** | Several successive estimates of one period | GDP (advance, second, third) |
| 12 | **Quarterly, heavily lagged** | Published long after the period it describes | 13F holdings (45 days after quarter end) |
| 13 | **Event, filed to a deadline** | Occurs unpredictably, disclosed within a fixed window | Form 4 insider trades (2 business days), 13D (10 days) |
| 14 | **Announced then effective** | Two dates, and the gap is itself tradeable | Index add/delete, dividends, M&A completion |
| 15 | **Sporadic** | Trades irregularly; absence is information | Corporate and municipal bonds, small-cap options |
| 16 | **Irregular / unscheduled** | No calendar at all | News, ratings actions, central-bank speeches, geopolitical events |
| 17 | **Static, rarely amended** | Changes seldom, and each change matters a lot | Security master, sector classification, index membership |

An eighteenth deserves separate mention because it is not really a price at all:

| 18 | **Appraisal / smoothed** | Valued by estimate rather than transaction; autocorrelated and understates volatility | Private real estate marks, private equity NAVs |

---

## 2. Inventory by category

### 2.1 Traded prices

*Archetypes 1, 2, 15.*

- **Equities** — common, preferred, ADRs, dual-listed lines
- **Funds that trade** — ETFs, ETNs, closed-end funds (which carry a premium/discount to NAV worth
  observing in its own right)
- **Listed options** — the full surface: strikes × expiries × calls/puts, per underlying. Liquid
  near-the-money strikes are archetype 1; deep wings are archetype 15
- **Futures** — equity index, rates, commodity, FX, crypto; plus options on futures
- **FX** — spot, forwards, non-deliverable forwards, cross rates
- **Government bonds** — on-the-run continuous, off-the-run considerably thinner
- **Corporate bonds** — sporadic; a given issue may not print for days
- **Municipal bonds** — more sporadic still
- **Convertibles**, **preferreds**, **structured notes**
- **Swaps** — interest rate, credit default (single name and indices), dealer-quoted
- **Crypto** — 24/7, with no close to strike a NAV against

### 2.2 Derived from traded prices

*Same clock as the source, but computed — so a derivation error propagates silently.*

- OHLCV bars at any resolution; VWAP, TWAP
- **Implied volatility surface** and the greeks (the current system's only market input)
- **Yield curves** bootstrapped from bond prices; TIPS breakevens
- **Credit spreads** — bond yield less a benchmark; OAS
- **Volatility indices** — VIX and its complex (VIX9D, VIX3M, VVIX), SKEW, MOVE for rates
- **Realised volatility** — window-dependent, so the window is part of the definition
- Correlation and covariance matrices; beta; factor loadings

### 2.3 Market microstructure

*Archetypes 1 and 3. Sub-second, session-bound, and by far the highest volume.*

- **Level 1** — national best bid and offer with sizes
- **Level 2** — depth of book by price level
- **Level 3 / MBO** — individual orders, add/modify/cancel
- **Trade prints** with condition codes: odd lot, late, out-of-sequence, off-exchange
- **Quote conditions and halts** — including limit-up/limit-down bands
- **Auction imbalances** — archetype 3: published only inside a short window before the open and
  close, and unavailable outside it
- **Venue analysis** — lit versus dark share, exchange breakdown
- **Odd-lot activity** — historically excluded from the tape, informative on retail behaviour

### 2.4 Positioning and flow

*Archetypes 5–13. This is where two-timestamp discipline matters most, because almost everything here
describes a date well before its publication.*

| Data | Archetype | Effective vs knowable |
|---|---|---|
| Options open interest | 5 | Prior session, available next morning |
| Short interest | 8 | Semi-monthly settlement date, published ~a week later |
| Fails to deliver | 8 | Semi-monthly, lagged |
| CFTC Commitments of Traders | 7 | **As of Tuesday, published Friday afternoon** |
| 13F institutional holdings | 12 | **Quarter end, published up to 45 days later** |
| 13D / 13G stakes | 13 | Crossing event, filed within a deadline |
| Form 4 insider trades | 13 | Transaction date, filed within 2 business days |
| ETF creations / redemptions | 5 | Prior day |
| Fund flows | 6 / 9 | Weekly or monthly, lagged |
| Margin debt | 9 | Monthly, lagged |
| Securities lending — borrow rate and availability | 5 | Daily, some intraday |

**13F is the clearest warning in the whole taxonomy.** A position it discloses may have been closed
four months before anyone can read about it. Treating it as current holdings is not a small error.

### 2.5 Corporate fundamentals and events

*Archetypes 11, 13, 14.*

- **Earnings** — scheduled and pre-announced; the announcement date itself is data
- **Guidance**, and guidance revisions
- **Financial statements** — 10-Q, 10-K, 8-K, each with its own filing deadline
- **Restatements** — the same period, re-reported. See §3.2
- **Dividends** — *four distinct dates*: declaration, ex-dividend, record, payment. Archetype 14, and
  the ex-date is the one that moves the price
- **Splits and reverse splits** — announced then effective
- **Buybacks** — announced as authorisation; actual execution disclosed quarterly and in arrears
- **M&A** — announcement, regulatory milestones, completion or termination
- **Spin-offs, rights issues, tender offers**
- **Index additions and deletions** — announced, effective later; the gap is heavily traded
- **Credit rating actions** — and the watch/outlook changes that precede them
- **Bankruptcy, delisting, halts**
- **Share count and float changes**
- **Lock-up expirations** — scheduled from the IPO date

### 2.6 Macro and economic releases

*Archetypes 6, 9, 10, 11.*

- **Labour** — employment report (monthly, and revised for two subsequent months), jobless claims
  (weekly), JOLTS, ADP
- **Inflation** — CPI, PPI, PCE, import/export prices
- **Growth** — GDP (three estimates), industrial production, retail sales, durable goods
- **Housing** — starts, permits, existing and new home sales, NAHB
- **Surveys** — ISM manufacturing and services, regional Fed surveys, PMIs, consumer confidence,
  University of Michigan sentiment (**preliminary and final — archetype 10**)
- **Trade** — balance, current account
- **Central bank** — policy decisions (scheduled, ~8/year), statements, minutes (~3 weeks later),
  projections/dot plot (quarterly), speeches (archetype 16), balance sheet (weekly)
- **Fiscal** — Treasury auction calendar, results, refunding announcements, budget balance

### 2.7 Rates and credit

- Policy rates; overnight rates (SOFR, EFFR — archetype 5); term rates
- Treasury curve; swap rates and swap spreads; basis
- CDS — single name and indices; investment-grade and high-yield spread indices
- Repo — general collateral versus specials; a name going special is a signal in itself
- Commercial paper; mortgage rates (weekly survey plus daily indicative)

### 2.8 Commodities and real assets

- Energy — crude, refined products, natural gas, power; **EIA inventories are archetype 6**, weekly
  on a fixed day and time, and move the market hard
- Metals — precious and base; warehouse stocks
- Agriculture — with USDA reports on a published calendar
- Shipping and freight — Baltic Dry, container rates, AIS vessel tracking
- **Housing** — Case-Shiller (monthly, ~2-month lag), FHFA, vendor indices with shorter lags
- **Commercial real estate** — REIT prices (archetype 1) against NCREIF appraisals (archetype 18) for
  the same underlying buildings

### 2.9 Alternative data

*Mostly archetypes 5, 6, 9, 16. Vendor-dependent, and the lag is usually the product.*

- News feeds, machine-readable headlines, embargo timing
- Social and message-board sentiment (the current system's second input)
- **Analyst estimates and revisions** — consensus, dispersion, and the revision itself
- Analyst ratings and price-target changes
- Earnings call transcripts and their scheduled timing
- Web traffic, app downloads, search interest
- Card and transaction panels; receipt panels
- Job postings; employee reviews; headcount
- Satellite and geospatial — parking lots, storage tanks, crop health
- Weather and forecasts — directly relevant to energy, agriculture, utilities, insurance
- Patents, clinical trial registries, regulatory dockets, government contracts

### 2.10 Reference and static data

*Archetype 17. Boring until it is wrong, and then it is wrong everywhere at once.*

- Security master — CUSIP, ISIN, FIGI, ticker, listing venue, and **ticker changes over time**
- Corporate action history — the adjustment factors every price series depends on
- Sector and industry classification, which is periodically restructured
- Index membership, historical as well as current
- Shares outstanding and free float
- Contract specifications, tick sizes, lot sizes
- **Trading calendars and holidays — per market and per country**
- Borrow classification: easy or hard to borrow

---

## 3. The traps

These are the failure modes worth designing against, not incidental caveats. Each one produces results
that look correct.

### 3.1 Publication lag is not a detail

Every entry in §2.4 and §2.6 describes a moment earlier than the moment it becomes available. Using a
figure at its effective date rather than its knowable date is lookahead bias: it inflates every result
it touches and **is invisible in the output**. A backtest built on it looks excellent and means
nothing.

This is why the clock carries two timestamps rather than one, and why the guard lives in the clock
rather than in each consumer.

### 3.2 Revisions and vintages

GDP is published three times. Payrolls are revised for two subsequent months. Seasonal adjustment
factors are re-benchmarked annually, changing history. Company financials are restated.

So a series is not a value per date — it is a value per *(date, vintage)*. A decision made on the first
print was made without the later ones, and evaluating it against the final revision judges it on
information it could not have had.

### 3.3 Point-in-time fundamentals

The same problem in equity data. A screen run over restated financials assumes knowledge of a
restatement that had not happened. Point-in-time databases exist precisely because the naive version is
so misleading.

### 3.4 Survivorship and look-through

A universe built from currently listed names silently excludes everything that failed. Index membership
must be historical. Delisted tickers get reused.

### 3.5 Multi-date events

Dividends have four dates; index changes and M&A have at least two. Collapsing them to one loses the
part that matters — for a dividend the ex-date moves the price, not the payment date.

### 3.6 Stale prices understate risk

An illiquid bond or an appraised property shows low measured volatility because it is not being
repriced, not because it is not risky. Correlations computed across assets on different clocks are
biased toward zero. Archetypes 15 and 18 need this stated wherever they are consumed.

### 3.7 Time zones, daylight saving and settlement

Release times are stated in local market time; 08:30 Eastern is not a fixed UTC moment. Trading
calendars differ by market and country. Trade date is not settlement date.

### 3.8 Absence is data

A bond that has not traded, a security that is halted, a filing that is late, an expected release that
does not appear — each is informative, and each looks identical to a gap in the feed unless the system
distinguishes them.

---

## 4. Where this system currently stands

| | |
|---|---|
| Consumed today | Option implied-volatility surfaces (synthetic); social/message-board posts (synthetic) |
| Modelled in the clock registry | ~18 data classes across 5 archetypes |
| Catalogued here | ~150 data types across 18 archetypes |

The gap is deliberate. The point of the taxonomy is not to consume everything — it is to make the
registry archetype-first, so that adding a data type is a line rather than a redesign, and so that
nothing is added without its clock being stated.

## 5. Suggested order

1. **Archetypes into the registry**, and existing entries reclassified against them.
2. **The archetypes the current pipeline already implies but does not model**: daily-struck closes,
   windowed auction data, sporadic instruments where absence is meaningful.
3. **Positioning and flow (§2.4)** — the richest source of two-timestamp cases, and therefore the
   best exercise of the lookahead guard.
4. **Macro releases (§2.6)** — scheduled, revised, and the natural driver of causally coherent world
   events.
5. **Corporate events (§2.5)** — multi-date, which the current model cannot express at all.
6. Everything else as analysis demands it.

Precision on individual release times, lags and calendars should be verified against a vendor
specification before any of this is used against real data. The archetypes are stable; the specific
lags quoted here are accurate enough to design against and not accurate enough to trade on.
