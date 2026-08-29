# Task Queue — the Strategic Priority Register, in paper form

A maintained document (edited as work moves; see `README.md` for the verbatim/maintained
distinction). This realizes addendum 31 §3's Strategic Priority Register and addendum 32 §12's
priority queues in the only form the current system can honestly support: a human-maintained
document, worked one item at a time, with the owner acting as the Board. No parliament, committee,
or voting body exists yet to run the full addendum 32 procedure — building one is itself an entry
below (TQ-05), and until then this file *is* the queue those documents describe.

**Conventions** (from the addenda themselves):

- **NEED / WANT** — addendum 31 §2. A Need materially threatens required objectives if unresolved;
  a Want is desirable and competes for priority. Wants may be deliberately never done (Directive S5).
- **Flag** — addendum 31 §2.2: GREEN / YELLOW / ORANGE / RED / CRITICAL, Needs only.
- **QUICK_WIN** — addendum 32 §15: very low cost, low risk, reversible, beneficial; accelerated path.
- **Status** — QUEUED / IN_PROGRESS / DONE (with the `SPEC_RECONCILIATION.md` § recording it) /
  BLOCKED (with the blocker) / DEFERRED (with the reason) / DECLINED (with the reason).

Every entry names its source specification. Executed items get a reconciliation section; this file
holds the queue, not the record.

---

## Queue, in priority order

> **Checkpoint 2026-08-29.** Both halves of the organization are built. The *operating*
> machinery is exercised; the *governing* machinery — Parliament, the governed store, agents that
> read what binds them, releases that apply and reverse, an appeal heard by a peer, and a
> Constitution the organization may amend at two-thirds — went from specified-and-absent to built
> between 2026-08-27 and 2026-08-29. **None of it has any text in force**: the Articles and the
> Constitution both wait on the owner.
>
> **The system was re-scoped on 2026-08-28.** Project Providence (addenda 49–52, §140) makes the
> product a personal AI world; financial intelligence becomes the *Personal Portfolio Manager*,
> one of about fifteen personal agents. Market data and the broker are no longer the head of this
> queue — agent identity, client binding and the Usher are.
>
> **Newest and least proven: the Software Department** (addendum 53, §150–§152). Five gates on an
> issue workflow, a DBA that opens an issue when a scheduled check fails, and a loop that staffs
> itself and stops at the one perspective that needs a judgement.
>
> **`simulation verify` is stale.** Last PASS at `579f5c4`; five increments have landed since,
> including three new schema tables and a change to the loop every agent shares. Re-running it is
> the next session's first task.
>
> **With the owner:** TQ-100 — *what refuses a persona that crosses the line?* — which addendum 53
> §7.9 makes a **freeze** on TQ-101 rather than a recommendation. Also the genesis Articles and
> Constitution (§120, §142), and `JARVIS_GAP_ANALYSIS.md`, which scores against a Constitution
> that became v2.0 on 2026-08-28.
>
> **The product side has not moved since TQ-80** — no prices, no broker, no client. A deliberate
> consequence of the chosen track, and under Providence no longer the critical path.
>
> **RECOMMENDED NEXT, in order:**
>
> 1. **Re-run `python -m simulation verify`** — stale since `579f5c4`. See `HANDOFF.md` for the
>    two things to watch (`record_grade` now raises on an empty rationale in the hot path; the
>    DBA makes every scenario an eight-agent run).
> 2. **The unmet Definition-of-Done items at §150 §7** — chiefly that `metrics.open_at_end` is
>    re-aimed and **has never been forced to fire**. Re-aimed is not proven (§136).
> 3. **The 45 properties on `simulation/property_history.worklist()`** that have never been
>    observed failing. A worklist, not a defect list — and where the next §149-shaped defect is.
>
> Blocked or with the owner: **TQ-101** (frozen by addendum 53 §7.9 until TQ-100 is answered),
> **TQ-75/TQ-49/TQ-50** (owner action), **TQ-95** (Evolution's relay, unblocked by TQ-96 but not
> yet argued for).
>
> This block states the *present*. The increment-by-increment narration is in
> `SPEC_RECONCILIATION.md`, newest section last, which is where history belongs.
>
> **Addendum 44 (portfolio subsystem, §97).** TQ-44 done (§99) — every portfolio has an explicit
> owner, `resolve()` is the only way to one, and the §15.5 regression is permanent. TQ-45 done —
> 45a the canonical holding shape (§100), 45b the provider abstraction and its conformance suite
> (§101). TQ-69 done (§110) — the whole subsystem now sits behind the backend. **TQ-46 is specified
> and next**; TQ-47, TQ-48 and TQ-49 follow it. TQ-50 is blocked on owner action.
>
> **Owner direction 2026-08-26 (§109): the Gateway authenticates; the backend authorizes and holds
> business logic.** **TQ-69 is done (§110)** — `portfolios` and `portfolio_holdings`, the ownership
> guard, `holdings` and the providers are in `financial_intelligence.db`, and the Gateway reaches
> them over HTTP behind `require_gateway`. There are now two checks where there was one. Route-level
> capability gating stays at the Gateway and was never the drift. **TQ-46 is unblocked and next**;
> it raised **TQ-70** (three identity populations) and **TQ-71** (four retired holdings tables).
>
> **Addendum 45 (local intelligence and competitive model routing, §102).** Six increments built
> and **no local model behind any of them**: TQ-51 the routing ladder (§103), TQ-53 the task
> signature and vocabularies (§104), TQ-54 the Model Performance Registry and eight leaderboards
> (§105), TQ-55 the routing decision record (§106), TQ-56 `LocalAIService` and its conformance
> suite (§107), TQ-59 the deterministic check and escalation decision (§108). `routing` now stands
> on the `seeded_leaderboard` rung.
>
> **TQ-52's blocking question is answered (2026-08-27).** It was held on what "Inkling" is; the
> owner named it and, once this machine had internet access, it was measured. **Inkling is Thinking
> Machines Lab's open-weights model: 975B parameters, 41B active, Apache 2.0 — and its smallest
> known build is 226 GB at 1-bit.** Against 8 GB VRAM and 16.5 GB RAM (§102) it is out of reach by
> about an order of magnitude, so it is recorded as **out, with the reason**, and the pool is
> Llama + DeepSeek + Qwen/Mistral/Gemma at 7–8B. A finding, not a substitution. What remains of
> TQ-52 is the survey itself; TQ-57, TQ-58, TQ-60 … TQ-68 queue behind that.
>
> Also open: **TQ-07** (consumer-gated), **TQ-20** and **TQ-21** (owner actions), **TQ-28**
> (the isolation guard), and the deferred animated presenter.
> Desktop Phase A and B are done (TQ-30/31/32); Pre-Alpha Milestone 1 is complete.
>
> **Previously: Pre-Alpha Milestone 1** (addenda 38–39, assimilated 2026-08-25, §70) —
> TQ-22 → TQ-23 → TQ-24 in that order, since each is the next one's foundation; TQ-25 carries a
> recorded startup conflict and TQ-26 is blocked on an owner decision about having two operator
> UIs. Also open: TQ-07 (consumer-gated), and two owner actions from the continuity work —
> **TQ-21** (verify the off-machine key copy actually decrypts) and **TQ-20** (provision the
> Linux host, deferred 2026-08-25).

### TQ-01 — Assimilate the Organizational Doctrine lineage (addenda 28–33)

**NEED (GREEN) · QUICK_WIN · DONE — `SPEC_RECONCILIATION.md` §47**

Source: the six documents supplied 2026-08-23. Verbatim assimilation into `addenda/`, index and
precedence in `README.md`, disposition in §47, and this register. The seventh supplied document
(the options arbitrage library) was verified byte-identical to addendum 27's body — already
assimilated 2026-08-22; no action.

### TQ-02 — Business Continuity baseline, slice 1: backup with tested restore

**NEED (YELLOW) · DONE — `SPEC_RECONCILIATION.md` §48**

Source: addendum 29 §7–§8, §45 (items 3, 4, 7, 8, 17, 18), Directives 2–6. Today a single disk
failure loses every store the organization has ever written — a direct violation of 29 §1.3 (no
single point of irrecoverable failure), and the framework's §45 baseline says automated backup of
critical persistent state SHALL exist before public exposure, which the Gateway lineage is already
built toward. Scope: a provider-neutral `StorageProvider` interface (29 §8.1) with a
local-directory adapter first (29 §1.7 explicitly blesses local storage as a provider); backup sets
covering the backend database, the Gateway store, and `user_data/`, carrying §7.4's metadata
(backup id, creation time, source versions, per-file integrity hashes); and a restore path **proven
by an automated test that actually restores and verifies** (§1.4: an untested backup is not a
recovery asset). Encryption-before-upload (§10.1) is deferred within this slice with the reason
recorded: the first adapter is same-machine local disk, where encryption adds key-loss risk
(§10.3) without leaving the failure domain; it becomes mandatory with the first remote adapter.

### TQ-03 — Evolution Directive E17: agents expose behavior version and certification state

**NEED (GREEN) · QUICK_WIN · DONE (behavior version) — `SPEC_RECONCILIATION.md` §49.**
The certification-state half is deliberately deferred *inside* §49: no machinery produces a
per-agent certification state yet, and a defaulted column would assign what addendum 30 insists is
earned. It arrives with the machinery that writes it.

Source: addendum 30 §26, Directive E17 ("Every agent SHALL expose a behavioral version and
certification state"). Agents today carry runtime identity (`identity`, `spawned_at`) and the
knowledge they act on is versioned (strategies, peer groups), but the agent registry row exposes no
behavior version and no certification state, so mixed-version operation and targeted retraining
(30 §26's stated purpose) have nothing to key on. Scope: additive registry columns, populated at
spawn, surfaced through the existing admin/monitor views. Keys into the certification machinery the
training loop already has (addendum 13 lineage) rather than inventing a parallel one.

### TQ-04 — Security Defense §32 baseline audit

**NEED (GREEN) · QUICK_WIN · DONE — `SPEC_RECONCILIATION.md` §50**

Twenty items audited: 8 satisfied, 5 partial with the missing piece named, 4 absent (three promoted
below as TQ-08/09/10, MFA folded into §50's exposure-precondition list), 3 n/a with named triggers.
The exposure preconditions are restated in one place in §50 so exposure can never happen by drift.

### TQ-05 — Strategic Priority Register, machine-readable

**WANT · DONE — `SPEC_RECONCILIATION.md` §54**

`backend/register.py` + `/admin/register` routes. One correction to this entry's own premise,
recorded in §54: the store does **not** supersede this paper file — the development queue (this
file) and the organization's register of proposals are different registers, and duplicating one
into the other would manufacture two sources of truth. The store starts empty and holds what the
organization files: petitions and mandates, ordered by the doctrine (Needs before Wants, flag
severity, Quick-Win acceleration), with fail-closed vocabulary and reasons on every parking
transition.

### TQ-06 — Options arbitrage library, next increment per addendum 27 §11

**WANT · DONE (buildable scope) — `SPEC_RECONCILIATION.md` §55**

ARB-015 (option-implied dividend) and ARB-016 (implied financing/borrow basis) built as D-class
`Diagnostic`s under their own schema with their own `diagnose_chain` entry point — addendum 27
§8's schema-level separation of D from arbitrage, pinned by test. The executable-band discipline
replaces mid-price gaps: a declaration inside the band the spreads allow is no signal at all.
The rest of Phase 2 is blocked on world capabilities, recorded below; the diagnostics' first
consumer (reference-data validation cross-checking declared dividends/borrow against the market)
is named in §55 as the natural next increment.

### TQ-07 — Governance cost/impact profile on register entries

**WANT · QUEUED · consumer-gated**

Source: addendum 32 §14, §16. The register (TQ-05) now exists to carry the profile, but the
profile's *consumer* — the enhanced-scrutiny path where a committee weighs cost against benefit —
is part of the deferred parliamentary machinery. Until something reads the fields, adding them
would be the "table nothing writes to" error in reverse; queued until a consumer exists or the
owner wants the profile for their own review.

### TQ-08 — Incident response runbook, including credential revocation

**NEED (GREEN) · QUICK_WIN · DONE — `docs/INCIDENT_RESPONSE.md`, noted in `SPEC_RECONCILIATION.md` §51**

Preserve evidence → stop (clean shutdown or the orphan-cleanup procedure §48 observed) → revoke
(sessions, Gateway sessions, provider key at the console, Gateway password) → assess against audit
trails and `behavior_version` → restore through the fail-closed continuity path → written review.
Its own limits are stated in the document.

### TQ-09 — Dependency scanning habit

**WANT · DONE — noted in `SPEC_RECONCILIATION.md` §53**

`pip-audit` pinned in requirements-dev with the cadence documented beside it (before each push
that changes requirements, and on picking the project back up). Its first run found and fixed six
known vulnerabilities in the venv's own pip (25.0.1 → 26.2.1); the environment now scans clean.
**Upgraded to CI enforcement 2026-08-25** — `.github/workflows/ci.yml` runs it on every push and
pull request and fails the build on a finding (`SPEC_RECONCILIATION.md` §67).

### TQ-11 — Origination cooldown on the idle loops

**NEED (YELLOW) · DONE — `SPEC_RECONCILIATION.md` §58 · owner-directed 2026-08-25**

The idle organization spent ~500k tokens/hour re-purchasing judgment chains the moment each one
completed (§57's measured fact). `ORIGINATION_COOLDOWN_SECONDS` (default one hour per security,
env-tunable) now gates all three origination points; observation and answering stay free. Measured
after: zero steady-state spend, ceiling ~one chain per security per hour.

### TQ-10 — Cost circuit breaker on the model provider

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §52**

`app/model_budget.py`: shared per-UTC-day SQLite ledger, pre-call refusal with post-hoc accounting
(damage bounded to limit + one reply), refusals recorded in the ledger, `/chat` mapping to a
legible 503. Per-caller attribution and currency-denominated limits deferred within §52.

### TQ-12 — Business Continuity slice 2: automated backup, retention, encrypted secondary

**NEED (YELLOW) · DONE — `SPEC_RECONCILIATION.md` §59**

Source: addendum 29 §45 ("automated backup ... SHALL exist" — §48's copy was manual), §7.6
(retention), §10 (encryption before leaving the failure domain). A backup loop in the backend
lifespan plus a clean-shutdown backup (interval = the de facto RPO, 6h default, env-tunable,
0 disables); retention pruning in the mirror of creation order; `CONTINUITY_SECONDARY_ROOT` as
a second destination, unconditionally Fernet-encrypted — closing §48's recorded deferral, whose
reason (same failure domain) stops applying the moment a copy leaves the machine. The key is
Tier-0 recovery material; its custody obligation is printed at generation and recorded in §59.

### TQ-13 — Assimilate the Organizational Doctrine second set (addenda 34–37)

**NEED (GREEN) · QUICK_WIN · DONE — `SPEC_RECONCILIATION.md` §60**

Source: the four documents supplied 2026-08-25 (Training & Monte Carlo Simulation Framework,
Multi-LLM Enterprise Strategy, Department of Education, Evolution's Continuous Optimization
addendum). Verbatim assimilation into `addenda/` 34–37, index and precedence in `README.md`,
dispositions in §60, and the entries below. The owner's priority directive — Reference Data
Engine and Simulation Engine first — is recorded in §60 and ordered here.

### TQ-14 — Simulation Engine: world capabilities for the blocked detector families

**NEED (YELLOW) · DONE — `SPEC_RECONCILIATION.md` §61 (forward leg) and §63 (event-stepped
timeline) · owner-directed head of queue (2026-08-25, §60)**

Source: addendum 25 (the world's own spec), addendum 34 §6–§8, and the blocked register below.
Scope item 1 (§61): four forward variants under `options_arbitrage_forward`, ARB-013/014 as
their detectors (TQ-B1 resolved; addendum 27 §11 Phase 1 complete), wired end to end; the
instrument is per-variant for the finance §61 records. Scope item 2 (§63): the
`options_arbitrage_timeline` strategy — State(t) + Event(t) → State(t+1) over a fixed listed
ladder with seeded market drift, opportunity onset/resolution windows, per-step grading through
the existing evaluate(), and stored step sequences whose detection-latency consumer is named.
Addendum 34's fuller trial vocabulary (outages, delayed data, collaboration events, stages
3–9) is future work per §63; American-style worlds (TQ-B3) remain a larger, separate increment.

### TQ-15 — Reference Data Engine: market-implied validation of declared dividends and borrow

**NEED (YELLOW) · DONE — `SPEC_RECONCILIATION.md` §62 · owner-directed second (2026-08-25, §60)**

Source: addendum 24 §6 (validation duty), §55's own closing sentence (the diagnostics' first
consumer), addendum 34 §2. Built as §62 records: `market_implied` is a registered `derived`
source ranked below every declaring one; certification cross-checks each focus asset's stored
chains through `diagnose_chain` and records declarations outside the executable band as
append-only `reference_conflicts` rows, one per (asset, field, expiry), deduplicated per
distinct disagreement. A disagreement is data — it never blocks readiness, never flips
validation_status, and a malformed observation is named in the check detail rather than
allowed to take down startup.

### TQ-16 — Model Registry and Model Requirement Profiles, as metadata first

**WANT · DONE — `SPEC_RECONCILIATION.md` §64**

Source: addendum 35 §3–§5, under addendum 30 §12's metadata-before-code doctrine. Built as
`docs/model_registry.yaml` + `tests/test_model_registry.py` under organization.yaml's
assertion discipline: one honest configured row with measured facts only (unmeasured fields
carry no numbers, enforced), six profiles — one per code location that actually reaches the
model — with call shapes bound to their sizing constants, universal `provisional: true` per
35 §2, a consumer scan that fails the suite on any undeclared model consumer, and the pinned
`routing: none_single_model` decision as a tripwire: registering a second model fails the
suite until routing is revisited deliberately.

### TQ-17 — Collaboration scoring baseline, from records the system already writes

**WANT · DONE — `SPEC_RECONCILIATION.md` §65**

Source: addendum 34 §16–§17, addendum 36 §8, addendum 37 §8. Two dimensions added to
`backend/competency.py` — `collaboration_responsiveness` (cross-checks answered, by the
span's role) and `uqi_responsiveness` (UQI questions answered, by the span's identity) —
computed from records the organization already writes, under the module's existing four
rules: absent is not zero, earned not assigned, no universal score, attribution by tenure.
`no_evidence` counts as an answer and latency folds into the rate (the timeout machinery
already marks slow answers `unanswered`). Handoff completeness stays unbuilt with its
blocker named: no queryable linkage from a report back to the cross-check it grew from.
Feeds the leadership gate (§60 disposition 5) whenever promotion machinery exists.

### TQ-18 — Optimization measurement baseline: per-caller spend attribution

**WANT · DONE — `SPEC_RECONCILIATION.md` §66**

Source: addendum 37 §3–§4 ("measure organizational resource use"), closing §52's recorded
deferral now that its consumer exists. A `spend_by_caller` table beside the existing totals,
written in the same transaction; agents declare their identity in `agents/base.py`'s shared
run loop and the two chat surfaces in their lifespans, with undeclared spend bucketed as
`unattributed` rather than guessed. Refusals carry the caller too. Deliberately not a second
budget — the limit stays organization-wide, because a per-caller cap would break §52's damage
bound. Currency-denominated limits and per-caller *limits* remain deferred with reasons.

### TQ-19 — Off-machine copy of `backup.key`

**NEED (YELLOW) · DONE 2026-08-25 — owner confirmed an off-machine copy exists ·
`SPEC_RECONCILIATION.md` §69, `docs/SECOND_FAILURE_DOMAIN.md`**

**Where the copy lives is deliberately not recorded here.** Naming the storage location of a
recovery credential in a repository tells a reader where to go looking for it; the fact of
custody is what this queue needs, and the location belongs to the owner
(`docs/PUBLIC_PRIVATE_BOUNDARY.md`'s rule applied to a credential rather than a document).
Verifying that the copy actually works is its own entry, **TQ-21** — custody and correctness are
different claims, and this one only established the first.

Source: addendum 29 §10.3. The encrypted secondary now writes to a Dropbox-synced folder, and
`backup.key` is deliberately **not** there — key beside ciphertext is the same as no encryption.
The consequence is the open gap: the disaster that takes this disk takes the key with it, and
every encrypted copy becomes noise. A perfectly encrypted backup with a lost key is not a backup.

Scope, entirely manual: put a copy of `C:\Users\ADMIN\my-ai\backup.key` somewhere that is neither
this machine nor this Dropbox account — a password-manager entry, a different cloud account, or
paper in a drawer. Flagged YELLOW rather than GREEN because it undermines a capability that is
*already built and running*: until it is done, the secondary destination is protecting against a
disk failure it could not actually recover from.

### TQ-20 — Provision the Linux host (the second failure domain's host half)

**NEED (GREEN) · QUEUED · owner-deferred 2026-08-25 ("leave it locally for now") ·
`SPEC_RECONCILIATION.md` §68/§69, runbook in `docs/SECOND_FAILURE_DOMAIN.md`**

Source: addendum 29 §1.3, §18–§21. The *data* domain is done and rehearsed (§69) — state now
survives this machine. What remains is the *host* domain: somewhere the organization could
actually run, turning an RPO-only story into one with an RTO. Deferred by owner decision, not by
a technical blocker: §68 proved the suite green on Linux, so this needs a machine rather than a
port, and provisioning spends money and requires an account — an owner action by nature.

Scope when taken up: `docs/SECOND_FAILURE_DOMAIN.md` steps 1–6, whose load-bearing step is step 5,
the restore rehearsal on the host (§1.4 — an untested restore is a hypothesis, not a recovery
asset), followed by recording the result. Failover orchestration, live replication and geographic
separation stay out of scope and remain in the deferred list below.

### TQ-21 — Verify the off-machine key copy actually decrypts a backup

**NEED (YELLOW) · QUICK_WIN · QUEUED · needs the owner to produce the copy; the test itself is
two minutes · `SPEC_RECONCILIATION.md` §69, `docs/SECOND_FAILURE_DOMAIN.md`**

Source: addendum 29 §1.4 ("a backup that has never been restored is not a recovery asset"),
applied to the key rather than to the backup. TQ-19 established that a copy exists off this
machine; it did not establish that the copy is *correct*. Text moved through any transport —
a chat app, a clipboard, a retyped note — can gain a trailing space, lose a character, or pick
up a line break, and a Fernet key that is one byte wrong fails exactly as completely as a key
that was never saved.

The failure mode this closes is the worst-shaped one available: the disk dies, the encrypted
Dropbox copies are all present and intact, the saved key is produced — and it does not work.
Everything looks recoverable right up to the moment it isn't.

Scope: save the off-machine copy to a scratch file, decrypt a real backup set from the secondary
destination using that file via `CONTINUITY_KEY_PATH` (never overwriting the live `backup.key`),
confirm the restore verifies, then delete the scratch file. Same flag as TQ-19 for the same
reason — it decides whether a capability that is already built and running can actually deliver.

### TQ-22 — Boot configuration and a persisted lifecycle stage

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §71**

Source: addendum 39 §2, §4, §17; addendum 38 §2. Two absences with one shape: no non-secret
boot configuration exists (lifecycle scope lives in code constants), and `PRE_ALPHA` appears
nowhere in the codebase, so nothing can read the stage or alter behavior by it. Scope: a
`boot_config.json` carrying lifecycle stage, global/implemented asset classes, current focus and
simulation focus **in the built vocabulary** (§70 disposition 2 — `stock`/`stock_option`, not a
second naming scheme), loaded through one accessor rather than read from disk at call sites, and
a persisted stage the COO can read at startup. Deliberately not a second configuration framework
(39 §17's own warning).

### TQ-23 — Metadata Engine as a named, observable startup phase

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §72**

Source: addendum 39 §7, §12, §13, §14. The *work* already exists — schema init, seeding, the
fail-closed reference gate — but no component announces itself, verifies the four datasets
against boot configuration, reports counts, publishes `METADATA_READY`, and idles. Scope: that
component, over the datasets that already exist (§70 disposition 1 — `agent_names` and
`asset_classes`' three flags, never three new tables), strictly idempotent per 39 §13, with
`METADATA_READY` as the hard gate before the Reference Data Engine begins (39 §14). The one
genuine extension — a broader capability registry (39 §10) — stays out until a capability that
is not an asset class exists.

### TQ-24 — The status event stream (the observability spine)

**NEED (YELLOW) · DONE — `SPEC_RECONCILIATION.md` §73**

Source: addendum 38 §4.3, §4.6, §7, §12, §13. The largest genuinely new thing these specs ask
for, and what every other Milestone-1 item displays: structured operational events carrying
timestamp, lifecycle stage, source department/engine/agent, event type, severity, status,
message, and correlation id, durably stored (38 §4.6 explicitly does not require an enterprise
event store) and queryable. Flagged YELLOW because 38's Definition of Done is mostly
observability — §70's closing finding is that persistence is largely already satisfied and
observability is the gap. Must carry failure honestly (38 §12: a failed component must not
silently disappear, and dependents must not falsely report success) and must not flood (38 §13).

### TQ-25 — Server Superuser, and the login-gated COO start

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §74** (which resolves §70 disposition 4's conflict)

Source: addendum 39 §3; addendum 38 §3. Two parts. The easy one: `SERVER_SUPERUSER_ID`/
`SERVER_SUPERUSER_PASSWORD` behind an auth abstraction, deliberately *not* conflated with the
Gateway's own superuser (39 §3's explicit warning). The hard one: 38 §3.3 requires the COO not to
start before login, and `backend/main.py`'s lifespan bootstraps it unconditionally today —
addendum 18's lifecycle-managed initialization and §40's reference gate both assume that. The
reconciliation §70 proposes (server starts, workforce stays dormant until an operator
authenticates) is a real change to a startup path several increments touch, and is queued here
rather than smuggled in elsewhere.

### TQ-26 — The COO operator interface

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §76** (unblocked by the owner decision in §75)

Source: addendum 38 §4. The live status area and its filters: the *server console*, a live
newspaper covering everything the system is doing, served by the backend. The owner's decision
(§75) settled what this is relative to the Gateway — the Gateway is a door (an entry point into
the system), this is a window (the organization's whole internal life) — and how it differs from
`panel/` (control and state) and `monitor/` (client conversations): this one reports narration.
The COO chat that answers from real state is split out as TQ-27, being a different kind of work.

### TQ-27 — The COO chat, and the console's living desks

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §77**

Source: addendum 38 §4.5, §11, plus four owner requests made during the work. Built:
`backend/coo_chat.py` (grounded answering — the state is gathered first and handed over as the
only source of truth, with an explicit `not_built_yet` section so the COO can tell "idle" from
"does not exist", and an unavailable model reported rather than fabricated); a streaming
`/console/chat` so the reply is genuinely interruptible, with Escape stopping the stream, the
voice and the microphone together; ten languages defaulting to Tamil-accented English, with the
voice picker honest that the accent depends on OS-installed voices; `backend/finance_desk.py`
(a front page over this system's *own* simulated world, SIMULATED on every path, headlines
flagged as placeholders until newspaper agents exist); and `backend/chatterbox.py` (the living
collaboration map, where `silent` — a question that timed out — is its own state because
folding it into "not completed" would bury the actual failure).
### TQ-28 — The database-isolation guard trips after a real backend has run

**NEED (YELLOW) · QUEUED · found 2026-08-25 while verifying the console**

`tests/test_db_isolation.py::test_the_guard_reports_nothing_when_the_database_is_untouched`
fails on a full-suite run once the real `financial_intelligence.db` has a populated WAL — which
is what running an actual backend leaves behind. Established while investigating:

- It reproduces on the **committed** state (`b8b9067`), so it is not caused by the console work.
- It passes on small subsets and fails on both halves of the suite, so it is not one test file.
- With the real database made **read-only** the suite still reports a change and **no write
  error occurs** — so nothing is writing. Something merely *opens* the file, and SQLite updates
  or checkpoints the WAL on connect/close.
- The WAL is stable at rest with nothing running, so it is not an external process.

That last point is the useful one: the guard's docstring says it exists to catch "a leaked
write", but a leaked *open* produces the same signature. Scope: find the connection (it is
almost certainly a default-path `get_connection()` somewhere in a fixture or import), and
decide whether the guard should distinguish an open from a write — a guard that fires on reads
will eventually be disbelieved, which is the failure mode its own docstring warns about.

Worth doing before it gets normalised as "that test that always fails after you run the stack".

### TQ-29 — `remediation.corrective_items` takes minutes on a real database

**NEED (YELLOW) · DONE — `SPEC_RECONCILIATION.md` §80.** Four missing indexes on the columns
the compliance check correlates on: **195.9s → 0.01s** on the same real database, plan verified
SCAN-free and pinned by test. The console's Alerts desk has its recommendations back.

Measured against a real 146MB `financial_intelligence.db`: **195.9 seconds** to return two
rows. Every other console read on the same database is milliseconds. It was wedging the whole
console — polled every six seconds, the calls piled up, exhausted the worker pool and blocked
every other request — so it has been removed from the polled overview and the Alerts desk now
says the recommendations are not computed there.

This is a defect in `remediation`, not in the console: the analysis is presumably fine on the
small datasets it was built and tested against, and nothing had ever run it against real
history. Scope: find the quadratic (it aggregates findings against opportunities and rules out
prior work — the `_ruled_out` scan is the first place to look), bound or index it, and give the
recommendations a home the console can afford to draw. Until then the corrective analysis is
reachable only by calling it directly.

### TQ-30 — Native desktop shell, and the bootstrap invariant

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §82.** Native window, own runtime, clean sleep
(the first attempt orphaned twelve agents — `terminate()` skips uvicorn's teardown on Windows),
Start Menu shortcut with a matching AppUserModelID so the taskbar button is My AI rather than
Python, and the loopback requirement measured rather than assumed: an inline-HTML window has no
secure context and therefore no microphone.

Phase A's first half. A native window hosting the existing console rather than a reimplementation
of it (40 §18 Phase A: "move the existing web views into the shell ... without changing core
business logic"), with the COO runtime behind it. Plus 40 §4.1's hard invariant — "main.py must
not become the business application, it is a bootstrapper only" — enforced by a guard, because it
is the same class of rule as the import-time-side-effect check and degrades the same way: one
convenient addition at a time, unnoticed until the launcher owns half the system.

Verify in the first hour, not the last: whether the chosen shell's webview exposes speech
recognition (§81 risk 1). Voice is 40 §11's *default* path, and a shell that cannot hear is a
Phase B blocker discovered too late.

### TQ-31 — The living workspace: layout, view state, and the draft requirement

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §83.** §5.3 verified literally: a half-typed
sentence, a selected tab and a filter all survived killing every process with no shutdown. Saved
continuously server-side (the COO must be able to speak about the workspace), one transaction per
write, and a read that never fails.

Phase A's substance, and the part with the sharpest acceptance test in the whole document
(40 §5.3): "If the user types half a sentence and the machine crashes before Send, the same text
must be present in the same field after recovery." Unambiguous, cheap, impossible to fake.

Scope: continuous incremental checkpointing of tabs, selected filters, scroll and focus position,
and every editable surface's draft text; atomic writes so a partial save cannot corrupt the last
good state (§15); schema version metadata for forward migration; and restore-on-launch that makes
startup feel like waking rather than rebuilding. 40 §5.4's distinction is the design rule —
persist declarative state, reconstruct transient resources from it.

### TQ-32 — Voice and natural language as control surfaces over the views

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §84.** View commands are matched
deterministically and act with no model call (`backend/view_intents.py`); anything not recognised
with certainty falls through to the COO untouched, because swallowing a question would replace an
answer with a tab change. Questions plainly about one desk focus it *and* get answered.

Phase B. Much of this exists: the COO chat answers from real state (§77), and barge-in already
stops stream, voice and microphone together. What is missing is the *control* half — 40 §11's
"show that tab", "zoom in", "open the agent conversation": natural language changing the visual
focus rather than only answering. 40 §10's rule governs the design: natural language is another
control surface over one source of truth, not a second reporting system.

### TQ-33 — The live studio: the look, and the choreography

**NEED (GREEN) · DONE 2026-08-25 · addenda 41 §2/§5/§7/§14/§15/§19/§20, 40 §8.3–§8.5 ·
`SPEC_RECONCILIATION.md` §86**

Promoted from WANT to NEED, and widened: addendum 41 makes the *look* a requirement rather than a
preference, in the strongest terms the lineage has used. §18: "If an implementation looks like a
Bloomberg Terminal, it has failed the visual requirement." The console as built is exactly that —
dense, monospaced, terminal-flavoured — because an earlier owner instruction asked for it (§85
disposition 1 records the reversal honestly).

Scope: broadcast composition over terminal density — strong hierarchy, large surfaces, clean
typography, adaptive density (41 §19: low on overview, higher on drill-down); status treatment that
distinguishes active/waiting/completed/blocked/failed/needs-attention (§20); and the choreography —
bring a panel forward, dim what is irrelevant, expand, spotlight, restore, with restrained
camera-like transitions (§14, §15). Motion must be informative: 41 §7's "pointer behavior must
always correspond to real information. No meaningless animation."

**Deliberately without the human figure**, which stays deferred with its reason (§85 disposition 4).
Most of 41 §27's acceptance criteria are satisfied by this entry alone.

### TQ-38 — The server reports a dormant workforce while six agents are working

**NEED (RED) · DONE 2026-08-25 · `SPEC_RECONCILIATION.md` §87 · addendum 38 §3.3**

> Fixed. The cause recorded below is wrong in one detail and §87 corrects it:
> `reconcile_on_start` is read-only and only reports. The spawning came from
> `_controller_poll_loop`, which ran in full regardless of the gate — `watch_coo`
> revived the stale COO, which filed spawn directives that the same loop executed.
> The loop is now gated on the workforce having been started, and the console
> reports authorisation and observed liveness as two separate facts.

The dormancy gate and the controller's start-up reconciliation disagree, and the
console repeats the wrong one.

Starting the backend with no operator login and no `SERVER_AUTOSTART_WORKFORCE`
prints the intended banner:

```
= SERVER UP, WORKFORCE DORMANT. The COO and every agent wait for an operator
= login (addendum 38 §3.3).
```

Four lines above it, in the same log:

```
[COO] 6 agents (6 active) | not running: analysis-1, explorer-1, speculator-1
[speculator] enriched case #5673 (SYN1) with 3 new item(s)
[controller] reconciled on start: {'coo': 'stale', 'heartbeat_age_seconds': 6254.7}
```

Six agent processes were spawned as children of the server at the moment it
booted, and they did real work — the speculator enriched cases and the analysis
desk pulled a report past its starvation guard. The login gate governs
`_operational_startup`; reconciliation revives whatever the database still lists
as active, independently and without consulting it.

Two problems, and the second is the worse one:

1. **The gate does not hold.** A server told to wait for an operator does not
   wait. Whether reconciliation *should* be exempt is a real design question —
   an agent orphaned by a crash arguably should be recovered — but it has to be
   decided, not discovered.
2. **The console reports the opposite of what is happening.** `/console/status`
   derives `awaiting_login` from `startup_report is None`, so the briefing said
   "workforce dormant, awaiting operator login" while six agents ran behind it.
   A console whose entire purpose is to be a truthful window onto the
   organization stated the reverse of the truth, and would have gone on doing so
   indefinitely.

Flagged RED because (2) is the failure this system is least able to tolerate:
every other signal the operator has comes through that window.

Found by reading the log of a server started to look at a stylesheet — not by
the suite, which has no test that asserts a dormant server spawns no children.
That test is part of the fix.

### TQ-35 — Kumbhakarnan: the COO's identity as persisted state

**NEED (GREEN) · DONE 2026-08-25 · addendum 42 §3, §4, §19, §20 · `SPEC_RECONCILIATION.md` §88**

The COO gets a name that outlives the code. 42 §19: "changing implementation versions must not
silently replace the COO's identity." The principle already exists — `agent_names` makes a name the
durable agent and `AGENT_NAME_POOL` already reserves one name for the CEO — but the COO's identity
is not yet a first-class persisted object with its own id, creation timestamp, personality, voice
identity and visual identity, versioned separately from the software (42 §4's three version types).

### TQ-36 — The migration pipeline, and the developer's escape hatch

**NEED (YELLOW) · DONE 2026-08-25 · addendum 42 §7–§10, §14, §22, §23 ·
`SPEC_RECONCILIATION.md` §89**

Sequential `migrate_5_to_6`-style steps rather than one giant converter (42 §9), each deterministic,
logged and idempotent where practical; 42 §23's ordering (validate → backup → migrate → validate →
activate) so a failed migration never leaves the active state broken; and 42 §22's rule that a
snapshot failing validation is *preserved for diagnosis*, never destroyed.

Flagged YELLOW for the half that is easy to postpone and shouldn't be: 42 §14's development-mode
escape hatches — reset, load a specific snapshot, disable persistence, force migration, inspect raw
state. "Persistence must help development, not trap developers inside stale state" becomes a live
risk the moment identity is persistent, and the cheapest time to build the way out is before
anybody is stuck in it.

### TQ-37 — The presenter frame and the briefing rhythm

**WANT · DONE 2026-08-25 · addenda 41 §8, §9, §16, §21, §22 ·
`SPEC_RECONCILIATION.md` §90**

The presenter's *behaviour* without its body: a briefing that narrates what completed, what is
underway, what is blocked and what needs attention (41 §8), with the display tracking the narration;
41 §16's broadcast rhythm (main story → supporting graphic → interruption → drill-down → return);
and 41 §21's persisted presenter state — current topic, briefing position, pending interruption —
which is also the voice-interaction state addendum 40 §5.2 named and TQ-31 correctly deferred.

41 §22's failure isolation is the invariant to keep pinned throughout: the presenter "must never own
critical business state", so a presenter that dies takes nothing with it.

### TQ-34 — Role-based Gateway

**WANT · DONE 2026-08-25 · addendum 40 §13/§14, 41 §23, 43 §15/§16 ·
`SPEC_RECONCILIATION.md` §92**

Two owner clarifications during the work settled what addendum 40 §13.2 left as a heading with
no body: an operator logging into the Gateway sees **the same studio** the desktop console shows
(the same file, proxied, never a second console), and a regular user meets **an agent** — info
only today, with real skills to come. Both recorded in §92.

### TQ-44 — Portfolios as owned entities, with the guard that makes them safe

**NEED (GREEN) · DONE 2026-08-26 (`SPEC_RECONCILIATION.md` §99) · addendum 44 §3, §5, §9, §12,
§15.1, §15.5, §20 Phase 1+3 · spec: `docs/specs/TQ-44_portfolio_ownership_and_isolation.md`**

Phase 1 and Phase 3 together, and they were one entry on purpose. Holdings were keyed directly by
client, so there was no portfolio id to guess; introducing a `Portfolio` entity introduces the
guessable handle §5.2 spends four bullets on. The entity and the ownership guard therefore landed
in the same increment — an entity shipped a week before its guard is a week of exactly the
exposure this specification exists to prevent.

Built: `gateway/portfolios.py` (the `portfolios` table, `OwnerContext`, and `resolve()` — the one
gate), holdings re-keyed from `client_id` to `portfolio_id` with `asset_class`, and the migration.
`client_id` was removed rather than kept beside `portfolio_id`: two sources of truth for ownership
can disagree, and the one that disagrees quietly hands somebody the wrong positions.

The spec's three open questions were decided before any code and are recorded in its §10 — the
migration lives in `gateway/store.init_schema` because `backend/migrations.py` would have announced
a backup that did not contain `gateway.db`; `client_holdings` is renamed rather than dropped, which
doubles as the idempotency mechanism; migrated rows get the literal `UNKNOWN` asset class, because
`EQUITY` would be a guess.

**No superuser branch** (§5.3): one ownership comparison, both owner domains through it, tested from
both sides. §15.5's permanent regression exists —
`test_a_client_cannot_receive_the_superuser_portfolio_when_it_is_the_only_one` — reproducing §93's
conversation leak in portfolio form.

Migration verified against a copy of a genuinely pre-TQ-44 database, seeded by the old code from a
worktree at `74f8fbe`: 11 holdings across 4 clients, 11 after, no orphans, no owner changed.

Two clients then logged into a running Gateway and each saw only their own portfolio. Asked in
conversation for another client's holdings, the representative refused; asked for market value, it
refused and said why. Suite 2232.

Left deliberately for the entries that own them: the holding field rename (TQ-45, spec §3.9), the
Superuser portfolio itself (TQ-46), and `app/tools/portfolio.py`'s missing owner argument (TQ-46).

### TQ-45 — The PortfolioProvider abstraction, and its conformance suite

**NEED (GREEN) · DONE 2026-08-26 (45a `SPEC_RECONCILIATION.md` §100, 45b §101) ·
depends on TQ-44 (done, §99) · addendum 44 §7, §6.3, §15.3, §15.4, §20 Phase 2 ·
spec: `docs/specs/TQ-45_portfolio_provider_abstraction.md`**

Split into **45a** (the canonical holding shape) and **45b** (the provider, the conformance suite
and the demo rebuild), so the provider is written against the final holding shape once rather
than twice.

**45a is done** (§100). Holdings are `symbol` / `quantity` / `average_cost` / `as_of`, and
`asset_class` speaks the house vocabulary — `stock`, `stock_option`, … plus `unknown` — imported
from `reference_data` rather than mirrored, because §70 had already refused that substitution
once. Both migration paths were verified against genuinely old databases seeded by the old code
in a worktree. Running it found a defect no test saw: `clear()` emptied the live table while ten
demo holdings survived in the retired one, and `outstanding()` reported clean. Fixed, with two
permanent regressions.

**45b is done** (§101). `PortfolioProvider` is a Protocol whose data-reaching methods take a
*resolved portfolio* rather than addendum 44 §7's `account_ref` — a public function taking a bare
reference is the by-id bypass TQ-44 exists to prevent, one layer below where the tripwire looks.
`ManualPortfolioProvider` and `SimulatedPortfolioProvider` both satisfy a conformance suite written
before the second one existed, and they genuinely differ in what they can answer, which is what
makes `supports()` a contract rather than a decoration. The demo clients are rebuilt on §6.1's
diversity, including a covered call — which is *short*, and forced a decision about how a short
position is counted and why it must not be weighted.

The suite was mutation-tested rather than trusted: five deliberate breakages, and the one it
initially **missed** was the §3.2 bypass it exists to prevent. Widened, it then caught a violation
in this increment's own code. All five open questions in the spec are now decided and recorded.

`PortfolioProvider` with `list_accounts` / `get_account` / `get_holdings` / `get_balances` /
`get_positions` / `refresh` / `health_check`, returning canonical internal objects rather than
broker shapes (§7). `SimulatedPortfolioProvider` first, implementing the same interface a
brokerage provider will (§6.3), so the switch is an adapter rather than a rewrite.

§15.4 asks for **one conformance suite every provider must satisfy**, which is the part worth
building before there are two providers: a contract with a single implementation is a
description, and the suite is what turns it into a contract. Written so `SchwabPortfolioProvider`
inherits it unchanged.

Also rebuilds the demo clients on the provider interface. §96's three clients (`customer`,
`avery`, `morgan`) predate it and are seeded directly; addendum 44 §6.1 wants distinct
portfolios per client with the diversity it names — large-cap plus a covered call, growth plus
long calls or protective puts, diversified plus cash — which needs `asset_class` from TQ-44.

### TQ-69 — Move the portfolio subsystem behind the backend, where authorization lives

**NEED (ORANGE) · DONE 2026-08-26 (`SPEC_RECONCILIATION.md` §110) · unblocks TQ-46 ·
owner direction 2026-08-26 (§109) · addendum 16 §7, addendum 40 §14 ·
spec: `docs/specs/TQ-69_portfolio_subsystem_behind_the_backend.md`**

Owner direction: *"Gateway is for establishing identity — Gateway only does authentication. Back
end does authorization and all business logic."*

`gateway.db` holds nine tables and two of them are authentication. `portfolios` and
`portfolio_holdings` — with the ownership guard that authorizes every read of them — are business
logic sitting in the process specified to do none. Addendum 16 §7 says external clients must not
reach internal databases; the Gateway holding the database is the same boundary crossed from the
other side.

Scope: `portfolios`, `portfolio_holdings`, `gateway/portfolios.py`'s guard,
`gateway/holdings.py` and `gateway/portfolio_providers.py` move backend-side. The Gateway reaches
them over HTTP, the way `gateway/jarvis.py` already reaches `/admin` — read-only enforcement in the
one method that touches the network, which is the pattern that already exists rather than a new
one.

**None of the work in §96, §99, §100, §101 or §106 is wasted.** The ownership guard, the canonical
holding shape, the provider contract and the routing decision log are all correct and all
portable. What changes is which process owns the table and which process authorizes the call —
and the guard gets *stronger*, because a Gateway request then passes a backend authorization check
it currently is the only check for.

Flagged ORANGE, not for difficulty but for blast radius: it moves live client financial data
between databases, and §99's rule stands — test against a **copy** of a seeded database, and the
§15.5 regression must still pass at the end, from the Gateway's side, over HTTP.

Two things to settle before building, in the spec this entry needs:

- **Does the Gateway keep a read-through cache?** §23 wants the Gateway usable when an internal
  component is down, which is the reason it has local storage at all. A portfolio it cannot reach
  is different from a conversation it cannot reach — showing somebody stale holdings is worse than
  showing them nothing. Leaning: no cache, and an honest refusal when the backend is down.
- **What happens to the client agent, conversations and the scoreboard?** Same category of drift
  (§109), deliberately not moved here. Moving four subsystems because one needed it is how a
  boundary correction becomes a rewrite.

**Specified 2026-08-26.** Writing it turned up the thing that shapes the increment: **this system
has three separate identity populations** — backend users (`users.json`), Gateway clients
(`clients` in `gateway.db`), and environment credentials — and `gateway/auth.py` says the
separation is deliberate. So "move portfolios to the backend" contains a question that is not
about tables: whose id owns a portfolio once the owner and the store are in different processes.

Decided: **the backend stores `owner_id` opaquely.** It never learns who Gateway clients are; the
Gateway authenticates and asserts a subject, the backend authorizes that subject against that
portfolio. That is exactly the owner's division, and it keeps the increment small — reconciling
the three populations is a much larger change nothing here needs (spec §10 Q2).

Stated so nobody overclaims it: **the move does not defend against a compromised Gateway**, which
can assert any owner it likes. It defends against a *buggy* one — which is the failure this project
has actually had twice, in §93's conversation leak and §106's privacy-misrouting finding, neither
of which any second check existed to catch.

A second find, which unblocks TQ-46 more cheaply than expected: `backend/main.py`'s `/chat` already
resolves `username = Depends(get_current_user)` and hands it nowhere near `retrieve_portfolio`.
§16.7's "ownerless retrieval" is not missing an identity mechanism — it is discarding one it
already has.

**Done** (§110). The tables, the guard, `holdings` and the providers are in
`financial_intelligence.db`; the Gateway reaches them over HTTP through
`gateway/portfolio_client.py`, behind `require_gateway` (`app/gateway_auth.py`). Suite 2462 →
**2497 passing, 1 skipped**.

The three §10 questions were decided and recorded before any code: the routing decision log stays
in `app/` (confirmed by reading its twenty-seven columns and `task_signature`'s fifteen fields —
none of them carries client content, so there is no second copy to leave outside the guard); the
identity populations are not reconciled here and the question is queued as **TQ-70**; and which id
owns the SUPERUSER portfolio is flagged into TQ-46's spec as its Q4 rather than settled cheaply
here.

**The migration's ordering is its design.** Two files cannot be written atomically, so: bring the
source to the current shape, copy inside the destination's transaction, **verify while the source
is still intact**, and only then rename to `*_pre69`. Verification is by *ownership* rather than by
count — a move that landed every row and swapped two owners would pass a count check perfectly, and
would be the worst outcome the increment could have.

**`gateway/store.init_schema` refuses to start on an unmigrated database.** Not a warning, because
the failure it prevents does not look like one: the client is not shown an error, they are given a
brand-new empty portfolio while their real one sits unreachable, and holdings recorded into the new
one are hidden by a later migration.

Verified live, all three steps, against `gateway.db` seeded by the pre-TQ-69 code in a worktree and
made harder than the happy path (an archived portfolio, an unflagged holding stated in
conversation, a SUPERUSER portfolio): migrated a copy with every id, owner and `as_of` identical;
two demo clients over real HTTP against both running processes seeing only their own; and the
backend **killed** underneath a live Gateway, where all four holdings tools returned
`{error, unavailable}` and nothing else.

Mutation-tested twenty-six ways across four rounds, which found two real defects — a test that was
green for the wrong reason, and an import tripwire that matched one spelling and missed the
ordinary one. That is the fourth scanner in this project to be wrong while the module it guarded
was right (§101, §104, §107).

### TQ-72 — Unwind server-side portfolio custody

**NEED (ORANGE) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §116) · owner direction 2026-08-26
(§111) · reversed the storage half of §96, §99, §100, §101, §110**

**Done.** Suite 2525 → **2407 passing, 8 skipped** — about 120 tests over a table that no longer
exists, replaced by roughly 60 denser ones. Mutation-tested nine ways, nine caught by the test
written for each.

`holdings.concentration` needed **no edit at all**: §101 built it to take *holdings, not a
connection*, so a contract test could not pass trivially, and that decision turned out to be what
made the analysis portable across the removal of the entire storage layer. The provider contract
survived for the same reason — the tests that had to go were exactly the ones its own guard
(*"could a provider that must make a network call satisfy this?"*) would have caught.

**A defect surfaced while repointing `retrieve_portfolio`.** It read one file for every account,
recorded in `test_multi_user_isolation.py` as *"a single shared file by design"*. It was not a
design; it was the ownerless retrieval wearing a second hat, and a fully-granted second account
read the first's positions with no code wrong anywhere. The source path is now derived from the
authenticated username with **no fallback to a shared location** — a fallback is how one account
reads another's file the day their own is missing.

**`require_gateway` was deleted one increment after being built**, and deliberately: it existed to
make an *asserted owner* safe to accept, and no route accepts one now. A gate with nothing behind
it is worse than none, because the next person to add a route sees it and assumes it applies.

Owner direction: *"The portfolios don't live in this system… the system only processes portfolios
for clients… and holds no information of the portfolios in the system."*

Remove the custody. `portfolios` and `portfolio_holdings`, the storage half of
`backend/portfolios.py` and `backend/holdings.py`, §110's migration and `/portfolios` surface, and
most of `gateway/portfolio_client.py`.

**Nothing has to be extracted first, and that was checked rather than assumed** (§111):
`financial_intelligence.db` carries neither table, `gateway.db` does not exist on this machine, and
the only rows that ever existed were demo data in scratch copies. This is a code reversal, not a
client-data extraction — which is timing rather than care.

**What survives is most of it**, because most of it was never storage. `holdings.concentration` is
already a pure function over supplied positions — §101 made it take *holdings, not a connection*,
and that decision now pays for itself. The canonical holding shape, `PortfolioProvider`,
`is_priced`, the asset-class vocabulary and the consent flow all stand.

Three things must not be lost while the tables go:

- **Isolation does not disappear, it moves.** `resolve()` answered "whose stored row is this?", and
  with no stored rows that question goes — but addendum 44 §9.4's does not: **an agent retaining
  one client's portfolio context while serving another.** Isolation becomes a property of a
  request's lifetime rather than of a table, and §15.5's regression needs rewriting in that shape
  rather than deleting.
- **"Never stored" must be enforced, not intended.** A rule that lives only in prose is one a
  future increment breaks while adding a helpful cache. It needs what `is_priced` and the ownership
  guard got: a scan that fails.
- **Every durable writer owes the audit §106 already passed.** TQ-69 §10 Q1 confirmed
  `routing_decisions` holds no client content; under this architecture that stops being a happy
  finding and becomes a requirement. The audit log, transcripts, status events and anything logging
  a tool result owe the same check.

### TQ-78 — Consolidation: several sources, one view

**NEED (GREEN) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §117) · addendum 9 §3, §112 · chosen
ahead of TQ-73 and TQ-76 (reasoning below)**

Built as `backend/consolidation.py`. All four decisions below were made and are recorded in §117:
merge by symbol, an asset-class disagreement becomes `unknown` rather than a guess, a long and a
short at different brokers keep their legs, `as_of` is the **minimum** across sources, and a
partial consolidation is never reported as complete.

Addendum 9 §3, canonical since August 2026 and never built:

> *"Normalize and reconcile positions sufficiently to analyze the portfolio as a whole. Combine
> duplicate or overlapping exposures where appropriate."*

And §112, the owner stating what the product is:

> *"Client needs consolidated portfolio analysis that is usually not provided by discount
> brokers."*

**A broker can already show a client their own account. The consolidation is the thing being
sold**, and nothing in this system does it. Every caller handles exactly one source:
`app/tools/portfolio.py`, `gateway/demo_clients.py` and the provider interface itself all take a
`Source`, singular, and `holdings.concentration` takes one flat list in which the same security
held at two brokers appears as two unrelated rows.

### Why this, ahead of TQ-73 and TQ-76

Both were offered as next. Both are blocked in ways their own entries do not name, and both
**assume this exists**:

- **TQ-73** is *"the credential envelope and the stateless fetch/analyse pipeline"*. Its envelope
  waits on an unanswered design question (what the encryption defends against, §113); its fetch has
  nothing to fetch from until the owner has broker API access; its valuation waits on TQ-75. What
  is left that is buildable today is *"the reconciliation across sources"* — this entry. Its own
  text says every interface must take **sources, plural, from the first line**.
- **TQ-76** is the curriculum. §114 established that there is **no Portfolio Analyst agent** — a
  curriculum with no student — and its grading dimensions begin *"did it reconcile two sources into
  one position"*. It cannot grade behaviour that does not exist.

So the shared prerequisite neither entry names is the reconciliation itself. Building it first means
TQ-73's envelope has something to carry credentials *for*, and TQ-76 has a behaviour to grade.

Chosen over the other shared prerequisite — the Portfolio Analyst agent — because an agent without
consolidation is a wrapper around `concentration`, which `/chat` effectively already has. The agent
is worth building once there is something worth tasking it with.

### The decisions this increment has to make, and none of them is obvious

- **What merges.** Two sources reporting `SYN1` are one position. Two sources *disagreeing about
  its asset class* are not a merge, they are a conflict — and picking one would be the fabrication
  §100 refused when it declined to map `EQUITY` to a house code.
- **Whether a long at one broker and a short at another net to nothing.** Economically they offset;
  reporting `0` would erase two real positions with two cost bases and different tax treatment.
  §101's rule about shorts, one level up.
- **How fresh a consolidated view is.** Its sources were fetched at different times, so it is
  current as of **none of them**. §17: *do not silently claim it is current.*
- **What happens when one source of several fails.** A partial consolidation presented as complete
  is a portfolio missing an account, and the client cannot see which.

### TQ-79 — The Portfolio Analyst, and the transport that keeps nothing

**NEED (GREEN) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §117) · addendum 9 §2, §3 · §112, §115**

The role addendum 9 §2 specifies and `docs/README.md` had listed as *"Not built"* since the
addendum-12 gap analysis. Built as `agents/portfolio_analyst.py` and `backend/analysis_requests.py`.

The problem it had to solve was not the analysis. Every other agent here reads a queue in the
database and writes results back to it; §111 says client data is never retained. The resolution is
that **the database is a transport**: delete-on-read, discard-on-disconnect, expiry enforced on read
rather than by a sweeper.

**What it does not solve, and is not claimed to:** a subprocess agent cannot be handed a secret
through a table without the secret landing on disk. `_refuse_secrets` refuses any source descriptor
carrying a credential key, so the transport carries *which source* and never *how to open it*. The
credential path remains TQ-73's.

### TQ-80 — The silently partial account, detected

**NEED (GREEN) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §118) · owner direction 2026-08-27
("close the known gap") · §100, §104, addendum 9 §3**

TQ-76's curriculum shipped `portfolio.detects_a_silently_partial_account` as a declared `KNOWN_GAP`,
failing loudly. This closed it.

The defect: the analyst treated **the positions it received as all the positions there are**, so a
broker whose positions endpoint truncated produced a report naming no failure and flagging nothing.
An absence defaulted to the favourable value, which §100 and §104 forbid everywhere else.

The fix: providers assert `position_count` on the account; the base returns `None` and refuses to
count what it returned; `SourceAnswer` carries holdings and the expected count; `complete` became
`not failures and not incomplete and not unconfirmed`. Unknown suppresses the completeness claim
without inventing a shortfall.

Mutation testing forced one further change worth naming here: an analyst that simply **stopped
asking** passed the exercise, because every view became unconfirmed and the client's complaint was
suppressed. `Exercise.must_report` now requires the detection to *appear* — absence of complaint is
not evidence of competence. 8/8 mutations caught by the test written for each.

### TQ-84 — The living documentation, which does not exist

**NEED (ORANGE) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §122) · addendum 47 · ahead of TQ-81
(reasoning below)**

Built as [`docs/JARVIS.md`](JARVIS.md), with `tests/test_living_documentation.py` keeping it current
by failing rather than by anyone remembering to. Custody per the owner directive of the same day:
one writer, declared in `docs/document_custody.yaml`, refused at `gateway/repositories.py::publish`
— which turned out to be an open write path into the repository from inside the running system.

**One thing it did not do:** `HANDOFF.md` is not retired. §121 concluded it should be; owner
direction was to keep it for the next session change. It carries a staleness notice instead.

Addendum 47 §2 requires **one** authoritative structure that new specifications are merged into.
This project has forty-one verbatim addenda, a 10,900-line append-only decision record, a 2,200-line
queue, a stale handoff, a gap analysis, a design spec marked stale since 2026-08-16, and a
documentation plan proposed the same day and never executed. **What it does not have is the
document addendum 47 is about.**

### Why ahead of TQ-81

47 §20: *"External development tools such as Claude Code should use the living documentation as a
primary source of architectural truth during the bootstrap phase."* Every entry below it — Parliament,
the governed-knowledge layer, the Software Engineering Department — is work whose whole purpose is to
be handed over to agents who will read documentation rather than reconstruct the system from source.
Building the handover target last is the same ordering mistake as building a curriculum before there
was a student (§117).

It is also the cheapest of the four and the only one with no unresolved design question.

### What it is, and what it is not

- **It is not another file beside the others.** 47 §2's whole point is that adding one more document
  makes the problem worse. It replaces `README.md`'s role as the map and retires `HANDOFF.md`, whose
  job — *"a session with no memory of the conversation that produced this state"* — is 47 §26's
  target end state stated in smaller words.
- **It does not absorb the change record.** `SPEC_RECONCILIATION.md` is what 47 §23 calls change
  traceability, and 47 §22 says history *"should not clutter the main readable document"*. The living
  document states the current truth; the record says how it got there. Neither replaces the other.
- **It does not edit the addenda.** They are provenance, not documentation (§121).
- **Status per 47 §10**, at component level only — 47 §11 forbids turning it into a project-management
  database, and detailed tracking is what this file is for.
- **Unfinished ideas must be labelled** (47 §17), so nothing reads as built that is not.

The hard part is 47 §12 step 11-12 and §24: *"Does the document still make sense as one story?"*
Forty-one addenda contain several superseded designs — stored portfolios (§111), the ownerless
retrieval, the pre-TQ-72 custody — and merging them naively produces a document that describes three
architectures at once.

### TQ-86 — An agent that actually reads the governed data before acting

**NEED (ORANGE) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §126) · addendum 46 §3, §8 ·
addendum 30 §12 · §125**

Built as `backend/operating_context.py`, wired into `register.file_entry`. A resolution carried
live, an instrument adopted under it, and the register began refusing submissions without a source
reference — **with no code change**.

The finding: **code cannot obey prose.** An instrument carries `text` for people and an optional
`requires` payload for machines; one without a `requires` is reported as *prose only* rather than
silently treated as satisfied. And an obligation nothing understands is **refused, never skipped** —
accepting it would produce a rule that was voted through, is reported as in force, and changes
nobody's behaviour.

**What remains** is named at §126 §6 and queued as TQ-87: one code path reads its context, not the
organization.

TQ-82 built the store. **Nothing reads it.** Every agent still behaves as its code says, which
means the organization can now change a rule by vote and no agent's behaviour changes — the
governed layer is a filing cabinet until something consults it.

Addendum 46 §3 is the requirement, and it is the whole premise of the data-driven architecture:

> *"An agent may read new information, interpret it, incorporate it into its operating context, and
> modify its decisions and behavior accordingly… A behavioral change does not automatically imply a
> software change."*

### The decisions this has to make, and none is obvious

- **When does an agent read?** Every cycle is expensive and every startup is stale. Something has
  to notice that an instrument changed.
- **What does an agent do with a rule it cannot follow?** Refuse the work, do it the old way, or
  escalate. Silently ignoring an instrument it did not understand is the failure that makes the
  whole layer decorative.
- **How is compliance visible?** An agent claiming to follow a policy and an agent following it look
  identical from outside — TQ-80's lesson, one level up. Absence of complaint is not evidence.
- **Which levels bind which agents?** A department policy binding an agent in another department is
  either a bug or a law, and the store cannot tell them apart today.

The natural first subject is addendum 46 §39's own worked example: interdepartmental requests
carrying requester, objective, priority, deadline, dependencies and acceptance criteria.

### TQ-87 — The rest of the organization reads what governs it

**WANT · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §127) · addendum 46 §3 · §126**

Explorer, Speculator and the admin register route now check what governs them, refuse when an
instrument is not satisfied, and record what they acted under. A second obligation kind
(`minimum_count`) earned by a real consumer, and a tripwire that fails if any filing site stops
naming its filer.

**Found by running it:** a refusal raised inside a live agent printed as `work_fn error` - true of a
broken agent, false of one obeying the organization. An organization whose policies make its agents
look broken will have its policies removed by whoever watches that stream. `GovernedRefusal` now has
its own voice.

**Still ungoverned:** Analysis and the COO. Grading and directing are the two behaviours most worth
governing, and neither has an obligation kind that fits - which waits for a rule somebody actually
wants rather than a kind invented in advance.

TQ-86 wired one code path. The Explorer, the Speculator, the Analysis agent and the COO still act
purely on their code, so a resolution binding them changes nothing.

Three things this needs that TQ-86 did not:

- **An obligation kind per behaviour.** `required_fields` fits a submission. What fits *"file a
  report only when the evidence meets this bar"* is a different shape, and inventing kinds without a
  behaviour to obey them would be the registry claiming a mechanism that does not exist.
- **A filer on every call.** `file_entry(filed_by=None)` files as ungoverned, honestly recorded and
  still a hole: a caller that omits the filer is not governed. Closing it is a sweep across call
  sites rather than an increment.
- **Re-reading.** A context is built when work happens; nothing notices an instrument adopted
  mid-cycle. No agent needs that yet, which is why TQ-86 did not build it.

### TQ-88 — Simulation exercises the governed organization

**NEED (GREEN) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §128) · owner direction 2026-08-27 ·
addendum 34, addendum 46**

`simulation/seeding.py` and `governed_organization.yaml`: **11/11 properties pass** on a live run
with the Articles in force, an instrument binding every role, eight reports filed under it and none
outside it. TQ-89 was done in the same increment once `developing_story` and `saturation` gave the
evidence.

**Three defects the runs found, none visible in 2,636 passing tests:** `governed_by` recorded the
literal string `"ungoverned"` as though it were an authority; the archive trigger destroyed
`governed_by` the moment a report was judged; the Speaker wrote three hundred rows in three hundred
seconds. All three fixed and pinned. §128 §8.

Owner direction: *"I want all simulation issues dealt with first so that we can have end to end
simulation and make sure everything works as intended."*

A survey of every active scenario found that **governance is exercised by no scenario at all**. Four
increments built Parliament, the Articles, the governed store and agents that obey instruments, and
every simulation still measured an organization for which all of it was decoration.

A scenario was only ever a set of `FI_*` environment variables, and governance lives in rows — so
this adds a `seed` to the scenario vocabulary, applied before the Controller starts, **through the
production API and never through SQL**. A fixture able to build states the organization cannot reach
measures the fixture rather than the system.

Also closes two vacuities the survey exposed in `baseline_steady_state`: nothing asserted the
pipeline moved at all (so `unanalysed_completed_reports == 0` passed over zero completions), and
nothing watched the Speaker, which joined the baseline population in TQ-81.

### TQ-89 — The queue-pressure metric cannot tell saturation from growth

**NEED (YELLOW) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §128) · re-aimed, not deleted**

`queue.retirement_ratio` replaces it: 0.2 over ninety seconds, 0.8 over three hundred. The bar sits
loose in the control run, where ten arrivals move the measure 0.1 per completion, and tight in
`developing_story`, where five minutes make the sample worth something. `pressure_ratio` is still
reported and no longer asserted.

`saturation` answered its own question in the same survey: max depth 10 against a structural ceiling
of one report per producer per security. **It saturates.**

`baseline_steady_state` fails one property: `queue.pressure_ratio` reads **22.01** against a ceiling
of 5.0 documented from measurements of 1.89 and 3.15.

**The organization has not regressed; the metric is reading a burst.** `pressure_ratio` is
`drain_interval / arrival_interval`, and `saturation.yaml` already characterised why arrivals come
in a burst: *"discovery agents check has_pending_report before filing, so at most one report per
producer per security can be waiting. With ten securities under observation that puts a ceiling on
the backlog no matter how slow judgment is."* Ten reports arrive in eleven seconds, the producer
goes quiet because every security's last report is unconsumed, and the ratio measures intra-burst
spacing against a drain rate that is unchanged.

That is the exact distinction `saturation.yaml` exists to settle — *"a queue that grows without
bound and one that saturates at a fixed depth need completely different fixes"* — and the metric
asserted against cannot make it.

**Re-aimed, not deleted** (§105, §110, §116). The concern is unchanged: does the backlog grow
without bound. A burst-insensitive statement of it is what this needs, measured from the saturation
run rather than guessed — the same discipline `TIMING_CONSTANTS.md` records for every other number
whose correctness depends on a rate.

### TQ-90 — A governed refusal is recorded nowhere

**NEED (YELLOW) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §130) · addendum 46 §17**

`governed_refusals` records who was refused, on what subject, by which instrument, and **which
obligations were unmet by name — never their values**. Written at the check rather than at the call
sites, so a new call site inherits the record along with the enforcement.

`misdrafted_instrument.yaml` demonstrates the case it exists for: a rule requiring a field nothing
produces. Zero reports, zero analyses, zero arrivals, a hundred cross-checks exchanged, seven agents
healthy, no respawns, no failed directives — **and 91 refusals**. Before this the run was
indistinguishable from a quiet market.

When an instrument in force refuses a filing, the agent says so on stdout and **nothing is written
down**. The organization cannot count its own refusals, no metric can assert on them, no scenario
can require one, and nothing can notice that a rule is refusing everything.

That last case is the dangerous one: a badly drafted instrument that rejects every report looks
exactly like a quiet market.

`status_events` already exists for durable narration and is the natural home. What it needs deciding
is what a refusal record may contain — a report's summary is the organization's own, not a client's,
so §111 does not bite here, but the rule should be stated rather than assumed.

### TQ-91 — The two simulation systems have never met

**WANT · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §129)**

`python -m simulation verify` runs every runnable scenario and the whole curriculum and gives one
verdict. **Not merged** — a scenario measures the organization operating and a curriculum measures
an agent learning, and the seam is real. What was missing was a verdict, not a merge.

The verdict has three values: `INCOMPLETE` is not a softer `FAIL`. **A scenario that did not run is
not a scenario that passed**, and only `PASS` exits zero. It prints what it does not cover with
every verdict, so a green line means something specific and limited.

There are two: `simulation/harness.py` runs the real organization in its own database under a
scenario, and `simulation/training.py` runs the Department of Education's curriculum against
simulated exchanges and clients. **Neither knows the other exists.**

A curriculum exercise cannot be a scenario property, a scenario cannot run a curriculum, and
"everything works end to end" currently means two different things depending on which was run.

Not obviously one system: a scenario measures the organization operating, a curriculum measures an
agent learning, and merging them for symmetry would be the kind of tidying that costs more than it
returns. What is worth having is one command that runs both and one report that says whether the
organization works — which is nearly all of what the owner asked for and is cheaper than a merge.

### TQ-92 — Read the cooperation the organization already records

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §149 · addendum 48 §3, §12, §13 ·
addendum 37 §9, O9 · `SPEC_RECONCILIATION.md` §131**

`backend/cooperation.py`, and **the refusal is the design**: no score and no ranking, asserted over
the parsed module, because addendum 48 §12 forbids exactly what a cooperation score produces. It
reports *composition* — answers with a finding, answers honestly empty, and how often the agent was
itself left waiting — and refuses to collapse them, because what counts as enough depends on what
the agent does.

`left_waiting` is counted against the **asker**: an unanswered cross-check names a role and never
acquires a responder, so attributing it to a person would be inventing a culprit.

**Reading the existing evidence found two more checks that could not fail** (§149 §3): the schema
comment beside `outcome` named `'answered'`, a value nothing has ever written — the first draft
trusted it and matched nothing — and `metrics.open_at_end` filtered on `status = 'open'`, which is
not in the vocabulary, so `baseline_steady_state`'s *"no cross-check was left open"* has been
asserting a tautology in every run ever made. Both re-aimed.

Nothing reads the report yet, which is named rather than left to be found.

<details><summary>The entry as it was queued</summary>

Addendum 48 §3 makes cooperation a measured property and a condition of leadership. Addendum 37 O9
has said the same since it was assimilated: *"No agent may qualify for leadership without
demonstrated collaboration."* Both were read as unbuilt because nothing scores cooperation.

**But the evidence is already being written.** `cross_check_requests` records one agent asking
another for help and the answer coming back or not; `cross_check.unanswered_rate` is precisely a
measure of one agent leaving another waiting, and it has been a scenario property for a long time
under a timing rationale rather than an ethical one.

So this is not a new score. It is reading what exists as what it is:

- **cooperation per agent**, from cross-checks answered against cross-checks received, and from
  UQI answers;
- **reported by role**, because an agent that answers nobody is a fact about that agent;
- **no invented threshold.** What counts as insufficient cooperation depends on what the agent does,
  and a number nobody measured would be a policy wearing a measurement's clothes.

### What this must not become

A cooperation score that agents are ranked on is a metric agents will optimize, and §12 of the
Scripture forbids exactly the resulting behaviour — *"empty activity, performative work, needless
conflict, and actions that create work without creating value."* An agent that answered every
cross-check with nothing to raise its number would score perfectly and cooperate not at all.

The measure has to be of *outcomes* — was the asker helped — rather than of *activity*. That is the
same distinction §118 drew between detecting something and no longer claiming to know, and it is
the hard part of this entry.

</details>

### TQ-93 — A liveness signal that does not wait for the work to finish

**NEED (YELLOW) · DONE 2026-08-28 (`SPEC_RECONCILIATION.md` §134) · `TIMING_CONSTANTS.md`**

Split into two signals. `last_liveness_at` is emitted by a daemon thread on its own five-second
clock with its own connection; `last_heartbeat_at` still means a cycle completed. COO's crash
detection reads liveness, so an agent inside a slow model call is no longer mistaken for a dead one,
and an agent that emits no liveness is judged by progress exactly as before.

**The threshold now depends on a rate this system sets** rather than on the slowest call of a
vendor's model — nine ticks inside 45 seconds. That is the resolution of §133's finding, and it was
reached by changing what the number depends on rather than by raising it.

Slow-but-alive is reported and not acted on, once per episode and again on recovery: an agent slow
for ten minutes with nobody saying so is the other failure.

An agent's heartbeat advances when its work returns. `agents/analysis.py` already heartbeats
immediately before every model call - the fix for the 10s threshold that once duplicated a
busy agent - but that bounds the gap at **one model call**, not at ~10s, and a full
`simulation verify` observed a 45.2s gap while the agent was alive and working.

COO respawned it. The incident closed as `recovered` with `action: heartbeat resumed (1.0s old)`,
which is the organization correctly noticing it had been wrong - after spawning a duplicate.

### Why a bigger threshold is the wrong fix

The gap is bounded by the slowest single model call, and that is set by a vendor rather than by this
system. Any threshold chosen to sit above it is chosen against a number nobody controls, and every
increase makes the detector slower to notice a genuinely dead agent. **That trade is what
`TIMING_CONSTANTS.md` exists to stop being made by guess.**

### What this needs to decide

- **Whether liveness and progress are the same signal.** They are currently one field. An agent
  inside a slow call is alive and not progressing, and nothing can currently say so.
- **Who emits it.** A background thread heartbeating on its own clock is the obvious answer and
  makes the signal say *"the process is up"* rather than *"the work is moving"* - which is a
  weaker claim, and the weaker claim may be the true one.
- **What COO does with two signals.** A stale *progress* signal on a live process is a different
  event from a dead process, and only one of them warrants a respawn.

Until this lands the threshold stays where a measurement put it and the property that catches the
symptom stays where it is: **the verification is intermittently red for a real reason, which is the
correct state for a suite to be in.**

### TQ-94 — A fault that makes an agent slow rather than dead

**NEED (YELLOW) · DONE 2026-08-28 (`SPEC_RECONCILIATION.md` §136) · addendum 29 §15**

`slow_agent.yaml` stalls one model call for ninety seconds through `SlowProvider`, a decorator in
the same shape as `BudgetedProvider`. Live: COO reported *"analysis-1 is alive and its work has not
advanced for 45s. Not a crash and not being replaced"*, then *"advancing again"* sixty-eight seconds
later, with **zero incidents and zero respawns**. Before TQ-93 that exact stall opened an incident
and replaced the agent.

Injected at the model call rather than at the process, because SIGSTOP would stop the liveness
thread too and test the mechanism backwards. Outside the budget wrapper, so a stalled call costs
what a slow real one would.

`population.slow_reported` and `slow_recovered` are new metrics, because **a scenario cannot assert
on a condition it cannot see** — which is what made §135's green silent about the thing it was built
to check.

`simulation/faults.py` can `kill`, `stop` and `lock_database`. **All three produce a dead agent**,
and the condition this organization has actually been getting wrong is a *live* one: an agent inside
a slow model call, alive and not advancing, which COO twice mistook for a crash.

The first fully green verification (§135) did not exercise it. Zero `agent_slow` events across nine
runs, because nothing was slow past the threshold — so `no agent was respawned` passing is
consistent both with the fix working and with the condition not arising. **A green run over a
condition that never happened is not evidence about the condition.**

### What it has to do, and what it must not

- **Make an agent slow without making it sick.** Pausing the process (SIGSTOP) also stops the
  liveness thread, which produces a *dead-looking* agent and tests the wrong thing. The delay has to
  sit where the work is, leaving the liveness clock running - which is the whole distinction TQ-93
  drew.
- **Assert the thing that used to fail.** `no agent was respawned`, plus an `agent_slow` event
  raised and cleared: the fix working means the organization noticed, said so, and did nothing.
- **Not become a way to make the suite green.** A fault that produces a slow agent nobody notices
  would pass every property while proving nothing, which is the failure this entry exists to
  prevent one level up.

The natural mechanism is the same one `simulation/exchange.py` already uses for `slow` - a delay
injected at a boundary the agent crosses - rather than anything that touches the process.

### TQ-85 — Signed commits, so document custody prevents rather than only detects

**WANT · QUEUED · owner action required · `SPEC_RECONCILIATION.md` §122**

Document custody (TQ-84) has three layers and is honest about the third: in a public repository
without commit signing, whoever can change a custodial document can change the digest that guards
it. The suite makes an unauthorized edit **visible**; nothing makes it **impossible**.

Signing closes it: a commit touching `docs/JARVIS.md` that does not carry the custodian's signature
is rejected rather than merely noticed. It needs a key the owner holds, which is why this is a Want
with an owner dependency rather than an increment anyone can execute.

Until it exists, `JARVIS.md` says so in the same paragraph that claims the protection — a custody
notice implying more than it delivers would be the falsely-written-charter problem
`backend/charter.py` exists to avoid.

### TQ-81 — Parliament, and the Articles it amends

**NEED (ORANGE) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §123) · addendum 32 · addendum 46 §6,
§39 · §119, §120, §122**

Built as `backend/parliament.py`: the Articles, resolutions with 46 §17's provenance, a
quorum-and-threshold vote in two tiers, and the level-0 refusal with an escalation queue nothing
inside the system can clear. Wired into `/console/overview` and the COO's digest, both of which had
answered *"no parliament, committee or voting body exists yet"* since addendum 32 was assimilated.

**The Articles' amendment threshold is a constant in code, not a clause in the Articles** — an
instrument whose amendment bar is one of its own clauses can be lowered by simple majority and then
walked through. §120's argument one level down.

**No Articles are in force in the working database.** The genesis text is level 0's to write; the
machinery cannot vote itself an instrument. That is the one thing this increment could not do and
is now the open item at §123 §9.

**The system reports this gap in its own words.** `backend/main.py` and `backend/coo_chat.py` both
answer *"No parliament, committee or voting body exists yet"*, and addendum 46 routes every
authorized change through one. It is the load-bearing organ of the newest specification and it is
the one that is not built.

Not the whole of addendum 32. The minimum that makes 46's pipeline real:

- **the Articles** (§120, corrected at §122 — the organization's highest instrument, named so the
  word *Constitution* stays with the owner's document and *Charter* keeps its existing meaning as
  the agent charter), and the amendment path 32 §19 specifies;
- **resolutions** with the provenance 46 §17 requires: what changed, why, who proposed it, what
  evidence supported it, who approved it, when it became active, what it replaced;
- **the vote**, at whatever quorum the Charter sets, with 32 §19's supermajority for Charter change;
- **refusal and escalation at level 0** (§120 §6) — one refusal shape for every reason, and an
  escalation queue that no in-system actor can discharge.

`backend/register.py` (TQ-05) already holds petitions and mandates with fail-closed vocabulary and
a reason on every transition. **This builds on that rather than beside it** — a second register
would be the two-sources-of-truth mistake §54 already declined once.

**Deliberately out of scope:** elections, ministers, committees, the weekly session, the
State-of-the-Union event. Addendum 32 specifies all of them and none is required for a directive to
be authorized. They enter when something needs them.

### TQ-82 — The governed-knowledge layer and the authority hierarchy

**NEED (ORANGE) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §125) · addendum 46 §4, §5, §17 ·
addendum 30 §12 · addendum 39 · §120, §123**

Built as `backend/governed_knowledge.py`. Precedence enforced **on read** — `effective()` returns
the highest active authority on a subject and nothing else can be returned; subordinate material is
reachable under a name that says what it is. Levels 3-9 need an enacted resolution whose `affects`
matches; levels 10-12 need none and carry none. Superseded, never deleted. Conflicts reach the
Speaker, which is what waiting for TQ-81 bought.

**What it does not do, asserted by a test rather than admitted in prose:** it detects precedence
violations, not contradictions. A procedure whose words contradict its policy is adopted without
complaint, because nothing here reads the text.

**What is still missing is a reader** — nothing in the organization consults `effective()` before
acting. See TQ-86.

Addendum 46 §2's architecture — *stable machinery, evolving data* — as something that exists rather
than something that is intended. The store of 46 §4 (the Articles, laws, policies, procedures,
strategies, priorities, knowledge, training material, lessons learned, directives), ordered by 46
§5's precedence with §120's level 0 above all of it.

The whole difficulty is in the ordering, not the storage:

- **A conflict must be detected, not resolved by whoever read it last.** This is the Conflict Rule
  the addenda already carry, moved from a document into runtime. Lower-level material cannot
  silently override higher-level material — *silently* being the word that makes it a mechanism.
- **Detection needs somewhere to escalate**, which is why this depends on TQ-81 rather than the
  other way round.
- **Level 0 is defined by its absence** (§120 §5). No table, no protected row, no admin route. The
  refusal that guards the boundary is what gets built; the thing it guards is not here.
- **Versioning is the point, not a feature.** 46 §17's provenance questions are the schema.
- **Superseded is not deleted.** 46 §18: *"Nothing about rollback should erase history."*

### TQ-83 — The Software Engineering Department

**NEED (GREEN) · DONE 2026-08-28 (`SPEC_RECONCILIATION.md` §137) · addendum 46 §7–§12, §19–§21 ·
§119**

`backend/engineering.py` and `agents/software_engineer.py`. The department takes an authorized
directive and either proposes the instrument that would put the outcome in force, or **names the
capability the architecture lacks** — addendum 46 §8's ladder, with its question answered by
`operating_context.UNDERSTOOD_OBLIGATIONS`, which already knows whether a mechanism exists.

Live, it produced §40's own example unprompted: a directive needing
`secure_video_transport` came back as *"No instrument can create the mechanism"* — level 5.

**Measured by outcome, never by level** (§119's warning). The producer never approves its own
proposal, asserted by parsing the agent's call graph. The §119 deviation — intake direct from a
resolution because Evolution does not exist — is named in every row rather than left in a comment.

### TQ-95 — Evolution's directive relay

**NEED (YELLOW) · DECLINED FOR NOW 2026-08-28 (`SPEC_RECONCILIATION.md` §138) · addendum 30 §4,
§23, §28 · addendum 46 §13 · §119, §137**

Asked its own question first and the answer was no. Of the fourteen fields addendum 30 §4 asks an
Evolution Directive to carry, this system can fill **one** the resolution does not already carry —
affected agent classes — and cannot fill training requirements, evaluation or certification
criteria, or a rollout and rollback plan, because it has no release and no rollback.

A relay built today would move a directive through a stage that adds one computable field and four
empty ones. That is the failure this project keeps recording, arriving as a whole department.

**And §119 was carrying two concerns as one.** The *authority* bypass it feared was closed by TQ-83:
intake requires an enacted resolution. What remains is a *planning* deficiency, which a relay would
dress rather than fix.

Built instead: `engineering.impact_of` — who an instrument binds, what it displaces, and **whether
adopting it would be refused**, checked against the real refusal rather than asserted. It names what
it does not assess every time.

### TQ-97 — Persistent agent identity, and the id that is not a name

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §140 · addendum 51 §2, §3, §5, §6 ·
addendum 49 §20 · addendum 50 §11, §12**

Implementation priority one in both new documents (51 §26, 50 §18), and the thing every other
Providence increment keys off: no personal agent can be bound to a client without an `agent_id`,
and no career can survive a role change without one.

**Most of it was already built and one part of it was built wrong.** The owner decision of
2026-08-17 already separated the durable agent from its job — `agent_names.name` is the agent,
`agent_registry.identity` is the desk, `agent_assignments` records which held which and when, and
no work row is ever denormalised against a name. What was wrong is *what the durable thing was*:
the display name. Addendum 51 §3 requires the id to be **independent of display name**, and
`coo_identity.rename()` already existed to turn that into a defect — renaming a name-keyed agent
either breaks every join or hands its history to whoever holds the name next.

`backend/agent_identity.py` makes `agent_id` the anchor and demotes the first name to a display
attribute of it. **A name that has ever been held is never given to another agent**, enforced
against the whole history rather than the current binding — the case a current-holder check misses
is retirement, which is exactly when a name looks free.

**The last name is derived, never stored.** 51 §5 lists `last_name` *and* `current_role`, which is
two places for one fact and the collision 47 §5 forbids. §2 says the last name *is* the role
designation, so it is rendered from the desk: *Jack Explorer Agent 1* becomes *Jack Reporter Agent
1* by moving desk, which is 50 §12's career path costing nothing. An agent at no desk has no last
name rather than a placeholder. The COO's designation comes from 51 §2's own example — data from
the specification, never a stemming rule inferred from it, because any rule that turns `explorer`
into `Explore` also turns `speculator` into something nobody chose.

**Three of 51 §6's eight lifecycle states are refused by name.** `training`, `evolving` and
`archived` are specified and unproducible here, and a column that accepted them would assert a
capability by existing (§49). The refusal says *specified and unreachable* rather than *unknown*,
because those are different facts.

**Not done, and named:** nothing yet uses this identity to carry experience, role history or
training history, so addendum 49 §20's *"preserving useful prior learning"* has an anchor and no
content. `agent_names` is not migrated onto it — the existing personnel history keeps working
unchanged, and joining the two is TQ-99.

### TQ-98 — The client profile, and the boundary a watchlist sits on

**NEED (ORANGE) · DONE — `SPEC_RECONCILIATION.md` §143 · addendum 51 §4, §13, §15 ·
owner direction §111 · `SPEC_RECONCILIATION.md` §140 §5**

`backend/client_profile.py`. The guard went in before the table, and holding that order
changed the design: **provenance is a convention, not the guarantee.** A caller can pass
`client_stated` for a derived symbol and nothing would know. What the schema really
guarantees is that **a watchlist entry is a symbol and nothing else** — no quantity, no cost
basis, no account — so a watchlist built entirely from a fetched portfolio is still not a
portfolio, because the facts worth protecting have nowhere to go.

§111's tripwires are re-aimed rather than trusted: they ask about a `portfolios` table and
would pass forever while `client_watchlist` grew a `quantity` column. The replacements
enumerate the watchlist's columns against the real schema, close the preference vocabulary to
51 §15's sixteen fields, and assert over the import graph that no module can both read
positions and write a profile.

**The tripwire falsified this increment's own claim on its first run.** The docstring said
*"the first client data this system keeps"*; `gateway/client_agent.py` has held `client_agents`
since addendum 43 §16. The correction is at §143 §3, and it carries a finding: **addendum 50
§6's Personal Usher is partly built already** — a persistent, named, client-bound
representative with voice, visual identity and continuity across meetings — under addendum 43's
name. What is missing is the conversational half.

Nothing reads the profile yet, which is named rather than implied: a store 51 §26 blocks on,
not a behaviour change.

<details><summary>The entry as it was queued</summary>

Every Providence agent is personal, and a personal agent is bound to a `client_id` and works within
that client's profile, permissions and preferences (51 §4). 51 §15 lists seventeen profile fields;
51 §13 has the Personal Reporter consider the client's watchlists, profession, projects and
location.

**This meets a constraint bought with a defect.** §111: the system *"holds no information of the
portfolios."* TQ-72 deleted the storage layer an earlier reading had built, and an import tripwire
fails the suite if a storage module returns.

§140 §5 draws the boundary, and it must be written into a guard **before the table exists**:

- **A profile is what the client told the system about how to serve them.** Preferences, topics,
  tone, consent. §111 never spoke about it and Providence cannot work without it.
- **A portfolio is what the client owns at a broker.** TQ-73's fetch-analyse-discard pipeline is
  unchanged.
- **A watchlist is the line.** Symbols a client typed are a preference; symbols derived from a
  fetched portfolio are a portfolio wearing a preference's name, and the two are indistinguishable
  in the data. The rule is *stored only as something the client typed*, and the tripwire has to be
  re-aimed to say so (§105 — re-aimed, never deleted).

Building the profile first and re-aiming the guard afterwards is how a constraint erodes, so the
guard comes first in this entry deliberately.

</details>

### TQ-99 — Join the personnel record to the agent id

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §148 · addendum 51 §3, §5 ·
`SPEC_RECONCILIATION.md` §140 §4**

Done, and the debt is worth naming: TQ-97 said the deviation would be held **one** increment
and it was held **five**. A deliberate deviation with a stated expiry is a reasonable trade; the
same deviation four increments later is drift with a good story attached (§148).

The property it buys could not hold before: **a renamed agent keeps one continuous personnel
history.** `assignment_history` was keyed by the display name, so a rename split the folder in
two — which is exactly what addendum 51 §3's *independent of display name* exists to prevent.

Backfill follows `_ensure_assignment`'s own pattern — on registration, no migration store — and is
**backdated to when the name was bound**, because an identity dated at backfill would report every
agent as created the moment somebody restarted the system.

A rename moves the pool binding and the desk, and nothing else: spans keep the name they were
written under, because what the record said at the time is a fact. Live: seven agents, seven
identities, seven spans, none unkeyed, no disagreement between the pool and the identity.

<details><summary>The entry as it was queued</summary>

TQ-97 introduced `agent_id` beside `agent_names` rather than under it, so nothing broke and two
notions of "the durable agent" now exist. That is the state 47 §5 forbids, held deliberately for
one increment so the identity could be built and tested without a migration in the same change.

What this owes: `agent_names` and `agent_assignments` keyed by `agent_id`, `personnel_record` and
`attributed_work` reading through it, and the existing bindings backfilled with ids — backdated to
when the name was actually bound, for the reason `_ensure_assignment` already gives about spans
starting at backfill time orphaning every prior hour of work.

</details>

### TQ-100 — What refuses a persona that crosses the line

**NEED (ORANGE) · QUEUED · addendum 50 §8 · addendum 49 §15 · addendum 50 §3 ·
`SPEC_RECONCILIATION.md` §140 §6**

Addenda 49 and 50 allow personas inspired by recognizable styles and, with consent and reference
material, by *"someone personally meaningful"* to the client. They carry their own guardrails — a
clear distinction from an actual human, and no false representation as a licensed professional.

**The finding is not that the guardrails are missing. It is that this system cannot obey them.**
§126 and §131: code cannot obey prose, and an instrument with no machine-readable obligation is
reported `prose_only` — in force and enforced by nothing. Every sentence of the guardrail lands
there.

**The question this entry owns, and it comes before any code:** what refuses a persona that
crosses the line, and is it a function or a paragraph? *"The model will decline"* is a
self-assessment wearing a mechanism's clothes (§119 §8), and it is the answer that will be
reached for first.

### TQ-96 — Release and rollback

**NEED (ORANGE) · DONE — `SPEC_RECONCILIATION.md` §139 · addendum 46 §16, §18 ·
addendum 30 §14, §26, §27 · `SPEC_RECONCILIATION.md` §119, §138**

**Done for governed data; declined for code, with the reason recorded.** The first
question — what a release *is* here, given the governed layer already changes
behaviour without one — is answered at §139: *a named set of governed changes that
stand or fall together, whose way back is authorized before the way forward is
taken.* `backend/release.py` supplies the boundary, the checkpoint, the health
verdict and the reversal; `governed_knowledge.reverse` restores rather than
re-adopts, so a rollback spends no new authority and adds no vote.

**The code half is not a gap to close.** The organization observes its code
version (`backend/version.py`) and may not choose it, because nothing in the
running system may write to the repository. So there is no `deploy()`, a tripwire
fails the suite if `release.py` reaches for `subprocess` or `os`, and what is kept
is the record — a rollback under a different code version says the data is
restored and the system is not.

**§119 §5's constraint was satisfied by the architecture rather than by care.** A
release must not be a restart script; 46 §18 step 4 asks agents to reload, and
nothing here caches what governs it, so there is nothing to reload.

Live: `release_and_rollback` applies a misdrafted release to a running
organization at +120s, judges it unhealthy at +220s on 77 refusals, and reverses
it at +235s. 14/14 properties, zero respawns, zero crashes, zero failed
directives. The first attempt was **green and vacuous** — every report in the run
was filed in its first nine seconds, so the release window contained no work at
all; the origination cooldown is compressed in that scenario for exactly that
reason (§139 §7).

**What remains unbuilt and why**: acceptance criteria (30 §16 — health is a
judgement with evidence, not a threshold anything computes), a postmortem written
into organizational knowledge (composed on demand instead; nothing reads that
store back), and Evolution's relay, which §138 declined and which is now
unblocked.

<details><summary>The entry as it was queued</summary>

**Original: NEED (ORANGE) · addendum 46 §16, §18 · addendum 30 §14, §27**

The thing Evolution's contribution has nothing to plan without, and the largest item
`simulation verify` lists among what it cannot see.

Addendum 46 §18 makes rollback *"a fundamental capability rather than an emergency
improvisation"*: a restoration point before a significant release, and a way back that preserves the
failed version rather than erasing it. §16 pairs it with a release model in which version N keeps
running while N+1 is prepared.

**§119 already set the constraint on how it may be built.** Addendum 30 §13 says this system *"is
not a single monolithic object that must be serialized and restarted"* and §14 makes full-system
shutdown a last resort, so a release must not be built as a restart script: rolling restart, canary,
version coexistence, compatibility adapters, and the COO's own handoff (30 §15).

The first honest question is what a release even *is* here, given that the governed layer already
changes behaviour without one. Rolling back an instrument is a supersession the store already
supports; rolling back **code** is a different problem, and conflating them would be §138's mistake
in the other direction.

§119 adjudicated that Software Engineering receives directives **through Evolution**: 46 §13 draws
*"Approved Directive → Software Department intake"* with nothing between, and that gap is where a
bypass appears by accident. TQ-83 built the department and Evolution still does not exist, so every
directive carries `arrived_via = "resolution_directly_no_evolution_relay"`.

The deviation is declared and bounded. What it needs is the smallest piece of addendum 30 that makes
the relay real — an evolution directive with its own record (30 §4, §22) — and **not** the
forty-agent catalog, which §119 §3 already reinterpreted as responsibilities rather than headcount.

The question it has to answer: what does Evolution *add* between a resolution and the department?
If the honest answer is nothing, the relay is ceremony and §119's adjudication should be revisited
rather than implemented.

One general-purpose Software Engineer agent type occupying roles rather than a catalog of
specialists (46 §9–§11, adjudicated at §119 §3), spawned to workload (§10), with the independence
rule holding for significant change: **the agent that produces a change is not the sole authority
that approves it** (§11).

**Directives arrive through Evolution, not on a parallel channel from Parliament** (§119 §2). 46
§13 draws *Approved Directive → Software Department intake* with nothing between; addendum 30 §28
forbids the equivalent bypass one level up, and building the gap is how the bypass appears.

Graded from the first task by the curriculum machinery that already runs (§117): Phase 1 (46 §21)
is a curriculum, not productivity — *"The purpose is not productivity. The purpose is to teach the
department the correct engineering habits."*

**Two measurement risks recorded at §119 §8, to be answered by the design rather than discovered
later.** The §8 ladder must require evidence the outcome was achieved, not evidence that code was
avoided — TQ-80's defect in a new setting. And 46 §32's external-dependency metric must be derived
from observed facts rather than self-reported by the party it measures.

</details>

### TQ-73 — The credential envelope and the stateless fetch/analyse pipeline

**NEED (ORANGE) · QUEUED · depends on TQ-72 · owner direction 2026-08-26 (§111) · addendum 9 §2,
§3, §5**

Owner direction: *"The system fetches the portfolios from external systems using client credentials
and the client credentials is stored on the client side and is passed to the server as encrypted
json data and system uses this info to fetch the portfolio data, processes them but never stores
them on the server side."*

The replacement for what TQ-72 removes, and addendum 9 §2's lifecycle made real: request →
fetch → analyse → report → retain nothing.

**The shape is sharper than "the client supplies portfolio information"** (§115). What crosses the
boundary inbound is a **source name and credentials — a pointer and a key, not a portfolio.** The
agent queries the external sources itself, one or more, and consolidates. That makes the agent an
**outbound caller**, which no agent here is today: Explorer, Speculator and Analysis read a database
the organization filled. The seam where the simulation engine answers that call has to exist in the
agent's design from the first line, rather than being introduced when somebody wants to test it.

**The unit of retention is the session, not the request.** Discard is triggered by the client
disconnecting, so a multi-turn session may legitimately hold a consolidated portfolio in memory
across several questions. There is a *lifetime* to manage, not merely an absence of writes.

**State the guarantee as "this system retains nothing", never as "your data exists nowhere."** An
external reasoning model may retain what it was sent, and that is somewhere this system cannot
delete. The consent flow is the only control on it (TQ-46 §11 Q2, measured), and claiming the
stronger guarantee would be the overclaim §110 §4.3 refused about the Gateway, in a domain where it
matters more.

**The open question this entry owns, and it is a design decision rather than a detail: what does
the encryption defend against?** TLS already protects the wire. Envelope encryption on top of it
protects against the server's own logs, crash dumps and disk — which is exactly the threat this
architecture cares about — but only if the key is not sitting beside the payload. Answer that
before writing the format.

**And state the guarantee accurately.** The server must decrypt the credentials to call the broker,
so they exist in its memory in plaintext at fetch time. The property held is **never persisted**,
which is real and worth having. It is not *never seen*, and writing it down the strong way would be
the error §110 §4.3 refused when it declined to claim the portfolio move defended against a
compromised Gateway.

**The product is the consolidation** (§112). *"Client needs consolidated portfolio analysis that
is usually not provided by discount brokers."* A broker can already show a client their own
account; several sources in one view is the thing being sold. So every interface here takes
**sources, plural**, from the first line — a design that fits one account and grows a list later is
the one that quietly assumes single-source everywhere nobody is looking. Reconciliation is core
rather than polish: the same security at two brokers is one position, and addendum 9 §3 asked for
exactly that reconciliation long before addendum 44 was written.

**That question is answered** (§113), and the answer is the one that costs work. Owner: *"Prices
come from market data store. Positions come from broker dealers and other external sources. Risk,
sensitivity, greeks etc are calculated locally."* §112's proposal — that prices ride along with the
fetched positions, so the organization never produces one — is **refuted**. Prices are ours, so §96
and §101 are reopened deliberately.

`is_priced()` moves rather than relaxes: **from the portfolio's `data_mode` to the price's
provenance.** `data_mode` describes where the *positions* came from, and under §113 a portfolio can
be entirely real while the only available price is synthetic — which `data_mode` cannot express.
`observations` has carried `origin` and `source` on every row since addendum 20 §4, so the
mechanism exists. The new rule is stricter than the one it replaces: a `LIVE` portfolio priced from
`parity_world(seed=4)` passes today and must not.

**Blocked on TQ-75 for anything valued at all** — the store holds no real prices, and not merely as
a policy matter: `JE-000001` is not `AAPL`, so every lookup for a real holding misses.

Blocked in practice on the same thing TQ-49/TQ-50 are — there is no external system to fetch from
until the owner has broker API access — so the buildable half is the envelope, the request shape,
the reconciliation across sources, and the analysis over supplied holdings, which
`holdings.concentration` already does.

### TQ-77 — The simulated exchange, and simulated clients arriving through the Gateway

**NEED (GREEN) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §117) · owner direction 2026-08-27
(`SPEC_RECONCILIATION.md` §115) · addendum 25, addendum 34, `simulation/harness.py`**

Built as `simulation/exchange.py` and `simulation/client_sessions.py`. The dependency on "TQ-73's
agent seam" turned out to be wrong: the seam is the *provider registry*, which already existed, and
the exchange registers in it as an ordinary provider. There is no simulation branch in the analyst
and nothing there for one to be added to.

Owner direction: *"The simulation engine simulates all external calls the agent makes and also the
task that is assigned to the agent. This task is assigned to the agent through the gateway and when
the system sees that what is happening is the simulation phase, it will behave accordingly using
the simulation engine to mimic client requests and also provide the portfolio to the agents through
simulated exchanges."*

Two substitutions, both **at the boundary and never inside the agent**:

1. **Inbound** — a simulated client requests analysis *through the Gateway*, with a source name and
   credentials, and closes the session with satisfaction or disappointment.
2. **Outbound** — a simulated exchange answers the agent's query for portfolio data.

**The agent must not be able to tell.** That is the whole property, and it is why §115 corrected
§114: there is one code path, and what changes is what answers the call. `simulation/harness.py`
already states the philosophy — *"It does not import agents, stub providers, or drive the pipeline…
Isolation is the database, not a flag"* — and this extends it one boundary further out.

What it lands on rather than invents:

- **`run_mode` is already a closed vocabulary** (`simulation`, `historical`, `live`) and
  `backend/missions.py` already refuses anything but `simulation`, enforced rather than documented
  (addendum 25). The "simulation phase" has a name here already.
- **The harness already runs the real organization** in an isolated database and chooses only the
  environment it comes up in.
- **The three imaginary clients already exist** with deliberately awkward portfolios (§101,
  addendum 44 §6.1) — a covered call, a concentration, a missing cost basis.

The one thing to get right and easy to get wrong: **how the system knows it is in the simulation
phase must not be a value the agent reads.** An agent that can branch on it is an agent whose
training and production behaviour can diverge, which is the property this entry exists to
guarantee. The harness's answer — the environment, not a flag in a row — is the precedent.

### TQ-75 — A real market data source, because the store has none

**NEED (ORANGE) · QUEUED · blocks TQ-73's valuation and TQ-74 · owner direction 2026-08-26 (§113) ·
addendum 20 §4, `MARKET_DATA_TAXONOMY.md`**

Owner direction: *"Prices come from market data store."* They do not yet, for real securities.
Measured on the live database rather than assumed:

```
observations:    20 rows, all origin='synthetic', source='parity_world(seed=4)'
security_master: 10 securities, ids JE-000001…, no real tickers
```

**The obstacle arrives as a miss, not as a wrong number**, which is the good version of this
problem. `JE-000001` is not `AAPL`; the synthetic universe shares no symbol with a real portfolio,
so a price lookup for a real holding finds nothing. Nothing has to be caught by a reviewer — it
cannot silently produce a plausible figure, because it cannot produce a figure.

This entry obtains prices for real securities. What it must settle:

- **Which source, and its licence.** Market data redistribution is licensed, and the terms differ
  between displaying a price to the person whose position it is and storing a history. Read the
  terms before writing an ingester — this is the same discipline TQ-52 applies to model weights.
- **Provenance on every row, which the schema already supports.** `observations.origin` and
  `source` exist and are already unique-indexed together with the entity and timestamp. Real prices
  arrive tagged as real; the synthetic world keeps writing alongside them, which addendum 20 §4's
  docstring already calls *"convergence, not an error"*.
- **Coverage is a fact to report, not to paper over.** A consolidated portfolio will contain
  instruments the store cannot price. Those positions are reported as unpriced with a reason —
  §100's rule that absent is `unknown` rather than a plausible default, applied where it matters
  most.
- **Staleness is not freshness.** A price from Friday shown on Monday without saying so is §17's
  *"do not silently claim it is current"*, one domain over.

Not a queued convenience: **no valuation, no risk figure and no scenario result can be computed for
a real portfolio until this exists.**

**It does not block training** (§114). Owner direction the same day: a store holding only simulated
data means the whole process is a simulation, and that is a legitimate state — it is the training
environment. TQ-73 and TQ-74 can be built and exercised now against imaginary clients; what waits on
this entry is **serving a real client**, which is the right thing to gate.

### TQ-76 — A portfolio-analysis curriculum, and imaginary clients to practise on

**NEED (GREEN) · DONE 2026-08-27 (`SPEC_RECONCILIATION.md` §117) · owner direction 2026-08-26
(`SPEC_RECONCILIATION.md` §114) · addendum 36 (Department of Education), addendum 34 §17,
addendum 13, addendum 9**

Built as `backend/curriculum.py` and `simulation/training.py`. Six exercises over five competencies,
each declared remediation or capability-building per addendum 36 §4. It found one real gap on its
first run — see TQ-80.

Owner direction: *"Agents are being trained and we need simulation exercises for simulated requests
for portfolio analysis from imaginary clients as part of training and this needs to be incorporated
in the curriculum in the department of education."*

**The Education deferral's own unblock condition has fired**, and it was checked rather than
asserted (§114). §60 disposition 3 deferred the departmental machinery *"until a real curriculum
need the existing loop cannot express."* This one cannot be expressed:

- there is **no Portfolio Analyst agent** — `agents/` holds explorer, speculator, analysis, coo;
  addendum 9's pipeline has been recorded as "Not built" since the addendum-12 gap analysis;
- the grading substrate is **discovery-shaped** — `grades`' 669 rows score `relevance`, `novelty`,
  `evidence_quality`, `worth_the_compute`, which are the dimensions of a market *finding*, not of a
  portfolio analysis;
- there is no curriculum, exercise or certification table at all.

**Buildable now, and that is the point of §114.** A store holding only synthetic prices makes the
whole pipeline a simulation, which is the training environment rather than a broken production one.
TQ-75 gates serving a real client; it does not gate practising.

What this increment owes:

- **Exercises shaped like the real workflow.** The imaginary client supplies their imaginary
  portfolio per exercise, the analyst consolidates in memory, and nothing is kept but the grade.
  **§111 applies to training too** — an exercise that stored portfolios would train agents on a
  workflow this system does not have, and every habit formed would be one that is wrong in
  production and was rewarded in training.
- **Grading is the client's verdict, and the owner supplied it** (§115): the session ends with the
  client expressing *satisfaction or disappointment*. In simulation the simulated client supplies
  it, which is what makes the curriculum gradeable at all. Build the grading around that rather
  than inventing dimensions from the output — it is a better signal than anything derivable, and
  it is the one production will actually have.
  Derived dimensions still earn their place *underneath* it, to explain a verdict rather than
  replace it: did it reconcile two sources into one position, did it identify the concentration,
  did it refuse to price what it could not price and say so rather than approximating. The last is
  worth weighting hardest — it is the behaviour the whole domain depends on and the first thing
  lost under pressure to produce an answer.
- **The imaginary clients already exist.** `backend/portfolio_providers.SIMULATED_PORTFOLIOS` holds
  three with deliberately awkward portfolios — a covered call, a concentrated position, a missing
  cost basis (§101, addendum 44 §6.1). They were built as demo data to delete before going live;
  under §114 they are training fixtures, which do not get deleted.
- **Separate the two policies that share one flag.** "Simulated data that must be gone before a
  real client exists" and "training fixtures that must still be there in a year" are opposite
  requirements wearing one `simulated` flag. `demo_clients.outstanding()` asks *"is any simulated
  client data present"*; the honest question becomes *"outside the training environment"*.
  **Draw it deliberately** — widening `outstanding()` to ignore anything flagged as training would
  re-create §100's finding exactly: a clean report that is not true, which is the one a pre-launch
  checklist believes.

The Speculator curriculum (36 §10) still waits on the collaboration scoring it would be graded by
(TQ-17); this one does not, because its grading dimensions are its own.

### TQ-74 — Scenario simulation over a consolidated external portfolio

**WANT · QUEUED · depends on TQ-73 · owner direction 2026-08-26 (§112) · addendum 34, addendum 9 §5**

Owner direction: *"We need to build advanced portfolio analysis tools that will do scenario analysis
of consolidated external portfolios such as scenario simulation and analysis."*

**The simulation engine already exists and has never had a consumer outside its own validation**
(addendum 34, `simulation/`, mission control). This is the consumer, which is worth noticing: the
engine was built against §14's maturity ladder and graded on its own outputs, and a real portfolio
to run scenarios over is the first thing that makes it answer somebody's question rather than its
own.

Two rules must hold when they meet, and neither is new:

- **A simulated scenario over a real portfolio carries its label everywhere it appears** (§77's
  `SIMULATED_NOTICE`, addendum 25). A what-if about somebody's real money that loses its label on
  the way to a screen is the failure this project has guarded against since §70.
- **Scenario output is not a price.** `is_priced` governs what a position is worth *now*; a scenario
  says what it might be worth under stated assumptions. Keeping those apart is what stops a stress
  test from quietly becoming a valuation.

Addendum 9 §5 defers the detail this will need — Greeks, scenario analysis, stress testing,
correlations, factor exposures, risk limits — and says so explicitly, so this entry is where that
deferred list gets picked up rather than a new direction.

### TQ-70 — Three identity populations, and whether any two of them are one

**NEED (YELLOW) · QUEUED · raised by TQ-69 (spec §10 Q2, decided 2026-08-26) · addendum 16 §7,
addendum 44 §9.2, §98, §109**

This system authenticates people in three unrelated places, and it was never decided that it
should:

| population | where | who is in it |
|---|---|---|
| backend users | `users.json`, `app/users.py`, `user_data/<username>/` | My AI users — per-user permissions, preferences, audit |
| Gateway clients | `clients` in `gateway.db` (§98) | the `subject` that owns portfolios, holdings, conversations |
| environment credentials | `gateway/auth.py`, `MY_AI_ADMIN_USERS`, `GATEWAY_BACKEND_USER` | the operator, internal accounts, and the Gateway's own backend account |

TQ-69 found them (spec §3) and deliberately kept them apart: the backend stores `(owner_type,
owner_id)` **opaquely**, so it authorizes strings it never has to interpret. That was the right
call for that increment and it is not a decision about the long run. This entry is the long run.

**The entry exists so the fourth store cannot arrive without comment.** Three identity stores with
no queue entry saying so is a system where a fourth is added by somebody who reasonably assumes
that is how this is done.

Three things it has to get right, and one it must not do:

- **It is a data migration over credentials.** Deliberately not run alongside TQ-69, which is a
  data migration over client financial records: two at once means that if the result is wrong,
  nobody can tell which half did it.
- **Nothing may be re-keyed.** The backend now holds real client portfolios under those opaque
  strings. Any merge either preserves them exactly or changes whose data a portfolio is — and
  TQ-69 spec §6.3 already ruled on that: *a migration that restamps or re-keys anything has
  changed whose data it is.*
- **`normalise` stays one implementation.** Two normalisations that can disagree are two
  identities for one person, which is the failure `gateway/clients.normalise` exists to prevent.
  It is one function today, imported rather than copied; a reconciliation is exactly where a
  second one gets written.
- **The environment credentials are not a merge candidate.** `gateway/auth.py` says their
  separation is intentional, and an operator credential living in the same store as customer
  logins is one compromise away from being one. This entry treats "three stores" as three
  different *kinds* of thing, not three copies of one.

Output is a decision, not necessarily a merge: "these two are one population and here is the
migration", or "they are three populations and here is the entry that says why", are both
acceptable answers. What is not acceptable is the current state — no answer, and no record that
the question was asked.

### TQ-46 — The Superuser portfolio as its own ownership domain

**NEED (YELLOW) · PAUSED 2026-08-26 — premise changed by owner direction (§111) · partially
built on branch `tq-46-superuser-ownership-domain` · depends on TQ-72 · addendum 44 §4, §10, §16,
§21.4, §21.6 · spec: `docs/specs/TQ-46_superuser_ownership_domain.md`**

**Paused, not abandoned.** Its ownerless-retrieval fix (§16.7) is still wanted and still correct:
`retrieve_portfolio` had no owner, and the two-layer consent model around it is the only control on
forwarding holdings to an external model (its §11 Q2, measured). What changed underneath it is
where the holdings come from — §111 says the system stores none, so migrating
`data/portfolio.xlsx` *into* a table is now the wrong direction.

**That question is answered** (§112). Owner, 2026-08-26: *"my portfolio is also external, fetched
not stored."* So `data/portfolio.xlsx` is migrated nowhere — it is a **source**, one the operator
maintains by hand, fetched and analysed like any other. The Superuser stops being a special case in
the data model and stays one only in authorization, which is what addendum 44 §4 actually asked
for: *"never exposed through normal client-facing Gateway paths"* is a routing rule, and it
survives the storage going away untouched.

What is left of this increment is therefore the half that was always right — retiring the ownerless
retrieval — with the operator as the **first real test of the §112 workflow**: a client with an
external source, supplied per request, stored nowhere.

The work already on the branch that survives regardless: the owner argument on `retrieve_portfolio`
and `execute_tool`, `for_superuser` requiring a resolved id, the `superuser` pseudo-login and
`subject_for` making it one identity rather than two, and the isolation test that could not be
written before — a fully granted, fully consented second account still cannot reach the first's
holdings.

**Was blocked by owner direction** (§109): the Gateway authenticates, the backend authorizes and
holds business logic. The portfolio subsystem was on the wrong side of that line, so TQ-69 moved it
first — building a `SUPERUSER` domain into `gateway.db` and moving it a week later is the mistake
TQ-44 refused to make with the entity and its guard. TQ-69 is done, and this is next.

**All four §11 questions are decided and recorded (2026-08-26).**

**Q4 — answered by the owner:** *"Krish is the superuser of this system… the architect… the owner…
the creator. The system serves Krish primarily. The system also has other clients… However, they
are just clients. The clients pay for service."* So the SUPERUSER portfolio is owned by the
**backend `username`** — Krish is explicitly not in the clients population, and
`gateway/clients.py` is the registry of external paying clients.

**The finding that came with it:** both candidate stores currently spell the operator identically
(`GATEWAY_SUPER_USER=krish`, and `krish` in `users.json`), so the two possible answers **coincide
today by accident of naming**. Either choice would appear to work, and the difference would surface
only on a rename, a second operator, or two `.env` files — at which point the operator's portfolio
becomes **empty rather than erroring**. The increment removes the ambiguity rather than maintaining
the coincidence: **exactly one caller may assert `SUPERUSER`, and it is the backend.** TQ-47's tab
is in the console, which is backend-side, so both consumers already are.

**Q2 — confirmed by measurement, and the leaning was wrong.** The operator's portfolio is *not*
`LOCAL_ONLY`: only `account_id` is, and `sanitize_portfolio_rows` strips it before anything is
forwarded, so the rows that reach a model carry no `LOCAL_ONLY` field and §108's `PATH_REFUSED`
never fires. **The consent prompt is the only control, not a redundant one** — deleting it as
duplicated would have left nothing. Marking the portfolio `LOCAL_ONLY` to make §108 apply is
refused: with no local model, that would take `/chat`'s only tool permanently out of service.

**Q3 — two capabilities**, declared and checked where the surface actually is (backend-side, per
Q4) rather than in `gateway/roles.py` as §6's file table guessed before TQ-69 landed. A capability
nothing checks is machinery with no user, which is the same rule that keeps the other five
unbuilt.

**Q1 — reading B** (decided earlier): keep the capability, remove the ownerlessness. No consent
machinery is deleted.

**Q1 is decided: reading B** — keep the capability, remove the ownerlessness. The spec called B
expensive because the backend cannot reach `gateway.db`; under the corrected architecture that
sentence describes the problem rather than the constraint, and B is simply the shape the system
was specified to have.

The Superuser portfolio is not a client portfolio and must never be reachable through a client
path (§1, §4.1, §4.2). Today the operator's portfolio is `data/portfolio.xlsx` behind
`app/tools/portfolio.py`, which §16 correctly calls the legacy single-portfolio design.

Scope: `owner_type = SUPERUSER` as a structurally separate domain that no client query can
resolve to; explicit `PORTFOLIO_VIEW_SUPERUSER` / `PORTFOLIO_ANALYZE_SUPERUSER` capabilities
(§10) rather than a superuser bypass — §5.3 is explicit that `if superuser: skip all ownership
checks` is not the implementation; and §16's migration, ending at item 7: **remove the global
ownerless retrieval**. `retrieve_portfolio` today takes permissions, preferences and an audit log
but no owner, which is precisely the shape §16.7 names.

Flagged YELLOW for one thing that must be got right rather than discovered: the operator already
holds `CAP_HOLDINGS` through the client-facing Gateway path (§92, §96). That is harmless while
those holdings are the operator's own Gateway-stated ones; it stops being harmless the moment a
SUPERUSER-owned portfolio exists and the two paths can resolve to each other. §97 records the
three-way vocabulary collision (Server Superuser, Gateway Super User, ROLE_OPERATOR) that makes
this easy to get wrong.

**Specified 2026-08-26** — `docs/specs/TQ-46_superuser_ownership_domain.md`. Writing it settled
what the YELLOW flag actually is, **by measuring rather than reasoning**: the two paths *cannot*
resolve to each other. `_owned_by` compares `(owner_type, owner_id)` as a pair, so one name in two
domains is two owners, and TQ-44's guard already refuses in both directions. The security half of
the flag is closed.

What remains is narrower and different — **ambiguity**. After this increment the operator has two
portfolios under one name, and nothing distinguishes them in what they read. That is not a breach;
it is somebody being shown the wrong money, which §96 already called "a confusion worth naming".
The flag stays YELLOW because that hazard is real, just not the one the entry named.

Three open questions in the spec's §11, and **Q1 is load-bearing and is the owner's**: §16.7 says
remove the ownerless retrieval, which admits two readings — retire `retrieve_portfolio`, or give
it an owner. Re-owning it is blocked by architecture (the backend cannot reach `gateway.db`), so
the leaning is to retire it — but that removes a portfolio tool from `backend/main.py`'s `/chat`,
which is a product decision rather than a technical one.

### TQ-71 — Drop the retired holdings tables, deliberately

**NEED (GREEN) · QUEUED · raised by TQ-69 (§110) · §99, §100, §110**

A fully-migrated `gateway.db` now carries four tables holding retired copies of client financial
records:

| table | left by | keyed by |
|---|---|---|
| `client_holdings_legacy` | TQ-44 (§99) | client |
| `portfolio_holdings_pre45` | TQ-45a (§100) | portfolio |
| `portfolios_pre69` | TQ-69 (§110) | portfolio |
| `portfolio_holdings_pre69` | TQ-69 (§110) | portfolio |

Renaming rather than dropping was right every time — it is what makes each migration idempotent by
construction, and it is the only way anybody can answer "did that move the data correctly?" a week
later. **Four of them is no longer a habit, it is an accumulation**, and §100 already showed what
an unwatched archive costs: after the TQ-45a rename, `clear()` emptied the live table while ten
demo holdings sat in `portfolio_holdings_pre45` and `outstanding()` reported everything clean.

This entry exists because **dropping a table holding client financial records is not a side effect
of anything**. It needs its own decision, and three things settled with it:

- **A retention answer, not a tidiness one.** How long is a pre-migration copy worth keeping, and
  what is it for? "Diagnosis" was the reason given in TQ-44's spec §10 Q2 and nobody has needed it
  since; that is evidence either way and should be stated rather than assumed.
- **Demo rows go first regardless.** `gateway/demo_clients._clear_archives` already reaches every
  one of these, and it must keep doing so for as long as they exist — a pre-launch check that says
  "clean" while simulated customers sit in an archive is the §100 finding again.
- **Verified against a copy before dropping**, like every other change to these tables, and after
  confirming the live data matches. A drop is the one migration step that cannot be rolled back by
  renaming something.

Cheap, and worth doing before anything else adds a fifth.

### TQ-47 — The Superuser Portfolio tab

**WANT · QUEUED · depends on TQ-46 · addendum 44 §4.3, §11.2, §11.3, §11.4, §15.2, §20 Phase 4**

A dedicated tab in the console (§11.2): Overview, Holdings, Options, Risk, Analysis, Broker
Connection, Sync Status, History. Visible only to the Superuser, not discoverable through client
navigation, not addressable by guessing a portfolio id — **and §4.3's last line is the one that
matters**: backend authorization remains mandatory even when the UI hides the tab, which is
addendum 40 §14's rule that §92 already enforces route by route.

Carries §11.4's simulation banner in the form the finance desk already uses (§77's
`SIMULATED_NOTICE`), and §11.3's connection states — including `Connected - stale`, which is the
one that stops old data reading as current.

### TQ-48 — Snapshots, provenance and portfolio audit logging

**NEED (YELLOW) · QUEUED · depends on TQ-44, TQ-45 · addendum 44 §3.5, §12, §13, §14, §17,
§20 Phase 5**

Three things that belong together because each is unverifiable without the others.

**Snapshots** (§3.5) so an analysis can be reproduced, with `payload_hash`. **Provenance** on
every analysis artifact (§12): portfolio_id, owner_id, snapshot_id, as_of_timestamp, provider.
**Audit logging** of portfolio access (§14) — PORTFOLIO_VIEW, PORTFOLIO_ANALYZE, PORTFOLIO_SYNC,
BROKER_CONNECT/DISCONNECT, AUTHORIZATION_DENIED — recording the denials, because an audit trail
of successes cannot answer the question anybody asks it after an incident (the same reasoning
§89 applied to migrations).

And §13's freshness: `last_synced_at`, `as_of_timestamp`, `provider_status`, with analysis able
to **state** that data is stale rather than presenting it as current. §17's failure behaviour
belongs here too — a stale snapshot retained and marked, never silently claimed as fresh.

### TQ-49 — The Schwab boundary, with the live connection off

**WANT · QUEUED · depends on TQ-45 · addendum 44 §8.1-§8.6, §18, §20 Phase 6**

§8.1 is explicit that architecture work must not wait on API access, so this is everything
except the connection: `SchwabPortfolioProvider` satisfying TQ-45's conformance suite against
recorded fixtures, `BrokerageConnection` (§3.6) with `credential_reference` rather than
credentials, normalization to canonical types (§8.6), account mapping one-external-to-one-owner
(§8.5), and configuration placeholders (§8.4) — **placeholders only, never values**, with
secrets absent from committed files, from logs, from the UI and from prompts (§8.3).

The point of doing this before access exists is §18's: adding a provider later should require an
adapter and a mapping, not a redesign of ownership. That is only true if the first adapter is
written while the interface can still change.

### TQ-50 — Schwab live, read-only

**WANT · BLOCKED — owner action: Charles Schwab developer/API access · depends on TQ-49 ·
addendum 44 §8, §20 Phase 7, §21.13**

Blocked on something only the owner can do, and recorded as such rather than as a next step.
When access arrives: OAuth authorization flow (§8.3), the authorized Superuser account mapped to
the Superuser portfolio, read-only synchronization, conformance tests against the live provider,
and the verification §20 Phase 7 ends on — that no client pathway can reach Superuser data.

**Read-only. No order execution in this phase** (§2.4, §8.2, §19), and this entry is not the
place that decision gets revisited.

This is also the increment where `portfolio_valuation` — declared-and-unbuilt since §95 — becomes
buildable, because it is the first time this system has a real price rather than a simulated one.
Until then its blocked_reason stays true and stays said.

### TQ-51 — Unpin `routing: none_single_model`, deliberately

**NEED (GREEN) · DONE 2026-08-26 (`SPEC_RECONCILIATION.md` §103) · addendum 45 §1, §6,
§45 Phase A · `SPEC_RECONCILIATION.md` §64, §102**

The precondition under everything else in this lineage, and it exists because §64 put it there on
purpose: `docs/model_registry.yaml` carries `routing: none_single_model` as a **pinned decision,
not an omission**, and `tests/test_model_registry.py` fails the suite the day a second configured
model is registered. Addendum 45 requires four to eight. So the tripwire fires on the first real
step, which is exactly what it was for — routing gets revisited on purpose rather than acquired by
drift.

Scope: decide and record what replaces the pin, and change the tripwire from "a second model is a
failure" to "a second model without a leaderboard entry is a failure". The tripwire must not be
deleted; it must be re-aimed, or the discipline §64 bought is spent rather than kept.

Also settle here whether the Model Performance Registry (§8) **extends** `model_registry.yaml` or
sits beside it. They answer different questions — one is "what is configured", the other is "what
performs well at what" — but two files that both rank models is the two-models-of-one-fact problem
§70 and §100 have each ruled on once. Decide before either is built.

Small, and deliberately first.

**Done** (§103), and it changed no runtime behaviour: still one model, still
`routing: none_single_model`. Three decisions came out of it. The two registries are
**separate, split by writer rather than by subject** — one is hand-authored, committed and
asserted against the code; the other is machine-written after every task, and scores in git
would dirty the tree on every inference. The real collision turned out sharper than "both rank
models": it is `preferred_model`, a hand-authored answer to the question addendum 45 §16 says
an agent must not answer, now carrying a **planned handover** to seed status at TQ-60 rather
than a quiet drift. And the boolean pin became a **ladder** (`routing_stages`), where each rung
carries its own tripwire and a rung whose assertion is not built **refuses to be stood on** — so
advancing the marker early fails loudly instead of leaving a second model reachable by nothing.
Mutation-tested five ways, five caught.

### TQ-52 — The candidate survey: what can actually run on this machine

**NEED (GREEN) · DONE 2026-08-27 · `docs/local_model_candidates.yaml` · depends on TQ-51 (done) ·
addendum 45 §5, §34, §35, §43, §44**

Metadata before code (addendum 30 §12), and this one is metadata before *downloads*. Produces
`docs/local_model_candidates.yaml`: for each candidate, the licence, the parameter count, the
quantization that fits, the runtime, the VRAM and RAM it needs, and whether it runs here at all.
No model artifacts, no runtime installation, no code.

**The hardware is the constraint and it is measured, not assumed** (§102): NVIDIA RTX 3050,
**8 GB VRAM**, 16.5 GB system RAM, 365 GB free disk. A 7B–8B model at 4-bit quantization fits in
VRAM; a 70B-class model does not, at any quantization. Disk is ample for a pool of six; VRAM is
not ample for two resident at once, which makes §15's challenger comparisons **sequential**. That
is a latency cost, not a blocker, and the plan should say so rather than discover it.

**"Inkling" — answered by the owner 2026-08-26, and then measured 2026-08-27 once this machine had
internet access.** The name was the fact this entry was blocked on; the survey was still owed the
artifact, the licence and the runtime, from published material rather than from a name.

**Found, and it does not run here.**

| | |
|---|---|
| what it is | **Inkling**, Thinking Machines Lab — an open-weights model |
| size | **975B total, 41B active per token** (MoE: 6 of 256 experts plus 2 shared, 66 layers) |
| licence | **Apache 2.0** — permissive, no obstacle |
| runtimes | SGLang, vLLM, Transformers, Ollama, LM Studio; llama.cpp **only via unmerged PR #25731** |
| smallest known build | **226 GB**, at 1-bit quantization |

Against this machine's measured hardware (§102): **8 GB VRAM, 16.5 GB system RAM, 365 GB free
disk.**

The 226 GB build *fits on the disk* with about 139 GB to spare, and that is the only sense in which
it fits. Running it means holding weights in 24.5 GB of combined VRAM and RAM, so roughly nine
tenths of every token's weight reads would come off disk — and that is at **1-bit**, where quality
is degraded to the point that "it ran" would not mean "it answered". The MoE routing helps compute
and not storage: 41B active per token still selects those experts from all 975B, which have to be
somewhere reachable.

**So the finding is a finding, not a substitution** — which is what this entry insisted on when the
answer was still unknown. Inkling is real, properly licensed, and out of reach of this hardware by
roughly an order of magnitude. The initial pool is **Llama + DeepSeek + Qwen/Mistral/Gemma at
7–8B**, which §102 already established fits in 8 GB of VRAM at 4-bit, and Inkling is recorded as
out with the reason stated rather than quietly dropped.

Nothing about this system may depend on any of them until the survey writes them all down in
`docs/local_model_candidates.yaml` with the same three facts each.

**Done 2026-08-27.** `docs/local_model_candidates.yaml` carries the licence, parameter count,
quantization, runtime and VRAM figure for each candidate, plus the verdict and its reason.

**The initial pool is three, not six:** `qwen35-9b` (Apache 2.0, Q4_K_M ≈ 5.7 GB — the general
candidate and the first to try), `deepseek-r1-distill-8b` (MIT, ≈ 5.2 GB — a reasoning specialist,
whose thinking tokens are a cost as well as a capability), and `gemma-4-e4b` (Apache 2.0 since
Gemma 4 — the small fast fallback for when context matters more than capability). Three rather than
six because §15's challenger comparisons are sequential on 8 GB of VRAM anyway: a pool of six would
have been five models nobody had run.

All three of addendum 45's named candidates are resolved with a stated verdict rather than a quiet
omission. **Llama is out twice over** — Llama 4 Scout is 109B with a non-OSI community licence, and
Meta's open-weight line has since moved to Muse Glimmer 30B, which is Apache 2.0 and still needs
24–32 GB of VRAM. Muse Glimmer is recorded as the **near-miss to revisit first if this hardware
changes**, which is more useful than leaving it out.

**Disk was never the constraint.** 365 GB holds any of these many times over; 8 GB of VRAM is the
whole limit, which is what makes the pool small and the comparisons sequential.

**What the survey does not establish is that any of them is good enough.** Nothing has been
downloaded or run, and no figure in that file was measured on this machine — every one is a
published number with its source recorded, so `fits: true` means *the numbers say it should*. §108
stands unchanged until one of them has actually been run: a `LOCAL_ONLY` task with no local model
is refused, never escalated. TQ-57 produces the first `measured:` block.

Two things worth carrying into it. **A model that needs an unmerged PR is not a runtime this
project has**, and that applies to any candidate, not only this one — the honest column is "runtime
available today", not "runtime announced". And **§108's rule is live and unchanged**: a `LOCAL_ONLY`
task with no local model is refused, never escalated. Finding that the headline candidate does not
fit does not soften that; it is the reason the rule was written to be true today rather than after
a download.

Two failure modes stay refused, and they are why this paragraph is longer than the answer:
**substitution** — if what turns up is not an obtainable open-weight local model, the pool is
Llama + DeepSeek + Qwen/Mistral/Gemma and that is recorded as a finding, never filled in with
something similarly named (§102's original refusal, still standing) — and **fabrication**, if the
survey cannot find the licence or the weights, the row says `unknown` and the candidate is out
until somebody supplies them. An owner's identification settles which vendor to go and read; it
does not settle what the model is.

Output is a decision an owner can act on: the initial pool, named, with the reason each candidate
is in or out.

### TQ-53 — Task Signature, task categories, and the complexity vocabulary

**NEED (GREEN) · DONE 2026-08-26 (`SPEC_RECONCILIATION.md` §104) · depends on TQ-51 (done) ·
addendum 45 §20, §21, §42, §45 Phase A**

The vocabulary everything else keys off, and buildable today with no model behind it.

`TaskSignature` (§20's fifteen fields), the eight task categories (§42) and the complexity levels
(§21) as **closed vocabularies, fail-closed on read as well as write** — the house rule
`gateway/portfolios.py` and `gateway/holdings.py` already work under.

Exactly the eight categories §42 names, and no more: "do not prematurely create dozens" is the
instruction, and the project has its own version of it in §70 and §100 — one model of one fact.

Note for the record and not for action here: **`CREATIVE_GENERATION` has no consumer in a
financial intelligence system.** It is built because §42 says start with exactly these eight, and
it is expected to carry no traffic. If it still has none when TQ-62 has evidence, merging it is
the review §42 anticipates.

**Done** (§104), as `app/task_signature.py`. Four of §20's fifteen fields turned out to name facts
this codebase already had words for: `agent_role` is `ROLE_CHARTERS`, `error_cost` is the
registry's `criticality` (**one vocabulary**, tied by a test), `latency_sensitivity` diverges from
the registry's free-text `latency_tolerance` (**recorded, not reconciled** — the prose carries
measurements a closed vocabulary would lose, so TQ-60 owns it), and `privacy_level`'s `LOCAL_ONLY`
shares a name with `DataClass.LOCAL_ONLY` while meaning something different — a *task* constraint
versus a *field* classification, joined by a one-way derivation `privacy_floor_for()` now makes
mechanical. Privacy is **required rather than defaulted**, and nothing in the module ranks or names
a model — asserted, not trusted. Mutation-tested six ways, six caught.

### TQ-54 — Model Performance Registry and the eight leaderboards, seeded provisional

**NEED (GREEN) · DONE 2026-08-26 (`SPEC_RECONCILIATION.md` §105) · depends on TQ-51 (done),
TQ-53 (done) · addendum 45 §8, §9, §10, §11, §12, §13, §45 Phase A + C**

The competition, as data. §8's fields, per model per task category, with §12's initial ordering
seeded by hand and **marked `SEEDED` / `PROVISIONAL`** — the same discipline
`model_registry.yaml` already applies with `provisional: true` on every row (§35 §2).

The three properties that make it a competition rather than a table, each with its own permanent
test:

- **§11 — a failure in one category does not demote globally.** A model may lose rank in
  `LONG_CONTEXT_AND_MEMORY` and stay leader in `CODING_AND_DEBUGGING`.
- **§10 — outcomes move rank.** Penalties and rewards, tunable.
- **§13 — no permanent privileged position.** A front-runner can fall behind a runner-up; a
  challenger can become leader.

Empirical evidence must be able to **dominate the seed** once it exists (§12), which means a
seeded score and a measured score are distinguishable in the schema rather than averaged into one
number nobody can interpret later.

No model calls. The registry is real; the data in it is honestly labelled as a guess.

**Done** (§105), as `app/model_performance.py` — storage following `app/model_budget.py`'s
shared-ledger pattern. The seed is stored once and the composite derived on read, so §12's
"empirical data should dominate the initial seed" happens by arithmetic rather than by anybody
deciding; §11 is structural, since `record_outcome` has no statement that reaches another
category's row. `routing` is now `seeded_leaderboard`.

Two things came out of building it. The **hand-authored seed ordering moved into
`docs/model_registry.yaml`** as `seed_ordering`, because the rung's tripwire has to run in CI and
CI has no database — which sharpens §103's split rather than contradicting it: human decisions in
the committed file, machine writes in the database. And **§103's ladder had a hole its author fell
into**: `enforced: true` was set and the marker moved before the rung's assertion existed, and the
suite went green. A flag in a YAML file recorded an intention and read as a fact. Now
`ENFORCED_STAGES` is declared beside the tests that implement it and the YAML must agree.
Mutation-tested eight ways, eight caught.

### TQ-55 — The Routing Decision Record

**NEED (GREEN) · DONE 2026-08-26 (`SPEC_RECONCILIATION.md` §106) · depends on TQ-53 (done) ·
addendum 45 §26, §32, §45 Phase A**

§26's fields, written from the first routing decision onward rather than added once there is
traffic worth analysing — a log that starts late is a log with a hole in it exactly where the
early mistakes are.

Records the decision *and* its outcome: estimated versus actual cost and latency, validation
result, quality score, `was_escalation_worthwhile`. That last field is the one the whole lineage
is for.

**Done** (§106), as `app/routing_decisions.py`, sharing `model_performance.db` with the
leaderboards — §26's outcome fields are the same facts that feed `record_outcome`, so `complete()`
is the single write path that closes the log and scores the tally. §26's four duplicated fields are
derived from the stored signature rather than re-stored; `risk_level` turned out to be the **third**
name in this codebase for one fact (`criticality`, `error_cost`, `risk_level`) and reads off the
signature rather than adding a column.

Running §25's own portfolio-analysis example found a **§36 violation nothing would have noticed**:
a `LOCAL_ONLY` step escalated to an external model and the log recorded it silently. `privacy_
violation` is now derived on read and counted in `summary()` — §41's `PRIVACY_MISROUTING`,
detected here and prevented in TQ-60. Detection, never refusal: a log that would not record a
violation hides what it exists to reveal. Mutation-tested eight ways, eight caught.

### TQ-56 — `LocalAIService`: the interface and its conformance suite, with nothing behind it

**NEED (GREEN) · DONE 2026-08-26 (`SPEC_RECONCILIATION.md` §107) · depends on TQ-53 (done) ·
addendum 45 §4, §45 Phase A**

§4's interface, built the way TQ-45b built `PortfolioProvider` (§101) — because that increment
just proved the pattern and found a real hole in it by attacking it.

**The conformance suite is written before the second implementation**, for the reason §101
records: a contract with a single implementation is a description of that implementation. The
guard, applied to every contract test: *could a provider that must load a multi-gigabyte model off
disk satisfy this?* If it needs an in-process stub, the test is wrong.

Ships with no model. A stub implementation that refuses honestly is the whole of it, and that is
not a placeholder — it is the shape `ManualPortfolioProvider` has in §101, and it is what makes
the capability declaration testable before any hardware is involved.

**Agents must never call a local model directly** (§4, §47) — a source-scan tripwire in the style
of `test_nothing_outside_portfolios_queries_the_portfolios_table`, so the rule survives review
rather than depending on it.

**Done** (§107), as `app/local_ai.py`. `NoLocalModelsService` ships as the honest description of a
machine with no runtime, and a `_FakeLocalService` in the suite gives the contract a second
implementation that genuinely differs — without it every refusal test would pass vacuously.
`infer()` (no model named) refuses naming TQ-60, because choosing needs privacy, hardware and
budget as well as the leaderboard. `InferenceResult` splits `load_ms` from `latency_ms`, turning
§102's 8 GB finding into a constraint the type enforces: a cold load may not go unreported, so a
ranking cannot learn about disk speed and file it as reasoning quality. An unrunnable benchmark
returns `passed=None`, never `False` — a model that could not run has not failed, it has not taken
one. The runtime tripwire is planted before any runtime exists.

A source scanner was too crude for the **third** time (§101, §104, §107), so
`conftest.executable_source()` is now the one implementation of "read only the code" and all four
scanners use it. Mutation-tested ten ways, ten caught.

### TQ-57 — The first local model actually running behind the service

**NEED (YELLOW) · QUEUED — next once TQ-52 unblocks · depends on TQ-52, TQ-56 (done) ·
addendum 45 §44, §45 Phase B**

Where artifacts arrive: runtime, one model from TQ-52's approved pool, health checks, hardware
monitoring, launch scripts, and a baseline benchmark. It must satisfy TQ-56's conformance suite
**unchanged** — if it has to modify a test, the contract was wrong, not the model.

**Do not commit model binaries to git** (§44). Storage layout and `.gitignore` are part of this
entry, not an afterthought — the repository is small and must stay so.

YELLOW rather than GREEN because it is the first entry that depends on a download, a licence and a
GPU behaving, none of which is under this project's control.

### TQ-58 — The rest of the pool, each entering as a challenger

**WANT · QUEUED · depends on TQ-57 · addendum 45 §34, §43, §45 Phase B**

§34's model addition process, run once per additional candidate: verify licence, verify hardware
fit, install, baseline benchmark, provisional scores, enter the challenger pool.

A new model enters as a **challenger, not as a leader** (§34), whatever anybody expects of it.
§43's "do not assume every model must remain permanently installed" applies here with force at
8 GB: what is resident and what is on disk are different questions.

### TQ-59 — The deterministic-first check, and the capability/escalation decision

**NEED (GREEN) · DONE 2026-08-26 (`SPEC_RECONCILIATION.md` §108) · depends on TQ-53 (done),
TQ-54 (done) · addendum 45 §3, §16, §17, §19, §45 Phase D**

§3 is explicit that these are **two decisions that must not be conflated**, so they are two
entries. This is the first: *can this be done without a model at all, and if a model is needed, is
local enough?*

§19's deterministic-first check comes before any of it — "AI should not be used merely because AI
is available" — and it is the cheapest, most testable part of the whole lineage.

The escalation decision is itself an intelligent task with its own leaderboard
(`CAPABILITY_AND_ESCALATION_DECISION`, §17), and the model best at making it may not be the model
best at doing the work. That is the point of giving it a category rather than a constant.

**Done** (§108), as `app/capability.py`. The useful discovery: **this project was already doing
§19 in four places** without a name for it — `holdings.concentration`, the Explorer's IV-surface
detector, the ARB-* detectors, and slot allocation. `DETERMINISTIC_CAPABILITIES` records that
practice rather than imposing a new constraint, with each entry's `code_ref` asserted against the
filesystem.

The live case it settles: **a `LOCAL_ONLY` task with no local model is REFUSED, not escalated.**
Falling back externally would be helpful and would break the one rule §36 states without
qualification. `PATH_REFUSED` is deliberately not an execution path — there is nothing to log when
nothing ran — which closes §106's finding from the other end: TQ-55 could only *detect* a
`LOCAL_ONLY` task that had already gone external; routed through this module that decision is
never made.

`forced` marks a constraint apart from a heuristic, so §17's leaderboard never scores a model for
"getting right" a call privacy made for it. Mutation-tested nine ways, nine caught, including both
privacy mutations.

### TQ-60 — Model selection, with policy and resource overrides

**NEED (GREEN) · QUEUED — next once a local model exists · depends on TQ-54 (done),
TQ-59 (done) · addendum 45 §9, §18, §24, §25, §35, §36, §45 Phase E**

§3's second decision: *which model?* Task signature to leaderboard to front-runner, with
runner-up fallback and §9's override reasons.

Two overrides that are **not** performance and must beat the leaderboard outright:

- **Privacy** (§36). `LOCAL_ONLY` / `LOCAL_PREFERRED` / `EXTERNAL_ALLOWED` / `EXTERNAL_REQUIRED`.
  Sensitive data never leaves the machine because an external model ranks higher. This project
  already has the shape of that rule in the Gateway's capability gating, and client holdings are
  the obvious `LOCAL_ONLY` case.
- **Hardware** (§35). The theoretically best model is not selected if it cannot run right now.
  At 8 GB VRAM this is not a corner case, it is the common path.

Routing at **task-step** level as well as whole-task (§25) — §25's own example is portfolio
analysis, which this project has.

### TQ-61 — Challenger mode and the exploration policy

**NEED (GREEN) · QUEUED · depends on TQ-54, TQ-60 · addendum 45 §13, §14, §15, §33,
§45 Phase I (partial)**

The entry that stops the system from being trapped by the original human guess, which §13 names as
the specific risk of seeding rankings by hand.

Exploration rate (§14), scheduled leader-versus-challenger runs (§15), and periodic re-evaluation
of a stable leader (§33). Both models get the same task; an evaluator compares correctness,
completeness, instruction following, format compliance, latency and resource use.

At 8 GB VRAM, leader and challenger **cannot both be resident**, so comparisons are sequential and
the latency figures need care: a model that had to be loaded from disk did not take longer to
think. Measure them separately or the ranking learns the wrong lesson.

### TQ-62 — The evaluator, and validation before penalty

**NEED (GREEN) · QUEUED · depends on TQ-54 · addendum 45 §38, §39, §45 Phase F (partial)**

Deliberately queued **before** the simulation competition, because §38 is a precondition for
scoring rather than a refinement of it: *validate before penalising*, and **"a model should not
lose points solely because another model disagrees."**

Validation first where it is free and certain — unit tests, schema checks, syntax checks,
deterministic recalculation, known-answer checks — and an evaluator model only where it is not.
The evaluator itself is monitored for bias and error (§39), which means it needs a scorecard like
everything else.

### TQ-63 — Simulation competition

**NEED (GREEN) · QUEUED · depends on TQ-57, TQ-61, TQ-62 · addendum 45 §27, §45 Phase F**

§27's proving ground: a representative benchmark set from real agent tasks, front-runner versus
challenger, candidate versus candidate, scored and fed back into the registry until the seed bias
is measurably reduced (§12, §13).

This project already runs a real agent population under the `simulation` pytest marker, which is
what makes §27 buildable here rather than aspirational.

### TQ-64 — Historical simulation

**WANT · QUEUED · depends on TQ-63 · addendum 45 §28, §45 Phase G**

Replay historical tasks and historical project/market data against the rankings simulation
produced: do they hold, or did the benchmark set flatter somebody? Refines penalties, rewards and
escalation thresholds against workloads nobody designed for the test.

### TQ-65 — External providers, and their task-specific scorecards

**WANT · QUEUED · depends on TQ-60, TQ-62 · addendum 45 §22, §23, §37, §45 Phase H**

§23's `ExternalAIProvider` — **partly built already**: `app/model_provider.ModelProvider` is a
Protocol with `AnthropicProvider` behind it, named for its vendor precisely so a second can exist.
This entry extends rather than replaces it, and TQ-51's decision about one-registry-or-two governs
where the scorecards live.

§37's cost model, both halves, and the half that gets forgotten is the local one: **local
execution is not free** — GPU time, power, queue time, and blocking other agents while a 5 GB
model holds the card.

### TQ-66 — Observability and the routing error types

**NEED (GREEN) · QUEUED · depends on TQ-55, TQ-63 · addendum 45 §40, §41**

§40's metrics and §41's eight named error types, of which two matter most because they are the
ones a routing system gets wrong in *opposite* directions and can hide behind each other:
`UNDER_ESCALATION` and `OVER_ESCALATION`. A system optimising cost drifts to the first; one
optimising quality drifts to the second; a dashboard showing only "escalation rate" shows neither.

### TQ-67 — Routing knowledge, and its lifecycle

**WANT · QUEUED — precondition unclear · depends on TQ-63, TQ-66 · addendum 45 §30, §31, §32**

§30 requires routing knowledge to join "the linked, multi-entry knowledge architecture", and §31
gives learned knowledge a lifecycle: `OBSERVED` → `PROVISIONAL` → `VALIDATED` → `STRONG` →
`DEGRADED` → `RETIRED`, with evidence counts and contradictory evidence tracked.

**The precondition is not obviously built.** Nothing in this repository matches "linked,
multi-entry knowledge architecture" as a thing that exists, and this entry should not pretend
otherwise: before it starts, somebody has to say whether that architecture is an existing subsystem
under another name, a separate unqueued task, or something this entry creates. Recorded as unclear
rather than assumed — see §102.

The §31 lifecycle is independently valuable and could be built against the registry alone if the
larger architecture turns out not to exist yet.

### TQ-68 — Production routing thresholds

**WANT · QUEUED · depends on TQ-63, TQ-64, TQ-66 · addendum 45 §29, §45 Phase I**

§29's live-entry rule: before production the system must *know*, with stated confidence, the best
local model per major category, the runner-ups, the failure patterns, when to escalate, the
preferred external model per class, and the approximate cost and latency of each.

Then the thresholds, privacy rules, budget rules, exploration rate, challenger schedule and
dashboards. **The production result may use different models for different jobs, and there may be
no single universal winner** (§47) — the queue entry says so because a plan that quietly expects
one winner will be read as a failure when it does not get one.

Not a licence to expose anything: §50's preconditions still stand, and nothing in this lineage
changes them.


### TQ-42 — Client-owned holdings

**NEED (GREEN) · DONE 2026-08-26 · owner direction 2026-08-26 ·
`SPEC_RECONCILIATION.md` §96**

The data model §95 named as the real blocker: a client's holdings, owned by the
client, so `portfolio_analysis` can exist without handing anybody the operator's book.

Holdings come from the client telling their representative — the only honest producer available,
and the relationship addendum 43 §16 describes rather than a mechanism beside it. No account
column at all (stronger than stripping one on egress), arithmetic computed rather than narrated,
and nothing ever valued because every price here is simulated. That last constraint produced a
more precise successor skill: `portfolio_valuation`, newly declared and unbuilt.

Ships with simulated clients (`python -m gateway.demo_clients`) per owner direction, built so
that removing them before live is a command: flagged rows, seeding refused outside PRE_ALPHA and
ALPHA, and an `outstanding()` check so a pre-launch step can know rather than hope.

### TQ-43 — Per-client Gateway credentials

**NEED (YELLOW) · DONE 2026-08-26 · exposed by TQ-42 · addendum 43 §15/§16, addendum 44 §3.2/§9.2/§9.3 ·
`SPEC_RECONCILIATION.md` §98**

The Gateway has one credential per *role*, so every client shares one password and therefore one
subject. Everything downstream is already per-client — conversations (§93), the representative's
identity (§93), holdings (§96) — and all of it keys off a subject that only one person can
currently be.

This is why TQ-42's demo ships three clients but only one that can log in. The isolation is real
and tested; the doorway is what does not exist yet.

Flagged YELLOW rather than GREEN because it is a precondition for exposure rather than for
correctness: nothing today is reachable beyond loopback (§50), and a client Gateway with one
shared client password must not be the thing that changes that.

### TQ-39 — The client agent gets an identity

**WANT · DONE 2026-08-25 · addendum 43 §16, 41 §24 · `SPEC_RECONCILIATION.md` §93**

Turned out to contain a breach rather than only a feature: the Gateway had one conversation for
the whole database, so a client's socket opened onto the operator's transcript. Reproduced, then
closed — conversations now belong to the subject who logged in. §93 records it.

43 §16 gives the personal client agent a name, a face, a voice, scoped memory and relationship
continuity. TQ-34 built the boundary it sits behind; the agent behind it is still the Gateway's
generic assistant. The mechanism already exists — `coo_identity` (§88) is the same shape, one
organization-scoped identity with its own versioning — so this is that pattern applied per client
rather than new machinery.

### TQ-41 — Sweep every comparison against a clock

**NEED (GREEN) · DONE 2026-08-26 · owner request · `SPEC_RECONCILIATION.md` §94**

Three bugs in three days shared a shape (§90, §91, §93). Sixty-three comparisons audited: one
more bug (`status_events`' inclusive `since`, compensated for in one of two briefing call sites
and not the other), and a rule that is *not* "always use strict" — equality must give the answer
a zero-width window demands, and which answer that is depends on which side the window sits.
A blanket rule would have broken `list_stale_active_agents` in the direction of never marking a
crashed agent crashed.

### TQ-40 — The client agent's skills

**WANT · DONE 2026-08-26 · owner direction 2026-08-25 · `SPEC_RECONCILIATION.md` §95**

The owner's framing: "initially this will be limited to giving info and later this agent will
have many abilities such as portfolio analysis and trade ideas and many other skills yet to be
decided."

The mechanism is decided even though the skills are not: **each skill is its own capability and
its own entry in `TOOL_CAPABILITY`**, never a widening of what `converse` means. That is what
keeps a client agent that gained portfolio analysis from silently having gained the ability to
read the repository — the failure §92 exists to prevent, arriving later by a different route.

**This entry's own premise was wrong and §95 corrects it.** "Portfolio analysis needs a
portfolio" implied there is none; `app/tools/portfolio.py` has read `data/portfolio.xlsx`
through a two-layer consent model since long before this was written. The real blocker is that
there is exactly one such file and it belongs to the *operator* — wiring it to a Gateway client
would hand an external person somebody else's positions.

That finding added the field §92's mechanism was missing: a capability answers "may this role
invoke it", not "whose data does it read". Skills now carry a **scope**, and no skill a client
can invoke may read organization data — checked at import, because a registry mistake is a
permissions mistake.

Both named skills ship **declared and unbuilt, with specific reasons**, so the agent answers the
question truthfully instead of improvising. Still genuinely blocked: portfolio analysis needs
client-owned holdings (a data model, not a wire-up), and trade ideas need output this system is
willing to stand behind — everything it generates is simulated (addendum 25), and a trade
suggestion is the most dangerous place to blur that.

Phase D. The Gateway already exists as an authenticated boundary with one Super User; what 40 §13
adds is *roles* — internal authorized, client/external meeting a named personal agent, and a
scoped demo mode — with 40 §14's rule that the presentation layer must never bypass backend
authorization just because the data exists on the server. Gated behind the exposure preconditions
TQ-04 and §50 already record: nothing is exposed beyond loopback today, and roles do not change
that.

---

## Blocked

### TQ-B1 — ARB-013 and ARB-014 (forward/futures detectors)

**RESOLVED — `SPEC_RECONCILIATION.md` §61.** The blocker was always the instrument, and TQ-14's
first scope item built it: the world lists forwards in the four forward variants' scenarios,
and ARB-013/014 price against them under `scan_forward`. What remains of this entry's original
wording is the *futures* half: the built instrument is a forward (no variation margin, no
convexity), and a futures adapter owes addendum 27's adjustments before reusing the detectors —
deferred until a futures instrument has a reason to exist.

### TQ-B2 — ARB-012 (calendar consistency)

**RESOLVED — `SPEC_RECONCILIATION.md` §56.** This entry's premise was half wrong and §56 corrects
it: the world has priced three expiries per scenario since Day Zero; what was missing was the
cross-expiry detector shape, the clean-world guarantee across expiries, and the wiring. ARB-012 is
built on the genuinely proven rules (puts unconditionally, calls only dividend-free — the first
derivation's dividend credit was refuted by the clean-world property test), trained by a
whole-ladder-lift variant under its own strategy, and wired through Explorer, evaluation, and
diagnosis. Two §45-class world findings were fixed on the way.

### TQ-B3 — ARB-017 / 019 / 020 (American exercise family)

**Source: addendum 27 §11 Phase 2, §6.** Blocked: the library's `STYLES` deliberately refuses
non-European snapshots (applying European parity to American options is the spec's №2 guarded
error), and the world generates European chains only. Unblocks with an American-style world *and*
the §6 scenario engine — a substantially larger increment than any detector.

## Deferred, with reasons

- **Parliament, ministers, elections, two-tier voting, committees, Cabinet** (addendum 32 §2–§11,
  §17–§18, §33–§36) — requires an agent population with standing, elections measuring real trust,
  and an owner decision on human Board composition. At the current population (a handful of
  role-agents on one machine) the machinery would be ceremony without constituents. The queue and
  classification conventions are adopted now (this file); the parliamentary procedure is not.
- **Emergency Defense Mode, Threat Intelligence branch, Edge/DDoS defense** (addendum 28 §5, §6,
  §20) — nothing is exposed beyond loopback; the Gateway's own spec keeps the host loopback-only.
  These activate with actual exposure. TQ-04 records the posture so the trigger is explicit.
- **Multi-region, multi-zone, clean-room recovery, failover orchestration** (addendum 29 §14,
  §18–§21, §34) — single-machine deployment; there is no second failure domain to fail over to.
  TQ-02 creates the first recovery copy, which is the honest first rung of 29 §44's maturity ladder.
  **Half of this is now real** (`SPEC_RECONCILIATION.md` §68, §69): the suite is proven green on
  Linux, so a second domain no longer means a second Windows machine; and the *data* domain is
  configured and rehearsed — encrypted backups now leave this disk to a Dropbox-synced folder,
  with a verified restore (40 tables, `integrity_check: ok`). What stays deferred is the *host*
  domain: nothing is provisioned, because that spends money and needs an account, and
  `docs/SECOND_FAILURE_DOMAIN.md` is the runbook for the owner to do it. Failover, live
  replication and geographic separation remain out of scope.
- **Distillation of addendum 33 into constitutional directives** (33 §0) — the constitution is held
  privately; distilling into it is an owner action, not a repository action.
- **Evolution Directives / trainer hierarchy as separate machinery** (addendum 30 §4–§6) — the
  training loop built under addendum 13 already performs train→evaluate→certify with separated
  roles; §47 records the mapping. New machinery only when a real systemic evolution needs a
  directive the existing loop cannot express.
- **Education's departmental machinery: Curriculum Architect and trainer agents** (addendum 36
  §1–§2, §5) — the function exists distributed across the addendum-13 loop (versioned
  strategies, evaluation feedback); a role-holding agent waits, per §47's precedent, until a
  curriculum need the existing loop cannot express. The **professor layer** defers itself
  (36 §2.3). §60 disposition 3. **Partially fired 2026-08-26 (§114): a curriculum need arrived
  that the loop cannot express — see TQ-76. The curriculum lifts; the role-holding agent does
  not, on the same test one level up.**
- **Model routing, fallback, and the migration lifecycle** (addendum 35 §7, §10) — activate
  when the Model Registry (TQ-16) holds a second model worth routing to; a routing engine with
  one route is machinery without a decision to make. §60 disposition 2.
- **The Optimization Agent as a dedicated role** (addendum 37 §4) — the discipline is adopted
  (O1–O9, practiced once in §58) and its measurement substrate is queued (TQ-18); the
  role-holding agent waits with the rest of the departmental machinery. §60 disposition 4.
- **Leadership collaboration gate enforcement** (addenda 34 §18, 36 §9, 37 §9) — no promotion
  machinery exists to gate. Recorded in §60 disposition 5 as a standing constraint that binds
  the day promotion machinery is built.
- **Multi-viewpoint staged debate, including model-diversity debate** (addendum 34 §3, 35 §9)
  — the §47 parliamentary deferral, unchanged; the model-diversity detail is preserved in §60
  disposition 6 for the day a parliament exists.
- **The animated human presenter** (addenda 40 §8.2, 41 §3–§6/§12/§13) — now with a name,
  Kumbhakarnan, and a fuller brief: standing, turning, gesturing, facial expression and body
  language. It remains a substantial project and the reasoning is unchanged, with one addition from
  41 §3 that makes the shortcut worse rather than better: a *static portrait is explicitly ruled
  out*, so a still image standing in for the presenter would fail the specification rather than
  approximate it. The honest placeholder is a frame that says what it is waiting for (TQ-37).
- **The animated human presenter, original-design constraint** (addendum 41 §4, 42 §20) — when it is
  built, the character must be an original interpretation inspired by the Kumbhakarna tradition and
  must not copy any specific film, television, comic, game or commercial depiction. Recorded here
  because it is a constraint on *how* it is made, not a reason to defer it.
- **The animated human presenter (original entry)** (addendum 40 §8.2) — a believable animated person with gaze,
  lip-sync, posture and gesture is real-time avatar rendering plus viseme-driven speech timing: a
  substantial project, and one where a poor result is worse than none, because an unconvincing
  figure damages trust in the intelligence behind it (§81 disposition 4). The *choreography* half
  — pointer, spotlight, panel focus — is separable, carries most of the communicative value, and
  is queued as TQ-33. The figure itself waits for a deliberate decision to build or buy it.
- **Intent-based work model** (addendum 40 §12) — "take last year's rental accounting file, update
  it, send it to my accountant" requires tool-use over the file system, spreadsheets and email
  under an authorization model that does not exist yet. It is the north star's mechanism, not a
  next increment; the Gateway's capability boundary (addendum 28) is where its safety story has to
  start.
- **AI-first minimal host** (addendum 40 §21, Phase E) — the direction, explicitly, rather than a
  deliverable. Recorded so it stays a direction rather than quietly becoming a plan.
- **Simulation maturity stages 3–9** (addendum 34 §20) — role workflows through continuous
  whole-organization Monte Carlo, historical validation, shadow operation. The world is at
  stages 1–2; TQ-14 is the honest next rung, and each further stage is its own increment
  gated on the one before it.

### TQ-101 — The Personal Usher, and the half of it that already exists

**NEED (ORANGE) · QUEUED · addendum 50 §6, §9, §10 · addendum 49 §10, §11, §12, §13 ·
addendum 51 §15, §16, §17 · `SPEC_RECONCILIATION.md` §143 §3**

The client's primary host and orchestrator, and the role both Providence documents build
toward. **Half of it is already built and was found rather than designed** (§143 §3):
`gateway/client_agent.py` has given each client a persistent, named, client-bound
representative — with voice, visual identity, and continuity across meetings — since
addendum 43 §16, without Providence's vocabulary. That is §131's shape again, where
cooperation had been measured for months as `cross_check.unanswered_rate`.

What exists: a stable identity per client, relationship continuity as two facts (last seen,
meetings), and a client profile to be personal about (TQ-98).

What does not: **the conversational half, and it is the whole difficulty.** Addendum 51 §16
lists fifteen intent types, and the Usher must tell `FACT_REQUEST` from `THINKING_ALOUD` from
`COMPLAINT` *before* answering. 49 §11 and §13 make that a requirement rather than a nicety —
patience, and relationship before correction.

**The question this entry owns, and it comes before the code:** intent classification is the
first thing in this system that genuinely needs a model to read text, and §126 established
what happens when code is asked to obey prose. `if "?" in text` is a parser pretending to be a
reader. So either it waits for addendum 45's local intelligence, or the seam where a model
answers is in the design from the first line — and what happens when no model is reachable is
part of that design, not an afterthought.

Do not build a persona layer here. TQ-100 owns what refuses a persona that crosses the line,
and it is unanswered.

### TQ-102 — The right to appeal an unfavourable ruling

**NEED (ORANGE) · DONE — `SPEC_RECONCILIATION.md` §145 · owner direction 2026-08-28 ·
addendum 32 §19 · addendum 46 §11 · `SPEC_RECONCILIATION.md` §144 §4, §137**

`backend/appeal.py`. **The hard question dissolved rather than being answered.** All three
candidate adjudicators fail — a standing one is removable by whoever appointed it, Parliament
contains the author, and the owner is what the charter already says is not an appeal. The
charter's requirement is *"reviewed by someone other than whoever made it"*, which needs a
**peer of the author**, not a court. Nothing is appointed, so nothing can be removed — and it
is 46 §10's *work determines staffing* again, the rule that gave the Portfolio Analyst
`on_demand` instead of a new agent class.

**Two of the charter's three unenforced protections were the same missing thing**: you cannot
appeal a ruling you were never told about. `rulings_about` is derived from the join
`compliance.self_evaluated` already used, so there is no notification table and no sweeper
whose stopping would look like an organization with nothing to report.

**An appeal that lapses is a denial nobody had to make**, so there is no dismiss, deny, expire
or delete — asserted over the parsed module. `summary` reports filed *and* heard, because zero
appeals filed and forty filed with none heard are the same silence in one number (§130).

`UNENFORCED_COUNT` went 3 → 2 and **only one change was a discharge** (§145 §5). Appeal is
enforced; *"an agent is told what is found about it"* is not, because the read path now exists
and nothing reads it — being told is passive in a way that having a right is not.

<details><summary>The entry as it was queued</summary>

Named by the owner as one of two examples of the *"undeniable and inalienable"* fundamental
rights that belong in the Constitution: **the right to appeal an unfavorable ruling.** The
other, the right to vote, is built.

**This system already declares it owes this and does not provide it.** `backend/charter.py`
has carried *"a settled matter can be appealed"* as aspirational since it was written —
*"no adjudicator exists... the owner is both first and last instance, which is not an
appeal."* The finding is that the charter was right and the reason beside it had gone stale:
*"deferred until a contested caseload justifies it"* is a volume argument, and a fundamental
right does not wait for demand. Corrected in place at §144 §4.

**What it requires is one sentence and one hard problem.** The charter states the requirement:
a ruling an agent believes wrong is reviewed *by someone other than whoever made it*. That is
addendum 46 §11's independence rule arriving from a third direction — the producer is not the
approver (TQ-83), the grader is not the producer (§117), and now the reviewer of a ruling is
not its author.

The hard problem is **who adjudicates**. This organization's only non-owner authority is a
vote, and:

- An adjudicator appointed by simple majority can be removed by one, which makes an appeal
  reviewable by whoever is currently winning.
- Routing every appeal to Parliament makes the electorate the appellate court, and the
  electorate contains whoever made the ruling.
- Routing it to the owner is what happens today, and the charter already says that is not an
  appeal.

So this is a governance design before it is a function, and the design decision is the
deliverable. Note that a right established constitutionally would need two-thirds to remove,
which is the first thing in this system that would actually use §142's machinery for the
purpose the owner described.

**Related and not the same:** §137's missing reviewer role. An adjudicator and a reviewer are
both *somebody other than the author*, and whether they are one role is part of this entry.

</details>

### TQ-103 — Let an agent read its own record, and act on it

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §146 · addendum 47 §14 ·
`SPEC_RECONCILIATION.md` §145 §5, §145 §6 · organization-model declared gap 1**

Done, and it found the thing that made it worth doing: **every grade this organization has
ever produced was written by its own producer** (§146 §1). Nine of nine in a full run, detected
by `compliance.self_evaluated` since it was written, read by nobody.

That gave the appeal a ground that is a fact rather than an opinion — the grader was the
producer, and the grade declared the work not worth the compute — so no threshold is invented
and an agent is not appealing on a schedule.

**The loop ran live and unprompted in a 90-second baseline run:** Analysis graded its own work,
read its own record, appealed; nobody was eligible; the COO enqueued a spawn saying *"has an
appeal waiting for somebody other than its author to hear it"*; the peer that arrived overturned
it — on the ruling's **independence**, explicitly not on the work's quality. 13/13 properties
still passed, and the favourable grade was left alone.

**What it does not fix is the larger half** (§146 §6): grading is still not independent, and an
overturned grade changes nothing downstream. TQ-104.

<details><summary>The entry as it was queued</summary>

TQ-102 built the read path and left the telling. `backend.appeal.rulings_about` returns every
grade made about an agent's own analyses, and **nothing in `agents/` calls it** — so an agent
that does not think to look is still not told, and the charter keeps
*"an agent is told what is found about it"* as unenforced for exactly that reason.

Small, and it is the increment that turns two mechanisms into behaviour:

1. An agent's cycle consults its own rulings.
2. Having read one, it may file an appeal — which nothing currently does, so the right built
   at TQ-102 is available and unexercised.
3. The COO spawns a peer when an appeal is waiting. An appeal is workload, 46 §10 says work
   determines staffing, and `appeal.unheard()` already makes the condition visible. Without it
   this organization — one of each role — heard appeal is rare by construction.

**The trap to write against:** an agent that reads its grades and changes nothing has closed
declared gap 1 on paper. §118's rule — *absence of complaint is not evidence of competence* —
means the test has to require the reading to *appear* in what the agent does, not merely to
have happened.

### TQ-104 — Grading that carries independent information

**NEED (ORANGE) · DONE, AND ITS PREMISE WAS FALSE — `SPEC_RECONCILIATION.md` §147 ·
agent charter (duties) · addendum 7 §8 · addendum 46 §11**

**Grading was already independent.** A grade is a ruling about the *upstream report* —
`agents/analysis.py`'s own prompt says so — and Analysis, its consumer, writes it. §146's finding
was wrong and is retracted in place.

What the check found instead is worse than what it retracted. `compliance.self_evaluated`
compared the grader to the **analysis result's** producer, which `agents/analysis.py` makes one
identity by construction — so it flagged every grade ever written, **could never return false**,
and was named in `backend/charter.py` as the mechanism enforcing a duty. A charter citing a check
that cannot fail is the falsely-written charter that file exists to prevent, arriving inside it.

Three fixes: the detector re-aimed at the report's producer; `appeal`'s subject model corrected
(the graded party is the report's filer, so TQ-102/TQ-103 had it inverted and §146's live
demonstration ran on a grievance the defect invented); and `record_grade` now requires a
rationale, which it had never validated.

Live: the same scenario now registers seven agents instead of eight and files no appeal. The
extra agent §146 celebrated was the defect.

<details><summary>The entry as it was queued, on the false premise</summary>

**Every grade this organization has ever produced was written by its own producer.**
`agents/analysis.py` records the analysis and the grade under one identity; measured at nine of
nine in a full run. The charter's duty says a grade written by the producer *"looks complete and
carries no independent information, which is harder to notice than an absent one"*, and
`compliance.self_evaluated` has detected exactly this since it was written while nothing read
the detector.

TQ-103 made it **visible and contested** — the affected agent appeals, a peer confirms the
ruling was not independent. That is not a fix. Analysis grades its own work on the next cycle.

Two decisions, and the second is the harder one.

**1. How a grade becomes independent.** Addendum 7 §6–§8 treats analysis and grading as one
handoff, which is why they share an identity — so this is not a bug to patch but a design to
revisit. Options: a second Analysis agent grades the first's output (the peer machinery
`appeal.eligible_adjudicators` already picks); a distinct grader role; or the consumer of the
analysis grades it, which is what the duty literally says and which nothing currently models.

**2. What an overturned grade *means*.** Today: nothing. The `grades` row is untouched by
design — nothing erases a ruling — and whatever reads grades still reads it, so the COO's lens
still moves on a grade a peer found carried no independent judgement.

Excluding overturned grades from what consumes them is the obvious answer and **is not
obviously right**: the organization would lose most of its grades, and losing a bad measurement
is only an improvement if something replaces it. Decide this with option 1, not before it —
independent grading is what makes discarding the old ones affordable.

**The trap:** making Analysis stop grading itself, with no second grader, produces an
organization with no grades at all and a clean `self_evaluated` report. That is TQ-80's defect
exactly — the analyst that stopped asking, and every complaint disappeared.

</details>

### TQ-105 — The Database Vocabulary Contract, and the audits that keep it true

**NEED (ORANGE) · DONE — `SPEC_RECONCILIATION.md` §150 · addendum 53 §3.3, §7.2, §7.3, §7.4,
§7.6, §7.7, §8, §9 · `SPEC_RECONCILIATION.md` §147, §149**

Addendum 53's mandatory remediation, and the systemic fix for the three defects §147 and §149
found. `backend/vocabulary.py`.

**It points at the constants rather than restating them** — a contract that spelled the values
again would be a fourth place to drift. **It audits in both directions**: the source, for query
literals outside the contract; the database, for values outside it. That distinction is the one
that mattered — a value absent from a database may not have happened yet, while a value absent
from the contract can never be written, and only the contract tells them apart.

**A scan that resolved nothing is not a pass.** `check()` returns `INCONCLUSIVE`, reports
literals resolved and rows examined per column, and names what it does not cover (53 §3.3, §9).

**And the write side can no longer invent a value** — `answer_cross_check` validates the
outcome. That direction was entirely missing, and is how `'answered'` survived.

Proven to fail on the two defects that actually shipped, reconstructed as written (53 §5.3
question 3). The live-codebase scan then found no further violations — a claim worth something
only because the same scan demonstrably fails on the two that existed.

**Six of §14's sixteen conditions are not met and are named at §150 §7**, including the one
worth carrying: `metrics.open_at_end` is re-aimed and has **not** been forced to fire under a
run that genuinely ends with a pending cross-check. Re-aimed is not proven.

### TQ-106 — The Software Department as an operating department

**NEED (ORANGE) · DONE — `SPEC_RECONCILIATION.md` §151 · addendum 53 §1, §2, §5, §6, §11, §12 ·
`SPEC_RECONCILIATION.md` §150 §1, §150 §8**

`backend/software_department.py`, `agents/dba.py`, `agents/qa_engineer.py`,
`simulation/property_history.py`.

**The design is five gates on §6's ten steps**, and each corresponds to a defect this project
shipped: a root cause needs all three perspectives, from three identities; a correction needs a
prevention in the same call; closing needs the *name* of a test observed failing; and the verifier
is not the corrector — the fifth instance of a rule already applied four times.

Severity 1 escalates through `parliament.escalate` rather than a second owner queue: there is no
CEO (§150 §2), and its contract — nothing in the system can answer it, no resolve, no expiry — is
already right.

**The DBA is baseline and runs continuously** (53 §11); a failing check *opens an issue* rather
than printing, because `compliance.self_evaluated` flagged every grade for months unread. Live:
eight agents, 13/13, zero issues opened because nothing was wrong.

**QA answers §5.3's third question from evidence already on disk** — 83 run summaries nothing had
read. 8 properties have been observed failing, 66 have not, and it flags the §149 defect (15
passes, only ever `0`). It is a **worklist, not a findings list**, and says so.

**A tripwire caught this increment's own design error**: `test_no_agent_can_tell_it_is_in_a_simulation`
refused the history reader inside the QA agent. The reader moved to `simulation/`. §151 §5 —
the counter-example to §147 and §149.

Not built: the librarian (§13), release gating (§10), and nothing works an issue end to end.

<details><summary>The entry as it was queued</summary>

TQ-105 built the safeguard the remediation list demanded. This is the department itself, and it
is deliberately second: a department created before the defects it was chartered to prevent were
fixed would have inherited them as its first backlog.

What it owes: the three persistent agents (DBA, Software Engineer, QA Engineer), 53 §6's ten-step
issue workflow, §12's severity levels, §11's background operation and scheduled health checks,
and §13's librarian interface.

**§150 §1 adjudicated the staffing question and left one part open.** Three perspectives that
must be independently held is what addendum 46 §11 asks for, and **QA's independence is
load-bearing rather than organizational** — §149 §4 found three defects that survived because the
tests were built from the same misreading as the code, which is exactly what 53 §5.2 forbids.
What is *not* settled is whether they are three processes or one type occupying three roles;
46 §10's *work determines staffing* answers that when the work exists.

**Two things to carry in:** there is no CEO (§150 §2 — the boot function 53 §22 describes is the
COO's, and the naming is unreconciled), and §13's librarian does not exist, so lessons have
nowhere to go that anything reads.

</details>

### TQ-107 — Staff the department's loop

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §152 · addendum 53 §2, §6, §11 ·
addendum 46 §10 · `SPEC_RECONCILIATION.md` §146, §151**

§151 left the department with gates and nobody working them. The whole increment is one
judgement made repeatedly — **which parts of §6's workflow are facts and which are judgements** —
and the value is in what was left alone.

**Two perspectives are facts.** The DBA's database view is transcription of what its check
already established, filed only on issues it opened. QA's verification view answers *why did the
tests not catch it* from one backend fact: was the column contracted at all. Where neither
applies QA says **the question is open** rather than producing a sentence — *a fabricated
verification perspective is worse than a missing one, because it satisfies the gate that exists
to make somebody look.*

**The implementation perspective is a judgement and nothing supplies it**, so the loop reaches
two of three and stops at a wall that says what it needs. Live: the DBA opens and reviews, the
COO staffs QA naming the reason, QA files, and `record_root_cause` refuses.

**Staffing reuses `appeal.roles_awaiting_a_peer`'s shape** in the same shortfall machinery: an
issue nobody can review is an appeal nobody can hear. On-demand roles carry a target of zero, so
this is what brings them into existence at all.

**Two mistakes worth keeping** (§152 §4): the directive reason recorded *"establishing initial
population"* for an agent staffed because an issue needed it, and `ALL_STAFFABLE_ROLES` was a
module-level snapshot that silently ignored a changed target — caught immediately by
`tests/test_slot_allocation.py`. Both are the same error in different clothes: **a value captured
once where the thing it describes can change.**

### TQ-108 — Recover the queue from something that is not working it

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §154 · `ARCHITECTURE_READINESS_REVIEW.md` B7 ·
directive §21.11 · addendum 02 §7 and Scenario C · `SPEC_RECONCILIATION.md` §134, §136**

First Phase 1 increment after the readiness review, and the only one of the five that was a
defect rather than a coverage gap.

`release_stale_claims` returns an abandoned report to the queue, and its sole caller was
`agents/analysis.py` — so **the recovery of the analysis queue ran only while an Analysis agent
was alive.** The single case in which nothing sweeps is every instance of that role being down,
which is exactly the agent-type failure the healing specification is written to survive. The
recovery path had a dependency on the thing it recovers.

**Moved to the COO**, which is the third application of one rule this system already makes twice
in the same function: lens health and source standings are the COO's because *the producer must
not be the judge*. This is the same shape one column along — **the recovery of a queue must not
depend on a worker of that queue.** COO qualifies as the home because the Controller watches and
restarts it, and `executive_failure` already asserts the organization survives losing it, so the
sweeper is covered by a recovery that does not depend on it.

**The existing tests said the function works and nothing said it runs** (§134). Five tests called
`release_stale_claims` directly and all five would have passed with no caller at all. Two source
assertions now name the caller, and **both were observed failing** against a deliberately
reverted tree before being trusted — the rule §149 exists to enforce.

**Live, with the condition forced.** `FI_CLAIM_TIMEOUT_SECONDS=25` puts the timeout below a real
judgment cycle so claims go stale on demand; `baseline_steady_state` then logged
`[COO] returned 1 abandoned report(s) to the queue` twice across 96 COO cycles, 13/13 properties
passing. The production constant is unchanged at 180s, measured against a 42s worst case — the
run lowered it the way `slow_agent` stalls a model call, because **a green run over a condition
that never happened is not evidence about the condition.**

### TQ-109 — Make every claim recoverable, and keep it that way

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §155 · `ARCHITECTURE_READINESS_REVIEW.md` B6, S2 ·
directive §21.11 · `SPEC_RECONCILIATION.md` §134, §136, §149, §154**

Phase 1 item 2, and the review was wrong about all three channels it named.

`coo_directives` has **no claim** — pending → completed in one Controller cycle, so a death
leaves the safe state. `software_issues` has **no claim** — its statuses are completed steps, not
ownership. And the claimed table in engineering is `engineering_directives`, not
`engineering_work`: `claim_next` set `status='in_progress'` and `claimed_by` with **no
`claimed_at` and no sweep**, so an engineer that died holding a directive stranded it forever,
invisible to `open_directives`. One real defect, and not the one named — *a review is not
evidence either* (§136).

**Fixed** with `claimed_at` plus `release_stale_claims`, swept from the COO cycle on §154's rule.
**No lease service was built:** two claimed queues and a third recovering by row expiry is not
three users, and machinery with no user does not get built. The timeouts differ deliberately —
180s is sized against a measured 42s model call, 60s against database work, because `handle`
makes no model call at all. A test asserts they cannot converge on one number fitting neither.

**The durable part is the claim registry.** `tests/test_claim_recovery.py` scans the DDL for
`claimed_*` columns and fails until every table carrying one declares how its claims come back.
It is guarded against being vacuous from both directions: the registry may not name a table with
no claim, so a scanner finding nothing goes red rather than green. `fi_db.SCHEMA_SOURCES` now
serves both the scan and the additive-migration walker, because a second hand-maintained copy
would drift and drift here is a claim nobody checks.

**The finding is bigger than the fix.** `engineering.receive` has **no production caller** —
nothing in the running organization files a directive, the engineer is on-demand and therefore
never spawned, and no scenario touches the department at all. §119 recorded that directives
arrive through an Evolution department that does not exist; the consequence, stated plainly for
the first time, is that **the Software Engineering Department has never been exercised by a
running organization.** This increment fixed something real in the code and unreachable in
production.

**Live:** 96 COO cycles with both sweeps called and no errors, 13/13 properties; and the additive
migration run against a real pre-change database from an earlier run, which is the *no such
column* failure it exists to prevent. The abandoned-directive condition itself could not be
produced live, for the reason above.

### TQ-110 — Register every store, and separate the two things called schema_version

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §156 · `ARCHITECTURE_READINESS_REVIEW.md` B3, S3 ·
directive §21.11 · addendum 42 §9, §23 · `SPEC_RECONCILIATION.md` §89**

Phase 1 item 1, the largest, and blocked by something the review did not see.

The engine registered **2 stores against 66 tables**, so `status()` reported a complete picture
of 8% of the database. Registering the rest was blocked because `Store`'s version contract was
implemented over the **per-row `schema_version` column** — `MAX` for one store, `MIN` for the
other, and a writer issuing `UPDATE <table> SET schema_version = ?` across every row.

**Those are two different things wearing one name.** `fi_db.SCHEMA_VERSION`'s own comment says
bump it *"when the meaning of newly-written rows changes in a way a future reader/grader needs to
distinguish from older rows"* — rows at 2, 3 and 7 coexist on purpose, because a v3
`detector_event` names the lens that produced it and a v2 one does not. Extending the existing
pattern to those tables would restamp every historical row on the first migration and destroy
exactly what a grader reads them for. A duller consequence of the same confusion: `SCHEMA_VERSION`
is 7 while those tables have never been migrated, so registering it as `code_version` would send
the runner hunting six rungs that do not exist.

**`store_schema_versions` now holds the store version and nothing touches the row stamps.**
Twenty-two stores, one per module rather than one per table, with table lists derived from each
module's DDL so they cannot drift. `fi_db` registers itself because `migrations` sits below it;
the engine's own two tables are deliberately not a store, since an engine that versioned its own
audit trail would need itself working to repair itself.

**Backfill refuses to guess.** `BACKFILL_VERSION` is a constant and not `code_version`: stamping
whatever the code says would assert an unknown database is already current. Once any store moves
past 1 an untracked database could be anywhere between, and either guess corrupts — so
`AmbiguousVersion` is raised. The guard cannot fire today; it is written for the day it can.

**A distinction that was true by accident** is now true on purpose: `created` and `present` were
one question while the version was an aggregate over rows, because an empty table had no
`MAX(schema_version)`. `present` is now computed from whether any table holds a row.

**Two tripwires, both observed failing.** Unregistering `parliament` names all six of its tables;
restoring the row-stamp writer fails the stamp test over rows at 3 and 7.

**Live:** 13/13 properties, and the run's own database carries 22 store versions all written by a
real startup. On an earlier run's database, `detector_events` stamps set to 3 and 7 came out
`[(3, 31), (7, 32)]` unchanged with `fi_db` at store version 1.

**Still zero migrations.** The engine has 22 registered stores and no steps — the Knowledge Store
expansion is unblocked and will be `fi_db`'s 1 → 2, the first real rung outside a test.

### TQ-111 — Re-aim a property that could not fail, and measure the write ceiling

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §157 · `ARCHITECTURE_READINESS_REVIEW.md` N8, N2, R3 ·
directive §19, §21.11 · `SPEC_RECONCILIATION.md` §149, §93**

Phase 1 items 4 and 5, closing the phase. Both are one idea from opposite ends: **a clean result
means nothing until you know a dirty one was possible.**

`saturation_two_judges` asserted *"two judgment agents were staffed"* as `population.registered
at_least 7`, enumerating six baseline roles plus two judges. Correct when written; the Speaker and
then the DBA raised the floor **without** any judgment agent to seven, so the property passed with
zero analysis agents. Re-aimed at `population.registered_by_role.analysis at_least 2` — live it
reports `2 >= 2`, at the boundary, where it previously reported `9 >= 7` on the wrong quantity.
Sixth instance of the §149 shape. The new metric is zero-filled across known roles so an unstaffed
role fails with `0 >= 2` rather than *"no metric at ..."*, which would read as a broken scenario.

`simulation/contention.py` measures what SQLite's single writer leaves: N real subprocesses, each
opening the production `Database` against one file. **8/16/24 writers × 300 writes: zero contended,
zero lost, zero duplicated, ~3000 writes/sec.** That zero was not reported until the instrument was
shown to detect the condition — with `FI_DB_BUSY_TIMEOUT_MS=0`, the same run produced **6443
contended, 757 landed, 0 unaccounted, 0 duplicated**, which also proves the invariant holds while
contention is happening.

**Nothing acts on the number** (directive §19 wants evidence, not a preference). The one change is
a name: `Database.Contended`, subclassing `sqlite3.OperationalError` so existing handlers are
untouched. `database is locked` reaching an agent is indistinguishable from that agent being
broken, and at Providence's population it would present as several unrelated agents failing at
once — §93's liveness/progress argument, one subsystem along.

### TQ-112 — The Demonstration Engine, and the demo it cannot give you

**NEED (GREEN) · DONE — `SPEC_RECONCILIATION.md` §158 · Demonstration Engine Specification ·
`SPEC_RECONCILIATION.md` §113, §149, §153, §155, §156**

A subsystem that shows what this system can actually do, orchestrating the real thing. Taking the
specification's own rule seriously — *"if a feature is not implemented, the demo must not pretend
that it exists"* — is most of the increment.

**The flagship demonstration cannot be run.** The specification's trading flow is Explorer →
Speculator → Analyst → **Trader** → Evaluator with entry, exit, P&L and attribution. There is no
Trader, no trade is placed, no position is held, and every price is synthetic against identifiers
like `JE-000001` (§113). The organization implements the first three roles and stops at judgment.
That, plus eight more absences, is the first output of the engine rather than a footnote.

**No second event table.** `status_events` already carries eleven of the specification's eighteen
demo-event fields and is written during ordinary operation, so the specification's own *"avoid
invasive instrumentation where ordinary telemetry is sufficient"* settles it. `backend/demonstration.py`
records only what did not exist: which acts ran and which real run each used. **It holds no
results** — every number is read from the run's own database, because a demo table of metrics is a
second answer to *what happened*.

**The witness is the design.** A scenario can pass every property while the thing an act set out
to show never happened, so an act does not claim its capability because it ran: it asks a question
of the finished run's metrics and reports `not_observed` when the answer is no. Every witness is
asserted to return false against a database in which nothing happened.

**The registry's absent half is the one that rots.** A capability claimed and missing fails
loudly; one listed as absent and since built fails silently forever. So each `ABSENT` entry names
the module or table whose absence makes it true — observed failing by adding a `trades` table.

**Deliberately not built:** the Superuser 0-10 score (directive §10 wants feedback attached to five
subjects, and a demo-only table is the wrong shape for four of them), narration, the live
presentation layer, and six of nine demo modes. **Nothing is marked client-safe**, and a test holds
that until somebody decides otherwise.

**Not adopted:** the specification's Definition of Done making demo coverage part of "done". Two of
the acts it would immediately demand cannot be written — the Software Department has no production
caller able to file it work (§155), and the Knowledge Store is the thin store §153 describes.

**Two defects found by running it, recorded at §159.** The first full run failed on act 7 — the
restart-and-continue the specification calls its major success criterion — with every role up
except the COO. `reconcile_on_start` and `respawn_coo` judged a COO alive from **heartbeat age
alone**, and a clean shutdown leaves a heartbeat seconds old beside a `process_state` of `stopped`.
Carrying that database into a new run, which is what persistence *is*, presented a COO that looked
alive and was not; the organization ran with **no executive** until the heartbeat aged out. Both
facts were in the same row and only one was read — §93's shape a third time. Adoption now requires
a fresh heartbeat *and* a running process; the unclean-death case that the guard exists for is
unchanged and a test holds it. Two of the three new tests were observed failing against the
unfixed code.

The second was the Demo Engine's own: the failing act **crashed the demonstration** instead of
being recorded, so five shown acts were reported as nothing at all. A failing act and a failing
witness are now both recorded and the run continues — withholding a finding is the one dishonesty
the specification cannot tolerate.
