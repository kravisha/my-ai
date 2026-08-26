# Handoff — checkpoint 2026-08-26 (session close)

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
.venv/Scripts/python.exe -m pytest -q    # expect 2462 passed, 1 skipped, 5 deselected
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
4. [`docs/specs/TQ-69_portfolio_subsystem_behind_the_backend.md`](specs/TQ-69_portfolio_subsystem_behind_the_backend.md)
   — the next task, fully specified.

---

## 2. Where the project stands

`master` clean and pushed. Suite **2462 passing, 1 skipped**. CI green on Windows
and Linux. Nothing running; no orphaned processes.

**Three areas.**

- **Backend** (`backend/main.py`, port 8000) — the organization. Owns
  `financial_intelligence.db`. Agents, the COO (Kumbhakarnan), the simulated
  market, the studio at `/console`. Has its own per-user model (`users.json`,
  `/auth/login`, `get_current_user`).
- **Gateway** (`gateway/main.py`, port 8100) — the door. Owns `gateway.db`. The
  only component intended to face outward.
- **The routing subsystem** (`app/`) — added this session, imported by both
  processes: `task_signature`, `model_performance`, `routing_decisions`,
  `local_ai`, `capability`. **Infrastructure only; no local model behind it.**

**Owner direction, 2026-08-26 (§109):** *"Gateway is for establishing identity —
Gateway only does authentication. Back end does authorization and all business
logic."* The Gateway's route-level capability gating **stays** and is not the
drift; what drifted is data ownership. TQ-69 corrects the portfolio half.

**The Gateway's security model** (§92–§101): three roles; every route and every
model tool declares a capability with a tripwire; client data keyed to a
`subject` resolved from the session; per-client credentials; portfolios as owned
entities behind one guard.

---

## 3. Completed this session

Eleven merged records, `SPEC_RECONCILIATION.md` §99–§109. Suite went 2187 → 2462.

| § | What | PR |
|---|---|---|
| §99 | **TQ-44** — portfolios as owned entities, with the guard in the same increment | #46 |
| — | TQ-45 specified; two vocabulary collisions named before anybody hit them | #47 |
| §100 | **TQ-45a** — the canonical holding shape (`symbol`/`quantity`/`average_cost`/`as_of`) | #48 |
| §101 | **TQ-45b** — `PortfolioProvider` and its conformance suite | #49 |
| §102 | Addendum 45 assimilated verbatim; TQ-51…TQ-68 queued | #50 |
| §103 | **TQ-51** — the single-model routing pin becomes a ladder | #51 |
| §104 | **TQ-53** — the task signature and its vocabularies | #52 |
| §105 | **TQ-54** — the Model Performance Registry and eight leaderboards | #53 |
| §106 | **TQ-55** — the routing decision record | #54 |
| §107 | **TQ-56** — `LocalAIService` and its conformance suite | #55 |
| §108 | **TQ-59** — the deterministic check and escalation decision | #56 |
| §109 | Owner direction: the Gateway boundary corrected; TQ-46 specified | #57 |
| — | TQ-69 specified | #58 |

### The four findings worth carrying forward

Each was found by running or measuring rather than by reasoning, and each is
recorded in full at the § named.

1. **A clean report that was not true** (§100). After the field rename,
   `demo_clients.clear()` emptied the live table and `outstanding()` reported *"No
   simulated client data is present"* while ten demo holdings sat in the retired
   one. The suite was green throughout. Cause: two archives keyed differently —
   one by client, one by portfolio.
2. **A conformance suite that passed 47 tests and still had a hole** (§101). Five
   deliberate mutations; the one it missed was the by-id bypass it existed to
   prevent, because the scan walked a *fixed list* of method names and a newly
   added method slipped past. Mutation-testing every suite is now the habit.
3. **A privacy violation nothing would have noticed** (§106). Running addendum 45
   §25's own portfolio example routed a `LOCAL_ONLY` step to an external model;
   the log recorded it faithfully and no reader would have looked.
   `privacy_violation` is now derived on read. §108 then closed it from the other
   end, by refusing the decision rather than detecting it after the fact.
4. **A source scanner too crude, three times** (§101, §104, §107). Each time the
   module was right and the test wrong. `conftest.executable_source()` is now the
   single implementation of "read only the code".

---

## 4. Constraints that must not be violated

Each cost something to learn. Reversing one silently would undo real work.

### Ownership and isolation

1. **`portfolios.resolve()` is the only way to a portfolio**, and holdings and
   providers take a *resolved portfolio*, never an id (§99, §101). A second by-id
   retrieval path is the failure mode to watch for — it will not look like a
   bypass, it will look like a convenience. One was nearly written during TQ-44
   itself, and addendum 45 §7's own `get_holdings(account_ref)` is another,
   declined in TQ-45's spec §3.2.
2. **No superuser bypass.** `if superuser: skip checks` is forbidden (addendum 44
   §5.3). There is exactly **one** ownership comparison in `gateway/portfolios.py`
   and both owner domains go through it.
3. **The ordering inside `resolve()` is load-bearing** (§99). Ownership is
   compared *before* the row is interpreted, so a corrupt row cannot become an
   existence oracle for anybody but its owner.
4. **Errors must not reveal that another client exists** (addendum 44 §9.3). One
   identical refusal for absent / foreign / archived.

### Privacy

5. **`PRIVACY_LOCAL_ONLY` and `DataClass.LOCAL_ONLY` are different facts** (§104).
   One classifies a *task*, the other a *field*. The derivation runs one way: a
   LOCAL_ONLY field forces a LOCAL_ONLY task, never the reverse.
6. **A `LOCAL_ONLY` task with no local model is refused, never escalated** (§108).
   Falling back externally would be helpful and would break the one rule addendum
   45 §36 states without qualification. This is **live today** — no local model
   exists.
7. **The routing log detects privacy misrouting; it does not prevent it** (§106).
   Never make the log refuse a violation — a log that would not record one hides
   what it exists to reveal.

### The Gateway boundary

8. **The Gateway authenticates; the backend authorizes and holds business logic**
   (§109, owner direction). `sessions` and `clients` are the only two tables that
   belong in `gateway.db`. Route-level capability gating **stays** at the Gateway
   and is not the drift.

### Pricing and fabrication

9. **`is_priced()` is one line and LIVE-only** (§99, §101). A `SIMULATED`
   portfolio is not priced. A cash balance is not a price — it is a quantity
   somebody holds — which is why `get_balances` may exist without widening it.
10. **A cold load is not slow thinking** (§107). `InferenceResult` keeps `load_ms`
    separate from `latency_ms`; a ranking that folded them would learn about disk
    speed and record it as reasoning quality.
11. **Absent is `null` / `unknown`, never a plausible default.** `unknown` is a
    *member* of a vocabulary rather than an absence (§100, §104).
12. **The seed and the measurement never merge** (§105). `seed_score` is written
    once; the composite is derived on read, so addendum 45 §12's "empirical should
    dominate the seed" is arithmetic rather than a decision somebody makes.

### Vocabulary

13. **One model of one fact.** Enforced four times: §70 (asset classes), §100
    (EQUITY/OPTION withdrawn for the house codes), §104 (`error_cost` tied to the
    registry's `criticality`), §106 (`risk_level` read off the signature rather
    than stored a third time).
14. **Holding fields are `symbol`/`quantity`/`average_cost`/`as_of`** (§100), and
    `asset_class` uses `reference_data.ASSET_CLASSES` **imported, not mirrored**.

### Tripwires that must be re-aimed, never deleted

15. **`enforced` on a routing rung must match `ENFORCED_STAGES`** in
    `tests/test_model_registry.py` (§105). §103's ladder had a hole its author
    walked into: a flag in a YAML file recorded an intention and read as a fact.
16. **Agents never reach a local runtime directly** (§107).
    `app/local_ai.service()` is the only entry point; a scan checks every module
    for `KNOWN_LOCAL_RUNTIMES` imports.
17. **A source scan reads code, not prose.** Use `conftest.executable_source()`.
18. **Nothing outside `gateway/portfolios.py` queries the `portfolios` table.**

---

## 5. Task queue

| Task | Status |
|---|---|
| **TQ-69** — move the portfolio subsystem behind the backend | **SPECIFIED — next** |
| TQ-46 — Superuser ownership domain | SPECIFIED, **blocked on TQ-69** |
| TQ-47 / TQ-48 / TQ-49 | queued (addendum 44) |
| TQ-50 — Schwab live | **BLOCKED** — owner obtaining API access |
| **TQ-52** — local model candidate survey | **BLOCKED** — owner must say what "Inkling" is |
| TQ-57 / TQ-58 / TQ-60 … TQ-68 | queued, all behind TQ-52 |
| TQ-51 / TQ-53 / TQ-54 / TQ-55 / TQ-56 / TQ-59 | **DONE** §103–§108 |
| TQ-44 / TQ-45 | **DONE** §99, §100, §101 |
| TQ-07 | consumer-gated |
| TQ-20 / TQ-21 | owner actions |
| TQ-28 | open, benign |

Full entries and reasoning in [`TASK_QUEUE.md`](TASK_QUEUE.md).

---

## 6. Open items and known issues

1. **TQ-21 — verify the off-machine copy of `backup.key` actually decrypts.**
   Owner action, and **the one most worth raising**: an untested backup is not a
   recovery asset. Unchanged for the whole session.
2. **TQ-52 is blocked on one fact: what "Inkling" is.** Addendum 45 §47 requires
   it as an initial local candidate and it is not identifiable as an open-weight
   local model. It has deliberately **not** been substituted with something
   similarly named. Everything else in that lineage queues behind it. Hardware is
   already measured (§102): 8 GB VRAM, 16.5 GB RAM, 365 GB free disk.
3. **TQ-20 — Linux host for a second failure domain.** Owner action, deferred.
4. **TQ-28 — the isolation guard trips after a real backend runs.** A read
   changes the database hash (WAL). Known, benign, unfixed. **Stop the stack
   before running the suite** or it fails spuriously.
5. **Five of nine `gateway.db` tables are business logic** (§109).
   `client_agents`, `conversations`, `messages`, `scoreboard_items`,
   `scoreboard_notes` belong backend-side under the corrected boundary, along
   with `portfolios` and `portfolio_holdings` which TQ-69 moves. The other four
   are **deliberately not queued** — moving four subsystems because one needed it
   is how a boundary correction becomes a rewrite.
6. **Three separate identity populations exist** (TQ-69 spec §3): backend users
   (`users.json`), Gateway clients (`clients` in `gateway.db`), and environment
   credentials. `gateway/auth.py` says the separation is deliberate. Reconciling
   them is TQ-69's §10 Q2, recorded and not queued.
7. **Three legacy tables accumulate.** `client_holdings_legacy` (§99),
   `portfolio_holdings_pre45` (§100), and `*_pre69` after TQ-69. Dropping them
   deliberately is worth its own entry.
8. **`acquired_on` accepts prose.** A live agent stored `"last month"` there.
   Predates TQ-45a; belongs with TQ-48's provenance work.
9. **The clock-comparison family.** Four bugs in four days (§90, §91, §94, and
   the zero-width window in `f5c05d0`). The rule is **not** "always use strict".
   Re-read §94 before touching one.
10. **`app/tools/portfolio.py` has no owner argument** — addendum 44 §16.7's
    target, TQ-46's to fix. Note that `/chat` already resolves `username` and
    hands it nowhere near the tool: the owner is available and discarded.
11. **`gateway.db` may hold demo data** if the Gateway has been run locally.
    `python -m gateway.demo_clients status` reports; `clear` removes. Must be
    clean before any live exposure.
12. **No exposure beyond loopback.** Nothing is externally reachable (§50's
    preconditions). Several queued items are preconditions *for* exposure, not
    licence to enable it.
13. **Bash heredocs are unreliable here** for large Python files — they fail with
    "unexpected EOF". Use the Write tool. Confirmed again this session.
14. **`Database.transaction` refuses `executescript`.** sqlite3 commits before
    running a script, which would end the transaction and make a rollback
    impossible. Issue DDL with `execute` inside a transaction block.

---

## 7. Exactly what to do next

**Implement TQ-69**, following
[`docs/specs/TQ-69_portfolio_subsystem_behind_the_backend.md`](specs/TQ-69_portfolio_subsystem_behind_the_backend.md).

It is specified, unblocked, and **blocks TQ-46**. Owner direction (§109) put the
portfolio subsystem on the wrong side of the authentication/authorization line;
this moves it.

1. Read the spec end to end. **§4.2** (the backend stores `owner_id` opaquely) and
   **§4.3** (what this buys and what it does not) matter most.
2. Decide §10's three open questions and record them, the way TQ-44's three,
   TQ-45's five and TQ-46's Q1 were decided before any code.
3. `git checkout -b <name>`.
4. **The headline test is addendum 44 §15.5's permanent regression, run from the
   Gateway's side over HTTP.** If that does not pass over the wire, the move
   failed whatever else is green.
5. Migrate against a **copy** of a seeded database; verify counts, ids and owners
   before renaming anything.
6. Full suite, then the spec's §13 live check — and note **step 3 of it**: stop
   the backend with the Gateway still running and confirm the refusal names it
   and serves nothing stale. That is the step most likely to be skipped.

**Specified** — `docs/specs/TQ-69_portfolio_subsystem_behind_the_backend.md`.
Writing it found the thing that shapes the work: **three separate identity
populations** exist (backend users in `users.json`, Gateway clients in
`gateway.db`, environment credentials), and `gateway/auth.py` says the separation
is deliberate. The decision that keeps the increment small: **the backend stores
`owner_id` opaquely** — it never learns who Gateway clients are, the Gateway
authenticates and asserts a subject, the backend authorizes it.

Stated so nobody overclaims it: this **does not** defend against a compromised
Gateway, which can assert any owner. It defends against a *buggy* one — the
failure that has actually happened twice here (§93, §106), with no second check
to catch either.

**If you would rather unblock the other lineage instead**, the single thing
needed is the owner's answer to what "Inkling" is (§6 item 2).

**And if the owner has ten minutes**, TQ-21 is worth more than either: an
untested backup is not a recovery asset.

---

## 8. Working conventions

- **Branch first.** Never commit to `master`. Open a PR, wait for CI on **both**
  platforms, merge with `--rebase` to preserve the 1:1 commit↔§record mapping.
- **One increment at a time**, full suite green, count stated.
- **Record before moving on:** a `SPEC_RECONCILIATION.md` §, and the queue entry
  updated.
- **Run it and look.** A green suite is not evidence. Every real defect found in
  this project came from starting the thing and reading its output — three of
  this session's four findings did (§3).
- **Attack your own tests.** A suite that has never failed has not been shown
  capable of failing. Mutation-test each increment: break the module several ways
  and confirm each is caught. This found a real hole twice (§101, §105).
- **Decide open questions before code, and record them.** Done four times this
  session; it has never once been wasted effort.
- **Never fabricate.** Absent is `null` / `unknown` / `needs_reconstruction`.
  Simulated data is labelled everywhere it appears.
- **Use a copy of the real database** for any live run; never mutate
  `financial_intelligence.db`. To test a migration realistically, a `git worktree`
  at the pre-migration commit can seed one with the old code — that is how §99 and
  §100 were verified.
- **Stop the stack afterwards** and confirm no orphaned agents remain
  (`taskkill /PID <uvicorn> /T /F`, then check for stray `python.exe`).
