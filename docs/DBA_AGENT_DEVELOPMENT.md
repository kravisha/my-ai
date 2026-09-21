# The DBA Agent as a data developer

Krish's *DBA Agent — Expectations, Goals & Responsibilities v1.0* (2026-09-21).
The requirements specification asked for a database agent; this asks for a
**data-development department**: an agent that reasons from a task sentence to
a data model, builds the API for it, tests what it built, and learns from
having done it.

`docs/DBA_AGENT.md` covers the agent itself. This covers what it can now build.

---

## 1. What Krish decided, and what follows from it

| Question | Decision | What it changed |
|---|---|---|
| §9 "create data-access code" vs. this repo's rule that an agent may not write and run its own code | *"the agent seeking this service will seek to use the API provided by the DBA, and therefore the DBA is in charge of creating the APIs"* | The deliverable is **a real, named, versioned API per capability**. What the DBA writes to make that true is a declaration, not a `.py` file. A client cannot tell the difference; the difference is that this can be reviewed as a diff, rolled back with a `SELECT`, and cannot reach anything its declaration does not name. |
| §31's four autonomy stages | **Stage 2** — the DBA proposes, Krish accepts | `permissions.POLICY` does not give the DBA `administer`, and `registry.publish` requires it. Structural, not procedural: there is no flag to flip, and granting is not an operation the DBA has. |
| §4 "all persistent information goes through the DBA" | New state does; `financial_intelligence.db` and `gateway.db` stay where they are | Migrating a live store is its own milestone with its own tests. |
| §16's Tamil | Jarvis should be able to answer in Tamil generally | Delivered for the DBA's own explanations. The wider Jarvis-wide work is named, scoped separately, and **not pretended to be done**. |

---

## 2. The flow

```
requirement ("Create a persistent task handoff system…")
   → advice from past designs          experience.advice_for
   → design, or questions              design.design
   → draft recorded                    registry.save_draft
   → its own tests, actually run       selfcheck.run_tests
   → the twelve pre-publish checks     selfcheck.self_check
   → staged, with the evidence         registry.stage
   → [ Krish accepts ]                 develop.publish
   → serving, documented, audited      routes, apispec
```

Every step is a module; `develop.py` is the order and the evidence carried
between them. Every attempt is recorded — **including the ones that asked**,
because those are what `advice_for` turns into a question asked up front next
time.

---

## 3. Reasoning from a task to a data model (§8)

`patterns.py` holds five archetypes — `handoff_queue`, `message_stream`,
`agent_state`, `event_log`, `catalogue` — each a claim that a class of data
problem has a known good shape, and each carrying the answers §8 demands for
its class.

Trigger words are **weighted**: "work" and "record" appear in almost every
requirement while "mailbox" and "handoff" appear in exactly one kind, and a
flat count let two weak words outvote one decisive one. A weak best score or a
near-tie is **not a coin toss** — `match` reports it is unsure and the designer
asks (§19's *unclear entity definition*).

`Design.reasoning` answers all twelve of §8's questions in words, attached to
the design. A design that cannot say why it has its shape is unreviewable, and
§30's correction loop needs something to correct.

Different sentences produce genuinely different schemas. An `event_log`
declares **no update operation**, so `/api/v1/<name>/update` is a **404** —
that is the claim the archetype makes about itself, expressed as the absence of
a path rather than as a rejected request.

---

## 4. The eight things it will not decide (§19)

Each is a test, and each asserts that **nothing was built**. A DBA that asks
the question and designs the table anyway has not asked anything.

unclear entity definition · conflicting requirements · unknown ownership ·
unclear retention · ambiguous identity · uncertain relationship · unsafe
deletion · insufficient permission information

Two are worth naming:

- **"Nobody said how long" is not `keep_forever`.** §8 asks what should
  eventually expire. A table that grows until somebody notices is what the
  silent default produces, so it is a question.
- **It will not invent a grant.** A capability published with a guessed
  permission is a data surface somebody can reach that nobody decided they
  could.

---

## 5. It tests what it builds (§27, §28)

`selfcheck.run_tests` runs **fifteen cases against a real `DBAgent` and a real
database** — creating, reading, updating, colliding, being refused, being
rolled back, being told the store is unreachable. Not a review of the
declaration.

The database is a throwaway: a capability that is not published yet must not be
able to write to the store other agents read. It is published *there*, exercised,
and the directory is deleted. Nothing about the live store changes and the
evidence is still real.

`selfcheck.self_check` then asks §28's twelve questions. A capability that
fails either is never offered — "staged" means the DBA has done its part, and
offering a failing design would put the decision in front of Krish with the
work half done.

---

## 6. What the DBA's own generated tests found

The battery was written, run, and **immediately failed on a real defect**:

> `permissions_are_enforced` — `dba`, who is granted nothing, got `success`

A capability declared `grants` and **nothing read them**. Any agent holding
global `create` could write to a capability that had granted it nothing.
Permissions defined and not enforced are worse than permissions not defined,
because the declaration tells anybody reading it otherwise.

Now both must allow it: the global policy is a ceiling on what an agent could
ever do, and the capability's grant is the specific allowance for this data.
`None` (a built-in, no grant table) and `{}` (granted nobody anything) are
deliberately different, because conflating them fails open.

---

## 7. What two reviews found after the tests passed

The first review's ten findings are in `docs/DBA_AGENT.md`. The second, against
this milestone, found ten more. The two worth naming:

| Defect | Why it mattered |
|---|---|
| **Publishing v2 turned every v1 caller's path into a 404.** `call_capability` served `registry.current`. | The exact failure §26 exists to prevent, arriving from the code meant to prevent it. Both versions now serve until the old one is retired. |
| **A design race could serve `schema_mismatch` for a capability that was serving fine.** The adopted types are process-global and `selfcheck` repoints them at a throwaway database; a reader thread in that window lost. Worse, `grants_for` could return `None` there — which **fails open**. | The window is now held under a lock for the whole battery. |

The rest: `link`/`unlink` bypassed capability grants entirely (a relationship is
a write to *both* records, and is checked as one now); a `deletable` capability
published a `delete` endpoint nobody was granted; a capability could be named
after a built-in type, which would make every subsequent request raise; the
catalogue routes were unauthenticated and `?version=` served drafts; rejecting
a design destroyed the test evidence §30 says to keep; `init_schema` stamped
every old database as current, so the version column was the one thing that
could no longer be trusted; no episode was ever written for a publication, so
`meta_report`'s "reached publication" claim could never fire; and the stored
`fingerprint` was never read, so asking twice built it twice.

Every one is now a regression test, and **each was run against the unfixed code
to confirm it fails there.** One did not — it asserted "somebody holds delete"
where the point was that the *writers* do, and the owner grant satisfied it. It
was strengthened until it failed.

---

## 8. §33's twelve goals, and §34's demonstration

Both are single tests in `tests/test_dba_development.py`, so a reader can see
all of it answered in one place. §34 is one test rather than fifteen because
the claim is that the **flow** works — a step that passes in isolation while
the one before it left the wrong state behind has demonstrated nothing.

The demonstration, over HTTP: Jarvis asks → the DBA asks back about retention
and permissions → answered, it designs `task_handoff`, builds it, runs fifteen
tests → Jarvis is refused publication (403) and Krish accepts → Agent A creates
a work request at `/api/v1/task_handoff/create` → Agent B finds what is waiting
for it → Agent B marks it done → the audit trail shows both agents, both
actions, the reason and what changed → the DBA has stored what it learned.

---

## 9. Still honest about what is not built

- ~~**Backup and restore**~~ — **built**; see `docs/DBA_AGENT.md` §8. `health`
  now reports the real current backup and `diagnose`'s `backup_age` check
  fails only for real reasons: nothing taken, nothing verified, or nothing
  recent.
- **Semantic search / pgvector** (§18) — Phase 3.
- **§12's full Jarvis state** — the `agent_state` type exists and survives a
  restart; what Jarvis chooses to persist through it is Jarvis's next piece of
  work, not the DBA's.
- **Tamil beyond the DBA** — §43's explanations are bilingual here. Everywhere
  else is a separate scoped milestone. A shape with no Tamil rendering returns
  the **English sentence unchanged** rather than half-translating, because the
  sentence is the part a person actually reads.
- **Stages 3 and 4 of §31** — the DBA is at stage 2 by Krish's decision, and
  moving is a decision rather than a drift.
