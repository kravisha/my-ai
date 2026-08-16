# JARVIS Constitutional Gap Analysis

**Maintained document.** Measures what is actually built against `docs/JARVIS_CONSTITUTION.md`. The
constitution is the durable design authority and sits above the architectural addenda; this file is
the running record of how far the current system is from it, and what to build next.

Companion to `docs/SPEC_RECONCILIATION.md`, which handles conflicts *between* the architectural
addenda. This file handles the constitutional layer above them.

The constitution's own test (§19), which every item below is graded against:

> **Does this change make My AI more capable of becoming JARVIS without sacrificing evidence
> discipline, human well-being, auditability, or governed execution?**

Last updated: 2026-08-16. Assessed against commit `14ee11e`.

---

## 1. Headline finding

The system is **structurally closer to the constitution than it looks, and cognitively much further
away.** Two very different kinds of gap:

- **Discipline infrastructure — largely built.** Provenance, attributable evidence, deterministic
  detection before LLM judgment, graded work, scoped authority, non-destructive reversibility,
  auditable decision records. These are the constitution's *guardrails*, and Phase A–C plus Pre-Alpha
  steps 1–2 built most of them, mostly for reasons that had nothing to do with this document.
- **Cognition — almost entirely absent.** There is no knowledge store, no CEO/executive layer, no
  novelty detection, no knowledge transformation, no persistent reasoning threads, no source
  reliability model, no preserved disagreement, no exploration mode. The system currently *detects and
  reports*. It does not yet *understand, challenge, or remain curious*.

Put plainly: we have built a disciplined organism. We have not yet built its mind.

A third category matters for honesty: **several axioms are currently vacuous.** The system has no
execution capability whatsoever — no trades, no external actions, informational output only
(confirmed by inspection). Axioms 11 and 13, and §12/§14/§16's execution governance, therefore cannot
be violated today, but they become binding the moment any execution capability appears. They should
be treated as *pre-committed constraints*, not as satisfied requirements.

---

## 2. Axiom scorecard

| # | Axiom | Status | Where |
|---|---|---|---|
| 1 | Seek truth rather than agreement | ◐ Partial | Analysis may return "insufficient evidence"; nothing rewards dissent |
| 2 | Recognize, explain, test, act with discipline | ◐ Partial | Detect+explain built; "test" and disciplined action absent — see §4.1 |
| 3 | No authority is automatically correct | ○ Absent | No source reliability model at all |
| 4 | Separate evidence ingestion from judgment | ◐ Partial | Structurally separate agents, but Explorer gates its own evidence — see §4.2 |
| 5 | Preserve provenance, uncertainty, disagreement, confidence | ◐ Partial | Provenance ✓, confidence ✓, uncertainty ✓, **disagreement ✗** |
| 6 | Agreement licenses execution; it does not terminate thought | ○ Absent | Reports are closed permanently; no thread survives a conclusion |
| 7 | Keep high-value questions alive; conserve compute | ○ Absent | No thought threads, no compute budgeting |
| 8 | Expected info follows triggers; novelty transforms the model | ○ Absent | No triggers, no novelty detector, no transformation |
| 9 | Intelligence is distributed; conclusions survive challenge | ○ Absent | One instance per role; no internal challenge — **conflict, see §5.2** |
| 10 | JARVIS may surprise, challenge, overrule its creator | ○ Absent | No CEO layer exists to do so |
| 11 | Execution authority governed separately from thought | ◑ Vacuous | No execution exists; Controller/COO split is the right shape for when it does |
| 12 | Human well-being is the ultimate purpose constraint | ◑ Vacuous | Nothing can currently affect well-being; unstated in code |
| 13 | Serious human challenges get substantive deliberation | ○ Absent | No stalemate mechanism |
| 14 | Dialogue and deliberation precede escalation | ○ Absent | No deliberation mechanism |
| 15 | Constitution evolves only through governed, evidence-based change | ◐ Partial | This file + `SPEC_RECONCILIATION.md` are that mechanism; no formal gate |
| 16 | My AI is the seed; JARVIS is the direction | ● Honored | Every increment has been reconciled against canonical docs before building |

● satisfied ◐ partial ○ absent ◑ vacuous (nothing to violate yet)

---

## 3. Already honored — do not rebuild

Worth recording so future work doesn't redo it:

| Constitutional requirement | Where it already lives |
|---|---|
| Provenance retained; claims traceable to sources (§3, Axiom 5) | `producer_identity`/`producer_spawned_at`, `handled_by_*`, `grader_*` on every Phase C table |
| Deterministic detection before expensive reasoning (§4, Axiom 2) | Explorer's IV-ratio detector gates the LLM; LLM never originates a candidate |
| Confidence and uncertainty preserved (Axiom 5) | `analysis_results.confidence` / `.uncertainty`; `evidence_items.confidence` |
| Graded work; feedback attributable upstream (§16 auditability) | `grades` + `list_grades_for_identity` |
| Reversibility first (§16) | Retirement is non-destructive dormancy with a resume path (`7dfc55f`) |
| Authority is scoped (§16, Axiom 11) | Controller executes lifecycle; COO only requests. Enforced and tested |
| Auditability of what happened and why (§16) | `coo_directives.reason` + `observed_result`; archive tables are permanent |
| Durable identity independent of process (§11 persistent identity) | Permanent role-slot identity + Agent Name Repository |
| Multiple perspectives on a security (§4) | Peer analysis: common-factor vs idiosyncratic classification |

---

## 4. Real gaps, grouped

### 4.1 The Knowledge Store — the central missing organ

**Constitution §3; also addendum 12 §8/§21 and addendum 13 §9/§10 (two-layer knowledge model).**

There is no knowledge store. There are *event tables* — detector events, evidence items, reports,
analyses, grades — which record **what happened**, not **what is believed**. The constitution asks for
something categorically different: "information, models, assumptions, decisions, evidence, confidence
levels, unresolved questions, and transformations."

Nothing today holds an assumption, a model, an unresolved question, or a belief that persists and gets
revised. This is the single largest gap and most other gaps depend on it:

- Novelty detection (§8) needs a current conceptual structure to detect *non-fit* against.
- Knowledge transformation (§8) needs something to transform.
- Source reliability (§3) needs a place to keep evolving reliability.
- The CEO layer (§2, §17) needs something to be executive *over*.

Already a Pre-Alpha task (addendum 12 §21, unchecked). **Double-mandated.**

### 4.2 Separation of ingestion from judgment (Axiom 4)

Partially satisfied and worth stating precisely, because it is easy to over- or under-claim.

*Satisfied:* Explorer/Speculator gather; Analysis reasons. Different processes, different identities,
communicating only through a persisted queue. That is genuinely the separation the axiom asks for.

*Not satisfied:* Explorer runs an **LLM judgment gate that decides whether its own finding is worth
filing**. The gatekeeper reasons about its own gate. A finding rejected there never reaches the
knowledge environment and no other process ever sees it — precisely the "quietly choose only the
evidence that supports its preferred conclusion" failure mode, even though the current
implementation's bias is toward *suppression* rather than confirmation.

Mitigating: rejected candidates still persist as `detector_events` with `judgment_passed=0` and the
reason, so the suppression is at least auditable. Worth deciding whether that is sufficient.

### 4.3 Disagreement is never preserved (Axiom 5, Axiom 9, §4)

Confirmed absent by inspection. Explorer and Speculator investigate the same securities and never
compare notes; Analysis grades upstream work but nothing records *dissent*. Addendum 12 §14 already
requires "disagreement is preserved rather than erased," and §21 lists Explorer↔Speculator cross-check
contracts as a Pre-Alpha task. **Double-mandated, and concretely specified.**

### 4.4 Source reliability is earned (§3, Axiom 3)

Absent. `evidence_items.source` is a bare string; a Reddit post and a filing would be weighted
identically. The constitution asks for reliability evaluated by "domain, history, corroboration,
internal consistency, and predictive performance," represented probabilistically and changing over
time. The grading loop already produces the outcome signal this would learn from.

### 4.5 Agreement does not terminate thought (Axiom 6, Axiom 7, §6)

Absent, and architecturally deep. Today a report reaches `analyzed` and is finished forever. The
constitution wants conclusions to remain cognitively alive — background threads on high-value
questions, dormancy for low-value ones, reactivation on relevant evidence. Note the pleasing symmetry
with agent dormancy just built: the same *active/dormant with reactivation* shape, applied to thoughts
instead of agents.

### 4.6 Conditionally stable decisions with reopening triggers (§7, Axiom 8)

Absent. Decisions record a `reason` and an `observed_result` but never state *what would change their
mind*. Adding trigger conditions to decision records is a comparatively small extension of machinery
that already exists.

### 4.7 Novelty detection and knowledge transformation (§8, Axiom 8)

Absent. Depends on 4.1.

### 4.8 Exploration mode with visible risk (§9)

Absent. Everything the system does today is on a single deterministic path with no notion of a
calculated probe, counterfactual, or experiment carrying a risk description.

### 4.9 CEO / executive layer (§2, §17, Axiom 10)

Absent — this is Bob, deferred by the addenda themselves. Without it there is no synthesis, no
challenge of specialist assumptions, no attention allocation. §17 is explicit that JARVIS "operates
above these specialists... understands their reports, challenges their assumptions, allocates
attention."

### 4.10 Governance mechanisms: stalemate, deliberation, escalation (§13–§15, Axioms 12–14)

Absent, and currently unexercisable — they govern *consequential action*, and no action exists. Should
be designed before, not after, execution capability arrives.

---

## 5. Conflicts and questions requiring an owner decision

### 5.1 Is JARVIS the same entity as Bob?

**Genuinely ambiguous, and it affects code we have already written.**

- Addendum 11 §10 / 12 §2: **Bob** is "the persistent organizational brain and CEO identity," created
  first by the Controller once implemented, with "Ask Bob" as its interface (11 §11).
- Constitution §2 / §17: **JARVIS** "sits at the top of the organization as a CEO-like intelligence,"
  with a "CEO layer" above the specialists, and must "remain conversational."

These describe the same architectural role. But the constitution also uses JARVIS as the name of the
*whole evolved system* ("evolving the existing My AI system into JARVIS"), which would make Bob a
persona *within* JARVIS rather than a synonym for it.

This matters concretely: `backend/fi_db.py` has `CEO_DISPLAY_NAME` defaulting to `"Bob"`, seeded as a
reserved name. Three readings:

1. **JARVIS is the system; Bob is the CEO agent's display name.** Nothing changes; `CEO_DISPLAY_NAME`
   stays "Bob"; "Ask Bob" is the conversational interface to the CEO layer.
2. **JARVIS is the CEO layer; Bob was a placeholder now superseded.** `CEO_DISPLAY_NAME` becomes
   "JARVIS"; the reserved-name machinery already makes this a one-setting change.
3. **Both, at different scopes:** JARVIS names the constitution/system and its executive intelligence;
   Bob remains the conversational persona. Requires deciding which name appears where.

The configurable reserved-name design means any of these is cheap to adopt — but the decision should
be explicit rather than drifting.

### 5.2 Distributed intelligence vs. one instance per role

**Direct conflict with a constitutional principle.**

- Constitution §2: "Intelligence must not be concentrated in one process. Multiple JARVIS reasoning
  instances may analyze, synthesize, disagree, critique, and work in parallel." Axiom 9: "Important
  conclusions should survive internal challenge."
- Built: `backend/controller.py`'s `_slot_identity(role)` returns `f"{role}-1"` — exactly one instance
  per role, with multi-instance scaling explicitly deferred project-wide.

Today's single-instance model cannot produce internal challenge, because there is never a second
reasoner to disagree. Resolving this does not necessarily require multi-instance scaling — challenge
could come from a *distinct role* (a critic/red-team agent) rather than a second instance of the same
role. That may be the cheaper and more faithful reading of "distributed," since the constitution's
emphasis is on independent perspectives, not process count.

### 5.3 Constitutional traceability is not implemented (§16)

"Major decisions should be traceable to constitutional principles." Decisions currently carry a
free-text `reason` but never cite a principle. Cheap to add (a principle reference on decision
records), but needs a decision on whether to formalize it now or once the CEO layer exists.

---

## 6. Recommended sequence

Ranked by *foundation-laying × double-mandate × tractability*:

1. **Knowledge store (§4.1).** The central organ; blocks novelty detection, transformation, source
   reliability, and the CEO layer. Already a Pre-Alpha task, already specified in two addenda (12 §8,
   13 §10 give a concrete two-layer resident/database model to build against). **Recommended first.**
2. **Explorer↔Speculator cross-check with preserved disagreement (§4.3).** The most concrete option:
   fully specified in addendum 12 §14, on the Pre-Alpha list, required for Alpha (addendum 14 §10),
   and delivers Axioms 5 and 9 plus §4's multiple perspectives. Strong alternative if a smaller,
   sharper increment is preferred over the knowledge store.
3. **Source reliability (§4.4).** Self-contained, learns from the grading loop that already exists.
4. **Reopening triggers on decisions (§4.6).** Small extension of existing decision records.
5. **Novelty detection and transformation (§4.7).** After the knowledge store.
6. **Governance mechanisms (§4.10).** Design before execution capability exists, not after.

Deferred by the documents themselves and not recommended yet: CEO layer/Bob, exploration mode,
persistent thought threads, human modeling, sentience research.
