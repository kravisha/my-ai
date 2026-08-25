"""The server console (backend/console/ + /console routes; addendum 38 §4,
owner decision SPEC_RECONCILIATION §75; TQ-26).

The live newspaper: narration of everything the organization is doing, with
filters derived from the stream rather than enumerated, and a standing-status
view answering the question a scrolling feed cannot. What this suite holds is
the API the page renders from — the page itself is one dependency-free file,
verified by loading it against a real backend rather than by asserting on
markup.
"""

from pathlib import Path

import pytest

from backend import fi_db, metadata_engine, status_events

CONSOLE_HTML = Path(__file__).resolve().parent.parent / "backend" / "console" / "index.html"


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A file-backed database plus `app.state.db_path` pointing at it.

    File-backed rather than `:memory:` on purpose: since §78 the console
    routes hand a *path* to a worker thread which opens its own connection
    there, and two `:memory:` connections are two different empty databases.
    Using a real file means these tests exercise the actual production path -
    worker thread, own connection - rather than a shortcut around it.

    Yields the connection the test writes through; the routes read the same
    file from their own."""
    from backend import main as backend_main

    db_path = tmp_path / "fi.db"
    conn = fi_db.get_connection(str(db_path))
    fi_db.init_schema(conn)

    monkeypatch.setattr(backend_main.app.state, "db_path", str(db_path), raising=False)
    monkeypatch.setattr(backend_main.app.state, "startup_report", None, raising=False)
    try:
        yield conn, backend_main
    finally:
        conn.close()


def _feed(wired, **params):
    """Await /console/feed on this thread; the route does its reading on a
    worker thread with its own connection."""
    import asyncio

    _, backend_main = wired
    defaults = {"limit": 200, "source": None, "attention_only": False, "since_id": None}
    defaults.update(params)
    return asyncio.run(backend_main.console_feed(**defaults))


def _publish(conn, message, **overrides):
    payload = {"engine": "metadata_engine", "severity": status_events.SEVERITY_INFO}
    payload.update(overrides)
    return status_events.publish(conn, "state_change", message, **payload)


# --- the page --------------------------------------------------------------------


def test_console_page_is_served():
    """Served as a file; no database involved, so TestClient is fine here."""
    from fastapi.testclient import TestClient

    from backend import main as backend_main

    response = TestClient(backend_main.app).get("/console")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Declared, not guessed - the page carries Tamil script (addendum 41's
    # studio is the same document that holds the language picker).
    assert "charset=utf-8" in response.headers["content-type"].lower()
    assert "Kumbhakarnan" in response.text


def test_page_is_self_contained():
    """No build step and no CDN: the backend is loopback-only and the whole
    surface is two read endpoints. A bundler would be more machinery than the
    thing it builds."""
    html = CONSOLE_HTML.read_text(encoding="utf-8")
    assert "<script src=" not in html          # no external JS
    assert "cdn" not in html.lower()
    assert "/console/feed" in html             # it reads the API this suite tests


# --- the feed (§4.2/§4.4) ---------------------------------------------------------


def test_feed_returns_narration_newest_first(wired):
    conn, _ = wired
    for i in range(3):
        _publish(conn, f"event {i}")
    body = _feed(wired)
    assert [e["message"] for e in body["events"]] == ["event 2", "event 1", "event 0"]


def test_feed_filters_by_source(wired):
    conn, _ = wired
    _publish(conn, "from metadata")
    _publish(conn, "from explorer", engine=None, agent="explorer-1")
    body = _feed(wired, source="explorer-1")
    assert [e["message"] for e in body["events"]] == ["from explorer"]


def test_feed_filters_to_attention_only(wired):
    conn, _ = wired
    _publish(conn, "routine")
    _publish(conn, "concerning", severity=status_events.SEVERITY_WARNING)
    _publish(conn, "broken", severity=status_events.SEVERITY_ERROR)
    body = _feed(wired, attention_only=True)
    assert {e["message"] for e in body["events"]} == {"concerning", "broken"}


def test_since_id_sends_only_what_is_new(wired):
    conn, _ = wired
    """A console left open all day sends deltas rather than re-fetching the
    whole feed - the restraint §13 asks of publishers, applied to the reader."""
    first = _publish(conn, "old news")
    body = _feed(wired)
    assert body["events"]

    _publish(conn, "breaking news")
    delta = _feed(wired, since_id=first)
    assert [e["message"] for e in delta["events"]] == ["breaking news"]


def test_feed_limit_is_capped(wired):
    conn, _ = wired
    """An operator cannot ask the server for an unbounded page."""
    for i in range(5):
        _publish(conn, f"event {i}")
    body = _feed(wired, limit=100000)
    assert len(body["events"]) == 5  # capped path still returns what exists


# --- the sidebar -----------------------------------------------------------------


def test_filter_list_is_derived_not_enumerated(wired):
    conn, _ = wired
    """§4.4's real requirement: a new department appears because it
    published, not because the page was edited."""
    _publish(conn, "hello", engine=None, department="Department of Cheese")
    body = _feed(wired)
    names = {s["name"] for s in body["sources"]}
    assert "Department of Cheese" in names


def test_standing_answers_where_things_stand(wired):
    conn, _ = wired
    """The question a scrolling feed cannot answer without the reader doing
    the work by eye (§4.5)."""
    _publish(conn, "starting", status=status_events.STATUS_STARTING)
    _publish(conn, "now idle", status=status_events.STATUS_IDLE)
    _publish(conn, "waiting on data", engine="simulation_engine",
             status=status_events.STATUS_WAITING)

    standing = {e["source_engine"]: e for e in _feed(wired)["standing"]}
    assert standing["metadata_engine"]["status"] == status_events.STATUS_IDLE  # latest wins
    assert standing["simulation_engine"]["status"] == status_events.STATUS_WAITING


def test_awaiting_login_is_reported_so_the_page_can_say_so(wired):
    conn, _ = wired
    """38 §12: a dormant system must look dormant rather than look broken."""
    assert _feed(wired)["awaiting_login"] is True


def test_feed_before_the_database_is_known_is_empty_not_an_error(monkeypatch):
    """A console opened while the server is still coming up must render,
    not 500."""
    import asyncio

    from backend import main as backend_main

    monkeypatch.setattr(backend_main.app.state, "db_path", None, raising=False)
    body = asyncio.run(backend_main.console_feed(limit=50, source=None,
                                                 attention_only=False, since_id=None))
    assert body == {"events": [], "sources": [], "standing": [], "awaiting_login": True,
                    # Not 0: with no database, "how many agents are running" has
                    # no answer, and 0 would be an answer (TQ-38, §87).
                    "live_agents": None}


# --- the whole startup, as the operator would read it ------------------------------


def test_a_real_startup_is_readable_end_to_end(wired):
    conn, _ = wired
    """The console's actual job: after a startup, an operator can read what
    happened, see where everything stands, and filter to what needs
    attention - without having watched it live."""
    metadata_engine.run(conn)
    body = _feed(wired)

    messages = [e["message"] for e in body["events"]]
    assert any("Metadata Engine starting" in m for m in messages)
    assert any("Metadata ready" in m for m in messages)
    assert "metadata_engine" in {s["name"] for s in body["sources"]}
    assert body["standing"][0]["status"] == status_events.STATUS_IDLE


# --- the console cannot state a falsehood about the workforce (TQ-38, §87) --------


def test_awaiting_login_and_live_agents_are_reported_as_separate_facts(wired):
    """The console said "workforce dormant, awaiting operator login" while six
    agents worked behind it, because it derived one fact from the other:
    `awaiting_login` came from `startup_report is None`, and the page rendered
    that as though it meant "nothing is running".

    They are different questions. One is about authorisation - has an operator
    started a workforce in this process. The other is about the world - are
    agents running. A server can be dormant while agents survive an unclean
    shutdown, and that is exactly the situation the operator most needs to see.
    """
    conn, _ = wired
    fi_db.register_agent(conn, "speculator-1", "speculator", pid=4242)
    fi_db.record_heartbeat(conn, "speculator-1")

    body = _feed(wired)

    assert body["awaiting_login"] is True, "no operator has started a workforce"
    assert body["live_agents"] == 1, (
        "an agent heartbeating right now must be reported as running, whatever "
        "the startup report says"
    )


def test_a_genuinely_dormant_server_reports_no_live_agents(wired):
    """The ordinary case, asserted so the previous test cannot pass by always
    returning a number greater than zero."""
    conn, _ = wired
    assert _feed(wired)["live_agents"] == 0


def test_liveness_comes_from_heartbeats_not_from_the_registry_s_belief(wired):
    """`agent_registry.process_state` says "running" for every process the
    machine lost in an unclean shutdown - it is what the registry was last
    told, not what is true. A heartbeat inside the threshold cannot be stale by
    construction, because something had to write it."""
    conn, _ = wired
    fi_db.register_agent(conn, "analysis-1", "analysis", pid=99)
    # Registered, never heartbeated: claimed by the registry, silent in fact.
    assert _feed(wired)["live_agents"] == 0

    stale = "2020-01-01T00:00:00+00:00"
    conn.execute("UPDATE agent_registry SET process_state='running', "
                 "last_heartbeat_at=? WHERE identity='analysis-1'", (stale,))
    assert _feed(wired)["live_agents"] == 0, (
        "a six-year-old heartbeat is not a running process"
    )


def test_the_controller_is_not_counted_as_a_stray_agent(wired):
    """The Controller heartbeats every tick *by design*, including while the
    server is dormant, so that a healthy Controller is distinguishable from a
    dead one. It runs inside this process rather than as a subprocess.

    The first version of the liveness check counted it, and a dormant server
    announced "1 agent(s) are heartbeating... nothing in this process started
    them" about its own Controller. Found by starting the server and reading
    what it printed - the fix for a console that stated a falsehood had
    introduced a fresh one."""
    from backend.controller import CONTROLLER_IDENTITY

    conn, backend_main = wired
    fi_db.register_agent(conn, CONTROLLER_IDENTITY, "controller", pid=1)
    fi_db.record_heartbeat(conn, CONTROLLER_IDENTITY)

    assert _feed(wired)["live_agents"] == 0
    assert backend_main.live_agents(conn) == []
