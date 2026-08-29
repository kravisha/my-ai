# Architecture Readiness Review

**Subject:** four supplied specifications of 2026-08-29 — Knowledge Store, Software
Engineering Healing & Recovery, Multiprocessing & Process Isolation, and
Miscellaneous Architecture / Alpha Readiness / Persistence — reviewed as a set
and against the system that exists.

**Status:** review only. No specification has been edited. No production code has
been written. The four documents remain unassimilated in `~/Downloads` and carry
no addendum number.

> **ANSWERED, 2026-08-29 — read [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) §153 with this.**
> The owner's *Software Department and Self-Evolution Implementation Directive*
> resolves **C1** (an approval spectrum, not one of the three options offered),
> **B8** (simulation knowledge does reach the live store), **C4**, and **X9**.
> **C2** and **C3** were closed in §153 rather than returned. Two contradictions
> survive and still need a decision: **T1** — the deploy mechanism must exist
> before the policy that would use it — and **T2** — directive §2 forbids the data
> repair that doc 02's H1/H2 are built on. The **NO-GO** in §12 stands until those
> two are answered; **Phase 1 is now explicitly authorized** and underway.

**Method:** the specifications were read in full, then every claim they make
about the existing system was checked against the source rather than against
`JARVIS.md`. Where this review contradicts `JARVIS.md`, the source was read and
the file reference is given.

---

## 1. Executive Summary

The four specifications are individually coherent and collectively describe a
credible destination. **They are not implementable as written**, and the reason
is not that any one of them is incomplete.

Three findings dominate everything else.

**First, the healing specification requires the one capability the architecture
was deliberately built to prevent.** Document 02 §14 ends its code-repair flow at
`CONTROLLED RELEASE`, and §20 sets the target state *"JARVIS REPAIRS JARVIS"*
with routine repair no longer requiring Claude Code. Document 04 §6 and §7 make
that a formal gate and cutover. But nothing in the running system may write to
the repository, and that is enforced rather than merely intended:
`tests/test_release.py:498` fails the suite if `backend/release.py` so much as
imports `subprocess`, `os`, `shutil`, `signal`, `socket` or `multiprocessing`;
`tests/test_living_documentation.py:149` fails it if any component writes into
`docs/`; and `backend/version.py` can *ask* git which commit is running but has
no path to choose one. These are prevention-by-absence, the same argument that
keeps the Constitution out of every table. **The new specifications ask for the
capability those tripwires exist to deny.** This cannot be resolved by
implementation. It is an owner decision about what mediates a code change.

**Second, the multiprocessing specification is aimed at a system that no longer
exists.** Document 03 §5 sequences multiprocessing as step 7 of 10, a *"late
Alpha"* conversion, and its Assumptions section correctly says topology must be
verified from the codebase. Verified: Jarvis is **already multiprocess**. Agents
are OS subprocesses launched at `backend/controller.py:524`, coordinated through
SQLite in WAL mode with `busy_timeout`, atomic guarded-UPDATE claims, and claim
expiry (`backend/db.py:47`, `backend/fi_db.py:4348`). The conversion §5 schedules
happened long ago. What has never happened is §21 — the acceptance audit. Read
literally, document 03 defers to late Alpha the only work it actually still asks
for.

**Third, the Knowledge Store specification contradicts the knowledge store that
exists**, and the contradiction has no silent migration. `fi_db.record_knowledge`
(`backend/fi_db.py:3562`) writes every record at `status='active'` —
authoritative on arrival. Document 01 §3.3 says agent statements are *not*
automatically authoritative and §3.8 requires ingestion and judgment to be
separate processes. Document 01 §18 then forbids any migration that *"silently
convert[s] raw data into validated knowledge."* So mapping the existing rows to
`VALIDATED` is precisely the forbidden migration, and mapping them to `CANDIDATE`
retroactively withdraws the records that `agents/analysis.py:204` reads before
every judgment. Neither direction is available without the owner.

Beneath those, this review found **8 blocking issues, 11 non-blocking issues, 8
contradictions or ambiguities, 10 missing shared services, and 4 recommended
specification changes.** The foundations are better than the specifications
assume — the database abstraction, the claim protocol, the migration *engine*,
agent identity and the isolation rule are all genuinely process-ready. The gaps
are in coverage, not in design: the migration engine governs 2 of ~66 stores,
three of six work channels have no claim expiry, and there is no message envelope
at all.

**Verdict: NO-GO** on implementing the four specifications as written.
**Conditional GO** on a decision-independent foundations phase (§9, Phase 1) that
can begin immediately and makes every later phase cheaper. Five owner decisions
(§9, Phase 0) gate the rest.

---

## 2. Architecture Readiness Assessment

Assessed against the nine capabilities named in the request. *Ready* means the
contract exists and is exercised; *partial* means the mechanism exists and does
not cover the ground the specifications assume; *not ready* means the
specification's precondition is absent.

| Capability | State | Evidence |
|---|---|---|
| **Agent persistence** | **Partial** | `backend/agent_identity.py` gives every agent an immutable `agent_id`, a name never reissued, and a personnel record joined to it (TQ-97/TQ-99). Identity survives restart. **Experience, training history and performance history do not exist** — doc 04 §8 lists them as persistence content and nothing carries them. Only the COO has continuity in practice. |
| **Restart and recovery** | **Not ready** | The mechanisms are real but uneven. `discovery_reports` has claim expiry at 180s; `coo_directives`, `engineering_work` and `software_issues` have none, so an agent that dies holding one strands it permanently. Worse, the reclaim for the one channel that has it runs *inside the agent type it recovers* (`agents/analysis.py:517`). No test in 164 test files is named for restart, crash, or recovery. |
| **Knowledge storage and retrieval** | **Partial** | `knowledge_records` exists with provenance, confidence, supersession and non-deletion — roughly 8 of the ~24 fields doc 01 §4 requires. No validation state, no relationships, no keyword dictionary, no entry points, no retrieval contract. Three writers, one real in-agent reader. |
| **Inter-agent queries and communication** | **Partial** | Two query mechanisms already exist and neither is named in the specifications: the **UQI** (`uqi_requests`, identity-addressed, live-answered, 60s) and **cross-check** (`cross_check_requests`, role-addressed, carrying the asker's independent finding first). Both are good designs. Neither has a correlation ID, a schema version on the message, or an idempotency key — all required by doc 03 §11. |
| **Software-engineering-agent operation** | **Not ready** | Five gates on a ten-step workflow exist (`backend/software_department.py`); the DBA opens issues; QA files a verification view. **Steps 5–7 — correct, test, verify — are unimplemented and unimplementable**: `JARVIS.md` §4 states it plainly, TQ-83 established the engineer writes no code, and §1 above explains why it cannot. |
| **Testing and rollback** | **Partial** | Governed-data release and rollback are built and exercised live (`backend/release.py`, the `release_and_rollback` scenario). **Code rollback does not exist and is not this organization's to perform.** No sandbox (`JARVIS.md` §10: `TO BE DEVELOPED`), which doc 02 §13 and §14 both require. |
| **Alpha testing** | **Not ready** | `lifecycle_stage` is a string in `boot_config.json` validated against a tuple (`backend/boot_config.py:68`). Nothing computes readiness; promotion is a text edit. Doc 04 §3 requires an evidence-backed declaration that *"must not be a vague confidence statement."* Separately, `backend/migrations.py:97` permits the destructive `reset` in `ALPHA`. |
| **Eventual multiprocessing** | **Ready — and already in production use** | See §1. WAL, `busy_timeout=5000`, atomic claims, no cross-process object references, authoritative state in the database, liveness on its own clock. The contracts are process-ready because they already cross processes. |
| **Future scaling without replacement** | **Partial** | The logical boundaries scale. The **storage engine does not**: SQLite admits one writer, and `Database.__init__` sets a 5-second ceiling on waiting for it. Adequate at eight agents; Providence's ~15 personal agents plus a newsroom is a different write profile. |

**Aggregate:** the architecture is *better prepared for multiprocessing than the
specifications assume* and *less prepared for recovery, knowledge and readiness
than they assume.* The specifications' risk model points at the wrong half of the
system.

---

## 3. Blocking Issues

Ordered by what they block. Each names the specification clause, the code, and
what must be decided or built before implementation can start.

### B1 — The self-repair mandate collides with prevention-by-absence

**Specs:** 02 §14, §17, §20; 04 §6, §7, §21.
**Code:** `tests/test_release.py:498`, `tests/test_living_documentation.py:149`,
`backend/version.py:37`.

Doc 02 §14's code-repair flow requires the department to author a fix, sandbox
it, test it, review it, release it and roll it back. Doc 04 §7 makes the
department *"the normal implementation authority for Jarvis software changes."*
The architecture forbids every step from `SANDBOX` onward, by tripwires that fail
the suite — not by omission.

This is not a bug in either side. The tripwires were bought with the reasoning at
§139 §3: *code is not this organization's to deploy.* The specifications now say
it must be. **One of the two has to give, and which one is the owner's call.**

*Cannot be resolved in code.* See §7, change **C1**, for the three options and
their trade-offs.

### B2 — Knowledge validation has no legal migration

**Specs:** 01 §3.3, §3.8, §5, §18, §19.
**Code:** `backend/fi_db.py:3562`, `agents/analysis.py:204`.

`record_knowledge` writes `status = KNOWLEDGE_ACTIVE` unconditionally. There are
three writers — Analysis, COO, and the compliance check — and no validating
authority anywhere in the system. Doc 01 requires a seven-state lifecycle in
which `VALIDATED` is reached only by a judgment separate from the ingestion.

The existing `active` rows must map somewhere:

- → `VALIDATED` is the migration doc 01 §18 forbids in terms. It would assert an
  organizational judgment that never occurred, about records written by an agent
  concerning its own work.
- → `CANDIDATE` is honest and **withdraws live behaviour**: `open_questions_for`
  feeds Analysis the organization's open questions before every judgment, and
  `knowledge_exists` is the duplicate guard that stops the COO relearning one
  stale lens every second.

There is also no answer to *who validates*. This project applies
producer-is-not-approver four times (approval, grading, health judging, appeal).
A fifth application needs a fifth role, and doc 01 §7 names only *"a designated
organizational function."*

*Owner decision required* before any Knowledge Store code. See **C2**.

### B3 — The migration engine governs 2 of ~66 stores

**Specs:** 01 §18, §19; 03 §12, §15.
**Code:** `backend/migrations.py:266` — the only two `register(Store(...))` calls
in the repository are `workspace` and `coo_identity`.

Sixty-six `CREATE TABLE` definitions exist across `backend/`. Each stamps a
`schema_version` on its rows, which records a version but supplies no
`read_version`, `write_version`, `validate`, `inspect` or migration path. The
engine is well built — sequential steps, a hard failure on a missing rung, one
transaction, backup before, version written by the runner after validation — and
it has never governed a table that changed.

Expanding `knowledge_records` from 14 columns to doc 01 §4's ~24 concepts is the
first real migration this project will ever run. It would run against an
unregistered store. The module's own docstring names the danger exactly: *"a
pipeline whose first production run is also its first run ever, on the day it
matters most."*

*Must be built before the Knowledge Store, not with it.*

### B4 — Three colliding lifecycle vocabularies

**Specs:** 02 §6; 03 §8.
**Code:** `backend/agent_identity.py:128`, `backend/fi_db.py:1894`.

Three vocabularies now describe an agent's condition:

| Source | Values |
|---|---|
| `agent_identity.SPECIFIED_STATES` (addendum 51 §6, closed; three refused) | created, training, active, waiting, paused, evolving, retired, archived |
| `fi_db` lifecycle + process | active, dormant · running, stopped, crashed |
| **Doc 02 §6 (new)** | ACTIVE, DEGRADED, QUARANTINED, TEMPORARILY_DISABLED, RESTARTING, RETIRED |

Doc 02 §6 is internally ambiguous. Its closing lines — *"Retirement is a
lifecycle decision. Temporary disabling is a recovery action"* — argue for two
independent axes. Its list argues for one, because it contains `ACTIVE` and
`RETIRED`, which are already addendum 51 lifecycle values. `DEGRADED`,
`QUARANTINED`, `TEMPORARILY_DISABLED` and `RESTARTING` exist in neither current
vocabulary.

Implemented as one axis, an agent quarantined for repair is no longer `active`
and every query keyed on lifecycle state silently stops seeing it — including the
COO's staffing check, which would then spawn a replacement for an agent that is
being repaired. Implemented as three, the mapping must be written down before the
first healing function.

*Ambiguity must be resolved in the specification.* See **C3**.

### B5 — No message envelope; six uncoordinated channels

**Specs:** 03 §11, §15, §21; 02 §5.2 (H2 rerun).
**Code:** `coo_directives`, `cross_check_requests`, `uqi_requests`,
`portfolio_analysis_requests`, `engineering_work`, `software_issues` — six
tables, six status vocabularies, three timeout constants, no shared contract.

Doc 03 §11 requires one logical contract carrying sender, recipient, message ID,
**correlation ID**, type, payload, **schema version**, timestamp, priority,
provenance, **acknowledgement semantics**, **retry semantics**, error response and
**idempotency key**. Of those fourteen, the existing channels carry sender,
recipient, type, payload, timestamp and a per-row `schema_version` — and that
column records the *table's* version, not the message's, so it cannot serve doc 03
§15's version-boundary rule.

The bolded four are absent everywhere. This blocks doc 02 directly: H2's
`RERUN / REPROCESS / RESTART` and doc 03 §18's *"avoid duplicate side effects"*
are unimplementable without an idempotency key. Building healing first and the
envelope second means every healing operation is rewritten.

### B6 — Three of six work channels strand work on crash

**Specs:** 03 §12, §18; 02 §5.2.
**Code:** `backend/fi_db.py:4367` (180s), `CROSS_CHECK_TIMEOUT_SECONDS` (30s),
`UQI_TIMEOUT_SECONDS` (60s) — and nothing for `coo_directives`,
`engineering_work`, `software_issues`.

Doc 03 §12 requires *"ownership/lease semantics for work"* and *"restart-safe task
state"* as a property of the database's coordination role, not of one queue. An
agent that dies holding a directive or an engineering work item leaves it claimed
forever; nothing sweeps it, and no test would notice.

`release_stale_claims` is the correct pattern, and its docstring reasons the
timeout properly against a measured worst case. It needs to become a service three
more channels use, not a function one of them has.

### B7 — Queue recovery depends on the agent type it recovers

**Specs:** 02 §7 and Scenario C; 03 §10, §18.
**Code:** `agents/analysis.py:517` — the sole caller of `release_stale_claims` is
inside `_analysis_work`.

Abandoned analysis reports return to the queue only because a *running Analysis
agent* sweeps them at the top of its cycle. Doc 02 §7 is the case where a defect
disables **every instance of one agent type**, and Scenario C makes it an
acceptance test. In that exact scenario the sweeper is among the disabled, so the
reports of the agents being repaired are stranded for the duration of the repair —
and remain stranded if the type is not restored.

This is a circular recovery dependency inside the very failure mode doc 02 is
written to handle. Recovery must be driven by something that is not the thing
being recovered — the Controller or the COO, both of which run continuously and
watch each other.

### B8 — Isolation-by-database and knowledge-that-survives are in conflict

**Specs:** 01 §1, §14; 03 §13.
**Standing constraint:** `JARVIS.md` §7 and constraint 9 — *"Isolation is the
database, not a flag"* (§115), enforced because an agent that can read
`simulation/` has one code path that changes between training and production.

Doc 01 §14 calls simulation and historical operation *"major knowledge-generation
environments"* and requires the system to preserve scenario provenance, ground
truth, decisions, outcomes, lessons and failures — while §1 requires knowledge to
survive process restart, deployment and migration. Doc 01 §14 then requires that
synthetic, historical and live evidence *"never be silently mixed"*, with
provenance making the source environment explicit.

Today those two rules do not conflict, only because simulation knowledge is
discarded: the harness isolates by using a different database, so nothing learned
in a run reaches the organizational store at all. Satisfying doc 01 §14 requires
one of:

- **an export path across the database boundary** — knowledge earned in a run is
  promoted into the live store by something outside the agents; or
- **an environment flag on the knowledge record** — which is the flag §115
  forbids, if any agent can read it; or
- **accepting that simulation knowledge does not persist** — which contradicts
  doc 01 §14.

The first is available and the others are not, but it is a new component with its
own authorization question, and it must be decided before the Knowledge Store
schema is fixed. A `source_environment` column added later is a migration; added
now it is a column.

---

## 4. Non-blocking Issues

Real, worth fixing, and none of them stops implementation from starting.

**N1 — Doc 03's activation sequence describes completed work.** §5 steps 1–7
schedule a conversion that happened before these documents were written. The
remaining work is §21, presented there as a post-conversion checklist. Left as
written, the audit is deferred behind a conversion that cannot occur. *(Spec
change **C4**.)*

**N2 — SQLite is the scaling ceiling, and it will present as agent flakiness.**
`backend/db.py:47` sets `timeout=5.0` and `busy_timeout=5000`. One writer at a
time. At eight agents this is invisible; at Providence's ~15 personal agents plus
a newsroom plus the software department it becomes contention, and contention
surfaces as `OperationalError: database is locked` inside whichever agent lost —
which reads as that agent being broken. The `Database` abstraction is exactly the
right place to have put this, and a Postgres migration is a new class rather than
a rewrite. It is not yet needed. **It should be measured before it is needed**,
because the failure signature is misleading.

**N3 — Knowledge has three writers and one genuine reader.** Writers: Analysis
(`agents/analysis.py:440`), COO (`agents/coo.py:480`), compliance
(`backend/fi_db.py:4831`). The only in-agent read is `open_questions_for`, scoped
to one `record_kind` and one security. Lessons are read only by an HTTP endpoint
for display. Doc 01 §11 wants retrieval before significant work, by every agent.
`JARVIS.md` §13 already declares this gap.

**N4 — Incident learning is not wired to knowledge.** `software_issues.lesson` is
a TEXT column; nothing converts it into a knowledge record. Doc 01 §13 and doc 02
§18 both close this loop, and the comment at
`backend/software_department.py:353` explicitly defers it to addendum 53 §13's
librarian, which is `TO BE DEVELOPED`.

**N5 — There is no department entity.** `docs/organization.yaml` models roles with
`process:`, `reports_to:` and `watched_by:` — genuinely useful, and asserted
against code. It has no `department`, no `version`, no `persistent_state_location`.
Doc 03 §8 requires an authoritative mapping over all of them.

**N6 — Two incident tables, disjoint vocabularies.** `incidents`
(open/recovered/escalated, agent health) and `software_issues`
(severity/classification, workflow). Doc 02 §11 wants one triage model carrying
severity, **blast radius**, failure type and **recovery class**; neither existing
table has the bolded fields, and it is not obvious they should merge — one is a
health event, the other a work item.

**N7 — No agent-type suppression.** Doc 02 §7 step 2 requires *preventing creation
of additional affected instances*. Today the COO staffs by role from
`BASELINE_POPULATION` (`agents/coo.py:71`) and would immediately respawn to
target. Disabling a type without a suppression the COO honours means fighting the
COO.

**N8 — `saturation_two_judges` has a property that can no longer fail.**
`simulation/scenarios/saturation_two_judges.yaml:34` asserts *"two judgment agents
were staffed"* as `population.registered at_least 7`, with the comment
*"controller, coo, dummy, explorer, speculator and two analysis agents."* The
enumeration predates both the Speaker and the DBA. The floor without any judgment
agent is now seven, so the property passes with zero analysis agents staffed. This
is the §149 shape — a check aimed where the answer is a tautology — in the one
property that exists to observe the thing the scenario is named for. *Re-aim, do
not delete (constraint 5).*

**Observed, not inferred.** The 2026-08-29 verification run registered **9 agents**
in `saturation_two_judges` (`controller, coo, dummy, explorer, speculator,
analysis×2, speaker, dba`) and 8 in every other staffed scenario. The assertion is
`at_least 7`. Both judgment agents could fail to staff and the property would still
pass by one.

**N9 — Doc 04 §4 asks for documentation/implementation alignment that is already
drifting.** `JARVIS.md` §10 states the backend has *42 tables*; there are 66
`CREATE TABLE` definitions across `backend/`. `test_living_documentation.py`
checks the components named, not the counts stated.

**N10 — The four specifications are unnumbered and unclassified.** They are not
addenda 54–57 and have not been assessed against `PUBLIC_PRIVATE_BOUNDARY.md`.
Their content reads as technical *what* and *how* — publishable — but that is a
judgment somebody has to record, not one to assume by committing them.

**N11 — Doc 04 §4's readiness evidence includes items nothing measures.**
*"Software Engineering maturity"* and *"remaining external engineering dependency"*
both appear. `JARVIS.md` §8 already records the trap: the external-dependency
metric answered by the external developer is a self-assessment wearing a
measurement's clothes. Doc 04 §5's five-stage trajectory (HIGH → ZERO) has no
defined observable.

---

## 5. Contradictions and Ambiguities Found

Eight, separated by whether they contradict the built system, contradict each
other, or are unresolved inside one document.

### Contradictions with the built system

**X1 — Self-repair vs prevention-by-absence.** Doc 02 §14/§20 and doc 04 §6/§7
against `test_release.py:498` and `test_living_documentation.py:149`. Full
statement at **B1**. *This is the one that changes the shape of the project.*

**X2 — Immediate authority vs validated knowledge.** Doc 01 §3.3/§3.8 against
`record_knowledge`'s unconditional `active`. Full statement at **B2**.

**X3 — Knowledge that survives vs isolation by database.** Doc 01 §14 against
`JARVIS.md` constraint 9 / §115. Full statement at **B8**.

**X4 — Doc 03's topology assumption against the codebase.** §5's *"late Alpha"*
conversion against `controller.py:524`. The specification's own Assumptions
section anticipated this and instructed verification; the verification says the
sequence is already at step 7. Full statement at **N1**.

### Contradictions between the new specifications

**X5 — Doc 03 defers what doc 02 depends on.** Doc 02 §5.3 (H3) and §7 require
targeted component isolation, disabling one agent type, and restarting a repaired
population — capabilities doc 03 §10 assigns to the multiprocess runtime and doc
03 §5 places at step 7, *after* Alpha. Doc 02 §21 Scenarios C and D are Alpha
acceptance scenarios. **So doc 02 requires during Alpha the containment doc 03
delivers after it.** In practice X4 dissolves this — the runtime already exists —
but if doc 03's sequence is taken literally, doc 02's acceptance scenarios cannot
be run.

**X6 — Doc 01 §15 requires of the Knowledge Store what doc 03 §11 has not yet
supplied.** §15 demands idempotent operations, version checks and no reliance on
in-process state — properties of a message and claim contract that doc 03 §11
specifies and nothing implements. The Knowledge Store is therefore specified to
depend on a service specified in a document whose activation doc 03 §5 defers.
Ordering, not content: resolved by building the envelope first (§8).

### Ambiguities inside a single specification

**X7 — Doc 02 §6's state list is one axis or two.** Full statement at **B4**. The
prose argues two, the list presents one.

**X8 — Doc 01 §7's "designated organizational function" is unnamed.** The store
requires validation (§3.3), maintenance, deduplication, stale review, conflict
identification and schema evolution (§7). §7 requires traceability and forbids
silent rewriting, but assigns the function to nobody. Addendum 53 §13's librarian
is the nearest candidate and is `TO BE DEVELOPED`. Until it is named, `VALIDATED`
is a state nothing can produce — which by this project's own rule
(`agent_identity.REACHABLE_STATES`, §49) means it should be *refused* rather than
declared.

**X9 — Doc 04 §6 does not say who assesses the gate.** The Engineering
Self-Reliance Gate lists sixteen capabilities the department must demonstrate. If
the department demonstrates them to itself, that is the §119 self-assessment trap
doc 04 §5 otherwise avoids. If the Creator assesses, doc 04 §3's *"evidence-based
statement"* needs the evidence collected by something that is not the subject.

---

## 6. Missing Interfaces and Shared Services

Ten. Ordered so that each depends only on those above it.

| # | Service | Required by | State today |
|---|---|---|---|
| **S1** | **Message envelope** — sender, recipient, message id, correlation id, type, payload, message schema version, timestamp, priority, provenance, ack, retry, error, idempotency key | 03 §11, §15; 02 §5.2 | Absent. Six channels each carry a subset. |
| **S2** | **Lease service** — claim, renew, expire, sweep; one implementation, every channel | 03 §12, §18; 02 §5.2 | Pattern exists on 3 of 6 channels; no shared service; sweep runs inside a worker (**B7**). |
| **S3** | **Store registration for migration** — `read_version`/`write_version`/`validate`/`inspect`/`migrations` for every table | 01 §18, §19; 03 §15 | Engine complete; 2 of ~66 stores registered. |
| **S4** | **Health/recovery state axis** — degraded, quarantined, temporarily disabled, restarting; independent of lifecycle | 02 §6, §7; 03 §8 | Absent. Two axes exist, neither carries these. |
| **S5** | **Runtime topology map** — identity → type → department → lifecycle → process → health → code version → state location | 03 §8, §21 | Partial: `organization.yaml` has role/process; no department, version or state location (**N5**). |
| **S6** | **Knowledge retrieval contract** — best current answer, evidence, confidence, provenance, contradictions, related, status/version; concise or full history | 01 §17 | Absent. `list_knowledge` returns rows. |
| **S7** | **Keyword dictionary and entry points** — keyword → entry point → relationships → related knowledge → evidence | 01 §8 | Absent entirely. |
| **S8** | **Knowledge validation authority** — the function that promotes CANDIDATE to VALIDATED, and is not the contributor | 01 §3.3, §3.8, §7 | Absent, and unnamed in the specification (**X8**). |
| **S9** | **Repair authorization boundary** — explicit repair operations, auditable change records, review by severity, post-change validation | 02 §13, §15 | Absent. The system has `OwnerContext` for client scope and `_require_superuser` for owner action; a repair API would be a third, unaudited write path into authoritative state. |
| **S10** | **Readiness evidence collector** — gathers doc 04 §4's fifteen items and produces §20's report | 04 §3, §4, §20 | Absent. `lifecycle_stage` is a config string. |

**A note on S9, because it is a security service and reads as a convenience.**
Doc 02 §5.1 (H1) proposes online data repair with *"no unnecessary process
shutdown"* — that is, by design, an authenticated write path that modifies
authoritative state outside the normal domain APIs. Every guarantee in
`JARVIS.md` §9 is stated as a property of the *only* write paths that exist. A
repair path is a second write path, and the tripwires enforcing *"client
portfolios are never stored"* and *"a watchlist entry is a symbol and nothing
else"* are written against modules, not against arbitrary SQL. **A repair
operation that can write any table can write a portfolio into one.** S9 must land
before H1, not with it.

---

## 7. Recommended Specification Changes

Four. Each states what should change, why, what it prevents, and what it costs.
**None has been applied** — the documents in `~/Downloads` are untouched.

### C1 — Doc 02 §14/§20 and doc 04 §6/§7: state what mediates a code change

**What should change.** The self-repair specifications should name the mechanism
by which a code change reaches the repository, and should distinguish *authorship*
from *application*. §20's three lines should become four:

> JARVIS DEVELOPS JARVIS · JARVIS DIAGNOSES JARVIS · JARVIS REPAIRS JARVIS ·
> **and a mechanism outside JARVIS applies what JARVIS authored.**

**Why.** Three options exist and the specifications currently imply the second
without saying so.

| Option | What it means | Cost |
|---|---|---|
| **(a) Keep the tripwires; the department authors, an external applier applies** | The department produces a complete, tested, reviewed patch as governed data. A mechanism the running system cannot invoke applies it. | Doc 04 §5's *"ZERO FOR ROUTINE DEVELOPMENT"* becomes *zero authorship*, not zero involvement. Honest, and a smaller claim than §7 makes. |
| **(b) Relax the tripwires; the department writes to a sandbox clone only** | `release.py` stays clean; a new, separately-tripwired module may write inside a sandbox directory and never the live tree. Promotion out of the sandbox stays external. | A sandbox must exist first (`TO BE DEVELOPED`). Two write paths to audit instead of none. |
| **(c) Remove the tripwires** | The organization deploys its own code. | Discards §139 §3 and the reasoning behind it. An organization that can rewrite the tests constraining it has no constraints — the exact argument §120 makes about the Constitution and a store that ranks. **Not recommended.** |

**What it prevents.** An implementation that quietly picks (c) by deleting a
failing test. The tripwires fail loudly; a specification requiring the capability
they deny will produce a session that reads the failure as an obstacle rather than
as the decision it is.

**Trade-off.** (a) is the smallest change and makes doc 04 §7's cutover a weaker
claim than written. That weakening is the point: it is what is true.

### C2 — Doc 01 §5: name the validating authority, and the migration of existing rows

**What should change.** §5 should state (i) which organizational function
promotes `CANDIDATE` to `VALIDATED`, (ii) that it may not be the contributor, and
(iii) what happens to knowledge written before the lifecycle existed. §18 should
carry an explicit exemption clause for the bootstrap migration, or that migration
is illegal under §18's own words.

**Why.** Without (i), `VALIDATED` is a state nothing can produce, and this project
refuses those rather than declaring them (`agent_identity.py:140`). Without (iii),
**B2** has no legal move.

**What it prevents.** A knowledge store shipping with a validation column that
everything sits in one value of — the *"capability asserted by existing"* failure
addendum 51's three refused states already guard against.

**Trade-off.** Naming the authority means either building a role or assigning
validation to the owner. Owner validation does not scale and is honest; an agent
validator needs the fifth application of producer-is-not-approver, and a peer that
exists.

### C3 — Doc 02 §6: separate the recovery axis from the lifecycle axis

**What should change.** §6's list should be split explicitly:

> **Lifecycle** (addendum 51 §6, unchanged): created · training · active ·
> waiting · paused · evolving · retired · archived
>
> **Recovery condition** (new, orthogonal): normal · degraded · quarantined ·
> temporarily_disabled · restarting

with §6's existing sentence — *"Retirement is a lifecycle decision. Temporary
disabling is a recovery action"* — promoted from a closing remark to the rule
governing the split.

**Why.** §6 already contains the right principle and then contradicts it with a
flat list (**B4**).

**What it prevents.** An agent quarantined for repair silently disappearing from
every query keyed on `lifecycle_state = 'active'` — including the COO's staffing
check, which would then spawn a replacement for an agent being repaired. That is
`JARVIS.md`'s §93 defect (a busy agent declared dead and duplicated) reappearing
through a new door.

**Trade-off.** A third column on the agent record, and every existing query has to
be read to decide which axis it meant.

### C4 — Doc 03 §5: replace the conversion sequence with an audit sequence

**What should change.** §5's steps 1–7 should record that agent multiprocessing is
already in operation, and re-aim the sequence at §21's acceptance criteria as an
audit of the existing runtime. §7's granularity discussion should record the
choice already made — one OS process per agent, database-mediated — as an
observation rather than an open option.

**Why.** §5 currently defers to late Alpha the only work it still asks for
(**N1**, **X4**), and §7 presents as open a decision the code has already taken.

**What it prevents.** A roadmap containing a phase that cannot execute, and — more
expensively — a green Alpha that never ran §21 because §21 was filed under
work-not-yet-reached.

**Trade-off.** None material. The specification becomes shorter and more accurate.
Its Assumptions section already invited this correction.

---

## 8. Dependency Graph

Read top to bottom: nothing may be built before what sits above it.

```
                    ┌───────────────────────────────────┐
                    │   OWNER DECISIONS (Phase 0)       │
                    │   C1 code-change mediation        │
                    │   C2 validation authority         │
                    │   C3 lifecycle axes               │
                    │   B8 simulation-knowledge path    │
                    │   N10 numbering + classification  │
                    └───────┬──────────┬────────────┬───┘
                            │          │            │
        ┌───────────────────┘          │            └──────────────┐
        ▼                              ▼                           ▼
 ┌──────────────┐            ┌──────────────────┐       ┌────────────────────┐
 │ S3 migration │            │ S1 envelope      │       │ S4 recovery-state  │
 │ registration │            │ S2 lease service │       │    axis            │
 │  (B3)        │            │  (B5, B6, B7)    │       │  (B4)              │
 └──────┬───────┘            └────────┬─────────┘       └─────────┬──────────┘
        │                             │                           │
        │      ┌──────────────────────┼───────────────────────────┤
        ▼      ▼                      │                           ▼
 ┌────────────────────┐               │                  ┌────────────────────┐
 │ KNOWLEDGE STORE    │               │                  │ S5 topology map    │
 │  object + states   │               │                  │  (N5)              │
 │  S6 retrieval      │               │                  └─────────┬──────────┘
 │  S7 entry points   │               │                            │
 │  S8 validation     │◄──────────────┘                            │
 └────────┬───────────┘        (agents query knowledge             │
          │                     through the envelope)              │
          │                                                        │
          │            ┌───────────────────────────────────────────┤
          ▼            ▼                                           ▼
 ┌────────────────────────────┐                        ┌──────────────────────┐
 │ N4 incident → knowledge    │                        │ S9 repair authority  │
 │    learning loop           │                        │  boundary            │
 └────────────┬───────────────┘                        └──────────┬───────────┘
              │                                                   │
              └────────────────────┬──────────────────────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │ HEALING  H1 → H2             │
                    │ N6 unified incident triage   │
                    │ N7 agent-type suppression    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────┴───────────────┐
                    ▼                              ▼
        ┌────────────────────────┐     ┌──────────────────────────┐
        │ H3 offline repair      │     │ S10 readiness evidence   │
        │  ! NEEDS SANDBOX       │     │  collector → §20 report  │
        │  ! NEEDS C1 DECISION   │     └──────────┬───────────────┘
        └────────────┬───────────┘                │
                     │                            ▼
                     │                 ┌──────────────────────────┐
                     └────────────────►│ ALPHA READINESS GATE     │
                                       │ computed, not configured │
                                       └──────────┬───────────────┘
                                                  ▼
                                       ┌──────────────────────────┐
                                       │ MULTIPROCESS AUDIT (§21) │
                                       │ then long-duration Alpha │
                                       └──────────────────────────┘
```

**Two cycles to break, both named above.**

- **B7:** queue recovery → Analysis agent → queue recovery. Break by moving the
  sweep to the Controller or COO (S2).
- **X9:** self-reliance gate → assessed by the Software Engineering Department →
  which the gate governs. Break by having S10 collect evidence from the record —
  which tasks came back, which commits, which sessions — rather than by asking the
  subject.

**One ordering that looks optional and is not.** S1/S2 sit *above* the Knowledge
Store because doc 01 §15 requires the store to be safe for multiprocess use with
idempotent operations and version checks (**X6**). Building the store on ad-hoc
channels and adding the envelope afterwards means rewriting every knowledge write.

---

## 9. Phased Implementation Roadmap

Six phases. Phase 1 can start today; everything from Phase 2 waits on Phase 0.

### Phase 0 — Owner decisions *(no code; blocks Phases 2–6)*

1. **C1** — what mediates a code change: (a), (b) or (c).
2. **C2** — who validates knowledge, and what becomes of the existing `active` rows.
3. **C3** — one axis or two for agent condition.
4. **B8** — does simulation-earned knowledge reach the live store, and by what path.
5. **N10** — addendum numbers, and public/private classification for all four documents.

Also worth settling here, because it already blocks Providence: **TQ-100**, which
addendum 53 §7.9 makes a freeze on TQ-101 rather than a recommendation.

### Phase 1 — Foundations *(decision-independent; start now)*

Nothing here depends on a Phase 0 answer, and everything later is cheaper for it.

1. **S3** — register every store with the migration engine. The largest single
   item; mechanical; the engine already exists and is tested.
2. **S2** — extract the lease/claim pattern into one service; apply it to
   `coo_directives`, `engineering_work` and `software_issues` (**B6**).
3. **B7** — move `release_stale_claims` out of `agents/analysis.py` and into the
   Controller or COO cycle.
4. **N8** — re-aim `saturation_two_judges`'s staffing property at something that
   can fail. Re-aim, do not delete.
5. **N2** — measure write contention at 8, 16 and 24 concurrent agents. Record the
   number; do not act on it yet.

### Phase 2 — The envelope *(needs C3 for the state fields)*

**S1** — one message contract, then migrate the six channels onto it one at a time
behind the migration engine built in Phase 1. `uqi_requests` first: it is the
smallest, and its 60-second timeout already implies most of the semantics.

### Phase 3 — Knowledge Store *(needs C2, B8, and Phases 1–2)*

The knowledge object expanded to doc 01 §4; the seven states with `VALIDATED`
reachable only through **S8**; **S6** retrieval contract; **S7** entry points;
relationships (doc 01 §9) held relationally, as §9 permits; **N3** retrieval
before work, one agent role at a time; **N4** the incident→knowledge loop.

Acceptance is doc 01 §20's chain A–I, run as a simulation scenario rather than a
unit test — a restart is in the middle of it.

### Phase 4 — Healing *(needs S4, S9, and Phase 3)*

**S4** recovery axis; **N6** unified triage carrying blast radius and recovery
class; **N7** agent-type suppression the COO honours; then **H1** and **H2** only.
Doc 02 Scenarios A, B, C and E are reachable here. **H3 and Scenario D are not** —
they need a sandbox and the C1 answer.

### Phase 5 — Readiness *(needs Phases 1–4 for the evidence to exist)*

**S10** evidence collector and doc 04 §20's report. The Alpha gate becomes a
computed verdict over evidence, on the precedent this project already set at
§123/§142: **the bar is a constant in code, not a value in the file it governs.**
`lifecycle_stage` stays in `boot_config.json` as a declaration; promotion requires
the computed verdict to agree.

In the same increment, remove `ALPHA` from `migrations.DESTRUCTIVE_STAGES`
(`backend/migrations.py:97`). `reset` destroys persistent identity and the
Knowledge Store, and doc 04 §11 defines Alpha as sustained continuous operation.
The module's own docstring already says an escape hatch that can be pulled in
production is a loaded gun; Alpha is the moment that becomes true.

### Phase 6 — Multiprocess audit *(not conversion — see C4)*

Doc 03 §21's ten criteria run as an audit of the runtime that exists, then doc 03
§20's long-duration test with the fault set it names.

---

## 10. Testing and Validation Strategy

The suite is 2,936 tests across 164 files and is strong on domain logic. It is
close to silent on exactly what these four specifications introduce.

**Measured gap:** no test file is named for restart, recovery, crash, persistence
or concurrency. Two files mention concurrency at all — `tests/test_faults.py:174`,
which asserts that a deliberately locked database raises, and
`tests/test_release.py:498`, the import tripwire. Neither exercises contention.
**Doc 01 §19 makes *"recovery from interrupted writes has been tested"* a minimum
Alpha requirement; it is currently untested.**

Five instruments, in the order they should be built.

**1. A contention harness.** N real processes writing the same tables through the
production `Database` class. Asserts no lost write, no silent duplicate, and that
a lock timeout surfaces as a named condition rather than as an agent error. This
is the only way **N2** gets a number instead of an opinion.

**2. Kill-and-restart per store.** For each store registered by **S3**: write,
kill the process mid-write, restart, assert the invariant. Doc 01 §19's
interrupted-write requirement is this test.

**3. The acceptance chains as scenarios, not unit tests.** Doc 01 §20's A–I and
doc 02 §21's A–E each contain a restart or a process disable in the middle. A unit
test cannot contain one. They belong in `simulation/scenarios/` beside
`slow_agent`, which exists for exactly this reason — *a green run over a condition
that never happened is not evidence about the condition.*

**4. Property re-aiming, continuously.** `simulation/property_history.worklist()`
lists **45 scenario properties never observed failing**. **N8** is a forty-sixth
found in this review, and it is not decay — it was wrong when written. Every new
property from these specifications should be added to that worklist and forced to
fail once before it is trusted. The rule holds: *re-aim, never delete*
(constraint 5).

**5. Tripwires for the new invariants**, in the style the project already uses:

- No module outside the repair service may write authoritative state outside its
  domain API (**S9**).
- No knowledge record may reach `VALIDATED` by the identity that contributed it
  (**S8** — the fifth producer-is-not-approver).
- No queue may exist without a registered lease (**S2**) — an assertion over the
  channel registry, so a channel added later cannot forget.
- No store may exist without a migration registration (**S3**) — the same shape,
  and the one that would have caught **B3**.

The last two matter most: they convert a coverage gap into a suite failure, which
is the only mechanism in this project that has reliably held.

---

## 11. Risks and Mitigations

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **C1 is answered by deleting a tripwire** mid-implementation, because it fails and reads as an obstacle. The organization silently acquires the ability to edit the tests that constrain it. | **Critical** | Answer C1 in Phase 0 and record it in `SPEC_RECONCILIATION.md` before any healing code. Add a tripwire over the tripwires: the suite fails if `test_release.py`'s forbidden-import list shrinks. |
| R2 | **The Knowledge Store schema is fixed before B8 is answered**, and `source_environment` becomes a migration on a store with production rows rather than a column. | High | Phase 0 gates Phase 3. If B8 must slip, add the column now and leave it `unknown` — this project's own rule (§100, §104, §118, §132) makes `unknown` the correct absence value, and it costs nothing. |
| R3 | **SQLite contention appears as agent unreliability** during long-duration Alpha and is diagnosed as an agent defect. Days lost; possibly a correct agent "repaired". | High | Phase 1 item 5 measures it before Alpha. Surface `database is locked` as a distinct, counted, attributed condition — the same argument as §93's liveness/progress split and the misdrafted-instrument refusal counter: *one number cannot tell those apart and two can.* |
| R4 | **H1 online repair becomes an unaudited write path** and silently defeats the portfolio tripwires, which are written against modules rather than against SQL. | High | **S9 lands before H1** (§6). Every repair goes through an explicit, enumerated operation; no general SQL execution; a tripwire asserts the repair module cannot reach a table outside its declared set. |
| R5 | **Doc 03 §5 read literally defers the §21 audit past Alpha**, and Alpha runs on a multiprocess runtime that was never audited. | Medium | **C4**. The audit is Phase 6, and it is an audit, not a conversion. |
| R6 | **The migration engine's first real run is the Knowledge Store expansion**, and it fails on a store with live rows. | Medium | **S3 in Phase 1**, ahead of any schema change. Exercise it with a real no-op registration on a live store first. |
| R7 | **Agent-type failure strands work permanently** because the sweeper is in the disabled type (**B7**), and doc 02's own Scenario C is the trigger. | Medium | Phase 1 item 3. Cheap, and it is the fix for the one circular dependency in the recovery path. |
| R8 | **The self-reliance gate is assessed by its subject** (**X9**), repeating §119's known trap for the external-dependency metric. | Medium | S10 derives evidence from the record — tasks returned, commits, sessions — never from a self-report. Doc 04 §5's five stages need observables before thresholds. |
| R9 | **Specification growth continues** (doc 04 §2 names this) and Phase 1 never finishes because Phase 0 keeps reopening. | Medium | Phase 1 is deliberately decision-independent. It proceeds regardless of how long Phase 0 takes, which is the point of separating them. |
| R10 | **`reset` is available during Alpha** and destroys persistent identity and knowledge in the phase that exists to prove they survive. | Medium | Phase 5, and it is a two-line change. Track it now so it is not remembered on the day it is used. |

---

## 12. Verdict

### NO-GO for implementing the four specifications as written.

Three reasons, and only the first is fatal:

1. **B1 / C1** — doc 02 and doc 04 require code-change capability that the
   architecture forbids by tests bought with defects. No amount of implementation
   resolves it; it is an owner decision, and a session that meets it mid-build
   will meet it as a failing test.
2. **B2 / B8** — the Knowledge Store cannot be migrated legally under doc 01
   §18's own rule, and its schema cannot be fixed until the simulation-knowledge
   path is decided.
3. **B3 / B5 / B6 / B7** — the foundations the specifications assume (migration
   coverage, message envelope, leases, non-circular recovery) are absent or
   partial, and every one is more expensive to add underneath finished Knowledge
   Store and healing code than before it.

### GO for Phase 1, immediately and unconditionally.

Five items, none depending on a Phase 0 answer, all required under every possible
answer: register the stores, extract the lease service, move the sweep out of the
agent it recovers, re-aim the staffing property, and measure contention. This is
roughly five ordinary increments in this project's rhythm, and it makes Phases
2–6 materially cheaper.

### The condition for a full GO

Phase 0's five decisions recorded in `SPEC_RECONCILIATION.md`; C1–C4 applied to
the specifications by their author; the four documents numbered and classified;
Phase 1 green. At that point this review should be re-run against the amended
specifications rather than trusted — it was written before any of them changed.

### One thing worth saying plainly

The specifications are good, and the system is in better structural shape than
they assume. The database abstraction, the claim protocol, the migration engine,
identity, and isolation-by-database were all built correctly for a multiprocess
future that has quietly already arrived. What this review found is not rot. It is
**coverage** — good patterns applied to some of the surface and not the rest — and
**one genuine collision** between where the project is going and a constraint it
deliberately built to stop itself.

That collision is the decision worth making carefully. Everything else is work.

---

*Prepared 2026-08-29 against commit `9e6550c`, branch `tq-78-consolidation`.
Specifications reviewed unedited from `~/Downloads`; none has been assimilated
into `docs/addenda/`.*

*Rendered form of this review, for reading rather than diffing:*
<https://claude.ai/code/artifact/391c1f9d-cd0f-41f1-9a5b-08abaa581032>
*Same content, same date. Updating it from a later session means passing that URL
explicitly — publishing without it creates a second artifact rather than a new
version of this one.*
