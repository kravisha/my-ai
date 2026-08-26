# Handoff — checkpoint 2026-08-26 (TQ-45 complete)

Written for a session with **no memory of the conversation that produced this
state**. Everything needed to continue is here or linked from here.

This file describes the *present*. It is rewritten at each checkpoint rather than
appended to — the history lives in `SPEC_RECONCILIATION.md` and in git.

---

## 1. Run these first

```bash
cd C:/Users/ADMIN/my-ai
git log --oneline -5
git status --porcelain --branch          # expect clean, synced with origin/master
.venv/Scripts/python.exe -m pytest -q    # expect 2298 passed, 5 deselected
```

Use **`.venv/Scripts/python.exe`**, not bare `python` — the system Python has no
dependencies installed.

Then read, in order:

1. **This file** — to the end.
2. [`docs/README.md`](README.md) → "Picking up mid-project" — the map.
3. [`docs/TASK_QUEUE.md`](TASK_QUEUE.md) — the head block says what is next.
4. [`docs/TASK_QUEUE.md`](TASK_QUEUE.md) TQ-46 — the next task. **It has no
   specification yet**; see §7.

---

## 2. Where the project stands

`master` plus this checkpoint, clean and pushed. Suite **2298 passing**. Nothing
running; no orphaned processes.

**Two processes, two databases.**

- **Backend** (`backend/main.py`, port 8000) — the organization. Owns
  `financial_intelligence.db`. Agents, the COO (Kumbhakarnan), the simulated
  market, and the studio at `/console`.
- **Gateway** (`gateway/main.py`, port 8100) — the door. Owns `gateway.db`.
  A separate process on purpose (addendum 16 §7); it is the only component
  intended to face outward.

**The Gateway's security model** (built §92–§99):

- Three roles: `operator`, `internal`, `client`.
- Every route declares a capability; a tripwire test fails if one does not.
- **Model tools are capability-gated too** — that was the half that would have
  been a breach, since route checks are theatre if the agent will fetch things
  on the caller's behalf.
- Client data — conversations, representative identity, holdings, portfolios,
  credentials — is keyed to a `subject` resolved from the session, never from
  anything a caller sent.
- Clients register individually (`python -m gateway.clients add`); there is no
  shared client password.
- **Portfolios are owned entities** (§99). `portfolios.resolve()` is the one
  function that answers "whose data is this?", and a tripwire test fails if any
  other module queries the table.
- **Holdings arrive through a provider** (§101). `gateway/portfolio_providers.py`
  is the one interface; its data-reaching methods take a *resolved portfolio*,
  never an id.

**The operator's studio through the Gateway** is the *same file*
(`backend/console/index.html`), proxied — not a second console.

---

## 3. Completed this session

Nine merged PRs, each with a `SPEC_RECONCILIATION` record:

| § | What | PR |
|---|---|---|
| §92 | Role-based Gateway; operator gets the same studio, proxied | #37 |
| §93 | Client agent identity — **and a conversation leak it uncovered** | #38 |
| §94 | Clock-comparison sweep (63 comparisons audited) | #40 |
| §95 | Client agent skills registry; the `scope` field | #39 |
| §96 | Client-owned holdings + removable demo clients | #41 |
| §97 | Addendum 44 assimilated; TQ-44…TQ-50 queued | #42 |
| §98 | **TQ-43** per-client Gateway credentials | #43 |
| — | TQ-44 specification + previous handoff | #44 |
| §99 | **TQ-44** portfolios as owned entities + the guard | #46 |
| — | TQ-45 specified; two collisions named before anybody hit them | #47 |
| §100 | **TQ-45a** the canonical holding shape | #48 |
| §101 | **TQ-45b** the provider abstraction + its conformance suite | this branch |

**TQ-44 final status: COMPLETE.** `gateway/portfolios.py` is the entity and the
guard; holdings are re-keyed from `client_id` to `portfolio_id`; two clients
logged into a running Gateway and each saw only their own.

**TQ-45 final status: COMPLETE.** 45a (§100) made holdings `symbol` /
`quantity` / `average_cost` / `as_of` with the house `asset_class` vocabulary.
45b (§101) put `PortfolioProvider` between the analyzer and wherever holdings
come from, with a conformance suite two providers satisfy, and rebuilt the demo
clients on §6.1's diversity. All five of the spec's open questions are decided
and recorded in its §11. Nothing outstanding.

**TQ-46 is next and has no specification yet.**

---

## 4. Constraints that must not be violated

Each cost something to learn. Reversing one silently would undo real work.

1. **Nothing is valued while the data is simulated.** Every price this system
   produces is simulated (addendum 25). `portfolios.is_priced()` is now the
   single mechanical rule — `data_mode == LIVE` and nothing else — and every
   portfolio this build creates is `MANUAL`. A `market_price` field existing is
   not permission to fill it in.
2. **No superuser bypass.** Addendum 44 §5.3 forbids `if superuser: skip checks`.
   `SUPERUSER` is a separate owner domain, not a skeleton key. There is exactly
   **one** ownership comparison in `gateway/portfolios.py` (`_owned_by`) and both
   domains go through it. A second one is where a bypass gets written.
3. **Ownership and capability are separate checks.** Passing one must never imply
   passing the other (addendum 44 §2.1; the `scope` field, §95).
4. **A client is offered no organizational tools.** Each new skill gets its own
   capability — widening `converse` is the failure §95 exists to prevent.
5. **Simulated data is flagged, not named.** `demo_clients.clear()` removes by
   *client*, not by row flag, because holdings stated during a demo conversation
   arrive unflagged and are still demo data. It also clears
   `client_holdings_legacy`, or demo rows would survive there.
6. **The client's holdings come from the client.** Not from
   `data/portfolio.xlsx`, which is the operator's and reached by a different
   path. Wiring them together is the bug §96 exists downstream of.
7. **Errors must not reveal that another client exists** (addendum 44 §9.3).
   `clients.authenticate` compares against a decoy hash for unknown users;
   `portfolios.resolve` raises one identical refusal for absent/foreign/archived.
   **The ordering inside `resolve` is load-bearing** — ownership is compared
   *before* the row is interpreted, so a corrupt row cannot become an existence
   oracle. See §99 and `test_an_unreadable_row_still_refuses_a_stranger…`.
8. **One vocabulary for asset class** (§100, spec §11 Q1). `gateway/holdings.py`
   **imports** `reference_data.ASSET_CLASSES` rather than mirroring it, plus
   `unknown`. Addendum 44's `EQUITY`/`OPTION` were withdrawn because §70 had
   already refused that substitution once — two models of one fact. Do not
   reintroduce them, and do not copy the list.
   `implemented_asset_classes` is **not** a limit on what a client may hold.
9. **`resolve()` is the only way to a portfolio; holdings and providers take a
   resolved portfolio, never an id.** A second by-id retrieval path is the
   failure mode to watch for — it will not look like a bypass, it will look like
   a convenience. One was nearly written during TQ-44 itself (§99), and
   addendum 44 §7's own `get_holdings(account_ref)` is another, declined in
   TQ-45b's spec §3.2. `test_no_provider_method_accepts_a_bare_id` scans **every
   public method** for an id-shaped parameter; it was widened after a mutation
   run showed the fixed-list version missing exactly that case.
10. **A provider says what it cannot do** (§101). `get_balances` and `refresh`
    have no honest answer for a manual portfolio, so they raise
    `ProviderCapabilityUnavailable` carrying a sentence the client can hear.
    Never return `{}` or a zero: those are answers, and the true answer is an
    explanation.
11. **`is_priced()` is one line and LIVE-only.** A simulated portfolio is not
    priced (spec §11 Q2). A cash balance is not a price — it is a quantity
    somebody holds, not a valuation — which is why `get_balances` may exist
    without widening the rule.

---

## 5. Task queue

| Task | Status |
|---|---|
| **TQ-46** — superuser ownership domain; retire the ownerless retrieval | **next — needs a spec** |
| TQ-45 — the provider abstraction | **DONE** §100 (45a), §101 (45b) |
| TQ-47 — Superuser Portfolio tab | queued |
| TQ-48 — snapshots, provenance, audit logging | queued |
| TQ-49 — Schwab boundary, live disabled | queued |
| TQ-50 — Schwab live, read-only | **BLOCKED** — owner obtaining API access |
| TQ-07 | consumer-gated |
| TQ-20 / TQ-21 | owner actions |
| TQ-28 | open, benign |

Full entries and reasoning in [`TASK_QUEUE.md`](TASK_QUEUE.md).

---

## 6. Open items and known issues

None blocks TQ-46.

1. **TQ-21 — verify the off-machine copy of `backup.key` actually decrypts.**
   Owner action, and the most worth raising: an untested backup is not a recovery
   asset.
2. **TQ-20 — Linux host for a second failure domain.** Owner action, deferred.
3. **TQ-28 — the isolation guard trips after a real backend runs.** A read
   changes the database hash (WAL). Known, benign, unfixed. **Stop the stack
   before running the suite** or it fails spuriously.
4. **The clock-comparison family.** Four bugs in four days (§90, §91, §94, and
   the zero-width window in `f5c05d0`). §94 swept all 63 comparisons and
   classified them. The rule is **not** "always use strict" — it depends whether
   the boundary instant belongs inside the window. Re-read §94 before touching
   one.
5. **`app/tools/portfolio.py` has no owner argument.** Addendum 44 §16.7 says to
   remove that global behaviour. Currently unreachable from the Gateway, so not
   urgent; TQ-46 owns it.
6. **Two retired holdings tables now exist** in a migrated database:
   `client_holdings_legacy` (pre-TQ-44, keyed by *client*) and
   `portfolio_holdings_pre45` (pre-TQ-45a, keyed by *portfolio*). Both are kept
   for diagnosis and both are reached by `demo_clients.clear()` — the second only
   after §100 found it was not. **They are keyed differently, which is what made
   that easy to get half-right**; anything else that sweeps them must handle both
   keys. Dropping them deliberately is worth a line in TQ-46.
7. **`acquired_on` accepts prose.** A live agent stored `"last month"` there,
   which is what the client said rather than an invention, but a date column that
   takes free text is worth a decision. Predates TQ-45a; belongs with TQ-48's
   provenance work.
8. **`gateway.db` may hold demo data** if the Gateway has been run locally.
   `python -m gateway.demo_clients status` reports; `clear` removes. Must be
   clean before any live exposure.
9. **No exposure beyond loopback.** Nothing is externally reachable (§50's
   preconditions). Several queued items are preconditions *for* exposure, not
   licence to enable it.
10. **Bash heredocs are unreliable here** for large Python files — they fail
    with "unexpected EOF". Confirmed again this session. Use the Write tool.
11. **`Database.transaction` refuses `executescript`.** sqlite3 commits before
    running a script, which would end the transaction and make a rollback
    impossible while still looking atomic. Issue DDL with `execute` inside a
    transaction block. The TQ-45a migration hit this on its first run.

---

## 7. Exactly what to do next

**TQ-46 — the Superuser portfolio as its own ownership domain.** Its queue entry
is written; **there is no implementation spec yet**, so the first step is writing
one the way TQ-44's and TQ-45's were written. Both are the model to follow, and
deciding their open questions before coding is the part that paid off twice.

What TQ-46 inherits, already decided and built:

1. **`SUPERUSER` is a separate owner domain, not a skeleton key** (§99). The
   guard already refuses a superuser reaching a client's portfolio, and a test
   asserts it from both directions. TQ-46 gives the operator portfolios of their
   *own*; it must not add a branch to `resolve`.
2. **`app/tools/portfolio.py` still has no owner argument** — addendum 44 §16.7
   says to remove that global behaviour, and this is the entry that owns it.
   Currently unreachable from the Gateway.
3. **A provider interface exists** (§101), so the operator's portfolio has an
   obvious shape to arrive in rather than needing a new one.

Then: `git checkout -b <name>`, one increment, full suite green, a
`SPEC_RECONCILIATION` §, the queue entry updated, and **run it and look**.

## 8. Working conventions

- **Branch first.** Never commit to `master`. Open a PR, wait for CI on both
  platforms, merge with `--rebase` to preserve the 1:1 commit↔§record mapping.
- **One increment at a time**, full suite green, count stated.
- **Record before moving on:** a `SPEC_RECONCILIATION.md` §, and the queue entry
  updated.
- **Run it and look.** A green suite is not evidence. Every real defect found in
  this project came from starting the thing and reading its output. TQ-44's own
  verification is the pattern: seed a scratch database, start the Gateway, log in
  as two clients, and *ask the agent for the other client's data* rather than
  only asserting it in a test.
- **Never fabricate.** Absent is `null` / `unknown` / `needs_reconstruction`,
  never a plausible default. Simulated data is labelled everywhere it appears.
- **Use a copy of the real database** for any live run; never mutate
  `financial_intelligence.db`. To test a migration against realistic data, a
  `git worktree` at the pre-migration commit can seed one honestly with the old
  code — that is how TQ-44's was verified.
- **Stop the stack afterwards** and confirm no orphaned agents remain
  (`taskkill /PID <uvicorn> /T /F`, then check for stray `python.exe`).
