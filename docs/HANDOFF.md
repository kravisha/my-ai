# Handoff — checkpoint 2026-08-29

Written for a session with no memory of the conversation that produced this
state. **Rewritten at each checkpoint, not appended to.**

## Read this first, and read it short

This file is deliberately thin. [`JARVIS.md`](JARVIS.md) is the map — what the
system is, how it is organised, what is built and what is not — and duplicating
it here is how one of the two goes stale (§121).

| Read | For |
|---|---|
| **[`JARVIS.md`](JARVIS.md)** | The whole system. Start here, read to the end. Maintained under addendum 47, kept honest by `tests/test_living_documentation.py`. |
| **This file** | Where the last session stopped and what to do next. Nothing else. |
| [`TASK_QUEUE.md`](TASK_QUEUE.md) | Every task, its status and its reasoning. |
| [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) | Why anything is the way it is. **152 sections**, newest last. §139–§152 are this session. |
| [`PUBLIC_PRIVATE_BOUNDARY.md`](PUBLIC_PRIVATE_BOUNDARY.md) | What may not be committed. Read before assimilating any supplied document. |

## Run these first

```bash
cd C:/Users/ADMIN/my-ai
git log --oneline -5
git status --porcelain
.venv/Scripts/python.exe -m pytest -q
```

Expect **2936 passed, 8 skipped, 5 deselected**. Use `.venv/Scripts/python.exe`,
never bare `python` — the system Python has no dependencies. The 8 skips are
deliberate and named where they are declared.

## What the next session should do first

**Re-run the full verification. It is stale.**

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m simulation verify
```

Last PASS was 2026-08-29 at commit `579f5c4`, and **five increments have landed
since** — twelve source files including `backend/fi_db.py` (three new schema
tables), `agents/coo.py` (a new baseline role and two staffing signals),
`agents/base.py` (the loop *every* agent shares), and `simulation/metrics.py`.
Only `baseline_steady_state` has been run against them.

Expect roughly 25–30 minutes. `INCOMPLETE` rather than `PASS` is the honest
answer if the daily model budget is exhausted — six scenarios need a model, and a
verifier reporting "no failures" over scenarios it skipped would be certifying an
organization it had not examined (§129).

**Two specific things to watch**, both untested by events rather than proven safe:

- `record_grade` now **raises** on an empty rationale, in the hot path. Traced:
  `_analysis_work` catches it and marks the report `failed` rather than killing
  the agent. If a model ever returns a blank rationale, this run is where it
  surfaces.
- The **DBA is now a baseline role**, so every scenario runs eight agents instead
  of seven. Nothing should assert on the count, and nothing did in
  `baseline_steady_state` — but the other ten scenarios have not seen it.

Then: the remaining Definition-of-Done items at §150 §7. The one worth carrying is
that **`metrics.open_at_end` is re-aimed and has never been forced to fire** under
a run that genuinely ends with a pending cross-check. Re-aimed is not proven
(§136's distinction).

## Where the project stands

**The system was re-scoped on 2026-08-28.** Project Providence (addenda 49–52,
§140) makes the product *a personal AI world* — one person, one world, entered
through a device-independent portal, hosted by a Personal Usher, served by ~15
personal agents and informed by an AI newsroom. **The financial intelligence work
everything here was built for becomes the Personal Portfolio Manager, one agent
among them.** Market data and the broker connection are no longer the head of the
queue.

**Governance is complete and exercised.** Parliament carries resolutions, the
governed store holds instruments under a precedence rule, agents read what binds
them, refusals are counted and attributed, the Speaker reports it, releases apply
and reverse, and the organization may amend its own Constitution at two-thirds.

**A Software Department now exists** (addendum 53) and is the newest thing: five
gates on a ten-step issue workflow, a DBA that opens an issue when a scheduled
check fails, and a QA reader that answers *has this tripwire ever been observed
failing?* from the run history.

**The product side has not moved since TQ-80.** No prices, no broker, no client.
Under Providence that is no longer the critical path; it is still true.

## What this session did

Fourteen commits, `bfb3258` through `21efdde`, recorded at §139–§152.

| Increment | What it settled |
|---|---|
| **TQ-96** §139 | *What is a release when the governed layer already changes behaviour without one?* A named set of governed changes that stand or fall together, whose way back is authorized before the way forward. The **code** half is declined, not deferred. |
| **Providence** §140 | Addenda 49–52 assimilated. Six conflicts; two against constraints bought with a defect. |
| **TQ-97** §140 §4 | Persistent agent identity. The durable identity here **was the display name**, which addendum 51 §3 forbids in terms. |
| **§141** | *Owner correction.* The Constitution is **one document**, addendum 49 is its v2.0, and **it applies to the system with the owner inside it**. §120's *outside the system entirely* was a misunderstanding. |
| **§142** | *Owner decision.* The organization may amend the Constitution at **two-thirds**. The bar is a code constant, because a threshold inside the document it guards can be lowered once and walked through. |
| **TQ-98** §143 | The client profile — the first backend store that persists client data. A watchlist entry is **a symbol and nothing else**. |
| **§144** | *Owner direction.* What belongs in the Constitution: **does this rule need to stand the test of time?** |
| **TQ-102** §145 | The right to appeal. **There is no court** — a peer of the author, chosen by neither party. |
| **TQ-103** §146 | An agent reads its own record. **Partly retracted by §147.** |
| **TQ-104** §147 | **§146 was wrong.** Grading was already independent, and `compliance.self_evaluated` compared two fields that are one identity by construction — it could never return false. |
| **TQ-99** §148 | The personnel record joined to `agent_id`. A renamed agent keeps one continuous history. |
| **TQ-92** §149 | Cooperation **read, not scored**. Found two more checks that could not fail. |
| **TQ-105** §150 | Addendum 53 assimilated. The **Database Vocabulary Contract**. |
| **TQ-106/107** §151, §152 | The Software Department, its five gates, and the loop that staffs itself and **stops at the implementation perspective**. |

## Known blockers and open questions

- **With the owner:** **TQ-100** — *what refuses a persona that crosses the line,
  a function or a paragraph?* Unanswered, and addendum 53 §7.9 **freezes TQ-101**
  (the Personal Usher) until it is. That is now a specification, not a
  recommendation.
- **`JARVIS_GAP_ANALYSIS.md` is stale.** It scores the build against the
  Constitution, and the Constitution became v2.0 on 2026-08-28 (§141 §1).
- **The genesis Articles and the genesis Constitution are unwritten.** Both
  machineries run and hold no text; the first text is the owner's, because a vote
  needs an electorate only the Articles can supply (§120, §142).
- **No CEO.** Addendum 53 §22 starts the department with one; the Controller owns
  lifecycle and the COO spawns. Flagged as unreconciled, not silently mapped
  (§150 §2).
- **The Gateway already holds persona material.** `gateway/client_agent.py` stores
  `voice` and `visual`, which §109 puts on the backend's side — the accident 53
  §7.9 warns against, which had already happened (§150 §4). Not corrected: §7.9
  says preserve working code until TQ-100 is answered.
- **Nothing corrects or verifies a software issue.** Steps 5–7 need an agent that
  can read and write code; TQ-83 established the engineer writes none. The gates
  hold meanwhile (§152 §5).
- **45 scenario properties have never been observed failing.**
  `simulation/property_history.worklist()` lists them. A worklist, not a defect
  list — but it is where the next §149-shaped defect will be found.
- **`MODEL_BUDGET_DAILY_TOKENS=1500000`** is set in `.env` (gitignored) on the
  owner's authority. The guard still exists; do not remove it.

## Constraints that must not be violated

Each was bought with a defect. `SPEC_RECONCILIATION.md` has the story.

1. **Client portfolios are never stored** (§111). No table exists; a tripwire
   fails the suite if a storage module returns. **Re-aimed at §143** — the
   originals asked about a `portfolios` table and would have passed forever while
   `client_watchlist` grew a `quantity` column. A client *profile* now persists
   (TQ-98) and the boundary is structural: a closed 16-field vocabulary, and **a
   watchlist entry is a symbol and nothing else**.
2. **The Constitution is not in any store**, and the reason is the store, not its
   author (§120, corrected by §141 and §142). It **applies to the whole system and
   the owner is part of the system**; the organization may amend it at two-thirds;
   and the **amendment bar is a constant in code**, never a clause in the document
   it guards. Addendum 49 is the Constitution and is **held privately** —
   `tests/test_public_private_boundary.py` enforces that rather than asking.
3. **The Articles' amendment threshold is a constant in code** (§123). A rule a
   vote can reach is not a rule.
4. **Absence is `unknown`, never a plausible default** (§100, §104, §118, §132).
5. **Tripwires are re-aimed, never deleted** (§105, §110, §116, §128, §134, §147,
   §149).
6. **One identical refusal for every reason** a caller is not entitled to
   distinguish (addendum 44 §9.3, §123).
7. **`docs/JARVIS.md` is under document custody.** Editing it means updating
   `docs/document_custody.yaml`'s digest in the same commit, or the suite fails.
8. **Simulation seeds go through the production API, never SQL** (§128).
9. **No agent may know it is in a simulation** (§115). An agent that reads
   `simulation/` has one code path that changes between training and production.
   This fired on TQ-106's first design and was right (§151 §5).
10. **When a query filters on a domain value, use the constant** (§149 §4,
    addendum 53 §7.6). A bad constant fails at import; a bad literal fails by
    returning nothing, which reads as good news.

## Security and isolation

Unchanged except where noted. Full table in `JARVIS.md` §9.

- **The repository is public** (`github.com/kravisha/my-ai`), and on 2026-08-28
  that cost something: addendum 49 — the Constitution — was assimilated into
  `docs/addenda/` by the ordinary intake rule, reached one local commit, and was
  removed from history before any push (§141 §3). **Nothing leaked.** The boundary
  had been prose since 2026-08-16 with nothing enforcing it; it is now
  `tests/test_public_private_boundary.py`.
- **Private set:** the Constitution (addendum 49) and addenda 5, 11, 15, 22. A
  reference you cannot follow means private, not missing.
- **Isolation is the database, not a flag** (`simulation/harness.py`).
- **Ownership is evidence, never a parameter.** Every client-scoped call takes an
  `OwnerContext` resolved from the session (addendum 44 §9.2).

## Pending integrations

None active. All are owner actions or blocked:

- **TQ-75** real market data — unheld, needs a provider choice and a cost.
- **TQ-49/TQ-50** the Schwab boundary — blocked on owner API access.
- **TQ-73** the credential envelope — buildable in part; blocked on TQ-75 for
  anything valued.
- **TQ-57…TQ-68** local models and competitive routing — blocked on TQ-52's pool
  being installed. None is installed; routing is pinned to `none_single_model`
  and a tripwire fails the day a second model is registered.
- **TQ-20 / TQ-21 / TQ-85** owner actions (Linux host, key verification, signed
  commits).

## Working rhythm

Assimilate verbatim → reconcile against the *addenda* and not the build (§111) →
queue → one increment → suite green → **run it and look** → record a
`SPEC_RECONCILIATION.md` § → update the queue and `JARVIS.md` → commit →
**push, merge to `master`, push** (owner instruction 2026-08-29; run
`tests/test_public_private_boundary.py` first, the repository is public).

**A green suite is not evidence.** Every real defect in this project came from
starting the thing and looking at it — and three of the four found this session
came from reading a query against the data it actually returns.

## Five ways this project has been wrong, which keep recurring

- **A test over data does not test the rule that produced the data** (§117, §118,
  §123, §129).
- **A test that constructs its own input never tests the code that constructs the
  input** (§132).
- **A function tested in isolation is not a function that runs** (§134).
- **A seam asserted by reading source is not a seam that runs** (§136).
- **A check aimed where the answer is a tautology** (§147, §149). *New this
  session, and it is not decay* — these were wrong the day they were written and
  passed every test, because the tests were built from the same misreading. Three
  instances in two days: a comment naming a value nothing writes, a filter on a
  status that does not exist, and a join on the one column that cannot differ.
