"""The Software Engineer: one general type, many roles (TASK_QUEUE TQ-83;
addendum 46 §7-§13, §21; docs/SPEC_RECONCILIATION.md §119, §137).

Addendum 46 §9 asks for *"one primary general-purpose Software Engineer agent
type"* rather than a catalog of specialists, and §11 says roles describe
responsibilities rather than implementations. This is that type. Project manager,
architect, reviewer and tester are things an instance *does*, not classes it
belongs to - §119 adjudicated that in this system's favour and this is the first
role built under it.

## What it does, which is less than the name suggests

It takes an authorized directive, works out how the organization's stated outcome
would be enforced, and either **proposes an instrument** or **says the
architecture lacks the mechanism**.

It does not write code. §8's ladder puts code last and calls it the case where
*"the existing architecture genuinely lacks the mechanism required"*; an engineer
that reaches that rung names the gap and stops. Naming it is the work.

## Why it does not approve its own proposal

Addendum 46 §11: *"The agent that produces a change should not be the sole
authority that approves the same change."* So this agent proposes and never
adopts. `backend/engineering.approve` refuses an approver that matches the
author, and this file never calls it - a test asserts both.

**That leaves proposals waiting for somebody who does not exist yet.** There is no
reviewer role, so nothing in the organization can currently approve one. That is
the honest state and it is better than the alternative: an engineer that adopted
its own work would satisfy §11 in wording and break it in fact.

## On demand, because work determines staffing

Addendum 46 §10: *"Work determines staffing. Staffing does not determine work."*
So this is `on_demand` like the Portfolio Analyst - it exists when there are
directives and produces nothing when there are none. A quiet cycle here means the
organization has asked for nothing, not that the department is broken, and
anything watching it has to know the difference (§117).

Run directly as: python -m agents.software_engineer <identity>
"""

from __future__ import annotations

import sys

from agents.base import run_agent
from backend import engineering

ROLE = engineering.ROLE


def handle(conn, directive: dict, *, engineer: str) -> dict:
    """One directive, from assessment to a proposal or a named gap.

    Returns what happened, so a caller - a test, a curriculum exercise - can see
    the judgement rather than infer it from the database."""
    level, reasoning = engineering.assess(directive)
    work_id = engineering.record_assessment(
        conn, directive["id"], engineer=engineer, level=level, reasoning=reasoning)

    if level == engineering.LEVEL_CODE:
        # Not a failure. §8 defines this rung as the architecture lacking the
        # mechanism, and a department that could never say so would report a data
        # solution for every problem - which is what §119 said to write the
        # metric against.
        engineering.record_needs_code(conn, work_id, detail=reasoning)
        return {"work_id": work_id, "level": level, "outcome": engineering.OUTCOME_NEEDS_CODE,
                "reasoning": reasoning}

    engineering.propose_instrument(
        conn, work_id, instrument=engineering.instrument_for(directive))
    return {"work_id": work_id, "level": level, "outcome": None, "reasoning": reasoning,
            "awaiting": "approval by somebody who is not the author (§11)"}


def _engineer_work(conn, identity: str) -> None:
    directive = engineering.claim_next(conn, identity)
    if directive is None:
        # Idle, and idle is correct: this role works when the organization has
        # asked for something (§10).
        return

    print(f"[software_engineer] taking directive {directive['id']}: {directive['title']}")
    result = handle(conn, directive, engineer=identity)
    if result["outcome"] == engineering.OUTCOME_NEEDS_CODE:
        print(f"[software_engineer] directive {directive['id']} needs a capability this "
              f"system does not have: {result['reasoning']}")
    else:
        print(f"[software_engineer] directive {directive['id']} can be met as governed data; "
              f"instrument proposed and awaiting an approver who is not me")


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print("usage: python -m agents.software_engineer <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]

    def work_fn(conn) -> None:
        _engineer_work(conn, identity)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()
