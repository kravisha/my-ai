# The Learning Engine

**Specifications:** Krish, 2026-09-21 — Document 1 (*Master Functional
Specification*) and Document 2 (*Completion, Demonstration and User-Acceptance
Expectations*).
**Status:** built, integrated, 85 tests. Awaiting Krish's own acceptance test.

---

## 1. The decision everything rests on

**A learned skill is a `Recipe`: a declarative specification executed by a fixed
interpreter — not generated Python.**

Document 2 §3's own worked example asks for a capability that runs *"without
relying on an external LLM"* and is *"a reusable deterministic capability"*. A
recipe is both: it really executes, it really is deterministic, and running it
costs zero tokens.

What a recipe is **not** is arbitrary code, and three things already in this
repository made that the right call rather than a timid one:

| | Why generated code was the wrong answer |
|---|---|
| `backend/engineering.py` §8 | Its ladder puts code last and says an engineer that reaches it *"names the gap and stops"*. A learning engine writing Python would cross a documented architectural boundary on its own initiative. |
| `app/initiative.py` | `HARM_WIDENS_ITS_OWN_AUTHORITY` refuses self-granted authority at every boldness setting. Code Jarvis wrote and then ran is that harm wearing a feature's clothes. |
| Addendum 46 §2 | *Stable machinery, evolving data.* A recipe versions, diffs, reverts and is readable by a person — which makes Document 1 §24's rollback requirement a `SELECT` rather than a mechanism. |

**Composing a recipe is real work.** The first exercise maps network connections
to owning processes. Getting there requires discovering that `/proc/net/tcp`
skips a header, that its addresses are **little-endian** hex (`0100007F` is
`127.0.0.1`, not `1.0.0.127`), that the state column is a hex enum rather than a
name, that the join key is a socket inode found across thousands of `/proc/*/fd`
symlinks, and that the process name is a separate per-row file read. Every one is
found by being wrong first. That is the loop.

---

## 2. What is where

| Module | Responsibility | Document 1 § |
|---|---|---|
| `app/learning/objective.py` | vague ability → learnable objective; decomposition; inventory | §5–§8 |
| `app/learning/research.py` | questions, source trust, provenance, confirmation debt | §9–§11 |
| `app/learning/recipe.py` | the skill representation, 17 primitives, 12 transforms, the interpreter | — |
| `app/learning/sandbox.py` | where practice happens, and the two allow-lists | §13 |
| `app/learning/practice.py` | attempt → observe → diagnose → revise; 10 failure classes | §14–§17 |
| `app/learning/mastery.py` | the 10 states, computed from evidence | §22 |
| `app/learning/memory.py` | lessons, and meta-learning across episodes | §25, §26 |
| `app/learning/store.py` | six tables in `learning.db` | — |
| `app/learning/engine.py` | the lifecycle, and the plain-language narration | §3, §12, §20–§23 |
| `gateway/tools.py` | eleven conversational tools | Document 2 §8 |

**Reused rather than rebuilt**, per Document 1 §30: capability-gap and boundary
detection (`app/capability_gaps.py`, `app/boundaries.py`), the escalation policy
(`app/capability.py`), the cost ledger (`app/model_budget.py`,
`app/model_calls.py`), the reversibility gate (`app/initiative.py`), the
competency vocabulary (`backend/curriculum.py`), and the four registries that
answer *"what can I already do"*.

---

## 3. The five things Jarvis cannot do

This is the part worth reviewing. A subsystem that reports on its own progress
has an obvious failure mode, and Document 2 §10 names it exactly.

1. **He cannot claim a skill is learned.** `mastery.state_of()` is a pure
   function from recorded evidence to a state. There is no setter — no
   `mark_mastered`, no `set_state` — and a test asserts no such function exists.
2. **He cannot pass a gate he did not run.** Held-out cases are a separate state
   transition, not one more test file, because a suite mixing them cannot tell
   fitting from learning.
3. **He cannot register his own skill.** `register_learned_skill` without
   `krish_accepted` is classified as `HARM_WIDENS_ITS_OWN_AUTHORITY` and refused
   at every boldness setting. Evidence alone stops at `awaiting_user_feedback`.
4. **He cannot extend his own reach.** The 17 primitives, the 15 readable path
   patterns and the 15 runnable programs are fixed in code. A skill that needs
   more is a boundary proposal.
5. **He cannot rest on an assertion.** Every finding records its source and starts
   unconfirmed; it becomes knowledge only when a test that depended on it passed.
   Outstanding debt is reported.

---

## 4. The sandbox, and the holes a probe found

Two allow-lists plus a deny-list, all fixed in `app/learning/sandbox.py`. No
shell — commands run as `argv` — no network, a temporary directory that is
deleted, and bounds on time and output size.

**Every command listed is read-only, and that is the selection rule.** Not "low
risk": each program reports state and has no mode that changes any. No package
manager, no editor, no `wmic`, and above all **no interpreter** — a recipe able to
run `python` would be a recipe able to do anything, which would make the whole
declarative design pointless.

The first security probe of this module found three real holes, and each is now a
regression test:

| Hole | Why it existed | Fix |
|---|---|---|
| `fnmatch`'s `*` crosses `/` | so `/proc/net/*` matched `/proc/net/../../etc/passwd` | segment-aware matcher; `*` is confined to one path segment |
| `/proc/net` is a symlink | resolving first turned `/proc/net/tcp` into `/proc/<pid>/net/tcp`, so the declared pattern stopped matching | match the normalised path, then check the resolved one too (except under `/proc`, where symlinks pointing out are the point) |
| `/proc/*/environ` | holds every API key on the machine, and one wrong wildcard would have exposed it | an explicit `DENIED_PATTERNS` list checked after the allow-list |

---

## 5. Diagnosis costs nothing, by construction

Document 1 §17: *"Jarvis must not immediately request help from an expensive
external model."* The way to guarantee that is for the first diagnosis to need no
model at all. `practice.diagnose()` classifies from the recipe's own step trace
into ten classes, and returns the cheapest rung of §17's ladder that could fix it.

The rule that earns its place:

> **A step whose `rows_in` was positive and `rows_out` was zero is the failure,
> even when the recipe reported success.**

That is the bug this loop hits most — a filter comparing against the wrong
literal, or a `derive` naming a field that is not there. The final answer is
merely *empty*, which reads as "nothing to report" rather than "step 8 is
broken", and a model asked to explain an empty list will invent a plausible
reason. The trace knows.

---

## 6. What is honestly missing

Stated here rather than discovered later.

- **No web access.** Six of Document 1 §10's ten source tiers need to fetch a
  document and nothing in this repository can. `research.unavailable_sources()`
  records all six with the reason. What remains is the repository, its docs, and
  **empirical probing of the machine** — which sits *above* all ten, because
  §11's own words are that testing tells you what actually happens.
- **No local model.** Every model call goes to Kimi. So "learn to stop using an
  LLM for this" currently means *deterministic* replacement only. That is real,
  and it is half of what the specification implies.
- **No scheduler.** The Gateway runs when Krish speaks. Learning is driven by
  conversation; there is no background loop, so Document 1 §28's continuous
  operation is the policy without the clock.
- **Meta-learning has one episode.** `memory.meta_report()` refuses to generalise
  below two and says so. It will have something to say after the second skill.

---

## 7. Running it

The conversational path is Document 2 §8's conversation; the tools are
`explain_how_i_learn`, `what_to_learn_next`, `begin_learning`, `plan_learning`,
`record_learning_finding`, `propose_skill_recipe`, `test_skill`,
`learning_status`, `demonstrate_skill`, `record_skill_feedback`,
`register_learned_skill`, `use_learned_skill`.

```python
from app.learning import default_engine, explain_how_i_learn, candidates
explain_how_i_learn()          # generated from the implementation
candidates()                   # ranked, with the evidence behind each
default_engine().status(slug)  # state, what is missing, evidence
default_engine().narrate(slug) # the same thing in sentences
```

`learning.db` holds the store (`LEARNING_DB_PATH` moves it) and is gitignored —
it is what this machine has learned, not what the code is.

---

## Related

- `tests/test_learning.py` — 85 tests, including Document 2 §12's fourteen
  conditions as an explicit checklist
- `docs/INITIATIVE.md` — the reversibility and harm floor this sits inside
- `docs/CONFIDENCE.md` — why there is no confidence mechanism to learn against yet
- `AI-CONSTITUTION.md` — "Take risks and challenge boundaries"
