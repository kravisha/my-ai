"""The status event stream (backend/status_events.py, addendum 38
§4.3/§4.4/§4.5/§4.6/§12/§13; TQ-24, SPEC_RECONCILIATION §73).

The observability spine of Pre-Alpha Milestone 1. What this suite holds:
the schema is the specification's and refuses vocabulary nobody defined; the
filter list is *derived* from the stream so a new department appears without
a UI edit (§4.4's actual requirement); the queries §4.5 lists are answerable
from real state; failures stay visible (§12); and the store stays bounded
(§13's warning against log flooding).
"""

import pytest

from backend import fi_db, metadata_engine, status_events
from backend.status_events import (
    SEVERITY_CRITICAL, SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING,
    STATUS_FAILED, STATUS_IDLE, STATUS_READY, STATUS_WAITING,
)


def _publish(conn, **overrides):
    payload = {
        "event_type": "state_change", "message": "something happened",
        "engine": "metadata_engine",
    }
    payload.update(overrides)
    event_type = payload.pop("event_type")
    message = payload.pop("message")
    return status_events.publish(conn, event_type, message, **payload)


# --- the schema is the specification's --------------------------------------------


def test_every_field_the_spec_names_is_stored(conn):
    """Addendum 38 §4.3's twelve fields, round-tripped."""
    event_id = status_events.publish(
        conn, "startup", "Explorer training task started",
        severity=SEVERITY_WARNING, status=STATUS_WAITING, lifecycle_stage="PRE_ALPHA",
        department="Education", engine="simulation_engine", agent="explorer-1",
        task_id="task-7", correlation_id="trace-1",
    )
    event = status_events.recent(conn, limit=1)[0]
    assert event["event_id"] == event_id
    assert event["timestamp"]
    assert event["lifecycle_stage"] == "PRE_ALPHA"
    assert event["source_department"] == "Education"
    assert event["source_engine"] == "simulation_engine"
    assert event["source_agent"] == "explorer-1"
    assert event["event_type"] == "startup"
    assert event["severity"] == SEVERITY_WARNING
    assert event["status"] == STATUS_WAITING
    assert event["message"] == "Explorer training task started"
    assert event["task_id"] == "task-7"
    assert event["correlation_id"] == "trace-1"


def test_unfilled_fields_stay_null_rather_than_padded(conn):
    """An engine is not an agent and startup is not a task. Inventing empty
    values to look schema-complete is how a schema stops meaning anything."""
    _publish(conn)
    event = status_events.recent(conn, limit=1)[0]
    assert event["source_agent"] is None
    assert event["task_id"] is None
    assert event["source_department"] is None


def test_vocabulary_is_fail_closed(conn):
    """A stream containing severities nobody defined cannot be filtered by
    severity, which is most of what a stream is for."""
    with pytest.raises(ValueError, match="unknown severity"):
        _publish(conn, severity="SPICY")
    with pytest.raises(ValueError, match="unknown status"):
        _publish(conn, status="VIBING")
    assert status_events.recent(conn) == []  # nothing was stored


def test_an_event_from_nowhere_is_refused(conn):
    """It would be in the table and invisible in every filtered view - the
    "failed component silently disappearing" §12 forbids, wearing a
    different hat."""
    with pytest.raises(ValueError, match="names no source"):
        status_events.publish(conn, "orphan", "who said this?")
    with pytest.raises(ValueError, match="empty message"):
        _publish(conn, message="")


def test_batch_refuses_unknown_fields(conn):
    """A typo'd 'sevrity' silently becoming INFO would be a stream that lies
    quietly."""
    with pytest.raises(ValueError, match="unknown field"):
        status_events.publish_many(conn, [
            {"event_type": "x", "message": "m", "engine": "e", "sevrity": "ERROR"},
        ])


# --- §4.2/§4.4 the feed and its filters -------------------------------------------


def test_feed_is_newest_first_and_limited(conn):
    for i in range(5):
        _publish(conn, message=f"event {i}")
    feed = status_events.recent(conn, limit=3)
    assert [e["message"] for e in feed] == ["event 4", "event 3", "event 2"]


def test_source_filter_matches_any_source_column(conn):
    """§4.4's filter list mixes departments, engines and agents in one
    control - an operator picking "Explorer" does not care which column it
    lives in."""
    _publish(conn, engine="reference_data_engine", message="ref")
    _publish(conn, engine=None, agent="explorer-1", message="by agent")
    _publish(conn, engine=None, department="Education", message="by department")

    assert [e["message"] for e in status_events.recent(conn, source="explorer-1")] == ["by agent"]
    assert [e["message"] for e in status_events.recent(conn, source="Education")] == ["by department"]
    assert [e["message"] for e in status_events.recent(conn, source="reference_data_engine")] == ["ref"]


def test_attention_filter_selects_warnings_and_worse(conn):
    """§4.4's Errors/Warnings filter."""
    _publish(conn, severity=SEVERITY_INFO, message="fine")
    _publish(conn, severity=SEVERITY_WARNING, message="odd")
    _publish(conn, severity=SEVERITY_ERROR, message="broken")
    _publish(conn, severity=SEVERITY_CRITICAL, message="very broken")

    got = status_events.recent(conn, severities=status_events.ATTENTION_SEVERITIES)
    assert {e["message"] for e in got} == {"odd", "broken", "very broken"}
    with pytest.raises(ValueError, match="unknown severity filter"):
        status_events.recent(conn, severities=("LOUD",))


def test_filter_list_is_derived_from_the_stream(conn):
    """§4.4's real requirement: "Architecture should allow new departments to
    appear without rewriting the UI." A hardcoded list fails the day a
    department is added; a derived one cannot."""
    assert status_events.sources(conn) == []

    _publish(conn, engine="metadata_engine")
    _publish(conn, engine="metadata_engine", severity=SEVERITY_ERROR)
    _publish(conn, engine=None, department="Department of Cheese")  # a department nobody enumerated

    found = {(s["kind"], s["name"]): s for s in status_events.sources(conn)}
    assert ("engine", "metadata_engine") in found
    assert ("department", "Department of Cheese") in found
    assert found[("engine", "metadata_engine")]["events"] == 2
    assert found[("engine", "metadata_engine")]["attention"] == 1


# --- §4.5 queryability ------------------------------------------------------------


def test_failures_answers_what_failed(conn):
    """"What failed during startup?" as a query rather than a scroll. A
    WARNING is worth seeing but is not a failure."""
    _publish(conn, severity=SEVERITY_WARNING, message="pool getting low")
    _publish(conn, severity=SEVERITY_ERROR, status=STATUS_FAILED, message="Metadata Engine failed")
    _publish(conn, severity=SEVERITY_CRITICAL, status=STATUS_FAILED, message="disk gone")

    assert {e["message"] for e in status_events.failures(conn)} == {
        "Metadata Engine failed", "disk gone",
    }


def test_current_status_answers_where_everything_stands(conn):
    """A feed answers "what happened"; this answers "where does everything
    stand" - which is what §4.5's "which departments are idle?" and "what is
    waiting for work?" actually ask."""
    _publish(conn, engine="metadata_engine", status=STATUS_READY, message="ready")
    _publish(conn, engine="metadata_engine", status=STATUS_IDLE, message="idle")
    _publish(conn, engine="simulation_engine", status=STATUS_WAITING,
             message="waiting for reference data")

    standing = {e["source_engine"]: e for e in status_events.current_status(conn)}
    assert standing["metadata_engine"]["status"] == STATUS_IDLE     # latest, not first
    assert standing["simulation_engine"]["status"] == STATUS_WAITING
    assert len(standing) == 2


def test_correlation_id_traces_one_pass(conn):
    _publish(conn, correlation_id="run-1", message="a")
    _publish(conn, correlation_id="run-1", message="b")
    _publish(conn, correlation_id="run-2", message="c")
    assert len(status_events.recent(conn, correlation_id="run-1")) == 2


# --- §4.6/§13 durable, bounded ----------------------------------------------------


def test_history_survives_a_new_connection(tmp_path):
    """§4.6's restart continuity: the point of durability is that the events
    from before the shutdown are still there after it."""
    path = tmp_path / "fi.db"
    first = fi_db.get_connection(str(path))
    fi_db.init_schema(first)
    status_events.publish(first, "shutdown", "SYSTEM_STOPPING", engine="coo")
    first.close()

    second = fi_db.get_connection(str(path))
    events = status_events.recent(second)
    second.close()
    assert [e["message"] for e in events] == ["SYSTEM_STOPPING"]


def test_prune_bounds_the_stream_oldest_first(conn):
    """§13: useful observability, not log flooding. The store is bounded."""
    for i in range(10):
        _publish(conn, message=f"event {i}")
    assert status_events.prune(conn, keep=4) == 6
    remaining = [e["message"] for e in status_events.recent(conn)]
    assert remaining == ["event 9", "event 8", "event 7", "event 6"]
    assert status_events.prune(conn, keep=4) == 0  # already at the limit
    with pytest.raises(ValueError, match="at least one"):
        status_events.prune(conn, keep=0)


def test_retention_limit_fails_loud_on_a_bad_value(monkeypatch):
    monkeypatch.delenv(status_events.RETENTION_ENV, raising=False)
    assert status_events.retention_limit() == status_events.DEFAULT_RETENTION
    monkeypatch.setenv(status_events.RETENTION_ENV, "lots")
    with pytest.raises(ValueError, match="not an integer"):
        status_events.retention_limit()


# --- the first real publisher -----------------------------------------------------


def test_metadata_engine_narration_lands_in_the_stream(conn):
    """The engine built in §72 is this stream's first publisher: its whole
    startup narration is queryable afterwards, under one correlation id."""
    report = metadata_engine.run(conn)
    feed = status_events.recent(conn, limit=50)

    assert len(feed) == len(report["events"])
    assert {e["source_engine"] for e in feed} == {"metadata_engine"}
    assert len({e["correlation_id"] for e in feed}) == 1  # one startup, one trace
    messages = " | ".join(e["message"] for e in feed)
    assert "Metadata ready" in messages
    assert "Metadata Engine starting" in messages
    # And it is findable the way an operator would ask for it.
    standing = status_events.current_status(conn)
    assert standing[0]["status"] == STATUS_IDLE


def test_a_failed_metadata_pass_is_visible_in_the_stream(conn, tmp_path, monkeypatch):
    """§12: a failed component must not silently disappear. The failure is
    queryable by exactly the question an operator asks."""
    monkeypatch.setenv("BOOT_CONFIG_PATH", str(tmp_path / "absent.json"))
    report = metadata_engine.run(conn)
    assert report["ready"] is False

    failures = status_events.failures(conn)
    assert failures and "Boot configuration could not be loaded" in failures[0]["message"]
    assert failures[0]["status"] == STATUS_FAILED
