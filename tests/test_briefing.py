"""The live briefing (backend/briefing.py; addendum 41 §8, §9, §16, §21, §22;
TQ-37, SPEC_RECONCILIATION §90).

§8 gives four example lines the COO might say. Every one of them is a count or a
name — which means every one can be wrong in a way the operator has no way to
check, and a confidently wrong briefing is worse than no briefing at all.

So most of this suite is about what the COO refuses to claim: no window without
a real last-seen time, no news on a quiet morning, no approval queue invented to
satisfy an example that has no source. The rest holds §16's rhythm and §8's
promise that the display follows the narration.
"""

import pytest

from backend import briefing, chatterbox, fi_db, status_events, workspace
from backend.briefing import (
    CATEGORIES, CATEGORY_ATTENTION, CATEGORY_BLOCKED, CATEGORY_COMPLETED,
    CATEGORY_UNDERWAY,
)


@pytest.fixture
def conn(tmp_path):
    connection = fi_db.get_connection(str(tmp_path / "fi.db"))
    fi_db.init_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


def _publish(conn, message, **overrides):
    payload = {"engine": "metadata_engine", "severity": status_events.SEVERITY_INFO}
    payload.update(overrides)
    return status_events.publish(conn, "state_change", message, **payload)


def _categories(result):
    return [item["category"] for item in result["items"]]


# --- a quiet organization gets a briefing too --------------------------------------


def test_nothing_happening_is_a_briefing(conn):
    """A presenter that only works when there is news is a presenter that fails
    on a quiet morning. §8 does not ask for something to be found."""
    workspace.save(conn, {"activeTab": "newsroom"})
    result = briefing.compile(conn)
    assert result["quiet"] is True
    assert result["items"] == []
    assert "quiet" in result["note"].lower()
    assert briefing.spoken(result)


def test_quiet_and_cannot_tell_are_reported_as_the_two_facts_they_are(conn):
    """An empty briefing with no window is *both* "nothing to report" and "I
    could not have told you if there were" - and the first version of this
    reported only the reassuring half."""
    result = briefing.compile(conn)
    assert result["quiet"] is True and result["since"] is None
    assert "do not know when you were last here" in result["note"]
    assert "quiet" in result["note"].lower()


def test_a_quiet_briefing_never_raises_on_an_empty_database(conn):
    """Every section is optional and none may take the briefing down with it."""
    assert briefing.compile(conn)["items"] == []


# --- "while you were away" needs a real window -------------------------------------


def test_without_a_last_seen_time_nothing_is_called_new(conn):
    """The sharpest fabrication risk in the module. "Three tasks completed while
    you were away" over an unknown interval is an invented claim wearing a
    helpful phrase - so with no workspace checkpoint, the completed section is
    silent and the briefing says why."""
    _publish(conn, "a mission finished", status=status_events.STATUS_COMPLETED)

    result = briefing.compile(conn)

    assert result["since"] is None
    assert CATEGORY_COMPLETED not in _categories(result)
    assert "do not know when you were last here" in result["note"]


def test_the_window_comes_from_the_operator_s_own_checkpoint(conn):
    """The workspace is written continuously while somebody is here and not at
    all while nobody is, which makes it the honest answer to "when were you last
    at the console"."""
    workspace.save(conn, {"activeTab": "newsroom"})
    assert briefing.last_seen(conn) == workspace.load(conn)["updated_at"]


def test_completed_work_is_reported_against_that_window(conn):
    # An explicit window rather than the wall clock: on Windows two calls can
    # land in the same tick, which would make this test's result depend on
    # timer granularity rather than on the behaviour it is asserting.
    since = "2020-01-01T00:00:00+00:00"
    _publish(conn, "mission m-1 finished", status=status_events.STATUS_COMPLETED)
    _publish(conn, "mission m-2 finished", status=status_events.STATUS_COMPLETED,
             engine="simulation_engine")

    result = briefing.compile(conn, since=since)

    completed = [i for i in result["items"] if i["category"] == CATEGORY_COMPLETED]
    assert len(completed) == 1
    assert completed[0]["count"] == 2
    assert "2 things completed" in completed[0]["text"]


def test_work_completed_before_the_operator_left_is_not_news(conn):
    """Otherwise every visit would re-announce the same history."""
    _publish(conn, "old news", status=status_events.STATUS_COMPLETED)
    workspace.save(conn, {"activeTab": "newsroom"})

    result = briefing.compile(conn, since=briefing.last_seen(conn))
    assert CATEGORY_COMPLETED not in _categories(result)


def test_an_event_stamped_exactly_at_the_checkpoint_is_not_new(conn):
    """The boundary, and it is not theoretical: Windows' clock granularity is
    coarse enough that publishing an event and checkpointing the workspace in
    the same tick produces identical timestamps, which an inclusive `since`
    would report as news on every single visit."""
    workspace.save(conn, {"activeTab": "newsroom"})
    since = briefing.last_seen(conn)
    conn.execute("UPDATE status_events SET timestamp = ?", (since,))
    _publish(conn, "stamped at the boundary", status=status_events.STATUS_COMPLETED)
    conn.execute("UPDATE status_events SET timestamp = ? WHERE message = ?",
                 (since, "stamped at the boundary"))

    assert CATEGORY_COMPLETED not in _categories(briefing.compile(conn, since=since))


@pytest.mark.parametrize("seconds,expected", [
    (10, None), (89, None),          # a window switch is not an absence
    (600, "10 minutes"),
    (7200, "2 hours"),
    (172800, "2 days"),
])
def test_absence_is_described_in_units_a_person_uses(seconds, expected):
    """And a very short one is not described at all: telling an operator what
    changed in the eleven seconds they spent switching windows is noise dressed
    as attentiveness."""
    assert briefing._describe_absence(seconds) == expected


def test_an_unparseable_checkpoint_is_no_window_rather_than_a_wrong_one(conn):
    assert briefing._away_seconds("not a timestamp", "2026-08-25T00:00:00+00:00") is None


# --- §8's four questions, each from real state --------------------------------------


def test_a_failure_is_reported_with_its_source_and_view(conn):
    _publish(conn, "model provider unreachable", severity=status_events.SEVERITY_ERROR,
             status=status_events.STATUS_FAILED)

    item = briefing.compile(conn)["items"][0]

    assert item["category"] == CATEGORY_ATTENTION
    assert "metadata_engine" in item["text"]
    assert item["view"] == "alerts"
    assert item["focus"] == "metadata_engine"


def test_warnings_do_not_lead_the_briefing(conn):
    """A WARNING is worth seeing, not worth leading with - the same line
    status_events.failures already draws."""
    _publish(conn, "something to note", severity=status_events.SEVERITY_WARNING)
    assert CATEGORY_ATTENTION not in _categories(briefing.compile(conn))


def test_repeated_failures_from_one_source_become_one_line(conn):
    """A briefing is spoken. Eight lines saying the same engine failed is the
    feed read aloud, which the operator already has a scrollable version of."""
    for i in range(8):
        _publish(conn, f"attempt {i} failed", severity=status_events.SEVERITY_ERROR,
                 status=status_events.STATUS_FAILED)

    attention = [i for i in briefing.compile(conn)["items"]
                 if i["category"] == CATEGORY_ATTENTION]
    assert len(attention) == 1
    assert attention[0]["count"] == 8
    assert "8 failures in total" in attention[0]["text"]


def test_work_underway_names_the_components_doing_it(conn):
    _publish(conn, "scanning", status=status_events.STATUS_RUNNING)
    _publish(conn, "pricing", engine="simulation_engine", status=status_events.STATUS_RUNNING)

    underway = [i for i in briefing.compile(conn)["items"]
                if i["category"] == CATEGORY_UNDERWAY]
    assert underway and underway[0]["count"] == 2
    assert "metadata_engine" in underway[0]["text"]
    assert underway[0]["view"] == "organization"


def test_a_waiting_component_is_reported_as_blocked_not_idle(conn):
    """§8's second example. "Waiting" and "idle" are different facts and this
    system has always insisted on the difference."""
    _publish(conn, "waiting on market data", engine="simulation_engine",
             status=status_events.STATUS_WAITING)

    blocked = [i for i in briefing.compile(conn)["items"]
               if i["category"] == CATEGORY_BLOCKED]
    assert blocked and "waiting" in blocked[0]["text"]
    assert blocked[0]["focus"] == "simulation_engine"


def test_an_idle_component_is_not_reported_as_blocked(conn):
    _publish(conn, "nothing to do", status=status_events.STATUS_IDLE)
    assert CATEGORY_BLOCKED not in _categories(briefing.compile(conn))


def test_agents_mid_conversation_are_reported(conn, monkeypatch):
    """§8's third example, "Two agents are collaborating on TQ-27", from the
    living map rather than from a phrase."""
    monkeypatch.setattr(chatterbox, "living_map", lambda c, **kw: {
        "conversations": [{"state": chatterbox.STATE_ACTIVE, "from": "Explorer",
                           "to": "Analyst", "about": "SYN3", "asked_at": None}]})

    underway = [i for i in briefing.compile(conn)["items"]
                if i["category"] == CATEGORY_UNDERWAY]
    assert any("Explorer and Analyst" in i["text"] and "SYN3" in i["text"] for i in underway)
    assert any(i["view"] == "chatterbox" for i in underway)


def test_a_timed_out_question_is_blocked(conn, monkeypatch):
    """Silence is the chatterbox's own state, and it is a blockage rather than
    a quiet moment - somebody asked and nobody answered."""
    monkeypatch.setattr(chatterbox, "living_map", lambda c, **kw: {
        "conversations": [{"state": chatterbox.STATE_SILENT, "from": "Explorer",
                           "to": "Analyst", "about": None, "asked_at": None}]})

    blocked = [i for i in briefing.compile(conn)["items"]
               if i["category"] == CATEGORY_BLOCKED]
    assert any("heard nothing" in i["text"] for i in blocked)


def test_no_approval_queue_is_invented(conn):
    """§8's fourth example - "This item needs your approval" - has no source:
    nothing in this system records that the owner's approval is pending.
    Manufacturing one to satisfy an example would be exactly the fabrication
    the rest of this module exists to prevent, so it is deliberately absent and
    recorded as such in §90."""
    _publish(conn, "anything at all")
    for item in briefing.compile(conn)["items"]:
        assert "approval" not in item["text"].lower()
        assert item["category"] in CATEGORIES


# --- §16's rhythm -------------------------------------------------------------------


def test_the_main_story_is_whatever_is_most_true(conn):
    """§16 wants a broadcast order, not a fixed report order. With something
    broken, the failure leads."""
    workspace.save(conn, {"activeTab": "newsroom"})
    since = briefing.last_seen(conn)
    _publish(conn, "a thing finished", status=status_events.STATUS_COMPLETED)
    _publish(conn, "scanning", status=status_events.STATUS_RUNNING,
             engine="simulation_engine")
    _publish(conn, "provider unreachable", severity=status_events.SEVERITY_ERROR,
             status=status_events.STATUS_FAILED, engine="reference_data_engine")

    assert briefing.compile(conn, since=since)["items"][0]["category"] == CATEGORY_ATTENTION


def test_with_nothing_broken_the_news_leads_instead(conn):
    """A briefing that always opened with the same category would be a report."""
    workspace.save(conn, {"activeTab": "newsroom"})
    since = briefing.last_seen(conn)
    _publish(conn, "scanning", status=status_events.STATUS_RUNNING)
    _publish(conn, "a thing finished", status=status_events.STATUS_COMPLETED,
             engine="simulation_engine")

    assert briefing.compile(conn, since=since)["items"][0]["category"] == CATEGORY_COMPLETED


def test_a_briefing_is_bounded(conn):
    """Past a dozen lines it stops being a briefing and becomes the feed read
    aloud."""
    for i in range(40):
        _publish(conn, f"failure {i}", severity=status_events.SEVERITY_ERROR,
                 status=status_events.STATUS_FAILED, engine=None, agent=f"agent-{i}")
    assert len(briefing.compile(conn)["items"]) <= briefing.MAX_ITEMS


# --- §8: the display follows the narration -------------------------------------------


def test_every_item_names_a_view_the_console_can_open(conn, monkeypatch):
    """The mechanism behind §8's "relevant panel comes into focus". An item
    naming a view the console does not have would leave the display where it
    was while the COO talked about somewhere else."""
    from backend import view_intents

    workspace.save(conn, {"activeTab": "newsroom"})
    since = briefing.last_seen(conn)
    monkeypatch.setattr(chatterbox, "living_map", lambda c, **kw: {
        "conversations": [
            {"state": chatterbox.STATE_ACTIVE, "from": "A", "to": "B",
             "about": None, "asked_at": None},
            {"state": chatterbox.STATE_SILENT, "from": "C", "to": "D",
             "about": None, "asked_at": None}]})
    _publish(conn, "done", status=status_events.STATUS_COMPLETED)
    _publish(conn, "running", status=status_events.STATUS_RUNNING, engine="simulation_engine")
    _publish(conn, "waiting", status=status_events.STATUS_WAITING, engine="market_engine")
    _publish(conn, "broke", severity=status_events.SEVERITY_ERROR,
             status=status_events.STATUS_FAILED, engine="reference_data_engine")

    items = briefing.compile(conn, since=since)["items"]
    assert len(items) >= 5, "this test should exercise every section"
    for item in items:
        assert item["view"] in view_intents.VIEWS, f"{item['view']!r} is not a desk"


def test_spoken_form_carries_every_line(conn):
    """The voice path and the transcript are the same briefing addressed to two
    senses; one dropping a line the other has would make them disagree."""
    _publish(conn, "broke", severity=status_events.SEVERITY_ERROR,
             status=status_events.STATUS_FAILED)
    _publish(conn, "running", status=status_events.STATUS_RUNNING, engine="simulation_engine")

    result = briefing.compile(conn)
    text = briefing.spoken(result)
    for item in result["items"]:
        assert item["text"] in text


# --- §22: the presenter owns nothing --------------------------------------------------


def test_compiling_a_briefing_writes_nothing(conn):
    """§22: the presenter "must never own critical business state". The cheapest
    guarantee is that it owns no state at all - so this is a pure read, and a
    presenter that dies takes nothing with it."""
    _publish(conn, "something", severity=status_events.SEVERITY_ERROR,
             status=status_events.STATUS_FAILED)
    before = {table["name"]: conn.fetchone(f"SELECT COUNT(*) AS n FROM {table['name']}")["n"]
              for table in conn.fetchall(
                  "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    briefing.compile(conn)
    briefing.compile(conn)

    after = {table["name"]: conn.fetchone(f"SELECT COUNT(*) AS n FROM {table['name']}")["n"]
             for table in conn.fetchall(
                 "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    assert before == after


def test_the_presenter_has_no_table_of_its_own(conn):
    """§21's state lives in the workspace payload, which is declarative view
    state (§5.4's own category) and already discardable. A store of its own
    would be a thing the presenter owned, which is what §22 forbids."""
    tables = {row["name"] for row in conn.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any("presenter" in name for name in tables)
