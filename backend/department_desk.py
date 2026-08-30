"""What a department head does each cycle.

One implementation, three entry points. The heads differ only in which
department they speak for, and three copies of the same loop would be three
places for it to drift.

The work is deliberately small: read the department's own records and publish a
summary to the ordinary telemetry stream. That makes the department's current
state observable to anyone - the console, the newsroom, an operator - without
anybody having to query its tables and interpret them, which is what a head is
for.

Publishing rather than storing: `status_events` already carries source, type and
message, and a departmental-report table would be a second place the same facts
live (§158's rule).
"""

from __future__ import annotations

from backend import departments, status_events
from backend.db import Database


def report_department(conn: Database, *, department: str, identity: str, role: str) -> int:
    """Summarise this department, and say so. Returns how many items it had.

    A department with nothing on its record publishes nothing. Silence there is
    accurate - and a head that filed a cheerful summary of an empty table would
    be the charter-written-falsely problem in a suit."""
    items = departments.summarise(conn, department)
    if not items:
        return 0
    entry = departments.DEPARTMENTS[department]
    try:
        status_events.publish(
            conn, source_engine="departments", source_agent=identity,
            source_department=entry["name"],
            event_type="department.report", severity="info", status="ok",
            message=f"{entry['name']}: {len(items)} item(s) on the record; "
                    f"latest - {items[0]['headline']}")
    except Exception:  # noqa: BLE001 - telemetry must not stop a department reporting
        pass
    return len(items)
