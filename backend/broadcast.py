"""The television station: schedule, run of show, scripts, appearances, ad breaks
(docs/SPEC_RECONCILIATION.md §160; Development Philosophy §3, §11, §12).

The station is a real capability of this organization, tested through simulation
rather than being a simulation feature. It reports on the organization's own
activity: what the Explorer detected, what Analysis graded, what broke and what
recovered. **Nothing on air is invented for television** - every story carries the
table and row it was drawn from, and a script quotes that record rather than
composing around it.

## Completeness first, and what that licenses

Written under the standing directive that the order is COMPLETE, WORKING,
RELIABLE, CORRECT, EXCELLENT. So this is deliberately provisional in places the
directive says it may be:

- **Scripts are template-composed, not model-written.** A rough script is a
  Stage 3 problem; a missing script is a Stage 1 one. Templates also mean the
  station runs when the model budget is exhausted, which is when a broadcast
  most needs to keep going.
- **The schedule is a fixed rota**, not a planning agent. It exists, it runs, and
  replacing it later changes one function.
- **Ad slots are structural and unsold.** The break exists in the run of show and
  is reported as unsold, so a client can fill it without the schedule being
  rebuilt around them.

Each of those is marked `provisional` in the record it produces, so nothing later
mistakes a placeholder for a decision.

## What airs is not a second event stream

Segments going to air publish to `status_events` with `source_engine='broadcast'`,
which is the same telemetry every other subsystem writes. §158 established the
rule when the Demonstration Engine wanted its own event table: ordinary telemetry
is sufficient, so a second stream would be instrumentation nobody needs and one
more thing to keep in step.

## Fallback is completeness, not failure

Philosophy §11: a fallback firing during early simulation may demonstrate the
system is *more* complete. So a booked guest that cannot appear is substituted,
and a segment with no story is dropped and the schedule continues - both recorded
as what they are, and both exercised deliberately rather than waited for.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta

from backend.db import Database, now_iso, parse_timestamp

SCHEMA = """
-- The programme catalogue. A format, not an episode.
CREATE TABLE IF NOT EXISTS programmes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    -- What this programme is for, which decides what the newsroom feeds it.
    remit TEXT NOT NULL,
    planned_seconds INTEGER NOT NULL,
    -- Whether this format books an agent guest. A programme that never has one
    -- is the anchor reading alone, which is a different show.
    books_guest INTEGER NOT NULL DEFAULT 0,
    -- The programme's standing expert - its beat. Booked when the story itself
    -- names no agent, which is the ordinary case for governance: a resolution is
    -- about the organization rather than about one agent, and the Speaker is
    -- already Parliament's spokesperson, so inviting it to discuss the House is
    -- its existing job on air rather than a new one.
    guest_role TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- One broadcast day. Opened when the station goes on air, closed at sign-off.
CREATE TABLE IF NOT EXISTS broadcast_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id TEXT NOT NULL UNIQUE,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    -- Who actually presented. Null until somebody does: the day is scheduled by
    -- the executive and the anchor may not be running yet, and recording an
    -- intended presenter would claim an appearance that had not happened.
    anchor_identity TEXT,
    status TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- The run of show: what is scheduled to air, in order.
CREATE TABLE IF NOT EXISTS run_of_show (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    -- programme | news_flash | ad_break | sign_off
    kind TEXT NOT NULL,
    programme_slug TEXT,
    title TEXT NOT NULL,
    planned_seconds INTEGER NOT NULL,
    status TEXT NOT NULL,
    aired_at TEXT,
    -- Set when a news flash pre-empts this segment, so the interruption and the
    -- return to schedule are both readable rather than inferred from timestamps.
    interrupted_by INTEGER,
    resumed_at TEXT,
    detail TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS run_of_show_by_day ON run_of_show (day_id, sequence);

-- What the newsroom found, drawn from the organization's own record.
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id TEXT NOT NULL,
    filed_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT NOT NULL,
    -- Provenance, and it is required. A story with no source is something
    -- somebody made up, which is the one thing a newsroom must not air.
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    -- routine | notable | breaking. Breaking pre-empts the schedule.
    urgency TEXT NOT NULL,
    -- The agent whose work this story is about, when there is one. It is who
    -- gets booked to discuss it.
    subject_identity TEXT,
    status TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS stories_by_day ON stories (day_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS stories_unique_source
    ON stories (day_id, source_table, source_id);

-- What the anchor is handed. The anchor is supplied a script; it does not
-- invent the newsroom workflow (TV-station specification §3).
CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL,
    prepared_by TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    headline TEXT NOT NULL,
    body TEXT NOT NULL,
    -- The story ids this script was built from, so a viewer can be told where
    -- any line came from.
    story_ids TEXT NOT NULL,
    -- Template-composed rather than written. Marked so Stage 3 knows what to
    -- replace, and so nothing reads a placeholder as an editorial decision.
    provisional INTEGER NOT NULL DEFAULT 1,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS scripts_by_segment ON scripts (segment_id);

-- Who appeared, as what.
CREATE TABLE IF NOT EXISTS appearances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL,
    day_id TEXT NOT NULL,
    -- anchor | reporter | guest | panelist
    role_on_air TEXT NOT NULL,
    booked_identity TEXT NOT NULL,
    booked_at TEXT NOT NULL,
    appeared_identity TEXT,
    appeared_at TEXT,
    -- booked | appeared | substituted | unavailable
    outcome TEXT NOT NULL,
    -- Set when this appearance replaced somebody who could not appear. A
    -- substitution is a fallback working, not a failure (philosophy §11).
    substitute_for TEXT,
    detail TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS appearances_by_day ON appearances (day_id);

-- Commercial inventory. Structural now, sold later.
CREATE TABLE IF NOT EXISTS ad_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id TEXT NOT NULL,
    segment_id INTEGER NOT NULL,
    seconds INTEGER NOT NULL,
    -- unsold | sold. Nothing sells one yet, and `advertiser` stays null rather
    -- than carrying a placeholder that would read as a booked client.
    status TEXT NOT NULL,
    advertiser TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);
"""

SCHEMA_VERSION = 1

# --- vocabularies, closed -----------------------------------------------------------

SEGMENT_PROGRAMME = "programme"
SEGMENT_NEWS_FLASH = "news_flash"
SEGMENT_AD_BREAK = "ad_break"
SEGMENT_SIGN_OFF = "sign_off"
SEGMENT_KINDS = (SEGMENT_PROGRAMME, SEGMENT_NEWS_FLASH, SEGMENT_AD_BREAK, SEGMENT_SIGN_OFF)

SEGMENT_SCHEDULED = "scheduled"
SEGMENT_AIRED = "aired"
SEGMENT_INTERRUPTED = "interrupted"
# No story to carry it. Dropped and the schedule continues - philosophy §11's
# safe skip-and-continue, recorded rather than silently skipped.
SEGMENT_DROPPED = "dropped"
SEGMENT_STATUSES = (SEGMENT_SCHEDULED, SEGMENT_AIRED, SEGMENT_INTERRUPTED, SEGMENT_DROPPED)

URGENCY_ROUTINE = "routine"
URGENCY_NOTABLE = "notable"
URGENCY_BREAKING = "breaking"
URGENCIES = (URGENCY_ROUTINE, URGENCY_NOTABLE, URGENCY_BREAKING)

STORY_FILED = "filed"
STORY_SCRIPTED = "scripted"
STORY_AIRED = "aired"
STORY_STATUSES = (STORY_FILED, STORY_SCRIPTED, STORY_AIRED)

ROLE_ANCHOR = "anchor"
ROLE_REPORTER = "reporter"
ROLE_GUEST = "guest"
ROLE_PANELIST = "panelist"
ON_AIR_ROLES = (ROLE_ANCHOR, ROLE_REPORTER, ROLE_GUEST, ROLE_PANELIST)

APPEARANCE_BOOKED = "booked"
APPEARANCE_APPEARED = "appeared"
APPEARANCE_SUBSTITUTED = "substituted"
APPEARANCE_UNAVAILABLE = "unavailable"
APPEARANCE_OUTCOMES = (APPEARANCE_BOOKED, APPEARANCE_APPEARED,
                       APPEARANCE_SUBSTITUTED, APPEARANCE_UNAVAILABLE)

AD_UNSOLD = "unsold"
AD_SOLD = "sold"

DAY_ON_AIR = "on_air"
DAY_CLOSED = "closed"

AD_BREAK_SECONDS = 30

# How fast the broadcast clock runs against the wall clock.
#
# `planned_seconds` was a decorative column until this: every segment declared a
# duration and nothing read one, so a 695-second rundown aired in thirteen
# cycles and the station churned fourteen days through a three-minute run. A
# column nothing reads is the §149 shape, and this is what makes it mean
# something.
#
# 1.0 is real time - a programme billed at ninety seconds occupies ninety. A
# scenario compresses it so a full day fits inside a short run, which is the
# separation of real from simulated time the Demonstration Engine specification
# asks for rather than a fudge: the rundown still declares real durations and
# only the clock reading them is scaled.
BROADCAST_TIME_SCALE = float(os.environ.get("FI_BROADCAST_TIME_SCALE", "1"))

# How long the station stays off air between days. Without it the executive
# reopens the moment sign-off lands, which is what produced fourteen days where
# there should have been one.
DAY_GAP_SECONDS = float(os.environ.get("FI_BROADCAST_DAY_GAP_SECONDS", "300"))


# --- the schedule -------------------------------------------------------------------
#
# A fixed rota, and provisional by declaration. A planning agent that chose the
# running order from the day's news is Stage 3; what Stage 1 needs is that a
# schedule exists, runs, and has somewhere for each kind of segment to go.

PROGRAMME_CATALOGUE = (
    {"slug": "market_open", "name": "Market Open", "remit": "detection",
     "planned_seconds": 60, "books_guest": 0, "guest_role": None},
    {"slug": "the_desk", "name": "The Desk", "remit": "discovery",
     "planned_seconds": 90, "books_guest": 1, "guest_role": "speculator"},
    {"slug": "under_review", "name": "Under Review", "remit": "judgment",
     "planned_seconds": 90, "books_guest": 1, "guest_role": "analysis"},
    # Parliament's own programme. The Speaker reads the state of the House and
    # files a report as its ordinary work (§124), so appearing to discuss it is
    # that job with an audience - not a role invented for television.
    {"slug": "the_house", "name": "The House", "remit": "governance",
     "planned_seconds": 60, "books_guest": 1, "guest_role": "speaker"},
    {"slug": "systems_watch", "name": "Systems Watch", "remit": "operations",
     "planned_seconds": 60, "books_guest": 1, "guest_role": "dba"},
    # Departmental programmes. Each is a head accounting for its own records:
    # the curriculum and how the exercises went, what strategy has been adopted
    # and what the register says is needed next, and how the agents themselves
    # are doing. Every one of those was already recorded and had nobody who could
    # speak to it.
    {"slug": "class_notes", "name": "Class Notes", "remit": "curriculum",
     "planned_seconds": 60, "books_guest": 1, "guest_role": "education_head"},
    {"slug": "forward_plan", "name": "The Forward Plan", "remit": "strategy",
     "planned_seconds": 60, "books_guest": 1, "guest_role": "strategy_head"},
    {"slug": "the_roster", "name": "The Roster", "remit": "personnel",
     "planned_seconds": 60, "books_guest": 1, "guest_role": "personnel_head"},
    # The trader talks their own book: the calls that worked, the ones that did
    # not, and what is still open. A programme about one agent's record rather
    # than about the organization's, which is why its guest is the desk itself.
    {"slug": "the_long_and_short", "name": "The Long and the Short", "remit": "trading",
     "planned_seconds": 90, "books_guest": 1, "guest_role": "trader"},
    # The one programme that reports on subjects rather than on the
    # organization's own record. Its guest is the head of strategy, because an
    # under-examined sector is a strategy question - and the beat keeps it
    # sourced: every item is a row in `emerging_sectors`, never an improvisation.
    {"slug": "where_nobody_is_looking", "name": "Where Nobody Is Looking",
     "remit": "sectors", "planned_seconds": 90, "books_guest": 1,
     "guest_role": "strategy_head"},
    {"slug": "closing_bell", "name": "Closing Bell", "remit": "summary",
     "planned_seconds": 45, "books_guest": 0, "guest_role": None},
)

# Where the ad breaks fall. After the second and fourth programmes: real breaks
# in the run of show, so the inventory exists before anybody wants to buy it.
AD_BREAK_AFTER = (2, 4, 7)


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)
    for programme in PROGRAMME_CATALOGUE:
        conn.execute(
            "INSERT OR IGNORE INTO programmes (slug, name, remit, planned_seconds,"
            " books_guest, guest_role, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (programme["slug"], programme["name"], programme["remit"],
             programme["planned_seconds"], programme["books_guest"],
             programme["guest_role"], SCHEMA_VERSION))


# --- the broadcast day ---------------------------------------------------------------


def open_day(conn: Database, day_id: str, *, anchor_identity: str | None = None) -> int:
    """Go on air, and lay out the run of show.

    The whole rota is written up front rather than segment by segment, because a
    schedule that does not exist until the moment it airs cannot be pre-empted -
    and being interrupted and returning to it is most of what this workflow has
    to demonstrate."""
    row = conn.execute_returning_id(
        "INSERT INTO broadcast_days (day_id, opened_at, anchor_identity, status, schema_version)"
        " VALUES (?, ?, ?, ?, ?)",
        (day_id, now_iso(), anchor_identity, DAY_ON_AIR, SCHEMA_VERSION))

    sequence = 0
    for index, programme in enumerate(PROGRAMME_CATALOGUE, start=1):
        sequence += 1
        segment_id = conn.execute_returning_id(
            "INSERT INTO run_of_show (day_id, sequence, kind, programme_slug, title,"
            " planned_seconds, status, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (day_id, sequence, SEGMENT_PROGRAMME, programme["slug"], programme["name"],
             programme["planned_seconds"], SEGMENT_SCHEDULED, SCHEMA_VERSION))
        if index in AD_BREAK_AFTER:
            sequence += 1
            break_id = conn.execute_returning_id(
                "INSERT INTO run_of_show (day_id, sequence, kind, title, planned_seconds,"
                " status, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (day_id, sequence, SEGMENT_AD_BREAK, "Commercial break",
                 AD_BREAK_SECONDS, SEGMENT_SCHEDULED, SCHEMA_VERSION))
            conn.execute(
                "INSERT INTO ad_slots (day_id, segment_id, seconds, status, schema_version)"
                " VALUES (?, ?, ?, ?, ?)",
                (day_id, break_id, AD_BREAK_SECONDS, AD_UNSOLD, SCHEMA_VERSION))
        _ = segment_id

    sequence += 1
    conn.execute(
        "INSERT INTO run_of_show (day_id, sequence, kind, title, planned_seconds, status,"
        " schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (day_id, sequence, SEGMENT_SIGN_OFF, "Sign-off", 20, SEGMENT_SCHEDULED, SCHEMA_VERSION))
    return row


def record_presenter(conn: Database, day_id: str, identity: str) -> None:
    """Stamp who is presenting, first time only.

    `WHERE anchor_identity IS NULL` so a fallback presenter taking over mid-day
    does not overwrite the anchor that opened the bulletin - the per-appearance
    record carries who read what, and this is the day's billing."""
    conn.execute(
        "UPDATE broadcast_days SET anchor_identity = ? WHERE day_id = ? AND anchor_identity IS NULL",
        (identity, day_id))


def current_day(conn: Database) -> dict | None:
    return conn.fetchone(
        "SELECT * FROM broadcast_days WHERE status = ? ORDER BY id DESC LIMIT 1", (DAY_ON_AIR,))


def close_day(conn: Database, day_id: str) -> None:
    conn.execute("UPDATE broadcast_days SET closed_at = ?, status = ? WHERE day_id = ?",
                 (now_iso(), DAY_CLOSED, day_id))


# --- stories -------------------------------------------------------------------------


def file_story(conn: Database, *, day_id: str, kind: str, headline: str, summary: str,
               source_table: str, source_id: str, urgency: str,
               subject_identity: str | None = None) -> int | None:
    """Put a story on the newsroom's desk.

    Returns None when this source has already produced a story today - the unique
    index is the guard, because a newsroom that re-files the same incident every
    cycle would fill the schedule with one event."""
    if urgency not in URGENCIES:
        raise ValueError(f"unknown urgency {urgency!r}; known are {list(URGENCIES)}")
    existing = conn.fetchone(
        "SELECT id FROM stories WHERE day_id = ? AND source_table = ? AND source_id = ?",
        (day_id, source_table, str(source_id)))
    if existing:
        return None
    return conn.execute_returning_id(
        "INSERT INTO stories (day_id, filed_at, kind, headline, summary, source_table,"
        " source_id, urgency, subject_identity, status, schema_version)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (day_id, now_iso(), kind, headline, summary, source_table, str(source_id),
         urgency, subject_identity, STORY_FILED, SCHEMA_VERSION))


def stories_for(conn: Database, day_id: str, *, kind: str | None = None,
                status: str = STORY_FILED, urgency: str | None = None) -> list[dict]:
    clauses, params = ["day_id = ?", "status = ?"], [day_id, status]
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if urgency is not None:
        clauses.append("urgency = ?")
        params.append(urgency)
    return conn.fetchall(
        f"SELECT * FROM stories WHERE {' AND '.join(clauses)} ORDER BY id", tuple(params))


def mark_stories(conn: Database, story_ids: list[int], status: str) -> None:
    for story_id in story_ids:
        conn.execute("UPDATE stories SET status = ? WHERE id = ?", (status, story_id))


# --- the run of show -----------------------------------------------------------------


def next_programme(conn: Database, day_id: str) -> dict | None:
    """The next scheduled *programme*, which is what a flash pre-empts.

    Interrupting an ad break is not an interruption worth the name - nothing is
    cut away from and nothing has to be returned to. Live, the flash landed on
    whichever segment happened to be next and the schedule had nothing to
    resume, so the return-to-programme path never ran (§160)."""
    return conn.fetchone(
        "SELECT * FROM run_of_show WHERE day_id = ? AND status = ? AND kind = ?"
        " ORDER BY sequence LIMIT 1",
        (day_id, SEGMENT_SCHEDULED, SEGMENT_PROGRAMME))


def _scale() -> float:
    """Read at call time, so a scenario or a test can change the clock without a
    reimport - the convention every other tunable here follows."""
    return max(0.001, float(os.environ.get("FI_BROADCAST_TIME_SCALE",
                                           str(BROADCAST_TIME_SCALE))))


def segment_is_due(conn: Database, day_id: str) -> tuple[bool, float]:
    """Whether the next segment may go to air yet, and how long until it may.

    A segment occupies its `planned_seconds` from the moment it airs, divided by
    the broadcast clock's scale. So the rundown plays at the pace it declares
    instead of as fast as the anchor's work cycle happens to turn.

    **A news flash is exempt.** Breaking news that waited for the schedule would
    not be breaking - the whole point of the segment is that it does not wait."""
    pending = next_segment(conn, day_id)
    if pending is None:
        return True, 0.0
    if pending["kind"] == SEGMENT_NEWS_FLASH:
        return True, 0.0

    last = conn.fetchone(
        "SELECT aired_at, planned_seconds FROM run_of_show"
        " WHERE day_id = ? AND aired_at IS NOT NULL ORDER BY aired_at DESC LIMIT 1",
        (day_id,))
    if last is None:
        # Nothing has aired yet; the day goes on air as soon as it is opened.
        return True, 0.0

    occupies = timedelta(seconds=last["planned_seconds"] / _scale())
    due_at = parse_timestamp(last["aired_at"]) + occupies
    now = parse_timestamp(now_iso())
    remaining = (due_at - now).total_seconds()
    return remaining <= 0, max(0.0, remaining)


def ready_for_a_new_day(conn: Database) -> bool:
    """Whether the station may go back on air.

    False while a day is running, and false during the gap after one closes. The
    executive reopening the instant sign-off landed is what turned a broadcast
    day into a fourteen-times-repeated bulletin."""
    if current_day(conn) is not None:
        return False
    last = conn.fetchone(
        "SELECT closed_at FROM broadcast_days WHERE closed_at IS NOT NULL"
        " ORDER BY id DESC LIMIT 1")
    if last is None:
        return True
    gap = float(os.environ.get("FI_BROADCAST_DAY_GAP_SECONDS", str(DAY_GAP_SECONDS)))
    elapsed = (parse_timestamp(now_iso()) - parse_timestamp(last["closed_at"])).total_seconds()
    return elapsed >= gap / _scale()


def next_segment(conn: Database, day_id: str) -> dict | None:
    return conn.fetchone(
        "SELECT * FROM run_of_show WHERE day_id = ? AND status = ? ORDER BY sequence LIMIT 1",
        (day_id, SEGMENT_SCHEDULED))


def segments_of(conn: Database, day_id: str) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM run_of_show WHERE day_id = ? ORDER BY sequence", (day_id,))


def insert_news_flash(conn: Database, day_id: str, *, title: str, before_sequence: int) -> int:
    """Cut into the schedule.

    Inserted at a half-step rather than by renumbering everything after it: the
    original running order stays readable, which is what makes *"the schedule was
    interrupted here and resumed there"* a fact rather than a reconstruction."""
    conn.execute(
        "UPDATE run_of_show SET sequence = sequence * 10 WHERE day_id = ? AND sequence < 10",
        (day_id,))
    row = conn.fetchone(
        "SELECT MIN(sequence) AS s FROM run_of_show WHERE day_id = ? AND status = ?",
        (day_id, SEGMENT_SCHEDULED))
    at = (row["s"] if row and row["s"] is not None else before_sequence * 10) - 1
    return conn.execute_returning_id(
        "INSERT INTO run_of_show (day_id, sequence, kind, title, planned_seconds, status,"
        " schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (day_id, at, SEGMENT_NEWS_FLASH, title, 30, SEGMENT_SCHEDULED, SCHEMA_VERSION))


def mark_interrupted(conn: Database, segment_id: int, *, by_segment: int) -> None:
    conn.execute(
        "UPDATE run_of_show SET status = ?, interrupted_by = ? WHERE id = ?",
        (SEGMENT_INTERRUPTED, by_segment, segment_id))


def resume_segment(conn: Database, segment_id: int) -> None:
    """Return to the programme that was pre-empted. The interruption is only half
    the workflow; a station that never came back would be a station that broke."""
    conn.execute(
        "UPDATE run_of_show SET status = ?, resumed_at = ? WHERE id = ?",
        (SEGMENT_SCHEDULED, now_iso(), segment_id))


def air(conn: Database, segment_id: int, *, detail: str | None = None) -> None:
    conn.execute(
        "UPDATE run_of_show SET status = ?, aired_at = ?, detail = ? WHERE id = ?",
        (SEGMENT_AIRED, now_iso(), detail, segment_id))


def drop(conn: Database, segment_id: int, *, why: str) -> None:
    """Skip a segment and keep the schedule moving (philosophy §11).

    Recorded rather than silently passed over: a dropped segment with a reason is
    an operational fact, and one that vanished would make the run of show a lie
    about what aired."""
    conn.execute(
        "UPDATE run_of_show SET status = ?, detail = ? WHERE id = ?",
        (SEGMENT_DROPPED, why, segment_id))


# --- scripts and appearances ----------------------------------------------------------


def write_script(conn: Database, *, segment_id: int, prepared_by: str, headline: str,
                 body: str, story_ids: list[int], provisional: bool = True) -> int:
    return conn.execute_returning_id(
        "INSERT INTO scripts (segment_id, prepared_by, prepared_at, headline, body,"
        " story_ids, provisional, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (segment_id, prepared_by, now_iso(), headline, body, json.dumps(story_ids),
         int(provisional), SCHEMA_VERSION))


def script_for(conn: Database, segment_id: int) -> dict | None:
    return conn.fetchone(
        "SELECT * FROM scripts WHERE segment_id = ? ORDER BY id DESC LIMIT 1", (segment_id,))


def book(conn: Database, *, segment_id: int, day_id: str, identity: str,
         role_on_air: str) -> int:
    if role_on_air not in ON_AIR_ROLES:
        raise ValueError(f"unknown on-air role {role_on_air!r}; known are {list(ON_AIR_ROLES)}")
    return conn.execute_returning_id(
        "INSERT INTO appearances (segment_id, day_id, role_on_air, booked_identity,"
        " booked_at, outcome, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (segment_id, day_id, role_on_air, identity, now_iso(), APPEARANCE_BOOKED,
         SCHEMA_VERSION))


def appeared(conn: Database, appearance_id: int, identity: str, *,
             substitute_for: str | None = None, detail: str | None = None) -> None:
    conn.execute(
        "UPDATE appearances SET appeared_identity = ?, appeared_at = ?, outcome = ?,"
        " substitute_for = ?, detail = ? WHERE id = ?",
        (identity, now_iso(),
         APPEARANCE_SUBSTITUTED if substitute_for else APPEARANCE_APPEARED,
         substitute_for, detail, appearance_id))


def unavailable(conn: Database, appearance_id: int, *, why: str) -> None:
    conn.execute(
        "UPDATE appearances SET outcome = ?, detail = ? WHERE id = ?",
        (APPEARANCE_UNAVAILABLE, why, appearance_id))


def appearances_of(conn: Database, day_id: str) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM appearances WHERE day_id = ? ORDER BY id", (day_id,))


def bookings_for(conn: Database, segment_id: int) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM appearances WHERE segment_id = ? ORDER BY id", (segment_id,))


def ad_slots_of(conn: Database, day_id: str) -> list[dict]:
    return conn.fetchall("SELECT * FROM ad_slots WHERE day_id = ? ORDER BY id", (day_id,))
