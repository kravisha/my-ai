# Specification Reconciliation

**Maintained document — unlike `docs/addenda/*`, this file is meant to be edited.** The addenda are
verbatim, immutable copies of user-provided specifications. This file is the project's own record of
how those specifications were reconciled against each other and against what is actually built.

Every canonical document in this project carries the same Conflict Rule (addendum 5 §2, 6 §8, 7 §10,
10 §11, 11 "Interpretation rule", 12 "About This Consolidation", 13 §17): *do not silently preserve
both models — stop, resolve, and update the canonical specification so one internally consistent rule
remains.* Since the addenda themselves are marked do-not-edit, **this file is where that resolution is
recorded.**

Last updated: 2026-08-17.

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
