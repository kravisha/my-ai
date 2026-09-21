"""The DBA Agent: the guardian and operator of persistent system information.

Krish's specification of 2026-09-21. Jarvis coordinates; the DBA manages
persistent information; the database remains the source of truth.

## The one decision this package is shaped by

**The integrity rules are code, and the model is never in the path of a write.**

§36 says it plainly - *"The LLM should not be the mechanism that guarantees
database integrity"* - and §35 wants deterministic golden tests over core
operations. So every rule in this package that can decide a write is a pure
function over the request and the stored rows: validation, permissions,
duplicate detection, conflict evaluation, and above all the ask-back. A model
may translate Krish's English into a structured request before it arrives here,
and may translate a structured result back into a sentence afterwards
(§43) - but between those two points nothing consults a model, because a
subsystem whose integrity depends on a model being in a good mood has no
integrity to speak of.

That is not a new position for this repository. `app/model_routing.py` refuses
to let a prompt decide routing; `app/learning/recipe.py` makes a learned skill
data rather than generated code; `app/initiative.py` decides harm before it
reads its own configuration. This is the same rule applied to the thing that
outlives every conversation.

## Two rules that outrank every other sentence here

**§44, never-silent-failure.** The DBA must never report success unless the
requested persistent change actually succeeded. So `changed` is *computed from
what the database did*, never set by the code that hoped it would happen - the
same discipline `app/learning/mastery.py` uses for a skill's state, and for the
same reason: a field a caller can assert is a field that will eventually be
asserted wrongly.

**§45, never-guess.** If uncertain, ask. If conflicting, reconcile or ask. If
unauthorized, refuse. If the database is unavailable, report failure. If the
record cannot be uniquely identified, ask. Every one of those five is a refusal
to proceed, and none of them is a judgement call made in the moment.

## What this package deliberately does not do

**It does not seize the two databases that already exist.** §2.3 makes the
database the source of truth; it does not say this agent must take over
`financial_intelligence.db` and `gateway.db` on its first day. Those are live
stores behind two running services, and moving them behind a new agent is a
migration, not a milestone - §46 puts that kind of work in a later phase. The
DBA owns `dba.db`, governs everything placed in it, and the existing two stay
where they are until moving one is its own piece of work with its own tests.
That is stated here rather than discovered later, because the difference
between "the DBA governs persistent information" and "the DBA governs the
information it has been given" is exactly the kind of gap that reads as a lie
in six months.

**It is not a general-purpose assistant** (§37). It is excellent at persistent
information, integrity, retrieval, validation, history, permissions,
reconciliation and clarification. Jarvis remains the orchestrator.

## What it reuses rather than rebuilds

`backend/db.py` is §5.2's abstraction, already written, and its own docstring
anticipated this exact use: *"reusable by any future persistence need ...
without becoming a dumping ground for unrelated concerns."* It brings WAL mode,
busy-timeout handling, `Contended`, and `transaction()` - which is §5.3.
`backend/migrations.py` is §5.7, with sequential steps, a version written by the
runner only after validation, a pre-upgrade backup and a dry-run mode. Writing a
second connection layer or a second migration engine next to those would have
been the kind of duplication this system's own review process exists to catch.
"""
