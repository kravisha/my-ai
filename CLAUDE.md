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

---

## Two rules about what gets built

**Machinery with no user does not get built.** This repo says it in
`backend/migrations.py` and it has been violated repeatedly — a complete life
ledger nothing wrote to, a log scanner with no log, a capability-gap detector
nothing read. After building a mechanism, find its producer and its consumer and
name them. If either is missing, that is the next task, not a later one.

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
`python -m desktop.verify`.
