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
