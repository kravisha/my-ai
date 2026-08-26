# TQ-46 — The Superuser Portfolio as Its Own Ownership Domain

**Implementation specification.** Status: SPECIFIED, not implemented (2026-08-26).

Written so a session with no prior context can build this without further design
work. Where a decision was made, it is recorded with its reasoning so it is not
silently re-litigated; where a question is genuinely open, §11 says so.

| | |
|---|---|
| **Source specification** | [`addenda/addendum_44_client_owned_holdings_superuser_portfolio.md`](../addenda/addendum_44_client_owned_holdings_superuser_portfolio.md) §4, §10, §16, §21.4, §21.6 |
| **Dispositions** | [`SPEC_RECONCILIATION.md`](../SPEC_RECONCILIATION.md) §97, §99, §101 |
| **Queue entry** | [`TASK_QUEUE.md`](../TASK_QUEUE.md) TQ-46 |
| **Depends on** | TQ-44 (§99, owned portfolios), TQ-45 (§100/§101, canonical holdings + providers) — both done |
| **Blocks** | TQ-47 (the UI tab), TQ-48 (snapshots and audit) |

---

## 1. Objective

Give the operator's own portfolio an owner, in a domain no client query can reach,
and retire the last ownerless retrieval in the codebase.

On completion: `data/portfolio.xlsx` is no longer read by a function that does not
know whose it is; a `SUPERUSER`-owned portfolio exists; and addendum 44 §21's
items 4 and 6 hold — *Superuser holdings are stored under a separate Superuser
ownership context*, and *normal clients cannot see or query the Superuser
portfolio*.

## 2. Problem

`app/tools/portfolio.py::retrieve_portfolio` takes a permission manager, a
preference store and an audit log — and **no owner**. It reads
`data/portfolio.xlsx` and returns whatever is in it.

That is §16's "legacy single-portfolio design", and §16.7 says to remove it. It is
the last place in this codebase where portfolio data is reached without anybody
asking whose it is.

TQ-44 built the machinery that makes an answer possible: `owner_type = SUPERUSER`
already exists as a vocabulary member, `for_superuser()` already builds the
context, and `resolve()` already refuses across domains. **Nothing creates a
superuser-owned portfolio, and nothing grants the capability to view one.**

---

## 3. What the YELLOW flag actually is — measured, not assumed

The queue entry flags one hazard: the operator holds `CAP_HOLDINGS` through the
client-facing Gateway path (§92, §96), and *"it stops being harmless the moment a
SUPERUSER-owned portfolio exists and the two paths can resolve to each other."*

**They cannot resolve to each other, and this was checked rather than reasoned
about.** Creating both portfolios under the single owner id `operator`:

| | |
|---|---|
| `OwnerContext('CLIENT', 'operator')` reaching the SUPERUSER portfolio | refused |
| `OwnerContext('SUPERUSER', 'operator')` reaching the CLIENT portfolio | refused |
| each domain's `listing()` | shows only its own |

`_owned_by` compares `(owner_type, owner_id)` as a pair, so one name in two
domains is two owners. TQ-44's guard already carries this case.

**So the security half of the flag is closed, and the remaining hazard is
different and narrower: ambiguity.** After this increment the operator has *two*
portfolios — the holdings they stated through the Gateway as a client, and the
real superuser portfolio — and nothing in the current output distinguishes them.
An operator asking "what do I hold?" and getting the wrong one is not a breach; it
is somebody being shown the wrong money, which is its own failure and one this
project has refused before (§96's "two portfolios for one person is a confusion
worth naming").

**Do not downgrade the flag to GREEN.** The remaining hazard is real; it is just
not the one the entry named. §3.4 below is what addresses it.

---

## 4. Design decisions

Decided. Do not re-open without recording a reason.

### 4.1 ~~The Superuser portfolio lives in `gateway.db`~~ — **WITHDRAWN 2026-08-26 (§109)**

This section decided the Superuser portfolio should live in `gateway.db` with
every other portfolio, reasoning from one-table-one-guard. **The reasoning was
sound and its premise was wrong**: it took the current location of the portfolio
subsystem as given.

Owner direction, 2026-08-26: *"Gateway is for establishing identity — Gateway only
does authentication. Back end does authorization and all business logic."*

Under that, the portfolio subsystem — the table, the ownership guard, the
providers — is business logic *and* authorization, and belongs backend-side.
`TQ-69` moves it, and **this entry is blocked on that**. Building a `SUPERUSER`
domain into `gateway.db` and relocating it a week later is the mistake TQ-44
refused to make with the entity and its guard: work done in a place it is known
not to belong.

What survives from the withdrawn decision is its actual content, and it still
holds: **one `portfolios` table, one `resolve()`, one guard.** Two portfolios
tables would be two models of one fact (§70, §100, §104). That argument was never
about *which* database — only that there must be one.

### 4.2 `SUPERUSER` means the operator role, said once

§97 recorded a three-way vocabulary collision: a Server Superuser
(`app/server_auth.py`, who starts the workforce), a Gateway Super User
(`gateway/auth.py`), and `ROLE_OPERATOR` (§92).

Addendum 44's "Superuser" is the second and third — the person at the Gateway —
and **not** the first. `portfolios.OWNER_SUPERUSER` already exists; this increment
adds the sentence saying which of the three it means, in one place, next to the
constant. Three near-synonyms drifting is how somebody eventually grants the
wrong one a portfolio.

`for_superuser()`'s default `operator_id="operator"` should become the resolved
operator subject rather than a literal, for the same reason client contexts take
theirs from the session (§9.2).

### 4.3 Explicit capabilities, never a superuser bypass

§10 asks for `PORTFOLIO_VIEW_SUPERUSER` and `PORTFOLIO_ANALYZE_SUPERUSER`, and
§5.3 forbids `if superuser: skip all ownership checks`.

`gateway/roles.py` already works this way: every capability is declared, and
`test_every_declared_tool_has_a_capability` fails on an unmapped one. So this adds
capabilities to an existing mechanism rather than introducing one.

**The operator holds every capability today** (`roles.py`'s stated invariant), and
that invariant should not be carved up here — the operator holding
`PORTFOLIO_VIEW_SUPERUSER` is correct. What matters is that a **client** does not,
and that the capability is checked rather than inferred from the role.

### 4.4 The two portfolios are named apart, in the data

The remaining hazard from §3, addressed where it cannot be forgotten:
`display_name`.

The superuser portfolio is created with a name that says what it is, and the
operator's Gateway-stated holdings keep theirs. §96 already established that
naming is what keeps these apart — *"these are holdings told to a representative,
never a broker account"* — and that sentence was written for exactly this
collision, one increment before it could happen.

A test asserts the two are distinguishable in any listing an operator sees.

### 4.5 Provider type: `MANUAL`, not a new one

The superuser portfolio's holdings come from a spreadsheet somebody maintains by
hand. That is `PROVIDER_MANUAL` and `MODE_MANUAL` in TQ-45b's vocabulary, and
`ManualPortfolioProvider` already reads it correctly.

It becomes `SCHWAB` / `LIVE` in TQ-49–TQ-50, and **not before** — §101's
`is_priced()` stays LIVE-only, so nothing about the operator's portfolio is
valued in this increment either. `data/portfolio.xlsx` has a purchase price and no
market price; that does not change here.

### 4.6 The migration reads the spreadsheet once and stops

§16.4: *"Move operator/Superuser data into a Superuser-owned portfolio."*

After it runs, `data/portfolio.xlsx` is **legacy**: still on disk, no longer the
source of truth, and no code path reads it. §16.1 says to mark it as legacy rather
than delete it, which matches this project's `client_holdings_legacy` and
`portfolio_holdings_pre45` habit (§99, §100).

---

## 5. Data contracts

No schema change. TQ-44's `portfolios` table already holds everything needed:

```
owner_type       SUPERUSER
owner_id         <the resolved operator subject>
portfolio_type   PRIMARY
provider_type    MANUAL
data_mode        MANUAL
display_name     names it as the operator's own (§4.4)
simulated        0
```

Holdings are TQ-45a's canonical shape (`symbol`, `quantity`, `average_cost`,
`asset_class`, `as_of`). `data/portfolio.xlsx`'s columns map:

| spreadsheet | canonical | note |
|---|---|---|
| Ticker | `symbol` | |
| Shares | `quantity` | |
| Purchase Price | `average_cost` | per share, which is what `average_cost` means (§100) |
| Purchase Date | `acquired_on` | |
| Account ID | — | **dropped**, see §9 |

`asset_class` is `unknown` unless the sheet says otherwise. It does not.

### New capabilities (`gateway/roles.py`)

```python
CAP_PORTFOLIO_VIEW_SUPERUSER = "portfolio_view_superuser"
CAP_PORTFOLIO_ANALYZE_SUPERUSER = "portfolio_analyze_superuser"
```

Granted to `ROLE_OPERATOR` only. §10's other five (`PORTFOLIO_VIEW_OWN`,
`..._REFRESH_OWN`, `..._MANAGE_CONNECTION`, `..._VIEW_SIMULATION`) are **not**
added here — see §11 Q3.

---

## 6. Files and modules

| file | change |
|---|---|
| `gateway/roles.py` | two capabilities, granted to the operator |
| `gateway/portfolios.py` | one sentence saying which "Superuser" this is (§4.2); `for_superuser` takes the resolved subject |
| `gateway/superuser_portfolio.py` | **new** — creation, the spreadsheet migration, and the operator-facing read |
| `gateway/tools.py` | superuser portfolio tools, under the new capabilities |
| `app/tools/portfolio.py` | retired or re-owned — **§11 Q1** |
| `app/tools/__init__.py`, `backend/main.py` | follow whatever Q1 decides — note `TOOLS` has exactly one entry |
| `app/privacy_preferences.py`, `app/privacy_filter.py`, `app/permissions.py`, `app/main.py`, `desktop/screens/dashboard.py` | **only under Q1's reading A** — the consent subsystem loses its only consumer |
| `tests/test_backend_chat.py`, `test_backend_admin.py`, `test_main_cli.py`, `test_tools_portfolio.py` | exercise the consent flow through this tool |
| `data/portfolio.xlsx` | marked legacy, left on disk |
| `tests/test_superuser_portfolio.py` | **new** — §7 |
| `tests/test_gateway_roles.py` | the two new capabilities in the role matrix |

---

## 7. Required tests

Permanent regressions. The first three are the increment.

**Isolation (§21.6)**

- `test_a_client_cannot_reach_the_superuser_portfolio` — by id, by listing, and
  through every holdings tool
- `test_the_operators_two_portfolios_are_separate_and_named_apart` — §3's real
  hazard: both exist under one owner id, neither resolves the other, and an
  operator reading a listing can tell which is which
- `test_no_client_capability_grants_superuser_portfolio_access` — the capability
  is checked, not inferred from the role (§5.3)

**The ownerless retrieval is gone (§16.7, §21.1)**

- `test_no_portfolio_retrieval_takes_no_owner` — a source scan, in the style of
  `test_nothing_outside_portfolios_queries_the_portfolios_table`, asserting that
  nothing reads `data/portfolio.xlsx` without an owner context

**Migration**

- Every spreadsheet row lands, with `average_cost` per share and `acquired_on`
  preserved
- `Account ID` does not appear in the migrated data **or the database** (§9)
- Idempotent: running it twice does not duplicate holdings
- The superuser portfolio is `MANUAL` / `MANUAL` and `is_priced()` is False

**Vocabulary**

- `test_superuser_means_the_operator_not_the_server_superuser` — asserts the
  distinction §97 recorded, so the three names cannot drift into each other

---

## 8. Acceptance criteria

Addendum 44 §21 items 4 and 6.

1. A `SUPERUSER`-owned portfolio exists, in the same table and behind the same
   guard as every other.
2. No client path resolves to it — by id, by listing, or through any tool.
3. `PORTFOLIO_VIEW_SUPERUSER` / `PORTFOLIO_ANALYZE_SUPERUSER` are declared,
   granted to the operator, and checked rather than inferred.
4. `data/portfolio.xlsx` is migrated, marked legacy, and read by nothing.
5. **No function reaches portfolio data without an owner** (§16.7).
6. The operator's two portfolios are distinguishable in anything they read.
7. Nothing is priced; `is_priced()` unchanged.
8. Full suite green on Windows and Linux.

---

## 9. Security and privacy implications

1. **`Account ID` must not be migrated.** `app/data_classification.py` classes it
   `LOCAL_ONLY` and `privacy_filter` strips it on egress. TQ-44's holdings schema
   has **no account column at all** — the stronger form §96 chose deliberately,
   because *"a field that does not exist cannot be leaked by a future reader who
   forgets to sanitize."* The migration must drop the column, not carry it.
2. **The privacy consent machinery does not come along.** `retrieve_portfolio`'s
   `needs_consent` flow exists because that path forwards the operator's holdings
   to an external reasoning model. Whether the Gateway path needs an equivalent is
   §11 Q2, and it is a real question rather than an oversight.
3. **`PATH_REFUSED` applies** (§108). A superuser portfolio task marked
   `LOCAL_ONLY` on a machine with no local model cannot be done, and says so.
4. **No superuser bypass** (§5.3). The operator gets capabilities, not an
   exemption.

---

## 10. What this increment does not do

Per addendum 44 §19 and §97: the UI tab (TQ-47), snapshots and audit logging
(TQ-48), the Schwab boundary (TQ-49), live trading or money movement, and
cross-client aggregation.

**Administrative access to a client's portfolio stays unimplemented** (§99's
§3.3). §10 permits it only through explicitly authorized administrative
workflows; none exists, and building the permission before the workflow would be
an authorization surface with no consumer.

---

## 11. Open questions

Decide these first and record the decisions, the way TQ-44's three and TQ-45's
five were decided before any code.

**Q1 — Is `retrieve_portfolio` retired, or given an owner?** *The load-bearing
one, and the one whose cost this spec initially undersold.*

§16.7 says *"remove any global get_current_portfolio() behavior that has no owner
argument"*, which admits both readings.

**Measure the blast radius before choosing.** The first draft of this section
said retiring means `/chat` "loses its portfolio tool", which is accurate and
badly incomplete. Measured:

- `app/tools.TOOLS` has **exactly one entry**. `retrieve_portfolio` is not *a*
  backend tool, it is *the* backend tool, and retiring it takes `/chat` to zero.
- It is the **only consumer of the consent subsystem**: `backend/main.py`'s
  `needs_consent` / `consent_answer` / `consent_key` pause-and-resume flow,
  `PrivacyPreferenceStore`'s always/never dispositions, `app/main.py`'s CLI
  prompts, and `desktop/screens/dashboard.py`'s handling of them.
- `privacy_filter.sanitize_portfolio_rows` and the single entry in
  `permissions.RESOURCE_PATHS` exist to serve it.

So the two readings are:

- **A — retire fully.** Delete the tool, the function, and the consent machinery
  that then has no consumer. `/chat` becomes conversation-only and the operator's
  portfolio lives at the Gateway. Cleanest against §16.7, and it deletes a
  working privacy guarantee that cost real effort — one whose *absence* nothing
  would notice, because nothing would exercise it.
- **B — retire the ownerlessness, keep the capability.** Delete
  `retrieve_portfolio` as it stands and give the backend an owned equivalent
  reading the migrated SUPERUSER portfolio. This needs the backend to reach
  portfolio data it structurally cannot (§4.1), so it costs either a second
  portfolios table — two models of one fact, refused in §70, §100 and §104 — or
  an HTTP call inward to the Gateway, which inverts the door.

**Decided 2026-08-26: reading B** — owner's call, and the architecture makes it
cheap rather than expensive.

B was described above as costing "either a second portfolios table or an HTTP
call inward to the Gateway", which was true only while the portfolio subsystem sat
at the Gateway. Owner direction the same day (§109) put it backend-side, where
authorization lives — so the backend reaching an owned portfolio is not a
workaround, it is the specified shape, and the second portfolios table never
arises.

**No consent machinery is deleted.** `retrieve_portfolio` still exists, still
pauses for consent before forwarding holdings to a reasoning model, and still
runs behind `permissions` — it simply stops being ownerless. The subsystem keeps
its only consumer, which under reading A it would have lost.

The one thing to confirm rather than assume, from Q2: that the migrated portfolio
carries the privacy level the consent flow assumes. §108's `PATH_REFUSED` is a
stronger guarantee than a prompt, and the two should agree rather than each
believing it is the control.

**Q2 — Does the Gateway path need the consent flow?** `retrieve_portfolio` pauses
and asks before forwarding holdings to an external model
(`portfolio_holdings:reasoning_model`). The Gateway's holdings tools have no such
pause — because §96's client holdings are the client's own words to their own
agent.

The operator's portfolio going to an external model is a different act. **Leaning:
the honest answer is §108's**, which already exists — a portfolio marked
`LOCAL_ONLY` is refused rather than forwarded, and that is a stronger guarantee
than a consent prompt. But confirm the operator's portfolio *is* marked
`LOCAL_ONLY`, rather than assuming it.

**Q3 — Two capabilities or seven?** §10 lists seven. This spec adds the two the
increment needs. The other five have no consumer: `PORTFOLIO_VIEW_OWN` duplicates
`CAP_HOLDINGS`, `..._MANAGE_CONNECTION` is TQ-49's, `..._VIEW_SIMULATION` is
already covered by the `simulated` flag. **Leaning: two now**, the rest when
something needs them — the standing rule that machinery with no user does not get
built.

**Q4 — Which id owns the SUPERUSER portfolio?** *Flagged here by TQ-69 (its §10
Q3, decided 2026-08-26 to flag rather than settle), and it is load-bearing for
this increment in a way that is easy to miss.*

TQ-69 put the portfolio subsystem behind the backend and had the backend store
`(owner_type, owner_id)` **opaquely** — it authorizes those strings and never
interprets them. That makes this question un-answerable by the backend on purpose,
and answerable by exactly two callers, because only two can assert an owner:

- **the Gateway**, which knows a Gateway subject — §109's reading, where SUPERUSER
  means the operator at the door; and
- **`/chat`**, which knows a backend `username` from `users.json`, already resolved
  by `Depends(get_current_user)` and currently discarded (TQ-69 spec §3).

Those are two different identity populations (TQ-70), so this is a choice between
them rather than a naming detail. TQ-69 narrows the space and deliberately does not
choose within it: choosing there would have been choosing cheaply, in the increment
with no consumer for the answer.

**What this spec must do, beyond deciding:** *store* the choice, and test it.
With two owner domains and two candidate operator ids, the wrong pairing is **not
refused — it returns an empty portfolio.** `resolve()` is working correctly when
that happens: the operator asked under one id and the row is owned by the other,
which is precisely the "not yours" answer, indistinguishable by design from "no
such portfolio" (addendum 44 §9.3). §15.5's permanent regression covers a client
receiving the operator's portfolio. **Nothing yet covers the operator silently
receiving nobody's**, and "no data" is the failure that reads as a working system —
so this increment owes a test with the opposite shape to §15.5's.

Note this interacts with Q1's decided reading B: an owned backend equivalent of
`retrieve_portfolio` reads *the migrated SUPERUSER portfolio*, so if the migration
stamped one id and `/chat` asserts the other, reading B delivers an empty tool
result rather than an error, on the increment's headline path.

---

## 12. Risks

**Risk 1 — the ambiguity, not the breach.** §3. The guard holds; the confusion is
what to design against, and §4.4 is thin protection if the operator-facing output
is not actually checked. Read it, do not assume it.

**Risk 2 — Q1's reading A removes more than a feature.** `retrieve_portfolio` is
the backend's *only* tool and the consent subsystem's *only* consumer, so
retiring it takes `/chat` to zero tools and leaves four modules of privacy
machinery with nothing exercising it. That is the right architecture and a
considerably worse day than "loses its portfolio tool" suggests. **Do not do it
silently**, and do not leave the orphaned machinery in place unexercised —
untested privacy code that nothing calls is the shape of a control that has
already stopped working and not been noticed.

**Risk 3 — the `Account ID` column.** It is in the spreadsheet and must not reach
the database. The test asserts its absence in the data *and* in the schema,
because a migration that carried it into a column nobody reads is still a leak
waiting for a future reader.

---

## 13. Verification

```bash
.venv/Scripts/python.exe -m pytest -q
python -m gateway.superuser_portfolio migrate   # against a COPY first
python -m gateway.superuser_portfolio show
```

Then **run it and look** — the pattern §99, §101, §106 and §108 each earned:

1. Start the Gateway, log in as the operator, and read the superuser portfolio.
2. Log in as a demo client and try to reach it — by id, by listing, and by asking
   the agent for it in conversation.
3. **Ask the operator's agent "what do I hold?"** and check which portfolio comes
   back. This is §3's real hazard and the only place it shows up.
4. Confirm no account id appears anywhere in the output or the database.
5. Stop the stack; confirm no orphaned processes.
