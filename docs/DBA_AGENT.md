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

- ~~**§25 backup and §26 restore.**~~ **Built** — see §8 below.
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

## 5b. It can now design capabilities of its own

The expectations document of the same date asks for more than this: an agent
that reasons from a task sentence to a data model, builds the API, tests it,
and learns from having done it. That is built, and it is documented in
**`docs/DBA_AGENT_DEVELOPMENT.md`**.

What changed here: a published capability's type is adopted at runtime, so a
new schema becomes a working API without an edit to this repository; and a
capability's own `grants` are enforced on top of the global policy, so an agent
needs both.

---

## 8. Backup and restore (§25, §26)

> *"A backup is not considered valid until restoration has been tested."*

That line decides the design. **Taking a backup restores it** — into a
throwaway database, integrity-checked, with its row counts compared table by
table against the source — before it is recorded as good. `current()` returns
only a verified backup, so recency alone never makes one eligible.

### Four things it gets right on purpose

**It is not a file copy.** These databases run in WAL mode, so the bytes in
the `.db` file are not the database. The gap is not subtle: with five rows
written, a file copy of the `.db` alone **does not contain the table at all**,
while `Database.backup_to` — SQLite's online backup API — has everything.
That is the first test in the file.

**The catalogue does not live in the database it protects.** Each backup has a
JSON manifest beside it and the catalogue is built by scanning the directory. A
record of your backups stored inside the database you are restoring is a record
you have lost at the moment you need it. A test deletes the database entirely
and asserts the catalogue still answers.

**Restoring backs up the current state first**, as a `pre_restore` backup — so
a restore that was a mistake is itself undoable. A test restores, then restores
the safety copy, and finds the "lost" row again.

**The last verified backup is never pruned**, whatever `keep` says. The case it
exists for is every recent backup silently failing verification while retention
removes the only good one.

### Restoring, and its four guards

`administer` only · an explicit `confirmed` (the refusal names the recovery
point, so whoever confirms has been told what they are giving up) · a verified
backup unless overridden aloud · and the current state backed up first.

Two defects the restore test found in this implementation:

| | |
|---|---|
| `shutil.copy2` **truncates the destination in place**, so a connection open across the restore watched its database become a half-written file and got a disk I/O error. | Now written beside it and `os.replace`d — atomic. The open connection keeps the old inode, unlinked but alive, and finishes safely. |
| Nothing checked whether another process was mid-write. | `BEGIN IMMEDIATE` before the swap; if it cannot take the lock the restore is refused, naming step 1 of the procedure. That makes "stop writers first" a check rather than a hope. |

### What a review found after all of that passed

Eight more, and the first two are the shape worth remembering: **the safety net
was breaking the recovery path.**

| Defect | Why it mattered |
|---|---|
| The pre-restore safety backup ended in `prune()`, which deleted **the backup being restored** once the new entry pushed it past `keep`. | Restoring the oldest copy destroyed it and then failed for its absence. `take(protect=…)` now exempts it. |
| A restore from a **corrupt live database** died inside its own mandatory safety backup with an uncaught sqlite3 error — failing in exactly the situation a restore exists for. | A proper backup of a corrupt database is impossible; a byte copy is not, and is better evidence than nothing. It is written as `UNRESTORABLE-raw-copy-*` and deliberately given **no manifest**, so nothing can later mistake it for a backup. |

The rest: row counts were read *before* the copy, so any concurrent write made
a perfectly good backup verify as FAILED (they are now read from the snapshot,
and drift is recorded rather than punished); `due()` asked for the newest
*verified* backup, so a failing backup became an unbounded series of them;
retention counted every entry against `keep`, so failures evicted the good
copies — it now counts restorable ones; a `backup:` section written as a list
was silently replaced by defaults, in the module that promises to refuse rather
than default; and two smaller ones about the write-lock check and the swap
order.

Each is a regression test, and each was run against the unfixed code. One did
not fail there and is labelled as such rather than kept as decoration.

### What Windows CI found, on the platform Krish runs

The suite was green on Linux and **red on Windows**, with three restore tests
failing `os.replace` → *Access is denied*. Two distinct causes, and the first
is not in this feature at all:

| | |
|---|---|
| **`backend/db.py` leaked a handle on a failed open.** `sqlite3.connect` succeeds on any file — it does not read it — so a corrupt file got a live connection and then raised on the first PRAGMA, leaving that connection open until the garbage collector happened to run. | On posix, a leaked descriptor. On Windows, a **held lock** — so a restore could not replace the corrupt database it was recovering from. A recovery blocked by the damage it was recovering from. Every caller of `Database` had this; backup is just where it showed. |
| **Windows cannot replace a file any process has open**, full stop — unlike posix, where the rename is atomic and the old inode survives for existing readers. | The restore now **refuses** with a message naming the cause, rather than falling back to the in-place overwrite. That overwrite is what gave an open connection a half-written database in the first place, and quietly taking the unsafe path on one platform is how a restore becomes the incident. |

There is now a **posix-runnable proxy** for the Windows constraint: a test that
asserts the restore holds *no open connection* at the moment it swaps the file.
A restore that held one would pass on Linux and fail on Windows, which is
precisely what happened and cost a seventeen-minute CI run to discover. Its
first version counted closed connections too and failed against correct code —
a closed connection is still an object and holds no handle.

### What a review found in the scheduler itself

Nine, and the first is the one worth carrying forward: **the observability was
blind to the failure it was added to catch.**

`run_all_if_due` catches every per-store error and returns them inside its
result — so the `except` wrapped around it never fired, `failures` stayed `0`
for ever, and the `backup_scheduler` health check built to notice failing
backups would have reported healthy while every one of them failed. A green
light wired to nothing.

The rest, each now a regression test:

- `_last_backup` mixed a dba-scoped `current()` with an all-store
  `catalogue()`, so with no DBA backup it reported a **gateway** backup as the
  DBA's own — `status: verified` and `verified: False` in the same object.
- `stop()` cleared the thread handle even when the join timed out, so a later
  `start()` could run **two schedulers at once**: duplicate backups, and one
  thread's `prune()` able to unlink a file the other was hashing.
- Backing up another service's database opened it **read-write** and issued
  `PRAGMA journal_mode=WAL` — a write to its header. "Backing up is a read"
  was a claim, not a fact. That finding is now moot: the DBA no longer touches
  another system's database at all, and the read-only open was removed with
  its only caller rather than left as machinery nothing uses.
- The scheduler-pass endpoint audited every run as a success, checking a
  top-level key its own result never contains.
- `/health` re-scanned and re-parsed every manifest six times per request.
- A blanket `except` hid real corruption in the DBA's own store behind
  `schema_version: 0`.

And a flake the clock caught rather than the review: three scheduler tests
called `check_once()` and asserted a backup appeared, which is only true past
`backup.hour`. They passed all afternoon and failed the moment the date rolled
past midnight — a test that would have gone off at 3am on somebody else's
machine. The fixture pins the hour now.

### One honest note about a guard

`_replace` also unlinks the `-wal`/`-shm` sidecars. **No test could be made to
require it** — in every case constructed, including one where the checkpoint is
forced to fail, closing the probe connection already causes SQLite to delete
the log. The code says so where it is, and the test asserts the *outcome* (no
stale log survives a restore) rather than pretending to pin that line. A test
that cannot fail is worse than no test.

### Running it

| | |
|---|---|
| `python -m dba.backup --if-due` | what a cron entry or timer calls |
| `python -m dba.backup --take` / `--list` / `--verify ID` | by hand |
| `POST /backups`, `/backups/run-if-due`, `/backups/{id}/verify`, `/backups/{id}/restore` | over HTTP, operator credential only |
| `config/dba.yaml` | where backups go, how many are kept, the hour, the free-space floor |

**The DBA takes its own backups.** Starting the service starts a scheduler
thread; stopping it stops the thread. Nothing else has to be installed on the
machine.

> *"This should be done by the DBA who keeps everything backed up and safe."*
> — Krish

He is right, and the first version was wrong in a way worth recording: it left
scheduling to a cron entry somebody had to install, and said so honestly.
Honest and wrong. An agent whose responsibility is that persistent information
is safe, and which needs someone else to remember to run it, is not keeping
anything safe — it is a tool that describes a backup system.

It is a thread rather than an async task because `take` blocks on SQLite pages
and file hashing, and doing that on the event loop would stall every request.
It wakes every fifteen minutes and **acts rarely**: `due` is idempotent through
the catalogue, so a machine that runs all day gets exactly one backup, and a
machine asleep at 02:00 gets one at 09:15 when it wakes. A failing backup never
stops the loop — a DBA that stopped serving requests because it could not back
itself up would have turned a backup problem into an outage.

`DBA_AUTOBACKUP=0` turns it off, and `state()` then says so in words rather
than reporting a scheduler that merely isn't there. The test suite sets it off:
a thread taking backups underneath a test counting them is nondeterminism
nobody asked for.

`GET /backups` answers §26's documentation questions from what is actually on
disk. `GET /backups/scheduler` answers the one this system most needed and did
not have: **is anything actually taking backups?** A backup system with no
scheduler running is one where every existing backup quietly gets older, and
nothing else in the report would say so.

### One store, on purpose

I briefly took "everything" to mean all three databases and had the DBA back
up `gateway.db` and `financial_intelligence.db` as well, reasoning that
backing a database up is only a read. Krish's correction:

> *"we are building three separate systems for separate purposes and only
> eventually they will be merged. For now they evolve separately for
> simplicity."*

Which answers a question the read/write distinction does not reach. **The cost
was never the write — there was none. It was the coupling.** This module would
have had to know where two other systems keep their files, what their
databases are called and which of their tables matter, and every one of those
is a thing that breaks quietly when the other system evolves. Three systems
able to change shape without consulting each other is the property being
protected, and it is worth more right now than a second copy of a database its
own system is responsible for.

When they merge, what gets backed up across all three is **Jarvis's** call —
it is the orchestrator, and that is a coordination question rather than a
database one.

`STORES` keeps its registry shape rather than collapsing to a constant,
because "for now just one" is a statement about now. The scheduler loops over
the registry, `run_all_if_due` tolerates one store failing without stopping
the others, and retention groups by store — all dormant with one, all kept
because the bug each prevents was found the hard way while there were three.

### Still not built

**An encrypted secondary location** (§25 says *eventually*) — there is no
second location configured and nothing is encrypted at rest, so every backup
is a readable copy of the database sitting beside it. **The other two
systems** — not backed up here, on purpose, per the section above. Both are
reported by `describe()` under `not_implemented` rather than left out, the
second one naming Jarvis as whose decision it becomes.

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
