"""Producer: builds the run of show, so the anchor does not have to.

The station's control room. Each cycle it reads what the organization has done,
files stories against the records that prove them, writes the scripts, books the
agent each story is about, and cuts a news flash into the schedule when something
breaking arrives.

**It never presents.** The anchor is the COO, and an anchor that also decided what
was newsworthy would be an executive reporting on itself with nothing between the
two - the same producer-is-not-approver rule this system already applies to
approval, grading, health judgement, appeal and knowledge validation.

Runs on demand rather than as baseline population: the station is on air when
somebody has opened a broadcast day, and a producer with no day to produce is a
process burning a slot. `agents/coo.py`'s ON_DEMAND_ROLES carries it.

Run directly as: python -m agents.producer <identity>
"""

from __future__ import annotations

import sys

from agents.base import run_agent
from backend import broadcast, fi_db, gallery

ROLE = "producer"


def _producer_work(conn, identity: str) -> None:
    day = broadcast.current_day(conn)
    if day is None:
        # Nothing on air. Correct and idle - the station is a capability the
        # organization uses, not one that must always be running.
        return

    outcome = gallery.produce(conn, day["day_id"], producer_identity=identity)
    if any(outcome.values()):
        print(f"[producer] {day['day_id']}: scripted {outcome['scripted']}, "
              f"booked {outcome['booked']}, flashes {outcome['flashes']}, "
              f"dropped {outcome['dropped']}")


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print("usage: python -m agents.producer <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]

    def work_fn(conn) -> None:
        _producer_work(conn, identity)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()
