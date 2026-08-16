# Specification Reconciliation

**Maintained document — unlike `docs/addenda/*`, this file is meant to be edited.** The addenda are
verbatim, immutable copies of user-provided specifications. This file is the project's own record of
how those specifications were reconciled against each other and against what is actually built.

Every canonical document in this project carries the same Conflict Rule (addendum 5 §2, 6 §8, 7 §10,
10 §11, 11 "Interpretation rule", 12 "About This Consolidation", 13 §17): *do not silently preserve
both models — stop, resolve, and update the canonical specification so one internally consistent rule
remains.* Since the addenda themselves are marked do-not-edit, **this file is where that resolution is
recorded.**

Last updated: 2026-08-16.

---

## 1. Document precedence

| Layer | Document | Status |
|---|---|---|
| **Constitutional** | `docs/JARVIS_CONSTITUTION.md` (2026-08-16) | **Supreme.** "The constitution is the durable design authority." Governs principles; the addenda describe construction. Where they conflict, the constitution governs and the addendum is reconciled to it. Gaps tracked in `docs/JARVIS_GAP_ANALYSIS.md` |
| Architectural | Original addendum 1 | Base My AI product (voice/universal-agent). Unrelated to Financial Intelligence; historical. |
| Architectural | First FI set, addenda 2–4 | **Superseded** by addenda 5–10 (per addendum 5's header). Historical only. |
| Architectural | Second FI set (2026-08-14), addenda 5–10 | Canonical, except where addenda 11–14 explicitly clarify — see §2. |
| Architectural | Third FI set (2026-08-15), addenda 11–14 | Canonical. Where these conflict with 5–10, these win. |
| Derived | Addendum 15 (2026-08-16), rationality monitoring | Canonical for its subject, but **not a verbatim import** — derived from owner rulings in discussion, and editable as the design evolves. Nothing in it is built. |

Within the newest set: addendum 11 is the organizational constitution, 12 the integration spec
(its §21 Pre-Alpha task list drives current work), 13 the training design, 14 the acceptance criteria.

Addendum 15 differs in kind from 11–14: those are verbatim user-supplied specifications marked "do
not edit," whereas 15 was written here from owner decisions given in conversation on 2026-08-16 plus
the owner-supplied `Sentinel_Argument_for_Claude.txt`. It is therefore amendable in place rather than
reconciled against.

**Not saved as an addendum:** `Financial Intelligence Gap1 Redesign Notes.pdf` and
`agent-identity-redesign.pdf` (both in `C:\Users\Krish\Downloads\`). These are voice-session working
notes and proposals, not canonical specifications — the same treatment the Gap 1 notes already had.
Their dispositions are recorded in §4 below.

---

## 2. Superseded statements

### 2.1 Coordinator is not an agent → Controller **is** an agent

- **Old (addendum 6 §1):** "Coordinator: internal server component. It is a factory manager and
  executor, not an autonomous policy maker." Listed alongside "Server", not as a spawned process, with
  no interface of its own — only a dashboard *produced by* it.
- **New (addendum 11 §3, §14, §15; addendum 12 §2, §24):** "The Controller Agent is the sole authority
  that physically instantiates agents... The server remains the persistent backend runtime environment.
  The Controller is the agent authority operating through that environment." Startup is explicitly
  ordered: server → Controller → *Controller creates COO* (addendum 11 §13, addendum 12 §22).
- **Resolution: the new framing wins.** Implemented in commit `a577889`.

Two precise points, because the supersession is narrower than it first looks:

1. **What changed:** the Controller is no longer mere infrastructure. It has an identity
   (`controller-1`), an `agent_registry` row, a heartbeat, health state, an assigned name, and a
   durable organizational record — satisfying addendum 11 §2's "every agent has a defined role,
   identity, state, ... health state, and durable organizational record."
2. **What did *not* change:** "executor, not an autonomous policy maker" is still true and still
   binding. Addendum 11 §3 keeps it ("a service authority, not an arbitrary gatekeeper") and §15
   restates it ("The COO decides operational need; the Controller executes lifecycle changes"). The
   COO/Controller authority split is unchanged in substance — it was already how the code worked
   before this reconciliation.

**Naming:** addendum 6 says "Coordinator"; addenda 11–14 say "Controller". The code now uses
**Controller** exclusively (`backend/controller.py`). "Coordinator" appearing anywhere in code is stale.

**Owner clarification (2026-08-15)** that settled this: Controller and Coordinator are *the same
entity*; COO is a *separate* agent. The Controller is the backend server's own agent identity — the
server comes up *as* Controller rather than containing one. It is therefore the one agent that is not
a spawned subprocess.

### 2.2 Retirement is dormancy, and lifecycle is separate from process liveness

- **Old (built until 2026-08-16):** a single `agent_registry.status` column held `active`/`gone`/
  `crashed`. Retirement set a flag; the agent exited; the row read `gone` — indistinguishable from any
  other clean exit. Nothing was reversible, and because COO treated any non-`active` agent as missing,
  a retired agent was **respawned within a cycle**. Retirement silently did nothing.
- **New (addendum 11 §9, addendum 12 §4):** "Retire means serialize the agent's state and place it
  into a dormant/sleep state. Retirement is non-destructive and reversible." Plus a **resume** path,
  and "destructive deletion is a separate, exceptional, rare maintenance operation."
- **Resolution (owner decision, 2026-08-16): adopted.** Implemented in commit `7dfc55f`.

The owner's framing, which is sharper than the documents' own wording: **implement lifecycle states
separate from process liveness. Let processes exit, but preserve agent identity, status, and history
in the database.** So `agent_registry` now carries two orthogonal axes:

| Axis | Values | Who writes it |
|---|---|---|
| `lifecycle_state` | `active`, `dormant` | **Controller only** — organizational standing |
| `process_state` | `running`, `stopped`, `crashed` | the agent itself (`stopped`), COO's health check (`crashed`) |

Conflating them was what made dormancy inexpressible. The same event — "no process is running" — has
opposite correct responses depending on standing: refill an `active` role, leave a `dormant` one alone.

Consequences worth knowing:

- **A dormant agent is never respawned by COO.** Retiring the only agent of a baseline role genuinely
  leaves that role unstaffed until someone resumes it. That is what retirement *means*; COO must not
  undo a Controller decision.
- **Resume restores standing only.** `resume_agent` flips `lifecycle_state` back to `active`; COO's
  normal baseline check then sees an in-service role with no process and requests the spawn. The agent
  returns under the same permanent identity, same name, full history.
- **`status` is retained but now derived** (`_derive_status`) from the two axes, so historical rows and
  the old vocabulary stay coherent. Never make a decision from it. `SCHEMA_VERSION` bumped to **2**
  because the meaning of newly-written rows genuinely changed.
- **Registration never un-retires.** `register_agent` reports process liveness; it deliberately leaves
  `lifecycle_state` alone on the ON CONFLICT path.
- **Crash detection never retires.** COO marking a dead process `crashed` is an observation, not a
  lifecycle decision.

**Cognitive state serialization is explicitly deferred** (owner decision) — see §5. The literal phrase
"serialize the agent's state" is satisfied today by preserving the durable organizational record
(identity, name, performance history, grades, evidence), all of which already lives in the database.
Serializing *process memory* is deliberately not built, and arguably shouldn't be: addendum 13 §9
requires durable knowledge to live in the database as organizational property rather than inside an
agent's transient context, so a correctly-built agent should have little worth serializing.

#### Sleep is dormancy — not a third state (owner decision, 2026-08-16)

Addendum 11 §9's phrase "a dormant/**sleep** state" left it open whether *sleep* named something
distinct from dormancy. It does not. **Owner ruling: sleep and dormancy are the same concept, two
words for one state.** The `lifecycle_state` axis stays two-valued.

This was considered and rejected on the merits, not on effort. The candidate distinction was that
dormancy is an organizational standing decision that waits for someone to reverse it, whereas sleep
is temporary and expected to end on its own. But COO's behaviour is *identical* for both — don't
respawn, don't count the role as understaffed — so the only real difference is **why it stopped and
when it should resume**. That is data, not a state: a reason and a wake condition, both expressible
as fields on a row that already exists. Adding a third value to a tested lifecycle model to carry
one nullable column's worth of meaning is structure for its own sake.

The one consequence to hold onto: **a sleeping agent does not wake itself.** Dormancy waits for an
external `resume_agent`, and COO deliberately will not respawn a dormant agent — that is the entire
point of separating the axes. So something must hold the alarm clock.

#### Who wakes a sleeping agent (owner decision, 2026-08-16)

**The agent that put another agent to work owns waking it.** Whoever commissioned an agent is
responsible for resuming it from dormancy.

Two readings had to be separated before the rule means anything. The Controller is the *exclusive
executor* of every lifecycle action (addendum 11 §15), so read literally the answer would always be
"the Controller," which says nothing. The rule attributes to the **requester**: COO asks, Controller
acts, COO owns the wake. That is already recorded — `coo_directives.requested_by` is `NOT NULL` and
survives into `coo_directives_completed`, for spawn and retire alike. **No schema change is needed**;
the supervisory link is a query against the most recent completed directive for that identity, the
same shape as `most_recent_completed_spawn` (and with the same ordering caution — order by `id`, not
by timestamp, per the millisecond-tie bug fixed earlier).

**The duty attaches to the role slot, not the process.** Because identities are permanent role slots,
a supervisor that crashes returns as the same identity with its history intact and still owes the
wake. This is the permanent-identity decision paying off somewhere it was not designed for. Only if
the *role itself* is dissolved does the obligation dangle, and that case escalates to the owner —
consistent with how concerns about Bob are handled. A sleeping agent nobody can wake is the same
class of defect as the pre-2026-08-16 retirement that silently did nothing.

### 2.3 Portfolio Analysis — no conflict, just note

Addendum 9 (on-demand portfolio analysis) remains canonical for the analysis content itself. Addendum
12 §18–20 adds that Banker mediates client access to it. Not a conflict; layered.

---

## 3. Adopted — with implementation status

| Requirement | Source | Status |
|---|---|---|
| Persistence behind a data-access abstraction; SQLite may remain; migration-ready | 12 §9, 13 §11 | **Done** — `backend/db.py`, commit `116e237` |
| Controller as an agent (identity, health, durable record) | 11 §2–3, 12 §2 | **Done** — commit `a577889` |
| Startup order: server → Controller → COO | 11 §13, 12 §22 | **Done** — `backend/main.py` lifespan |
| Only Controller creates/changes lifecycle state | 11 §15, 12 §24 | **Done** — pre-existing; sole path is `Controller._handle_spawn`/`_handle_retire` |
| COO decides need and *requests*; never instantiates | 11 §4, §15 | **Done** — pre-existing; COO only enqueues directives |
| Diverse global Agent Name Repository | 12 §10, §21 | **Done** — `agent_names`, commit `a577889` |
| Every active agent also has an immutable internal identifier | 12 §10, 14 §4 | **Done** — permanent role-slot identity (`38273a6`); names layer over it |
| CEO display name configurable, default Bob, not hard-coded | 12 §10, §21 | **Done** — `CEO_DISPLAY_NAME`, seeded reserved |
| Versioned, expandable Security Universe | 12 §10, §21 | **Done (metadata only)** — `security_universe`; no consumer yet, see §5 |
| Durable performance record independent of process instance | 5 §4 | **Done** — permanent identity, commit `38273a6` |
| Retirement is non-destructive, reversible dormancy | 11 §9, 12 §4 | **Done** — commit `7dfc55f`, see §2.2 |
| Lifecycle state separate from process liveness | owner, 11 §2 | **Done** — commit `7dfc55f` |
| Resume path restores a retired agent | 11 §9 | **Done** — `resume_agent` + `resume` directive |
| Destructive deletion is separate/exceptional | 11 §9, 12 §4 | **Done** — nothing in the codebase deletes an agent record |
| Provenance from evidence → event → report → analysis → grade | 5 §3 | **Done** — Phase C tables, commit `2512b2f` |
| Peer groups explicit and versioned | 7 §5 | **Done** — commit `b65d04b` |
| Deterministic detection; LLM for interpretation only | 12 §1 | **Done** — Explorer detector is deterministic; LLM is a gate |
| Every meaningful work unit is graded | 11 §7, 12 §1 | **Partial** — discovery/analysis work is graded; training and COO-decision grading exist only as spawn-outcome observation |
| Idle is a valid state; agents don't invent work | 14 §5 | **Done** — Analysis idles when the queue is empty; nothing manufactures work |
| System stays quiet when nothing is happening | 12 §1 | **Done** — no-trigger scans produce no rows |

---

## 4. Declined or narrowed — with reasoning

### 4.1 "Sleeping Pool" identity model — **declined** (mechanism only)

Source: `agent-identity-redesign.pdf` (not canonical; a proposal, shared twice).

Proposed: agents never killed, only slept; a fixed permanent name pool; **wake the best-performing
sleeping agent** on spawn; **sleep the worst-performing** on retire; serialize agent state; rank by
age/seniority when performance data is thin.

- **Adopted from it:** permanent, durable identity (commit `38273a6`) — but on the strength of
  addendum 5 §4, which requires it independently and canonically, not on this document's say-so.
- **Adopted separately:** the Agent Name Repository (commit `a577889`) — again from the *canonical*
  addendum 12 §10, which requires names independently. This is **not** the sleeping pool's name pool:
  no wake/sleep ranking is attached.
- **Declined:** the wake-best / sleep-worst ranking mechanism and state serialization. There is
  nothing real to rank on yet (no trained agent state exists), and performance-ranked selection is the
  deferred recognition/rewards layer being folded into basic spawn/retire mechanics. Revisit once
  Phase D produces real trained state and real performance data.
- **Also noted, for the record:** that document's "Problem" and "Open implementation considerations"
  sections were verbatim reproductions of analysis produced earlier in the same working session. It was
  flagged to the owner rather than treated as independent corroboration.

### 4.2 Controller as a separately-spawned subprocess — **narrowed, not declined**

The canonical docs say "Start the Controller Agent" (addendum 11 §13 step 2), which could be read as a
separate process. Per the owner's clarification, the Controller **is** the server process. It is
therefore the sole agent that never appears in `BASELINE_ROLES` and is never spawned via
`subprocess.Popen`.

> **Invariant — do not violate:** role `controller` must never be added to `agents/coo.py`'s
> `BASELINE_ROLES`. COO would treat it as missing and ask the Controller to spawn an
> `agents/controller.py` that deliberately does not exist. Guarded by
> `tests/test_controller.py::test_controller_is_never_in_baseline_roles`.

### 4.3 Retirement as a queue-drain mechanism — **declined**

Source: `Financial Intelligence Gap1 Redesign Notes.pdf` (not canonical). Proposed replacing the
`retire_requested` flag with a per-agent pending-tasks queue: COO stops feeding tasks, the agent drains
its queue and exits itself.

**Declined (2026-08-16).** The goal — "finish what you're doing, retire when your plate is empty" — is
already satisfied: `agents/base.py` checks the retirement flag *after* `work_fn(conn)` returns, so an
agent always completes its current unit of work and exits on its own terms. Nothing forcibly kills it.
Adopting the proposal would mean building per-agent task queues that do not exist (Explorer and
Speculator self-schedule; Analysis pulls from a shared queue), and rewriting a mechanism that is
tested, real-subprocess-tested, and manually verified — to obtain a property it already has.

### 4.4 Archive triggers as SQLite-specific behavior — **narrowed**

Addendum 12 §9 / 13 §11 require that "agents must not depend directly on SQLite-specific behavior."
The two pending→completed archive triggers are SQLite trigger syntax, but they are invisible to every
caller outside `backend/fi_db.py` — no agent, and no code outside that module, knows they exist. The
requirement is therefore already satisfied. Rewriting them in application code is deferred to whenever
an actual PostgreSQL migration happens (itself explicitly deferred, addendum 12 §23).

---

## 5. Deferred — accepted in principle, not built

| Item | Source | Note |
|---|---|---|
| HR Agent | 11 §5, 12 §3, 14 §3 | Not built |
| Training Agents (Explorer/Speculator/Analysis/Executive) | 11 §6, 13, 14 §3 | Not built — Phase D |
| Independent evaluation agent | 11 §8, 12 §3 | Not built |
| Banker (stub for Alpha, active in Alpha Plus) | 12 §18, 14 §12 | Not built |
| Portfolio Analysis agent | 12 §20, 14 §11 | Not built (addendum 9 content predates it) |
| Bob / CEO, Ask Bob | 11 §10–11, 12 §23 | Explicitly deferred by the docs themselves |
| UQI (Universal Human Query Interface) | 14 §7 | **Next planned step** — pairs with the Controller control-panel UI |
| Minimum agent self-awareness (answer "who are you", etc.) | 14 §6 | Not built; prerequisite for UQI being meaningful |
| Simulation Experiment Framework | 14 §9, 12 §11 | Not built — Phase D |
| Competency/skill catalogs | 12 §6, §21, 13 §3 | Not built |
| Two-layer resident/database knowledge model | 12 §8, 13 §10 | Not built |
| Cognitive/process state serialization on retire | 11 §9, 12 §4 | **Deferred, future work** (owner decision, 2026-08-16). Dormancy itself is built — see §2.2. What is *not* built is serializing an agent's in-process cognitive state, because none meaningfully exists yet and addendum 13 §9 says durable knowledge belongs in the database rather than in agent context. Revisit when Phase D gives agents real trained state |
| Explorer↔Speculator cross-check contracts + escalation policy | 12 §14, §21 | Not built — the two agents currently work independently |
| COO starvation/backlog scaling | 6 §5, 11 §4 | Not built; now unblocked (a real queue exists) |
| `run_id` on messages | 10 §3 | Not built; tied to the replay clock (addendum 8 §7) |
| Security Universe consumers | 12 §10 | Table exists; no agent reads it yet. Wiring Explorer's watchlist to it belongs with multi-security graduation |
| Ten-security graduation | 8 §4 | Currently at 4 |

---

## 6. Open conflicts — unresolved, need an owner decision

### 6.2 Multi-hop provenance

One-hop provenance is built (each record carries producer and handler identity). Tracing a grade all
the way back to the raw evidence that started the chain was never worked out. Not blocking anything
today; will matter as chains get longer.

### 6.3 Every meaningful work unit is graded — partially honored

Addendum 11 §7 says *every* meaningful action produces an evaluation artifact, explicitly including
management, scaling, training, and evaluation work. Today only discovery/analysis output is genuinely
graded; COO's decisions get an observed-outcome check but no quality grade, and there is no training or
evaluator work to grade yet. Not a contradiction so much as a large unbuilt surface — listed here so it
is not mistaken for done.

---

## 7. Graduation path and current position

From addendum 14 §16:

- **Pre-Alpha** — metadata, contracts, persistence abstraction, agent population, skill catalogs,
  simulation foundations. ← **current position**
- **Alpha** — full organization continuously operational on simulated data, with UQI, training,
  evaluation, end-to-end synthetic workflow.
- **Alpha Plus** — activate and train the Banker/client relationship layer.
- **Beta** — move the certified organization to historical market data.

Progress against addendum 12 §21's Pre-Alpha task list:

- [x] Global Agent Name Repository + configurable reserved CEO name
- [x] Versioned Security Universe
- [x] Persistence/knowledge abstraction over SQLite
- [ ] Common agent identity/lifecycle/task/evidence/report/grade/outcome/health contracts — *partial:*
      identity, health, evidence, report, grade, and outcome records exist; task and lifecycle
      contracts do not
- [ ] Skill catalogs
- [ ] Pluggable Simulation Engine + scenario libraries
- [ ] Role-specific Training Agents + grading/feedback persistence
- [ ] Explorer↔Speculator cross-check contracts + escalation policy
- [ ] Banker session/relationship memory + on-demand Portfolio Analysis flow
- [ ] Alpha performance milestones, stability duration, failure/recovery expectations, graduation criteria
