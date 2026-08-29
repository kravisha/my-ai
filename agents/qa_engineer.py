"""The QA / Test Engineer (TASK_QUEUE TQ-106; addendum 53 §5, §5.3, §11;
docs/SPEC_RECONCILIATION.md §149, §151).

Addendum 53 §5.1: *"Passing tests are not sufficient evidence of correctness."*

## What this agent does, and where the rest of QA's capability lives

It surfaces issues waiting on §6 step 7 - adversarial verification - and **it does
not verify them.** Step 7 requires somebody to construct the bad state and observe
the failure; an agent that marked a safeguard proven because a scan completed
would be manufacturing the evidence the scan exists to look for.

§5.3's third question - *has the tripwire actually been observed failing under
that condition?* - is answered from the scenario run history, and that reader is
`simulation/property_history.py` rather than a function here.

**It was written here first and a tripwire refused it.**
`test_no_agent_can_tell_it_is_in_a_simulation`: *"an agent has one code path, and
what changes between training and production is what answers its call."* An agent
that reads `simulation/runs` knows it is being simulated. The capability is QA's;
the data is the harness's, so the QA role invokes that reader when auditing rather
than on a work cycle (§151).
"""

from __future__ import annotations

import sys

from agents.base import run_agent
from backend import software_department

ROLE = "qa_engineer"


def _qa_work(conn, identity: str) -> None:
    """Surface what is waiting on adversarial verification.

    **It does not verify.** §6 step 7 requires somebody to construct the bad state
    and observe the failure; an agent that marked a safeguard proven because a
    scan completed would be manufacturing the evidence the scan looks for."""
    reviewed = _review_waiting_issues(conn, identity)
    if reviewed:
        print(f"[qa] filed the verification perspective on {reviewed} issue(s)")

    waiting = [row for row in software_department.open_issues(conn)
               if row["status"] == software_department.STATUS_CORRECTED]
    for issue in waiting:
        print(f"[qa] issue {issue['id']} on {issue['component']} awaits adversarial "
              f"verification: a test observed failing under the bad state (53 §5.3)")


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print("usage: python -m agents.qa_engineer <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]

    def work_fn(conn) -> None:
        _qa_work(conn, identity)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()


def _verification_perspective(conn, issue) -> str:
    """Why the tests did not catch this — from facts, never from a guess.

    §2's third question is the one nobody was asking (§149 §4), and it is also the
    easiest to answer with a plausible sentence. So this answers only what the
    backend can establish:

    - **was the column contracted at all?** `vocabulary.allowed` knows. An
      uncontracted column is one no audit could have covered, which is a complete
      and useful answer to *why did nothing catch it*.
    - **is there a validated write path?** A vocabulary that is only checked on
      read is one the write side is free to invent, which is how `'answered'`
      survived.

    Where neither applies, it says the question is open rather than inventing a
    reason. **A fabricated verification perspective is worse than a missing one**:
    it satisfies the gate that exists to make somebody look."""
    from backend import vocabulary

    evidence = issue["evidence"] or ""
    for (table, column) in vocabulary.CONTRACT:
        if table in evidence or table in (issue["component"] or ""):
            return (
                f"{table}.{column} is in the vocabulary contract and the audit covers it, so a "
                f"literal outside the contract fails the suite. If this issue was opened by that "
                f"audit, the safeguard worked; if not, the audit does not reach this shape and "
                f"that is the gap.")
    return (
        f"No vocabulary contract covers {issue['component']}, so no audit could have caught this. "
        f"Whether a test *should* have is open and needs somebody to look - this perspective "
        f"reports what the backend can establish and does not guess at the rest.")


def _review_waiting_issues(conn, identity: str) -> int:
    """File the verification perspective where one is missing.

    Never the implementation perspective, and never a correction: QA that wrote
    the fix could not then verify it (§5.2), and this agent exists on the other
    side of that line."""
    from backend import software_department

    filed = 0
    for issue in software_department.open_issues(conn):
        if issue["root_cause"] is not None:
            continue
        if software_department.PERSPECTIVE_VERIFICATION not in \
                software_department.missing_perspectives(conn, issue["id"]):
            continue
        software_department.review(
            conn, issue["id"],
            perspective=software_department.PERSPECTIVE_VERIFICATION,
            reviewer=identity, finding=_verification_perspective(conn, issue))
        filed += 1
    return filed
