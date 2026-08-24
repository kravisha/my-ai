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

**WANT · QUEUED**

Source: addendum 31 §3, §5 (petitions), §22 (intake pipeline); addendum 32 §12, §14–§15 (cost/
impact and Quick-Win classification). Supersedes this paper file with a backend store: petitions,
Need/Want classification, flags, cost/impact profile, status, and a panel view. The petition
*sources* the specs describe (agent self-reflection time, trainer/mentor pre-review) come later;
the register itself is the enabling substrate. Also the natural home for addendum 32's Quick-Win
accelerated path.

### TQ-06 — Options arbitrage library, next increment per addendum 27 §11

**WANT · QUEUED**

Source: addendum 27 §11 Phase 2 ordering; reconciliation §46's deferrals. Candidates in the spec's
own order: ARB-012 calendar diagnostics (D-class, diagnostic only — the world already has multiple
expiries), then Phase 2 detectors (ARB-014 cash-and-carry, ARB-015 option-implied dividend,
ARB-016 borrow basis, ARB-017/019/020 American family — the last three need American-style worlds
the simulation does not yet generate). Per-detector-family lenses and difficulty progression stay
deferred per §46 until grades distinguish families.

### TQ-07 — Governance cost/impact profile on scoreboard entries

**WANT · QUEUED · after TQ-05**

Source: addendum 32 §14. Once the register exists, high-cost/high-side-effect classification
(32 §16) and the Quick-Win path (32 §15) attach to it. Pointless as a paper exercise before then.

### TQ-08 — Incident response runbook, including credential revocation

**NEED (GREEN) · QUICK_WIN · DONE — `docs/INCIDENT_RESPONSE.md`, noted in `SPEC_RECONCILIATION.md` §51**

Preserve evidence → stop (clean shutdown or the orphan-cleanup procedure §48 observed) → revoke
(sessions, Gateway sessions, provider key at the console, Gateway password) → assess against audit
trails and `behavior_version` → restore through the fail-closed continuity path → written review.
Its own limits are stated in the document.

### TQ-09 — Dependency scanning habit

**WANT · QUEUED · from §50 item 14**

Source: addendum 28 §13.2, §32 item 14. No CI exists to host scanning; the honest minimum is
`pip-audit` in requirements-dev with a documented cadence, upgraded to CI enforcement when CI
exists.

### TQ-10 — Cost circuit breaker on the model provider

**NEED (GREEN) · QUEUED · from §50 item 18**

Source: addendum 28 §19.3, §32 item 18. Not exposure-gated: the risk exists the moment a real
API key does. A per-run and per-day token/call budget on the provider layer that refuses, visibly,
instead of spending — with the refusal recorded like any other denial.

---

## Blocked

### TQ-B1 — ARB-013 (forward/futures vs synthetic forward)

**Source: addendum 27 §11 Phase 1.** The one Phase 1 detector not built. Blocked: the training
world (addendum 25) generates equity option chains only — no forward or futures instruments exist
for the detector to price against, and inventing them is a world-design increment (addendum 25's
scope), not a detector increment. Unblocks if/when the simulation grows a forward leg.

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
