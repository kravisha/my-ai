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
> **TQ-34** (the role-based Gateway, §92) is done, and with it every entry the 40–43 lineage
> generated except the deferred animated figure.
>
> **TQ-39** (the client agent, and the conversation leak it uncovered, §93) is done.
>
> **TQ-41** (the clock-comparison sweep, §94) is done — one more bug found, and the rule
> that came out of it is not the one three fixes in a row suggested.
>
> **TQ-40** (the client agent's skills, §95) is done — the mechanism, the scope field the
> mechanism was missing, and two skills declared-and-unbuilt with reasons the agent gives
> aloud. Both remain genuinely blocked on data, not on effort.
>
> **TQ-42** (client-owned holdings, §96) is done, which built the first real client skill.
>
> **Current focus: the portfolio subsystem** (addendum 44, assimilated 2026-08-26, §97) —
> **TQ-44** (portfolios as owned entities *and* the guard, which must not ship apart) is
> **done** (§99): every portfolio has an explicit owner, `resolve()` is the only way to one,
> and the §15.5 regression is permanent. **TQ-45 is done** — 45a the canonical holding shape
> (§100), 45b the provider abstraction and its conformance suite (§101). Remaining in that
> lineage: TQ-46 (the Superuser ownership domain), TQ-47 (its tab), TQ-48 (snapshots,
> provenance, audit), TQ-49 (the Schwab boundary). TQ-50 is blocked on owner action.
>
> **New lineage: local intelligence and competitive model routing** (addendum 45, assimilated
> 2026-08-26, §102) — **TQ-51 … TQ-68**. Owner-supplied and explicitly superseding the earlier
> local-model routing specification. It starts at **TQ-51**, which unpins
> `routing: none_single_model` — the tripwire §64 planted for exactly this moment, firing on the
> first real step of the lineage that needed it. **TQ-51 is done** (§103): the pin is now a
> ladder whose rungs each carry a tripwire, `preferred_model` has a planned handover to seed
> status, and the two registries are split by writer. Next is **TQ-52** (the candidate survey) or
> **TQ-53** (the task signature and vocabularies) — independent of each other, and TQ-53 needs no
> hardware answers. **TQ-56 is done** (§107) — the interface local intelligence will arrive
> behind, with nothing behind it yet. **TQ-55 is done** (§106) — every routing decision is logged from the
> first one, and it already detects §36 privacy misrouting. **TQ-54 is done** (§105) — the eight leaderboards exist, seeded and
> provisional, and `routing` now stands on the `seeded_leaderboard` rung. **TQ-53 is done**
> (§104) — the task signature, the eight categories and the
> complexity and privacy vocabularies, with four collisions against existing house vocabularies
> resolved. Next is **TQ-54** (the registry and leaderboards, which also advances the routing
> marker) or **TQ-52**, still waiting on what "Inkling" is.
>
> Two findings from assimilation that shape the order, both in §102: the GPU is **8 GB**, which
> makes a pool of six feasible on disk and sequential in VRAM; and **"Inkling"**, named as an
> initial candidate, is not identifiable as an open-weight local model — TQ-52 has to answer what
> it is before anything depends on it.
>
> **Owner decision wanted**: whether this lineage or the remaining addendum 44 entries (TQ-46
> onward) is worked first. They are independent.
>
> **TQ-43** (per-client Gateway credentials, §98) is **done** — it was the precondition under
> most of that, and the demo now seeds three clients who each log in as themselves.
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

### TQ-46 — The Superuser portfolio as its own ownership domain

**NEED (YELLOW) · QUEUED · depends on TQ-44 · addendum 44 §4, §10, §16, §21.4, §21.6**

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

**NEED (GREEN) · QUEUED · depends on TQ-51 · addendum 45 §5, §34, §35, §43, §44**

Metadata before code (addendum 30 §12), and this one is metadata before *downloads*. Produces
`docs/local_model_candidates.yaml`: for each candidate, the licence, the parameter count, the
quantization that fits, the runtime, the VRAM and RAM it needs, and whether it runs here at all.
No model artifacts, no runtime installation, no code.

**The hardware is the constraint and it is measured, not assumed** (§102): NVIDIA RTX 3050,
**8 GB VRAM**, 16.5 GB system RAM, 365 GB free disk. A 7B–8B model at 4-bit quantization fits in
VRAM; a 70B-class model does not, at any quantization. Disk is ample for a pool of six; VRAM is
not ample for two resident at once, which makes §15's challenger comparisons **sequential**. That
is a latency cost, not a blocker, and the plan should say so rather than discover it.

**This entry also has to answer what "Inkling" is.** Addendum 45 §5 and §43 name it alongside
Llama and DeepSeek as an initial candidate. It is not identifiable as an open-weight local model
from this side, and the project does not fabricate: no task may depend on it until somebody has
confirmed the actual artifact, its licence and its runtime. If it turns out to be something other
than a local LLM, the pool is Llama + DeepSeek + Qwen/Mistral/Gemma and that is recorded as a
finding, **not quietly substituted**.

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

**NEED (GREEN) · QUEUED · depends on TQ-53, TQ-54 · addendum 45 §3, §16, §17, §19, §45 Phase D**

§3 is explicit that these are **two decisions that must not be conflated**, so they are two
entries. This is the first: *can this be done without a model at all, and if a model is needed, is
local enough?*

§19's deterministic-first check comes before any of it — "AI should not be used merely because AI
is available" — and it is the cheapest, most testable part of the whole lineage.

The escalation decision is itself an intelligent task with its own leaderboard
(`CAPABILITY_AND_ESCALATION_DECISION`, §17), and the model best at making it may not be the model
best at doing the work. That is the point of giving it a category rather than a constant.

### TQ-60 — Model selection, with policy and resource overrides

**NEED (GREEN) · QUEUED · depends on TQ-54, TQ-59 · addendum 45 §9, §18, §24, §25, §35, §36,
§45 Phase E**

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
