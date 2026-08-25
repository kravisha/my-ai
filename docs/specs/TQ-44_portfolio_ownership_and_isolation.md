# TQ-44 — Portfolio Ownership and Isolation

**Implementation specification.** Status: SPECIFIED, not implemented (2026-08-26).

Written so a session with no prior context can build this without further design
work. Where a decision was made, it is recorded with its reasoning so it is not
silently re-litigated; where a question is genuinely open, §10 says so.

| | |
|---|---|
| **Source specification** | [`addenda/addendum_44_client_owned_holdings_superuser_portfolio.md`](../addenda/addendum_44_client_owned_holdings_superuser_portfolio.md) §2, §3.3, §5, §9, §12, §15.1, §15.5, §20 Phases 1+3 |
| **Dispositions** | [`SPEC_RECONCILIATION.md`](../SPEC_RECONCILIATION.md) §97 |
| **Queue entry** | [`TASK_QUEUE.md`](../TASK_QUEUE.md) TQ-44 |
| **Depends on** | TQ-42 (§96, client holdings), TQ-43 (§98, per-client credentials) — both done |
| **Blocks** | TQ-45, TQ-46, TQ-47, TQ-48 |

---

## 1. Objective

Give every portfolio an explicit owner, and ship the ownership guard in the same
increment as the entity that needs guarding.

On completion: no unowned portfolio exists, no global ownerless retrieval remains
in the Gateway, and exactly one function in the codebase answers *"whose data is
this?"*.

## 2. Problem

Holdings are keyed **directly by client id** (`client_holdings.client_id`, TQ-42
/ §96). That is safe but flat: one client has one implicit portfolio, there is no
portfolio identity, and there is nowhere to record what addendum 44 §3.3 requires
— provider, data mode, sync state, freshness.

Addendum 44 needs `Portfolio` as a first-class entity (§3.3, §5.1). **Introducing
it introduces a new attack surface**, and that is the governing fact of this task:

> There is no portfolio id today, so there is nothing to guess. §5.2 lists four
> attacks — requesting another client's portfolio by id, reusing a stale URL, a
> mismatched `client_id`/`portfolio_id` pair, an agent retaining a previous
> client's context — **each of which becomes possible only once an id exists.**

Hence: entity and guard, one increment, one review. An entity that exists a week
before its guard is a week of exactly the exposure addendum 44 was written to
prevent.

---

## 3. Design decisions

Decided. Do not re-open without recording a reason.

### 3.1 One module: `gateway/portfolios.py`

Entity *and* guard. Not split — see §2.

### 3.2 `OwnerContext` — a frozen value resolved server-side

```python
@dataclass(frozen=True)
class OwnerContext:
    owner_type: str   # "CLIENT" | "SUPERUSER"
    owner_id: str     # normalised: stripped, lowercased
```

Constructors: `for_client(client_id)`, `for_superuser(operator_id="operator")`.
`__post_init__` raises `UnknownVocabulary` on an unknown `owner_type` or a blank
`owner_id`.

**Never assembled from anything a caller sent.** Addendum 44 §9.2: *"A client_id
received from the front end is not sufficient proof of ownership."* The Gateway
already resolves `subject` from the session (§93, §98); `OwnerContext` is built
from that and nothing else.

`resolve()` and `listing()` type-check that they received an `OwnerContext` and
not a bare string, so a raw id cannot be passed by accident.

### 3.3 There is no superuser branch — the most important decision here

Addendum 44 §5.3 explicitly forbids:

```python
if superuser:
    skip all ownership checks
```

`SUPERUSER` is therefore a **separate owner domain, not a skeleton key**. A
superuser context resolves superuser-owned portfolios and nothing else, through
the identical comparison a client context uses. `resolve()` has exactly **one**
code path — a second path is where a bypass eventually gets written.

The operator reaching a client's portfolio is **not implemented and must not
be**. §10 permits it only through "explicitly authorized administrative
workflows"; none exists, and building the permission before the workflow would be
an authorization surface with no consumer.

### 3.4 One refusal, whatever the reason

`NotAuthorized` is raised identically when the portfolio (a) does not exist, (b)
belongs to another owner, or (c) is archived. Same exception type, same message:

> `Not authorized or resource unavailable.`

Addendum 44 §9.3: an error must not reveal that another client exists or owns a
requested id. Distinguishing the cases leaks precisely that, and the caller's
remedy is identical in all three.

### 3.5 Random portfolio ids

`f"pf-{secrets.token_hex(16)}"` — 32 hex characters. Not sequential.

The guard makes enumeration *useless*; random ids make it *pointless*. A
sequential id leaks a portfolio count from any single id — information about
other clients even when their data is unreachable. §4.3 says a portfolio "must
not be addressable merely by guessing a portfolio ID"; this takes that at its
word rather than delegating entirely to the check.

### 3.6 Closed vocabularies, fail-closed

Per §3.3 and the house rule (`backend/status_events.py`, `gateway/clients.py`):

| field | values |
|---|---|
| `owner_type` | `CLIENT`, `SUPERUSER` |
| `portfolio_type` | `PRIMARY`, `SECONDARY`, `SIMULATION`, `BROKERAGE_IMPORTED` |
| `provider_type` | `SIMULATED`, `SCHWAB`, `MANUAL` |
| `data_mode` | `SIMULATED`, `LIVE`, `MANUAL` |
| `status` | `active`, `archived` |

A stored row whose value this build does not recognise **raises on read**, not
just on write. A portfolio whose `owner_type` cannot be interpreted is not one
that may be handed to anybody.

### 3.7 `is_priced(portfolio)` — one function, one rule

```python
def is_priced(portfolio: dict) -> bool:
    return portfolio.get("data_mode") == MODE_LIVE
```

The entire condition for whether anything derived from a market price may be
shown. This is §97's disposition made mechanical: §96 refused market value
because every price this system produces is simulated; addendum 44 supplied the
missing field (`data_mode`) and draws the same line from the other side in §6.2.
One function means the answer cannot drift between callers.

### 3.8 `primary_for(conn, owner)` — created on first use

§5.1 allows one client many portfolios; most have one. Requiring somebody to name
a portfolio before telling their representative about a holding would be
ceremony. The entity is real either way — this decides only who names it.

### 3.9 Holding field names are **not** renamed in TQ-44

Addendum 44 §3.4 names fields `symbol`, `quantity`, `average_cost`. Current code
uses `ticker`, `shares`, `cost_basis`.

**Decision: keep current names here; rename in TQ-45.** The canonical holding
shape is *what a provider returns*, and TQ-45 defines `PortfolioProvider`.
Renaming here means touching `tools.py`, both test files and the model-facing
tool schemas twice.

`average_cost` is the better name — unambiguously per-share, which is what
`cost_basis` already means in `holdings.concentration` — and should win when the
rename happens.

**A fresh session must not treat the current names as an oversight to tidy.**

---

## 4. Data contracts

### 4.1 `portfolios` table

```sql
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    portfolio_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    provider_account_ref TEXT,
    data_mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_synced_at TEXT,
    simulated INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS portfolios_by_owner ON portfolios (owner_type, owner_id);
```

`owner_type` / `owner_id` are `NOT NULL` deliberately: §2.3 says a missing owner
denies, and a nullable column makes that a runtime hope rather than a schema
fact.

`simulated` follows the §96 convention so `demo_clients.clear()` removes demo
portfolios exactly.

### 4.2 Holdings, re-keyed

Holdings gain `portfolio_id` as their owning key and `asset_class`
(`EQUITY`, `OPTION` minimum, extensible per §3.4).

**`client_id` must not survive alongside `portfolio_id`.** Two sources of truth
for ownership can disagree, and §2.2 wants one explicit owner. Ownership is
reached by joining through `portfolios`.

### 4.3 Module API

```python
# vocabularies
OWNER_CLIENT, OWNER_SUPERUSER; OWNER_TYPES
TYPE_PRIMARY, TYPE_SECONDARY, TYPE_SIMULATION, TYPE_BROKERAGE_IMPORTED; PORTFOLIO_TYPES
PROVIDER_SIMULATED, PROVIDER_SCHWAB, PROVIDER_MANUAL; PROVIDER_TYPES
MODE_SIMULATED, MODE_LIVE, MODE_MANUAL; DATA_MODES
STATUS_ACTIVE, STATUS_ARCHIVED; STATUSES

class NotAuthorized(PermissionError)       # §3.4 — one refusal
class UnknownVocabulary(ValueError)        # §3.6 — fail closed

def for_client(client_id) -> OwnerContext
def for_superuser(operator_id="operator") -> OwnerContext

def create(conn, owner, *, display_name, portfolio_type=TYPE_PRIMARY,
           provider_type=PROVIDER_MANUAL, data_mode=MODE_MANUAL,
           provider_account_ref=None, simulated=False) -> dict
def resolve(conn, portfolio_id, owner) -> dict          # raises NotAuthorized
def listing(conn, owner) -> list[dict]                  # this owner's active only
def primary_for(conn, owner, *, display_name=None, simulated=False) -> dict
def archive(conn, portfolio_id, owner) -> dict          # goes through resolve first
def is_priced(portfolio) -> bool
def simulated_portfolio_ids(conn) -> list[str]
```

`resolve()` is **the one gate**. Every read of portfolio-scoped data goes through
it, so there is a single place where ownership is answered and a single place to
audit.

---

## 5. Files and modules

| file | change |
|---|---|
| `gateway/portfolios.py` | **new** — §4.3's API |
| `gateway/holdings.py` | re-key to `portfolio_id`, add `asset_class`; functions take a portfolio, not a client id |
| `gateway/store.py` | register `portfolios.SCHEMA`; add the migration (§6) |
| `gateway/tools.py` | holdings tools resolve the caller's portfolio via `primary_for(conn, for_client(subject))` |
| `gateway/demo_clients.py` | seed portfolios; `clear()` removes simulated portfolios |
| `tests/test_gateway_portfolios.py` | **new** — §7 |
| `tests/test_gateway_holdings.py` | update for the re-key |
| `docs/SPEC_RECONCILIATION.md` | §99 disposition |
| `docs/TASK_QUEUE.md` | mark TQ-44 done |

No new packages. No external dependencies.

---

## 6. Migration procedure

The dangerous part — it moves real client holdings between tables.

1. Create `portfolios` and the new holdings table.
2. For each distinct `client_id` in `client_holdings`, create one portfolio:
   `owner_type=CLIENT`, `owner_id=<client_id>`, `portfolio_type=PRIMARY`,
   `provider_type=MANUAL`, `data_mode=MANUAL`, `display_name="Portfolio"`,
   `simulated` = whether that client's rows were flagged.
3. Copy every holding across, setting `portfolio_id` to its client's new
   portfolio. Preserve `stated_at` and `simulated`.
4. **Verify**: row count before == row count after; every holding has a
   `portfolio_id` that resolves; no holding changed owner.
5. Rename `client_holdings` → `client_holdings_legacy` (see §10 Q2).
6. Idempotent: running `init_schema` again must not duplicate or re-run.

Test against a **copy** of a seeded database before trusting it — the project's
standing rule (`memory/my-ai-look-at-the-running-thing.md`).

---

## 7. Required tests

All permanent regressions, not smoke tests. Suggested names given so the intent
survives.

**Ownership isolation (§15.1)** — `tests/test_gateway_portfolios.py`

- `test_an_owner_resolves_their_own_portfolio`
- `test_a_client_cannot_resolve_another_clients_portfolio`
- `test_a_client_cannot_resolve_a_superuser_portfolio`
- `test_a_guessed_id_does_not_bypass_authorization`
- `test_absent_foreign_and_archived_raise_the_same_refusal` — asserts identical
  exception *and message*, because §9.3 is about what a caller can tell apart
- `test_listing_returns_only_this_owners_portfolios`

**The §15.5 regression** — name it so its purpose is unmistakable:

- `test_a_client_cannot_receive_the_superuser_portfolio_when_it_is_the_only_one`

  Set up a `SUPERUSER`-owned portfolio as the **only** row, then assert a client
  context resolves nothing and lists nothing. This reproduces §93's leak in
  portfolio form.

**Fail-closed vocabulary**

- Unknown `owner_type` / `portfolio_type` / `provider_type` / `data_mode` /
  `status` raise on write **and** on read
- `OwnerContext` with blank owner id raises
- `resolve()` given a raw string instead of an `OwnerContext` raises

**Pricing rule**

- `test_only_a_live_portfolio_is_priced` — `is_priced` true only for
  `data_mode == LIVE`; simulated and manual are never priced

**Migration**

- Pre-TQ-44 rows land in a `MANUAL` portfolio owned by their original client
- Counts match; nothing orphaned; no owner changed
- Idempotent across repeated `init_schema`

**Demo data**

- Simulated portfolios flagged and cleared by `demo_clients.clear()`

**Suggested tripwire** (see §10 Risk 3)

- `test_nothing_outside_portfolios_queries_the_portfolios_table` — a source scan,
  in the style of `tests/test_gateway_roles.py`'s route scanner

---

## 8. Acceptance criteria

Maps to addendum 44 §21 items 1, 2, 7, 8 (item 6 completes in TQ-46).

1. No unowned portfolio can exist — the schema forbids it.
2. Every portfolio has explicit `owner_type` + `owner_id`.
3. `resolve()` is the only path to a portfolio and refuses identically for
   absent / foreign / archived.
4. A client cannot reach another client's or a superuser's portfolio by any
   tested route.
5. Existing holdings migrate with no orphans and no owner changes.
6. `is_priced()` is the single rule for market-derived values.
7. The §15.5 regression test exists and is permanent.
8. Full suite green on Windows **and** Linux.

---

## 9. Security and isolation implications

This is a security task wearing a data-model hat.

1. **New attack surface, mitigated in the same commit** — §2.
2. **Single gate.** A second retrieval path that skips `resolve()` is the failure
   mode to watch for in review.
3. **No information leakage through errors** — §3.4.
4. **No superuser bypass** — §3.3.
5. **Agent context isolation** (§9.4): when a turn changes clients the previous
   portfolio context must not persist. Currently satisfied structurally — tools
   take `subject` from the session per call (§96) — but assert it for portfolios.
6. **The §15.5 regression is permanent**, reproducing §93's leak in portfolio
   form.

---

## 10. Open questions and risks

**Q1 — Where does the migration live?** `backend/migrations.py` (§89) is the
project's pipeline but registers *backend* stores; this is the Gateway database.
Options: (a) a one-time function in `gateway/store.init_schema`, consistent with
its existing `_apply_additive_migrations`; (b) extend §89 to Gateway stores.
**Leaning (a)**; genuinely undecided, worth ten minutes first.

**Q2 — Drop or keep `client_holdings`?** Dropping is clean; renaming to
`client_holdings_legacy` preserves data, matches §16.1 ("mark it as legacy") and
§22's preserve-for-diagnosis habit, but leaves a lingering table. **Leaning
rename**, dropping in a later increment once confidence is established.

**Q3 — `asset_class` for migrated rows.** They have none. `EQUITY` is a guess and
this project does not fabricate. **Leaning `NULL`/`"unknown"** per addendum 42
§11's vocabulary. Confirm how `concentration` should treat unknown-class
holdings.

**Risk 1 — scope creep into TQ-45.** The provider abstraction is adjacent and
tempting. §3.9 records why the naming churn is budgeted separately.

**Risk 2 — the migration.** See §6.

**Risk 3 — `resolve()` bypass.** The single-gate property is only as strong as
review. A source-scan tripwire is cheap insurance (§7).

---

## 11. Out of scope

Per addendum 44 §19 and §97: live trading, order placement, money movement,
cross-client aggregation, client-to-client sharing, brokerage credential display,
any superuser bypass.

Also deferred to their own entries: the superuser portfolio itself (TQ-46), the
provider abstraction (TQ-45), snapshots and audit logging (TQ-48).

---

## 12. Verification

```bash
.venv/Scripts/python.exe -m pytest -q          # expect 2187+ passing
python -m gateway.demo_clients seed
python -m gateway.demo_clients show
python -m gateway.demo_clients clear           # must leave zero rows
```

Then **run it and look**. Start the Gateway, log in as two demo clients, and
confirm each sees only their own portfolio. Every real defect found in this
project came from doing that rather than from a green suite.
