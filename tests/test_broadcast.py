"""The television station, and the separations it is built on
(backend/broadcast.py, newsroom.py, gallery.py; agents/anchor.py, producer.py;
docs/SPEC_RECONCILIATION.md §160).

Stage 1 tests, deliberately: does the component exist, does it connect, can the
end-to-end process complete. The Development Philosophy §10 is explicit that the
final standard is not required at the first testing layer, so nothing here
asserts editorial quality, ordering elegance or wording.

What it *does* assert is the small number of things that would make the station
dishonest rather than merely rough:

- a story with no source record cannot be filed;
- an executive cannot quietly become the permanent presenter again;
- a programme whose remit nothing feeds would silently never air;
- a breaking story cannot also be read as a calm item later.
"""

import ast
import inspect

import pytest

from agents import anchor, coo, producer
from backend import broadcast, fi_db, gallery, newsroom


@pytest.fixture(autouse=True)
def fast_clock(monkeypatch):
    """Run the rundown at a scale where a whole day fits in a unit test.

    The clock is real by default: a programme billed at ninety seconds occupies
    ninety, which is what stopped a 695-second day airing in thirteen. A test
    walking a full day would otherwise sit through it, so the scale moves and
    nothing else does - the rundown still declares the same durations."""
    monkeypatch.setenv("FI_BROADCAST_TIME_SCALE", "100000")


@pytest.fixture
def conn(tmp_path):
    connection = fi_db.get_connection(str(tmp_path / "tv.db"))
    fi_db.init_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


def _staff(conn, *pairs):
    for identity, role in pairs:
        fi_db.register_agent(conn, identity, role, abs(hash(identity)) % 9000)


# -- the separation the Dedicated Anchor specification exists for -----------------


def test_the_executive_does_not_present():
    """§13: executive agents run the organization, the Anchor explains it.

    Asserted against the COO's source rather than by running a broadcast,
    because the coupling this forbids is re-introduced by *adding a call*, and
    the moment it is added is the moment to fail (§136: a seam asserted by
    reading source is not a seam that runs - but a seam that must not exist is
    exactly what source can prove)."""
    tree = ast.parse(inspect.getsource(coo))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "present_next" not in called, (
        "agents/coo.py presents. The Dedicated Anchor specification supersedes any "
        "earlier design that made an executive the permanent presenter, and §13 "
        "forbids re-coupling them.")


def test_the_anchor_presents():
    """The other half. A role that exists and never presents is not a separation,
    it is a deletion."""
    tree = ast.parse(inspect.getsource(anchor))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "present_next" in called


def test_the_producer_does_not_present_and_the_anchor_does_not_produce():
    """§11's split, both ways. A producer that presents is the anchor deciding
    what is newsworthy one identity along."""
    produced = {
        node.func.attr for node in ast.walk(ast.parse(inspect.getsource(producer)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    presented = {
        node.func.attr for node in ast.walk(ast.parse(inspect.getsource(anchor)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "present_next" not in produced
    assert "produce" not in presented


def test_a_running_anchor_presents_rather_than_the_executive(conn):
    _staff(conn, ("anchor-1", "anchor"), ("coo-1", "coo"), ("speaker-1", "speaker"))
    identity, is_fallback, _ = gallery.resolve_presenter(conn)
    assert identity == "anchor-1" and is_fallback is False


def test_a_second_anchor_is_a_backup_rather_than_a_second_presenter(conn):
    """§9: the role supports more than one instance. Two anchors must not both
    present - that would air two segments a cycle and interleave the rundown."""
    _staff(conn, ("anchor-1", "anchor"), ("anchor-2", "anchor"))
    identity, is_fallback, detail = gallery.resolve_presenter(conn)
    assert identity == "anchor-1" and is_fallback is False
    assert "backup" in detail


def test_the_station_stays_on_air_when_no_anchor_is_running(conn):
    """§8: the system must not fail because one Anchor is unavailable - and the
    substitute is recorded as a fallback, because §8 is equally explicit that it
    must not become the normal architecture."""
    _staff(conn, ("coo-1", "coo"), ("speaker-1", "speaker"))
    identity, is_fallback, detail = gallery.resolve_presenter(conn)
    assert identity == "speaker-1" and is_fallback is True
    assert "fallback" in detail


def test_with_nobody_running_the_station_says_so_rather_than_guessing(conn):
    identity, is_fallback, detail = gallery.resolve_presenter(conn)
    assert identity is None and is_fallback is True


# -- provenance ------------------------------------------------------------------


def test_a_story_carries_the_record_it_came_from(conn):
    broadcast.open_day(conn, "day-1")
    story_id = broadcast.file_story(
        conn, day_id="day-1", kind=newsroom.KIND_DETECTION, headline="h", summary="s",
        source_table="detector_events", source_id="7",
        urgency=broadcast.URGENCY_ROUTINE)
    row = conn.fetchone("SELECT * FROM stories WHERE id = ?", (story_id,))
    assert row["source_table"] == "detector_events" and row["source_id"] == "7"


def test_the_same_record_is_not_reported_twice_in_one_day(conn):
    """The newsroom runs every cycle. Without this it would re-file the same
    incident until the schedule carried nothing else."""
    broadcast.open_day(conn, "day-1")
    first = broadcast.file_story(
        conn, day_id="day-1", kind=newsroom.KIND_INCIDENT, headline="h", summary="s",
        source_table="incidents", source_id="1", urgency=broadcast.URGENCY_BREAKING)
    again = broadcast.file_story(
        conn, day_id="day-1", kind=newsroom.KIND_INCIDENT, headline="h", summary="s",
        source_table="incidents", source_id="1", urgency=broadcast.URGENCY_BREAKING)
    assert first is not None and again is None


def test_an_unknown_urgency_is_refused(conn):
    broadcast.open_day(conn, "day-1")
    with pytest.raises(ValueError):
        broadcast.file_story(
            conn, day_id="day-1", kind="detection", headline="h", summary="s",
            source_table="t", source_id="1", urgency="catastrophic")


# -- the schedule ----------------------------------------------------------------


def test_every_programme_remit_is_fed_by_something():
    """A programme whose remit no story kind feeds could never air, and would
    drop every day while looking like a scheduling accident. `summary` is fed by
    what already aired rather than by a kind, which is why it is checked
    separately rather than being an exception nobody wrote down."""
    fed = set(newsroom.REMIT_OF_KIND.values()) | {newsroom.REMIT_SUMMARY}
    needed = {p["remit"] for p in broadcast.PROGRAMME_CATALOGUE}
    assert not needed - fed, f"programmes with no source of stories: {sorted(needed - fed)}"


def test_every_programme_beat_names_a_real_role():
    """A beat pointing at a role that does not exist books nobody, silently, for
    the life of the programme."""
    for programme in broadcast.PROGRAMME_CATALOGUE:
        if programme["guest_role"]:
            assert programme["guest_role"] in fi_db.ROLE_CHARTERS, (
                f"{programme['name']} books {programme['guest_role']!r}, which is not a role")


def test_the_run_of_show_has_breaks_and_a_sign_off(conn):
    broadcast.open_day(conn, "day-1")
    kinds = [s["kind"] for s in broadcast.segments_of(conn, "day-1")]
    assert broadcast.SEGMENT_AD_BREAK in kinds
    assert kinds[-1] == broadcast.SEGMENT_SIGN_OFF
    assert len(broadcast.ad_slots_of(conn, "day-1")) >= 1


def test_commercial_inventory_is_unsold_rather_than_pretended(conn):
    """Nothing sells one yet. An advertiser placeholder would read as a booked
    client, which is the one thing this must not imply before there is one."""
    broadcast.open_day(conn, "day-1")
    for slot in broadcast.ad_slots_of(conn, "day-1"):
        assert slot["status"] == broadcast.AD_UNSOLD and slot["advertiser"] is None


# -- breaking news ---------------------------------------------------------------


def test_a_breaking_story_never_reaches_a_programme(conn):
    """It belongs to a news flash. A programme that also carried it would report
    the same event twice - once as an interruption and once as a calm item."""
    broadcast.open_day(conn, "day-1")
    broadcast.file_story(
        conn, day_id="day-1", kind=newsroom.KIND_INCIDENT, headline="agent down",
        summary="s", source_table="incidents", source_id="1",
        urgency=broadcast.URGENCY_BREAKING)
    assert newsroom.stories_for_remit(conn, "day-1", "operations") == []


def test_breaking_news_interrupts_and_the_schedule_resumes(conn):
    """The interruption is only half the workflow. A station that never came
    back would have broken rather than cut away."""
    _staff(conn, ("anchor-1", "anchor"), ("producer-1", "producer"),
           ("analysis-1", "analysis"))
    broadcast.open_day(conn, "day-1")
    conn.execute(
        "INSERT INTO incidents (subject_identity, subject_role, detected_by, detected_at,"
        " symptom, status, schema_version) VALUES ('analysis-1','analysis','coo-1',?,"
        "'heartbeat stopped moving','open',1)", (fi_db._now(),))
    gallery.produce(conn, "day-1", producer_identity="producer-1")

    interrupted = [s for s in broadcast.segments_of(conn, "day-1")
                   if s["status"] == broadcast.SEGMENT_INTERRUPTED]
    assert interrupted, "a breaking story did not pre-empt anything"

    for _ in range(20):
        if gallery.present_next(conn, "day-1", anchor_identity="anchor-1") is None:
            break
        gallery.produce(conn, "day-1", producer_identity="producer-1")

    resumed = [s for s in broadcast.segments_of(conn, "day-1") if s["resumed_at"]]
    assert resumed, "the schedule never returned to the pre-empted programme"


# -- fallbacks are completeness --------------------------------------------------


def test_a_programme_is_not_dropped_before_its_own_airtime(conn):
    """Closing Bell recaps what aired, so when the rundown is first produced it is
    empty by definition. Dropping it there killed it before the day happened."""
    _staff(conn, ("producer-1", "producer"))
    broadcast.open_day(conn, "day-1")
    gallery.produce(conn, "day-1", producer_identity="producer-1")
    statuses = {s["title"]: s["status"] for s in broadcast.segments_of(conn, "day-1")}
    assert statuses["Closing Bell"] == broadcast.SEGMENT_SCHEDULED


def test_a_segment_with_no_script_is_dropped_and_the_schedule_continues(conn):
    """Philosophy §11's safe skip-and-continue, applied at the only moment the
    answer is final."""
    _staff(conn, ("anchor-1", "anchor"))
    broadcast.open_day(conn, "day-1")
    first = gallery.present_next(conn, "day-1", anchor_identity="anchor-1")
    assert first is not None and "dropped" in (first.get("detail") or "")
    assert gallery.present_next(conn, "day-1", anchor_identity="anchor-1") is not None


def test_an_absent_guest_is_substituted_by_one_of_its_own_role(conn):
    _staff(conn, ("anchor-1", "anchor"), ("analysis-1", "analysis"), ("analysis-2", "analysis"))
    broadcast.open_day(conn, "day-1")
    segment = broadcast.segments_of(conn, "day-1")[0]
    broadcast.write_script(conn, segment_id=segment["id"], prepared_by="producer-1",
                           headline="h", body="b", story_ids=[])
    broadcast.book(conn, segment_id=segment["id"], day_id="day-1",
                   identity="analysis-1", role_on_air=broadcast.ROLE_GUEST)
    fi_db.mark_process_stopped(conn, "analysis-1")

    gallery.present_next(conn, "day-1", anchor_identity="anchor-1")

    booking = broadcast.appearances_of(conn, "day-1")[0]
    assert booking["outcome"] == broadcast.APPEARANCE_SUBSTITUTED
    assert booking["appeared_identity"] == "analysis-2"


def test_the_anchor_asks_rather_than_speaking_for_an_agent(conn):
    """§6: the Anchor must not invent another agent's experience when that agent
    can supply it - and a substitute characterising work it did not do is the
    same error wearing a colleague's face. So a substitution puts a question."""
    _staff(conn, ("anchor-1", "anchor"), ("analysis-1", "analysis"), ("analysis-2", "analysis"))
    broadcast.open_day(conn, "day-1")
    segment = broadcast.segments_of(conn, "day-1")[0]
    broadcast.write_script(conn, segment_id=segment["id"], prepared_by="producer-1",
                           headline="h", body="b", story_ids=[])
    broadcast.book(conn, segment_id=segment["id"], day_id="day-1",
                   identity="analysis-1", role_on_air=broadcast.ROLE_GUEST)
    fi_db.mark_process_stopped(conn, "analysis-1")

    gallery.present_next(conn, "day-1", anchor_identity="anchor-1")

    asked = conn.fetchall("SELECT asked_by, target_identity FROM uqi_requests")
    assert asked and asked[0]["asked_by"] == "anchor-1", (
        "the anchor let a stand-in speak for the absent agent without asking it anything")


# -- the whole thing ---------------------------------------------------------------


def test_the_speaker_is_invited_to_discuss_parliament(conn):
    """A governance story is about the organization rather than about one agent,
    so it names no subject. The Speaker already reads the state of the House and
    files a report as its ordinary work - appearing to discuss it is that job
    with an audience."""
    _staff(conn, ("anchor-1", "anchor"), ("producer-1", "producer"), ("speaker-1", "speaker"))
    broadcast.open_day(conn, "day-1")
    conn.execute(
        "INSERT INTO governed_items (adopted_at, subject, level, text, binds, adopted_by,"
        " resolution_id, schema_version) VALUES (?, 'report_filing', 'organization_policy',"
        " 'Reports must name their lens.', '*', 'coo-1', 1, 1)", (fi_db._now(),))
    gallery.produce(conn, "day-1", producer_identity="producer-1")

    booked = [a for a in broadcast.appearances_of(conn, "day-1")
              if a["booked_identity"] == "speaker-1"]
    assert booked, "Parliament's programme booked nobody to discuss Parliament"
    assert booked[0]["role_on_air"] == broadcast.ROLE_PANELIST


def test_the_station_runs_from_open_to_sign_off(conn):
    """Stage 2's question, at unit scale: did every expected kind of action
    happen? Not in the right order, not well - just at all."""
    _staff(conn, ("anchor-1", "anchor"), ("producer-1", "producer"),
           ("explorer-1", "explorer"), ("speaker-1", "speaker"), ("analysis-1", "analysis"))
    now = fi_db._now()
    conn.execute(
        "INSERT INTO detector_events (created_at, producer_identity, producer_spawned_at,"
        " security, detector_type, peak_iv, baseline_iv, ratio, threshold, neighborhood_desc,"
        " surface_seed, scope, schema_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
        (now, "explorer-1", now, "JE-000001", "iv_spike", 0.62, 0.44, 1.42, 1.2, "n", 4, "local"))
    broadcast.open_day(conn, "day-1")

    aired = []
    for _ in range(25):
        gallery.produce(conn, "day-1", producer_identity="producer-1")
        result = gallery.present_next(conn, "day-1", anchor_identity="anchor-1")
        if result is None:
            break
        aired.append(result["kind"])

    assert broadcast.SEGMENT_PROGRAMME in aired
    assert broadcast.SEGMENT_AD_BREAK in aired
    assert broadcast.SEGMENT_SIGN_OFF in aired
    day = conn.fetchone("SELECT * FROM broadcast_days WHERE day_id = 'day-1'")
    assert day["status"] == broadcast.DAY_CLOSED
    assert day["anchor_identity"] == "anchor-1", "the day was not billed to its presenter"


# -- the broadcast clock ---------------------------------------------------------
#
# `planned_seconds` was a decorative column: every segment declared a duration and
# nothing read one, so a 695-second rundown aired in thirteen work cycles and a
# three-minute run produced fourteen broadcast days. A column nothing reads is
# §149's shape, and these are what make it mean something.


def test_a_segment_waits_for_the_previous_one_to_finish(conn, monkeypatch):
    monkeypatch.setenv("FI_BROADCAST_TIME_SCALE", "1")
    _staff(conn, ("anchor-1", "anchor"))
    broadcast.open_day(conn, "day-1")
    segment = broadcast.segments_of(conn, "day-1")[0]
    broadcast.write_script(conn, segment_id=segment["id"], prepared_by="producer-1",
                           headline="h", body="b", story_ids=[])

    first = gallery.present_next(conn, "day-1", anchor_identity="anchor-1")
    assert first["kind"] == broadcast.SEGMENT_PROGRAMME

    second = gallery.present_next(conn, "day-1", anchor_identity="anchor-1")
    assert second["kind"] == "waiting", (
        "the next segment aired immediately; the rundown's declared durations are "
        "not being honoured")
    due, remaining = broadcast.segment_is_due(conn, "day-1")
    assert due is False and remaining > 0


def test_breaking_news_does_not_wait_for_the_schedule(conn, monkeypatch):
    """A flash that queued behind a ninety-second programme would not be
    breaking. The exemption is the whole point of the segment."""
    monkeypatch.setenv("FI_BROADCAST_TIME_SCALE", "1")
    _staff(conn, ("anchor-1", "anchor"), ("producer-1", "producer"), ("analysis-1", "analysis"))
    broadcast.open_day(conn, "day-1")
    segment = broadcast.segments_of(conn, "day-1")[0]
    broadcast.write_script(conn, segment_id=segment["id"], prepared_by="producer-1",
                           headline="h", body="b", story_ids=[])
    gallery.present_next(conn, "day-1", anchor_identity="anchor-1")
    assert broadcast.segment_is_due(conn, "day-1")[0] is False

    conn.execute(
        "INSERT INTO incidents (subject_identity, subject_role, detected_by, detected_at,"
        " symptom, status, schema_version) VALUES ('analysis-1','analysis','coo-1',?,"
        "'heartbeat stopped moving','open',1)", (fi_db._now(),))
    gallery.produce(conn, "day-1", producer_identity="producer-1")

    assert broadcast.segment_is_due(conn, "day-1")[0] is True, (
        "breaking news waited for the schedule")


def test_the_station_does_not_come_straight_back_on_air(conn, monkeypatch):
    """The executive reopening the instant sign-off landed is what turned one
    broadcast day into fourteen."""
    monkeypatch.setenv("FI_BROADCAST_TIME_SCALE", "1")
    monkeypatch.setenv("FI_BROADCAST_DAY_GAP_SECONDS", "3600")
    broadcast.open_day(conn, "day-1")
    assert broadcast.ready_for_a_new_day(conn) is False, "a day is already running"
    broadcast.close_day(conn, "day-1")
    assert broadcast.ready_for_a_new_day(conn) is False, (
        "the station went straight back on air after sign-off")


def test_the_gap_does_eventually_pass(conn, monkeypatch):
    """The other side. A gap nothing can wait out is a station that goes off air
    once and never returns."""
    monkeypatch.setenv("FI_BROADCAST_TIME_SCALE", "1")
    monkeypatch.setenv("FI_BROADCAST_DAY_GAP_SECONDS", "0")
    broadcast.open_day(conn, "day-1")
    broadcast.close_day(conn, "day-1")
    assert broadcast.ready_for_a_new_day(conn) is True


# -- the one programme that reports on subjects ----------------------------------


def test_every_sector_on_air_comes_from_the_catalogue(conn):
    """`Where Nobody Is Looking` is the only programme not reporting the
    organization's own record, so the catalogue is what keeps it sourced. A
    station that improvised a subject would be doing the one thing a newsroom
    must not."""
    from backend import sectors

    broadcast.open_day(conn, "day-1")
    newsroom.gather(conn, "day-1")
    stories = broadcast.stories_for(conn, "day-1", kind=newsroom.KIND_SECTOR)
    assert stories, "the catalogue produced no stories"

    known = {str(s["id"]) for s in sectors.all_sectors(conn)}
    for story in stories:
        assert story["source_table"] == "emerging_sectors"
        assert story["source_id"] in known, (
            "a sector went to air that is not in the catalogue")


def test_a_sector_goes_to_air_with_its_standing(conn):
    """These are premises, not findings. A confident sentence about an unexamined
    idea is how a station starts making claims its organization cannot support,
    so the standing travels with the item."""
    broadcast.open_day(conn, "day-1")
    newsroom.gather(conn, "day-1")
    for story in broadcast.stories_for(conn, "day-1", kind=newsroom.KIND_SECTOR):
        assert "premise" in story["summary"]
        assert "has not investigated" in story["summary"]


def test_an_unknown_standing_is_refused(conn):
    from backend import sectors

    with pytest.raises(ValueError):
        sectors.add(conn, slug="x", name="X", field="f", premise="p", benefit="b",
                    why_overlooked="w", added_by="owner", evidence_note="proven")


def test_the_sector_programme_books_the_head_of_strategy(conn):
    """An under-examined sector is a strategy question, and a sector story is
    about the subject rather than about an agent - so it names no subject and
    would otherwise book nobody."""
    _staff(conn, ("anchor-1", "anchor"), ("producer-1", "producer"),
           ("strategy_head-1", "strategy_head"))
    broadcast.open_day(conn, "day-1")
    gallery.produce(conn, "day-1", producer_identity="producer-1")

    booked = [a for a in broadcast.appearances_of(conn, "day-1")
              if a["booked_identity"] == "strategy_head-1"]
    assert booked, "nobody was booked to discuss the overlooked sectors"
