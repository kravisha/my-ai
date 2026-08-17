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
    exempt: bool = False
    reason: str = ""

    def describes_evaluation(self) -> str:
        if self.evaluation[0] == COLUMN:
            return f"{self.table}.{self.evaluation[1]} is set"
        return f"a row in {self.evaluation[1]} keyed by {self.evaluation[2]}"


EVALUATION_RULES = (
    # The path that works. Analysis grades the report it consumed, and writes the
    # grade before completing it, so there is no window in which a completed
    # report is legitimately ungraded - which is why no grace period is needed
    # here and why one would only hide a real violation.
    EvaluationRule(
        name="discovery report",
        table="discovery_reports_completed",
        key="id",
        completed_at="completed_at",
        producer="producer_identity",
        evaluation=(TABLE, "grades", "report_id"),
        consumer="the judgment agent that consumed it",
    ),
    # Answered and consumed by the agent that asked, and never evaluated. There
    # is a consumer, which is what makes this a rule violation rather than a
    # question about whether the rule applies.
    EvaluationRule(
        name="cross-check answer",
        table="cross_check_requests",
        key="id",
        completed_at="answered_at",
        producer="responder_identity",
        evaluation=(TABLE, "grades", "report_id"),
        consumer="the agent that requested it",
    ),
    # Satisfies the rule under another name. COO records an observed result once
    # it can see whether the decision panned out, which is evaluation on
    # completion by the consumer - it simply does not live in `grades`. Included
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
    # Exempt, and the reason is the point: the consumer is a person, and the
    # organization has no mechanism by which a human records a grade. Listing it
    # as exempt keeps it visible; dropping it from the table would make the
    # absence indistinguishable from an oversight.
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

# Paths deliberately outside the check. Pinned so a fifth cannot be added
# quietly - the same ratchet the organization model uses for unclosed feedback
# loops, applied to the rules about rules.
EXEMPT_COUNT = 1


def _table_exists(conn: Database, table: str) -> bool:
    return conn.fetchone(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ) is not None


def unevaluated(conn: Database, rule: EvaluationRule, limit: int = 50) -> list[dict]:
    """Completed work of one kind that carries no evaluation."""
    if rule.exempt or not _table_exists(conn, rule.table):
        return []

    if rule.evaluation[0] == COLUMN:
        missing = f"w.{rule.evaluation[1]} IS NULL"
    else:
        _, table, column = rule.evaluation
        missing = (
            f"NOT EXISTS (SELECT 1 FROM {table} e WHERE e.{column} = w.{rule.key})"
            if _table_exists(conn, table) else "1=1"
        )

    rows = conn.fetchall(
        f"SELECT w.{rule.key} AS item, w.{rule.producer} AS producer, "
        f"w.{rule.completed_at} AS completed_at FROM {rule.table} w "
        f"WHERE w.{rule.completed_at} IS NOT NULL AND {missing} "
        f"ORDER BY w.{rule.completed_at} LIMIT ?",
        (limit,),
    )
    return [
        {
            "rule": rule.name,
            "item": row["item"],
            "producer": row["producer"],
            "completed_at": row["completed_at"],
            "expected": rule.describes_evaluation(),
            "consumer": rule.consumer,
        }
        for row in rows
    ]


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

    Reports the paths that pass as well as the ones that fail. A check that only
    listed violations could not distinguish a compliant organization from one
    whose rules were never applied to most of its work."""
    findings, passing, exempt = [], [], []

    for rule in EVALUATION_RULES:
        if rule.exempt:
            exempt.append({"rule": rule.name, "reason": rule.reason})
            continue
        breaches = unevaluated(conn, rule, limit)
        if breaches:
            findings.extend(breaches)
        else:
            passing.append(rule.name)

    self_judged = self_evaluated(conn, limit)

    return {
        "unevaluated": findings,
        "self_evaluated": self_judged,
        "passing": passing,
        "exempt": exempt,
        "total_findings": len(findings) + len(self_judged),
        # Said explicitly. "Nothing was found" and "nothing was checked" are
        # different results, and a summary that could not tell them apart would
        # let an empty database read as a compliant organization.
        "rules_applied": len(EVALUATION_RULES) - len(exempt),
    }


def summarise(report: dict) -> str:
    lines = [
        f"{report['total_findings']} finding(s) across {report['rules_applied']} rule(s)",
    ]
    for finding in report["unevaluated"]:
        lines.append(
            f"  UNEVALUATED  {finding['rule']} #{finding['item']} by {finding['producer']} "
            f"- expected {finding['expected']}, to be written by {finding['consumer']}"
        )
    for finding in report["self_evaluated"]:
        lines.append(
            f"  SELF-JUDGED  {finding['rule']} #{finding['item']} - {finding['finding']}"
        )
    if report["passing"]:
        lines.append(f"  compliant: {', '.join(report['passing'])}")
    for entry in report["exempt"]:
        lines.append(f"  exempt: {entry['rule']} - {entry['reason']}")
    return "\n".join(lines)
