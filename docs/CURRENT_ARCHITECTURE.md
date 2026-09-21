# Current architecture of the model path

**Written:** 2026-09-21, before any code in Task 01 was changed.
**Method:** read the source, not the design documents. Where the two disagree,
this file describes the source and says so.
**Scope:** the agent loop, where model calls are made, where the router is, and
every code path that can reach an external API. Nothing else.

This is the "read before writing" artifact of `jarvis-task-01`. It exists so
that the router repair in Deliverable B is a change to a described system rather
than to a remembered one.

---

## 1. Runtime and layout

| Field | Value as found |
|---|---|
| Language | Python (CI pins 3.12; the sandbox this was verified in runs 3.11) |
| Web framework | FastAPI + uvicorn, two separate services |
| Local model | **None installed.** `app/local_ai.NoLocalModelsService` is the honest implementation and reports zero models |
| External model | Kimi, `k3-256k` over `https://api.kimi.com/coding/v1`, OpenAI dialect (`app/kimi_provider.py`) |
| Router | `app/model_routing.LocalFirstRouter` |
| Spend ledger | `app/model_budget.py`, shared SQLite at `model_spend.db` |
| Test suite | 3280 passing before this task |

There are **two independent services**, and they are not one app with two
routers:

- `gateway/` — Krish's own assistant ("Jarvis"). FastAPI + a WebSocket at
  `/ws/conversation`. This is the surface the two faults in the task were
  observed on.
- `backend/` — the simulated organization (agents, departments, the COO
  console). It has its own `/chat`, its own database, and its own agent
  population.

They share exactly one thing on the model path: `app/model_gateway.py`'s
process-wide provider singleton.

---

## 2. Where the agent loop lives

There are three agent loops, not one, and they reach the model differently.

### 2.1 The Gateway conversation loop — `gateway/conversation.py::run_turn`

The loop the task's faults were observed on.

```
gateway/main.py::conversation_socket   (WebSocket /ws/conversation)
  provider = app.model_gateway.default_provider()          # line 959
  → gateway/conversation.run_turn(db_path, history, provider, role=…)
      for _ in range(MAX_TOOL_ROUNDS):
          for event in provider.stream(system, messages, offered, max_tokens)
          … execute tools, append tool_result, loop …
      yield {"type": "reply", "text": …}
```

`run_turn` is a generator of events (`text`, `tool`, `ui`, `reply`). The socket
handler forwards `text` fragments to the browser as they arrive.

**This is where fault 1 is surfaced.** `gateway/main.py:1078-1083`:

```python
except Exception as exc:  # noqa: BLE001 - reported to the client, not swallowed
    logger.exception("model turn failed")
    …
    await websocket.send_json({"type": "error", "error": f"model error: {exc}"})
```

Every exception raised anywhere under `provider.stream` has its `str()` put on
the wire to the browser. `app/model_budget.BudgetExceededError`'s message is:

> `Daily model token budget exhausted: 512334 tokens recorded today (limit 500000). Raise MODEL_BUDGET_DAILY_TOKENS deliberately if this spend is intended.`

That sentence, verbatim, is "Jarvis replies that he doesn't have any more
tokens". It is not a prompt problem and no prompt change can fix it: the string
is assembled in `app/model_budget.py` and forwarded by `gateway/main.py`.

### 2.2 The backend chat loop — `backend/main.py` `/chat` (around line 1177)

```python
while True:
    try:
        response = call_reasoning_model(SYSTEM_PROMPT, messages, TOOLS)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
```

Same leak, second surface: the ledger's sentence becomes an HTTP 503 body.

### 2.3 The agent population — `agents/base.py` run contract

Four agents call a model, each through `app/model_gateway.call_reasoning_model`:
`agents/analysis.py` (three call sites), `agents/explorer.py`,
`agents/introspection.py`, `agents/speculator.py`. None of them constructs a
provider; none of them names a vendor. `agents/base.py`'s run loop declares the
spend attribution label (`app/model_budget.set_caller`).

---

## 3. Where model calls are made

One funnel, and it is already narrow:

```
callers                         app/model_gateway.py                app/model_routing.py
────────────────────────────    ───────────────────────────────     ─────────────────────────
agents/*.py                 ┐
backend/main.py /chat       ├─→ call_reasoning_model()  ─┐
                            ┘                            │
gateway/main.py:959         ┐                            ├─→ default_provider()
backend/coo_chat.py:258,296 ┴─→ default_provider()  ─────┘        │
                                                                  ▼
                                                   SlowProvider?   (fault injection, inert
                                                        │           unless FI_FAULT_* is set)
                                                        ▼
                                                   BudgetedProvider  (the spend ledger)
                                                        │
                                                        ▼
                                                   LocalFirstRouter
                                                    ├── local  = None today
                                                    └── remote = KimiProvider() when
                                                                 KIMI_API_KEY is set
```

`default_provider()` is a module-level singleton built on first use.
`set_provider()` replaces it, and is how the suite substitutes a stand-in.

### The layering, and why it is that order

`BudgetedProvider` is **outside** the router, deliberately (documented at
`app/model_gateway.py:126-137`): the ledger must count every call once whichever
tier served it. A consequence that matters for this task: a budget refusal is
raised *before* the router chooses, so the router never sees it and cannot fall
back from it. `LocalFirstRouter.complete` re-raises `BudgetExceededError`
untouched on purpose — "the ceiling exists to stop work, not to move it
somewhere else".

---

## 4. Where the router is, and what it actually decides

`app/model_routing.LocalFirstRouter`, and the decision as found is:

```
complete(system, messages, tools, max_tokens):
    usable, escalation = local_is_usable()       # availability only
    if usable:
        try:   return local.complete(...)
        except BudgetExceededError: raise
        except Exception:  escalation = LOCAL_FAILED
    if remote is None:  raise ModelRoutingFailure
    return remote.complete(...)
```

`local_is_usable()` asks two questions and no more:

1. is `self.local` not `None`? → otherwise `LOCAL_NOT_OFFERED`
2. does `app/local_ai.available()` return True? → otherwise `NO_LOCAL_RUNTIME`

`available()` is `bool(service().list_models())`, and
`NoLocalModelsService.list_models()` returns `[]`.

### The finding that the task's fault 2 reduces to

**Nothing is bypassing the router, and the confidence threshold is not
miscalibrated. There is no confidence assessment at all, and there is no local
model to be confident about.**

- `self.local` is `None` in every constructed router: `build_router(local=None)`
  is the only construction in the runtime and no caller passes an argument.
- So `local_is_usable()` returns `(False, LOCAL_NOT_OFFERED)` on **every**
  request, and **every** request escalates to Kimi.
- The escalation reason recorded is therefore accurate and constant. It is not
  "the local model could not cope"; it is "no local provider is configured in
  this deployment".

"Calls are going to Kimi that the local model could have handled" is true in the
sense that matters to the bill and false in the sense the task assumed: they are
going to Kimi because there is nothing else, not because a threshold is wrong.
Deliverable A's instrumentation is what makes that statement evidence rather
than a reading of the source, which is why it comes first.

A second finding, smaller: the word "confidence" does not appear in
`app/model_routing.py` at all. `app/capability.py` decides
*deterministic / local / external* from a task signature, and
`app/routing_decisions.py` records decisions — but neither is wired into
`LocalFirstRouter`. They are a parallel, unconnected lineage. See
`docs/CONFIDENCE.md`.

### What the router refuses to become

`assert_no_anthropic` walks the provider graph at construction (`inner`,
`local`, `remote`, `cheap`, `capable`) and refuses to build a router with a
class from a module or of a name containing "anthropic". It is called twice: in
`LocalFirstRouter.__init__` and again in `default_provider()` on the assembled
graph. There is deliberately no feature switch.

---

## 5. Every code path that can reach an external API

The exhaustive static list, with router status, is
[`docs/CALL_SITES.md`](CALL_SITES.md). In summary as found today:

- **Reaching Kimi:** one class, `app/kimi_provider.KimiProvider`, constructed in
  exactly one place, `app/model_routing.build_router`. Every runtime path to it
  goes through `LocalFirstRouter`. No direct call site exists in `agents/`,
  `backend/`, `gateway/` or `providers/`.
- **Reaching Anthropic:** `app/model_provider.AnthropicProvider` still exists
  and can still construct a client, but nothing in the runtime constructs the
  class, and `assert_no_anthropic` would refuse a router containing it.
- **Reaching other external APIs, not models:** `providers/market_data.py`,
  `providers/social_data.py`, `gateway/remote.py`. Out of scope here; listed in
  `CALL_SITES.md` so "every external call" is not left ambiguous.

So the primary purpose of Deliverable A — finding `routed_by: direct_call`
paths — has a static answer of "none" going in. The runtime instrumentation is
still worth building, for the reason the task gives: a static sweep cannot see a
path that reaches the provider through a variable, and it is the mechanism that
keeps the answer "none" as the code changes.

---

## 6. Observability as found

| What | Where | Shape |
|---|---|---|
| One line per routed call | `LocalFirstRouter._record` | `logging`, `model.routing` logger, `provider=… model=… location=… escalation=… latency_ms=… input_tokens=… output_tokens=…` |
| Counters | `LocalFirstRouter.counts`, `model_routing.counters()` | local / remote / escalated / failed / anthropic_runtime |
| Spend | `app/model_budget.todays_spend`, `spend_by_caller` | SQLite, per UTC day, per caller label |
| Routing decisions | `app/routing_decisions.py` | SQLite, rich schema — **not written by `LocalFirstRouter`** |
| Model outcomes | `app/model_performance.py` | SQLite leaderboard — also not written by the router |

Three gaps that Deliverable A closes, all of them structural rather than
oversights:

1. **The log line is written by the router**, so a call that did not pass
   through the router is not logged at all. The task requires the opposite
   layering, and it is right: instrument the HTTP call.
2. **There is no request id.** A single user turn can make several model calls
   (`MAX_TOOL_ROUNDS` in `gateway/conversation.py`), and nothing ties them
   together.
3. **No call log survives the process.** Everything is `logging`, so the
   nightly self-diagnosis of Deliverable C has nothing to read.

---

## 7. Configuration as found

Read from the environment, no config file on the model path:

| Variable | Read by | Default |
|---|---|---|
| `KIMI_API_KEY` | `app/kimi_provider.credential_present`, `api_key` | none — no remote tier without it |
| `KIMI_BASE_URL` | `configured_base_url` | `https://api.kimi.com/coding/v1` |
| `KIMI_MODEL_REMOTE` | `configured_model` | `k3-256k` |
| `KIMI_TIMEOUT_SECONDS` | `configured_timeout` | 120 |
| `MODEL_BUDGET_DAILY_TOKENS` | `app/model_budget` | 500000 |
| `MODEL_BUDGET_DAILY_CALLS` | `app/model_budget` | 2000 |
| `MODEL_BUDGET_DB_PATH` | `app/model_budget` | `model_spend.db` |
| `MODEL_BUDGET_CALLER` | `app/model_budget` | `unattributed` |
| `FI_FAULT_MODEL_DELAY_SECONDS` | `app/model_gateway` | unset, inert |
| `ANTHROPIC_API_KEY` | `app/model_provider` only, unreachable in runtime | kept for the Claude development sessions |

**There is no `config/router.yaml` and no threshold to configure**, because
there is no threshold. `config/` holds one file today,
`remote-targets.example.json`.

---

## 8. What is broken but not in this task's scope

Recorded here rather than fixed, per §8 of the task:

- `app/routing_decisions.py` and `app/model_performance.py` are a complete
  decision-recording and scoring lineage that **nothing on the live model path
  writes to**. The self-improvement loop they describe is not running. Wiring
  them to `LocalFirstRouter` is a larger change than this task, and doing it
  badly would put two disagreeing accounts of the same call in two databases.
- `app/model_tiering.TieredProvider` is live, tested, and constructed by
  nothing. It is the right shape for choosing between a frugal and a capable
  *local* model and is deliberately kept.
- `app/capability.py` answers "deterministic, local, or external" and is not
  consulted by the router, so the execution hierarchy it encodes is not
  enforced on the live path.
- `gateway/main.py:1078`'s bare `except Exception` forwarding `str(exc)` is a
  general information-disclosure shape, not only a "tokens" problem. This task
  fixes the user-facing wording and the classification; it does not rewrite the
  handler.

---

## Appendix — what Task 01 changed

This document describes the system **as found on 2026-09-21, before the
change**, and it is left that way on purpose: it is the evidence the repair was
based on, and rewriting it into a description of the result would delete the
finding. What follows is the delta.

### New modules

| Module | What it is |
|---|---|
| `app/model_calls.py` | The call log. One JSON record per model call, written *inside* `KimiProvider` rather than in the router, so a call that skipped the router is still recorded. Holds the `direct_call` guard. |
| `app/router_config.py` | Reads `config/router.yaml`. The confidence threshold, the retry policy, the report schedule. |
| `app/confidence.py` | The confidence seam. Returns "sufficient, unmeasured" — see `docs/CONFIDENCE.md`. |
| `app/user_messages.py` | The only vocabulary a user-facing handler may speak in. |
| `app/retry_queue.py` | Requests queued after exhausted capacity. |
| `app/capability_gaps.py` | What was asked for and could not be done, and the monthly audit. |
| `app/self_diagnosis.py` | The nightly and weekly reports, and what reaches the morning brief. |

### Changed

- `app/model_routing.py` — the four permitted escalations, quota fallback,
  configurable threshold, two new counters.
- `app/kimi_provider.py` — `KimiQuotaExhausted`, and the recording inside
  `complete`/`stream`.
- `gateway/streaming.py` — the worker thread now runs in a copy of the calling
  context, so the request id survives the hop.
- `gateway/main.py`, `backend/main.py`, `backend/coo_chat.py` — the four leaking
  handlers from §5 now speak `app/user_messages.py`.
- `gateway/conversation.py` — records a capability gap when a turn runs out of
  tool rounds (§6.1's "answered only partially").
- `backend/briefing.py` — a `_self_report` section, guarded.

### Running the reports

```bash
python -m app.self_diagnosis --if-due     # what the schedule says is owed
python -m app.self_diagnosis --nightly    # one now, for the last 24 hours
python -m app.self_diagnosis --weekly
python -m app.capability_gaps             # the monthly skills audit
```

`scripts/register-jarvis-self-diagnosis.ps1` registers the hourly
`--if-due` check on Windows. Hourly rather than nightly deliberately: the
schedule lives in `config/router.yaml`, and a machine asleep at 03:00 would
otherwise skip a night without saying so.

### Section 8's list, revisited

Everything in §8 is still true and still unfixed, with two additions found
while doing this work and deliberately left alone:

- `backend/main.py`'s desk handlers (around lines 649 and 741) and
  `backend/continuity.py`'s summary put `f"{exc}"` into an `error` key for the
  operator console. Same shape as the fault this task fixed, different surface,
  and no model exception can reach them.
- Nothing re-executes a queued retry. The queue is written, counted, reported
  and closed out; replaying a turn is a product decision about Jarvis's
  behaviour rather than a routing change. `app/retry_queue.py`'s docstring
  gives the full reasoning.
