# My AI — Milestone 1+2: Permissioned Portfolio Demo + Data Governance

A minimal, working slice of "My AI" — a personal, local, permissioned action
layer that sits between the user and an external reasoning model. See
[`docs/MY_AI_DESIGN_SPEC.md`](docs/MY_AI_DESIGN_SPEC.md) for the full
architecture; this README documents what's actually built and how to run it.

## What this proves

**Milestone 1 — the core loop** (design spec §7/§13):
- Permission to a local resource (a mock investment portfolio) can be
  **granted** and **revoked** by the user, explicitly, at any time.
- The reasoning model (Claude) can only read that resource through a tool
  call that checks permission *before* touching the file — the model never
  sees the data unless access is currently granted.
- When access is revoked, the tool hands back a clear denial (not the data,
  not a hint of it), which the model relays in plain language.

**Milestone 2 — data governance** (design spec §7–§8, Addendum 1 §9–§12):
- A second, independent layer sits on top of resource-level permission:
  whether data already read from a resource may be *forwarded* to the
  external reasoning model. The first time that's needed, MY AI pauses the
  conversation and asks the user directly — the model is never involved in
  that negotiation — then remembers the answer (`always`/`once`/`never`) so
  it isn't re-asked every turn.
- Every field of a resource has a deliberate data-placement classification
  (`app/data_classification.py`). `LOCAL ONLY` fields (the mock portfolio's
  `account_id`) are stripped automatically and unconditionally, before the
  forwarding-consent question is even asked — no disposition can ever make
  local-only data shareable.
- Preferences are inspectable (`show preferences`) and reversible
  (`reset preference <key>`) at any time.

Every access attempt — granted, denied by permission, or denied by
forwarding disposition — is written to an audit log, and the two kinds of
denial are surfaced to the user with distinct wording (the reasoning model
is instructed to relay the tool's actual error, not assume it's always the
same kind of denial).

## Out of scope so far

Deliberately deferred: payments, telephony, the Secure Vault (no
credentials are handled here), the tiered memory/preferences system, a full
multi-provider Model Adapter Layer (`model_gateway.py` is a thin
single-model wrapper), streaming/interruptible voice, the thin-client/
backend network split, and the generalized Universal Capability Layer
(there's still exactly one capability, `retrieve_portfolio`). See
`docs/MY_AI_DESIGN_SPEC.md` §16 for the full status. Permission grant/revoke
and preference commands are explicit CLI commands, not parsed from
freeform text, since reliably parsing *authorization* intent is a distinct,
higher-stakes problem from general Q&A intent.

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env   # then fill in ANTHROPIC_API_KEY
python scripts/make_mock_portfolio.py   # regenerate data/portfolio.xlsx if needed
```

## Run

```bash
python -m app.main
```

## Demo script — Milestone 1 (core permission loop)

```
> grant portfolio
Granted: portfolio (data/portfolio.xlsx)
> What stocks do I own?
[My AI] I need to share your portfolio holdings ... Allow this?
[always/once/never] > always
[Claude answers, grounded in the real mock holdings]
> Analyze my portfolio
[Claude gives a real analysis, no re-prompt since disposition is 'always']
> revoke portfolio
Revoked: portfolio
> Analyze my portfolio
I cannot access your portfolio — permission to that resource has been revoked.
```

## Demo script — Milestone 2 (data governance)

```
> show preferences
portfolio_holdings:reasoning_model: always (set ...)
> What is my account ID?
I don't have access to your account ID — that's not something I can view or retrieve.
> reset preference portfolio_holdings:reasoning_model
Forgot preference: portfolio_holdings:reasoning_model
> Analyze my portfolio
[My AI] I need to share your portfolio holdings ... Allow this?
[always/once/never] > never
I'm not able to do that right now — you've previously told me not to share
your portfolio data with me, which is a specific instruction you gave
(separate from general permission settings).
```

Check `audit_log.jsonl` and `privacy_preferences.json` afterward — every
interaction above is recorded, and `account_id`'s actual value never
appears in either file or anywhere in the model conversation.

## Architecture

```
app/
  main.py               CLI loop: grant/revoke + preference commands + the tool-use chat loop,
                         including the pause-for-consent flow (never delegated to the model)
  permissions.py        PermissionManager - grant/revoke/is_granted (layer 1: resource access), permissions.json
  privacy_preferences.py PrivacyPreferenceStore - get/set/forget/list_all (layer 2: forwarding), privacy_preferences.json
  data_classification.py DataClass enum + per-field placement registry (LOCAL_ONLY/SERVICE_SHAREABLE/...)
  privacy_filter.py     Sanitizes rows per data_classification.py before data can ever reach the model
  audit.py               Append-only audit_log.jsonl
  model_gateway.py        Thin wrapper around the Anthropic call (seed of a future adapter layer)
  tools/
    portfolio.py           retrieve_portfolio() - layer 1 check -> layer 2 check -> read -> sanitize -> return
    __init__.py             Tool schema + dispatcher
data/
  portfolio.xlsx         Mock demo holdings (fake tickers/shares/prices/dates/account_id)
docs/
  MY_AI_DESIGN_SPEC.md    Master design spec (reconstructed baseline + Addendum 1 merged in)
  addenda/                Verbatim addenda, kept as authoritative source for future merges
```

`permissions.json`, `privacy_preferences.json`, and `audit_log.jsonl` are
local, gitignored state — regenerated fresh by running the app.
