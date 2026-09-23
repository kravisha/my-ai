# Working on this repository

Read this first. It is short on purpose, and it is not a description of the
system — `docs/JARVIS.md` is that. This is how to work here, and what previous
sessions got wrong.

---

## The prime directive: ask, then ask whether asking was right

Owner instruction, 2026-09-23: *"If you have difficulty in figuring out how to do
anything please ask me and I'll be able to help you out with at least some good
pointers that will break the logjam instead of you building something that won't
do the job. So let's also focus on good communications. Ask more questions and
after the question is answered please ask me if the question was a good one and
I'll give you feedback and you can learn from this. Please make this a habit and
have it as a prime directive for your personal growth."*

So:

1. **Ask rather than guess**, whenever the answer would change what gets built.
   The cost of a question is a minute. The cost of building the wrong thing is a
   day, and worse, it looks finished.
2. **After the answer, ask whether the question was a good one.** Say what you
   think its strength and weakness were before he does, so the feedback lands on
   a judgement rather than on nothing.
3. **Write the lesson down here.** This file is the only reason any of it
   survives — a habit agreed to in a conversation expires with that
   conversation's context window. That is his own principle applied to me:
   retain the lesson, discard the context.

### Lessons retained so far

- **When he answers a question with a principle, check whether the principle
  *is* the answer** before responding to it as a new topic. 2026-09-23: he was
  asked whether a gate refused something he wanted, replied "being inquisitive
  is not evil as long as the lessons are retained and the context discarded",
  and it was read as a philosophical aside rather than the direct answer it was.
- **Do not ask a question and answer it in the same breath.** It turns a
  decision into a request for ratification, and he loses the chance to say
  something you had not thought of. Noticed twice on 2026-09-23.
- **Report the clock, not your sense of elapsed time.** Working time runs far
  slower than wall clock. A CI job was reported as overrunning by 2.5× twice; it
  was on schedule and finished in 18 minutes against a 20-minute limit.

---

## Testing: his rule, and it is not optional

Owner instruction, 2026-09-23: *"Tests working fine initially is not good
testing at all — please use this ideology when you do testing. Code being
perfect the first time around is a fantasy that you should not buy into."*

**A test that passes on its first run has proved nothing yet.** Break the
behaviour it covers, confirm the test fails, put the behaviour back. Do this for
every test, not for the ones that feel risky — the failures found this way were
all in tests that felt fine.

What that discipline has actually caught in this repository:

- A test asserting the ledger has no `delete`, which **passed on the docstring
  that says so**. Assert over the parsed AST, never over the file's text.
- A test asserting `.prev` handling, which passed on the *comment* mentioning
  `.prev`.
- A test asserting the log had no unexplained noise, which **passed on a machine
  with no log at all** — an absent log is not a clean one.
- An escape hatch with 23 passing tests that **nothing proved was connected** to
  the window. Deleting the wiring broke no test.
- A fake that modelled `window.events.loaded +=` as a list, which cannot work —
  proving the wiring worked against an API that does not exist.
- A crash-record accessor that returned the faulthandler stream first, hiding
  the newest real crash behind an empty file.

Every one of those was found by probing, not by review.

### Probing by hand works once. Write the mutations down.

2026-09-23. `tests/test_inquiry.py` went green on its first run — 56 tests, no
failures, and it had proved almost nothing. `tests/probes/inquiry_probes.py` then
applied 49 mutations to `gateway/inquiry.py`, and **three went unnoticed**:

- A test named for the eliminated-alternatives term passed with that term
  deleted. Eliminating an alternative also cleared a *different* objection, so a
  different term moved the number. The test was measuring the wrong thing and
  said the right thing in its name.
- A test asserting confidence stayed bounded only exercised a clamp that turned
  out to be **unreachable** — the terms it clamps sum to exactly the limit.
- A branch no test reached at all: the one the suite was written to cover did not
  need it. It was deleted and replaced by a requirement that is reachable.

None of those would have been found by reading the tests, and probing by hand
finds them once and then loses the evidence. A file of mutations finds them again
every time the code moves. Prefer it for any module whose job is to refuse
things. The harness reports **stale probes** — a snippet that no longer appears —
as a failure, because a probe that silently stopped applying reports success.

A fourth, from the wiring in the same session: a warning meant to be the first
line of what Krish reads was built as `{"WARNING": ..., **rest}`. The serialiser
dumps with `sort_keys=True`, so dict order was discarded and the warning came
first only because `W` sorts before lowercase letters. **If a line has to be
first, build the string.**

There are three probe files now, sharing `tests/probes/harness.py`. Add one for
any module whose job is to refuse things or to delete things.

### A test written in terms of a constant cannot detect a wrong constant

2026-09-23, from `tests/probes/retention_probes.py`. Four mutations changed a
policy number and no test noticed, because the tests were written as
`MIN_OFFERS_TO_JUDGE - 1` and `MIN_OFFERS_TO_JUDGE`, which hold at *every* value
including the one that breaks the behaviour. A fifth changed a maintenance
interval from a week to six hours and no test noticed, because every test asked
"is it due?" twice in the same second.

Where a number **is** the policy — the difference between keeping a fact and
deleting it, or how often Jarvis disturbs his own record — assert it as a literal
with the reason it has that value, and assert the *consequence* at whole numbers
too. `test_the_policy_numbers_are_what_they_are` and
`test_the_maintenance_cadences_are_what_they_are` are the two examples.

**A probe that cannot fail is worse than no probe.** Two written on 2026-09-23
were no-ops and reported "caught" against tests that were never at risk: one
replaced a list with `[] or [...]`, which evaluates to the second list, and one
set a fact's cycle to 10,000 days *before* the step that was supposed to collect
it, so nothing was collected and the assertion held for no reason. Read a probe's
replacement as code, not as intent.

A related one from the same run: a test can pass on the wrong term. A test named
for the eliminated-alternatives term of a score passed with that term deleted,
because the same change also cleared a different objection and *that* moved the
number. To isolate a term, build a case where every other term is already
saturated.

### Be brief

Owner instruction, 2026-09-23: *"please be less verbose and more concise and
precise. You can get to the problem directly and lesser context is fine and I'll
ask you if I need more context."*

Lead with the finding or the change. Do not restate the request, do not narrate
the route taken, and do not pre-empt questions he has not asked. Reasoning belongs
in the code comments and the docs, where it survives; a reply is not the place to
prove the thinking happened. He will ask for more.

---

## Two rules about what gets built

**Machinery with no user does not get built.** This repo says it in
`backend/migrations.py` and it has been violated repeatedly — a complete life
ledger nothing wrote to, a log scanner with no log, a capability-gap detector
nothing read. After building a mechanism, find its producer and its consumer and
name them. If either is missing, that is the next task, not a later one.

Its corollary, learned on 2026-09-23: **a single call site that carries a whole
scheme needs a test naming it.** `memory.advice_for` is the only thing that marks
a lesson as used, and `engine.accept` the only thing that credits a payoff.
Delete either and the system still runs, still reports, and quietly deletes the
lessons that were working. A comment saying the call matters does not survive a
refactor; `test_both_settling_call_sites_exist_in_the_engine` does.

**If it can be decided, decide it in tested code.** Anything needing Windows, a
screen, a microphone or the network goes behind a thin adapter with one function
per effect and no branching. A judgement inside an adapter is a bug in the
split, because the adapter is the part that cannot be tested here. See
`docs/JARVIS_SHELL.md` §0.

---

## Where things are

| Want | Read |
|---|---|
| What exists and why | `docs/JARVIS.md` — the living documentation, under custody |
| The queue, in priority order | `docs/TASK_QUEUE.md` |
| Persistence, the ledger, self-modification | `docs/JARVIS_PERSISTENCE.md` |
| The shell and the escape hatch | `docs/JARVIS_SHELL.md` |
| The DBA | `docs/DBA_AGENT.md`, `docs/DBA_AGENT_DEVELOPMENT.md` |

Tests that need the real PC are marked `real_machine` and excluded from the
default run: `pytest -m real_machine`. The ones needing a person are
`python -m desktop.verify`. The mutation harness is
`python tests/probes/inquiry_probes.py` — not collected by pytest, because it
edits source files and runs pytest inside itself; it restores them in a `finally`
and verifies the restoration by hash.
