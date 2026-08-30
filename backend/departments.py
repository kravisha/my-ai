"""Department heads: who speaks for a department, and what they can speak to
(docs/SPEC_RECONCILIATION.md §160).

Three departments already keep records and had nobody who could account for
them. The Department of Education runs a curriculum and stores its results;
Strategy holds adopted strategies and the Strategic Priority Register; Personnel
holds every agent's assignments and the events on their record. All of that was
readable and none of it had a voice.

So each gets a head. The role is thin on purpose and the Development Philosophy
§1 is the licence: what Stage 1 needs is that the component exists, is connected
and can be exercised - a head that summarises its own department and can be
interviewed about it is that, and a richer department is Stage 3.

## A head speaks only to its own records

`summarise` reads the department's own tables and nothing else. That is the whole
guard against the failure a televised department head invites: an executive
summary assembled from an impression rather than from the record. If the tables
say nothing, the head says nothing, and the programme is dropped - which is
honest and is what the schedule already does with an empty remit.

The Speaker is the precedent and is deliberately not duplicated here: it already
speaks for Parliament, reads the state of the House and files a report as its
ordinary work. These are the same job for three more departments.
"""

from __future__ import annotations

from backend.db import Database

EDUCATION = "education"
STRATEGY = "strategy"
PERSONNEL = "personnel"


def _rows(conn: Database, sql: str, params: tuple = ()) -> list[dict]:
    try:
        return conn.fetchall(sql, params)
    except Exception:  # noqa: BLE001 - a department whose tables predate it says nothing
        return []


def _education(conn: Database) -> list[dict]:
    """What the curriculum has examined, and how it went.

    Reports the verdict as recorded, including the failures. A curriculum whose
    KNOWN_GAP exercise passes means the curriculum is out of date rather than
    that the organization improved (§118), so a head that reported only passes
    would be reporting the one number that cannot be trusted."""
    out = []
    for row in _rows(conn, "SELECT id, curriculum, exercise_id, competency, verdict, passed"
                           " FROM curriculum_results ORDER BY id DESC LIMIT 5"):
        out.append({
            "source_table": "curriculum_results", "source_id": row["id"],
            "headline": f"{row['curriculum']}: {row['exercise_id']} {row['verdict']}",
            "summary": (f"Competency {row['competency']}. The exercise "
                        f"{'passed' if row['passed'] else 'did not pass'}, and the verdict on "
                        f"the record is {row['verdict']}."),
        })
    return out


def _strategy(conn: Database) -> list[dict]:
    """Adopted strategies, and what the register says the organization needs next."""
    out = []
    for row in _rows(conn, "SELECT id, name, version, statement, status FROM strategies"
                           " ORDER BY id DESC LIMIT 3"):
        out.append({
            "source_table": "strategies", "source_id": row["id"],
            "headline": f"Strategy '{row['name']}' v{row['version']} is {row['status']}",
            "summary": (row["statement"] or "").strip()[:300] or "No statement was recorded.",
        })
    for row in _rows(conn, "SELECT id, title, category, need_flag, status FROM strategic_register"
                           " ORDER BY id DESC LIMIT 3"):
        out.append({
            "source_table": "strategic_register", "source_id": row["id"],
            "headline": f"On the register: {row['title']}",
            "summary": (f"A {row['category']} the organization has entered, "
                        f"flagged {row['need_flag'] or 'unflagged'}, currently {row['status']}."),
        })
    return out


def _personnel(conn: Database) -> list[dict]:
    """Who is doing what, and what has happened on their record.

    Keyed on `agent_id` rather than the display name, because a renamed agent
    keeps one continuous history and a name-keyed report would split the folder
    in two (TQ-99)."""
    out = []
    for row in _rows(conn, "SELECT id, agent_id, name, event_kind, subject, detail"
                           " FROM personnel_events ORDER BY id DESC LIMIT 4"):
        out.append({
            "source_table": "personnel_events", "source_id": row["id"],
            "headline": f"{row['name'] or row['agent_id']}: {row['event_kind']}",
            "summary": (row["detail"] or row["subject"] or "").strip()[:300]
                       or "Recorded on the agent's personnel file.",
        })
    for row in _rows(conn, "SELECT id, name, role, identity, started_at FROM agent_assignments"
                           " WHERE ended_at IS NULL ORDER BY id DESC LIMIT 3"):
        out.append({
            "source_table": "agent_assignments", "source_id": row["id"],
            "headline": f"{row['name'] or row['identity']} is at the {row['role']} desk",
            "summary": (f"Assigned as {row['identity']} since {row['started_at']}. "
                        "The desk is the job; the agent is who holds it."),
        })
    return out


# The department, its head's role, the programme remit it feeds, and the reader
# that turns its records into something sayable. One entry per department that
# has both records and a head - a department with no records would give its head
# nothing to be interviewed about.
DEPARTMENTS = {
    EDUCATION: {
        "name": "Department of Education",
        "head_role": "education_head",
        "remit": "curriculum",
        "reader": _education,
    },
    STRATEGY: {
        "name": "Strategy",
        "head_role": "strategy_head",
        "remit": "strategy",
        "reader": _strategy,
    },
    PERSONNEL: {
        "name": "Personnel and Training",
        "head_role": "personnel_head",
        "remit": "personnel",
        "reader": _personnel,
    },
}

HEAD_ROLES = tuple(d["head_role"] for d in DEPARTMENTS.values())


def summarise(conn: Database, department: str) -> list[dict]:
    """What this department can currently account for, from its own records."""
    entry = DEPARTMENTS.get(department)
    if entry is None:
        raise ValueError(f"unknown department {department!r}; known are {sorted(DEPARTMENTS)}")
    return entry["reader"](conn)


def department_of_role(head_role: str) -> str | None:
    for slug, entry in DEPARTMENTS.items():
        if entry["head_role"] == head_role:
            return slug
    return None
