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
from backend import governed_knowledge, operating_context, parliament

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
    return {
        **state,
        "governance_conflicts": unsettled,
        "refusals_by_instrument": refusing,
        # Named individually so a reader is not left to infer which resolutions
        # are outstanding from a count.
        "open_resolution_titles": [item["title"] for item in open_items],
        "articles_versions": len(parliament.articles_history(conn)),
        # The Speaker's own words about the state it found, so a surface has
        # something to render that is a statement rather than a number.
        "says": _say(state, open_items, unsettled, refusing),
    }


def _say(state: dict, open_items: list, unsettled: list, refusing: dict) -> str:
    if not state["articles_in_force"]:
        return ("Parliament stands ready and has no Articles. There is no roll, so nothing "
                "can be put to a vote until the owner adopts the founding text.")
    parts = [f"The Articles are in force at version {state['articles_version']}."]
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
