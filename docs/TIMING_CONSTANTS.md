# Timing Constants Audit

**Maintained document.** Every constant in this system whose correctness depends on how fast
something else runs, what rate that is, and whether the rate has ever been *measured* rather than
assumed.

The reason this file exists: a constant compared against a rate cannot be validated by unit tests,
because unit tests supply the rate themselves. Three defects have now been found this way and none
of them were findable from a green suite:

| Constant | Symptom | Found by |
|---|---|---|
| `HEALTH_STALE_THRESHOLD_SECONDS` was 10s | Healthy agents marked crashed mid-LLM-call and duplicated | Manual verification, Phase C |
| `STARVATION_SECONDS` was 120s | Below the queue's 260-400s drain time, so every report starved and prioritisation silently became FIFO | Measuring Analysis throughput |
| `UQI_TIMEOUT_SECONDS` was 15s | Questions to `analysis-1` returned 'unanswered' while it worked normally | Measuring answer latency per agent |

Last measured: 2026-08-16, against a real backend at ten securities with five forced anomalies.

---

## Measured rates

These are the facts every constant below is judged against.

| Rate | Measured value | How |
|---|---|---|
| Agent cycle, `coo` / `explorer` / `speculator` / `dummy` / `controller` | **~1.0 s** | Heartbeat advance over 40s |
| Agent cycle, `analysis` | **~10 s** | Heartbeat advance over 40s |
| Analysis report throughput | **0.05 reports/s** (one per ~20s) | Completed-report count over 60s |
| Pending report queue depth | **13-20** (bounded by per-producer dedup) | Queue count, held steady |
| Queue drain time | **260-400 s** | depth ÷ throughput |
| UQI answer latency, procedural agents | **2.2-3.6 s** | Ask, watch the DB for the answer |
| UQI answer latency, `analysis-1` | **5.8 / 19.4 / 24.0 s** | Three samples, same method |
| Spawn → agent registered | **0.09-1.62 s** | Directive `completed_at` → registry `spawned_at`, 4 agents |
| Cross-check answer latency | **min 0.7s, median 6.1s, max 15.4s** (n=23) | `answered_at − created_at` |

---

## The constants

Verdict key: **OK** = margin over the measured rate. **TUNED** = corrected after measurement.
**UNMEASURED** = depends on a rate nobody has measured; not known to be wrong.

| Constant | Value | Depends on | Margin | Verdict |
|---|---|---|---|---|
| `HEALTH_STALE_THRESHOLD_SECONDS` (coo) | 45 s | Longest gap between an agent's heartbeats | Analysis heartbeats mid-work before its model call, so gaps stay ~10s | **OK** — 4.5× |
| `UQI_TIMEOUT_SECONDS` (fi_db) | 60 s | Slowest agent's cycle + its own answer call | Worst observed 24.0s | **TUNED** from 15s |
| `STARVATION_SECONDS` (triage) | 900 s | Queue drain time | Worst drain 400s | **TUNED** from 120s |
| `CROSS_CHECK_TIMEOUT_SECONDS` (fi_db) | 30 s | Responder's answer latency under queueing | Max observed 15.4s | **OK** — 2× |
| `OBSERVATION_GRACE_SECONDS` (coo) | 5 s | Spawn → process start → registration | Worst observed 1.62s | **OK** — 3.1× |
| `HEARTBEAT_INTERVAL_SECONDS` (base) | 1.0 s | Nothing downstream — it *sets* the rate | n/a | **OK** |
| `CONTROLLER_POLL_INTERVAL_SECONDS` (main) | 1.0 s | Directive latency tolerance | n/a — it sets the rate | **OK** |
| `POLL_INTERVAL_MS` (panel, monitor) | 2000 ms | Operator patience only | n/a | **OK** |
| `REQUEST_TIMEOUT_SECONDS` (panel) | 5 s | Backend response time for read routes | Local reads are milliseconds | **OK** |
| `SEEN_WINDOW` (speculator) | 40 posts | Evidence retained for cross-check answers | Bounded by design | **OK** |
| `ANALYSIS_RECENCY_WINDOW_SECONDS` | 300 s | How long "recently analysed" should mean | A judgment, not a rate | **n/a** |
| `REGIME_EWMA_ALPHA` (fi_db) | 0.05 | Observations per regime shift | Explorer observes ~1/s/security; a shift migrates the estimate in ~40 observations | **UNMEASURED** — see below |
| `min_observations` (regime binding) | 30 | Observations before a regime estimate is trusted | Reached in seconds at ten securities | **OK** |
| `min_graded_reports` (lens validity) | 10 | Grades before a lens is judged | Reached in minutes | **OK** |
| `SESSION_LIFETIME` (session) | 7 days | Operator session length | A policy, not a rate | **n/a** |

---

## The one that stays unmeasured

**`REGIME_EWMA_ALPHA = 0.05`** — the weight on each new market observation. Too high and the
estimate chases noise; too low and a real regime shift takes so long to register that the lens stays
bound to conditions that ended. The verified regime shift migrated the estimate 0.2999 → 0.3802 and
tripped the drift check, so the value is *adequate* — but "adequate once" is not a calibration, and
the right value depends on how often real regimes change, which the synthetic fixture cannot tell us.
It is the only constant here whose dependent rate cannot be measured from the system as it stands,
because the rate is a property of real markets rather than of this software.

---

## The rule this file encodes

**Any constant whose correctness depends on a rate must be checked against the measured rate, not
reasoned about.** Where a measurement exists, encode it as a test so the constant cannot drift back
underneath it — `tests/test_triage.py` does this for `STARVATION_SECONDS`, and
`tests/test_uqi.py` for `UQI_TIMEOUT_SECONDS`.

Re-measure when any of these change: the model behind `call_reasoning_model`, the number of
securities, the number of Analysis instances, or the agent cycle interval.
