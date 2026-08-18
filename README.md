# My AI — Milestone 1+2+3+4+5: Permissioned Portfolio Demo + Data Governance + Multi-User Auth + Client-Server Split + Server Monitor

A minimal, working slice of "My AI" — a personal, local, permissioned action
layer that sits between the user and an external reasoning model. This README
documents what's actually built and how to run it.

**The design documents live in [`docs/`](docs/README.md)** — the architectural
addenda and the maintained records of how they were reconciled against each
other and against the code. That index explains which documents govern which,
and what to read first depending on what you want to know. The constitution and
three addenda are held privately and named there without links; see
[`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) for what that split is and why. For the original product architecture specifically, see
[`docs/MY_AI_DESIGN_SPEC.md`](docs/MY_AI_DESIGN_SPEC.md).

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

**Milestone 3 — multi-user authentication:**
- The CLI now starts with a login/register step (`app/users.py` for
  bcrypt-hashed accounts, `app/session.py` for a persisted local session)
  before anything else runs, matching vibe-agent's login pattern and the
  actual CLI-tooling norm (`gh`/`aws`/`docker`/`gcloud`): log in once, and
  re-running `python -m app.main` skips straight past the prompt via
  `"Welcome back, <username>."` until the session expires (7 days) or you
  run `logout`.
- Every account gets **fully isolated** permissions, preferences, and audit
  trail (`user_data/<username>/...`) — no shared/tenant concept. Two users
  can have completely different grant/consent state even though they read
  the same shared demo file (`data/portfolio.xlsx` intentionally stays
  shared; only the governance state around it is per-user).
- Usernames are normalized to lowercase and restricted to
  `[a-z0-9_-]{1,32}` (a username becomes a directory name, so this also
  closes a path-traversal risk and a Windows case-collision risk).

**Milestone 4 — desktop GUI + client-server split:**
- A real Tkinter desktop app (`desktop/`) — a login/register window plus a
  dashboard (Chat / Access & Privacy / Activity tabs) — replacing the
  terminal as the primary way to use My AI, modeled on the sibling
  `vibe-agent` project's desktop app.
- My AI is no longer one process. All business logic moved into a FastAPI
  backend (`backend/main.py`) that owns every store and the tool-use loop;
  the CLI and the desktop GUI are now both thin HTTP clients (`api_client.py`)
  that only render UI and call the backend — the same client-server shape
  `vibe-agent` uses, just without an HTTP framework the CLI needs to run
  the backend first (`uvicorn backend.main:app`). `app/session.py` became a
  real multi-token store (many logged-in clients at once, matching
  `vibe-agent`'s DB `Session` table) instead of a single local session file.
- The one thing `vibe-agent` has no equivalent of: the live `always`/`once`/
  `never` consent pop-up mid-chat. Solved statelessly — `POST /chat` can
  pause a reply with `needs_consent` instead of finishing it; the client
  shows its own prompt/dialog, then resubmits the same conversation with the
  answer attached, and the server resumes the one pending tool call. No
  server-side conversation memory needed to support this.
- The desktop client still gets the "Welcome back" skip-login convenience
  (which `vibe-agent`'s own client doesn't bother with) by caching its
  bearer token locally and verifying it against `GET /auth/me` on launch.

**Milestone 5 — server monitor:**
- A standalone operator tool (`monitor/`, `python -m monitor.app`) - a
  connected-clients list on the left, the selected client's live
  conversation on the right, both refreshed every 2 seconds. Not a user
  client: no login, watches every account's conversation via two new
  unauthenticated `/admin/*` routes on the backend.
- "Client" means **account**, not session/token — if the same person is
  logged in via both the CLI and the desktop GUI at once, their messages
  appear merged under one entry, consistent with how permissions/
  preferences are already scoped per-user rather than per-session.
- The backend now keeps an **in-memory, process-lifetime** transcript per
  account (`backend/transcripts.py`) purely for this monitor to read - a
  live "what's happening right now" view, not a permanent record (restarts
  clear it; `audit_log.jsonl` remains the permanent record, but only for
  tool *access* attempts, not full chat text). A consent pause/resume
  round-trip (two separate `/chat` calls) is deliberately recorded as a
  single question-and-answer pair, not two questions.
- Chose polling over a truly live push (see Milestone 4's `always`/`once`/
  `never` pop-up problem for the same tension) since running Tkinter's
  mainloop and uvicorn's async event loop in one process is fiddlier than
  the alternative — a small trade-off of a couple seconds' latency for a
  much simpler, safer implementation, reusing the exact standalone-app
  pattern `desktop/` already established.

## Out of scope so far

Deliberately deferred: payments, telephony, the Secure Vault (no
credentials are handled here), the tiered memory/preferences system, a full
multi-provider Model Adapter Layer (`model_gateway.py` is a thin
single-model wrapper), streaming/interruptible voice, deploying the backend
anywhere other than localhost (the thin-client/backend *split* is now
built — see Milestone 4 above — but it still only ever runs as two local
processes on your own machine, same as `vibe-agent`), and the generalized
Universal Capability Layer (there's still exactly one capability,
`retrieve_portfolio`). See
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

## Running tests

```bash
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest
```

158 tests in `tests/`, covering every module in `app/`, the FastAPI backend
(`tests/test_backend_*.py`, via `TestClient` — no real server needs to be
running), `api_client.py`'s own request/response/error-handling logic
(`tests/test_api_client.py`, against a mocked `requests`), the HTTP-backed
CLI (`tests/test_auth_cli.py`, `tests/test_main_cli.py`, against a mocked
`APIClient`), and the server monitor's backend half — `TranscriptStore`
(`tests/test_transcripts.py`) and the `/admin/*` routes plus their `/chat`
integration (`tests/test_backend_admin.py`; `monitor/app.py` itself has no
automated tests, consistent with `desktop/`'s own zero-Tkinter-widget-tests
precedent — verified manually instead). The suite is fully hermetic: no real
`ANTHROPIC_API_KEY` is required, no real server is ever started, and no
network call is ever made — `call_reasoning_model` is mocked in every test
that touches the chat loop, `getpass.getpass` is mocked in every test that
touches login/register (real `getpass` reads directly from the console on
Windows, bypassing redirected stdin entirely, so it can't be driven by
piped input the way the rest of the CLI can for manual smoke testing), and
`tests/conftest.py` sets a dummy key before any app module is imported
(importing `app.model_gateway` alone requires *a* key to be set, since it
constructs the Anthropic client at import time). All persisted state is
redirected to `tmp_path` fixtures per test, so tests never touch your real
local data.

Writing the Milestone 2 tests surfaced one real bug: `PrivacyPreferenceStore
.list_all()` did a shallow `dict()` copy, letting a caller mutating a
returned entry silently corrupt the store's actual state — fixed to copy
each entry too. Manually driving the CLI post-Milestone-2 surfaced a second:
answering `once` to a consent prompt never actually granted the pending
call, since the tool was re-invoked with no way to bypass the still-unset
disposition — fixed by threading a one-time bypass through
`execute_tool`/`retrieve_portfolio`. Writing `POST /chat`'s consent-resume
branch for Milestone 4 surfaced a third: the chosen disposition
(`always`/`never`) was being applied to the resumed tool call *after*
executing it instead of before, so resuming would just hit the same
`needs_consent` wall again — fixed by persisting the disposition first.
Verified live for Milestone 5 too: a real consent pause/resume round-trip
through the monitor's transcript correctly shows up as one question and
one answer, not two.

## Run

Two processes now — start the backend first, then whichever client you want:

```bash
# terminal 1
.venv/Scripts/python.exe -m uvicorn backend.main:app --reload
```

```bash
# terminal 2 - either one
.venv/Scripts/python.exe -m app.main        # CLI
.venv/Scripts/python.exe -m desktop.app     # desktop GUI
```

Both clients start with a login/register step — everything from there is
scoped to whichever account you log into, and either client can be logged
into as a *different* account than the other, at the same time, against the
same backend.

## AI Communication Gateway

A separate service on its own port (`gateway/`, addenda 16–18), and the only
one intended to be reachable from outside this machine. It does not run inside
the backend on purpose: addendum 16 §7 makes it the single external boundary,
and sharing a port with the internal and `/admin` routes would defeat that.

It needs a Super User credential, which comes from the environment rather than
from `users.json` — a route that could grant this privilege would be an
escalation surface, and the Gateway login should not be the ordinary
application password:

```bash
.venv/Scripts/python.exe -m gateway.hash_password
```

Put the printed `GATEWAY_PASSWORD_HASH=...` line and a `GATEWAY_SUPER_USER=...`
in `.env`, then:

```bash
.venv/Scripts/python.exe -m uvicorn gateway.main:app --port 8100
```

Open <http://localhost:8100> and sign in. **Unset means nobody can log in** —
an unconfigured Gateway refuses every attempt and says which variables are
missing, rather than defaulting open.

What works today: the boundary, Super User sessions, and a streaming
conversation with the analysis model over a WebSocket, persisted so closing the
tab and returning resumes it (G1); and the **Project Scoreboard** — questions and
concerns that deserve a decision later rather than an interruption now (G3).

The Scoreboard is reachable two ways, and both land on the same board. Saying
"put that on the board as important and blocking" files it during the turn, which
is the point: the Super User decides, rather than transporting the decision
somewhere to be recorded. And `POST /scoreboard` is there for producers that are
not the conversation — a monitoring agent files under its own name.

An urgent item sorts first and is counted in the header. **Nothing rings a
phone**: addendum 17 §10 defers notification channels to a separate
specification, so an urgent item is seen when you look.

It also reaches **Git** (G4). The assistant reads tracked files from the project
repositories — a question about what a specification says is answered by reading
it — and can publish a document. A publish commits to a **new branch**, pushes
nothing, and never touches the working tree: it builds the commit with git
plumbing against HEAD, so uncommitted work stays uncommitted and the checked-out
branch stays checked out. A person reviews the branch and pushes it.

Configure the repositories it may reach, or it has none:

```bash
GATEWAY_PRIVATE_REPO=C:/path/to/private-repo
GATEWAY_PUBLIC_REPO=C:/path/to/public-repo
```

**Publishing defaults to the private repository.** A public target needs explicit
confirmation, and a screen refuses content that reads like the organizational
philosophy `docs/PUBLIC_PRIVATE_BOUNDARY.md` keeps private — because publishing
publicly cannot be undone. Only files git is *tracking* can be read, which is why
`.env` is invisible to it.

It can also **see the running system** (G5): which agents exist, their lifecycle
state and process state kept separate, and how stale each heartbeat is. That is
read-only — it cannot retire, resume or spawn anything, because the Controller
alone executes lifecycle changes. Point it at a backend account with:

```bash
GATEWAY_BACKEND_URL=http://localhost:8000
GATEWAY_BACKEND_USER=<an account in the backend's MY_AI_ADMIN_USERS>
GATEWAY_BACKEND_PASSWORD=<its password>
```

**And it keeps working when the backend does not.** With Jarvis stopped, the
conversation, the Scoreboard and Git all carry on; the system view says the
backend did not answer and why. That is addendum 16 §23, and it is why the
Gateway is a separate process with its own database.

What does not work yet: voice, and pushing. `docs/SPEC_RECONCILIATION.md` §20 to
§23 record why it is shaped this way and what the remaining increments are.

## Simulation

`simulation/` runs the whole system — real server, real agent processes, real
database — under conditions written down in a scenario file, so a run can be
repeated and compared instead of performed from memory.

```bash
.venv/Scripts/python.exe -m simulation list
```

```bash
.venv/Scripts/python.exe -m simulation run baseline_steady_state
```

Each run gets its own directory under `simulation/runs/`, holding its own
database, the backend log, and a `manifest.json` recording the seed, the full
`FI_*` configuration, the code version, and whether a reasoning model was
reachable. Isolation is the database itself, by way of `FI_DB_PATH`, so a run
cannot touch the working database and two runs cannot collide.

A run is only reported successful if the server shut down through the path that
stops its agents, verified from both the log and the registry — an agent process
left alive would keep writing to a database nobody is reading.

Scenarios declare *properties* that must hold across repeats, never expected
output: a reasoning model sits in the pipeline, so the stimulus is exactly
reproducible and the wording of the result is not.

```bash
# terminal 3, optional - the operator-side conversation monitor
.venv/Scripts/python.exe -m monitor.app
```

No login for the monitor — it watches every account's conversation. Pick a
client from the left list to see their conversation on the right; it
refreshes every couple of seconds as new messages come in.

## Demo script — Milestone 3 (multi-user auth)

```
[My AI] Login or register? [login/register] > register
Choose a username: alice
Choose a password: ********
Confirm password: ********
Registered and logged in as alice.
My AI (Milestone 4). Logged in as alice. Commands: ...
> logout
Logged out.
```

Run it again within 7 days without logging out, and it skips straight past
the prompt:

```
Welcome back, alice.
My AI (Milestone 4). Logged in as alice. Commands: ...
```

Register a second account (`bob`) — from the other client, or the same one
after logging out — and you'll find `alice`'s grants, preferences, and
audit trail are completely invisible to `bob`: the backend keeps each
account's `permissions.json`/`privacy_preferences.json`/`audit_log.jsonl`
under its own `user_data/<username>/`, even though both read the same
`data/portfolio.xlsx`.

## Demo script — Milestone 1 (core permission loop)

```
> grant portfolio
Granted: portfolio
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

Check `user_data/<username>/audit_log.jsonl` and `privacy_preferences.json`
afterward — every interaction above is recorded, and `account_id`'s actual
value never appears in either file or anywhere in the model conversation.

## Architecture

```
backend/
  main.py                The FastAPI process - owns every store and the tool-use loop (incl. the
                         needs_consent pause/resume protocol - see the Milestone 4 section above).
                         Every route requires Authorization: Bearer <token> except /auth/register,
                         /auth/login, and the two unauthenticated /admin/* routes the monitor polls.
                         Nothing else in this repo touches app/*.py stores directly anymore - only
                         this process does.
  transcripts.py          TranscriptStore - in-memory, per-account conversation log for the
                         monitor only (not persisted, not the permanent record - that's still
                         audit_log.jsonl for tool access, this is just "what's happening right now")
api_client.py             APIClient - thin requests wrapper shared by app/main.py and desktop/,
                         mirrors vibe-agent's desktop/client.py shape (raises APIError, holds a
                         bearer token)
app/
  main.py                CLI: login/register/logout + grant/revoke + preference commands, all now
                         via api_client.APIClient - a local .cli_session file caches the bearer
                         token so re-running skips login (verified against GET /auth/me)
  users.py               UserStore - register/authenticate (bcrypt), users.json + user_data/<user>/
  session.py              SessionStore - many concurrently-valid tokens (one per logged-in
                         client), sessions.json - backend-only now, no client touches this directly
  permissions.py         PermissionManager - grant/revoke/is_granted (layer 1: resource access),
                         user_data/<user>/permissions.json
  privacy_preferences.py PrivacyPreferenceStore - get/set/forget/list_all (layer 2: forwarding),
                         user_data/<user>/privacy_preferences.json
  data_classification.py DataClass enum + per-field placement registry (LOCAL_ONLY/SERVICE_SHAREABLE/...)
  privacy_filter.py     Sanitizes rows per data_classification.py before data can ever reach the model
  audit.py               AuditLog - append-only per-user audit_log.jsonl
  model_gateway.py        Thin wrapper around the Anthropic call (seed of a future adapter layer)
  tools/
    portfolio.py           retrieve_portfolio() - layer 1 check -> layer 2 check -> read -> sanitize -> return
    __init__.py             Tool schema + dispatcher
desktop/
  app.py                  Tk root, frame-swap between LoginScreen/DashboardScreen, a local
                         .gui_session file caches the bearer token the same way the CLI's does
  screens/
    login.py                Login/register form, calls api_client.APIClient instead of app/*.py
    dashboard.py             ttk.Notebook: Chat / Access & Privacy / Activity tabs. Chat runs on a
                         background thread (self.after(0, ...) hand-off) so a slow reply never
                         freezes the window; a needs_consent reply shows a ConsentDialog and the
                         chosen answer fires a second background-thread call to resume
monitor/
  app.py                  Standalone operator tool, no login - client list (left) + selected
                         client's live conversation (right), polls GET /admin/clients and
                         GET /admin/clients/<username>/transcript every 2s via plain `requests`
                         (not api_client.APIClient - these two routes are unauthenticated)
gateway/
  main.py                 The external boundary (addenda 16-17): its own FastAPI app on its own
                         port, Super User login, and the conversation WebSocket. Nothing is
                         constructed at import; the database belongs to lifespan
  store.py                gateway.db - sessions (tokens stored hashed) and the conversation
                         transcript. Separate from financial_intelligence.db so the Gateway
                         survives the backend being down, which addendum 16 §23 requires
  auth.py                 Who the Super User is, from the environment. Unset means nobody
  conversation.py         The analysis assistant's system prompt and one turn's mechanics,
                         including the tool loop. Not backend/main.py's /chat - that is the
                         user's permissioned personal assistant; this one answers about the
                         project
  scoreboard.py           The Project Scoreboard (addendum 16 §16): deferred questions, their
                         discussion, and the order they come back in - which is the routing
                         policy addendum 17 §6 puts on the Gateway
  tools.py                What the assistant can actually do. Five Scoreboard tools and three
                         Git ones; failures come back as tool results the model can correct
                         itself from
  jarvis.py               The window onto the running backend: read-only GETs, short timeouts,
                         and "unavailable" as an ordinary answer rather than an exception -
                         which is what addendum 16 §23's isolation actually requires
  repositories.py         Git as the artifact exchange (addendum 16 §14/§20): tracked-files-only
                         reads, and publishes that commit to a new branch via plumbing - no
                         checkout, no push, no working-tree writes. Holds the public/private
                         boundary guard
  streaming.py            Runs the blocking model stream on a worker thread so the event loop
                         stays free to read the socket while a reply is being produced
  static/index.html       The whole client: one file, no build step, no external requests
data/
  portfolio.xlsx         Mock demo holdings (fake tickers/shares/prices/dates/account_id) - shared
                         across all users; only the governance state around it is per-user
docs/
  MY_AI_DESIGN_SPEC.md    Master design spec (reconstructed baseline + Addendum 1 merged in)
  addenda/                Verbatim addenda, kept as authoritative source for future merges
```

`users.json`, `sessions.json`, `.cli_session`, `.gui_session`, and
`user_data/<username>/` (each holding that user's
`permissions.json`/`privacy_preferences.json`/`audit_log.jsonl`) are local,
gitignored state — regenerated fresh as you register/use accounts.
