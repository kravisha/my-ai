# Documentation Reconciliation Plan

**Status: Proposed — for owner review. Nothing has been moved, merged, or deleted.**

Response to `PROJECT_JARVIS_DOCUMENTATION_DIRECTIVE_FOR_CLAUDE.txt` (2026-08-16), whose §17 asks for
an inventory and reconciliation pass *before* consolidation. The ten deliverables it specifies are
below, preceded by the blocker §15 requires be raised explicitly.

Assessed against commit `46aa60d`, 549 tests passing.

---

## 0. The blocker §15 requires be flagged first

**This repository is public: `github.com/kravisha/my-ai`.**

The directive is unambiguous — *"A directory named internal_docs is not private if it is committed to a
public Git repository."* Creating `internal_docs/` here would produce something worse than the current
state: material filed under a name that asserts confidentiality while being world-readable, which is
how genuinely sensitive content ends up published by people who believed the directory name.

§15 offers three architectures. Assessed against this project:

| Option | Assessment |
|---|---|
| **A — make the whole repository private** | Simplest and fully effective. Costs the public artifact you have deliberately built and asked me to publish twice. |
| **B — a separate private documentation repository** | **Recommended.** Keeps the public repo as the shareable artifact, puts institutional memory somewhere access-controlled. Costs one cross-repo link and the discipline of remembering which repo a document belongs in. |
| **C — another access-controlled store** | Viable, but splits documentation from version control and from the code it describes. |

**Nothing in the private layer should be created until this is decided.** Everything below is
structured so the decision can be made once and applied cleanly.

An honest qualifier on urgency: I scanned the current `docs/` for credentials and personal
identifiers and found none, and the addenda are your own architectural specifications, already public
by your choice. So today's exposure is **not** an incident. The risk is prospective — §13's failure
log, §8's risk/audit domain, and §7's operational procedures are exactly the material that should
never have been public, and the directive asks me to start producing them.

---

## 1. Documentation inventory

Twenty-one documents, 4,308 lines. Every one is currently public.

### Maintained (this project's own records — edited as things move)

| Document | Lines | Purpose | Health |
|---|---|---|---|
| `JARVIS_CONSTITUTION.md` | 283 | Supreme authority: axioms, evidence discipline, governance, direction | Current |
| `JARVIS_GAP_ANALYSIS.md` | 817 | Built-versus-constitution, with verification evidence per closed gap | Current, and the single most useful file |
| `SPEC_RECONCILIATION.md` | 347 | Conflicts *between* specs; owner decisions; what was declined and why | Current |
| `TIMING_CONSTANTS.md` | 100 | Rate-dependent constants and whether the rate was measured | Current |
| `README.md` (docs) | 91 | Index, precedence, reading orders | Current |
| `MY_AI_DESIGN_SPEC.md` | 193 | Original product spec: permissioned action layer, data governance | **Stale — see §3** |

### Verbatim addenda (supplied specifications, marked do-not-edit)

| Set | Documents | Status |
|---|---|---|
| Third FI set | 11 (organization), 12 (integration), 13 (training), 14 (Alpha acceptance) | Canonical |
| Derived | 15 (rationality monitoring) | Canonical for its subject; **nothing in it is built** |
| Second FI set | 5, 6, 7, 8, 9, 10 | Canonical except where 11–15 clarify |
| First FI set | 2, 3, 4 | **Superseded** by 5–10 |
| Base product | 1 (universal agent) | Historical; unrelated to Financial Intelligence |

### Named by the directive but **not present in this repository**

| Referenced as | Reality |
|---|---|
| "the ChatGPT organizational architecture handoff pack" (§4) | Not in the repo. Two ChatGPT documents were supplied in conversation — a LiveKit/JARVIS assimilation and the Sentinel argument. The latter became addendum 15; the former was assessed and not adopted. Neither was saved as a file. |
| "the forthcoming Simulation and Organizational Learning design" (§4) | Does not exist yet. §9–§11 of the directive commission it. |

Both need to exist as documents before §4 can reconcile them. Recorded as gaps in §6 below rather
than treated as if present.

---

## 2. Authority map

The precedence chain is already established and working; the directive asks that it be made explicit,
which `docs/README.md` partly does.

```
JARVIS_CONSTITUTION.md            supreme — principles
        │
        ├── addenda 11–15         organization, integration, training, acceptance
        │       │
        │       └── addenda 5–10  where 11–15 do not clarify
        │               │
        │               └── addenda 2–4   SUPERSEDED
        │
        ├── SPEC_RECONCILIATION.md    where conflicts between the above are resolved
        │                             and owner decisions recorded
        │
        └── JARVIS_GAP_ANALYSIS.md    what is actually built against all of it
```

Governing relationships by subject:

| Subject | Governed by | Reconciled in | Verified in |
|---|---|---|---|
| Axioms, evidence discipline | Constitution | — | Gap analysis §2 scorecard |
| Agent roles and authority | Addendum 11 | Reconciliation §2.1 | `backend/controller.py`, `agents/coo.py` |
| Lifecycle and dormancy | Addendum 11 §9 | Reconciliation §2.2 | `tests/test_controller.py` |
| Detection and peer analysis | Addendum 7 | — | `agents/explorer.py` |
| Cross-check and disagreement | Addendum 12 §14 | Gap analysis §4.3 | `tests/test_triage.py`, live verification |
| Training and knowledge | Addendum 13 | Gap analysis §4.1 | `backend/fi_db.py` knowledge store |
| Alpha acceptance | Addendum 14 | — | `tests/test_control_panel.py`, `tests/test_uqi.py` |
| Rationality monitoring | Addendum 15 | Reconciliation §1 | **Nothing — unbuilt by design** |
| Rate-dependent constants | — | `TIMING_CONSTANTS.md` | Live measurement |

---

## 3. Duplication and conflict report

**No two active documents make contradictory authoritative claims.** The Conflict Rule has been
applied throughout, and `SPEC_RECONCILIATION.md` holds the resolutions. What follows is genuine
friction, not contradiction.

| # | Finding | Severity | Proposed handling |
|---|---|---|---|
| 1 | **`MY_AI_DESIGN_SPEC.md` is stale.** Last touched 2026-08-11, before the entire Financial Intelligence build. It describes the permissioned-action-layer product; the repo is now predominantly an agent organization. The root README still points at it as "the full architecture". | Medium | Mark **historical**, retitle to reflect that it governs the *product layer* only, and repoint the root README at the docs index. Do not delete — it still governs `app/` accurately. |
| 2 | **Root README describes Milestones 1–5**, which stop before Phase C. It has not been updated across ~19 increments. | Medium | Rewrite the "what this proves" section against current state. |
| 3 | **Addendum 15 is derived, not verbatim**, unlike 1–14. Already flagged in the reconciliation doc and its own header. | Low | Already handled; carry the distinction into any new structure. |
| 4 | **Addenda 2–4 are superseded but sit alongside canonical ones**, distinguished only by the index. | Low | Move to an `archive/` or `historical/` subfolder so the filesystem states it, not only the index. |
| 5 | **No document describes the *code*.** Every doc is specification or measurement; nothing explains module layout, how to run the system, or how the pieces connect at the source level. The knowledge lives in module docstrings, which are unusually thorough but not navigable. | **High** | The largest genuine gap. See §6. |
| 6 | **No orphan documents.** Every file in `docs/` is reachable from the index, and every one is referenced by something. | — | No action. |
| 7 | **Two ChatGPT inputs were assessed in conversation and never recorded as documents.** The reasoning — including why the LiveKit architecture was not adopted — exists only in chat history, which the directive's §16 explicitly says must not be required. | Medium | Write them up as decision records. See §6. |

---

## 4. Proposed documentation tree

Deliberately flatter than the directive's fourteen-directory sketch, which §2 permits ("Claude may
improve this taxonomy… the resulting hierarchy must remain simple and obvious"). Fourteen directories
for a repository with twenty-one documents would create more empty scaffolding than structure — and
empty structure is the failure mode this project has spent nineteen increments refusing.

### Public layer — `docs/`

```
docs/
  README.md                     index, precedence, reading orders
  OVERVIEW.md                   (new) what Project Jarvis is, in one page
  ARCHITECTURE.md               (new) module map, how to run it, how the pieces connect
  STATUS.md                     (new) designed-vs-built, GREEN/YELLOW/GRAY/RED
  JARVIS_CONSTITUTION.md
  SPEC_RECONCILIATION.md
  TIMING_CONSTANTS.md
  diagrams/                     (new) mermaid sources, regenerable
  addenda/                      canonical specifications 5–15
  archive/                      addenda 1–4, MY_AI_DESIGN_SPEC.md
```

### Private layer — **separate repository**, pending the §0 decision

```
jarvis-internal/
  00_START_HERE/README.md       the §3 entry point
  DECISIONS/                    ADRs, including the ChatGPT assessments
  FAILURE_LOG/                  §13 organizational failure and evolution log
  SIMULATION/                   §9-§11 design, including Monte Carlo
  RISK_AND_SAFETY/              §8
  OPERATIONS/                   runbooks, verification procedures
  AI_HANDOFFS/                  §14
```

**`JARVIS_GAP_ANALYSIS.md` is the hard classification call.** It is the most useful document in the
repository *and* the most revealing: it enumerates precisely what is absent, unvalidated, and
unverified. That is either honest engineering transparency or a capability map for someone assessing
weaknesses, depending entirely on who reads it. My recommendation is **public** — it is what makes
this repository credible rather than promotional, and nothing in it is exploitable in the §15 sense.
Flagged for your decision rather than assumed.

---

## 5. Migration map

| Document | Action | Rationale |
|---|---|---|
| `JARVIS_CONSTITUTION.md` | **KEEP** (public) | Supreme authority; already canonical |
| `JARVIS_GAP_ANALYSIS.md` | **KEEP** (public — pending §4 decision) | Current, verified, most useful single file |
| `SPEC_RECONCILIATION.md` | **KEEP** (public) | Canonical conflict record |
| `TIMING_CONSTANTS.md` | **KEEP** (public) | Current; unusual and worth showing |
| `docs/README.md` | **KEEP + EXTEND** | Add status terminology, new documents |
| `MY_AI_DESIGN_SPEC.md` | **MOVE → `archive/`, retitle** | Stale as system architecture; accurate for `app/` only |
| Addenda 5–15 | **KEEP** in `addenda/` | Canonical |
| Addenda 1–4 | **MOVE → `archive/`** | Superseded or unrelated; filesystem should say so |
| Root `README.md` | **REWRITE** | Describes a five-milestone product that has since become an agent organization |
| — | **CREATE** `OVERVIEW.md`, `ARCHITECTURE.md`, `STATUS.md`, `diagrams/` | See §6 |

**Nothing is deleted.** Superseded material is archived with its status stated, per the directive's
§5 and this project's existing practice of preserving what turned out wrong.

---

## 6. Missing canonical documents

Only genuine gaps — each justified by something a new engineer could not currently determine.

| # | Document | Why it is genuinely missing | Priority |
|---|---|---|---|
| 1 | **`ARCHITECTURE.md`** | Nothing describes the code. A new engineer cannot learn the module map, the polling model, that SQLite is the only IPC, or how to run the system, without reading 7,900 lines. This is the single largest gap. | **High** |
| 2 | **`STATUS.md`** | §6 of the directive requires a designed-vs-built view with GREEN/YELLOW/GRAY/RED. The gap analysis has the content but organizes it by constitutional gap, not by capability. | **High** |
| 3 | **`OVERVIEW.md`** | The root README opens with "Milestone 1+2+3+4+5", which tells a newcomer nothing about what this is. | High |
| 4 | **Decision records** | Roughly twenty substantive decisions this session exist only in commit messages — sleep-equals-dormancy, trainer-as-sentinel, labelled-never-filtered, structural-not-semantic novelty. Commit messages are durable but not navigable. | Medium |
| 5 | **Simulation and Monte Carlo design** (§9–§11) | Commissioned by the directive; does not exist. Note that addendum 8 already specifies simulation/training and would govern it. | Medium |
| 6 | **Organizational failure log** (§13) | Does not exist. There is real material: the orphaned processes, the three rate-constant defects, the novelty off-by-one. | Medium |
| 7 | **Diagrams** (§8) | None exist in any form. | Medium |
| 8 | **ChatGPT assessment records** (§14) | The LiveKit assessment and the sentinel reconciliation happened in conversation; only the outcome survives. | Medium |

**Deliberately not proposed:** an org chart of roles that do not exist. §7 lists CEO, HR, trainers,
evaluators, rotations, succession, promotion. Of these, only COO, Explorer, Speculator, Analysis and
Controller are real. §7 itself says *"Do not manufacture bureaucracy simply to fill an org chart"* —
documenting the unbuilt ones as though they were organizational fact would be exactly that.

---

## 7. Public/private classification

| Material | Layer | Rationale |
|---|---|---|
| Constitution, addenda, reconciliation | **Public** | Already public by your choice; architectural thinking, nothing exploitable |
| Architecture, overview, status | **Public** | The point of a public repository |
| Timing constants | **Public** | Operational tuning with measurements; discloses nothing sensitive |
| Gap analysis | **Public, flagged** | See §4 — enumerates weaknesses; honest but revealing |
| Decision records | **Public** | Reasoning about architecture, not operations |
| Failure log (§13) | **Private** | §15: "sensitive failure analysis". Deliberately catalogues where the system breaks |
| Risk register (§8) | **Private** | §15: "internal risk findings that materially increase attackability" |
| Operational runbooks | **Private** | §15: "private operational procedures" |
| AI handoffs | **Private** | Working material; §15's "unnecessary internal reasoning/history" |
| Anything with credentials | **Neither** | `.env` is untracked and must stay so |

Independent of classification: secret scanning stays on the whole repository. A document's folder is
not a security control — the §0 blocker is the same principle at repository scale.

---

## 8. Simulation documentation plan

The directive commissions this (§9–§11), and one thing should be said before designing it: **addendum
8 already specifies training, simulation, validation and continuous learning**, and addendum 13
extends it. A new simulation design must be reconciled against those rather than written beside them,
or it becomes the two-active-documents problem §5 forbids.

Proposed sequence, smallest first:

1. **Reconcile first.** What addendum 8 §4's test progression and §5 regression framework already
   mandate, and what §9–§11 add beyond it.
2. **Design the minimum subsystem.** §10 explicitly says *"Do not assume these require six permanent
   autonomous agents… Design for minimum complexity first."* My reading of the current system: the
   Scenario Designer, Monte Carlo Controller, and Event Generator are **configuration and a
   harness**, not agents. Evaluation already exists as `grades`. Only the Analysis/Curriculum function
   plausibly needs autonomy, and only once there are trials to analyse.
3. **Check the fixture can produce the phenomenon.** This project's most reliable lesson: four
   increments were reshaped by discovering the fixture could not exhibit what the detector was meant
   to detect. Simulation is a fixture-generation subsystem, so this applies with full force.
4. **Metrics (§11) last.** The directive warns about Goodhart effects; the honest sequence is to
   measure what simulation reveals, not to define metrics an unbuilt system will be judged by.

One risk worth naming now: §9's principle that simulation should use *normal organizational
interfaces* is already partially satisfied — synthetic providers feed the real Explorer and Speculator
through the real interfaces. That is a genuine head start and should be built on rather than replaced.

---

## 9. Diagram plan

Mermaid, source-controlled in `docs/diagrams/`, rendered by GitHub natively. Seven views per §8, with
status colouring.

| View | Content | Feasible today? |
|---|---|---|
| A. Organization chart | Controller, COO, Explorer, Speculator, Analysis, dummy — GREEN. Bob, HR, trainers, evaluators, sentinels — GRAY | Yes |
| B. Dependency and feedback flow | Detection → cross-check → triage → analysis → grades → lens health → back to detection | Yes — and this is the one that pays |
| C. Agent lifecycle | The two-axis model: lifecycle × process, with stop/retire/resume transitions | Yes |
| D. Governance and authority | COO requests, Controller executes, operator directs, owner decides | Yes |
| E. Knowledge and learning flow | Evidence → grades → source standing; lens failure → lesson; uncertainty → open question → next analysis | Yes |
| F. System architecture | Backend, panel, monitor, agents-as-processes, SQLite as sole IPC | Yes |
| G. Simulation architecture | — | **Not yet** — nothing to draw until §8 exists |

§8 requires the dependency view to **identify missing feedback loops**. Three are currently missing
and the diagram should show them as such: nothing feeds analysis quality back into Explorer's
detection; nothing feeds source standing back into what gets collected; nothing revises the
conceptual structure when novelty appears.

---

## 10. Implementation plan

Small, reversible phases. **Phase 0 gates everything private.**

| Phase | Work | Reversible? | Depends on |
|---|---|---|---|
| **0** | **Owner decides the §0 repository architecture** | n/a | Owner |
| 1 | Create `OVERVIEW.md`, `ARCHITECTURE.md`, `STATUS.md`. Rewrite root README. Purely additive | Yes | — |
| 2 | Add `docs/diagrams/` views A–F | Yes | Phase 1 |
| 3 | Move addenda 1–4 and `MY_AI_DESIGN_SPEC.md` to `archive/`, update the index. Git-tracked moves | Yes | Phase 1 |
| 4 | Write decision records for this session's substantive decisions | Yes | — |
| 5 | Stand up the private layer per the Phase 0 decision; seed the START_HERE entry point | Yes | **Phase 0** |
| 6 | Move failure log, risk, operations, AI handoffs into the private layer | Yes | Phase 5 |
| 7 | Simulation reconciliation and minimum design | Yes | Phase 5 |

Phases 1–4 are safe to begin immediately: they add public documentation and archive superseded
material without touching the public/private boundary. Phases 5–7 must wait for Phase 0.

---

## What I recommend

**Decide Phase 0 now** — my recommendation is option B, a separate private repository, keeping this
one as the public artifact.

**Then let me do Phases 1–4**, which are the highest-value work in this plan and need no decision:
the repository currently cannot tell a new engineer what the code looks like or how to run it, and
that is a larger gap than anything the private layer would hold.

**And one caution about the directive itself.** It asks for fourteen internal directories, seven
diagram families, a simulation department, and an organizational chart covering roles that do not
exist. Building all of that now would produce a documentation system describing a system that is not
there — the same failure this project has refused nineteen times in code. I would rather document
what exists accurately and let the structure grow as the system does.
