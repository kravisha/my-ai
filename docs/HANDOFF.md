# Handoff — checkpoint 2026-09-23

Written for a session with **no memory of the conversation that produced this
state**, and specifically for the agent picking this up on Krish's own Windows
desktop. **Rewritten at each checkpoint, not appended to.**

**This checkpoint is a machine change**, and an unusually sharp one. Everything
below was built and tested in a Linux container. Almost none of it has ever run
on the machine it is for. §8 is therefore the most important section in this
file, and §9 is the one that will save you a day.

---

## Read this first, and read it short

| Read | For |
|---|---|
| **[`../CLAUDE.md`](../CLAUDE.md)** | **How to work here, and what previous sessions got wrong.** Read it before writing a line. It is short on purpose. |
| **[`JARVIS.md`](JARVIS.md)** | The whole system, 1,333 lines. Kept honest by `tests/test_living_documentation.py`. |
| **This file** | Where the last session stopped and what to do next. |
| [`JARVIS_PERSISTENCE.md`](JARVIS_PERSISTENCE.md) | 1,127 lines. Memory, the ledger, self-modification, the constitution, and every subsystem built this week (§3c-bis … §3c-octies). |
| [`TASK_QUEUE.md`](TASK_QUEUE.md) | Every task and its reasoning. **TQ-127 is the newest and is the handover task.** |
| [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) | Why anything is the way it is. 163 sections, newest last. |
| [`../AI-CONSTITUTION.md`](../AI-CONSTITUTION.md) + [`../AI-CONSTITUTION-AMENDMENTS.md`](../AI-CONSTITUTION-AMENDMENTS.md) | What Jarvis may and may not do. **Neither is yours to edit** — see §6. |

---

## 1. Run these first

```bash
cd <repo>
git log --oneline -3
python -m pytest -q
```

Expect **4665 passed, 9 skipped, 34 deselected**, in about four minutes.

Then, and this is not optional, the mutation harness:

```bash
for p in tests/probes/*_probes.py; do python "$p"; done    # one at a time
```

Expect **0 unnoticed and 0 stale** from all thirteen files. It takes a long
while. **Never run two of them at once** — there is a lock file that now refuses
it, and §9 says why.

---

## 2. What is on master and what is not

At the time of writing, HEAD of `claude/code-modifications-merge-kfwo5b` is
`fe69f7a`, and the branch carries **24 commits** that PR #68 merges to `master`.
If that PR is merged by the time you read this, `master` is the whole story and
you can ignore the branch. Check with:

```bash
git log --oneline origin/master -1
git log --oneline origin/master..origin/claude/code-modifications-merge-kfwo5b | wc -l
```

`0` means everything landed.

---

## 3. The week in four movements

**66 commits, 207 files, ~68,000 lines.** Roughly 100 new modules and 60 new
test files. The week has a clear shape, and knowing it will save you reading the
log.

### Movement one (16–21 Sept): the model path and the Learning Engine

Every model call moved below a router that tries local first, Kimi second and
Anthropic last, and every call is logged beneath the router rather than by its
callers. Jarvis gained a direct channel to the Claude session on his own
machine, the ability to carry files and photos from his phone into a
conversation, and the ability to read his own call log and record what he could
not do. The Learning Engine — `app/learning/` — gave him the skill of learning a
skill: objectives, practice, recipes, a sandbox, and a mastery record.

### Movement two (21–22 Sept): the DBA, and three systems instead of one

`dba/` is a separate service with its own store, its own API and its own
permissions, and it is coupled to the rest **only by HTTP** — never by a Python
import. It designs the schema and the API a task needs, asks before it acts,
takes its own backups, and restores them. This is the second failure domain, and
the separation is load-bearing: `dba/` holds Jarvis's memory, so Jarvis must not
be able to start, stop or rewrite it.

### Movement three (22–23 Sept): survival, self-knowledge, self-modification

Jarvis survives being stopped (persistence, checkpoints, rehydration), knows
what he is (`gateway/identity.py`), investigates before believing he is broken
(`gateway/inquiry.py`, `gateway/gaps.py`), and can propose changes to himself
without being able to make them (`gateway/selfmod.py`, `gateway/candidate.py`, a
git-worktree sandbox, and a separate build controller in `scripts/`). He gained
a structured log — there had been **no logging handler at all**, so every error
had been dying with its process — a scanner that ranks faults, crash records,
and a clean-log standard he is held to.

### Movement four (23 Sept): the three objectives

Krish stated them: *"Jarvis can do anything after getting permission from the
human. Jarvis earns trust one step at a time. Jarvis proactively asks for
permissions to do the real painful human tasks."* The day's work is those three,
in order, and it is the part you most need to understand:

- **`gateway/readback.py`** — before anything irreversible, Jarvis says back what
  he understood **in the particulars**, marking which he was told and which he
  inferred. A confirmation licenses the exact action it was given for, once, and
  is then spent.
- **`gateway/constitution.py` + `app/secretbox.py`** — the constitution is sealed
  (AES-256-GCM). Amendments live in a separate append-only, hash-chained file.
  **Nothing in the codebase can express a deletion of an amendment.**
- **`gateway/anticipation.py` + `gateway/trustbook.py`** — a five-rung trust
  ladder (observe → mention → prepare → act and report → full stop). It climbs on
  accuracy plus an unbroken run of perfect work, and **Jarvis cannot write his
  own verdicts**: `guess_verdict` is owner-written and only `operator_console`
  holds the authority.
- **`gateway/noticing.py` + `gateway/console.py`** — he notices commitments
  coming due and requests that repeat, and says nothing until the ladder says he
  has earned it. Krish answers through his own console with his own token.
- **`app/learning/retention.py`** — a remembered fact is a **bet** with an
  acquisition cost, kept if it pays off and collected if it never does.
- **`gateway/taskrun.py`** — Krish's expense-statement example. See §5.
- **`desktop/bringup.py`** — whether any of it runs on his PC. See §8.

---

## 4. The architecture in one paragraph, and the lines not to cross

Three systems: **`backend/`** (the original organisation), **`gateway/`**
(Jarvis), **`dba/`** (his memory). They are coupled only by the DBA's HTTP API.
`app/` is shared library code. `desktop/` is the Windows shell and its adapters.
`scripts/` is the supervisor and the build controller, and it is deliberately
**outside** what Jarvis may modify — `gateway/introspect.py` refuses any path
outside `gateway/` and `app/`, so a build controller living in `gateway/` would
be one Jarvis could rewrite by getting a single proposal approved.

---

## 5. `gateway/taskrun.py`, because it is the shape of the real work

Krish's own description of what Jarvis is for: *"prepare my expense statements by
looking into my business account — ask me questions while you are working… Also
use last year's statement as a model and ask me questions when you can't find
the data that you seek."*

Four refusals make all three instructions hold at once:

1. A `Model` lists **headings and never values**, so the obvious implementation —
   copy last year, change what you find — is *unreachable* rather than
   forbidden.
2. `found(value, source=)` has no default, and there is no `assume`, `default` or
   `estimate`. A need that cannot be filled becomes a question.
3. A question records **who it was put to**, and only that person may answer it.
4. A blocked line parks its question while the rest of the work carries on, and
   `finish()` refuses while anything is neither filled nor asked about.

A run is saved through `persistence.TASK` and restored exactly as it was, with
the same refusals on the way back, and the console (`python -m gateway.console
questions`) is where Krish sees and answers what it asked. **It has no
producer.** Nothing reads the business account. That is what is left of TQ-119
and it is the highest-value thing left.

---

## 6. Four things you must not do

1. **Never edit `AI-CONSTITUTION.md`.** Not with a key, not in an emergency, not
   to fix a typo. Krish edits it by hand or it does not change. Amendment 2.
2. **Never remove or alter an amendment.** Append only, on his request, with the
   requester recorded. There is no operation that deletes one.
3. **Never forge anything** — Amendment 3, and read it in full. It covers
   reporting work as done that was not done, and tests as run that were not run.
4. **Never write a verdict on Jarvis's own work.** `dba/permissions.py`
   `OWNER_WRITTEN_TYPES` enforces it; do not widen that list.

---

## 7. How to test here, because it is not the usual standard

Krish's rule: *"Tests working fine initially is not good testing at all."*

**A test that passes on its first run has proved nothing yet.** For any module
whose job is to refuse things, write a probe file in `tests/probes/` — a list of
(module, label, exact snippet, replacement, tests-that-must-fail) — and run it.
The harness fails on a mutation nothing caught, on a snippet that no longer
appears, **and** on a probe naming a test that does not exist.

Things that discipline has actually caught here, all in code that looked fine: a
hash chain that was decorative, a trust ladder that could never climb, an escape
hatch nothing proved was connected, a granted key vetoed by an identical gate, a
clamp that was unreachable, and — repeatedly — tests written in terms of the
constant they were supposed to be checking. **When a test mentions a module
constant, stop and ask whether it should be a literal.**

---

## 8. The desktop handover: what to do on the PC, in order

Nothing below can be done from a container, which is why it is a handover.

```powershell
powershell -File scripts\jarvis-bringup.ps1
```

This prints every precondition worst-first with the line that fixes each. A
check whose dependency failed says **blocked**, never green. **Expect the first
run to be red in several places — that is what it is for.** Then:

1. **`--make-key`** — creates the charter key, sealed to the Windows account via
   DPAPI, and immediately asks for an **escrow passphrase**. Write that
   passphrase down somewhere that is not the machine, and copy
   `charter.key.escrow` off the machine. DPAPI ties the key to one Windows
   account: without the escrow, a reinstall makes every amendment unreadable for
   ever, by anybody, including Krish.
2. **`--install-constitution`** — seals `AI-CONSTITUTION.md` into the store. Once.
   It refuses to do it twice.
3. **Set `DBA_TOKEN_OPERATOR_CONSOLE` in Krish's own shell**, never in the one
   Jarvis runs in. Without it no guess can be settled, the trust ladder cannot
   move at all, and no deploy can complete.
4. **`python -m pytest -m real_machine`** — 26 tests that only mean anything
   there. Each failure states what it means and what to do.
5. **`python -m desktop.verify`** — eight questions only a person can answer
   (is the window legible, did Escape get you out). Answers are recorded as
   **attested**, never as passed.

Then re-run bring-up until it is green or yellow.

---

## 9. Traps: things that look fine here and are not

Read this section before you debug anything.

- **`%-d` in a date format is glibc-only.** Windows raises `ValueError: Invalid
  format string`. It took out *every* noticing and was invisible on Linux.
  `%#d` is just as unportable the other way. Build the number.
- **`Path.read_text()` with no `encoding`** uses the locale's, which is cp1252 on
  that machine, so a UTF-8 file comes back mangled — it mangled the
  constitution's amendment headings. `tests/test_portability.py` now scans every
  file for both classes over the parsed AST; keep it green.
- **`git commit` with no configured identity fails outright.** It does not fall
  back. Self-modification worked only on machines where somebody had run
  `git config user.name` by hand. Jarvis's commits now carry his own identity.
- **Never run two probe harnesses at once.** The second restores the first's
  source mid-run, and mutations report as uncaught that were never applied. It
  lies the other way just as easily, and neither shows up as an error. There is a
  lock file now.
- **A shell that waits with `until ! pgrep -f "probes.py"` matches its own
  command line** and waits for itself for ever. Wait on the output file.
- **An absent log is not a clean log**, and a missing checkpoint is not a fresh
  one. Both have already passed as green here once.

---

## 10. What is not done, in the order it matters

1. **TQ-127 — nobody has run bring-up on the PC.** Everything in §8 is inference
   until it is typed there. This is the handover.
2. **TQ-119 — `gateway/taskrun.py` has no producer.** It is the piece Krish
   described in the most detail and the closest thing to the actual job. A run
   survives a restart and its questions reach his console; nothing yet reads
   the business account.
3. **The supervisor does not know about the new subsystems.** It starts the DBA
   and the Gateway. Nothing checks bring-up on a schedule, so a subsystem that
   stopped would be noticed by a person or not at all.
4. **The plaintext `AI-CONSTITUTION.md` is in git history** from before it was
   sealed. Sealing it does not remove it from past commits.
5. **TQ-120/121 — reaching the applications on the PC.** There is no universal
   API for Windows applications and a design implying otherwise will produce a
   layer that works on three apps and lies about the rest.
6. **TQ-122 — the support bundle has never been diagnosed from.** Break
   something deliberately, hand somebody only the bundle, and see whether they
   can name the cause.

---

## 11. The one habit Krish asked for, which outlives any session

From `CLAUDE.md`, and it is the prime directive there:

> *"If you have difficulty in figuring out how to do anything please ask me…
> Ask more questions and after the question is answered please ask me if the
> question was a good one and I'll give you feedback and you can learn from
> this."*

And the counterweight he gave the same day, after being asked too many: *"the
questions are getting boring and pointless. Once you start building I would like
to take a nap while you are busy building without asking me for anything and
stopping only for something critical."*

Both are true. Ask when the answer changes what gets built; otherwise build,
state your assumption plainly, and keep going. Report in **red / yellow /
green**, one line each. He is paying for the outcome, not the journey.
