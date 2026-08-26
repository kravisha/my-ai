# Handoff — checkpoint 2026-08-26 (TQ-59 complete; the Gateway boundary corrected)

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

Then read, in order:

1. **This file** — to the end.
2. [`docs/README.md`](README.md) → "Picking up mid-project" — the map.
3. [`docs/TASK_QUEUE.md`](TASK_QUEUE.md) — the head block says what is next.
4. [`docs/TASK_QUEUE.md`](TASK_QUEUE.md) TQ-46 — the next task. **It has no
   specification yet**; see §7.

---

## 2. Where the project stands

`master` plus this checkpoint, clean and pushed. Suite **2462 passing, 1
skipped**. The skip is deliberate: `none_single_model`'s tripwire stands down
now that a later rung of the routing ladder governs. Nothing running; no
orphaned processes.

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
| §101 | **TQ-45b** the provider abstraction + its conformance suite | #49 |
| §102 | Addendum 45 assimilated; TQ-51…TQ-68 queued | #50 |
| §103 | **TQ-51** the single-model pin becomes a ladder | #51 |
| §104 | **TQ-53** the vocabulary routing decides on | #52 |
| §105 | **TQ-54** the competition, as data | #53 |
| §106 | **TQ-55** every routing decision, and the violation it found | #54 |
| §107 | **TQ-56** the interface local intelligence will arrive behind | #55 |
| §108 | **TQ-59** can this be done without a model, and if not is local enough | this branch |

**TQ-44 final status: COMPLETE.** `gateway/portfolios.py` is the entity and the
guard; holdings are re-keyed from `client_id` to `portfolio_id`; two clients
logged into a running Gateway and each saw only their own.

**TQ-45 final status: COMPLETE.** 45a (§100) made holdings `symbol` /
`quantity` / `average_cost` / `as_of` with the house `asset_class` vocabulary.
45b (§101) put `PortfolioProvider` between the analyzer and wherever holdings
come from, with a conformance suite two providers satisfy, and rebuilt the demo
clients on §6.1's diversity. All five of the spec's open questions are decided
and recorded in its §11. Nothing outstanding.

**Addendum 45 is assimilated** (§102) — local intelligence and competitive model
routing, owner-supplied, queued as TQ-51 … TQ-68. Nothing built.

**TQ-51, TQ-53, TQ-54, TQ-55, TQ-56 and TQ-59 are done** (§103–§108). Still one model and no
model calls anywhere in the lineage. `routing` stands on **`seeded_leaderboard`**,
the eight leaderboards exist seeded and provisional, and every routing decision
is logged from the first one — including detection of §36 privacy misrouting,
which TQ-55 found by running §25's own example. `app/local_ai.py` is the
interface local models will arrive behind, with an honest null implementation
and a conformance suite already written.

`app/capability.py` answers §3's first decision, and its live answer today is
worth knowing: **a `LOCAL_ONLY` task that needs a model cannot be done at all**,
because no local model is installed and §36 forbids the external fallback.

**Every remaining entry in this lineage needs either hardware or the Inkling
answer**, so TQ-52 is now the head of it with nothing else buildable ahead.

**The other lineage is still open**: TQ-46 … TQ-50 (the rest of addendum 44).
Neither blocks the other. See §7.

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
11. **The routing ladder is not a comment** (§103). `docs/model_registry.yaml`
    carries `routing_stages`; each rung has its own tripwire and **a rung whose
    assertion is not built refuses to be stood on**. Advancing `routing` is a
    deliberate act with a queue entry behind it — TQ-54 earns `seeded_leaderboard`,
    TQ-63 earns `competitive`. Re-aim it, never delete it: §64 planted it, and it
    fired exactly when it was supposed to.
12. **`PRIVACY_LOCAL_ONLY` and `DataClass.LOCAL_ONLY` are different facts**
    (§104). One classifies a *task* — this work may not go to an external
    model; the other classifies a *field* — this value never leaves the
    process. The derivation runs **one way**: a LOCAL_ONLY field forces a
    LOCAL_ONLY task, never the reverse. `task_signature.privacy_floor_for()`
    is that derivation; do not collapse the two vocabularies into one.
13. **`enforced` on a routing rung must match `ENFORCED_STAGES`** in
    `tests/test_model_registry.py` (§105). §103's ladder was built so that
    advancing the marker to a rung with no assertion fails loudly; it did not,
    because `enforced` was a flag in a YAML file recording an intention. The
    author of TQ-54 walked into it. A flag is not a tripwire — the tests have to
    agree with it.
14. **The seed and the measurement never merge** (§105). `seed_score` is written
    once and never updated; the composite is derived on read. §12's "empirical
    should dominate the seed" is arithmetic, not a decision somebody makes, and
    blending them would make it impossible.
15. **The routing log detects privacy misrouting; it does not prevent it**
    (§106). `routing_decisions` flags a `LOCAL_ONLY` task that went external and
    counts it in `summary()`. Enforcement is TQ-60's. **Never make the log
    refuse a violation** — once prevention exists, a violation can only arrive
    through a bug or a bypass, and a log that would not record those hides what
    it exists to reveal.
16. **Agents never reach a local runtime directly** (§107, addendum 45 §4,
    §47). `app/local_ai.service()` is the only supported entry point, and
    `test_no_module_reaches_a_local_runtime_directly` parses every module for an
    import of anything in `KNOWN_LOCAL_RUNTIMES`. Adding a runtime to the pool
    means adding its name to that list in the same increment.
17. **A cold load is not slow thinking** (§107, from §102's 8 GB finding).
    `InferenceResult` keeps `load_ms` separate from `latency_ms` and refuses a
    cold load that does not report it. Never fold them together — a ranking that
    did would learn about disk speed and record it as reasoning quality.
18. **A source scan reads code, not prose.** Use
    `conftest.executable_source()`; it strips every string literal. Three
    hand-rolled scanners were too crude before it existed (§101, §104, §107),
    each time with the module right and the test wrong.
19. **A `LOCAL_ONLY` task with no local model is refused, never escalated**
    (§108). Falling back to an external provider would be helpful and would
    break the one rule §36 states without qualification. `PATH_REFUSED` is
    deliberately not an execution path — there is nothing to log when nothing
    ran. This is live today, because no local model is installed.
20. **The Gateway authenticates; the backend authorizes and holds business
    logic** (§109, owner direction 2026-08-26). `sessions` and `clients` are the
    only two tables that belong in `gateway.db`. The Gateway reaches everything
    else over HTTP, the way `gateway/jarvis.py` already reaches `/admin`.
    Route-level capability gating **stays** at the Gateway and is not the drift
    (addendum 17 §14, §92) — a door that refuses is not a door doing business
    logic. TQ-69 corrects the portfolio half; the rest is recorded drift.
21. **`is_priced()` is one line and LIVE-only.** A simulated portfolio is not
    priced (spec §11 Q2). A cash balance is not a price — it is a quantity
    somebody holds, not a valuation — which is why `get_balances` may exist
    without widening the rule.

---

## 5. Task queue

| Task | Status |
|---|---|
| **TQ-52** — candidate survey: what can run on this machine | **next** — blocked on the Inkling answer |
| TQ-51 / TQ-53 / TQ-54 / TQ-55 / TQ-56 / TQ-59 — ladder, vocabulary, leaderboards, decision log, service, escalation | **DONE** §103–§108 |
| TQ-57 / TQ-58 / TQ-60 … TQ-68 — the rest of the lineage | queued (§102), all behind hardware |
| TQ-46 … TQ-50 — the rest of addendum 44 | queued, needs a spec |
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

TQ-52 needs one owner answer — see §7. Nothing else in the lineage is buildable ahead of it.

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
7. **Five of nine `gateway.db` tables are business logic** (§109).
   `client_agents`, `conversations`, `messages`, `scoreboard_items` and
   `scoreboard_notes` belong backend-side under the corrected boundary, along
   with `portfolios` and `portfolio_holdings` which TQ-69 moves. The other four
   are **deliberately not queued** — moving four subsystems because one needed it
   is how a boundary correction becomes a rewrite. They get entries when
   something needs them.
8. **`acquired_on` accepts prose.** A live agent stored `"last month"` there,
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

**TQ-69 — move the portfolio subsystem behind the backend.** Owner direction,
2026-08-26 (§109): *"Gateway is for establishing identity — Gateway only does
authentication. Back end does authorization and all business logic."*

`portfolios` and `portfolio_holdings`, with the ownership guard that authorizes
every read of them, are business logic sitting in the process specified to do
none. **TQ-46 is blocked on this** — building a `SUPERUSER` domain into
`gateway.db` and relocating it a week later is the mistake TQ-44 refused to make
with the entity and its guard.

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

**None of §96, §99, §100, §101 or §106 is wasted by this.** The guard, the
canonical holding shape, the provider contract and the decision log are all
correct and all portable. What moves is which process owns the table and which
authorizes the call — and the guard gets *stronger*, because a Gateway request
then passes a backend check it is currently the only check for.

**Then TQ-46**, whose spec is written and whose Q1 is decided (reading B: keep
the capability, remove the ownerlessness). Under the corrected architecture that
reading is cheap rather than expensive, and no consent machinery is deleted.

**The addendum 45 lineage is at its hardware boundary** — six increments built
(§103–§108), and everything remaining waits on **TQ-52: what "Inkling" is.**

**And still open, unchanged all session: TQ-21** — verify the off-machine copy of
`backup.key` actually decrypts. The only item where the downside is losing work
rather than delaying it.

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
