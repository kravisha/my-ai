# Confidence assessment

**Task 01 §4.3.** What produces the confidence score, its range, and the current
threshold.

---

## The answer, first

**Nothing produces a confidence score. There is no mechanism, and there never
was one — not even a placeholder.**

The task allowed for finding a placeholder and asked, if so, to say so rather
than invent a fix:

> *"If no real mechanism exists and the score is a placeholder, say so
> explicitly rather than inventing one — that finding is more useful than a
> fabricated fix."*

It is one step emptier than that. Before this task the word "confidence" did not
appear in `app/model_routing.py` at all. There was no score, no placeholder, no
variable waiting to be filled, and no threshold compared against anything.

## What the router actually decided, before and after

`LocalFirstRouter` escalated on two questions and no others:

1. Is a local provider configured? (`self.local is not None`)
2. Does `app/local_ai.available()` return True?

Both are availability. Neither is quality. Since `build_router(local=None)` is
the only construction in the runtime, question 1 answers "no" on every request,
so **every request escalates**, always, for the reason
`no local provider is configured in this deployment`.

The finding from `docs/CURRENT_ARCHITECTURE.md` §4 restated: the task's
hypothesis that "the confidence threshold may be miscalibrated" cannot be right,
because there is no confidence threshold in the decision and there is no local
model to be confident about.

## What this task added, and what it deliberately did not

Added — `app/confidence.py`, a **seam**:

```python
verdict = confidence.assess(answer=answer, request=messages)
if verdict.sufficient:
    return answer          # the local answer stands
# otherwise: escalate with reason `low_confidence`
```

`assess()` returns an `Assessment` with:

| Field | Today's value | Why |
|---|---|---|
| `score` | `None` | "nobody measured this", which is a different statement from `0.0` — a zero would escalate every request under any threshold above zero |
| `sufficient` | `True` | an answer is not rejected on the strength of a measurement nobody took |
| `threshold` | from `config/router.yaml` | 0.65 |
| `mechanism` | `"none"` | named, so the nightly report can say it |
| `detail` | `app.confidence.NO_MECHANISM` | the sentence you are reading, in the code |

Not added — a scorer. Writing one would have meant choosing, in an afternoon,
between self-reported certainty (a model's own estimate of its correctness,
which is the least reliable number in the field), token-level log-probabilities
(unavailable through the OpenAI-dialect endpoint this system uses, and
meaningless across two different models), and a second model judging the first
(which doubles the cost of the thing local-first exists to reduce). Each is a
research decision. None of them belongs in a task whose §8 says "do not expand
beyond the four deliverables".

## The range and the threshold

- **Range:** 0.0–1.0. Declared by `app/router_config._validated`, which refuses
  a value outside it and refuses a quoted number — a string threshold would
  compare greater than every float score, escalating everything, silently.
- **Current threshold:** `0.65`, in `config/router.yaml` under
  `router.confidence_threshold`.
- **Configurable:** yes, as §4.3 requires. It is read at call time and cached on
  the file's modification time, so an edit takes effect without a restart.
- **Effective today:** none. There is nothing to compare against it.

`router.escalate_on_low_confidence` (default `true`) exists so a future scorer
can be *observed* before it is *acted on*: with it off, scores are recorded in
`logs/model_calls.jsonl` and no request escalates because of one. That is how a
threshold gets calibrated from evidence instead of from a first guess.

## The decision rule, in full

Stated here so it is not re-derived from the code each time:

| Situation | Verdict | Escalation reason |
|---|---|---|
| `score is None` (today, always) | sufficient | — |
| `score >= threshold` | sufficient | — |
| `score < threshold` and `escalate_on_low_confidence` | insufficient | `low_confidence` |
| `score < threshold`, escalation off | sufficient, score recorded | — |
| the assessor itself raised | sufficient | — |

The last row is the one with a trap in it. A broken scorer must not become an
escalation policy: an assessor that throws on every call would otherwise send
every request to the paid API, and it would look like the local model getting
worse. The inverse of `local_is_usable`'s rule about a broken availability
check, and for the same reason — in each case the safe direction is the one
that does not silently change where the work goes.

## How `escalation_reason` reads in the log, and one thing to watch for

`logs/model_calls.jsonl`'s `escalation_reason` is §3.1's closed vocabulary. The
router maps its own sentences onto it (`app/model_routing._LOG_REASONS`), and
one mapping deserves calling out because it will otherwise be misread:

> **"no local model runtime is installed" is recorded as `local_error`.**

Nothing broke. The alternative was `not_applicable`, which would claim the call
never left local when it did. The four permitted escalations are about the local
tier being unable to serve, and a tier that does not exist is the limiting case
of unable — but a reader of the nightly report will otherwise conclude the local
model is crashing several hundred times a day. It is not. There is no local
model.

## What would have to be true for the threshold to matter

Three things, in order:

1. A local model exists (TQ-57 installs a runtime; `app/local_ai.py` is the
   interface it arrives behind).
2. Something scores its answers, and `confidence.register()` installs it.
3. Enough scored calls accumulate in `logs/model_calls.jsonl` for
   `app/self_diagnosis.suggest_threshold` to have data.

Only then does the nightly report's threshold section say anything but "no call
carried a confidence score". Until then it says that, every night, which is the
honest report and also a standing reminder of which increment is missing.

## Related

- `docs/CURRENT_ARCHITECTURE.md` §4 — what the router decides today
- `docs/CALL_SITES.md` — every path that can reach a model
- `app/confidence.py` — the seam
- `app/router_config.py`, `config/router.yaml` — the threshold
- `app/capability.py` — a *different* decision (deterministic / local /
  external), from a task signature, not wired into `LocalFirstRouter`. Worth
  knowing about before writing a second one.
