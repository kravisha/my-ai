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

## 3c-ter. What is worth remembering, and what gets collected

`app/learning/retention.py` decides; `app/learning/memory.py` and
`app/learning/store.py` act; `gateway/upkeep.py` is the only thing that calls it.

Krish, 2026-09-23, asked whether *"the March invoice from Acme always arrives
late"* is a lesson or a context, and answered it himself: *"it's a fact that
Claude may choose to remember and this cost may or may not be rewarded by a cost
saving use in the future - that's how Jarvis learns how to guess correctly what
to remember and what to discard - all deadweight unreferenced information should
be eventually garbage collected as well."*

### A fact is a bet, and both halves are now kept

`lessons` counted one number, `times_seen`: how often the world produced the
pattern. That is the acquisition side of a bet with nothing recorded about the
return. Three numbers now:

| | what it means |
|---|---|
| `times_seen` | how often the world produced this pattern. Acquisition. |
| `times_offered` | how often the fact was a candidate, chosen or not. |
| `times_referenced` | how often it was actually handed to a decision. Use. |
| `times_paid_off` | how often the thing it was handed to then went well. Return. |

`memory.advice_for` is the only thing that moves the middle two and
`engine.accept` the only thing that moves the last. Those are single call sites
carrying the whole scheme, which is why each has a test: delete one and the
system still runs, still reports, and quietly collects the lessons that were
working.

### Acme is the case that kills a naive collector, twice

A collector that discards anything unreferenced for ninety days deletes the March
Acme fact every June and re-learns it every March at full cost. So a fact carries
`expected_interval_days` and is cold only after several of **its own** cycles.

That alone was not enough, and the first version of the module was wrong about it
in a way only a mutation found: Acme survived, and so did a fact that cost twelve
model calls and had never been referenced once in five hundred days, because an
unstated cycle defaults to a year and a year bought it eight hundred days of
protection. The distinction is not time - it is whether anything ever **asked a
question the fact could have answered**. A fact offered two hundred times and
never chosen is dead. A fact offered two hundred times and chosen each March is
Acme. A fact never offered is not judged at all, because its silence is evidence
about the thing that never asked.

### Collecting leaves the lesson about the lesson

The row goes, which is what was asked for. What stays is one increment on
`lesson_kinds`: how many of this kind were recorded, referenced, paid off and
collected unused, and what they cost in total. One row per kind, so the record of
what was thrown away is bounded by the number of kinds and can never become the
deadweight it exists to prevent. `retention.worth_recording` reads it and stops
recording a kind that has never once helped - keeping a door ajar by recording
every tenth one anyway, because a policy that closed a kind for ever could never
find out it had become useful.

### The guardrails

- **Probation before collection.** A fact used and never once useful stops being
  offered first; a wrong call there costs a missed hint rather than the fact. And
  probation is a window, not a state to live in: it ends in collection, or in
  restoration when the verdict comes back.
- **A clock problem must never become a deletion.** An unparseable timestamp
  makes a fact look brand new, not ancient.
- **A dry run.** `JARVIS_MEMORY_COLLECTION_DRY_RUN=1` reports what would go and
  collects nothing. Not a debug flag - it is how a collector earns trust on a
  real machine before it is allowed to delete anything.
- **Weekly, not six-hourly.** Every rule here is measured in months.

### The numbers are thought, then ratified by outcomes

Krish, 2026-09-23: *"Deciding what to retain and what to forget shouldn't be a
guessing game. It should be based on deep thought and then ratified by real life
experiences."*

Every constant in `retention.py` is the first half - reasoned, with the reasoning
written beside it - and reasoning is both where a number like
`CYCLES_BEFORE_COLD = 2.25` comes from and where it stops. The second half needs
an observable that says a decision was **wrong**, and there is exactly one: a
fact that was collected and then had to be learned again. Re-acquisition is the
cost of a bad discard, it is measurable, and nothing else here is.

So `discard_lesson` leaves a tombstone of `(kind, pattern)` with how long the fact
had been quiet, and `record_lesson` checks for one. A match means the collector
was wrong, and two things follow:

- the kind's `regretted` tally rises, and `retention.ratification` turns that into
  a verdict on the policy itself. Above `REGRET_RATE_TOO_HIGH` (one in ten) it
  reports *the numbers are too aggressive*, names which to raise, and shows what
  was thrown away so a person can judge. A collector that never regrets anything
  is keeping everything.
- the re-learned fact is given an `expected_interval_days` of at least how long it
  had been quiet **plus** how long it stayed collected - the real cycle, learned
  from the mistake. **A yearly fact collected wrongly once cannot be collected
  wrongly twice.** That is the loop closing, and it is what replaced the honest
  placeholder this section used to admit to.

`ratification` reports and never retunes. A collector that adjusted its own
thresholds from its own regrets would be the one thing nobody could audit: the
numbers would drift, each drift justified by the one before, and the reasoning
written beside each constant would quietly stop being true. Asserted over the
parsed module - nothing assigns to a policy constant anywhere.

Tombstones are pruned past three default cycles, because beyond that a re-learn is
a new fact rather than evidence, and a tombstone table that grew for ever would be
the deadweight the collector exists to prevent.

### Still a proxy

`cost` is the attempts a lesson was derived from, not model calls measured, and it
is labelled as one at every site that sets it.

---

## 3c-quater. The constitution: encrypted, owner-amendable, tamper-evident

`app/secretbox.py`, `gateway/charter.py`, `gateway/constitution.py`.

Krish, 2026-09-23: *"Things such as the constitution need the explicit permission
of the human to be changed. They are read only principles to act by... keep the
constitution and the amendments encrypted and hidden and only visible to
superuser and Jarvis and other agents."*

Three defences against three different failures. Running them together would
have produced something that felt secure and was not:

| | against |
|---|---|
| **encrypted at rest** | a copy leaving the machine - a backup, a sync folder, a support bundle |
| **the owner's key** | Jarvis amending it because he decided he should |
| **the chained amendment log** | Jarvis amending it *anyway*, by writing the file directly |

**The third is the one that matters and the easiest to leave out.** Jarvis runs
as a process with the filesystem and the decryption key, so nothing stops him
rewriting the sealed file. What he cannot do is produce a `charter_grant` - that
record needs `administer`, which only the operator console holds, and it lives in
another service. So an unsanctioned amendment leaves one of two holes and
`verify` names both: the sealed text matches no link, or a link names a grant
that was never issued. A lock Jarvis holds the key to is not a lock; a record he
cannot forge without leaving a hole is a deterrent that survives him being wrong.

`install` refuses to overwrite, there is no `write`, and `amend` writes the chain
link **before** the new text. A crash between them leaves a link with no matching
text, which `verify` reports as damage; the other order leaves changed text with
no link, which is indistinguishable from the attack.

### Both charter documents are walls

Krish, 2026-09-23: *"Please don't add anything to the constitution directly - add
only as amendment which means additional to the constitution. And don't allow
Jarvis or yourself to ever change the constitution. Only I should be able to
change the main document, manually, myself."*

So `AI-CONSTITUTION.md` is in `introspect.SEALED`: no key opens it, no emergency
reaches it, no proposal may name it, and `gateway/constitution.py` has no
function that writes its text. The earlier design gated it on his charter key,
which was the wrong shape - a key can be in force at a moment nobody intended,
and this is the document where that costs everything.

This is the only wall in the system, and the reason it is the only one is the
reason it has to be one. Every other limit here is *ask first* or *needs a key*,
because a lock the owner cannot open in a hurry is a lock that can hurt him. That
argument does not apply to the document every other rule is derived from: an
agent that can edit the source of its own limits does not have limits, it has a
preference.

`AI-CONSTITUTION-AMENDMENTS.md` is walled too, on Krish's instruction the same
day: *"Yes wall the amendments too."* It was briefly keyed, on the reasoning that
a charter nobody may draft is a cage - which was thinner than it looked, because
**drafting is not writing**. Nothing stops Jarvis proposing an amendment, arguing
for one at length, or pointing out that the constitution contradicts itself. He
writes the argument; Krish writes the amendment. A cage would be an agent
forbidden to raise the subject.

So `gateway/constitution.py` has no function that composes either document. Two
were removed the hour after they were written: `amend`, which rewrote the
constitution behind the charter key, and `add_amendment`, which composed an
amendment from a caller's string. What remains is `seal_what_krish_wrote`, which
takes both texts whole and records them, and a test that asserts over the parsed
module that exactly two functions write that file and neither authors a word.

`verify` compares the sealed constitution against what the newest seal was taken
**alongside**. A mismatch means Krish edited by hand - which clears on a re-seal -
or something changed it that should not have been able to. A hand seal carries no
grant, by design: Krish does not grant himself permission, he is the permission.
What it must carry is a name, and an entry with neither is reported.

### The limit, stated rather than footnoted

Encryption at rest does not protect against code running as Jarvis, because the
key must be reachable from his process for him to read his own constitution.
`secretbox.describe()` says so in the data, and a test asserts that it does.

### Where the key lives: DPAPI, and his own arrangement decided it

`app/keystore.py` decides; `app/dpapi.py` is the adapter. Answered 2026-09-23.

The two candidates were Windows DPAPI tied to Krish's account and a passphrase
entered at startup. The passphrase is stronger and is the wrong answer, because
of something already in this repository: `scripts/keep-jarvis-up.ps1` exists
precisely to restart Jarvis with nobody at the keyboard, *"because Krish leaves
on vacation tomorrow and the failure he cannot recover from"* is Jarvis staying
down. A passphrase means that after the first unattended restart he cannot open
his own constitution until Krish is home and types it. In his actual use, the
stronger option produces a Jarvis governed by a document he cannot read.

The seal was never protection from Jarvis and cannot be — this file says so
three sections above, because he runs as a process with the filesystem and the
key. What it protects is the document being read off the machine, or altered
without it showing. DPAPI is exactly the right size for that and asks nothing of
a person.

**Which is why the escrow is not optional.** DPAPI ties the key to one Windows
account: a reinstall, a lost profile or a new machine makes every amendment
unreadable for ever, by Krish as much as by Jarvis. So the key is also written
out wrapped in a passphrase he chooses and keeps elsewhere, salted per
installation, and a keystore with no escrow is reported as incomplete on every
single run until there is one. It is the one failure here with no recovery, so
it is the one thing the module nags about — but it never *blocks*, because
refusing to run over a missing backup would be a lock keeping him out of his own
constitution to protect him from losing it.

Four states, and each says what to do rather than that something is wrong:
`absent`, `unreadable` (a key sealed by a different account — restore the
escrow), `no_escrow` (works, has no backup), `ready`. A stale escrow — one
holding a different key than the one in use — is reported as `no_escrow`,
because a backup that restores the wrong key is worse than a missing one: it is
mistaken for a backup.

Also open: the plaintext `AI-CONSTITUTION.md` is in git history. Sealing it from
here on does not remove it from past commits.

---

## 3c-quinquies. Saying it back before doing it

`gateway/readback.py`.

Krish, 2026-09-23: *"Give him all the capabilities and the command that he cannot
change is that user will decide what help he needs from Jarvis and Jarvis should
reiterate his understanding back to the user for critical tasks that are
important such as sending emails as opposed to raising volume on the radio - the
later shouldn't need a confirmation. When user confirms Jarvis will act and
complete execution. This is a relationship that has to be cultivated with time
and trust."*

Four claims, kept separate because they are separable:

**All the capabilities.** Nothing in this module is a capability gate. It does
not decide what Jarvis can do, only what he says first.

**Which actions need it is not decided here.** `app/initiative.py` already ranks
actions by reversibility and reach, and already answers that raising a volume is
`act` and mailing another person is `propose`. `needs_readback` reads that
verdict. A second list of "important verbs" would be a second thing to keep in
step with the first, and a new consequential action would be safe only if
somebody remembered to add it.

**A read-back is particulars, and marks which are Jarvis's.** *"Shall I send the
email?"* catches nothing - the misunderstanding is never in the verb. So an
`Understanding` is a list of particulars, each carrying where it came from:

> to: accounts@acme.example — you said
> attachment: Q3-statement.pdf — you said
> subject: Late invoice, Q3 — **I worked that out**
> *(1 of those is mine rather than yours: subject.)*

That last line is the whole point. A read-back of only what it was told confirms
nothing, because the error lives in what was inferred. Three sources, not two:
`defaulted` reads as *"nobody said, so I used the usual"*, which invites a
different correction from *"I worked that out"*.

**The user decides, structurally.** `confirm` refuses a confirmation whose
`confirmed_by` is the agent itself - the same shape as the owner-written charter
grant, and for the same reason: a permission the asker can issue is not a
permission. A rule Jarvis is merely asked to follow is exactly what stops holding
in the case it is for.

**On confirmation, act and complete.** A confirmation produces a `Mandate` whose
scope is the confirmed particulars. Execution runs inside it without asking
again - re-asking halfway is not caution, it is nagging, and it is what makes a
person stop granting anything. Stepping outside is refused by particular, not
just by name: confirmed to send one email and sending three is the failure this
exists for, and the action's name is identical in both.

An unresolved unknown blocks confirmation unless each one is named, the same way
`gateway/inquiry.py` handles a standing objection.

### Wired into the tool loop, and the hole that closed

`gateway/tools.execute` builds an `Understanding` for any call the policy rates
`propose` and returns its lines under `needs_confirmation.read_back`.

Particulars are derived from the call's own arguments, so a tool added tomorrow
reads back tomorrow rather than when somebody remembers it - and **every argument
is marked `inferred` unless the tool declares otherwise**, because the model
chose those values. A read-back that calls Jarvis's own choice *"you said"*
confirms nothing. `TOLD_ARGUMENTS` is the short list of arguments that cannot be
anything but a quotation; `publish_document.repository` is the only entry.

The hole: `confirm_public` was a boolean the **model** set after relaying a
proposal, so the thing being asked was answering on behalf of the person being
asked. `execute` now takes `confirmed_by` from the session - the same property
`subject` already had, for a sharper reason - and a call naming Jarvis himself
gets the read-back instead. A tool argument cannot carry a person's consent,
because the model writes the arguments.

### Across turns: the register

A read-back is offered on one turn and answered on the next, so
`readback.Register` holds the question in between. Three properties carry it:

- **The model never handles a token.** `execute` asks the register for a live
  mandate covering *this exact call*, rather than being given an identifier it
  could replay. A call whose arguments drifted between the proposal and the
  attempt finds nothing and is proposed again - which is where `Mandate.covers`
  stops being a check that can only pass.
- **A mandate is spent.** Yes to sending one email is not yes to sending it four
  times. `proceed` may be called as often as an execution needs, because it only
  reads; spending happens once, at the call site.
- **Both sides lapse**, at ten minutes. A question nobody answered has been
  overtaken by the conversation, and a yes still lying around later is not
  consent to something happening now.

A yes into a room with two open questions is refused until one is named, and
re-proposing the same action replaces the earlier ask so an answer cannot land
on a question the user has stopped looking at.

`confirm_pending` is a module function and deliberately **not** a tool: a tool is
something the model can call.

---

## 3c-sexies. Earning a free hand

`gateway/anticipation.py`, fed by `gateway/readback.py`.

Krish, 2026-09-23: *"trust means anticipating correctly what i need and correctly
executing it to perfection... at some point I know that he would execute to
perfection and would give him a free hand to complete things as per his
discretion and just present me the final result which is the point called the
full stop."*

A `Guess` is written down before the outcome is known and says what triggered it.
Three outcomes, not two: `not_now` - right about the need, wrong about the
moment - is kept apart from `wrong`, because holding a door for somebody who
wanted to walk past is a different mistake from holding a door that is not there.

**Outcome and quality are recorded at different moments**, and the first version
conflated them. `settle` took both together, so the quality had to be known when
Krish said yes - before the work had been done. It never was, every guess was
rated `None`, `perfect_run` was permanently zero, and the ladder could not climb
past `mention` however well anything went. A ladder nothing can climb is
decoration. So `settle` closes the anticipation when he answers, and `rate`
records how the work turned out afterwards, once. Neither will take a verdict
from the agent.

The ladder, per domain: **observe** → **mention** → **prepare** → **act and
report** → **full stop**. Five settled guesses before the rate means anything,
eighty per cent wanted to start offering, then three, five and ten consecutive
faultless executions. One botched execution drops it immediately and climbing
back costs the same as the first climb - slow up, fast down, which is how it
works with people. A run rather than a rate, because a rate lets an old failure
be washed out by volume.

An **unprompted** read-back is the producer: Jarvis raising something Krish did
not ask for is a guess, and must say what prompted it. A read-back for something
he asked for is not a guess at all. His yes is the grade; silence past the window
is `not_now`, settled by the clock. `tools.rate_work` is how he says how the work
went, and `tools.awaiting_a_verdict` is what lets *"how did that go?"* be asked
about something specific.

Neither is a tool. A tool is something the model can call.

### Noticing, which is where the guesses come from

`gateway/noticing.py`, run by the maintenance sweep every four hours.

The ladder had nothing on it: `anticipation` scores guesses, `readback` offers
them, and nothing made one. This makes them, and it makes them by **reading rows
this system already keeps** rather than by observing anything - commitments with
a due date, requests that keep coming back. That is the whole difference between
anticipation and invention: every prompting carries the record it came from, so
*"why did you think that?"* has an answer that is not a feeling. A test asserts
over the imports that the module can reach nothing else.

**Noticing and saying are separate decisions**, and this is the first place in
the system where a rung changes behaviour rather than describing it. Everything
noticed is recorded as a guess; `worth_saying` asks the ladder which of it Krish
actually hears. At `observe` the answer is *none of it* - and recording it anyway
is what makes the bottom rung a starting point rather than a trap, because an
assistant that only writes down what it is allowed to say can never demonstrate
it was right and so can never climb.

Three more rules, each with a number in `describe()`:

- **`MOST_PER_SWEEP = 3`.** A person who points out six things you might want is
  helping; sixty is a cost. The cap is on what is said and never on what is
  noticed.
- **`QUIET_DAYS = 7`.** A prompting whose guess was recently settled `not_now` is
  held back. He answered; asking again that afternoon is how a person learns to
  stop reading what they are asked. Only *not now* buys quiet - being right is
  not a reason to stop.
- **`DUE_WITHIN_DAYS = 2` and `TIMES_BEFORE_A_PATTERN = 3`.** Long enough to act
  on, short enough not to be noise; and twice is a coincidence.

### Where the record is kept

`gateway/trustbook.py`. It lived in a Python list until 2026-09-23, so every
restart wiped what Jarvis had earned - the same failure as a ladder nothing can
climb, wearing a different hat. Persisting it exposed a second one: the grades
were somewhere he could have written them.

So it is two entity types, not one:

| | written by |
|---|---|
| `guess` — what he thought Krish would want, and why | Jarvis |
| `guess_verdict` — whether he was right, and how well he then did | the operator console only |

`dba/permissions.OWNER_WRITTEN_TYPES` holds the second, so writing one needs
`administer`. The checks in `anticipation.settle` and `rate` are still worth
having - they catch the honest mistake at the call site and say why - but a check
inside the process being judged is advice. The DBA's refusal, in another service
over HTTP, is the part that holds when the advice is ignored.

**Loading is deliberately hostile.** A verdict naming a guess that is not there
is *reported*, not skipped: a missing row is ordinary, but an extra verdict is
the shape a forged promotion would take, and a loader that quietly dropped one
would be the place nobody looks. Two verdicts on one guess are reported the same
way, and the first one stands.

### Krish's side, and why it is a different process

`gateway/console.py`, run as `python -m gateway.console`.

The sweep was writing guesses nothing could ever settle, so every one of them
would have aged quietly into a wrong answer. A record that only accumulates
failures is worse than no record, because it looks like evidence.

The console closes that loop, and it authenticates as `operator_console` with
Krish's own token - refusing to run at all when that token is missing, rather
than falling back to Jarvis's identity. A verdict written in the name of the
agent being judged is not a verdict.

**The consequence, stated rather than left to be discovered: a "yes" typed into a
conversation with Jarvis does not settle a guess.** It settles the *action* -
`readback`'s mandate, which is in-process and needs no store - and that is enough
to get the work done. The durable verdict that moves the ladder is slower and
comes from here. If the conversation could write verdicts then the Gateway would
hold the operator's token, and there would be no separation at all.

`lapse` settles what Krish never answered, after a week, as **`not_now` rather
than `wrong`** - he may well have needed the thing and not wanted it raised then,
and recording silence as a bad guess teaches Jarvis to stop noticing when the
lesson available is to wait. It is written from the console for the same reason
everything else is: "no answer" is still a judgement. A guess that was never
meant to be said does not lapse at all, because punishing Jarvis for a silence
that was his own is arithmetic dressed as rigour.

Timestamps are microseconds. At second granularity, three results judged in the
same second sort arbitrarily and a failure can land ahead of the successes that
followed it - which is exactly the bug `gateway/persistence.py` hit, for exactly
the same reason.

---

## 3c-septies. A long job done in front of him

`gateway/taskrun.py`, probed by `tests/probes/taskrun_probes.py`.

Krish, 2026-09-23, describing the thing he actually wants from all of this:

> *"I should say Jarvis prepare my expense statements by looking into my
> business account - ask me questions while you are working on the account so
> that we don't have any confusion about what needs to be done. Also use last
> year's statement as a model and ask me questions when you can't find the data
> that you seek."*

Three instructions in one sentence, pulling against each other. Work without
interrupting him. Ask when genuinely stuck. Follow a model. Everything in this
module is one of the four refusals that let all three hold at once.

### The model carries shape and never values

*"Use last year's statement as a model"* is the most dangerous sentence in the
request, because the obvious implementation is the worst one: copy last year's
figures, change what you can find, ship it. Every number in that statement is
then a claim about this year sourced from a different year, and the ones nobody
got round to checking are indistinguishable from the ones that were.

So a `Model` is a list of `Field(name, means)` and holds no value anywhere. The
copy-last-year implementation is not forbidden, it is **unreachable** - there is
no attribute for a figure to travel in. That is Amendment 3 made structural
rather than promised, and it is the one claim here that no behavioural test can
prove: a `Field` that grew a `value` would break nothing until the morning a
figure came through it. `test_a_model_cannot_carry_a_value` therefore asserts
over the parsed AST of the module, which is the lesson from the ledger test that
passed on a docstring.

Each `Run` also builds its own `Need` objects from the model. A model that
handed out shared ones would put last quarter's figures in this quarter's
statement by a second road, and a probe closes it.

### A line is filled from a source, or it is not filled

`Need.found(value, source=)` - `source` is keyword-only and has no default.
There is no `assume`, no `default`, no `estimate`, and a test asserts the full
method list rather than trusting the docstring that says so. A need that cannot
be filled becomes a `Question` and that is the only other exit from `unmet`.

An empty statement with three honest questions attached is a better morning's
work than a complete one with a plausible number in it, and only one of those
two is recoverable by being told.

### The one who was asked is the one who may answer

`Need.ask` records **who the question was put to**, at the moment of asking, so
that the answer has somebody to be checked against instead of naming itself.
`answered(value, by=)` refuses anyone else - Jarvis first, because Amendment 1
is easiest to break exactly here: he is holding the pen, he has a good guess,
and afterwards a guess and an answer look identical. A third party is refused
for the same reason. `waive` is Krish's decision to leave a line out and is
recorded as his; Jarvis waiving a line is an assistant with no holes to report.

Who the work is for is who its questions go to. Hard-wiring Krish would mean a
run for anyone else quietly asked the wrong person, and a run *for* Jarvis is
refused outright.

### Parking a question does not stop the work

`depends(name, on=)` makes *"carry on with the independent work"* computable
rather than a judgement. A blocked line parks its question, `workable()` hands
back everything else, and the blocked one is never attempted with a value
nobody confirmed. A blocker that is merely **asked** does not release the work
behind it; only a settled one does.

A dependency loop is refused where it closes, not discovered later. A loop does
not crash: every line in it is quietly unworkable forever, the narration says
*waiting on* about each of them, and the run looks busy while nothing moves.
`finish` would catch it eventually - at the end of a morning nobody got anything
out of.

### Finishing is a claim, so it is checked

`finish()` refuses while any line is neither filled nor asked about, and names
each one with what it means. If questions are open it raises `Stuck` and quotes
them. Reporting a statement as done with a silent hole in it is the failure this
whole arrangement exists against, and it is the one that looks most like
success.

### Not yet done

Nothing calls this. It is the decision half of the split: it has no store, no
clock beyond `now`, no account and no way to read one. The producer is the piece
that reads Krish's business account and the consumer is the piece that puts the
open questions in front of him - the console already knows how to do the second
for `noticing`, and the natural next step is one path for both.

---

## 3c-octies. Whether it runs on his machine at all

`desktop/readiness.py` decides, `desktop/machine.py` looks things up,
`desktop/bringup.py` is what he types. Probed by
`tests/probes/readiness_probes.py`.

Everything in sections 3c-bis to 3c-septies was written and tested in a Linux
container, and none of it had ever started on the machine it is for. Two of them
broke the first time Windows saw them — a glibc-only date format that took out
every noticing, and a file read without an encoding that mangled the amendment
headings. Neither was visible from here. So *"does it run on my PC"* needs an
answer that is a list rather than a yes.

    python -m desktop.bringup

Three rules it is built on, each from something that already went wrong here:

**An unchecked thing is never green.** `tests/test_real_machine.py` once had a
log check that passed on a machine with no log, because scanning nothing returns
nothing. A check whose precondition failed is `BLOCKED` and names what blocked
it. There is no path from *"could not look"* to *"fine"*. The reading's defaults
are the worst case for the same reason, field by field, asserted as literals so
that adding a fact costs somebody one deliberate thought about what it means
when nobody supplied it.

**Order is by dependency, not importance.** Telling him the constitution is not
installed, when the cause is that the DBA is down, is telling him about a
symptom. `NEEDS` makes that computable — the same arrangement `taskrun` uses,
for the same reason — and a test holds the table to the order the checks
actually run in, because `_need_met` reads its predecessor directly rather than
through a `None` branch nothing could reach.

**Every red says what to do.** Whoever reads this is alone with it, possibly on a
phone. `assert x` tells him nothing and so does *"constitution: FAILED"*.

The four actions — make a key, write an escrow, restore a key, install the
constitution — are flags rather than things it does on its own, because a status
command that fixes things is one nobody can run to find out where they stand.
Each refuses to overwrite what is already there: replacing a key is every
amendment gone, silently, until somebody needs one.

**It does not start anything.** `keep-jarvis-up.ps1` owns that: the thing that
restarts Jarvis has to be the thing that survives him, and a bring-up that also
ran him would be a second supervisor with different opinions. It says which one
is not running and the exact line that starts it.

Nine more `real_machine` tests cover the half built on 2026-09-23 — the key and
its backup, the constitution opening, no amendment altered, the trust record
surviving a restart, the console authenticating as the operator rather than as
Jarvis, the upkeep loop actually sweeping, and the two Windows-only failures
above, each asserted where it broke.

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

### The commit says who made it

`identity.git_identity()`, passed on every `git` invocation in
`gateway/candidate.py` and on the one in `selfmod.commit_candidate` that writes
history. Two things it settles, and the second is the one that was actually
broken:

**A commit Jarvis wrote says Jarvis wrote it.** Inheriting the machine's
configured identity puts a candidate change Krish has never seen into the
history under his name — Amendment 3's first item, a record claiming to come
from somebody else, arrived at by doing nothing in particular.

**And `git commit` with no identity configured does not fall back to anything.**
It fails: *"Author identity unknown"*. A CI runner has no identity and neither
does a fresh Windows account, so self-modification worked only on machines where
somebody had already set git up by hand — and failed on the one machine it is
for. It was red on CI for a day while every local run was green, because what it
depended on was the developer's git config rather than anything in the
repository. `tests/test_logscan.py` now reproduces that machine with a fixture
rather than trusting the one it runs on.

The flags go on each command rather than into a config file. Writing the
identity somewhere would work and would be wrong twice: it would follow every
other program on the machine that runs git, and a repository whose config Jarvis
edits is one he can later commit through as somebody else.

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
