"""Head of Strategy.

Speaks for the department and only from its own records. Thin on purpose: what
Stage 1 needs is that the role exists, is connected and can be exercised, and a
head that summarises its department and can be interviewed about it is that.

The Speaker is the precedent - it reads the state of Parliament and files a
report as its ordinary work, and appearing to discuss it is that job with an
audience. This is the same job one department along.

Run directly as: python -m agents.strategy_head <identity>
"""

from __future__ import annotations

import sys

from agents.base import run_agent
from backend import departments
from backend.department_desk import report_department

ROLE = "strategy_head"
DEPARTMENT = departments.STRATEGY


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print(f"usage: python -m agents.{ROLE} <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]

    def work_fn(conn) -> None:
        report_department(conn, department=DEPARTMENT, identity=identity, role=ROLE)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()
