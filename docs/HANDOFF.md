# Handoff — checkpoint 2026-08-26

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
.venv/Scripts/python.exe -m pytest -q    # expect 2187 passed, 5 deselected
```

Use **`.venv/Scripts/python.exe`**, not bare `python` — the system Python has no
dependencies installed.

Then read, in order:

1. **This file** — to the end.
2. [`docs/README.md`](README.md) → "Picking up mid-project" — the map.
3. [`docs/TASK_QUEUE.md`](TASK_QUEUE.md) — the head block says what is next.
4. [`docs/specs/TQ-44_portfolio_ownership_and_isolation.md`](specs/TQ-44_portfolio_ownership_and_isolation.md)
   — the next task, fully specified.

---

## 2. Where the project stands

`master` at **`fddde30`** plus this checkpoint, clean and pushed. Suite **2187
passing**. CI green on Windows and Linux. Nothing running; no orphaned processes.

**Two processes, two databases.**

- **Backend** (`backend/main.py`, port 8000) — the organization. Owns
  `financial_intelligence.db`. Agents, the COO (Kumbhakarnan), the simulated
  market, and the studio at `/console`.
- **Gateway** (`gateway/main.py`, port 8100) — the door. Owns `gateway.db`.
  A separate process on purpose (addendum 16 §7); it is the only component
  intended to face outward.

**The Gateway's security model** (built §92–§98):

- Three roles: `operator`, `internal`, `client`.
- Every route declares a capability; a tripwire test fails if one does not.
- **Model tools are capability-gated too** — that was the half that would have
  been a breach, since route checks are theatre if the agent will fetch things
  on the caller's behalf.
- Client data — conversations, representative identity, holdings, credentials —
  is keyed to a `subject` resolved from the session, never from anything a
  caller sent.
- Clients register individually (`python -m gateway.clients add`); there is no
  shared client password.

**The operator's studio through the Gateway** is the *same file*
(`backend/console/index.html`), proxied — not a second console.

---

## 3. Completed this session

Eight merged PRs, each with a `SPEC_RECONCILIATION` record:

| § | What | PR |
|---|---|---|
| §92 | Role-based Gateway; operator gets the same studio, proxied | #37 |
| §93 | Client agent identity — **and a conversation leak it uncovered** | #38 |
| §94 | Clock-comparison sweep (63 comparisons audited) | #40 |
| §95 | Client agent skills registry; the `scope` field | #39 |
| §96 | Client-owned holdings + removable demo clients | #41 |
| §97 | Addendum 44 assimilated; TQ-44…TQ-50 queued | #42 |
| §98 | **TQ-43** per-client Gateway credentials | #43 |
| — | TQ-44 specification + this handoff | #44, this checkpoint |

**TQ-43 final status: COMPLETE.** Merged `943fe71`, CI green both platforms.
Verified live: three demo clients each log in as themselves, meet their own
representative (Nadim / Farida / Yusra), and get their own conversation and
holdings. Nothing outstanding.

**TQ-44 status: SPECIFIED, NOT IMPLEMENTED.** Full specification at
`docs/specs/TQ-44_portfolio_ownership_and_isolation.md`. A `gateway/portfolios.py`
was started during design and **deliberately deleted** — its reasoning is in the
spec; it is not in git history and should not be looked for.

---

## 4. Constraints that must not be violated

Each cost something to learn. Reversing one silently would undo real work.

1. **Nothing is valued while the data is simulated.** Every price this system
   produces is simulated (addendum 25). `portfolio_valuation` is
   declared-and-unbuilt in `gateway/skills.py` with that as its stated reason.
   Addendum 44 supplies `data_mode`; §97's rule is that market-derived values
   appear **only** where `data_mode == LIVE`. A `market_price` field existing is
   not permission to fill it in.
2. **No superuser bypass.** Addendum 44 §5.3 forbids `if superuser: skip checks`.
   `SUPERUSER` is a separate owner domain, not a skeleton key. Spec §3.3.
3. **Ownership and capability are separate checks.** Passing one must never imply
   passing the other (addendum 44 §2.1; the `scope` field, §95).
4. **A client is offered no organizational tools.** Each new skill gets its own
   capability — widening `converse` is the failure §95 exists to prevent.
5. **Simulated data is flagged, not named.** `demo_clients.clear()` removes by
   *client*, not by row flag, because holdings stated during a demo conversation
   arrive unflagged and are still demo data.
6. **The client's holdings come from the client.** Not from
   `data/portfolio.xlsx`, which is the operator's and reached by a different
   path. Wiring them together is the bug §96 exists downstream of.
7. **Errors must not reveal that another client exists** (addendum 44 §9.3).
   `clients.authenticate` compares against a decoy hash for unknown users;
   `portfolios.resolve` must raise one refusal for absent/foreign/archived.
8. **Holding field names stay `ticker`/`shares`/`cost_basis` until TQ-45.** The
   rename to addendum 44's `symbol`/`quantity`/`average_cost` is budgeted there.
   Spec §3.9. Do not treat the current names as an oversight.

---

## 5. Task queue

| Task | Status |
|---|---|
| **TQ-44** — portfolios as owned entities + the guard | **SPECIFIED — next** |
| TQ-45 — `PortfolioProvider` abstraction + conformance suite | queued |
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

None blocks TQ-44.

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
6. **`gateway.db` may hold demo data** if the Gateway has been run locally.
   `python -m gateway.demo_clients status` reports; `clear` removes. Must be
   clean before any live exposure.
7. **No exposure beyond loopback.** Nothing is externally reachable (§50's
   preconditions). Several queued items are preconditions *for* exposure, not
   licence to enable it.
8. **Bash heredocs are unreliable here** for large Python files — they fail with
   "unexpected EOF". Use the Write tool for multi-line file creation.

---

## 7. Exactly what to do next

**Implement TQ-44**, following
[`docs/specs/TQ-44_portfolio_ownership_and_isolation.md`](specs/TQ-44_portfolio_ownership_and_isolation.md).

1. Read the spec end to end. §3.3 (no superuser branch) and §10 (open questions)
   matter most.
2. Decide the three open questions in §10 and record the decisions.
3. `git checkout -b portfolios-as-owned-entities`
4. Build `gateway/portfolios.py` first — entity **and** guard together.
5. Write the §15.5 regression test early; it is the point of the increment.
6. Migrate `client_holdings`, testing against a **copy** of a seeded database.
7. Full suite, then start the Gateway and log in as two demo clients to confirm
   each sees only their own portfolio.

---

## 8. Working conventions

- **Branch first.** Never commit to `master`. Open a PR, wait for CI on both
  platforms, merge with `--rebase` to preserve the 1:1 commit↔§record mapping.
- **One increment at a time**, full suite green, count stated.
- **Record before moving on:** a `SPEC_RECONCILIATION.md` §, and the queue entry
  updated.
- **Run it and look.** A green suite is not evidence. Every real defect found in
  this project came from starting the thing and reading its output.
- **Never fabricate.** Absent is `null` / `unknown` / `needs_reconstruction`,
  never a plausible default. Simulated data is labelled everywhere it appears.
- **Use a copy of the real database** for any live run; never mutate
  `financial_intelligence.db`.
- **Stop the stack afterwards** and confirm no orphaned agents remain
  (`taskkill /PID <uvicorn> /T /F`, then check for stray `python.exe`).
