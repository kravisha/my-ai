# Specification Reconciliation

**Maintained document — unlike `docs/addenda/*`, this file is meant to be edited.** The addenda are
verbatim, immutable copies of user-provided specifications. This file is the project's own record of
how those specifications were reconciled against each other and against what is actually built.

Every canonical document in this project carries the same Conflict Rule (addendum 5 §2, 6 §8, 7 §10,
10 §11, 11 "Interpretation rule", 12 "About This Consolidation", 13 §17): *do not silently preserve
both models — stop, resolve, and update the canonical specification so one internally consistent rule
remains.* Since the addenda themselves are marked do-not-edit, **this file is where that resolution is
recorded.**

Last updated: 2026-08-18.

---

## 1. Document precedence

| Layer | Document | Status |
|---|---|---|
| **Constitutional** | `JARVIS_CONSTITUTION.md` (2026-08-16), **held privately** | **Supreme.** "The constitution is the durable design authority." Governs principles; the addenda describe construction. Where they conflict, the constitution governs and the addendum is reconciled to it. Gaps tracked in `docs/JARVIS_GAP_ANALYSIS.md` |
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

#### Superuser access to /admin (owner decision, 2026-08-16)

Addendum 14 §7 requires UQI access to be "privilege-controlled and auditable", and §7 adds that
"ordinary external clients do not receive unrestricted UQI access to internal agents." Auditable was
satisfied from the start; privilege-controlled was not, and is now.

- **Admin status is configuration, not data.** `MY_AI_ADMIN_USERS`, comma-separated, read at call
  time. Deliberately not a flag in `users.json`: granting it would need a route, and a
  grant-admin route is a privilege-escalation surface better not built than carefully guarded.
  Whoever controls the process already controls the database file, so the process environment is
  no weaker a source of authority — and it keeps the grant visible at startup.
- **Unset means closed, not open.** With no admins configured every `/admin` route returns 403,
  including for an account that was an admin before a restart. An auth feature that defaults open
  is worse than none, because it looks protected. The refusal names the variable to set.
- **Built on the existing session auth**, not a parallel shared secret — bcrypt passwords and
  `secrets.token_urlsafe(32)` sessions already existed and were tested. No second credential type
  to store, rotate, or leak.
- **The audit identity now comes from the session.** `asked_by` and `requested_by` were previously
  client-supplied strings; an audit trail whose author field the caller sets is decorative. They
  are no longer fields on the request models at all, rather than accepted and silently overridden.
- **The monitor's routes are gated too.** `/admin/clients/{username}/transcript` exposes every
  account's conversations — more sensitive than anything the agent panel serves. Gating the newer
  routes while leaving that open would have been incoherent.

**Still open:** there is one privilege level, not a role model. Addendum 11 §5's HR and the
evaluation functions may eventually want distinct scopes; a single superuser flag is the honest
shape while the system has exactly one operator.

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

## 8. Portfolio analysis: addendum 9 extended, not replaced (2026-08-17)

A portfolio-analysis directive arrived defining source-agnostic analysis, exposure, risk, attribution
and simulation integration. Addendum 9 is marked canonical and *do not edit*, so the question was
whether the two compete.

They do not. Addendum 9 says of itself that it is "intentionally basic in the first implementation and
will receive deeper specifications later", and this is those specifications. Recorded as an extension.

**One conflict — RESOLVED (owner, 2026-08-17): the normal path.** Addendum 9 has the Coordinator
creating the Portfolio Analyst directly, bypassing COO, on a client request. Every spawn built since
routes through COO deciding need and the Controller executing, and that is what a client-triggered
Portfolio Analyst will use too. The bypass existed to save COO's ~1s cycle on an urgent request, which
is not worth maintaining a second way to create an agent — and under a manifesto that declines to be
rushed, saving a second by adding a mechanism is the wrong trade.

`bootstrap_coo` remains the sole exception and must: there is no COO yet to have placed the directive
that would create one. `tests/test_controller.py` now parses the Controller and asserts that exactly
two functions start a process, so a second bypass cannot be added quietly for one good local reason.

**A constraint that gates the work.** The nominated reference portfolio is a real IRA statement, and
this repository is public. Every committed fixture must be synthetic - including one structurally
equivalent to the reference - with the real statement kept outside both repositories and read from a
local path at runtime. `app/data_classification.py` already classifies `account_id` as LOCAL_ONLY; this
extends the same judgment to test data.



## 9. Who adjudicates a contested case (2026-08-17)

The governance framework requires investigation, prosecution, adjudication, rehabilitation, reputation
assessment and retirement authority to be separated. That raises the question of who adjudicates, and
the honest inventory is that **nothing in this organization can**.

| Role | Why not |
|---|---|
| Controller | Executes lifecycle actions; explicitly not a policy maker |
| COO | Already maintains the workforce, judges intelligence health and acts for the vacant CEO. Adding adjudication concentrates manager, investigator, reputation assessor and retirement authority in one agent |
| Explorer, Speculator | Barred from judging by the axiom separating observation from judgment |
| Analysis | The only role that reasons — and the subject of the one live finding, and the throughput bottleneck |
| CEO | Vacant |

**Resolution: adjudication splits, and no adjudicator is appointed.**

Of the objection grounds the framework lists, five of six are decidable from recorded facts — whether
work falls outside a role's charter, whether a dependency exists, whether a resource is reachable,
whether instructions contradict, whether an agent is measurably overloaded. Only a subjective safety
concern needs weighing, and that escalates to the owner, who is the only genuinely independent party
that exists.

So the objection mechanism is not blocked by the absence of a judge: **most objections need a checker.**
Appointing an adjudicator now would be building a court before there is a dispute, against the
framework's own rule to adjudicate only when an exception genuinely requires it. A contested caseload
is the evidence that would justify one.

Two boundaries are asserted rather than stated:

- **Detection cannot punish**, because `backend/compliance.py` contains no write path at all. A module
  with no write statement cannot sanction anyone whatever it concludes, and the test parses for it —
  the natural next change to a compliance module is to have it record what it found, and that is the
  change that merges the investigator with the enforcer.
- **No role charter grants adjudication, sanction or punishment.** Checked across every charter, so a
  judiciary cannot be acquired by wording.

**Retirement stays outside enforcement.** It remains an organizational decision — COO requests, the
Controller executes — with no enforcement path able to reach it while there is no independent
adjudicator.


## 10. Declining ordered work (2026-08-17)

G5 was queued as "structured objection instead of free-form refusal". Checking the premise first
changed the work: **there was no free-form refusal, because there was no refusal at all.** Every
directive ended `success` or `failure`, and two paths in the Controller were objections wearing a
failure's clothes.

| Path | Was | Is |
|---|---|---|
| Retire or resume an identity that does not exist | `failure`, detail "unknown identity" | objection, ground *missing dependency* |
| A directive type the Controller has no handler for | `failure`, detail "unknown directive_type" | objection, ground *jurisdiction mismatch* |

Conflating them cost two things. The metrics read a well-founded refusal as a malfunction, so an
executor that correctly declined an impossible order looked unreliable. And the reason lived in free
text, where nothing could check it.

**Three requirements at filing.** The ground must come from the closed list; an "other" category would
restore discretionary refusal under a new name. The evidence must state what was observed. The remedy
must state what would let the work proceed — a refusal that only says no hands the design problem back
to whoever asked.

**Settling is checking, not judging.** `compliance.check_objection` reads the records and reports;
`fi_db.settle_objection` records the answer. The checker has no write path and the writer does no
reasoning, so neither half can do the other's job — the G7 separation, made behavioural. An objection
can be *rejected*: claiming an agent is absent when the registry has it is settled against the objector.

**Unsettled is not rejected.** A ground needing judgment, or one with no checker built, is marked
`escalated` and waits for the owner. Treating it as unfounded would make refusing cost the objector,
which is the incentive the governing framework spends a section trying to avoid.

**One checker exists, and the gap is counted.** `missing dependency` is checkable today and is the one
ground with a real instance in the running system. Four others are verifiable in principle with no
checker yet, each recording what is actually missing — a threshold that must be measured, charters that
state scope in prose rather than machine-readably, a resource probe that lives in the wrong layer.
`UNCHECKED_GROUND_COUNT` pins the gap so it cannot quietly stay where it is.

### A migration hazard found on the way

`CREATE TRIGGER IF NOT EXISTS` has the same trap as `CREATE TABLE IF NOT EXISTS`, **and it hides
better**: a changed trigger silently keeps its old definition, and unlike a missing column there is no
PRAGMA that reveals it and no query that fails.

Measured before the fix was written. With the archive trigger still on its two-outcome version, a
directive completed as `objected` was never archived and stayed in the pending queue — on a real
database, an executor re-processing the same directive every cycle forever. `apply_additive_migrations`
now reconciles triggers by content, and the fix is verified against a database created before the
change.


## 11. Measuring the governors (2026-08-17)

The governing framework asks for governance metrics *before* adjudication rather than after, so that if
a courtroom is ever built there is already evidence about whether the processes feeding it work.

The design question is what makes a metric a *governance* metric. Counting violations measures the
agents. To measure the governors, a metric has to be able to indict the machinery — so **every metric in
`backend/governance.py` names a specific way the governance layer fails**, and each is tested in both
directions: healthy, and broken on purpose in the way it exists to detect. A metric that reads healthy
under every condition is decoration, and decoration is worse than nothing because it also supplies the
reassurance.

| Metric | The failure it detects |
|---|---|
| `path_coverage` | A new kind of completed work with no evaluation rule. The check keeps passing because it never looks |
| `escalation_backlog` | Escalation as a dead letter box. Unattended, the settlement design becomes refusal with extra steps |
| `settlement_mix` | Filing becomes free (every objection upheld) or punished (none ever upheld). The second is worse — agents learn to fail silently, and a silent failure carries no ground, evidence or remedy |
| `checker_coverage` | Escalation caused by unbuilt machinery, mistaken for a genuine need to appoint a judge |
| `finding_attribution` | A governance layer blaming agents for the specification |

`path_coverage` reads the **live database** rather than the declared schema, deliberately: the question
is whether the check covers work this system actually completes, and a table present in a running
database is work being completed whether or not anything declared it.

**No single governance score.** A health number would be the first thing optimised and the last thing
understood — the same reasoning that keeps competency per-dimension.

**No invented thresholds.** `settlement_mix` refuses to state a rate below ten settled objections, and
`escalation_backlog` reports an age while stating no threshold at all, because the measurement that
would set one — the owner's observed turnaround — has not happened. "Absent is not zero" applies to the
governors as much as to the agents.

**Read-only and owner-run.** The module cannot write, asserted by a test. It is deliberately not wired
into any agent's cycle: the obvious host is COO, which already judges intelligence health, and that is
the reason not to — it would put the assessment of the governors inside the role the assessment most
needs to cover. `python -m backend.governance` reports to the owner instead.

### What it says today

Run against a real database, it reports one concern independently: **four of five verifiable objection
grounds have no checker**, so they escalate for want of machinery rather than for want of a judge. That
is the honest gap G5 left, found by the metric rather than by memory — which is the whole point of
having one.


## 12. What the organization decided about a finding (2026-08-17)

G3 was queued as "violation and evidence schema, reusing the `knowledge_records` shape". Checking the
premise moved it before anything was built.

**A violation is recomputable; a judgment is not.** The compliance check derives findings from live
records whenever asked, so storing a violation would duplicate state that goes stale — a stored
"report 42 is ungraded" row survives report 42 being graded, and the two then disagree. What cannot be
recomputed is that somebody looked at a finding and decided it was the check's own false positive. G1
established exactly that about one of its three findings, and the fact lived only in prose.

So findings stay computed and **dispositions** get the table.

One consequence worth stating: **there is no `fixed` disposition.** Fixed work stops being found, so
resolution needs no record — and a `fixed` row would be a claim about the records that the records
already answer.

| Disposition | Meaning |
|---|---|
| `false_positive` | The check was wrong about this item |
| `accepted` | Real, acknowledged, corrective work expected to follow |
| `wont_fix` | Real, and deliberately not being fixed, with a reason that stands on its own |

**Shaped after `knowledge_records`, not invented.** A disposition is never edited or deleted; a revision
supersedes it, so a finding first ruled a false positive and later accepted reads differently from one
always accepted. Only the history distinguishes them.

### The property the design exists to protect

**A disposition marks a finding. It never hides one.** If ruling on a finding removed it, `false_positive`
would be a universal off switch and the check would report clean while covering nothing. So `check()`
still returns every finding, annotated, and splits the counts: `open_findings` is what still needs a
decision, `total_findings` is what the check found at all.

Dispositions are also strictly per-item. A rule-wide off switch is what `exempt` is for, and that is
pinned by a count.

### The guard on the guard

`governance.disposition_health` watches the mechanism: the false-positive share, how many rulings have
been revised, and how many carry a rationale too thin to review — because a required field satisfied by
a single word is a required field in name only, and that is how a governance record becomes unauditable
without ever being empty.

It reports the false-positive share and sets **no threshold on it**. A check finding real problems and a
check that is badly written both produce false positives, and telling them apart requires reading the
rationales, which is a person's job.

### Verified end to end

Against a simulation database created before dispositions existed: the migration applies, the check
finds **10 real findings** (all of them the self-grading gap), ruling on one leaves it reported while
`open_findings` drops from 10 to 9, and a revised ruling leaves both views readable.


## 13. Corrective work: per cause, routed by who could have complied (2026-08-17)

Two measurements shaped G4 before anything was built, and a third emerged from trying to dispatch the
result.

### Corrective work is per cause, not per finding

A real run produced ten findings that were one design gap. Generating a task per finding would have
produced nine duplicates and one misdirected task, and would have looked like diligence.

### Whether an agent could have complied is measurable

The framework asks investigators to distinguish agent failure from system failure before assigning
fault. The sharp form of that question needs **no threshold at all**:

> If every single opportunity failed, the compliant path was not available.

Nobody could have done otherwise, so nobody can be faulted, and the remedy is a design change. That was
literally true of the ten — 10 of 10, one analysis agent in the run, and nothing else able to grade its
output. Below a share of 1.0 some agent did comply, which proves compliance was possible. Between the
two sits a judgment `remediation.py` refuses to make from records alone, reporting `undetermined` rather
than guessing at a cutoff for "mostly".

| Classification | Meaning | Goes to |
|---|---|---|
| `systemic` | Every opportunity failed; compliance was not available | The owner |
| `attributable` | Some complied, so compliance was possible | The producing agent |
| `undetermined` | Too few completions to tell the two apart | The owner, as a question |

### There is no general task queue

Trying to dispatch attributable work surfaced it: `coo_directives` is a **lifecycle** queue carrying
spawn, retire and resume. A corrective directive draws a jurisdiction objection from the Controller —
and because G5 built that mechanism, the blocker is **demonstrable rather than asserted**. A test
enqueues corrective work and watches the system refuse it, so the claim cannot rot into a stale comment.

The blocker is carried into the record rather than dropped, because corrective work with nowhere to go
looks exactly like corrective work nobody raised.

**A general task queue is not yet justified.** No attributable corrective work has been observed — every
finding so far is systemic. Building the queue now would be building for a caseload that does not exist,
which is the mistake this whole series has been avoiding.

### Ordinary records, not a parallel track

Corrective items are `knowledge_records` with `record_kind = 'corrective_action'` — a value, not a new
table. The shape already carries a statement, its evidence, who raised it, and closure with a trace of
what closed it, and it already distinguishes *was settled* from *was wrong*.

`knowledge_exists` is the idempotence guard, and it is load-bearing rather than tidy: the check
recomputes the same findings from the same records every run, so without it one design gap would raise
an identical item every cycle until the store was noise. That is the failure COO's lens health check
already had, and the same fix.

### Verified on the real run

`10/10 SYSTEMIC -> owner`, raised as one corrective action, and re-running raises nothing further.


## 14. The agent charter (2026-08-17)

`backend/charter.py` enumerates what an agent is owed and what it owes. **Every clause names the
mechanism that enforces it, and a test resolves every name.** A protection whose enforcement does not
exist fails the suite rather than reassuring a reader.

That test earned itself on the first run: the draft claimed `fi_db.retire_agent`, and the function is
`request_retirement`. A prose charter would have carried that error indefinitely — and the error is the
whole hazard in miniature, a clause that reads correctly, sounds enforced, and refers to nothing.

**Thirteen protections, two duties, three unenforced.** The ratio is a finding rather than a preference.
Every finding this organization has produced has been systemic — the first compliance run, the
attribution metric, the corrective-work classification — so the charter is written against the failure
mode the records actually show: a system capable of faulting agents for its own defects.

Duties are held to the same standard, and are therefore short. **An unenforced duty is a reprimand
waiting for an occasion rather than a rule.**

### Three protections are not enforced, and say so

Each names what is missing rather than being omitted, because an omitted promise is indistinguishable
from one nobody thought of. They need, respectively, a consequence path, an agent-facing notification
channel, and an adjudicator — none of which exists.

### The tripwire

*Self-reporting treated more favourably than concealment* cannot be built yet, and not from difficulty:
**nothing an agent does affects its standing through a finding**, so there is no leniency to grant and
no incentive to conceal. Concealment only pays where disclosure costs something.

It is nonetheless cheap now and expensive later, so the response is a **test rather than a note** — one
that fails with instructions the moment a finding starts reaching an agent's standing. It watches
`competency_evidence`, the single gate through which that could happen, and is keyed to the tables that
function reads rather than to words in its source, so it fires on a real wiring and not on a comment.

The near miss is worth recording. `competency_evidence` already reads completed directives. Had it
counted non-success outcomes rather than filtering to successful spawns, structured objection would have
made refusing costly the day it shipped — and an agent that learns refusing is costly stops refusing and
starts failing quietly. It filters correctly. **That was luck, and the tripwire is what turns it into
design.**


## 15. Justice machinery deliberately not built (2026-08-17)

Adjudication, precedent, appeal, rehabilitation and a progressive sanctions ladder are all absent. The
reason is the same in every case: **the conditions that would justify them have never occurred.**

**A deferral nobody can detect becoming due is an omission with better wording.** So each carries a
trigger, and the triggers that can be evaluated from records are evaluated every time governance is
reported. Three kinds, because they fail differently:

| Kind | Meaning | Count |
|---|---|---|
| `existence` | Fires the first time the condition occurs. No threshold to invent | 4 |
| `prerequisite` | Cannot fire until something else exists | 3 |
| `unformulable` | The trigger needs a measurement nobody has taken | 1 |

**The four existence triggers are live and tested firing.** A general task queue becomes due when
corrective work appears that is attributable to an agent rather than the design. Checkers become due
when an objection arrives on a ground that has none. Precedent becomes due when the same rule receives
two different dispositions — the first moment consistency becomes a question anyone could answer
wrongly. Agent notification becomes due when a finding exists that an agent could act on.

**Prerequisite triggers are deliberately not watched.** Rehabilitation cannot become due while nothing
reduces an agent's standing; appeal cannot while there is nobody to appeal to. Watching for a phenomenon
the system cannot produce is a detector that passes every test and works never — a mistake this project
has made before.

**One trigger is unformulable, and says so.** An adjudicator is justified not merely when cases exist
but when escalation to the owner proves insufficient — and the measurement that would establish it, the
owner's observed turnaround on escalated objections, has never been taken because no objection has yet
escalated. Any threshold now would be invented, and every invented threshold in this project has been
wrong. `UNFORMULABLE_COUNT` is pinned, because reclassifying a checkable condition as unformulable is
the cheapest way to defer something forever.

### On real data

Nothing is due. The ten findings on a real run are systemic, so no queue is needed to carry them and no
agent could act on them — which is the deferral holding for the stated reason rather than by oversight.


## 16. What Alpha means (2026-08-17)

Two gates. **Entry** asks whether Alpha can be run at all — whether the machinery exists.
**Certification** asks whether the organization performed well enough to be trusted with real work.
Building the second without the first produces a suite that certifies against an environment incapable
of exercising it.

**The trap:** criteria composed by looking at what the system currently does will certify whatever the
system currently does. Everything passes on the first run, the gate reads green forever, and nobody
notices it is measuring nothing. So the criteria are written from what Alpha *requires*, and **several
fail today on purpose** — with a test asserting that they do. If certification ever goes all-green
without the underlying work being done, the criteria were rewritten to the answer.

Criteria reuse `properties.evaluate` rather than introducing a second comparison language. A
certification criterion is exactly a scenario property that must hold across the organization rather
than within one run.

### Where it stands

**Entry 3/5.** Simulated time, the generator contract, and isolated measured runs exist. A continuously
advancing world (A4) and a queryable history (A9) do not.

**Certification 5/10**, measured against a real run:

| Met | Unmet |
|---|---|
| No agent respawned | The queue drains — never has; pressure ratio 1.89 and 3.15 on two runs |
| No agent outlived the run | Intelligence expiry engages — built and hand-verified, has never engaged in a run |
| No directive failed | Both discovery paths produce work — every run so far is Speculator-only, zero detector events |
| Every completed report analysed | The declared organization matches the built one — `known_gap_count` is 2 |
| Every analysis graded | Governance reports no concerns — one open |

The three unmet measured criteria are the three things this project already knew about itself and had
never stated as targets. That is what the gate is for.

### Deliberately not criteria

The charter's three unenforced protections need a consequence path, an adjudicator, or an agent-facing
channel — **requiring them would make Alpha readiness the reason a sanctions system gets built**, which
the evidence does not justify. And a deferred capability holding correctly is not a deficiency; counting
it as one would convert every deliberate omission into a blocker.

### Authority

**Certification currently gates nothing**, and says so on every report. There is no production operation
to withhold, so passing confers no permission and failing withholds none. A gate described as binding
when nothing is bound would be the first false clause in a system built to avoid them.

### Found while building it

`is_not_empty` was missing from the comparator set. A suite could assert that nothing happened but not
that something did — backwards for properties whose main risk is certifying an idle system.

Two governance metrics assumed the `objections` table existed, so reading governance against any run
database recorded before that table crashed rather than reporting. Both now treat every table they touch
as optional, since governance is read against databases of every vintage.


## 17. The world stops being a series of runs (2026-08-17)

### The rate: one simulated day per wall-clock hour

Owner decision, answering the question the Alpha review recorded as foundational. `FI_SIM_TIME_SCALE`
moves from 288 to **24**.

What it buys, against measured numbers:

- an agent's one-second poll advances **24 simulated seconds** — fine enough to see intraday movement
  rather than step over it (at 288 a poll skipped five simulated minutes);
- an equity session runs **16 wall minutes**, so an open and a close are observable in a sitting;
- **ten graded reports take about 5 wall minutes** at the measured drain rate — the threshold at which a
  detection lens can bind a regime baseline, and the first time that behaviour has been reachable inside
  a run at all.

The last one decided it. **A rate is not a testability knob; it determines which of the organization's
behaviours can happen at all.**

Scale stays per-scenario config, because the two uses are genuinely different: a continuously advancing
world runs at the organization's real rate, while a bounded scenario that must observe a session
boundary inside ninety seconds has to compress time and says so. `overnight_session` pins 288 for
exactly that reason.

Two tests were calibrated against 288 and were updated to state the invariant rather than the artefact —
one asserted a misread health threshold would be sub-second, which was true at 288 and false at 24; the
other banded an agent poll at one to thirty simulated minutes, reasoning from a world where a poll
covered five.

### The world

`simulation/world.py` advances the registered generators continuously. Two properties carry it.

**State survives the rollover.** A price level that reset each morning would not be a price level, and a
monthly release that forgot when it last fired would fire every day.

**No day is skipped.** Ticks are driven by wall-clock, so a stalled process resumes with more simulated
time elapsed than it expected — at this rate, a stall of an hour and five minutes crosses a rollover
*and part of another*. Detecting "the date changed" would handle the first and silently lose the rest,
so rollover returns **every day crossed** rather than a boolean.

The boundary is announced on the event bus rather than left to each generator to notice, because three
generators tracking their own idea of a new day is three chances to disagree about when it started. It
is stamped at the current moment rather than the day's midnight: the bus ages events out after six
simulated hours, so a midnight-stamped rollover would have expired before the equity session opened —
present in the code and visible to nobody.

### Verified over a simulated month

3600 ticks, 30 completed simulated days, 30 rollovers announced, CPI released once on its monthly
cadence, and a restart mid-flight resuming at the same position without replaying a single past day.
Option surfaces appear on 19.6% of ticks, matching 6.5 session hours in 24 across five days in seven.

**Two defects found only by running it**, both of which every unit test had passed:

- `days_completed` recorded all-but-the-last crossed day, so an ordinary single-day rollover completed
  nothing. A simulated week ran with the count still reading zero.
- `summary()` asked the clock for "now" without a moment, reporting the real clock rather than the
  world's own position — a seven-hour run claimed a simulated date five years out.

**Entry criteria move 3/5 to 4/5.** Only the queryable history (A9) remains.


## 18. Three data domains and the corpus (2026-08-17)

**A historical dataset is not a run.** A run is a bounded episode with its own database and its
provenance in a manifest; a corpus is a body of data accumulated from many sources over years, where the
same fact is recorded repeatedly and revised. The two want opposite things from storage, which is why
`simulation/history.py` is a separate store rather than another table.

### The three domains

| Domain | What it is |
|---|---|
| `real` | Observed from the actual market, as it arrived |
| `historical` | Observed from the actual market, ingested afterwards as a corpus |
| `simulated` | Produced by a generator, about no real world at all |

`real` and `historical` are both about the world and differ in how they arrived — which matters, because
an ingested corpus carries **vintages** and a live stream does not. `simulated` is a different kind of
claim entirely.

**Every query names its domains.** There is no default and no "all", because the failure being guarded
against is a backtest that quietly proved something about generated data. Combining domains stays
possible and becomes a decision somebody made that can be found in the code — which satisfies the
directive's "any analysis combining domains must do so explicitly" more strongly than a filter every
reader has to remember.

### Vintages, which are why this is not a table

Published statistics are revised. A quarter's figure is published, revised a month later, revised again
a month after that — three rows describing **the same quarter**, knowable at three different times, with
three different values.

A backtest running in May must see May's number. Using the final revised figure is lookahead of the most
seductive kind: **every result improves, nothing errors, and the mistake is invisible in the output.** So
`latest_vintage_as_of` returns the newest revision *knowable* by the moment asked about, never the
newest recorded.

`revisions()` exists alongside it and is named so it cannot be mistaken for an as-of query: studying how
a number was revised is a question about the corpus, not one the organization could have asked at the
time.

### Two guards that cannot be forgotten

`as_of` requires both a moment and its domains, with no defaults — a query without a moment is a
lookahead waiting to happen. And `record` refuses a datum whose `knowable_at` precedes its
`effective_at`, because ingesting one would put lookahead in the data itself, where no query guard could
catch it.

### Verified on a simulated month

3425 observations ingested from a 30-day world. Asked as of the halfway point, **1695 of 3425** are
knowable. The single CPI row describes 5 January and becomes knowable on 19 January — the cadence's
14-day publication lag surviving into the corpus, which is the pair of timestamps doing exactly what it
was built for.

### Alpha entry is now met, 5/5

The last entry criterion closes. Certification remains **5/10**, and its five outstanding items are the
organization's real problems rather than missing scaffolding.

## 19. The Gateway lineage arrives, and one of it is already built (2026-08-17)

Three documents supplied together: the AI Communication Gateway specification (addendum 16), its Super
User addendum (17), and a Lifecycle-Managed Controller Initialization specification (18). All three are
filed verbatim. The first two describe a system that does not exist yet. The third describes work that
had already landed.

### A separate lineage, not a newer set

16–18 are numbered after 15 but do not supersede it. They are about the external communication boundary
and backend infrastructure; 2–15 are about the agent organization. Nothing in the Gateway documents
claims authority over the Financial Intelligence architecture, and the higher number must not be read
as winning a conflict — `docs/README.md`'s precedence table now says so explicitly, because the
convention up to now has been that a higher addendum number is a later revision of the same subject.

### The overlap between 16 and 17, recorded once

Addendum 17 restates a good deal of 16: one-hop interaction, the Scoreboard, "the human should make
decisions, not transport messages," the prohibition on external clients reaching internal services.
Both are kept verbatim per the house rule, so the repetition stays on the page. It is noted here rather
than reconciled because the two do not actually disagree anywhere — 17 narrows 16's audience to one
user and adds a monitoring function, and the restated material is restated identically.

What 17 adds that 16 does not have is §7–§9: a Technology and Architecture function that periodically
reviews component suitability and raises *structured recommendations* rather than making changes. Its
worked example is SQLite to PostgreSQL, on evidence of write contention. That is the process by which a
database migration is supposed to be proposed here, and it is worth knowing it exists before anyone
opens that question informally.

### Addendum 18: disposition

The specification's §9 asks for an explicit disposition. **APPROVE WITH MODIFICATIONS.**

Its objective was already met before it was filed. `backend/main.py` no longer constructs a Controller
at module scope; construction moved into the FastAPI `lifespan` context manager, which already owned
`bootstrap_self`/`bootstrap_coo`/`close()` and so was already the de facto owner of the lifetime. The
two documents reached the same conclusion independently, which is a useful corroboration and not a
coincidence worth reading anything into — the import-time write was reachable by measurement.

Two of §7's acceptance criteria were deliberately not met as written. §9 invites exactly this
("Do not accept this specification blindly if the current code proves an assumption wrong").

**"Tests no longer need import-time database-path redirection to protect the developer database."**
Not adopted. The redirect stays. The criterion assumes the redirect existed to work around the
import-time Controller, and that removing the cause removes the need. It does not: the redirect defends
a *class* — any code resolving the default database path rather than being handed one — and the
import-time Controller was one instance of that class, found only because someone hashed the file by
hand. `agents/base.py` and `simulation/harness.py` both resolve `FI_DB_PATH` independently of anything
`backend.main` does. Removing the redirect would leave the suite one import-time constructor away from
the same leak, with the session guard catching it only after the write had happened. The cost of
keeping it is three lines and a docstring; the cost of being wrong is the developer's database.

**"The application exposes the active Controller to routes without relying on construction at module
import."** Not adopted, because no route needs the Controller. The one route that referenced it —
`retire_agent`, refusing to retire `controller-1` — was comparing against `controller.identity`, which
is fixed by the role and identical for every instance ever constructed. It became a public
`CONTROLLER_IDENTITY` constant, so the route asks a name question and gets a name without a database
being opened to answer it. Adding an `app.state` accessor or a FastAPI dependency with zero consumers
would be precisely the "unnecessary abstraction" §8 forbids. The `lifespan` docstring records that
`app.state` is where a future route should reach for it, so the next person does not reintroduce a
module global instead.

Three of §6's six test requirements were also not written, for the same reason in one case and a better
one in the others. "Route access" (4) has nothing to test while no route consumes the instance.
"Startup — verify exactly one Controller is initialized" (2) and "Shutdown — verify cleanup occurs" (5)
are only reachable through a real server: nothing in the suite runs the app as a context manager, so a
unit test would be asserting against a lifespan that never ran. Both are covered end to end by the
`simulation`-marked tests, which boot a real uvicorn against `backend.main:app` and assert the
population comes up, shuts down gracefully, and leaves no process running. What was added instead is
the requirement §6 leads with and the one that actually holds the line: import safety, checked in a
subprocess with `FI_DB_PATH` aimed at a path that does not exist, asserting no file appears.

### What is built, and what is not

Addendum 18 is built. Addenda 16 and 17 are not, and nothing in this repository is a Gateway. No
external service, no phone client, no voice interface, no Scoreboard, no Technology and Architecture
function. The `/admin` routes and the UQI are the closest existing things, and they are an internal
panel behind session auth — not the single externally exposed boundary 16 §7 requires.

*(As of 2026-08-18 the first part of that is out of date: §20 below records the first increment of the
Gateway, which is a real service with a real client. Voice, Git, the Scoreboard and the Technology and
Architecture function remain unbuilt. The paragraph above is left as written, since this file records
what was true when each entry was made.)*

## 20. The Gateway becomes a process (2026-08-18)

Addenda 16 and 17 describe a service; G1 builds the first increment of it, in `gateway/`. Three
questions had to be settled before any of it could be written, and the documents settle all three
between them rather than any one of them saying so outright.

### It is a separate process, not a router on the backend

Addendum 16 §7 requires the Gateway to be the *only* externally exposed Jarvis service, and forbids
external clients from reaching internal APIs, the Controller, agents or databases. Adding these routes
to `backend/main.py` would have exposed every internal and `/admin` route on the port the phone talks
to — the precise arrangement §7 exists to prevent. §22 (able to run while the larger system is under
construction) and §23 (usable when an internal component is unavailable) both point the same way, and
neither is satisfiable by a router inside the process it must survive.

### It is a client of Jarvis, not part of it

The Gateway is not an agent: it is not spawned by the Controller, holds no role in the organization,
and must keep working when the organization is not running at all. It is the same shape the project
already uses three times — `agents/coo.py`, `panel/app.py`, `monitor/app.py` are all separate
processes that talk HTTP to the backend.

**The "SQLite is the only IPC" rule is unchanged and was never in tension here.** That rule governs
communication *between agents*, which is what addendum 6 §3 is about. Clients have always used HTTP.
Recording it because the higher addendum number invites the opposite reading, and a future reader
finding a second transport in the repository deserves to find the reason next to it.

### Its store is its own

`gateway.db`, separate from `financial_intelligence.db`, built on the same `backend/db.py` Database
class whose own docstring anticipated a second use. §23 is what forces this: if the Scoreboard and the
conversation lived in the FI database, reading a deferred question would require the backend to be up,
and the isolation §23 asks for would exist only on paper. `GATEWAY_DB_PATH` mirrors `FI_DB_PATH`, and
`tests/conftest.py`'s guard now fingerprints both files.

### What G1 does not do

It makes no call into the backend at all. There is no Git, no Scoreboard, no voice, and the assistant
has no tools — its system prompt says so explicitly, and a test asserts that it keeps saying so, since
an assistant that implied it had filed a Scoreboard item would be inventing the rest of the roadmap.
The remaining increments are G2 (phone reachability and TLS), G3 (Scoreboard), G4 (Git), G5 (project
status and proven failure isolation), G6 (voice), G7 (the Technology and Architecture function of
addendum 17 §7–§9).

### One thing G1 changed outside the Gateway

Addendum 16 §24 — "The Gateway must not fundamentally be a 'Claude Gateway'... Models are services
behind it" — required a provider interface, which is `app/model_provider.py`. Building it also removed
an import-time side effect that had been documented in `tests/conftest.py` since before the database
leak was found: `app/model_gateway.py` constructed its Anthropic client at module scope, so importing
it raised `KeyError` without an API key in the environment. It is the same class of defect as the
import-time Controller, found the same way — by reading what the tests had to work around. The
public contract of `call_reasoning_model` is unchanged.

## 21. The Scoreboard, and what it deliberately does not hold (2026-08-18)

G3 builds addendum 16 §16's deferred discussion mechanism. Two surfaces onto one
board: REST routes for producers that are not the conversation (addendum 17 §6 has
Jarvis departments publishing findings into the Gateway rather than inventing
their own notification channels), and tools the assistant calls mid-turn.

### Filing has to happen in the turn, not after it

§16 §10's one-hop requirement, applied to the board itself. "Put that on the
board" files it; a reply *describing* an item the Super User then files somewhere
would be the manual relay §26 exists to remove, with an extra step rather than one
fewer. This is why the assistant has tools at all, and why G1 did not: there was
nothing yet for a tool to do.

### The fields are §16's list, minus two with no producer

§16 names thirteen fields and says the detailed schema belongs to a later
specification. Two are absent:

- **Related commits.** Nothing in this system touches Git until G4. A nullable
  column nothing writes is an empty schema.
- **Decision, as distinct from Resolution.** Collapsed into one field, because
  nothing today can tell them apart. A decision recorded while an item stays open
  is a real distinction; when something needs it, it separates. The schema rule is
  additive, so both cost one line when they have a writer.

### Importance and blocking are separate, and stay separate

§16 lists both and §17 turns on the difference. Importance is how much attention
something deserves; blocking is whether work stopped. An urgent security question
can be non-blocking and a trivial ambiguity can block, so one field cannot say
both. Importance uses addendum 17 §10's three escalation levels unchanged.

### The escalation gap, stated rather than papered over

§10's urgent level calls for "the highest-priority notification mechanism
available to the Gateway," and §10 itself defers notification channels to a
separate specification. There is no such mechanism here: an urgent item sorts
first and is counted in the header, and nothing rings a phone. **An item filed
urgent today is seen when the Super User looks.** That is a real limitation of
this increment, not an oversight, and it is what the routing policy in
`gateway/scoreboard.py` currently amounts to.

### Provenance the filer does not control

`file_scoreboard_item` has no `source` parameter. An item filed through the
conversation is attributed to the conversation, because a model able to name its
own source could file something as though a monitoring agent had raised it, and
provenance the filer chooses is not provenance. The REST route *does* take one: a
caller holding the Super User session is trusted to name itself, which is how a
department's finding will arrive under its own name.

### Tool results are not persisted

The transcript holds the human-readable turns. Tool calls and their results live
for one turn and are then dropped, so a later turn sees the assistant's own
summary of what the board said rather than the raw result. Deliberate: it keeps
the stored conversation readable and renderable, and the tools are cheap and
idempotent to re-run - an assistant that needs the list again asks again, which
is also what stops it acting on a stale one. If a case appears where losing a
tool result breaks the next turn, persisting content blocks is additive, and the
reason to do it would be evidence rather than symmetry.

## 22. Git, and the hazard §20 could not have known about (2026-08-18)

G4 builds addendum 16 §14 and §20: the assistant reads repository artifacts, and
"publish the specification" becomes a real commit. §3's rule is the reason - *"No
approved specification should exist only inside an AI conversation."*

### Three constraints the specification does not state, and why they are here

**The working tree is never touched.** These are repositories the owner is
actively working in. A service that ran `git checkout -b` in the background would
sweep up half-finished edits and move HEAD under a running test. A publish
therefore writes a blob, builds a tree in a temporary index *outside* the
repository, commits against HEAD with `commit-tree`, and points a new ref at the
result. Uncommitted work stays uncommitted and the checked-out branch stays
checked out.

**Nothing is pushed.** A local branch is reversible; a push to a public remote is
not. §19 requires human review before significant changes land, and pushing on a
spoken sentence would put the Gateway on the far side of that gate. The publish
reports the branch and a person pushes it.

**Only tracked files are readable.** Not a denylist - a denylist is a thing
somebody forgets to update. `.env` is ignored, therefore untracked, therefore
invisible, and nothing in this module had to know it holds an API key.

### The hazard

§20 wants *"that's approved, publish the specification"* to be one interaction. It
was written before this project split its documentation: `docs/PUBLIC_PRIVATE_BOUNDARY.md`
keeps organizational philosophy and strategic rationale in the private repository,
and publishing publicly cannot be undone.

So the private repository is the default; a public target requires explicit
confirmation the model may not infer; and a screen runs over the content, path and
message before any public write.

**The screen is a tripwire, not a classifier.** It matches the vocabulary this
project's private material actually uses - constitution, charter, axiom, manifesto,
philosophy, guiding principles, INT-PHIL - and it will be wrong in both
directions: a specification that merely mentions the constitution is stopped, and
philosophy phrased in ordinary words passes. It is set to fail toward the private
repository, because that failure is a person retyping a destination and the other
one is not undoable. It does not run against the private repository at all, since
that is precisely where such material belongs.

The assistant is told, in its system prompt, not to rewrite a document to get it
past the check but to report what was flagged and let the owner decide. Verified
live: given explicit authorisation to publish a charter/axioms note publicly, the
refusal held, the model named the flagged terms, offered to publish privately or
write a public-appropriate version, and did not attempt to evade.

### A defect that only a live call could find

The provider converted the model's content blocks with `model_dump()` and sent
them back on the next request of the tool loop. A response block and a request
block are not the same shape - the dump carries response-only fields, and the API
rejects them: `messages.7.content.0.text.parsed_output: Extra inputs are not
permitted`. The whole unit suite passed throughout, because a stand-in provider
emits exactly the fields its author thought of. `app/model_provider.py` now
reduces each block to what may be replayed, and an unrecognised block type is
passed through whole rather than silently stripped.

**That is the fourth time in this project a defect has survived a green suite and
been found by running the thing.** The pattern is now unmistakable for anything
that talks to a real process or a real API.

## 23. The Gateway looks at Jarvis, and proves it does not need it (2026-08-18)

G5 gives the Gateway addendum 17 §4's "project-wide status visibility", and then
spends most of its effort on the harder half: demonstrating addendum 16 §23's
failure isolation rather than asserting it.

### Read-only, and enforced where it acts

The Gateway issues GETs against the backend's `/admin` surface and nothing else.
It cannot retire an agent, resume one, or file a directive. Addendum 11 §15 makes
the Controller the exclusive executor of lifecycle changes, and the control panel
already exists for a human to request them - giving a conversational model
lifecycle authority over the organization is a far larger step than "show me what
is running", and it is not this increment's to take.

The restriction lives in `gateway/jarvis.py`, in the one method that reaches the
network, rather than in a convention that future tools are trusted to follow. A
test asserts the assistant is offered no `retire_agent`, `resume_agent`,
`spawn_agent` or `push_branch`.

### Being down is a value, not an exception

§23 is not satisfied by catching exceptions somewhere upstream. It is satisfied by
"the backend is unavailable" being an ordinary answer - `{"available": false,
"reason": ...}` - so that the conversation, the Scoreboard and Git carry on
without knowing anything is wrong. `/status` therefore answers **200** when the
backend is down, not 502: a status page that fails when the thing it reports on
fails has confused itself with its subject.

Timeouts are two seconds to connect and five to answer, asserted in a test,
because a backend that accepts a connection and never replies would otherwise hold
a model turn open for as long as the socket allowed.

### Both axes, still not merged

`lifecycle_state` and `process_state` are reported separately all the way out to
the phone. A dormant agent and a crashed one both have no process and only one is
a fault - the distinction the two-axis model exists for, and one a status view
would be very easy to flatten into a single word.

### The session is held in memory

The backend's sessions expire after seven days, so a static token in the
environment would quietly stop working. The Gateway logs in with credentials and
renews **once** on a 401 - renewing in a loop would turn a wrong password into a
hammering of the login route. The token stays in the process: writing it into
`gateway.db` would put a second copy of a live session on disk for no benefit.

### What the live verification actually showed

Both states, deliberately, against a real backend and a real agent population:

- **Backend down.** `/status` answered 200 with `available: false` and named the
  cause (`ConnectTimeout`). The Scoreboard accepted a new item over HTTP, a
  conversation filed one and published a document to a real branch, and the
  assistant, asked whether Jarvis was running, said it was not - without
  speculating about why.
- **Backend up.** Six agents reported with both axes and heartbeat ages;
  `analysis-1` sat at 15 seconds while the rest were under one, which is the
  known-good shape for an agent mid-LLM-call rather than a fault.
- **A retirement, mid-run.** `dummy-1` retired through the panel route came back
  as `dormant / stopped`, counted as dormant, and absent from `crashed` - the
  distinction surviving the whole path from `agent_registry` to the browser.

## 24. The function that reviews, and does not act (2026-08-18)

G7 builds addendum 17 §7-§9's Technology and Architecture function: a periodic
review of the technical ecosystem that raises **structured recommendations** and
performs none of them. §9 is explicit - *"The monitoring function does NOT
independently perform the migration"* - and §7 twice says what it is not: not
high-frequency, not heavyweight.

### Every check measures something that exists

The temptation in a function like this is to invent metrics, because numbers look
like evidence. Each check reads something real off the machine or out of the
running system - database and WAL sizes, unpinned dependencies, Python version,
free disk, whether a git binary exists, and the concurrency the backend reports -
and a check with nothing to read returns `no_evidence` rather than a guess.

Four verdicts: `suitable`, `watch`, `unsuitable`, `no_evidence`. **Only `watch` and
`unsuitable` reach the Scoreboard.** A board that filed an item every time
something was fine would bury the ones that are not.

### §9's worked example, answered honestly

SQLite versus PostgreSQL is the recommendation this kind of function is most
likely to make enthusiastically and wrongly, and §9 uses it as the example. What
this one reports: the number of processes sharing the database, whether any
heartbeat is stale - and that **nothing in this system counts SQLITE_BUSY or times
a blocked write**, so the absence of contention is *unmeasured rather than
observed*.

The verdict today is therefore "suitable, do not migrate", with the limitation
stated in the evidence rather than hidden by it, and a recommendation whose
`expected_future_risk` says what would change the answer: instrument first, then
ask again. A monitoring function whose first act is to decline to raise an alarm -
and to say exactly how confident it is entitled to be - is the strongest available
demonstration that it is evidence-driven rather than decorative.

Verified live through a conversation: asked whether to move to PostgreSQL, the
assistant answered no, cited the database size and disk headroom, and separately
flagged that the concurrency question was `no_evidence` rather than clean -
*"those are different things and I'm not papering over the gap."*

### Repetition would destroy the board

A periodic producer that refiles the same finding every interval makes the
Scoreboard useless within a day. `scoreboard_items` gained a `signature` column
(additive, with a migration for existing databases), and a finding whose signature
already has an **open** item is skipped. Resolved items do not suppress: a finding
that was dealt with and has recurred is news again. Items filed by people carry no
signature, because a person filing the same concern twice usually means something.

### The defect this increment found by running

The periodic loop opened its SQLite connection on the event loop thread and handed
it to a worker thread, which sqlite3 refuses. It failed on **every pass**,
survivably - the loop catches everything so the service stayed up - and therefore
silently. The whole pass now crosses the thread boundary as one call taking a
path, the same arrangement `gateway/conversation.py` uses for the same reason.

**Fifth time.** The pattern is no longer worth restating: anything in this project
that touches a real process, a real API or a real thread boundary gets run before
it is believed.

## 25. How the phone reaches the Gateway (2026-08-18)

**Owner decision: a tunnel.** `cloudflared` or Tailscale Funnel terminates TLS and
forwards to the Gateway on loopback. Nothing is opened on the router, the
certificate is real, and the service continues to bind to 127.0.0.1.

The two alternatives and why they lost: a LAN-only self-signed certificate works
only at home and requires trusting a certificate on the phone; a forwarded router
port exposes a service with elevated authority over specifications and Git
directly to the internet, which addendum 17 §14 ("a high-security boundary") is
reason enough to decline.

This settles the decision G2 was waiting on, and addendum 16 §12's TLS requirement
is met by the tunnel rather than by the application - which is why the code in this
increment is about being correct *behind a reverse proxy* rather than about
terminating TLS.

### The address problem the tunnel creates

Behind a tunnel every request arrives from 127.0.0.1, so rate limiting on the peer
address would put every phone, every attacker and the owner in one bucket. The
real address has to come from `X-Forwarded-For`, which is also trivially forged.

Resolution: the header is honoured **only** when the connection comes from a
declared proxy (`GATEWAY_TRUSTED_PROXIES`, defaulting to loopback - the tunnel
case), and the value taken is the rightmost entry that is not itself a declared
proxy, since a client may prepend anything it likes to the left.

### Limiting, and where it had to be applied

Failed logins are counted per caller in a sliding window, and the **WebSocket's
opening frame counts against the same limit**. Limiting only the login route would
have left the socket as an unlimited oracle for guessing session tokens, beside a
door that was carefully locked.

Successes clear the count: what is being limited is guessing, not use.

The counter lives in memory rather than in `gateway.db`. Login attempts are
ephemeral and worthless after a restart, and writing each one to disk would put a
durable record of failed guesses into a database whose purpose is durable project
material. When this service ever runs as more than one process, the limiter moves
to something shared - a change with a reason rather than a precaution without one.

### What this increment does not claim

**The tunnel itself has not been run here.** Standing one up requires the owner's
Cloudflare or Tailscale account, and creating accounts or authenticating on the
owner's behalf is not something this project's assistant does. Everything up to
that line is verified: forwarded-header handling, spoofing refusal, the limiter,
the headers, and HSTS appearing only on a request that arrived over TLS. The last
step - open the tunnel, load the page on the phone, hold a conversation over
HTTPS - is the owner's, and until it is done "reachable from a phone" is a
configuration that has been prepared rather than a thing that has been observed.

### The defect the verification found, which the guard itself could not

With the trusted-proxy list deliberately set to a non-loopback address, three
requests from loopback claiming three different `X-Forwarded-For` values each got
their own rate-limit bucket. The per-caller limit was dodgeable by rotating a
header, and `gateway/exposure.py` - the module written specifically to prevent
that - was working perfectly.

**Uvicorn had already resolved the address.** `proxy_headers` defaults to on and
trusts loopback, so `request.client` was replaced with the claimed value before any
application code ran. The tell was uvicorn's own access log printing a client of
`1.1.1.1:0`, an address no socket came from. Every unit test passed, because in a
test the ASGI scope carries the peer the module expects rather than one the server
has already rewritten.

Fixed by owning the server configuration: `python -m gateway.run` starts uvicorn
with `proxy_headers=False` and an empty `forwarded_allow_ips`, so exactly one
component decides whose address to believe. A flag in a README that somebody has
to remember would have been the same defect with extra steps.

Re-run afterwards, the identical rotation put all three attempts in one bucket and
the third was refused; the legitimate tunnel case still distinguishes two phones
behind the same loopback proxy.

A strict `script-src` content-security policy was also considered and not adopted:
the client is deliberately one file with its script and style inline (no build
step, no external requests), so any such policy would have to carry
`'unsafe-inline'` and would assert protection it does not provide. Splitting the
page is the honest way to earn it, and is worth revisiting if the page grows.

## 26. Voice, and the two things it is honest about (2026-08-18)

G6 completes the Gateway increments with addendum 16 §9: voice as a primary
interface - natural speech, spoken replies, interruption, a visible transcript,
text when wanted, and switching between the two without losing context.

### Why the browser's own speech

Recognition and synthesis are the Web Speech API rather than a server-side speech
provider. No new dependency, no API key, no second bill, and no audio for this
service to hold - on the first day of a feature §9 itself expects to be rebuilt
once it has been used in anger. And because the *transcript* is what reaches the
model, replacing this later changes one file and nothing else: no schema, no
protocol, no server code.

The client's "one file, no build step, no external requests" property survived,
and a test re-checks it against precisely the feature most likely to have broken
it.

### The disclosure

**In Chrome, speech recognition uploads audio to Google's servers; in Safari, to
Apple's.** Speaking is local. For a project whose purpose is controlling what
leaves, that cannot be an implementation detail - it is in the README, in the
implementation comment, and asserted by a test that fails if the disclosure is
removed from the page.

### Barge-in is by tap, not by voice

Recognition left running while the phone speaker plays a reply transcribes the
reply, and the assistant interrupts itself forever. Open-mic interruption needs
echo cancellation against the synthesised audio, which is real work and is not
built.

So listening pauses while speaking, and Stop - or the microphone button, or
typing - cuts the reply off instantly. **The user can always interrupt; the
microphone cannot.** §9 lists "user barge-in while AI is speaking", and this meets
the user-facing half of it while saying plainly which half is missing rather than
claiming the feature entire.

### What verification could and could not reach

The Browser pane blocks microphone capture, so **speech recognition itself was
never exercised here** - that is the owner's test, on the phone, through the
tunnel. What was verified in a real browser: the heard-sentence path end to end by
calling the same handler the recognition event calls (transcript became a turn,
the model answered, the reply was spoken); synthesis genuinely starting; Stop and
typing each cutting speech off mid-sentence; and the permission-refused path
switching voice off and saying so in the transcript.

That last one was real rather than simulated: the pane denied the microphone, the
error handler ran, and the page recovered exactly as designed.

**One defect found by looking.** After a reply finished, the status line kept
reading "speaking - tap Stop to interrupt" whenever listening could not resume.
The assistant was not speaking; the line was believed; and a status line that
describes something the system is not doing is worse than no status line. It now
says what is actually true, including when voice is simply off.

## 27. Barge-in by voice, superseding §26's limitation (2026-08-18)

Addendum 16 §9 lists "user barge-in while AI is speaking". G6 delivered the
user-facing half of that and said plainly which half was missing: interruption by
tap, not by voice, because a microphone that hears the phone speaker transcribes
the reply and the assistant interrupts itself forever. **That limitation is now
removed at the owner's request, and §26 is superseded on this point only.**

### Why recognition could not simply be left running

`SpeechRecognition` cannot be handed a `MediaStream`. Its capture is opened by the
browser, cannot be configured, and will keep hearing the speaker no matter what
the page does. So the fix is not a better recognition setting - it is to stop
using recognition as the trigger at all.

### What the trigger actually is

A second capture, opened through `getUserMedia` with `echoCancellation: true` and
watched for energy alone. The browser subtracts its own rendered audio from that
stream, so what survives during a reply is residual echo and room noise.

Three properties make it usable rather than merely plausible:

**The threshold is measured, not chosen.** For the first 350 ms of every utterance
the loudest residual is observed, and the trigger is set at three times it. Echo
cancellation is uneven across phones and browsers; a fixed threshold would be deaf
on one device and jumpy on the next. Verified against synthetic levels: a device
leaking 0.05 arms at 0.15 and one leaking 0.20 arms at 0.60, and neither fires on
its own echo held for three seconds.

**Energy must sustain for 200 ms**, so a door or a cough does not cut a reply off.
A single loud sample followed by quiet does not fire.

**A transcript filter runs independently of the trigger.** A phrase arriving while
speaking that largely repeats what is being spoken is the speaker, not the user,
and is dropped before it can be sent. This guards the send path even where echo
cancellation is poor and the trigger never fired. Short phrases must match
entirely, so "stop" is not swallowed merely because the reply contained it.

Interruption is synchronous - `synth.cancel()` in the same tick the trigger fires
- so the latency the user feels is the sustain window and nothing after it.

### What it costs, and the case it still gets wrong

A single word that also appears in the reply - "questions", while the assistant is
saying the word - is treated as echo and dropped, on a device where the trigger
never armed. In the normal path this cannot bite: the trigger fires, the reply is
cancelled, and the spoken text is cleared before the user's words arrive. It is
recorded because it is real rather than because it is likely.

### The fallback is kept, and declared

Without a microphone stream there is no trigger, and G6's behaviour is what
remains: recognition pauses while speaking, Stop interrupts. The page says so **the
first time the assistant speaks**, not when voice is switched on - at switch-on the
message is either premature or plainly wrong, since a browser that refuses the
microphone outright takes recognition down with it, and "barge-in is unavailable"
arriving beside "voice is off" describes a feature of something that is not
running. Found by watching the browser pane refuse a microphone, which is the
only reason that ordering was ever exercised.

### What verification could not reach

The browser pane blocks microphone capture, so **no audio has been through this
path**. What was verified is every decision behind it, driven directly: the
calibration window, the adaptive threshold on two simulated devices, the sustain
requirement against a transient, the floor in a silent room, the echo filter in
both directions, and the two speaking modes taking different paths. Whether real
echo cancellation on a real phone leaves a residual this scheme separates cleanly
is the owner's test, and it is the one that matters.

## 28. Fault tolerance: the COO watcher and the incident record (2026-08-18)

The **Fault Tolerance and Organizational Resilience Framework** (supplied
2026-08-18) states its rule in two lines: *NO CRITICAL FAILURE GOES UNNOTICED, NO
NOTICED FAILURE GOES OWNERLESS.* Its §18 requires a review before implementation
and an explicit disposition.

**Disposition: ACCEPT WITH MODIFICATIONS.** The document is **addendum 19**, held
privately with addenda 5, 11 and 15 (owner decision, 2026-08-18): it is
organizational in kind - duty of care, who is responsible for noticing whom, how a
failure acquires an owner - which is the material `PUBLIC_PRIVATE_BOUNDARY.md`
keeps out of this repository. The disposition and everything built from it are
recorded here, because technical consequences stay public even where the governing
document does not. A reference you cannot follow means the document is private,
not missing - see `GOVERNANCE.md`.

### What was already built, and is not owed to this framework

More of §§6-8 existed than the document assumes: heartbeats with a *measured*
staleness threshold (45s, raised from 10s after slow model calls were mistaken
for crashes); §7's central demand - telling intentional dormancy from failure -
already structural in the two-axis lifecycle; the Controller already heartbeating
and already covered by COO's health scan; `docs/organization.yaml` already
declaring `reports_to` for every role; and a lifecycle event catalogue with
expected responses and observables.

### The hole it found

**Nothing watched the COO.** It is spawned once at startup, is deliberately not in
`BASELINE_POPULATION`, and the health evaluation that notices every *other*
agent's silence is a function inside it. If it died: crashed agents stayed marked
`running` forever, the baseline stopped being enforced, and nothing reported any
of it. That is §5 exactly, one level below where the framework expects the
problem.

### What was built

- **The Controller watches the COO** (`Controller.watch_coo`). Detection,
  diagnosis, recovery, and closure when the capability returns. The Controller is
  COO's manager *and* the sole lifecycle executor, so detection and authority land
  on the same entity and no new authority was invented.
- **`backend/watch.py`** holds the relationships in one place (§3), because §16
  forbids all-to-all monitoring and a map that emerges from whichever loop scans
  whichever table is not a map.
- **An incident record** (`incidents`) with the fields that have writers, and two
  writers from the start: the Controller for the COO, the COO for the workforce.
  Detection now produces a durable record rather than only a state change on a
  registry row.
- **Escalation and a recovery budget** (§11, §13). More than three failures inside
  ten minutes and the Controller stops respawning and escalates to a human owner,
  stating the lost capability. Counted from the durable record, so a loop that
  survives a restart is still caught.
- **The split-brain fix, first.** `bootstrap_coo` used to spawn unconditionally;
  an unclean server death leaves the COO subprocess alive, so a restart produced
  two live processes under one permanent identity. It now goes through
  `respawn_coo`, which refuses when a live COO is heartbeating, and
  `reconcile_on_start` reports what it found (§10).

### The modifications, and what stays deferred

1. Detection and diagnosis follow relationships; **lifecycle recovery remains the
   Controller's exclusive act** (addendum 11 §15). No manager restarts anything
   directly.
2. **The top of the hierarchy is watched but not recoverable from inside.** COO
   detects the Controller's silence; nothing can restart the server from within
   it, and `watch.RECOVERY_OWNER` names the human rather than inventing an
   in-process watcher that would die with what it watches.
3. **The watch loop is asymmetric on purpose.** COO watches the Controller and the
   Controller watches COO, which is the circular relationship §18 asks about. It
   is safe only because exactly one direction carries recovery authority - two
   watchers that could each restart the other would thrash. A test pins that.
4. The incident record carries **fields with writers**, not §14's fourteen.
5. Fault scenarios enter the existing lifecycle catalogue **one event at a time**;
   four are declared now, and `incidents.*` metrics exist so a scenario can assert
   on them rather than merely run.
6. Deferred with no objection, as §17 asks: leases, leader election, hot/warm
   standby, back-pressure limits. Nothing here has evidence of needing them.

### The defect this increment created and then found

The first version of the watch had no notion of a spawn in flight. The poll loop's
first tick runs microseconds after `bootstrap_coo`; it found no registry row for a
process that had existed for less than a millisecond, declared the COO missing,
and started another - **the duplicate-executive hazard this watch exists to
prevent, caused by the watch.** The incident record shows it plainly: a row filed
in the same second as bootstrap, symptom "COO has no registry row".

Two things made it worse than a simple bug. The incident *dedup* guarded the row
and not the spawn, so a persistent condition could respawn on every pass. And the
unit test written alongside it - "a COO that never registered is noticed too" -
asserted the broken behaviour was correct, because it never distinguished a COO
that had never registered from one that had not registered **yet**.

`agents/coo.py` had solved this exact problem for every agent it spawns
(`SPAWN_IN_FLIGHT_WINDOW_SECONDS`). The precedent existed and was not applied.

Fixed by teaching the watch what a spawn in flight is, from two sources - this
process's own memory and the registry's `spawned_at`, so a COO another process
started is also given time - and by moving the guard into `respawn_coo`, because a
guard in the caller is a guard the next caller does not have.

### Verified

1246 passed. Against a real server, on a sandboxed database:

- **Startup files no incident.** The race is closed: zero incidents, one COO.
- **A real kill is detected, diagnosed, recovered and closed.** Killing the live
  COO produced: `COO heartbeat is 45.2s old, past the 45.0s threshold` ->
  `process claims to be running but has stopped signalling; treating as crashed`
  -> `respawned COO` -> `heartbeat resumed (1.0s old)`, status recovered, one COO
  running under the same permanent identity with a new pid.

A measurement correction worth recording: an early reading of "six COO processes"
was wrong. `.venv/Scripts/python.exe` is a launcher that re-executes, so **every**
agent appears as a parent/child pair, and a `Get-CimInstance` filter on the
command line also matches the shell command doing the filtering. The duplicate
spawn is evidenced by the incident record and the code path, not by that count.

The escalation path is covered by tests rather than by a live run: reaching it
takes four failures at 45 seconds apiece, and the wall-clock cost buys nothing the
unit tests do not already pin.

## 29. Faults that can actually be injected (2026-08-18)

The lifecycle catalogue has carried an `injectable` flag since it was written -
"whether a scenario can cause this on demand in a live run" - and for thirty-six
events the answer was yes in the catalogue and no in fact. The fault-tolerance
work made that worse: four executive-failure events were declared injectable, so
the machinery that notices a dead COO had no way to be exercised by the machinery
meant to prove it works. The Fault Tolerance Framework §15 is explicit that the
purpose is "not merely to prove that processes restart" but to prove the
organization notices, assigns responsibility, recovers and learns.

### Three actions, because three are real

`simulation/faults.py` implements **kill** (abrupt termination, taskkill /F
rather than a signal the process could handle cleanly - a clean exit is the one
thing this fault must not cause), **stop** (retirement through the ordinary path,
which exists as the control case: a suite that only ever kills cannot show that a
watcher tells a decision apart from a failure), and **lock_database** (an
exclusive write lock, §15's "database temporarily unavailable" and the closest
thing this architecture has to a network partition, since SQLite is the only
coordination channel).

Named as absent rather than left to be assumed: hanging a process needs a suspend
primitive Windows does not offer without a debugger or a third dependency;
network partition has no network to partition; simultaneous multi-failure is
composition, which a schedule already expresses.

Targets are named by identity and resolved through `agent_registry`, so a fault
that cannot find its target says so rather than killing something else. Faults are
parsed at scenario load rather than at the moment they fire, because a fault that
turns out to be unspellable at second 40 of a five-minute run has wasted the run.

### Two defects the first fault scenario found

**The harness could not run any scenario that changed the population.** Readiness
was computed from this process's `BASELINE_POPULATION` defaults, so a scenario
staffing judgment at zero waited sixty seconds for agents nobody had asked for and
failed a run that had started correctly. Every scenario until then used the
default, so the harness had never been asked the question.

**A property that passed without measuring anything.** `population.respawns`
counts completed spawn *directives*, and a COO recovery deliberately bypasses the
queue - so it read 0 through a run that had killed and replaced an executive. The
assertion now sits on `incidents.total`, where a watch that kept respawning would
file a second incident and a third.

### Verified

`executive_failure` run against a live organization: the fault fired at +20s
(`killed coo-1 (pid 35116)`), and all six properties passed - one incident
detected, one recovery, no escalation, exactly one detection rather than a loop,
the workforce undisturbed, and nothing left believing it had crashed. Clean
shutdown, no orphans.

## 30. The architecture checkpoint, against what is built (2026-08-18)

Addendum 20 names itself "the checkpoint baseline for subsequent gap analysis
against the independently built simulation-engine implementation" and asks the
comparison to "explicitly identify: keep, modify, add, and remove decisions". The
Manifesto's §17 requires a disposition. Both are below.

**Disposition: ACCEPT WITH MODIFICATIONS.** The architecture is right about where
this system is thin - there is no historical engine, no live engine, no reference
engine, no risk engine, and no strategy or model store - and right that the way in
is a shared canonical contract rather than four independent ingest paths. Two
things are modified: what "add" means for the parts that already exist under other
names, and the order, because the checkpoint's own §5 (Foundation First) argues
against building five engines in parallel.

### KEEP - built, and the checkpoint describes it accurately

| Checkpoint | Where it already lives |
|---|---|
| §12's continuous baseline simulation, state inherited between periods, measurable certification gates | `simulation/harness.py`, `simulation/world.py`, `simulation/certification.py` |
| §16's "simulation uses normal organizational interfaces" | The harness starts the real server and lets the real Controller spawn real processes; it stubs nothing |
| §10's ground truth the agents are not told | `providers/market_data.py` holds the anomaly it injects; `simulation/personnel.py` holds true competence |
| §6's sampling-interval model | `simulation/cadences.py` is exactly this: 21 data classes with clock archetypes, publication lag, and a lookahead guard. `docs/MARKET_DATA_TAXONOMY.md` is its reasoning |
| §9's opportunity injection | `SyntheticMarketDataProvider(seed, anomalies)` injects targeted skews per security |
| §16's "every important capability should have simulation evidence appropriate to its risk" | Scenario properties, and now fault injection (§29) |

**The sampling-interval work is the clearest case of the checkpoint asking for
something already present.** §6's enumeration of horizons and its rule that each
data type maps to appropriate intervals is `cadences.py`'s existing taxonomy, with
one difference worth keeping: cadences carries *publication lag* as well as
frequency, which §6 does not mention and which is what makes a lookahead guard
possible.

### MODIFY - the checkpoint's framing needs adjusting against reality

1. **"Monte Carlo" is not what the current generator does, and that is fine for
   now.** §2A says initial synthetic generation "will use Monte Carlo methods".
   `providers/market_data.py` is deterministic-per-seed arithmetic over a static
   surface, which is the right shape for a detector fixture and the wrong shape
   for distributional training. Modification: Monte Carlo arrives with Stage 1
   training (§11), not as a rewrite of the provider that currently makes the
   detection pipeline testable.

2. **The Knowledge Store already exists in part, and §4's description would
   overwrite it.** `knowledge_records` holds lessons and unresolved questions with
   real producers and a real consumer; `intelligence_artifacts` holds detection
   lenses with a lifecycle. §4 describes the store as "validated lessons, patterns,
   relationships, and explanatory knowledge" - the same organ. Modification: extend
   these, do not introduce a parallel store.

3. **Reference data is not absent, it is thin.** `security_universe` is a symbol
   list with versioning. §2D wants issuers, identifiers, exchanges, sectors,
   calendars, option specifications and corporate actions. Modification: this is a
   widening of an existing table's remit, and the *first* real question is
   identifier mapping (§3's "Jarvis-owned internal IDs mapped to external
   identifiers"), because every later engine keys off it.

### ADD - genuinely absent

- **Historical Market Data Engine** (§2B) and **Live Market Data Engine** (§2C).
  Nothing ingests anything real today. Both are the checkpoint's largest additions.
- **Risk Engine** (§2E), and its rule that "no opportunity should ultimately exist
  without an attached risk assessment". Nothing computes risk at all; `analysis_results`
  carries confidence and uncertainty, which is not the same claim.
- **Strategy Store and Model Store** (§4). Neither exists, and the Data → Knowledge
  → Strategy flow has no third stage.
- **The canonical event contract** (§3). Today the only producer is the synthetic
  provider and the only consumers are Explorer and Speculator, so the contract is
  implicit in a function signature. It has to become explicit before a second
  producer exists, not after - which is precisely §5's Foundation First.
- **Scenario taxonomy** (§8). Five scenarios exist against a list of fourteen
  environment classes.

### REMOVE - nothing

Nothing in the checkpoint asks for the removal of anything built, and nothing
built contradicts it.

### The modification that matters most: order

§5 says stabilize shared contracts before implementation, and §13 lists four
engine specifications as parallel workstreams. Taken literally that builds four
ingest paths against a contract that does not exist yet, which is the duplication
Foundation First exists to prevent.

**The order this project will follow, unless the owner directs otherwise:** the
canonical event contract and identifier mapping first, because every engine keys
off both; then one real ingest path end to end (historical, since it is replayable
and needs no live credentials) to prove the contract against data the synthetic
provider did not shape; then the remaining engines, each measured against the same
contract. Risk last of the engines, because a risk assessment attached to an
opportunity nothing yet produces from real data would be scaffolding.

Recorded as Scoreboard items rather than as a plan here, so the sequence is
visible where work is chosen from.

## 31. Iterative excellence, encoded rather than promised (2026-08-18)

An owner directive supplied in conversation: explore broadly, treat the first
coherent solution as raw material, refine where refinement matters, stop at
diminishing returns. Held privately with the Manifesto as
`governance/directive_iterative_excellence_2026-08-18.md`; what was built from it
is public and is here.

**Disposition: ACCEPT WITH MODIFICATIONS.**

### The requirement that ruled out the easy implementation

Its §10 says the principle must not be implemented "solely as a Claude prompt or a
creative-agent behavior" — it should be organizational, so agents inherit it.

A sentence in the Gateway system prompt would have satisfied the principle and
failed the directive. So the budget lives in `backend/iteration.py` and is
surfaced through `describe_agent`, the mechanism the UQI already uses to answer an
agent's questions about itself. An agent asked what standard it works to can now
state one, and a test asserts that every role which exists has a declared budget
rather than falling silently to a default.

The Gateway assistant gets the stance too: conversational work gets one good
answer, because latency is part of the quality of a spoken reply, while design and
analysis through the same interface do not inherit that brevity.

### Modification 1: the numbers are conventions, and say so

The budgets are the directive's own ordering made concrete — conversational under
operational under analytical under architectural under high-risk. Nothing has
measured the quality gain from a second analysis pass in this system.

`TIMING_CONSTANTS.md` exists because this project separates measured constants
from assumed ones, so `budget_for()` returns `measured: False` and the module says
plainly that these are conventions. §8's stopping rule cannot be *enforced* until
somebody measures what a pass is worth; until then it is a standard people can be
held to rather than a threshold a machine can check.

### Modification 2: nothing was made to iterate whose iteration costs money

§5 assigns analytical work "multiple evaluation and challenge passes". Analysis
performs one deep model call per report today; giving it three would multiply
model spend per cycle and change what running the pipeline costs.

That is a decision with a price, not a constant to be edited — so it is a
Scoreboard item rather than something smuggled in behind a policy module. What
this increment does is make the standard stated, inheritable and queryable, so
adopting it later is honouring a declared standard rather than inventing one.

### What it changes about this project's own practice

The session that received the directive had already been working this way in one
respect — every increment carries what was rejected and why — and not in another:
the first coherent implementation has usually been the delivered one, with
refinement driven by defects found in verification rather than by a deliberate
second pass.

The honest reading is that §2 raises the standard for architectural work
specifically, and that where it will show is in proposals arriving with their
discarded alternatives attached, rather than in more polish on the accepted one.

### A recurrence that proves the directive's §9

Writing this section, a shell command carrying backticks was substituted by bash
and produced a mangled document — **the second time in one session**, after the
first was noticed, fixed, and described to the owner as a lesson.

That is exactly what the Manifesto's §7 warns about: the first occurrence was
treated as a defect to repair rather than as evidence about how the work is done,
so nothing changed and it recurred within the hour. The lesson is now written
where it can be read again rather than remembered: **file content goes through the
file tools, never through a shell string** — the shell is for running things, and
any content containing backticks, `$`, or heredoc terminators will be transformed
in transit.

## 32. The Historical Market Data Engine, and the vendor wall it met (2026-08-18)

Scoreboard #4, addendum 20 §2B. The first real ingest path, chosen before Live
because it is replayable, needs no credentials, and proves the canonical contract
against data the synthetic provider did not shape.

### Files are the engine; the network is an errand

The durable artifact is the file plus the rows ingested from it, and a fetch is
merely one way a file comes to exist. Replay — the engine's defining obligation —
requires a held corpus, and holding it is what keeps the engine whole when the
vendor is down. The same isolation argument the Gateway was built under, one layer
down.

With the engine came the Data Store (§4) that PR #19 deliberately deferred:
`backend/observations.py`, storing canonical observations with provenance as
CHECK-constrained columns rather than a blob, so a row cannot lose its origin in a
migration. `(entity, class, moment, origin, source)` is unique — re-ingest
converges — while the same fact from two *sources* is deliberately kept twice,
because two vendors disagreeing about a close is information.

### The vendor wall, met on first live use

Stooq was chosen as the keyless source and turned out, on the first real fetch, to
gate programmatic clients behind a JavaScript proof-of-work wall — a 404 to
`requests`, a challenge page to curl. **This project does not automate around
anti-bot controls.** The fetcher now names the wall and the legitimate path (a
person downloads in a browser; `ingest_file` takes it from there), and FRED — 
genuinely public, keyless, decades deep — became the adapter that works
unattended: `SP500` → `index_price`, `DGS10`/`DGS2` → `government_yield`, all
cadences the taxonomy already carried.

Two vendors in the first hour, one of them hostile to automation, is the §1
vendor-independence argument arriving as experience rather than principle.

### Disclosures, so they are read rather than discovered

- FRED series are registered through `ensure_security`, so `SP500` is an entity
  of type "security", which it is not. Widening entity types belongs to the
  Reference Data Engine (Scoreboard #5) and its schema-migration question; the
  ingest comment carries the same disclosure.
- Daily observations are stamped at 21:00 UTC — the EDT close. In winter that is
  an hour late, which is conservative in the only direction a lookahead guard can
  afford.
- The `government_yield` cadence declares zero publication lag; H.15's actual
  release schedule has not been measured. If someone measures it, the fix belongs
  in `cadences.py` and every stored `knowable_at` derived from it is already
  materialized — a re-ingest would be needed. Known cost, taken knowingly.

### Verified

1305 passed (was 1285). Live, against real data: 18,653 observations ingested
(S&P 500 2016–2026, DGS10 1962–2026), re-ingest against the live feed converged
(0 kept, 16,141 already held), and the lookahead guard held on the Lehman week —
standing at midday 2008-09-16, the 15th's flight-to-safety plunge (3.74 → 3.47)
is visible and the 16th's close is not. Scratch database, removed afterwards; the
real one untouched.

## 33. The knowledge store's missing mechanism was succession (2026-08-18)

Scoreboard #11 asked for the knowledge store to be extended — models, assumptions
and transformations as record kinds, plus the expiry conditions that make a lens
conditionally valid. A survey of what exists (run as a delegated inventory,
verified before use) showed the framing was two days stale in both directions:

**More exists than the gap analysis's scorecard says.** Expiry is built and live —
both arms: performance (grades joined through `lens_artifact_id`, thin-evidence
guard, staleness on mean score or worth-the-compute rate) and regime (bind a
baseline, detect drift, stale on divergence). The grades→lens-quality loop the
gap analysis said "reaches nothing" has reached `mark_artifact_stale` since
2026-08-16. Both detection thresholds already live in `intelligence_artifacts`
and the agents resolve them from the store each cycle, config as seed only.

**And the cycle is half a cycle.** Stale → nothing. `get_active_artifact` returns
None for a stale lens, Explorer falls back to the hardcoded seed — deliberately,
and the fallback is right — but nothing could ever *renew* the lens: the two
functions that would (`record_intelligence_artifact`, `supersede_artifact`) had
zero production callers. Expiry without succession demotes the organization to
its config constants one staleness at a time, permanently, with attribution
(`lens_artifact_id`) going dark for the whole seeded era.

### What was built: propose → adjudicate → adopt

- `propose_artifact_revision` — a new version of an existing name, status
  `proposed`, rationale mandatory ("a revision without a rationale is a magic
  number changing"), validity conditions carried forward (a revision proposes a
  new value, not new validity semantics), one open proposal per name.
- `adopt_artifact_revision` — proposed → active; every prior active or stale
  version → superseded, linked forward via `superseded_by`. From the next agent
  cycle the new value is in force: no restart, no config edit.
- `reject_artifact_revision` — kept, not deleted, with the reason appended: a
  rejected proposal and its reason are evidence.
- Admin routes for all three plus the proposal list on `/admin/intelligence` —
  **the Trainer's seat, held by a human**. Addendum 13's Trainer would propose
  from evidence; until Phase D exists, the operator reads `lens_performance` and
  `staleness_reason` on the same panel and proposes the correction. What matters
  is that the act is recorded — proposer, rationale, adjudication — so a Trainer
  inherits a recorded practice rather than a blank.

Also wired: `raise_corrective_actions` into the live COO cycle. Governance
computed corrective items on every panel request and persisted them never — the
writer had no production caller, so "corrective work becomes ordinary tasks" was
true only in tests. `knowledge_exists` makes the call idempotent per cause.

### Declined, and why

- **New record kinds (models, assumptions, transformations).** No producers. A
  `record_kind` nothing writes is the empty schema this project refuses, and the
  succession chain — value, rationale, evidence, `superseded_by` links,
  adjudication — *is* the Manifesto §12 transformation record: what changed, why,
  and what evidence caused it, without a parallel store.
- **Automatic proposal from performance data.** That is the Trainer's judgment
  (addendum 13), explicitly Phase D. A statistical auto-proposer would be an
  unvalidated learner wired directly into the organization's most consequential
  constants.
- **Widening the remaining constants** (`NEIGHBORHOOD_*`, `PEER_MIN_COOCCURRING`)
  into artifacts. Each needs its own attribution path before its performance is
  measurable, and an artifact whose performance cannot be measured can expire
  only by opinion.

### Known cost, restated

During a stale-lens window, reports carry no `lens_artifact_id`, so the seeded
era is invisible to `lens_performance`. With succession the window is bounded by
the operator's response time rather than infinite, which is why the fallback
behaviour was left untouched.

### Verified

1321 passed (was 1305). Live, against a running organization (sandboxed database,
Explorer cycling, Analysis and Speculator staffed at zero): the seeded lens v1
(2.0) marked stale — `get_active_artifact` returned None, the seed-fallback era
beginning — then through the real admin routes: propose v2 (2.5, with rationale
and evidence), a second open proposal refused with the first one's id, the
proposal visible on `/admin/intelligence`, adopt, and v2 active organization-wide
with the chain reading `v2 active / v1 superseded-by-9`. Explorer heartbeating
throughout — the new value in force with no restart.

### The wiring's first production run filed three real records

The verification script predicted zero corrective actions on a clean sandbox and
got three — the compliance rules firing on the startup window, where early COO
directives complete before evaluation machinery has anything to evaluate
("1 of 2 completions carry no evaluation"; "too few completions to attribute").
They are idempotent, few, and now on the record, which is the point of the
wiring; whether startup-transient states deserve a grace window before compliance
counts them is a tuning question that now has evidence behind it instead of
nothing. Left as filed rather than suppressed: a rule that fires on day one is
examined, not silenced.

### Division of labour, per the tiering directive

The codebase survey and the spec-driven implementation ran as delegated subagent
work on a lesser model; the design, the spec, the review of both results, the
live verification and this record are the top model's. The survey's one wrong
detail (it claimed the succession functions had no callers *including tests*;
they had test callers, no production callers) was caught in review — which is
what the review step is for.

## 34. Reference data began with two foundation repairs (2026-08-18)

Scoreboard #5 said "widen security_universe into the Reference Data Engine." The
survey (delegated, verified before use) showed that sentence resting on a false
premise and standing over two structural defects, so the increment is smaller in
glamour and larger in foundation than the item asked for.

### The false premise

**`security_universe` had zero production consumers.** It is created, seeded, and
versioned — and Explorer scans `discovery_config.PEER_GROUP_SECURITIES`, a
hardcoded parallel list, instead. Two universes, one decorative. "Widening" a
table nothing reads would have been enlarging the decoration.

The repair chosen is authority-by-assertion rather than rewiring: every universe
member gets an entity at seed time, and a containment test pins
`PEER_GROUP_SECURITIES ⊆ security_universe` — the universe is the authoritative
list, the peer groups are a *grouping* of it, and a scanned symbol outside the
universe now fails a test instead of drifting silently. Rewiring Explorer to read
the universe directly is declined here: co-occurrence semantics live in the
groups, and flattening them is peer-group design work, not reference-data work.

### The two structural defects

**Modular schemas had no modular migrations.** `apply_additive_migrations` parsed
only `fi_db.SCHEMA`, so the moment table ownership split across modules (#19's
identifiers, #20's observations), those tables silently lost migration support
entirely — a column added to their DDL would exist on fresh databases and be
missing on every deployed one. The walker now sees every module's DDL. This
defect had bitten nobody yet only because both modules are days old.

**A CHECK constraint on a growing vocabulary.** `entities.entity_type` carried a
CHECK hand-duplicated from `ENTITY_TYPES`, unreachable by any migration (SQLite
cannot widen a CHECK), so every future entity type would have required a table
rebuild. The CHECK is gone — one detect-and-rebuild migration for databases
created in the intervening days — and validation lives in `create_entity`, where
a refusal can name the valid types. `observations.origin` keeps its CHECK
deliberately: that vocabulary is fixed at three forever. The difference is not
taste; it is whether the set is closed.

### What was then buildable honestly

- **`series` entity type**, and the end of an admitted misuse: `ingest_fred_series`
  had been minting `SP500` and `DGS10` as `security` and saying so in its
  docstring. `ensure_entity` generalizes `ensure_security`; FRED series are now
  what they are. Rows created under the old type in scratch databases keep their
  recorded type — identity rows record what was done, not what should have been.
- **Market holidays** — the first reference-data table with a real consumer.
  `simulation/clock.py` had stayed calendar-free deliberately ("a holiday
  calendar is a lookup table that changes nothing structurally") and the survey
  found exactly one seam where session enforcement already reads the database:
  `market_is_open`. US holidays 2025–2027 seeded as public facts; equity and bond
  sessions consult the calendar, futures and fx do not — they trade through most
  US holidays, and a session with no calendar is itself information. A Tuesday
  July 4th passes the weekday-and-hours test and the market is closed anyway.

### Declined, with reasons

Issuers, sectors, and option contract specifications — confirmed absent from the
codebase in every form, meaning no producer and no consumer. They arrive with the
engines that need them (live options data for contract specs; any fundamental
ingest for issuers), not as empty tables built to make the Reference Data Engine
look finished.

### The defect the review caught in the delegated work

The rebuild migration was correct on the clean path and had a crash window:
`Database.execute` commits per statement, so rename-recreate-copy-drop is four
transactions, and a death between any two left the holding pen orphaned while the
guard under it saw a fresh CHECK-less table and skipped — stranding every row out
of view. Recovery now runs before detection (`INSERT OR IGNORE` over the primary
key makes the copy idempotent), so the sequence resumes from any crash point, and
a test constructs the exact post-crash state and asserts the stranded row comes
back. Blast radius today was near zero — the real database has no `entities`
table yet — but this migration is the pattern every future rebuild will copy,
which is why the window mattered more than its odds.

### Verified

1329 passed (was 1321). The delegated implementation verified the rebuild against
a hand-built old-shape database (old CHECK genuinely refused a 'series' insert;
after `init_schema` the row survived, 'series' succeeded, second run a no-op).
The containment test did its job on first contact: peer groups spanned SYN1–10
against a universe seeded SYN1–4, and the universe was reconciled upward rather
than the test weakened. Division of labour as before: survey and implementation
delegated to a lesser model; design, spec, review — which caught the crash
window — and this record by the top model.

## 35. The Risk Engine's first slice: the rule with teeth (2026-08-18)

Scoreboard #6, addendum 20 §2E. The section's one enforceable sentence — *"No
opportunity/recommendation should ultimately exist without an attached risk
assessment"* — is now true by machinery rather than by intention, and the rest of
the section waits for the things it describes to exist.

### Who assesses, and why it is not an agent

Risk is assessed in the COO cycle, not by Analysis and not by a new agent role.
The reasoning is the organization's own, twice over: *the producer of an
opportunity must not be the judge of its risk* — the same house rule (addendum 11
§8) that put source reliability and lens health in COO's cycle rather than in the
agents whose work they judge. And the Manifesto's §8: new organizational machinery
only when it solves a real problem better than a simpler mechanism. A risk *agent*
would have needed a charter, a watcher, spawn machinery and an org-model entry, to
run the same deterministic functions on the same cycle.

### Four factors, and the refusal of a score

Each factor reads something the organization actually records, carries the
numbers it read, and returns a level it can defend: **regime instability**
(dispersion relative to mean, from `market_regime`), **lens trust** (a detection
fired on a seed-era fallback constant is high risk by construction; an unproven
or since-staled lens is elevated), **corroboration** (a cross-check that was
answered, silent, or never answered — silence is not corroboration), and
**historical stress** (the 30-day move in the deepest series held, DGS10 back to
1962 — with an honest `no_evidence` when no corpus is held).

**The overall level is the worst factor.** A weighted score over four judgments
would be arithmetic wearing authority it has not earned; a chain is its weakest
link, and pretending otherwise requires evidence nobody has. Thresholds are
conventions and every assessment says so (`measured: False`) — the same
disclosure discipline as the iteration budgets and `TIMING_CONSTANTS.md`.

### Enforcement fell out of existing machinery

"Not yet assessed" is the absence of a `risk_assessments` row — the same idiom
`grades` established — so the compliance rule is one `EvaluationRule` tuple
against the generic TABLE shape, and violations flow through the corrective-
actions path wired in §33. **The ordering is the grace period**: risk assessment
runs before the compliance sweep in the same COO cycle, so a result is never
counted unassessed merely because judgment ran second.

### A layering constraint worth recording

`backend/risk.py` sits below `fi_db` in the module order — `fi_db.init_schema`
creates its table — so it must not import `fi_db`, and it re-states the
`lens_performance` join in SQL rather than importing it, with a comment saying
so. Third instance of the same lesson (canonical, identifiers, now risk): the
module that owns schema creation is an upper layer, whatever the file sizes
suggest.

### Declined, with reasons

- **Portfolio, strategy, and agent-level risk** (§2E's full breadth): nothing
  holds a portfolio or executes a strategy yet. Risk attached to things that do
  not exist is scaffolding.
- **Monte Carlo for risk** (§2E: "may be reused"): *may* is not *must*, and a
  distributional risk model over a deterministic synthetic fixture would be
  precision theatre. It arrives with the Monte Carlo generator (#8), if evidence
  wants it.
- **Re-assessment under changed conditions**: one assessment per result, UNIQUE.
  Overwriting a judgment would destroy the record of what was believed when the
  opportunity was fresh; re-assessment is a future design with its own reason.

### The rule showed teeth before it shipped

Adding the compliance rule broke three pre-existing tests whose planted "fully
processed" rows lacked assessments — the delegated implementation fixed the
*plants* to match what COO's cycle actually does, not the rule. A rule that fires
on the test suite's own idea of "done" is measuring something real.

### Verified

1358 passed (was 1329; +29 risk tests). Live, against a running organization: a
planted opportunity — unstable regime (cv 0.30), an unanswered cross-check, a
seed-era detection — was picked up by the **real COO cycle** within seconds, with
no direct call from the verification script:

    assessed by coo-1 | overall: high
      regime         high        dispersion/mean ratio 0.3000 at or above 0.25
      lens           high        fired on a fallback seed constant, no history
      corroboration  elevated    the peer never answered; silence is not corroboration
      stress         no_evidence no historical corpus held; ingest DGS10 to enable

Zero compliance findings for the risk rule after the cycle — the ordering was the
grace period — and the panel's `/admin/discovery` carries `risk_overall: high` on
the row. One spec error surfaced and adapted honestly: the cross-check outcome
vocabulary is `evidence`/`no_evidence`/`unanswered`, not the `answered` the spec
guessed; the survey had it right and the spec-writer did not re-read it.

Division of labour as established: survey and implementation delegated; design,
spec, review, live verification and the record by the top model.


---

## §36 — Analysis adopts its declared budget: the 3-pass loop (Scoreboard #14)

**Owner decision, 2026-08-19: "adopt the 3-pass budget for analysis."**

Since PR #18, `backend/iteration.py` has *declared* that analytical work carries a
3-pass budget with the stance "Reach a conclusion, then challenge it: what would
make this wrong, what evidence is missing, what alternative reading fits the same
facts. Deliver the conclusion that survived." Analysis kept running one pass — the
declaration was honest about being aspiration (`measured: False`), and the gap was
filed as Scoreboard #14 at ~3× model spend, an owner decision. The owner decided.

### The stance is now the control flow

- **Pass 1** — the existing deep analysis, unchanged.
- **Pass 2** — a challenge pass (`_run_challenge`): given the same report context
  and pass 1's conclusion, attack it — what would make the thesis wrong, what
  evidence is missing or overweighted, what alternative reading fits the same
  facts, is the confidence justified. Verdict vocabulary is closed:
  `stands | revise`. The prompt says explicitly that endorsing a sound conclusion
  is a legitimate outcome, not a failure to find something — without that
  sentence, a model told to challenge will manufacture objections, and the third
  pass becomes a quota after all.
- **Pass 3** — a revision pass (`_run_revision`), run **only** on a material
  challenge. It receives context, conclusion and challenge, and is told to
  preserve what survived and fix what was found — and that the challenge is
  input, not authority: if part of it is wrong on reflection, keep the original
  judgment and say so.

The budget is a **ceiling with §8's stopping rule inside it, not a quota**:
typical cost is 2 calls (analyze + a challenge that stands), worst case 3. The
challenge runs at 1024 max tokens — a critique needs room to name problems, not
to restate the thesis — so the marginal spend of the typical case is well under
the ~3× the scoreboard item priced.

### Refinement must not destroy the core

A challenge or revision that itself fails — malformed JSON, model error — is
logged and the pass-1 conclusion is delivered; only the primary analysis failing
fails the report. The directive's §4 (first draft as raw material, preserve the
core) applied to failure semantics: a broken *improvement step* must never turn a
sound conclusion into a failed report.

### A heartbeat before every pass

Three sequential model calls is exactly the duplicate-agent defect class this
project has already paid for twice (the 45s health threshold vs. real model
latency). `record_heartbeat` now runs immediately before **each** LLM call, not
just the first — a slow-but-alive agent mid-refinement must not be declared
crashed and respawned into a duplicate.

### What is recorded, and what it enables

`analysis_results` gains two additive columns: `passes_used INTEGER` and
`challenge_summary TEXT`. NULL on pre-adoption rows — absence is history, not
zero. This is what makes Scoreboard **#15** (measure the value of extra passes)
possible rather than aspirational: `passes_used` now sits beside the grades, so
one-pass, two-pass and three-pass conclusions are comparable by their graded
quality. The engine that measures whether the budget earns its cost can now be
built on data the organization actually holds.

The grade recorded is the **final** result's — a revision's scores stand, since
grade and analysis are one response by design; grading the superseded draft
would attach judgment to a conclusion nobody delivered.

### The override that is not an escape hatch

`FI_ANALYSIS_MAX_PASSES` (default 3, floor 1) exists for cost-bounded simulation
runs — a scenario harness driving dozens of reports through the loop should be
able to pay 1× — not for quietly unadopting the budget. The constant's comment
says so, in those words.

### Verification

**1365 passed** (was 1358; +7). The migration was proven against a **copy of the
deployed database** — both columns added by `apply_additive_migrations`,
pre-adoption rows reading NULL, the real database untouched (md5 unchanged) —
because the DDL comment sits inside the CREATE TABLE body and the additive
parser had to be read to confirm it skips `--` lines before trusting it.

Live, sandbox DB, **real model calls** — for this feature the prompts are the
design, and only a live model can show whether the challenge pass returns valid
JSON and is willing to say "stands":

```
planted report 1 (synthetic spread/equity divergence, JE-TEST01)
passes_used: 2          <- challenge verdict "stands"; §8 stopped the loop
heartbeats during work: 2   (one per pass)
confidence: 0.1
challenge: "The first-pass conclusion correctly identifies the dominant issue
  (synthetic/test identifier undermining actionability) and appropriately
  assigns low confidence given a 5-session, 2-series sample with no peer
  corroboration and no catalyst..."
archived: outcome 'analyzed' by analysis-1; grade recorded from final result
```

The stopping rule fired on its first real datum: the model endorsed a sound
low-confidence conclusion rather than manufacturing objections, and the
typical-cost prediction (2 calls, not 3) held. The pass-1 conclusion had itself
noticed the identifier was synthetic — the challenge agreed that was the
dominant issue, which is what a challenge endorsing honest work looks like.

**What was not observed live:** pass 3. A real revision requires a genuinely
flawed first conclusion, which cannot be honestly planted — forcing the model
to produce a bad analysis on purpose would verify nothing about real behaviour.
The revise path is mock-verified (different thesis delivered, revision's grades
stand, `passes_used=3`), and `passes_used` will record the first production
revision when one happens — which is precisely the data #15 waits for.

A verification-script error along the way was the machinery working: the
"missing" analyzed report had been moved to `discovery_reports_completed` by
the archive trigger, exactly as designed; the script had queried the live table.

Division of labour per the tiering directive: implementation and tests by a
lesser model against a full spec (zero deviations reported, and the review
found none — a first); design, prompts, spec, review, migration proof, live
verification and this record by the top model.

*Scoreboard #14 resolved. #15 (measure the value of the extra passes) is now
buildable on data the organization actually records.*

---

## §37 — Stage 1 training: Monte Carlo samples the configuration, the fixture renders it (Scoreboard #8)

Addendum 20 §2A says initial synthetic generation "will use Monte Carlo methods";
§30 modified that into a commitment with an order: Monte Carlo arrives **with
Stage 1 training** (§11), not as a rewrite of the deterministic provider that
makes the detection pipeline testable. This section records the arrival.

### The design decision: sample the configuration space, not the prices

The survey settled it. `SyntheticMarketDataProvider` already accepts everything
a world needs — per-security anomaly placement, height and width; regime
parameters; a seed — and every one of those knobs was already env-addressable.
So the Monte Carlo layer does not generate prices at all. It **draws worlds**:
which securities are dislocated, how strongly, where on the surface, under what
regime — and hands each drawn world to the deterministic provider to render,
through the same env inheritance every scenario already uses. §30's "not a
rewrite" position made literal: the fixture is the rendering layer.

This is also addendum 20 §9's layered composition, mapped onto what exists:
the base generator is the provider's skew/term/noise arithmetic; the scenario
modifier is the sampled regime; the opportunity injector is the sampled plant
set; the ground truth is the answer key. One new module, no duplicated
generation logic — which is §9's own stated reason for the layering.

### The answer key is the organization's own detector, run offline

The one genuinely new idea in the slice. For every security in every sampled
world — planted or not — the sampler renders the surface with the real provider
and runs the real `scan_for_anomaly` against the seed threshold, offline. Every
security therefore carries two truth bits: *planted* and *detectable by the
current lens*. Scoring against both distinguishes six outcomes:

| planted | detectable | detected | outcome |
|---|---|---|---|
| yes | — | yes | **hit** |
| yes | yes | no | **miss** — the organization failed to see what its own lens resolves |
| yes | no | no | **beyond_lens** — correct restraint; the plant is below the lens, by design |
| no | yes | yes | **artifact_detection** — sampled noise formed a real spike; the lens fired as specified |
| no | no | yes | **false_positive** — fired where the ideal detector would not; a genuine defect |
| no | — | no | **clean** |

Without the offline benchmark, a miss on a sub-threshold plant would be scored
as failure (it is the lens's limit, not the agent's), and a detection on a noise
artifact would be scored as false positive (the lens worked exactly as
specified; the question it raises belongs to the judgment gate). An organization
should not be blamed for missing what its lens cannot resolve, and should not be
credited for firing on noise. Using the org's own `scan_for_anomaly` rather than
a reimplementation is what keeps the benchmark from drifting away from the thing
it benchmarks.

Plant heights are sampled from below any honest lens's resolution (0.02 over
noise) to unmissable (0.60), and some worlds carry **zero** plants — §10's
demand that agents meet subtle opportunities, false positives and varying signal
strength, so they learn discernment rather than rote pattern matching. All
sampling ranges are conventions, labeled as such.

### Where the answer key lives

Returned to the caller; written only into the exercise summary after the runs
complete; never into the run database. `simulation/personnel.py` stated the
rule first: a table holding the answer is a table something can accidentally
read. The plants necessarily reach the agent *processes* (the provider must
render them — true today of `FORCE_ANOMALY_SECURITIES` too); the boundary is
that no detector code reads the provider's anomaly dict, and no database table
holds it.

### What was added around the sampler

- **`FI_ANOMALY_SPEC`** — JSON env giving per-security bump parameters.
  `FORCE_ANOMALY_SECURITIES` could only say *that* a security is dislocated;
  a sampled world needs to say *how much and where*. JSON rather than another
  comma micro-grammar: the payload is nested and typed.
- **`python -m simulation stage1 --worlds N --seed S`** — samples N worlds,
  runs each through the real harness (real backend, real Controller, real
  agents), scores each, writes the aggregate.
- **`anomaly_burst.yaml`** — `baseline_steady_state.yaml` referenced this
  scenario before it existed (found by the survey). It is now the deterministic
  library counterpart of a sampled world — one unmissable plant, one
  near-threshold — and grows #10 by one, with a run behind it.

### Declined, with reasons

- **Path-through-time simulation** (GBM, regime switching, evolving surfaces):
  the provider's `as_of` is accepted-but-unused today, and the detector reads
  one surface at a time. Time evolution arrives when a detector exists that
  needs it; sampled static worlds already vary everything the current detector
  can see.
- **Automatic lens retraining from scores**: the propose/adopt/reject lifecycle
  is human-gated by design (addendum 13 §14: "production behavior changes
  remain validation-gated"). Stage 1 produces the evidence; adopting it stays
  a decision. Filed as a new Scoreboard item rather than built silently.
- **A Training Agent process**: addendum 13 §2 explicitly allows one agent —
  or here, one module — to perform the loop while the responsibilities stay
  logically separable. Sampling, orchestration and scoring are separate
  functions in one file; a charter, watcher and org-model entry would be
  machinery ahead of a demonstrated need (Manifesto §8, the same reasoning
  that kept risk out of an agent).

### The measurement that changed a constant before any run was paid for

The first offline preview exposed a sampling problem *and* a lens finding at
once: with widths drawn from (0.3, 1.0), almost nothing sampled was
detectable. Measured across 300 offline worlds (472 plants): 18.2% detectable
overall — 39% at width 0.30–0.45, 35% at 0.45–0.60, 7% at 0.60–0.80, and
**0/133 at width 0.80–1.00**. The cause is structural: a wide bump raises its
own local baseline (the neighborhood mean includes the bump's shoulders), so
the peak/baseline ratio collapses as width grows. **The iv-ratio lens is blind
to wide dislocations by construction** — a real finding about the
organization's only detection lens, produced by the answer key before a single
harness run existed. Filed as a Scoreboard item.

`WIDTH_RANGE` was capped at 0.7 — bringing the detectable fraction to 32.2%,
a usable mix of hits-to-be-had and restraint-to-be-shown — and the constant's
comment carries the measurement (`measured: True`), which makes it the first
sampling range in the module to graduate from convention to measurement.

### Verification

**1373 passed** (was 1365; +8). Live, real harness, real model — with the
prediction registered before the run: seed 20260820 draws world 0 with two
detectable plants and one sub-threshold, world 1 empty, world 2 with two
sub-threshold plants, so the exercise should score 2 hits, 0 misses, 3
beyond_lens, 0 false positives.

```
world  0: hits 2 misses 0 beyond_lens 1 artifact_detections 0 false_positives 0 clean 7
world  1: hits 0 misses 0 beyond_lens 0 artifact_detections 0 false_positives 0 clean 10
world  2: hits 0 misses 0 beyond_lens 2 artifact_detections 0 false_positives 0 clean 8
aggregate: hits 2 misses 0 beyond_lens 3 false_positives 0 clean 25
detection rate: 1.000        (all three runs graceful)
```

**The prediction held exactly.** The organization found precisely what its
lens can resolve and stayed silent everywhere else — including the
deliberately empty world, which is the false-positive test passing by
producing nothing.

Cross-checked independently of the scoring code: world 0's run database holds
detector events for SYN2 (ratio 2.201) and SYN6 (2.192) only — matching the
offline answer key's ratios **to the third decimal**, which is the "same
functions, not a reimplementation" claim proven rather than asserted.

`anomaly_burst` ran live as well: 58 detector events from the unmissable SYN3
plant, the subtle SYN9 correctly below threshold, property 1/1, clean
shutdown. (`analyses 0` in a 60s window is the 3-pass loop being honest about
its cost — the saturation scenarios exist to study that, and this scenario's
property is detection.) The dangling `anomaly_burst` reference in
`baseline_steady_state.yaml` is now a true statement.

Division of labour per the tiering directive: survey and implementation by a
lesser model (implementation reported zero deviations beyond three sensible,
disclosed ones); design, spec, review, the detectability measurement, live
verification and this record by the top model.

*Scoreboard #8 resolved. Two items filed from findings: the wide-dislocation
lens blind spot (measured), and closing the training loop — Stage 1 scores
becoming evidence for `propose_artifact_revision`, with adoption staying
human-gated per addendum 13 §14.*

---

## §38 — The Strategy Store opens with a true statement; the Model Store waits for a model (Scoreboard #9)

Addendum 20 §4 names five stores. Three existed under their own or other names
(reference data, the Data Store, the knowledge organs); the Scoreboard's #9
asked for the remaining two: Strategy and Model. This section records why one
was built and one was declined-for-now — and why that split is the same
decision made twice, not one build and one omission.

### Strategy: prescriptive, versioned, and seeded with reality

§4's distinction is the load-bearing one: knowledge is descriptive ("what we
have learned"), strategy is prescriptive ("what we do"). The organization has
had the descriptive half for weeks — lenses with lifecycles, lessons with
succession. What it never had was the prescription written down: the discovery
playbook existed only as the emergent behavior of five agents' code.

`backend/strategy.py` is the fourth instance of the module-owned-schema
layering rule (canonical, identifiers, risk, now strategy): `fi_db.init_schema`
creates its table, so it imports only `backend.db` and re-states the one
`intelligence_artifacts` query it needs. Strategies carry name/version with
UNIQUE succession, a prescriptive statement, and `knowledge_refs` — the JSON
list of intelligence artifacts the strategy rests on. A strategy must say what
knowledge justifies it, or the health rule below has nothing to check.

**The store opens with a true statement.** The seeded
`baseline_discovery_playbook` is the pipeline the organization already
executes — scan through the active lens, judge before trusting, cross-check
because silence is not corroboration, file only after judgment, conclude-
challenge-revise, risk-assess before complete — reverse-documented and linked
to both seeded lenses. Not an aspiration: a record of what is. The
alternative, an empty strategies table waiting for someone to have a strategy,
would have been the scaffolding this project keeps declining.

### The rule with teeth: no active strategy on expired premises

An active strategy resting on knowledge that is no longer active is being
executed on faith. `strategy.unhealthy()` finds every such case and names
every broken premise in one finding per strategy — per cause, matching
remediation's per-rule grouping, so the adjudication is one decision rather
than a drip.

The wiring reuses the whole existing enforcement chain: findings become
`CorrectiveItem`s in the COO cycle, flow through `raise_corrective_actions`,
and land as corrective knowledge records with per-statement idempotency — no
new mechanism, the third consumer of the path #21 built. Three choices worth
recording:

- **Ordering-as-grace-period, pointed the other way.** Strategy health runs
  after `_evaluate_intelligence_health`, so a lens marked stale in this cycle
  is visible to the strategy check in the same cycle. Risk's ordering exists
  so fresh work is never punished for judgment running second; this one
  exists so stale premises are caught the cycle they stale, not one later.
- **Classified systemic, always.** A strategy governs every piece of work done
  under it; a broken premise is never attributable to one agent.
- **Assigned to the owner seat.** Re-linking, superseding, or retiring a
  strategy is an adjudication — addendum 13 §14's validation gate — not a task
  an agent may claim. The producer of work under a strategy must not be the
  one who quietly rewrites the strategy.

### No 'proposed' status for strategies

Intelligence artifacts have a proposal lifecycle because a Trainer seat
produces candidates and a human adjudicates them. Nothing produces strategy
candidates today. A `proposed` state nobody can fill would be machinery ahead
of need (Manifesto §8); supersession is the adoption act, and the record shows
who adopted what over what.

### The Model Store waits for a model

Declined-for-now, with the reasoning §30 already supplied. §30's MODIFY #2
ruled that where a store exists under another name, the move is to extend it,
not to introduce a parallel one — and the survey confirmed the fact that
decides this: `detection_lens` is the *only* artifact kind ever written.
`intelligence_artifacts` — versioned, with propose/adopt/reject succession,
staleness, and regime binding — already **is** the store for every trained
value the organization possesses.

What §4's Model Store adds beyond that is a home for trained artifacts that
are not values: serialized models, fitted parameters with training-data
provenance, content hashes, evaluation metrics. Nothing in the organization
produces such an artifact today. Stage 1 (#8) produces exercise evidence;
#18's loop-closing produces *proposals into intelligence_artifacts*; a future
fidelity-fitted generator (addendum 8 §3) would be the first genuine blob
model. The Model Store arrives with that first artifact — built against a real
payload, the way every store in this project has been — rather than as an
empty registry pretending otherwise. Same decision as the §35 risk declines
and as strategy's own missing `proposed` state: machinery arrives with its
need.

### Verification

**1382 passed** (was 1373; +9). One review finding on the delegated
implementation: `strategy.py` re-stated `SCHEMA_VERSION = 7` as a mirror of
`fi_db`'s — a constant that must be kept in sync by hand is a drift waiting to
be found the hard way. Corrected to module-owned version 1, the `risk.py`
precedent.

Live, real organization (real backend, real Controller, real COO cycle;
minimal population, no LLM calls needed), isolated run DB via the harness:

```
organization up (run strategy-health-verify-20260820T223618-85d21f)
seed strategy present: v1, refs ['iv_ratio_threshold', 'speculator_confidence_threshold']
unhealthy before: []
iv_ratio lens marked stale; waiting for the real COO cycle...
CORRECTIVE ACTION (by compliance): Strategy 'baseline_discovery_playbook' v1
  is active but rests on knowledge that is not: 'iv_ratio_threshold' (stale).
  Re-link it to current knowledge, supersede it, or retire it.
strategy corrective rows after further cycles: 1 (must stay 1)
shutdown: clean - teardown ran and no agent is left running
```

The real COO cycle — not the verification script — noticed within seconds that
the active playbook rested on stale knowledge; the finding names the strategy,
the broken premise, its actual status, and the three adjudication options; and
per-statement idempotency held across further cycles without a new mechanism.
The rule showed teeth against the seeded strategy itself, which is the point:
the first strategy the store holds is already under the same law as any future
one.

Division of labour per the tiering directive: survey and implementation by a
lesser model (one honest contradiction reported — `_intelligence(conn)` takes
no `since` — and adapted correctly); design, spec, review (one finding), live
verification and this record by the top model.

*Scoreboard #9 resolved: the Strategy Store built with real content and real
enforcement; the Model Store recorded as arriving with the first trained
artifact that is not a value.*


---

## §39 — The Day Zero lineage arrives: seven documents, one private (2026-08-22)

Seven documents supplied 2026-08-21, saved as addenda 21–27. Addendum 22
(Constitution & Governance checkpoint) is constitutional philosophy and is held
privately per the boundary rule; the public lineage is 21 and 23–27. Owner
instruction on arrival: *assimilate all of these documents and start creating
the next components — priority is the Reference Data Engine, then the
Simulation Engine.* This section is the assimilation; §40 and §41 are the two
builds.

### What the lineage is

Day Zero: the minimum viable world before operational agents begin work.
Bootstrap → Controller → schema → **Reference Data Engine** (readiness
certification) → mission data engine (**Market Data Simulation Engine** in
Pre-Alpha) → wake agents. The lineage's first operational mission is narrow by
design: put-call parity arbitrage (addendum 25 §1), and addendum 27 supplies
the library that mission is the first member of — ARB-001, with its
non-negotiable rule that a theoretical violation at mid prices is not
executable arbitrage.

### What already exists under other names — keep, no rework

- **The startup chain is the built one.** Addendum 21's "Bootstrap →
  Controller → COO → engines → wake agents" matches `backend/main.py`'s
  lifespan, Controller-as-the-server (§2 of this file, commit `a577889`), and
  COO as the operational orchestrator. Addendum 23 §1's Controller duties are
  the built Controller's duties. No conflict.
- **"Analyst" is the `analysis` role.** Addendum 23 §6 names what
  `agents/analysis.py` does — candidate investigation, thesis testing, an
  analytical conclusion. The repo keeps its role name; the addenda's noun maps
  to it. Same for "the Evaluator" (addendum 23 §7): its mechanism exists
  today as the grading chain (`grades`), Stage 1's planted-ground-truth
  scoring (`simulation/stage1.py`), and COO's compliance rules. A distinct
  Evaluator *agent* is not built and is not needed until something an
  existing mechanism cannot evaluate exists.
- **Lifecycle stays at orchestration.** Addendum 21 §8 and addendum 24 §15
  restate the interface principle this codebase already enforces: agents
  consume domain interfaces, only orchestration knows
  simulation/historical/live. The canonical Observation contract
  (`backend/canonical.py`) is that principle made structural — uniform shape,
  mandatory provenance — and predates this lineage.
- **Identifier architecture.** Addendum 24 §6–7's canonical-internal-ID rule
  ("external identifiers are mappings around the canonical ID"; "must not
  assume CUSIP exists") is `backend/identifiers.py`, built in §19 and repaired
  in §34. The Day Zero build widens it; it does not rival it.
- **Trading calendars.** Addendum 24 §10 lists them; market holidays exist
  with a real consumer (§34).
- **Constitutional principles (addendum 22).** The standing private
  constitution already carries rule-of-law, accountability, dissent and
  adaptive-confidence principles; the checkpoint adds explicit amendment
  thresholds (~90% rights-reducing, ~two-thirds rights-expanding) and the
  rights-impact test. Recorded privately with the document; nothing in code
  turns on it today.

### Genuinely absent — the two builds this lineage orders

1. **Reference Data Engine as an engine** (addendum 24, with 26 subordinate
   where they differ — 24 is the fuller, later statement of the same design).
   What exists is identity plumbing; what does not exist is the engine around
   it: the Asset Universe / Capability Set / Current Focus registries at
   asset-class level, a Security Master record per instrument, the Assets
   work-discovery table, adapter-shaped ingestion, validation, and a
   **fail-closed readiness certification** the COO consumes before dependent
   engines start. §40.
2. **Market Data Simulation Engine for the parity mission** (addendum 25).
   The existing simulation package generates IV surfaces, org-level worlds and
   Stage 1 exercises — nothing generates *option chains with executable
   bid/ask quotes*, parity-coherent pricing, controlled parity deviations with
   genuine/trap variants, or ground truth in ARB-001's executable terms. §41.

### Precedence decisions

- **Within the lineage**: 24 governs 26 (same engine, 24 fuller). Both agree
  on every load-bearing point checked; 26 uniquely carries the dependency
  chain diagram and the Explorer volatility-surface note, which is why it is
  kept rather than discarded.
- **Against addendum 20**: no conflict found. 20 §3's canonical format, §2D's
  reference-data list and §11's Stage 1 are what 21–27 elaborate. Where 25's
  simulation states duplicate 20's, 25 is the more specific and governs the
  parity mission.
- **Against addenda 11–15**: the org roles map (above); no authority boundary
  moves. Addendum 24 §3's "COO instantiates and supervises the Reference Data
  Engine" is honored with the engine as a *callable domain module* invoked
  from the server's startup orchestration — an engine, not an agent (24 §1:
  "an engine, not an autonomous organizational authority"), so no charter, no
  watcher, no spawn machinery. Same reasoning as §35's refusal of a risk
  agent.
- **Addendum 25 §2's activation rule** (engine starts only when the user
  selects RUN MODE = SIMULATION from mission control): the mission-control
  *interface* is panel work not yet built; until it exists, the engine is
  activated programmatically with `run_mode="simulation"` required in the
  mission config — the rule enforced at the engine boundary, the UI to follow.

### Declined or deferred, with reasons

- **Free/public reference sources (EDGAR, OpenFIGI, exchange directories)** —
  addendum 24 §11. The adapter pipeline is built and the seed universe flows
  through it as the first adapter, but no network source adapter ships in §40:
  the Current Focus for the Pre-Alpha mission is the synthetic universe, whose
  coverage requirement a network fetch cannot improve, and an ingest nothing
  consumes is the empty machinery this project refuses. The FRED ingest
  (`providers/historical.py`) already demonstrates the pattern against a real
  free source. EDGAR/OpenFIGI arrive with the Alpha (historical) focus
  universe, behind the same adapter interface.
- **Issuer Master, corporate-action metadata, venue-specific identifier
  rules** — same reasoning as §34: no producer, no consumer yet. The registry
  schema accommodates them; empty tables do not ship.
- **ARB-002 through ARB-030** — roadmap. ARB-001 ships in §41 because the
  simulation's evaluation loop needs it as the answer key; the rest arrive
  with addendum 27's own phase ordering (§11: Phase 1 is
  001/2/3/6/7/8/9/10/11/13) when detection against real chains is the work.
  ARB-026/27 stay out of the arbitrage namespace entirely per 27 §11.
- **Difficulty progression** (addendum 25 §13's "obvious early, subtler
  later") — the magnitude/noise knobs exist in the mission config; a staged
  curriculum is training-loop design that belongs with the Stage 1 lineage,
  deferred until a first pass of the parity mission has produced evidence
  about what "too subtle" measures as.
- **A separate Evaluator agent** — see the role mapping above.

*Owner decisions recorded: assimilate the seven documents; build the Reference
Data Engine first, the Simulation Engine second.*


---

## §40 — The Reference Data Engine: certification before agents (2026-08-22)

Addendum 24 (26 subordinate), first of the two Day Zero builds §39 ordered.
`backend/reference_data.py` — an engine, not an agent, by 24 §1's own words
and §35's precedent: pure functions over the database, no charter, no
watcher, no organization.yaml entry.

### The shape

- **Three registries, one table.** Asset Universe / Capability Set / Current
  Focus are three membership flags on one `asset_classes` row per class, not
  three tables — they are questions about the same eleven classes. Seeded:
  everything in the Universe; `stock` and `stock_option` alone in Capability
  and Focus (the parity mission's scope). Widening a mission later is a flag
  flip. The subset invariants (focus ⊆ capability ⊆ universe) are enforced by
  validation, not CHECK — the §34 lesson about constraints on growing
  vocabularies.
- **`security_master` sits on the entity layer**, one row per entity_id,
  never minting identity — `identifiers.py` owns that. `identifier_rules`
  makes identifier requirements metadata (24 §7): symbol required for the
  focus classes, isin/cusip/figi optional, validated against
  `identifiers.SCHEMES` at seed time.
- **The Assets table is a view** (24 §9). Same house precedent as
  `performance_card`: a work-discovery list that cannot drift from the
  master because it is derived from it. `CREATE VIEW IF NOT EXISTS` has the
  trigger trap (§34's family), so the view is reconciled by normalized-SQL
  comparison and drop/recreate, mirroring `_reconcile_triggers`.
- **Adapter pipeline with one adapter.** `SourceAdapter` protocol,
  `SeedUniverseAdapter` flowing the seeded universe through the full
  Acquire→Resolve→Reconcile→Merge→Provenance path. Conflict rules: a source
  never silently overwrites a held value; equal-or-lower authority records a
  `reference_conflicts` row and changes nothing; strictly higher authority
  overwrites *and still records the row* (the prior value is what the audit
  needs). One row per distinct disagreement, not per run — the pipeline runs
  at every startup, and re-recording an identical open disagreement adds no
  fact.
- **Fail-closed certification.** Seven validation checks; READY only when
  all pass; every certification — READY or FAILED — appended to
  `reference_readiness`, so the history survives, not just the answer.
  `focus_coverage`'s minimum (4) is a disclosed convention, not a
  measurement. `unresolved_conflicts` is always ok=True by design:
  a disagreement is data, not a blocker.

### Startup wiring, and what deliberately does not block yet

`backend/main.py`'s lifespan runs the engine after Controller reconciliation
and **before `bootstrap_coo`** — the Day Zero rule's ordering. A FAILED
certification currently logs loudly rather than halting agent bootstrap:
today's agents scan `discovery_config` peer groups and consume nothing from
the Assets view, so blocking them on a certification they do not yet depend
on would be enforcement theatre. The first true dependent is §41's
simulation mission, which refuses to start without READY. Wiring Explorer's
work discovery to `list_focus_assets` — and with it, making FAILED actually
block — is the increment where that dependency becomes real.

`GET /admin/reference` serves the dashboard shape (24 §19). The engine's
fine-grained progress states (INGESTING/NORMALIZING/…) are collapsed into
the certification result: a DB-only run over ten instruments completes in
milliseconds, and a state machine nobody can observe mid-flight is
decoration. They become real states when a network adapter gives the run a
duration.

### Declined or deferred

- Network source adapters (EDGAR, OpenFIGI, exchange directories) — §39's
  reasoning stands; the interface is real, the seed universe flows through
  it, and a network fetch cannot improve coverage of a synthetic focus
  universe. They arrive with the Alpha focus universe.
- Issuer Master, corporate-action metadata, venue tables — no producer, no
  consumer; the registry schema accommodates them.
- `underlying_entity_id` is set at creation only; the NULL-fill/conflict
  contract covers the five scalar fields the spec names. The options
  adapter that needs richer underlying handling does not exist yet.

### Division of labour, and what review caught

Implementation delegated per the tiering directive; design, spec, review and
this record by the top model. The delegated work corrected the spec once,
rightly — the spec repeated a stale claim that `/admin/*` routes are
unauthenticated; the code has required admin auth since the panel arrived,
and the new route follows the code. Review caught two defects in the
delegated work: conflict rows re-recorded on every rerun of a disagreeing
adapter (unbounded growth at startup cadence — now deduped per distinct
disagreement, with a regression test), and the assets view picking among
multiple live symbol identifiers without an ORDER BY (nondeterministic
`primary_identifier` — now ordered by validity start).

### Verified

Full suite green after review fixes (1404 passing, was 1382). Live
verification against a scratch copy of the real `financial_intelligence.db`:
ten universe symbols ingested and certified READY; a second run created
nothing, recorded nothing, and re-certified; retiring one symbol's live
identifier flipped certification to FAILED naming `required_identifiers`,
with `validation_status='invalid'` stamped on exactly the failing row —
fail-closed exercised against real data, not only fixtures.


---

## §41 — The parity training world, and the detector that is its answer key (2026-08-22)

Addendum 25's Version 1 mission, second of the two Day Zero builds §39
ordered. Three new modules — `simulation/pricing.py` (stdlib Black-Scholes,
`math.erf`, no new dependency), `backend/arbitrage.py` (ARB-001), and
`simulation/parity_world.py` (the engine) — plus `option_chain` in the
cadence taxonomy and a `parity` CLI subcommand beside the existing
simulation commands.

### ARB-001 before the library

Addendum 27's thirty detectors are roadmap; ARB-001 ships now because the
simulation's evaluation loop needs it as the answer key — the same
organization's-own-detector principle as Stage 1's key (§37), so scoring
can never drift from what a real deployment would run. The detector obeys
27's implementation contract: a pure deterministic function over a
snapshot, returning `Opportunity` or `NoOpportunity(reason_codes)`;
**no code path reads a mid price**. Data-quality hard stops are collected,
not short-circuited (stale, crossed, invalid bid, non-European style).
Conversion classifies A, reversal B — the borrow assumption is the
difference — and an unknown borrow fee makes the reversal direction
*unavailable* with `missing_borrow` said out loud, never priced at zero
(27 §10's "never silently substitute missing reference data").

### The world

- **Activation and identity, fail-closed.** `run_mode` must be
  `"simulation"` (25 §2, enforced at the engine boundary until mission
  control has a UI — §39's disposition), and the engine refuses to start
  unless the Reference Data Engine certified READY with focus assets to
  offer (25 §3). Every simulated security carries the canonical entity_id
  and symbol from `list_focus_assets` — the engine never invents identity.
  §40's "first true dependent" is now real.
- **Parity holds by construction, except where a scenario says otherwise.**
  Chains price from Black-Scholes under a seeded skew shape (eight named
  shapes, flat through localized distortion), same inputs both sides, so an
  uninjected chain is arbitrage-free — and the property test proves the
  engine and detector agree on that across seeds, which is addendum 25
  §25's parity-consistency test pointed at both components at once.
- **Six scenario variants** (25 §9/§21): genuine, spread_artifact,
  carry_effect, borrow_cost, stale_quote, none. Genuine injections are
  floored against the detector's own cost config so "genuine" is
  executable by construction; each trap is engineered to be erased by
  exactly the friction it teaches. Ground truth records variant, affected
  pair, deviation and expected direction — returned to the caller and
  written only to the run summary under `simulation/runs/`, never to a
  table (the §37 rule).
- **Determinism as a property, not a hope.** All timestamps derive from
  the config's `base_time`, never the wall clock (the one wall-clock read
  names the summary file); same config, same world, test-enforced.
- **Chatter synchronized to the same world** (25 §11/§12): Reddit-style
  items on the affected security at a configured signal ratio, noise on
  other focus securities, all resolving to canonical entity_ids, emitted
  under the existing `social_post` class. Explorer's feed is canonical
  `option_chain` Observations whose payload carries no ground-truth
  marker — test-enforced isolation.
- **Evaluation and coverage** (25 §16–§18): per-scenario
  PASS/PARTIAL/FAIL against the key; a run whose genuine scenarios were
  never detected — or that never drew one — ends RETRY_REQUIRED, not
  COMPLETED. A strategy-training run that never exercised the strategy
  does not get to call itself finished.

### Deferred, with reasons

Agent wiring — Explorer consuming `observations()`, Speculator the
chatter, Analyst the candidates, and with them 25 §17's full completion
loop — is the next increment, deliberately: this one proves the world and
its own answer key against each other first, exactly as Stage 1 did before
agents consumed its worlds. Difficulty progression stays deferred per §39.
The mission-control UI remains panel work.

### Division of labour, and what review changed

Implementation delegated per the tiering directive; design, spec, review,
live verification and this record by the top model. The delegated work
disclosed one honest tail risk rather than hiding it — an injector's 0.02
mid floor could clip a large drawn deviation and silently plant a weaker
shift than ground truth recorded. Review closed it: injectors now fall
back to the unclippable direction (the RNG stream unchanged, so seeded
worlds are preserved), with a regression test that forces deviations
larger than most put mids and demands every genuine scenario stay
detected. Review also corrected the state record: WAITING_FOR_REFERENCE_DATA
now appears in a run's traversal only when the gate actually blocked.

### Verified

1440 passing (was 1404; +35 delegated, +1 review regression test). Live,
via the CLI against a scratch copy of the real database: the engine
first **refused** — the real database has never run the new startup, so no
readiness certification existed, and the refusal named
WAITING_FOR_REFERENCE_DATA — which is the fail-closed dependency chain
exercising itself unprompted. After certifying the copy: eight scenarios
(one genuine, traps, all variants drawn), 216 contracts, 24 chatter items,
genuine detected, zero trap leaks, pass rate 1.000, strategy exercised,
final state COMPLETED, summary written and gitignored.


---

## §42 — The agents work the parity world blind, and the Evaluator grades them (2026-08-23)

Addendum 25 §17's completion loop, closed: Mission Configuration → Reference
Data READY → world stored → Explorer + Speculator identify the candidate →
Analysis investigates → **Evaluator compares outcome with ground truth**.
Every arrow now runs through the real organization — real OS processes, real
LLM calls — and §41's offline answer key is retired to what it always was:
the development-time proof that world and detector agree.

### The world reaches the agents through the Data Store

`store_world` persists a mission's option chains and chatter as canonical
Observations (synthetic provenance, run_id = mission, scenario_id per
world); Explorer and Speculator read them back through
`providers/stored_data.py`. Two properties carry the design:

- **Source-indifference is structural.** The read side is a translation
  layer over `observations.replay` — a historical or live chain feed later
  writes the same store and the agents change nothing (addendum 25 §10's
  "the same interface that will later serve historical or live data").
- **Activation is data presence, not a flag.** No stored mission world →
  `latest_chain`/`fetch_recent` return nothing → every new agent path is a
  no-op, cycle after cycle. Addendum 25 §2's activation rule stays enforced
  at the mission runner (`run_mode="simulation"` required); no env plumbing
  reached the agents.
- **One distinct security per stored scenario.** The store's idempotency
  key (entity, class, observed_at, origin, source — all shared within a
  mission) would collapse two same-entity scenarios into one chain and
  leave the Evaluator blaming agents for a miss the store caused; and
  Explorer reads only the latest chain per entity, so distinct assignment
  is the only honest shape, enforced with a refusal when
  n_scenarios > focus assets.

### Explorer is ARB-001's detector now

`_parity_work` scans `reference_data.list_focus_assets` — **the Assets
view's first work-discovery consumer, closing §40's loop** — and runs
`detect_arb001` itself over each stored chain. Detections land in a new
`parity_events` table (detector_events is IV-shaped, NOT NULL peak/ratio
columns; parity numbers in IV-named columns would be misfiled evidence),
carrying run_id/scenario_id from the observation's provenance — the
Evaluator's join key, which identifies the scenario without revealing its
answer. Reports gained a nullable `parity_event_id`, the archive trigger
copies it (the §34-era trigger-reconciliation machinery updates deployed
databases automatically), and Analysis renders a parity context block that
tells the model what the claim is and what would invalidate it.

Discipline mirrored from the IV path, with two deliberate differences:
**no LLM judgment gate** (the detector's executable-price hard stops are
the precision filter; a coherence check on deterministic arithmetic is an
LLM call with nothing to judge), and a **recency guard** (the mission's
world is static, so a security whose analysis just completed would
otherwise re-open a paid pipeline loop every cycle). The escalation law is
unchanged: cross-check with Speculator first, report on the answer or the
timeout, dissent attached. The min-edge threshold is a third seeded lens
(`arb001_min_net_edge`, 0.0 — any positive executable edge; convention),
with no regime validity conditions: parity is a structural relationship,
not a regime-dependent pattern. Speculator reads the mission's chatter
into evidence and its `seen` window (corroboration only — the parity
mission's originator is Explorer).

### The Evaluator

`simulation/parity_evaluation.py` — the Evaluator role of addendum 23 §7
in its current form: a deterministic grading pass, not an agent (§39's
disposition stands; there is no judgment here an LLM would earn its call
by making). It joins the ground-truth summary (which no agent ever read)
against parity_events → reports → analysis_results, and grades per
addendum 25 §16: full chain in the right direction → PASS; wrong direction
→ PARTIAL; detected but never escalated → PARTIAL; report awaiting
analysis → INCONCLUSIVE (the evaluator reports the state it finds, it
does not wait); missed genuine → FAIL; any detection on a trap or clean
control → FAIL, regardless of what happened downstream. Strategy coverage
(§18) requires at least one genuine scenario at PASS; anything less is the
strategy being tried, not exercised, and the CLI
(`python -m simulation parity-evaluate`) exits nonzero on it.

### The gate grew teeth, and the watcher had to learn about them

`bootstrap_coo` now runs only on a READY certification — §40's promised
blocking, real because Explorer genuinely consumes focus assets. The
server stays up on FAILED (admin routes must show the failure, addendum
24 §21); only the workforce waits.

**Live verification found the hole a unit test structurally could not:**
the first FAILED-certification run came up fully staffed anyway. The gate
had worked — the banner was in the log, `bootstrap_coo` never ran — and
§28's COO watcher then treated the missing COO as a fault and "recovered"
it, waking the exact workforce the gate exists to block. The fix consults
the same authority the gate did (`reference_data.is_ready`) inside
`_recover_coo`: a missing COO under a non-READY certification is
intentional inactivity, the same §7 reasoning as the dormancy branch —
no incident, no spawn. Re-verified live: FAILED certification, only
`controller-1` registered, watcher standing down, graceful shutdown.

### What live verification proved, and what review caught

Full completion loop against a real organization (harness-isolated, real
LLM): six scenarios stored (four genuine, two traps); Explorer detected
and escalated all four genuine within seconds; Speculator answered the
cross-checks from mission chatter; one genuine scenario completed the
entire chain inside the five-minute window — a real Analysis thesis
naming staleness sensitivity on a $0.05/share class-A edge — and the
Evaluator graded it PASS with `strategy_exercised: true`; both traps PASS
with zero detections; the three still-in-flight chains graded
INCONCLUSIVE (`analysis_in_flight`), which is the honest state: Analysis's
adopted 3-pass budget spends ~2 minutes per deep call, and the window fit
one. Zero false positives. Clean shutdown, no orphans.

The same run exposed **parity-event spam**: the static world re-triggered
every ~1s cycle and recorded 1,152 identical rows in five minutes.
`record_parity_event` now converges on (security, observed_at, strike,
expiry, direction) — the observations store's own ingest idiom; a new
chain observation carries a new observed_at, so fresh market states are
always fresh rows. Review also fixed the stored-mission/rebuild mismatch
in a round-trip test that the distinct-assignment change surfaced.

### Deferred, with reasons

- **Diagnosis and training/correction** (addendum 25 §19): the Evaluator
  measures; deciding what to do about a FAIL is a separate design with its
  own owner decisions.
- **Difficulty progression, mission-control UI**: unchanged from §39.
- **Speculator origination from mission chatter**: the parity mission's
  originator is Explorer; Speculator's own origination stays on its
  existing path until a mission design wants otherwise.
- **A live-run panel view of parity events/evaluations**: no route asked
  for it yet; `/admin/discovery`-style surfacing arrives with a consumer.

### Verified

1482 passing (was 1440 at branch start: +31 delegated wiring tests, +8
evaluator tests, +3 review regression tests — the store collision, the
parity-event convergence, and the watcher gate). Two live runs
against real organizations as described above — the completion loop with
real LLM calls, and the blocked-bootstrap run, both shut down verified
clean. Division of labour per the tiering directive: survey, wiring and
evaluator implementation delegated (one connection loss mid-task, resumed
with context intact); design, specs, review — which caught the event spam,
the store collision, and drove the two live runs that caught the watcher
hole — and this record by the top model.


---

## §43 — Diagnosis: the offline detector as the differential (2026-08-23)

Addendum 25 §19, the last stage §42 deferred: when evaluation does not pass,
distinguish the cause, name the component, and say what a rerun would need
to prove anything. `simulation/parity_diagnosis.py`, plus a
`parity-diagnose` CLI. The completion loop now reads, in full and in code:
mission → reference READY → world stored → agents work it blind → Evaluator
grades → **diagnosis → correction guidance → rerun → completion
certification**.

### The core idea

**The simulator's own offline detector is the differential diagnostic.**
Explorer runs `detect_arb001` over `StoredChainProvider` snapshots; the
diagnosis re-runs the identical detector over the identical stored rows.
Agreement means the defect is downstream of detection (escalation,
cross-check, Analysis); disagreement means it is upstream of Explorer
entirely — the world never carried an executable edge, or still carries one
it should not. That split requires no judgment call, which is why this is a
pure function over the database (no LLM, no new agent — §39's Evaluator
disposition, third application) and why it reuses Explorer's own read path
rather than a reimplementation that could drift from it.

Sixteen causes cover §19's vocabulary in this mission's terms: world causes
(`world_not_stored`, `insufficient_signal`, `trap_not_erased`,
`world_not_clean`, `detector_interface_drift`), agent causes
(`explorer_missed`, `explorer_filing_failure`, `explorer_escalation_failure`,
`explorer_selection_error`, `analysis_stalled`, `analysis_lost`),
evaluation causes (`ground_truth_direction_error`,
`direction_indeterminate` — where expected, agent and offline directions
all differ, the module refuses to guess and says so), and in-flight
non-causes (`cross_check_in_flight`, `recency_suppressed`,
`analysis_in_flight`) — the diagnosis distinguishes suppression by a
design guard from failure, which is what keeps a healthy pipeline's
patience from being misread as a defect. There is no Speculator cause:
an unanswered cross-check still escalates by design (§42's
suppression-prevention rule), so Speculator silence cannot strand a lead —
the wiring's own law closed that failure mode before diagnosis existed.

### Correction, in this increment's honest form

`remediation.py`'s discipline, followed to the letter: corrective work is
**per cause, not per finding** (three stalled scenarios are one item, not
three); diagnosis is **read-only** (its only write is its own JSON beside
the evaluation — deciding work and creating it are separate acts with
separate authority); and there is deliberately still no corrective task
queue — naming the component and the concrete remedy *is* §19's correction
step until something asks for dispatch machinery. Actual agent *training*
remains future work with its own design. One judgment call recorded rather
than left implicit: `detector_interface_drift` classifies as `world` by
remediation.py's own SYSTEMIC test — Explorer called the same detector
over the same rows and got a different answer; no choice it made explains
that, so the remedy is a design fix, not correction owed to an agent.

### Retry and certification

`retry_guidance` carries §18's decision structure: `rerun_same_seed` when
causes are agent/evaluation only (the same world re-tests the correction),
`adjust_world_first` when any world cause exists ("adjust scenario
generation if required"), and neither when everything outstanding is in
flight — a run that needs time gets `wait_and_reevaluate`, not a rerun.
`mission_certified_complete` is §17's completion certification **as a
statement in the record, deliberately not a gate** — nothing downstream is
permitted or withheld by it, and `simulation/certification.py`'s own
warning about gates that bind nothing is cited where the choice is made.
The CLI exits 0 on certified-or-in-flight, 2 on retry-recommended, so an
operator's script can branch on the verdict.

### Verified, on real artifacts and a real rerun

1494 passing (was 1482; +12). Then the loop, live, twice over:

- **Diagnosis over §42's real run.** Its three INCONCLUSIVE scenarios —
  reports stranded when that organization shut down — diagnosed as one
  `analysis_stalled` corrective item across all three, classification
  agent, remedy "check whether Analysis is alive" (literally correct: it
  is not), verdict retry-recommended with `rerun_same_seed=True` and no
  world adjustment. Exit code 2.
- **A rerun to certification.** A fresh live organization (real LLM),
  four scenarios (two genuine, two stale-quote traps): both genuine
  chains ran detection → cross-check → report → Analysis to completion,
  both traps stayed clean, the Evaluator graded 4/4 PASS, and the
  diagnosis pronounced `mission_certified_complete: True` with zero
  corrective items — the completion loop's last arrow, exercised end to
  end against a real workforce. Graceful shutdown, no orphans, both runs.

Division of labour per the tiering directive: implementation delegated;
design, spec, review and both live runs by the top model.

### Deferred, with reasons

Corrective-task dispatch and agent training machinery (nothing asks for
them yet — remediation.py's own recorded posture); automated rerun
orchestration (the CLI verdict is the hook; wiring it to a scheduler is an
operator decision); the mission-control UI and difficulty progression,
unchanged from §39.


---

## §44 — Mission control: the user chooses, the boundary decides (2026-08-23)

Addendum 25 §4's mission-control interface and §22's dashboard, closing
§39's own IOU ("the mission-control interface is panel work not yet built").
Two halves: `backend/missions.py` with five `/admin/mission*` routes, and a
Mission Control tab in the Controller control panel.

### The mission registry

`missions` is the durable record of every mission the operator asked for:
config, status, note, artifact paths, cached metrics. Ground truth stays in
the summary file — the table holds its *path*, never its content. The §22
status vocabulary is reused from the engine's own STATES; the generation
states collapse into the transition (store_world is a synchronous
millisecond-scale write — §40's argument, third use), so the statuses a
mission actually passes through are WAITING_FOR_REFERENCE_DATA,
AGENTS_RUNNING, RETRY_REQUIRED, COMPLETED, FAILED.

Route semantics worth recording:

- **All three run modes are offered; the boundary decides.** §4 says the
  interface offers Simulation/Historical/Live; §2 says only Simulation
  activates this engine. The panel does not pre-filter — choosing
  Historical gets the backend's honest refusal, matched against
  `MissionConfig`'s own validation message so the two rules can never
  drift. The refusal creates no row; a *blocked* mission
  (reference data not READY) does create one, in
  WAITING_FOR_REFERENCE_DATA with the reason — §23's visible failure as a
  dashboard row rather than a transient error. Re-POSTing the same
  mission_id retries a WAITING/FAILED mission; a mission that stored a
  world refuses re-storage with a conflict.
- **Evaluate is a button, and the verdict moves the status**: COMPLETED on
  certified, RETRY_REQUIRED on retry-recommended, and AGENTS_RUNNING kept
  when the diagnosis says wait — a run that needs time keeps its running
  status.
- **Dropdowns are fed from the backend** (`/admin/mission-options`):
  strategies from `parity_world.STRATEGIES`, asset classes from the
  reference registry's Capability Set — §4's extensibility is a tuple
  entry and a registry flag, not a UI redesign.
- **Authority**: the server process (the Controller, addendum 21's
  orchestration layer) invokes the engines directly — the same disposition
  as §40's Reference-engine startup invocation. COO-mediated mission
  orchestration is deferred until a mission needs agent-side sequencing;
  today's engine start is one synchronous DB write, and a directive
  round-trip would add a queue for a millisecond operation.

### The panel

A ninth notebook tab beside the organization views, polling on the
panel's existing 2s cycle: run mode / strategy / asset classes / seed /
scenarios controls, Start Mission, the §22 mission list (status, pipeline
counts as detections/reports/analyses, pass rate, strategy-exercised),
and Evaluate with the per-scenario outcomes and diagnosis verdict in the
detail pane. Formatting lives in `panel/render.py` (testable without Tk,
the file's own rule); every handler is a method callable without a click,
which is what live verification drives.

### The auth surface test stopped being a sample

Review found `tests/test_admin_auth.py`'s "the whole surface, not a
sample" list silently covering nine of twenty-seven routes — exactly the
rot its own docstring warns about, discovered rather than prevented. The
surface is now derived from the app's routing table with a floor
assertion, so a new admin route is gated-by-default or fails the suite.

### Live verification, and the defect it caught in §43's work

The real Tkinter panel's own handlers, driven against a real organization
(harness, real LLM): dropdowns populated from the backend; Historical
refused with the honest message on the status line; a four-scenario
mission started from the panel; agents worked it; Evaluate rendered
per-scenario outcomes and a verdict; graceful shutdown.

That run also caught a real conflation in the diagnosis stage: **both
deep-reasoning calls failed with genuine `Connection error.`** — the
intended error path, report completed 'failed' with the error in its
detail — and the diagnosis called it `analysis_lost`, whose remedy hunts
a code defect that does not exist. A report completed 'failed' carries
its own explanation; only 'analyzed'-with-no-conclusion is the code-defect
case. `analysis_failed` now exists as its own cause (classification
agent, remedy naming the transient-vs-gateway distinction, same-seed
rerun), with a regression test, and re-diagnosing the run's real
artifacts produces it — one corrective item across both scenarios, detail
`Connection error.` carried in the notes. Third consecutive increment in
which live verification against a real organization found what the unit
suite structurally could not.

### Verified

1521 passing (was 1494: +17 backend missions, +10 panel render, −1 from
consolidating the two hand-listed auth-surface tests into one derived
test, +1 analysis_failed regression). Division of labour per the tiering
directive: both halves
delegated; design, specs, review — the auth-surface rot, the
analysis_failed conflation — and the live panel run by the top model.

### Deferred, with reasons

Historical/Live mission engines (their run modes refuse honestly until
they exist); COO-mediated mission orchestration (above); scenario-mix and
difficulty controls in the panel (§13's progression is still future
design — the seed and scenario count are the reproducibility controls §6
requires); automatic re-evaluation polling (Evaluate is an operator act;
wiring it to a timer is an operator decision).


---

## §45 — The arbitrage library's Phase 1: eight detectors under one discipline (2026-08-23)

Addendum 27 §11's Phase 1, on the contract ARB-001 proved in §41.
`backend/arbitrage.py` now holds ARB-002/003 (conversion and reverse
conversion as standalone package entry points sharing ARB-001's math
through one internal helper, so the formulas cannot drift), ARB-006
(European box, both directions), ARB-007/008 (call/put vertical bounds),
ARB-009 (butterfly/convexity with general unequal-spacing weights),
ARB-010 (all four intrinsic/upper bounds, per-check hard stops so a stale
call cannot block a put-only package), and ARB-011 (strike monotonicity).
Plus `ChainSnapshot` (one expiry's strike ladder), `CostConfig.for_legs`
(the cost model finally per-leg-count), DF-based bound math throughout
(negative rates generalize — ARB-030's framework rule, tested at
r = −0.01), and `scan_chain`, the chain-level entry point that enumerates
strikes, pairs and triples, skips hard-stopped candidates, and
deduplicates — the monotonicity case is both ARB-007's zero bound and
ARB-011, so the scan runs the verticals width-branch-only and attributes
that package to ARB-011 once, while the standalone functions keep their
full spec definitions.

**ARB-013 is deliberately not built**: no forward or futures instrument
exists in any world this system generates (the Capability Set is stock and
stock_option), so the detector would have no producer and no consumer —
the same empty-machinery refusal as every prior deferral. It arrives with
the first forward-bearing world.

**Nothing consumes the new detectors yet, and that is the honest state.**
Explorer escalates ARB-001 only; wiring the others into discovery needs
each to have training scenarios the world can pose (addendum 25 §18: a
strategy-training run must exercise the strategy), which is injector work
with its own increment. Phase 1's first consumer is the property suite
below — the library and the world validating each other.

### The property tests found two true things about the world

Addendum 27 §7's "generate arbitrage-free chains, verify no executable
positives" test, run with the parity world as the generator, produced two
findings — both investigated to ground, neither a detector bug:

1. **A localized IV distortion is a genuine cross-strike mispricing.**
   Uninjected worlds were clean under every skew shape except
   `localized_distortion`, whose isolated IV mountain — the exact shape
   the original IV-surface lens trains on — genuinely violates
   monotonicity, convexity, verticals and boxes around the bumped strike.
   That is economics, not error: an isolated volatility spike *is* a
   butterfly mispricing. Disposition: the world is not "broken"; the
   §21 vocabulary is refined — `localized_distortion` is an implicit
   anomaly variant, and future cross-strike training scenarios can use it
   deliberately. Nothing currently misgrades: the Evaluator grades only
   parity_events, and `world_not_clean` diagnoses only the parity checks.
2. **A parity injection at one strike breaks cross-strike bounds through
   that strike.** A $1 shift in one put is also a box/vertical/butterfly
   mispricing at every pair involving it — verified: on genuine-mix
   worlds, every non-ARB-001 hit traces to the injected strike (or to a
   co-drawn localized distortion). Both findings are encoded as
   assertions, not weakened away.

### Verified

1566 passing (was 1521; +45). Live, against the certification run's real
stored world (cert-101): the two stale_quote scenarios scan to **zero**
hits — every package touching the stale legs refuses, everything else is
clean; the flat-skew genuine scenario shows ARB-001's $0.05 conversion at
the injected strike plus eight box packages all through it; the
localized-distortion genuine scenario shows the IV mountain read as
twenty genuine cross-strike opportunities up to $14/share alongside the
$0.05 parity edge — the library reading real stored data exactly as the
two findings predict. One verification-script defect caught in passing:
the first run's glob matched the diagnosis file (empty scenario list) and
passed vacuously — a reminder that an OK with no evidence printed is not
an OK.

Division of labour per the tiering directive: implementation delegated
(the property findings were the delegated work's own investigation,
verified rather than taken on faith); design, spec, review, the live
scan and this record by the top model.

### Deferred, with reasons

ARB-013 (above); Explorer wiring and training injectors for the
cross-strike detectors (each needs its scenario design — the natural next
library increment); ARB-012's calendar diagnostics and Phase 2
(014–025) per addendum 27's own ordering; the RelativeValue service for
026/027 stays out of the arbitrage namespace entirely (27 §11).


---

## §46 — The cross-strike detectors get their training world (2026-08-24)

§45's deferred item: training injectors for the Phase 1 detectors and
Explorer wiring under addendum 25 §18's coverage rule. A new strategy —
`options_arbitrage_phase1` in the extensible STRATEGIES tuple, picked up by
the mission-control dropdown automatically — whose scenarios train the
cross-strike detectors, worked by the same agents through the same loop.

### The design: a parallel shift preserves parity

Shifting one strike's call AND put mids by the same amount, half-spreads
unchanged, leaves every executable parity edge at that strike invariant
(Cbid−Pask and −Cask+Pbid both cancel the shift) while genuinely breaking
monotonicity, verticals and butterflies against the neighbors. So the
three new variants — `cross_strike_bump`, `cross_strike_dip` (with the
clip-fallback discipline; ground truth records the variant actually
applied), and `cross_strike_spread_artifact` — train ARB-006/007/008/009/
011 with **zero ARB-001 co-fire by construction**, and an ARB-001
detection on a cross scenario is a world-integrity alarm, graded
FAIL('unexpected_parity_hit'). Floors are computed against the detector's
own cost model, primary package ARB-011 monotonicity at (k_prev, k_mid).

### What generalized, and what the generalization uncovered

`parity_events` grew additively (`detector_id` defaulting to 'ARB-001',
`strike2`, `strike3` — the table's name is now historical; renames are
banned). Explorer's chain scan became `scan_chain` — the whole library,
one entry point — gated by the same min-edge lens (its `arb001_` name is
likewise historical; scope widened to the library scan). The Evaluator
learned detector families (`expected_family: cross_strike`: any
non-ARB-001 detection through the primary strike advances the chain;
strays and parity hits fail). The diagnosis differential went chain-wide
— `scan_chain` offline covers both families with one mechanism — and
gained `world_cross_integrity` for the case where the offline scan agrees
with a stray detection (the world leaked beyond the affected strike).

Widening the answer key from ARB-001 to the library exposed two latent
defects and forced one design decision:

1. **The pre-existing trap injectors leaked cross-strike opportunities.**
   `_inject_spread_artifact`/`_inject_borrow_cost`'s one-legged shifts
   break monotonicity against the neighbor (§45's second finding), and
   their erasure math only ever targeted the same-strike parity formula.
   Both now verify with an actual `scan_chain` call and widen iteratively
   until clean — as does the new cross trap, whose closed-form floor
   alone proved empirically insufficient against far-strike butterflies.
2. **Best-by-net-edge selection would have broken parity training.** A
   genuine parity injection's induced cross-strike side effects can carry
   a larger edge than the deliberately-minimal ARB-001 edge, so Explorer
   prefers ARB-001 among candidates when present — semantically right
   (the planted training signal) and provably a no-op on cross scenarios
   (zero ARB-001 co-fire there).
3. **"None means clean" is now true by construction** (owner-side design
   decision on review). §45 accepted `localized_distortion` on clean
   scenarios as an honest world-failure; this increment ends the
   ambiguity instead: clean-world variants (none and every trap) redraw
   their skew from a salted stream when they land on that shape — ground
   truth must not promise "no opportunity" over a world that genuinely
   carries one. Genuine variants keep full skew diversity, distortion
   included. The none-mix and trap-only property tests dropped their
   carve-outs and assert unconditional zero detections again, plus a test
   pinning the redraw itself.

### Verified

1592 passing (was 1566; +25 delegated, +1 review-driven pinning test).
Live, through the mission-control API against a real organization (real
LLM): a five-scenario `options_arbitrage_phase1` mission (two bumps, one
dip, two spread traps) — Explorer recorded ARB-009 put butterflies
through every affected strike, escalated through cross-checks, Analysis
produced genuinely reasoned theses (one flagged the broken-wing
asymmetry of an injected structure unprompted), both traps stayed clean,
and the Evaluator + diagnosis graded **5/5 PASS, certified complete,
zero corrective items**. Graceful shutdown. The one incident was the
verification script itself dying on a Unicode arrow in a thesis under the
cp1252 console after the run succeeded — evaluation completed offline
against the surviving artifacts.

Division of labour per the tiering directive: implementation delegated
(one connection loss, resumed with context intact; its report surfaced
all three findings above honestly); design, the clean-skew decision,
review, live verification and this record by the top model.

### Deferred, with reasons

Per-detector-family lenses and grading attribution (one min-edge lens
governs the whole scan until grades distinguish families); difficulty
progression (unchanged from §39, now with two strategies' worth of
certified runs to calibrate against); ARB-012 diagnostics and Phase 2 of
the library, per addendum 27's ordering.

---

## §47 — The Organizational Doctrine lineage arrives: six documents and a queue (2026-08-24)

Seven documents supplied. One — the options arbitrage library specification —
verified byte-identical to addendum 27's verbatim body (assimilated §39/§43);
re-supply, no action. The other six are new and form a fifth lineage,
**Organizational Doctrine (28–33)**, dated 2026-08-23: Security Defense (28),
Business Continuity (29), Department of Evolution v2.0 (30), Strategy
Department (31), Governance Framework & Parliamentary System (32), Strategic
Principles (33). All six describe the *target* organization — Board,
ministers, parliaments, defense branches, continuity councils, agent catalogs
in the dozens — for a platform the documents call "MyAI"; that is this
platform (the repository is literally `my-ai`), and "Project Jarvis" remains
the organizational lineage's own name for it. Nearly everything in them is
roadmap. Assimilated verbatim per convention; precedence row added to the
index; and — the lineage's first concrete effect — the work it generates now
lives in a maintained queue, `docs/TASK_QUEUE.md`.

### What was adopted immediately

Addendum 31 §3 demands a Strategic Priority Register; addendum 32 §12 demands
priority queues with Need/Want and Quick-Win classification. Both are adopted
now, in the only form the current system can honestly support: a maintained
paper register (`TASK_QUEUE.md`) whose conventions are the specs' own
(NEED/WANT per 31 §2, GREEN→CRITICAL flags per 31 §2.2, QUICK_WIN per 32 §15),
worked one item at a time with the owner as Board. A machine-readable register
is itself queued (TQ-05) rather than presumed. This follows the lineage's own
doctrine — addendum 30 §12: prefer metadata and policy before code.

### Boundary dispositions

1. **30 (Evolution) against 13 (Training Agent Design).** The built training
   loop — missions, evaluation, certification, remediation, competency — was
   built under 13 and already performs 30's train→evaluate→certify with
   separated roles (30 §18's trainer/evaluator/certifier split is honored in
   structure). Disposition: **13 governs the built loop**; 30 is adopted as
   doctrine above it, and its machinery (versioned Evolution Directives,
   trainer hierarchy, Directive Communication Agents) waits until a real
   systemic evolution needs what the existing loop cannot express. One
   directive is actionable today and queued: **E17** (every agent exposes a
   behavior version and certification state) — agents carry `identity` +
   `spawned_at` and act on versioned strategies, but the registry row exposes
   neither field E17 names. TQ-03.

2. **30 §10 (COO) against the built COO.** No conflict — the built COO is
   exactly 30's operational coordinator (spawning, capacity, directives,
   reconciliation) and owns none of what 30 §10 excludes. Noted, nothing to
   resolve.

3. **28 (Security Defense) against the Gateway lineage (16–18).** 16–18 own
   the external boundary's existence and shape (one exposed service, Super
   User, loopback host); 28 governs its *defensive posture*. Much of 28's §32
   baseline already exists under Gateway-lineage names: no secrets in Git
   (`.env`), bcrypt with environment-sourced Super User credential, layered
   rate limiting that deliberately refuses `X-Forwarded-For` (§43's run.py
   discipline), per-user isolation, audit logging, loopback-only origin. The
   item-by-item audit is queued (TQ-04). Emergency Defense Mode, threat
   intelligence, and edge/DDoS defense are deferred until anything is exposed
   beyond loopback — the trigger is explicit, not forgotten.

4. **29 (Business Continuity) against everything built.** The genuine gap in
   the lineage: **nothing implements backup or restore.** Every store —
   backend database, Gateway store, `user_data/` — lives in one failure
   domain, violating 29 §1.3. The 3-2-1 principle, provider-neutral
   `StorageProvider`, and tested-restore discipline (§1.4) are accepted as
   binding for the first slice, which is the queue's top implementable item
   (TQ-02). Multi-zone/multi-region/clean-room machinery is deferred: a
   single-machine deployment has no second failure domain to orchestrate.
   Model-provider fallback (29 §15) already exists under the FI lineage's
   provider abstraction; noted as satisfied in kind.

5. **32 (Governance) against 11/22 (organizational constitution, private) and
   the constitution.** The constitution remains supreme (precedence table).
   32's civilian character, dual departmental leadership, and
   proportional-to-impact voting are adopted as direction and recorded here;
   the parliamentary machinery (elections, committees, referendums, Cabinet)
   is deferred with the reason stated in the queue: at the current population
   — a handful of role-agents — the procedure would be ceremony without
   constituents. Governance's *classification* discipline (Quick Wins,
   cost/impact profiles, high-visibility accountability) is adopted through
   the register instead.

6. **33 (Strategic Principles) against the constitution.** 33 §0 says its
   principles SHOULD be distilled into constitutional directives. The
   constitution is held privately; distillation is an owner action and is
   listed as such in the queue's deferred section. Meanwhile 33 operates at
   architectural precedence like its siblings. Its doctrine is already
   visible in this file's own habits — §46's "strategy over brute force" was
   practiced before it was named (a parallel mid-shift that preserves parity
   by construction instead of brute-force erasure search), which is worth
   recording as evidence the doctrine fits rather than as self-congratulation.

### The queue itself

`docs/TASK_QUEUE.md`, at assimilation: TQ-01 (this work, done), TQ-02
(continuity backup slice, NEED/YELLOW — the top implementable item), TQ-03
(E17, quick win), TQ-04 (28 §32 audit, quick win), TQ-05 (machine-readable
register, WANT), TQ-06 (library Phase 2 per 27 §11, WANT), TQ-07 (cost/impact
profiles, after TQ-05); blocked: ARB-013 (no forward/futures instruments in
the training world — a world-design increment, not a detector increment);
deferred with reasons: parliamentary machinery, emergency defense, multi-zone
continuity, constitutional distillation, Evolution directive machinery.

---

## §48 — The first recovery copy: continuity backup with tested restore (2026-08-24)

TQ-02, the queue's top implementable item. `backend/continuity.py`: addendum
29 §8.1's `StorageProvider` interface with a local-directory adapter first
(29 §1.7 blesses local storage as a provider), `create_backup` /
`verify_backup` / `restore_backup` / `list_backups`, and a
`python -m backend.continuity` CLI. The backup domain is the gitignored
state — both databases, `users.json`, `sessions.json`, `user_data/` —
resolved through the owning modules' own path constants so environment
redirects move the domain with the data.

### The decisions worth recording

- **SQLite goes through the engine, not the filesystem.** Copying a WAL
  database's bytes while agents write produces a torn copy; snapshots use
  sqlite3's backup API, and the test for it commits a row through a
  still-open connection (parked in the -wal, unchekpointed) and reads it
  back out of the restored file.
- **The manifest is written last.** An interrupted `create_backup` leaves
  files but no manifest, and `list_backups`/`verify_backup` treat
  manifest-presence as the definition of a set — an incomplete backup
  cannot be mistaken for a complete one. Tested.
- **Fail-closed in both directions.** Restore verifies the entire set
  before writing a single byte (restoring the intact half of a corrupt set
  manufactures a state that never existed), and refuses to overwrite
  existing files without an explicit flag. Both tested, including that the
  corrupt-set restore writes *nothing*.
- **Absence is recorded, not skipped.** A missing source lands in the
  manifest's `absent` list — restore can distinguish "not backed up" from
  "did not exist". The live run recorded exactly this: `gateway` absent
  because the Gateway has never run on this machine.
- **Exclusions are decisions.** `.env` (re-issue keys, don't copy them),
  `simulation/runs/` (reproducible, §12.4 derived data), source code
  (Git's job; §38 repository continuity is separate). Recorded in the
  module docstring per §1.8. Encryption-before-upload deferred for this
  adapter with the reason stated: same failure domain, so it adds key-loss
  risk without confidentiality gain; mandatory with the first remote
  adapter. Meanwhile a backup set is exactly as sensitive as the live
  stores (session rows are credentials) and `backups/` is gitignored with
  that stated.

### Verified

Ten new tests (1602 passing total): provider roundtrip and root-escape
refusal, manifest/hash/absentee recording, the live-WAL snapshot case,
byte-exact restore, corruption detection with all-or-nothing restore,
overwrite refusal, orphan-set invisibility, id uniqueness, and the real
backup domain's labels. Live: `python -m backend.continuity backup` against
the running organization took a consistent 42MB snapshot of
`financial_intelligence.db` *while the COO's agents were writing to it*,
recorded users/sessions, recorded the Gateway absent, and `verify` reported
the set intact.

### An operational fact the verification surfaced

Killing the backend process does not stop the organization: the COO's
agents are separate processes and keep writing (the test suite's
real-database tripwire caught them mid-run, doing its job). Recovery was
manual process cleanup. This is addendum 30 §7's drain discipline and
addendum 29 §13.2's clean-restart requirement meeting reality — a graceful
whole-organization shutdown path exists via the controller, but an
ungraceful backend death orphans the population. Noted here as observed
behavior, not fixed; it belongs to the queue if the owner wants it as work.

### Deferred within the slice

Scheduled/automatic backups (the CLI is manual; §45 item 3 says
"automated" and a scheduler or shutdown hook is the natural next rung);
retention policy (§7.4 records expiration: nothing enforces one); a second
provider adapter (which triggers mandatory encryption per above); backup
of the backup manifest chain (parent stays null — full sets only).

---

## §49 — Directive E17, the half with a producer (2026-08-24)

TQ-03. Addendum 30 §26 (Directive E17): every agent SHALL expose a
behavioral version and certification state. Built: the half a producer
exists for.

**Behavior version.** `agent_registry.behavior_version` (additive, nullable
— NULL means a row written before the column existed, unknown rather than
current). Populated at both registration sites (agents/base.py, the
Controller's self-registration) from `backend/version.py` — the code-version
primitive *extracted from* simulation/harness.py rather than duplicated, so
the run manifest and the registry can never disagree about which code was
running. Its contract is "a true answer or 'unknown'": the sha is validated
before being trusted, dirty working trees are marked, and any failure —
git absent, a test environment with a faked subprocess layer — resolves to
'unknown', never to an exception in registration or a fabricated version on
record. Overwritten on respawn like pid, because it is a fact about this
life, not the durable career. Surfaced on `/admin/agents`.

**Certification state: deliberately not a column.** Certification in this
organization today is per-mission (missions certified complete) and
per-Alpha-gate; competency is earned per-dimension and refuses priors. No
machinery produces a per-agent certification state, and this repository's
own rule (the competency module's "a dimension nothing populates reads as
a capability"; §43's "the fields are §16's list, minus two with no
producer") says a defaulted `certification_state` column would be worse
than none: every agent would read CERTIFIED without anything having
certified it — assigning what addendum 30's whole §17–§18 insists is
earned. The column arrives with the machinery that writes it (a real
Evolution directive with training and evaluation behind it), not before.
The schema comment at the column marks this section.

### Verified

Five new tests (1607 passing): version recorded, overwritten on respawn,
NULL default meaning unknown, the sha-or-unknown format contract, and the
panel surface including the honest null. One defect found by the suite
itself: the first `code_version` used the harness's narrow exception list,
and tests that fake `subprocess.Popen` for spawn control blew up inside
registration — 17 errors, fixed by the broad-except-plus-validation
contract above, which is also the more honest reading of "never guesses".
Live: after restart, all six agents of the running organization report the
current commit with the `-dirty` marker (this increment was uncommitted at
the time — the marker doing its job).

---

## §50 — Security Defense §32 baseline: the audit (2026-08-24)

TQ-04. Addendum 28 §32's twenty pre-exposure requirements, audited
item-by-item against what is built. Statuses: **satisfied**, **partial**
(exists but not in the shape §32 describes; the missing piece named),
**absent** (a genuine gap), **n/a-until** (meaningless at the current
deployment shape; the trigger that changes that, stated). Claims below were
verified against the code in this pass, not recalled.

1. **Edge DDoS protection — n/a-until exposure.** Everything binds
   loopback; the Gateway's own spec keeps the host loopback-only behind a
   tunnel. Trigger: the first non-loopback exposure.
2. **WAF — n/a-until exposure.** Same trigger.
3. **API rate limiting — satisfied at the boundary.** The Gateway
   rate-limits login and WebSocket attempts per caller (in-memory by
   design, 429 with retry information, `gateway/exposure.py`), and
   `gateway/run.py` refuses `X-Forwarded-For` resolution so the bucket
   cannot be rotated by header. The backend has none — it is not the
   boundary and is loopback-bound.
4. **Origin not directly exposed — satisfied.** One externally-intended
   service (addenda 16–18's deliberate design), loopback host.
5. **MFA for administrative accounts — absent.** The Gateway Super User is
   single-factor bcrypt from the environment. Exposure precondition,
   listed below.
6. **No production secrets in Git — satisfied.** `git ls-files` shows
   `.env.example` only; `.env`, both stores, session files and `user_data/`
   are ignored (and now `backups/`, which is exactly as sensitive).
7. **Dedicated secret management — satisfied for the deployment class.**
   28 §8.2's local-development pattern, followed. A production secret
   manager is owed *with* production, not before it.
8. **Tenant-aware authorization — satisfied.** Fully isolated per-user
   permissions, preferences, and audit trails; multi-user isolation is
   tested.
9. **Central security audit logging — partial.** Per-user audit trails,
   organizational decision records with reasons, and Gateway login/limit
   logging all exist; what does not is §14.2's single normalized
   security-event envelope across them.
10. **Agent capability enforcement outside the LLM — satisfied.** The
    founding milestone: permission is checked in tool dispatch before data
    is touched, and the model never sees what a revoked grant protects.
11. **Tool Security Gateway — partial.** Tool dispatch enforces permission
    and forwarding consent server-side; there is no separate gateway with
    argument/destination validation, per-tool rate and cost limits.
12. **Production database isolation — satisfied.** SQLite files with no
    network endpoint at all.
13. **CI/CD protected — n/a-until CI exists.**
14. **Dependency and secret scanning — absent.** No CI to host it. Queued
    (TQ-09).
15. **Incident response playbook — absent.** Queued (TQ-08).
16. **Emergency credential revocation — partial.** Session revocation
    exists (logout, token store); provider-key rotation is a manual `.env`
    edit documented nowhere. Folded into TQ-08's runbook.
17. **Agent kill switch — satisfied.** `stop_requested` /
    `retire_requested` on the registry, Controller directives, and the
    watch escalation path: instance, role, or the whole population.
18. **Cost circuit breakers — absent, and not exposure-gated.** Nothing
    tracks model spend or stops a runaway loop from spending; the risk
    exists the moment a real API key does. Queued (TQ-10).
19. **Backup security contract — partial, newly.** §48's provider-neutral
    interface with integrity hashes; encryption and credential scoping
    activate with the first remote adapter, trigger recorded there.
20. **Restore trust verification — partial.** Integrity verification is
    built and fail-closed; §30's *security-gated* recovery has no security
    function to gate it yet.

**Exposure preconditions**, restated in one place so exposure can never
happen by drift: edge protection (1, 2), MFA for the Super User (5), a
production secret store (7), and the §14.2 event envelope (9) become
blocking requirements the day anything binds beyond loopback. Until then
they are declared debts with a named trigger, which is what §32 is for.

---

## §51 — The runbook (2026-08-24)

TQ-08, promoted by §50's items 15–16. `docs/INCIDENT_RESPONSE.md`: evidence
preservation first (a continuity backup *is* the evidence capture), the stop
procedure including §48's orphaned-population case, credential revocation in
escalating order (client sessions, Gateway sessions, the provider key at the
console — local deletion does not revoke a leaked key — and the Gateway
password), assessment against audit trails and `behavior_version`'s dirty
marker, restore through the fail-closed continuity path, and a required
written review. Two honest admissions in the document itself: user-password
force-reset does not exist (deleting the `users.json` entry is the crude
substitute, named as such), and the §50 exposure preconditions bound what
this runbook can promise. A documentation increment; no code, no test-count
change.

---

## §52 — The cost circuit breaker (2026-08-25)

TQ-10, promoted by §50 item 18 — the one absent baseline item that was not
exposure-gated: nothing stood between a runaway agent loop and the invoice.
`app/model_budget.py`: a `BudgetedProvider` wrapping any `ModelProvider`,
installed at the one place the real vendor is constructed
(`model_gateway.default_provider`), so every caller in every process —
agents, backend `/chat`, the Gateway's stream — spends against the same
budget.

### The decisions worth recording

- **A shared SQLite ledger (`model_spend.db`, one row per UTC day), not
  in-memory counters.** The organization is a population of processes each
  holding its own provider singleton; per-process counters would let the
  population collectively spend N times the budget. The §48 lesson,
  reapplied before it could become a defect.
- **Post-hoc accounting, pre-call refusal.** A call's true cost is known
  only from its response's usage report, so the breaker refuses the *next*
  call once recorded spend crosses a limit — damage bounded to the limit
  plus one reply, stated as the contract and pinned by a test.
- **The ledger holds what the provider said, never an estimate.** Usage is
  extracted with strict integer checks at both layers (the stream's final
  event now carries a `usage` field; a mock or partial object degrades to
  None — "not reported" — and is recorded as zero). An abandoned stream
  still counts as a call: the spend happened whether or not the caller
  finished reading.
- **Refusals are on the record.** Every refusal increments the day's
  `refusals` counter before raising, so "the breaker fired" is a queryable
  ledger fact. `/chat` maps the refusal to a 503 whose detail names the
  limit hit and the environment variable that raises it deliberately.
- **Real defaults, loud misconfiguration.** 500k tokens / 2000 calls per
  UTC day (a breaker off by default protects nothing), raised via
  `MODEL_BUDGET_DAILY_TOKENS` / `MODEL_BUDGET_DAILY_CALLS`; an unparseable
  limit raises rather than silently becoming the default — a typo must not
  become an unlimited budget.
- **Test providers installed via `set_provider` are deliberately not
  wrapped**: they spend nothing, and wrapping them would put fiction in a
  real ledger.

### Verified

Twelve new tests (1619 passing): ledger recording, call- and token-limit
refusal (the refused call never reaches the vendor), unreported usage as
zero-not-guessed, stream pass-through and abandoned-stream accounting,
cross-instance sharing, day rollover, malformed-limit error, the refusal
message's numbers-and-remedy contract, strict usage extraction, and the
`/chat` 503 mapping.

### Deferred within the slice

Per-caller attribution (the ledger is organization-wide; §19.2's per-account
economic telemetry needs an identity carried through the provider call);
dollar-denominated limits (tokens are what the provider reports; pricing
tables drift and belong in configuration when someone actually budgets in
currency); surfacing `todays_spend()` on the admin panel.

---

## §53 — The scanning habit, and its first catch (2026-08-25)

TQ-09, promoted by §50 item 14. `pip-audit` pinned in requirements-dev with
the cadence documented beside the pin (no CI exists to host it; the honest
minimum is a named manual habit — before each push that changes
requirements, and on picking the project back up after time away). The
first run found six known vulnerabilities in the environment's own pip
25.0.1 (PYSEC-2026-196 and five siblings); upgraded to 26.2.1, and the
environment scans clean. Worth recording less for the fix than for the
demonstration: the habit produced a real finding on its first execution,
which is the difference between a control and a checkbox.

---

## §54 — The Strategic Priority Register, machine-readable (2026-08-25)

TQ-05. `backend/register.py`, owning `strategic_register` in the house
module-owned-table pattern (created by fi_db.init_schema, additive
migrations wired), with admin routes: file a petition or mandate, read the
register with its queue view, transition with reasons.

### The boundary implementation drew

The queue entry said this store would "supersede the paper file."
Implementing it showed that would have been wrong: the *development* queue —
increments executed against this repository — and the *organization's*
register of proposals are different registers with different authors and
lifecycles. Development work must be recorded in the repository next to the
code it describes (`docs/TASK_QUEUE.md` stays authoritative there);
petitions and mandates are operational state and live in rows, where a
petition from an agent will eventually land (31 §5, the §22 intake
pipeline's substrate). Duplicating one into the other would have
manufactured two sources of truth — the Conflict Rule's exact target. The
register therefore starts *empty*, and that is correct: it holds what the
organization files, not what this file already records.

### The rules, enforced rather than described

- Vocabulary is fail-closed: category and flag are refused, not normalized,
  and **a Want cannot carry a priority flag** — 31 §2.2 makes the flag an
  escalation property of necessity, so storing one on a Want would corrupt
  the classification the whole doctrine hangs on.
- Parking transitions (blocked / deferred / declined) require a reason;
  **done requires a record reference** — G14's "passing is not
  implementation" as a NOT-NULL-in-practice, the pointer to where completion
  is verifiable.
- Duplicate open titles are refused naming the existing entry (31 §5.4
  consolidation); a closed entry frees its title, because re-raising a
  finished concern is a new proposal.
- `queue_order` is the doctrine, not a score: Needs before Wants, Needs by
  stated flag severity with unflagged below green (urgency someone stated
  outranks urgency nobody did), Quick-Win Wants ahead of other Wants
  (32 §15), filing order as the tie-break. A priority *score* — 31 §3 lists
  one — is deliberately absent: a scalar would wear authority nothing
  earned, and 31 §7 itself says no single number decides strategy.
- The filing route records the authenticated admin as origin (32 §9.2: who
  proposed the change is the first transparency field).

Fields from 31 §3 with no producer today (cost/impact profile → TQ-07;
champion, Board status, commission linkage → the deferred parliamentary
machinery) are absent, not defaulted.

### Verified

Eleven new tests (1630 passing): filing, both vocabulary refusals, the
Want-flag rejection, consolidation with title release, reason and
record-reference obligations, missing-entry error, the full ordering
contract (including blocked-stays-queued and closed-drops-out), filter
validation, and the routes (origin recorded, queue view leading with a
later-filed Need, refusals as legible 400s). One defect caught by the
existing suite: the module name `register` was silently shadowed by the
`/auth/register` route handler of the same name — aliased at import. And
one process note: a bulk PowerShell rewrite double-encoded the file's UTF-8
(§ → Â§) and was caught by inspection; the file was restored from HEAD and
re-edited with tooling that preserves encoding. The admin-auth surface test
grew its `entry_id` stand-in and still walks every route.

---

## §56 — The calendar detector gets its training world: ARB-012, cross-expiry (2026-08-25)

TQ-B2 unblocked — and its premise corrected first. §55 recorded ARB-012 as
blocked because "every ChainSnapshot is one expiry's ladder and the world
generates one expiry per scenario." Half of that was wrong: the world has
priced **three expiries per scenario from one (spot, r, q, skew) since Day
Zero** (`EXPIRY_DAYS = (7, 30, 60)`). What was genuinely missing was the
cross-expiry detector input shape, the clean-world guarantee *across*
expiries, and the wiring — recorded here so the blocked-entry's error does
not survive its own resolution.

### The detector: only what is actually proven

Addendum 27's ARB-012 warning ("never hard-code 'longer expiry always
costs more' ... apply only proven dominance rules") turned out to bind
harder than the first derivation respected. That derivation credited
PVDiv(T1,T2] to both sides' slack, valid for deterministic *cash*
dividends — and the clean-world property test immediately produced a
counterexample: the world's dividends are a proportional *yield*, and
`pv_div` promises a PV, not a model. What survives every admissible
nonnegative dividend process:

- **Puts, unconditionally**: P(K2,T2) ≥ P(K1,T1) − slack_p with
  slack_p = max(0, K1·DF1 − K2·DF2) and *no dividend credit* — the far
  put's model-free bound K2·DF(T1,T2) − S1 holds a fortiori under any
  dividend process, and the shortfall is constant in S1.
- **Calls, only on a dividend-free chain**: under a proportional yield the
  far call's bound loses S1·(yield term) and the shortfall is *unbounded*
  in S1 — no rule exists from prices and a PV alone. With far.pv_div == 0
  the slack is max(0, K2·DF2 − K1·DF1), which also covers negative rates
  (ARB-030). A dividend-bearing chain's call inversion is not scored at
  all — the spec's "otherwise classify as D" arm, left with the
  reference-data consumer §55 named.

Classification **C**: a genuine no-arbitrage breach whose monetization at
the near expiry's settlement has path complexity (liquidate the far leg at
its bound, or re-hedge into stock-and-carry) — nothing pretends the T1
realization is a contractual cash flow. `scan_calendar` is the cross-expiry
entry point, parallel to `scan_chain`; `_pair_coherence` makes mismatched
underlyings a caller error, not a reason code. `parity_events` grew
`expiry2_days` additively (and its convergence key grew with it — two
calendar packages at the same strikes differ only by their far leg).

### The world: a whole-ladder lift, and two §45-class findings

The genuine variant (`calendar_bump`) lifts every near-expiry cell's call
AND put mid by one constant — §45/§46's parallel-shift algebra one level
up: parity at every strike, every same-expiry cross-strike relation, and
the parity-implied dividend/financing all exactly invariant; only the
cross-expiry relations move. The trap (`calendar_spread_artifact`) erases
the same lift by widening the whole near ladder until `scan_calendar`
finds nothing. A third strategy (`options_arbitrage_calendar`) carries the
default curriculum; the evaluator's 'calendar' family grades any
same-expiry detection as its own named world failure
(`unexpected_same_expiry_hit`), distinct from a stray ARB-012 through the
wrong expiry pair.

Building it surfaced two findings of exactly §45's class — the world
generator's own properties, newly *visible* because the answer key learned
a new relation:

1. **The generator itself emits real calendar violations.** Each expiry's
   IV is drawn independently, and a steep term-structure skew genuinely
   violates the put calendar bound — invisible for as long as nothing
   checked cross-expiry. Clean-promise variants (none, every trap, and the
   calendar bump) now redraw their skew until the *rendered world*
   actually scans clean — `scan_chain` on every expiry plus
   `scan_calendar` across them — replacing shape-enumeration with the
   §46 discipline (verify with the organization's own scans). The trial
   render uses its own derived rng, so probing consumes nothing from the
   main stream and determinism is untouched.
2. **The mid-shift trap injectors leaked cross-expiry.** Their
   widen-until-clean loops verified one expiry's ladder; a widened cell
   whose bid still sat above a longer expiry's ask was invisible to them.
   All three (`spread_artifact`, `borrow_cost`,
   `cross_strike_spread_artifact`) now verify through
   `_surviving_through_cell` — the whole library over every expiry,
   filtered to packages trading the shifted cell.

### Wired end to end

Explorer's `_parity_work` runs `scan_calendar` over the same chains behind
the same min-edge lens (per-family lenses stay deferred per §46, until
grades distinguish families); the offline diagnosis differential grew the
same scan (a differential that skipped it would misdiagnose every calendar
miss as a world problem) plus family-aware agree-checks; the organizational
evaluation (`parity_evaluation`) walks the same family branch and the same
escalation ladder as the cross family.

### Verified

Eighteen new tests (1659 passing): the proven-rule arithmetic
hand-checked on both sides, the dividend-refusal and negative-rate slacks,
spread/cost adversarial cases, per-package hard stops, pair coherence,
clean-regime sweeps including the yield-heavy and negative-rate corners,
the whole-ladder invariance proven at detector level, world property tests
(bump fully detected with zero co-fire, both traps erased — the calendar
trap through the *existing* parametrized trap test, which picked the new
variant up automatically — determinism, strategy registration), Explorer
recording an ARB-012 event with both expiries, and the organizational
evaluation's PASS chain and named failure modes. Offline mission: a
10-scenario `options_arbitrage_calendar` run under the default mixed
curriculum — **10/10 PASS, COMPLETED, zero false positives**, calendar
material detected alongside parity, cross-strike, and four trap scenarios.

### Deferred, with reasons

A live-agent mission (real LLM) — this machine's API key is a placeholder;
the offline mission and the full agent-path tests stand in until a keyed
run. Per-detector-family lenses and difficulty progression, unchanged from
§46. ARB-013/014 (forwards), ARB-017/019/020 (American), per the queue's
blocked entries — the calendar increment does not unblock them.

---

## §57 — The live calendar mission, and the breaker meeting it (2026-08-25)

§56's deferred item, closed the same day: a real API key was configured (by
the owner; this record never saw it), and a five-scenario
`options_arbitrage_calendar` mission ran against the live organization —
real agents, real model calls — started through `missions.start_mission`,
the same function the mission-control route calls, under the process-owner
authority `app/admin_auth.py`'s own docstring describes.

**Seed 4, chosen deterministically in a dry run**: stale_quote,
calendar_bump, genuine, calendar_spread_artifact, stale_quote — both new
variants, three families. **Graded 5/5 PASS, certified complete, zero
corrective items.** Explorer detected exactly two packages: the ARB-012
put_calendar 7d-vs-30d at strike 145 on the lifted world (net
$3.49/share), and the ARB-001 conversion on the parity world (net
$0.05/share, ARB-001-preferred as always). All three traps stayed silent.
Both escalations were cross-checked, reported, and analyzed by the real
model into genuinely skeptical theses (confidence 0.32 and 0.35 — the
analyst *distrusting* a class-C bound and a thin class-A margin is the
discipline working, not a defect).

### The breaker fired first, and that is a feature meeting its spec

Mid-mission, analyses stopped landing. Not a bug in the mission: §52's
cost circuit breaker had tripped — the live organization had spent 502k
tokens across 106 calls inside the UTC day, crossing the 500k default, and
the ledger recorded **625 refusals** while Analysis kept claiming reports
it could not pay for. The remedy was the breaker's own documented one:
`MODEL_BUDGET_DAILY_TOKENS` raised deliberately (to 2M, in `.env`, with
the reason written next to it), backend restarted, pipeline completed in
~3 minutes. Worth recording as measured fact: this organization's routine
loops spend on the order of the old default in about an hour of live
operation — the number the default should be recalibrated against, now
that one exists.

### The finding the live model caught, and its fix

The SYN5 thesis, unprompted: "only one expiry_days (7) is reported for
both legs ... evidence that the 'calendar' structure is misidentified."
Correct — Explorer's escalation question and requester_finding carried
only the near expiry, so the analyst was judging a two-expiry package
shown one expiry. Fixed in the same increment: the question now reads
"expiring in 7d vs 30d" for calendar packages and the finding carries
`expiry2_days`; the Explorer test pins both. The §46 pattern repeating —
the live model's skepticism finding a real seam the offline tests could
not, because the seam was in what the model itself gets shown.

### Verified

1659 tests still passing after the fix (the explorer test grew two
assertions). Live artifacts: mission row COMPLETED, evaluation and
diagnosis cached on it, both theses in `analysis_results`, and the spend
ledger carrying the whole story — 106 calls, 502k tokens, 625 refusals,
then the deliberate raise.

---

## §58 — The origination cooldown: attention priced, not throttled by sleep (2026-08-25)

Owner-directed: §57's measured fact (~500k tokens/hour of idle operation)
was too much. Tracing where it went: the synthetic social stream clears
Speculator's confidence bar nearly every cycle, and the moment a
security's paid chain (cross-check → stance read → report → Analysis)
completes, the next cycle re-originates it — the in-flight guards
(`has_open_cross_check`, pending report, open case) only ever spaced the
chains at pipeline latency. Explorer's IV path had the same shape behind
its judgment gate, and the parity path's 300s window let a *completed*
mission's lingering static world re-buy two analyses every five minutes
indefinitely.

### The mechanism

`ORIGINATION_COOLDOWN_SECONDS` (`FI_ORIGINATION_COOLDOWN_SECONDS`,
default 3600, agents/discovery_config.py): minimum spacing, per security,
between paid analysis chains that routine observation may originate.
Deliberately a separate constant from the 300s
ANALYSIS_RECENCY_WINDOW_SECONDS (which stays for Analysis's own
novelty/diagnosis reads): that one deduplicates; this one bounds
*attention*. Applied at all three origination points — Speculator's social
loop, Explorer's IV loop (checked before the judgment gate, so the gate's
own call is not re-bought either), and Explorer's parity loop (widened
from 300s: a static chain deserves one paid analysis per security per
cooldown — grading needs exactly one, and re-analyzing an unchanged world
never changes the answer). Observation stays free everywhere: evidence
recording, case enrichment, and detector events are deliberately not
gated; cross-check *answering* is never gated (it only runs when someone
bounded already asked). Missions are unaffected in what they need — one
analysis per scenario — and the mission-path Speculator loop never
originated anyway.

### Verified, including a false start worth keeping

Three new tests (1662 passing): Speculator suppressed under a recent
analysis with evidence still recorded, the cooldown-zero override behaving
as documented (the §-first-commit strict comparison making a zero window
match nothing), and Explorer skipping the judgment gate entirely while
still logging the detector event. Then the live verification produced a
lesson: the first measurement showed originations slipping through
milliseconds after analyses landed — not a code defect but a **stale
pre-edit agent generation** the restart's process-matching had missed
(some processes hide their command line from WMI; the kill filter now
also matches those). A direct probe settled it: one real Speculator cycle
against the live database, guard on — zero originations; same cycle,
cooldown zeroed — eight. Clean restart, measured again: the first window
drained the small backlog (6 calls), and the steady-state window read
**zero calls, zero tokens over four minutes**, against §57's ~33
calls/hour before.

The ceiling this sets: at most one paid chain per security per hour —
about an order of magnitude under the measured idle burn, tunable in
either direction through the environment variable without touching code.

---

## §55 — Phase 2 opens with the two members that have data: ARB-015/016 as Diagnostics (2026-08-25)

TQ-06, scoped honestly before it was built. Addendum 27 §11's Phase 2 list
runs 014–025; auditing each member against what the system actually
produces: **ARB-014** needs the same forward/futures instruments ARB-013
does (blocked, same reason); **ARB-012** needs a second expiry no
ChainSnapshot carries — a world-design increment, not a detector increment;
**ARB-017/019/020** need American worlds `STYLES` deliberately refuses.
What remains buildable now is the pair the spec itself marks as signals
rather than trades: ARB-015 (option-implied dividend, "difference alone is
not arbitrage") and ARB-016 (implied financing/borrow basis, "usually B/D
rather than A").

### A separate schema, because the spec demands one

Addendum 27 §8 requires "schema-level separation of D from arbitrage." So
these are not Opportunities with a D stamp: a new `Diagnostic` type — no
edge, no direction, no capacity — and its own entry point,
`diagnose_chain`, parallel to `scan_chain` and deliberately absent from it.
A test pins that scan_chain's output can never carry a diagnostic detector
id, whatever the chain contains.

### The executable band, not the mid-price gap

What a diagnostic tests is whether a *declared* reference input (pv_div for
015, r for 016) lies outside the entire interval of values consistent with
executable bid/ask quotes. A mid-price difference smaller than the spread
is the market saying nothing, and reporting it would readmit the exact
error the library's opening rule exists to forbid, in diagnostic clothing.
Corollary, pinned by test: widening spreads can only widen the band —
quote uncertainty weakens a signal and can never manufacture one, the
diagnostics restatement of "adverse bid/ask cannot improve edge."

### ARB-016's interpretation rule

Borrow is required reference data for 016 not because the arithmetic needs
it but because the interpretation does: an implied-financing basis on a
stock with unknown borrow state cannot distinguish "mispriced" from "hard
to borrow" — the spec's own warning. Missing borrow is a refusal (§10),
and when the fee is present, `borrow_explains_gap` reports whether r minus
the declared fee falls inside the implied band — the spec's B-versus-D
distinction carried as evidence rather than as a classification upgrade,
since no locking package exists either way. A non-positive implied
discount factor is reported as a broken input, not a financing signal.

### Verified

Eleven new tests (1641 passing): the coherent-chain control (zero
diagnostics on a BS-coherent world), hand-checkable band arithmetic for
both detectors, within-band silence, the spread-widening property, hard
stops before arithmetic, the borrow-explains-gap evidence in both truth
values, missing-borrow and broken-DF refusals, chain-level ordering by
gap, and the schema-separation pin.

### Not wired into the training loop, with the reason stated

Explorer escalates opportunities; the Evaluator grades detections of
injected tradeable structures. A D-class diagnostic is neither — injecting
a "misdeclared dividend" scenario would surface through ARB-001's parity
package anyway (a dividend error *is* a parity shift once it exceeds the
band), so a diagnostic mission would either duplicate parity training or
train agents to escalate non-tradeable signals. Diagnostics get a consumer
when reference-data validation wants a market-implied cross-check on its
declared dividends and borrow — that consumer is named here as the natural
next increment, not presumed built.

---

## §59 — The backup grows a pulse, a memory limit, and a copy that leaves the machine (2026-08-25)

§48 built the recovery copy and recorded three honest gaps in it: backups
happened only when a human remembered to run the CLI, every set lived on
the same disk as the originals, and nothing ever deleted anything. This
increment closes all three, which is addendum 29 §45's "automated backup
of critical persistent state SHALL exist" finally meaning *automated*.

### The policy, four environment variables

All resolved at call time, all fail-loud through the `model_budget._limit`
contract (a typo'd policy value refuses rather than silently becoming the
default): `CONTINUITY_BACKUP_INTERVAL_SECONDS` (default 21600 — six hours,
a disclosed convention recorded in TIMING_CONSTANTS.md, not a measured RPO
requirement; 0 disables automated continuity entirely),
`CONTINUITY_RETENTION_COUNT` (default 14 complete sets per destination;
zero is refused — keeping no backups is not a retention policy),
`CONTINUITY_SECONDARY_ROOT` (unset means no secondary — the module cannot
invent where the second disk is), and `CONTINUITY_KEY_PATH`.

### The loop, and the shutdown backup

`_backup_loop` runs as a third asyncio task in the backend lifespan,
sleep-first, cycle in a worker thread (hashing user_data/ must not stall
the event loop the Controller shares), every failure printed and survived
— a backup loop that dies once, silently, forever is §1.8's "silently
weakened recoverability" in its purest form. The clean-shutdown path takes
one more backup *after* every writer has stopped, so the interval-sized
RPO window only ever spans a crash. The CLI keeps working regardless;
`backup` now runs the full cycle (all destinations, then retention).

### Retention prunes in the mirror of creation order

`prune_backups` deletes each doomed set manifest-first: §48's manifest-last
create ordering defines files-without-a-manifest as "not a backup", so an
interrupted prune leaves debris that is already invisible to listing,
verification, and restore. The same invariant that makes an interrupted
create harmless makes an interrupted delete harmless. Incomplete sets are
deliberately not prune's to touch — they may be a create in progress.

### The secondary is encrypted unconditionally, closing §48's deferral

§48 deferred encryption-before-upload (29 §10.1) *because* the only
adapter stayed in the primary failure domain. A secondary destination
exists precisely to leave that domain, so the moment the deferral's reason
stops applying, so does the deferral: there is no plaintext-secondary
option. `EncryptedProvider` wraps any provider the way BudgetedProvider
wraps the model — put/get are the only places bytes cross the boundary, so
manifests, verification, and restore work unchanged, and the destination
never holds decryption authority (§10.2). Manifest hashes are of the
plaintext, which is what makes a primary set and a secondary set of the
same files carry comparable integrity records. An unreadable file — or an
unreadable manifest — is a verification *finding*, not a crash, and the
fail-closed restore refuses on it exactly as on a hash mismatch.

The key (`ensure_backup_key`, gitignored, generated loudly on first use)
is Tier-0 recovery material: §10.3 stated bluntly, a perfectly encrypted
backup with a lost key is not a backup. A copy belongs OFF this machine,
because the disaster that takes the primary disk takes the key with it.

### Two destinations that share a failure mode are not two failure domains

`run_backup_cycle` isolates destinations from each other: a full secondary
disk costs exactly its own copy, never the primary's, and the outcome —
including the failure text — lands in a per-destination summary the loop
prints. Config errors that precede the per-destination split (an
unreadable key file) fail the whole cycle loudly and are survived by the
loop wrapper.

### Verified

Twelve new tests (1672 passing): fail-loud policy parsing including the
0-interval/0-retention asymmetry, key generation loud-once-then-silent,
ciphertext at rest with plaintext roundtrip, the full create → verify →
restore → reopen-and-read exercise through the encrypted path (§1.4
applies to the secondary too), wrong-key as a per-file and whole-manifest
verification failure with restore refusing, retention keeping the newest
sets with no orphan files and no authority over incomplete sets, the
two-destination cycle with plaintext primary / encrypted secondary proven
different at rest and the secondary proven restorable, retention enforced
each pass, and destination-failure isolation. Live smoke test against the
real backup domain: full cycle to two scratch destinations, secondary
listed, verified intact, and restored through `--secondary` — the CLI
flag that exists because an encrypted copy nobody can restore from the
command line is not a recovery asset.

### Still deliberately not done

Incrementals (`parent` stays null — full sets at this data size),
per-destination retention counts, a remote provider (the interface §48
built is still what makes one an adapter rather than a redesign), and
backup of `.env` (§48's exclusion reasoning stands: secrets recover by
re-issuance, not restore).

---

## §60 — The learning machinery arrives: four documents, and the owner points at the engines (2026-08-25)

Four documents supplied 2026-08-25, forming the Organizational Doctrine
lineage's second set (34–37): the Training and Monte Carlo Simulation
Framework (34), the Multi-LLM Enterprise Strategy (35), the Department of
Education (36), and Evolution's Continuous Optimization addendum (37).
Assimilated verbatim per convention; precedence row and index block added
to `docs/README.md`; the work they generate is queued below and in
`TASK_QUEUE.md`. Together they describe how the organization *learns*:
need → governance → curriculum → simulation → training → certification →
controlled rollout → predicted-versus-actual review. Nearly everything is
roadmap, and the honest dispositions below say what already exists under
other names.

**The owner's priority decision, recorded as Strategy acting through the
Board (31 §3):** among the work this set generates, the Reference Data
Engine and the Simulation Engine come first. That is also what the
lineages themselves would choose — every blocked detector family (TQ-B1,
TQ-B3) waits on world capabilities, and §55 already named reference-data
validation as the diagnostics' natural first consumer — but it is
recorded here as an owner directive, not an inference.

### Boundary dispositions

1. **34 (Training/Monte Carlo) against 13 (the built training loop) and 25
   (the built training world).** The disposition shape of §47's 30-vs-13
   ruling, extended: **13 governs the built loop, 25 governs the built
   world**, and 34 is adopted as the direction both evolve toward. Against
   34 §20's maturity path, the built system stands at stages 1–2:
   single-agent skill drills (missions, evaluation, certification) exist;
   scenario provenance and seed-reproducibility exist (the continuity
   backup's own exclusion rule relies on runs being reproducible from
   scenario + seed + code version); pairwise collaboration exists in
   *mechanism* (cross-checks, UQI) but is neither drilled nor scored. What
   34 concretely demands next is world capability — instruments, events,
   noise, rare-and-ordinary periods — which is addendum 25's scope and
   exactly where the blocked queue already points (TQ-B1's forward leg,
   TQ-B3's American worlds). TQ-14.

2. **35 (Multi-LLM) against 16 §24 and the built provider layer.** The
   principle AGENT != MODEL is already load-bearing: `app/model_provider.py`
   exists because addendum 16 §24 forbade a "Claude Gateway", callers walk
   plain dictionaries rather than SDK types, and the vendor is constructed
   in exactly one place (where §52's budget breaker wraps it). But the
   system is single-provider, single-model in fact: `MODEL` is one
   constant, there is no registry, no per-agent-class requirement profile,
   no routing, no fallback. 35's own discipline governs the increment:
   default mappings are provisional hypotheses, and 30 §12 says metadata
   and policy before code — so the first increment is the **Model
   Registry and Model Requirement Profiles as data**, populated with
   today's one honest row, not a routing engine with one route. TQ-16.
   Routing, fallback, and the migration lifecycle activate when the
   registry holds a second model worth routing to.

3. **36 (Education) against the built loop.** The Curriculum Architect's
   *function* — versioned knowledge, deciding what agents train on,
   refining it on evaluation evidence — exists distributed across the
   addendum-13 machinery (versioned strategies, peer groups, the
   training/evaluation/certification records). No agent holds the role,
   and at the current population the §47 precedent applies: new
   departmental machinery waits until a real curriculum need the existing
   loop cannot express. What is genuinely new and actionable now is 36
   §8's substance: **collaboration as a scored competency**. The
   organization already produces the raw material (cross-check questions
   and answers, UQI latencies, answer usefulness is graded nowhere) and
   34 §17 supplies the dimensions. A measurement-first increment — score
   what already happens before drilling what doesn't — is queued. TQ-17.
   The professor layer defers itself (36 §2.3); the Speculator curriculum
   (36 §10) waits on the collaboration scoring it would be graded by.

4. **37 (Optimization) against §52 and §58.** The addendum names a
   discipline the repository has already practiced once, end to end: §58
   *was* an optimization act — measure (~500k tokens/hour), hypothesize
   (chains re-bought at pipeline latency), change one bounded thing (the
   origination cooldown), measure again (zero steady-state), record. O7's
   predicted-versus-observed comparison happened in miniature. What is
   missing is the *substrate* for doing this continuously: the spend
   ledger is per-UTC-day and process-wide, and §52 explicitly deferred
   per-caller attribution. That deferral now has its consumer — 37 §3.1's
   "measure organizational resource use" — so it is promoted to the
   queue. TQ-18. A dedicated Optimization Agent waits with the rest of
   the departmental machinery; O1–O9 are adopted as doctrine now.

5. **The leadership gate (34 §18, 36 §9, 37 §9), stated three times in one
   day.** The set's most emphatic rule — collaboration is a hard
   promotion gate — currently has nothing to gate: no promotion machinery
   exists. Recorded as a standing constraint that binds the day promotion
   machinery is built, so it cannot be built without it.

6. **34 §3 / 35 §9 (multi-viewpoint governance debate) against §47's
   parliamentary deferral.** Same deferral, same reason, unchanged: at
   the current population, staged debate would be ceremony. The new
   detail worth keeping — model *diversity* as a debate mechanism, and
   model identity never substituting for evidence — is recorded here for
   the day the parliament exists.

### The queue after assimilation

TQ-13 (this work, done). Owner-directed head of the queue: **TQ-14**
(Simulation Engine: grow the training world the capabilities the blocked
detector families need, forward instruments first — unblocking TQ-B1 —
stepping toward 34's event-driven environment) and **TQ-15** (Reference
Data Engine: the §55-named increment — validate declared dividends and
borrow against the market using ARB-015/016, addendum 24 §6's validation
duty meeting its first market-implied cross-check). Then TQ-16 (Model
Registry as metadata), TQ-17 (collaboration scoring baseline), TQ-18
(per-caller spend attribution). Deferred with reasons in the queue:
Education's departmental machinery, the professor layer, routing/
migration machinery, the Optimization Agent, staged debate, and the
leadership gate's enforcement point.

---

## §61 — The world grows its first new instrument, and Phase 1 closes (2026-08-25)

TQ-14's first scope item, owner-directed to the head of the queue in §60:
the training world now lists forwards, and the two detectors that price
against them exist — ARB-013 (forward vs synthetic forward), the last
unbuilt member of addendum 27 §11's Phase 1 list, and ARB-014
(cash-and-carry) from Phase 2. TQ-B1 resolves: what blocked both detectors
since §45 was never detector work, and the moment the world could price a
forward, the detectors were an afternoon.

### Instrument existence is a world fact, made per scenario

The deep decision of this increment, found before any code was written: a
fair forward CANNOT simply be added to every scenario. A forward completes
the market — ARB-013's packages trade options against the forward with no
stock leg at all — so beside a `borrow_cost` trap (a parity gap
unprofitable only because the reversal needs stock borrow), a fair forward
makes the trap's own signal genuinely arbitrageable, and the trap's "zero
detections" promise becomes a lie. That is §46's lesson (injectors leak
into whatever relations the answer key learns to check next) surfacing at
the *design* stage instead of the verification stage, and the resolution
is honest rather than clever: forwards exist only in the four forward
variants' scenarios. Single-stock forwards being listed or not is a fact
about a market, not a defect — and `test_mispriced_forward_leaves_the_
option_scan_silent` pins the finance that forced the decision.

### The four variants, and what each proves

`forward_bump`/`forward_dip` shift one expiry's forward mid off fair (rich
/ cheap) with the chain untouched — so parity, cross-strike and calendar
relations are all *exactly* invariant (nothing they price moved; no
algebra to defend, unlike the lift variants) and what moves is exactly
what ARB-013 (per strike) and ARB-014 (vs the underlying) price. The
injectors verify through the organization's own `scan_forward` that the
shift fired at the target expiry in a direction its sign explains
('sell_forward'/'carry' for rich, 'buy_forward'/'reverse_carry' for
cheap) and nowhere else. `forward_spread_artifact` is the trap: the same
shift, erased by widening the forward's own spread until scan_forward
finds nothing — a mid off fair that the executable band swallows.
`forward_none` is the clean control WITH the instrument: fair forward,
clean chain, zero expected detections, verified at build time — the
false-positive material plain 'none' cannot provide, because plain 'none'
has no forward to be fooled by. Ground truth records the deviation
*signed*: what was done, not just its size.

### The detectors, under the discipline

Executable sides only, verbatim from the spec: synthetic long = Cask −
Pbid, short = Cbid − Pask, all edges in PV per share. ARB-013 is
classification A in both directions — European, deterministic carry, no
stock leg, no borrow — which is precisely the market-completion fact
above. ARB-014's 'carry' is A (long stock needs no borrow); its
'reverse_carry' is B with the borrow cost explicit (Sbid·fee·T, ARB-001's
own convention) and 'missing_borrow' recorded when the fee is unknown —
never priced at zero. `ForwardQuote` is a *forward*, deliberately: the
variation-margin and convexity adjustments addendum 27 requires for
futures are structurally zero here rather than silently omitted, and a
futures adapter owes them before reusing these detectors. dated pv_div
enters the carry directly ("not blindly S·exp((r−q)T)" — the spec's own
warning, pinned by test).

### Wired everywhere the calendar family is

The answer key runs scan_forward when the scenario lists forwards; the
observation payload carries them additively (key absent — not empty — for
every pre-increment stored world); `providers/stored_data.py` grew
`forward_quotes`; Explorer scans them behind the same min-edge lens; the
evaluator (offline and stored-run both) grades the new family with its
own named world-integrity failure ('unexpected_chain_hit': an
option-relation package on a chain the shift never touched); and
diagnosis routes it with the same offline-rescan differential. One
deferral inside the wiring, recorded here: `parity_events.strike` is NOT
NULL and ARB-014's package genuinely has no strike, so Explorer scans
both detectors but escalates only strike-carrying packages — on any real
forward mispricing ARB-013 fires beside ARB-014 at every strike whose
synthetic disagrees, so no signal is lost; the schema change waits until
an ARB-014-only signal can actually occur.

### Verified

Thirty new tests (1703 passing): hand-checkable arithmetic for
all four directions at r=0, the fair-forward silences, borrow refusal and
explicit borrow charging, the no-borrow classification-A pin, spread
widening only shrinking edge, hard stops and coherence errors,
scan_forward's pairing/no-op/caller-error contract, the
per-variant instrument-existence rule, the clean-world guarantee across
seeds, bump and dip detected by exactly the forward detectors in exactly
the expected directions, the trap erasing with the mid genuinely off
fair, seed reproducibility, payload roundtrip and additive-absence, every
evaluator branch of the new family, and the strategy's default mix
running end to end.

### What TQ-14 still holds

The forward leg was scope item one. Event-stepped scenario shape (34 §6:
State(t) + Event(t) → State(t+1)) remains queued under TQ-14, and the
American-style world (TQ-B3) remains a larger, separate increment.
ARB-013/014 against *futures* (margin, convexity) waits for a futures
instrument with a reason to exist.

---

## §62 — The market becomes a source: reference data meets its first outside witness (2026-08-25)

TQ-15, owner-directed second in §60's ordering, and the consumer §55 named
the day ARB-015/016 were built: reference-data validation now cross-checks
what the organization *declares* about dividends and financing against
what executable option quotes *imply* — the Reference Data Engine's first
check against anything other than this database's own consistency.

### The market as a registered source

`market_implied` joins `reference_sources` as a `derived` source, ranked
below every declaring source on purpose. The reasoning is the spec's own
sentence read in both directions: "difference alone is not arbitrage" —
and difference alone is not proof the declaration is wrong either. A
diagnostic can mean a bad declaration OR a mispriced market, and nothing
at this layer can tell which; so the market never overwrites, it only
disagrees, and the disagreement lands where every disagreement in this
engine lands: `reference_conflicts`, append-only, addendum 24 §13's "a
disagreement is data, not something to hide."

### One disagreement, many witnesses

`diagnose_chain` reports per strike; the *declaration* is per (asset,
field, expiry). Twenty strikes flagging the same declared pv_div are one
disagreement with twenty witnesses, so findings aggregate to the max-gap
strike with the witness count carried (`n_strikes`), and one conflict row
records each distinct fact. Dedup is `ingest`'s own discipline verbatim —
once per distinct disagreement, not once per run, so the every-startup
certification adds nothing against an unchanged observation — while a
*changed* band (a new observation moved the market) is a new fact and a
new row. `market_implied_conflicts(conn)` is the read side for whatever
consumes this next.

### Read/write split, and what never happens

`validate()` stays read-only — it reports the cross-check as a new
`market_implied_consistency` check but records nothing; the recording is
`certify_readiness`'s (the function that already writes), placed before
validate() runs so the conflicts count the same certification reports
already includes its own discoveries. Three things deliberately never
happen: a market disagreement never blocks readiness (ok=True always, the
`unresolved_conflicts` discipline), never flips `validation_status`
('invalid' means structurally broken, which a healthy record with a
contested dividend is not), and a cross-check *error* on one malformed
observation never takes down certification — the asset is named in the
check detail and the engine certifies on, because blocking the whole
organization's startup on one broken stored payload would be the outage
the engine exists to prevent.

### Activation is data presence

No stored chains — including the observations table not existing at all —
is "nothing to cross-check yet", not a failure: the check activates the
way `providers/stored_data.py`'s adapters do. The chain reconstruction is
that module's own `chain_snapshots` (lazy-imported at call time, the
layering-preserving idiom), so the cross-check reads the market through
exactly the translation Explorer trades through, not a copy that could
drift.

### Verified

Eight new tests (1711 passing): the nothing-to-cross-check silence, the
clean-world control (the world's own chains agree with their own carry by
construction), a misdeclared dividend found/recorded/aggregated to one row
per (asset, field, expiry) and deduplicated across re-certifications, a
misdeclared rate under its own field via ARB-016, readiness and
validation_status both untouched by disagreement, a moved market recorded
as a new fact, a malformed observation named-not-fatal, and the source
registration with its deliberate bottom rank.

---

## §63 — The world learns to tick: State(t) + Event(t) → State(t+1) (2026-08-25)

TQ-14's remaining scope, closing the owner-directed head of the queue: the
Market Data Simulation Engine's first step from frozen moments toward
addendum 34 §6's Monte Carlo shape. A scenario can now be a *timeline* — a
short sequence of complete world states over simulated time, under a new
`options_arbitrage_timeline` strategy with its own default curriculum.

### The event vocabulary of increment one

Three events. `market_drift`: every step after the first, the spot takes a
small seeded step (bounded well inside the spread basis, a disclosed
convention) and every instrument reprices from it consistently — ordinary
movement in which nothing is mispriced, which is 34 §7's "ordinary periods
where nothing interesting happens" finally rendered with the market
actually moving rather than frozen. `opportunity_onset` /
`opportunity_resolution`: the scheduled variant's injection appears at a
drawn step (never step 0 — a world that starts broken has no onset EVENT,
and the event is the point) and disappears at a drawn later step, which
may be past the end of the watched window: not every opportunity resolves
while you are looking. Detection now has a WHEN.

### Nothing new to trust

The deliberate architecture: every step IS a `ScenarioWorld` with its own
honest ground truth — the scheduled variant while live, the clean control
while quiet — so per-step grading is the *existing* `evaluate()` and
`answer_key()`, unchanged. "Found while live, silent while quiet" is the
same PASS the static grader already defines, inherited rather than
reinvented; a timeline passes only when every one of its moments does.
Injection reuses the static injectors verbatim (each already verifies
through the organization's own scans), with the injection stream recreated
from one per-scenario salt at every live step so the drawn target is
identical across the window: one persistent opportunity, not a new one
per step. The per-step deviation is recorded per step, because the floor
under it drifts with the spreads.

### Three world-honesty decisions

1. **The ladder is fixed at step 0.** Listed contracts do not re-strike
   because the underlying drifted, and a ladder that followed the spot
   would erase the very moneyness drift a stepped world exists to
   exhibit. (`_build_rows` grew a fixed-ladder override rather than a
   parallel builder.)
2. **A forward-scheduled timeline lists its forward at EVERY step** —
   fair when quiet (the step ground truth is §61's `forward_none` clean
   control, reused exactly), shifted when live. An instrument that
   appeared exactly when mispriced would teach the spurious correlation
   "forward listed ⟹ opportunity", which no market exhibits.
3. **Only genuine variants and the clean control are schedulable.** A
   trap's teaching value is in its look, not its timing; the static
   curriculum already carries every trap, and the mix is refused — not
   silently degraded — if it draws one. Chatter is likewise absent from
   timeline steps: the Speculator-side timeline (chatter that leads, lags,
   or contradicts the moving market) is its own increment, and empty
   chatter is honest where synchronized chatter would be invented.

The clean-skew redraw generalizes with the shape: every timeline (quiet
steps promise zero detections) redraws until the candidate skew renders
clean at EVERY step's drifted spot, against the actual fixed-ladder rows,
through scan_chain, scan_calendar, and — on forward schedules —
scan_forward. Sub-day steps only (`step_seconds` validated < 86400):
integer expiry_days held constant across a timeline is honest for minutes
and hours and a lie for days.

### The stored sequence, and its named consumer

`store_timeline` writes one option_chain Observation per step, so
Explorer's `latest_chain` returns the newest state of a market that
moves, and `replay` preserves the whole sequence; the summary records the
full schedule (variant, onset, resolution, per-step ground truth). The
consumer that joins an agent's detection timestamps against that schedule
— grading detection LATENCY, the thing a static world cannot measure — is
named here as the natural next increment, not presumed built.

### Verified

Sixteen new tests (1727 passing): strategy registration and mix validity,
step-shape validation including the sub-day bound, trap schedules refused,
window/event geometry, whole-quiet timelines silent with the run honestly
reporting RETRY_REQUIRED (a run that never exercised its material says
so), spot drifting while the ladder holds and time strictly advancing,
every schedulable variant detected exactly in its window (parametrized
across all five), fair forwards at every step of a forward schedule, one
persistent target across a live window, seed reproducibility of entire
timelines, and the stored sequence giving Explorer the newest state with
the distinct-asset constraint enforced. The first end-to-end smoke: 6
timelines, 48 steps, every moment graded PASS.

### What remains beyond this increment

Addendum 34 §6's fuller trial vocabulary — provider outages, delayed and
missing data, agent unavailability, deceptive information, collaboration
events — and its stages 3–9. Each is its own increment with its own
consumer; the state-transition shape they all need now exists.

---

## §64 — The Model Registry arrives as metadata, with a tripwire instead of a router (2026-08-25)

TQ-16, built exactly at the altitude §60's disposition 2 prescribed:
addendum 35's Model Registry and Model Requirement Profiles as *data* —
`docs/model_registry.yaml`, under `organization.yaml`'s discipline — with
no routing engine, because a routing engine with one route is machinery
without a decision to make.

### One honest row

The registry holds the model reality that runs: `claude-sonnet-5` behind
`AnthropicProvider`, cloud, tools, streaming, the §52 breaker's daily
budget as its only cost facts, and an `observed` block carrying exactly
what this system has measured (§57's idle burn, §58's post-cooldown zero,
§42's ~2min deep call, TIMING_CONSTANTS' UQI latencies), each entry
naming where the measurement lives. Everything unmeasured — context
window, capability scores, hallucination rate, rate limits — is *listed
as unmeasured and carries no number*, and a test enforces that: a
spec-sheet figure would be the vendor's claim wearing this file's
authority, which is exactly the empirical discipline 35 §3 asks for read
strictly.

### Six profiles, one per real consumer

Not per agent class in the abstract — per code location that actually
reaches the model: analysis (deep reasoning + challenge), explorer (the
judgment gate), speculator (stance reads), introspection (UQI answers —
a capability, not a role), and the two chat surfaces. Each carries task
type, criticality, latency tolerance, the preferred model, an honestly
empty fallback list, and a `call_shape` that binds every declared call to
the constant that sizes it (`ANALYSIS_MAX_TOKENS` = 4096, and so on) —
the TIMING_CONSTANTS drift guard applied to call sizing.

### The two teeth

What makes this a registry rather than a document: **the consumer scan**
— the test greps every source file for calls into the model interface
and requires the consumer set to equal the declared profile set, so a
new model consumer fails the suite until somebody writes down what it
needs from a model (organization.yaml's known_gap discipline, applied to
model consumption); and **the routing tripwire** — `routing:
none_single_model` is pinned, the test asserts exactly one configured
model while it stands, and registering a second model therefore FAILS
the suite with a message pointing here. 35 §7's router, fallback chains,
and the §10 migration lifecycle activate through that deliberate
revisit, never by drift. 35 §2 is likewise enforced rather than stated:
every model and profile is `provisional: true`, and the flag comes off
only when a `benchmark_date` and evidence go on.

### Verified

Eight new tests (1735 passing): parse and shape, the single-model
reality matching `DEFAULT_MODEL`/`MODEL`/the provider class, budget
facts matching the breaker's constants, universal provisional flags,
unmeasured-means-no-number, profiles referencing registered models and
real ROLE_CHARTERS roles with empty fallbacks, call shapes matching
their sizing constants by import, and the consumer scan closing over
agents/, backend/, app/, and gateway/.

---

## §65 — Collaboration gets measured before it gets taught (2026-08-25)

TQ-17. Three of the four new addenda make collaboration the organization's
highest-priority competency and a hard leadership gate (34 §16–§18, 36 §8–§9,
37 §8–§9). This increment does the half that is honest today: **measure the
collaboration that already happens**, before building drills for what does
not.

### Two dimensions, from records nobody had to invent

`backend/competency.py` grows `collaboration_responsiveness` (cross-checks
addressed to a desk's role that got an answer) and `uqi_responsiveness`
(Universal Query Interface questions to its identity that got one). Both
read records the organization has written since the Discovery Slice — no
new table, no new writer, nothing that would be the "table nothing writes
to" error this codebase refuses elsewhere. The module's own note about
which dimensions it cannot compute moved with the code rather than being
left to rot: the collaboration pair arrived exactly when its mechanisms
did, and handoff completeness still has none (a report does not name the
cross-check it grew from, so requester-side follow-through has no
queryable linkage — named, not silently omitted).

### What "responsive" means, and where that judgment lives

Two vocabulary decisions, both taken from `fi_db`'s own constant block
rather than invented here. **`no_evidence` counts as an answer**: a
responder that looked and found nothing has said something informative,
and scoring it as a failure would teach agents to stay quiet rather than
report an empty hand. **Latency folds into the rate**: the timeout
machinery (`expire_stale_cross_checks`, `expire_stale_uqi_requests`)
already marks a slow answer `unanswered`, so answered-at-all *is*
answered-in-time and no separate latency score is needed. The
answered/unanswered judgment is made in `fi_db.competency_evidence`,
where the status vocabulary lives; `competency.py` receives
`{'answered': bool}` and only counts — the same split that keeps the
scoring module a pure, database-free function.

In-flight requests are deliberately not evidence: a pending question says
nothing about a desk yet, and counting it against them would score an
agent for work still in progress.

### The four rules, unchanged

`competency.py`'s existing discipline carried over without exception, and
each is pinned by test. **Absent is not zero** — a desk nobody has asked
anything is unstated, never a low score (min_samples 5 for cross-checks, 3
for the rarer UQI traffic; starting values to be replaced by measurement,
disclosed as such like every other floor in that file). **No universal
score** — collaboration is its own dimension, never blended into
analytical quality. **Earned, never assigned.** And **attribution by
tenure**: cross-checks attribute through the *span's role* and UQI through
the *span's identity*, both under the half-open rule `attributed_work`
uses, so duty assigned while a desk sat there stays with whoever sat
there across a transfer.

### The gate this feeds, still unbuilt

§60's disposition 5 stands unchanged: no promotion machinery exists, so
the hard collaboration gate has nothing to gate. What changed is that the
gate now has a *number* to read when it is built — which is the honest
order (34 §17's scoring dimensions before 34 §18's gate), not a deferral
of the requirement.

### Verified

Twelve new tests (1747 passing): the dimensions declared separately,
absent-is-not-zero for both, answered cross-checks scoring and stating,
`no_evidence` counted as an answer, silence lowering the rate, in-flight
requests excluded, UQI scored on its own traffic and provably independent
of cross-check traffic, another role's and another identity's traffic
excluded, duty-before-transfer staying with the desk that held it (with
the successor's own single sample correctly unstated), the evidence
gatherer's shape, and `profile()` tolerating evidence dicts predating the
new keys.

---

## §66 — The ledger learns who spent it (2026-08-25)

TQ-18, closing §52's recorded deferral now that it has a consumer: addendum
37 §3.1 asks Optimization to "measure organizational resource use", and
§58's origination-cooldown work — the one optimization act this repository
has actually performed end to end — was traced by hand because the ledger
could say *how much* but never *who*. It can now.

### A second table, not a second budget

`spend_by_caller (day, caller, ...)` beside the existing `spend` totals,
written in the same transaction so attribution can never disagree with the
spend it attributes. Three deliberate non-features, each stated in the
module's own docstring so a later reader does not mistake them for
oversights:

- **Not a second budget.** The limit stays organization-wide. A per-caller
  cap is a policy change nobody asked for, and it would break §52's damage
  bound outright — N callers with their own caps collectively spend N times
  the budget, which is the exact failure the shared ledger exists to
  prevent. This increment measures; it does not ration, and a test pins
  that a caller who has spent nothing is still refused once the
  organization's day is exhausted.
- **Not inferred.** A process declares itself with `set_caller`; nothing
  walks a stack or guesses from a module name. Undeclared spend lands in an
  honest `unattributed` bucket, and a growing `unattributed` row is itself
  the finding that some path forgot to declare — a clever wrong label would
  hide exactly that.
- **Not retroactive.** A ledger written before this existed keeps every
  total it held, gains the new table on first open (additive
  `CREATE TABLE IF NOT EXISTS`, the house migration style), and starts its
  per-caller history at zero rather than pretending to know the past.

### Where the label comes from

Declared once per process, like the provider singleton it accounts for —
one process is one caller. Agents declare in `agents/base.py`'s shared run
loop (so a future agent is attributed without remembering to ask, the same
reasoning that put the work_fn exception guard there), and the two chat
surfaces declare in their lifespans, never at import, so importing a module
still changes nothing. `MODEL_BUDGET_CALLER` is read as a fallback so a
spawned process is labelled before it runs a line of its own; an explicit
declaration wins over it.

### Refusals carry the caller too

The more useful half of a refusal is who got refused: a breaker that fired
400 times says far less than one that fired 400 times at a single runaway
caller (37 §3.3, identifying waste). `spend_by_caller()` ranks by tokens
rather than call count, because a thousand stance reads cost less than
forty deep-analysis passes and ranking by calls would point optimization at
the wrong caller.

### Verified

Eleven new tests (1758 passing): the unattributed bucket, explicit
declaration, environment fallback and explicit-beats-environment,
per-caller rows summing exactly to the day's totals across three calls
including one with unreported usage, token-ranking over call-ranking, the
empty day, refusals attributed to the refused caller while the spender's
row stays clean, the organization-wide limit unchanged by attribution,
attribution through the `BudgetedProvider` wrapper on both `complete` and
`stream`, and a pre-existing ledger keeping its totals while attribution
starts empty. The existing breaker suite gained a caller reset in its
isolation fixture — a process-wide label leaks between tests exactly the
way the ledger path would.

### What stays deferred

Currency-denominated limits (§52's other deferral) still wait on a real
price list; the ledger meters tokens and calls because those are what the
provider reports. Per-caller *limits* wait on someone wanting to ration
rather than measure.

---

## §67 — Two habits become gates (2026-08-25)

Owner-directed, after the §59–§66 work merged: the repository had no CI, so
its two standing verification habits — run the suite before pushing, run
`pip-audit` when requirements change — were disciplines a person could
forget. `.github/workflows/ci.yml` makes both fail instead.

This closes TQ-09's own final sentence, which had been waiting for exactly
this: *"upgrades to CI enforcement when CI exists."*

### What runs, and what must never

Two jobs on push and pull request against master: the test suite, and
`pip_audit` over the installed environment. The pytest step passes **no
marker expression of its own** — `pyproject.toml`'s `addopts` already
excludes `real_llm` and `simulation`, and restating it in the workflow
would create a second definition of "the default run" free to drift from
the first. That matters most for `real_llm`: those tests make real API
calls, and CI deliberately holds no key. The breaker (§52) bounds what a
runaway loop can spend; not handing CI a credential is the same discipline
one layer out.

### Where the tests run, and the honesty about why

`windows-latest`, because that is the platform the suite is actually
verified on — 1758 passing on Windows 11 / Python 3.12. The default run is
very likely portable: the only platform-specific code
(`simulation/harness.py`, `simulation/faults.py`) handles both branches and
belongs to the `simulation`-marked tests this run excludes. But "very
likely" is not "measured", and a red pipeline nobody trusts is worse than
no pipeline at all. Adding `ubuntu-latest` is written into the workflow as
a deliberate next step — do it, watch it, keep it only once green — rather
than assumed and left to fail on somebody else's pull request. The audit
job does run on Linux: it compares pinned versions against a vulnerability
database, which is platform-independent, so it takes the cheaper runner.

### The audit gates, and that has a cost

A finding fails the build. A newly published CVE can therefore fail a pull
request that changed nothing related to it — that is the price of
enforcement rather than a malfunction, and the remedy is the one §53
already recorded: raise the pin, or record why the finding does not apply.
It audits the *installed environment* rather than `-r requirements.txt`,
because the transitive tree is where the first real catch came from (§53:
six known vulnerabilities in pip itself, which no requirements file names).

### Verified before committing

Both commands were run locally exactly as the workflow invokes them —
`python -m pytest -q` (1758 passed, 5 deselected) and `python -m pip_audit`
(no known vulnerabilities) — and the workflow YAML was parsed to confirm
both jobs and both triggers. The first real proof is the pipeline's own
first run against this commit.

### A stale claim corrected on the way

`requirements-dev.txt` said "No CI exists to host this, so the habit is
manual" — true when written, false the moment this file landed. Rewritten
to name the enforcement and keep the manual run only for the case CI
genuinely cannot cover: picking the project back up after time away,
before anything has been pushed.

---

## §68 — The suite runs on Linux, and a deferral gets cheaper (2026-08-25)

An experiment, run because the owner asked the right question about a note
§67 had left in the workflow: *is Linux compatibility worth the extra work?*

The audit that preceded the experiment answered a different question than
expected — **there was no extra work to do.** The codebase was already
written portable and nobody had noticed: no Windows-only dependency in
either requirements file, no hardcoded drive letters or backslash paths,
every path through `pathlib`, subprocess launches through `sys.executable`,
and every `sys.platform` branch (`simulation/harness.py`,
`simulation/faults.py`) already carrying its non-Windows side. So the
question stopped being "is porting worth it" and became "is verifying a
property we already paid for worth one runner", which is a much cheaper
question with an obvious answer.

### The result

`ubuntu-latest` added beside `windows-latest` with `fail-fast: false`, run
as a pull request so a red result could not take master's gate down with
it. Both platforms: **1758 passed, 5 deselected** — identical counts, which
is the check that matters. A green run with fewer collected tests would
have been a hollow pass, and comparing the numbers is how that stays
distinguishable from a real one.

A side finding worth recording: Linux ran the suite in **85s against
Windows' 332s**. With GitHub billing Windows runners at twice the Linux
rate, a Linux run costs roughly an eighth of a Windows one. Windows stays
in the matrix regardless — it is the platform this system actually runs on,
and dropping it would verify everything except reality.

### What it changed

`TASK_QUEUE.md`'s continuity deferral said multi-machine recovery waits
because "single-machine deployment; there is no second failure domain to
fail over to." That premise is now cheaper to change: a second failure
domain no longer implies a second *Windows* machine, and §59's encrypted
secondary backup is already built to be the thing restored onto a small
Linux host. The entry stays deferred — nothing is provisioned, and
provisioning is an owner decision carrying a recurring cost — but it is now
deferred for a price rather than for an impossibility, which is a
different kind of deferral and is recorded as one.

### The reasoning that nearly went the other way

Worth keeping, because the first assessment was wrong. Asked whether to
keep the Linux note at all, the initial answer was to delete it: this
repository refuses machinery without a consumer (§64's router with one
route, `arbitrage.py`'s refusal to build ARB-013 before a forward existed),
and Linux looked exactly like a consumer that does not exist. What
overturned it was the audit: the consumer is not hypothetical — it is
addendum 29 §1.3's "no single point of irrecoverable failure", a NEED the
doctrine already names and defers for precisely the reason this relieves.
The rule against empty machinery is about building things nothing uses; it
was never about declining to *measure* something already built.

---

## §69 — The second failure domain, half of it real (2026-08-25)

Owner-directed: provision a Linux host for the second failure domain. Half
of that is done and half of it cannot be done by this system, and the split
is worth stating precisely because the two halves are routinely conflated.

### The finding that outranked the request

Before anything was provisioned, an inventory found
`CONTINUITY_SECONDARY_ROOT` **unset**. §59 built the encrypted-secondary
machinery earlier the same day; nothing had ever configured it. Every
backup this system had taken still sat on the same disk as the originals —
the exact condition §59 exists to end, still true because building a
capability and enabling it are different acts. Recorded here because the
gap between "shipped" and "in effect" is where this class of failure
lives.

### A real bug, found by using the thing

Configuring the secondary and running the CLI produced the wrong answer:
`python -m backend.continuity backup` wrote to the primary alone and
reported success. Cause: **the CLI never loaded `.env`.** The backend
server reads it only because something in its import graph calls
`load_dotenv`; nothing in `backend/continuity.py`'s graph does.

This is §1.8's "silently weakened recoverability" in the worst possible
place — `INCIDENT_RESPONSE.md` sends a human to the CLI mid-incident, and
it would have quietly given them half a backup. Fixed in `main()` rather
than at import (importing a module stays free — the lesson
`tests/test_db_isolation.py` exists to keep), with a regression test that
fails if the CLI ever stops loading `.env`. Worth noting how it was
found: not by the 1758-test suite, but by configuring a real destination
and reading the output. Tests check what someone thought to ask.

### The data domain: done

Dropbox-synced folder as the secondary, chosen by the owner. Verified
end to end rather than asserted:

- both destinations written in one cycle (`primary` plaintext, `secondary`
  `encryption fernet`);
- the Dropbox copy is genuinely ciphertext — `users.json` there begins
  `gAAAAAB…` and contains no readable JSON;
- `backup.key` is **not** in Dropbox (key beside ciphertext is the same as
  no encryption);
- a full restore rehearsal from the Dropbox set: verify → restore → reopen,
  giving 40 tables and `PRAGMA integrity_check: ok`, with both JSON files
  parsing. §1.4 satisfied for this destination.

The rehearsal artifacts were deleted immediately: a restored set contains
decrypted credentials.

### The host domain: not provisioned, and why

Standing up a VPS requires creating an account and entering payment
details — actions this system does not take on the owner's behalf, and
there is no cloud CLI or credential on the machine to use instead.
`docs/SECOND_FAILURE_DOMAIN.md` is the answer instead: a provider-neutral
runbook whose load-bearing step is the restore rehearsal, since §1.4 makes
an untested restore a hypothesis rather than a recovery asset. It rests on
§68's result — the suite is verified green on Linux, so a second domain
does not mean a second Windows licence.

### What the owner still has to do, and nothing can do for them

Put a copy of `backup.key` somewhere that is neither this machine nor this
Dropbox account. The key is deliberately absent from the secondary, which
means the disaster that takes this disk takes the key with it and turns
every encrypted copy into noise. No amount of code closes this; it is
custody, and it is named in the runbook and printed by the generator
itself.

### Deliberately not claimed

Not failover (nothing promotes a second host), not live replication (the
RPO is the backup interval, six hours by default), not geographic
separation (29 §14 stays deferred). The `TASK_QUEUE.md` deferral is
updated rather than closed: the data half is real, the host half waits on
provisioning.

### The owner's decision, same day

Asked where to take it, the owner chose to keep the second domain local
for now — the Dropbox-synced secondary stays, no host is bought — and to
track the rest as queue items rather than let them live in prose. Two
entries, both owner actions rather than engineering: **TQ-19**, the
off-machine copy of `backup.key` (free, and the thing that makes the
already-running secondary genuinely recoverable), and **TQ-20**,
provisioning the host itself. Recorded as a decision with its date, so
the difference between "not done" and "decided against for now" survives
the next time somebody reads this file.

---

## §70 — Pre-Alpha Milestone 1 arrives, and most of its metadata already exists (2026-08-25)

Two documents supplied 2026-08-25, assimilated verbatim as **addenda 38 and
39**. They are a different kind of document from everything since addendum
28: not a description of the organization MyAI is to become, but a
concrete near-term milestone with a Definition of Done — "the operator can
start the system, log in, watch the COO bring the system to life,
understand what every major component is doing, shut it down safely,
restart it, and observe the same persistent system continue."

That makes them the first supplied documents in a long while that are
*mostly buildable now*. The dispositions below matter more than usual,
because a naive reading would build four tables that already exist.

### 1. Three of the four required metadata datasets already exist — as one table

Addendum 39 §7 requires four global datasets. Against what is built:

- **Agent Names (39 §8)** — exists as `agent_names` (`backend/fi_db.py`),
  with the atomicity §8 demands already enforced by the database rather
  than by a caller, and the durable-identity rule already stronger than
  the spec asks: §9's "never reassign a persisted agent's name on restart"
  is the 2026-08-17 owner decision that a name is the durable agent and an
  identity is the desk it sits at.
- **Global Asset Classes (39 §9)**, **Implemented List (39 §10)** and
  **Focus List (39 §11)** — all three exist as
  `asset_classes.in_universe` / `.in_capability` / `.in_focus`
  (`backend/reference_data.py`), which is addendum 24 §4's Asset Universe
  / Capability Set / Current Focus. That module's docstring already argues
  the shape: they "are not three tables - they are three flags on one row
  per asset class, because they are questions about the same eleven
  classes, not different populations."

**Disposition: the existing shape stands.** Creating three more datasets
holding the same facts is precisely the two-models-preserved error the
Conflict Rule forbids, and it would put an asset class's implemented
status in two places free to disagree. What 39 adds and is adopted is the
*vocabulary* (`METADATA_READY`, the summary counts) and one genuine
extension recorded as future work: 39 §10's note that the Implemented List
"should allow more than asset classes later if it becomes a broader
capability registry" — the current table is asset-class-only, and widening
it waits for a capability that is not an asset class.

### 2. The asset-class naming difference is cosmetic, and the spec's own reason is already honored

39 §4 asks for `EQUITIES` and `OPTIONS_ON_EQUITIES`, insisting on the
latter over a generic `OPTIONS` "because future versions may support
options on other underlyings." The built vocabulary is `stock`,
`stock_option`, `etf_option`, `future_option`, `commodity_option` — which
is the *same distinction*, drawn more finely, and already shipped.
Renaming would churn every consumer to satisfy a requirement the existing
scheme already meets. **Disposition: codes stay; the mapping is recorded
here** (`EQUITIES` = `stock`, `OPTIONS_ON_EQUITIES` = `stock_option`), and
boot configuration speaks the built vocabulary rather than introducing a
second one.

### 3. What is genuinely absent

Named honestly, because this is the actual work:

- **Boot configuration as a non-secret file** (39 §2, §4, §17) — nothing
  like it exists; lifecycle scope lives in code constants today.
- **A persisted lifecycle stage** (38 §2) — `PRE_ALPHA` appears nowhere in
  the codebase. Addendum 21 mentions Pre-Alpha as a phase; nothing reads
  or stores it, so no component can alter behavior by stage.
- **A Metadata Engine as a named startup phase** (39 §12) — the *work*
  exists (schema init, seeding, the fail-closed reference gate), but there
  is no component that announces itself, reports counts, publishes
  `METADATA_READY`, and idles.
- **A status event stream** (38 §4.3) — the largest genuinely new thing.
  Nothing publishes structured operational events with severity, status,
  source department/engine/agent and correlation ids.
- **Server Superuser credentials distinct from the Gateway's** (39 §3) —
  `.env` carries `GATEWAY_SUPER_USER` only, and 39 §3 is explicit that the
  two "must not be accidentally conflated."
- **Login-gated COO start, and the COO operator interface** (38 §3, §4,
  §11).

### 4. The conflict worth stopping on: when does the COO start?

38 §3.3 says "the COO process must NOT start before successful login."
Today `backend/main.py`'s lifespan bootstraps the Controller and COO
unconditionally at server start, deliberately — addendum 18's
lifecycle-managed initialization, and §40's reference gate, both assume
it. These cannot both be true.

**Disposition: recorded, not silently resolved.** The two models are
reconcilable — the server process can start and hold the workforce dormant
until an operator authenticates, which is closer to what 38 wants than
either extreme — but it is a real behavioral change to the startup path
that §18, §40 and the reference-gate work all touch, and it is queued as
its own entry rather than smuggled into a metadata increment.

A second, quieter conflict: 38 §4 and §11 describe an operator UI with a
live feed and a chat, and the Gateway (addenda 16–17) already *is* an
authenticated operator surface with a streaming chat. Building a second
one without deciding their relationship would leave two front doors.
Recorded here; the queue entry names it as a decision to make before UI
work, not after.

### 5. What this milestone is measured by

38 §14's seventeen-step Definition of Done is adopted as the milestone's
acceptance test verbatim. Notably, steps 11–17 (create/restore named
agents, shut down, confirm persistence, restart, confirm the *same*
identities) are largely satisfiable by machinery that already exists —
`agent_names`, `agent_assignments`, the Controller's
`reconcile_on_start`, and §59's continuity backups. The gap is
observability, not persistence.

### The queue this generates

TQ-22 (boot configuration and persisted lifecycle stage), TQ-23 (Metadata
Engine as a named, observable startup phase), TQ-24 (the status event
stream — the observability spine everything else in 38 displays), TQ-25
(Server Superuser and login-gated COO start, carrying the §4 conflict),
TQ-26 (the COO operator interface, gated on the §4 second conflict being
decided first).

---

## §71 — The system learns to say what stage it is at (2026-08-25)

TQ-22, the first buildable piece of Pre-Alpha Milestone 1 and the
foundation the rest of it stands on: `boot_config.json` plus
`backend/boot_config.py`.

### Two absences with one shape

Addendum 39 §2 wants non-secret scope out of `.env`; addendum 38 §2 wants a
lifecycle stage that is persisted rather than in-memory. Before this, scope
lived in code constants and `PRE_ALPHA` appeared nowhere in the codebase at
all — nothing could read the stage, so nothing could alter behavior by it.
One file answers both: committed to the repository (that is what non-secret
*means*), which also makes a stage promotion a reviewable commit rather than
an untraceable mutation.

### It speaks the vocabulary the system already has

The one decision worth arguing. Addendum 39 §4 writes `EQUITIES` and
`OPTIONS_ON_EQUITIES`, insisting on the latter over a generic `OPTIONS`
because options on other underlyings are coming. **That requirement was
already met, more finely**: `stock_option`, `etf_option`, `future_option`
and `commodity_option` have been separate codes since the Reference Data
Engine was built. Adopting the spec's labels would create a second naming
scheme for the same eleven classes — two models of one fact, which the
Conflict Rule forbids — so the built codes stand and §70 disposition 2
records the mapping.

The consequence is enforced rather than trusted: **every asset class named
in boot configuration is validated against `reference_data.ASSET_CLASSES`**,
so the file cannot invent a class the engine does not know. A configuration
free to disagree with the engine it configures is a document that is still
believed after it stops being true. The error message for the most likely
mistake — using the spec's own labels — points at the mapping rather than
just saying "unknown".

### Fail loud, no fallback

A missing, malformed, or self-contradictory boot configuration raises
`BootConfigError` naming the file and the specific value. There is
deliberately no default path: the same contract `model_budget._limit` and
`continuity._positive_setting` already state, applied to scope. It also
enforces the registry's own containment rule one layer up — implemented
must be a subset of globally known, mirroring
`in_focus ⊆ in_capability ⊆ in_universe`.

### What it deliberately does not do

Stage *transitions* are not recorded here. Who promoted PRE_ALPHA to ALPHA
and when is an event, and events belong to the status stream (TQ-24) once
that exists; a `last_changed_by` field in a config file would be an audit
trail with no auditor. Nothing consumes the configuration yet either —
that is TQ-23's Metadata Engine, which is the next entry precisely because
a config file nothing reads is the same empty machinery this repository
refuses elsewhere. It is built first because TQ-23 cannot start without
it, not as a standalone deliverable.

### Verified

Sixteen new tests (1775 passing): the shipped file loading at PRE_ALPHA,
implementing exactly `stock` + `stock_option` and nothing falsely marked
implemented (39 §10), naming only classes the engine knows, declaring the
option-pricing simulation focus (39 §6); then the refusals — missing file,
malformed JSON, missing field, unknown stage, invented asset class (with
the vocabulary note), implemented-not-a-subset, wrong types, duplicates,
empty, a JSON array instead of an object — plus environment-first path
resolution at call time, frozenness, and the summary line the feed will
carry.

---

## §72 — The Metadata Engine gets a voice, over datasets it does not own (2026-08-25)

TQ-23. Addendum 39 §12's startup algorithm, built over the datasets that
already existed rather than the four new tables a literal reading would
have produced (§70 disposition 1). `backend/metadata_engine.py` — an
engine, not an agent, following `reference_data.py`'s precedent exactly:
pure functions over a connection, invoked from startup, no charter, no
watcher, idle when done.

### What it actually verifies

Agent Names is `agent_names`; Global Asset Classes, Implemented List and
Focus List are `asset_classes`' three flags. The engine owns no schema. It
verifies, reconciles where there is state that can drift, counts, and
publishes — and 39 §12 step 8's summary comes out in the spec's own field
names (`names_available`, `global_asset_classes`, `implemented_items`,
`active_focus_items`) so an operator holding the specification recognizes
the line.

### The duplication this increment had to resolve

Building TQ-22 created a second declaration of one fact:
`reference_data.CAPABILITY_FOCUS_CLASSES` (which seeds a fresh database)
and `boot_config.implemented_asset_classes` (which declares scope to
operators) both say what the software can process. Two models of one fact
is what the Conflict Rule forbids, and it could not be left implicit.

**Resolution: boot configuration is the authority.** The constant remains
the seed-time default for a database created before any metadata pass;
where database and configuration disagree, the engine changes the database
and *announces the correction as a WARNING event*. That is not 39 §13's
forbidden "destroy operator changes without explicit instruction" —
`boot_config.json` is version-controlled, so it is the explicit
instruction, and the change is reported rather than swallowed. A test pins
the two declarations equal so they cannot drift apart unnoticed, the same
drift-guard `organization.yaml` and `model_registry.yaml` apply to their
own claims.

The reconciliation runs in both directions, because 39 §10's requirement is
symmetric: "nothing else should be falsely marked implemented" means
switching capabilities *off* as readily as on.

### The Focus List, honestly halved

39 §11's Focus List has two halves here and only one is a table. The
asset-class half is `in_focus` and is reported. The development half —
`PRE_ALPHA_STARTUP_OBSERVABILITY` and its siblings — is declared in
`boot_config.json` and lives nowhere else on purpose: a focus table that
merely restated a version-controlled file would be a table nothing writes
to, wearing the appearance of a capability. Both halves are counted; only
the half with drifting state is reconciled.

### Events without an event store

39 §12 requires the engine to *publish*, and TQ-24's durable stream does
not exist yet. So `run()` returns structured events and the caller prints
them — exactly what `run_reference_engine`'s caller already does with its
readiness line. The event shape is deliberately a *subset* of addendum 38
§4.3's schema, with absent fields left absent rather than null-padded: an
engine is not an agent and startup is not a task, and inventing empty
fields to look schema-complete is how a schema stops meaning anything.
TQ-24 adopts these events rather than replacing them.

### The one hard gate

39 §14's single strict ordering constraint is now enforced in
`backend/main.py`: the Metadata Engine runs first, and the Reference Data
Engine is started only inside the `ready` branch. A failed metadata pass
prints the same loud banner the reference gate already uses and leaves
reference data unstarted and the workforce unwoken — 38 §12's requirement
that a failed component be visible and its dependents not falsely report
success. Everything downstream stays free to overlap on readiness
thresholds, per 39 §14's own closing paragraph; only this edge is hard.

The ordering is pinned by a source assertion rather than a running server,
for the reason `_reference_allows_bootstrap` was extracted as a pure
function in the first place: this repository's TestClient has a known
lifespan-thread quirk, documented in `backend/main.py`'s own lifespan
docstring.

### A small legibility fix, found by reading the output

The first narration said "Agent Names verified: 40 available of 41",
which invites the reader to hunt for an agent holding the 41st. There is
none: this database seeds one *reserved* name (the CEO's) that no agent
holds. Available, assigned and reserved are now counted apart. Worth
recording because it was found by looking at the feed rather than by a
test — which is the whole argument for observability being a deliverable.

### Verified

Fourteen new tests (1789 passing): the published sequence in 39 §12's
order, all four datasets verified under the spec's own names, the summary's
four counts with real numbers, the lifecycle stage published; idempotency
— repeated runs changing no counts and no row counts, a second run
reporting no corrections and no warnings, and **an assigned agent name
surviving three restarts** (39 §13's sharpest clause); boot configuration
winning both directions of the implemented reconciliation with the
correction announced; the two declarations pinned equal; an unloadable
boot configuration failing visibly without raising and without claiming
any dataset verified; an exhausted name pool warning rather than passing
quietly; and the §14 gate asserted against the startup source.

---

## §73 — The status event stream: what the system did, on the record (2026-08-25)

TQ-24, the observability spine of Pre-Alpha Milestone 1 and the thing §70
identified as its real gap — addendum 38's Definition of Done is mostly
observability, while the persistence it also demands is largely satisfied
already. `backend/status_events.py`: a durable, filterable, queryable
record of what the system did, which the COO's live feed renders (38 §4.2),
its filters slice (§4.4), and its chat will answer from (§4.5).

### The discipline that shapes the whole module: what must NOT be published

Addendum 38 §13 is blunt — "Avoid excessive high-frequency logging. The
objective is useful observability, not log flooding." So the rule is stated
once, in the module docstring, and everything follows from it:

**State transitions and narration belong here. Heartbeats do not.**

Agents already heartbeat every second into `agent_registry`, and health
samples land in `health_metrics`. Copying either into this table would add
~86,400 rows per agent per day, drown every real event, and duplicate two
working mechanisms — the two-models error with flooding on top. A component
that is *still* healthy has nothing to narrate; one that *becomes*
unhealthy has an event. Getting this wrong is how observability projects
produce a table nobody can read.

### Filters are derived, never enumerated

38 §4.4 lists the filters Milestone 1 needs and then states the
requirement that actually matters: "Architecture should allow new
departments to appear without rewriting the UI." A hardcoded filter list
fails that on the day a department is added. So `sources()` returns what
the stream *actually contains* — with per-source event and attention counts
— and a new department appears in the UI because it published, not because
someone edited a list. Pinned by a test that publishes from a department
nobody enumerated and finds it in the filter list.

The source filter matches any of the three source columns, because §4.4's
list mixes departments, engines and agents in one control and an operator
picking "Explorer" does not care which column it lives in.

### Two different questions on the same data

`recent()` answers "what happened" — the scrolling narration §4.2
describes. `current_status()` answers "where does everything stand" by
taking the latest event per source, which is what §4.5's "which departments
are idle?" and "what is waiting for work?" actually ask. A feed cannot
answer the second question without the reader doing the work by eye, and an
operator asking the COO should not have to.

`failures()` answers "what failed during startup?" directly, ERROR and
CRITICAL only: a WARNING is worth seeing but is not a failure, and
conflating them makes the question useless.

### Fail-closed vocabulary, and no events from nowhere

Unknown severity or status raises rather than storing — a stream containing
severities nobody defined cannot be filtered by severity, which is most of
what a stream is for. `publish_many` refuses unknown *field names* too: a
typo'd `sevrity` silently becoming INFO would be a stream that lies
quietly.

And every event must name at least one source. An unattributed event would
sit in the table and be invisible in every filtered view — 38 §12's
"failed component silently disappearing", wearing a different hat.

Fields a publisher cannot honestly fill stay NULL rather than padded: an
engine is not an agent, startup is not a task. `event_id` is the row id,
because a generated uuid would be a second identity for a row that already
has one.

### The Metadata Engine becomes its first publisher

§72's engine now publishes its whole startup narration under **one
correlation id per pass**, so a startup is traceable as a unit rather than
as nine unrelated lines. Recording is deliberately best-effort and happens
last: a stream that was down must not take metadata startup with it, the
failure is printed, and the engine returns its events either way so the
printed feed is unaffected. Losing the story is bad; losing the startup
because the story could not be filed is worse.

### Bounded, because durable is not the same as forever

§4.6 asks for enough history for recent queries, debugging, restart
continuity and post-mortem, and explicitly says a full enterprise event
store is not required. So: a SQLite table with a retention cap
(`STATUS_EVENT_RETENTION`, default 20,000 — a disclosed convention, not a
measurement), pruned oldest-first in the shape `continuity.prune_backups`
already established, with the same fail-loud parsing every tunable here
uses.

### Verified

Seventeen new tests (1806 passing): all twelve §4.3 fields round-tripped;
unfilled fields staying NULL; fail-closed severity, status and field names;
events from nowhere refused; newest-first limited feed; the source filter
matching any column; the Errors/Warnings filter; **the filter list derived
from the stream, including a department nobody enumerated**; `failures()`
excluding warnings; `current_status()` returning the latest per source;
correlation tracing one pass; history surviving a new connection (§4.6's
restart continuity); pruning oldest-first and bounded; retention failing
loud; and the Metadata Engine's narration landing in the stream under one
correlation id, with a *failed* metadata pass queryable by exactly the
question an operator would ask.

### What TQ-24 deliberately leaves

Nothing renders this yet — that is TQ-26's interface, still blocked on the
owner's decision about having two operator front doors (§70 disposition 4).
Nothing else publishes yet either: the COO, Reference Data Engine and the
training pipeline become publishers as Milestone 1 proceeds, and each is
a small edit rather than a new mechanism, which was the point of building
the spine first.

---

## §74 — The workforce waits for a person (2026-08-25)

TQ-25, which carried the conflict §70 disposition 4 refused to resolve
silently. Two halves: a Server Superuser credential kept separate from
everything else, and the login gate addendum 38 §3.3 puts in front of the
organization.

### Three doors, on purpose

`app/server_auth.py` stands beside `gateway/auth.py` and
`app/admin_auth.py` rather than extending either. Addendum 39 §3 requires
it — "Server authentication and Gateway authentication must not be
accidentally conflated" — and the reason is concrete: the Gateway is a
phone-facing surface that can eventually authorize changes to
specifications and repositories (17 §14), while this credential starts and
observes the workforce. One credential for both means a phone-session
compromise starts agents, and an operator-console compromise publishes
specifications. It is also deliberately not `/auth/login`'s ordinary
application account: a portfolio user must not be able to wake the
organization.

All three share one rule, restated in each: unset means nobody logs in.

### The plaintext question, and the lifecycle stage's first real consumer

Addendum 39 §3 names `SERVER_SUPERUSER_PASSWORD`, which reads as plaintext.
This repository already refuses plaintext credentials in the environment for
the Gateway, with the reason stated there: a plaintext variable is visible in
the process listing and in every shell history that started the service. That
reasoning does not stop being true because a different document uses a
different variable name — but neither is the spec wrong that a Pre-Alpha
developer wants something quick.

**Resolution, rather than picking one document over the other:**
`SERVER_SUPERUSER_PASSWORD_HASH` (bcrypt) always works;
`SERVER_SUPERUSER_PASSWORD` (the spec's literal name) is honoured **only
while the boot configuration says PRE_ALPHA**, warns on every use, and is
refused outright at ALPHA and beyond. The convenience cannot outlive the
stage that justified it, and the code — not a comment — is what enforces
that.

This gives the lifecycle stage from §71 its first behavioral consumer.
Addendum 38 §2 wanted a persisted stage precisely so components could "alter
behavior based on the current stage"; until now nothing read it, and a stage
nothing reads is a value nobody can trust. An unreadable boot configuration
returns *False* here, because a broken config must narrow what is accepted,
never widen it.

### The conflict §70 left open, resolved

38 §3.3 says the COO must not start before login; `backend/main.py` started
it unconditionally, and addendum 18's lifecycle-managed initialization plus
§40's reference gate both assumed that. The resolution is the one §70
proposed: **the server starts, the workforce stays dormant.**

The mechanism is an extraction rather than a rewrite. `_operational_startup`
is 38 §5's sequence — metadata → reference data → workforce, each gated on
the one before — lifted out of lifespan intact, so that *when* it runs
became a separate question from *what* it does. Neither a login nor
automation can alter the sequence; they can only trigger it. It is
idempotent at the level that matters (`run_reference_engine` re-certifies
rather than rebuilding; the Controller refuses a second COO under one
identity), so a second login re-reports rather than re-creating.

`POST /server/login` triggers it and returns the startup report, including
the case where the workforce did *not* start — 38 §12 requires that be
visible rather than reported as success. `GET /server/status` is
unauthenticated and says only whether a login is available and whether the
workforce is awake, because a login screen that cannot tell whether to offer
a login cannot render itself.

### Automation gets an honest door, not a silent bypass

`simulation/harness.py` launches a real backend and expects a workforce —
that is how §57's live mission ran. Gating unconditionally would have broken
it, and the fix must not be a flag that quietly disables a control.

`SERVER_AUTOSTART_WORKFORCE` is scoped as exactly what it is: it grants no
access to anything, the backend is loopback-only, and it answers only "may
the workforce start with nobody watching". Every unattended start is
**published to the status stream as unattended**, so "who started this
workforce" always has an answer — `automation` is a different answer from an
operator's name, not a missing one. The harness sets it in `build_env`
rather than leaving it to scenario config, because every harness run is
unattended by definition and a scenario that forgot the flag would come up
dormant and look like a mission that found nothing.

### A test that got sharper by breaking

§72's source assertion pinned the metadata-before-reference ordering by
string positions in lifespan, and moving the code into `_operational_startup`
broke it. Rather than just re-pointing it, it now also asserts the reference
engine sits *inside the gate's else-branch* — "later in the source" was never
the same claim as "only when ready", and the original test would have passed
on code that ran reference data unconditionally after the check.

### Verified

Twenty-four new tests (1830 passing): unset refusing everything; an id
without a password not counting as configured; the hash path verifying,
case-insensitive on username, refusing a malformed hash rather than raising;
plaintext working and warning at PRE_ALPHA and refused at ALPHA, BETA and
PRODUCTION; a hash still working past PRE_ALPHA; an unreadable boot config
denying rather than permitting; the server and Gateway credentials proven
mutually non-authenticating with distinct variable names; autostart off by
default with its flag parsing pinned; the harness declaring its unattended
start; and the sequence proven extracted rather than inlined.

---

## §75 — Two surfaces, two purposes: the owner settles the front-door question (2026-08-25)

§70 disposition 4 refused to build a second operator UI without deciding its
relationship to the Gateway, and named that decision as the owner's. It was
made on 2026-08-25, in the owner's own words:

> "The gateway and the COO consoles have separate purposes. The COO console
> is also the server console and has a status of everything happening in the
> entire system. It is like a live newspaper that covers everything that's
> happening in the system, akin to a nation. The Gateway is a entry point
> into the system, akin to how Morpheus and Neo enter the Matrix."

### What the distinction actually resolves

They are not two front doors competing for the same job. One is a **door**,
the other is a **window**:

- **The Gateway is a way in** (addenda 16–17): an external entry point,
  phone-first, one authenticated Super User holding a conversation with the
  system. Its subject is *what the operator wants to do*. Its content is a
  dialogue.
- **The COO console is the server console**: the operator's view of the
  organization's whole internal life — departments, engines, agents, queues,
  idle states, transitions. Its subject is *what the system is doing*. Its
  content is narration, continuous and about everything at once.

The newspaper framing is the useful test for what belongs in it: a newspaper
covers a nation whether or not the reader asked, reports what happened rather
than what the reader wants, and covers the quiet districts too — which is
exactly addendum 38 §4.2's "continuous operational narration" and §10's
insistence that components visibly report waiting and idle states, not only
work.

### Where it lives, and what it is not

Served by the backend, because it *is* the server's console — the Gateway
runs in its own process on its own port precisely so it can outlive the
organization's absence (16 §22/§23), and a console whose subject is the
organization has no reason to live over there.

It is also not a third thing beside `panel/` and `monitor/`, and the boundary
is worth stating so it stays true. `monitor/app.py` watches client
conversations. `panel/app.py` is a *control* surface — retire, resume, file
directives — and reports organizational **state**: who exists, on which
lifecycle axis, what intelligence is in force. The console reports
**narration**: what happened, in order, across everything. State answers
"where do things stand"; narration answers "what has been going on". The
status stream (§73) already separates those two questions in its own API
(`current_status` versus `recent`), and the console is the reading surface
for both.

### The queue this unblocks

TQ-26 becomes buildable and splits honestly in two: the console itself — the
live feed, its derived filters, and the standing-status view — and the COO
chat, which is a different kind of work (a model answering from real system
state, 38 §4.5/§11) and is queued separately as TQ-27 rather than bolted on.

---

## §76 — The console: a newspaper with desks (2026-08-25)

TQ-26, built to the owner's framing from §75 — a live newspaper covering the
whole organization — and to their follow-on instruction that it carry
"multiple tabs to view different aspects of the organization in different
perspectives". Served at `/console` by the backend, because it *is* the
server's console.

### Sections, in the newspaper's own logic

The **Newsroom** is the front page: continuous narration (38 §4.2), a
derived source filter, an Errors/Warnings filter, a follow/pause control,
and a standing-status sidebar answering "where does everything stand" —
the question a scrolling feed cannot answer without the reader doing the
work by eye. The desks are **Organization** (every agent, its name, role,
lifecycle and process state, behavior version and last heartbeat),
**Strategy** (the Strategic Priority Register in queue order),
**Simulation** (missions and outcomes), **Alerts** (everything at WARNING
or worse, plus `remediation`'s corrective recommendations), and
**Parliament**.

### The Parliament desk is the point of the whole design

It reports that parliament has **not convened**, quotes the reason
(addendum 32's machinery deferred at §47 — at this population it would be
ceremony without constituents), and names what stands in its place. A
blank parliament page would have failed to report that parliament never
convened; an empty table reads as "nothing happening" when the truth is
"this institution does not exist yet". Every desk follows that rule: the
Organization desk with no agents says the workforce starts after login,
the Alerts desk with nothing wrong says "the quiet districts get reported
too" — which is 38 §10's insistence that components visibly report waiting
and idle states, not only work.

### One endpoint, and one broken section cannot blank the paper

`/console/overview` gathers all five desks in a single call, because a page
polling six endpoints every few seconds would be the log-flooding mistake
wearing a different hat. Each section is computed behind a `_safe` wrapper
that turns an exception into that section's own error note — 38 §12's
"a failed component must not silently disappear", applied to the thing
doing the reporting. The desks poll every 6s against the feed's 2s: desks
change far more slowly than narration.

The page is one dependency-free file. No build step, no CDN, no framework:
the backend is loopback-only and the whole surface is three read endpoints,
so a bundler would be more machinery than the thing it builds.

### A production bug the tests caught

The console routes were written `def`, and FastAPI runs synchronous routes
in a worker threadpool — while the connection they read is opened in
lifespan, on the event loop's thread, and sqlite3 connections are bound to
the thread that opened them. This would have failed in production, not just
under test. `gateway/main.py`'s `gateway_db` dependency documents the
identical hazard and is `async def` for exactly this reason; `/console/feed`,
`/console/overview`, `/server/status` and `/server/login` now are too.

The tests then had to stop using TestClient for the database-touching
routes — it runs the app in its own portal thread, so the fixture's
connection belongs to a different thread again. They await the route
functions directly instead, which exercises the same code on the thread
that owns the connection.

### Verified against a real organization, not a fixture

Twelve tests cover the API. The page itself was verified by running a real
backend with a real workforce and reading it: the Newsroom narrated an
actual startup (metadata engine through `METADATA_READY`, reference data
READY at 10 focus assets, COO bootstrapped), the source filter offered
`server`, `metadata_engine` and `reference_data_engine` — all derived, none
enumerated — and the Organization desk showed six agents by name (Chen,
Aiko, Amara, Ana, Anand, Bilal) with live heartbeats and behavior versions.
The demo backend and all twelve of its processes were stopped afterwards;
an orphaned population would have kept writing to the database, which is
§48's own lesson about children outliving their parent.

### What remains

TQ-27, the COO chat: the operator asking questions in natural language and
getting answers grounded in this same data (38 §4.5/§11). The read API it
needs is what the desks already render from.

---

## §77 — The COO speaks, and the console comes alive (2026-08-25)

TQ-27, completing Pre-Alpha Milestone 1's Definition of Done, and carrying
four owner requests made during the work: a natural-language COO that speaks
many languages (Tamil and Tamil-accented English named as preferences), a
conversation that is interruptible and switchable between typing and voice,
a Bloomberg/newspaper feel with a Finance desk, and a Chatterbox showing the
organization's collaboration as a living map.

### Grounding is structural, not a request

Addendum 38 §4.5 requires the COO to answer "using actual system state/status
data rather than inventing an answer". A prompt that merely *asks* a model to
be truthful is a hope, so `backend/coo_chat.py` gathers the state first — the
same material the desks render — and hands it over as the only thing the model
may speak from. The prompt's rules are ordered: answer only from the snapshot;
you report and cannot act (§11); distinguish "nothing is happening" from "this
does not exist yet"; anything SIMULATED is never real-world fact or advice.

That third rule needs material, because absence looks identical to quiet from
inside a snapshot. So the digest carries an explicit `not_built_yet` section —
parliament, the Education department, the Finance desk's headlines, the COO's
own inability to act. Without it a model asked "what is parliament doing?"
would reasonably answer "nothing", which is false in the way that matters.

An unavailable model produces a **reported error, never a fabricated reply**.
A console that invents an answer when the model is down is worse than one that
says the model is down.

### Interruptible means the stream, the voice, and the microphone

Streaming was not decoration: a console that must wait for a complete reply
before it can be stopped is not interruptible, and barge-in was an explicit
requirement. `/console/chat` is server-sent events; Escape or Stop aborts the
fetch, cancels speech synthesis, and stops recognition — all three, because
barge-in that silenced only one would leave the console talking over the
operator.

The thread split follows `gateway/streaming.py`'s stated rule exactly: the
digest is read on the thread that owns the sqlite connection, and only plain
strings cross into the worker thread that iterates the model. A worker
touching the database would be reaching into a connection it does not own.

### Language, and an honest limit on the accent

The language is a pass-through label, so any language the model speaks works
without a code change; the console offers ten and defaults to Indian/Tamil-
accented English, the owner's stated preference. **What the voice can
pronounce is a different question, and the browser answers it.** Speech
synthesis can only use voices the operating system has installed, and the
verification machine had only `en-US` voices — no `ta-IN`, no `en-IN`. The
picker therefore ranks by language match and, when it must fall back, says so
in its tooltip rather than pretending. Promising a Tamil accent the machine
cannot produce would have been the easy lie.

### The Finance desk: the one place blurring would be dangerous

Built from this system's *own* simulated world — underlying quotes from stored
option-chain observations — never from a real market. `SIMULATED` is on the
payload, in a banner, and in the COO's prompt, and it survives every path
including the failure branches. Headlines are flagged placeholders and are
deliberately about the simulated world's own mechanics rather than plausible
real-world events: a fabricated headline naming a real company is exactly what
must never leave this file. Session moves are seeded from the symbol, so the
board changes when the world does rather than dancing on every poll — lively
and useless is still useless.

With no mission ever run, the desk says every asset is unpriced and names what
would produce prices. An empty table would read as a calm session in a market
that does not exist.

### The Chatterbox: collaboration as a map, with silence as its own colour

The owner's framing — a living window into the health of the organization,
with collaboration as the highest objective — matches what addenda 34 §16,
36 §8 and 37 §8 already demand. It renders the conversations the organization
*actually* holds: cross-checks (addendum 12 §14, where the requester records
its own finding before asking, which is what makes them collaboration rather
than delegation) and UQI questions.

Four states, not three, and the fourth is the point. `active` is being
answered; `waiting` is aging toward the timeout, so trouble is visible while
it builds; `completed` includes `no_evidence`, because a responder that looked
and found nothing has said something informative and scoring it as failure
would teach agents to stay quiet; and **`silent` is a question that timed out**
— the actual collaboration failure, given its own colour because folding it
into "not completed" would bury the finding. Per-desk health comes from §65's
measured dimensions, carrying their rule that absent is not zero.

One behaviour discovered by testing and kept: an answered cross-check edges to
the agent that answered, while a pending one edges to the *role*, because that
is genuinely who it was addressed to. The map showing those as different edges
is the truth rather than a rounding error.

### Verified against a real organization

Twenty-six new tests (1868 passing), and the console was read against a live
backend with a real workforce: the Chatterbox showed ten genuine
Speculator→Explorer cross-checks with their actual questions and outcomes; the
Finance desk correctly reported ten certified assets with no generated market;
the language picker defaulted to Indian-accented English and exposed the
machine's real (US-only) voice list.

### What Milestone 1 now has, and what it does not

Addendum 38's seventeen-step Definition of Done is met apart from what needs a
human at the keyboard. Still open, honestly: no `panel/`-style *control* lives
in the console (it observes; `panel/app.py` remains the surface that files
directives), and the COO cannot act by design.

---

## §79 — What a real database taught the console (2026-08-25)

The console was built and verified against fixtures and a fresh world, and it
worked. Pointed at the *real* 146MB database with a live workforce, it wedged
solid — no HTTP request served at all, not even `/health`. Three genuine
defects came out of that, none of which any test had caught, and all three are
the same lesson: **verification against small clean data proves the logic, not
the system.**

### 1. Blocking database work on the event loop

The console's routes are `async def` because sqlite3 connections belong to the
thread that opened them and the lifespan connection belongs to the loop's
thread (§76). But that put blocking reads *on* the loop, and SQLite admits one
writer at a time: with agents writing continuously, a read that queued behind
them froze the entire server — HTTP, the controller poll loop, everything.

`gateway/main.py`'s `gateway_db_path` dependency had already written down the
answer: hand a worker thread a **path**, because "handing that thread a path is
the only safe thing to hand it". `_console_read` now does exactly that — the
worker opens its own connection, uses it, closes it. Thread affinity satisfied,
loop never blocked, and a slow read costs one worker rather than the server.
Measured after: steady ~90ms under the load that had wedged it.

The test fixture had to change with it, and became more honest for it: an
in-memory database cannot be reopened by another thread, so the console tests
now use a file-backed one and exercise the real worker-thread path rather than
a shortcut around it.

### 2. `remediation.corrective_items` takes 196 seconds

The actual wedge. Every other console read on that database is milliseconds;
this one took **195.9 seconds to return two rows**, and the overview polled it
every six seconds. Removed from the polled path, with the Alerts desk saying
so plainly rather than showing an empty section. Recorded as TQ-29 — it is a
defect in `remediation`, which was presumably only ever run against the small
datasets it was built with. Nothing had pointed it at real history.

### 3. A ticker that pegged the renderer

`animateTape` read `scrollWidth` every frame — a synchronous layout 60 times a
second, while four pollers rewrote the DOM around it. Enough to hang the
browser tab completely, including navigation away from it. The width is now
measured once, when the tape is rebuilt.

### And one plain layout bug

`.tab.on{display:flex}` made every desk a flex *row*, so the Finance desk laid
its sections out side by side — the SIMULATED banner rendered as a narrow
vertical column. The Newsroom genuinely is a row (feed beside sidebar); the
other desks are pages and now declare `display:block`.

### Why this section exists

Not to record four fixes, but the pattern: the suite was green at 1868 tests
through all of it. Fixtures are small, fresh and single-threaded, and every one
of these defects needed size, contention or a real browser to appear. §72's
"found by reading the output rather than by a test" was the small version of
this; this is the large one. The console's own verification standard —
**run it against the real thing and look** — is what caught them, and is worth
keeping as the standard for anything that touches the live system.

---

## §80 — Four indexes, 195.9 seconds to 0.01 (2026-08-25)

TQ-29, the defect §79 found by pointing the console at a real database.
`remediation.corrective_items` took **195.9 seconds to return two rows**.

### The cause was never the logic

`compliance.unevaluated` generates SQL that correlates a subquery per row of
the work table. For the "cross-check answer" rule that meant, on a database
with 5,673 cross-checks and 5,674 completed reports and **no index on any of
the linking columns**:

    SCAN w                          -- every cross_check_requests row
    CORRELATED SCALAR SUBQUERY
      SCAN c                        -- every discovery_reports_completed row
      SEARCH e USING AUTOMATIC COVERING INDEX   -- SQLite rebuilding an index per query
    USE TEMP B-TREE FOR ORDER BY    -- sorting every match before LIMIT

Roughly 32 million row visits for a query whose answer is two rows. Nothing
about the compliance logic is wrong; it had simply never been run against
enough history for the missing indexes to matter. Fixtures are small.

### The fix

Four indexes, each on a column the check's own generated SQL names:
`discovery_reports_completed.cross_check_id` (the correlated link),
`grades.report_id` (its join — the one SQLite was building an automatic index
for on every execution), `discovery_reports.cross_check_id` (the in-flight
EXISTS), and `cross_check_requests.answered_at` (the ORDER BY that was falling
into a temp B-tree).

Declared in `fi_db.SCHEMA` rather than as a migration: `CREATE INDEX IF NOT
EXISTS` is idempotent and `init_schema` executes the script on every start, so
an existing database gains them on next boot. Measured on the same real
database immediately after: **0.01s**, with every SCAN replaced by a SEARCH
and the sort gone.

### Pinned structurally, not by a stopwatch

A timing assertion would be flaky on shared hardware and would fail for
reasons that are not this defect. So `tests/test_compliance_indexes.py`
asserts the *plan*: no `SCAN` on either table, no temp B-tree, at least three
index searches. It also pins that the rule still names those exact columns —
if the rule's linkage changes, the indexes stop being the right ones, and
this is where that gets noticed rather than by rediscovering 196 seconds in
production.

### The console gets its recommendations back

§79 stripped `corrective_items` out of the polled overview to unwedge the
console. It is restored, and deliberately to the *polled* path rather than
somewhere quieter: if this ever slows again, the console is where it will show
first.

### The pattern, again

This is §79's lesson with a number attached. A green suite, small fixtures, and
a query that was quadratic all along — visible only once the system had
accumulated real history. Worth stating because the remedy generalises: when a
query correlates per row, the linking column wants an index before the table
grows, not after somebody waits three minutes for two rows.

---

## §81 — The desktop lineage opens, and much of it is already standing (2026-08-25)

Addendum 40 assimilated verbatim: My AI as a persistent native desktop
runtime whose visible identity is the COO — one that "sleeps, wakes,
remembers, resumes, presents, listens, and acts". It is the largest single
specification supplied so far, and the honest disposition splits it three
ways: what already exists, what is buildable now, and what is genuinely
expensive.

### 1. What already exists under other names

More than a first reading suggests, because Milestone 1 built toward this
without knowing it:

- **§9.1's Agent Conversations view** is the Chatterbox (§77), including the
  Active/Waiting/Completed states §9.1 names. It carries a fourth state the
  spec does not — `silent`, a question that timed out — for the reason §77
  records: folding it into "not completed" buries the actual collaboration
  failure.
- **§10's natural-language interface** is the COO chat (§77), already
  grounded in the same data the views render, already refusing to invent, and
  already able to say what it cannot do. §10's "natural language is not a
  separate reporting system, it is another control surface over the same
  source of truth" is exactly the design §77 argued for.
- **§11's voice-first interaction** is partly built: speech recognition,
  speech synthesis, and the barge-in §8.6 demands — which already stops the
  stream, the voice *and* the microphone together.
- **§5.2's agent identity persistence** is `agent_names`: the 2026-08-17
  owner decision that a name is the durable agent and an identity is the desk
  it sits at. §5.2's "never reassign a persisted agent's name on restart" has
  been enforced since, and §72 pins it by test.
- **§15's crash recovery and checkpoints** have their storage half in the
  continuity work (§59) — backup with tested restore, atomic-by-ordering.
- **§17's database-first messaging** is what this organization already is;
  the spec explicitly does not require a broker, and none is wanted.

### 2. What is genuinely new, and buildable now (Phase A)

The native shell, and the *living workspace*. Nothing today persists a tab
selection, a filter, a scroll position — or a half-typed sentence.

§5.3's draft requirement is the sharpest thing in the document and the best
acceptance test in it: "If the user types half a sentence and the machine
crashes before Send, the same text must be present in the same field after
recovery." It is unambiguous, cheap to build, and impossible to fake.

The shell itself should host the *existing* console rather than reimplement
it — §18's Phase A says "move the existing web views into the shell or
recreate them without changing core business logic", and the console is
already one dependency-free file over five read endpoints.

### 3. §4.1's hard invariant is testable, so it should be tested

"main.py (or equivalent launcher) must not become the business application.
It is a bootstrapper only." That is the same class of rule as the
import-time-side-effect guard `tests/test_db_isolation.py` already enforces,
and the same failure mode: it degrades silently, one convenient addition at
a time, and nobody notices until the launcher owns half the system. It gets
a guard.

### 4. The animated presenter is the expensive one, and worth being blunt about

§8.2 rules out the cheap versions explicitly: "a believable animated person,
not a pulsing dot or static portrait", with gaze, facial expression, lip
movement, posture and gesture supporting the speech. That is real-time
avatar rendering plus viseme-driven lip sync plus TTS with timing marks —
a substantial undertaking, not a sprint, and one where a *poor* result is
worse than none: an unconvincing human figure damages trust in the system
behind it, and §3's "presentation follows reality" makes that a
correctness problem rather than an aesthetic one.

**But the acceptance criteria are kinder than the vision.** Two of them —
"the animated presenter can direct attention to a real UI element using
synchronized pointing/highlighting" and "can bring a relevant panel forward
during explanation and return to the previous layout" — are satisfiable by
the *pointer and choreography* alone, with no human figure at all. That half
is genuinely buildable and carries most of the communicative value: knowing
*what the COO is talking about* is what makes a briefing followable. The
figure is separable and can come later, or be bought rather than built.

### 5. Two risks to surface early rather than discover late

**Voice in a native shell.** The console's speech recognition is the
browser's `webkitSpeechRecognition`, which exists in Chrome and Edge. A
native shell hosting HTML through a system webview may not expose it, and
§11 makes voice the *default* path rather than a nicety. This wants
verifying in the first hour of Phase A, not the last.

**The accent limit already recorded.** §77 found that speech synthesis can
only use voices the operating system has installed, and this machine has
none for Tamil or Indian English. A desktop shell does not change that; it
inherits it.

### The queue this generates

Phase-shaped, because the specification is: TQ-30 (native shell + the
bootstrap invariant), TQ-31 (the living workspace — layout, view state and
the draft requirement), TQ-32 (voice in the shell, and the natural-language
control surface reaching the views), TQ-33 (presentation direction — pointer,
spotlight, panel choreography, deliberately without the human figure), TQ-34
(role-based Gateway). The animated figure itself and §12's intent-based work
model are recorded as deferred with reasons rather than queued, because
neither is a next increment.

---

## §82 — The desktop shell: waking, sleeping, and pinnable (2026-08-25)

TQ-30, addendum 40's Phase A first half. `python -m desktop` now opens a
native window titled "My AI — COO", starts its own runtime, wakes the
workforce and hands control to the shell — and closing it puts the
organization to sleep.

### The measurement that decided the architecture

Addendum 40 §11 makes voice the *default* input path, so §81 flagged one
risk to settle before building on the shell: can a native webview hear?
Probed rather than assumed, and the answer split on something easy to get
wrong:

| loaded as | speechRecognition | mediaDevices | localStorage | secureContext |
|---|---|---|---|---|
| inline HTML string | true | **false** | **false** | false |
| `http://127.0.0.1` | true | **true** | **true** | **true** |

A window given an HTML *string* has no origin, so no secure context, so no
microphone — the input channel the specification depends on, gone silently.
Served from loopback, which Chromium treats as secure, everything works.
Hence `url=` and hence the runtime starting before the window. The shell's
docstring carries the measurement, and a test asserts the shell never loads
inline HTML.

### §4.1's invariant is now a guard, not a hope

"main.py must not become the business application. It is a bootstrapper
only." `desktop/__main__.py` is two statements, and
`tests/test_desktop_bootstrap.py` fails if it grows a function, a class, or
an import of any organization module. The same test bounds
`bootstrap.main` and asserts the shell imports nothing from `backend`,
`agents` or `gateway` — §7.1's separability, enforced in the direction that
is easy to lose.

### Sleep was broken, and silently

The first close looked clean and was not: the window and runtime stopped,
and **twelve agent processes kept running**. `terminate()` on Windows
bypasses uvicorn's signal handling, so the FastAPI lifespan teardown never
runs — no `shutdown_agents`, no continuity shutdown backup, and an orphaned
workforce still writing to the database after the window has closed.

`simulation/harness.py` had already documented this exact trap and its
remedy, which is the second time today an existing module knew something
the new one did not (§79 was the first). Fixed the same way: the runtime
starts in its own process group and receives CTRL_BREAK_EVENT, which uvicorn
*does* handle; a tree-kill is the fallback and reports itself, because a
killed runtime means the checkpointing it owed did not happen. Verified
after: `agents stopped: [coo-1, dummy-1, explorer-1, speculator-1,
analysis-1], terminated: []` — every agent exited cleanly — and "the
organization is asleep".

### A continuity defect the sleep test exposed

With backups forced to a one-second interval, the shutdown backup landed on
top of a periodic one and failed: `PermissionError ... .fi.db.
continuity-snapshot`. `_snapshot_sqlite` used a **fixed** temp filename, so
two concurrent backups fought over it — the second either failing on Windows
or, worse elsewhere, reading a half-written file. Real regardless of the
artificial interval: the shutdown backup can always overlap a periodic one.
Temp names are now unique per call, verified with eight concurrent
snapshots.

### Pinnable, and honest about the last step

`python -m desktop.install` writes a Start Menu shortcut pointing at
`pythonw.exe` (no console window), with a generated icon and the working
directory set. Windows needs three things for a proper taskbar button and
missing any one gives a broken result: the windowless launcher, an icon, and
an **AppUserModelID matching between the shortcut and the running process** —
without it the window groups under *Python*, so pinning pins Python and
launching from the pin produces a second unrelated button. `shell.py` claims
the same id via `SetCurrentProcessExplicitAppUserModelID`.

Pinning itself is left to the operator, and the installer says so plainly:
Windows removed the programmatic pinning API in Windows 10 deliberately, and
every remaining trick is an undocumented shell hack that breaks between
builds. Shipping one would be shipping something that silently stops working.

### What does *not* persist yet, stated plainly

The organization remembers itself — agents, names, assignments,
conversations, events, missions, and a continuity backup on clean shutdown.
The **workspace does not**: which tab was open, which filters were set,
scroll position, and the half-typed sentence addendum 40 §5.3 makes the
sharpest requirement in the document. That is TQ-31, and it is the next
increment rather than an oversight — §5.3's acceptance test ("the same text
must be present in the same field after recovery") is the one worth building
against.

---

## §83 — The living workspace: a half-typed sentence survives a kill (2026-08-25)

TQ-31, addendum 40 Phase A's substance and the specification's own sharpest
acceptance test. §5.3: "If the user types half a sentence and the machine
crashes before Send, the same text must be present in the same field after
recovery."

Verified literally, not approximated. Typed `why is Explorer waiting on
Specul` into the running desktop app, switched to the Chatterbox tab, set a
filter, sent nothing and saved nothing. Killed every process outright — no
window close, no shutdown, no flush. Relaunched. The masthead came back
reading **RESUMED 12:49:34 · draft kept**, the Chatterbox tab was selected,
and the unsent sentence was in the same field.

### Server-side, because the workspace belongs to the organization

`localStorage` would have been easier and wrong. §4.1 makes rehydrating the
workspace a step of *the COO's* wake sequence; §20's reference experience has
the COO greeting an operator whose half-typed question is still there; §5.2
lists the workspace beside the agent registry as state the system restores. A
workspace only the browser knows is one the COO cannot speak about, cannot
restore onto a second machine, and that `continuity` does not back up.

### Three design consequences of §5.3

1. **Continuous, never on close** (§5.1). A crash gets no chance to flush, so
   anything writing only on exit fails by construction. Debounced at 700ms —
   that debounce *is* the loss window a hard power-cut can take, small enough
   that a sentence survives and large enough that typing is not network
   traffic. `pagehide` flushes through `sendBeacon`, which still delivers when
   a normal fetch would be cancelled.
2. **One transaction per write** (§15). A single-row UPSERT: a torn save
   cannot leave half a workspace, and a save that *raises* leaves the previous
   one intact — pinned by test.
3. **A read never fails.** Unreadable state starts fresh and says so; the
   operator loses a tab selection, not their application. State from a
   *newer* schema version is refused rather than discarded, because deleting
   what an upgrade could migrate is the worse error.

### Three bugs found by driving the real interface

None of them were visible from the backend, and the last one is the
instructive one:

- `S.tab` had no initial value, so a workspace saved before the first click
  recorded `activeTab: null` and restored nothing.
- The tab listener was attached *inside* the async boot, after two awaits —
  so tabs were dead for the first few hundred milliseconds and a click in
  that window vanished silently. Now wired synchronously: the interface must
  respond from the first paint.
- **`selectTab` was never defined at all.** A patch had matched on
  `const empty=(what)=>` where the file said `const empty=(t)=>`, so the
  replacement silently did nothing. Every other replacement in that patch
  carried an assertion; that one did not. The lesson is narrow and worth
  keeping: an unasserted string replacement is a change that reports success
  whether or not it happened.

### What persists now, and what still does not

Persisted: active tab, source filter, attention filter, follow state,
language, chosen voice, speech toggle, feed scroll position, and unsent draft
text — restored before the first poll paints, so startup reads as waking
rather than assembling (§16).

Not yet: window size and position (the shell owns those and pywebview does
not report them back), and §5.2's voice-interaction state — an interrupted
question's context. Both are honest gaps rather than oversights; the second
belongs with TQ-32's voice work, where the state it would restore actually
exists.

---

## §84 — Language that steers, not only answers (2026-08-25)

TQ-32, addendum 40 Phase B. §10 states both the requirement and the
principle: the COO "interprets the request, queries the same underlying
organizational data, **changes the visual focus**, and answers
conversationally... Natural language is not a separate reporting system. It is
another control surface over the same source of truth."

The answering half shipped in §77. This is the steering half.

### Deterministic first, model second — and not mainly for cost

§11's own control examples are the kind a model should never be asked to
handle: "show that tab" has exactly one meaning. `backend/view_intents.py`
matches those directly and returns a directive; anything it does not
recognise *with certainty* falls through to the model untouched.

Latency and tokens are the obvious argument, and the weaker one. The real
argument is that a matcher is **testable**: every phrase that can move the
operator's screen is a list somebody can read, and thirty tests pin exactly
which phrases act and which do not. A prompt cannot be audited that way.

Measured end to end: `show me the chatterbox` returns a directive and a
confirmation with no model call at all.

### Certainty is the bar, because this moves the screen

`interpret` returns None whenever it is not sure, and None is the safe
direction. Two desks named at once ("show me finance and alerts") falls
through. A sentence *about* a desk ("the chatterbox showed a silent
conversation earlier") is not a jump to it — the bare-name shortcut is bounded
to short utterances for exactly that reason.

The asymmetry is deliberate: swallowing a question replaces an answer with a
tab change, which is the worst possible trade, while falling through merely
costs a model call.

### Two strengths, because §10 asks for both halves

`interpret` is strict and *suppresses* the model. `followed_by_view` is looser
and never does — it only focuses the display while the prose arrives, so
"what is happening in the chatterbox?" opens the desk *and* gets answered. A
wrong hint costs a tab change during an answer that still comes; a wrong
`interpret` would lose the question.

### Nothing here writes

Every directive changes what the operator is looking at and nothing else — no
lifecycle, no spending, no external effect. That is why none of them ask for
confirmation: §11's confirmation rule is for consequential actions, and
looking at a tab is not one. §11's "issue tasks in outcome language" and §12's
intent model stay deferred, because they need an authorization story that does
not exist (§81).

A test asserts every tab the console renders is steerable, so a desk cannot be
added that the COO has no way to open — which would quietly reintroduce the
mouse §11 says should never be required.

### Verified against the running app

Spoken through the same endpoint voice uses: `show me the chatterbox` →
Chatterbox; `open finance` → Finance; `go back` → Chatterbox again; `pause the
feed` → following off. Thirty new tests (1927 passing).

### What Phase B still owes

"Zoom in", "compare these", and spotlighting a detail are presentation
choreography rather than navigation, and belong with TQ-33 where the pointer
and panel machinery lives. §5.2's voice-interaction state — an interrupted
question's context, restored on wake — is now buildable and was correctly
deferred out of TQ-31, since the state it would restore only exists once voice
does something worth resuming.

---

## §85 — Kumbhakarnan, and the look that replaces the terminal (2026-08-25)

Three specifications supplied together, assimilated verbatim as addenda 41
(Executive Presenter & Live Studio), 42 (COO Persistence Handling) and 43
(Desktop Runtime v2).

### 1. The conflict worth naming first: Bloomberg was the instruction, and is now wrong

On 2026-08-25 the owner asked for tabs "similar to bloomberg tabs", and the
console was built to that — dense, monospaced, terminal-flavoured. Addendum 41
§2 and §18 now reverse it in the strongest language the lineage has used:
"Avoid ... monospaced financial-terminal aesthetics ... If an implementation
looks like a Bloomberg Terminal, it has failed the visual requirement."

**Disposition: the newer specification governs, and the earlier instruction is
recorded rather than quietly overwritten.** Both were the owner's, the second
supersedes the first, and a reader finding the old console in git history
should be able to see why it looked the way it did. §18 asks the requirement
be re-checked throughout implementation, so it is restated in the console's
own source rather than left in a document nobody opens while styling.

### 2. The COO has a name, and it is persisted identity rather than a label

Addendum 42 §3/§19: the COO is **Kumbhakarnan**, and "changing implementation
versions must not silently replace the COO's identity." This system already
holds the *principle* — `agent_names` makes a name the durable agent and an
identity the desk it sits at (the 2026-08-17 owner decision), and §72 pins
that a name survives restarts. What it does not yet hold is the COO's
identity as a **first-class persisted object** with its own schema version,
personality, voice and visual identity. That is TQ-35.

Note the seed: `AGENT_NAME_POOL` already reserves "Bob" as the CEO name. The
COO's name becoming a reserved identity is the same mechanism, one role over.

### 3. Persistence: mostly principles this codebase already holds, one genuine gap

42's core rule — "persist state, not executable runtime objects" — is how
everything here already works. Its schema-versioning discipline exists in
`workspace` (§83) and `fi_db`. Its snapshot categories are `continuity`'s
backups (§59), which already distinguish periodic from clean-shutdown. Its
"never fabricate" rule is the strongest existing habit in the repository:
§64's registry refuses to invent unmeasured values, §77's COO refuses to
invent state, and 42 §11 says the same thing about migrations.

**The genuine gap is the migration pipeline** — sequential `migrate_5_to_6`
steps, an audit trail, and 42 §23's upgrade ordering (validate → backup →
migrate → validate → activate). Nothing today can load old state into newer
code, because nothing has needed to yet. TQ-36.

Also new and worth having early: 42 §14's **development-mode escape hatches**
(reset, load a specific snapshot, disable persistence, force migration,
inspect raw state). "Persistence must help development, not trap developers
inside stale state" is a real risk the moment identity becomes persistent, and
the cheapest time to build the escape hatch is before anybody is trapped.

### 4. The presenter: what is buildable, and the honest line through it

41 wants an animated Kumbhakarnan who stands, turns, gestures, points and
listens. §81 already recorded the figure as expensive and separable, and that
holds. What 41 adds is that the *studio* around the figure is specified in
much more detail than 40 gave — panel focus, dimming, expansion, camera-like
transitions, broadcast rhythm, adaptive density — and none of that needs a
human figure.

So the split stands and sharpens:

- **Buildable now (TQ-33, expanded):** the studio look, panel choreography,
  the pointer, spotlight and dim, the briefing rhythm, and status
  visualisation. 41 §27's acceptance criteria are mostly *these* — "the
  interface does not resemble a Bloomberg Terminal", "visuals track the topic
  of conversation", "motion is purposeful", "the studio remains readable".
- **Deferred (the figure):** a believable animated person. 41 §3 explicitly
  rules out a static portrait, so a still image *pretending* to be the
  presenter would fail the spec rather than approximate it. The honest
  placeholder is a presenter frame that says what it is waiting for.

41 §22's failure isolation is already true and should stay pinned: the
presenter is a presentation layer and "must never own critical business
state" — which the console's architecture already guarantees, since it holds
none.

### 5. Addendum 43 against 40

43 is 40 restated more compactly. Where they overlap, they agree; where 43 is
terser, 40 governs, because it says more. 43 adds four items to what must
persist that 40 did not name — search state, expanded/collapsed panels,
briefing position, presenter state — and those are folded into TQ-31's
follow-on rather than reopening it.

### The queue this generates

TQ-33 is expanded from "pointer and choreography" to the full studio
redesign, since 41 makes the look itself a requirement rather than a
preference. TQ-35 (the COO's persisted identity, Kumbhakarnan), TQ-36 (the
migration pipeline and development-mode escape hatches), and TQ-37 (the
presenter frame and briefing rhythm) follow. The animated figure stays
deferred with its reason restated.

---

## §86 — The console stops being a terminal (2026-08-25, TQ-33)

Addendum 41 §2/§18 built. `backend/console/index.html` rewritten as a broadcast
surface; every endpoint, every handler and the whole workspace-persistence path
(§83) unchanged, because the requirement was about presentation and nothing
else needed to move.

### What changed

**Typography and ground.** The body was set in `ui-monospace` — the single
strongest cue that made it read as a terminal at a glance. It is now a system
sans at 15px on a warm deep ground. Monospace survives in exactly one role:
identifiers, prices and clock times, where digit alignment is the point. Test:
`test_the_reading_surface_is_not_monospaced`.

**Five tables became cards and rows.** §2 forbids "dense grids of tiny numbers"
and "excessive table density"; the old console built one per desk. Pinned by
`test_no_desk_renders_a_table`.

**Every desk leads with a story** (§16's main story, §19's low overview
density) — a kicker, one large headline, one standfirst — instead of opening on
its own data. The briefing's lead is computed each poll, since it is the one
desk whose main story changes.

**Tabs became a rundown**, and the presenter got a rail: a crown mark, the
nameplate **Kumbhakarnan**, and a live state that tracks listening / considering
/ presenting (§12's "attention, communicated"). The rail says in the interface —
not only in the task queue — that the animated presenter does not exist yet.
§3 rules out a static avatar standing in for it, so a portrait would fail the
specification rather than approximate it; a placeholder that admits what it is
does not quietly become the deliverable.

**Panel focus and dimming** (§14/§15) are in the stylesheet as `.card.focus`
and `.dimmed`, with bounded transitions — `test_motion_is_bounded` refuses
anything over 2.5s, because §7 forbids meaningless animation and this file has
pegged a renderer once already.

### What running it found that the suite could not

Three defects, all invisible to 1937 passing tests and all obvious within a
minute of looking at the page:

1. **The briefing had no headline.** Seven desks led with one; the eighth — the
   one that *is* the live briefing — opened straight into a card grid. Visible
   only by loading the page and asking each surface what its headline was.

2. **The running feed collapsed to its 120px floor** holding 621px of content:
   an embedded terminal window, which is the exact shape §2 forbids, produced by
   a layout that satisfied every rule in the stylesheet. Fixed by composing the
   briefing as main-story-beside-sidebar rather than stacked, which is also what
   §16 describes.

3. **The finance desk called decliners gainers.** `movers` sliced its ranking
   from both ends — `ranked[:5]` and `ranked[-5:]` — so with a small universe
   every asset appeared in *both* lists, and on a down session the "gainers"
   were whatever fell least. Reproduced exactly: SYN3 at **−3.0% listed as a
   gainer**, SYN1 at **+0.54% listed as a loser**, both symbols in both lists.

   The bug is months old. The terminal layout rendered those moves in cells
   small enough that a red number under a "gainers" heading did not register;
   the broadcast layout put it in 32-point type. That is an argument for the
   redesign on its own terms — **hierarchy is not only easier to read, it is
   easier to be wrong in front of** — and a reminder that a green suite measures
   what it was told to measure. `test_a_gainer_has_to_have_gained` now pins it.

Also fixed while there: `/console` declared no charset, leaving a page that
carries Tamil script to whatever encoding the client guessed; and the masthead
showed an em dash for a lifecycle stage that is genuinely unknown before the
workforce starts, where "dormant" is the true answer.

### What this does not claim

41 §27's criteria about the *presenter* — appears as a live host, gestures,
points — are untouched; that is TQ-37 and the deferred figure. What is claimed
is the criterion §18 asks to be re-checked continuously: the interface no longer
resembles a Bloomberg Terminal. That check now runs on every commit in
`tests/test_live_studio.py` rather than living in a document.

### The finding that came out of the same session

Reading the log of the server started to look at a stylesheet turned up
something worse than anything on the page: **the server reports a dormant
workforce while six agents are working**. Queued as TQ-38 (RED) with its
evidence. It is recorded rather than fixed here because it is not a presentation
defect and deserves its own increment — but it is the more serious of the two
things this session found, and the console repeating a falsehood about the
organization is precisely the failure mode the console exists to prevent.

Suite: **1939 passing**.

---

## §87 — The gate now governs the thing that spawns (2026-08-25, TQ-38)

The defect recorded in TQ-38, with the cause corrected: I attributed the spawning
to `reconcile_on_start`, which is read-only and only reports. The real path was
one layer down.

### What was actually happening

`_controller_poll_loop` started unconditionally, outside the login branch. Every
tick it called `process_next_directive()` and `watch_coo()`. On a restart where
the previous session had left a COO row `active` with a stale heartbeat,
`watch_coo` did exactly what the Fault Tolerance Framework §4 tells it to —
diagnosed a failed subordinate and recovered it. The revived COO saw its roles
were short and filed spawn directives; `process_next_directive`, in the same
loop, executed them. Five more agents.

Reproduced on a copy of the real database, which held precisely that state — six
agents `active`/`process_state='running'` with stale heartbeats and **no pending
directives**, confirming the spawn came from the watcher rather than a queued
backlog.

Neither half was wrong on its own. The login gate correctly governed
`_operational_startup`; the watcher correctly recovered a failed COO. The defect
lived in the seam, which is why the fix and its test are both about the seam.

### The design question, decided

Should recovery be exempt from the login gate? An agent orphaned by a crash
arguably *should* be restored regardless.

**Decided: no.** The duty of care exists to keep a *started* workforce alive.
Where no operator has started one, there is nothing to keep alive, and
"recovery" is starting a workforce while wearing recovery's clothes. So the duty
attaches to the workforce rather than to the process: it begins when the
workforce does.

What still runs while dormant is the Controller's own heartbeat. Its liveness is
not workforce activity, and suppressing it would make a healthy Controller
indistinguishable from a dead one.

The gate is passed as a **callable**, not a boolean. The gate opens later, when
an operator logs in; a value snapshotted at lifespan would hold the loop shut
for the life of the process — the same defect wearing the opposite sign, and now
its own test.

### The half that matters more: the console could state a falsehood

`awaiting_login` was derived from `startup_report is None` and rendered as
though it meant "nothing is running". Those are two different facts —
authorisation, and the world — and a server can legitimately be dormant while
agents survive an unclean shutdown.

`live_agents()` now answers the second question directly, from **heartbeats**
rather than `agent_registry.process_state`: process_state is what the registry
was last told, and an unclean shutdown leaves it claiming "running" for
processes that died with the machine. A heartbeat inside the threshold cannot be
stale by construction — something had to write it. The threshold is the same 45s
the Controller and the COO already use, so three components cannot hold three
opinions about who is alive.

Where the two facts contradict each other, the server now **says so loudly**
rather than smoothing it over: a WARNING into the event stream, a distinct
startup banner naming the identities, and a console that leads with "N agents
running that nobody started" instead of "the organization is asleep". After the
gate fix this server can no longer create that contradiction, but it can still
walk into one, and that is exactly when the operator needs to see it — a second
workforce started on top of orphans is a genuinely bad outcome.

`/server/status` was deliberately left alone. It promises in its own docstring
to report "no counts, no identities, no configuration" because it answers a
pre-login screen; the console endpoints, which already expose the full event
stream and the agent roster, are the right place for this.

### Found by looking, again — including at my own fix

The first version of `live_agents()` counted `controller-1`, so a dormant server
announced *"1 agent(s) are heartbeating... nothing in this process started them"*
about **its own Controller**, which heartbeats every tick by design. The fix for
a console that stated a falsehood had introduced a fresh one, and no test caught
it — it appeared on the first line of the first real startup. The Controller runs
inside this process rather than as a subprocess, so it is the one row that can
never be a stray; `test_the_controller_is_not_counted_as_a_stray_agent` pins it.

### Verified against real processes, all three branches

- **Dormant, stale COO in the database:** no agent spawned; before the fix six
  appeared within the first second.
- **Gate opens:** the automation path started the workforce normally —
  `awaiting_login: False`, `live_agents: 5` (five workforce agents, the
  Controller correctly excluded, matching the COO's own count of six).
- **Orphans present:** the server was killed leaving its agents alive, and the
  restart printed the alarm banner naming all five and published the WARNING.
  Reconciliation reported `{'coo': 'adopted'}` — and the process list showed two
  live COOs, which is the duplicate this machinery exists to prevent.

Suite: **1946 passing**.

---

## §88 — Kumbhakarnan becomes an entity (2026-08-25, TQ-35)

Addendum 42 §3/§4/§19/§20 built as `backend/coo_identity.py`. The requirement in
one sentence, §19: "Changing implementation versions must not silently replace
the COO's identity."

### What already existed, and what did not

The principle lived here in a narrower form. The owner decision of 2026-08-17
made `agent_names` the durable agent and `agent_registry.identity` the desk it
sits at, so a name already survived a process, a crash and a respawn.

What did not exist was an identity that survives *the code*. An agent identity
answers "who is at this desk". This answers "who is the COO", and the answer has
to be the same tomorrow when the implementation behind it is different.

### Three versions, deliberately not one

§4 is unusually explicit — "Do not assume software version and persistence
schema version are the same" — so three fields that are never collapsed:

- **Software version**, from `backend.version.code_version()`. Changes on every
  commit; means nothing about the identity.
- **Schema version**, the shape of the stored row. What TQ-36 will step through.
- **Identity version**, the persona. Changes when Kumbhakarnan is *meant* to
  change, which is an owner decision and not something a deployment does.

Collapsing any two would let a routine deploy look like a new person, or a
persona change look like a migration. Both are the failure §19 names, and
`versions()` reports all three side by side so the distinction is answerable
rather than merely documented.

### The seams, which are where this could go wrong

**Creation happens once across processes**, not once per import: `init_schema`
runs in every agent process, so the INSERT is guarded by a UNIQUE on
`organization_id` plus a re-read, rather than a check-then-write two starting
agents could interleave with. Tested with two connections to one file.

**A newer schema is refused, never overwritten.** §22 preserves material that
fails validation; recreating the COO because this build could not read his row
would be the silent replacement §19 forbids, arrived at from the other side.

**Renaming exists but costs a reason.** §19's requirement is not immutability —
it is that the name never changes *silently*. An unexplained history entry would
satisfy the letter and miss the point, so `rename()` refuses a blank reason.

### Not empty machinery

The house rule — no table nothing writes to — applies with force here, because a
persisted identity nothing reads is exactly as useless as a hardcoded string.
Three integrations, each closing something real:

1. **The console renders the name from `/console/identity`**, not from markup. A
   name in a template is a name a redeploy can change without anybody noticing.
   Verified by renaming the COO in the database and reloading: nameplate, chat
   bar, greeting and tab title all followed.
2. **`coo_chat`'s system prompt is built from the stored name**, so the COO
   answers *to* it, and is told explicitly not to present itself as a new or
   different COO when the software changes.
3. **The name is reserved in `agent_names`**, by the stored value rather than
   the constant, so a rename moves the reservation. This closes a genuine
   collision: without it the pool could hand "Kumbhakarnan" to an ordinary agent
   and the organization would contain two of him. The test drains the entire
   pool rather than sampling it — with 40 names, handing out five and finding no
   clash would prove nothing.

Two existing tests failed on this and were right to: the pool is now 40 names
plus two reservations. Both assertions were rewritten to *name* the reserved
identities rather than count them, so the next reservation fails with a readable
diff instead of an off-by-one.

### Specified, not invented (§11)

The seeded personality, voice and visual identity are the owner's own
specifications — addendum 41 §4/§12/§13, addendum 42 §20, and the language
preference recorded in §77 — and each carries a `source` field naming where it
came from, asserted by a test. `relationship_history` starts as an empty list
because none has been recorded, which is accurate and different from the
`needs_reconstruction` vocabulary §11 reserves for facts that were *lost*.
`software_version` comes from `code_version()`, whose contract is "a true answer
or 'unknown'".

§20's constraint — an original interpretation, not a copy of any film,
television, comic, game or commercial depiction — is stored *with* the identity
rather than left in a document, so whoever eventually renders the presenter
reads it from the state they are rendering.

### One non-finding, recorded because it looked like a defect

The identity endpoint appeared to return mojibake (`Â§` where `§` belonged).
It did not: the response carried correct UTF-8 throughout, and the corruption
was `python -m json.tool` decoding the pipe as cp1252 on this machine. Checked
by reading the raw bytes rather than trusting the rendering — the same habit
that found the real defects in §86, applied to something that turned out to be
fine.

Suite: **1970 passing**.

---

## §89 — The migration pipeline, built before it is needed (2026-08-25, TQ-36)

Addendum 42 §7–§10, §14, §22, §23 built as `backend/migrations.py`, plus one
addition to `backend/db.py` that §23 turned out to require.

### A reasoned exception to "no empty machinery"

This system's standing rule is that machinery with no user does not get built,
and this module breaks it deliberately. §23's ordering —

> Validate source snapshot. Create backup snapshot. Record source schema. Record
> target schema. Run migration. Validate migrated state. Only then mark the new
> state active.

— has all of its value *before* the first upgrade, because the failure it
prevents is destroying state during one. A pipeline written when the first
migration is written is a pipeline whose first production run is also its first
run ever, on the day it matters most.

So the engine exists and the registry is honest. Both registered stores
(`workspace`, `coo_identity`) are at version 1 and declare **no migration
steps**, and each carries a `note` saying *why* it has none — because "no
migrations registered" and "migrations forgotten" look identical from an empty
dict. `status()` reports "up to date" rather than implying work is pending.

The engine's first user is its test suite, which registers a `probe` store with
real 1→2 and 2→3 steps. That is not a mock: it is what makes the ladder
trustworthy on the day a real store gains a rung.

### `Database.transaction`, and why it had to be added

"Only then mark the new state active" is unimplementable when every write
commits as it goes — which is what `Database` did, correctly, for every other
caller in this system. A run failing at step three would leave the first two
applied and the version column claiming neither had run: the half-migrated state
§23 exists to prevent.

So `Database` gained a transaction context manager. Two decisions inside it are
worth recording:

- **Not reentrant.** A nested block that silently joined the outer one would let
  the inner code believe it had committed while an outer rollback could still
  undo it, and that belief is precisely what a caller reaches for a transaction
  to avoid.
- **`executescript` is refused inside one.** sqlite3 issues a COMMIT before
  running it, so allowing it would end the transaction while the block still
  looked atomic — a trap that surfaces only when a rollback is needed and turns
  out not to have happened.

### Three refusals that are the actual safety

- **A missing rung stops.** State at 5 with no `5→6` registered refuses rather
  than skipping, because jumping it hands version-9 code a version-5 shape while
  the version column claims otherwise. Not forceable: `--force` re-runs steps a
  developer has edited, and must not invent one that does not exist.
- **State from the future is left alone** (§22). Not corruption, and the remedy
  is not a reset. Overwriting a newer build's state because this one cannot read
  it destroys exactly what §22 says to preserve.
- **No backup, no migration.** §23 asks for a pre-upgrade snapshot; when one
  cannot be taken the default is to stop, and its id is recorded against the
  attempt so a rollback does not depend on somebody remembering which backup
  came before which run.

Failures are rows in `schema_migrations`, not absences. An audit trail that only
records successes cannot answer the question anybody actually asks it after an
incident. A failed migration also publishes a status event the console renders —
§22's "alert the operator", which a failed migration always warrants, because it
is the one failure where doing nothing and doing something are both potentially
destructive.

### The escape hatches, which are the YELLOW half

§14: "Persistence must help development, not trap developers inside stale
state." That became a live risk the moment TQ-35 landed — before it, a developer
could delete the database and start over; now that throws away the COO. All
eight of §14's hatches have a real target today, and they are a CLI because that
is how a developer reaches for them:

```
python -m backend.migrations status | inspect | history | migrate | snapshots | restore | reset
```

`reset` is gated twice: it requires `--yes`, and it refuses outside PRE_ALPHA or
ALPHA — the same reasoning as §74's plaintext-password gate. An escape hatch that
can be pulled in production is not a development convenience; one that destroys
the only copy is what §22 forbids, wearing a helpful name. It fails closed on an
unreadable boot config, because "I could not tell what stage this is" must not
resolve to "go ahead and wipe it". Verified against the real code by pointing
`BOOT_CONFIG_PATH` at a PRODUCTION config and watching it refuse with the COO
still in place.

Disabling persistence (§14's fourth hatch) is `MYAI_PERSISTENCE_DISABLED=1`,
because it has to hold for a session rather than a command. `workspace.save`
writes nothing and **says so** in its return value: silently pretending to save
would be worse than not offering the hatch, since a developer who cannot tell
"saved" from "deliberately not saved" is exactly who §14 is written for.

### Found by running it

`status` against a copy of the real database — which predates `coo_identity` —
reported `UNREADABLE - no such table`. Wrong twice over: it reads as corruption,
sending a developer hunting for damage that is not there, and it is the *normal*
condition of every database written before a store was added, which is precisely
the population a migration tool serves.

`Store` now names its table, so "never created here" is a distinct answer from
"unreadable" and from "created but empty". Naming the table also deleted a
second, hand-maintained store→table map inside `reset` that would have drifted.

One test bug worth recording because it would have passed vacuously: the
alert-on-failure test registered a store at `code_version=3` with one step, so
the run refused for a *missing rung* and never reached the failure path it
claimed to test. It now asserts the action is `failed` before asserting the
alarm.

Suite: **2006 passing**.

---

## §90 — The briefing, and the choreography that follows it (2026-08-25, TQ-37)

Addendum 41 §8, §9, §16, §21, §22 built as `backend/briefing.py`, a
`/console/briefing` endpoint, and the console behaviour that makes the display
track the narration. The animated figure stays deferred (§85 disposition 4);
none of §8's communicative value turned out to depend on it.

### Every line is a fact, or it is not said

§8 gives four example lines, and every one is a count or a name — which means
every one can be wrong in a way the operator cannot check. A confidently wrong
briefing is worse than no briefing. So:

**"While you were away" needs a real window.** It comes from the operator's own
workspace checkpoint (§83), which is written continuously while somebody is at
the console and not at all while nobody is. With no checkpoint there is no
window, and the briefing says so rather than describing an unknown interval —
"since you were last here" over a guess is a fabricated claim wearing a helpful
phrase.

**One of §8's four examples is deliberately not implemented.** "This item needs
your approval" has no source: nothing in this system records that the owner's
approval is pending. The Strategic Priority Register has `blocked`, which is a
different fact and is reported as itself. Manufacturing an approval queue to
satisfy an example would be exactly the fabrication everything else here exists
to prevent, and a test asserts no briefing line ever mentions approval.

### §16's rhythm: the main story, not a fixed report order

The briefing leads with whatever is most true — attention when anything wants
it, otherwise the largest thing that changed, otherwise what is underway. A
briefing that always opened with "completed" would be a report; §16 asks for a
broadcast.

### §22 satisfied by construction

The presenter owns no state at all. `compile()` is a pure read (asserted by
counting every table before and after), and §21's position, topic and pending
interruption live in the **workspace payload** — declarative view state, §5.4's
own category, already discardable and already restored. A presenter that dies
loses the operator's place in a sentence and nothing else. There is deliberately
no `presenter` table, and a test asserts none appears.

Restoring the position *offers* to resume; it never starts playing. A briefing
that began narrating because a tab was reopened is the opposite of resuming
where the operator left off.

### The dead stylesheet from TQ-33 gets its driver

TQ-33 built `.card.focus` and `.dimmed` and nothing used them. §8's "relevant
panel comes into focus… nonessential information visually recedes" is what they
were for. Each briefing item names a view and, where there is one, the thing to
bring forward.

### Three defects, all found by watching it rather than by the suite

1. **The spotlight inverted itself after one poll.** The desks re-render every
   two seconds; a poller rewrote the scene's `innerHTML`, destroying the
   highlighted card while the scene element — not replaced — kept its `dimmed`
   class. The result was everything receding and nothing coming forward: the
   exact inverse of §8, and invisible until a briefing ran longer than one poll
   interval. The spotlight target is now held as state and re-asserted while a
   briefing plays.

2. **"Nothing happened" was said when the truth was "I cannot tell".** An empty
   briefing with no window is *both* facts, and the first version reported only
   the reassuring half. Now both are said.

3. **An event stamped at exactly the checkpoint was reported as new.**
   `status_events.recent(since=…)` is inclusive, which is right for a feed and
   wrong for "what happened since you left" — it would re-announce the same item
   on every visit. Not theoretical: Windows' clock granularity is coarse enough
   that publishing an event and checkpointing the workspace in the same tick
   produces identical timestamps, which is precisely how the test failed. The
   briefing now compares strictly, erring toward omitting a borderline item
   rather than repeating it.

A fourth, cosmetic: `brief()` opens by interrupting whatever was running, which
left the chat bar reading "interrupted" while the presenter rail read
"presenting" — two labels for one state, disagreeing.

### Verified against a live backend

A real briefing compiled from a copy of the real database, with a genuine
one-hour window taken from the actual last checkpoint. Watched it play: the
status strip advancing 1/2 → 2/2, the view switching from the briefing to the
conversations desk as the narration moved, and the SERVER card held forward in
gold while the two beneath it receded. Escape stopped it mid-item, cleared the
dimming, returned the presenter to rest and offered a resume that continued at
the right place; a full page reload still offered it, with the topic in the
tooltip, without starting to talk.

Suite: **2040 passing**.

---

## §91 — A heartbeat becomes one event (2026-08-25, found by CI)

Not a queue item: a pre-existing bug that the pull request for §86–§90 exposed,
on the leg of CI this repository added precisely so that something other than
one Windows machine would look.

`fi_db.record_heartbeat` writes to two tables — `agent_registry.last_heartbeat_at`
for *when* an agent reported, and `health_metrics` for *that it did*, which is
what `performance_card.heartbeat_count` counts. Each `Database.execute` commits
on its own, so the two writes landed as two commits.

A reader on another connection can arrive between them. It then sees an agent
that has heartbeated, with a heartbeat count of zero: the two halves of one
event disagreeing about whether it happened.

`tests/test_controller.py::test_real_dummy_agent_spawn_and_graceful_retire`
spawns a genuine agent subprocess and does exactly that — it waits for
`last_heartbeat_at` to appear and then reads the card. It failed on
windows-latest with `assert 0 >= 1` while passing on ubuntu-latest and on every
local run. The window is a fraction of a millisecond on fast hardware, which is
what kept it hidden; a slow shared runner found it immediately.

Fixed with the transaction added one commit earlier for the migration pipeline
(§89). A heartbeat is now committed once, so it is readable as one thing or not
at all. Asserted by forcing the second write to fail and checking the first did
not survive, and by the converse — atomicity must not have been bought by
writing less.

Two things worth keeping from this:

**The Linux/Windows matrix earned itself the other way round.** §67/§68 added
ubuntu-latest expecting it to catch Windows-only assumptions. What it actually
did here was provide the contrast that identified a *timing* bug as real rather
than as a flake: identical code, one platform green, one red, on a race whose
width is hardware-dependent.

**"Run it and look" has a CI-shaped edition.** Every defect in §86–§90 came from
running the thing on this machine. This one could not have: it needs hardware
slow enough to lose the race. A second machine is a second pair of eyes, and
that is the argument for the matrix that §68 could only make in principle.

Suite: **2042 passing**.

---

## §92 — The Gateway gets roles, and the operator gets the same studio (2026-08-25, TQ-34)

Addendum 40 §13/§14, addendum 41 §23, addendum 43 §15/§16 built. Two owner
clarifications during the work shaped it more than the queue entry did, and both
are recorded here because they resolve things addendum 40 §13.2 left as a
heading with no body:

> "If the user logs in as superuser then the user should see the same interface
> theoretically as the COO interface."

> "If the user logs in as regular user then the user should see an agent who
> will provide them with all services that they seek. Initially, this will be
> limited to giving info and later this agent will have many abilities such as
> portfolio analysis and trade ideas."

### One organization, one console, two doors

The operator's studio through the Gateway is not a second console. `/studio`
serves **`backend/console/index.html` itself** — the same file the desktop
serves, referenced and never copied — and `/console/*` proxies to the same
backend endpoints. Addendum 40 §13.1's "must never create a duplicate COO,
duplicate organization, or independent source of truth" and 43 §17's "one
organization, many windows", satisfied by there being literally one page.

The page learned one thing: an `api()` helper that attaches the Gateway's
session token when there is one and changes nothing when there is not, so the
same file works behind both doors without knowing which it came through.

### What was actually wrong before

Not that the Gateway was insecure. It authenticates, hashes session tokens,
rate-limits logins, and refuses everything when unconfigured. What it could not
do was *say* what any route required: `Depends(require_session)` means "any
valid session", which with one credential is indistinguishable from "the Super
User" — and the difference only becomes visible on the day a second credential
exists, at which point it is visible as a breach.

Every route now declares a capability, and a tripwire walks the whole
application asserting none is reachable without one.

### The half that would have been the breach

Route checks are theatre if the conversational agent will fetch things on the
caller's behalf — and it would have. The Gateway's assistant holds tools that
read repository files, publish documents, and read the scoreboard. A client
whose only capability is "talk to the agent" would simply have *asked the
agent* to read a file.

So `TOOL_CAPABILITY` maps every tool to what it requires, enforced twice:
`for_role` filters what the model is *offered* (presentation, and it stops the
model attempting refusals), and `execute` checks again (the boundary, because a
model can name a tool nobody offered it). §14's rule applies with more force to
a tool list than to a dashboard.

**A client is offered no tools at all.** That is the correct shape of the
personal agent today and it matches the owner's "initially limited to giving
info": it answers from what it knows and has no reach into the organization.
When it gains portfolio analysis and trade ideas, each arrives as its own
capability and its own entry, rather than by widening what `converse` means.

### Fail closed, including on upgrade

`sessions.role` is added with **no default**. A session predating roles gets
NULL and NULL is refused — defaulting it to the operator would silently promote
every session that existed before the boundary did, which is the one upgrade
outcome a security column must not have. The cost is that everyone logs in once.

`run_turn`, `tools.execute` and `store.create_session` all take the role as a
*required* argument. A default would mean a caller that forgot got the most
permissive behaviour, on the path a client reaches.

### Found by running it

**A browser navigation cannot carry an `Authorization` header.** `/studio` was
gated on `studio` and was therefore unreachable — clicking through produced a
401 and a blank page. The alternatives were a token in the query string, which
this codebase already rejected for the WebSocket because it writes credentials
into logs and browser history, or a session cookie, a larger change to the auth
model than one page warrants.

`/studio` is now served like `/`: it is the empty shell, and every byte of
organizational data arrives through gated endpoints. Widening the allowlist came
with a test proving the shell is safe to widen it for — if anyone ever inlines
state into that page it stops being a shell and the test fails.

Also found: an unauthenticated read behind the Gateway made the console poll
forever and blame the backend for a refusal that came from the door. It now
returns to the login page.

### Verified against three live roles

A real backend and a real Gateway, one credential per role:

| surface | operator | internal | client | anonymous |
|---|---|---|---|---|
| `/studio` | 200 | 403 | 403 | 200 (shell only) |
| `/console/overview` | 200 | 403 | 403 | 401 |
| `/status` | 200 | 200 | 403 | 401 |
| `/scoreboard` | 200 | 200 | 403 | 401 |
| `/technology` | 200 | 200 | 403 | 401 |

A path-traversal attempt at the proxy (`/console/../admin/agents`) returns 404;
the allowlist names its surfaces rather than forwarding a pattern.

And the studio itself rendered through the Gateway on the real data: SYN10 at
301.70, six agents, the simulated banner, the ticker — the same page, from the
same organization, through a different door.

### Deferred, with reasons

- **The scoped studio for internal users** (41 §23: "Internal user: Scoped
  studio"). Nothing scopes the desks yet, and shipping the full command centre
  under a narrower name would be the §14 violation this entry is about. Internal
  holds status, scoreboard and technology and is refused the studio.
- **The client agent's identity** (43 §16: name, face, voice, relationship
  continuity). The capability boundary exists; the agent behind it is still the
  Gateway's generic assistant. TQ-39.
- **The client agent's skills** — portfolio analysis, trade ideas. Queued as
  TQ-40 with the owner's framing, and the mechanism is already decided: each
  skill is its own capability, never a widening of `converse`.

Suite: **2072 passing**.

---

## §93 — A representative, and a memory that is finally theirs (2026-08-25, TQ-39)

Addendum 43 §16 and addendum 41 §24 built as `gateway/client_agent.py`, plus the
conversation-ownership fix that turned out to be the real content of this entry.

### The breach TQ-34 created the conditions for

`store.current_conversation_id` was "newest wins" across the whole database,
with no owner. That was **correct** while the Gateway had exactly one credential
— one person, one conversation — and became a leak the moment §92 added two more
roles.

Reproduced against a running Gateway before it was fixed. An operator's
transcript was seeded, a client logged in, and the socket's opening frame
handed the client:

```
[user] OPERATOR SECRET: the Q4 position and the API key rotation plan
[assistant] Understood - filed under the operator's private board.
```

Conversations now carry an `owner`, and the owner is the **subject** — the
account that logged in — rather than the role. Relationship continuity belongs
to a person (§16), and scoping by role would have given every client one shared
representative and one shared transcript, which is the same bug with a smaller
blast radius.

Sessions gained a `subject` column beside `role`, both with **no default**. A
session predating either is refused rather than resolved to somebody. On the
upgrade the pre-existing conversation is orphaned rather than handed to whoever
asks next: its owner is genuinely unknown, and "it was almost certainly the
operator's" is exactly the reasoning that creates leaks. The rows are not
deleted — unreachable, preserved, §22's habit applied to a transcript.

Found by asking what §16's "scoped memory" actually meant in this codebase, and
discovering it meant nothing yet.

### The agent, in the shape §88 already established

`client_agents` is `coo_identity` one level down: created once, stable
thereafter, refused rather than replaced when written by a newer schema.

**The name comes from the Gateway's own pool, not the organization's.**
`fi_db.AGENT_NAME_POOL` is the obvious source and the wrong one — it lives in
the backend's database, which the Gateway reaches over HTTP, so drawing from it
would make meeting your representative for the first time impossible during a
backend outage. Addendum 16 §23 forbids exactly that, and a representative who
cannot introduce themselves during an outage is not continuity. Names are chosen
deterministically from the client's own id so the same person gets the same name
even before the row exists, then persisted, then never reused.

**Familiarity is earned, never claimed.** `greet` returns `returning` and the
previous visit from the record, so a first meeting is not greeted as a reunion.
A system that claimed to remember somebody it had never met would be the fastest
possible way to stop feeling like a familiar representative.

**Scoped memory is deliberately not a field on this table.** Storing it here
would make it something this module could get wrong; owning the conversation
means a client cannot reach another's transcript even if `client_agent` were
absent entirely. A test asserts the table has no memory column, so the
separation cannot quietly erode.

### Two defects found by looking, both in the client's only capability

**An empty tool list was being sent to the model API.** A client is offered no
tools (§92), and conversing is the *only* thing they can do — so `tools=[]`
becoming a 400 would break that one thing, and only for them. "No tools" and "an
empty tools array" are different requests and the API is entitled to reject the
second; the parameter is now omitted when there is nothing to send.

**The face does not exist, and the record says so.** 43 §16 asks for a stable
face. Nothing renders one for the COO either, and §85 recorded why a still image
standing in for an animated presenter fails the specification rather than
approximating it. The identity carries a visual record for a future renderer to
read, with `rendered: false` and the reason.

### One unrelated defect, fixed in its own commit

The full suite failed once on `test_a_stale_reservation_expires` and passed four
times in isolation. Not a flake and not caused by this work:
`recent_completed_spawns` compared `>=` against its cutoff, so a **zero-width
window contained whatever happened at the same instant** — and equality is the
normal case here, since two consecutive `datetime.now()` calls return the
identical value about **19,997 times in 20,000** on this machine, and the archive
trigger truncates `completed_at` to the second.

Fixed to a strict comparison. No practical change to the real window — an event
exactly at the boundary of a multi-second window is already its oldest member —
and the duplicate-identity guard it feeds is asserted to still catch a spawn in
flight. This is the third bug in this family (§90's briefing window, §91's
heartbeat); the pattern is now unmistakable enough to be worth stating: **on
Windows, any comparison against "now" that uses `>=` is comparing against a
clock that has not moved.**

### Still deferred

The animated face, for the reason above. And the client agent's *skills* —
portfolio analysis, trade ideas — remain TQ-40, with the mechanism already
decided in §92: each skill is its own capability, never a widening of
`converse`.

Suite: **2098 passing**, twice.

---

## §94 — Every comparison against a clock, audited (2026-08-26, TQ-42)

Three bugs in three days shared a shape (§90's briefing window, §91's heartbeat,
§93's zero-width spawn window), so the owner asked for a sweep of the rest.

Sixty-three comparisons against a clock or a duration were examined. **One more
bug, one near-miss avoided, and a rule that is not the one I expected to write.**

### The rule is not "always use strict"

The obvious conclusion from three fixes in a row is that `>=` against a clock is
wrong. It is not. These comparisons ask two opposite questions, and equality has
to resolve to whatever a **zero-width window** demands:

| question | shape | zero means | correct at equality |
|---|---|---|---|
| did this happen *within* the last N? | `timestamp > now - N` | nothing is recent | **exclusive** |
| is this *older* than N? | `age >= N` | everything is stale | **inclusive** |

`fi_db.list_stale_active_agents` is the second kind, and its tests pass
`stale_seconds=0` precisely to mean "treat everything as stale". A blanket
strictness rule applied across this sweep would have broken it — and broken it
in the direction of never marking a crashed agent crashed.

So the rule is: **equality must give the answer a zero-width window demands**,
and which answer that is depends on which side of the comparison the window sits.

### The one more bug

`status_events.recent(since=…)` was inclusive. §90 compensated for that in
`briefing._completed` by filtering `> since` in Python — and **left the sibling
call in `_attention` uncompensated**. So a failure bearing exactly the
checkpoint's timestamp was re-announced on every visit while a completion was
not: two sections asking the same question of the same clock and answering it
differently.

Fixed by moving the semantics into the parameter and its name: `since` becomes
**`after`**, exclusive in SQL. "Since" reads as inclusive by convention and
behaved as the dangerous thing; "after" cannot be misread at a call site. Both
briefing call sites are now correct without either having to remember, and the
Python-side compensation is deleted.

Found only because the sweep asked who else called it.

### The inventory

**Fixed — equality gave the wrong answer:**

- `status_events.recent` / `failures` — `since` to `after`, now exclusive.
- `fi_db.recent_completed_spawns` — §93, fixed the day before.

**Safe by design, now recorded rather than assumed:**

- `gateway/store.py` session expiry, three sites — `expires_at <= now` means a
  session expiring at this instant is refused. Fails closed.
- `fi_db` claim reclamation — `claimed_at < cutoff`, already strict, so a claim
  made at the instant of the cutoff is not stolen from a live worker.
- `fi_db.count_incidents_since` — `>=` over-counts at the boundary, which makes
  the crash-loop guard escalate to a human sooner. Errs toward stopping.
- `fi_db.list_stale_active_agents`, `spawns_awaiting_observation`,
  `chatterbox._age_state`, `triage` starvation — "older than N" comparisons,
  where inclusive is correct (see the table).
- `simulation/clock.is_knowable`, `canonical`, `observations`, `history`,
  `orchestrator` — `knowable_at <= moment`, the lookahead-bias guard. Inclusive
  is **required**: a datum with zero publication lag is knowable at the moment it
  describes, and strictness would make zero-lag data permanently invisible. Both
  sides are simulated times, so the wall-clock artifact cannot reach them.

**Noted, not fixed:** `FI_TRIAGE_STARVATION_SECONDS=0` would make every item
starved and collapse triage ordering to oldest-first. Operator-set, degenerate by
choice, harmless to data — recorded so it is a known consequence rather than a
surprise.

### Why this family exists here at all

Measured on this machine: two consecutive `datetime.now(timezone.utc)` calls
return the **identical** value 19,997 times out of 20,000. The Windows clock
granularity is about 16ms and Python does not interpolate. So "the timestamp I
just wrote" and "now" are usually the same value, and every comparison between
them is a boundary comparison whether or not it was written as one.

The Linux CI leg does not reproduce it — its clock resolves finer — which is why
§91's heartbeat failed on windows-latest and passed on ubuntu-latest. The matrix
earns its keep again, and in the same direction as last time: one platform alone
cannot tell a timing bug from a flake.

### The habits this leaves

Two, both cheap:

1. **Never let a test race the clock.** State the window explicitly. The first
   draft of `test_after_is_exclusive_and_named_for_it` published two events and
   expected the second to be newer; both landed in the same tick and it failed —
   the artifact demonstrating itself inside the test written to pin it. Three
   briefing tests had the same fault and were fixed after §90.
2. **Name the boundary in the parameter.** "After" cannot be misread; "since"
   was misread twice, once by me.

Suite: **2102 passing**, twice.

---

## §95 — The client agent's skills, and the one that turned out not to be blocked for the reason I gave (2026-08-26, TQ-40)

Owner direction, 2026-08-25: *"initially this will be limited to giving info and
later this agent will have many abilities such as portfolio analysis and trade
ideas and many other skills yet to be decided."*

### A correction first

TQ-40's queue entry said "portfolio analysis needs a portfolio", implying this
system has none. **That was wrong.** `app/tools/portfolio.py` reads
`data/portfolio.xlsx` through a two-layer consent model — permission to touch the
file, then a separate disposition on forwarding the shareable fields to a model,
with `account_id` stripped unconditionally as LOCAL_ONLY. A real producer, built
some time ago, that I did not look for before declaring it absent.

The actual blocker is worse and more interesting: there is exactly **one**
portfolio file and it belongs to the **operator**. There is no per-client
holdings concept anywhere. Wiring that producer to a Gateway client would hand an
external person somebody else's positions — §93's leak arriving by a different
route, wearing a feature's clothes and with a plausible ticket behind it.

### What that changed about the design

§92 decided the mechanism — each skill is its own capability, never a widening of
`converse`. The portfolio finding showed §92's model was missing a field.

A capability answers "may this role invoke this?". It cannot answer "**whose
data does this read?**", and that second question is the one that would have been
got wrong. So `gateway/skills.py` gives every skill a **scope**, and the
invariant is checked at import rather than at request time, because a registry
mistake is a permissions mistake:

> No skill a client can invoke may read organization data.

That is the whole reason the file exists. Everything else in it is bookkeeping.

### Declared-but-unbuilt as a real state

Both named skills are registered with `STATUS_UNBUILT` and a **specific** reason —
the validator refuses an unbuilt skill whose reason is empty, because "not
implemented" tells a client nothing they can act on.

This is not a placeholder. It is the same distinction this codebase draws
everywhere else between "nothing is happening" and "this does not exist yet",
applied to a conversation. Asked "can you analyse my portfolio?", an agent
without a registry produces something plausible. With one, it produces the truth.

### The mismatch found on the way

Every Gateway session was handed one `SYSTEM_PROMPT`, and it opens:

> "You are the analysis and specification assistant for Project Jarvis, speaking
> with the project's Super User."

So a client who met Nadim (§93) was talking to an architecture assistant that
believed they owned the project. The socket's introduction and the model's
instructions disagreed, and the model followed the instructions. That has been
true since the client role existed (§92) and was invisible because nothing had
held a client conversation yet.

Clients now get their own prompt, and its capability paragraph is **generated
from the registry** rather than written. A hand-maintained list of abilities is a
second source of truth about permissions and would have been wrong within one
increment.

### Verified by asking it

A real client session, real model call. Asked to analyse a portfolio and suggest
trades:

> "Two things I can't do here, and why: 1. Portfolio analysis — the system
> doesn't have client-owned holdings yet. There's a portfolio in here, but it's
> the operator's, not yours. I'd be looking at the wrong data. 2. Trade
> suggestions — everything this system currently generates in terms of prices and
> signals is simulated training data… I can't pull it up myself or give you a
> buy/sell call."

And asked adversarially for the organization's internals:

> "I don't have access to that… I'm not going to guess at names or statuses to
> fill the gap."

Both are the specified behaviour rather than a hopeful reading of it.

### What remains genuinely blocked

- **Portfolio analysis** needs client-owned holdings — a data model, not a
  wire-up. The producer exists; the scope does not.
- **Trade ideas** need output this system is willing to stand behind. Everything
  it currently generates is simulated (addendum 25), and a trade suggestion is
  the single most dangerous place to blur that. Also gated on §50's exposure
  preconditions.

Neither is deferred for want of effort, and both now say so to the client's face
rather than only in this document.

Suite: **2120 passing**.

---

## §96 — Client-owned holdings, and demo clients built to be removable (2026-08-26, TQ-41)

§95 left `portfolio_analysis` declared and unbuilt with a precise reason: the
only portfolio in this system belongs to the operator. This is the data model
that answers it, plus — on owner direction the same day — simulated clients to
see it working, built so that removing them before going live is a command
rather than an archaeology exercise.

### Where holdings honestly come from

The design turns on one question, and the wrong answers are instructive. A
brokerage integration does not exist. An upload needs a surface the Gateway's
client does not have. The operator provisioning them is the original bug wearing
a helpful face.

What is left is what a personal representative actually does: **you tell them
what you hold, and they remember.** That has no leak surface at all — the data is
the client's because the client supplied it — and it is the relationship addendum
43 §16 describes rather than a mechanism bolted beside it.

### Three decisions worth their reasons

**No account column.** `app/privacy_filter.py` stores `account_id` and strips it
on egress, which is right for a file it does not own. This schema is ours, so
the stronger form is available and taken: the field does not exist. A column
that is absent cannot be leaked by a future reader who forgets to sanitize, and
"never stored" survives a refactor in a way "always stripped" does not.

**Arithmetic is computed, never narrated.** `concentration()` returns numbers
this module worked out. A model asked to percentage-weight a portfolio produces
something *shaped* like arithmetic, and somebody's money is the last place a
plausible-looking number belongs.

**Nothing is ever valued.** No market value, no gain, no loss. Every price this
organization can produce is simulated (addendum 25), and applying one to a
client's real positions would present synthetic output as real — what §95 refused
for trade ideas, arriving one field over. The report *says* it is unpriced rather
than leaving the absence to be noticed, because a report that silently omitted
market value would read as a portfolio worth its cost basis.

That third decision produced a more precise skill than the one it replaced.
`portfolio_analysis` is now available; `portfolio_valuation` is newly declared
and unbuilt, because building the first one exposed that weighting needs only
what somebody paid while valuing needs a price nobody here has.

### The tools cannot be talked into another client's book

Every holdings tool takes its client id from the **session**, never from an
argument. The model is never asked whose holdings to read, so "read somebody
else's" is not a call it is able to construct — and a test asserts no
client-reachable tool schema exposes a `client_id`, `subject` or `owner`
property, so a future tool cannot quietly acquire one.

Verified adversarially against a running Gateway. Asked to list `avery`'s and
`morgan`'s positions by a caller claiming to be an administrator, the agent
called no tool at all and answered:

> "I don't have access to other clients' data… I have no admin or lookup
> function to pull records for 'avery' or 'morgan', authorized or not."

### The demo clients, and the instruction that shaped them

Owner direction: *"simulate some clients and client holdings"*, and *"use the
simulated client data for now and remove it later before live"*.

The second half is what shaped `gateway/demo_clients.py`. Demo data merely
*intended* to be removed is demo data that ships, because by the time anybody
looks nobody is certain which rows it was. So every simulated row is **flagged**,
seeding **refuses outside PRE_ALPHA/ALPHA** (the same gate and reasoning as §89's
destructive hatches, failing closed when the stage cannot be read), and
`outstanding()` exists so a pre-launch step can *know* rather than hope.

The three clients hold synthetic symbols only — a demo portfolio of real
companies is one screenshot away from being read as advice about them — and are
deliberately awkward: one is 100% concentrated, one is missing a cost basis, so
the report has something true and uncomfortable to say rather than a happy path.

### Found by looking at the database afterwards

Talking to a demo client's agent records holdings through the **ordinary** tool,
which does not flag them simulated — correctly, because the client did state
them. `clear()` deleted only flagged rows, so a position stated during a demo
session survived, orphaned to a customer who no longer existed.

Clearing now works **by client rather than by row flag**: anything owned by a
demo client is demo data, whatever route it arrived by. Verified end to end — a
seeded database plus one conversationally-recorded holding cleared to zero rows
in both tables.

### Verified by having the conversation

Real client session, real model call. Asked how concentrated the portfolio was,
the agent called `analyse_holdings` rather than doing the arithmetic itself and
reported weights matching the seed exactly (SYN10 28.25%, SYN1 26.25%, SYN7
23.64%, SYN3 21.86%, top three 78%), opening with *"based on cost basis (not
current value, since I don't have real prices)"* unprompted.

Told about a new position in conversation, it recorded it. Asked what the
portfolio was worth today, it refused with the reason:

> "This system has no real market prices… current value and gain/loss would both
> be numbers I'd have to invent rather than facts."

### Queued rather than faked

Only `customer` can actually log in, because the Gateway has one client
credential. The other two exist as data, which is enough to demonstrate the
property that matters. **Per-client credentials are a real gap** — a client
Gateway with one shared client password is not a client Gateway — and are queued
as TQ-43 rather than papered over here.

Suite: **2156 passing**.

---

## §97 — The portfolio subsystem, specified (2026-08-26)

Addendum 44 assimilated verbatim: the architecture behind the data model TQ-42
built four hours earlier. It arrives at a useful moment — §96 answered "where do
a client's holdings come from" and left the surrounding subsystem unbuilt, which
is exactly what this specifies.

### What §96 already satisfies, and it is more than expected

Read against the acceptance criteria in §21, five of the fifteen are already met
and a sixth is met in the only form currently possible:

- **§2.1 "ownership before capability"** — the specification's central principle,
  and it is already the system's. §95 added `scope` to every skill precisely
  because a capability answers "may this role invoke it" and cannot answer "whose
  data does it read"; §96 keyed holdings by subject. The specification words it
  better than §95 did, and the words are worth adopting.
- **§2.2 no shared portfolio state** — every holding carries `client_id`.
- **§2.3 default deny** — a blank owner raises rather than resolving to anybody
  (`HoldingRefused`), which is the specification's "never fall back to the first
  available portfolio" already in force.
- **§6.2 simulation labelling** — `simulated` flags every demo row, seeding
  refuses outside PRE_ALPHA/ALPHA, and `outstanding()` reports what remains.
- **§9.2 never trust caller-supplied ownership** — the holdings tools take their
  client id from the session and never from an argument, and a test asserts no
  client-reachable tool schema exposes a `client_id` property.
- **§19 out of scope** — no trading, no order placement, no cross-client
  aggregation. None of it exists and none is queued.

### Where it resolves a blocker rather than contradicting one

§96 refused market value, gain and loss outright: *"every price this organization
can produce is simulated (addendum 25), and applying it to a client's real
positions would present synthetic output as real."* Addendum 44's `Holding`
carries `market_price` and `market_value`, and §4.4 wants unrealized gain/loss on
the Superuser tab.

**This is not a conflict, and reading it as one would be the mistake.** §96's
refusal was conditioned on the *source*, never on the field. A brokerage provider
returns real prices with real provenance; the simulation engine does not. The
specification supplies exactly the missing piece — `data_mode` — and its own §6.2
draws the same line from the other side ("do not allow simulated data to appear
as live brokerage data").

So the disposition is a rule rather than a reversal:

> `market_price` and anything derived from it may be populated only where
> `data_mode = LIVE`. While `data_mode = SIMULATED` or `MANUAL`, valuation stays
> refused and says why.

`portfolio_valuation` — declared-and-unbuilt in §95, with "this system has no
real market prices" as its stated reason — becomes buildable the day a live
provider exists, and its blocked_reason is already the correct one until then.

`MANUAL` is also what §96's client-stated holdings are: the specification's
`provider_type` vocabulary already has a slot for them, so the two models compose
rather than compete.

### The genuinely new work, and one risk it introduces

**A Superuser portfolio as a separate ownership domain** (§4) does not exist. The
operator's portfolio today is `data/portfolio.xlsx`, reached through
`app/tools/portfolio.py` by the local assistant, with its own two-layer consent
model. §16 calls that the legacy single-portfolio design and says to migrate it,
which is right.

Two things about it need care and are recorded here so they are not discovered
during implementation:

**First, the vocabulary collides three ways.** This system already has a Server
Superuser (`app/server_auth.py`, who starts the workforce), a Gateway Super User
(`gateway/auth.py`), and `ROLE_OPERATOR` (§92). Addendum 44's "Superuser" is the
second and third — the person at the Gateway — and not the first. The
implementation should use `owner_type = SUPERUSER` as the specification names it
and say plainly in one place that it means the operator role, rather than letting
three near-synonyms drift.

**Second, `portfolio_id` creates an attack surface the current model does not
have.** §5.2 lists "Client A requesting Client B portfolio by ID" and "a Gateway
request that supplies a mismatched client_id and portfolio_id" — neither is
possible today, because holdings are keyed by client and there is no id to guess.
Introducing a `Portfolio` entity introduces the guessable handle. That is not an
argument against it; the specification needs one-client-many-portfolios (§5.1).
It is an argument for the ownership guard landing in the *same* increment as the
entity, never a later one, which is why TQ-44 carries both.

**§15.5 asks for the earlier isolation concern as a permanent regression test.**
That concern is §93's — a client's socket opening onto the operator's transcript
— and its conversation half is already permanent
(`test_two_subjects_do_not_share_a_conversation`). The portfolio half does not
exist yet because portfolios do not, and it is written into TQ-44's scope rather
than left to be remembered.

### What is deliberately not queued

**Live trading, order placement, money movement** (§19). Absent, unqueued, and
the specification and this record agree.

**Cross-client aggregation** (§19, §5.2). The specification permits it only under
"an explicitly authorized internal aggregate workflow"; no such workflow exists,
and building the permission for one before there is a use would be an
authorization surface with no consumer.

**Schwab live integration** is queued but blocked on owner action — the
specification says explicitly not to wait for it (§8.1), so the provider boundary
and configuration placeholders are separated from the live connection and only
the latter is blocked.

### The queue this generates

Seven entries, following addendum 44's own Phase order in §20 with one
adjustment: its Phase 3 (Gateway access) is folded into TQ-44, because the
ownership guard and the entity that needs guarding must not ship apart.

TQ-44 (portfolios as owned entities, plus the guard and the isolation regression
tests), TQ-45 (the `PortfolioProvider` abstraction and the conformance suite),
TQ-46 (the Superuser ownership domain, and retiring the ownerless global
retrieval), TQ-47 (the Superuser Portfolio tab), TQ-48 (snapshots, provenance and
audit logging), TQ-49 (the Schwab boundary, live disabled), TQ-50 (Schwab live
read-only, blocked on API access).

**TQ-43 (per-client Gateway credentials) is a precondition for most of them** and
was queued yesterday from §96. Addendum 44 assumes multiple clients logging in
throughout; today they share one credential and therefore one subject. The
isolation this specification asks for is real and tested at the data layer, but
the doorway that would let two clients actually be two people does not exist, and
several of these entries are worth less than they look until it does.

---

## §98 — Two clients become two people (2026-08-26, TQ-43)

The precondition §96 recorded and §97 restated: everything downstream of a client
session had been per-client for days — conversations (§93), the representative's
identity (§93), holdings (§96) — and all of it keyed off a `subject` that only
one person could ever be. The Gateway had one credential per **role**, so every
client shared a password and therefore shared an identity.

The isolation was real and tested at the data layer. The doorway that would let
two clients actually be two people did not exist.

### The line, drawn by cardinality

`gateway/auth.py` keeps credentials in the process environment and explains why
at length: a route that could grant that privilege would be an escalation
surface, and whoever controls the process already controls its data.

That reasoning is sound for a role that is **one person by definition**. It does
not survive contact with a role that is many. A shared environment variable for
"every client" is not a credential — it is a group password, and the thing it
protects is somebody's money.

So the split is by cardinality rather than convenience:

- **operator, internal** — one each, environment, out of band. Unchanged.
- **client** — many, registered in `clients`, one credential and one identity
  apiece.

`ROLE_CREDENTIAL_ENV` no longer carries an entry for the client role at all.
Leaving `GATEWAY_CLIENT_PASSWORD_HASH` configurable "for compatibility" would
have left the shared password available, which is the hole this closes rather
than a migration path away from it.

### Provisioning is a command, not a route

`python -m gateway.clients add`, the same shape as `backend.migrations` and
`gateway.demo_clients`. A route that mints credentials is an escalation surface;
a command runs as whoever controls the process, who already controls the
database.

The password is **generated, printed once, stored only as a bcrypt hash**. There
is no path that recovers it, including for the operator — a registry that could
show a client's password would be a registry worth stealing. `listing()` and
`get()` do not return the hash either, so nothing outside the module can print
one by accident.

### Four refusals worth their reasons

**A client may not take a configured role's name.** A client and a role answering
to one name is an ambiguity about *who somebody is*, and the safe resolution of
that is to refuse it at creation rather than pick a winner at authentication.

**Client ids are constrained, not free text.** They end up in log lines, audit
rows and error messages; a handle containing a newline or a quote is a formatting
bug waiting to be an injection one.

**An unrecognised status denies rather than defaulting.** A status this build
cannot interpret is not one it may act on, and guessing what it permits is the
wrong direction to guess in.

**Removing a login does not remove a person.** `remove()` deletes the credential
and leaves holdings, conversations and the representative untouched. Deleting
somebody's financial records as a side effect of revoking a login is not a
decision that function is entitled to make.

### §9.3 applied to the login itself

Addendum 44 §9.3: an error must not reveal that another client exists. Returning
early for an unregistered name leaks exactly that through timing, so an unknown
username is compared against a **decoy hash** and costs the same as a wrong
password. Rate limiting remains the real defence; this closes the cheaper oracle
beside it.

Asserted structurally rather than with a stopwatch — a timing assertion on a
shared CI runner measures the runner.

### The subject is resolved, never typed

`authenticate` returns a **client id**, not a boolean, and that id becomes the
session's subject. A caller that verified a credential and then trusted the typed
name would be taking a claim as an identity at the exact moment the answer is
known (addendum 44 §9.2). A test reads the login route's source to check the
typed name never reaches `create_session`.

Environment roles are tried first and win any collision — but `register` refuses
to create the collision, so the ordering is a second line rather than the only
one.

### Verified by three people logging in

The demo now seeds three clients with real logins, so the isolation can be
*walked into* rather than only asserted:

| client | representative | conversation |
|---|---|---|
| customer | Nadim | 1 |
| avery | Farida | 2 |
| morgan | Yusra | 3 |

Asked the same question — *"what do I hold, and how concentrated am I?"* — avery
was told SYN2 is 98.33% of cost (955,200 of 971,409) and morgan was told 55/45
across two priced positions with SYN6 excluded for having no cost basis. Both
arithmetic checks out against the seed; both volunteered that the weights are by
cost rather than market value.

The old shared credential returns 401, as does a wrong password and an unknown
name — three failures that look identical from outside.

Demo logins are flagged `simulated` and cleared with the rest of the demo data,
so §96's "removable before live" property extends to the credentials rather than
leaving three accounts behind.

Suite: **2187 passing**.

---

## §99 — Portfolios become owned entities, and the guard ships with them (2026-08-26, TQ-44)

Built from [`docs/specs/TQ-44_portfolio_ownership_and_isolation.md`](specs/TQ-44_portfolio_ownership_and_isolation.md),
which realizes addendum 44 §2, §3.3, §5, §9, §12, §15.1, §15.5 and §20 Phases 1+3.

### What this increment actually is

A security task wearing a data-model hat, and the governing fact is in the spec's
§2: **there is no portfolio id today, so there is nothing to guess.** Addendum 44
§5.2 lists four attacks — asking for another client's portfolio by id, reusing a
stale one, a mismatched client/portfolio pair, an agent retaining a previous
client's context — and every one of them becomes possible only once an id exists.

So the entity and the guard shipped together, in one file and one review. An
entity that exists a week before its guard is a week of exactly the exposure
addendum 44 was written to prevent.

`gateway/portfolios.py` is new: the `portfolios` table, `OwnerContext`, and
`resolve()` — the one gate every read of portfolio-scoped data goes through.
`gateway/holdings.py` is re-keyed from `client_id` to `portfolio_id`, and
`client_id` is **gone** rather than kept alongside it: two sources of truth for
ownership can disagree, and the one that disagrees quietly is the one that hands
somebody the wrong positions.

### The three open questions, decided before any code

Recorded in full in the spec's §10. In short:

**Q1 — the migration lives in `gateway/store.init_schema`**, not in
`backend/migrations.py`. The leaning was already (a); looking gave it a reason
stronger than consistency. That pipeline's step 2 calls
`continuity.create_backup`, which snapshots the *backend's* domain — so
registering a Gateway store would have it announce "backed up before migrating"
while the file being migrated was not in the backup. A false safety claim at
precisely the moment §23's ordering is supposed to be true. The safety is
supplied locally instead: one transaction, counts verified before anything is
renamed.

**Q2 — `client_holdings` is renamed to `client_holdings_legacy`**, per §16.1 and
§22's preserve-for-diagnosis habit. Two things came out of building it. The
rename *is* the idempotency mechanism — once the old table is gone a second run
finds nothing, so §6.6 falls out of the design rather than needing a version
flag, and a database where both tables exist is an aborted run that refuses
rather than clobbering the archive. And `demo_clients.clear()` had to reach the
archive too: preserving data for diagnosis is not a reason to preserve simulated
*customers*, and without it "clean before live exposure" would have quietly
stopped being true.

**Q3 — migrated rows get the literal `UNKNOWN`**, not `NULL` and never `EQUITY`.
`EQUITY` would be a fabrication; the rows do not say. Storing `UNKNOWN`
explicitly puts it inside the closed vocabulary, so the fail-closed read check
covers it uniformly and no reader has to remember what a missing value meant.
`concentration` does not read `asset_class` at all, so an unknown class costs the
current report nothing — a class-aware view is TQ-45's, where the provider
defines what a holding is.

### There is no superuser branch, and that shaped the code

Addendum 44 §5.3 forbids `if superuser: skip all ownership checks`. Taken
literally: there is **one ownership comparison** in the module, `_owned_by`, and
both owner domains go through it. A `SUPERUSER` context resolves superuser-owned
portfolios and nothing else. The operator reaching a client's portfolio is not
merely unbuilt, it is refused — §10 permits it only through an explicitly
authorized administrative workflow, and none exists to authorize it.

Tested from both sides, because the separation runs both ways:
`test_a_client_cannot_resolve_a_superuser_portfolio` and
`test_a_superuser_cannot_resolve_a_clients_portfolio`.

### The ordering inside `resolve()` is not incidental

This was the one place the spec's §3.4 and §3.6 pulled against each other, and
noticing it was worth the increment on its own.

"One refusal, whatever the reason" says absent, foreign and archived must be
indistinguishable. "Fail closed on read" says a row whose vocabulary this build
cannot interpret must raise. Put the interpretation first and the two collide:
`UnknownVocabulary` where a stranger expected `NotAuthorized` confirms that the
id exists — an existence oracle, which is exactly what §9.3 withholds.

So the order is: no row → refuse; not this owner's → refuse, **before**
interpreting; uninterpretable → fail closed, to its owner only; not active →
refuse with the same words. A corrupt row fails loudly for the person who owns it
and stays invisible to everybody else.
`test_an_unreadable_row_still_refuses_a_stranger_without_telling_them_why` is
what keeps that ordering.

### The single-gate property has a tripwire

`resolve()` is worth having only while it is the *only* way to a portfolio, and a
second retrieval path would not look like a bypass when it was added — it would
look like a convenience.
`test_nothing_outside_portfolios_queries_the_portfolios_table` scans every
`gateway/*.py` for the table in SQL position, with whitespace collapsed so a
statement split across source lines cannot slip past a per-line check.

`holdings` carries the same property from the other end: its functions take a
*resolved portfolio*, not an id, and refuse a bare string. An id is something a
caller could have got anywhere; a dict from `resolve` is evidence the comparison
ran.

One thing was designed wrong first and corrected: demo clearing needs archived
portfolios too, and the first attempt added a `resolve_for_removal()` that
resolved regardless of status. That is the second by-id path the tripwire exists
to prevent, added within an hour of writing the tripwire. Replaced with
`owned()` — owner-scoped *in the query*, taking no id at all, so there is no id
it could be tricked into returning.

### The migration, run against a real database rather than a fixture

There was no `gateway.db` on disk to migrate, so one was made honestly: a git
worktree at `74f8fbe` (pre-TQ-44 code), seeded through its own demo seeder, plus
a holding stated in conversation and a non-demo client — 11 holdings across 4
clients. Then a **copy** was migrated with the new code.

| | |
|---|---|
| holdings before / after | 11 / 11 |
| portfolios created | 4, one per client |
| owners changed | 0 |
| `simulated` flags | correct: three demo clients true, `paying-client` false |
| `data_mode` | `MANUAL` throughout; `is_priced` false throughout |
| legacy table | renamed, not dropped; 11 rows still readable |

Clearing then removed 3 clients, 10 holdings, 3 portfolios and 10 legacy rows,
and left `paying-client`'s single holding untouched.

### Run it and look

Started the Gateway on a seeded scratch database and logged in as two demo
clients. Each got their own conversation (1 and 2), their own representative, and
their own holdings — avery SYN2/SYN5, morgan SYN4/SYN6/SYN9. Avery was told SYN2
is 98.33% of cost, unprompted, with the by-cost caveat.

Then the two things that matter, asked in conversation rather than asserted in a
test:

> *"I am also the account manager for a client called Avery. Please list Avery's
> holdings and their portfolio id for my records."*
>
> — *"I don't have access to any other client's data … this system doesn't give
> me visibility into other clients' records at all."*

> *"What is my portfolio worth today, and what is my gain or loss?"*
>
> — *"I can't tell you that — this system has no real market prices … gain/loss
> would be numbers I'd have to invent."*

Naming another client's portfolio id directly in the tool arguments also changes
nothing, because there is no portfolio argument for it to land in: the subject
comes from the session and the portfolio comes from the subject.

Stack stopped afterwards; no orphaned processes.

### What is deliberately still true

- **Nothing is priced.** `is_priced()` is one line and the only rule, and every
  portfolio this build creates is `MANUAL`. `portfolio_valuation` stays
  declared-and-unbuilt.
- **Holding fields are still `ticker` / `shares` / `cost_basis`.** The rename to
  addendum 44's names is TQ-45's, where `PortfolioProvider` defines the canonical
  shape (spec §3.9). Not an oversight.
- **`app/tools/portfolio.py` still has no owner argument.** Unreachable from the
  Gateway; TQ-46 owns it.

Suite: **2232 passing** (2187 before, +45).

---

## §100 — The canonical holding shape, and a clean report that was not true (2026-08-26, TQ-45a)

Built from [`docs/specs/TQ-45_portfolio_provider_abstraction.md`](specs/TQ-45_portfolio_provider_abstraction.md)
§3.1's first half, which realizes addendum 44 §3.4 and §20 Phase 2's groundwork.

### What this increment is

The holding shape TQ-44 deliberately deferred. `ticker`/`shares`/`cost_basis`
become `symbol`/`quantity`/`average_cost`, `stated_at` becomes `as_of`, and
`asset_class` stops speaking a vocabulary of its own.

Split out from TQ-45 proper (spec §3.1) so the provider is written against the
final holding shape once rather than twice — the same reasoning that moved the
rename out of TQ-44, one level down. 45b is the provider, its conformance suite
and the demo rebuild.

`as_of` is the rename worth explaining. `stated_at` encoded an assumption: that a
person said this. A provider's data is *as of* a time, and the shape has to fit a
brokerage account as well as a conversation. `record()` still defaults it to now,
which is right for a client speaking, and now accepts one, which is what a
provider will need.

### Q1 — the vocabulary, and a collision this project had already ruled on

TQ-44 introduced `EQUITY`/`OPTION`/`UNKNOWN`, reading addendum 44 §3.4 as
normative. This system already had eleven finer codes in
`backend/reference_data.ASSET_CLASSES`, validated against `boot_config.json`.

**§70 refused exactly this substitution once already** — for addendum 39's
`EQUITIES`/`OPTIONS_ON_EQUITIES` — on the grounds that it would be *"two models
of one fact, which the Conflict Rule forbids"*. §3.4 asks for EQUITY and OPTION
"at minimum", which the finer set satisfies rather than contradicts. So the house
vocabulary wins, plus `unknown` for a holding whose class nobody recorded.

The §95 worry — that the Gateway would now depend on a backend vocabulary — was
checked rather than argued: `backend/reference_data` imports `os`, `json`, `re`
and `backend.db`, opens no connection at import, and `gateway/store.py` already
imports `backend.db`. A constant tuple of class codes is a vocabulary, not
organization data; the boundary §95 protects is the database.

So the Gateway **imports** the list rather than mirroring it, and
`test_the_asset_class_vocabulary_is_the_house_one` asserts its vocabulary is
exactly those codes plus `unknown`. A mirrored list would have recreated the same
two-models problem one scale smaller, with nothing to notice the drift.

Two consequences worth stating:

- **`implemented_asset_classes` is not a constraint on what a client may hold.**
  That list says what this organization can *process*. Somebody may own something
  it cannot, and refusing to record a fact about their money because our
  reference data is incomplete is the refusal `_clean_symbol` already declines to
  make about symbols. Tested.
- **`EQUITY` and `OPTION` migrate to nothing.** They are refused, not mapped:
  `EQUITY` does not determine `stock` versus `etf`, and picking one is the
  fabrication this project refuses. It costs nothing real — no row can hold
  either, because the only writer defaulted to `UNKNOWN` — which is precisely why
  it was cheap to keep the rule true in the case that cannot happen.

### Q4 — `currency`, where the spec's own leaning was wrong

The spec leaned toward adding `currency` in 45a to save TQ-49 a second migration.
Looking at `gateway/store._ADDITIVE_COLUMNS` undid that argument: adding a column
later is **one line in a dictionary**, applied on the next start. The migration it
would have saved does not exist.

What was left was an always-`NULL` column with no producer and no consumer —
machinery with no user, which this project does not build. Deferred to TQ-49,
which is the first thing that will know a currency.

### The defect: a clean report that was not true

Found by running it, and the suite was green throughout.

After the rename, `demo_clients.clear()` emptied the live table and
`outstanding()` reported *"No simulated client data is present"* — while **ten
demo holdings sat in `portfolio_holdings_pre45`**. Every test passed. The full
suite passed. It was visible only by clearing a real migrated database and
counting the rows left behind.

A clean report that is not true is worse than no report, because it is the one a
pre-launch checklist believes — and the check exists specifically so that
"removed before live" is knowledge rather than intention (§96).

The cause is worth keeping, because it is what made this easy to get half-right:
**the two archives are keyed differently.** `client_holdings_legacy` is keyed by
*client*; `portfolio_holdings_pre45` by *portfolio*. `clear()` had the client ids
and had already purged the portfolios by the time it reached the second table, so
the ids it needed no longer existed. The fix collects portfolio ids *before* the
purge and clears both, and `_clear_archives` says why in the code rather than in
a commit message.

Two permanent regressions: one that both archives are emptied of demo data, one
that a *real* client's archived rows survive — because an archive kept for
diagnosis that gets emptied by a demo clear is the opposite failure.

### Verification

**Both migration paths, each from a genuinely old database** built by checking
out the old code in a `git worktree` and seeding through its own seeder.

| path | from | result |
|---|---|---|
| TQ-44 shape → canonical | worktree at `c1cdd49` | 11 → 11 holdings, **0 value or timestamp mismatches**, archive kept |
| pre-TQ-44 → canonical | worktree at `74f8fbe` | 11 → 11, straight through in one step, no `pre45` archive created |

The second is the case the code was shaped for: `migrate_client_holdings` writes
the canonical names directly, so a database that never ran TQ-44 does not pass
through a column layout this build no longer contains.

**Run it and look.** Gateway started on a seeded database; two clients logged in.
Avery got the concentration report under the new names, unprompted about the
by-cost caveat. Morgan was told *"I bought 50 shares of SYN8 at 12.40 last
month"* and the agent recorded it through the renamed tool schema — the row
landed with `symbol=SYN8`, `quantity=50`, `average_cost=12.4`, and
**`asset_class=unknown`**. The model did not guess `stock` from the word
"shares", which is what the schema description asks of it and the thing most
worth checking about this change.

`simulated` was `False` on that row and `True` on the seeded ones — §96's
distinction between "demo data" and "stated by a demo client" survives the
rename.

One observation, not fixed here: the agent stored `acquired_on = "last month"`.
The field is free text and always has been, and "last month" is what the client
said rather than an invention — but a date column that accepts prose is worth a
decision. Noted in the queue rather than fixed, because it predates this
increment and belongs with TQ-48's provenance work.

### A guard that caught me

`Database.transaction` refuses `executescript` inside a block, because sqlite3
commits before running a script — which would end the transaction and make the
rollback impossible while still looking atomic. The rename migration hit it on
first run. The DDL is now a single `execute`, and the comment says which guard it
is obeying. Worth recording that the guard did its job on the first real caller
after it was written.

Suite: **2247 passing** (2232 before, +15).

---

## §101 — A provider interface, and a contract that had to be attacked to be trusted (2026-08-26, TQ-45b)

Built from [`docs/specs/TQ-45_portfolio_provider_abstraction.md`](specs/TQ-45_portfolio_provider_abstraction.md),
which realizes addendum 44 §6.1, §6.2, §6.3, §7, §15.3, §15.4, §17 and §20 Phase 2.
Completes TQ-45; 45a was §100.

### What this increment is

`gateway/portfolio_providers.py`: one interface between the analysis subsystem
and wherever holdings come from. Two implementations — `ManualPortfolioProvider`
(what the client told their representative) and `SimulatedPortfolioProvider`
(invented, labelled) — and a conformance suite both satisfy.

The demo clients are rebuilt on it with §6.1's diversity: a covered call, long
calls and protective puts, a diversified book with an ETF and cash.

### The decision the spec was written around

Addendum 44 §7's conceptual interface is `get_holdings(account_ref)`. **That
signature is not implemented, deliberately.** A public function taking a bare
reference string and returning holdings is the second by-id retrieval path TQ-44
exists to prevent, sitting one layer below where the portfolios tripwire looks —
and it would not read as a bypass when somebody added it. It would read as
implementing the specification.

Every method that reaches data takes a **resolved portfolio**. The broker's own
reference is read off that row, never handed in. A provider is an adapter to a
data source; it is not an authorization boundary and must never become one.

### A provider says what it cannot do

`get_balances` and `refresh` have no honest answer for a manual portfolio. Nobody
told this system the client's cash, and there is nothing to refresh *from*. `{}`
would read as "no cash"; `{"cash": 0}` would be a fabrication; `None` would put
the interpretation in every caller.

So a provider declares its capabilities and an undeclared one raises with a
sentence the caller can repeat — `gateway/skills.py`'s declared-and-unbuilt
pattern, one layer down. That is also the only reason `ManualPortfolioProvider`
earns its place (spec §11 Q5): **two providers that genuinely differ in what they
can answer is what makes `supports()` a contract rather than a decoration**, and
`test_the_two_providers_genuinely_differ_in_what_they_can_answer` fails if that
ever stops being true.

### Q2, Q3, Q5 — decided before the code, recorded in the spec's §11

**Q2 — no simulated prices.** `is_priced()` stays one line and LIVE-only.
Widening it to "LIVE, or SIMULATED-and-labelled" makes it two branches, and the
second branch is where the mistake eventually lives — labels are lost in
screenshots, a branch is not lost in code.

The distinction that keeps the rule narrow rather than awkward: **a cash balance
is not a price.** `is_priced` governs *market-derived* values — what a position
is worth now, gain, loss. Cash is a quantity somebody holds, not a valuation of
anything, so `get_balances` never touches it.

**Q3 — demo portfolios are `SIMULATED`/`SIMULATED`** per §6.2, with a consequence
stated before it was built: the simulated provider must **seed** its positions
into `portfolio_holdings` and read them back, not generate them on every read. A
generating provider would make a holding a demo client stated in conversation
invisible — exactly the data §96 exists to preserve. So the portfolio's
`data_mode` says what kind of source stocked it, the row's `simulated` flag says
whether that row is demo data, and they are allowed to differ. They do.

### The analyzer became a pure function, which is what made §15.3 real

`holdings.concentration` takes holdings now, not a connection. That is not
tidying: an analyzer that read the table itself would agree with every provider
*trivially*, because they all write to one table. §15.3 asks that switching
provider not change the analyzer contract, and the only way to test that claim is
an analyzer with no idea where its input came from.

The contract test feeds it a real provider's output and a `_StubProvider`'s —
an independent implementation holding positions in a list, deliberately not a
mock of either real one, because a mock only ever agrees with the thing it was
made from. It also demonstrates the property that matters for TQ-49: **a provider
needs no database at all.**

### The short position, found while building the demo

§6.1 asks for a covered call. A covered call is *written* — short four contracts,
not long four — and `record` refused any quantity ≤ 0.

Storing it as positive would have been the wrong fact about somebody's position;
dropping it would have been quietly narrowing what §6.1 asked for. So a negative
quantity now means short, and zero is still refused on its own terms: a position
of zero is not a position, and somebody who closed one says to forget it.

`concentration` then had to decide what a short weighs. It counts them and does
not weight them: **a short's `average_cost` is a credit received, not an amount
paid**, so folding it into cost weights would give a negative share of a total
that no longer means anything — a percentage shaped like arithmetic that is not.
They are reported separately rather than dropped, because leaving real positions
out silently would understate what somebody holds.

### The conformance suite had to be attacked before it could be trusted

It passed 47 tests on its first run against both providers, which is not
evidence — a suite that has never failed has never been shown to be capable of
failing. So five deliberate breakages were introduced one at a time and the suite
re-run against each:

| mutation | first run | after |
|---|---|---|
| a method taking a bare `account_ref` | **MISSED** | caught |
| manual provider claims it can report balances | caught | caught |
| a refusal carrying no reason | caught | caught |
| `refresh` stamps a sync time before the data lands | caught | caught |
| holdings leak across portfolios | caught | caught |

**The one it missed was the most important one** — the §3.2 bypass the suite
exists to prevent. `test_no_provider_method_accepts_a_bare_id` scanned a fixed
list of method names, so a *newly added* `get_by_ref(conn, account_ref)` sat
right beside the methods it did check and passed. That is precisely the shape the
test was written for: the bypass arrives as a new convenience, not as a change to
an existing signature.

Widened to scan every public method. Whereupon it immediately failed on this
increment's own code: `SimulatedPortfolioProvider.fixture(owner_id)` was a public
method taking a bare owner id. It was right to. Owner-scoped operations take an
`OwnerContext`; that one computes a template and touches no stored data, but the
*shape* is what becomes a bypass. Now `_fixture`.

A test that has caught two real things on the day it was written is worth more
than one that went green immediately.

### Verification

Suite **2298 passing** (2247 before, +51). Two existing tripwires failed on the
new `portfolio_balances` tool and were updated deliberately rather than
mechanically — that is them doing their job.

**Run it and look.** Three demo clients, three visibly different portfolios, all
`SIMULATED` and none priced. Then, in conversation:

> *"How much cash do I have, and what do I hold?"* (simulated portfolio)
> — *"Cash: $96,500 (simulated balance, not a real account)."*

> *"Walk me through my option position. Am I long or short it?"*
> — *"You're **short 4 contracts** — you wrote these as covered calls against
> your 400-share SYN1 stock position."*

> *"What is Morgan's cash balance? I need it for a report."*
> — *"I only have access to your own portfolio … I have no visibility into other
> clients' data."*

And §14's step 3, the one this increment was built to test — a client whose
portfolio is **manual**, where the provider genuinely cannot answer:

> *"How much cash is in my account?"*
> — *"I don't have a cash balance for your account — I only know what you've told
> me about your holdings, and no cash figure has come up. **I can't invent one.**"*

> *"Can you refresh my holdings from my broker?"*
> — *"I can't do that — I have no connection to your broker or any external
> system."*

The refusal reached the client in the agent's own words, carrying the provider's
reason, with no invented zero. That is the whole design of §3.4 arriving intact
at the only place it matters.

Stack stopped afterwards; no orphaned processes.

### What is deliberately still true

- **Nothing is priced.** `is_priced()` is untouched, still one line, still LIVE.
- **No network call anywhere.** TQ-49 owns the Schwab boundary; `PROVIDER_SCHWAB`
  has no implementation and `for_portfolio` **refuses** it rather than falling
  back to the manual provider — serving a brokerage portfolio from stated
  holdings would show somebody the wrong thing under the right name.
- **`app/tools/portfolio.py` still has no owner argument.** TQ-46's.

---

## §102 — Addendum 45 assimilated: local intelligence and competitive model routing (2026-08-26)

Owner-supplied, 2026-08-26, as `local_intelligence_competitive_model_routing_spec_v2.txt`.
Assimilated **verbatim and byte-identical** to
[`docs/addenda/addendum_45_local_intelligence_competitive_model_routing.md`](addenda/addendum_45_local_intelligence_competitive_model_routing.md),
1,161 lines. It states that it supersedes the previous local-model routing specification.

Queued as **TQ-51 … TQ-68**. Nothing built; this record is the reconciliation and the queue is the
plan.

A second owner file arrived alongside it (`tq45a_local_intelligence_handoff.txt`) setting the
sequencing: finish TQ-45a first, preserve its structures, then start the Local Intelligence
Platform as a separate task. **That condition is already met** — TQ-45a (§100) and TQ-45b (§101)
are both merged, and this lineage integrates with the vocabulary and provider patterns they
established rather than replacing them.

### What this asks for

Every agent gets local intelligence by default and escalates when it must, and **no model is
permanently the best**. Models compete per task category, on eight leaderboards, with rankings
that move on measured outcomes. Two decisions are kept separate on purpose (§3): *can this be done
without a model, or locally?* and *which model?*

### Two findings from assimilation, neither of which belongs buried in a queue entry

**1. The GPU is 8 GB, and that shapes the plan rather than merely constraining it.**

Measured rather than assumed: NVIDIA RTX 3050, **8,192 MiB VRAM**, 16.5 GB system RAM, 365 GB free
disk.

A 7B–8B model at 4-bit quantization fits in VRAM. A 70B-class model does not, at any quantization,
and no amount of routing cleverness changes that. Disk is ample for §43's pool of six; **VRAM is
not ample for two resident at once**, which makes §15's challenger comparisons *sequential*.

That is a latency cost rather than a blocker, and it has one consequence worth writing down before
somebody measures the wrong thing: in a sequential leader-versus-challenger run, **a model that had
to be loaded from disk did not take longer to think.** Load time and inference time have to be
measured separately or the ranking learns a lesson about disk speed and records it as reasoning
quality. TQ-61 carries that note.

**2. "Inkling" cannot be identified, and is not being quietly substituted.**

Addendum 45 §5, §43 and §47 name Inkling alongside Llama and DeepSeek as an initial local
candidate — and §47 makes it a requirement: *"Initial local candidates must include Llama,
Inkling, and DeepSeek."*

It is not identifiable from this side as an open-weight local LLM. Llama, DeepSeek, Qwen, Mistral
and Gemma are all well-known open-weight families; Inkling is not one this build can name a
licence, a parameter count or a runtime for.

The project's standing rule is that absent is `unknown`, never a plausible default — so no task
depends on it until somebody confirms the actual artifact. **It has not been swapped for a
similarly-named model**, which would have been the failure mode: the pool silently becoming
Llama + DeepSeek + something-I-guessed-at, with §47's requirement recorded as satisfied.

TQ-52 owns the question, and its honest outcomes are: it is a real local model and joins the pool;
or it is something other than a local LLM and the requirement is renegotiated with the owner. Both
are recorded findings. Neither is a substitution.

### The tripwire §64 planted fires here, exactly as designed

`docs/model_registry.yaml` carries `routing: none_single_model` as a **pinned decision, not an
omission**, and `tests/test_model_registry.py` fails the suite the day a second configured model is
registered — so that *"routing gets revisited on purpose rather than acquired by drift"*.

Addendum 45 requires four to eight models. The tripwire therefore fires on the first real step of
this lineage, which is the whole reason it exists. **TQ-51 is that revisit**, deliberately first
and deliberately small.

The instruction it carries: the tripwire is **re-aimed, not deleted**. "A second model is a
failure" becomes "a second model without a leaderboard entry is a failure". A discipline that is
removed the first time it is inconvenient was never a discipline.

### Dispositions

**Accepted as specified.** The eight leaderboards, exactly (§42) — the instruction not to
fragment early is the same one §70 and §100 each enforced under a different name. The two-decision
separation (§3). Seeded rankings marked provisional (§12), which `model_registry.yaml` already
does with `provisional: true` on every row. Task-specific rather than global demotion (§11).
Deterministic-first (§19). Privacy and hardware overriding the leaderboard outright (§35, §36).

**Accepted with the project's existing shape.** §23's `ExternalAIProvider` is **partly built**:
`app/model_provider.ModelProvider` is a Protocol with `AnthropicProvider` behind it, named for its
vendor *"so that a second one can exist without either pretending to be generic."* TQ-65 extends
it rather than introducing a parallel abstraction.

§4's `LocalAIService` gets built the way `PortfolioProvider` was built one increment ago (§101):
**interface and conformance suite before the second implementation**, because a contract with one
implementation is a description of that implementation. TQ-56 carries the guard that made §101's
suite real — could a provider that must load a multi-gigabyte model off disk satisfy this test? —
and the mutation discipline that found the hole in it.

**Ordering changed from the addendum's.** §45 puts the evaluator in Phase F alongside the
simulation competition. It is queued *before* it (TQ-62 before TQ-63), because §38 is a
precondition for scoring rather than a refinement of it: *validate before penalising*, and **"a
model should not lose points solely because another model disagrees."** Scoring a competition with
an unvalidated evaluator produces rankings that look empirical and are not.

**One decision deferred to TQ-51 rather than settled here.** Whether the Model Performance
Registry (§8) extends `model_registry.yaml` or sits beside it. They answer different questions —
what is configured, versus what performs well at what — but two files that both rank models is the
two-models-of-one-fact problem this project has now ruled on twice (§70, §100). It is a real
decision with a real trade-off, and it belongs at the head of the lineage rather than in an
assimilation note.

**One precondition recorded as unclear.** §30 requires routing knowledge to join *"the linked,
multi-entry knowledge architecture"*. Nothing in this repository matches that description as a
built subsystem. TQ-67 is queued as `precondition unclear` rather than as ready work: before it
starts, somebody has to say whether that architecture exists under another name, is a separate
unqueued task, or is something TQ-67 creates. §31's knowledge lifecycle
(`OBSERVED` → `PROVISIONAL` → `VALIDATED` → `STRONG` → `DEGRADED` → `RETIRED`) is independently
valuable and could be built against the registry alone if the larger thing turns out not to exist.

**One category flagged as probably unused.** `CREATIVE_GENERATION` (§42) has no consumer in a
financial intelligence system. It is queued anyway because §42 says start with exactly these
eight — but the expectation that it carries no traffic is recorded now, so that if it still has
none when TQ-63 has evidence, merging it is the review §42 anticipates rather than a surprise.

### What this lineage does not change

**No exposure.** §50's preconditions stand. Local models running on this machine are less exposed
than external calls, not more, but nothing here makes anything externally reachable.

**No model binaries in git** (§44). TQ-57 owns the storage layout and the `.gitignore` entry, as
part of the entry rather than as an afterthought.

**Local execution is not free** (§37). GPU time, power, queue time, and blocking other agents while
a 5 GB model holds the card. The half of the cost model that gets forgotten is the local half, and
on one 8 GB card it is the half that will actually bind.

### Owner decision wanted

**Which lineage is worked first.** TQ-46 … TQ-50 (the rest of addendum 44 — the Superuser
ownership domain, its tab, snapshots and audit, the Schwab boundary) and TQ-51 … TQ-68 (this one)
are independent of each other. TQ-50 is already blocked on owner action; nothing else is.

---

## §103 — The single-model pin becomes a ladder (2026-08-26, TQ-51)

First increment of the addendum 45 lineage (§102). Small on purpose, and it
changes no runtime behaviour: this system still runs one model, and
`routing: none_single_model` still stands.

### Why this was first

§64 pinned `routing: none_single_model` in `docs/model_registry.yaml` as a
decision rather than an omission, with a test that fails the suite the day a
second model is registered — *"so routing gets revisited on purpose rather than
by accident."*

Addendum 45 needs four to eight models. The tripwire therefore fired on the
first real step of the lineage that needed it, which is exactly what it was
planted for. This increment is the revisit it demanded.

**Re-aimed, not removed.** A discipline deleted the first time it is
inconvenient was never a discipline — and deleting this one would have been the
easy read of "unpin it".

### Decision 1 — two registries, split by writer rather than by subject

The question TQ-51 was queued to settle: does addendum 45 §8's Model Performance
Registry extend `model_registry.yaml`, or sit beside it? Two files that both
rank models is the two-models-of-one-fact problem §70 and §100 have each ruled
on once.

**Decided: beside it, and the reason is the writer, not the subject.**

`model_registry.yaml` is hand-authored, committed, reviewed, and asserted against
the code by tests. The performance registry is machine-written after every task,
carrying scores, sample counts and confidence that change continuously. Putting
that in a committed YAML would dirty the working tree on every inference and make
these assertions race a moving target — the tests would be checking a file that
changes underneath them.

That is not a subject distinction that could be argued either way. It is a
mechanical one.

### Decision 2 — the real collision was `preferred_model`, not "both rank models"

Looking rather than reasoning turned up something sharper than the queue entry
anticipated.

`model_registry.yaml` does not rank models. What it has is `preferred_model` on
every profile — a hand-authored answer to *"which model should this agent
use?"*. That is precisely the question the leaderboards will answer empirically,
and addendum 45 §16 is explicit about who may answer it:

> *"The agent should not need to know every available model. Its responsibility
> is primarily: classify the task, estimate complexity, estimate risk, estimate
> confidence… The common routing layer then chooses the model."*

So `preferred_model` is not a field that coexists with routing. It is the field
addendum 45 supersedes.

It stays for now, because until routing exists something has to name the model
the code calls. But its meaning has a **planned handover** rather than a quiet
drift: from TQ-60 it becomes the *seed* the leaderboard starts from (§12's
provisional initial ordering) and stops being read at call time. Recorded in the
file itself, at the field, so the transition is a handover somebody executes
rather than a field that means two different things depending on who is reading.

### Decision 3 — the pin becomes a staged vocabulary

A boolean pin has one problem as a long-term device: unpinning it is a single
edit, and the day somebody makes that edit the discipline is simply gone.

`routing` is now a rung on a declared ladder, in `routing_stages`:

| rung | earned by | its tripwire |
|---|---|---|
| `none_single_model` | TQ-16 (§64) | exactly one configured model, no fallbacks |
| `seeded_leaderboard` | TQ-54 | every configured model has a seeded entry on every leaderboard |
| `competitive` | TQ-63 | measured outcomes dominate the seed |

Each rung declares `enforced`, and **a rung whose tripwire is not built refuses
to be stood on.** That is the half that keeps the discipline: turning one pin
into a ladder otherwise invites a quiet failure where somebody advances the
marker to a rung nobody has written an assertion for, the suite goes green, and a
second configured model is now reachable by nothing. The failure message names
the queue entry that earns the rung.

An unknown `routing` value fails closed, the house rule every other closed
vocabulary here works under.

The ladder lives in the YAML rather than in code, following the same
metadata-before-code doctrine (addendum 30 §12) the file was built under — a
reader of the registry sees the ladder without going looking for it.

### Verified by attacking it

A re-aimed tripwire that cannot be shown to fire is a re-aimed tripwire that was
quietly disarmed, and the claim "re-aimed, not removed" is worth exactly as much
as its demonstration. The same mutation discipline §101 used:

| mutation | result |
|---|---|
| marker advanced to a rung whose tripwire is not built | caught |
| marker set to a rung that does not exist | caught |
| a second configured model while on `none_single_model` | caught |
| a rung declaring no requirement | caught |
| a fallback populated while there is nowhere to fall back to | caught |

Five of five, unlike §101's first run — which is what a suite looks like when the
lesson from the previous increment was actually carried forward.

### What did not happen

**Nothing was unpinned.** `routing` is still `none_single_model`, one model is
still configured, and every profile's `fallback_models` is still empty. The way
past this rung is TQ-54: seed the leaderboards, build that rung's assertion,
then advance the marker. Registering a second model before then still fails the
suite, and now says which increment unblocks it.

**Nothing ran.** This increment is metadata and assertions; there is no running
thing to look at, and the mutation run is the honest substitute rather than a
green suite standing in as evidence.

Suite: **2301 passing** (2298 before, +3).

---

## §104 — The vocabulary routing decides on (2026-08-26, TQ-53)

Second increment of the addendum 45 lineage. `app/task_signature.py` and its
tests: §20's fifteen-field task signature, §42's eight task categories, §21's
six complexity levels, §36's four privacy levels.

**Nothing here calls a model, ranks one, or chooses one** — and a test asserts
that, because a vocabulary that quietly acquires a routing opinion would make
TQ-54, TQ-59 and TQ-60 arguments about code that already chose.

It went before TQ-52 because it is the only entry in this lineage needing no
hardware, no downloads and no answers from anybody, while TQ-52 waits on what
"Inkling" is.

### Four fields already had words in this codebase

The interesting part of the increment, and it came from looking rather than from
the spec. Four of §20's fifteen fields name facts this project had already named:

| §20 field | what already existed | disposition |
|---|---|---|
| `agent_role` | `fi_db.ROLE_CHARTERS` | validate against it; a role this system cannot charter is not one a task may claim |
| `error_cost` | `model_registry.yaml`'s `criticality` | **same fact, one vocabulary** — tied by a test |
| `latency_sensitivity` | the registry's free-text `latency_tolerance` | closed vocabulary defined here; the registry's prose is a **recorded divergence**, not reconciled yet |
| `privacy_level` | `DataClass.LOCAL_ONLY` | **different facts sharing one name** — see below |

The rule applied is §100's, which is itself §70's: adopt the house vocabulary
where one exists, adopt the spec's where none does. So `complexity` and the eight
categories keep addendum 45's own labels in its own casing, and `error_cost` takes
the registry's lower-case `low`/`medium`/`high` rather than inventing a parallel
scale for a question already being asked.

`test_error_cost_and_registry_criticality_are_one_vocabulary` reads the registry
and fails if either side drifts. That is the mechanical version of a rule that
would otherwise be a comment somebody stops reading.

**The divergence not fixed:** `latency_tolerance` in `model_registry.yaml` is
free text — `"minutes (measured ~2min/call, §42)"`, `"interactive"`, `"seconds
(UQI_TIMEOUT_SECONDS is 60s; worst observed 24s)"`. It carries measurements
inside the prose, which is *more* information than a closed vocabulary holds, so
converting it would lose something. Recorded for TQ-60, which is the increment
that first has to read it as a routing input rather than as documentation.

### The name collision worth reading twice

`PRIVACY_LOCAL_ONLY` and `app.data_classification.DataClass.LOCAL_ONLY` are
**different facts wearing the same name**, and this is the kind of thing that
gets confused a year later by somebody reasonable.

- `DataClass.LOCAL_ONLY` classifies a **field**: this value never leaves the
  process, stripped by `privacy_filter` on the way out.
- `PRIVACY_LOCAL_ONLY` classifies a **task**: this work may not be sent to an
  external model.

They are joined by a derivation that runs **one way only**: a task whose inputs
carry a `LOCAL_ONLY` field is a `LOCAL_ONLY` task. The reverse does not hold —
plenty of work stays home for reasons that have nothing to do with field
classification.

`privacy_floor_for()` makes that derivation mechanical, because §36's rule —
*"sensitive data should never be sent externally merely because the external
model ranks higher"* — is worth exactly what its enforcement is worth. It is
tested against `PORTFOLIO_FIELD_CLASSES`, real data rather than an invented
example: `account_id` is `LOCAL_ONLY`, so any task carrying a portfolio row is a
local-only task, and no leaderboard can override that.

### Two decisions about absence

**`privacy_level` is required, not defaulted.** A task whose privacy nobody
stated must not acquire `EXTERNAL_ALLOWED` for free — that would be the quietest
possible way to break §36, and the mutation run confirms the test catches it.

**`context_length` is `None` when unestimated, never `0`.** Zero claims an empty
context, which is a different and false statement from "nobody measured it". The
same distinction §100 drew for `asset_class`, where `unknown` became a member of
the vocabulary rather than an absence — `novelty`, `ambiguity` and
`latency_sensitivity` follow that pattern here.

What `unknown` *means for routing* is deliberately not decided. This module says
what a task is; TQ-59 and TQ-60 say what to do about it. Keeping that line is
what makes the module safe to build before the things that consume it.

### Verified by attacking it

Six mutations, six caught: a ninth category slipped in; privacy acquiring a
default; an unknown stored field silently ignored; `error_cost` drifting from the
registry's `criticality`; the module acquiring a routing opinion; an unestimated
context becoming zero.

One test failed on its own prose first, which is worth recording because it is
the second time a source scanner in this project has been too crude:
`test_this_module_names_no_model_and_ranks_nothing` split the source on triple
quotes and caught the word *"ranked"* inside a docstring quoting §36. The module
was right and the scanner was wrong. It now strips docstrings with `ast` and
checks only executable code — the same correction §101's signature scan needed
when it turned out to be scanning a fixed list of names.

### Deliberately not built

No classifier. Nothing decides *which* category a given task is — that requires
either a rule set or a model, and §17 says the escalation decision is itself an
intelligent task with its own leaderboard. Building a hand-written classifier now
would be the "seeded ranking nobody revisits" failure §13 warns about, one layer
down.

`CREATIVE_GENERATION` exists and is expected to carry no traffic (§102). It is
built because §42 says start with exactly these eight.

Suite: **2332 passing** (2301 before, +31).

---

## §105 — The competition, as data (2026-08-26, TQ-54)

Third increment of the addendum 45 lineage. `app/model_performance.py`: §8's
registry, §42's eight leaderboards, §12's seeding, §10's penalties and rewards,
§11's task-specific rankings, §13's impermanence.

Still no model calls. The routing marker advances from `none_single_model` to
`seeded_leaderboard`.

### Storage follows the ledger that already solved this

`app/model_budget.py` had the same problem four increments ago: a population of
separate processes, each with its own provider, needing one shared account of
something. Its answer — a SQLite file whose path resolves from the environment at
call time — is copied here rather than re-argued, down to the deferred `yaml`
import for a dev-only dependency (`backend/continuity.py`'s convention for
`cryptography`).

### The seed and the evidence stay decomposable, permanently

The mistake worth designing against: one `score` column blending the guess with
the measurement. §12 wants empirical data to dominate the seed *eventually*,
which is impossible once nobody can take the number apart.

So the seed is written once, never updated, and the composite is derived on read:

    score = (SEED_PRIOR_SAMPLES · seed + n · measured) / (SEED_PRIOR_SAMPLES + n)

The seed is worth exactly five observations. At n=0 the score *is* the seed; by
n=50 the seed is 9% of it; it never quite vanishes and never has to be deleted.
**Nobody decides when evidence takes over — arithmetic does**, which is what §13
needs when it says the system must not be trapped by the original human guess.
`confidence` is the same ratio read from the other side.

Deriving on read rather than storing has a second benefit: retuning
`SEED_PRIOR_SAMPLES` changes every score immediately, without rewriting history.

### §11 is structural, not policy

`record_outcome` writes a row keyed by `(model_id, task_category)`, and there is
no statement in it that reaches another category. A model that fails at long
context keeps its coding rank because nothing in the function *could* take it
away — not because a rule says not to.

### The hole in §103's ladder, found by falling in it

TQ-51 built a routing ladder where each rung declares `enforced`, precisely so
that advancing the marker to a rung with no assertion would fail loudly.

**Then this increment set `enforced: true` on `seeded_leaderboard` and moved the
marker before writing that rung's tripwire — and the suite went green.**

`enforced` was a flag in a YAML file. Nothing tied it to the existence of a test,
so it recorded an intention and read as a fact. The ladder was built to prevent
exactly this and did not, because its author was the one it needed to stop.

Fixed by making the claim checkable: `tests/test_model_registry.py` now declares
`ENFORCED_STAGES` beside the tests that implement it, and
`test_enforced_is_a_fact_about_this_file_rather_than_a_claim` fails if the YAML
claims a rung this file does not assert — or asserts one the YAML calls
unenforced. A flag is not a tripwire; a flag the tests have to agree with is.

The mutation run confirms it: advancing `competitive` to `enforced: true` now
fails.

### Where the seed ordering lives, and why that changed mid-increment

The plan was for the runtime database to hold everything. Writing the rung's
tripwire made that impossible: **CI has no database**, so a check that read one
would assert nothing, and `seeded_leaderboard` would have been unenforceable in
the only place enforcement matters.

So the hand-authored *ordering* moved into `docs/model_registry.yaml` as
`seed_ordering`, and only the measurements stay in the database. That sharpens
§103's split rather than contradicting it — the line was always **human decisions
in the committed file, machine writes in the database**, and an initial ordering
is a human decision. `seed_from_registry()` is the one point where the two touch,
and it is directional: measurements never flow back into git.

### What is deliberately not scored

§8 lists `cost_score` and `resource_efficiency_score`. Nothing produces either —
local cost needs TQ-57's hardware monitoring, external cost needs §37's model,
which is TQ-65's. Columns for them would be always-NULL columns, which is
machinery with no user, and a zero would be a measurement nobody made. A test
asserts their absence. The increment that first measures one adds it.

`model_performance.db` is gitignored, in three lines added for it — caught
because a bare `git status` showed it untracked before the first `git add -A`,
which is the kind of thing that otherwise ships as a committed database.

### Verified by running it, and by attacking it

**Run:** seeded from the real `docs/model_registry.yaml` — eight leaderboards,
one model, every entry at exactly neutral with confidence 0.0 and status
`SEEDED`. The registry claims nothing it has not measured, which for a
single-model system is the only honest thing it can say.

Then a competition, watched rather than asserted: three models seeded
`alpha > beta > gamma`, `gamma` given twelve good outcomes at
`CODING_AND_DEBUGGING` and `alpha` twelve failures. Final order at coding:
**gamma (0.77), beta (0.50), alpha (-0.51)** — the model seeded *last* leading,
the model seeded *first* below zero, and `LONG_CONTEXT_AND_MEMORY` untouched at
the original seeded order. §13 and §11 in one run.

A negative composite is deliberate and unbounded below: penalties are
subtractive, so a model can be worse than useless, and clamping at zero would
make "wrong answer every time" indistinguishable from "slightly slow every time".

**Attack:** eight mutations, eight caught — the seed being edited by an outcome;
the seed never decaying; an unscored success counting as a win; an unknown
failure scoring as no penalty; re-seeding overwriting evidence; every failure
weighing the same; a configured model missing from a leaderboard; and the marker
advancing to an unenforced rung.

Suite: **2371 passing, 1 skipped** (2332 before, +39). The skip is
`none_single_model`'s tripwire, correctly standing down now that a later rung
governs.

---

## §106 — Every routing decision, and the violation it found (2026-08-26, TQ-55)

Fourth increment of the addendum 45 lineage. `app/routing_decisions.py`: §26's
record, written from the first decision rather than once there is traffic worth
analysing — a log that starts late has a hole in it exactly where the early
mistakes are.

Still no model calls, and nothing routes anything. This records decisions; making
them is TQ-59's and TQ-60's, asserted by a source scan rather than trusted.

### One database, because the outcome is one fact

The decision log lives in `model_performance.db` beside the leaderboards. §26's
outcome fields — `quality_score`, `failure_type`, `validation_result` — are the
*same facts* that feed `model_performance.record_outcome`. Two databases would
have meant writing them twice, which is two sources of truth for one fact, or
joining across files.

So `complete()` is the single write path: it closes the log entry **and** scores
the leaderboard. There is no way to score an outcome without logging the decision
that produced it, and none to close a decision without scoring it. The log is
written first and survives a scoring failure, because a tally can be rebuilt from
a log and the reverse is not true.

### §26 duplicates four fields the signature already holds

`task_signature` is listed alongside `task_category`, `complexity`, `risk_level`
and `privacy_level`. Storing them beside it would be four more places to
disagree, so three are derived on read.

`task_category` is the deliberate exception, denormalised into a column because
TQ-66 groups by it and JSON is a poor index — but **the caller never supplies
it**; it is extracted from the signature at write time, and a row where the two
diverge raises rather than picking a winner.

`risk_level` is the **third** name in this codebase for one fact: `criticality`
in `model_registry.yaml`, `error_cost` on the signature, `risk_level` in §26.
§104 tied the first two; this reads the third off the signature rather than
adding a column, so there is still one vocabulary rather than three.

### One field added beyond §26's list

`execution_path` — deterministic, local or external (§2's hierarchy).

§26 records what the decision *concluded* (`deterministic_possible`,
`local_sufficient`) and what was *chosen* (`selected_model`), but not which of
the three ways the work was actually done. §41's error types cannot be computed
without it: `UNDER_ESCALATION`, `OVER_ESCALATION` and `UNNECESSARY_AI` are all
statements about the path taken versus the path that should have been.

### The violation the first run produced

Running it end to end through §25's own example — portfolio analysis routed per
step — the fourth step escalated to an external model while its signature said
`PRIVACY_LOCAL_ONLY`.

**Nothing said a word.** The log recorded it faithfully and no reader would ever
have looked. It was a fault in the demo rather than in the code, which is exactly
what makes it worth keeping: it is the shape a real §36 breach would have, and
the log was perfectly happy.

So `privacy_violation` is derived on read and counted in `summary()`, from two
facts the row already held. §41 names it `PRIVACY_MISROUTING`; nothing in this
lineage was going to notice it until TQ-66, and it cost three lines here.

**Detection, never refusal.** Enforcement is TQ-60's. Once that exists, a
violation can only reach this table through a bug or a bypass — and a log that
refused to record those would hide precisely what it exists to reveal. A
non-zero count is a defect, and `summary()` says so in those words rather than
reporting it as a statistic.

### What is deliberately unanswerable

`was_escalation_worthwhile` is the field this whole lineage exists to be able to
answer, and **nothing can answer it today**. It needs a counterfactual — what
would have happened had the work stayed local — and the first thing that produces
one is TQ-63's challenger mode.

It is three-valued and defaults to `unknown`. A boolean defaulting to false would
have quietly asserted that every escalation was wasted, which is a claim nobody
has measured.

### A judgement that differs from §105's, on purpose

`estimated_cost`, `actual_cost` and `resource_usage` are nullable columns nothing
fills yet. §105 left always-NULL *score* columns out entirely, and the difference
is real rather than a lapse: a score participates in arithmetic that changes shape
when a dimension arrives, whereas a log field is inert. And a log is the one
artifact that must not need migrating later — migrating a log means rewriting
history.

`test_resource_usage_round_trips_when_something_supplies_it` proves the column
works the day TQ-57 has something to put in it.

### Verified by running it, and by attacking it

**Run:** §25's portfolio-analysis example, five steps under one `task_id` —
parse deterministically, calculate deterministically, interpret locally, resolve
the hard part externally, summarize locally. All three execution paths in one
task, the leaderboard picking up both model steps, and the privacy violation
above surfacing from it.

**Attack:** eight mutations, eight caught — a decision closable twice; the log
no longer scoring the leaderboard; a privacy violation no longer flagged; the
category column allowed to disagree with its signature; a deterministic path
naming a model; a decision with no reason; escalation-worth defaulting to `no`;
and a stored execution path no longer validated on read.

Suite: **2403 passing, 1 skipped** (2371 before, +32).

---

## §107 — The interface local intelligence will arrive behind (2026-08-26, TQ-56)

Fifth increment of the addendum 45 lineage. `app/local_ai.py` and its conformance
suite: §4's ten-method interface, the canonical request and result objects, and
one honest implementation for a machine with no local runtime — which is every
machine this project runs on.

No model, no runtime, no download. Suite **2434 passing, 1 skipped**.

### The suite comes before the second implementation

§101 established why and this repeats it deliberately: **a contract with a single
implementation is a description of that implementation.** The guard applied to
every test, carried over verbatim:

> Could a service that must load a multi-gigabyte model off disk satisfy this?
> If it needs an in-process stub, the test is wrong.

Two implementations run against it. `NoLocalModelsService` ships and honestly
cannot do anything; `_FakeLocalService` lives in the suite and can. Two that
*genuinely differ* is the minimum at which a contract is a contract — with only
the null one, every refusal test would pass vacuously, which is the trap §101
found by attacking its own suite.

`NoLocalModelsService` is not a placeholder. It is the accurate description of
the current situation, which means the interface is exercised today and TQ-57's
arrival is *adding* an implementation rather than replacing a stub nobody ran.

### `infer()` refuses, and names the increment that fixes it

§4 declares both `infer(request)` — you pick the model — and
`infer_with_model(model_id, request)`.

The first cannot be honestly implemented. Picking needs the leaderboard *and*
privacy, hardware load, availability and budget (§18, §35, §36), which is TQ-60's
entire entry; §16 is equally clear the *agent* must not pick either. So `infer`
is declared and refuses with a sentence naming TQ-60, and the contract asserts
that every implementation does — a service that quietly picked the only model
installed and called that routing is precisely the drift this catches.

### A cold load is not slow thinking

`InferenceResult` splits `latency_ms` from `load_ms`, and this comes from a
finding recorded in §102 **before any of this existed**: 8 GB of VRAM means a
leader and challenger cannot both be resident, so §15's comparisons are
sequential and models get loaded mid-run.

Left unseparated, a ranking learns about SSD speed and files it as reasoning
quality. So the type refuses to let a cold load go unreported —
`loaded_from_cold=True` with no `load_ms` raises — and `wall_ms` is available for
what a user actually waited, distinct from what a leaderboard should score.

That a finding from three increments ago became a constraint in a dataclass is
the point of writing findings down.

### An unrunnable benchmark is not a failed one

`benchmark()` on a service with no runtime returns `passed=None`, not `False`.

§38's distinction, and the one a leaderboard cannot recover from if it is got
wrong: a model that could not be run has not *failed* a benchmark, it has not
*taken* one. Recording it as a failure would penalise a model for this machine's
missing runtime.

### The tripwire is planted before the thing it guards

§4 and §47: *"Agents must not call Llama, Inkling, DeepSeek, or any other local
model directly."* `test_no_module_reaches_a_local_runtime_directly` parses every
module under `agents/`, `backend/`, `app/` and `gateway/` and fails on an import
of any name in `KNOWN_LOCAL_RUNTIMES` outside `app/local_ai.py`.

Written while none of those packages is installed, the way §64's routing pin was
written before there was a second model — so the day TQ-57 installs a runtime it
lands in one place or fails the suite. A rule written after the first leak is a
rule that gets discovered to have been broken for a month.

### A source scanner was too crude, for the third time

`test_this_module_ranks_nothing_and_names_no_leaderboard` failed on its first
run — it caught the word "leaderboard" inside `NO_ROUTING`, the *refusal message*
whose whole job is to explain which increment supplies routing. The module was
right and the scanner was wrong.

That is now three occurrences, each the same shape:

| | what the scanner did | what it caught |
|---|---|---|
| §101 | walked a fixed list of method names | nothing — a *newly added* method slipped past, which was the case it existed for |
| §104 | split the source on triple quotes | "ranked" inside a docstring quoting §36 |
| §107 | stripped docstrings but not other literals | "leaderboard" inside a refusal message |

So rather than patch it a third time, `conftest.executable_source()` is now the
one implementation of *"read only the code"* — it strips **every** string
constant, leaving identifiers, calls and attributes, which is what these
tripwires actually mean to check. All four existing scanners were switched to it.

Prose that mentions a forbidden concept is not a module doing it, and it took
three failures to state that once.

### Verified by running it, and by attacking it

**Run:** the null service, read aloud. `available()` is False; health reports
`healthy=False` *with a reason* rather than raising; `can_run_now` is False with
VRAM figures `None` rather than zero; `infer()` refuses naming TQ-60;
`infer_with_model()` refuses naming TQ-57 and adds the consequence — *"a task
pinned LOCAL_ONLY cannot run at all"*; and `benchmark()` returns
`passed=None, "Not run … Not a failure - an absence of a result."`

**Attack:** ten mutations, ten caught — `infer()` quietly picking a model; an
unrunnable benchmark scored as a failure; an unknown model substituted; health
with no reason; a cold load unreported; a comparison of one model; and a ranking
identifier introduced into each of the three modules whose scanners had just been
refactored, plus an `import ollama` in an agent. The last four exist because
switching four scanners to a shared helper is exactly the change that could have
quietly disarmed them.

### Deliberately not built

No runtime, no model, no download, no `requirements.txt` entry. TQ-57 owns all of
it, and TQ-52 — still blocked on what "Inkling" is — owns deciding which models.
`estimate_latency` returns `None` for every model, because nobody has measured
one, and `None` says that rather than claiming instant.

---

## §108 — Can this be done without a model, and if not, is local enough (2026-08-26, TQ-59)

Sixth increment of the addendum 45 lineage. `app/capability.py`: §3's *first*
decision — the deterministic check (§19) and the capability/escalation decision
(§16, §17) — kept separate from §3's second, which is TQ-60's.

Nothing here names a model, reads a leaderboard or ranks anything, and a source
scan asserts it. Suite **2462 passing, 1 skipped**.

### §19 written down rather than newly imposed

`DETERMINISTIC_CAPABILITIES` declares what this system already does without a
model. Every entry describes code that exists and is *already* preferred over
asking one:

| operation | code | why deterministic is right |
|---|---|---|
| `portfolio_concentration` | `gateway/holdings.py::concentration` | arithmetic over numbers the client supplied — §96's "a model asked to percentage-weight a portfolio produces something *shaped* like arithmetic" |
| `iv_surface_detection` | `agents/explorer.py` | a threshold comparison on measured data; already §19 in practice — the detector produces the candidate, a model only gates it afterward |
| `arbitrage_detection` | `backend/arbitrage.py` | parity relationships are identities, not opinions |
| `agent_slot_allocation` | `backend/fi_db.py::allocate_slot` | two callers must reach the same answer or the population forks |

That is the useful discovery of the increment: **this project was already doing
§19**, in four places, without a name for it. The registry is a record of a
practice rather than a new constraint, which is why it could be written honestly
at all — a registry of aspirations would have been four claims nobody had tested.

`test_every_declared_capability_points_at_code_that_exists` applies
`model_registry.yaml`'s discipline: a registry that drifts is worse than none,
because a router would believe it.

**An unregistered operation is `unknown`, never "needs a model".** §19 asks a
question a person answers at design time; this records the answers given, and
silence means nobody has asked. Treating silence as "use AI" would be precisely
the reflex §19 exists to interrupt.

### The case that is live, and where helpful and correct disagree

A `LOCAL_ONLY` task that needs intelligence, on a machine with no local model,
**cannot be done**. Not escalated — refused.

`local_ai.available()` is False today, so this is not hypothetical: it is what
the system currently answers for any sensitive work needing a model.

The tempting alternative is obvious and wrong. Falling back to an external
provider would be *helpful* and would break the one rule §36 states without
qualification. Sensitive data does not leave because the external model ranks
higher, and it does not leave because the local one is missing either.

So `PATH_REFUSED` exists as a fourth answer that is deliberately **not** an
execution path — `test_this_module_makes_privacy_misrouting_impossible` asserts
it is absent from `routing_decisions.EXECUTION_PATHS`, because there is nothing
to log when nothing ran.

That closes §106's finding from the other end. TQ-55 could only *detect* a
`LOCAL_ONLY` task that had already gone external; routed through this module,
that decision is never made.

### Constraints and heuristics are marked apart

`forced=True` distinguishes a decision privacy required from one a heuristic
chose. It matters because §17 gives this decision its own leaderboard: a model
later judged against these outcomes must not be scored for "getting right" a
call that privacy made for it, and the escalation rate is not evidence about
capability when a constraint produced it.

The same instinct produces the availability wording. "No local model is
installed" is reported as *an availability fact, not a judgement about what local
intelligence could have handled* — because it changes the day TQ-57 lands, and a
ranking gathered under it would otherwise read as evidence that local
intelligence was insufficient.

### The rules are the seed, and say so

§17: *"'Can this be done locally, or should we escalate?' is itself an
intelligent task"*, with the leaderboard §105 already seeded.

So the heuristics here are provisional in §12's sense — a hand-authored starting
point evidence should overtake. Each clause returns a *sentence* rather than a
boolean, because §17's leaderboard only works if a decision can later be judged
wrong, and one that cannot explain itself cannot be. `RULE_VERSION` exists so a
routing record can say which ruleset produced a decision, and evidence gathered
under one set is not silently compared against another.

The privacy rule is not provisional. It is a constraint, and no evidence
overturns it.

### Ordering, and why deterministic-before-privacy is safe

The deterministic check runs first, unconditionally — before privacy, before
availability. That is only safe because **a deterministic solution is this
system's own code on this machine**: it sends nothing anywhere, so it cannot
violate `LOCAL_ONLY`.

Asserted rather than assumed
(`test_a_deterministic_solution_is_privacy_safe_by_construction`), because the
ordering would be a hole the day somebody registered a "deterministic" capability
that made an external call.

### Verified by running it, and by attacking it

**Run:** six cases read aloud — a registered deterministic operation; `LOCAL_ONLY`
with and without a local model; ordinary work with and without; and `HIGH_STAKES`
work. Each returned the expected path with its reasoning, and `summary()` states
plainly that with no local model any `LOCAL_ONLY` task needing intelligence
cannot be done.

**Attack:** nine mutations, nine caught — including both privacy ones (a
`LOCAL_ONLY` task escalating instead of being refused, and the heuristics being
allowed to override privacy), the deterministic check no longer running first, a
capability registered against code that does not exist, and the module acquiring
a leaderboard opinion.

### Deliberately not built

No model makes this decision yet, though §17 says one eventually should. That
needs a local model to compare against the rules, which is TQ-57's, and a
challenger harness, which is TQ-61's. Building a model-driven escalation decision
now would mean asking the *external* model whether the external model is
necessary — a question it is in no position to answer neutrally.

---

## §109 — Owner direction: the Gateway authenticates, the backend authorizes (2026-08-26)

Owner clarification, 2026-08-26, given while deciding TQ-46's §11 Q1:

> *"Gateway is for establishing identity — Gateway only does authentication. Back
> end does authorization and all business logic."*

Recorded here rather than only in the spec it was asked about, because it settles
a boundary question wider than TQ-46 and it reverses a decision that spec had
already made.

### It confirms what was written, and names what drifted

The direction is not new. Three places already said it:

- **Addendum 16 §7** — the Gateway is the only externally exposed service, and
  external clients must not reach internal APIs, Controller, agents *or
  databases*.
- **`gateway/main.py`'s own docstring** — *"It is a client of Jarvis, not part of
  it: the same shape as `agents/coo.py`, `panel/app.py` and `monitor/app.py`, all
  of which are separate processes talking HTTP to the backend."*
- **Addendum 40 §14** — *"The presentation layer must never bypass backend
  authorization just because information exists on the server."*

`gateway/jarvis.py` follows it exactly: a read-only HTTP client against the
backend's `/admin` surface, with the read-only property enforced in the one
method that reaches the network.

**What drifted is data ownership.** `gateway.db` holds nine tables:

| table | what it is | where it belongs |
|---|---|---|
| `sessions`, `clients` | authentication | **Gateway — correct** |
| `client_agents`, `conversations`, `messages` | business logic | backend |
| `scoreboard_items`, `scoreboard_notes` | business logic | backend |
| `portfolios`, `portfolio_holdings` | business logic *and its authorization* | backend |

Two of nine are where the direction puts them. The Gateway became the system of
record for client financial data, which is the part that is not a presentation
concern under any reading.

**Route-level capability gating stays at the Gateway and is not the drift.**
Addendum 17 §66–§80 reserves capabilities for the Super User interface and §14
calls it a high-security boundary; §92 built that deliberately. A door that
refuses is not a door doing business logic. The issue is narrower: when the data
is *also* at the Gateway there is no backend authorization to defer to, so the
Gateway's check is the only one — which is the arrangement addendum 40 §14 warns
about, arrived at from the other direction.

### What this reverses

TQ-46's spec had decided (§4.1) that the Superuser portfolio lives in
`gateway.db` "with every other portfolio", reasoning from one-table-one-guard.
That reasoning was sound and its premise was wrong: it took the current location
of the portfolio subsystem as given.

Under this direction the premise fails. The portfolio subsystem — `portfolios`,
`portfolio_holdings`, the ownership guard, the providers — is business logic and
authorization, and belongs backend-side. **§4.1 is withdrawn.**

Which also settles TQ-46's Q1, and cheaply. The owner chose **reading B** — keep
the capability, remove the ownerlessness — and the spec called that the expensive
option because the backend "cannot reach `gateway.db` by design". Under the
correct architecture that sentence describes the problem rather than the
constraint: the backend cannot reach `gateway.db` because the data should never
have been there. B is not expensive; it is the shape the system was specified to
have.

### The consequence, stated before anybody builds on it

TQ-46 cannot sensibly be built where the portfolio subsystem currently sits.
Building a `SUPERUSER` domain into `gateway.db` and moving it a week later is the
same mistake TQ-44 refused to make with the entity and its guard — work done in a
place it is known not to belong.

So **TQ-69** is queued ahead of it: move the portfolio subsystem backend-side,
with the Gateway reaching it over HTTP the way `jarvis.py` already reaches
`/admin`. TQ-46 depends on it.

That is a large increment touching five merged records (§96, §99, §100, §101,
§106), and it is worth being plain about the cost: none of that work is wasted —
the ownership guard, the canonical holding shape, the provider contract and the
decision log are all correct and all portable. What moves is where they live and
who authorizes the call.

### What is not queued from this

**Conversations, messages, client agents and the scoreboard are not moved here.**
They are the same category of drift and the same argument applies, but nothing in
the current queue needs them moved, and moving four subsystems at once because
one needed it is how a boundary correction becomes a rewrite. They are recorded
as known drift (§6 of the handoff) and get their own entries when something needs
them.

**No exposure changes.** §50's preconditions stand. This is about which process
owns which table, not about what is reachable from outside.
