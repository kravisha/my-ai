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


def opportunity_count(conn: Database, rule_name: str) -> int:
    """How many chances there were to comply with a rule.

    The denominator that turns a count of findings into a statement about the
    system. Ten ungraded reports out of ten is a design that does not permit
    grading; ten out of two hundred is ten agents that did not grade. Without
    this the two are the same number.

    `analysis result` is the self-grading check rather than an evaluation rule,
    so its opportunities are the analyses that were graded at all - an ungraded
    analysis had no chance to be graded independently or otherwise."""
    if rule_name == "analysis result":
        if not (_table_exists(conn, "grades") and _table_exists(conn, "analysis_results")):
            return 0
        return conn.fetchone(
            "SELECT COUNT(*) AS n FROM grades g JOIN analysis_results a "
            "ON g.analysis_result_id = a.id"
        )["n"]

    rule = next((r for r in EVALUATION_RULES if r.name == rule_name), None)
    if rule is None or not _table_exists(conn, rule.table):
        return 0
    return conn.fetchone(
        f"SELECT COUNT(*) AS n FROM {rule.table} w "
        f"WHERE w.{rule.completed_at} IS NOT NULL AND {rule.applies_when}"
    )["n"]


def _annotate_dispositions(conn: Database, findings: list[dict]) -> None:
    """Mark each finding with the active ruling on it, if any.

    A read, like everything else here. Recording a disposition is a write and
    lives in `fi_db` - this module can see what was decided and can never decide
    anything, which is the same separation that keeps the checker from settling
    its own objections."""
    if not findings or not _table_exists(conn, "finding_dispositions"):
        return
    rulings = {
        (row["rule"], row["item"]): row
        for row in conn.fetchall(
            "SELECT * FROM finding_dispositions WHERE status = 'active'"
        )
    }
    for finding in findings:
        ruling = rulings.get((finding["rule"], str(finding["item"])))
        finding["disposition"] = ruling["disposition"] if ruling else None
        finding["disposition_rationale"] = ruling["rationale"] if ruling else None


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

    # Attach any ruling the organization has already made. Findings are never
    # removed by a disposition, only marked: a dispositioned finding that
    # disappeared would make `false_positive` a universal off switch, and the
    # check would stop covering things while still reporting clean.
    _annotate_dispositions(conn, violations)
    _annotate_dispositions(conn, self_judged)
    all_findings = violations + self_judged

    return {
        "unevaluated": violations,
        "in_flight": in_flight,
        "blocked": blocked,
        "self_evaluated": self_judged,
        "passing": passing,
        "exempt": exempt,
        # Findings nobody has ruled on yet - the ones actually awaiting a
        # decision, as distinct from the ones already answered for.
        "open_findings": sum(1 for f in all_findings if f.get("disposition") is None),
        "dispositioned": sum(1 for f in all_findings if f.get("disposition") is not None),
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


# --- objections -------------------------------------------------------------
#
# Who decides a contested case, given that nothing in this organization can.
#
# The Controller executes and does not decide. Explorer and Speculator are
# procedurally barred from judging - separating observation from judgment is an
# axiom, not a convenience. Analysis is the only role that reasons, and it is
# both the subject of the one live finding and the throughput bottleneck. COO
# already maintains the workforce, judges intelligence health and acts for the
# vacant CEO; adding adjudication would make one agent the manager, the
# investigator, the reputation assessor and the authority that can retire the
# accused. There is no adjudicator, and appointing one would be building a court
# before there is a dispute.
#
# **But most objections do not need a judge - they need a checker.** Of the
# grounds the governing framework lists, all but one are decidable from recorded
# facts: whether the work falls in the role's charter, whether a dependency
# exists, whether a resource is available, whether the instructions contradict
# each other, whether the agent is genuinely overloaded. Only a subjective
# safety concern requires someone to weigh it.
#
# So adjudication splits. Verifiable objections are settled by checking, which
# needs no authority at all. Anything left escalates to the owner, who is the
# only genuinely independent party that exists. When a contested caseload
# appears, that is the evidence for appointing an adjudicator; until then the
# framework's own rule applies - adjudicate only when an exception genuinely
# requires it.

VERIFIABLE = "verifiable"      # decidable from records, no judgment needed
JUDGED = "judged"              # needs someone to weigh it


@dataclass(frozen=True)
class ObjectionGround:
    """An allowed reason to object to ordered work, and how it gets decided.

    A closed list on purpose. An open "other" category would make refusal
    discretionary, which is the thing a structured objection exists to replace.

    Every ground carries a `remedy`: the shape of the answer to "what would have
    to be true for this work to proceed". An objection that only says no leaves
    the requester exactly where they were, and a blocked agent that reports the
    obstacle without proposing a way past it has transferred the design problem
    back rather than doing its share of it.

    Internal rationale: INT-PHIL-0025"""

    name: str
    kind: str
    decided_by: str
    evidence: str
    remedy: str


OBJECTION_GROUNDS = (
    ObjectionGround(
        "workload harm", VERIFIABLE,
        "queue depth, handling latency and the agent's in-flight work",
        "the metrics already record whether an agent is behind; an assertion of being busy is not "
        "the same as being measurably overloaded",
        "the capacity that would clear it - another slot for the role, a deferral until in-flight "
        "work completes, or a reprioritisation naming what should yield",
    ),
    ObjectionGround(
        "jurisdiction mismatch", VERIFIABLE,
        "the role charter's allowed and not_allowed lists",
        "charters already state what a role may and may not do, so whether work falls outside one "
        "is a lookup",
        "the role that should hold this work, or - if no role does - that the capability is missing "
        "and what a role holding it would be responsible for",
    ),
    ObjectionGround(
        "missing dependency", VERIFIABLE,
        "whether the referenced record exists",
        "a task naming a report, artifact or agent that is not there is decidable without opinion",
        "what would have to be produced first, and by whom. A dependency that does not exist "
        "anywhere is a component to build, not merely an absence to report",
    ),
    ObjectionGround(
        "unavailable resource", VERIFIABLE,
        "whether the required provider, model or data class is reachable",
        "the same check the harness already makes about model availability",
        "the substitute that would serve, or the degraded result obtainable without it, stated with "
        "what the degradation costs",
    ),
    ObjectionGround(
        "contradictory instructions", VERIFIABLE,
        "whether two governing requirements cannot both be satisfied",
        "contradiction is demonstrable by naming both requirements",
        "which requirement the objector believes should yield and why - a contradiction reported "
        "without a recommendation is half the analysis",
    ),
    ObjectionGround(
        "integrity or safety concern", JUDGED,
        "escalation to the owner",
        "the one ground that needs weighing rather than checking - an agent believing execution "
        "would cause harm is exactly the case where being wrong in either direction is expensive",
        "what would make the work safe to perform, if anything would. This is the one ground where "
        "'nothing would' is a legitimate remedy, and saying so explicitly is the point",
    ),
)

# Grounds needing a judge. Pinned, because the cheapest way to acquire a
# judiciary is to keep reclassifying checkable things as matters of opinion.
JUDGED_GROUND_COUNT = 1


def objection_grounds(kind: str | None = None) -> tuple:
    if kind is None:
        return OBJECTION_GROUNDS
    return tuple(ground for ground in OBJECTION_GROUNDS if ground.kind == kind)


# --- settling an objection --------------------------------------------------
#
# G7 settled who adjudicates by finding that most objections do not need one.
# This is that finding made executable: a checker reads the records and reports
# what they show.
#
# It lives here, in the module with no write path, on purpose. **The checker
# cannot settle anything.** It returns a Settlement describing what the records
# say, and a separate call with its own authority records it. Investigation
# proposes, and something else disposes - which is the same separation the
# read-only construction of this module already asserts, extended to the one
# mechanism most likely to erode it.

UPHELD = "upheld"          # the records agree with the objector; the work should not proceed
REJECTED = "rejected"      # the records contradict the objection; the work stands
UNSETTLED = "unsettled"    # nothing here can decide it, and why is stated


@dataclass(frozen=True)
class Settlement:
    """What the records say about an objection. Not a decision - a reading.

    `checked_by` distinguishes the three ways an outcome can be reached, because
    "the records settled it" and "nobody has built the check yet" are different
    facts and reporting them the same way would hide the second one."""

    outcome: str
    reason: str
    checked_by: str


RECORDS = "records"                # decided by reading what exists
OWNER = "owner"                    # needs judgment; escalates
NO_CHECKER = "no checker yet"      # verifiable in principle, unbuilt in practice


# Grounds that are decidable from records in principle but have no checker
# implemented, each with what is actually missing. Stated rather than left as an
# absence: an unchecked ground looks identical to a checked one that always
# returns UNSETTLED, and the difference is whether anyone knows work remains.
#
# Following the rule that an undefined response is a finding rather than an
# omission - the same discipline as the lifecycle catalogue's null responses.
UNCHECKED_GROUNDS = {
    "workload harm": (
        "queue depth and latency are recorded, but 'measurably overloaded' needs a threshold, and "
        "calibrating one against no measurement is how every wrong timing constant in this project "
        "got set. Blocked on the threshold-calibration work, not on the query"
    ),
    "jurisdiction mismatch": (
        "charters state scope in prose. Matching a directive against prose is not a check, it is a "
        "guess with a lookup in it. Needs charters to carry a machine-readable scope first"
    ),
    "unavailable resource": (
        "a probe exists (simulation.harness.model_is_available) but lives in the simulation layer, "
        "and backend must not depend on it. Needs a backend-level resource probe"
    ),
    "contradictory instructions": (
        "requires naming both requirements and showing they cannot both hold. Decidable by a reader, "
        "not by anything that exists to read them"
    ),
}

# Pinned. The gap between "verifiable in principle" and "checkable today" is a
# number, so it cannot quietly stay where it is: closing one requires editing
# this count, and opening a new one requires the same.
UNCHECKED_GROUND_COUNT = 4
CHECKED_GROUND_COUNT = 1


def _check_missing_dependency(conn: Database, directive: dict) -> Settlement:
    """Does the record this work refers to actually exist?

    The one ground with a real instance in the running system: the Controller
    already refuses to retire or resume an identity it cannot find, and recorded
    that as a *failure* - conflating "the executor broke" with "the order named
    something that is not there". The second is an objection, and it is settled
    by looking."""
    identity = directive.get("target_identity")
    if not identity:
        return Settlement(
            UNSETTLED,
            "the directive names no target identity, so there is no referenced record to look for",
            NO_CHECKER,
        )

    row = conn.fetchone("SELECT identity FROM agent_registry WHERE identity = ?", (identity,))
    if row is None:
        return Settlement(UPHELD, f"no agent is registered as {identity}", RECORDS)
    return Settlement(REJECTED, f"{identity} is registered; the dependency exists", RECORDS)


_CHECKERS = {"missing dependency": _check_missing_dependency}


def check_objection(conn: Database, ground: str, directive: dict) -> Settlement:
    """Read the records and report what they say about an objection.

    Three outcomes and no fourth. A judged ground escalates to the owner; a
    verifiable ground with no checker says so and names what is missing; a
    verifiable ground with a checker gets checked."""
    known = {g.name: g for g in OBJECTION_GROUNDS}
    if ground not in known:
        raise ValueError(f"unknown objection ground: {ground!r}")

    if known[ground].kind == JUDGED:
        return Settlement(UNSETTLED, known[ground].decided_by, OWNER)

    checker = _CHECKERS.get(ground)
    if checker is None:
        return Settlement(UNSETTLED, UNCHECKED_GROUNDS[ground], NO_CHECKER)
    return checker(conn, directive)
