"""The Software Department's issue record, and the gates that make it a discipline
(TASK_QUEUE TQ-106; addendum 53 §1, §2, §6, §12, §13, §15;
docs/SPEC_RECONCILIATION.md §150, §151).

Addendum 53 §1: the department *"is not merely a repair service. Its responsibility
is to make the system progressively harder to break in the same way twice."*

That sentence is the whole design. A department that recorded issues and closed
them would be a ticket queue; what makes it the thing §1 describes is **what it
refuses to let you close.**

## The five gates

§6's ten steps are a workflow, and a workflow nothing enforces is a suggestion.
Five of the ten are enforced here, and each one is a defect this project has
actually shipped:

1. **A root cause needs three perspectives first** (§6 step 3). §2 says the triad
   *"must not work as isolated silos"*, and the three questions are different in
   kind: is the data wrong, is the implementation wrong, **why did the tests not
   catch it**. §149 §4 found three defects where the answer to the third was *the
   tests were built from the same misreading* - and nobody was asking.
2. **The three perspectives come from three identities.** One agent supplying all
   three is one belief wearing three hats, which is the failure the separation
   exists to prevent. This is the fifth instance of the rule already applied at
   `engineering.approve`, `compliance.self_evaluated`, `release.judge` and
   `appeal.hear`.
3. **Closing needs a prevention, not only a correction** (§6 step 6). A fix
   without a safeguard is the same defect available again tomorrow, which is §1's
   *harder to break in the same way twice* made mechanical.
4. **Closing needs an adversarial proof naming a test** (§6 step 7). §5.3: *"Every
   tripwire must be demonstrated to fail under a deliberately constructed bad
   state."* The named test is the answer to *has it been observed failing?*
5. **The verifier is not the corrector.** §5.2 forbids deriving implementation and
   expected values from one assumption, and one agent doing both derives them from
   one assumption by construction.

## What severity 1 does, and what it does not

§12 escalates a critical issue to the CEO. **There is no CEO** (§150 §2), and
inventing a second escalation queue beside `parliament.owner_escalations` would be
two places where a matter waits for a person.

So a severity-1 issue escalates through `parliament.escalate`, whose contract is
already exactly right: *"Raise something to the owner. Nothing in this system can
answer it"*, with no `resolve`, no `dismiss` and no expiry. Reused rather than
rebuilt.

## What this does not do

- **It does not fix anything.** It records, gates and refuses. The correcting is
  `backend/engineering.py`'s and a person's.
- **It does not submit lessons to a librarian** (§13). The librarian does not
  exist, and writing lessons into a store whose declared gap 2 is that nothing
  reads them back would grow the gap while looking like it closed one.
- **It does not gate a release** (§10). `backend/release.py` exists and this does
  not stand in front of it; wiring that before the department has ever handled an
  issue would be ceremony.

Sits below `fi_db`, so it must not import it.
"""

from __future__ import annotations

import json

from backend import parliament
from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS software_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at TEXT NOT NULL,
    opened_by TEXT NOT NULL,
    -- Addendum 53 §6 step 1. Four facts, because "it is broken" is not an intake.
    observed TEXT NOT NULL,
    evidence TEXT NOT NULL,
    component TEXT NOT NULL,
    expected TEXT NOT NULL,
    -- A stable name for "this same finding again", so a scheduled check that
    -- keeps finding one thing opens one issue rather than one per cycle.
    signature TEXT NOT NULL,
    classification TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    -- §6 steps 4-6, 9-10. NULL until the gates below are satisfied.
    root_cause TEXT,
    correction TEXT,
    corrected_by TEXT,
    prevention TEXT,
    -- §6 step 7: the test that was observed failing under the bad state.
    proof_test TEXT,
    verified_by TEXT,
    release_note TEXT,
    lesson TEXT,
    closed_at TEXT,
    escalation_id INTEGER,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS software_issues_open ON software_issues (status, id);
-- One open issue per finding. A scheduled health check runs every cycle and would
-- otherwise file the same defect forever.
CREATE UNIQUE INDEX IF NOT EXISTS software_issues_one_open_per_signature
    ON software_issues (signature) WHERE status <> 'closed';

CREATE TABLE IF NOT EXISTS software_issue_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    -- Which of §2's three questions this answers.
    perspective TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    finding TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    UNIQUE (issue_id, perspective)
);
"""

SCHEMA_VERSION = 1

# Addendum 53 §2's three perspectives. Not job titles - three different questions
# about one defect, and the third is the one nobody was asking (§149 §4).
PERSPECTIVE_DATA = "database"        # is the schema, vocabulary, query or state wrong?
PERSPECTIVE_IMPLEMENTATION = "implementation"   # is the logic or integration wrong?
PERSPECTIVE_VERIFICATION = "verification"       # why did the tests not catch it?
PERSPECTIVES = (PERSPECTIVE_DATA, PERSPECTIVE_IMPLEMENTATION, PERSPECTIVE_VERIFICATION)

# §6 step 2.
CLASSIFICATIONS = (
    "database_schema", "software_logic", "test_verification", "integration",
    "release_rollback", "observability", "mixed",
)

# §12. Three levels, and only the first does anything automatic.
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_NORMAL = "normal"
SEVERITIES = (SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_NORMAL)

STATUS_OPEN = "open"
STATUS_REVIEWED = "reviewed"
STATUS_CORRECTED = "corrected"
STATUS_CLOSED = "closed"
STATUSES = (STATUS_OPEN, STATUS_REVIEWED, STATUS_CORRECTED, STATUS_CLOSED)


class IssueRefused(PermissionError):
    """A step this department will not take out of order, or at all."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def open_issue(conn: Database, *, observed: str, evidence: str, component: str,
               expected: str, signature: str, classification: str, severity: str,
               opened_by: str) -> int:
    """Addendum 53 §6 step 1, with step 2's classification and §12's severity.

    **Four facts are required and none is optional.** *"It is broken"* is not an
    intake: without the expected behaviour there is nothing to compare against,
    and without the evidence nobody can re-examine the judgement later. That is
    `record_disposition`'s rule about rationales, one level up.

    Returns the existing issue's id when one is already open for this signature,
    rather than raising. A scheduled health check calls this every cycle and
    would otherwise have to catch an exception to make progress - which is using
    an exception as a filter, and would eventually be wrapped in a bare except."""
    for name, value in (("observed behaviour", observed), ("evidence", evidence),
                        ("component", component), ("expected behaviour", expected),
                        ("signature", signature), ("opener", opened_by)):
        if not (value or "").strip():
            raise IssueRefused(f"An issue needs its {name}.")
    if classification not in CLASSIFICATIONS:
        raise IssueRefused(
            f"unknown classification {classification!r}; known are {list(CLASSIFICATIONS)}")
    if severity not in SEVERITIES:
        raise IssueRefused(f"unknown severity {severity!r}; known are {list(SEVERITIES)}")

    existing = conn.fetchone(
        "SELECT id FROM software_issues WHERE signature = ? AND status <> ?",
        (signature.strip(), STATUS_CLOSED))
    if existing is not None:
        return existing["id"]

    issue_id = conn.execute_returning_id(
        "INSERT INTO software_issues (opened_at, opened_by, observed, evidence, component,"
        " expected, signature, classification, severity, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), opened_by.strip(), observed.strip(), evidence.strip(),
         component.strip(), expected.strip(), signature.strip(), classification,
         severity, STATUS_OPEN))

    if severity == SEVERITY_CRITICAL:
        # §12 severity 1 escalates to a person. Through the queue that already
        # exists and already has the right contract - no resolve, no dismiss, no
        # expiry - rather than a second place where a matter waits for somebody.
        escalation = parliament.escalate(
            conn,
            summary=(f"Severity-1 software issue {issue_id} on {component.strip()}: "
                     f"{observed.strip()}"),
            raised_by=opened_by.strip())
        conn.execute("UPDATE software_issues SET escalation_id = ? WHERE id = ?",
                     (escalation, issue_id))
    return issue_id


def review(conn: Database, issue_id: int, *, perspective: str, reviewer: str,
           finding: str) -> None:
    """One of the three perspectives on this defect (§6 step 3).

    Recorded per perspective, so the same reviewer cannot file the same angle
    twice and appear to be three people."""
    require(conn, issue_id)
    if perspective not in PERSPECTIVES:
        raise IssueRefused(
            f"unknown perspective {perspective!r}; addendum 53 §2's are {list(PERSPECTIVES)}")
    if not (finding or "").strip():
        raise IssueRefused(
            "A review states what it found. An empty one is a reviewer having been "
            "assigned rather than having looked.")
    if not (reviewer or "").strip():
        raise IssueRefused("A review needs its reviewer.")
    conn.execute(
        "INSERT INTO software_issue_reviews (issue_id, perspective, reviewer, finding,"
        " reviewed_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (issue_id, perspective) DO UPDATE SET reviewer = excluded.reviewer,"
        " finding = excluded.finding, reviewed_at = excluded.reviewed_at",
        (issue_id, perspective, reviewer.strip(), finding.strip(), now_iso()))


def reviews(conn: Database, issue_id: int) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM software_issue_reviews WHERE issue_id = ? ORDER BY perspective",
        (issue_id,))


def record_root_cause(conn: Database, issue_id: int, *, root_cause: str) -> None:
    """§6 step 4: why the defect was *possible*, not where it appeared.

    **Gated on all three perspectives, from three identities.** §2 forbids the
    triad working as silos, and one agent supplying all three angles is one
    belief wearing three hats - which is the exact failure §149 §4 recorded,
    where implementation and tests came from a single misreading."""
    require(conn, issue_id)
    if not (root_cause or "").strip():
        raise IssueRefused("A root cause that says nothing is a step skipped.")

    filed = reviews(conn, issue_id)
    missing = [p for p in PERSPECTIVES if p not in {row["perspective"] for row in filed}]
    if missing:
        raise IssueRefused(
            f"Issue {issue_id} has no {', '.join(missing)} review. Addendum 53 §2 investigates "
            f"every significant defect from three perspectives, and the third - why the tests "
            f"did not catch it - is the one nobody was asking (SPEC_RECONCILIATION 149).")
    reviewers = {row["reviewer"] for row in filed}
    if len(reviewers) < len(PERSPECTIVES):
        raise IssueRefused(
            f"The three perspectives on issue {issue_id} came from {len(reviewers)} "
            f"identit{'y' if len(reviewers) == 1 else 'ies'} ({', '.join(sorted(reviewers))}). "
            f"One agent supplying all three is one belief wearing three hats, which is the "
            f"failure the separation exists to prevent.")

    conn.execute(
        "UPDATE software_issues SET root_cause = ?, status = ? WHERE id = ?",
        (root_cause.strip(), STATUS_REVIEWED, issue_id))


def record_correction(conn: Database, issue_id: int, *, correction: str,
                      prevention: str, corrected_by: str) -> None:
    """§6 steps 5 and 6, and they are one call on purpose.

    **A correction without a prevention is the same defect available again
    tomorrow.** §1's *"progressively harder to break in the same way twice"* is
    the department's whole reason for existing, and separating the two calls
    would make the second one optional in practice."""
    issue = require(conn, issue_id)
    if issue["root_cause"] is None:
        raise IssueRefused(
            f"Issue {issue_id} has no root cause yet. §6 step 4 comes before step 5, because "
            f"a correction written first fixes where the defect appeared.")
    for name, value in (("correction", correction), ("prevention", prevention),
                        ("corrector", corrected_by)):
        if not (value or "").strip():
            raise IssueRefused(
                f"A {name} is required. A fix without a safeguard leaves the same defect "
                f"available tomorrow (addendum 53 §1)." if name == "prevention"
                else f"A {name} is required.")
    conn.execute(
        "UPDATE software_issues SET correction = ?, prevention = ?, corrected_by = ?,"
        " status = ? WHERE id = ?",
        (correction.strip(), prevention.strip(), corrected_by.strip(),
         STATUS_CORRECTED, issue_id))


def close(conn: Database, issue_id: int, *, proof_test: str, verified_by: str,
          lesson: str, release_note: str | None = None) -> None:
    """§6 steps 7, 8 and 10. The gate that makes the rest mean something.

    **`proof_test` names the test that was observed failing under the deliberately
    constructed bad state** (§5.3). Not a claim that verification happened - the
    name of the thing somebody else can run. §5.3's third question is *has the
    tripwire actually been observed failing under that condition?*, and a boolean
    cannot answer it.

    **The verifier is not the corrector** (§5.2). One agent doing both derives the
    implementation and the expected values from one assumption by construction,
    which is how three defects passed every test (§149 §4)."""
    issue = require(conn, issue_id)
    if issue["status"] == STATUS_CLOSED:
        raise IssueRefused(f"Issue {issue_id} is already closed.")
    if issue["correction"] is None:
        raise IssueRefused(f"Issue {issue_id} has no correction to verify.")
    for name, value in (("proof test", proof_test), ("verifier", verified_by),
                        ("lesson", lesson)):
        if not (value or "").strip():
            raise IssueRefused(
                f"Closing an issue needs the {name}." if name != "proof test" else
                "Closing an issue needs the name of the test that was observed failing under "
                "the bad state (addendum 53 §5.3). A claim that verification happened is not "
                "the same as the name of a thing somebody else can run.")
    if verified_by.strip() == (issue["corrected_by"] or "").strip():
        raise IssueRefused(
            f"{verified_by} wrote the correction and cannot also be its verification "
            f"(addendum 53 §5.2). One agent doing both derives the fix and the expected "
            f"values from a single assumption.")

    conn.execute(
        "UPDATE software_issues SET proof_test = ?, verified_by = ?, lesson = ?,"
        " release_note = ?, status = ?, closed_at = ? WHERE id = ?",
        (proof_test.strip(), verified_by.strip(), lesson.strip(),
         (release_note or "").strip() or None, STATUS_CLOSED, now_iso(), issue_id))


def get(conn: Database, issue_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM software_issues WHERE id = ?", (issue_id,))


def require(conn: Database, issue_id: int) -> dict:
    issue = get(conn, issue_id)
    if issue is None:
        raise IssueRefused(f"No software issue {issue_id}.")
    return issue


def open_issues(conn: Database) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM software_issues WHERE status <> ? ORDER BY id", (STATUS_CLOSED,))


def lessons(conn: Database) -> list[dict]:
    """§6 step 10's captured lessons, for whoever eventually reads them.

    Kept here rather than written into `knowledge_records`: addendum 53 §13 hands
    that to a librarian who does not exist, and the organization model's declared
    gap 2 is that lessons written there are never read back. A second unread
    writer would grow the gap while looking like it closed one."""
    return conn.fetchall(
        "SELECT id, component, signature, root_cause, prevention, proof_test, lesson,"
        " closed_at FROM software_issues WHERE status = ? AND lesson IS NOT NULL"
        " ORDER BY id", (STATUS_CLOSED,))


def summary(conn: Database) -> dict:
    """What the department has and has not dealt with.

    Two numbers where one would hide the difference (§130): an organization with
    no issues and one whose issues are all stuck at step 3 both look quiet from a
    single count."""
    rows = conn.fetchall("SELECT status, severity, COUNT(*) AS n FROM software_issues"
                         " GROUP BY status, severity")
    by_status = {status: 0 for status in STATUSES}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + row["n"]
    unclosed = open_issues(conn)
    return {
        "by_status": by_status,
        "open": [
            {"id": row["id"], "component": row["component"], "severity": row["severity"],
             "status": row["status"],
             # Which of §6's steps it is waiting on, named rather than inferred
             # from a status word.
             "waiting_on": (
                 "three-perspective review" if row["root_cause"] is None
                 else "correction and prevention" if row["correction"] is None
                 else "adversarial verification")}
            for row in unclosed],
        "critical_unclosed": [row["id"] for row in unclosed
                              if row["severity"] == SEVERITY_CRITICAL],
        "not_done": [
            "lessons are not submitted to a librarian - addendum 53 section 13's "
            "librarian does not exist, and the store it would write to has no reader",
            "this department does not gate a release - backend/release.py runs "
            "without it",
        ],
    }
