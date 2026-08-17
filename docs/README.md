# Design Documents

Everything governing this system's design, in one place. Twenty documents accumulated across several
design sessions; this index says what each one is, which govern which, and what order to read them in.

**Start here:** [`JARVIS_CONSTITUTION.md`](JARVIS_CONSTITUTION.md) for the principles,
[`JARVIS_GAP_ANALYSIS.md`](JARVIS_GAP_ANALYSIS.md) for what is actually built against them.

---

## Precedence

Documents disagree with each other, so the order matters. Higher layers win.

| Layer | Document | Authority |
|---|---|---|
| **Constitutional** | [`JARVIS_CONSTITUTION.md`](JARVIS_CONSTITUTION.md) | **Supreme.** Governs principles. Where an addendum conflicts, the constitution wins and the addendum is reconciled to it. |
| Architectural | [`addenda/`](addenda) 11–15 (newest set) | Canonical. Where these conflict with 5–10, these win. |
| Architectural | [`addenda/`](addenda) 5–10 | Canonical except where 11–15 clarify. |
| Architectural | [`addenda/`](addenda) 2–4 | **Superseded** by 5–10. Historical only. |
| Architectural | [`addenda/addendum_1_universal_agent.md`](addenda/addendum_1_universal_agent.md) | Base product (voice / universal agent). Unrelated to Financial Intelligence; historical. |
| Implementation | The code | Reconciled against the above before each increment. |

Every canonical document carries the same **Conflict Rule**: do not silently preserve two models —
stop, resolve, and record the resolution. [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) is where
those resolutions live, because the addenda themselves are marked do-not-edit.

## Verbatim versus maintained

A distinction worth knowing before editing anything.

- **Verbatim** — `addenda/` 1–14 are unedited copies of supplied specifications. They are the
  authoritative source and are never changed; disagreements with them get recorded elsewhere.
- **Maintained** — `JARVIS_GAP_ANALYSIS.md`, `SPEC_RECONCILIATION.md`, `TIMING_CONSTANTS.md`, and
  `addenda/addendum_15_agent_rationality_monitoring.md` are this project's own records, edited as the
  design and the code move.

---

## The maintained documents

| Document | What it holds |
|---|---|
| [`JARVIS_CONSTITUTION.md`](JARVIS_CONSTITUTION.md) | The durable design authority: axioms, evidence discipline, governance, the direction from "My AI" toward JARVIS. |
| [`JARVIS_GAP_ANALYSIS.md`](JARVIS_GAP_ANALYSIS.md) | The running measurement of built-versus-constitution. Axiom scorecard, what is honored, what is absent, what closed and how it was verified. The most useful single file for understanding current state. |
| [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) | Where conflicts *between* specifications are resolved, and where owner decisions are recorded. Also lists what was declined, and why. |
| [`TIMING_CONSTANTS.md`](TIMING_CONSTANTS.md) | Every constant whose correctness depends on a rate, what that rate is, and whether it has been *measured*. Three real defects were found this way. |
| [`MY_AI_DESIGN_SPEC.md`](MY_AI_DESIGN_SPEC.md) | The original My AI product spec — permissioned action layer, data governance, client/server split. |

## The addenda

**Financial Intelligence, third set (11–15)** — the current architecture.

| | |
|---|---|
| [11 — Agent-Driven Organizational Architecture](addenda/addendum_11_agent_driven_organizational_architecture.md) | The organizational constitution. Roles, authority boundaries, lifecycle, Bob as CEO. |
| [12 — Consolidated Architecture Specification](addenda/addendum_12_consolidated_architecture_specification.md) | The integration spec; its §21 Pre-Alpha task list drives current work. |
| [13 — Training Agent Design](addenda/addendum_13_training_agent_design_specification.md) | Training, evaluation, reinforcement, knowledge preservation. |
| [14 — Alpha Acceptance Specification](addenda/addendum_14_alpha_acceptance_specification.md) | What must demonstrably work before Alpha. Origin of the UQI and agent self-awareness requirements. |
| [15 — Agent Rationality Monitoring](addenda/addendum_15_agent_rationality_monitoring.md) | Behavioral health and sentinels. **Derived, not verbatim** — written from owner decisions in discussion. Nothing in it is built. |

**Financial Intelligence, second set (5–10)** — canonical except where the newer set clarifies.

| | |
|---|---|
| [5 — System Constitution and Development Principles](addenda/addendum_5_system_constitution_and_development_principles.md) | |
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

**To understand the intent:** constitution → addendum 11 → addendum 12.

**To understand what exists:** gap analysis → `SPEC_RECONCILIATION.md` §2 (superseded statements) → the
code.

**To pick up development:** gap analysis's closing recommendations → `SPEC_RECONCILIATION.md` §6 (open
conflicts) → `TIMING_CONSTANTS.md` if touching anything rate-dependent.

**To understand why something was *not* built:** `SPEC_RECONCILIATION.md` §4 (declined, with reasoning).
Several things in this system were deliberately left out, and that file says which and why.
