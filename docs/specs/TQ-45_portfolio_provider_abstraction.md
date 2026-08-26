# TQ-45 — The `PortfolioProvider` Abstraction and Its Conformance Suite

**Implementation specification.** Status: SPECIFIED, not implemented (2026-08-26).

Written so a session with no prior context can build this without further design
work. Where a decision was made, it is recorded with its reasoning so it is not
silently re-litigated; where a question is genuinely open, §11 says so.

| | |
|---|---|
| **Source specification** | [`addenda/addendum_44_client_owned_holdings_superuser_portfolio.md`](../addenda/addendum_44_client_owned_holdings_superuser_portfolio.md) §6.1, §6.2, §6.3, §7, §15.3, §15.4, §17, §20 Phase 2 |
| **Dispositions** | [`SPEC_RECONCILIATION.md`](../SPEC_RECONCILIATION.md) §97, §99 |
| **Queue entry** | [`TASK_QUEUE.md`](../TASK_QUEUE.md) TQ-45 |
| **Depends on** | TQ-44 (§99, portfolios as owned entities) — done |
| **Blocks** | TQ-46, TQ-47, TQ-48, TQ-49 |

---

## 1. Objective

Put a broker-independent interface between the analysis subsystem and wherever
holdings come from, and prove it is a contract rather than a description by
writing the conformance suite before the second implementation exists.

On completion: `holdings.concentration` works off canonical holdings without
knowing their source; `SimulatedPortfolioProvider` satisfies a suite that
`SchwabPortfolioProvider` will inherit unchanged; and the holding shape is the
one addendum 44 §3.4 names.

## 2. Problem

Holdings have exactly one source today: the client says what they hold and
`holdings.record` writes it down (§96). That is honest and has no leak surface,
but it is the *only* shape the code can imagine. A brokerage account arrives as a
different thing entirely — accounts, balances, positions, a sync time, a
provider that can be down — and none of those have anywhere to live.

Addendum 44 §6.3 states the requirement precisely: simulation must implement the
same interface a brokerage provider will, so the switch is an adapter rather than
a rewrite.

**The trap is building the interface around the one implementation that exists.**
§15.4 is the countermeasure and it is the part worth building first: *one
conformance suite every provider must satisfy*. A contract with a single
implementation is a description of that implementation. The suite is what turns
it into a contract, and writing it while only the simulated provider exists is
what stops `SchwabPortfolioProvider` from discovering, a month from now, that the
"interface" encoded three assumptions only a local database could satisfy.

---

## 3. Design decisions

Decided. Do not re-open without recording a reason.

### 3.1 Build it as two increments, in this order

TQ-45 as queued contains a mechanical rename, a vocabulary reconciliation, a new
abstraction, and a demo rebuild. That is too much for one review, and mixing a
rename that touches every call site with a new interface makes both harder to
see.

- **TQ-45a — the canonical holding.** The field rename, the `asset_class`
  vocabulary (§11 Q1), and their migration. No new abstraction.
- **TQ-45b — the provider.** The `PortfolioProvider` protocol, the conformance
  suite, `SimulatedPortfolioProvider`, and the demo rebuild on top of it.

45a first, so the provider is written against the final holding shape once
rather than twice. This is the same reasoning that moved the rename out of TQ-44
(§3.9 there) — applied one level down.

Each is its own branch, PR and `SPEC_RECONCILIATION` §.

### 3.2 The provider takes a **resolved portfolio**, not an `account_ref`

The most important decision here, and a deliberate deviation from addendum 44 §7.

The addendum's conceptual interface is:

```
get_holdings(account_ref)
get_balances(account_ref)
get_positions(account_ref)
```

A public function that takes a bare reference string and returns holdings is
**exactly the second by-id retrieval path TQ-44 exists to prevent** — the one the
tripwire test scans for, and the one that was nearly written during TQ-44 itself
(§99). It would not look like a bypass when it was added. It would look like
implementing the specification.

So:

```python
def get_holdings(self, conn, portfolio: dict) -> list[Holding]
```

`portfolio` is a dict that came back from `portfolios.resolve()`, carrying the
proof that the ownership comparison ran — the same discipline `gateway/holdings.py`
already enforces with `_portfolio_id`. The broker's own reference lives in
`portfolios.provider_account_ref`, so the provider reads it *from the resolved
row* rather than being handed one by a caller.

**The gate stays in front of the provider, never behind it.** A provider is an
adapter to a data source; it is not an authorization boundary and must never
become one.

`list_accounts(owner_context)` keeps its owner-scoped shape, because that one
takes no id and cannot be tricked into returning somebody else's — the same
property that made `portfolios.owned()` safe to exist beside `resolve()`.

### 3.3 `typing.Protocol`, not an ABC

The house pattern: `app/model_provider.ModelProvider` and
`backend/reference_data.SourceAdapter` are both structural protocols. Follow it.
An implementation declares conformance by passing the suite, not by inheriting.

`SimulatedPortfolioProvider` is named for what it is, following
`AnthropicProvider`'s stated reasoning — *"named for its vendor so that a second
one can exist without either pretending to be generic."*

### 3.4 A provider declares what it cannot do, rather than returning an empty answer

`get_balances` and `refresh` have **no honest answer for a MANUAL portfolio.**
Nobody told this system how much cash the client holds, and there is nothing to
refresh *from* — the source is a person who spoke last Tuesday.

Returning `{}` or `{"cash": 0}` would read as "zero cash", which is the
fabrication this project refuses everywhere else. Returning `None` puts the
interpretation in every caller.

So each provider declares its capabilities, and an undeclared one raises:

```python
class ProviderCapabilityUnavailable(NotImplementedError):
    """This provider cannot answer that, and says why rather than guessing."""

def supports(self, capability: str) -> bool
```

Refused with a *reason the caller can repeat aloud*, exactly as
`gateway/skills.py` does for a declared-and-unbuilt skill. This is the same
pattern one layer down: the answer to "why can't you tell me my cash balance?"
is a sentence, not a blank field.

The conformance suite asserts the refusal, not the value — that is what makes it
satisfiable by a provider that genuinely has balances *and* one that genuinely
does not.

### 3.5 `refresh()` never invents freshness

§17 is explicit: if the broker is unavailable, retain the last snapshot, **mark it
stale, do not silently claim it is current.** `portfolios.last_synced_at` is the
field that carries this and is `NULL` today for every row.

Rules, mechanical:

- `refresh()` sets `last_synced_at` **only** when data was actually fetched.
- A failed refresh leaves the previous value alone and reports the failure.
- A provider that cannot refresh (MANUAL) raises per §3.4 rather than stamping
  `last_synced_at` with the time somebody asked.

A `last_synced_at` that updates on a failed sync is worse than a NULL one: it is
a timestamp that asserts freshness it does not have.

### 3.6 The simulated provider generates; it does not read the organization

`SimulatedPortfolioProvider` must not reach into `financial_intelligence.db`.

That is the §95 invariant — no skill a client can invoke may read organization
data — and it survives here for the same reason. Naming a symbol is fine; the
demo clients already hold `SYN1`–`SYN10`, which are named as constants in
`gateway/demo_clients.py` rather than fetched from the backend. **Naming a symbol
is not the same as querying the organization's database for it**, and the second
is a client-reachable path into `financial_intelligence.db`.

The generated positions are deterministic — a fixed table, not a random draw —
so the demo is reproducible and a test can assert against it.

### 3.7 `health_check()` answers about the provider, never about the data

`{"healthy": bool, "detail": str}`. For the simulated provider it is always
healthy and says it is simulated. It exists now so the Schwab provider has
somewhere to report a down API without inventing a return shape at the moment it
first fails.

### 3.8 The analyzer contract is what the suite protects

§15.3's *"switching provider does not change analyzer contract"* is the property
that makes the abstraction worth having. `holdings.concentration` is the analyzer.

The test is: build the same positions through two different providers and assert
`concentration` returns identical output. With one real provider, use an in-suite
`StubPortfolioProvider` as the second — not a mock of the first, an independent
implementation, because two implementations is the minimum number at which a
contract is a contract.

### 3.9 Nothing here becomes priced

`portfolios.is_priced()` stays one line and `LIVE`-only. A `SIMULATED` portfolio
is still not priced, and the reasoning is in §11 Q2 — it is the question most
likely to be answered wrongly by somebody being helpful.

---

## 4. Data contracts

### 4.1 The canonical `Holding` (TQ-45a)

Addendum 44 §3.4's names, finally adopted:

| current | canonical | note |
|---|---|---|
| `ticker` | `symbol` | |
| `shares` | `quantity` | |
| `cost_basis` | `average_cost` | unambiguously per-share, which is what it already meant |
| `asset_class` | `asset_class` | vocabulary per §11 Q1 |
| `stated_at` | `as_of` | a provider's data is *as of* a time; "stated" assumed a person |

Deliberately **not** added yet: `market_price`, `market_value`, `provider_position_id`,
`metadata`. §3.9 — a field existing is not permission to fill it in, and
`provider_position_id` has no producer until TQ-49.

`currency` is a genuine gap: every holding is implicitly USD and nothing says so.
Add it as `currency TEXT NOT NULL DEFAULT 'USD'` **only if** the reviewer agrees a
default is honest here; otherwise leave it to TQ-49, where a broker supplies it.
See §11 Q4.

The dataclass is frozen, like `OwnerContext`, and for the same reason: it is what
a provider returned, not a working variable.

### 4.2 Provider capabilities

```python
CAP_HOLDINGS = "holdings"      # every provider; the minimum to be one at all
CAP_BALANCES = "balances"
CAP_POSITIONS = "positions"    # positions distinct from holdings (options legs, lots)
CAP_REFRESH = "refresh"
CAP_ACCOUNTS = "accounts"
```

Closed vocabulary, fail-closed on an unknown one, matching `gateway/portfolios.py`'s
house rule.

### 4.3 Module API — `gateway/portfolio_providers.py`

```python
class ProviderCapabilityUnavailable(NotImplementedError)
class ProviderRefused(RuntimeError)          # §17: malformed data, quarantined

@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: float
    average_cost: float | None
    asset_class: str
    as_of: str
    note: str | None = None
    acquired_on: str | None = None
    simulated: bool = False

class PortfolioProvider(Protocol):
    name: str
    provider_type: str                        # portfolios.PROVIDER_* 
    def supports(self, capability: str) -> bool: ...
    def list_accounts(self, conn, owner) -> list[dict]: ...
    def get_account(self, conn, portfolio: dict) -> dict: ...
    def get_holdings(self, conn, portfolio: dict) -> list[Holding]: ...
    def get_balances(self, conn, portfolio: dict) -> dict: ...
    def get_positions(self, conn, portfolio: dict) -> list[Holding]: ...
    def refresh(self, conn, portfolio: dict) -> dict: ...
    def health_check(self) -> dict: ...

def for_portfolio(portfolio: dict) -> PortfolioProvider
```

`for_portfolio` resolves `portfolios.provider_type` to its implementation and
**raises on an unknown one** rather than falling back to the manual provider —
fail closed, per the vocabulary rule. A portfolio whose provider this build does
not recognise is not one whose holdings it may present.

### 4.4 The two providers built here

| provider | `provider_type` | supports | source |
|---|---|---|---|
| `ManualPortfolioProvider` | `MANUAL` | holdings, accounts | `portfolio_holdings` — what the client stated |
| `SimulatedPortfolioProvider` | `SIMULATED` | holdings, accounts, positions, balances, refresh | its own deterministic table |

`ManualPortfolioProvider` is not a stopgap. It is the honest description of the
source that exists today, and having it means the client-stated path goes through
the same interface as everything else rather than being the special case
everything else is compared against.

---

## 5. Files and modules

**TQ-45a**

| file | change |
|---|---|
| `gateway/holdings.py` | rename fields; `asset_class` vocabulary; the migration |
| `gateway/tools.py` | tool schemas + handlers use `symbol`/`quantity`/`average_cost` |
| `gateway/store.py` | register the migration |
| `gateway/demo_clients.py` | seed positions under the new names |
| `tests/test_gateway_holdings.py`, `tests/test_gateway_portfolios.py` | updated |

**TQ-45b**

| file | change |
|---|---|
| `gateway/portfolio_providers.py` | **new** — §4.3 |
| `gateway/holdings.py` | reads go through the provider |
| `gateway/demo_clients.py` | rebuilt on `SimulatedPortfolioProvider` (§6.1's diversity) |
| `gateway/skills.py` | revisit `portfolio_valuation`'s reason — still blocked, possibly for a newly precise reason |
| `tests/test_portfolio_provider_contract.py` | **new** — the conformance suite (§7) |
| `tests/test_gateway_providers.py` | **new** — simulated-provider specifics |

No new packages. No external dependencies. **No network calls** — TQ-49 owns the
Schwab boundary and TQ-50 is blocked on owner action.

---

## 6. Migration procedure (TQ-45a)

Smaller than TQ-44's and in the same place — `gateway/store.init_schema`, for the
reason recorded in TQ-44's §10 Q1 (`backend/migrations.py` cannot honestly back
up `gateway.db`).

1. Create `portfolio_holdings` with the canonical column names.
2. Copy every row across, mapping `ticker`→`symbol`, `shares`→`quantity`,
   `cost_basis`→`average_cost`, `stated_at`→`as_of`. Map `asset_class` per the
   vocabulary chosen in §11 Q1 — `UNKNOWN` maps to whatever that decision names
   as its unknown, and **does not become a guess**.
3. Verify: row count before == after; no holding changed portfolio.
4. Rename the old table to `portfolio_holdings_pre45`.
5. Idempotent by the same construction TQ-44 used: the rename removes what a
   second run would look for, and both tables present means an aborted run,
   which refuses rather than clobbering.

SQLite can `ALTER TABLE … RENAME COLUMN`, which is tempting and **should not be
used here**: it cannot do the whole set atomically with the verification step,
and TQ-44's copy-verify-rename shape is already proven against a real database.
Match it.

`demo_clients.clear()` must reach `portfolio_holdings_pre45` too, for the reason
TQ-44's §10 Q2 records about `client_holdings_legacy`. There will then be **two**
legacy tables; dropping both is worth its own line in TQ-46 rather than
accumulating quietly.

---

## 7. The conformance suite (§15.4) — the point of the increment

`tests/test_portfolio_provider_contract.py`. Written so a new provider is added
by supplying a fixture and nothing else.

```python
class PortfolioProviderContract:
    """Every PortfolioProvider must satisfy this, unchanged.

    Subclass and supply `provider` + `seeded_portfolio`. SchwabPortfolioProvider
    inherits this class as-is (TQ-49); if it has to modify a test, the contract
    was wrong, not the broker."""
```

Required tests, each stating what it protects:

**Shape**
- every `get_holdings` element is a `Holding`, never a broker dict or a raw row
- `symbol` is upper-cased and non-blank; `quantity` > 0; `average_cost` is
  `None` or > 0 — never `0.0` standing in for unknown
- `asset_class` is in the vocabulary; an unrecognised one raises

**Ownership** — the property TQ-44 established, asserted at this layer too
- a provider given a portfolio returns only that portfolio's holdings
- there is no provider method that accepts a bare id (asserted by signature
  inspection, so a future method cannot quietly add one)

**Capability honesty**
- `supports(CAP_HOLDINGS)` is true for every provider
- an unsupported capability raises `ProviderCapabilityUnavailable`, and the
  message is non-empty — a refusal a caller can repeat
- a supported capability does not raise

**Freshness (§17)**
- `refresh` sets `last_synced_at` only on success
- a failed refresh leaves the prior value and reports the failure
- a provider without `CAP_REFRESH` raises rather than stamping a time

**Pricing**
- no provider returns a market price, market value, gain or loss in this build
- `portfolios.is_priced` is false for everything the provider produces

**Health**
- `health_check()` returns `healthy` and `detail`, and `detail` is non-empty

**The analyzer contract (§15.3)**
- `concentration` over holdings from two different providers with the same
  positions returns identical output

## 7.1 Other required tests

- **Simulated distinctness (§15.3)** — the three demo clients hold genuinely
  different portfolios, asserted rather than eyeballed
- **Labeling (§6.2)** — every simulated portfolio is `data_mode=SIMULATED`,
  `provider_type=SIMULATED`, `simulated=1`
- **Migration (45a)** — counts match, nothing re-owned, idempotent, `UNKNOWN`
  does not become a guess
- **The §15.5 regression still passes** — it is permanent and this touches the
  layer beneath it

---

## 8. Acceptance criteria

Maps to addendum 44 §21 items 3, 8, 9, 10 (11–13 complete in TQ-49).

1. A `PortfolioProvider` protocol exists and no analysis code knows where
   holdings came from.
2. `SimulatedPortfolioProvider` and `ManualPortfolioProvider` both satisfy the
   conformance suite.
3. The suite is written so a third provider is added by supplying a fixture.
4. Holdings use `symbol` / `quantity` / `average_cost`, migrated with no orphans.
5. `asset_class` speaks one vocabulary across the codebase (§11 Q1).
6. Simulated portfolios are distinct, labeled, and deterministic.
7. No provider method accepts a bare portfolio id.
8. Nothing is priced; `is_priced` is unchanged and still one line.
9. Full suite green on Windows **and** Linux.

---

## 9. Security and isolation implications

1. **The gate stays in front of the provider** (§3.2). This is the whole security
   content of the increment: a provider that accepted an `account_ref` would
   reintroduce by-id retrieval one layer below where the tripwire looks.
2. **Extend the tripwire.** `test_nothing_outside_portfolios_queries_the_portfolios_table`
   should also fail if a provider method signature takes an id-shaped argument.
3. **The simulated provider must not read `financial_intelligence.db`** (§3.6).
   Worth a test, since it is a client-reachable path into organization data —
   the §95 invariant.
4. **Malformed provider data is quarantined, not stored** (§17): reject with
   `ProviderRefused` and preserve what was already there.
5. **No credentials anywhere in this increment.** Brokerage credential storage is
   TQ-49's, and §14 forbids displaying them at all.

---

## 10. Two collisions found while writing this spec

Both are things a builder would otherwise hit mid-increment. Neither is a defect
in shipped behaviour.

### 10.1 `asset_class` has two vocabularies, and §70 already ruled on this

TQ-44 introduced `EQUITY` / `OPTION` / `UNKNOWN` in `gateway/holdings.py`,
following addendum 44 §3.4 literally.

This system already had a vocabulary for the same fact: `stock`, `stock_option`,
`etf`, `etf_option`, `future`, `future_option`, `commodity`, `commodity_option`,
`fx`, `fixed_income`, `digital_asset` — in `backend/reference_data.ASSET_CLASSES`,
validated against `boot_config.json`.

**§70 already refused exactly this substitution once**, for addendum 39's
`EQUITIES` / `OPTIONS_ON_EQUITIES`:

> *Adopting the spec's labels would create a second naming scheme for the same
> eleven classes — two models of one fact, which the Conflict Rule forbids.*

The precedent is on the nose, and TQ-44 created the second scheme anyway by
reading §3.4 as normative rather than illustrative — reasonably, since §3.4 says
"initial asset classes should support **at minimum** EQUITY and OPTION", which
the finer vocabulary satisfies rather than contradicts. This is the right
increment to resolve it, because 45a is already rewriting the column. See §11 Q1.

### 10.2 Demo clients are `MANUAL`, but §6.2 says simulated portfolios must be `SIMULATED`

`demo_clients.seed` calls `portfolios.primary_for`, which creates a `MANUAL` /
`MANUAL` portfolio. Addendum 44 §6.2 requires `data_mode = SIMULATED` and
`provider_type = SIMULATED` for simulated portfolios, and the row-level
`simulated` flag TQ-44 uses is a *different* fact — "this is demo data to be
cleared" rather than "this data came from a simulation".

Nothing is currently wrong: no simulated data is presented as live, and
`is_priced` is false either way. But the demo rebuild is where these have to be
reconciled, and the interesting case is a holding a demo client states *in
conversation* — genuinely MANUAL data inside a SIMULATED portfolio. See §11 Q3.

---

## 11. Open questions

Decide these first and record the decisions, the way TQ-44's §10 was decided
before any code. Each has a leaning; none is settled.

**Q1 — Which `asset_class` vocabulary?** House (`stock`/`stock_option`/…) or
addendum 44's (`EQUITY`/`OPTION`)? **Leaning house**, on §70's precedent and the
Conflict Rule: one model of one fact. It is finer, already validated against
`reference_data.ASSET_CLASSES`, and satisfies §3.4's "at minimum" by covering
more. Against it: the Gateway would then depend on a backend vocabulary, which
brushes against the §95 invariant — though importing a *constant list* is not
reading organization data, and the boundary that matters is the database. If
adopted, decide what the unknown value is called (`unknown`, matching the house
lower-case style) and confirm `boot_config`'s `implemented_asset_classes` is not
accidentally made a constraint on what a *client* may say they hold — it must
not be. A client may hold something this system cannot process.

**Q2 — Does a `SIMULATED` portfolio get simulated prices?** **Leaning firmly no,
and this is the one most likely to be got wrong by somebody being helpful.** The
argument for is superficially strong: the portfolio is explicitly labeled
simulated, so a simulated valuation is not a lie, and it would make the demo far
more impressive. The argument against is that `is_priced()` is one line and one
rule (§3.7), and widening it to "LIVE, or SIMULATED-and-labeled" makes it two —
which is precisely the drift a single function exists to prevent. Labels are lost
in screenshots; a second branch is not lost in code. If a demo genuinely needs it
later, build it as a separately named `simulated_valuation` that can never be
mistaken for the real one — and only when something actually asks, per the
standing rule that machinery with no user does not get built.

**Q3 — `data_mode` for demo clients.** §6.2 says `SIMULATED`/`SIMULATED`; they
are `MANUAL`/`MANUAL` today (§10.2). **Leaning: seed them as SIMULATED**, since
that is what they are and §6.2 is explicit. The awkward case is a holding a demo
client states in conversation, which is genuinely MANUAL data inside a SIMULATED
portfolio — the same shape as §96's "a demo client's stated holding is unflagged
but still demo data". Probably: the *portfolio's* `data_mode` describes its
provider, the *row's* `simulated` flag describes whether it is demo data, and the
two are allowed to differ because they answer different questions. Confirm that
reading survives contact with the conformance suite.

**Q4 — `currency` now or in TQ-49?** Every holding is implicitly USD and nothing
records it. **Leaning: add it in 45a with a `'USD'` default**, because a
canonical holding shape that cannot express currency is one TQ-49 will have to
migrate again. Against: a default is a small fabrication for a client who states
a foreign holding, and this project does not default. Possible resolution — the
column exists, `NULL` means unrecorded, and the simulated provider sets `'USD'`
because it knows what it generated.

**Q5 — Does `ManualPortfolioProvider` earn its place, or is MANUAL just
"no provider"?** **Leaning: it earns it.** Without it the client-stated path is
the special case every other provider is compared against, which is how an
interface ends up shaped like its first implementation — the §2 trap. Against: it
is an adapter over a local table with no external source, and `supports()` will
be false for most of the interface. That is not an argument against building it;
it is the first real test of whether §3.4's capability declaration works.

---

## 12. Risks

**Risk 1 — the interface gets shaped like the simulated provider.** The §2 trap,
and the reason the conformance suite is written first rather than after. A
concrete guard: while writing each contract test, ask whether a provider that
must make a network call could satisfy it. If the answer needs a local database,
the test is wrong.

**Risk 2 — scope creep into TQ-46/TQ-48.** The Superuser portfolio, snapshots,
provenance and audit logging are all adjacent and all queued separately. A
provider that starts recording who read what has become TQ-48.

**Risk 3 — the rename touching two legacy tables.** After 45a there are two
(`client_holdings_legacy`, `portfolio_holdings_pre45`). Both must be reachable by
`demo_clients.clear()` and both should be dropped deliberately, not left to
accumulate.

**Risk 4 — `is_priced` widening under demo pressure.** See §11 Q2. Flagged twice
on purpose.

---

## 13. Out of scope

Per addendum 44 §8.2, §19 and §97: any network call, Schwab authentication or
configuration (TQ-49), live trading or order placement, money movement,
cross-client aggregation, brokerage credential storage or display, the Superuser
portfolio itself (TQ-46), its UI tab (TQ-47), and snapshots, provenance or audit
logging (TQ-48).

`app/tools/portfolio.py`'s missing owner argument remains TQ-46's.

---

## 14. Verification

```bash
.venv/Scripts/python.exe -m pytest -q          # expect 2232+ passing
python -m gateway.demo_clients clear
python -m gateway.demo_clients seed
python -m gateway.demo_clients show            # three visibly different portfolios
```

Then **run it and look**, the way TQ-44 was verified (§99) — that is the pattern
to copy, because a green suite is not evidence:

1. Seed a scratch database and start the Gateway against it.
2. Log in as two demo clients; confirm each sees only their own, and that the
   three portfolios are genuinely different rather than three copies.
3. **Ask the agent for a cash balance.** The refusal should be a sentence that
   says why, not a blank field or a zero.
4. **Ask it what the portfolio is worth.** Still refused, still for the reason in
   `skills.py`.
5. Stop the stack; confirm no orphaned processes.

Step 3 is the new one and the one worth doing carefully: it is the first time
this system refuses something because a *provider* cannot answer it rather than
because a skill is unbuilt, and hearing how that comes out of the agent's mouth
is the test of whether §3.4's design is right.
