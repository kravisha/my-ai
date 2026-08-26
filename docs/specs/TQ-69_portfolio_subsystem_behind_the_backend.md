# TQ-69 — Move the Portfolio Subsystem Behind the Backend

**Implementation specification.** Status: SPECIFIED, not implemented (2026-08-26).

Written so a session with no prior context can build this without further design
work. Where a decision was made, it is recorded with its reasoning so it is not
silently re-litigated; where a question is genuinely open, §10 says so.

| | |
|---|---|
| **Source** | Owner direction 2026-08-26 ([`SPEC_RECONCILIATION.md`](../SPEC_RECONCILIATION.md) §109); addendum 16 §7, §22, §23; addendum 40 §14 |
| **Queue entry** | [`TASK_QUEUE.md`](../TASK_QUEUE.md) TQ-69 |
| **Depends on** | TQ-44 (§99), TQ-45 (§100, §101), TQ-55 (§106) — all done |
| **Blocks** | TQ-46, and everything after it in the addendum 44 lineage |

---

## 1. Objective

Put the portfolio subsystem — the table, the ownership guard, the providers, the
decision log — in the process specified to hold business logic and do
authorization, and have the Gateway reach it the way it already reaches
`/admin`.

On completion: `gateway.db` holds only what authentication needs; a Gateway
request for a client's holdings passes a **backend** authorization check; and the
§15.5 regression still passes, from the Gateway's side, over HTTP.

## 2. Problem

Owner direction, 2026-08-26:

> *"Gateway is for establishing identity — Gateway only does authentication. Back
> end does authorization and all business logic."*

`gateway.db` holds nine tables. Two — `sessions`, `clients` — are authentication.
`portfolios` and `portfolio_holdings` are business logic carrying the ownership
guard that authorizes every read of them.

The direction is not new (§109): addendum 16 §7 forbids external clients reaching
internal databases, `gateway/main.py`'s own docstring calls the Gateway *"a client
of Jarvis, not part of it… talking HTTP to the backend"*, and `gateway/jarvis.py`
already works exactly that way. What drifted is where the data went.

**The concrete consequence, stated plainly:** the Gateway's ownership check is
currently the *only* check. There is no backend authorization to bypass, because
there is no backend authorization. That is addendum 40 §14's warning reached from
the other side.

---

## 3. What the investigation turned up, and it shapes everything below

**This system has three separate identity populations**, and they were not
designed as one:

| population | where | who is in it |
|---|---|---|
| backend users | `users.json`, `app/users.py`, `user_data/<username>/` | My AI users — per-user permissions, preferences, audit |
| Gateway clients | `clients` table in `gateway.db` (§98) | the `subject` that owns portfolios, holdings, conversations |
| environment credentials | `gateway/auth.py`, `MY_AI_ADMIN_USERS` | operator, internal, and the Gateway's own backend account |

`gateway/auth.py` says the separation is deliberate: the Gateway credential is
*"not the ordinary application"* account and comes from the environment rather
than `users.json`.

So "move portfolios to the backend" has a question inside it that is not about
tables: **whose id owns a portfolio, once the owner and the store are in
different processes?** §4.2 answers it.

**A second thing the investigation found, which matters for TQ-46:**
`backend/main.py`'s `/chat` already resolves `username = Depends(get_current_user)`
and passes it nowhere near `retrieve_portfolio`. The owner is *available at the
call site* and simply not handed down. §16.7's "ownerless retrieval" is not
missing an identity mechanism — it is discarding one it already has.

---

## 4. Design decisions

Decided. Do not re-open without recording a reason.

### 4.1 What moves, and what stays

**Moves to the backend:** `portfolios`, `portfolio_holdings`,
`gateway/portfolios.py`'s guard, `gateway/holdings.py`,
`gateway/portfolio_providers.py`, and `app/routing_decisions.py`'s log where it
records portfolio work.

**Stays at the Gateway:** `sessions`, `clients`, `gateway/auth.py`,
`gateway/roles.py`'s route-level capability gating.

**Route gating stays and is not the drift** (§109). Addendum 17 §14 calls the
Gateway a high-security boundary and §92 built that deliberately — a door that
refuses is not a door doing business logic. After this increment there are two
checks where there is currently one, which is the point.

**Not moved here:** `client_agents`, `conversations`, `messages`,
`scoreboard_items`, `scoreboard_notes`. Same category of drift, same argument, and
nothing in the queue needs them moved. Moving four subsystems because one needed
it is how a boundary correction becomes a rewrite (§109).

### 4.2 The backend stores `owner_id` opaquely

The key decision, and the one that keeps this increment small.

The backend does **not** learn who Gateway clients are. It stores
`(owner_type, owner_id)` as opaque strings and authorizes against them exactly as
`portfolios.resolve()` does today. The Gateway authenticates a client, then
asserts a subject to the backend; the backend authorizes *that subject* against
*that portfolio*.

That is precisely the owner's division: **the Gateway establishes identity, the
backend decides what that identity may reach.** The alternative — reconciling
`users.json` with the Gateway's `clients` table — is a much larger change, needed
by nothing here, and is §10 Q2's, not this increment's.

Addendum 44 §9.2 says *"a client_id received from the front end is not sufficient
proof of ownership."* The Gateway is not the front end. It is the authenticator,
and it is itself authenticated to the backend (`gateway/jarvis.py` logs in with
`GATEWAY_BACKEND_USER` and renews on 401). The phone remains unable to assert a
subject; only the Gateway can, and only because it proved who it is first.

### 4.3 What this buys, and what it does not — stated so nobody overclaims it

**It does not defend against a compromised Gateway.** A Gateway that an attacker
controls can assert any `owner_id` it likes. That is inherent to any
on-behalf-of design and it must not be papered over.

**It defends against a *buggy* Gateway**, which is the realistic failure and the
one this project has already had twice: §93's conversation leak and §106's
privacy-misrouting finding were both Gateway-side logic serving the wrong data,
neither of which any second check existed to catch.

Note the comparison honestly: today a compromised Gateway *has the database*, so
the move does not weaken anything. It adds a check the current arrangement cannot
have, and that check is worth having for the failure mode that actually occurs.

### 4.4 The HTTP surface is on-behalf-of, and says so in its shape

A new surface, not `/admin` — `/admin` is the operator's read-only window and
these calls act for a client.

```
POST /portfolios/resolve      {owner_type, owner_id, portfolio_id}
GET  /portfolios              ?owner_type&owner_id
POST /portfolios/primary      {owner_type, owner_id, ...}
GET  /portfolios/{id}/holdings ?owner_type&owner_id
POST /portfolios/{id}/holdings {owner_type, owner_id, symbol, quantity, ...}
```

Every route takes the owner explicitly and **every route authorizes**. There is
deliberately no route that returns a portfolio without an owner — §16.7's rule
applied to the new surface before it can be broken, rather than after.

`require_gateway` gates the surface: the caller must be the Gateway's own backend
account. An ordinary backend user reaching these routes is refused, because they
have no business asserting somebody else's subject.

### 4.5 The Gateway keeps no cache

Addendum 16 §23 wants the Gateway usable when an internal component is down,
which is why it has local storage at all. That reasoning does not extend here.

A conversation the Gateway cannot reach is an inconvenience. **Holdings the
Gateway cannot reach must not be served from a stale copy** — showing somebody
last week's positions as though they were current is the same class of wrong as
§101's `is_priced` rule, and worse than showing nothing.

So: no cache, and an honest refusal naming the backend as unavailable. §17's
failure behaviour agrees — *"do not silently claim it is current."*

### 4.6 One table, one guard — unchanged

`resolve()` moves; it does not multiply. Two portfolios tables would be two
models of one fact (§70, §100, §104) and two answers to *"whose data is this?"*,
which is what TQ-44 existed to prevent. The tripwire moves with it.

---

## 5. Files and modules

| file | change |
|---|---|
| `backend/portfolios.py` | **moved** from `gateway/portfolios.py`; tables into `fi_db`'s schema |
| `backend/holdings.py` | **moved** from `gateway/holdings.py` |
| `backend/portfolio_providers.py` | **moved** from `gateway/portfolio_providers.py` |
| `backend/main.py` | the `/portfolios` surface (§4.4) and `require_gateway` |
| `gateway/portfolio_client.py` | **new** — the HTTP client, shaped like `gateway/jarvis.py` |
| `gateway/tools.py` | holdings tools call the client instead of the local module |
| `gateway/demo_clients.py` | seeds through the backend |
| `gateway/store.py` | stops creating the two tables |
| `tests/*` | see §7 |

`gateway/jarvis.py` is the model for the client: connect and read timeouts, login
with renewal on 401, and the refusal enforced in the one method that reaches the
network.

---

## 6. Migration procedure

The dangerous part — it moves live client financial data between **databases**,
not just between tables.

1. Add `portfolios` and `portfolio_holdings` to `fi_db`'s schema.
2. Read every row from `gateway.db`.
3. Write them to `financial_intelligence.db`, preserving `portfolio_id`,
   `owner_type`, `owner_id`, `as_of` and `simulated` exactly. **A migration that
   restamps or re-keys anything has changed whose data it is.**
4. **Verify**: counts match; every portfolio resolves for its original owner;
   no holding changed portfolio; no owner changed.
5. Rename the `gateway.db` tables to `*_pre69` rather than dropping them —
   §16.1's habit, and this project's (`client_holdings_legacy`,
   `portfolio_holdings_pre45`).
6. Idempotent: the rename removes what a second run would look for.

**Test against a copy of a seeded database before trusting it** — the standing
rule (§99, §100), and this is the increment where it matters most.

**Three legacy tables will then exist** in a fully-migrated database. Dropping
them is worth its own line rather than accumulating quietly (§100 already flagged
two).

---

## 7. Required tests

The first is the increment. If it does not pass over HTTP, the move failed
whatever else is green.

**§15.5, from the Gateway's side, over the wire**

- `test_a_client_cannot_receive_the_superuser_portfolio_when_it_is_the_only_one`
  — the same permanent regression as §99, now exercised through the Gateway's
  HTTP client against a real backend route. It reproduced §93's leak in portfolio
  form; the move must not reintroduce the shape it was written against.

**The guard is now the backend's**

- Every isolation test from `tests/test_gateway_portfolios.py` runs against the
  backend module
- `test_the_backend_refuses_a_foreign_owner_even_when_the_gateway_asks` — the
  new check that did not exist before, and the reason for the increment
- `test_an_ordinary_backend_user_cannot_reach_the_portfolio_surface` — §4.4's
  `require_gateway`

**No ownerless route**

- A source scan over the new surface: no route returns portfolio data without an
  owner argument. §16.7's rule applied before it can be broken.

**Failure behaviour (§4.5)**

- Backend down → the Gateway refuses in words, and serves nothing stale
- `test_the_gateway_holds_no_portfolio_table` — `gateway.db`'s schema after this
  increment

**Migration**

- Counts match; ids, owners and `as_of` preserved exactly; idempotent; verified
  against a copy of a seeded database

---

## 8. Acceptance criteria

1. `portfolios` and `portfolio_holdings` are in `financial_intelligence.db` and
   nowhere else.
2. A Gateway request for holdings passes a backend authorization check.
3. No route returns portfolio data without an owner.
4. An ordinary backend user cannot reach the portfolio surface.
5. The §15.5 regression passes over HTTP.
6. The Gateway serves no stale portfolio data when the backend is unavailable.
7. Migration verified against a copy; nothing re-keyed, nothing re-owned.
8. Full suite green on Windows **and** Linux.

---

## 9. Security implications

1. **Two checks where there was one.** The Gateway gates the route, the backend
   authorizes the owner. §93 and §106 were both Gateway-side logic errors that no
   second check existed to catch.
2. **The trust boundary is explicit** (§4.2, §4.3). The backend trusts the
   Gateway's asserted subject because the Gateway is authenticated and is the
   authenticator. It does not defend against a compromised Gateway, and §4.3 says
   so rather than implying otherwise.
3. **`require_gateway` is not optional.** A surface that accepts an asserted
   subject from anyone is worse than no surface — it lets any authenticated
   backend user read any client's portfolio.
4. **No stale data on failure** (§4.5).
5. **The migration carries no new fields.** Nothing is added while data is in
   flight; it lands exactly as it left.

---

## 10. Open questions

**Q1 — Does the routing decision log move too?** `app/routing_decisions.py`
(§106) shares `model_performance.db`, which is neither database. It records
*routing*, not portfolios, and moving it would drag the leaderboards with it.
**Leaning: leave it.** It is `app/`-level infrastructure both processes import,
like `model_budget`, and that is a third honest category rather than drift. Worth
ten minutes' confirmation, because "leave it" is also what somebody would say to
avoid the work.

**Decided 2026-08-26: leave it — and the ten minutes were spent rather than
skipped.**

The confirmation the leaning asked for is a specific one, because "it records
routing, not portfolios" is an assertion about *columns*, and a column is
checkable. The question that decides Q1 is not "is this module about
portfolios?" — it is **does this table hold a second copy of client financial
data outside the guard?** If it did, leaving it would put holdings somewhere
`resolve()` cannot reach: the failure this whole increment exists to close,
wearing a name that would never attract attention.

It does not. `routing_decisions`' twenty-seven columns were read — identifiers,
timings, costs, a model name, a rank, a validation result, a status — and
`task_signature`, which is `app/task_signature.py`'s fifteen fields serialised.
Those fifteen were read too, and every one is a *classification* of a task
(category, complexity, privacy level, error cost, four required-capability
booleans, a context **length**) rather than any of its content. **No symbol, no
quantity, no owner id, no free-text payload.** Nothing in the log identifies a
client or reveals a position, so nothing in it belongs behind the ownership
guard, and there is no second copy to leave behind.

That is what makes the "third honest category" argument load-bearing rather than
convenient. `app/` holds what both processes import and neither owns —
`model_budget`, `capability`, `task_signature`, and this. The owner's line
(§109) divides *Gateway* from *backend*; it does not say everything must be one
of those two, and inventing that reading would move `model_budget` next, then
`capability`, and the boundary correction becomes the rewrite §109 explicitly
declined.

One consequence is worth stating rather than discovering: the routing log now
records work whose *data* lives in a different process from the one that logged
the decision. That costs nothing today — the two are never joined, and the log
was already keyed by task rather than by portfolio — but if anything ever wants
"which routing decisions touched this client's holdings", the answer is that the
log cannot say, deliberately. Adding an owner id to it would be adding client
identity to a table that has spent this increment earning the right not to have
any. **§106's rule stands unchanged: the log detects privacy misrouting, it does
not prevent it, and it must never become a place client data is kept.**

**Q2 — Do the identity populations get reconciled?** Three exist (§3), and this
increment deliberately keeps them apart by storing `owner_id` opaquely. Merging
`users.json` with the Gateway's `clients` table is a much larger change, needed by
nothing here. **Leaning: not now, and record it as known.** But it should be
*queued* rather than left implicit — a system with three identity stores and no
entry saying so is one where the fourth arrives without comment.

**Decided 2026-08-26: not now, and queued as TQ-70 rather than recorded as a
footnote.**

Not now, for the reason the leaning gives and one it does not. The reason it
gives: nothing in this increment needs it, and §4.2's opaque `owner_id` is what
keeps the move small. The reason it does not: **reconciling identity stores is a
data migration over credentials**, and this increment is already a data migration
over client financial records. Two of those in one change means that if the
result is wrong, nobody can tell which half did it.

Queued rather than noted, because a known thing with no entry is an unknown thing
with a good memory. TQ-70 owns the question, and it inherits one fact this
increment establishes that the reconciliation will have to answer to: the backend
now stores `(owner_type, owner_id)` for real client financial data **without
knowing what those strings mean**. Any future merge of `users.json` with the
`clients` table either preserves those strings exactly or re-keys somebody's
portfolio, and §6.3 already says what this project thinks of re-keying — *a
migration that restamps or re-keys anything has changed whose data it is.*

The third population — environment credentials (`gateway/auth.py`,
`MY_AI_ADMIN_USERS`, and now `GATEWAY_BACKEND_USER` as the backend reads it) —
is deliberately **not** a merge candidate. `gateway/auth.py` says its separation
is intentional, and an operator credential living in the same store as customer
logins would be one compromise away from being one. TQ-70 should say that out
loud rather than treat "three stores" as three of the same kind of thing.

**Q3 — Which id owns the SUPERUSER portfolio?** TQ-46's, but this increment
determines the answer space. §109 says SUPERUSER means the operator at the
Gateway; `/chat` knows a backend `username`. Those are different populations, and
TQ-46 cannot be built until somebody says which one owns the operator's
portfolio. **Flag it in TQ-46's spec rather than deciding it here.**

**Decided 2026-08-26: not decided here — flagged in TQ-46's spec as its §11 Q4 (its Q3 was already taken).
This increment narrows the answer space rather than choosing within it.**

Deciding it here would be deciding it *cheaply*, in the increment that has no
consumer for the answer, and it would arrive in TQ-46 as a constraint nobody
remembered choosing.

What this increment does settle, and what TQ-46 inherits:

- `owner_type` stays a two-member closed vocabulary, `CLIENT` and `SUPERUSER`,
  and `SUPERUSER` remains **a separate owner domain, not a skeleton key**
  (addendum 44 §5.3). Whichever id wins, it wins *inside* that domain and reaches
  no client.
- The backend never interprets `owner_id` (§4.2). So the question is not "what
  can the backend accept?" — it accepts either string — it is **who asserts it**,
  and only two callers can: the Gateway, which knows a Gateway subject, and
  `/chat`, which knows a backend `username` that is already resolved and already
  discarded (§3).
- The answer is therefore forced to be one of exactly two, and TQ-46 must pick one
  and *store the choice*.

That last point carries a consequence worth naming now. With two owner domains
and two possible operator ids, the wrong pairing is **not refused — it produces
an empty portfolio**. §15.5's regression covers a client receiving the operator's
portfolio; nothing yet covers the operator silently receiving nobody's, and
"no data" is the failure that reads as a working system.

---

## 11. Risks

**Risk 1 — it moves live client financial data between databases.** The
migration is the dangerous part and §6 is written accordingly. Test against a
copy; verify before renaming; never re-key.

**Risk 2 — a partial move is worse than none.** If some reads go over HTTP and
others still hit `gateway.db`, there are two sources of truth for one fact — the
problem this project has refused four times. The Gateway must stop creating those
tables in the same increment that stops reading them.

**Risk 3 — the refusal path is the one nobody tests.** §4.5's "backend down"
behaviour is easy to write and easy to leave unexercised. Test it by actually
stopping the backend, not by mocking a timeout.

**Risk 4 — overclaiming what the check buys.** §4.3. A second check against a
buggy Gateway is genuinely valuable; described as protection against a
compromised one it would be false, and a false security claim is worse than an
absent one.

---

## 12. Out of scope

The other four drifted subsystems (§4.1). Reconciling identity populations
(§10 Q2). Anything in addendum 44's TQ-46 onward — this increment moves the
subsystem and changes no behaviour a client can see. No exposure changes: §50's
preconditions stand.

---

## 13. Verification

```bash
.venv/Scripts/python.exe -m pytest -q
```

Then **run it and look**, which for this increment means running *both*
processes:

1. Migrate a **copy** of a seeded database; confirm counts, ids and owners.
2. Start the backend and the Gateway. Log in as two demo clients; confirm each
   sees only their own holdings — now over HTTP.
3. **Stop the backend with the Gateway still running.** Ask a client for their
   holdings. The refusal must name the backend as unavailable and serve nothing.
   This is Risk 3 and it is the step most likely to be skipped.
4. Confirm `gateway.db` no longer contains the two tables.
5. Stop both; confirm no orphaned processes.
