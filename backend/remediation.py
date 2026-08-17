"""What corrective work a finding actually calls for, and who can do it.

The framework asks that corrective rulings become ordinary tasks rather than a
parallel enforcement track. Two things had to be settled before that could be
built, and measurement settled both.

**Corrective work is per cause, not per finding.** A real run produced ten
findings that were one design gap - every analysis result graded by its own
producer. Ten tasks would have been ten wrong tasks: nine duplicates and one
misdirected.

**Whether an agent could have complied is measurable, not a matter of opinion.**
The framework's own rule is that many independent agents making the same error
implicates the system. The sharper form needs no threshold: **if every single
opportunity failed, the compliant path was not available.** Nobody could have
done otherwise, so nobody can be faulted, and the remedy belongs to whoever can
change the design. That was literally true of the ten - 10 of 10, share 1.0, with
one analysis agent in the run and nothing else able to grade it.

Below a share of 1.0 some agent did comply, which proves compliance was possible.
Between those two cases sits a judgment this module refuses to make from records
alone, and says so rather than guessing at a cutoff.

Read-only, like `compliance` and `governance`. Deciding what work is needed and
creating it are separate acts with separate authority.

Internal rationale: INT-PHIL-0028
"""

from __future__ import annotations

from dataclasses import dataclass

from backend import compliance
from backend.db import Database

# Every opportunity failed, so the compliant behaviour was never available. Not
# misconduct - a design defect, and the remedy is outside any agent's reach.
SYSTEMIC = "systemic"
# Some complied and some did not, which proves compliance was possible.
ATTRIBUTABLE = "attributable"
# Too few chances to tell the two apart. Stated, never guessed.
UNDETERMINED = "undetermined"

OWNER = "owner"


@dataclass(frozen=True)
class CorrectiveItem:
    """One piece of corrective work, covering every finding that shares a cause."""

    rule: str
    classification: str
    findings: int
    opportunities: int
    assigned_to: str
    statement: str
    rationale: str
    evidence_ref: str
    # Why this cannot currently be dispatched, empty when it can. Named rather
    # than left as silence: work that has nowhere to go looks exactly like work
    # nobody raised.
    blocked: str = ""


def classify(findings: int, opportunities: int) -> str:
    """Systemic, attributable, or not yet determinable - from counts alone.

    The only conclusive case is total failure, and it is conclusive without a
    threshold: if nothing ever complied, complying was not among the options."""
    if opportunities <= 1:
        return UNDETERMINED
    if findings >= opportunities:
        return SYSTEMIC
    return ATTRIBUTABLE


def _ruled_out(conn: Database) -> set:
    """Findings the organization has already decided need no correction.

    `accepted` is deliberately absent: accepting a finding means it is real and
    correction is expected, so it belongs in the work rather than out of it."""
    if not conn.fetchone(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'finding_dispositions'"
    ):
        return set()
    return {
        (row["rule"], row["item"])
        for row in conn.fetchall(
            "SELECT rule, item FROM finding_dispositions WHERE status = 'active' "
            "AND disposition IN ('false_positive', 'wont_fix')"
        )
    }


def corrective_items(conn: Database, limit: int = 200) -> list[CorrectiveItem]:
    """Group outstanding findings by cause and say what each one calls for."""
    report = compliance.check(conn, limit=limit)
    ruled_out = _ruled_out(conn)

    by_rule: dict[str, list[dict]] = {}
    for finding in report["unevaluated"] + report["self_evaluated"]:
        if (finding["rule"], str(finding["item"])) in ruled_out:
            continue
        by_rule.setdefault(finding["rule"], []).append(finding)

    items = []
    for rule, findings in sorted(by_rule.items()):
        opportunities = compliance.opportunity_count(conn, rule)
        classification = classify(len(findings), opportunities)
        items.append(_item(rule, findings, opportunities, classification))
    return items


def _item(rule: str, findings: list[dict], opportunities: int, classification: str) -> CorrectiveItem:
    producers = sorted({str(f.get("producer")) for f in findings})
    evidence = f"{rule}: {len(findings)} of {opportunities}"

    if classification == SYSTEMIC:
        return CorrectiveItem(
            rule=rule,
            classification=classification,
            findings=len(findings),
            opportunities=opportunities,
            assigned_to=OWNER,
            statement=f"{rule}: every completion failed the evaluation rule, so the design does not "
                      f"permit compliance",
            rationale=(
                f"all {opportunities} of {opportunities} failed. No agent chose this and none could "
                f"have chosen otherwise, so the remedy is a design change rather than corrective "
                f"work for {', '.join(producers)}"
            ),
            evidence_ref=evidence,
        )

    if classification == ATTRIBUTABLE:
        return CorrectiveItem(
            rule=rule,
            classification=classification,
            findings=len(findings),
            opportunities=opportunities,
            assigned_to=producers[0] if len(producers) == 1 else OWNER,
            statement=f"{rule}: {len(findings)} of {opportunities} completions carry no evaluation",
            rationale=(
                f"{opportunities - len(findings)} comparable completions did carry one, so "
                f"compliance was available here"
            ),
            evidence_ref=evidence,
            # The honest blocker, and G5 makes it demonstrable rather than
            # asserted: the Controller executes spawn, retire and resume, so a
            # corrective directive draws a jurisdiction objection. There is no
            # general task queue in this system.
            blocked=(
                "no queue carries corrective work. coo_directives is a lifecycle queue and the "
                "Controller objects to anything else on jurisdiction grounds. Building a general "
                "task queue is the remedy, and it is not yet justified: no attributable corrective "
                "work has been observed"
            ),
        )

    return CorrectiveItem(
        rule=rule,
        classification=classification,
        findings=len(findings),
        opportunities=opportunities,
        assigned_to=OWNER,
        statement=f"{rule}: {len(findings)} finding(s), too few completions to attribute",
        rationale=(
            f"{opportunities} completion(s) total. One case cannot distinguish an agent that failed "
            f"from a design that made compliance impossible"
        ),
        evidence_ref=evidence,
    )


def summarise(conn: Database) -> str:
    items = corrective_items(conn)
    if not items:
        return "no corrective work outstanding"
    lines = []
    for item in items:
        lines.append(
            f"{item.classification.upper():<13} {item.rule} "
            f"({item.findings}/{item.opportunities}) -> {item.assigned_to}"
        )
        lines.append(f"              {item.rationale}")
        if item.blocked:
            lines.append(f"              BLOCKED: {item.blocked}")
    return "\n".join(lines)
