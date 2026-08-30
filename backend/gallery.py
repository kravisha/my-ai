"""Producing and presenting: what turns the organization's record into a broadcast
(docs/SPEC_RECONCILIATION.md §160).

Named for the gallery - the control room a programme is directed from - because
that is what this is: the production side, separate from `broadcast` which is the
station's record and `newsroom` which is what there is to report.

Two halves, kept apart on purpose.

**Producing** assembles the run of show: it reads the day's stories, writes a
script for each programme, books whichever agent the story is *about*, and cuts a
news flash into the schedule when something breaking arrives. Nothing is invented
- a script quotes the stories it names, and a programme with no story is dropped
rather than padded.

**Presenting** airs the next segment. The anchor is handed a finished script
(TV-station specification §3: *"the anchor should not be forced to invent the
entire news workflow independently"*), reads it, and returns to the schedule after
an interruption.

The split matters because the anchor is the COO, and an anchor that also decided
what was newsworthy would be an executive reporting on itself with no separation
at all - the same producer-is-not-approver rule this system applies five times
elsewhere.

## Scripts are composed, and say so

Template-composed from the story's own headline and summary. Deliberately not
model-written: a rough script is a Stage 3 problem and a missing one is a Stage 1
problem, and templates keep the station on air when the model budget is gone -
which is exactly when a newsroom must not stop. Every script is stored
`provisional=1` so nothing later mistakes it for an editorial decision.
"""

from __future__ import annotations

import json

from backend import broadcast, fi_db, newsroom, status_events
from backend.db import Database

# Who reads the news. A **dedicated role**, not an executive doing it as well:
# the Dedicated Anchor specification §4 is explicit that making an executive the
# permanent presenter couples internal coordination to public presentation, and
# the Anchor does not need to run the organization in order to explain it.
#
# The role supports more than one instance (§9's financial, technology and
# breaking-news anchors), so nothing here names an identity - the presenter is
# resolved from whichever anchors are running.
ANCHOR_ROLE = "anchor"

# Who may present when no anchor is running at all. **Fallback, not architecture**
# (§8): the station must not go dark because one agent is unavailable, and §8
# permits another suitable agent - so the COO can read the news in an emergency
# and every such appearance is recorded as a fallback rather than as normal.
FALLBACK_PRESENTER_ROLES = ("speaker", "coo")

SOURCE_ENGINE = "broadcast"


def _publish(conn: Database, *, event_type: str, message: str, agent: str | None = None,
             severity: str = "info", correlation_id: str | None = None) -> None:
    """What airs goes to the ordinary telemetry stream, not a broadcast-only one.

    §158's rule, applied again: `status_events` already carries source, type,
    severity and correlation, and a second stream would be one more thing to keep
    in step for no reading it cannot already support."""
    try:
        status_events.publish(
            conn, source_engine=SOURCE_ENGINE, source_agent=agent,
            event_type=event_type, severity=severity, status="ok",
            message=message, correlation_id=correlation_id)
    except Exception:  # noqa: BLE001 - telemetry must never take the broadcast down
        pass


# --- producing ------------------------------------------------------------------------


def _script_body(stories: list[dict], programme_name: str) -> str:
    """A programme's script, composed from the stories it is carrying.

    Each line names its story so the anchor's words can be traced to the record
    they came from - which is what stops a template from becoming a place where
    unsourced sentences accumulate."""
    lines = [f"Good day. This is {programme_name}."]
    for story in stories:
        lines.append(f"[{story['id']}] {story['headline']}. {story['summary']}")
    lines.append("That is the picture as our own records have it.")
    return "\n".join(lines)


def produce(conn: Database, day_id: str, *, producer_identity: str) -> dict:
    """Fill the run of show: scripts, guests, and any interruption the news forces.

    Runs every cycle and is idempotent per segment - a segment that already has a
    script is left alone, so producing repeatedly develops the day rather than
    rewriting it."""
    newsroom.gather(conn, day_id)
    scripted, booked, flashes, dropped = 0, 0, 0, 0

    for segment in broadcast.segments_of(conn, day_id):
        if segment["status"] != broadcast.SEGMENT_SCHEDULED:
            continue
        if segment["kind"] != broadcast.SEGMENT_PROGRAMME:
            continue
        if broadcast.script_for(conn, segment["id"]):
            continue

        programme = conn.fetchone(
            "SELECT * FROM programmes WHERE slug = ?", (segment["programme_slug"],))
        if programme is None:
            continue
        stories = newsroom.stories_for_remit(conn, day_id, programme["remit"])
        if not stories:
            # Left scheduled, **not dropped**. A programme with nothing to report
            # yet has until its own airtime to acquire something, and dropping it
            # here took that away: Closing Bell recaps what aired, so at the
            # moment the run of show is first produced it is empty by definition
            # and was being killed before the day had happened.
            #
            # `present_next` drops a segment that reaches air with no script,
            # which is the same fallback applied at the only moment the answer is
            # final (philosophy §11's safe skip-and-continue).
            dropped += 1
            continue

        broadcast.write_script(
            conn, segment_id=segment["id"], prepared_by=producer_identity,
            headline=f"{programme['name']}: {stories[0]['headline']}",
            body=_script_body(stories, programme["name"]),
            story_ids=[s["id"] for s in stories])
        broadcast.mark_stories(conn, [s["id"] for s in stories], broadcast.STORY_SCRIPTED)
        scripted += 1

        if programme["books_guest"]:
            # The agent the story is about, when there is one. A governance story
            # is about the organization rather than about an agent, so those fall
            # through to the programme's standing expert - which is how the
            # Speaker comes on to discuss the House.
            subject = next((s["subject_identity"] for s in stories if s["subject_identity"]), None)
            if subject is None and programme["guest_role"]:
                standing = conn.fetchone(
                    "SELECT identity FROM agent_registry WHERE role = ? AND process_state = ?"
                    " ORDER BY identity LIMIT 1",
                    (programme["guest_role"], fi_db.PROCESS_RUNNING))
                subject = standing["identity"] if standing else None
            if subject:
                broadcast.book(conn, segment_id=segment["id"], day_id=day_id,
                               identity=subject,
                               role_on_air=(broadcast.ROLE_PANELIST if subject.startswith("speaker-")
                                            else broadcast.ROLE_GUEST))
                booked += 1

    # Flashes are cut in *after* the programmes are scripted, and the ordering was
    # settled by getting it wrong both ways. Interrupting first marks the pending
    # programme `interrupted`, so the scripting loop skips it and it reaches air
    # with nothing to read. Scripting first without excluding breaking stories let
    # an agent going down become a calm item inside Systems Watch - the opposite
    # of what breaking means.
    #
    # So: `stories_for_remit` never hands a programme a breaking story, and the
    # interruption is applied once every programme has its script.
    for story in newsroom.breaking_stories(conn, day_id):
        # The next *programme*, not the next segment. A flash that cut into an ad
        # break interrupted nothing and left nothing to return to, so the
        # resume-the-schedule half of the workflow never ran.
        pending = broadcast.next_programme(conn, day_id)
        if pending is None:
            break
        flash = broadcast.insert_news_flash(
            conn, day_id, title=f"NEWS FLASH: {story['headline']}",
            before_sequence=pending["sequence"])
        broadcast.write_script(
            conn, segment_id=flash, prepared_by=producer_identity,
            headline=story["headline"],
            body=f"We interrupt this programme. {story['headline']}. {story['summary']}",
            story_ids=[story["id"]])
        broadcast.mark_stories(conn, [story["id"]], broadcast.STORY_SCRIPTED)
        broadcast.mark_interrupted(conn, pending["id"], by_segment=flash)
        if story["subject_identity"]:
            broadcast.book(conn, segment_id=flash, day_id=day_id,
                           identity=story["subject_identity"],
                           role_on_air=broadcast.ROLE_REPORTER)
            booked += 1
        flashes += 1

    return {"scripted": scripted, "booked": booked, "flashes": flashes, "dropped": dropped}


# --- presenting -----------------------------------------------------------------------


def resolve_presenter(conn: Database) -> tuple[str | None, bool, str]:
    """Who is on air. Returns (identity, is_fallback, detail).

    Primary is any running anchor; a second running anchor is the backup and is
    reached by the same query, because "backup" is a position in the list rather
    than a different kind of agent. Only when no anchor is running at all does a
    fallback presenter take over, and that is recorded as a fallback - §8 allows
    another suitable agent and is explicit that it must not become the normal
    architecture."""
    anchors = conn.fetchall(
        "SELECT identity FROM agent_registry WHERE role = ? AND process_state = ?"
        " ORDER BY identity", (ANCHOR_ROLE, fi_db.PROCESS_RUNNING))
    if anchors:
        return anchors[0]["identity"], False, (
            "anchor on air" if len(anchors) == 1
            else f"anchor on air, {len(anchors) - 1} backup anchor(s) available")

    for role in FALLBACK_PRESENTER_ROLES:
        standby = conn.fetchall(
            "SELECT identity FROM agent_registry WHERE role = ? AND process_state = ?"
            " ORDER BY identity LIMIT 1", (role, fi_db.PROCESS_RUNNING))
        if standby:
            return standby[0]["identity"], True, (
                f"no anchor running; {standby[0]['identity']} presenting as fallback")

    return None, True, "no anchor and no fallback presenter is running"


def request_more(conn: Database, *, asker: str, segment_title: str,
                 subject_role: str) -> str | None:
    """Ask an operational agent for what the brief does not carry (§1, §10.8).

    Uses the UQI, which already exists and is answered by the target agent's own
    process rather than by reading the database on its behalf - so the answer is
    the agent speaking, which is what §6 requires when it forbids the Anchor from
    inventing another agent's experience."""
    target = conn.fetchone(
        "SELECT identity FROM agent_registry WHERE role = ? AND process_state = ?"
        " ORDER BY identity LIMIT 1", (subject_role, fi_db.PROCESS_RUNNING))
    if target is None:
        return None
    try:
        fi_db.ask_agent(conn, asker, target["identity"],
                        f"For {segment_title}: what did you find, in your own words?")
    except Exception:  # noqa: BLE001 - a question that could not be put is not fatal
        return None
    return target["identity"]


def _resolve_guest(conn: Database, booking: dict) -> tuple[str | None, str | None, str]:
    """Who actually appears.

    Returns (identity, substitute_for, detail). The booked agent appears if it is
    registered and running; otherwise the station substitutes another agent of the
    same role, and failing that reports the slot unfilled. All three are ordinary
    outcomes - philosophy §11 is explicit that a fallback firing may show the
    system is *more* complete, not less."""
    booked = booking["booked_identity"]
    agent = fi_db.get_agent(conn, booked)
    if agent is not None and agent["process_state"] == fi_db.PROCESS_RUNNING:
        return booked, None, "appeared as booked"

    role = agent["role"] if agent else (booked.rsplit("-", 1)[0] if "-" in booked else None)
    if role:
        for candidate in conn.fetchall(
                "SELECT identity FROM agent_registry WHERE role = ? AND process_state = ?"
                " AND identity != ? ORDER BY identity", (role, fi_db.PROCESS_RUNNING, booked)):
            return candidate["identity"], booked, f"substitute for {booked}, same role"

    return None, None, f"{booked} was unavailable and no substitute of its role was running"


def present_next(conn: Database, day_id: str, *, anchor_identity: str) -> dict | None:
    """Air one segment. Returns what happened, or None when the day is done.

    One segment per call rather than a loop, because the anchor is an ordinary
    agent doing this inside its own work cycle - a presenter that blocked until
    sign-off would stop being an agent and start being a script."""
    broadcast.record_presenter(conn, day_id, anchor_identity)

    # The rundown plays at the pace it declares. Without this every segment aired
    # on the anchor's next work cycle, so a 695-second day was over in thirteen
    # seconds and the station churned fourteen of them through one run.
    due, remaining = broadcast.segment_is_due(conn, day_id)
    if not due:
        return {"segment_id": None, "kind": "waiting", "title": "on air",
                "detail": f"{remaining:.0f}s of the current segment remaining"}

    segment = broadcast.next_segment(conn, day_id)
    if segment is None:
        broadcast.close_day(conn, day_id)
        _publish(conn, event_type="broadcast.sign_off", agent=anchor_identity,
                 message=f"{day_id}: off air")
        return None

    kind = segment["kind"]
    result = {"segment_id": segment["id"], "kind": kind, "title": segment["title"]}

    if kind == broadcast.SEGMENT_AD_BREAK:
        # The break is real airtime whether or not anybody has bought it. Reported
        # as unsold rather than skipped, so the inventory is visible to whoever
        # eventually sells it.
        slot = conn.fetchone("SELECT * FROM ad_slots WHERE segment_id = ?", (segment["id"],))
        status = slot["status"] if slot else broadcast.AD_UNSOLD
        broadcast.air(conn, segment["id"], detail=f"{status} inventory")
        _publish(conn, event_type="broadcast.ad_break", agent=anchor_identity,
                 message=f"{segment['title']} - {status}")
        result["detail"] = status
        return result

    if kind == broadcast.SEGMENT_SIGN_OFF:
        broadcast.air(conn, segment["id"], detail="signed off")
        broadcast.close_day(conn, day_id)
        _publish(conn, event_type="broadcast.sign_off", agent=anchor_identity,
                 message=f"{day_id}: signed off")
        result["detail"] = "signed off"
        return result

    script = broadcast.script_for(conn, segment["id"])
    if script is None:
        broadcast.drop(conn, segment["id"], why="no script was ready at air time")
        _publish(conn, event_type="broadcast.dropped", agent=anchor_identity,
                 severity="warning", message=f"{segment['title']}: no script ready")
        result["detail"] = "dropped, no script"
        return result

    guests = []
    for booking in broadcast.bookings_for(conn, segment["id"]):
        if booking["outcome"] != broadcast.APPEARANCE_BOOKED:
            continue
        identity, substitute_for, detail = _resolve_guest(conn, booking)
        if identity is None:
            broadcast.unavailable(conn, booking["id"], why=detail)
            _publish(conn, event_type="broadcast.guest_unavailable", agent=anchor_identity,
                     severity="warning", message=f"{segment['title']}: {detail}")
            # §1 and §10.8: when the brief is not enough, the Anchor asks. The
            # booked guest could not appear, so rather than speaking for it - which
            # §6 forbids - the Anchor puts the question to a running agent of the
            # same role and the answer comes from that agent's own process.
            booked_role = booking["booked_identity"].rsplit("-", 1)[0]
            asked = request_more(conn, asker=anchor_identity,
                                 segment_title=segment["title"], subject_role=booked_role)
            if asked:
                _publish(conn, event_type="broadcast.enquiry", agent=anchor_identity,
                         message=f"{segment['title']}: asked {asked} for more")
        else:
            broadcast.appeared(conn, booking["id"], identity,
                               substitute_for=substitute_for, detail=detail)
            guests.append(identity)
            _publish(conn, event_type="broadcast.guest", agent=identity,
                     message=f"{segment['title']}: {detail}")
            if substitute_for:
                # A stand-in is not the agent the story is about, so the Anchor
                # asks rather than letting the substitute characterise work it
                # did not do. §6: the Anchor must not invent another agent's
                # experience when that agent can supply it - and a substitute
                # speaking for the absent one is the same error wearing a
                # colleague's face.
                asked = request_more(
                    conn, asker=anchor_identity, segment_title=segment["title"],
                    subject_role=identity.rsplit("-", 1)[0])
                if asked:
                    _publish(conn, event_type="broadcast.enquiry", agent=anchor_identity,
                             message=f"{segment['title']}: asked {asked} for its own account")

    if kind == broadcast.SEGMENT_NEWS_FLASH:
        # §7: "For breaking or interactive situations, the Anchor may query the
        # knowledge system or relevant agents in real time." A flash is that
        # situation by definition, so the Anchor puts the question rather than
        # reading a prepared line about an event that is still developing.
        for story_id in json.loads(script["story_ids"]):
            story = conn.fetchone("SELECT subject_identity FROM stories WHERE id = ?",
                                  (story_id,))
            subject = (story or {}).get("subject_identity")
            if not subject:
                continue
            asked = request_more(conn, asker=anchor_identity,
                                 segment_title=segment["title"],
                                 subject_role=subject.rsplit("-", 1)[0])
            if asked:
                _publish(conn, event_type="broadcast.enquiry", agent=anchor_identity,
                         message=f"{segment['title']}: asked {asked} live for its own account")

    broadcast.air(conn, segment["id"],
                  detail=f"aired with {len(guests)} guest(s): {', '.join(guests) or 'none'}")
    broadcast.mark_stories(conn, json.loads(script["story_ids"]), broadcast.STORY_AIRED)
    _publish(conn,
             event_type=("broadcast.news_flash" if kind == broadcast.SEGMENT_NEWS_FLASH
                         else "broadcast.programme"),
             agent=anchor_identity,
             severity="warning" if kind == broadcast.SEGMENT_NEWS_FLASH else "info",
             message=f"{segment['title']}: {script['headline']}")

    # Coming out of a flash, the pre-empted programme goes back on the schedule.
    # The interruption is only half the workflow; a station that never returned
    # would be one that broke rather than one that cut away.
    if kind == broadcast.SEGMENT_NEWS_FLASH:
        for pre_empted in conn.fetchall(
                "SELECT id FROM run_of_show WHERE day_id = ? AND interrupted_by = ?",
                (day_id, segment["id"])):
            broadcast.resume_segment(conn, pre_empted["id"])
            _publish(conn, event_type="broadcast.resumed", agent=anchor_identity,
                     message=f"returning to the scheduled programme after {segment['title']}")

    result["guests"] = guests
    return result
