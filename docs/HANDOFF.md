# Handoff — checkpoint 2026-08-26 (TQ-69 merged)

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
.venv/Scripts/python.exe -m pytest -q    # expect 2497 passed, 1 skipped, 5 deselected
```

Use **`.venv/Scripts/python.exe`**, not bare `python` — the system Python has no
dependencies installed.

The **1 skipped** is deliberate and not a problem: it is the `none_single_model`
rung's tripwire, standing down because a later rung of the routing ladder now
governs (§103, §105).

Then read, in order:

1. **This file** — to the end.
2. [`docs/README.md`](README.md) → "Picking up mid-project" — the map, including a
   table of where each kind of answer lives.
3. [`docs/TASK_QUEUE.md`](TASK_QUEUE.md) — the head block says what is next.
4. [`docs/specs/TQ-46_superuser_ownership_domain.md`](specs/TQ-46_superuser_ownership_domain.md)
   — the next task, fully specified. **Read its §11 Q4 first.**

---

## 2. Where the project stands

`master` clean and pushed. Suite **2497 passing, 1 skipped**. CI green on Windows
and Linux. Nothing running; no orphaned processes.

**Three areas.**

- **Backend** (`backend/main.py`, port 8000) — the organization, and since TQ-69
  the holder of **all business logic and all authorization**. Owns
  `financial_intelligence.db`, which now includes `portfolios` and
  `portfolio_holdings`. Agents, the COO (Kumbhakarnan), the simulated market, the
  studio at `/console`. Has its own per-user model (`users.json`, `/auth/login`,
  `get_current_user`).
- **Gateway** (`gateway/main.py`, port 8100) — the door, and **only** the door.
  Owns `gateway.db`, which now holds sessions, clients, conversations, messages,
  client agents and the scoreboard. Reaches portfolios over HTTP through
  `gateway/portfolio_client.py`. The only component intended to face outward.
- **The routing subsystem** (`app/`) — imported by both processes:
  `task_signature`, `model_performance`, `routing_decisions`, `local_ai`,
  `capability`, and now `gateway_auth`. **Infrastructure only; no local model
  behind it.** TQ-69 §10 Q1 confirmed this is a third honest category rather than
  drift: nothing in it holds client data.

**Owner direction, 2026-08-26 (§109):** *"Gateway is for establishing identity —
Gateway only does authentication. Back end does authorization and all business
logic."* **TQ-69 (§110) corrected the portfolio half.** Route-level capability
gating stays at the Gateway and was never the drift.

**The security model as it now stands** (§92–§101, §110): three roles at the
Gateway; every route and every model tool declares a capability with a tripwire;
client data keyed to a `subject` resolved from the session; per-client
credentials; portfolios as owned entities behind one guard — **in the backend**,
reached only by the Gateway's own backend account through `require_gateway`.

---

## 3. Completed since the last checkpoint

One merged record, `SPEC_RECONCILIATION.md` §110. Suite went 2462 → 2497.

| § | What | PR |
|---|---|---|
| — | TQ-69's three §10 questions decided and recorded; owner's answer on Inkling recorded in TQ-52 | — |
| §110 | **TQ-69** — the portfolio subsystem behind the backend, with the migration and the live check | — |

### What TQ-69 changed, in one paragraph

`portfolios`, `portfolio_holdings`, the ownership guard, `holdings.py` and
`portfolio_providers.py` moved to `backend/`. The Gateway reaches them over HTTP.
**Before this, the Gateway's ownership check was the only check** — there was no
backend authorization to bypass, because there was no backend authorization. Now
a client's request passes the Gateway's route gate *and* `portfolios.resolve` in
a different process.

Stated so nobody overclaims it: **this does not defend against a compromised
Gateway**, which can assert any owner it likes. It defends against a *buggy* one
— the failure this project has actually had twice (§93, §106).

### The two findings worth carrying forward

Both came from attacking the tests rather than from reading them.

1. **A test that was green for the wrong reason** (§110).
   `test_the_gateway_refuses_in_words_when_the_backend_is_unreachable` passed
   against a mutation that deleted the refusal entirely: it never set the
   credentials, so the client refused as *unconfigured* before reaching the
   transport, and the unconfigured message happened to contain the same two words
   the test asserted.
2. **The fourth wrong scanner** (§110, after §101, §104, §107). The import
   tripwire matched the string `backend.portfolios` and missed `from backend
   import portfolios` — the ordinary spelling, and the one somebody would
   actually write. It reads the import graph with `ast` now. *An import is a node
   in a tree; matching how somebody happened to spell it is guessing.*

**And a discipline worth keeping:** the first mutation round reported 12/12
caught, and two of those catches were worthless — one mutation did not import,
and three ran under `-x` so what failed was whichever test came first in the
file. Attributing each catch to *the test written for it* is what found both
defects above. A tripwire credited with a catch it did not make is worse than no
tripwire, because it is believed.

---

## 4. Constraints that must not be violated

Each cost something to learn. Reversing one silently would undo real work.

### Ownership and isolation

1. **`portfolios.resolve()` is the only way to a portfolio**, and holdings and
   providers take a *resolved portfolio*, never an id (§99, §101). It now lives in
   `backend/portfolios.py`. A second by-id retrieval path is the failure mode to
   watch for — it will not look like a bypass, it will look like a convenience.
2. **No superuser bypass.** `if superuser: skip checks` is forbidden (addendum 44
   §5.3). There is exactly **one** ownership comparison in `backend/portfolios.py`
   and both owner domains go through it.
3. **The ordering inside `resolve()` is load-bearing** (§99). Ownership is
   compared *before* the row is interpreted.
4. **Errors must not reveal that another client exists** (addendum 44 §9.3). One
   identical refusal for absent / foreign / archived — **including the HTTP status
   code**, since that is something a caller can tell apart (§110).

### The Gateway boundary (§109, §110)

5. **The Gateway authenticates; the backend authorizes and holds business logic.**
   Route-level capability gating **stays** at the Gateway.
6. **No Gateway module imports `backend.portfolios`, `backend.holdings`,
   `backend.portfolio_providers` or `backend.portfolio_migration`.** One
   exception, checked and bounded: `gateway/clients.py` takes `normalise` and
   nothing else, so that there is one definition of when two owner ids are the
   same person. Two normalisations that could disagree would make one client into
   two owners, and **no ownership comparison could detect it** — both comparisons
   would be correct, about different people.
7. **The Gateway keeps no cache of anybody's holdings** (§110). Addendum 16 §23's
   "usable when an internal component is down" is why the Gateway has local
   storage at all, and that reasoning **does not extend to money**. A stale
   position shown as current is worse than nothing.
8. **`require_gateway` is not optional and is not `require_admin`.** A surface
   that accepts an asserted subject from anyone lets any authenticated backend
   user read any client's portfolio. The two gates name the same account today
   and answer different questions.
9. **`sessions` and `clients` are the only two tables that belong in
   `gateway.db`.** Five more are still there (§6 item 5) and are known drift.

### Privacy

10. **`PRIVACY_LOCAL_ONLY` and `DataClass.LOCAL_ONLY` are different facts** (§104).
    A LOCAL_ONLY field forces a LOCAL_ONLY task, never the reverse.
11. **A `LOCAL_ONLY` task with no local model is refused, never escalated** (§108).
    **Live today** — no local model exists.
12. **The routing log detects privacy misrouting; it does not prevent it** (§106).
    Never make the log refuse a violation. And never put client identity in it —
    §110 Q1 confirmed it holds none, which is why it could stay in `app/`.

### Pricing and fabrication

13. **`is_priced()` is one line and LIVE-only** (§99, §101). A cash balance is not
    a price.
14. **A cold load is not slow thinking** (§107). `load_ms` stays separate from
    `latency_ms`.
15. **Absent is `null` / `unknown`, never a plausible default.** And **"I could
    not check" is never "there is nothing there"** (§100, §110) — the reason
    `demo_clients.outstanding()` reports *not clean* when the backend is
    unreachable.
16. **The seed and the measurement never merge** (§105).

### Vocabulary

17. **One model of one fact.** Enforced five times now: §70, §100, §104, §106, and
    §110's wire vocabulary in `gateway/portfolio_client.py` — three strings the
    Gateway is allowed to say, held to the backend's own values by a test.
18. **Holding fields are `symbol`/`quantity`/`average_cost`/`as_of`** (§100), and
    `asset_class` uses `reference_data.ASSET_CLASSES` **imported, not mirrored**.

### Tripwires that must be re-aimed, never deleted

19. **`enforced` on a routing rung must match `ENFORCED_STAGES`** (§105).
20. **Agents never reach a local runtime directly** (§107).
21. **A source scan reads code, not prose** — use `conftest.executable_source()`.
    And where the question is about *imports*, read the import graph with `ast`
    rather than matching a spelling (§110).
22. **Nothing outside `backend/portfolios.py` queries the `portfolios` table**, and
    the scan covers **both trees** — it was pointed only at `gateway/` and would
    have gone on passing while saying nothing.
23. **Mutation-test every increment, and attribute each catch to the test written
    for it** (§101, §105, §110). Run without `-x`.

### Migrations

24. **`Database.transaction` refuses `executescript`.** Issue DDL with `execute`
    inside a transaction block.
25. **A migration that restamps or re-keys anything has changed whose data it is**
    (§110). Verify by *ownership*, not by count: a move that landed every row and
    swapped two owners passes a count check perfectly.
26. **Verify while the source is still intact, and rename only afterwards** (§110).
    Two files cannot be written atomically, so the ordering has to supply what a
    transaction cannot.

---

## 5. Task queue

| Task | Status |
|---|---|
| **TQ-46** — Superuser ownership domain | **SPECIFIED — next** (read its §11 Q4 first) |
| TQ-47 / TQ-48 / TQ-49 | queued (addendum 44), behind TQ-46 |
| TQ-50 — Schwab live | **BLOCKED** — owner obtaining API access |
| **TQ-52** — local model candidate survey | **UNBLOCKED** — owner answered what Inkling is |
| TQ-57 / TQ-58 / TQ-60 … TQ-68 | queued behind TQ-52 |
| **TQ-70** — three identity populations | queued (raised by TQ-69) |
| **TQ-71** — drop the four retired holdings tables | queued (raised by TQ-69) |
| TQ-69 | **DONE** §110 |
| TQ-44 / TQ-45 / TQ-51 / TQ-53 / TQ-54 / TQ-55 / TQ-56 / TQ-59 | **DONE** §99–§108 |
| TQ-07 | consumer-gated |
| TQ-20 / TQ-21 | owner actions |
| TQ-28 | open, benign |

Full entries and reasoning in [`TASK_QUEUE.md`](TASK_QUEUE.md).

---

## 6. Open items and known issues

1. **TQ-21 — verify the off-machine copy of `backup.key` actually decrypts.**
   Owner action, and **the one most worth raising**: an untested backup is not a
   recovery asset. Unchanged for two sessions now.
2. **TQ-52 is unblocked.** The owner answered on 2026-08-26: *Inkling is Inkling
   Labs' local model.* That unblocks the **looking**, not the conclusion — the
   survey still owes the artifact, the licence and the runtime from that vendor's
   own published material, substitution stays refused, and anything it cannot find
   is recorded as `unknown` rather than filled in. Hardware is measured (§102):
   8 GB VRAM, 16.5 GB RAM, 365 GB free disk.
3. **TQ-20 — Linux host for a second failure domain.** Owner action, deferred.
4. **TQ-28 — the isolation guard trips after a real backend runs.** A read changes
   the database hash (WAL). Known, benign, unfixed. **Stop the stack before
   running the suite** or it fails spuriously. (A backend run *between* pytest
   sessions is fine — the guard baselines at session start.)
5. **Five of nine `gateway.db` tables are still business logic** (§109).
   `client_agents`, `conversations`, `messages`, `scoreboard_items`,
   `scoreboard_notes`. Deliberately not queued: moving four subsystems because one
   needed it is how a boundary correction becomes a rewrite.
6. **Three identity populations exist** (§110, TQ-69 spec §3): backend users
   (`users.json`), Gateway clients (`clients` in `gateway.db`), environment
   credentials. `gateway/auth.py` says the separation is deliberate. **Now queued
   as TQ-70** rather than left implicit.
7. **Four retired holdings tables accumulate** in a fully-migrated `gateway.db`:
   `client_holdings_legacy`, `portfolio_holdings_pre45`, `portfolios_pre69`,
   `portfolio_holdings_pre69`. **Now queued as TQ-71.** Note
   `demo_clients._clear_archives` reaches all four and must keep doing so while
   they exist.
8. **`acquired_on` accepts prose.** A live agent stored `"last month"` there.
   Belongs with TQ-48's provenance work.
9. **The clock-comparison family.** Four bugs in four days (§90, §91, §94, and the
   zero-width window in `f5c05d0`). The rule is **not** "always use strict".
   Re-read §94 before touching one.
10. **`app/tools/portfolio.py` has no owner argument** — addendum 44 §16.7's
    target, TQ-46's to fix. `/chat` already resolves `username` and hands it
    nowhere near the tool: the owner is available and discarded. Under the
    corrected architecture the fix is now cheap (TQ-46 Q1 reading B).
11. **This machine has no `gateway.db`.** Nothing to migrate here; the TQ-69
    migration was verified against one seeded by the pre-TQ-69 code in a
    `git worktree`. **A machine that does have one must run
    `python -m backend.portfolio_migration` before the Gateway will start** — it
    refuses an unmigrated database on purpose.
12. **`GATEWAY_BACKEND_USER` / `GATEWAY_BACKEND_PASSWORD` are not configured in
    this repo's `.env`.** The Gateway therefore cannot reach the backend at all
    today — `jarvis` reports "not configured" and every holdings tool refuses.
    That is honest behaviour, and it means **the portfolio path needs those two
    variables set (plus that account in `MY_AI_ADMIN_USERS`) before it works
    outside a test.**
13. **No exposure beyond loopback.** Nothing is externally reachable (§50's
    preconditions). Several queued items are preconditions *for* exposure, not
    licence to enable it.
14. **Bash heredocs are unreliable here** for large Python files — they fail with
    "unexpected EOF". Use the Write tool. Confirmed again this session.
15. **Do not append to the docs with PowerShell's `Get-Content`/`Add-Content`.**
    Windows PowerShell 5.1 reads UTF-8 as ANSI by default and turns every `§`
    into `Â§`. It happened once before (§3908 records it) and again this session,
    caught immediately and reverted. Use Python with explicit `encoding="utf-8"`.

---

## 7. Exactly what to do next

**Implement TQ-46**, following
[`docs/specs/TQ-46_superuser_ownership_domain.md`](specs/TQ-46_superuser_ownership_domain.md).

It is specified, and TQ-69 unblocked it.

1. Read the spec end to end. **§11 Q4 is the one to settle first** — which id owns
   the SUPERUSER portfolio. TQ-69 narrowed it to two callers and deliberately did
   not choose; TQ-46 must, and must *store* the choice.
2. Note what that question costs if it is got wrong: with two owner domains and
   two candidate ids, **the wrong pairing is not refused, it returns an empty
   portfolio**. `resolve` is working correctly when that happens. §15.5's
   regression covers a client receiving the operator's portfolio; **nothing yet
   covers the operator silently receiving nobody's**, and this increment owes a
   test with that shape.
3. Q1 is already decided (reading B): keep the capability, remove the
   ownerlessness. The backend reaching an owned portfolio is no longer a
   workaround — it is the specified shape.
4. `git checkout -b <name>`, one increment, full suite green, count stated.
5. Mutation-test it, without `-x`, attributing each catch to the test written for
   it.
6. Record a `SPEC_RECONCILIATION.md` §, update the queue entry, and run it and
   look.

**If you would rather unblock the other lineage instead**, TQ-52 is now open:
go and read Inkling Labs' own material for the artifact, licence and runtime, and
write `docs/local_model_candidates.yaml`. It needs no code and no downloads.

**And if the owner has ten minutes**, TQ-21 is still worth more than either: an
untested backup is not a recovery asset.

---

## 8. Working conventions

- **Branch first.** Never commit to `master`. Open a PR, wait for CI on **both**
  platforms, merge with `--rebase` to preserve the 1:1 commit↔§record mapping.
- **One increment at a time**, full suite green, count stated.
- **Record before moving on:** a `SPEC_RECONCILIATION.md` §, and the queue entry
  updated.
- **Decide open questions before code, and record them.** Done five times now; it
  has never once been wasted effort.
- **Run it and look.** A green suite is not evidence. Every real defect found in
  this project came from starting the thing and reading its output.
- **Attack your own tests.** Mutation-test each increment, run **without `-x`**,
  and check that the test *written for* each mutation is the one that failed. A
  suite that has never failed has not been shown capable of failing; a tripwire
  credited with a catch it did not make is worse than none.
- **Never fabricate.** Absent is `null` / `unknown` / `needs_reconstruction`.
  Simulated data is labelled everywhere it appears.
- **Use a copy of the real database** for any live run; never mutate
  `financial_intelligence.db`. To test a migration realistically, a `git worktree`
  at the pre-migration commit can seed one with the old code — that is how §99,
  §100 and §110 were verified.
- **Restore anything a live run had to touch.** TQ-69's live check registered a
  backend account, so `users.json` was backed up first and restored afterwards,
  and the `user_data/` directories it created were removed.
- **Stop the stack afterwards** and confirm no orphaned agents remain
  (`taskkill /PID <uvicorn> /T /F`, then check for stray `python.exe` and that
  nothing is listening on 8000 or 8100).
