# Handoff — checkpoint 2026-08-30

Written for a session with no memory of the conversation that produced this
state. **Rewritten at each checkpoint, not appended to.**

**This checkpoint is a machine change.** Development moves to another machine and
resumes after a few days, so §2 below — what git does not carry — matters more
than usual and is not the ordinary boilerplate.

## Read this first, and read it short

| Read | For |
|---|---|
| **[`JARVIS.md`](JARVIS.md)** | The whole system. Start here, read to the end. Kept honest by `tests/test_living_documentation.py`. |
| **This file** | Where the last session stopped and what to do next. Nothing else. |
| [`TASK_QUEUE.md`](TASK_QUEUE.md) | Every task, its status and its reasoning. TQ-115 is the newest. |
| [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) | Why anything is the way it is. **162 sections**, newest last. §153–§162 are this session. |
| [`ARCHITECTURE_READINESS_REVIEW.md`](ARCHITECTURE_READINESS_REVIEW.md) | The GO/NO-GO review of the four 2026-08-29 specifications. **Read its banner** — four of its findings were later corrected by the increments they caused. |
| [`PUBLIC_PRIVATE_BOUNDARY.md`](PUBLIC_PRIVATE_BOUNDARY.md) | What may not be committed. Read before assimilating any supplied document. |

## 1. Run these first

```bash
cd <repo>
git log --oneline -3
.venv/Scripts/python.exe -m pytest -q
```

Expect **3020 passed, 8 skipped, 8 deselected**. HEAD is `6bf14a8`, and `master`
and `tq-78-consolidation` are identical and both pushed.

The 8 deselections are the `simulation` and `real_llm` markers — real processes
and real API calls, excluded from the default run. Run the contention harness
deliberately with `-m simulation` if you touch the database layer.

## 2. What git does not carry — read before starting on the new machine

Everything below is gitignored and **must be recreated or brought across**:

- **`.env`** (35 lines) — carries `MODEL_BUDGET_DAILY_TOKENS=1500000` and the
  Anthropic key. Without it every model-dependent scenario skips and `verify`
  reports `INCOMPLETE` rather than `PASS`, which is the honest answer but not the
  one you want to be surprised by.
- **`.venv/`** — recreate and install; the system Python has no dependencies.
  Always `.venv/Scripts/python.exe`, never bare `python`.
- **`financial_intelligence.db` and `gateway.db`** — the live databases. A fresh
  one is fine: `init_schema` builds everything and backfills store versions. What
  you lose is the COO's persisted identity, so **Kumbhakarnan starts again** on a
  new database. That is expected and not a defect; if continuity matters, copy
  the file across.
- **`simulation/runs/`** — every past run's database, log and manifest. The
  evidence behind several measured constants lives here. Losing it costs the
  ability to re-derive them, not the constants themselves — the numbers are
  written into the code comments with their sample sizes.
- **`demo_summary.json`** — output of the last Demonstration Engine run.

**And the supplied specifications are not in the repository.** Ten `.txt` files
sit in `~/Downloads` on the old machine and none has been assimilated, numbered
or classified — that is open decision 3 below. **Bring them across**, or the next
session will be reconciling against documents it cannot read:

```
01_JARVIS_Knowledge_Store_Specification.txt
02_JARVIS_Software_Engineering_Healing_and_Recovery_Addendum.txt
03_JARVIS_Multiprocessing_Process_Isolation_and_Scaling_Specification.txt
04_JARVIS_Misc_Architecture_Alpha_Readiness_and_Persistence_Specification.txt
Claude_Development_Philosophy_and_Blocker_Policy.txt
Dedicated_Anchor_Architecture_Change_Spec.txt
JARVIS_Demonstration_Engine_Specification_v1.txt
JARVIS_self_evolution_resolved_decisions_directive.txt
MyAI_Business_Continuity_Framework_v1.0.txt
MyAI_Department_of_Education_v1.0.txt
```

The last two have **never been read** in any session recorded here.

## 3. What this session did

Eight increments, `47a4f76` through `6bf14a8`, recorded at §153–§162.

| Increment | What it settled |
|---|---|
| **§153** | The owner's self-evolution directive reconciled. Four of five review decisions resolved; **T1 and T2 survive** as genuine policy questions. |
| **TQ-108** §154 | Queue recovery ran *inside the agent type it recovers*. Moved to the COO. |
| **TQ-109** §155 | One claim was unrecoverable and the review named the wrong table. Claim registry added. **Finding: `engineering.receive` has no production caller** — the Software Department cannot be handed work. |
| **TQ-110** §156 | Two things were both called `schema_version`. Separated; 22 stores registered where there had been 2. |
| **TQ-111** §157 | A property that could not fail, re-aimed. SQLite write ceiling measured: **zero contention at 24 writers, ~3000 writes/s**, and the instrument proven able to see contention before that zero was believed. |
| **TQ-112** §158, §159 | The Demonstration Engine. Its first run found a restart that came up **with no executive** — adoption read heartbeat age and ignored the process state its own shutdown had written. |
| **TQ-113** §160 | The television station: nine programmes, scripts, guests, breaking news, ad breaks, sign-off. **The Dedicated Anchor specification arrived mid-build** and moved presenting out of the COO. |
| **TQ-114** §161 | `planned_seconds` was a column nothing read, so a 695-second rundown aired in thirteen and one run produced fourteen broadcast days. |
| **TQ-115** §162 | The desk. A trader with a book of their own, five attribution verdicts, and a **conviction floor guessed at 0.5 that sat above the entire observed distribution** — the role was inert and looked like it was judging. |

**Live state: `tv_station` passes 20/20**, `python -m simulation run tv_station`.

## 4. What the next session should do first

**Re-run the full verification. It is stale by eight increments**, including two
new agent roles in the baseline population, four new stores (22 to 26) and two new
metric families.

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m simulation verify
```

Last `PASS` was 2026-08-29 at `c382ea5`. Expect 35–40 minutes; there are now
**12 scenarios**. `INCOMPLETE` rather than `PASS` is the honest answer if the
daily model budget is exhausted (§129).

**Two things to watch**, both new and neither exercised by `verify` yet:

- **The trader is in the baseline population.** Every scenario now runs 9 agents
  where it ran 8, and only `tv_station` and `baseline_steady_state` have seen it.
  Nothing asserts on the count; `saturation_two_judges` asserts on the role.
- **The COO now attributes closed trades** inside its own cycle. If a trade
  cannot be attributed the loop is wrapped, but the COO's cycle is the busiest
  path in the system and this is the newest thing in it.

Then: the **sector plausibility assessment** (§5 below), which is the one piece
of asked-for work that is specified and unbuilt.

## 5. Known blockers and open questions

**With the owner — only two, and neither blocks the next milestone:**

1. **T1 — what mediates a code change.** The self-evolution directive's *"increasing
   autonomy is a POLICY CHANGE, not a REWRITE"* requires the deploy mechanism to
   exist now with the policy off; three tripwires deny it. Recommended resolution
   at §153: the department authors an approved change record, a mechanism outside
   the runtime applies it. **Do not resolve this by deleting a tripwire.**
2. **T2 — the healing addendum's H1/H2 against directive §2.** Two owner documents
   dated the same day; §2 forbids the department editing operational data, and
   H1/H2 are largely that. Recommended: the department diagnoses and specifies,
   the owning domain performs through its own API.
3. **Classification of the ten supplied documents.** Nothing is committed. The
   later ones carry revenue targets, viewership and trading desks, which the
   boundary rule puts on the private side.

**Specified and unbuilt, and the owner asked for it:**

- **Sector plausibility assessment.** Owner direction 2026-08-30: rather than
  waiting for an outside body to fact-check a claim, analyse it ourselves and
  accept it as plausible if no logical blocker prevents it actualising. The
  catalogue in `backend/sectors.py` currently carries every entry at `premise`
  and says so on air. The honest build uses the model gateway the Explorer and
  Analysis already use, records the blockers considered alongside the verdict,
  and moves the standing to `plausible — no blocker found among these` or
  `blocked by X`.

**Standing gaps, unchanged:**

- **Nothing can file the Software Department work.** `engineering.receive` has no
  production caller (§155), so the department its 20-step lifecycle belongs to
  has never been handed a directive.
- **No CEO.** The owner confirmed the Superuser is currently the CEO and a
  dedicated one arrives later. The Dedicated Anchor specification's §2 separation
  is recorded as a constraint for that day, not implemented.
- **45+ scenario properties have never been observed failing.**
  `simulation/property_history.worklist()` lists them.
- **`JARVIS_GAP_ANALYSIS.md` is stale** — it scores against a Constitution that
  moved to v2.0 on 2026-08-28.

## 6. Constraints that must not be violated

Each was bought with a defect. Unchanged from the last checkpoint except where
noted.

1. **Client portfolios are never stored** (§111). **Extended at §162**: a
   trader's book is the *agent's own* record keyed on `agent_id`, and no row in
   it may carry a client — a test scans the schema, because the way §111 gets
   undone is an owner column added to a table that already exists.
2. **The Constitution is not in any store**; the organization amends it at
   two-thirds; the **bar is a constant in code** (§120, §141, §142, §123).
3. **Absence is `unknown`, never a plausible default** (§100, §104, §118, §132).
4. **Tripwires are re-aimed, never deleted** (§105, §110, §116, §128, §134,
   §147, §149, §157, §162).
5. **One identical refusal for every reason** a caller is not entitled to
   distinguish.
6. **`docs/JARVIS.md` is under document custody.** Editing it means updating
   `docs/document_custody.yaml`'s digest **in the same commit**, or the suite
   fails. This bit three times this session.
7. **Simulation seeds go through the production API, never SQL** (§128).
8. **No agent may know it is in a simulation** (§115).
9. **When a query filters on a domain value, use the constant** (§149 §4).
10. **Nothing in the running system writes to the repository.** `release.py` may
    not import `subprocess`/`os`; nothing may write into `docs/`. This is T1's
    subject — change it by decision, never by deleting the test.

## 7. Working rhythm

Assimilate verbatim → reconcile against the *specifications* and not the build →
queue → one increment → suite green → **run it and look** → record a
`SPEC_RECONCILIATION.md` § → update the queue and `JARVIS.md` → commit → **push,
merge to `master`, push** (run `tests/test_public_private_boundary.py` first —
the repository is public).

Under the owner's standing Development Philosophy: **COMPLETE → WORKING →
RELIABLE → CORRECT → EXCELLENT**, and do not reverse it. Make reversible
decisions autonomously, mark them provisional, and bring only true hard blockers.

## 8. How this project keeps being wrong

The five from the last checkpoint still hold. This session added two, and both
are worth carrying:

- **A constant guessed rather than measured makes a role inert while it looks
  like judgement** (§162). The trader's conviction floor was 0.5; across 414
  analyses the organization produces a median of 0.22 and reached 0.5 four times.
  The desk declined every idea it ever saw.
- **The tooling can turn a check into a tautology** (§162 §6). A word-boundary
  escape delivered through a shell heredoc arrived as a literal backspace byte;
  the regex matched nothing and the suite went green *because the check had
  stopped checking*. Verify a repaired check by making it fail, not by watching
  it pass.

And the one that keeps paying: **a green suite is not evidence.** Every defect
found this session came from running the thing and looking at it — the restart
with no executive, the fourteen broadcast days, the desk that never traded, the
news flash that interrupted an advert.
