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
