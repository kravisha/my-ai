"""Releases and rollback over governed data
(TASK_QUEUE TQ-96; addendum 46 §16, §17, §18; addendum 30 §13-§15, §26, §27;
docs/SPEC_RECONCILIATION.md §119, §138, §139).

## What a release is here, because the obvious answer is already taken

Adopting an instrument changes what agents do, immediately, with no deployment
and no restart. So *the moment new behaviour reaches production* is not what
this module provides - `governed_knowledge.adopt` provides it, and anything
here that made a rule wait for a release window would break addendum 46 §2's
central claim.

§139 settled what is left:

> **A release is a named set of governed changes that stand or fall together,
> whose way back is authorized before the way forward is taken.**

Addendum 46 §16's *"Version N keeps running while N+1 is designed, implemented,
tested, and prepared"* maps onto that without strain. **Version N is what is in
force; N+1 is the set staged against it.** TQ-83 already built the accumulating -
`engineering.propose_instrument` holds what an engineer would adopt for somebody
else to approve - and had nowhere to accumulate it to.

## The three things adoption does not do, which are the three this adds

**A boundary.** `adopt` takes one instrument on one subject. Three that only
make sense together are adopted one at a time, and a refusal on the second leaves
the first in force and the third absent - a state nobody proposed, nobody voted
for and nobody designed. `apply` is all or nothing.

**A way back that does not need a vote.** The store supersedes forward only, and
adopting the replacement needs an enacted resolution at the matching level. That
is the right cost for changing your mind and the wrong cost for an incident.
Addendum 30 §27's *"Rollback SHALL be defined before rollout"* is therefore the
mechanism rather than the advice: **the authority to reverse is the authority
already granted for the release**, captured at prepare time, so no second vote
stands between an unhealthy release and the way back.

**A health verdict.** Addendum 46 §18 step 2 is *"release state is marked
unhealthy"*, and until now nothing here marked anything as anything. An
instrument in force and an instrument in force and failing were the same row.

## Health is `unknown`, and it is never `healthy` by default

§118's rule, transferred without modification: **absence of complaint is not
evidence that a release is working.** A release that came back `healthy` because
nobody had objected would be the analyst that stopped asking sources how much
they held, wearing a release manager's coat.

So `health` starts at `unknown` and moves only when somebody records a judgement
with evidence, and **the judge may not be whoever prepared the release** -
addendum 46 §11's independence rule, and §117's reason for keeping ground truth
off the provider interface.

## What this module does not do, and must not

**It does not release code.** `backend/version.py` answers *which code is this?*
by asking git: the organization can observe its code version and cannot choose
it, because nothing in the running system may write to the repository. That is
the same prevention-by-absence that keeps agents out of `docs/` (§122) and the
Constitution out of every table (§120). A `deploy()` here would either not work
or breach that boundary.

What it holds instead is the **record** - the code version at prepare, at apply
and at reversal - so that addendum 30 §26's compatibility checking has facts to
check. This matters most at rollback: **restoring the data under a different code
version is not a return to the last known-good condition**, and a rollback
reporting success without saying so would claim a property it does not have.

**It does not restart anything, and does not need to.** Addendum 46 §18 step 4 is
*"agents reload the previous authorized organizational state"*, and this system
has nothing to reload: `operating_context.for_role` and `.check` read the store
at the point of work, and no agent caches an instrument across a cycle. §119 §5's
constraint - a release must not be built as a restart script - is satisfied by an
architecture that never cached, not by care taken here.

Sits below `fi_db` and above `governed_knowledge`, so it must not import the
first and may import the second.
"""

from __future__ import annotations

import json

from backend import governed_knowledge, parliament, version
from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prepared_at TEXT NOT NULL,
    -- A name a person uses in an incident, and the outcome the set is for.
    name TEXT NOT NULL,
    intent TEXT NOT NULL,
    prepared_by TEXT NOT NULL,
    -- The enacted resolution authorising the whole set. Addendum 30 §27: the
    -- way back is authorised here, at prepare time, because a vote is not
    -- available at the moment a rollback is needed.
    resolution_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'preparing',
    -- NEVER defaults to healthy. See the module docstring.
    health TEXT NOT NULL DEFAULT 'unknown',
    health_judged_by TEXT,
    health_evidence TEXT,
    health_judged_at TEXT,
    applied_at TEXT,
    applied_by TEXT,
    rolled_back_at TEXT,
    rolled_back_by TEXT,
    rollback_reason TEXT,
    -- Observed, never chosen (addendum 30 §26). Three stamps because a rollback
    -- under different code is not a return to the last known-good condition.
    code_version_prepared TEXT NOT NULL,
    code_version_applied TEXT,
    code_version_rolled_back TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS releases_status ON releases (status, id);

CREATE TABLE IF NOT EXISTS release_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    staged_at TEXT NOT NULL,
    staged_by TEXT NOT NULL,
    -- The instrument this would adopt, as `governed_knowledge.adopt` kwargs.
    instrument TEXT NOT NULL,
    -- Addendum 46 §16 steps 2-3, the restoration point: what was in force on
    -- this subject at this level when the release applied. NULL means nothing
    -- was, which reverses to nothing being - a real state, distinct from unknown.
    checkpoint_item_id INTEGER,
    checkpointed INTEGER NOT NULL DEFAULT 0,
    -- What adopting it produced. NULL until applied.
    adopted_item_id INTEGER,
    reversed_at TEXT
);
CREATE INDEX IF NOT EXISTS release_changes_by_release ON release_changes (release_id, id);
"""

SCHEMA_VERSION = 1

STATUS_PREPARING = "preparing"
STATUS_RELEASED = "released"
STATUS_ROLLED_BACK = "rolled_back"
STATUSES = (STATUS_PREPARING, STATUS_RELEASED, STATUS_ROLLED_BACK)

HEALTH_UNKNOWN = "unknown"
HEALTH_HEALTHY = "healthy"
HEALTH_UNHEALTHY = "unhealthy"
# `unknown` is first because it is the default and the honest one. A release
# nobody has judged is not passing; it is unjudged.
HEALTH = (HEALTH_UNKNOWN, HEALTH_HEALTHY, HEALTH_UNHEALTHY)


class ReleaseRefused(PermissionError):
    """A release operation this system will not perform, or an order it will not
    take out of order."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def prepare(conn: Database, *, name: str, intent: str, resolution_id: int,
            prepared_by: str) -> int:
    """Open a release candidate: Version N+1, against a Version N still running.

    **The resolution is required here rather than at apply**, and that is the
    whole of addendum 30 §27. The authority to reverse has to be granted at the
    same time as the authority to change, by the same vote, or it will not exist
    at the moment somebody needs it - and a rollback that had to be voted through
    is not a rollback, it is a second change."""
    for field, value in (("name", name), ("intent", intent),
                         ("preparer", prepared_by)):
        if not (value or "").strip():
            raise ReleaseRefused(f"A release needs a {field}.")
    resolution = parliament.get_resolution(conn, resolution_id)
    if resolution is None or resolution["status"] != parliament.STATUS_ENACTED:
        raise ReleaseRefused(
            "A release needs the enacted resolution that authorised it. Without one there "
            "is nothing to reverse under, so the way back would need a vote it cannot get.")
    return conn.execute_returning_id(
        "INSERT INTO releases (prepared_at, name, intent, prepared_by, resolution_id,"
        " status, health, code_version_prepared) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), name.strip(), intent.strip(), prepared_by.strip(), resolution_id,
         STATUS_PREPARING, HEALTH_UNKNOWN, version.code_version()))


def stage(conn: Database, release_id: int, *, instrument: dict, staged_by: str) -> int:
    """Add one instrument to the candidate. Nothing is in force yet.

    The instrument is the kwargs `governed_knowledge.adopt` takes, minus the two
    this module supplies: the resolution (the release's own) and the adopter
    (whoever applies it). A staged change carrying its own authority would be a
    change that could leave the set."""
    release = require(conn, release_id)
    if release["status"] != STATUS_PREPARING:
        raise ReleaseRefused(
            f"Release {release_id} is {release['status']!r}. A release that has already "
            f"applied is a record, not a candidate - stage into a new one.")
    if not (staged_by or "").strip():
        raise ReleaseRefused("A staged change needs whoever staged it.")
    if not isinstance(instrument, dict) or not instrument.get("subject"):
        raise ReleaseRefused("A staged change is an instrument, and an instrument has a subject.")
    for reserved in ("resolution_id", "adopted_by"):
        if reserved in instrument:
            raise ReleaseRefused(
                f"A staged change may not carry its own {reserved!r}: the release's resolution "
                f"authorises the whole set, and a change with its own authority is one that "
                f"could survive the set being reversed.")
    return conn.execute_returning_id(
        "INSERT INTO release_changes (release_id, staged_at, staged_by, instrument)"
        " VALUES (?, ?, ?, ?)",
        (release_id, now_iso(), staged_by.strip(), json.dumps(instrument)))


def apply(conn: Database, release_id: int, *, applied_by: str) -> list[int]:
    """Addendum 46 §16 steps 2-5: checkpoint, then adopt the set, atomically.

    **Any refusal means nothing is adopted.** A partially applied release is the
    state nobody designed - some of a change in force, the rest absent, and no
    vote behind that combination. `consolidation`'s rule about a partial
    portfolio (§117), applied to governance.

    The checkpoint is taken *inside* the same transaction and before the first
    adoption, because a restoration point captured after the first change
    restores to a state that already contains it."""
    release = require(conn, release_id)
    if release["status"] != STATUS_PREPARING:
        raise ReleaseRefused(f"Release {release_id} is already {release['status']!r}.")
    if not (applied_by or "").strip():
        raise ReleaseRefused("Applying a release needs whoever applied it.")
    staged = changes(conn, release_id)
    if not staged:
        raise ReleaseRefused(
            "A release with nothing staged changes nothing. Recording it would put a "
            "release in the history that no rollback could mean anything about.")

    adopted: list[int] = []
    with conn.transaction():
        for change in staged:
            instrument = json.loads(change["instrument"])
            standing = governed_knowledge.active_at_level(
                conn, instrument["subject"], instrument["level"])
            conn.execute(
                "UPDATE release_changes SET checkpoint_item_id = ?, checkpointed = 1"
                " WHERE id = ?",
                (None if standing is None else standing["id"], change["id"]))
        for change in staged:
            instrument = json.loads(change["instrument"])
            item = governed_knowledge.adopt(
                conn, resolution_id=release["resolution_id"], adopted_by=applied_by.strip(),
                **instrument)
            conn.execute("UPDATE release_changes SET adopted_item_id = ? WHERE id = ?",
                         (item, change["id"]))
            adopted.append(item)
        conn.execute(
            "UPDATE releases SET status = ?, applied_at = ?, applied_by = ?,"
            " code_version_applied = ? WHERE id = ?",
            (STATUS_RELEASED, now_iso(), applied_by.strip(), version.code_version(),
             release_id))
    return adopted


def judge(conn: Database, release_id: int, *, health: str, judged_by: str,
          evidence: str) -> None:
    """Record whether the release is performing within tolerance (addendum 46 §18 step 2).

    **The judge may not be the preparer.** Addendum 46 §11's independence rule,
    and the same reason `truth_for` is kept off the provider Protocol (§117): a
    party able to grade its own work passes by grading.

    Evidence is required for both verdicts, not only the bad one. A `healthy`
    with nothing behind it is the absence-of-complaint reading this project has
    already been bitten by (§118)."""
    release = require(conn, release_id)
    if release["status"] == STATUS_PREPARING:
        raise ReleaseRefused(
            "Nothing is in force yet, so there is nothing to judge the health of.")
    if health not in HEALTH or health == HEALTH_UNKNOWN:
        raise ReleaseRefused(
            f"A judgement is {HEALTH_HEALTHY!r} or {HEALTH_UNHEALTHY!r}. "
            f"{HEALTH_UNKNOWN!r} is what a release is before anybody looked, and it is "
            f"not something anybody can conclude.")
    if not (evidence or "").strip():
        raise ReleaseRefused(
            "A health verdict needs the evidence for it. Without it, 'healthy' means "
            "nobody complained, which is not the same thing (§118).")
    if (judged_by or "").strip().lower() == release["prepared_by"].strip().lower():
        raise ReleaseRefused(
            f"{judged_by} prepared this release and cannot also be the only judgement on "
            f"whether it worked (addendum 46 §11).")
    conn.execute(
        "UPDATE releases SET health = ?, health_judged_by = ?, health_evidence = ?,"
        " health_judged_at = ? WHERE id = ?",
        (health, judged_by.strip(), evidence.strip(), now_iso(), release_id))


def roll_back(conn: Database, release_id: int, *, rolled_back_by: str, reason: str) -> dict:
    """Addendum 46 §18 step 3: restore the checkpoint, under authority already granted.

    **Requires the release to have been marked unhealthy first**, which is §18's
    own step order made mechanical rather than procedural. Marking it takes one
    call and some evidence; skipping it would leave a rollback with no record of
    what it was for, and §18 step 6 wants the failure preserved for analysis.

    **No new resolution.** That is the point of the whole module: the release's
    resolution authorised this at prepare time, so an incident does not have to
    carry a vote through Parliament before it can stop the bleeding.

    Reversal *restores*; it does not re-adopt. See `governed_knowledge.reverse`
    for why that distinction is load-bearing and how it stays visible."""
    release = require(conn, release_id)
    if release["status"] != STATUS_RELEASED:
        raise ReleaseRefused(
            f"Release {release_id} is {release['status']!r}, and only a released one has "
            f"anything in force to reverse.")
    if release["health"] != HEALTH_UNHEALTHY:
        raise ReleaseRefused(
            f"Release {release_id} is marked {release['health']!r}. Addendum 46 §18 marks a "
            f"release unhealthy before restoring it, so the record says what the rollback "
            f"was for - a rollback with no verdict behind it preserves no failure evidence.")
    if not (reason or "").strip():
        raise ReleaseRefused("A rollback needs its reason; §18 step 6 preserves the failure.")
    if not (rolled_back_by or "").strip():
        raise ReleaseRefused("A rollback needs whoever performed it.")

    restored, withdrawn = [], []
    stamp = now_iso()
    with conn.transaction():
        # Reversed newest-first: a later change in the set may have replaced an
        # earlier one, and restoring the earlier before withdrawing the later
        # would put two equal authorities on one subject mid-rollback.
        for change in reversed(changes(conn, release_id)):
            if change["adopted_item_id"] is None or change["reversed_at"] is not None:
                continue
            governed_knowledge.reverse(
                conn, adopted_id=change["adopted_item_id"],
                restore_id=change["checkpoint_item_id"])
            conn.execute("UPDATE release_changes SET reversed_at = ? WHERE id = ?",
                         (stamp, change["id"]))
            if change["checkpoint_item_id"] is None:
                withdrawn.append(change["adopted_item_id"])
            else:
                restored.append(change["checkpoint_item_id"])
        conn.execute(
            "UPDATE releases SET status = ?, rolled_back_at = ?, rolled_back_by = ?,"
            " rollback_reason = ?, code_version_rolled_back = ? WHERE id = ?",
            (STATUS_ROLLED_BACK, stamp, rolled_back_by.strip(), reason.strip(),
             version.code_version(), release_id))
    return {
        "restored": restored,
        # Named separately from restored: a change that replaced nothing reverses
        # to nothing being in force on that subject, which is a real state and
        # not the same as having put something back.
        "withdrawn": withdrawn,
        **code_version_note(require(conn, release_id)),
    }


def code_version_note(release: dict) -> dict:
    """Whether the code moved under this release, and what that means for a rollback.

    Addendum 30 §26's compatibility checking, at the one moment it decides
    something. **Restoring the data under a different code version is not a
    return to the last known-good condition**, and this system cannot fix that -
    it does not choose its code version (§139 §3). So it is reported, with the
    versions named, and the caller is told plainly what the data restore did and
    did not achieve."""
    applied = release["code_version_applied"]
    reversed_under = release["code_version_rolled_back"]
    if applied is None or reversed_under is None:
        return {"code_version_matched": None}
    if applied == reversed_under:
        return {"code_version_matched": True}
    return {
        "code_version_matched": False,
        "code_version_note": (
            f"This release was applied under code {applied} and reversed under "
            f"{reversed_under}. The governed data is back to what it was; the system running "
            f"it is not. Nothing here can restore code, so this is reported rather than "
            f"corrected (SPEC_RECONCILIATION 139)."),
    }


def postmortem(conn: Database, release_id: int) -> dict:
    """Addendum 46 §18 step 7, composed from the record rather than written into it.

    §18 asks for a postmortem and for lessons to enter organizational knowledge.
    The first is every fact this release already carries, assembled - and
    assembling it beats storing a narrative, which would be a second copy that
    can disagree with the rows.

    The second is **deliberately not done**. The organization model's declared
    gap 2 is that lessons written when a lens goes stale are never read back;
    adding a second writer into a store with no reader would grow that gap while
    looking like it closed one. Named here rather than silently skipped."""
    release = require(conn, release_id)
    staged = changes(conn, release_id)
    return {
        "release": release["name"],
        "intent": release["intent"],
        "status": release["status"],
        "health": release["health"],
        "prepared_by": release["prepared_by"],
        "judged_by": release["health_judged_by"],
        "evidence": release["health_evidence"],
        "rollback_reason": release["rollback_reason"],
        "changes": [
            {"subject": json.loads(change["instrument"])["subject"],
             "adopted": change["adopted_item_id"],
             "restored_to": change["checkpoint_item_id"],
             "reversed_at": change["reversed_at"]}
            for change in staged],
        # 46 §18: nothing about rollback erases history. The failed instruments
        # are still rows in `governed_items`, superseded and readable, which is
        # what makes this composable at all.
        "failed_instruments_preserved": [
            change["adopted_item_id"] for change in staged
            if change["adopted_item_id"] is not None and change["reversed_at"] is not None],
        **code_version_note(release),
        "not_recorded": [
            "lessons into organizational knowledge - nothing reads that store back "
            "(declared gap 2), so a second writer would grow the gap",
            "acceptance criteria - health is a judgement with evidence, not a "
            "threshold anything computes (addendum 30 section 16 is unbuilt)",
        ],
    }


def get(conn: Database, release_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM releases WHERE id = ?", (release_id,))


def require(conn: Database, release_id: int) -> dict:
    release = get(conn, release_id)
    if release is None:
        raise ReleaseRefused(f"No release {release_id}.")
    return release


def changes(conn: Database, release_id: int) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM release_changes WHERE release_id = ? ORDER BY id", (release_id,))


def summary(conn: Database) -> dict:
    """What a surface needs to show that a release is in trouble.

    Unhealthy releases are named rather than counted, for the reason the Speaker
    names conflicting subjects: a count tells a reader something is wrong and not
    which thing, and the next thing they do is query the database themselves -
    which is the fallback §124 removed."""
    rows = conn.fetchall("SELECT * FROM releases ORDER BY id")
    return {
        "releases": len(rows),
        "in_force": [row["name"] for row in rows if row["status"] == STATUS_RELEASED],
        # The two states that need somebody to act, kept apart. An unhealthy
        # release still in force is an incident; a rolled-back one is history.
        "unhealthy_in_force": [
            row["name"] for row in rows
            if row["status"] == STATUS_RELEASED and row["health"] == HEALTH_UNHEALTHY],
        # A released change nobody has judged. Not a failure and not a pass -
        # `unknown` is what this project writes where a plausible default would
        # otherwise go (§100, §104, §118, §132).
        "unjudged_in_force": [
            row["name"] for row in rows
            if row["status"] == STATUS_RELEASED and row["health"] == HEALTH_UNKNOWN],
        "rolled_back": [row["name"] for row in rows if row["status"] == STATUS_ROLLED_BACK],
        "preparing": [row["name"] for row in rows if row["status"] == STATUS_PREPARING],
    }
