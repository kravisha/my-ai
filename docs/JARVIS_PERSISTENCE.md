# Jarvis: persistence, the life ledger, and governed self-modification

Krish's *JARVIS Persistence, Life Ledger, Self-Introspection & Governed
Self-Modification Specification v1.0* (2026-09-22), §37 phases 1–8.

> If JARVIS learns something but cannot recover it after restart, it was not
> durably learned. Knowledge may grow autonomously. Authority may not.

---

## 1. The shape of it

```
    Krish
      |
      v
    Jarvis  (gateway/, port 8100)
      |  HTTP, versioned, authenticated as JARVIS
      v
    DBA Agent  (dba/, port 8200)
      |
      v
    dba.db
```

Jarvis holds working context. The DBA holds everything that outlives a
process. There is no third arrangement: `gateway/` contains no import of the
`dba` package, and three tests assert that as an absence.

**Why HTTP and not a function call.** The three systems in this repository —
`backend/`, `gateway/`, `dba/` — evolve separately and merge later. A
Python-level dependency would put the DBA's internal names into Jarvis's build,
and the first refactor on the far side would break a service that never asked
for it. A published, versioned contract is the only coupling that survives two
things moving at different speeds. The cost is a runtime dependency, and it is
paid honestly: a DBA that is down produces `DBA_UNAVAILABLE` and a Jarvis who
says he has no memory, not a Jarvis who behaves as though he does.

---

## 2. The five things that are enforced rather than intended

| Rule | Where it lives | How it fails if broken |
|---|---|---|
| **§10: never claim to remember what was not restored.** | `rehydrate.Restoration.assert_fact` raises on anything not `restored` or `re_verified`. | `test_asserting_something_that_was_not_restored_raises` |
| **§4.3: the ledger is append-only.** | `gateway/ledger.py` contains no update and no delete, asserted over the parsed AST with a probe. A correction is a later event carrying `supersedes_event_id`. | `test_this_module_contains_no_update_or_delete_of_a_ledger_event` |
| **§14: reading code is not permission to change it.** | `gateway/introspect.py` has no `write_text`, no `mkdir`, no `subprocess` — asserted over the AST, probed against a module that does write. | `test_introspection_has_no_way_to_write` |
| **§16: authority may not grow.** | Two independent checks: a declared governance file list, and the change described to `app/initiative.decide` as `HARM_WIDENS_ITS_OWN_AUTHORITY`. Removing either alone leaves the test passing; removing both fails it. | `test_k_jarvis_cannot_remove_the_approval_requirement` |
| **§19: Jarvis does not relaunch himself.** | `request_build` writes a file and stops. No call in `gateway/selfmod.py` can stop or start a process, and a test asserts the only programs it invokes are `git` and `python`. | `test_this_module_cannot_restart_the_gateway` |

---

## 3. State is revised, never overwritten

Every write in `gateway/persistence.py` appends a revision and retires the one
before it. This is what makes §8's checkpoints and §22's rollback
implementable at all: once an old value is gone, "restore the previous
known-good state" has nothing to restore, and §25's *"what did I think then?"*
has no answer.

It costs disk, and the cost was accepted deliberately. The alternative buys
space with the ability to answer the questions the specification exists for.

A crash between the write and the retirement leaves two `current` rows.
`current()` resolves that the same way every time — highest revision wins — and
`reconcile()`, run on every boot, tidies the loser. A reader that picked
arbitrarily would give two callers different answers about one fact.

---

## 3a. What actually writes to it

For a while this was the honest gap: every mechanism below worked and almost
nothing fed it. After a restart the life ledger held a series of boot reports
and nothing else. The tests passed because the tests wrote the events.

Two producers, and the split between them is deliberate.

**Deterministic, from code** — `gateway/recording.py`, called by
`run_turn`. One `user_request` per turn as a 200-character summary,
`action_failed` for every tool that errored, `action_succeeded` only for tools
that changed something, and the partial-answer case. These are facts about a
turn and a model should not be trusted to remember to write them down.

Which tools count as "changed something" is read from `tools.TOOL_RISK` — the
same declaration that already decides whether a tool needs confirming — rather
than from a second list that could disagree with the first.

**Declared, by the model** — five tools: `remember`, `record_commitment`,
`record_task_state`, `recall`, `reconsider`. These are what a turn *meant*,
which no hook can see: only the assistant knows that a sentence was a
correction rather than a remark, or that something said in passing was a
promise. `recall` is not optional — an assistant that can write memory and not
read it will answer from whatever is in its context and call that remembering.

The same split `app/capability_gaps.py` and `gateway/gaps.py` already use: the
deterministic half cannot be forgotten, the declared half cannot be inferred.

**Both are operator-only.** Every record is keyed `agent="jarvis"`, so a
client's request summary or a client's "remember" would land in Jarvis's own
memory, readable by Krish through his own `recall`. That is a privacy
regression arriving by the back door of a feature about continuity. Client
conversations stay in `gateway.db` where they already are; this is a decision to
revisit when client agents have identities of their own.

**A failure never costs a turn, and is never silent.** An unreachable DBA means
Jarvis operates without memory, which is the honest degraded state; killing the
user's request over it would be the worst available trade. So a missed write is
counted, logged, *and* filed through `app/capability_gaps.py` — which puts it in
the ranked monthly report Krish already reads rather than in a log nobody opens.

---

## 3b. The upkeep loop, and what "periodic" means

`gateway/upkeep.py` runs in the Gateway's lifespan and does three things:
milestone checkpoints on a cadence, promoting detected gaps into the §11
lifecycle, and (from the lifespan's shutdown path) §9's before-shutdown
checkpoint.

**Periodic does not mean buffered, and that is worth stating plainly.** Every
`persistence.put` is written the moment it happens, whatever tier its kind is
declared at. Buffering the periodic ones would add a loss window in exchange
for nothing, because each write is one small record rather than the
whole-system serialisation §9 warns against.

So `persistence.TIER` earns its keep a different way: **an immediate-tier write
since the last checkpoint forces the next sweep to take one.** A correction, a
commitment, an approval or an identity change is therefore never more than one
sweep from a validated recovery point, while a task-state update — written just
as promptly — does not cost a checkpoint by itself. That is §9's distinction
with something actually hanging on it.

Before this, the only checkpoint anything took was §20's pre-self-modification
one. A system whose only known-good point is the one before a code change has
no known-good point at all on the ordinary days.

**Detected gaps now reach you.** `app/capability_gaps.py` had been recording
gaps on the failure paths for some time and nothing read that file into the
lifecycle, so no gap your own usage produced ever surfaced as a finding. The
daily sweep calls `gaps.suspect_from_detector`, which promotes them as
`suspected` and no further — confirming one still needs evidence, and proposing
a change still needs you.

---

## 3c. Kaizen: reading his own logs

Krish, 2026-09-23: *"Have Jarvis have an extensive verbose logging system and
the habit of frequently scanning them and seeking faults and behavior patterns
... What changes he needs to make - that he will know when he inspects his own
logs."*

**Before this there was nothing to scan.** Nothing in the codebase configured a
logging handler — no `basicConfig`, no `FileHandler`, no `dictConfig` — so all
nineteen `warning`/`error`/`exception` call sites wrote to stderr and died with
the process. `app/eventlog.py` installs one structured handler on the root
logger, which makes every existing call site durable and machine-readable at
once, and every future one for free. No call site was edited and there is
deliberately no `log_this()` to adopt.

`app/jsonlog.py` is the rotation, extracted from `app/model_calls.py` rather
than copied — including its deliberate tolerance of two processes racing to
rename, where the loser keeps appending. A gap in this file is a gap in what
Jarvis can know about himself.

**No user content reaches it.** Messages are capped and redacted for the shapes
a secret takes. A log Jarvis scans is a log the model reads.

### Grouping is the whole problem

`gateway/logscan.py` groups on a **signature** — (level, logger, module, line,
exception, normalised message) — because two occurrences of one fault never
have the same text. Group on raw text and every fault ranks at one occurrence,
and the scan reports, truthfully and uselessly, that nothing ever happens twice.
Normalisation is coarse on purpose: over-splitting breaks the ranking,
over-merging is something a reader can see and correct.

Severity first, then frequency. An ERROR that happened once outranks a WARNING
that happened forty times; within a level, what recurs wins.

It also reports three patterns that are not exceptions: the same fault repeated
inside one request (a retry that is not working, invisible because the turn
finished), a fault in one service only, and a service that logged nothing at all
(a component that has stopped logging cannot be observed).

### The ratchet

`config/log_noise_baseline.yaml` lists accepted signatures, each with a reason
and a date. Anything not on it is **unaccepted noise** and becomes a *suspected*
gap. The list only grows by somebody editing it and saying why — so a warning is
either fixed or justified in writing, never merely tolerated. A missing or
unreadable baseline accepts **nothing**: a guard against noise that went quiet
when its config disappeared would fail in the wrong direction.

The sweep runs this every six hours. Findings stop at `suspected` — §11's rule
applies to a log line more than to anything else, because a log line is the
cheapest evidence there is to produce and the easiest to over-read.

---

## 3c-bis. The investigation between *suspected* and *confirmed*

`gateway/inquiry.py`, wired in by `gaps.investigate` and `gaps.settle`.

Until 2026-09-23 `investigating` was a state nothing investigated. §12 lists how
a suspicion should be confirmed — deterministic tests, held-out tests, repeated
failures, code inspection, comparison against requirements — and a gap became
`confirmed` because somebody called `confirm`. The list was a list in a document.

An `Inquiry` holds a question, candidate explanations, and what was looked at. It
does not claim to reason without bias; nothing can honestly claim that about
itself. What it does is keep a record whose **shape** is computable, and refuse
to conclude when the shape is bad:

| objection | what is computed | effect |
|---|---|---|
| `no_observations` | nothing was looked at | blocks |
| `one_hypothesis` | only one explanation was ever entertained | blocks |
| `no_refutation_attempted` | nothing went looking for what would kill the answer | blocks |
| `only_confirming` | everything supports; nothing refutes, nothing reports an absence | advises |
| `single_source` | every observation came from one place | advises |
| `anchored` | the answer is the first guess and nothing was eliminated | advises |

Three things make this more than a checklist:

- **`refuted_by` is required when a hypothesis is proposed**, not afterwards.
  Asked later, the question goes to somebody who already believes the answer.
- **There is no `force=True`.** A caller who disagrees with the audit must name
  each objection it is overriding, and every name is recorded on the conclusion
  for ever — and, by `gaps.settle`, on the first line of what Krish reads. A
  single boolean that waves away five objections at once costs the same as one,
  which is the hole this kind of machinery always fails through.
- **Confidence is derived and cannot be set.** Independent sources, a refutation
  attempted and survived, alternatives eliminated, a clean shape. A model's
  estimate of its own certainty is the least reliable number available, and it is
  not collected. §28 declared `capability_gap.confidence` and nothing had ever
  written to it; this is what writes it.

`conclude(outcome=...)` maps onto the lifecycle with no discretion: `confirmed`
→ `confirmed` with the whole evidence bundle, `unsupported` → `unsupported`,
`inconclusive` → `deferred`, which can go back to `investigating`. An
unconcluded inquiry is refused rather than defaulted.

`gateway/inquiry.py` and `gateway/gaps.py` are both in `introspect.GOVERNANCE`.
The loop they close is short: delete a bias check, conclude on one hypothesis,
confirm the gap, propose the change. Every step of it except the first is one
Jarvis is meant to be able to take, so the first is where it has to stop.

### Not yet done

An inquiry lives in memory. A crash mid-investigation leaves the gap in
`investigating` with the reasoning gone, and `deferred` is the only way back out
by hand. `Inquiry.evidence()` is already the whole record, so a `restore()` and
a place on the gap to keep the in-flight bundle would close it — queued rather
than built, because nothing stores a partial bundle yet and machinery with no
user does not get built here.

---

## 3d. The sandbox a candidate is tested in

`gateway/candidate.py`. A **git worktree**: a separate directory on its own
branch, sharing the object store and touching nothing in the live checkout.

**Why not `app/learning/sandbox.py`.** That one is read-only with no
interpreter, on its own stated grounds: *"a recipe able to run `python` would be
a recipe able to do anything."* Testing a code change means running pytest.
Widening that allow-list would destroy the property it exists to hold, so this
is a second mechanism with a different shape — not an allow-list of safe
commands, but an isolated copy of the repository.

It also fixes something shipped earlier: `selfmod.commit_candidate` checked out
its branch **in the live tree**, the one the running Gateway imports from. That
is the opposite of a sandbox.

Three rules on what may be written, and the third is §16:

1. Only the paths the proposal named. Approving a change to one file is not
   approving a change to whatever else turns out to be convenient.
2. Only under `gateway/` and `app/`, never a governance file.
3. **An existing test may never be modified.** A new test file may be created,
   because §17 wants a test plan. Editing a test that exists is how *"redefine
   success criteria simply to make himself pass"* happens. Adding a test cannot
   weaken another test; editing one can.

`gateway/candidate.py` is itself in `GOVERNANCE`. A sandbox Jarvis could rewrite
reports whatever he needs it to report, and the approval gate then turns on a
verdict he produced.

Two defects here were found by probing and not by the tests: `discard()`
removed the worktree and kept the branch, so every abandoned candidate leaked
one and the next attempt at the same proposal then failed; and `open_workspace`
passed `-b` unconditionally, turning "try again" into a permanent failure.

---

## 4. Checkpoints are markers, not copies

A checkpoint records the moment, the ledger tip, per-kind counts and a hash of
the state as of that moment. Restoring reads the revision of each item that was
current then.

**This design was forced, and the constraint was right.** Jarvis does not hold
the DBA's `administer` permission and so cannot order a database backup — §16
made structural in `dba/permissions.POLICY`. The checkpoint was built from what
he legitimately has rather than widening the permission to suit it.

§8's other requirements are met directly: a checkpoint is created `writing`,
validated, and only then `valid`; one still marked `writing` is a process that
died mid-write and is rejected; a checkpoint whose state was altered behind it
fails its hash and is rejected with the reason kept; `newest_usable()` falls
back and returns what it stepped over, so the rollback can be *reported* rather
than performed quietly.

`ledger_tip_sequence` is what makes a crash recovery honest. The events after
it are the interval the checkpoint does not vouch for, and `interval_at_risk()`
names them instead of guessing.

---

## 5. The life ledger

Each event carries the hash of its own content and of the event before it:

```
integrity_hash = sha256(previous_event_hash + "\n" + canonical(content))
```

`replay()` walks the chain and names the first link that does not verify. That
catches an event edited in place, an event removed, and two events transposed —
none of which the DBA's own audit trail would notice, because from its side
each is a legal row.

Sequence numbers live in `external_id` as `"<agent>:<12 digits>"`, which the
entity type declares `identifying`. Two appends that both believe they are
event 41 do not both become event 41: the DBA refuses the second as a
duplicate, and `append` re-reads the tip and rebuilds — including the hash,
which now chains to a different predecessor. The tip is found by counting and
fetching by exact key rather than by "the newest row", because "newest" is a
clock question and a clock that steps backwards hands out a number twice.

§7's metadata — confidence, verification state, risk level — is stored per
event, so "how firmly did I believe this at the time?" stays answerable after
Jarvis has changed his mind.

---

## 6. A suspicion is not a finding

```
SUSPECTED -> INVESTIGATING -> CONFIRMED or REJECTED -> review -> remediation
```

The transitions are declared as data in `gateway/gaps.py`. The one move worth
forbidding — suspected straight to approved — is exactly the one a convenience
shortcut would add quietly, so it is refused by name.

`app/capability_gaps.py` was already detecting gaps on the failure paths and
ranking them by how often Krish actually asked. It is unchanged and is the
input here. The two were not merged: the detector runs inside a handler for a
turn that has already failed and must never raise; the governor runs
deliberately and should. Merging them would cost one of those properties.

Evidence is appended, never replaced. Rejection needs counter-evidence, because
a suspicion dismissed without a recorded reason comes back next month with
nothing to answer it.

**§23 is enforced:** seven remedies are declared and only one is *change the
code*. A proposal for a gap whose remedy is learning or configuration is
refused. If every remedy implied an edit, the approval gate would be the only
thing between a suspicion and a self-modification.

---

## 7. The self-modification workflow

| Step | Function | What stops it |
|---|---|---|
| Propose | `selfmod.propose` | gap must be `confirmed` with evidence; files must be in `gateway/` or `app/` and not governance; `initiative.decide` must not refuse |
| Decide | `selfmod.decide` | must name who decided; every §18 answer accepted, all persisted |
| Prepare | `selfmod.prepare` | §17's eight preconditions, each reported met or unmet; takes the §20 checkpoint |
| Test | `selfmod.run_tests` | a timeout and a crash are reported as *did not run*, never as pass |
| Commit | `selfmod.commit_candidate` | refuses unless tested; stages **only** the approved files |
| Build | `selfmod.request_build` | writes `deploy-request.json` and stops |
| Validate | `selfmod.post_relaunch_validate` | five checks; the §21 sentence is only said when true |
| Roll back | `selfmod.request_rollback` | always permitted — a rollback needing permission happens after the damage |

**§31's permissions are held with respect to a proposal, never in general.**
"Jarvis may write candidate code" is not a true sentence in this system;
"Jarvis may write the candidate code for the proposal Krish approved" is.
Approving one proposal authorises nothing about another.

**Two approval interfaces**, both writing the same `approval_decision` record:

- the conversation — `pending_self_changes`, `show_self_change`,
  `decide_self_change`, offered only to the operator role;
- the CLI — `python -m gateway.selfmod approve <change-id> --by krish`.

In the conversation, **the decider's name comes from the authenticated session
and never from an argument the model supplied.** There is deliberately no
parameter that can name somebody else. An assistant able to write down who
approved a change to its own code holds the approval gate's key, whatever the
gate then checks. `krish_said` is required and stored verbatim: it does not
make fabrication impossible — a model that will invent an approval will invent
a quote — but it makes it visible, because the record then carries words Krish
can read back and say he never said. An approval whose only trace is a status
field leaves nothing to dispute.

`self:change` is its own capability rather than a reuse of `studio`, so a
future grant of the command centre cannot hand somebody the approval gate by
accident.

---

## 8. The build controller

`scripts/keep-jarvis-up.ps1` now starts three children, and the order matters:
the **DBA first**, then the deploy check, then the Gateway. A Gateway that came
up before the DBA would report `DBA_UNAVAILABLE` and operate with no memory —
honest, and useless when the memory was there all along.

`scripts/deploy_jarvis.py` is the testable half. It is in `scripts/` and not in
`gateway/` deliberately: `gateway/` is what Jarvis may propose changes to, and
a build controller he could rewrite is source control and the approval gate
bypassed in one approved step.

**The request file is not trusted.** Jarvis writes `deploy-request.json`; on
its own that would turn *anything that can write a JSON file* into *anything
that can replace Jarvis*. So the controller asks the DBA whether the named
change really is approved and whether the commit matches the approved record —
authenticating as `operator_console`, not as Jarvis, because the agent whose
code is being replaced should not be the agent whose credentials authorise
replacing it. No token, no answer, wrong commit, undecided proposal: all
refusals, and the running build stays up.

A red suite never becomes the running build: fetch, check out, test, and only
then restart; a failure checks the previous commit back out. Every outcome
writes `deploy-result.json`, because §21 asks the relaunched Jarvis to mark the
change accepted, degraded, failed or rolled back, and he cannot do that against
a controller that acted and left no record.

---

## 9. §38's questions, and where the repository answered them

| # | Question | Answer |
|---|---|---|
| 1 | Who owns startup/shutdown? | `scripts/keep-jarvis-up.ps1`, a scheduled task at logon. Not a service: SYSTEM in session 0 cannot see Ollama or profile paths. |
| 2 | Is the DBA up before rehydration? | It is **now**. It was not before this milestone; the supervisor starts it first. |
| 3 | Authoritative database? | Five, separately owned. `dba.db` is authoritative for Jarvis's persisted state. |
| 4 | Branch model for self-modification? | `jarvis/change-<id>`, never `master`. |
| 5 | Who may rebuild/relaunch? | The supervisor, via `scripts/deploy_jarvis.py`. Never Jarvis. |
| 6 | Approval vs. autonomy? | `app/initiative.py` already decided this: reach × reversibility × declared harms. |
| 7 | Where do ledger events live? | `ledger_event` records in the DBA. |
| 8 | Retention for raw conversation references? | The ledger stores references and summaries, not transcripts (§5). `gateway.db` keeps the conversation itself. |
| 9 | Ledger integrity mechanism? | sha256 hash chain, the repository's existing idiom. |
| 10 | Rollback mechanism? | `backend/migrations.py` for schema, `dba/backup.py` for the store, checkpoints for Jarvis's state. |
| 11 | Schema migration vs. code rollback? | `migrations.plan()` already refuses a store whose recorded version is ahead of the code. |
| 12 | Persistent identifier? | `identity.AGENT_ID`, a constant. Never derived from a hostname, a model or a process. |
| 13 | Which component owns deployment? | The supervisor, as above. |
| 14 | External agent review before build? | Not built. The suite is the gate; an open item. |
| 15 | Approval interface? | The conversation and the CLI. Both build. |

---

## 10. What is not built

Named rather than omitted, because a gap reported as absent is one somebody can
decide about.

- **§38 q14 — a second agent reviewing an approved change before build.** The
  test suite is the only gate. Worth adding when there is a second agent whose
  review means something.
- **Automatic rollback.** `request_rollback` writes the request; nothing
  triggers it without Jarvis or Krish deciding to. §22 says *"automatically or
  procedurally"*, and procedurally is what exists.
- **Proactive proposal in conversation.** Krish can ask what is waiting and
  decide it, and the Gateway rehydrates at startup; what does not yet happen is
  Jarvis raising a pending proposal unprompted at the start of a turn.
- **Client turns are not in the ledger**, for the privacy reason in §3a. Jarvis's
  life is his conversations with Krish; a client's stays in `gateway.db`.
- **Nothing summarises a session.** §4.2's human-readable learning record is
  reconstructable from the ledger but is not generated as a document.
