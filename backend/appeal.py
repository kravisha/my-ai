"""The right to appeal an unfavourable ruling
(TASK_QUEUE TQ-102; owner direction 2026-08-28; addendum 46 §11;
docs/SPEC_RECONCILIATION.md §144 §4, §145).

Owner direction, 2026-08-28: the right to appeal an unfavorable ruling is one of
two examples of the *"undeniable and inalienable"* kind of rule that belongs in
the Constitution. The other, the right to vote, is built.

`backend/charter.py` has declared this one **owed and unenforced** since it was
written - *"a settled matter can be appealed... no adjudicator exists, and the
owner is both first and last instance, which is not an appeal."* This module is
that entry, discharged.

## Two of the charter's three unenforced protections were the same missing thing

**You cannot appeal a ruling you were never told about.**

The charter's *"an agent is told what is found about it"* and the organization
model's declared gap 1 - *a producing agent never learns how its own report was
judged* - are the prerequisite, not a neighbouring nicety. Building the appeal
alone would have produced a right nobody could exercise, which is the shape this
project keeps recording: a rule that exists and changes nothing.

So `rulings_about` comes first, and it is **derived rather than delivered**. No
notification table, no write that somebody has to remember to make: a grade is a
ruling about whoever produced the analysis, and the join already exists -
`compliance.self_evaluated` has used it since it was written. A notification a
sweeper writes is a notification that can silently stop.

## Who adjudicates, which was the hard part

Three answers were available and all three are bad:

- **A standing adjudicator appointed by vote** is removable by the same vote, so
  an appeal becomes reviewable by whoever is currently winning.
- **Parliament as the appellate court** makes the electorate the reviewer, and the
  electorate contains whoever made the ruling.
- **The owner** is what happens today, and the charter already says that is not an
  appeal.

The answer this architecture already had: **there is no court.** The charter's
requirement is precisely *"reviewed by someone other than whoever made it"*, and
that is satisfied by a **peer of the author** - same role, different instance -
chosen by neither party. This system implements that independence three times
already: the producer is not the approver (`engineering.approve`), the producer is
not the grader (`compliance.self_evaluated`), and the preparer is not the health
judge (`release.judge`). An appeal is the fourth, not a new kind of thing.

That removes the appointment problem entirely. **Nothing is appointed, so nothing
can be removed**, and 46 §10's *work determines staffing* is the same rule that
gave the Portfolio Analyst `on_demand` instead of a new agent class (§117).

## What happens when there is no peer, and why it is not a denial

This organization runs one of each role. **So most of the time there is nobody
eligible**, and that is a real finding about the workforce rather than a defect
here.

An appeal with no eligible adjudicator stays **open and unheard**. It is never
denied, never expired, never closed by a timeout - the same construction
`parliament.escalate` uses, which has no `resolve`, no `dismiss` and no expiry.
**An appeal that lapses is a denial wearing a timeout's clothes**, and it would be
indistinguishable from one that was heard and refused.

`summary` therefore reports two numbers and not one. Zero appeals filed is an
organization nobody disagrees with; zero heard against forty filed is a right that
exists on paper. **One number cannot tell those apart and two can** - §130's
lesson, in the place where the failure would be least visible.

## The right is not gateable by ordinary law

The owner placed this right in the Constitution, where changing it needs
two-thirds (§142, §144). This module therefore reads **no governed data at all**:
there is no instrument that can disable an appeal, no obligation kind that gates
one, and a test asserts the imports that would allow it are absent.

What an ordinary law *may* eventually govern is procedure - who hears what, in
what time. That distinction is the owner's own: durable rules in the Constitution,
situational ones in ordinary law.

**When the genesis Constitution is written, this right is one of the provisions it
should carry.** Nothing here can put it there; the text is the owner's (§142).

Sits below `fi_db`, so it must not import it - and it must not import
`governed_knowledge` or `operating_context` either, for the reason above.
"""

from __future__ import annotations

from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS appeals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filed_at TEXT NOT NULL,
    -- What is being appealed. A closed vocabulary: a kind nothing can produce
    -- would be a right over rulings that do not exist.
    ruling_kind TEXT NOT NULL,
    ruling_id INTEGER NOT NULL,
    -- Who the ruling was about, and who therefore may appeal it. Nobody else can:
    -- an appeal filed on another agent's behalf is an opinion.
    appellant TEXT NOT NULL,
    -- Who made the ruling. Recorded at filing rather than looked up at hearing,
    -- so the author cannot become eligible by a later edit.
    author TEXT NOT NULL,
    grounds TEXT NOT NULL,
    -- NULL until somebody eligible hears it. **There is no other terminal state.**
    -- No expiry, no dismissal, no auto-denial - see the module docstring.
    heard_by TEXT,
    heard_at TEXT,
    outcome TEXT,
    rationale TEXT,
    UNIQUE (ruling_kind, ruling_id)
);
CREATE INDEX IF NOT EXISTS appeals_unheard ON appeals (heard_at, id);
"""

SCHEMA_VERSION = 1

# A report and who filed it, across both tables. A judged report moves to the
# archive, and an agent's right to know how its work was graded must survive the
# work being finished - which is the defect §132 found in the governance metric,
# arriving here for the same reason.
_REPORTS = ("SELECT id, producer_identity FROM discovery_reports"
            " UNION ALL SELECT id, producer_identity FROM discovery_reports_completed")

# What can be appealed. One kind today, and the list is closed: a ruling kind
# nothing produces would be a right over nothing.
KIND_GRADE = "grade"
RULING_KINDS = (KIND_GRADE,)

OUTCOME_UPHELD = "upheld"
OUTCOME_OVERTURNED = "overturned"
OUTCOMES = (OUTCOME_UPHELD, OUTCOME_OVERTURNED)


class AppealRefused(PermissionError):
    """An appeal this system will not file, or a hearing it will not accept."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def rulings_about(conn: Database, identity: str) -> list[dict]:
    """Every unfavourable ruling made about this agent's work.

    **Derived, never delivered.** The charter owes an agent knowledge of what is
    found about it, and a notification table would be a write somebody has to
    remember to make - and a sweeper that stops looks exactly like an
    organization with nothing to report.

    ## Whose ruling this is, corrected at TQ-104

    A grade is a ruling about **the upstream report**, and the agent it judges is
    whoever filed that report - Explorer or Speculator. `agents/analysis.py`'s own
    prompt says so: *"a grade of the upstream report."*

    TQ-102 wired this to `analysis_results.producer_identity`, which is the agent
    that *wrote* the grade, not the one it was about. So `rulings_about` returned
    an agent its own rulings about other agents' work, and every conclusion drawn
    from that was inverted (§147).

    Declared gap 1 says *a producing agent never learns how its own **report** was
    judged* - it named the right party all along, and this now answers it."""
    identity = (identity or "").strip()
    if not identity:
        return []
    return [
        {
            "kind": KIND_GRADE,
            "id": row["id"],
            "author": row["grader_identity"],
            "decided_at": row["created_at"],
            "rationale": row["rationale"],
            "overall_score": row["overall_score"],
            "about": row["analysis_result_id"],
            # Whether this agent has already contested it. Derived here so a
            # caller listing its rulings never has to make a second query to
            # find out which are still open to it.
            "appealed": row["appeal_id"] is not None,
        }
        for row in conn.fetchall(
            "SELECT g.id, g.grader_identity, g.created_at, g.rationale, g.overall_score,"
            " g.report_id AS analysis_result_id, ap.id AS appeal_id"
            " FROM grades g"
            " JOIN (" + _REPORTS + ") r ON r.id = g.report_id"
            " LEFT JOIN appeals ap ON ap.ruling_kind = ? AND ap.ruling_id = g.id"
            " WHERE r.producer_identity = ?"
            " ORDER BY g.id",
            (KIND_GRADE, identity))
    ]


def _ruling(conn: Database, kind: str, ruling_id: int) -> dict | None:
    if kind != KIND_GRADE:
        return None
    return conn.fetchone(
        "SELECT g.id, g.grader_identity AS author, r.producer_identity AS subject"
        " FROM grades g JOIN (" + _REPORTS + ") r ON r.id = g.report_id"
        " WHERE g.id = ?", (ruling_id,))


def file_appeal(conn: Database, *, ruling_kind: str, ruling_id: int,
                appellant: str, grounds: str) -> int:
    """Contest a ruling made about your own work.

    **Filing always succeeds for the subject.** The right is not conditional on
    an adjudicator existing, on the grounds being good, or on anybody agreeing -
    a right available only when it is convenient to grant is a permission.

    Three refusals, and none of them is discretionary:

    - **Not the subject.** An appeal filed on another agent's behalf is an
      opinion, and this is the only place the distinction can be enforced.
    - **Already appealed.** One instance per ruling. There is no appeal of an
      appeal, because a second review needs a hierarchy this organization does not
      have - and an agent that could appeal until it won would be relitigating
      rather than appealing.
    - **No such ruling.** Refused plainly: it says nothing about what exists that
      the caller did not already know, since the caller named it.
    """
    if ruling_kind not in RULING_KINDS:
        raise AppealRefused(
            f"unknown ruling kind {ruling_kind!r}; appealable kinds are {list(RULING_KINDS)}")
    if not (grounds or "").strip():
        raise AppealRefused(
            "An appeal states why the ruling is wrong. Without grounds there is nothing "
            "for an adjudicator to review, and a review of nothing would uphold everything.")
    appellant = (appellant or "").strip()
    if not appellant:
        raise AppealRefused("An appeal needs whoever is making it.")

    ruling = _ruling(conn, ruling_kind, ruling_id)
    if ruling is None:
        raise AppealRefused(f"There is no {ruling_kind} {ruling_id}.")
    if ruling["subject"] != appellant:
        raise AppealRefused(
            f"{ruling_kind} {ruling_id} was not a ruling about {appellant}. An appeal filed "
            f"on another agent's behalf is an opinion.")
    if conn.fetchone("SELECT id FROM appeals WHERE ruling_kind = ? AND ruling_id = ?",
                     (ruling_kind, ruling_id)) is not None:
        raise AppealRefused(
            f"{ruling_kind} {ruling_id} has already been appealed. One instance per ruling: "
            f"there is no appeal of an appeal, and an agent that could appeal until it won "
            f"would be relitigating.")

    return conn.execute_returning_id(
        "INSERT INTO appeals (filed_at, ruling_kind, ruling_id, appellant, author, grounds)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (now_iso(), ruling_kind, ruling_id, appellant, ruling["author"], grounds.strip()))


def eligible_adjudicators(conn: Database, appeal_id: int) -> list[str]:
    """Who may hear this appeal: a peer of the author, and neither party.

    **A peer rather than a court.** Someone who can make this kind of ruling is
    someone holding the author's role; anyone else would be reviewing work they
    have no standing to judge. Nothing is appointed here, so nothing can be
    removed - which is the whole reason this shape was chosen over a standing
    adjudicator (see the module docstring).

    Returns `[]` honestly when the workforce has nobody. This organization runs
    one of each role, so that is the ordinary case rather than the exception."""
    row = require(conn, appeal_id)
    author_role = conn.fetchone(
        "SELECT role FROM agent_registry WHERE identity = ?", (row["author"],))
    if author_role is None:
        # The author is not in the registry - a retired or unknown identity. No
        # peer can be established, and guessing a role would be inventing the
        # adjudicator's standing.
        return []
    return [candidate["identity"] for candidate in conn.fetchall(
        "SELECT identity FROM agent_registry WHERE role = ? AND identity NOT IN (?, ?)"
        " ORDER BY identity",
        (author_role["role"], row["author"], row["appellant"]))]


def hear(conn: Database, appeal_id: int, *, adjudicator: str, outcome: str,
         rationale: str) -> None:
    """Review a contested ruling and say what you found.

    **The author may not hear it**, which is the charter's entire requirement and
    is enforced structurally rather than by convention. **Nor may the appellant**,
    for the same reason in the other direction.

    A rationale is required, on `record_disposition`'s rule: a ruling that does
    not say why is an assertion, and an appeal upheld without one is
    indistinguishable from an appeal ignored.

    **Nothing is erased.** The grade stays exactly as it was; overturning records
    that it was overturned beside it. Addendum 46 §18's rule about rollback -
    a reversed decision stays part of organizational memory - applies to a
    reversed judgement for the same reason."""
    row = require(conn, appeal_id)
    if row["heard_at"] is not None:
        raise AppealRefused(
            f"Appeal {appeal_id} was already heard by {row['heard_by']}. Hearing it again "
            f"would be a second instance, which this organization does not have.")
    adjudicator = (adjudicator or "").strip()
    if not adjudicator:
        raise AppealRefused("A hearing needs whoever heard it.")
    if adjudicator == row["author"]:
        raise AppealRefused(
            f"{adjudicator} made this ruling and cannot review it. The charter's requirement "
            f"is that a settled matter is reviewed by someone other than whoever made it.")
    if adjudicator == row["appellant"]:
        raise AppealRefused(
            f"{adjudicator} filed this appeal and cannot also decide it.")
    if outcome not in OUTCOMES:
        raise AppealRefused(f"unknown outcome {outcome!r}; known are {list(OUTCOMES)}")
    if not (rationale or "").strip():
        raise AppealRefused(
            "A hearing states its reasoning. An appeal upheld without one is "
            "indistinguishable from an appeal ignored.")

    conn.execute(
        "UPDATE appeals SET heard_by = ?, heard_at = ?, outcome = ?, rationale = ?"
        " WHERE id = ? AND heard_at IS NULL",
        (adjudicator, now_iso(), outcome, rationale.strip(), appeal_id))


def get(conn: Database, appeal_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM appeals WHERE id = ?", (appeal_id,))


def require(conn: Database, appeal_id: int) -> dict:
    row = get(conn, appeal_id)
    if row is None:
        raise AppealRefused(f"No appeal {appeal_id}.")
    return row


def unheard(conn: Database) -> list[dict]:
    """Appeals nobody has heard, oldest first.

    **There is no other way for an appeal to stay open**, because there is no way
    for one to close except by being heard. No expiry, no dismissal, no
    auto-denial: an appeal that lapsed would be a denial nobody had to make, and
    it would be indistinguishable from one that was heard and refused."""
    return conn.fetchall("SELECT * FROM appeals WHERE heard_at IS NULL ORDER BY id")


def summary(conn: Database) -> dict:
    """Two numbers, because one cannot tell the difference that matters.

    Zero appeals filed is an organization nobody disagrees with. Zero heard
    against forty filed is a right that exists on paper. §130's lesson - a rule
    forbidding its own subject looks exactly like a quiet market - applied where
    the failure would be least visible, because an unexercised right and a
    denied one both look like silence."""
    rows = conn.fetchall("SELECT * FROM appeals")
    heard = [row for row in rows if row["heard_at"] is not None]
    return {
        "filed": len(rows),
        "heard": len(heard),
        # Named individually. A count tells a reader that appeals are waiting and
        # not which, and the next thing they do is query the database themselves.
        "unheard": [row["id"] for row in rows if row["heard_at"] is None],
        "upheld": sum(1 for row in heard if row["outcome"] == OUTCOME_UPHELD),
        "overturned": sum(1 for row in heard if row["outcome"] == OUTCOME_OVERTURNED),
        # Stated every time, because it is the fact that makes the numbers above
        # readable: this organization runs one of each role, so an appeal usually
        # has no eligible peer and waiting is the ordinary case rather than neglect.
        "note": (
            "An appeal with no eligible adjudicator stays open. It is never denied, expired "
            "or closed by a timeout - a lapsed appeal would be a denial nobody had to make."),
    }


# --- what an agent can contest on the record alone --------------------------------------

def contestable_by(conn: Database, identity: str) -> list[dict]:
    """Rulings about this agent that the record alone shows are contestable.

    **Deterministic, and that is the whole design.** Whether a grade is *wrong* is
    a judgement, and an agent that appealed every low score would be appealing
    rather than disagreeing. So a ground has to be a fact already in the record.

    Two are, and both are the charter's own standards:

    - **The grader filed the report it graded.** No independent information, which
      is the duty `compliance.self_evaluated` exists to detect.
    - **The ruling carries no rationale.** `record_disposition` has always refused
      one, on the grounds that ruling without saying why is how a check stops
      covering things while still passing. A graded party cannot evaluate a
      reason it was not given.

    ## Corrected at TQ-104, and the correction removed the condition

    TQ-103's version compared the grader to the *analysis result's* producer,
    which `agents/analysis.py` makes identical by construction - so it matched
    every grade, and the agent it offered them to was the one that *wrote* them.
    The live demonstration at §146 was of a condition manufactured by that
    misreading (§147).

    Correctly aimed, **neither ground currently fires**: Analysis does not file
    reports, so it never grades its own, and `record_grade` now refuses a grade
    with no rationale. That is the honest state of a right whose grounds are
    real and whose occasions do not presently arise - and it is why nothing here
    files an appeal on a schedule."""
    identity = (identity or "").strip()
    if not identity:
        return []
    rows = conn.fetchall(
        "SELECT g.id, g.grader_identity, g.overall_score, g.rationale,"
        " r.producer_identity"
        " FROM grades g"
        " JOIN (" + _REPORTS + ") r ON r.id = g.report_id"
        " LEFT JOIN appeals ap ON ap.ruling_kind = ? AND ap.ruling_id = g.id"
        " WHERE r.producer_identity = ? AND ap.id IS NULL"
        "   AND (g.grader_identity = r.producer_identity"
        "        OR g.rationale IS NULL OR TRIM(g.rationale) = '')"
        " ORDER BY g.id",
        (KIND_GRADE, identity))
    contestable = []
    for row in rows:
        if row["grader_identity"] == row["producer_identity"]:
            grounds = (
                f"This grade was written by {row['grader_identity']}, which is the identity that "
                f"filed the report it grades, so it carries no independent information (agent "
                f"charter: work is evaluated by its consumer, not its producer). Asking for "
                f"review by someone other than its author.")
        else:
            grounds = (
                f"This grade carries no rationale, so there is nothing in it for the agent it "
                f"judges to evaluate or answer. A ruling that does not say why is an assertion. "
                f"Asking for review by someone other than its author.")
        contestable.append({
            "kind": KIND_GRADE,
            "id": row["id"],
            "author": row["grader_identity"],
            "overall_score": row["overall_score"],
            "rationale": row["rationale"],
            "grounds": grounds,
        })
    return contestable


def roles_awaiting_a_peer(conn: Database) -> list[str]:
    """Roles where an appeal is waiting and nobody is eligible to hear it.

    **The workload signal, for whoever staffs the organization.** Addendum 46 §10
    is *work determines staffing*, and a hearing needs a peer of the author -
    which this organization, running one of each role, usually does not have. The
    condition was already visible in `unheard()`; this names what would fix it.

    At most one role per entry however many appeals are waiting: **one peer hears
    all of them.** Returning a role per appeal would ask for five agents to do one
    agent's work, which is the shape 46 §9 warns against."""
    roles = []
    for row in unheard(conn):
        if eligible_adjudicators(conn, row["id"]):
            continue
        author_role = conn.fetchone(
            "SELECT role FROM agent_registry WHERE identity = ?", (row["author"],))
        if author_role is not None and author_role["role"] not in roles:
            roles.append(author_role["role"])
    return roles


def independence_finding(conn: Database, appeal_id: int) -> dict:
    """What a peer finds when it reviews a contested ruling, on the record alone.

    **This reviews the ruling's independence, not the work's quality**, and the
    distinction is the whole of what makes it honest. A peer cannot re-grade an
    analysis without redoing it; what it *can* establish from the record is
    whether the ruling was made by somebody with an independent view - which is
    the charter's own standard, and the ground the appeal was filed on.

    So an overturned grade does **not** mean the work was good. It means the
    grade did not carry the independent judgement a grade is supposed to carry,
    and the analysis is now ungraded rather than well graded. The rationale says
    so, because a reader seeing `overturned` and inferring quality would have
    learned something false from a true record.

    Deterministic, because the ground is. A peer asked to decide *whether the
    score was right* would be asked for an opinion, and an appeal decided by
    opinion is one whose outcome depends on who happened to be spawned."""
    row = require(conn, appeal_id)
    grade = conn.fetchone(
        "SELECT g.grader_identity, r.producer_identity, g.worth_the_compute"
        " FROM grades g JOIN (" + _REPORTS + ") r ON r.id = g.report_id"
        " WHERE g.id = ?", (row["ruling_id"],))
    if grade is None:
        return {
            "outcome": OUTCOME_UPHELD,
            "rationale": (
                "The ruling this appeal names is no longer in the record, so there is nothing "
                "to find it wanting. Upheld for want of anything to review, which is not the "
                "same as having been reviewed."),
        }
    if grade["grader_identity"] != grade["producer_identity"]:
        return {
            "outcome": OUTCOME_UPHELD,
            "rationale": (
                f"The ground does not hold: {grade['grader_identity']} did not file the report "
                f"it graded, so the ruling carried an independent view. This review reaches the "
                f"independence of the ruling and not the merits of the score."),
        }
    return {
        "outcome": OUTCOME_OVERTURNED,
        "rationale": (
            f"{grade['grader_identity']} graded a report it filed itself, so the ruling carried "
            f"no independent judgement (agent charter: work is evaluated by its consumer, not "
            f"its producer). **This says nothing about the quality of the work** - the report "
            f"is now ungraded rather than well graded, and an independent grade is what it is "
            f"owed."),
    }
