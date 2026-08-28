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
| [`addenda/`](addenda/) | Provenance. Forty-six supplied specifications, kept unedited. **Five more are held privately** and named without links (the Constitution — addendum 49 — and addenda 5, 11, 15, 22). | When you need the owner's exact words. |
| [`TASK_QUEUE.md`](TASK_QUEUE.md) | Detailed work tracking (47 §11). | When you need to know what is queued and in what order. |
| [`JARVIS_GAP_ANALYSIS.md`](JARVIS_GAP_ANALYSIS.md) | Built-versus-Constitution measurement. | When you need the axiom scorecard. |
| [`HANDOFF.md`](HANDOFF.md) | Where the last session stopped, and what to do first. Nothing else — it points here rather than repeating this. | Starting a session. |

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

Jarvis is the organization, and its employees are software agents. Since
2026-08-28 it is **the system currently realizing Project Providence**, and
financial intelligence is one of the services it provides rather than the whole
of what it is (§140).

That sentence is the architecture, not a metaphor. Addendum 46 §42 states it
directly: *"Jarvis should not be designed primarily as an application containing
many agents. It should be designed as an organization whose employees happen to
be agents."* The application is the infrastructure through which the organization
exists.

### Providence, and what changed on 2026-08-28

Four documents — addenda 49–52 — re-scope the system. **Providence is the
mission: one person, one personal world**, entered through a device-independent
portal, hosted by a Personal Usher, served by a society of trained personal
agents, and informed by an AI newsroom. The financial intelligence work becomes
the *Personal Portfolio Manager*, one of roughly fifteen personal agents named in
addendum 50 §3.

The Glossary defines *Project Jarvis* as *"the operational studio and interactive
environment through which Providence is currently being built and experienced."*
Read literally, the name of this document would denote the console. §140 §2
adjudicates it: **Providence is the mission and the world; Jarvis is the system
realizing it**, of which the studio is the part a client sees. The alternative
reading — that a third name is needed for the organization — is available and
would cost a rename of everything; if that is what was meant, §140 §2 is where to
say so.

Three things follow that are not yet built and are now the direction:

- **Every agent gets a persistent identity and a career.** Explorer → Speculator
  → Reporter, walked by one agent that keeps what it learned (49 §20, 50 §12).
  The first increment exists — see section 4.
- **Personal agents are bound to a client** and work within that client's
  profile, permissions and preferences (51 §4 and 51 §15).
- **A client-facing conversational agent**, the Usher, which must tell a question
  from thinking aloud before answering (51 §16, and 49 §11 on patience). Nothing like it
  exists here.

**One conflict was resolved by the owner the same day, and it corrected more
than it settled (§141).** Addendum 49 *is* the Constitution — v2.0 of one
document whose v1 was `JARVIS_CONSTITUTION.md` — it **applies to the system with
the owner inside it**, and it is held privately while the Vision, the Technical
Specification and the Glossary stay public. Two things follow:
`JARVIS_GAP_ANALYSIS.md` is **stale**, because the document it scores against
moved; and whether the organization may amend the Constitution is **reopened**,
because §120 answered it from the premise now corrected (§141 §5).

And addendum 51's persistent client profiles meet
§111's rule that client data is not stored; §140 §5 draws the boundary — **a
profile is what the client told the system, a portfolio is what the client owns**
— and a watchlist is stored only as something the client typed, never as
something derived from a fetched portfolio.

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
| **The Constitution** | Addendum 49, *Providence: Philosophy & Constitution* v2.0 — **held privately**, never in this repository (§141 §3). `JARVIS_CONSTITUTION.md` was its v1; one document, not two. Parliament holds its version and its text once the owner seeds it, and the organization amends it at two-thirds (§142). | The **Articles**, which are level 1 and amendable at the same bar. Precedence separates them, not price. |
| **The Scripture** | [Addendum 48](addenda/addendum_48_scripture_of_shared_success.md), *Shared Success*. How agents should be, rather than what the system should do. **Level 0, like the Constitution** — a document defining an authority cannot be amended by those it governs (§131). | The Articles, which the organization amends by vote. |
| **Providence** | The mission and the product: one person, one personal world (addenda 49–52). The thing Jarvis is being built to realize. | *Jarvis*, which is the system, not the mission. |
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
   0.  The Constitution              applies to the whole system, the owner
                                     included. Amendable by the organization
                                     at a two-thirds supermajority (§142).
   ═══════════════════════════════   the amendment BAR is not amendable
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

Levels 1–12 are addendum 46 §5. Level 0 is §120, twice corrected by the owner: the Constitution is **one document** — addendum 49 is its v2.0, held privately — it **applies to the system with the owner inside it** (§141), and **the organization may amend it at a two-thirds supermajority** (§142). §120's *outside the system entirely* and *no vote reaches it* were both wrong.

The line beneath level 0 has moved with it. What no vote may reach is not the Constitution but **the bar for amending it**, which is a constant in code — a threshold written into the document it guards can be lowered once and then walked through (§123).

**Lower-level material may not silently override higher-level material.** The
word doing the work is *silently*: a conflict is meant to be detected and
escalated, not resolved by whoever read it last.

### Why the Constitution is not stored anywhere

**Not because its author is external — the owner is part of the system (§141).**
The reason is the store, and it stands without that premise. The intuitive design
— keep it in the governed store, mark it unwritable — fails in both available
forms:

- At level 0 inside the store, its protection depends on ranking logic staying
  correct forever.
- At level 10, the honest slot for a document the organization did not author, a
  parliamentary law at level 3 **outranks it by construction**. The organization
  could legislate against a constitutional principle without amending anything.

**A store that ranks cannot hold something unrankable**, and **a rule a vote can
reach is not a rule** (§123). Either argument is sufficient on its own. So
constitutional constraints take the form this project already uses for everything
non-negotiable: a test that fails. No unanimous vote turns a red suite green.
Level 0 is defined by its absence — no table, no protected row, no admin route
(§120).

A proposal that would touch level 0 is refused in one shape — the same refusal
for unconstitutional, out of scope, and cannot-be-determined, so the refusal is
not a probe — and escalated to the owner. **That escalation goes to a participant
of this system who holds an identity in it**, not out of the system: the owner
authenticates through `_require_superuser`, and `record_owner_decision` writes
which owner decided into the organization's own table. No *agent* can discharge
it, which is the property that matters and is what §120 meant to say.

### What exists today

| Component | Status |
|---|---|
| The Constitution | `IMPLEMENTED` as a private document (addendum 49). The **machinery** to hold and amend it is `IMPLEMENTED` — genesis by the owner, amendment by the organization at two-thirds, every version kept (§142). **No text is in force**: the genesis text is the owner's to place, and nothing in this repository seeds it |
| The Articles | `IMPLEMENTED` as machinery — TQ-81. **None are in force.** The genesis text is adopted by the owner, not voted, because a vote needs an electorate and a threshold that only the Articles can supply |
| Parliament: resolutions, the vote, quorum and threshold | `IMPLEMENTED` — TQ-81. [`backend/parliament.py`](../backend/parliament.py) |
| The level-0 refusal and the owner-escalation queue | `IMPLEMENTED` — one refusal for every reason, and no function inside the system closes an escalation |
| Elections, ministers, committees, the weekly session | `TO BE DEVELOPED`, and deliberately not queued (see below) |
| The governed-knowledge layer and precedence rules | `IMPLEMENTED` — TQ-82. [`backend/governed_knowledge.py`](../backend/governed_knowledge.py) |
| Agents reading what governs them | `IN DEVELOPMENT` — TQ-86, TQ-87. [`backend/operating_context.py`](../backend/operating_context.py). Explorer, Speculator and the register obey governed data. **Analysis and the COO do not** |
| Strategic Priority Register (proposals, petitions, mandates) | `IMPLEMENTED` — [`backend/register.py`](../backend/register.py), §54 |
| The agent charter — what an agent is owed | `IMPLEMENTED` — [`backend/charter.py`](../backend/charter.py). Every protection names the mechanism that enforces it, and a test resolves every name; **two** are listed as *unenforced* rather than quietly omitted. TQ-102 discharged appeal (§145) and deliberately did **not** discharge *"an agent is told what is found about it"* — the read path exists and nothing reads it, and being told is passive in a way that having a right is not |
| Governance self-measurement | `IMPLEMENTED` — [`backend/governance.py`](../backend/governance.py). Read-only, because a module that measures the governors must not act on them |
| Compliance checking | `IMPLEMENTED` — [`backend/compliance.py`](../backend/compliance.py). `self_evaluated` was **re-aimed at §147**: it compared the grader to the analysis result's producer, which is one identity by construction, so it flagged every grade and could never return false |
Addendum 32 specifies elections, ministers and committees; none is required for a
directive to be authorized, so none was built. `parliament.summary()` names them
in the same object that reports the vote, because a status surface showing a
working ballot and nothing else would read as a finished governance layer.

### What belongs in the Constitution

Owner direction, 2026-08-28 (§144). The threshold was settled at §142; this is the
criterion, without which a two-thirds bar is a procedure with no subject.

> **Does this rule need to stand the test of time?**

Sharper than *is it important*, and the difference is what makes it usable. A
penalty for an agent that took a known shortcut and failed is important and
**situational** — it belongs in ordinary law, where a simple majority can change
it when the situation does. A right is not more important on any given day; it is
the one that must still be true in five years.

The two examples given are both rights: **the right to vote** and **the right to
appeal an unfavourable ruling.** Rights are level 0's natural inhabitants, because
their whole value is that the people they constrain cannot easily remove them.

**Both are now built.** The right to vote works — the roll is in the Articles,
`cast_vote` refuses anybody not on it, and amending the roll costs two-thirds. The
right to appeal was declared owed and unenforced in
[`backend/charter.py`](../backend/charter.py) from the day it was written, and
TQ-102 discharged it: [`backend/appeal.py`](../backend/appeal.py), §145.

**There is no court, and that was the answer rather than a compromise.** Every
candidate adjudicator fails — one appointed by vote is removable by the same vote,
Parliament contains the author, and the owner is what the charter already says is
not an appeal. The charter's requirement is *"reviewed by someone other than
whoever made it"*, which needs a **peer of the author**: same role, different
instance, chosen by neither party. Nothing is appointed, so nothing can be
removed. It is the fourth instance of one rule this system already applies three
times — producer is not approver, producer is not grader, preparer is not health
judge.

**An appeal that lapses is a denial nobody had to make**, so there is no
dismissal, no expiry, no auto-denial and no delete. It waits openly. And because
this organization runs one of each role, it would usually *keep* waiting —
so TQ-103 made a waiting appeal into staffing pressure: `roles_awaiting_a_peer`
names the role, and the COO raises that role's target by one. **Work determines
staffing** (46 §10), which is the same rule that gave the Portfolio Analyst
`on_demand` instead of a new agent class. `summary` still reports filed **and**
heard, since zero filed and forty filed with none heard are the same silence in
one number (§130).

**The loop was demonstrated live and the demonstration was of a defect** (§147).
TQ-102 read the graded party off the wrong column — a grade judges the *upstream
report*, so the agent it judges is the report's filer, not the Analysis agent that
wrote it. Corrected at TQ-104: `rulings_about(explorer-1)` returns the grades on
explorer-1's reports, and Analysis, being an author here rather than a subject,
gets nothing.

After the correction the same scenario files no appeal and spawns no peer, which
is right — the organization had been manufacturing grievances against itself every
cycle.

**And code cannot apply this criterion**, which matters because the direction
makes it tempting to try. The refusal covers what a proposal *declares*: a
situational penalty submitted as a constitutional amendment gets a two-thirds
vote, and a fundamental right submitted as ordinary law passes at a simple
majority. Choosing the route is a person's judgement (§126, §144 §3). A
classifier over the words would replace an honest limit with a confident one.

**A name now means two things.** The Constitution has *articles* — numbered
provisions — and level 1 is *the Articles*. Addendum 47 §5 forbids exactly that,
and it is flagged rather than resolved because renaming either is the owner's
(§144 §5). Nothing in code is affected today; `parliament` stores the Constitution
as one text with no article-level concept.

### The one rule a vote cannot reach

**The rule for changing the rules is not changeable by the rules**, and after
§142 this is the *only* thing at the top that a vote cannot reach.

The Articles carry the electorate, the quorum and the ordinary threshold — as
data, which is addendum 46 §2's whole point. Neither they nor the Constitution
carry the threshold for amending themselves; both are constants in code. An
instrument whose amendment bar is one of its own clauses can be lowered by simple
majority and then walked through.

That is tested rather than asserted: the suite amends the Constitution to say it
may be amended by simple majority, carries that at two-thirds, and then shows the
next amendment still needing two-thirds. **The text talks and the constant
decides.**

`CONSTITUTIONAL_AMENDMENT_THRESHOLD >= ARTICLES_AMENDMENT_THRESHOLD` is asserted
at import, because level 0 must never be cheaper to amend than level 1 — a
majority wanting an Articles change could otherwise take the constitutional route
and arrive with a highest-order directive (32 §19.2) for the same price. Today
both are two-thirds, which is the weakest form of that guarantee and is what the
specification states.

**One attack is named and deliberately not guarded.** The electorate for a
constitutional amendment is the Articles' roll, one level below the document being
amended — so a supermajority can amend the roll, and the roll decides who amends
the Constitution. A countermeasure would contradict 32 §19.3, which says in terms
that a constitutional amendment may require *"new voting rights"* and *"removal of
voting rights"*. Recorded at §142 §2 rather than engineered around.

**What the level-0 refusal cannot do**, stated rather than implied: the system
does not hold the Constitution, so nothing can read it and notice that a proposed
"policy" contradicts it. The refusal covers what a proposal *declares*. A
level-0 change wearing a lower label is not detectable here.

### How a rule reaches the organization, and where it stops

```
  proposal → vote → enacted resolution → instrument adopted at its level
                                              │
                                              ▼
                                    operating_context.for_role(agent)
                                              │
                                              ▼
                                    the agent's behaviour changes
                                              │
                                              ⚠  one code path, not the whole
                                                 organization (TQ-87)
```

**This works.** A rule was carried by vote and `register.file_entry` began
refusing submissions that did not satisfy it, with no code change — addendum 46
§2's claim executed rather than described.

It works for the Explorer, the Speculator and the register. **Analysis and the
COO do not read anything** — grading and directing are the two behaviours most
worth governing, and neither has an obligation kind that fits yet. Kinds are added
when a rule needs one, never in advance: a registry entry nothing obeys would
route work to nothing.

A rule obeyed must not look like a fault. When an agent is refused by an
instrument, it says so in its own words and carries on — because anything watching
the error stream would otherwise read a working policy as a malfunctioning
workforce, and remove the policy.

**Code cannot obey prose**, and the system says so rather than pretending
otherwise. An instrument carries `text` for people and an optional machine-
readable obligation; one without an obligation is reported as *prose only* — in
force, binding on whoever reads it, and not enforced by code. An obligation
nothing understands is **refused rather than skipped**, because a rule that was
voted through and changes nobody's behaviour is worse than no rule: everyone
believes the organization changed.

What an agent produces records the instruments it acted under, so *claimed to
follow* and *did follow* are different things on the record.

Precedence is enforced on read: the highest active authority on a subject is what
comes back, and lower material is reachable only under a name that says what it
is. Two equal authorities on one subject cause a refusal, never a choice — and
the conflict appears in the Speaker's report, because addendum 46 §5 requires it
to be escalated through governance rather than merely noticed.

**What it does not do:** detect a contradiction in the words. A procedure saying
the opposite of its policy is adopted without complaint. That limit is pinned by
a test, so it cannot quietly be believed away.

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

**Persistent.** Addendum 47 §14 lists what persistence may include: identity,
role history, experience, training history, performance history, important
decisions, lessons learned, responsibilities. Addendum 51 §3 makes an immutable
`agent_id` a requirement for *every* agent, because no personal agent can be
bound to a client and no career can survive a role change without one.

The COO has had a persisted identity since §88 — Kumbhakarnan, a name and a
continuity that survives restart and survives the code. TQ-97 built the general
one: [`backend/agent_identity.py`](../backend/agent_identity.py). Status:
`IN DEVELOPMENT` — identity, naming and lifecycle exist; role history,
experience and training history do not.

**The thing it corrected is worth knowing.** The owner decision of 2026-08-17
already separated the durable agent from its job — `agent_names.name` is the
agent, `agent_registry.identity` is the desk. But the durable thing *was the
display name*, which addendum 51 §3 forbids in terms (*"independent of display
name"*), and `coo_identity.rename()` already existed to turn that into a defect:
renaming a name-keyed agent either breaks every join or hands its history to
whoever holds the name next. So `agent_id` is now the anchor, the first name is a
display attribute of it, and **a name that has ever been held is never given to
another agent** — enforced against the whole history rather than the current
binding, because a name that changes hands makes every older sentence about it
ambiguous.

The last name is **derived, never stored**. Addendum 51 §2's *"Jack Explore Agent
1"* is a first name plus the desk's designation, so *Jack Explorer Agent 1*
becomes *Jack Reporter Agent 1* by moving desk — addendum 50 §12's career path,
costing nothing, because the last name was never a fact about the agent. An agent
at no desk has no last name rather than a placeholder.

Addendum 51 §6's eight lifecycle states are all named and **three are refused** —
`training`, `evolving`, `archived` — because nothing in this system produces
them, and a column that accepted them would assert a capability by existing.

**Temporary.** Every other agent is still a subprocess spawned for work and
released when the work ends, and it keeps nothing across a restart. Providence
requires that to change (49 §20, 50 §11); the identity to hang it from now
exists, and nothing yet uses it to carry experience.

**Shared organizational knowledge is separate from both**, and must stay so. What
the organization knows lives in the backend's knowledge tables; what a particular
continuing agent has learned is its own. Collapsing them would mean an agent's
private experience silently becoming organizational fact, or organizational fact
being lost when an agent is released.

**Client data belongs to neither**, and there are now two kinds of it. What a
client *owns* is held for the length of one request and discarded (section 5).
What a client *told* us persists — the profile, TQ-98 — and so does the Gateway's
record of having served them.

That second store was found rather than built: `gateway/client_agent.py` has
given each client a persistent named representative, with voice, visual identity
and continuity across meetings, since addendum 43 §16. **Addendum 50 §6's
Personal Usher is therefore half-built already** (§143 §3), under an older name —
the same shape as cooperation having been measured for months before addendum 48
asked for it. What is missing is the conversational half.

### Departments

Specified across the addenda; mostly `TO BE DEVELOPED`. What exists:

| Department | Status | Where |
|---|---|---|
| Department of Education | `IMPLEMENTED` (portfolio-analysis curriculum only) | [`backend/curriculum.py`](../backend/curriculum.py), [`simulation/training.py`](../simulation/training.py) |
| Personal agents (Providence) | `IN DEVELOPMENT` — TQ-97 identity, TQ-98 the client profile. The Usher is half-built in the Gateway and has no conversational half (TQ-101) | [`backend/agent_identity.py`](../backend/agent_identity.py), [`backend/client_profile.py`](../backend/client_profile.py) |
| Strategy | `IMPLEMENTED` in part — the register and the strategy store | [`backend/strategy.py`](../backend/strategy.py), [`backend/register.py`](../backend/register.py) |
| Department of Evolution | `TO BE DEVELOPED` | addendum 30 |
| Software Engineering | `IN DEVELOPMENT` — TQ-83, TQ-96. [`backend/engineering.py`](../backend/engineering.py), [`agents/software_engineer.py`](../agents/software_engineer.py). Delivers directives as governed data or names the capability gap, and stages approved work into a release candidate; **writes no code** |
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

**The database is a transport, not a store** — with one declared exception. A
request is deleted when claimed, a report when collected, a session's rows on
disconnect, and an expired row is treated as absent *on read* rather than
trusting a sweeper to have run. That is how an agent architecture built on
database queues serves a system that retains nothing (§117).

The exception is the **client profile** (TQ-98, §143), and it is stated here
rather than left to be discovered next to the rule it qualifies. A preference
discarded at disconnect is not a preference; it is a question asked again every
session, and addendum 51 §4 cannot have personal agents without one. So
`client_preferences` and `client_watchlist` persist, and the boundary is
structural:

- **A profile is what the client *told* the system.** Sixteen fields,
  addendum 51 §15's and no others — a closed vocabulary, because an open one is
  where a portfolio ends up.
- **A portfolio is what the client *owns*.** Unchanged: fetched per session,
  never stored.
- **A watchlist is the line.** Symbols the client typed are a preference; symbols
  derived from a fetched portfolio are a holding. The two are identical as data,
  so the `source` column is a **convention** and the guarantee is elsewhere: **a
  watchlist entry is a symbol and nothing else.** No quantity, no cost basis, no
  account, no price. A watchlist assembled entirely from a fetched portfolio is
  still not a portfolio, because what makes positions worth protecting has
  nowhere to go — and a test fails the suite if a column that could hold one
  appears.

Ownership is evidence here too: every call takes an `OwnerContext` resolved from
the session, never a `client_id` a caller sent. And leaving is a function —
`forget_everything` — because this is the first backend store that does not end
on its own.

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
| Governance under simulation | `IMPLEMENTED` — TQ-88. A scenario may seed the Articles, a carried resolution and an instrument, **through the organization's own API and never SQL** |
| Historical-data operation | `TO BE DEVELOPED` | Addendum 47 §6 and addendum 46 §27 both require it |

### What a simulated run can and cannot show

Every active scenario is run and read; the survey that produced the current set
is recorded at §128. Two things are worth knowing before trusting a green run:

- **A scenario cannot exercise deliberation.** No agent proposes or votes, so a
  governed run seeds its Articles and its resolution and measures what happens
  *after* a decision — an instrument in force, and agents that have to read it.
  `governed_organization` passes 11 of 11: eight reports filed under the rule and
  none outside it.
- **A seed cannot build a state the organization could not reach.** Every step
  goes through the production API; a fixture able to construct an instrument with
  no resolution behind it would measure the fixture rather than the system.

**One command answers the whole question:**

```bash
python -m simulation verify
```

It runs every runnable scenario and the whole curriculum and gives one verdict.
The two systems are not merged — a scenario measures the organization *operating*
and a curriculum measures an agent *learning* — but the answer is now in one
place.

The verdict has three values, and the third is the important one. `INCOMPLETE`
means nothing failed and not everything was asked: six scenarios need a model,
and a verifier reporting "no failures" over the ones it skipped would be
certifying an organization it had not examined. Only `PASS` exits zero.

A key being reachable is not a model being callable. When the daily token budget
is exhausted every call is refused, and a scenario that ran anyway would report
failures about spending that look exactly like failures about the organization —
so the budget is checked and those scenarios are skipped (§132).

It prints what it cannot see with every verdict — deliberation, real prices, a
real broker, historical operation, **code** release, and release acceptance
criteria. A green line therefore means something specific and limited, which is
the only kind worth having. That list is re-aimed rather than shortened: TQ-96
closed governed-data release and rollback, and the entry narrowed to the half
this organization may not perform rather than disappearing (§139 §6).

### Where the whole thing currently stands

One command, `python -m simulation verify`, runs eleven scenarios and the whole
curriculum. As of 2026-08-28 it returns **PASS**: forty-six properties across an
organization that starts, staffs itself, discovers, cross-checks, judges, grades,
governs itself under an instrument, refuses what a badly drafted instrument
forbids, and shuts down leaving nothing running.

A tenth scenario, `slow_agent`, stalls one model call for ninety seconds and
asserts what used to fail: no respawn, and an agent **reported** slow and then
reported advancing again. Live, COO said *"analysis-1 is alive and its work has
not advanced for 45s. Not a crash and not being replaced"*, and sixty-eight
seconds later *"advancing again"* — zero incidents. Before TQ-93 that exact stall
replaced the agent.

That scenario exists because the first green verification did not exercise the
liveness split at all: nothing happened to be slow that day, and **a green run
over a condition that never happened is not evidence about the condition**. The
condition is now producible on demand.

### Liveness and progress are two signals

An agent reports two things and they answer different questions. **Progress** —
a cycle completed — is bounded by the work, which means by the slowest model call.
**Liveness** — the process is up — is emitted by a thread on its own five-second
clock and is bounded by nothing the work does.

COO's crash detection reads liveness. An agent inside a slow model call is alive
and not advancing, which is reported and **not** treated as a crash; before TQ-93
that state had no name, so a busy Analysis agent was declared dead and duplicated.
An agent that emits no liveness at all — the Controller, which is the server
process — is judged by progress exactly as before.

The point is which clock each depends on. A staleness threshold above a
vendor's slowest call is a number chosen against something this system does not
control; above a five-second interval it chooses, it is a number this project can
justify. That is what `TIMING_CONSTANTS.md` asks of every constant.

### A rule that forbids its own subject

An instrument in force can be drafted so that nothing can satisfy it — by naming
a field the drafter assumed existed. The organization then goes completely
silent: no reports, no analyses, nothing in the queue, every agent healthy, no
respawns, no failed directives. **It looks exactly like a quiet market**, and
every instinct reads it as calm.

Refusals are counted, attributed to the instrument that caused them, and reported
by the Speaker. Zero filed and zero refused is a quiet market; zero filed and
ninety-one refused is a rule forbidding its own subject. One number cannot tell
those apart and two can. The `misdrafted_instrument` scenario runs exactly that
case.

The record carries the unmet obligations **by name and never their values**: a
submission's field names are the organization's vocabulary, its contents are
whatever somebody was filing.

### The department that is supposed to replace the external developer

Addendum 46's terminal claim is *Jarvis develops Jarvis*. The first increment
exists: an engineer takes an authorized directive and either proposes the
instrument that would put the outcome in force, or records that the architecture
lacks the mechanism.

The ladder's question — *can this be done as governed data?* — is answered by the
registry that already knows whether a mechanism exists, not by asking a model.
A model asked *"could this be data?"* answers plausibly every time, including
when it cannot.

**It writes no code.** Level 5 is named and stopped at, which addendum 46 §8
defines as the correct outcome rather than a failure. It never approves its own
proposal, and there is no reviewer role yet, so proposals wait for a person.

Every proposal carries an impact statement: who the instrument would bind, what it
would displace, and **whether adopting it would be refused** — caught at proposal
time rather than after somebody spends an approval finding out. It names what it
does not assess, because training, certification, rollout and rollback are all
things this system has no way to plan (§138).

Everything else in addendum 46 — phases 2 to 4, the complexity ladder, the
maturity metrics, the external-dependency curve — is unbuilt.

### What the organization is supposed to be, and what code can hold of it

Addendum 48 states the ethic: shared success between Creator, Agents and Clients,
cooperation over competition, maturity, reciprocal trust, responsible freedom, and
respect that is explicitly **not** blind obedience.

**Code cannot obey prose**, and the Scripture is entirely prose. Nothing here can
check maturity, patience or good faith; loaded into the governed store it would
sit permanently in `prose_only` — in force and enforced by nothing, which is what
that field exists to make visible. Its influence runs through three channels and
no others: the external developer, the agents' own prompts, and code that happens
to embody it.

One part of it is already measured under a different name. Cooperation is a
condition of leadership in both addendum 48 §3 and addendum 37 O9, and both were
read as unbuilt — while `cross_check.unanswered_rate` has been recording one agent
leaving another waiting since long before either was assimilated (TQ-92).

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

Everything in this section was `TO BE DEVELOPED` until TQ-83 and TQ-96. The
Software Engineering Department and the governed-data release are now built; the
Department of Evolution, the sandbox and the code release are not, and each says
so under its own heading.

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

`IMPLEMENTED` for governed data — TQ-96. [`backend/release.py`](../backend/release.py).
**Not built, and not this organization's to build, for code.**

The first question was what a release even *is* here, because the governed layer
already changes behaviour without one: adopting an instrument changes what agents
do immediately, so the ordinary meaning of *release* was already taken. §139
answers it:

> **A release is a named set of governed changes that stand or fall together,
> whose way back is authorized before the way forward is taken.**

That supplies the three things adoption does not. A **boundary** — `adopt` takes
one instrument, and a refusal partway through a set leaves a state nobody
designed, so `apply` is all or nothing. A **way back that needs no vote** — the
store supersedes forward only, so undoing a change meant carrying a resolution
through Parliament, which is the right cost for changing your mind and the wrong
cost for an incident. Addendum 30 §27's *"Rollback SHALL be defined before
rollout"* is therefore the mechanism and not the advice: the release's own
resolution authorizes the reversal, granted at prepare time. And a **health
verdict** — 46 §18 marks a release unhealthy, and nothing here marked anything as
anything.

**Health is `unknown` until somebody judges it with evidence, and never
`healthy` by default.** §118's rule unmodified: absence of complaint is not
evidence that a release is working. The judge may not be the preparer.

**Reversal restores rather than re-adopts.** The superseded row is reactivated
and the failed instrument is superseded *by the one it gave way back to* — a
`superseded_by` pointing backwards in id order, which no ordinary supersession
can produce. So a rollback is distinguishable from a change of mind by reading
the table, and nothing is deleted (46 §18).

**The code half is not performed here.** `backend/version.py` answers *which code
is this?* by asking git: the organization observes its code version and cannot
choose it, because nothing in the running system may write to the repository —
the same prevention-by-absence that keeps agents out of `docs/` and the
Constitution out of every table. So there is no `deploy()`, and a tripwire fails
the suite if `release.py` ever imports `subprocess` or `os`. What is kept instead
is the record: the code version at prepare, apply and reversal, and a divergence
reported rather than corrected — **restoring the data under a different code
version is not a return to the last known-good condition.**

**§119 §5's constraint turned out to be satisfied by the architecture rather than
by care.** A release must not be built as a restart script; addendum 46 §18 step
4 asks agents to reload the previous authorized state, and this system has
nothing to reload — `operating_context` reads the store at the point of work and
no agent caches an instrument. A governed-data release needs no restart because
nothing holds stale governed data; a code release needs one and is not performed
here.

The department stages into a candidate rather than adopting (46 §16's Version
N+1), and **what a piece of engineering work is currently worth is derived on
read, never stored** — a work row cannot know it was later reversed, so a
department scored on its stored outcome would keep credit for every rolled-back
change. That is §119 §8's metric trap in the dimension release created.

Still absent, named so the line above means something: acceptance criteria (health
is a judgement, not a computed threshold), a postmortem written into
organizational knowledge (composed on demand instead — nothing reads that store
back), and Evolution, which is the department addendum 30 §4 assigns the rollout
plan to.

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
| Client portfolios are never stored | `IMPLEMENTED` | No table exists; a tripwire fails the suite if a storage module returns. **Re-aimed at §143** — the originals asked about a `portfolios` table and would pass forever while the client watchlist grew a `quantity` column |
| A client profile holds statements, never holdings | `IMPLEMENTED` | Closed 16-field vocabulary; a watchlist entry is a symbol and nothing else; no module may both read positions and write a profile |
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

**Test suite: 2,862 passing, 8 skipped** (2026-08-28). The skips are deliberate
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
- A code release, or a code rollback. A **governed-data** release and rollback
  has happened — `release_and_rollback` applies one to a running organization,
  finds it misdrafted, and reverses it with no restart and no respawn (§139).
- An agent proposing a change to the organization of its own accord.
- Any Articles in force in the working database — the machinery runs, and the
  organization it would govern has not yet been given its instrument. The same is
  now true one level up: the Constitution's machinery runs and no text is in
  force.
- A constitutional amendment. The path exists and is tested; nothing has been
  amended, because there is nothing yet to amend.

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

1. **A producing agent learns how its work was judged, and cannot yet learn
   *from* it.** TQ-103 closed the half that needs no model: Analysis reads the
   rulings about its own work each cycle and acts on them. What it cannot do is
   let a grader's rationale change its reasoning, which needs something that
   reads text — the `prose_only` boundary again (§126).
1a. **Nothing files an appeal, and that is now the honest state** (§147). The
   right exists, its two grounds are facts in the record — the grader filed the
   report it graded, or the ruling carries no reasoning — and neither currently
   arises. §146 claimed otherwise and was wrong; see below.
2. **Lessons written when a lens goes stale are never read back.** They are
   preserved and guarded against duplication, and no consumer exists.

### Gaps in the service

3. **No real prices** (section 6). Blocks valuation and scenario work.
4. **No credential path** (section 5). The transport refuses secrets rather than
   carrying them, which is correct and is not a solution.

### Open questions awaiting an owner decision

5. **Where the living documentation and operational detail should live**, given a
   public repository (section 9).
5b. **Should level 0 cost more than level 1?** Answered in part: the
   organization may amend the Constitution at two-thirds (§142), the same bar as
   the Articles. So precedence separates them and price does not. Whether that is
   intended is an owner question; the code asserts only that level 0 is never
   *cheaper*.
5c. **`JARVIS_GAP_ANALYSIS.md` is stale.** It scores the build against the
   Constitution, and the Constitution became v2.0 on 2026-08-28 (§141 §1).
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
