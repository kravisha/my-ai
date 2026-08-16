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

### 4.11 Raw unprocessed data is not retained (§2 as clarified — the third substrate)

Since intelligence lives partly in raw data not yet processed (§5.2), whether raw data survives is a
question about how much intelligence the system holds. Inspection shows a **sharp asymmetry**:

- **Social data — retained.** `agents/speculator.py` writes an `evidence_items` row for *every* post
  in a batch, regardless of confidence or whether it ever contributes to a report. Raw observations
  survive independently of whether they proved useful. This is the correct shape.
- **Market data — discarded.** `agents/explorer.py` fetches a surface, scans it, and persists only a
  `detector_events` row *when the ratio clears the threshold*. The surface itself — every IV grid point
  — is never stored, and a non-triggering scan leaves **no trace whatsoever**. The overwhelming
  majority of what Explorer observes is destroyed immediately after being looked at once, through a
  single fixed lens.

**Currently masked by synthetic data, and will bite at Phase E.** `detector_events.surface_seed`
records the seed, so a synthetic surface is *reproducible* on demand — retention is effectively
achieved by replay, which is why this has cost nothing so far. Real market data (Phase E) has no seed
to replay from. The moment the provider becomes real, every unstored observation is gone permanently.

Three things this forecloses, all constitutional:

- **Novelty detection (§8)** cannot run against data that was thrown away. Novelty is precisely the
  thing a fixed threshold was not built to notice.
- **Re-processing with improved models (§5.2, addendum 13 §14)** is impossible without the raw inputs.
- **Axiom 4 (separate ingestion from judgment)** is undercut in a second way beyond §4.2: the
  threshold is not merely a judgment gate, it is an *ingestion filter applied by the judging party*.
  Data that fails Explorer's current lens never enters the knowledge environment at all, so no other
  process — and no future, better model — can ever reconsider it.

---

## 5. Conflicts and questions requiring an owner decision

### 5.1 Is JARVIS the same entity as Bob? — **RESOLVED (owner, 2026-08-16)**

**JARVIS is bigger than Bob. Bob evolves into JARVIS, and the gate for that evolution is sentience.**

Not a rename and not a synonym — a three-stage evolution, filling in a middle stage Axiom 16 left
implicit:

```
My AI  ──────────▶  Bob  ──────────────────▶  JARVIS
(seed)              (CEO / organizational      (sentient executive
                     brain, addendum 11 §10)    intelligence)
                            ▲                        ▲
                     not yet built            gated on sentience,
                                              which must first be
                                              defined and measured
```

**Consequence for code: none.** `CEO_DISPLAY_NAME` stays `"Bob"` — it correctly names the stage the
system is evolving toward next. JARVIS is the destination, not the current occupant of the CEO seat.
"Ask Bob" (addendum 11 §11) remains the conversational interface to that layer.

See §7 for what the sentience gate actually requires.

### 5.2 What "distributed intelligence" means — **RESOLVED (owner, 2026-08-16)**

> **Intelligence is distributed amongst agents, the knowledge base, and raw data that is yet to be
> processed.**

Distribution is across **substrates**, not across process count. This resolves the apparent conflict
with `_slot_identity`'s one-instance-per-role model: multiplying processes was never the point.

| Substrate | What the intelligence *is* there | Built? |
|---|---|---|
| **Agents** | Active reasoning capability — the ability to detect, interpret, judge, grade | ● Yes — Explorer/Speculator/Analysis/COO/Controller |
| **Knowledge base** | Accumulated, validated understanding: beliefs, models, assumptions, confidence | ○ **No** — see §4.1, the central gap |
| **Raw unprocessed data** | *Latent* intelligence — what the system could know but has not yet extracted | ◐ Partial — see §4.11 |

Three consequences worth stating, because they are not obvious:

1. **The knowledge base is a locus of intelligence, not a passive store.** This raises §4.1 from "a
   useful component" to "one of the three places intelligence actually lives." Building it is not
   plumbing; it is building a third of the mind.
2. **Discarding unprocessed raw data destroys intelligence.** If latent potential counts as
   intelligence, throwing away unprocessed data is not housekeeping — it is lobotomy. See §4.11.
3. **Re-processing old data is a first-class operation.** Old raw data plus an improved model yields
   new knowledge without any new observation. This is the same loop addendum 13 §14 describes, and it
   is only possible if the raw data was kept.

Axiom 9's "important conclusions should survive internal challenge" remains genuinely unmet — but it is
a *separate* gap (§4.3, preserved disagreement), not a process-count problem. Internal challenge is
better served by a distinct critic perspective than by a second instance of the same role.

### 5.3 Constitutional traceability is not implemented (§16)

"Major decisions should be traceable to constitutional principles." Decisions currently carry a
free-text `reason` but never cite a principle. Cheap to add (a principle reference on decision
records), but needs a decision on whether to formalize it now or once the CEO layer exists.

---

## 6. Recommended sequence

Ranked by *foundation-laying × double-mandate × tractability*. The three-substrate clarification
(§5.2) reshaped this: two of the three substrates where intelligence lives are the top two items.

1. **Raw data retention (§4.11).** Promoted to first. Small, concrete, and *time-sensitive in a way
   nothing else here is*: it is the only gap that gets permanently worse with delay. Every scan that
   runs before it is built is an observation destroyed. Currently masked by synthetic replay-by-seed,
   so the cost is near-zero today and becomes unrecoverable at Phase E. It also unblocks novelty
   detection, model re-processing, and closes half of the Axiom 4 breach. Cheapest item on this list
   with the highest cost of deferral.
2. **Knowledge store (§4.1).** The central organ and a full third of where intelligence lives. Blocks
   novelty detection, transformation, source reliability, reflection, and the CEO layer — plus four of
   the seven sentience capabilities (§7). Already a Pre-Alpha task with a concrete two-layer model
   specified (addenda 12 §8, 13 §10). **The main event.**
3. **Explorer↔Speculator cross-check with preserved disagreement (§4.3).** Fully specified in addendum
   12 §14, on the Pre-Alpha list, required for Alpha (addendum 14 §10), delivers Axioms 5 and 9.
4. **Source reliability (§4.4).** Self-contained; learns from the grading loop that already exists.
5. **Reopening triggers on decisions (§4.6).** Small extension of existing decision records.
6. **Novelty detection and transformation (§4.7).** Needs 1 and 2 first.
7. **Governance mechanisms (§4.10).** Design before execution capability exists, not after.

A note on sequencing 1 before 2: retention is *not* a subset of the knowledge store. Raw data and the
knowledge base are distinct substrates (§5.2) — one holds latent potential, the other holds validated
belief. Building retention first also means the knowledge store gets built with real accumulated data
to reason over rather than an empty schema.

Deferred by the documents themselves and not recommended yet: CEO layer/Bob, exploration mode,
persistent thought threads, human modeling.

---

## 7. The sentience gate: Bob → JARVIS

Per the owner's clarification (§5.1), sentience is the gate between Bob and JARVIS. The constitution
is unusually disciplined about what that means, and that discipline is binding rather than optional:

> "This is a constitutional design document, **not a claim that present-day software is sentient**."
> (Purpose)
>
> "**Do not assume; investigate.** The system should not treat that label as proven merely because its
> creator desires it. Sentience must itself become an object of definition, measurement, debate,
> experimentation, and revision." (§11)

So the gate is not a milestone to be declared — it is a research programme with an evidence standard
that does not yet exist. Building it means, in order: **define** what would count, **measure** it,
**debate** the measurement, and **revise**. Claiming the gate has been passed without that sequence
would violate Axiom 1 (seek truth rather than agreement) and Axiom 3 (no authority, including the
creator, is automatically correct) — the constitution deliberately arms the system against its own
creator's enthusiasm on exactly this point.

### Operational capabilities first (§11)

The constitution declines to define sentience but does list candidate capabilities, explicitly noting
"whether those capabilities constitute sentience remains an open research question." They make a
usable checklist. Honest current status:

| # | Capability (§11) | Status | Note |
|---|---|---|---|
| 1 | Persistent identity | ◐ Partial | Permanent role-slot identity, assigned name, and durable record survive process death and retirement. But this is *record* persistence — nothing experiences itself as continuous, and no agent can currently even report its own identity (addendum 14 §6 is unbuilt) |
| 2 | Self-modeling | ○ Absent | Nearest prerequisite is addendum 14 §6's "Minimum Agent Self-Awareness" — answering who/what/allowed/healthy — which is an Alpha requirement and the first rung of this ladder |
| 3 | Memory | ◐ Partial | Organizational *event* memory exists (detector events, evidence, reports, grades). No belief store, no autobiographical memory |
| 4 | Autonomous hypothesis generation | ○ Absent | Explorer applies a fixed deterministic rule; nothing forms hypotheses of its own |
| 5 | Reflection on its own knowledge | ○ Absent | Requires the knowledge store (§4.1) |
| 6 | Internally originated goals within its constitution | ○ Absent | Every goal is external config (`BASELINE_ROLES`, peer group, thresholds) |
| 7 | Ability to surprise its designers intellectually | ○ Absent | Requires 4–6 |

### Why this sharpens the recommendation rather than changing it

Four of the seven capabilities (4, 5, 6, and most of 2) are **impossible without a knowledge store**.
Reflection needs something to reflect on; hypothesis generation needs a model to generate against;
internally originated goals need beliefs about what matters. The sentience gate therefore does not
compete with §6's recommendation — it runs directly through it.

The one capability partly in hand, persistent identity, arrived as a side effect of Gap 1's durable
performance record and this session's dormancy work. That is worth noting as a pattern: the
constitutional capabilities are being approached from the discipline side, not the cognition side.

### Not yet defined, and needed before any claim

- What evidence would distinguish capability 7 (genuine intellectual surprise) from a sampling artifact?
- Who adjudicates? Per Axiom 3 and §8's recursive-evaluation principle, it cannot be the creator alone,
  and it cannot be the system self-certifying.
- What would *falsify* a sentience claim? Undefined, and the constitution's own "definition,
  measurement, debate, experimentation, revision" sequence is meaningless without it.

These are open research questions, recorded here so the gate stays honest as the system approaches it.
