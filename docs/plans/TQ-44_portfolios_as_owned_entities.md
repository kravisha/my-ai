# TQ-44 — Portfolios as owned entities, with the guard that makes them safe

**Status:** PLANNED, not implemented. Written 2026-08-26 so a fresh session can
build it without the conversation that designed it.

**Source:** addendum 44 §2, §3.3, §5, §9, §12, §15.1, §15.5, §20 Phases 1+3
(`docs/addenda/addendum_44_client_owned_holdings_superuser_portfolio.md`).
**Dispositions:** `docs/SPEC_RECONCILIATION.md` §97.
**Queue entry:** `docs/TASK_QUEUE.md` TQ-44.

---

## 1. Objective

Give every portfolio an explicit owner, and ship the ownership guard in the same
increment as the entity that needs guarding.

After TQ-44 there is no unowned portfolio, no global `get_current_portfolio()`,
and exactly one place in the codebase that answers "whose data is this".

## 2. The problem being solved

Holdings are currently keyed **directly by client id** (`client_holdings.client_id`,
built in TQ-42/§96). That is safe but flat: one client has exactly one implicit
portfolio, there is no portfolio identity, and there is nowhere to record what
addendum 44 §3.3 requires — provider, data mode, sync state, freshness.

The specification needs `Portfolio` as a first-class entity (§3.3, §5.1). **The
act of introducing it introduces a new attack surface**, and that is the central
design fact of this task:

> Today there is no portfolio id, so there is nothing to guess. §5.2 lists four
> attacks — requesting another client's portfolio by id, reusing a stale URL, a
> mismatched `client_id`/`portfolio_id` pair, an agent retaining a previous
> client's context — **every one of which becomes possible only once an id
> exists.**

Therefore the entity and its guard are one increment and one review. An entity
that exists a week before its guard is a week of exactly the exposure addendum 44
was written to prevent.

## 3. Architecture and design decisions

These were worked out in the session that wrote this plan. A fresh session should
treat them as decided unless it finds them wrong, in which case §7's process
applies (record the disagreement, do not silently re-decide).

### 3.1 New module: `gateway/portfolios.py`

Holds **both** the entity and the guard. Not split, for the reason in §2.

### 3.2 `OwnerContext` — a frozen value resolved server-side

```python
@dataclass(frozen=True)
class OwnerContext:
    owner_type: str   # CLIENT | SUPERUSER
    owner_id: str
```

Constructors `for_client(client_id)` and `for_superuser(operator_id)`.

**It must never be assembled from anything a caller sent.** Addendum 44 §9.2: "A
`client_id` received from the front end is not sufficient proof of ownership."
The Gateway already resolves `subject` from the session (TQ-39/§93, TQ-43/§98);
`OwnerContext` is built from that and nothing else.

`resolve()` type-checks its argument is an `OwnerContext` rather than a string,
so a caller cannot pass a raw id by accident.

### 3.3 There is **no superuser branch** — this is the most important decision

Addendum 44 §5.3 explicitly forbids:

```python
if superuser:
    skip all ownership checks
```

So `SUPERUSER` is modelled as a **different owner domain, not a skeleton key**. A
superuser context resolves superuser-owned portfolios and nothing else, through
the identical comparison a client context uses. `resolve()` has exactly one code
path; a second path is where a bypass eventually gets written.

The operator reaching a client's portfolio is **not** implemented and must not
be. §10 permits it only through "explicitly authorized administrative workflows",
and none exists. Building the permission before the workflow would be an
authorization surface with no consumer.

### 3.4 One refusal, whatever the reason

`NotAuthorized` is raised identically when the portfolio does not exist, belongs
to somebody else, or is archived. Same exception, same message:
*"Not authorized or resource unavailable."*

Addendum 44 §9.3: an error must not reveal that another client exists or owns a
requested id. Distinguishing the cases leaks exactly that, and the caller's
remedy is identical in every case.

### 3.5 Random portfolio ids

`pf-<32 hex chars>` via `secrets.token_hex(16)`, not sequential integers.

The guard makes enumeration *useless*; random ids make it *pointless*. A
sequential id leaks a portfolio count from any single id — information about
other clients even when their data is unreachable. §4.3 says a portfolio "must
not be addressable merely by guessing a portfolio ID"; this takes that at its
word rather than delegating entirely to the check.

### 3.6 Closed vocabularies, fail-closed

Per §3.3, and following the house rule (`backend/status_events.py`,
`gateway/clients.py`):

| field | values |
|---|---|
| `owner_type` | `CLIENT`, `SUPERUSER` |
| `portfolio_type` | `PRIMARY`, `SECONDARY`, `SIMULATION`, `BROKERAGE_IMPORTED` |
| `provider_type` | `SIMULATED`, `SCHWAB`, `MANUAL` |
| `data_mode` | `SIMULATED`, `LIVE`, `MANUAL` |
| `status` | `active`, `archived` |

A stored row whose vocabulary value this build does not recognise **raises**
rather than being returned. A portfolio whose `owner_type` cannot be interpreted
is not one that may be handed to anybody.

### 3.7 `is_priced(portfolio)` — one function, one rule

`data_mode == LIVE` is the entire condition for whether anything derived from a
market price may be shown.

This is §97's disposition made mechanical. §96 refused market value because every
price this system produces is simulated; addendum 44 supplied the missing field
(`data_mode`) and draws the same line from the other side in §6.2. Putting the
rule in one function means the answer cannot drift between callers.

### 3.8 `primary_for(conn, owner)` — created on first use

§5.1 allows one client many portfolios; most have one. Requiring somebody to name
a portfolio before telling their representative about a holding would be
ceremony. The entity is real either way — this only decides who names it.

### 3.9 Schema

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

`owner_type`/`owner_id` are `NOT NULL` deliberately. §2.3 says a missing owner
denies; a nullable owner column makes that a runtime hope rather than a schema
fact.

`simulated` follows the TQ-42/§96 convention so `gateway/demo_clients.clear()`
removes demo portfolios exactly.

### 3.10 Holdings re-keyed to `portfolio_id`

New canonical table, migrating from `client_holdings`:

- Add `portfolio_id` as the owning key and `asset_class` (`EQUITY`, `OPTION`
  minimum, extensible per §3.4).
- **Do not keep `client_id` alongside `portfolio_id`.** Two sources of truth for
  ownership can disagree, and §2.2 wants one explicit owner. Ownership is reached
  by joining through `portfolios`.

### 3.11 Field naming is deferred to TQ-45 — deliberately

Addendum 44 §3.4 names holding fields `symbol`, `quantity`, `average_cost`. The
current code uses `ticker`, `shares`, `cost_basis`.

**Decision: keep the current names in TQ-44; rename in TQ-45.** The canonical
holding shape is *what a provider returns*, and TQ-45 is where `PortfolioProvider`
defines it. Renaming here would mean touching `tools.py`, both test files and the
model-facing tool schemas twice.

`average_cost` is the better name (unambiguously per-share, which is what the
current `cost_basis` already means) and should win when the rename happens.

**A fresh session must not treat the current names as a mistake to fix
opportunistically** — the churn is budgeted for TQ-45.

## 4. Files and modules likely to change

| file | change |
|---|---|
| `gateway/portfolios.py` | **new** — entity, `OwnerContext`, `resolve`, `listing`, `create`, `primary_for`, `archive`, `is_priced` |
| `gateway/holdings.py` | re-key to `portfolio_id`, add `asset_class`, every function takes a portfolio rather than a client id |
| `gateway/store.py` | register `portfolios.SCHEMA`; add the one-time migration |
| `gateway/tools.py` | holdings tools resolve the caller's portfolio via `primary_for` before touching holdings |
| `gateway/demo_clients.py` | seed portfolios; `clear()` removes simulated portfolios |
| `tests/test_gateway_portfolios.py` | **new** — the guard, the vocabularies, §15.1 + §15.5 |
| `tests/test_gateway_holdings.py` | update for the re-key |
| `docs/SPEC_RECONCILIATION.md` | §99 disposition |
| `docs/TASK_QUEUE.md` | mark TQ-44 done |

## 5. Dependencies

- **TQ-43 (§98) — done.** Clients are individually registered; `subject` is a
  real per-person identity. `OwnerContext.for_client(subject)` depends on it.
- **TQ-42 (§96) — done.** `client_holdings` is what gets migrated.
- **Blocks:** TQ-45 (provider abstraction), TQ-46 (superuser domain), TQ-47
  (superuser tab), TQ-48 (snapshots/audit).

No external dependencies. No new packages.

## 6. Security and isolation implications

This is a security task wearing a data-model hat. The implications *are* the
task.

1. **New attack surface, mitigated in the same commit** — see §2.
2. **Single gate.** Every read of portfolio-scoped data goes through `resolve()`.
   One place to get right, one place to audit. A second retrieval path that
   skips it is the failure mode to watch for in review.
3. **No information leakage through errors** (§9.3) — see §3.4.
4. **No superuser bypass** (§5.3) — see §3.3.
5. **Agent context isolation** (§9.4): when a turn changes clients, the previous
   portfolio context must not persist. Currently satisfied structurally — tools
   take `subject` from the session per call (TQ-42) — but TQ-44 should assert it
   for portfolios specifically.
6. **The regression test §15.5 demands** — a client-facing Gateway request must
   never receive the superuser/operator portfolio merely because it is the only
   one stored. This reproduces the §93 leak in portfolio form. It is permanent.

## 7. Tests required

Adapted from §15.1 and §15.5. All must be permanent regressions, not smoke tests.

**Ownership isolation (§15.1)**
- Client A can resolve Client A's portfolio.
- Client A cannot resolve Client B's portfolio → `NotAuthorized`.
- Client B cannot resolve Client A's → `NotAuthorized`.
- A client cannot resolve a `SUPERUSER`-owned portfolio → `NotAuthorized`.
- A guessed/random id does not bypass authorization.
- The **same** exception and message for absent, foreign and archived — asserted,
  because §9.3 is about what a caller can tell apart.
- `listing()` returns only the owner's.

**The §15.5 regression**
- With a superuser portfolio as the **only** portfolio in the database, a client
  context resolves nothing and lists nothing. Named so its purpose is obvious.

**Vocabulary / fail-closed**
- Unknown `owner_type` / `portfolio_type` / `provider_type` / `data_mode` /
  `status` raise on write and on read.
- `OwnerContext` with a blank owner id raises.
- `resolve()` with a raw string instead of an `OwnerContext` raises.

**Pricing rule (§3.7)**
- `is_priced()` true only for `data_mode == LIVE`.
- A simulated or manual portfolio is never priced.

**Migration**
- A database with pre-TQ-44 `client_holdings` rows migrates so every holding
  lands in a `MANUAL` portfolio owned by its original client.
- Row counts match before and after; nothing is orphaned; nothing changes owner.
- Migration is idempotent (running `init_schema` twice does not duplicate).

**Demo data**
- Simulated portfolios are flagged and cleared by `demo_clients.clear()`.

## 8. Acceptance criteria

Maps to addendum 44 §21 items 1, 2, 7, 8 (2, 6 partially — 6 completes in TQ-46).

1. No unowned portfolio exists; the schema makes it impossible.
2. Every portfolio has an explicit `owner_type` + `owner_id`.
3. `resolve()` is the only path to a portfolio, and refuses identically for
   absent / foreign / archived.
4. A client cannot reach another client's or a superuser's portfolio by any
   tested route.
5. Existing holdings are migrated with no orphans and no owner changes.
6. `is_priced()` is the single rule for market-derived values.
7. The §15.5 regression test exists and is permanent.
8. Full suite green on Windows **and** Linux (see §11).

## 9. Unresolved questions and risks

**Q1 — Where does the migration live?** `backend/migrations.py` (§89) is the
project's migration pipeline but registers *backend* stores; this is the Gateway
database. Options: (a) a one-time function in `gateway/store.init_schema`,
consistent with its existing `_apply_additive_migrations`; (b) extend the §89
pipeline to Gateway stores. **Leaning (a)** for this increment, with (b) noted as
possible later — but this is genuinely undecided and worth 10 minutes' thought
before starting.

**Q2 — Keep or drop `client_holdings` after migration?** Dropping is clean;
renaming to `client_holdings_legacy` preserves the data, matches §16.1 ("mark it
as legacy") and §22's preserve-for-diagnosis habit, but leaves a table that
lingers. **Leaning rename**, then drop in a later increment once confidence is
established.

**Q3 — `asset_class` on existing rows.** Migrated holdings have no asset class.
`EQUITY` is a guess and this project does not fabricate. **Leaning `NULL` with
"unknown"**, per addendum 42 §11's vocabulary. Confirm against how the
concentration report should treat unknown-class holdings.

**Risk 1 — scope creep into TQ-45.** The provider abstraction is *right there*
and it is tempting to define the canonical holding shape while re-keying. Do not.
§3.11 records why the naming churn is budgeted separately.

**Risk 2 — the migration is the dangerous part.** It moves real client holdings
between tables. Test it against a copy of a seeded database before trusting it,
per the project's standing rule (`memory/my-ai-look-at-the-running-thing.md`).

**Risk 3 — `resolve()` bypass.** The single-gate property is only as good as
review. Consider a tripwire test (like `tests/test_gateway_roles.py`'s route
scanner) asserting no module outside `portfolios.py` queries the `portfolios`
table directly.

## 10. Explicitly out of scope

Per addendum 44 §19 and §97: live trading, order placement, money movement,
cross-client aggregation, client-to-client sharing, brokerage credential display,
any superuser bypass. Also out of scope here: the superuser portfolio itself
(TQ-46), the provider abstraction (TQ-45), snapshots and audit (TQ-48).

## 11. How to verify

```bash
.venv/Scripts/python.exe -m pytest -q          # expect 2187+ passing
python -m gateway.demo_clients seed
python -m gateway.demo_clients show
python -m gateway.demo_clients clear           # must leave zero rows
```

Then **run it and look** — the standing rule that has found every real defect in
this project. Start the Gateway, log in as two demo clients, confirm each sees
only their own portfolio.
