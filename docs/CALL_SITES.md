# Static inventory of every path that can reach a model

**Written:** 2026-09-21, from a grep sweep of the repository at commit `5318600`,
before any Task 01 code change.
**Purpose:** Deliverable A §3.3 — catch paths that runtime logging would miss
because they are rarely exercised. The runtime half of the same question is the
`routed_by` field in `logs/model_calls.jsonl`; this file is the half a log cannot
answer.
**Method, so it can be repeated:**

```bash
grep -rn "call_reasoning_model\|default_provider\|KimiProvider\|kimi_provider\|build_router\|LocalFirstRouter" --include=*.py .
grep -rn "\.stream(\|\.complete(" --include=*.py app agents backend gateway
grep -rni "anthropic\|api.kimi\|moonshot\|httpx\.\|requests\.\|urlopen" --include=*.py .
```

---

## 1. Headline

**Every runtime path that can reach Kimi goes through
`app/model_routing.LocalFirstRouter`. There are zero direct call sites in
application code.**

`app/kimi_provider.KimiProvider` is constructed in exactly one place in the
whole repository outside the test suite:

```
app/model_routing.py:340   remote = kimi_provider.KimiProvider() if kimi_provider.credential_present() else None
```

and that line is inside `build_router`, which returns the router itself. So the
class cannot be reached without the router existing, and the router is the only
thing holding a reference to it.

That is the answer going in. It is written down rather than assumed because the
task's fault 2 hypothesised the opposite, and because the value of the sweep is
that it can be re-run.

---

## 2. Paths to Kimi — the external model

| # | Call site | Reaches the model via | Through the router? |
|---|---|---|---|
| 1 | `agents/analysis.py:334` | `app.model_gateway.call_reasoning_model` | **Yes** |
| 2 | `agents/analysis.py:373` | `call_reasoning_model` | **Yes** |
| 3 | `agents/analysis.py:408` | `call_reasoning_model` | **Yes** |
| 4 | `agents/explorer.py:131` | `call_reasoning_model` | **Yes** |
| 5 | `agents/introspection.py:55` | `call_reasoning_model` (deferred import) | **Yes** |
| 6 | `agents/speculator.py:161` | `call_reasoning_model` | **Yes** |
| 7 | `backend/main.py:1179` (`/chat`) | `call_reasoning_model` | **Yes** |
| 8 | `backend/coo_chat.py:261` (console stream) | `default_provider().stream` | **Yes** |
| 9 | `backend/coo_chat.py:299` (console answer) | `default_provider().complete` | **Yes** |
| 10 | `gateway/conversation.py:283` (`run_turn`) | `provider.stream`, provider injected from `gateway/main.py:959` = `default_provider()` | **Yes** |

Two funnels feed all ten:

```
app/model_gateway.call_reasoning_model  ─┐
app/model_gateway.default_provider      ─┴─→ SlowProvider? → BudgetedProvider → LocalFirstRouter → KimiProvider
```

`SlowProvider` is inert unless `FI_FAULT_MODEL_DELAY_SECONDS` is set
(fault injection). `BudgetedProvider` is the spend ledger and sits outside the
router on purpose.

### 2.1 The one provider injection seam, and why it is not a bypass

`gateway/conversation.run_turn` and both `backend/coo_chat.py` entry points take
`provider` as an argument. `coo_chat` falls back to `default_provider()` when
passed `None`; `run_turn` requires one and `gateway/main.py:959` passes
`default_provider()`.

A caller could therefore pass any object with `.stream()`. In the repository
today only the test suite does, and the objects it passes are stand-ins that
reach no network. This is a seam for tests, not a route to the vendor — but it
*is* the shape a future bypass would take, and it is exactly what the runtime
`routed_by` field is instrumented to catch.

### 2.2 `KimiProvider._transport`

`app/kimi_provider.py:414` accepts a `transport` callable, documented as "a seam
for the tests, and only that … Left None in every real construction". Verified:
no non-test construction passes it. A transport that reached a different host
would not be a bypass of the router, but it would be an unlogged external call
if instrumentation sat above it — a second reason Deliverable A instruments
inside `KimiProvider`, below this seam's effect.

---

## 3. Paths to Anthropic — retired, kept, unreachable

| Call site | Status |
|---|---|
| `app/model_provider.py:166` `AnthropicProvider` | The class exists and `client()` would construct a real SDK client from `ANTHROPIC_API_KEY`. **Constructed by nothing in the runtime.** |
| `app/model_provider.py:204` `client().messages.stream(...)` | Only reachable through the above. |
| `app/model_tiering.py:156` `TieredProvider` | Live and tested; constructed by nothing. Both of its tiers *were* Anthropic models. |

Three independent things stop these being reachable, and only the third is
enforcement:

1. Nothing constructs them (a property of today's code).
2. `app/model_gateway.default_provider` builds `BudgetedProvider(build_router())`
   and nothing else.
3. `app/model_routing.assert_no_anthropic` walks the provider graph at
   construction and **raises** on a class whose name or defining module contains
   "anthropic". It runs in `LocalFirstRouter.__init__` and again on the assembled
   graph in `default_provider()`.

`ANTHROPIC_API_KEY` is still read in three places, all of them tooling rather
than runtime, and deliberately kept: `tests/conftest.py` (a placeholder so
imports survive), `simulation/harness.py` (reports whether an agent subprocess
could reach a model at all), `scripts/wake-claude-dev.ps1`.

---

## 4. Paths to a local model

**None, because there is no local model.**

`app/local_ai.NoLocalModelsService` refuses every inference call with a sentence
naming what is missing. `app/local_ai.KNOWN_LOCAL_RUNTIMES` lists ten runtime
package names and `tests/test_local_ai_contract.py::test_no_module_reaches_a_local_runtime_directly`
scans the repository for imports of any of them outside `app/local_ai.py`. That
tripwire passes, i.e. nothing imports a local runtime anywhere.

`LocalFirstRouter.local` is `None` in every runtime construction:
`build_router(local=None)` is the only call and no caller passes an argument.

---

## 5. Other external calls — not models, listed so "every external call" is unambiguous

| Call site | Destination | Notes |
|---|---|---|
| `providers/historical.py:218` | `stooq.com` | market history, `requests.get` |
| `providers/historical.py:329` | `fred.stlouisfed.org` | macro series, `requests.get` |
| `providers/market_data.py`, `providers/social_data.py` | per-provider | market/social data adapters |
| `gateway/remote.py:316` | tailnet peers | machine diagnosis, `urllib.request.urlopen` |
| `api_client.py` | `http://localhost:8000` | the project's own backend |

None of these reaches a model. They are out of scope for Task 01 and are not
instrumented by the model-call log.

---

## 6. Where a user sees a model failure — the fault-1 surfaces

Not a model call site, but the sweep that matters for §4.2, because these are the
four places an internal plumbing string can become an answer:

| Site | As found | Carries the ledger's "tokens" sentence? |
|---|---|---|
| `gateway/main.py:1082` | `send_json({"type": "error", "error": f"model error: {exc}"})` | **Yes** — this is the observed fault |
| `backend/main.py:1184` | `HTTPException(status_code=503, detail=str(exc))` | **Yes** |
| `backend/coo_chat.py:266` | `yield {"type": "error", "error": f"{exc.__class__.__name__}: {exc}"}` | **Yes** |
| `backend/coo_chat.py:304` | `return {..., "error": f"{exc.__class__.__name__}: {exc}"}` | **Yes** |

The string originates at `app/model_budget.py:282-285`. All four sites forward
`str(exc)` from a bare or near-bare handler, so they leak whatever any future
exception says as well — which is why Deliverable B's fix is a classifier plus a
user-facing vocabulary, rather than four edited f-strings.

---

## 7. Re-running this sweep

`tests/test_no_direct_model_calls.py` is the executable version of §2 and §4: it
fails if a module outside `app/model_routing.py` constructs `KimiProvider`, or if
application code calls `KimiProvider.complete`/`.stream` directly. A tripwire
rather than a document is what keeps this file from quietly going out of date —
the document explains, the test enforces.
