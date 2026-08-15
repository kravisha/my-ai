"""Trivial agent for proving the control plane (Controller spawn/retire
mechanics) actually works, before any real Explorer/Speculator/Analysis
logic exists (addendum 10 Phase A+B). Does nothing but heartbeat and wait
to be retired - the only agent built in this first increment.

Run directly as: python -m agents.dummy <identity>
Normally launched by backend/controller.py as a subprocess, not by hand.
"""

import sys

from agents.base import run_agent

ROLE = "dummy"


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.dummy <identity>", file=sys.stderr)
        raise SystemExit(1)
    run_agent(identity=sys.argv[1], role=ROLE)


if __name__ == "__main__":
    main()
