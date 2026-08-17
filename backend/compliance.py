"""Does completed work actually carry the evaluation the rules require?

The organization's own rule is that grading is part of task completion, not
optional metadata attached afterwards: work submitted to a queue is evaluated by
whoever consumes it, and that evaluation is recorded as the work moves out of the
active queue. This checks whether that is true.

**A query, not a subsystem.** Every record it inspects already exists; what was
missing was the asking. That matters for what comes after it - an organization
that discovers it needs an enforcement division should first find out whether it
has anything to enforce, and this is how.

Two questions, because they fail differently:

    unevaluated   work completed and nobody judged it
    self-judged   work completed and its own producer judged it

The second is the subtler one. A grade exists, the record looks complete, and the
evaluation carries no independent information - the rule is that the *consumer*
evaluates, precisely so that judging one's own work is not what happens.

Internal rationale: INT-PHIL-0024
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.db import Database

# Where evaluation lives for a given kind of work. Two shapes only:
#
#   ("column", name)          the column being non-NULL is the evaluation
#   ("table", table, column)  a row keyed back to the work is the evaluation
#
# Kept declarative so adding a completion path is an entry rather than a new
# query, and so the paths deliberately left out are visible as data instead of as
# an absence nobody notices.
COLUMN = "column"
TABLE = "table"
# Evaluation reached through a carrying record rather than directly. A
# cross-check answer is not graded in its own right; it is carried into a report
# and evaluated as part of it, so the rule has to follow the carrier or it
# reports work as neglected that was in fact judged.
VIA = "via"


@dataclass(frozen=True)
class EvaluationRule:
    """One kind of completed work, and what counts as having evaluated it."""

    name: str
    table: str
    key: str
    completed_at: str
    producer: str
    evaluation: tuple
    consumer: str
    # Restricts the rule to a subset of the table, so paths with genuinely
    # different obligations are separate rules rather than one rule with an
    # unstated exception.
    applies_when: str = "1=1"
    # Where a row means evaluation is legitimately still pending. Not-yet-judged
    # and never-will-be-judged are different findings with different remedies,
    # and reporting them alike would make an organization keeping up look exactly
    # like one neglecting its work.
    in_flight: tuple | None = None
    exempt: bool = False
    reason: str = ""
    # Compliance is impossible for structural reasons, with the remedy named.
    # Distinct from exempt: exempt means the rule does not apply, this means it
    # applies and cannot currently be met.
    blocked: str = ""

    def describes_evaluation(self) -> str:
        kind = self.evaluation[0]
        if kind == COLUMN:
            return f"{self.table}.{self.evaluation[1]} is set"
        if kind == VIA:
            _, carrier, link, target, key = self.evaluation
            return f"a row in {target} for the {carrier} that carries it"
        return f"a row in {self.evaluation[1]} keyed by {self.evaluation[2]}"


EVALUATION_RULES = (
    # The path that works. Analysis grades the report it consumed, writing the
    # grade before completing it, so there is no window in which a completed
    # report is legitimately ungraded - which is why no grace period is needed
    # and why one would only hide a real violation.
    EvaluationRule(
        name="discovery report (analysed)",
        table="discovery_reports_completed",
        key="id",
        completed_at="completed_at",
        producer="producer_identity",
        applies_when="w.outcome = 'analyzed'",
        evaluation=(TABLE, "grades", "report_id"),
        consumer="the judgment agent that consumed it",
    ),
    # The same work, failed, and it cannot comply. `grades.analysis_result_id` is
    # NOT NULL, so a grade requires an analysis result and a failed analysis
    # produces none. This is architectural rather than behavioural, which is the
    # governing framework's own first question - and enforcing it against the
    # producing agent would punish it for a constraint it cannot satisfy.
    EvaluationRule(
        name="discovery report (failed)",
        table="discovery_reports_completed",
        key="id",
        completed_at="completed_at",
        producer="producer_identity",
        applies_when="w.outcome = 'failed'",
        evaluation=(TABLE, "grades", "report_id"),
        consumer="the judgment agent that consumed it",
        blocked=(
            "grades.analysis_result_id is NOT NULL, so a grade cannot exist without an analysis "
            "result, and a failed analysis produces none. Remedy is a considered schema migration "
            "making the reference nullable - not something an agent can do"
        ),
    ),
    # Reported as neglected until the rule was checked against the records. Every
    # answered cross-check is carried into a report and evaluated as part of it,
    # so following the carrier is what the rule always should have done - the
    # first version looked for a grade keyed directly to the cross-check, which
    # nothing ever writes.
    EvaluationRule(
        name="cross-check answer",
        table="cross_check_requests",
        key="id",
        completed_at="answered_at",
        producer="responder_identity",
        evaluation=(VIA, "discovery_reports_completed", "cross_check_id", "grades", "report_id"),
        in_flight=("discovery_reports", "cross_check_id"),
        consumer="the judgment agent that reasons over both frames",
    ),
    # Satisfies the rule under another name. COO records an observed result once
    # it can see whether the decision panned out, which is evaluation on
    # completion by the consumer; it simply does not live in `grades`. Included
    # so the check confirms it rather than staying silent about a path it does
    # not cover.
    EvaluationRule(
        name="COO directive",
        table="coo_directives_completed",
        key="id",
        completed_at="completed_at",
        producer="requested_by",
        evaluation=(COLUMN, "observed_result"),
        consumer="COO, which requested it",
    ),
    # Exempt, and the reason is the point: the consumer is a person and nothing
    # lets a human record an evaluation. Listing it keeps it visible; dropping it
    # would make the absence indistinguishable from an oversight.
    EvaluationRule(
        name="operator question",
        table="uqi_requests",
        key="id",
        completed_at="answered_at",
        producer="target_identity",
        evaluation=(COLUMN, "answer"),
        consumer="the human operator who asked",
        exempt=True,
        reason="the consumer is a person, and nothing lets a human record an evaluation",
    ),
)

# Paths deliberately outside the check, and paths that cannot currently meet it.
# Both pinned, so neither can grow quietly - a rule marked exempt or blocked is
# how a compliance check stops covering anything while still passing.
EXEMPT_COUNT = 1
BLOCKED_COUNT = 1

VIOLATION = "violation"
IN_FLIGHT = "in_flight"
BLOCKED = "blocked"


def _table_exists(conn: Database, table: str) -> bool:
    return conn.fetchone(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ) is not None


def unevaluated(conn: Database, rule: EvaluationRule, limit: int = 50) -> list[dict]:
    """Completed work of one kind carrying no evaluation, classified by why.

    Three outcomes, because they need different responses. A **violation** is
    work nobody judged that somebody could have. **In flight** is work whose
    evaluation is legitimately still pending - reporting that as neglect would
    make an organization keeping up look exactly like one falling behind.
    **Blocked** is work that cannot be evaluated at all, and the remedy belongs
    to whoever can change the constraint rather than to the agent."""
    if rule.exempt or not _table_exists(conn, rule.table):
        return []

    kind = rule.evaluation[0]
    if kind == COLUMN:
        missing = f"w.{rule.evaluation[1]} IS NULL"
    elif kind == VIA:
        _, carrier, link, target, key = rule.evaluation
        if not (_table_exists(conn, carrier) and _table_exists(conn, target)):
            missing = "1=1"
        else:
            missing = (
                f"NOT EXISTS (SELECT 1 FROM {carrier} c JOIN {target} e ON e.{key} = c.id "
                f"WHERE c.{link} = w.{rule.key})"
            )
    else:
        _, table, column = rule.evaluation
        missing = (
            f"NOT EXISTS (SELECT 1 FROM {table} e WHERE e.{column} = w.{rule.key})"
            if _table_exists(conn, table) else "1=1"
        )

    pending = "0"
    if rule.in_flight and _table_exists(conn, rule.in_flight[0]):
        table, column = rule.in_flight
        pending = f"EXISTS (SELECT 1 FROM {table} p WHERE p.{column} = w.{rule.key})"

    rows = conn.fetchall(
        f"SELECT w.{rule.key} AS item, w.{rule.producer} AS producer, "
        f"w.{rule.completed_at} AS completed_at, ({pending}) AS pending FROM {rule.table} w "
        f"WHERE w.{rule.completed_at} IS NOT NULL AND {rule.applies_when} AND {missing} "
        f"ORDER BY w.{rule.completed_at} LIMIT ?",
        (limit,),
    )

    findings = []
    for row in rows:
        if rule.blocked:
            status, note = BLOCKED, rule.blocked
        elif row["pending"]:
            status, note = IN_FLIGHT, "the record carrying it has not completed yet"
        else:
            status, note = VIOLATION, ""
        findings.append({
            "rule": rule.name,
            "status": status,
            "item": row["item"],
            "producer": row["producer"],
            "completed_at": row["completed_at"],
            "expected": rule.describes_evaluation(),
            "consumer": rule.consumer,
            "note": note,
        })
    return findings


def self_evaluated(conn: Database, limit: int = 50) -> list[dict]:
    """Work whose grade was written by the agent that produced it.

    Not a missing evaluation - a present one that carries no independent
    information. The rule says the consumer evaluates, and this is the case it
    exists to prevent. Harder to spot than an absence, because the record looks
    complete.

    Reads `analysis_results` against `grades`, which is where producer and grader
    can currently coincide."""
    if not (_table_exists(conn, "analysis_results") and _table_exists(conn, "grades")):
        return []

    rows = conn.fetchall(
        "SELECT a.id AS item, a.producer_identity AS producer, g.grader_identity AS grader, "
        "a.created_at AS completed_at FROM analysis_results a "
        "JOIN grades g ON g.analysis_result_id = a.id "
        "WHERE g.grader_identity = a.producer_identity "
        "ORDER BY a.created_at LIMIT ?",
        (limit,),
    )
    return [
        {
            "rule": "analysis result",
            "item": row["item"],
            "producer": row["producer"],
            "grader": row["grader"],
            "completed_at": row["completed_at"],
            "finding": "graded by its own producer, so the evaluation is not independent",
        }
        for row in rows
    ]


def check(conn: Database, limit: int = 50) -> dict:
    """Every compliance question at once, with enough to act on each finding.

    Reports what passes as well as what fails. A check that only listed
    violations could not distinguish a compliant organization from one whose
    rules were never applied to most of its work."""
    violations, in_flight, blocked, passing, exempt = [], [], [], [], []

    for rule in EVALUATION_RULES:
        if rule.exempt:
            exempt.append({"rule": rule.name, "reason": rule.reason})
            continue
        buckets = {VIOLATION: violations, IN_FLIGHT: in_flight, BLOCKED: blocked}
        found = unevaluated(conn, rule, limit)
        for finding in found:
            buckets[finding["status"]].append(finding)
        if not any(f["status"] == VIOLATION for f in found):
            passing.append(rule.name)

    self_judged = self_evaluated(conn, limit)

    return {
        "unevaluated": violations,
        "in_flight": in_flight,
        "blocked": blocked,
        "self_evaluated": self_judged,
        "passing": passing,
        "exempt": exempt,
        # Only what somebody could have done and did not. Blocked and in-flight
        # work is reported separately on purpose: counting them here would put
        # a schema constraint and a queue still draining into the same number as
        # neglect, and the remedies have nothing in common.
        "total_findings": len(violations) + len(self_judged),
        "rules_applied": len(EVALUATION_RULES) - len(exempt),
    }


def summarise(report: dict) -> str:
    lines = [f"{report['total_findings']} finding(s) across {report['rules_applied']} rule(s)"]
    for finding in report["unevaluated"]:
        lines.append(
            f"  VIOLATION    {finding['rule']} #{finding['item']} by {finding['producer']} "
            f"- expected {finding['expected']}, from {finding['consumer']}"
        )
    for finding in report["self_evaluated"]:
        lines.append(f"  SELF-JUDGED  {finding['rule']} #{finding['item']} - {finding['finding']}")
    if report["in_flight"]:
        lines.append(f"  in flight:   {len(report['in_flight'])} awaiting the record that carries them")
    for finding in report["blocked"][:1]:
        lines.append(f"  BLOCKED      {finding['rule']} x{len(report['blocked'])} - {finding['note']}")
    if report["passing"]:
        lines.append(f"  compliant:   {', '.join(report['passing'])}")
    for entry in report["exempt"]:
        lines.append(f"  exempt:      {entry['rule']} - {entry['reason']}")
    return "\n".join(lines)
