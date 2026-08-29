# Handoff — checkpoint 2026-08-28 (Providence)

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
| [`SPEC_RECONCILIATION.md`](SPEC_RECONCILIATION.md) | Why anything is the way it is. 150 sections, newest last. |

## Run these first

```bash
cd C:/Users/ADMIN/my-ai
git log --oneline -5
git status --porcelain
.venv/Scripts/python.exe -m pytest -q
```

Expect **2900 passed, 8 skipped, 5 deselected**. Use `.venv/Scripts/python.exe`,
never bare `python` — the system Python has no dependencies.

The 8 skips are deliberate and named where they are declared.

## Where the project stands

**The system was re-scoped on 2026-08-28.** Project Providence (addenda 49–52,
reconciled at §140) makes the product *a personal AI world* — one person, one
world, entered through a device-independent portal, hosted by a Personal Usher,
served by ~15 personal agents and informed by an AI newsroom. **The financial
intelligence work everything here was built for becomes the Personal Portfolio
Manager, one agent among them.**

That changes what comes next. Market data (TQ-75) and the broker connection are
no longer the head of the queue; agent identity, client binding, the agent and
trainer libraries, the Usher and the Reporter are. Both Providence documents give
the same ordered priority and TQ-97 built the first item.

**The governance stack is complete and verified end to end.** Parliament carries
resolutions, the governed store holds instruments under a precedence rule, agents
read what binds them and refuse what they cannot satisfy, refusals are counted and
attributed, the Speaker reports all of it, and a Software Engineering Department
turns an authorized directive into governed data or names the capability the
architecture lacks.

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m simulation verify
```

Eleven scenarios and the curriculum, one verdict. **Last run: PASS (2026-08-29)**
— seventy-one properties and six curriculum exercises, with the model-dependent
scenarios actually run rather than skipped. It prints what it cannot see with
every verdict; read that list before trusting the green.

**The product side has not moved since TQ-80.** The system cannot price anything,
has no broker connection, and has never served a client. Under Providence that is
no longer the critical path, but it is still true and still worth stating.

## What this session did

Three commits on top of `c80ac29`:

- **TQ-96 — release and rollback** (§139). The question first: *what is a release
  when the governed layer already changes behaviour without one?* A named set of
  governed changes that stand or fall together, whose way back is authorized
  before the way forward is taken. The **code** half is declined, not deferred —
  this organization observes its code version and may not choose it.
- **Providence assimilated and reconciled** (addenda 49–52, §140). Six conflicts,
  two against constraints bought with a defect.
- **TQ-97 — persistent agent identity** (§140 §4). The durable identity here *was*
  the display name, which addendum 51 §3 forbids in terms.
- **§141 — owner correction.** The Constitution is one document, addendum 49 is
  its v2.0, and **it applies to the system with the owner inside it**. §120's
  *outside the system entirely* was a misunderstanding. Addendum 49 is now held
  privately, enforced rather than asked.

### The previous session, for context

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
1a. **Seed the genesis Constitution**, now that the machinery exists (§142). Same
   shape as the Articles: the owner's text, adopted once, and every amendment
   after it is a two-thirds vote. Addendum 49 is the document.
1b. **Re-run `JARVIS_GAP_ANALYSIS.md` against Constitution v2.0**, or say it is
   retired. It currently scores against v1 (§141 §1).
2. **Unhold market data.** TQ-75 was held pending *"all simulation issues dealt
   with first"*; that condition is met. It needs a provider choice and a cost.
3. **Signed commits** (TQ-85), which would make document custody prevent rather
   than only detect.

## Known blockers and open questions

- **No reviewer role.** The Software Engineer never approves its own proposal
  (46 §11), and nothing else in the organization can approve one, so proposals
  wait for a person. Deliberate — see §137.
- **Release and rollback exist for governed data** (TQ-96, §139) and are declined
  for code, because this organization observes its code version and may not
  choose it. Evolution's relay (§138) is unblocked.
- **Project Providence re-scopes the system** (addenda 49–52, §140). Financial
  intelligence becomes one personal agent among fifteen. TQ-97 built persistent
  agent identity; TQ-98 (the client profile, and the watchlist boundary §140 §5
  draws) is next and its guard comes before its table.
- **The organization may amend its own Constitution at two-thirds** (§142, owner
  decision). Built, tested, and holding no text: genesis is the owner's, like the
  Articles. Two consequences are recorded rather than engineered around — level 0
  and level 1 cost the same, and the roll that decides constitutional amendments
  is itself amendable (§142 §2).
- **Still with the owner**: what refuses a persona that crosses the line (TQ-100),
  and `JARVIS_GAP_ANALYSIS.md` is stale until re-run against Constitution v2.0.
- **The repository is public** (`github.com/kravisha/my-ai`), and on 2026-08-28
  that cost something: addendum 49 — the Constitution — was assimilated into
  `docs/addenda/` by the ordinary intake rule, reached one local commit, and was
  removed from history before any push (§141 §3). The boundary had been prose
  since 2026-08-16 with nothing enforcing it. It is now
  `tests/test_public_private_boundary.py`. **Nothing was pushed; nothing leaked.**
  The Constitution and addenda 5, 11, 15, 22 are held privately.
- **`MODEL_BUDGET_DAILY_TOKENS=1500000`** is set in `.env` (gitignored) on the
  owner's authority. The guard still exists; do not remove it.

## Constraints that must not be violated

These have each been bought with a defect. `SPEC_RECONCILIATION.md` has the story.

1. **Client portfolios are never stored** (§111). No table exists; a tripwire
   fails the suite if a storage module returns. **The tripwires were re-aimed at
   §143** — the originals asked about a `portfolios` table and would have passed
   forever while `client_watchlist` grew a `quantity` column. A client *profile*
   now persists (TQ-98) and the boundary is structural: a closed 16-field
   vocabulary, and **a watchlist entry is a symbol and nothing else.**
2. **The Constitution is not in any store** (§120, corrected by §141). It is
   enforced by tests that fail, never by data that ranks — a store that ranks
   cannot hold something unrankable, and a rule a vote can reach is not a rule.
   **It is not "the owner's, outside the system": it applies to the whole system
   and the owner is part of the system.** One document — addendum 49 is v2.0 of
   the one whose v1 was `JARVIS_CONSTITUTION.md` — and it is **held privately**,
   which `tests/test_public_private_boundary.py` now enforces rather than asks.
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

**TQ-99 — join the personnel record to `agent_id`.** TQ-97 introduced the id
beside `agent_names` rather than under it, so two notions of "the durable agent"
exist. That is the state 47 §5 forbids, held deliberately for one increment; it
should not be held for two.

Or **TQ-101 — the Personal Usher**, which §143 §3 found is already half-built:
`gateway/client_agent.py` has given each client a persistent named representative
since addendum 43 §16. The missing half is conversational, and it is the first
thing here that genuinely needs a model to read text — so the seam where a model
answers has to be in the design from the first line, along with what happens when
none is reachable.

**TQ-106 — the Software Department**, or the six unmet Definition-of-Done items
at §150 §7. The one worth carrying: **`metrics.open_at_end` is re-aimed and has
not been forced to fire** under a run that genuinely ends with a pending
cross-check. Re-aimed is not proven (§136's distinction).

**TQ-101 is frozen** by addendum 53 §7.9 until TQ-100 is answered — a
specification now, not a recommendation. And 53 §7.9's warning about the Gateway
becoming a personality host **had already happened**: `gateway/client_agent.py`
stores voice and visual, which §109 puts on the backend's side (§150 §4).

**Read §149 §4 before writing a query.** Three defects in two days were the same
shape: a literal written by hand into SQL where nothing checks it corresponds to
anything — `'answered'` (never written), `'open'` (not in the vocabulary), and a
join on the one column that cannot differ. All three passed every test. When a
query filters on a literal, use the constant; when there is no constant, ask why
the vocabulary has no single definition.

**Read §147 before trusting anything in §146.** TQ-104 found that its own
premise was false: grading was already independent, and
`compliance.self_evaluated` compared two fields that are one identity by
construction — so it flagged every grade, could never return false, and was cited
in the charter as an enforcement mechanism. The appeal machinery's subject model
was inverted for the same reason and is corrected.

**TQ-100 stays first among the unanswered**: *what refuses a persona that crosses
the line — a function or a paragraph?* It comes before any persona code.

Smaller alternatives: **TQ-92** (read the cooperation the organization already
records) or **TQ-28** (a real known defect: the database-isolation guard trips
after a backend has run).

## Working rhythm

Assimilate verbatim → reconcile against the *addenda* and not the build (§111) →
queue → one increment → suite green → **mutation-test with attribution** → run it
and look → record a `SPEC_RECONCILIATION.md` § → update the queue and
`JARVIS.md` → commit.

A green suite is not evidence. Every real defect in this project came from
starting the thing and looking at it.
