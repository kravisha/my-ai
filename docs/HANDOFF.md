# Handoff — checkpoint 2026-08-28

Written for a session with no memory of the conversation that produced this
state. **Rewritten at each checkpoint, not appended to.**

## Read this first, and read it short

This file is deliberately thin. [`JARVIS.md`](JARVIS.md) is the map — what the
system is, how it is organised, what is built and what is not — and duplicating
it here is how one of the two goes stale (§121, and this file *was* the one that
went stale).

| Read | For |
|---|---|
| **[`JARVIS.md`](JARVIS.md)** | The whole system. Start here, read to the end. It is maintained under addendum 47 and kept honest by `tests/test_living_documentation.py`. |
| **This file** | Where the last session stopped and what to do next. Nothing else. |
| [`TASK_QUEUE.md`](TASK_QUEUE.md) | Every task, its status and its reasoning. |
| [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) | Why anything is the way it is. 138 sections, newest last. |

## Run these first

```bash
cd C:/Users/ADMIN/my-ai
git log --oneline -5
git status --porcelain
.venv/Scripts/python.exe -m pytest -q
```

Expect **2724 passed, 8 skipped, 5 deselected**. Use `.venv/Scripts/python.exe`,
never bare `python` — the system Python has no dependencies.

The 8 skips are deliberate and named where they are declared.

## Where the project stands

**The governance stack is complete and verified end to end.** Parliament carries
resolutions, the governed store holds instruments under a precedence rule, agents
read what binds them and refuse what they cannot satisfy, refusals are counted and
attributed, the Speaker reports all of it, and a Software Engineering Department
turns an authorized directive into governed data or names the capability the
architecture lacks.

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m simulation verify
```

Ten scenarios and the curriculum, one verdict. **Last run: PASS** (2026-08-28),
and it was the first that exercised every mechanism rather than passing over some
of them. It prints what it cannot see with every verdict — read that list before
trusting the green.

**The product side has not moved since TQ-80.** The system cannot price anything,
has no broker connection, and has never served a client. That is a consequence of
the track the owner chose deliberately, not a defect.

## What this session did

Sixteen commits, `e48fd64` through `855f89a`. In order of what they built:

- **TQ-82, TQ-86, TQ-87** — the governed knowledge layer, and agents that read it.
  A rule can now be changed by vote and one real code path obeys it.
- **TQ-88 through TQ-91** — simulation. Governance is exercised by a scenario,
  `queue.pressure_ratio` was re-aimed after being found anti-correlated with
  health, and `simulation verify` gives one verdict over both simulation systems.
- **TQ-90** — refusals are recorded, so a rule that forbids its own subject no
  longer looks like a quiet market.
- **TQ-93, TQ-94** — liveness split from progress, and a fault that makes an agent
  slow rather than dead so the split can be shown to work.
- **TQ-83, TQ-95** — the Software Engineering Department, and the decision *not*
  to build Evolution's relay.
- **Addenda 46, 47, 48** assimilated and reconciled (§119, §121, §131).

Every one is recorded at `SPEC_RECONCILIATION.md` §117–§138.

## What only the owner can do

1. **Write the genesis Articles.** Parliament works and governs nothing in the
   working database: no Articles are in force, so there is no electorate and no
   arithmetic. Level 0's to write (§120). An offer to draft a candidate text and
   roll for approval or rejection stands and has not been taken up.
2. **Unhold market data.** TQ-75 was held pending *"all simulation issues dealt
   with first"*; that condition is met. It needs a provider choice and a cost.
3. **Signed commits** (TQ-85), which would make document custody prevent rather
   than only detect.

## Known blockers and open questions

- **No reviewer role.** The Software Engineer never approves its own proposal
  (46 §11), and nothing else in the organization can approve one, so proposals
  wait for a person. Deliberate — see §137.
- **No release, no rollback** (TQ-96). Evolution's contribution has nothing to
  plan without them, which is why §138 declined the relay.
- **The repository is public** (`github.com/kravisha/my-ai`). Raised in
  `DOCUMENTATION_RECONCILIATION_PLAN.md` §0 on 2026-08-16, never answered. The
  Constitution and addenda 5, 11, 15, 22 are held privately.
- **`MODEL_BUDGET_DAILY_TOKENS=1500000`** is set in `.env` (gitignored) on the
  owner's authority. The guard still exists; do not remove it.

## Constraints that must not be violated

These have each been bought with a defect. `SPEC_RECONCILIATION.md` has the story.

1. **Client portfolios are never stored** (§111). No table exists; an import
   tripwire fails the suite if a storage module returns.
2. **The Constitution is the owner's and is not in this system** (§120). It is
   enforced by tests that fail, never by data that ranks — a store that ranks
   cannot hold something unrankable.
3. **The Articles' amendment threshold is a constant in code**, not a clause in
   the Articles (§123). A rule a vote can reach is not a rule.
4. **Absence is `unknown`, never a plausible default** (§100, §104, §118, §132).
5. **Tripwires are re-aimed, never deleted** (§105, §110, §116, §128, §134).
6. **One identical refusal for every reason** a caller is not entitled to
   distinguish (addendum 44 §9.3, §123).
7. **`docs/JARVIS.md` is under document custody.** Editing it means updating
   `docs/document_custody.yaml`'s digest in the same commit, or the suite fails.
8. **Simulation seeds go through the production API, never SQL** (§128). A
   fixture able to build states the organization cannot reach measures the
   fixture.

## Four ways this project has been wrong, which keep recurring

Worth knowing before writing a test, because each was found by mutation testing
after the code looked right:

- **A test over data does not test the rule that produced the data** unless the
  data can exercise the rule (§117, §118, §123, §129).
- **A test that constructs its own input never tests the code that constructs the
  input** (§132).
- **A function tested in isolation is not a function that runs** (§134).
- **A seam asserted by reading source is not a seam that runs** — whenever a test
  reaches for `inspect.getsource`, ask what would still pass if the code were
  there and never executed (§136).

## What the next session should do first

**TQ-96 — release and rollback.** It was queued at §138 as the thing that unblocks
Evolution's contribution, and it is the largest item `simulation verify` lists
among what it cannot see.

Its first question is not how to build one but **what a release even is here**,
given that the governed layer already changes behaviour without one. Rolling back
an instrument is a supersession the store already supports; rolling back *code*
is a different problem, and conflating them would be §138's mistake in the other
direction. §119 §5 already set the constraint: addendum 30 §13 says this system
*"is not a single monolithic object that must be serialized and restarted"*, so a
release must not be built as a restart script.

Smaller alternatives if that is too large to start: **TQ-92** (read the
cooperation the organization already records — the only actionable part of
addendum 48) or **TQ-28** (a real known defect: the database-isolation guard trips
after a backend has run).

## Working rhythm

Assimilate verbatim → reconcile against the *addenda* and not the build (§111) →
queue → one increment → suite green → **mutation-test with attribution** → run it
and look → record a `SPEC_RECONCILIATION.md` § → update the queue and
`JARVIS.md` → commit.

A green suite is not evidence. Every real defect in this project came from
starting the thing and looking at it.
