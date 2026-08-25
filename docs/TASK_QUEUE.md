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
Upgrades to CI enforcement when CI exists.

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

---

## Blocked

### TQ-B1 — ARB-013 and ARB-014 (forward/futures detectors)

**Source: addendum 27 §11 Phase 1 (013) and Phase 2 (014).** Blocked: the training world
(addendum 25) generates equity option chains only — no forward or futures instruments exist for
either detector to price against, and inventing them is a world-design increment (addendum 25's
scope), not a detector increment. Unblocks if/when the simulation grows a forward leg.

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
- **Distillation of addendum 33 into constitutional directives** (33 §0) — the constitution is held
  privately; distilling into it is an owner action, not a repository action.
- **Evolution Directives / trainer hierarchy as separate machinery** (addendum 30 §4–§6) — the
  training loop built under addendum 13 already performs train→evaluate→certify with separated
  roles; §47 records the mapping. New machinery only when a real systemic evolution needs a
  directive the existing loop cannot express.
