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
