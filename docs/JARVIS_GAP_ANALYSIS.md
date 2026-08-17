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

### 1.1 What counts as intelligence — the core distinction

**Owner clarification, 2026-08-16.** This governs everything below and corrects an earlier version of
this document that had it wrong:

> Not all data is intelligence. **Only intelligence needs to be preserved; data does not.** Intelligence
> is *extracted from* data. Intelligence has an expiry date — it depends on market conditions, and when
> conditions change, intelligence changes. Intelligence is about **defining how to look at things,
> using pattern recognition as the key guiding principle to differentiate things.** Knowledge retention
> is imperative; data retention is not imperative and is done on an as-possible basis.

Three consequences, each of which changes a conclusion elsewhere in this file:

**1. Intelligence is the lens, not the observation.** The IV surface is data. A detected anomaly is an
observation. The *threshold, neighborhood definition, and peer-grouping that decide what counts as an
anomaly at all* — those are the intelligence. So is a validated lesson about when such a signal is
misleading. This sharpens what the knowledge store (§4.1) is for: it holds **ways of seeing**, not
piles of facts.

**2. Intelligence expires; data has no preservation claim.** Since a lens is only valid under the
market conditions it was derived for, intelligence carries validity conditions and goes stale. Data,
by contrast, has served its purpose once its intelligence is extracted. This reverses the earlier
recommendation to prioritize raw-data retention — see §4.11.

**3. Reconciling with "intelligence is distributed amongst agents, knowledge base, and raw data yet to
be processed" (§5.2).** No contradiction: unprocessed data holds intelligence in *latent* form. It is a
transient **source**, not a store. Distribution describes where intelligence can be *found*; the
preservation obligation attaches to the **extract**, not the source.

One narrow exception, recorded so it is not lost: §16 auditability requires preserving "sufficient logs
to reconstruct what information was available" at decision time. That is a claim about *provenance and
reference*, satisfiable by recording what was seen — not a mandate for bulk retention. Likewise,
regression fixtures (addendum 8 §5, 13 §14) need reproducible inputs, which for seeded generation means
preserving the **seed**, not the data.

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

> **CLOSED (2026-08-16).** Explorer and Speculator now investigate independently, exchange structured
> questions through `cross_check_requests`, and hand both findings to Analysis unreconciled. Verified
> against a real running backend; see the closing note.

Was: Explorer and Speculator investigated the same securities and never compared notes; Analysis
graded upstream work but nothing recorded *dissent*. Addendum 12 §14 requires "disagreement is
preserved rather than erased," and §21 lists Explorer↔Speculator cross-check contracts as a Pre-Alpha
task. **Double-mandated, and concretely specified.**

#### How it was closed

The prerequisite was the same one regime detection had. The synthetic social stream drew posts
uniformly at random per security with no reference to whether that security's surface was dislocated,
so chatter about an anomalous name was statistically identical to chatter about a flat one.
Corroboration was a question the fixture could not answer. Narratives now control what posts say, how
many arrive, and how many distinct authors write them, as three independent knobs — deliberately set
so **no single frame gets the right answer**, since a fixture where one signal suffices proves
nothing.

Two design decisions carried the increment:

- **Neither discovery agent judges whether the findings agree.** Explorer reports a ratio; Speculator
  reports what the crowd appears to be saying and how broadly it is sourced. Outcomes are
  `evidence` / `no_evidence` / `unanswered`, never `corroborated` / `contradicted`. Compatibility is a
  reasoning judgment and Analysis is the only role that reasons, so its context presents two
  unreconciled claims. A context that said "corroborated" would have made the decision upstream in a
  procedural agent and hidden the evidence against it.
- **Speculator gained one small LLM call.** This reverses a decision made when it had nothing to
  judge. A message board is a verbal medium and post counts invert the answer: the contradicting
  stream produces 26 posts against the corroborating stream's 6, so ranking by volume promotes exactly
  the wrong lead. Counting kept the job language cannot do — separating a crowd from three accounts
  posting repeatedly, which is §13's "coordinated noise" and "popularity without substance."

#### Verified end to end

Against a real backend with six live agents, cross-checks ran in **both** directions and correctly
separated all three cases from ground truth the system was never given:

| Security | Ground truth | Stance read | Distinct authors | Posts/author |
|---|---|---|---|---|
| SYN1 | corroborating | supports | 15 | 1.0 |
| SYN2 | contradicting | undercuts | 9 | 1.0 |
| SYN3 | coordinated | unclear | 3 | 5.67 |

The stance read caught the coordination unaided — "near-duplicate hype phrases repeated with little
variation, suggesting coordinated or low-diversity posting rather than broad organic attention" — so
both frames agreed independently rather than one carrying the result.

And the dissent reached the reasoning. Analysis discounted its own detector on contextual grounds:
on SYN2 (ratio 2.14) it concluded "social chatter attributes the move to index rebalancing, a hedge
roll, or a fat-finger print rather than directional positioning," landing at confidence 0.30. Before
this increment that ratio reached Analysis with nothing to weigh it against.

#### Still open

- **The escalation rule is not yet an intelligence artifact.** §14 wants it "configurable" and
  "calibrated through testing rather than permanently hard-coded" — which is the definition of a lens.
  Deliberately not built as an unconsumed artifact ahead of having something to calibrate against.
- **Speculator's evidence window is process-local.** A freshly respawned Speculator answers
  `no_evidence` until it has observed a cycle or two. Honest — it genuinely has not looked yet — but
  it means an early cross-check can under-report evidence that exists in the database. Observed live:
  the first SYN1 cross-check saw one post and the fifth saw fifteen.
- **Stance accuracy is unvalidated and cannot be validated here.** The templates were authored
  alongside the classifier, so any score against them measures nothing. It gets tested against real
  text or not at all.

### 4.3b Analysis is the throughput bottleneck at ten securities — *newly measured*

Not a constitutional gap, but a capacity fact discovered while completing addendum 8 §4 step 3, and
recorded here so the next increment is chosen on evidence rather than guesswork.

At ten securities across three peer groups, against a real running backend:

| | |
|---|---|
| Cross-checks | 17 opened, **17 consumed, 0 pending, 0 timed out** — the layer scales fine |
| Reports | **13 pending against 9 analysed**, steady at 13 across a minute |
| Regime | all 10 securities observed |
| Agents | all six healthy, no duplicate spawns |

**The backlog is bounded, not a leak.** `has_pending_report` dedups per producer *and* security, so
the ceiling is one pending report per producer per security — 20 with two producers and ten
securities. Observed 13 (explorer 4, speculator 9), holding steady rather than climbing. Nothing
accumulates without limit.

What it does mean is that **detection outpaces reasoning**. Explorer and Speculator are cheap per
security; Analysis spends one deep-reasoning call per report and handles one per cycle, so at ten
securities the latency from detection to analysis grows and some leads wait a long time. This is
precisely addendum 8 §4 **step 7** ("resource and scaling behavior under starvation and backlog"),
which the progression puts *after* step 3 — so it is the next step in that sequence rather than a
defect in this one.

Worth noting what the fix is *not*: draining more reports per Analysis cycle changes batching, not
throughput, since each still costs a model call. The real options are multiple Analysis instances -
deferred project-wide, since `_slot_identity` and `BASELINE_ROLES` both hard-assume one identity per
role - or prioritising which reports get analysed rather than taking them FIFO. The second is
cheaper and arguably more interesting: it would make "which lead is worth the compute" an explicit
judgment rather than an accident of arrival order.

### 4.4 Source reliability is earned (§3, Axiom 3)

> **CLOSED (2026-08-17).** Sources now earn a standing from how the reports built on their evidence
> were graded. Verified against a real backend: the ordering the system inferred matches ground truth
> it was never given.

Was: `evidence_items.source` was a bare string, so a Reddit post and a filing weighed identically.

#### The prerequisite, again

The fixture had **one** source (`SOURCES = ("reddit",)`), so a reliability model would have been a
scorer with nothing to discriminate between — the same trap the market regime and the social
narratives each hit. Three sources now say genuinely different things: `filing_feed` makes specific
checkable claims, `reddit` is the mixed retail stream, `pump_channel` is confident and content-free.
The difference is in what they *say*, never in a quality label, so the system has to infer standing
rather than read it.

#### Two refusals carry the design

- **Earned, never assigned.** No source is seeded with a prior. Writing "filings are trustworthy,
  forums are not" would assert exactly the authority Axiom 3 denies, and would make the model
  untestable — it would be reporting its own seed back. A source starts unknown, the same way a lens
  earns its regime baseline by being observed working.
- **Labelled, never filtered.** A source with a poor standing still has its evidence collected, still
  reaches Analysis, and is still weighed there. This is the property the whole design turns on: a
  reliability model that gated collection could never learn it was wrong, because a badly-rated
  source would stop contributing evidence, stop accumulating grades, and stay badly rated forever on
  a record that stopped growing. Analysis is told the standing *and* told explicitly not to treat a
  low one as grounds to ignore an item.

Standings are recomputed by COO rather than by Speculator, for the same reason lens health is COO's:
the producer of evidence must not judge its own sources (addendum 11 §8). Recomputed from the full
grade history rather than folded in incrementally, so a standing is exactly reproducible from the
record rather than dependent on update order.

#### Verified

Against a real backend, after 23 grades:

| Source | Graded contributions | Mean evidence quality | Stated |
|---|---|---|---|
| `filing_feed` | 17 | **0.429** | yes |
| `reddit` | 6 | **0.420** | yes |
| `pump_channel` | 6 | **0.250** | yes |

The ordering is correct against ground truth the system was never shown. Note the honest shape of it:
`pump_channel` separates clearly, but `filing_feed` and `reddit` are within 0.009 of each other — the
model distinguishes *content-free hype* from *substantive claims* confidently, and does not yet
distinguish filings from good forum posts. That is a real limit, not a rounding artifact.

#### Still open

- **The standing is descriptive, not yet consequential.** Analysis is told; nothing else changes. That
  is deliberate for now, but the constitution's "predictive performance" component would want a
  source's standing to inform *what gets collected next*, and doing that safely needs the
  never-suppress property preserved — probably by sampling low-standing sources rather than dropping
  them.
- **Reliability is global, not per-domain.** §3 asks for reliability by *domain*; a source good on
  filings and useless on rumour currently gets one number.
- **Thin separation between the two legitimate sources**, as above.

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

### 4.11 The system's intelligence is static, externally imposed, and cannot expire

> **PARTIALLY CLOSED (2026-08-16).** The two detection thresholds are now intelligence artifacts with
> provenance, rationale, and validity conditions; grades attribute back to the lens that produced the
> report; and COO marks a lens stale when its own stated conditions fail. **Both halves of expiry now
> exist:** performance *and* conditions — the market is characterized from observation, a lens earns a
> regime baseline by working under it, and COO invalidates it when the market leaves those conditions.
> **Still open:** lenses remain externally *originated* — nothing proposes a better value. See the two
> closing notes at the end of this section.

**Was the most serious gap in this document.** Directly implied by §1.1: if intelligence is the lens,
then the question is not what data the system keeps — it is whether its lenses can be evaluated,
learned, or retired. They could not.

Every lens the system owns is a hardcoded constant in `agents/discovery_config.py`:

| Lens | Value | What it decides |
|---|---|---|
| `IV_RATIO_THRESHOLD` | `2.0` | What counts as an anomaly at all |
| `NEIGHBORHOOD_STRIKE_RADIUS` / `_EXPIRY_RADIUS` | `1` / `1` | What "local" means — the comparison frame |
| `PEER_MIN_COOCCURRING` | `1` | Common-factor vs idiosyncratic |
| `SPECULATOR_CONFIDENCE_THRESHOLD` | `0.6` | What social evidence is worth filing |

Confirmed by inspection: there is **no regime detection, no expiry, no recalibration, and no
revalidation anywhere in the codebase.** Every match for "expir" is the *option* expiry dimension, an
unrelated domain concept. So the system's intelligence is:

- **Static** — a lens cannot change, ever, except by a human editing an env var.
- **Externally imposed** — not derived from evidence, not learned. Addendum 7 §4 calls the 2.0
  threshold "configurable," which it is; it is not *self-adjusting*, and nothing proposes a new value.
- **Non-expiring** — carries no validity conditions, despite intelligence being regime-dependent by
  definition. A threshold derived for a low-volatility regime keeps firing identically in a
  high-volatility one, with no signal that it has gone stale.
- **Regime-blind** — nothing characterizes current market conditions, so nothing could notice the
  conditions its intelligence depends on had changed.

**The learning loop grades outputs but never updates the apparatus.** `grades` measures whether a
*report* was relevant, novel, well-evidenced, worth the compute. That feedback is persisted and
attributable — and it never reaches the threshold that generated the report. The system can therefore
accumulate overwhelming evidence that its lens is wrong and remain structurally incapable of changing
it. This is the sharpest form of the "every meaningful work unit is graded" shortfall in §6.3 of the
reconciliation record.

Constitutional bearing:

- **§7 "Conditionally stable decisions"** — "a decision should state the assumptions and information
  changes that are sufficient to reopen it." Applied to intelligence: every lens should carry the
  conditions under which it stops being valid. None do.
- **Axiom 8** — "expected new information follows defined triggers." No lens defines a trigger.
- **Axiom 2** — "recognize patterns, explain them, **test them**." The patterns are asserted, never
  tested against whether they still hold.
- **§4 "Detect — explain — exploit"** — the detect stage uses a rule nobody validated.

#### What was built (2026-08-16)

`intelligence_artifacts` — the seed of the knowledge store, holding *ways of seeing* rather than
observations. `artifact_kind` is general so source reliability (§4.4) and validated lessons become
other kinds without a schema change; `detection_lens` is the only kind built.

- Both thresholds are now artifacts carrying **value, rationale, and validity conditions** — the latter
  being §7's "conditionally stable decisions" applied to intelligence rather than to decisions.
- Agents resolve their lens from the store each cycle. Config is now only the *seed*.
- `detector_events` and `discovery_reports` carry `lens_artifact_id`, so grades attribute back through
  `grades → discovery_reports_completed → lens_artifact_id`. The reference lives on the *report* so
  Explorer and Speculator attribute identically — Speculator reports have no detector event.
- COO's `_evaluate_intelligence_health` marks a lens stale when its conditions fail. Deterministic
  statistics over grades that already existed; no LLM. Runs in COO, not the producer — Explorer judging
  its own lens is the self-certification addendum 11 §8 forbids. Moves to HR when HR exists.
- Lifecycle `active → stale → superseded`, nothing ever deleted, mirroring agent dormancy and §8's
  "track intellectual evolution".

**Flags, never fixes.** Staleness records evidence; it does not change the value. Addendum 13 §14:
"continuous learning does not mean uncontrolled self-modification." A stale lens also does not stop
detection — agents fall back to the seed and keep working, because a flag is a signal for review.

**Refuses to judge on thin evidence.** Below `min_graded_reports` it does nothing however bad the few
grades look — the same guard that led to declining performance-ranked agent selection earlier.

Verified against a real running backend, and the loop produced a genuine finding on first contact:
Analysis graded four real Speculator reports at mean 0.267 with a **0.0** worth-the-compute rate, and
COO correctly marked that lens stale on that real evidence, recording the numbers, while leaving its
value at 0.6 and leaving Speculator running. That is exactly the signal the system previously
discarded — evidence that a lens is miscalibrated, now surfaced instead of lost.

#### Still open

- **Lenses are still externally originated.** The system can now notice a lens is wrong; it cannot
  propose a better one. Doing so is Trainer/HR territory (Phase D) and stays validation-gated.
- Only the two thresholds are artifacts. The neighborhood radii and `PEER_MIN_COOCCURRING` are still
  constants; they can follow the same pattern now that it is proven.

#### The conditions half — *closed*

"Intelligence depends on market conditions. Market conditions change, and when they change,
intelligence changes" is now implemented, not just recorded.

The first thing this required was making the change *possible*. `BASE_LEVEL` and `NOISE_AMPLITUDE`
were module constants and surfaces were cached permanently, so the synthetic market could not change
regime at all — a regime detector built against it would have been a detector for a phenomenon that
could never occur, worse than no detector. `SyntheticMarketDataProvider` now takes a `regime`.

The mechanism:

- **Explorer observes, COO judges.** Explorer computes the mean and standard deviation of every
  surface it scans — including non-triggering ones, since a regime is a property of the whole market
  and sampling only anomalies would characterize anomalies. It records nothing but the statistic.
- **`market_regime` is a current estimate, not a log.** One EWMA row per security, revised in place.
  Storing an observation per security per cycle would be ~4 rows/second of *data*, precisely what
  "data retention is not imperative" rules out. Deliberately outside `intelligence_artifacts`, whose
  update semantics are the opposite: artifacts are immutable and superseded, an estimate is revised.
- **A lens earns its baseline rather than being assigned one.** A seeded lens came from the
  specification, so the regime it was *derived* under is genuinely unknown and asserting one would be
  a fabrication. COO instead binds it to the conditions it has been observed *performing acceptably*
  under. Below `min_observations`, nothing happens at all — the same thin-evidence refusal as the
  performance arm.
- **Flags, never fixes.** Divergence marks the lens stale with the before/after numbers; the value is
  untouched. Proposing a corrected threshold for the new regime is Trainer work behind validation.

Verified end to end against a real running backend across a restart (six agents, real subprocesses,
real market observation). Bound at `mean_iv=0.2999`; the environment was then changed to a 0.45 base
level and the backend restarted against the same database. The EWMA migrated 0.2999 → 0.3802 and COO
marked the lens stale on its own:

> market regime diverged from the conditions this lens was observed working under (468 observations
> across 4 securities): mean IV moved 0.0803 (from 0.2999 to 0.3802, tolerance 0.08)

Its graded performance at that moment was **fine** — mean overall 0.72, worth-the-compute rate 0.70.
This is a lens invalidated by *conditions changing*, which the performance arm structurally could not
have caught.

And the flag was not academic. Measured directly: the identical dislocation that produced a
peak/baseline ratio of **2.22** under the old regime produces **1.74** under the new one. The fixed
2.0 threshold stops firing entirely — the lens is not merely degraded, it is blind. COO reached the
right verdict from conditions alone, without ever seeing that detection had collapsed.

#### Still open after the conditions half

- **The regime arm can be pre-empted by the performance arm.** A lens must pass performance to earn a
  regime baseline, and a lens marked stale is never regime-evaluated again. Observed live: real
  Analysis grades the repeated synthetic anomaly at 0.20–0.35 overall with `worth_the_compute=0` every
  time — correctly, since it is the same bump every cycle — so in the current fixture the performance
  arm always wins the race and the regime path is unreachable through the unmodified pipeline. The
  verification above therefore injected passing grades; every other element (observation, EWMA,
  binding, drift verdict) was the real system's own work. This is a fixture-realism limit rather than
  a logic error, but a market with genuinely varied dislocations is a prerequisite for the regime arm
  to matter in practice.
- **The statistics are crude and meant to be.** Level and dispersion were chosen because they are the
  specific mechanism by which *this* peak/baseline lens goes wrong. A real characterization would use
  vol-of-vol, term-structure change, clustering. The mechanism is the contribution; the statistic is
  replaceable.
- **No social regime.** Speculator's confidence bar deliberately carries no regime conditions, because
  nothing here characterizes a social regime — attaching market conditions to a social lens would let
  option volatility invalidate it on no evidence. That is the same "no detector for a phenomenon we
  cannot observe" trap avoided above.

### 4.12 Raw data retention — *demoted* to opportunistic

An earlier version of this file ranked this first. **That was wrong** (see §1.1): it treated data as
having a preservation claim of its own. Data does not; only extracted intelligence does, and retention
is "not imperative, done on an as-possible basis."

The factual asymmetry still stands and is worth knowing, but is no longer a priority:

- **Social data is retained** — `speculator.py` writes an `evidence_items` row for every post it sees,
  regardless of confidence.
- **Market data is not** — `explorer.py` persists only threshold-clearing detections; the surface is
  never stored and a non-triggering scan leaves no trace. `detector_events.surface_seed` makes
  synthetic surfaces reproducible by replay; real data at Phase E would not be.

The Phase E urgency argument previously made here **does not survive §1.1**: if intelligence expires
with market conditions, re-processing old observations under a new lens has limited value, because
those observations came from a regime where different intelligence applied. What is worth preserving
from a discarded observation is not the observation — it is any *evidence about whether the lens was
right*, which is intelligence and belongs in the knowledge store.

What may still be worth doing opportunistically, and cheaply: retain **aggregate characterizations**
rather than raw observations — distributional summaries sufficient to detect that the regime has
shifted. That is extracted intelligence, not data retention, and it is the natural input to §4.11's
expiry conditions.

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

| Substrate | What the intelligence *is* there | Preservation | Built? |
|---|---|---|---|
| **Agents** | Active reasoning capability — the lenses they apply, and the ability to detect, interpret, judge, grade | Imperative | ◐ Agents exist; their lenses are frozen constants — §4.11 |
| **Knowledge base** | Accumulated, validated understanding: models, assumptions, ways of seeing, confidence, validity conditions | **Imperative** | ○ **No** — §4.1, the central gap |
| **Raw unprocessed data** | *Latent*, unextracted intelligence — a transient **source**, not a store | As-possible only | ◐ Asymmetric — §4.12 |

Two consequences, corrected per §1.1:

1. **The knowledge base is a locus of intelligence, not a passive store.** This raises §4.1 from "a
   useful component" to "one of the three places intelligence actually lives." Building it is not
   plumbing; it is building a third of the mind.
2. **Raw data is a source, not a holding.** Its intelligence is realised by *extraction*, not by
   retention. An earlier version of this file inferred a preservation duty from this substrate and was
   wrong — see §1.1 and §4.12.

Axiom 9's "important conclusions should survive internal challenge" remains genuinely unmet — but it is
a *separate* gap (§4.3, preserved disagreement), not a process-count problem. Internal challenge is
better served by a distinct critic perspective than by a second instance of the same role.

### 5.3 Constitutional traceability is not implemented (§16)

"Major decisions should be traceable to constitutional principles." Decisions currently carry a
free-text `reason` but never cite a principle. Cheap to add (a principle reference on decision
records), but needs a decision on whether to formalize it now or once the CEO layer exists.

---

## 6. Recommended sequence

Reordered after §1.1. The previous ranking led with raw-data retention; that rested on treating data
as intelligence and is withdrawn.

1. **The knowledge store, holding intelligence artifacts that carry their own validity conditions
   (§4.1 + §4.11 together).** These are one piece of work, not two: a store of "ways of seeing" is
   incomplete without the expiry conditions that make each way of seeing *conditionally* valid, and
   expiry conditions have nowhere to live without the store. Together they:
   - build a full third of where intelligence lives (§5.2);
   - make the system's lenses first-class, inspectable objects instead of frozen constants — today
     `IV_RATIO_THRESHOLD = 2.0` is the single most consequential piece of intelligence in the system
     and it is a literal in a config file;
   - implement §7's "conditionally stable decisions" at the level that matters, and give Axiom 8 its
     triggers;
   - close the loop where `grades` already produce evidence about lens quality that currently reaches
     nothing;
   - unblock novelty detection (§4.7), source reliability (§4.4), reflection, and the CEO layer — plus
     four of the seven sentience capabilities (§7).

   Already a Pre-Alpha task, with a concrete two-layer resident/database model specified (addenda 12
   §8, 13 §10). **Recommended.**

2. **Explorer↔Speculator cross-check with preserved disagreement (§4.3).** The sharper, smaller
   alternative: fully specified in addendum 12 §14, on the Pre-Alpha list, required for Alpha
   (addendum 14 §10), delivers Axioms 5 and 9.
3. **Source reliability (§4.4).** A form of intelligence about sources; sits naturally in the store
   once it exists, and learns from the grading loop already built.
4. **Novelty detection and transformation (§4.7).** Needs the store.
5. **Governance mechanisms (§4.10).** Design before execution capability exists, not after.
6. **Opportunistic regime characterization (§4.12).** Aggregate summaries sufficient to detect a regime
   shift — the natural input to expiry conditions. Extraction, not retention. Cheap, non-urgent.

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
