"""The Speaker of the Parliament: its voice, and the only one it has
(TASK_QUEUE TQ-81; addendum 32 §10; docs/SPEC_RECONCILIATION.md §123, §124).

Owner direction, 2026-08-27:

> *"lets add a speaker for the parliament who is also the spokesperson and the
> speaker will answer all status updates about the parliament - if not the agent
> should be reporting and not the system."*

TQ-81 built Parliament and then had the **web server** describe it: the console
queried the tables and rendered them. That works and it is the wrong shape. The
organization's account of its own governance was being produced by a narrator
with no role in the story, no accountability for what it said, and - the part
that matters - no possible silence.

**A report has an author, a time, and an absence that can be noticed.** A query
has none of those. A query answers correctly whether anyone is minding Parliament
or not, so a console built on queries looks identical when nobody is.

## What the Speaker may do, and what it may not

It reads the state of Parliament and files a report. That is all of it.

It does not propose, vote, close a resolution, adopt Articles, escalate, or
resolve an escalation. This is not a matter of habit: `tests/test_speaker.py`
asserts that this module never calls those functions, because a spokesperson who
can also legislate is not reporting on a body, it *is* the body.

The asymmetry is deliberate and it is addendum 32's own: §10 seats the Speaker at
the session as its convenor and voice. Nothing there gives that seat a vote.

## Silence is information

If the Speaker stops, `latest_speaker_report` keeps returning the last thing it
said, with the time it said it - and the console shows that age rather than
substituting a fresh query. A stale report is a visible fact about the
organization. A fresh query over a dead Speaker is a comfortable fiction.

Run directly as: python -m agents.speaker <identity>
Normally spawned by the COO as part of the baseline population.
"""

from __future__ import annotations

import sys

from agents.base import run_agent
from backend import governed_knowledge, operating_context, parliament, release

ROLE = parliament.SPEAKER_ROLE


def compose_report(conn) -> dict:
    """What the Speaker has to say, from what Parliament currently is.

    Deliberately thin. The Speaker's value is not analysis - it is that somebody
    whose job this is looked, and can be found not to have looked."""
    state = parliament.summary(conn)
    open_items = parliament.open_resolutions(conn)
    # Addendum 46 §5 says a conflict between instruments is escalated *through
    # governance*. Governance's voice is this agent, so the Speaker is where a
    # subject with two equal authorities becomes visible to anybody (§125).
    # Read-only, like everything else here: it reports the conflict and has no
    # way to settle it, which is correct - settling it is a vote.
    unsettled = governed_knowledge.conflicts(conn)
    # What the organization's own rules have refused. Governance in action rather
    # than governance on paper, and the Speaker is where governance speaks (§124).
    refusing = operating_context.refusals_by_instrument(conn)
    # A release is a set of instruments carried by a resolution, so its state is
    # governance's business and the Speaker is where governance speaks. The case
    # this exists for is §130's, one level up: a change quietly making the
    # organization worse looks exactly like a change that is working, and a
    # release marked unhealthy that nobody surfaces is a rollback nobody performs.
    releases = release.summary(conn)
    return {
        **state,
        "releases": releases,
        "governance_conflicts": unsettled,
        "refusals_by_instrument": refusing,
        # Named individually so a reader is not left to infer which resolutions
        # are outstanding from a count.
        "open_resolution_titles": [item["title"] for item in open_items],
        "articles_versions": len(parliament.articles_history(conn)),
        "constitution_versions": len(parliament.constitution_history(conn)),
        # The Speaker's own words about the state it found, so a surface has
        # something to render that is a statement rather than a number.
        "says": _say(state, open_items, unsettled, refusing, releases),
    }


def _say(state: dict, open_items: list, unsettled: list, refusing: dict,
         releases: dict) -> str:
    if not state["articles_in_force"]:
        return ("Parliament stands ready and has no Articles. There is no roll, so nothing "
                "can be put to a vote until the owner adopts the founding text.")
    parts = [f"The Articles are in force at version {state['articles_version']}."]
    if state["constitution_in_force"]:
        # Said first among the substantive lines when it has moved: a level-0
        # change is the largest thing that can happen to this organization, and
        # a report that mentioned it after the open-resolution count would bury it.
        parts.append(
            f"The Constitution is in force at version {state['constitution_version']}.")
    else:
        parts.append(
            "No Constitution is in force. The genesis text is the owner's; until it "
            "exists there is nothing for a supermajority to amend.")
    parts.append(f"{len(open_items)} resolution(s) are open."
                 if open_items else "No resolution is open.")
    if state["outstanding_owner_escalations"]:
        parts.append(
            f"{state['outstanding_owner_escalations']} matter(s) are with the owner and "
            f"cannot be settled here.")
    if unsettled:
        parts.append(
            f"{len(unsettled)} subject(s) have two instruments of equal authority and "
            f"nothing may choose between them: {', '.join(c['subject'] for c in unsettled)}.")
    if refusing:
        # Reported, not judged. No threshold is invented here: what counts as too
        # many refusals depends on what the instrument is for, and a number
        # nobody measured would be a policy wearing a measurement's clothes.
        worst = max(refusing, key=refusing.get)
        parts.append(
            f"Instruments in force have refused {sum(refusing.values())} submission(s); "
            f"instrument {worst} accounts for {refusing[worst]} of them.")
    if releases["unhealthy_in_force"]:
        # Named, and said before the unbuilt-machinery line, because this is the
        # one thing in the report somebody has to act on today.
        parts.append(
            f"{len(releases['unhealthy_in_force'])} release(s) are in force and marked "
            f"unhealthy: {', '.join(releases['unhealthy_in_force'])}. Each has a way back "
            f"authorised already and nobody has taken it.")
    if releases["unjudged_in_force"]:
        # Unjudged is not passing. §118: absence of complaint is not evidence.
        parts.append(
            f"{len(releases['unjudged_in_force'])} release(s) are in force and nobody has "
            f"judged whether they worked: {', '.join(releases['unjudged_in_force'])}.")
    if releases["rolled_back"]:
        parts.append(
            f"{len(releases['rolled_back'])} release(s) were rolled back and are kept: "
            f"{', '.join(releases['rolled_back'])}.")
    parts.append("Elections, ministers, committees and the weekly session are not built.")
    return " ".join(parts)


def _speaker_work(conn, identity: str) -> None:
    parliament.record_speaker_report(
        conn, speaker_identity=identity, report=compose_report(conn))


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print("usage: python -m agents.speaker <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]

    def work_fn(conn) -> None:
        _speaker_work(conn, identity)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()
