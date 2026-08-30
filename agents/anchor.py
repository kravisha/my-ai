"""Anchor: the station's public face.

A dedicated role, and dedicated is the point. The Dedicated Anchor specification
§4 is explicit that making an executive the permanent presenter couples internal
coordination, decision-making and agent management to public presentation - and
the Anchor does not need to run the organization in order to explain what it is
doing.

So this agent presents and nothing else. It does not decide what is newsworthy
(the producer builds the run of show), it does not run the company (the COO
does), and when a booked guest cannot appear it **asks a running agent** rather
than speaking for one - §6 forbids the Anchor from inventing another agent's
experience when that agent could have supplied it.

The role supports more than one instance. §9 anticipates a financial anchor, a
technology anchor, a breaking-news anchor; nothing here is written around a
single identity, and a second anchor is a second instance of this role rather
than a new kind of agent. `gallery.resolve_presenter` picks whichever anchors are
running, so a backup is a position in that list.

On demand rather than baseline: an anchor with no broadcast day is a process
holding a slot for a station that is off air.

Run directly as: python -m agents.anchor <identity>
"""

from __future__ import annotations

import sys

from agents.base import run_agent
from backend import broadcast, gallery

ROLE = "anchor"


def _anchor_work(conn, identity: str) -> None:
    day = broadcast.current_day(conn)
    if day is None:
        return

    presenter, is_fallback, detail = gallery.resolve_presenter(conn)
    # Deliberately checked rather than assumed. With more than one anchor
    # running, only the one `resolve_presenter` names is on air - two anchors
    # both presenting would air two segments per cycle and interleave the
    # running order.
    if presenter != identity:
        return

    aired = gallery.present_next(conn, day["day_id"], anchor_identity=identity)
    if aired is None:
        print(f"[anchor] {day['day_id']}: off air")
        return

    guests = ", ".join(aired.get("guests") or []) or "no guests"
    marker = " (fallback presenter)" if is_fallback else ""
    print(f"[anchor] {aired['kind']}: {aired['title']} ({guests}){marker}")


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print("usage: python -m agents.anchor <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]

    def work_fn(conn) -> None:
        _anchor_work(conn, identity)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()
