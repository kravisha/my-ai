# Design Documents

Everything governing this system's design, in one place. Forty-six files here, accumulated across
several design sessions, and five more held privately; this index says what each one is, which govern
which, and what order to read them in.

**Five documents this index names are not in this repository** — the constitution and addenda 5, 11,
15 and 22. They are held privately, deliberately, and are named without links wherever they appear
below. [`GOVERNANCE.md`](GOVERNANCE.md) explains the split and
[`PUBLIC_PRIVATE_BOUNDARY.md`](PUBLIC_PRIVATE_BOUNDARY.md) the rule it is maintained under. A
reference you cannot follow means the document is private, not missing.

**Start here:** [`GOVERNANCE.md`](GOVERNANCE.md) for what governs this system and how much of it is
published, then [`JARVIS_GAP_ANALYSIS.md`](JARVIS_GAP_ANALYSIS.md) for what is actually built against
it. The gap analysis is the single most useful file here, and it is public in full.

---

## Precedence

Documents disagree with each other, so the order matters. Higher layers win.

| Layer | Document | Authority |
|---|---|---|
| **Constitutional** | `JARVIS_CONSTITUTION.md` — **held privately** | **Supreme.** Governs principles. Where an addendum conflicts, the constitution wins and the addendum is reconciled to it. |
| Architectural | [`addenda/`](addenda) 34–37 (Organizational Doctrine, second set) | Canonical **for training-through-simulation, multi-LLM model strategy, the Department of Education, and continuous optimization**. Extends 28–33 with the learning machinery: how needs become curricula, Monte Carlo simulations, trained and certified behavior, and measured real-world effect. Nearly all roadmap. Where these touch the built training loop (13), the simulation world (25), or the provider layer (16 §24), record the disposition in `SPEC_RECONCILIATION.md` §60 rather than assuming the newer set wins. |
| Architectural | [`addenda/`](addenda) 28–33 (Organizational Doctrine) | Canonical **for the target organizational structure: security defense, business continuity, systemic evolution, strategy, governance, and strategic doctrine**. A description of the organization MyAI is to become, not of the built system — nearly all of it is roadmap. Where these touch the FI addenda (11–15), the Gateway lineage (16–18), or Day Zero (21–27), record the disposition in `SPEC_RECONCILIATION.md` §47 rather than assuming the newer set wins. |
| Architectural | [`addenda/`](addenda) 21–27 (Day Zero lineage) | Canonical **for Day Zero startup, reference data, the simulation training world, and the arbitrage library**. Builds on 20's engine architecture. 22 is held privately. Within the lineage, 24 governs 26 where they differ. Where these touch other lineages, record the disposition in `SPEC_RECONCILIATION.md` §39 rather than assuming the higher number wins. |
| Architectural | [`addenda/`](addenda) 16–18 (Gateway lineage) | Canonical **for the external communication boundary and backend infrastructure only**. A separate subject from 2–15, not a newer set of it — these neither supersede nor are governed by the Financial Intelligence addenda. Where the two ever touch the same question, record it in `SPEC_RECONCILIATION.md` rather than assuming the higher number wins. |
| Architectural | [`addenda/`](addenda) 11–15 (newest FI set) | Canonical. Where these conflict with 5–10, these win. 11 and 15 are held privately. |
| Architectural | [`addenda/`](addenda) 5–10 | Canonical except where 11–15 clarify. 5 is held privately. |
| Architectural | [`addenda/`](addenda) 2–4 | **Superseded** by 5–10. Historical only. |
| Architectural | [`addenda/addendum_1_universal_agent.md`](addenda/addendum_1_universal_agent.md) | Base product (voice / universal agent). Unrelated to Financial Intelligence; historical. |
| Implementation | The code | Reconciled against the above before each increment. |

Every canonical document carries the same **Conflict Rule**: do not silently preserve two models —
stop, resolve, and record the resolution. [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) is where
those resolutions live, because the addenda themselves are marked do-not-edit.

## Verbatim versus maintained

A distinction worth knowing before editing anything.

- **Verbatim** — `addenda/` 1–14, 16–18 and 20–37 are unedited copies of supplied specifications. They are
  the authoritative source and are never changed; disagreements with them get recorded elsewhere.
- **Maintained** — `JARVIS_GAP_ANALYSIS.md`, `SPEC_RECONCILIATION.md`, `TIMING_CONSTANTS.md` and
  `organization.yaml` are this project's own records, edited as the design and the code move.
  Addendum 15 is maintained in the same sense, but privately.

---

## The maintained documents

| Document | What it holds |
|---|---|
| `JARVIS_CONSTITUTION.md` — **held privately** | The durable design authority: axioms, evidence discipline, governance, the direction from "My AI" toward JARVIS. |
| [`JARVIS_GAP_ANALYSIS.md`](JARVIS_GAP_ANALYSIS.md) | The running measurement of built-versus-constitution. Axiom scorecard, what is honored, what is absent, what closed and how it was verified. The most useful single file for understanding current state. |
| [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) | Where conflicts *between* specifications are resolved, and where owner decisions are recorded. Also lists what was declined, and why. |
| [`TIMING_CONSTANTS.md`](TIMING_CONSTANTS.md) | Every constant whose correctness depends on a rate, what that rate is, and whether it has been *measured*. Three real defects were found this way. |
| [`organization.yaml`](organization.yaml) | The organization as *implemented*, machine-readable. `tests/test_organization_model.py` asserts every claim in it against the code, so a role named here but not built — or built but not named — fails the suite. |
| [`model_registry.yaml`](model_registry.yaml) | Addendum 35's Model Registry and Requirement Profiles as *implemented*: the one configured engine, its measured facts (unmeasured fields carry no numbers), and a profile per model consumer. `tests/test_model_registry.py` asserts every claim against the code, and the pinned single-model routing decision trips the suite the day a second model is registered. |
| [`TASK_QUEUE.md`](TASK_QUEUE.md) | The Strategic Priority Register in paper form — the prioritized queue of work derived from the specifications, with Need/Want classification and status. Realizes addendum 31 §3 and addendum 32 §12 until a machine-readable register exists. |
| [`SECOND_FAILURE_DOMAIN.md`](SECOND_FAILURE_DOMAIN.md) | How this system stops depending on one machine: the data domain (done — encrypted backups to a synced folder, rehearsed) and the host domain (a runbook for the owner, since provisioning spends money). Its load-bearing step is the restore rehearsal, because §1.4 makes an untested restore a hypothesis. |
| [`INCIDENT_RESPONSE.md`](INCIDENT_RESPONSE.md) | What to actually do, in order, on suspected compromise: preserve evidence, stop the organization, revoke credentials, assess, restore, review. Written for this deployment's real shape, with its limits stated. |
| [`GOVERNANCE.md`](GOVERNANCE.md) | Which governing documents are held privately, why that is a split rather than an omission, and what remains public. |
| [`PUBLIC_PRIVATE_BOUNDARY.md`](PUBLIC_PRIVATE_BOUNDARY.md) | The rule the split is maintained under, so it stays a practice rather than a one-off migration. What moves, what must never move, and how a public comment references private reasoning by identifier. |
| [`MARKET_DATA_TAXONOMY.md`](MARKET_DATA_TAXONOMY.md) | What data an analysis organization can obtain from markets, organised by how it arrives in time rather than by asset class. |
| [`DOCUMENTATION_RECONCILIATION_PLAN.md`](DOCUMENTATION_RECONCILIATION_PLAN.md) | The 2026-08-16 inventory that produced the public/private split. A proposal, since partly executed — read it as the record of that decision, not as a description of current structure. |
| [`MY_AI_DESIGN_SPEC.md`](MY_AI_DESIGN_SPEC.md) | The original My AI product spec — permissioned action layer, data governance, client/server split. Governs `app/` accurately; stale as a description of the system as a whole. |

## The addenda

**Project Jarvis Gateway (16–18)** — a separate lineage, supplied 2026-08-17. Nothing in 16 or 17 is
built; 18 is built. These govern the external boundary and backend infrastructure, not the agent
organization.

| | |
|---|---|
| [16 — AI Communication Gateway Specification](addenda/addendum_16_gateway_specification.md) | The external communication boundary. One externally exposed service, voice-first phone client, Git as the durable artifact exchange, the Scoreboard for deferred discussion. |
| [17 — Super User Gateway Architecture](addenda/addendum_17_gateway_super_user_architecture.md) | Scopes Gateway v1 to a single Super User. Its §7–§9 add the Technology and Architecture monitoring function — how evidence that a component is becoming unsuitable becomes a structured recommendation. Calls itself "Addendum 1"; that is its number in the Gateway sequence, not this one. |
| [18 — Lifecycle-Managed Controller Initialization](addenda/addendum_18_controller_lifecycle_initialization.md) | Import-time side effects. **Already implemented** — see `SPEC_RECONCILIATION.md` §19 for the disposition and the two acceptance criteria deliberately not met. |

**Data and engine architecture (20)** — a third lineage, supplied 2026-08-18:
simulation, historical and live market data, reference data, and risk. Little of
it is built; [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) §30 records which
parts already exist under other names and which are genuinely absent.

| | |
|---|---|
| [20 — Simulation, Market Data and Core Engine Architecture](addenda/addendum_20_architecture_checkpoint.md) | The checkpoint baseline. Its §13 asks for a keep/modify/add/remove comparison against what is built; that comparison and the disposition are in [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) §30. |

**Day Zero (21–27)** — a fourth lineage, supplied 2026-08-21: the startup world.
Bootstrap order, the Reference Data Engine, the Market Data Simulation Engine
whose Version 1 mission is put-call parity arbitrage, and the options arbitrage
library that mission exists to teach. [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md)
§39 records what already existed under other names and what the lineage's build
increments added.

| | |
|---|---|
| [21 — Day Zero Bootstrap & Metadata Engine](addenda/addendum_21_day_zero_bootstrap_metadata_engine.md) | The startup sequence: Bootstrap → Controller → schema → Reference Data Engine → data world → wake agents. Lifecycle (Pre-Alpha/Alpha/Beta/Live) belongs to orchestration only. |
| 22 — Constitution & Governance checkpoint — **held privately** | The durable philosophical seed: rule of law, universal accountability, rights thresholds, dissent, due process, adaptive confidence. |
| [23 — Organization & Agent Architecture](addenda/addendum_23_organization_agent_architecture.md) | Who acts, advises, evaluates, governs, orchestrates: Controller, COO, Explorer, Speculator, Analyst, Evaluator, and the training loop. |
| [24 — Reference Data Engine (Specification 01)](addenda/addendum_24_reference_data_engine_specification.md) | The canonical reference-data engine spec: Asset Universe / Capability Set / Current Focus, Security Master, Assets table, ingestion, validation, fail-closed readiness. Governs 26 where they differ. |
| [25 — Market Data Simulation Engine (Specification 02)](addenda/addendum_25_market_data_simulation_engine_specification.md) | The training-world generator: option chains, skew generator, parity opportunity injection with genuine and trap variants, hidden ground truth, the evaluation loop. |
| [26 — Day Zero Reference Data Engine](addenda/addendum_26_day_zero_reference_data_engine.md) | Sibling of 24, less detailed; kept for the statements 24 lacks (dependency chain, Explorer's initial volatility-surface focus). |
| [27 — Full Options Arbitrage Library](addenda/addendum_27_options_arbitrage_library_specification.md) | ARB-001 through ARB-030, the executable-price discipline, cost model, A/B/C/D classification, and the pure-detector implementation contract. Mostly roadmap; ARB-001 is the first consumer. |

**Organizational Doctrine (28–33)** — a fifth lineage, supplied 2026-08-23: the
target organization. Six peer frameworks describing what MyAI is to become —
its defense, its resilience, how it changes itself, how it decides what to
pursue, how it governs itself, and the strategic doctrine underneath all of it.
Nearly everything here is roadmap; [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md)
§47 records what already exists under other names, what was adopted
immediately, and what is deferred with reasons. The work it generates is
queued in [`TASK_QUEUE.md`](TASK_QUEUE.md).

| | |
|---|---|
| [28 — Security Defense Framework](addenda/addendum_28_security_defense_framework.md) | The malicious-adversary division: zero trust, capability boundaries outside the model, the Tool Security Gateway, containment, Emergency Defense Mode, the security agent catalog, and the §32 minimum viable baseline. |
| [29 — Business Continuity Framework](addenda/addendum_29_business_continuity_framework.md) | Operating through disruption regardless of cause: service tiers, RPO/RTO, provider-neutral backup with tested restore, graceful degradation, clean-room recovery. Its §45 baseline is the lineage's most immediately implementable demand. |
| [30 — Department of Evolution v2.0](addenda/addendum_30_department_of_evolution.md) | How approved systemic change is trained, assimilated, certified, rolled out, and reversed. Draws the Strategy/Evolution boundary: Strategy decides what and why, Evolution decides how. Overlaps the addendum 13 training loop; §47 records the mapping. |
| [31 — Strategy Department](addenda/addendum_31_strategy_department.md) | What to pursue and in what order: Need/Want classification, GREEN→CRITICAL flags, the Strategic Priority Register, petitions, champions, commissions, Horizon Intelligence, Board sessions, Development Plans. |
| [32 — Governance Framework & Parliamentary System](addenda/addendum_32_governance_framework_parliamentary_system.md) | How the organization governs itself: civilian character, dual departmental leadership, two-tier democracy, committees, priority queues, Quick-Win and high-cost classification, verified constitutional implementation. |
| [33 — Strategic Principles](addenda/addendum_33_strategic_principles.md) | Constitutional-level doctrine addending 31: never become a dinosaur, strategy over brute force, blind-spot reviews, cooperation first with competition as tie-breaker, responsible growth, strategic humility. Directives SP1–SP17. |

**Organizational Doctrine, second set (34–37)** — the lineage's continuation, supplied
2026-08-25: the learning machinery. How the organization detects a need, debates it,
converts it into curriculum and Monte Carlo simulation, trains and certifies agents,
rolls the behavior out, and checks reality against the prediction — plus the
multi-LLM strategy and the optimization discipline that keep the whole thing
efficient. Nearly everything here is roadmap;
[`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) §60 records what already exists
under other names, the owner's priority decision, and what is deferred with
reasons. The work it generates is queued in [`TASK_QUEUE.md`](TASK_QUEUE.md).

| | |
|---|---|
| [34 — Training and Monte Carlo Simulation Framework](addenda/addendum_34_training_and_monte_carlo_simulation_framework.md) | The integrating loop: need → governance → directive → curriculum → Monte Carlo scenarios → training → certification → controlled rollout → lag-aware predicted-versus-actual review. Simulation as an evolving environment, not a question bank; collaboration as the primary training dimension; the nine-stage simulation maturity path. |
| [35 — Multi-LLM Enterprise Strategy](addenda/addendum_35_multi_llm_enterprise_strategy.md) | AGENT != MODEL. Model Registry, per-agent-class Model Requirement Profiles, cost-aware routing that never silently downgrades critical work, model-migration lifecycle, and collaboration quality as a model-fit criterion. |
| [36 — Department of Education](addenda/addendum_36_department_of_education.md) | Curriculum Architect and deliberately cheap trainers; versioned curricula; structured trainer feedback; simulation requests from curriculum needs; the Speculator curriculum as the worked example; collaboration as the universal top-priority competency. |
| [37 — Evolution: Continuous Optimization](addenda/addendum_37_evolution_continuous_optimization.md) | Optimization as a permanent sub-department of Evolution: measure, benchmark, evaluate agent-to-LLM fit and routing, recommend on evidence, change only through governance, compare predicted with observed. Directives O1–O9; collaboration as a non-negotiable constraint. |

**Financial Intelligence, third set (11–15)** — the current architecture.

| | |
|---|---|
| 11 — Agent-Driven Organizational Architecture — **held privately** | The organizational constitution. Roles, authority boundaries, lifecycle, Bob as CEO. |
| [12 — Consolidated Architecture Specification](addenda/addendum_12_consolidated_architecture_specification.md) | The integration spec; its §21 Pre-Alpha task list drives current work. |
| [13 — Training Agent Design](addenda/addendum_13_training_agent_design_specification.md) | Training, evaluation, reinforcement, knowledge preservation. |
| [14 — Alpha Acceptance Specification](addenda/addendum_14_alpha_acceptance_specification.md) | What must demonstrably work before Alpha. Origin of the UQI and agent self-awareness requirements. |
| 15 — Agent Rationality Monitoring — **held privately** | Behavioral health and sentinels. **Derived, not verbatim** — written from owner decisions in discussion. Nothing in it is built. |

**Organizational resilience (19)** — a later document in the same organizational
lineage, supplied 2026-08-18.

| | |
|---|---|
| 19 — Fault Tolerance and Organizational Resilience — **held privately** | Who is responsible for noticing that somebody stopped working, how a detected failure acquires an owner, and what recovery must reconcile before resuming. Its §18 asked for a review before implementation; the disposition and what was built are in [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) §28. |

**Financial Intelligence, second set (5–10)** — canonical except where the newer set clarifies.

| | |
|---|---|
| 5 — System Constitution and Development Principles — **held privately** | Development principles, including the Conflict Rule every canonical document carries. |
| [6 — Core Client/Server Agent Architecture](addenda/addendum_6_core_client_server_agent_architecture.md) | |
| [7 — Continuous Opportunity Detection and Analysis](addenda/addendum_7_continuous_opportunity_detection_and_analysis.md) | The IV-surface detector, peer analysis, grading. |
| [8 — Training, Simulation, Validation, Continuous Learning](addenda/addendum_8_training_simulation_validation_and_continuous_learning.md) | §4's test progression drives the graduation path. |
| [9 — On-Demand Portfolio Analysis (canonical)](addenda/addendum_9_on_demand_portfolio_analysis_canonical.md) | |
| [10 — Implementation Plan v1, First Real Slice](addenda/addendum_10_implementation_plan_v1_first_real_slice.md) | |

**Historical** — kept for provenance, not for guidance.

- [1 — Universal Agent](addenda/addendum_1_universal_agent.md) — the base product, unrelated to Financial Intelligence.
- [2](addenda/addendum_2_financial_intelligence_master_spec.md), [3](addenda/addendum_3_continuous_market_opportunity_detection.md), [4](addenda/addendum_4_on_demand_portfolio_analysis.md) — superseded by 5–10.

---

## Reading orders

**To understand the intent:** constitution → addendum 11 → addendum 12. The first two are private;
from this repository alone, `SPEC_RECONCILIATION.md` §2 carries the substance of what they settled,
and addendum 12 is public in full.

**To understand what exists:** gap analysis → `SPEC_RECONCILIATION.md` §2 (superseded statements) →
`organization.yaml` → the code.

**To pick up development:** gap analysis's closing recommendations → `SPEC_RECONCILIATION.md` §6 (open
conflicts) → `TIMING_CONSTANTS.md` if touching anything rate-dependent.

**To understand why something was *not* built:** `SPEC_RECONCILIATION.md` §4 (declined, with reasoning).
Several things in this system were deliberately left out, and that file says which and why.
