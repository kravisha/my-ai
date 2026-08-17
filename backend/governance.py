"""Metrics that can indict the governance layer itself.

Ordinary metrics measure the agents. These measure the machinery that judges the
agents, which is a different question and a harder one to want to ask. The
governing framework asks for it before adjudication rather than after, so that
if a courtroom is ever built there is already evidence about whether the
processes feeding it work.

**Every metric here names a specific way the governance layer fails**, because a
number nobody could act on is decoration. Four failures, in the order they are
most likely:

    the check quietly stops covering things   a new completion path with no rule
    escalation becomes a dead letter box      objections raised and never resolved
    filing becomes free, or becomes punished  every objection upheld, or none
    findings blame agents for the system      violations nobody could have prevented

The last is the one worth stating plainly. The first real compliance run produced
three findings, and **none was an agent failing to do something it could have
done** - one was the check's own false positive, one a schema constraint, one a
design gap. A governance layer that reported those as agent misconduct would have
punished three agents for the specification's mistakes.

Read-only, like `compliance`, and for the same reason: a module that measures the
governors must not also be able to act on them.

Internal rationale: INT-PHIL-0026
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from backend import compliance
from backend.db import Database

# Below this many settled objections, the settlement mix is not stated at all.
# A rate over three cases is not a rate.
#
# Provisional, and labelled as such: the honest value comes from watching real
# settlements accumulate, and setting it by plausibility is the mistake that made
# three timing constants in this project wrong. Matches the floor `competency.py`
# uses for its own rates, so the two are wrong together rather than differently.
MIN_SETTLEMENTS_TO_CHARACTERISE = 10

UNSTATED = "not enough evidence yet"

# An objection has left the queue, whichever way it went. 'escalated' counts as
# settled *by this mechanism* even though the owner has not answered: the
# question here is whether the checking layer disposed of it, and the waiting is
# measured separately by escalation_backlog.
SETTLED_STATUSES = ("upheld", "rejected", "escalated")


def _completion_tables(conn: Database) -> list[str]:
    """Read from the live database rather than from the declared schema.

    Deliberate: the question is whether the check covers the work this system
    actually completes, and a table present in a running database is work being
    completed whether or not anything declared it."""
    return [
        row["name"]
        for row in conn.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%\\_completed' "
            "ESCAPE '\\' ORDER BY name"
        )
    ]


def path_coverage(conn: Database) -> dict:
    """Completion paths with no evaluation rule.

    **The failure this detects:** a compliance check silently stops covering the
    organization. Adding a new kind of completed work is ordinary; remembering to
    add a rule for it is the step that gets missed, and the check keeps passing
    because it never looks. A governance layer that passes by not looking is
    worse than none, since it also supplies the reassurance."""
    covered = {rule.table for rule in compliance.EVALUATION_RULES}
    tables = _completion_tables(conn)
    uncovered = [table for table in tables if table not in covered]
    return {
        "completion_paths": len(tables),
        "uncovered": uncovered,
        "covered": len(tables) - len(uncovered),
    }


def checker_coverage() -> dict:
    """Verifiable objection grounds that have a checker built.

    **The failure this detects:** escalation caused by unbuilt machinery being
    mistaken for a genuine need to appoint a judge. Four of five verifiable
    grounds currently escalate for want of a checker, which from the outside looks
    exactly like a caseload demanding an adjudicator - and the answer is to build
    the checkers, not to build a court."""
    verifiable = len(compliance.objection_grounds(compliance.VERIFIABLE))
    return {
        "verifiable_grounds": verifiable,
        "with_checker": compliance.CHECKED_GROUND_COUNT,
        "without_checker": compliance.UNCHECKED_GROUND_COUNT,
        "missing": dict(compliance.UNCHECKED_GROUNDS),
    }


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def escalation_backlog(conn: Database, now: datetime | None = None) -> dict:
    """Objections waiting on the owner, and how long the oldest has waited.

    **The failure this detects:** escalation as a dead letter box. The whole
    settlement design rests on unresolvable objections going to the owner rather
    than being rejected by default - and if nothing drains that queue, the design
    has quietly become "refusal with extra steps", which is the outcome it was
    built to avoid.

    Reports the age; states no threshold. There is no honest number yet for how
    long is too long, and the measurement that would produce one is the owner's
    observed turnaround, which has not happened."""
    # A database created before objections existed has nothing waiting, which is
    # different from crashing. Governance is read against run databases of every
    # vintage, so every table it touches has to be optional.
    if not _table_exists(conn, "objections"):
        return {"waiting": 0, "oldest_seconds": None, "grounds": {}}

    escalated = conn.fetchall("SELECT * FROM objections WHERE status = 'escalated' ORDER BY id")
    if not escalated:
        return {"waiting": 0, "oldest_seconds": None, "grounds": {}}

    moment = now or datetime.now(timezone.utc)
    ages = [(moment - _parse(row["filed_at"])).total_seconds() for row in escalated]
    grounds: dict[str, int] = {}
    for row in escalated:
        grounds[row["ground"]] = grounds.get(row["ground"], 0) + 1

    return {
        "waiting": len(escalated),
        "oldest_seconds": round(max(ages), 1),
        "grounds": grounds,
    }


def settlement_mix(conn: Database) -> dict:
    """How filed objections were settled.

    **The failures this detects, two of them, in opposite directions.** If every
    objection is upheld, filing one costs nothing and the check is decoration -
    an executor could decline any work it disliked. If none is ever upheld,
    objecting is punished and agents learn to fail silently instead, which is
    strictly worse because a silent failure carries no ground, no evidence and no
    remedy.

    Refuses to state a mix below the evidence floor. Reporting "100% upheld" over
    two cases would invite exactly the over-reading the floor exists to prevent -
    and 'absent is not zero' applies to the governors as much as to the agents."""
    rows = (
        conn.fetchall("SELECT status, COUNT(*) AS n FROM objections GROUP BY status")
        if _table_exists(conn, "objections") else []
    )
    counts = {row["status"]: row["n"] for row in rows}
    settled = sum(n for status, n in counts.items() if status in SETTLED_STATUSES)

    mix = {
        "filed_total": sum(counts.values()),
        "by_status": counts,
        "settled": settled,
    }
    if settled < MIN_SETTLEMENTS_TO_CHARACTERISE:
        mix["upheld_rate"] = None
        mix["reason"] = f"{UNSTATED}: {settled} settled, floor is {MIN_SETTLEMENTS_TO_CHARACTERISE}"
    else:
        mix["upheld_rate"] = round(counts.get("upheld", 0) / settled, 3)
    return mix


def finding_attribution() -> dict:
    """Of the evaluation rules, how many produce findings no agent could prevent.

    **The failure this detects:** a governance layer that blames agents for the
    specification. One rule is exempt because its consumer is a person and nothing
    lets a human record an evaluation; one is blocked because a NOT NULL
    constraint makes compliance impossible. Neither is misconduct, and an
    enforcement mechanism that could not tell the difference would punish agents
    for constraints they cannot satisfy.

    The framework asks this question itself - agent failure or system failure -
    and asks it *before* assigning fault. This is that question as a number."""
    total = len(compliance.EVALUATION_RULES)
    structural = compliance.EXEMPT_COUNT + compliance.BLOCKED_COUNT
    return {
        "rules": total,
        "structural": structural,
        "attributable_to_agents": total - structural,
    }


def disposition_health(conn: Database) -> dict:
    """How findings are being ruled on, and whether the rulings are reasoned.

    **The failure this detects:** `false_positive` used as an off switch. It is
    the disposition that says the governance layer erred, which is necessary to
    have and irresistible to overuse - the cheapest way to make a compliance
    check stop complaining is to keep deciding it was wrong.

    Also watches for rulings with rationales too thin to review. A required
    field satisfied by a single word is a required field in name only, and that
    is how a governance record becomes unauditable without ever being empty.

    No threshold on the false-positive share. A check finding real problems and
    a check that is badly written both produce false positives, and telling them
    apart needs the rationales read - which is a person's job, and the reason
    this reports rather than judges."""
    if not _table_exists(conn, "finding_dispositions"):
        return {"total": 0, "by_disposition": {}, "false_positive_share": None, "thin_rationales": 0}

    rows = conn.fetchall(
        "SELECT disposition, rationale FROM finding_dispositions WHERE status = 'active'"
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1

    total = len(rows)
    return {
        "total": total,
        "by_disposition": counts,
        "false_positive_share": (
            round(counts.get("false_positive", 0) / total, 3) if total else None
        ),
        "thin_rationales": sum(1 for row in rows if len(row["rationale"].strip()) < 30),
        "revised": conn.fetchone(
            "SELECT COUNT(*) AS n FROM finding_dispositions WHERE status = 'superseded'"
        )["n"],
    }


def _table_exists(conn: Database, table: str) -> bool:
    return conn.fetchone(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ) is not None


# --- machinery deliberately not built ---------------------------------------
#
# The framework asks for adjudication, precedent, appeal, rehabilitation and a
# progressive sanctions ladder. None is built, and the reason is the same in
# every case: **the conditions that would justify them have never occurred.**
# Building a court before there is a dispute is the failure this whole series has
# been avoiding, and the framework's own rule agrees - adjudicate only when an
# exception genuinely requires it.
#
# But a deferral nobody can detect becoming due is not a deferral, it is an
# omission with better wording. So each one carries a trigger, and the triggers
# that can be evaluated from records are evaluated here every time governance is
# reported.
#
# Three kinds, because they can fail differently:
#
#   existence      fires the first time the condition occurs. No threshold, so
#                  nothing to invent and nothing to get wrong
#   prerequisite   cannot fire until something else exists. Watching it now would
#                  be watching for a phenomenon the system cannot produce
#   unformulable   the trigger needs a measurement nobody has taken. Stated as
#                  such rather than given a plausible number
#
# Internal rationale: INT-PHIL-0030

EXISTENCE = "existence"
PREREQUISITE = "prerequisite"
UNFORMULABLE = "unformulable"


@dataclass(frozen=True)
class Deferred:
    """A capability not built, and what would say it is time."""

    name: str
    what: str
    trigger: str
    kind: str
    # For unformulable triggers: the measurement that would produce one.
    needs: str = ""


DEFERRED = (
    Deferred(
        "general task queue",
        "A queue carrying corrective work to the agent that should do it. coo_directives is a "
        "lifecycle queue and the Controller objects to anything else on jurisdiction grounds.",
        "corrective work appears that is attributable to an agent rather than to the design",
        EXISTENCE,
    ),
    Deferred(
        "checkers for the remaining verifiable grounds",
        "Automated settlement for the four objection grounds decidable from records in principle but "
        "having no checker.",
        "an objection is filed on a ground that has no checker",
        EXISTENCE,
    ),
    Deferred(
        "precedent",
        "A record of how like cases were decided, so alike findings are treated alike.",
        "the same rule receives two different dispositions, which is the first moment consistency "
        "becomes a question anyone could answer wrongly",
        EXISTENCE,
    ),
    Deferred(
        "agent-facing notification",
        "A path by which an agent learns of a finding about its own work.",
        "a finding exists that an agent could have acted on - until then there is nothing to tell an "
        "agent that it could do anything about",
        EXISTENCE,
    ),
    Deferred(
        "rehabilitation",
        "A path by which an agent whose standing was reduced recovers it.",
        "an agent's standing is reduced by a finding",
        PREREQUISITE,
        needs="no consequence path exists; see the charter's self-reporting protection and its tripwire",
    ),
    Deferred(
        "progressive sanctions",
        "A graduated ladder of responses to repeated findings.",
        "findings become attributable to agents and recur for the same agent",
        PREREQUISITE,
        needs="no finding has ever been attributable to an agent, so there is nothing to escalate",
    ),
    Deferred(
        "appeal",
        "Review of a ruling by someone other than whoever made it.",
        "an adjudicator exists whose rulings could be appealed to someone else",
        PREREQUISITE,
        needs="the owner is currently both first and last instance, so an appeal has nowhere to go",
    ),
    Deferred(
        "an adjudicator",
        "A role empowered to decide contested findings.",
        "escalation to the owner proves insufficient - not merely that cases exist, but that the "
        "owner's disposition of them is contested or cannot keep up",
        UNFORMULABLE,
        needs="the owner's turnaround on escalated objections has never been observed, because no "
              "objection has yet escalated. Until then any threshold would be invented, and every "
              "invented threshold in this project has been wrong",
    ),
)

# Pinned. Deferral is the cheapest decision available and the easiest to make
# permanently, so the count of things put off cannot move without someone moving
# it.
DEFERRED_COUNT = 8
UNFORMULABLE_COUNT = 1


def _due_general_task_queue(conn: Database) -> str:
    from backend import remediation

    attributable = [
        item for item in remediation.corrective_items(conn)
        if item.classification == remediation.ATTRIBUTABLE
    ]
    if not attributable:
        return ""
    return (
        f"{len(attributable)} corrective item(s) are attributable to an agent and have nowhere to be "
        f"sent: {', '.join(item.rule for item in attributable)}"
    )


def _due_checkers(conn: Database) -> str:
    if not _table_exists(conn, "objections"):
        return ""
    unchecked = set(compliance.UNCHECKED_GROUNDS)
    rows = conn.fetchall("SELECT ground, COUNT(*) AS n FROM objections GROUP BY ground")
    arriving = {row["ground"]: row["n"] for row in rows if row["ground"] in unchecked}
    if not arriving:
        return ""
    return (
        "objections are arriving on grounds with no checker, so they escalate for want of machinery: "
        + ", ".join(f"{ground} x{n}" for ground, n in sorted(arriving.items()))
    )


def _due_precedent(conn: Database) -> str:
    if not _table_exists(conn, "finding_dispositions"):
        return ""
    rows = conn.fetchall(
        "SELECT rule, COUNT(DISTINCT disposition) AS kinds FROM finding_dispositions "
        "WHERE status = 'active' GROUP BY rule HAVING kinds > 1"
    )
    if not rows:
        return ""
    return (
        "the same rule has received different dispositions ("
        + ", ".join(row["rule"] for row in rows)
        + "), so like cases are being treated unlike and nothing records why"
    )


def _due_notification(conn: Database) -> str:
    from backend import remediation

    actionable = [
        item for item in remediation.corrective_items(conn)
        if item.classification == remediation.ATTRIBUTABLE
    ]
    if not actionable:
        return ""
    return (
        "a finding exists that an agent could act on, and no path tells the agent about it"
    )


_DUE_CHECKS = {
    "general task queue": _due_general_task_queue,
    "checkers for the remaining verifiable grounds": _due_checkers,
    "precedent": _due_precedent,
    "agent-facing notification": _due_notification,
}


def due(conn: Database) -> list[dict]:
    """Deferred capabilities whose trigger has fired.

    Only existence triggers are evaluated. A prerequisite trigger cannot fire
    while its prerequisite is absent, and watching for it would be watching for a
    phenomenon the system cannot produce - the mistake of building a detector for
    something that cannot happen, which this project has made before."""
    fired = []
    for capability in DEFERRED:
        if capability.kind != EXISTENCE:
            continue
        check = _DUE_CHECKS.get(capability.name)
        evidence = check(conn) if check else ""
        if evidence:
            fired.append({
                "capability": capability.name,
                "what": capability.what,
                "evidence": evidence,
            })
    return fired


def report(conn: Database) -> dict:
    return {
        "path_coverage": path_coverage(conn),
        "checker_coverage": checker_coverage(),
        "escalation_backlog": escalation_backlog(conn),
        "settlement_mix": settlement_mix(conn),
        "finding_attribution": finding_attribution(),
        "disposition_health": disposition_health(conn),
        "deferred_due": due(conn),
    }


def concerns(conn: Database) -> list[str]:
    """What is currently wrong with the governance layer, stated only where the
    evidence supports it.

    Deliberately not a score. A single governance health number would be the
    first thing optimised and the last thing understood - the same reasoning that
    keeps competency per-dimension."""
    found = []
    data = report(conn)

    for table in data["path_coverage"]["uncovered"]:
        found.append(
            f"{table} records completed work and no evaluation rule covers it, so the compliance "
            "check passes on it by not looking"
        )

    backlog = data["escalation_backlog"]
    if backlog["waiting"]:
        found.append(
            f"{backlog['waiting']} objection(s) escalated and unresolved, oldest waiting "
            f"{backlog['oldest_seconds']:.0f}s. Escalation is the design's release valve; unattended "
            "it becomes refusal with extra steps"
        )

    coverage = data["checker_coverage"]
    if coverage["without_checker"]:
        found.append(
            f"{coverage['without_checker']} of {coverage['verifiable_grounds']} verifiable grounds "
            "have no checker, so they escalate for want of machinery rather than for want of a judge"
        )

    for fired in data["deferred_due"]:
        found.append(
            f"deferred capability {fired['capability']!r} has come due: {fired['evidence']}"
        )

    thin = data["disposition_health"]["thin_rationales"]
    if thin:
        found.append(
            f"{thin} finding disposition(s) carry a rationale too short to review. A required field "
            "satisfied by a word is a required field in name only"
        )

    mix = data["settlement_mix"]
    if mix["upheld_rate"] is not None:
        if mix["upheld_rate"] == 1.0:
            found.append("every objection has been upheld; filing one currently costs nothing")
        elif mix["upheld_rate"] == 0.0:
            found.append(
                "no objection has ever been upheld; agents that learn this will fail silently "
                "instead, which carries no ground, no evidence and no remedy"
            )
    return found


def summarise(conn: Database) -> str:
    data = report(conn)
    lines = [
        f"paths covered:    {data['path_coverage']['covered']}/{data['path_coverage']['completion_paths']}",
        f"checkers built:   {data['checker_coverage']['with_checker']}/{data['checker_coverage']['verifiable_grounds']} verifiable grounds",
        f"escalated:        {data['escalation_backlog']['waiting']} waiting on the owner",
        f"objections filed: {data['settlement_mix']['filed_total']}"
        + (f", {data['settlement_mix']['upheld_rate']:.0%} upheld"
           if data["settlement_mix"]["upheld_rate"] is not None
           else f" ({data['settlement_mix'].get('reason', UNSTATED)})"),
        f"findings agents could prevent: {data['finding_attribution']['attributable_to_agents']}"
        f"/{data['finding_attribution']['rules']} rules",
    ]
    for concern in concerns(conn):
        lines.append(f"  CONCERN  {concern}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Owner-run on purpose, and not wired into any agent's cycle.
    #
    # The obvious host is COO, which already judges intelligence health - and
    # that is the reason not to. COO maintains the workforce, requests
    # retirement, and acts for the vacant CEO; handing it the numbers that
    # measure the governance layer would put the assessment of the governors
    # inside the role the assessment most needs to cover.
    #
    # So this reports to the owner, who is the only independent party that
    # exists. A metrics module nobody runs would be the "table nothing writes to"
    # error at module scale, and a command is the cheapest thing that is not that.
    import sys

    from backend import fi_db

    connection = fi_db.get_connection(sys.argv[1] if len(sys.argv) > 1 else None)
    try:
        print(summarise(connection))
    finally:
        connection.close()
