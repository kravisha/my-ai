# The DBA Agent

Krish's *DBA Agent / Database Engine Requirements & Specification v1.0*
(2026-09-21), Phase 1 and §47's minimum viable agent.

> JARVIS coordinates. DBA manages persistent information. The database remains
> the source of truth.

---

## 1. The decision the whole package is shaped by

**The integrity rules are code, and no model is in the path of a write.**

§36 says it: *"The LLM should not be the mechanism that guarantees database
integrity."* So validation, permissions, duplicate detection, the ask-back and
the audit event are all pure functions of the request and the stored rows. A
model may turn Krish's sentence into a structured request before it arrives,
and turn the structured result back into a sentence afterwards (§43). Between
those two points nothing consults a model.

That is not a new position here. `app/model_routing.py` refuses to let a prompt
decide routing; `app/learning/recipe.py` makes a learned skill data rather than
generated code. This is the same rule applied to the thing that outlives every
conversation.

It is also what makes §35's golden tests possible: same state, same request,
same answer, with no fixture pinning a model's mood.

---

## 2. The two rules that outrank everything else

| Rule | Where it is enforced |
|---|---|
| **§44, never-silent-failure.** Never report success unless the change actually succeeded. | `Response.changed` is computed from what the database did and the dataclass is frozen. `records.apply_changes` returns only fields that actually moved. A replayed idempotent request reports `changed: false`, because *that call* changed nothing. |
| **§45, never-guess.** If uncertain ask; if conflicting reconcile or ask; if unauthorized refuse; if unavailable report failure; if not uniquely identifiable ask. | `askback.Resolution.only` raises rather than picking one of several. Every question is built before a transaction opens. |

---

## 3. What is built

| § | Requirement | Where |
|---|---|---|
| 2.1 | Its own agent and service, not embedded in Jarvis | `dba/`, `dba/main.py`, and a test asserting nothing in `gateway/` or `backend/` imports it |
| 4 | Ask-back, all five examples | `dba/askback.py` |
| 5.2–5.7 | Abstraction, transactions, ids, timestamps, soft delete, schema version | `dba/store.py`, `dba/ids.py`, `dba/records.py` |
| 6 | Entities, relationships, metadata | `dba/entities.py`, `dba/records.py` |
| 8 | The logical operations | `dba/operations.py` |
| 9 | Raw SQL confined | only `dba/store.py` and `dba/records.py` name a column |
| 10 | Validation | `dba/validate.py` |
| 11 | Duplicate detection, never auto-merge | `dba/duplicates.py` |
| 13 | Audit trail, append-oriented | `dba/audit.py` |
| 14, 15, 16 | Permissions, classification, minimum disclosure | `dba/permissions.py`, `records.summary` |
| 22 | Idempotency | `dba/agent.py` |
| 23, 42 | Structured errors and response contract | `dba/contract.py` |
| 24 | Fail safely | `DBAgent.handle` catches and never returns a success |
| 28, 29 | Observability and diagnostics | `dba/health.py` |
| 30 | Dry run | every writing operation |
| 31 | Bulk, atomic or partial | `DBAgent.handle_many` |
| 43 | Plain-language explanation | `dba/explain.py`, generated from the response |
| 47, 48 | MVP and the six acceptance tests | `tests/test_dba.py` |

---

## 4. What is deliberately not built, and why

This repository's standing rule — stated in `backend/migrations.py` — is that
machinery with no user does not get built. Each of these is a later phase in
§46, and each is **reported as absent** rather than omitted, because an absent
measurement reads as a clean one:

- **§25 backup and §26 restore.** `health()` returns `last_backup: None` with a
  reason, and `diagnose()` fails its `backup_age` check on purpose. A system
  that reported a backup age of zero would be worse than one that says it has
  never taken one.
- **§7 agent mailbox, §41 event history, §18 vectors.** No tables. Phases 2–3.
- **§12 conflict resolution.** `reconcile` returns `unknown_action` naming §12
  and §46 rather than a stub that appears to reconcile something. The
  provenance and confidence columns it will need are already on `entities`,
  because columns are cheaper now than a migration onto live rows later.

**The DBA does not take over the two databases that already exist.**
`financial_intelligence.db` and `gateway.db` stay where they are. §2.3 makes
the database the source of truth; it does not say this agent must seize two
live stores on its first day, and moving one is a migration with its own tests
rather than a milestone. Stated here because the gap between *"the DBA governs
persistent information"* and *"the DBA governs the information it has been
given"* is exactly the kind of thing that reads as a lie in six months.

---

## 5. §49's open decisions, as taken

| Open question | Decision | Why |
|---|---|---|
| API transport | HTTP on port 8200, FastAPI | Two services here already work this way, and `agents/coo.py`, `panel/app.py`, `monitor/app.py` are all separate processes speaking HTTP. A bus is a new dependency and a new failure mode for one assistant talking to one database. A local socket would not survive the first time Krish wants this from his phone — which has already happened once in this project. |
| Cross-request transactions | **Not offered.** Atomicity is a batch (`/batch`), and `begin/commit/rollback_transaction` are its delimiters, refused standalone with that message. | A transaction held open across requests needs server-side session state, pins a connection, and locks the database when a caller dies mid-unit. |
| Permission model | Per-agent permission sets in `dba/permissions.POLICY`, checked per request, fail-closed on an unknown agent. | The shape `gateway/roles.py` already established and tested here. |
| Physical schema | Five tables; entity *types* are declarative data, not tables. | §6.3 wants important fields explicit and the rest in metadata. Per-type tables make a schema change per type; pure EAV makes every query a self-join, which is §27's dead end. |
| Identity of a caller | `X-DBA-Agent` + `X-DBA-Token` against `DBA_TOKEN_<AGENT>`; the body's `requested_by` must agree. | `requested_by` alone is a claim, and §14's whole point is that the DBA enforces rather than trusts. An agent with no configured token cannot call at all. |
| SQLite → PostgreSQL | Deferred, and the seam is `backend/db.py`. | Its own docstring: a Postgres backend means a new class implementing that same small interface, not touching every call site. |

---

## 5a. What a review found after all the tests passed

Ten defects, none caught by the 81 tests written alongside the code. Each is
now a regression test that fails without its fix. The two worth naming are the
package's own foundational rules, broken by the machinery meant to uphold them:

| Defect | Why it mattered |
|---|---|
| **A dry run burned the idempotency key.** `_remember` stored the preview's `committed: false` result under the request id, so the real write that followed with the same id was *replayed* as a success and never happened. | §44's exact lie, arriving through §22 — the one mechanism whose whole job is to make a repeat harmless. Preview-then-commit is the sequence §30 exists to support. |
| **A metadata criterion was filtered over a bounded window.** With one match inside it and one outside, `resolve` reported `exactly_one` and the update wrote to whichever row it happened to see. | §45's silent choice, through the code that exists to prevent it. Now filtered in SQL with `json_extract`; where that is unavailable a filled window raises `IncompleteScan` rather than answering from a partial view. |

The other eight: a batch let an exception escape where a single request
returned a structured error; a bulk archive wrote one audit row with a NULL id
instead of one per record; an archived record could never be hard-deleted;
`diagnose` crashed on the damaged store it existed to describe; `data_json
LIKE` matched JSON *keys*, so searching "notes" returned every record that has
a notes field; a create copied confidential values verbatim into the audit
table its own docstring said summaries exist to avoid; `resolve` read `limit`
as a field value; and a phone number of six spaces validated, stored, and could
never be matched again.

The pattern, which is the part worth carrying forward: **the dangerous defect
was not in a feature, it was in the thing wrapped around every feature.** Both
critical findings were in `dba/agent.py` and `dba/records.py` — the two modules
every operation passes through — and both broke a rule the package states in
its own first paragraph.

---

## 6. Running it

```
uvicorn dba.main:app --port 8200
export DBA_TOKEN_JARVIS=...        # nothing can call until a token exists
export DBA_DB_PATH=...             # optional; defaults to ./dba.db
```

| Route | |
|---|---|
| `POST /request` | one structured request, one structured response |
| `POST /batch` | a unit of work that lands or rolls back together |
| `GET /health` | §28; unauthenticated, carries counts and versions, no record data |
| `GET /diagnostics` | §29; authenticated, names identifiers |
| `GET /policy` | who may do what |
| `GET /types` | the declared entity types |

A clarification comes back as **HTTP 200** with
`status: clarification_required`. It is not a failed request — the DBA
understood it and is asking a question — and a 4xx would put it in the bucket
where clients retry or raise, which is the opposite of answering.

---

## 7. The shape of an exchange

```
POST /request
{ "action": "update", "entity_type": "person",
  "criteria": {"name": "John Smith"}, "data": {"phone": "+1 555 0100"} }

200 OK
{ "status": "clarification_required",
  "changed": false,
  "clarification": {
    "reason": "multiple_matching_records",
    "question": "2 person records match name. Which one do you mean?",
    "options": [ {"id": "person-1037e8...", "name": "John Smith", "email": "j.smith@example.com"},
                 {"id": "person-3ecc11...", "name": "John Smith", "email": "john.s@example.com"} ],
    "pending_action": "Update phone on person" },
  "explanation": "I have not changed anything. 2 person records match name. ..." }
```

Nothing was written. The options carry the field that tells the two apart and
not the rest of either record (§16).
