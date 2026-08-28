"""The Software Engineering Department's intake and work record
(TASK_QUEUE TQ-83; addendum 46 §7-§13, §21; docs/SPEC_RECONCILIATION.md §119, §137).

Addendum 46's terminal claim is *Jarvis develops Jarvis*. This is the first
increment of it, and most of the design is about being honest concerning how
little of that is true yet.

## What the department can actually do today

**Implement a directive as governed data, or say that it cannot.**

Addendum 46 §8 orders the ways to satisfy a directive - knowledge, then policy,
then configuration, then composition, and only then code - and calls the last one
a last resort. Levels 1 through 4 are all *data* changes, and TQ-82 built the
store for them. So the department's first real capability is the one §8 says
should be preferred anyway, and it needs no ability to write code.

What it cannot do is write code. An engineer that reached level 5 records that
the directive needs a mechanism the architecture lacks, and stops. That is not a
failure: §8 calls level 5 the case where *"the existing architecture genuinely
lacks the mechanism required"*, and naming it is the correct outcome.

## The trap §119 named, and the metric written against it

> *"A department measured on 'did you avoid a code change?' will report Level 1-4
> solutions for problems that need Level 5, and the metric will improve while the
> system does not."*

So a work record carries **what the directive asked for** and whether that
outcome was achieved - never merely which level was used. `assessed_level` is
descriptive; `outcome` is the judgement. A department that recorded only the
first would score perfectly by refusing to ever admit a code change is needed,
which is TQ-80's defect in a new costume.

## The producer is not the approver

Addendum 46 §11: *"The agent that produces a change should not be the sole
authority that approves the same change."* Enforced structurally - `approve`
refuses when the approver is the author - rather than left to a convention, for
the reason every other refusal here is structural.

## Where directives come from, and the gap that is declared rather than built around

§119 adjudicated that Software Engineering receives directives **through
Evolution**, not on a parallel channel from Parliament, because 46 §13 draws
*"Approved Directive -> Software Department intake"* with nothing between and that
gap is where a bypass appears by accident.

**The Department of Evolution does not exist** (addendum 30, unbuilt). So intake
requires an enacted resolution - authority requires provenance, the same rule
`governed_knowledge` applies - and the relay Evolution is supposed to perform is
absent. That is a declared deviation from §119, not a quiet one: `TQ-95` queues
the relay, and every directive carries `arrived_via` naming the shortcut in the
row itself, so nothing can later mistake this for the intended architecture.

Sits below `fi_db`, so it must not import it.
"""

from __future__ import annotations

import json

from backend import governed_knowledge, parliament
from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS engineering_directives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    -- What was asked for, and the outcome it is meant to produce. Kept apart
    -- deliberately: the second is what the work is judged against.
    title TEXT NOT NULL,
    intended_outcome TEXT NOT NULL,
    -- The enacted resolution authorising it. Required: an engineering directive
    -- with no authority behind it is somebody's idea, not the organization's.
    resolution_id INTEGER NOT NULL,
    -- What the organization wants to be true, in machine-readable form. The
    -- directive says WHAT; the engineer works out HOW it would be enforced and
    -- whether this architecture can enforce it at all.
    requirement TEXT NOT NULL,
    subject TEXT NOT NULL,
    binds TEXT NOT NULL,
    -- How this reached the department. See the module docstring: today the only
    -- honest value says Evolution's relay does not exist.
    arrived_via TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    claimed_by TEXT
);
CREATE INDEX IF NOT EXISTS engineering_directives_open ON engineering_directives (status, id);

CREATE TABLE IF NOT EXISTS engineering_work (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    directive_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    engineer TEXT NOT NULL,
    -- Addendum 46 §8's ladder. DESCRIPTIVE, never the score: a department
    -- measured on avoiding code change reports levels 1-4 for problems needing 5.
    assessed_level TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    -- What was actually done. NULL until the work is finished.
    proposed_instrument TEXT,
    -- Whether the intended outcome was achieved. This is the judgement.
    outcome TEXT,
    outcome_detail TEXT,
    -- What adopting this would do to the organization: who it binds, what it
    -- would displace, and whether it would be refused. The one piece of
    -- addendum 30 §4's impact analysis this system can honestly perform (§138).
    impact TEXT,
    -- Who approved it, which may never be the engineer that produced it.
    approved_by TEXT,
    approved_at TEXT,
    adopted_instrument_id INTEGER,
    -- Set instead of adopting when the approval goes into a release candidate
    -- rather than straight into force (TQ-96, §139): addendum 46 §16's Version
    -- N+1, accumulating while Version N runs.
    release_change_id INTEGER
);
CREATE INDEX IF NOT EXISTS engineering_work_by_directive ON engineering_work (directive_id);
"""

SCHEMA_VERSION = 1

ROLE = "software_engineer"

# Addendum 46 §8, in order. The index is the level number, so the tuple is the
# one place the ladder lives.
LEVELS = (
    "knowledge",              # 1: add or improve what agents know
    "directive",              # 2: change behaviour through an approved rule
    "configuration",          # 3: thresholds, workflows, permissions, routing
    "composition",            # 4: combine existing capabilities differently
    "code",                   # 5: only when the architecture lacks the mechanism
)
LEVEL_CODE = "code"

# Levels this department can currently deliver. Everything except code, which is
# the honest boundary rather than a temporary one - nothing here writes code.
DELIVERABLE_LEVELS = LEVELS[:-1]

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DELIVERED = "delivered"
STATUS_NEEDS_CODE = "needs_code"
# Approved into a release candidate and not yet in force. Distinct from
# delivered on purpose: a change waiting in Version N+1 has changed nobody's
# behaviour, and calling it delivered would be the department scoring for work
# the organization has not received (§119 §8).
STATUS_STAGED = "staged"
STATUSES = (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_DELIVERED, STATUS_NEEDS_CODE,
            STATUS_STAGED)

OUTCOME_ACHIEVED = "achieved"
OUTCOME_NEEDS_CODE = "needs_code"
OUTCOMES = (OUTCOME_ACHIEVED, OUTCOME_NEEDS_CODE)

# Derived states `delivered_outcomes` reports. They are computed from what is in
# force right now and never stored, for the reason given there.
STANDING_IN_FORCE = "in_force"
STANDING_STAGED = "staged"
STANDING_REVERSED = "reversed"
STANDING_SUPERSEDED = "superseded"
STANDING_NOT_DELIVERED = "not_delivered"

# The only honest value today. Named in the row so a later reader cannot mistake
# the current shortcut for the intended architecture (§119, TQ-95).
VIA_RESOLUTION_DIRECTLY = "resolution_directly_no_evolution_relay"
VIA_EVOLUTION = "evolution_relay"
ARRIVAL_ROUTES = (VIA_RESOLUTION_DIRECTLY, VIA_EVOLUTION)


class EngineeringRefused(PermissionError):
    """Work this department will not do, or an approval it will not accept."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def receive(conn: Database, *, title: str, intended_outcome: str, resolution_id: int,
            requirement: dict, subject: str, binds: str = "*",
            arrived_via: str = VIA_RESOLUTION_DIRECTLY) -> int:
    """Take a directive into the department.

    Refuses one with no enacted resolution behind it. **An engineering directive
    with no authority is somebody's idea**, and a department that acted on ideas
    would be the bypass §119 warned about arriving through the intake rather than
    through the design."""
    for name, value in (("title", title), ("intended outcome", intended_outcome)):
        if not (value or "").strip():
            raise EngineeringRefused(f"A directive needs a {name}.")
    if arrived_via not in ARRIVAL_ROUTES:
        raise EngineeringRefused(
            f"unknown arrival route {arrived_via!r}; known are {list(ARRIVAL_ROUTES)}")
    resolution = parliament.get_resolution(conn, resolution_id)
    if resolution is None or resolution["status"] != parliament.STATUS_ENACTED:
        raise EngineeringRefused(
            "An engineering directive needs the enacted resolution that authorised it.")
    if not isinstance(requirement, dict) or not requirement.get("kind"):
        raise EngineeringRefused(
            "A directive states what the organization wants enforced, as a requirement "
            "with a kind. Prose alone is a wish nothing can act on (§126).")
    if not (subject or "").strip():
        raise EngineeringRefused("A directive governs a subject; it needs one.")
    return conn.execute_returning_id(
        "INSERT INTO engineering_directives (received_at, title, intended_outcome,"
        " resolution_id, requirement, subject, binds, arrived_via, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), title.strip(), intended_outcome.strip(), resolution_id,
         json.dumps(requirement), subject.strip().lower(), (binds or "*").strip().lower(),
         arrived_via, STATUS_OPEN))


def assess(directive: dict) -> tuple[str, str]:
    """Which rung of addendum 46 §8's ladder this directive needs, and why.

    **The ladder's question, answered by the registry that already knows it.**
    §8 asks whether the existing architecture has the mechanism required. For an
    obligation, that is exactly `operating_context.UNDERSTOOD_OBLIGATIONS`: a kind
    in it can be enforced by adopting an instrument, and a kind not in it cannot
    be enforced by any amount of governed data.

    That is addendum 46 §40's worked example in miniature - *"Parliament
    determines that agents require secure real-time video, but the platform
    contains no video capability. Changing instructions cannot create a video
    transport."* **An obligation kind nothing understands is a capability gap**,
    and naming it is the correct outcome rather than a failure.

    Deterministic on purpose. A model asked *"could this be data?"* would answer
    plausibly every time, including for the cases where it cannot - and the
    department would report level 2 for problems needing level 5, which is
    exactly what §119 said to write this metric against."""
    from backend import operating_context

    requirement = json.loads(directive["requirement"])
    kind = requirement.get("kind")
    if kind in operating_context.UNDERSTOOD_OBLIGATIONS:
        return "directive", (
            f"The outcome is an obligation of kind {kind!r}, which this system already knows "
            f"how to obey. It can be put in force by adopting an instrument - addendum 46 §8 "
            f"level 2, and no code is required.")
    return LEVEL_CODE, (
        f"The outcome would need an obligation of kind {kind!r}, and nothing in this system "
        f"knows how to obey one. No instrument can create the mechanism, so this is a "
        f"capability gap: addendum 46 §8 level 5. Known kinds are "
        f"{sorted(operating_context.UNDERSTOOD_OBLIGATIONS)}.")


def instrument_for(directive: dict, *, level: str = "organization_policy") -> dict:
    """The instrument that would put this directive in force.

    Composed by the engineer rather than carried by the directive: the directive
    says what the organization wants to be true, and working out how it would be
    enforced - which subject, which level, who it binds - is the engineering."""
    return {
        "subject": directive["subject"],
        "level": level,
        "text": directive["intended_outcome"],
        "binds": directive["binds"],
        "requires": json.loads(directive["requirement"]),
    }


def claim_next(conn: Database, engineer: str) -> dict | None:
    """Take the oldest open directive, atomically.

    Guarded UPDATE rather than read-then-write, for the reason
    `analysis_requests.claim_next` gives: two engineers believing they own the
    same directive would produce two proposals for one decision."""
    for row in conn.fetchall(
            "SELECT * FROM engineering_directives WHERE status = ? ORDER BY id",
            (STATUS_OPEN,)):
        won = conn.execute_returning_rowcount(
            "UPDATE engineering_directives SET status = ?, claimed_by = ?"
            " WHERE id = ? AND status = ?",
            (STATUS_IN_PROGRESS, engineer, row["id"], STATUS_OPEN))
        if won:
            return get_directive(conn, row["id"])
    return None


def record_assessment(conn: Database, directive_id: int, *, engineer: str,
                      level: str, reasoning: str) -> int:
    """The ladder, applied and written down.

    `level` is **descriptive**. It says which rung the engineer judged this to
    need, and it is never the score - §119: a department measured on avoiding a
    code change will report a low rung for a problem that needs the top one."""
    if level not in LEVELS:
        raise EngineeringRefused(f"unknown level {level!r}; addendum 46 §8's are {list(LEVELS)}")
    if not (reasoning or "").strip():
        raise EngineeringRefused(
            "An assessment without its reasoning is a verdict nobody can check.")
    return conn.execute_returning_id(
        "INSERT INTO engineering_work (directive_id, started_at, engineer,"
        " assessed_level, reasoning) VALUES (?, ?, ?, ?, ?)",
        (directive_id, now_iso(), engineer, level, reasoning.strip()))


def propose_instrument(conn: Database, work_id: int, *, instrument: dict) -> None:
    """What the engineer would adopt, held for somebody else to approve.

    Held rather than adopted: addendum 46 §11 says the agent that produces a
    change is not the sole authority that approves it, and the way to make that
    true is for producing and adopting to be different calls made by different
    parties."""
    work = get_work(conn, work_id)
    if work is None:
        raise EngineeringRefused("No such work.")
    if work["assessed_level"] not in DELIVERABLE_LEVELS:
        raise EngineeringRefused(
            f"{work['assessed_level']!r} is not something this department can deliver. "
            f"Record the outcome as {OUTCOME_NEEDS_CODE!r} instead.")
    directive = get_directive(conn, work["directive_id"])
    conn.execute(
        "UPDATE engineering_work SET proposed_instrument = ?, impact = ? WHERE id = ?",
        (json.dumps(instrument), json.dumps(impact_of(conn, directive)), work_id))


def approve(conn: Database, work_id: int, *, approver: str) -> int:
    """Adopt what an engineer proposed, on somebody else's authority.

    **Refuses when the approver is the author.** Structural rather than
    conventional, for the reason every other refusal in this system is: a rule
    that lives only in prose is one a future increment breaks while adding
    something helpful."""
    work = get_work(conn, work_id)
    if work is None or not work["proposed_instrument"]:
        raise EngineeringRefused("There is nothing here to approve.")
    if (approver or "").strip().lower() == work["engineer"].strip().lower():
        raise EngineeringRefused(
            f"{approver} produced this change and cannot also be its only approval "
            f"(addendum 46 §11).")

    directive = get_directive(conn, work["directive_id"])
    proposal = json.loads(work["proposed_instrument"])
    item = governed_knowledge.adopt(
        conn, resolution_id=directive["resolution_id"], adopted_by=approver, **proposal)
    stamp = now_iso()
    conn.execute(
        "UPDATE engineering_work SET approved_by = ?, approved_at = ?,"
        " adopted_instrument_id = ?, outcome = ?, outcome_detail = ? WHERE id = ?",
        (approver, stamp, item, OUTCOME_ACHIEVED,
         f"adopted instrument {item} for {directive['intended_outcome']!r}", work_id))
    conn.execute("UPDATE engineering_directives SET status = ? WHERE id = ?",
                 (STATUS_DELIVERED, work["directive_id"]))
    return item


def record_needs_code(conn: Database, work_id: int, *, detail: str) -> None:
    """The directive needs a mechanism the architecture lacks.

    **Not a failure.** Addendum 46 §8 defines level 5 as exactly this case, and a
    department that could never say it would be the one §119 warned about - always
    reporting a data solution, always scoring well, never changing anything."""
    if not (detail or "").strip():
        raise EngineeringRefused("Saying a directive needs code needs the reason it does.")
    work = get_work(conn, work_id)
    if work is None:
        raise EngineeringRefused("No such work.")
    conn.execute(
        "UPDATE engineering_work SET outcome = ?, outcome_detail = ? WHERE id = ?",
        (OUTCOME_NEEDS_CODE, detail.strip(), work_id))
    conn.execute("UPDATE engineering_directives SET status = ? WHERE id = ?",
                 (STATUS_NEEDS_CODE, work["directive_id"]))


def impact_of(conn: Database, directive: dict) -> dict:
    """What adopting this directive's instrument would do.

    **Addendum 30 §4 asks an Evolution Directive to carry scope, affected
    departments, affected agent classes, training and evaluation criteria, and a
    rollout and rollback plan.** Almost none of that is answerable here: this
    system has no release, no rollback, no certification and no way to derive a
    training requirement from a directive (§138).

    What it *can* answer is who the instrument binds, what it would displace, and
    **whether adopting it would be refused** - which is worth more than it looks.
    Without it, a proposal that `governed_knowledge.adopt` will reject sits in
    the queue looking deliverable until somebody spends an approval on it and
    finds out. Catching at proposal time what would fail at adoption time is the
    impact analysis this architecture actually supports.
    """
    proposed = instrument_for(directive)
    standing = governed_knowledge.effective_item(conn, directive["subject"],
                                                 allow_ambiguous=True)

    roles = [row["role"] for row in conn.fetchall(
        "SELECT DISTINCT role FROM agent_registry ORDER BY role")]
    affected = roles if directive["binds"] == "*" else [directive["binds"]]

    refused = None
    if standing is not None and standing["level"] == proposed["level"]:
        # `adopt` refuses two equal authorities on one subject unless the new one
        # names what it replaces. An engineer proposing into an occupied level
        # has to say so, and today nothing lets a directive express that - so the
        # honest answer is that this proposal cannot be adopted as it stands.
        refused = (
            f"{directive['subject']!r} already has an instrument at {proposed['level']!r} "
            f"(id {standing['id']}). Adopting this would put two equal authorities on one "
            f"subject, which the store refuses.")

    return {
        "binds": directive["binds"],
        "roles_affected": affected,
        # Named rather than counted: "three roles" tells a reviewer nothing about
        # whether the right three.
        "displaces": None if standing is None else {
            "id": standing["id"], "level": standing["level"]},
        "would_be_refused": refused,
        # Stated every time, so a reader never mistakes what this covers for what
        # addendum 30 §4 asks for.
        "not_assessed": [
            "training requirements - nothing derives them from a directive",
            "evaluation and certification criteria - unbuilt",
            "rollout and rollback plan - this system has neither",
        ],
    }


def get_directive(conn: Database, directive_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM engineering_directives WHERE id = ?", (directive_id,))


def get_work(conn: Database, work_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM engineering_work WHERE id = ?", (work_id,))


def open_directives(conn: Database) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM engineering_directives WHERE status = ? ORDER BY id", (STATUS_OPEN,))


def outcomes(conn: Database) -> dict:
    """What the department has actually produced, by outcome.

    **By outcome, never by level.** The level says which rung was used; the
    outcome says whether the thing asked for happened. Reporting the first as a
    score is the failure §119 named before this department existed."""
    counts = {row["outcome"]: row["n"] for row in conn.fetchall(
        "SELECT outcome, COUNT(*) AS n FROM engineering_work WHERE outcome IS NOT NULL"
        " GROUP BY outcome")}
    return {
        "achieved": counts.get(OUTCOME_ACHIEVED, 0),
        "needs_code": counts.get(OUTCOME_NEEDS_CODE, 0),
        "open_directives": len(open_directives(conn)),
        # Named so nobody reads a department that only ever says "needs code" as
        # one that is working, or one that never says it as one that is honest.
        "in_flight": conn.fetchone(
            "SELECT COUNT(*) AS n FROM engineering_work WHERE outcome IS NULL")["n"],
    }


def stage_for_release(conn: Database, work_id: int, *, release_id: int, approver: str) -> int:
    """Approve a proposal into a release candidate instead of straight into force
    (TQ-96; addendum 46 §16; §139).

    The other half of `approve`, and the difference is *when it takes effect*.
    `approve` adopts, and the organization's behaviour changes on the spot;
    this stages, and the change waits in Version N+1 with the rest of a set that
    will stand or fall together.

    **The same independence rule, for the same reason.** Approving into a
    release is still approving (46 §11), so an engineer still cannot be the only
    authority behind their own change.

    **The release's resolution must be the directive's.** A change staged under
    somebody else's authority would be reversible under somebody else's authority
    - and addendum 30 §27's guarantee is precisely that the way back was granted
    by the vote that granted the way forward. Two resolutions in one set is two
    different answers to *who authorised undoing this*."""
    from backend import release as release_module

    work = get_work(conn, work_id)
    if work is None or not work["proposed_instrument"]:
        raise EngineeringRefused("There is nothing here to approve.")
    if work["approved_by"] or work["release_change_id"]:
        raise EngineeringRefused("That work has already been approved.")
    if (approver or "").strip().lower() == work["engineer"].strip().lower():
        raise EngineeringRefused(
            f"{approver} produced this change and cannot also be its only approval "
            f"(addendum 46 §11).")

    directive = get_directive(conn, work["directive_id"])
    candidate = release_module.require(conn, release_id)
    if candidate["resolution_id"] != directive["resolution_id"]:
        raise EngineeringRefused(
            f"Release {release_id} is authorised by resolution "
            f"{candidate['resolution_id']} and this directive by "
            f"{directive['resolution_id']}. A set reversed under one resolution cannot "
            f"contain a change authorised by another.")

    change_id = release_module.stage(
        conn, release_id, instrument=json.loads(work["proposed_instrument"]),
        staged_by=approver.strip())
    conn.execute(
        "UPDATE engineering_work SET approved_by = ?, approved_at = ?, release_change_id = ?"
        " WHERE id = ?",
        (approver.strip(), now_iso(), change_id, work_id))
    conn.execute("UPDATE engineering_directives SET status = ? WHERE id = ?",
                 (STATUS_STAGED, work["directive_id"]))
    return change_id


def delivered_outcomes(conn: Database) -> list[dict]:
    """What each piece of finished work is *currently* worth to the organization.

    **Derived on read, never stored, and that is the whole point.** A work row
    records that an instrument was adopted; it cannot record that the instrument
    was later reversed by a rollback, because nothing would think to come back and
    say so. A department scored on its stored `outcome` would therefore keep
    credit for every change that was rolled back - §119 §8's metric trap in the
    one dimension TQ-96 creates.

    This is the same move `analysis_requests` makes about expiry: **the condition
    is computed when somebody asks, rather than trusted to a sweeper that may not
    have run** (§117). A reversed instrument is a superseded row; asking is one
    query, and forgetting to ask is impossible when asking is the only way to
    read the answer.

    `standing` is the derived truth and `outcome` is what was recorded at the
    time. Both are returned, because they answer different questions and a caller
    that conflated them would be back where this started."""
    rows = []
    for work in conn.fetchall("SELECT * FROM engineering_work ORDER BY id"):
        item_id, standing = work["adopted_instrument_id"], None
        if work["release_change_id"] is not None:
            change = conn.fetchone("SELECT * FROM release_changes WHERE id = ?",
                                   (work["release_change_id"],))
            item_id = None if change is None else change["adopted_item_id"]
            if item_id is None:
                standing = STANDING_STAGED
            elif change["reversed_at"] is not None:
                standing = STANDING_REVERSED
        if standing is None:
            if item_id is None:
                standing = STANDING_NOT_DELIVERED
            else:
                item = governed_knowledge.get_item(conn, item_id)
                standing = (STANDING_IN_FORCE if item and item["superseded_at"] is None
                            else STANDING_SUPERSEDED)
        rows.append({
            "work_id": work["id"],
            "directive_id": work["directive_id"],
            "engineer": work["engineer"],
            "assessed_level": work["assessed_level"],
            "outcome": work["outcome"],
            "instrument_id": item_id,
            "standing": standing,
            "release_change_id": work["release_change_id"],
        })
    return rows
