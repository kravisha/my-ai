"""Reading the cooperation this organization has been recording all along
(TASK_QUEUE TQ-92; addendum 48 §3, §12, §13; addendum 37 §9, O9;
docs/SPEC_RECONCILIATION.md §131, §149).

Addendum 48 §3 makes cooperation a measured property and a condition of
leadership. Addendum 37 O9 has said the same since it was assimilated: *"No agent
may qualify for leadership without demonstrated collaboration."* Both were read as
unbuilt, because nothing scored cooperation.

**The evidence was already being written.** `cross_check_requests` records one
agent asking another for help and the answer coming back or not, and
`cross_check.unanswered_rate` has been a scenario property for months under a
*timing* rationale — a rise in it meant a timeout constant had drifted. It was
always also a record of one agent leaving another waiting.

So nothing here is a new measurement. It is reading what exists as what it is,
which is the same shape §131 found and this module discharges.

## The thing this must not become, and the refusal that keeps it from becoming it

Addendum 48 §12 forbids *"empty activity, performative work, needless conflict,
and actions that create work without creating value."* A cooperation **score** is
the most direct route to all four: an agent that answered every cross-check with
nothing, instantly, would score perfectly and cooperate not at all.

So this module **produces no score, and provides no ranking.** Not "does not
currently"; there is no function, and a test asserts there is none — the same
prevention-by-absence §120 argues for and the same rule that keeps the Speaker out
of `parliament.propose`.

What it reports instead is **composition**: how many requests an agent answered
with a finding, how many it answered honestly empty, and how often it was itself
left waiting. Those cannot be collapsed into one number without deciding what the
right mix is, and **what counts as sufficient cooperation depends on what the
agent does** — a Speculator asked about a quiet security should answer *no
evidence* most of the time, and an identical rate from a Speculator in a loud
market means something else entirely.

A threshold nobody measured would be a policy wearing a measurement's clothes
(§128). There is none here.

## Activity against outcome

The entry that queued this named the hard part: the measure has to be of
*outcomes* — was the asker helped — rather than of *activity*.

Two facts carry it, and neither can be raised by answering more:

- **`left_waiting`** is counted against the **asker**, not the responder. It is
  the only number here that is unambiguously a failure, and it is a fact about
  the organization rather than about any one agent — because an unanswered
  request has, by construction, nobody to attribute it to.
- **`answers_used`** counts answers a filed report actually linked to. An empty
  answer does not become a report, so this cannot be inflated by volume.

**`answers_used` is not a quality score**, and reading it as one would be the
error this module is written against: an honest *no evidence* is cooperation and
will never be used. It says how often an agent's help was built on, and nothing
about how often it should have been.

Read-only, like `backend/governance.py` and for a related reason: a module that
measures how agents treat each other must not also act on it, or the measurement
becomes an instrument and the agents start managing the instrument.

**Sits above `fi_db` and imports it**, unlike the stores in this package: it
declares no schema and `fi_db.init_schema` knows nothing about it. That is what
lets the outcome vocabulary come from the one place that defines it rather than
being restated here - and restating it is exactly what went wrong. The schema
comment beside the `outcome` column said `'answered'` for a value the code has
always written as `'evidence'`, and the first draft of this module trusted the
comment and matched nothing (§149).
"""

from __future__ import annotations

from backend import fi_db
from backend.db import Database

# Both are genuine answers. An honest "I looked and there is nothing" helps the
# asker, and treating it as a non-answer would push agents toward manufacturing
# findings - which is addendum 48 §12's "empty activity" arriving through the
# measurement meant to discourage it.
#
# Taken from `fi_db` rather than spelled out: one place defines this vocabulary,
# and a second copy is a copy that goes stale without failing.
ANSWERS = (fi_db.CROSS_CHECK_EVIDENCE, fi_db.CROSS_CHECK_NO_EVIDENCE)


def _table_exists(conn: Database, table: str) -> bool:
    return conn.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)) is not None


def by_agent(conn: Database) -> list[dict]:
    """What each agent did when another agent asked it for something.

    One row per agent that has either asked or answered. An agent that has done
    neither is absent rather than present with zeroes: it has not been in a
    position to cooperate or fail to, and a row of zeroes reads as a finding."""
    if not _table_exists(conn, "cross_check_requests"):
        return []

    agents: dict[str, dict] = {}

    def entry(identity: str) -> dict:
        return agents.setdefault(identity, {
            "identity": identity,
            # As a responder.
            "answered_with_a_finding": 0,
            "answered_no_evidence": 0,
            "answers_used": 0,
            # As a requester.
            "asked": 0,
            "left_waiting": 0,
            # Questions the organization had, closed by this agent's work.
            "questions_answered_for_others": 0,
        })

    for row in conn.fetchall(
            "SELECT responder_identity AS who, outcome, COUNT(*) AS n"
            " FROM cross_check_requests WHERE responder_identity IS NOT NULL"
            " GROUP BY responder_identity, outcome"):
        record = entry(row["who"])
        if row["outcome"] == fi_db.CROSS_CHECK_EVIDENCE:
            record["answered_with_a_finding"] += row["n"]
        elif row["outcome"] == fi_db.CROSS_CHECK_NO_EVIDENCE:
            record["answered_no_evidence"] += row["n"]

    # The outcome half: an answer a filed report was built on. Both report tables,
    # because a judged report moves to the archive and the help it used does not
    # stop having been used (§132's defect, which keeps arriving).
    if _table_exists(conn, "discovery_reports"):
        for row in conn.fetchall(
                "SELECT c.responder_identity AS who, COUNT(*) AS n"
                " FROM cross_check_requests c JOIN ("
                "   SELECT cross_check_id FROM discovery_reports"
                "   UNION ALL SELECT cross_check_id FROM discovery_reports_completed"
                " ) r ON r.cross_check_id = c.id"
                " WHERE c.responder_identity IS NOT NULL"
                " GROUP BY c.responder_identity"):
            entry(row["who"])["answers_used"] += row["n"]

    for row in conn.fetchall(
            "SELECT requester_identity AS who, COUNT(*) AS asked,"
            " SUM(CASE WHEN outcome IS NULL OR outcome NOT IN (?, ?) THEN 1 ELSE 0 END) AS waiting"
            " FROM cross_check_requests GROUP BY requester_identity",
            ANSWERS):
        record = entry(row["who"])
        record["asked"] += row["asked"]
        record["left_waiting"] += row["waiting"] or 0

    _add_questions_answered(conn, entry)
    return [agents[key] for key in sorted(agents)]


def _add_questions_answered(conn: Database, entry) -> None:
    """Open questions one agent raised and another agent's work closed.

    The second cooperation signal, and it is separate from cross-checks because
    the asking is different in kind: a cross-check is addressed to somebody, and
    an open question is left for whoever comes next.

    **Only questions raised by somebody else count.** An agent closing its own
    question is the organization thinking, not one agent helping another - and
    counting it would be the self-evaluation §147 spent an increment untangling,
    in a new place."""
    if not (_table_exists(conn, "knowledge_records")
            and _table_exists(conn, "analysis_results")):
        return
    for row in conn.fetchall(
            "SELECT a.producer_identity AS who, COUNT(*) AS n"
            " FROM knowledge_records k"
            " JOIN analysis_results a"
            "   ON ('analysis_results:' || a.id) = k.resolved_by_ref"
            " WHERE k.record_kind = 'open_question' AND k.resolved_at IS NOT NULL"
            "   AND k.recorded_by <> a.producer_identity"
            " GROUP BY a.producer_identity"):
        entry(row["who"])["questions_answered_for_others"] += row["n"]


def by_role(conn: Database) -> list[dict]:
    """Requests put to a role and left waiting.

    **Counted by role and not by agent, because an unanswered request has nobody
    to attribute it to.** A cross-check names the role it is addressed to and only
    acquires a responder when somebody answers, so the one number here that is
    unambiguously a failure is a fact about the organization's staffing rather
    than about any individual's willingness — which is the honest reading, and the
    one that does not let a metric become a grievance."""
    if not _table_exists(conn, "cross_check_requests"):
        return []
    return [
        {
            "role": row["responder_role"],
            "asked_of": row["asked_of"],
            "answered": row["answered"],
            # Pending and explicitly unanswered are one number here on purpose:
            # from the asker's side they are the same experience, and the
            # difference between them is about time rather than about help.
            "left_waiting": row["asked_of"] - row["answered"],
        }
        for row in conn.fetchall(
            "SELECT responder_role,"
            " COUNT(*) AS asked_of,"
            " SUM(CASE WHEN outcome IN (?, ?) THEN 1 ELSE 0 END) AS answered"
            " FROM cross_check_requests GROUP BY responder_role ORDER BY responder_role",
            ANSWERS)
    ]


def report(conn: Database) -> dict:
    """Everything this module can honestly say, and a list of what it cannot.

    The second list is not decoration. Addendum 48 §3 makes cooperation a
    condition of leadership, and a report that gave numbers without saying what
    they omit would be read as an answer to that - which it is not, and cannot be
    while `maturity`, `good faith` and `patience` are prose nothing can check
    (§131)."""
    return {
        "by_agent": by_agent(conn),
        "by_role": by_role(conn),
        # Said every time. A reader arriving at these numbers with addendum 48 §3
        # in mind is looking for a leadership criterion, and will not find one.
        "not_measured": [
            "whether an answer was any good - only whether it came, and whether a "
            "report was built on it",
            "whether an honestly empty answer should have found something, which "
            "depends on the market and not on the agent",
            "maturity, good faith, patience and reciprocity - addendum 48's other "
            "conditions, which are prose nothing here can check "
            "(SPEC_RECONCILIATION 131)",
            "any threshold for sufficient cooperation. There is none, deliberately: "
            "what is enough depends on what the agent does",
        ],
        # Named rather than left to be inferred from the absence of a score.
        "no_ranking": (
            "This module produces no score and no ranking. A cooperation score is "
            "the shortest route to addendum 48 section 12's empty activity and "
            "performative work: an agent answering everything with nothing would "
            "score perfectly and cooperate not at all."),
    }
