# Jarvis — Living Documentation

**The map of this system: what it is, how it is organized, what is built, what is
not, and why the important decisions went the way they did.**

Maintained under [addendum 47](addenda/addendum_47_living_documentation_standard.md),
the Living Documentation Standard. Written for two readers — a person, and an
agent that needs authoritative context without reconstructing the architecture
from source code (47 §9).

**Status of this document: IN DEVELOPMENT.** It is current as of 2026-08-27 and
covers the architecture, the organization, and the state of every major
component. It does not yet cover every module.

---

## 0. How to read this, and what the other documents are

This is the one place that describes the system as a whole. Four other artifacts
exist and none of them replaces this one:

| Artifact | What it is | When you want it |
|---|---|---|
| **This document** | The current truth. What exists, what it does, what state it is in. | Always first. |
| [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) | The change record. Numbered sections, append-only, in the order decisions were made. Every `§` reference in this document points there. | When you need *why*, or what was believed before. |
| [`addenda/`](addenda/) | Provenance. Forty-two supplied specifications, kept unedited. | When you need the owner's exact words. |
| [`TASK_QUEUE.md`](TASK_QUEUE.md) | Detailed work tracking (47 §11). | When you need to know what is queued and in what order. |
| [`JARVIS_GAP_ANALYSIS.md`](JARVIS_GAP_ANALYSIS.md) | Built-versus-Constitution measurement. | When you need the axiom scorecard. |

**Two rules about how these relate.**

The addenda are *not* documentation — they are the source this documentation was
built from. This document may contradict an addendum, but only by naming the `§`
that adjudicated it. A superseded design disappears from this map and stays in
the record.

The record is append-only and stays that way. It is why the conflict at §111 was
findable: §97's reasoning was still sitting there, unedited, four sections later.
A document rewritten in place to state the current truth would have erased the
evidence that a conflict existed at all. That is why this document and that one
are different files (§121).

### Custody: who may write this document

Owner directive, 2026-08-27: *"the living document needs to be safely secured and
not open for tampering by anyone. only one agent should have write access."*

**One writer at a time, declared in machine-readable form** in
[`document_custody.yaml`](document_custody.yaml) and enforced by
`tests/test_living_documentation.py`. Custody today is held by the external
maintainer, which is what addendum 47 §20 specifies for the bootstrap phase; 47
§21 transfers it to the Software Engineering Department when that department
exists, and the transfer is an owner decision recorded in the manifest, not a
change anyone can make by editing a file.

Three layers, and they do not provide the same kind of guarantee:

1. **Nothing in the running system can write it — prevention, by absence.** No
   agent, no route, and no backend module touches `docs/`. Agents write to the
   database; this document is not in the database. A tripwire scans the source
   for any write path into `docs/` and fails the suite if one appears. This is
   the same argument §120 makes about the Constitution: *the safest write path is
   one that does not exist.*
2. **Edits outside the custodian's hand are detectable — tamper-evidence.** The
   manifest records this document's digest, and the suite goes red when the file
   and the digest disagree. An edit made without the custodian's update step
   announces itself.
3. **Cryptographic prevention is not claimed.** In a public repository without
   signed commits, a determined editor can update the digest as easily as the
   text. Signing is the mechanism that would close it and it is an owner action;
   it is queued rather than pretended. **Stating this is part of the security
   guarantee** — a custody notice that implied more than it delivers would be the
   charter-written-falsely problem `backend/charter.py` exists to avoid.

### Status vocabulary

From addendum 47 §10, used at component level only. 47 §17's rule holds
throughout: **an unfinished idea is never written as if it were built.**

`TO BE DEVELOPED` · `IN DESIGN` · `IN DEVELOPMENT` · `IMPLEMENTED` · `TESTING` ·
`SIMULATION` · `HISTORICAL VALIDATION` · `PRE-ALPHA READY` · `ALPHA READY` ·
`BETA READY` · `QA` · `UAT` · `PRODUCTION READY` · `LIVE` · `DEPRECATED` ·
`RETIRED` · `BLOCKED`

Nothing in this system is `LIVE`. Nothing has passed `QA` or `UAT`. The whole
system is in bootstrap development, exercised in simulation.

---

## 1. What Jarvis is

Jarvis is a financial intelligence organization whose employees are software
agents.

That sentence is the architecture, not a metaphor. Addendum 46 §42 states it
directly: *"Jarvis should not be designed primarily as an application containing
many agents. It should be designed as an organization whose employees happen to
be agents."* The application is the infrastructure through which the organization
exists.

**What it does for the people it serves.** A client holds portfolios at several
external brokers. No broker can show them the whole picture, because each sees
only its own account. Jarvis fetches from all of them, reconciles the positions
into one view, and analyses it — concentration today, scenario and risk analysis
later. The portfolios stay the client's property: they are fetched per session
and discarded when the session ends (§111).

**Who it serves.** The owner first, then external clients who pay for the
service. No external client has been onboarded.

**What it is becoming.** Addenda 46 and 47 set the direction: an organization
that observes itself, proposes its own improvements, authorizes them through its
own governance, implements them with its own engineering department, and
eventually maintains itself without the external developer who built it.

### The names, fixed here

47 §5 requires that one concept keep one name. Three had drifted.

| Name | Means | Not to be confused with |
|---|---|---|
| **Jarvis** | The organization. The name used by every recent specification. | *My AI* / *MyAI* — the earlier name, still in the repository name and older addenda. Same system. |
| **The Constitution** | `JARVIS_CONSTITUTION.md`. The owner's document, held privately, never in this repository or any database (§120). | Anything the organization can amend. |
| **The Articles** | The organization's own highest instrument — what a supermajority may amend under addendum 32 §19, and what addendum 46 §4.1 places at the top of the governed store. | The **Charter**, which in this codebase already means [the agent charter](../backend/charter.py): what an agent is owed and which mechanism owes it. |

§120 first proposed *Charter* for the organization's instrument. That was wrong —
`backend/charter.py` has meant the agent charter since before addendum 47 arrived,
and reusing the word would have created exactly the collision 47 §5 forbids. The
correction is recorded at §122. **Neither the Constitution nor the Articles is
built** — see section 3 below.

---

## 2. How the system is put together

Two processes, two databases, one HTTP hop between them.

```
   client / owner
        │
        ▼
  ┌───────────────┐        HTTP        ┌────────────────────────────┐
  │   Gateway     │ ─────────────────► │        Backend             │
  │  port 8100    │                    │       port 8000            │
  │               │                    │                            │
  │ identity only │                    │ authorization + all        │
  │               │                    │ business logic             │
  │  gateway.db   │                    │ financial_intelligence.db  │
  └───────────────┘                    └────────────────────────────┘
                                          │
                                          ├── the COO, and the agents it spawns
                                          ├── the simulated market
                                          └── the studio at /console
```

**The Gateway is the door.** It is the only component intended to face outward.
Owner direction §109 draws the line sharply: *"Gateway is for establishing
identity — Gateway only does authentication. Back end does authorization and all
business logic."* A Gateway that decided anything about permissions would be a
second place where authorization lives, and the two would drift.

**The backend is the organization.** It owns the agents, the knowledge, the
market simulation, the analysis, and every decision about who may see what.

Status: `IMPLEMENTED`, exercised in development and simulation. Neither process
has run against a real external client.

### The application layer

`app/` holds the desktop-facing application: sessions, permissions, audit,
privacy filtering, model routing and the tool surface. It is where the owner's
own interface lives. Status: `IMPLEMENTED`.

---

## 3. Authority: who decides what

This is the part of the system with the largest gap between what is specified and
what exists, so it is written with the gap visible.

### The hierarchy

```
   0.  The Constitution              the owner's. Outside the system entirely.
   ═══════════════════════════════   nothing below may amend anything above
   1.  The Articles                  amendable at supermajority (addendum 32 §19)
   2.  Amendments to the Articles
   3.  Parliamentary laws and resolutions
   4.  Organization-wide policies
   5.  Department policies
   6.  Approved procedures
   7.  Current strategies
   8.  Operational directives
   9.  Project instructions
  10.  Knowledge and reference material
  11.  Historical observations
  12.  Suggestions and unapproved proposals
```

Levels 1–12 are addendum 46 §5. Level 0 and the line beneath it are §120.

**Lower-level material may not silently override higher-level material.** The
word doing the work is *silently*: a conflict is meant to be detected and
escalated, not resolved by whoever read it last.

### Why the Constitution is not stored anywhere

The intuitive design — keep it in the governed store, mark it unwritable — fails
in both available forms:

- At level 0 inside the store, its protection depends on ranking logic staying
  correct forever.
- At level 10, the honest slot for a document the organization did not author, a
  parliamentary law at level 3 **outranks it by construction**. The organization
  could legislate against a constitutional principle without amending anything.

**A store that ranks cannot hold something unrankable.** So constitutional
constraints take the form this project already uses for everything
non-negotiable: a test that fails. No unanimous vote turns a red suite green.
Level 0 is defined by its absence — no table, no protected row, no admin route
(§120).

A proposal that would touch level 0 is refused in one shape — the same refusal
for unconstitutional, out of scope, and cannot-be-determined, so the refusal is
not a probe — and escalated to the owner. That escalation ends outside the
system, and no in-system actor can discharge it.

### What exists today

| Component | Status |
|---|---|
| The Constitution | `IMPLEMENTED` as a private document; **not** represented in the system, deliberately |
| The Articles | `IMPLEMENTED` as machinery — TQ-81. **None are in force.** The genesis text is adopted by the owner, not voted, because a vote needs an electorate and a threshold that only the Articles can supply |
| Parliament: resolutions, the vote, quorum and threshold | `IMPLEMENTED` — TQ-81. [`backend/parliament.py`](../backend/parliament.py) |
| The level-0 refusal and the owner-escalation queue | `IMPLEMENTED` — one refusal for every reason, and no function inside the system closes an escalation |
| Elections, ministers, committees, the weekly session | `TO BE DEVELOPED`, and deliberately not queued (see below) |
| The governed-knowledge layer and precedence rules | `TO BE DEVELOPED` — TQ-82 |
| Strategic Priority Register (proposals, petitions, mandates) | `IMPLEMENTED` — [`backend/register.py`](../backend/register.py), §54 |
| The agent charter — what an agent is owed | `IMPLEMENTED` — [`backend/charter.py`](../backend/charter.py). Every protection names the mechanism that enforces it, and a test resolves every name; three protections are listed as *unenforced* rather than quietly omitted |
| Governance self-measurement | `IMPLEMENTED` — [`backend/governance.py`](../backend/governance.py). Read-only, because a module that measures the governors must not act on them |
| Compliance checking | `IMPLEMENTED` — [`backend/compliance.py`](../backend/compliance.py) |
Addendum 32 specifies elections, ministers and committees; none is required for a
directive to be authorized, so none was built. `parliament.summary()` names them
in the same object that reports the vote, because a status surface showing a
working ballot and nothing else would read as a finished governance layer.

### Two rules that a vote cannot reach

**The rule for changing the rules is not changeable by the rules.** The Articles
carry the electorate, the quorum and the ordinary threshold — as data, which is
addendum 46 §2's whole point. They do **not** carry the threshold for amending
themselves; that is a constant in code. An instrument whose amendment bar is one
of its own clauses can be lowered by simple majority and then walked through.

**What the level-0 refusal cannot do**, stated rather than implied: the system
does not hold the Constitution, so nothing can read it and notice that a proposed
"policy" contradicts it. The refusal covers what a proposal *declares*. A
level-0 change wearing a lower label is not detectable here.

**Until the Articles are adopted, the owner is the Board.** [`TASK_QUEUE.md`](TASK_QUEUE.md)
is the Strategic Priority Register in paper form, worked one item at a time, and
it says so at the top of the file.

---

## 4. The organization: departments, roles, and agents

### Roles that exist and run

Asserted against the code by `tests/test_organization_model.py` — a role named in
[`organization.yaml`](organization.yaml) but not implemented, or implemented and
not named, fails the suite.

| Role | Type | Process | Spawned by COO | What it does |
|---|---|---|---|---|
| **Controller** | infrastructure | the backend server itself | — | Lifecycle: starts, watches, restarts. Never spawned; it *is* the process |
| **COO** (Kumbhakarnan) | executive | subprocess | bootstrapped by Controller | Directs the organization, spawns agents, sets the active lens, records what a stale lens taught |
| **Explorer** | discovery | subprocess | yes | Goes looking. Files reports and detections |
| **Speculator** | discovery | subprocess | yes | Goes looking, differently. Files reports with evidence |
| **Analysis** | judgment | subprocess | yes | Grades what the others produce |
| **Portfolio Analyst** | on-demand | subprocess | **no** — on demand | The only role that works for a *client*. Tasked through the Gateway; produces nothing when nobody has asked |
| **Speaker** | spokesperson | subprocess | yes | Parliament's voice. Reads the state of Parliament and files a report; the console renders *that*, never its own query |
| **Dummy** | reference | subprocess | yes | The reference implementation the lifecycle machinery is tested against |

All `IMPLEMENTED`.

**The Speaker reports; it does not legislate.** It cannot propose, vote, close a
resolution or adopt Articles, and a test asserts the module never reaches those
functions — a spokesperson who can also legislate is not reporting on a body, it
is the body. It answers to the Articles rather than to an officer (`reports_to:
null`), while the COO spawns and watches it: **who starts a process is not who
directs it.**

Its silence is the point. If the Speaker stops, the console shows the age of the
last thing it said and does **not** fall back to querying Parliament — a fallback
would look identical whether the Speaker was working or dead (§124).

**The Portfolio Analyst is the shape everything new should take.** It is not part
of the baseline workforce: it exists when a client asks and not otherwise. Those
two ideas — *the COO can spawn this* and *this is always running* — were one field
until this role needed them separated (§117).

### Persistent agents, temporary agents, and shared knowledge

Addendum 47 §14 requires this distinction to be stated plainly, and until now it
was implied by the code rather than written down.

**Persistent.** The COO is the only agent with a persisted identity today —
Kumbhakarnan, a name and a continuity that survives restart (§88). Addendum 47
That addendum lists what persistence may include: identity, role history, experience,
training history, performance history, important decisions, lessons learned,
responsibilities. Only identity is implemented. Status: `IN DEVELOPMENT`.

**Temporary.** Every other agent is a subprocess spawned for work and released
when the work ends. It keeps nothing across a restart.

**Shared organizational knowledge is separate from both**, and must stay so. What
the organization knows lives in the backend's knowledge tables; what a particular
continuing agent has learned is its own. Collapsing them would mean an agent's
private experience silently becoming organizational fact, or organizational fact
being lost when an agent is released.

**Client data belongs to neither.** It is held for the length of one request and
discarded — see section 5.

### Departments

Specified across the addenda; mostly `TO BE DEVELOPED`. What exists:

| Department | Status | Where |
|---|---|---|
| Department of Education | `IMPLEMENTED` (portfolio-analysis curriculum only) | [`backend/curriculum.py`](../backend/curriculum.py), [`simulation/training.py`](../simulation/training.py) |
| Strategy | `IMPLEMENTED` in part — the register and the strategy store | [`backend/strategy.py`](../backend/strategy.py), [`backend/register.py`](../backend/register.py) |
| Department of Evolution | `TO BE DEVELOPED` | addendum 30 |
| Software Engineering | `TO BE DEVELOPED` — TQ-83 | addendum 46 |
| Governance | `TO BE DEVELOPED` (measurement exists; the department does not) | addendum 32 §20 |
| Security Defense, Business Continuity, Law Enforcement | `TO BE DEVELOPED` | addenda 28, 29 |

---

## 5. The service: consolidated portfolio analysis

This is what the organization sells, and it is the part that most recently
changed shape.

### The rule that governs everything here

**The portfolios do not live in this system.** Owner direction, §111:

> *"The portfolios are the personal property of the clients. The system only
> processes portfolios for clients and does portfolio analysis for clients for
> their external portfolios and holds no information of the portfolios in the
> system."*

The system holds no portfolio table. It never did hold client positions after
TQ-72 removed the storage layer that an earlier reading had built (§116).

### How a request flows

```
  client asks through the Gateway
        │  names sources; supplies credentials for them
        ▼
  backend/analysis_requests.py        the request, held only until claimed
        │
        ▼
  Portfolio Analyst (spawned on demand)
        │
        ├── fetches from each source           backend/portfolio_providers.py
        ├── consolidates into one view         backend/consolidation.py
        └── analyses it                        backend/holdings.py::concentration
        │
        ▼
  report, held only until the client collects it — then deleted
        │
        ▼
  client disconnects → everything for that session is discarded
```

**The database is a transport, not a store.** A request is deleted when claimed,
a report when collected, a session's rows on disconnect, and an expired row is
treated as absent *on read* rather than trusting a sweeper to have run. That is
how an agent architecture built on database queues serves a system that retains
nothing (§117).

### What consolidation actually decides

Addendum 9 §3 says to *"combine duplicate or overlapping exposures where
appropriate."* Most of [`backend/consolidation.py`](../backend/consolidation.py) is
the four places *appropriate* turns out to mean **do not**:

- **A merge is by symbol; a disagreement about the symbol is not a merge.** Two
  sources calling the same security a stock and an ETF are not one position seen
  twice — one is wrong, and the module does not know which. The position merges
  and the class becomes `unknown`, with the disagreement reported.
- **A long at one broker and a short at another do not net to nothing.** Two real
  positions exist, with two cost bases and different tax treatment. The net is
  reported *and the legs are kept*.
- **A consolidated view is as fresh as its oldest source.** `as_of` is the
  minimum, never the newest — two honest timestamps must not make a dishonest
  third.
- **A partial consolidation is not a portfolio.** Failures are carried, not
  dropped.

### Knowing when an answer is incomplete

A source's rows are not evidence that they are all of them. Every provider is
asked how many positions the account *says* it holds, on the account rather than
beside the holdings — because that is where a real broker reports it, and **the
account summary and the positions endpoint disagreeing is the only signal a
silent truncation gives** (§118).

A provider that cannot answer returns `unknown`, never a count of what it
happened to return. Unknown suppresses the completeness claim without inventing a
shortfall.

### Status

| Component | Status |
|---|---|
| Provider interface and conformance suite | `IMPLEMENTED` |
| Manual provider (a source somebody maintains by hand) | `IMPLEMENTED` |
| Simulated provider and simulated exchange | `SIMULATION` |
| Consolidation across sources | `IMPLEMENTED` |
| Concentration analysis | `IMPLEMENTED` |
| Portfolio Analyst agent, end to end | `SIMULATION` — never run against a real broker |
| Credential envelope (encrypted client credentials) | `TO BE DEVELOPED` — TQ-73 |
| Schwab connection | `BLOCKED` — prepared and disabled; needs owner API access |
| Scenario and risk analysis | `TO BE DEVELOPED` — TQ-74 |
| Valuation of any kind | `BLOCKED` on real prices — see section 6 |

**The credential problem is not solved.** A subprocess agent cannot be handed a
secret through a database table without the secret landing on disk. Today the
transport *refuses* any source descriptor carrying a credential key, so it
carries **which source** and never **how to open it**. TQ-73 owns the real answer.

---

## 6. Market data, and what the numbers mean

Owner direction, §113:

> *"Prices come from market data store. Positions come from broker dealers and
> other external sources. Risk, sensitivity, greeks etc are calculated locally
> during portfolio analysis."*

**The market data store holds no real prices.** Measured, not assumed: 20
observations, every one `origin='synthetic'`, produced by `parity_world(seed=4)`,
against a security master whose identifiers are `JE-000001` and not `AAPL`
(§113). The obstacle is mechanical rather than subtle — a real symbol arrives as
a miss, not as a wrong number.

Consequence: **nothing in this system values anything.** `is_priced` marks every
figure that is not market-derived, and a report that cannot price a position says
so rather than substituting. Status of real market data: `TO BE DEVELOPED` —
TQ-75, and it blocks valuation, scenario analysis, and serving a real client.

The simulated market itself (`simulation/parity_world.py`, the pricing and
regime machinery) is `IMPLEMENTED` and is what the organization exercises
against.

---

## 7. Simulation, training, and how the organization learns

### The principle that makes training honest

Training must exercise the production path, and this is **structural rather than
disciplinary** (§115). There is no simulation branch inside the Portfolio Analyst
and nothing there for one to be added to. The simulated exchange registers as an
ordinary provider and is reached the same way any provider is; what differs is
what answers the call, not what makes it.

`simulation/harness.py` states the rule: *"Isolation is the database, not a
flag."*

### The simulated world

| Component | Status | Notes |
|---|---|---|
| Simulated exchange | `IMPLEMENTED` | Behaves as `healthy`, `unreachable`, `slow`, `partial` or `malformed`. **An exchange that never fails is the wrong teacher** |
| Simulated clients | `IMPLEMENTED` | They request, collect, and *judge*, with a closed vocabulary of complaints |
| Ground truth | `IMPLEMENTED` | Deliberately **not** on the provider interface. Ground truth belongs to the grader; an interface that can be asked for it lets the graded party pass by asking |
| Fault injection | `IMPLEMENTED` | `simulation/faults.py` |
| Historical-data operation | `TO BE DEVELOPED` | Addendum 47 §6 and addendum 46 §27 both require it |

### The Department of Education

One curriculum exists: portfolio analysis, six exercises over five competencies.
Each competency declares whether it is *remediation* or *capability-building*,
because addendum 36 §4 says their goals and measurement differ.

Three design rules are worth knowing because they were each bought with a defect:

- **A `KNOWN_GAP` exercise must fail.** If one passes, the report says
  *"curriculum out of date"* rather than congratulating anyone. A gap that closes
  quietly is a gap nobody re-aimed.
- **Results keep codes and rules, never detail.** The detail quotes symbols, and
  a training-results table is the last place anyone would look for retained
  client positions.
- **Absence of complaint is not evidence of competence.** An analyst that simply
  stopped asking sources how much they held made every complaint disappear and
  passed its exercise, having detected nothing. Exercises may now require the
  detection to *appear* in the report (§118).

Current curriculum result: six exercises, all passing, no regressions, no
out-of-date exercises, and the run reports what it left behind — *client analysis
data held: 0 · positions written down: none.*

---

## 8. Evolution, engineering, release and rollback

Everything in this section is `TO BE DEVELOPED`. It is the direction addenda 46
and 47 set, and it is written here so the shape is visible before it is built.

### The architecture: stable machinery, evolving data

Addendum 46 §2: code provides the mechanisms, data provides the current
behaviour. Changing an organizational rule should normally mean changing governed
data, not rewriting software — the way a person reads a new law and complies
without being rebuilt.

The order to try, before writing code (46 §8):

1. **Knowledge** — add or improve what agents know.
2. **Directive or policy** — change behaviour through an approved rule.
3. **Configuration** — thresholds, workflows, permissions, routing.
4. **Capability composition** — combine what exists differently.
5. **Software** — only when the architecture genuinely lacks the mechanism.

**A known way to get this wrong, recorded before it happens:** a department
measured on *"did you avoid a code change?"* will report levels 1–4 for problems
that need level 5, and the metric will improve while the system does not. That is
the same failure as the analyst that stopped asking. The ladder has to require
evidence that the *outcome* was achieved, not evidence that code was avoided
(§119).

### The Software Engineering Department

One general-purpose Software Engineer type occupying roles — project manager,
architect, developer, reviewer, tester, release engineer — rather than a catalog
of specialists. **Work determines staffing, not the reverse.** For significant
change, the agent that produces it is never the sole authority that approves it.

Directives reach it **through Evolution**, not on a parallel channel from
Parliament. Addendum 46 §13 draws *Approved Directive → Software Department
intake* with nothing between, and building that gap is how a bypass appears by
accident (§119).

### Release and rollback

Version N keeps running while N+1 is designed, built and tested. But addendum 30
§13 is explicit that this system *"is not a single monolithic object that must be
serialized and restarted"*, and addendum 30 §14 makes full-system shutdown a last resort. **A
release must not be built as a restart script** (§119): rolling restart, canary,
version coexistence and compatibility adapters are the shape it has to take, and
the COO needs its own handoff because everything else depends on it.

Rollback is a first-class capability, not an improvisation, and **nothing about
rollback erases history**. A rolled-back version stays part of organizational
memory.

### The external dependency

The system is currently built by Claude Code, an external developer. Addendum 46
makes that a measured, shrinking dependency with an exit condition: departure
happens when capability has transferred, not when a date arrives.

**One caution, recorded now:** *"was the external developer required?"* answered
by the external developer is a self-assessment wearing a measurement's clothes.
It has to come from observed facts — which tasks came back, which commits, which
sessions — for the same reason ground truth is kept off the provider interface
(§119).

---

## 9. Security, privacy, and isolation

| Rule | Status | Mechanism |
|---|---|---|
| Client portfolios are never stored | `IMPLEMENTED` | No table exists; an import tripwire fails the suite if a storage module returns |
| One identical refusal for absent, foreign, and archived | `IMPLEMENTED` | A refusal that distinguishes them is a probe for what exists |
| Ownership context is evidence, not a variable | `IMPLEMENTED` | Built from the session subject, never from caller input |
| Closed vocabularies, fail closed on read as well as write | `IMPLEMENTED` | Unknown values are refused, not defaulted |
| Absent is `unknown`, never a plausible default | `IMPLEMENTED` | §100, §104, and enforced again at §118 |
| Nothing leaves the machine that is classified local-only | `IMPLEMENTED` | `app/data_classification.py`, `app/privacy_filter.py` |
| Audit of privileged action | `IMPLEMENTED` | `app/audit.py` |
| Capability gating on tools | `IMPLEMENTED` | `app/capability.py`, `app/permissions.py` |

**The repository is public** (`github.com/kravisha/my-ai`). Five documents are
held privately and named without links wherever they appear — the Constitution
and addenda 5, 11, 15 and 22. A reference you cannot follow means the document is
private, not missing. See [`PUBLIC_PRIVATE_BOUNDARY.md`](PUBLIC_PRIVATE_BOUNDARY.md).

**This is an open question, not a settled one.** Addendum 47 asks for security,
continuity and failure documentation; that is exactly the material that should
not be world-readable. Raised on 2026-08-16 in
[`DOCUMENTATION_RECONCILIATION_PLAN.md`](DOCUMENTATION_RECONCILIATION_PLAN.md)
and never answered. Nothing sensitive has been written yet, so this is a
prospective risk rather than an incident.

---

## 10. Environments and data stores

| | |
|---|---|
| **Backend database** | `financial_intelligence.db` — 42 tables. Agents, knowledge, market data, register, missions, incidents, grades. **No portfolio tables** |
| **Gateway database** | `gateway.db` — identity and sessions. Created on first Gateway run |
| **Model spend** | `model_spend.db` — what has been spent with which model |
| **Boot configuration** | `boot_config.json` and the metadata engine (addenda 21, 39) |
| **Sandbox** | `TO BE DEVELOPED`. Addendum 46 §14 wants an *organizational* experiment environment — cloned state, proposed policies, synthetic workloads, behavioural comparison. What exists (`simulation/`) substitutes at the provider boundary and shares the production code path: the right principle at a much smaller scale |
| **Build vs built environment** | `TO BE DEVELOPED` |

Databases run in WAL mode. Backups live in `backups/`.

---

## 11. Models and routing

| | |
|---|---|
| Configured engines | **One** — an Anthropic model behind `app/model_provider.py` |
| Local models running | **None.** The candidate survey is done: a pool of three fits this machine, recorded in [`local_model_candidates.yaml`](local_model_candidates.yaml). None is installed. Status `BLOCKED` on owner action |
| Competitive routing across eight leaderboards | `TO BE DEVELOPED` — addendum 45, TQ-51 through TQ-68 |
| Routing decision | Pinned to `none_single_model`, deliberately. A tripwire fails the suite the day a second model is registered, so the pin cannot be forgotten |

`AGENT != MODEL` holds structurally: there is exactly one place the vendor is
constructed. [`model_registry.yaml`](model_registry.yaml) records what has been
*measured*; fields nobody has measured carry no numbers.

---

## 12. Where the system actually stands

**Test suite: 2,509 passing, 8 skipped** (2026-08-27). The skips are deliberate
and named.

A green suite is not evidence the system works. Every real defect found in this
project came from starting it and looking at it, which is why increments end with
a live run rather than with a test report.

### What works end to end, in simulation

A client arrives through the Gateway, asks for consolidated analysis of several
external sources, an analyst is spawned, fetches from each, reconciles them,
notices when a source answered incompletely, analyses what it has, returns a
report, and everything is discarded when the client disconnects. The client
judges the result, and the Department of Education records the grade without ever
writing down a position.

### What has never happened

- A real broker connection.
- A real price.
- A real external client.
- A release, or a rollback.
- An agent proposing a change to the organization of its own accord.
- Any Articles in force in the working database — the machinery runs, and the
  organization it would govern has not yet been given its instrument.

A vote *has* happened: TQ-81's live run adopted genesis Articles against a scratch
database, carried an organization-policy resolution, and had a level-0 proposal
refused into an escalation queue nothing inside the system can clear (§123).

### The honest summary

The organization's *operating* machinery is built and exercised. Its *governing*
machinery is specified and absent. Addenda 46 and 47 are about the second, which
is why the next four pieces of work are the Articles and Parliament, the governed
knowledge layer, and the department that will eventually take over engineering.

---

## 13. Known gaps and open questions

Declared gaps are counted and asserted; a newly-unclosed loop fails the suite
until somebody declares it deliberately.

### Declared gaps in the organization model

1. **A producing agent never learns how its own report was judged.** Feedback
   closes at the lens level — the COO reads grades and moves the lens — so the
   organization learns while the individual agent does not.
2. **Lessons written when a lens goes stale are never read back.** They are
   preserved and guarded against duplication, and no consumer exists.

### Gaps in the service

3. **No real prices** (section 6). Blocks valuation and scenario work.
4. **No credential path** (section 5). The transport refuses secrets rather than
   carrying them, which is correct and is not a solution.

### Open questions awaiting an owner decision

5. **Where the living documentation and operational detail should live**, given a
   public repository (section 9).
5a. **What the genesis Articles should say, and who is on the roll.** The
   machinery is built and waiting; the first text is level 0's to write (§120,
   §123). Nothing in the system can vote itself an instrument.
6. **Whether `HANDOFF.md` is retired now or at the next session change.** Owner
   direction on 2026-08-27 was to keep it for later. It is currently *wrong* — it
   describes database tables that TQ-72 deleted — and carries a staleness notice
   until it is rewritten.

### Recorded risks that are not yet defects

7. The data-before-code ladder can be satisfied without achieving the outcome
   (section 8).
8. The external-dependency metric is currently self-reported (section 8).

---

## 14. What this document does not yet cover

Named so that absence is not mistaken for completeness (47 §17):

- The options arbitrage library and its detector families (addendum 27; partly
  built, several detectors blocked on world capabilities).
- The reference data engine and identifier rules.
- The desktop runtime, the live studio, and the briefing choreography
  (addenda 40–43; built).
- Incident response and business continuity (`INCIDENT_RESPONSE.md`).
- The full contents of the backend's 42 tables.

Each is documented elsewhere today and belongs here eventually.

---

*Maintained under addendum 47. When the architecture changes, this document
changes in the same increment — `tests/test_living_documentation.py` fails if the
components it names stop matching the system it describes.*
