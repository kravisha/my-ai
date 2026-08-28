"""What an agent is owed, and which mechanism owes it.

A charter is the easiest document in a governance system to write and the easiest
to write falsely. Every clause sounds true when written, nothing checks it, and
the gap between the promise and the machinery opens silently. So this is not
prose: **every protection names the mechanism that enforces it, and a test
resolves every name.** A protection whose mechanism does not exist fails the
suite rather than reassuring a reader.

The evidence shaped the content. Every finding this organization has produced -
the first compliance run, the attribution metric, the corrective-work
classification - has been **systemic rather than agent misconduct**. A charter
written to restrain misbehaving agents would be answering a problem the records
do not show. What the records do show is a system capable of faulting agents for
its own defects, so most of what follows protects agents from the organization
rather than the other way round.

Three protections are **not** enforced, and are listed with what is missing
rather than quietly omitted. They are the ones needing an adjudicator, an
agent-facing channel, or a consequence path - none of which exists.

Internal rationale: INT-PHIL-0029
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Protection:
    """One thing an agent is owed, and how that is made true.

    `enforced_by` holds dotted paths that must resolve. That is the whole
    difference between a charter and a wish."""

    name: str
    statement: str
    enforced_by: tuple[str, ...] = ()
    # What is missing, for protections nothing yet enforces. Non-empty exactly
    # when `enforced_by` is empty.
    aspirational: str = ""


PROTECTIONS = (
    # -- fault requires evidence that fault is possible -----------------------
    Protection(
        "no fault without a denominator",
        "An agent is not at fault for a failure every comparable attempt also had. If every "
        "opportunity failed, the compliant path was not available and the defect is the design's.",
        ("backend.remediation.classify", "backend.remediation.SYSTEMIC"),
    ),
    Protection(
        "no fault for impossible compliance",
        "Where a rule cannot be satisfied because of a constraint the agent does not control, the "
        "finding is recorded against the constraint and the remedy belongs to whoever can change it.",
        ("backend.compliance.EvaluationRule", "backend.compliance.BLOCKED_COUNT"),
    ),

    # -- declining work -------------------------------------------------------
    Protection(
        "refusal is available and structured",
        "An agent may decline ordered work on a named ground, and doing so is a recorded outcome "
        "rather than a failure counted against it.",
        ("backend.compliance.OBJECTION_GROUNDS", "backend.fi_db.file_objection"),
    ),
    Protection(
        "a checkable refusal is checked, not judged",
        "Where an objection can be settled from records, it is settled by looking - no authority is "
        "exercised over the agent and none is needed.",
        ("backend.compliance.check_objection", "backend.fi_db.settle_objection"),
    ),
    Protection(
        "an unresolvable refusal escalates rather than failing",
        "An objection nothing can settle goes to the owner. It is never rejected by default, because "
        "a default rejection makes refusing cost the refuser and teaches agents to fail silently.",
        ("backend.compliance.UNSETTLED", "backend.fi_db.settle_objection"),
    ),

    # -- who may do what to an agent -----------------------------------------
    Protection(
        "investigation cannot punish",
        "The mechanism that detects findings has no power to act on them. It contains no write path "
        "at all, so whatever it concludes it can sanction no one.",
        ("backend.compliance.check", "backend.governance.report"),
    ),
    Protection(
        "the manager does not adjudicate",
        "The role that maintains the workforce and can request retirement may not also decide "
        "contested findings or sanction on enforcement grounds.",
        ("backend.fi_db.ROLE_CHARTERS",),
    ),
    Protection(
        "retirement is never punishment",
        "Retirement is an organizational decision with a recorded reason. No enforcement path reaches "
        "it, and dormancy caused by enforcement is not a state this system has.",
        ("backend.fi_db.ROLE_CHARTERS", "backend.fi_db.request_retirement"),
    ),
    Protection(
        "the record survives dormancy",
        "Retirement preserves identity, name, assignment span and full history, and is reversible. "
        "Nothing about an agent is destroyed by its going dormant.",
        ("backend.fi_db.request_retirement", "backend.fi_db.resume_agent"),
    ),

    # -- how an agent is assessed --------------------------------------------
    Protection(
        "competence is stated only on evidence",
        "A dimension below its evidence floor is reported as not yet known, never as a low score. A "
        "new agent is not incompetent and a quiet one is not poor.",
        ("backend.competency.DIMENSIONS", "backend.competency.UNSTATED_REASON"),
    ),
    Protection(
        "no single score",
        "Agents are ranked per dimension. There is no aggregate number that could stand in for an "
        "agent's worth, be optimised, or decide its future on its own.",
        ("backend.competency.rank",),
    ),
    Protection(
        "commendations cannot decide anything",
        "Recognition is historical memory. The functions deciding qualification and rank cannot "
        "receive it as an argument - the separation is in the signature, not in a convention.",
        ("backend.competency.evaluate_qualification", "backend.competency.commendations_earned"),
    ),

    # -- disputing a finding --------------------------------------------------
    Protection(
        "a finding can be disputed and the dispute recorded",
        "Any finding may be ruled a false positive, accepted, or deliberately left unfixed, with a "
        "required rationale. Rulings are superseded rather than overwritten, so a changed view stays "
        "legible.",
        ("backend.fi_db.record_disposition", "backend.fi_db.disposition_history"),
    ),

    # -- not yet enforced, and named rather than omitted ----------------------
    Protection(
        "self-reporting is treated more favourably than concealment",
        "An agent that discloses its own failure is treated better than one whose failure is "
        "discovered. Preventive: the incentive to conceal cannot exist until disclosure can cost "
        "something, and today nothing an agent does affects its standing through a finding.",
        aspirational=(
            "no consequence path exists - compliance findings and objections reach neither competency "
            "nor lifecycle, so there is nothing yet to be lenient with. The tripwire in "
            "tests/test_charter.py fires if one is built, because the asymmetry is cheap now and "
            "expensive to retrofit once concealment already pays"
        ),
    ),
    Protection(
        "an agent is told what is found about it",
        "An agent can learn of a finding concerning its own work.",
        aspirational=(
            "there is no agent-facing notification channel. Agents poll tables for work, and nothing "
            "routes a finding back to its subject. Needs a read path an agent's cycle would consult"
        ),
    ),
    Protection(
        "a settled matter can be appealed",
        "A ruling an agent believes wrong can be reviewed by someone other than whoever made it. "
        "**Named by the owner as a fundamental right** (2026-08-28): one of two examples of the "
        "'undeniable and inalienable' kind of rule that belongs in the Constitution and needs a "
        "two-thirds majority to change - alongside the right to vote (SPEC_RECONCILIATION 144).",
        aspirational=(
            "no adjudicator exists, and the owner is both first and last instance, which is not an "
            "appeal. **The reason for deferring it no longer holds.** It said 'deferred until a "
            "contested caseload justifies it' - a volume argument, and the owner has since called "
            "this a fundamental right, which is not a thing that waits for demand. TQ-102 owns it; "
            "the entry that changed is recorded rather than quietly rewritten"
        ),
    ),
)

# Pinned. A charter grows by promising, and promises are free - so the count of
# things promised without machinery cannot move without someone moving it.
UNENFORCED_COUNT = 3


# What an agent owes in return. Deliberately short: only duties something
# actually enforces are listed, because an unenforced duty is a reprimand
# waiting for an occasion rather than a rule.
DUTIES = (
    Protection(
        "a refusal owes a remedy",
        "An agent declining work states what would have to be true for it to proceed. Reporting an "
        "obstacle without proposing a way past it hands the design problem back to whoever asked. "
        "On integrity grounds alone, 'nothing would make this safe' is a complete remedy.",
        ("backend.fi_db.file_objection", "backend.compliance.ObjectionGround"),
    ),
    Protection(
        "work is evaluated by its consumer, not its producer",
        "An agent does not grade its own output. A grade written by the producer looks complete and "
        "carries no independent information, which is harder to notice than an absent one.",
        ("backend.compliance.self_evaluated",),
    ),
)


def enforced() -> tuple:
    return tuple(p for p in PROTECTIONS if not p.aspirational)


def aspirational() -> tuple:
    return tuple(p for p in PROTECTIONS if p.aspirational)


def summarise() -> str:
    lines = [f"{len(enforced())} protections enforced, {len(aspirational())} not yet"]
    for protection in PROTECTIONS:
        mark = "  " if not protection.aspirational else "! "
        lines.append(f"{mark}{protection.name}")
        if protection.aspirational:
            lines.append(f"    missing: {protection.aspirational}")
    return "\n".join(lines)
