# Handoff — checkpoint 2026-08-26 (TQ-44 complete)

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
.venv/Scripts/python.exe -m pytest -q    # expect 2232 passed, 5 deselected
```

Use **`.venv/Scripts/python.exe`**, not bare `python` — the system Python has no
dependencies installed.

Then read, in order:

1. **This file** — to the end.
2. [`docs/README.md`](README.md) → "Picking up mid-project" — the map.
3. [`docs/TASK_QUEUE.md`](TASK_QUEUE.md) — the head block says what is next.
4. [`docs/specs/`](specs/) — TQ-45 has no spec yet; see §7 below.

---

## 2. Where the project stands

`master` plus this checkpoint, clean and pushed. Suite **2232 passing**. Nothing
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
| §99 | **TQ-44** portfolios as owned entities + the guard | this branch |

**TQ-44 final status: COMPLETE.** `gateway/portfolios.py` is the entity and the
guard; holdings are re-keyed from `client_id` to `portfolio_id`; the migration
ran against a copy of a genuinely pre-TQ-44 database (11 holdings, 4 clients, no
orphans, no owner changed); two clients logged into a running Gateway and each
saw only their own. The spec's three open questions were decided before any code
and are recorded in its §10. Nothing outstanding.

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
8. **Holding field names stay `ticker`/`shares`/`cost_basis` until TQ-45.** The
   rename to addendum 44's `symbol`/`quantity`/`average_cost` is budgeted there.
   Spec §3.9. Do not treat the current names as an oversight.
9. **`resolve()` is the only way to a portfolio, and holdings take a resolved
   portfolio rather than an id.** A second by-id retrieval path is the failure
   mode to watch for — it will not look like a bypass, it will look like a
   convenience. One was nearly written during TQ-44 itself (§99).

---

## 5. Task queue

| Task | Status |
|---|---|
| **TQ-45** — `PortfolioProvider` abstraction + conformance suite | **next — needs a spec** |
| TQ-46 — superuser ownership domain; retire the ownerless retrieval | queued |
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

None blocks TQ-45.

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
6. **`client_holdings_legacy` exists in any migrated database.** Kept for
   diagnosis (spec §10 Q2), dropped in a later increment once confidence is
   established. `demo_clients.clear()` already removes demo rows from it.
7. **`gateway.db` may hold demo data** if the Gateway has been run locally.
   `python -m gateway.demo_clients status` reports; `clear` removes. Must be
   clean before any live exposure.
8. **No exposure beyond loopback.** Nothing is externally reachable (§50's
   preconditions). Several queued items are preconditions *for* exposure, not
   licence to enable it.
9. **Bash heredocs are unreliable here** for large Python files — they fail with
   "unexpected EOF". Use the Write tool for multi-line file creation.

---

## 7. Exactly what to do next

**TQ-45 — the `PortfolioProvider` abstraction and its conformance suite.** Its
queue entry is written; **there is no implementation spec yet**, so the first
step is writing one the way TQ-44's was written (that spec is the model to
follow, and deciding its open questions before coding is the part that paid off).

Two things TQ-44 deliberately handed forward:

1. **The holding field rename.** `ticker`/`shares`/`cost_basis` →
   `symbol`/`quantity`/`average_cost` (addendum 44 §3.4). Budgeted here because
   the canonical holding shape is *what a provider returns*, and doing it in
   TQ-44 meant touching the tool schemas and both test files twice.
   `average_cost` is the better name — unambiguously per-share.
2. **`asset_class` is `UNKNOWN` everywhere today**, honestly so: the old rows do
   not say and the conversational tool does not ask. A provider is the first
   thing that could know, so decide there how a class-aware view treats
   `UNKNOWN` — `concentration` currently ignores the field entirely.

Then: `git checkout -b <name>`, one increment, full suite green, a
`SPEC_RECONCILIATION` §, the queue entry updated, and **run it and look**.

---

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
