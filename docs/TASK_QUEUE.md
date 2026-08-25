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

> **Owner-directed head of the queue** (2026-08-25, `SPEC_RECONCILIATION.md` §60): **both head
> items are now DONE** — TQ-14 (forward leg §61, event-stepped timeline §63) and TQ-15
> (market-implied validation §62). **Every entry the 34–37 assimilation generated is now
> DONE** (TQ-14 §61/§63, TQ-15 §62, TQ-16 §64, TQ-17 §65, TQ-18 §66). The one remaining
> **Current focus: the live studio** (addenda 41–43, assimilated 2026-08-25, §85) — **TQ-33**,
> the visual redesign, because addendum 41 makes the look a requirement and the console as built
> is the terminal it forbids — **done 2026-08-25** (§86), as are **TQ-38** (the dormancy gate
> that did not hold, §87) and **TQ-35** (Kumbhakarnan as persisted identity, §88).
>
> **TQ-36** (the migration pipeline and the escape hatches, §89) is done too.
>
> **TQ-37** (the briefing and its choreography, §90) is done, which closes every entry the
> 41–43 assimilation generated except the deferred animated figure.
>
> Next: **TQ-34** (role-based Gateway).
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

**NEED (GREEN) · QUEUED · addenda 41 §2/§5/§7/§14/§15/§19/§20, 40 §8.3–§8.5 ·
`SPEC_RECONCILIATION.md` §85**

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

**WANT · QUEUED · addendum 40 §13, §14 · `SPEC_RECONCILIATION.md` §81**

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
  (36 §2.3). §60 disposition 3.
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
