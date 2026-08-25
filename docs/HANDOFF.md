# Session handoff — 2026-08-26

Written for a fresh session with no memory of the conversation that produced this
state. Everything needed to continue is here or linked from here.

---

## 1. Run these first

```bash
cd C:/Users/ADMIN/my-ai
git log --oneline -5
git status --porcelain --branch          # expect clean, synced with origin/master
.venv/Scripts/python.exe -m pytest -q    # expect 2187 passed, 5 deselected
```

Note the interpreter: **`.venv/Scripts/python.exe`**, not bare `python` (the
system Python has no dependencies installed).

Then read, in order:

1. `docs/TASK_QUEUE.md` — the queue head says what is next
2. `docs/SPEC_RECONCILIATION.md` — newest § at the end; §92–§98 are this week
3. `docs/plans/TQ-44_portfolios_as_owned_entities.md` — the next task, fully planned

---

## 2. What was completed this session

Seven merged PRs, each with a `SPEC_RECONCILIATION` record:

| § | what | PR |
|---|---|---|
| §92 | Role-based Gateway; operator gets the same studio, proxied | #37 |
| §93 | Client agent identity — **and a conversation leak it uncovered** | #38 |
| §94 | Clock-comparison sweep (63 comparisons audited) | #40 |
| §95 | Client agent skills registry; scope field | #39 |
| §96 | Client-owned holdings + removable demo clients | #41 |
| §97 | Addendum 44 assimilated; TQ-44…TQ-50 queued | #42 |
| §98 | **TQ-43** per-client Gateway credentials | #43 |

`master` is at `943fe71`, clean, pushed, CI green on Windows and Linux.

---

## 3. TQ-43 final status: **COMPLETE**

Merged as `943fe71` (PR #43). CI green on both platforms. Suite 2187 passing.

Clients now register individually in `gateway/clients.py` instead of sharing one
`GATEWAY_CLIENT_PASSWORD_HASH`. Verified live: three demo clients each log in as
themselves, meet their own representative (Nadim / Farida / Yusra), and get their
own conversation and holdings.

```bash
python -m gateway.clients add <id> --name "Display Name"   # password shown once
python -m gateway.clients list | passwd | suspend | activate | remove
```

**Nothing is outstanding on TQ-43.**

---

## 4. TQ-44 status: **PLANNED, NOT IMPLEMENTED**

Full plan: **`docs/plans/TQ-44_portfolios_as_owned_entities.md`**

It contains objective, problem, design decisions, files to change, dependencies,
security implications, required tests, acceptance criteria, and open questions —
written to be implementable without this conversation.

A `gateway/portfolios.py` was started during design and **deliberately deleted**;
its design decisions were folded into the plan. Do not look for it in git — it
was never committed.

Three questions in the plan (§9) are genuinely open and worth deciding before
coding: where the migration lives, whether to drop or rename `client_holdings`,
and what `asset_class` should be for migrated rows.

---

## 5. Current architecture state

**Two processes, two databases.**

- **Backend** (`backend/main.py`, port 8000) — the organization. Owns
  `financial_intelligence.db`. Serves the studio at `/console`, agents, the COO
  (Kumbhakarnan), the simulated market.
- **Gateway** (`gateway/main.py`, port 8100) — the door. Owns `gateway.db`.
  Separate process on purpose (addendum 16 §7).

**Gateway roles** (`gateway/roles.py`, §92): `operator`, `internal`, `client`.
Every route declares a capability; a tripwire test asserts none is reachable
without one. **Tools are capability-gated too** — that was the half that would
have been a breach.

**Per-client everything** (§93, §96, §98): conversations, representative
identity, holdings and now credentials are all keyed by `subject`, resolved from
the session and never from a caller-supplied value.

**The operator's studio through the Gateway** (§92) is the *same file*
(`backend/console/index.html`), proxied — not a second console.

---

## 6. Design decisions a fresh session must not reverse

1. **Nothing is ever valued while data is simulated.** Every price this system
   produces is simulated (addendum 25). `portfolio_valuation` is
   declared-and-unbuilt in `gateway/skills.py` with that as its stated reason.
   Addendum 44 supplies `data_mode`; §97's rule is that market-derived values may
   appear **only** where `data_mode == LIVE`. Do not "just add market value".
2. **No superuser bypass.** Addendum 44 §5.3 forbids `if superuser: skip checks`.
   `SUPERUSER` is a separate owner domain, not a skeleton key. See plan §3.3.
3. **Ownership and capability are separate checks** (`scope` in
   `gateway/skills.py`, §95). Passing one must never imply passing the other.
4. **A client is offered no organizational tools.** `tools.for_role(client)`
   returns holdings tools only. Widening `converse` to add a skill is the failure
   §95 exists to prevent — each skill gets its own capability.
5. **Simulated data is flagged, not named** (§96). `demo_clients.clear()` removes
   by *client*, not by row flag — because holdings stated during a demo
   conversation arrive unflagged and are still demo data.
6. **The client's holdings come from the client.** Not from
   `data/portfolio.xlsx`, which is the operator's and is reached by a different
   path. Wiring them together is the bug §96 exists downstream of.
7. **Errors must not reveal that another client exists** (addendum 44 §9.3).
   `clients.authenticate` compares against a decoy hash for unknown users.
8. **Holding field names stay `ticker`/`shares`/`cost_basis` until TQ-45.** The
   rename to addendum 44's `symbol`/`quantity`/`average_cost` is budgeted there,
   not to be done opportunistically. Plan §3.11.

---

## 7. Task queue state

Head of queue (`docs/TASK_QUEUE.md`):

- **TQ-44** — portfolios as owned entities + the guard ← **NEXT**, planned
- TQ-45 — `PortfolioProvider` abstraction + conformance suite
- TQ-46 — Superuser ownership domain; retire the ownerless retrieval
- TQ-47 — Superuser Portfolio tab
- TQ-48 — Snapshots, provenance, audit logging
- TQ-49 — Schwab boundary, live disabled
- TQ-50 — Schwab live read-only — **BLOCKED on owner obtaining API access**

Also open: TQ-07 (consumer-gated), TQ-20 / TQ-21 (owner actions), TQ-28.

---

## 8. Known open items and concerns

Recorded rather than fixed. None blocks TQ-44.

1. **TQ-28 — the isolation guard trips after a real backend runs.** A read
   changes the database hash (WAL). Known, benign, unfixed. It makes the full
   suite fail if a backend is running; stop the stack before running tests.
2. **TQ-20 / TQ-21 — owner actions.** TQ-21 (verify the WhatsApp copy of
   `backup.key` actually decrypts) is the more urgent: an untested backup is not
   a recovery asset. TQ-20 is the Linux host for a second failure domain.
3. **The clock-comparison family.** Four bugs in four days (§90, §91, §94, and
   the zero-width window in `f5c05d0`). §94 swept all 63 comparisons and
   classified them; the rule is *not* "always use strict" — it depends whether
   the boundary instant belongs to the window. Re-read §94 before touching one.
4. **`app/tools/portfolio.py` has no owner argument.** Addendum 44 §16.7 says to
   remove that global behaviour. It is currently unreachable from the Gateway, so
   it is not urgent — TQ-46 owns it.
5. **`gateway.db` demo data.** If a Gateway has been run locally, it may hold
   simulated clients. `python -m gateway.demo_clients status` reports; `clear`
   removes. Must be clean before any live exposure.
6. **No exposure beyond loopback.** Nothing is reachable externally (§50's
   preconditions). Several queued items are preconditions *for* exposure, not
   licence to enable it.
7. **Bash heredocs are unreliable in this environment** for large Python files —
   they fail with "unexpected EOF". Use the Write tool for multi-line file
   creation.

---

## 9. Exactly what to do next

**Implement TQ-44**, following `docs/plans/TQ-44_portfolios_as_owned_entities.md`.

Suggested first moves:
1. Read the plan end to end, especially §3.3 (no superuser branch) and §9 (open
   questions).
2. Decide the three open questions in §9 and record the decisions.
3. Branch: `git checkout -b portfolios-as-owned-entities`
4. Build `gateway/portfolios.py` first — entity **and** guard together.
5. Write the §15.5 regression test early; it is the point of the increment.
6. Migrate `client_holdings`, testing against a **copy** of a seeded database.
7. Full suite, then run the Gateway and log in as two demo clients to confirm
   each sees only their own portfolio.

---

## 10. Working conventions in this project

- **Branch first.** Do not commit to `master`; open a PR, wait for CI on both
  platforms, merge with `--rebase` to preserve the 1:1 commit↔§record mapping.
- **One increment at a time**, with the full suite green and the count stated.
- **Record before moving on:** a `SPEC_RECONCILIATION.md` §, and the queue entry
  updated.
- **Run it and look.** A green suite is not evidence. Every real defect found in
  this project came from starting the thing and reading its output. See
  `memory/my-ai-look-at-the-running-thing.md`.
- **Never fabricate.** Absent is `null` / `unknown` / `needs_reconstruction`,
  never a plausible default. Simulated data is labelled everywhere it appears.
- **Use copies of the real database** for any live run; never mutate
  `financial_intelligence.db`.
- **Stop the stack afterwards** and confirm no orphaned agent processes remain:
  `taskkill /PID <uvicorn> /T /F`, then check for stray `python.exe`.
