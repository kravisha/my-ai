"""The log Jarvis reads to understand himself, and the rotation under it.

Krish, 2026-09-23: *"His beauty lies in the beauty of these log files with no
error messages or unnecessary warnings."* Before this there was no such file -
nothing in the codebase configured a logging handler, so every warning went to
stderr and died with the process.

Two things are being tested. `app/jsonlog.py` is the rotation extracted from
`app/model_calls.py` so there would not be two copies of it; the tests here are
the ones that copy never had, because it was only ever exercised through the
call log. `app/eventlog.py` is the handler.

Written to Krish's rule of the same day: *"tests working fine initially is not
good testing at all"*. Every assertion below was run against code with the
behaviour removed before being kept.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import eventlog, jsonlog, model_calls


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(eventlog.ENABLED_ENV, "1")
    monkeypatch.delenv(eventlog.LEVEL_ENV, raising=False)
    eventlog.reset_for_test()
    yield tmp_path
    eventlog.reset_for_test()


def _entry(when: str, **extra):
    return {"at": when, "level": "INFO", "message": "x", **extra}


# =============================================================================
# app/jsonlog.py - the rotation, finally tested directly
# =============================================================================


def test_a_write_on_a_new_day_rotates_yesterday_into_its_own_file(tmp_path):
    path = tmp_path / "events.jsonl"
    jsonlog.append(path, _entry("2026-09-21T10:00:00+00:00"), retention_days=30)

    # Age the live file so its mtime says yesterday, which is what rotation
    # reads - not the content, which may be a day the writer got wrong.
    yesterday = datetime(2026, 9, 21, tzinfo=timezone.utc).timestamp()
    import os
    os.utime(path, (yesterday, yesterday))

    jsonlog.append(path, _entry("2026-09-22T10:00:00+00:00"), retention_days=30)

    assert (tmp_path / "events-2026-09-21.jsonl").exists()
    assert path.exists()
    assert len(path.read_text().strip().splitlines()) == 1


def test_a_rotation_target_that_already_exists_is_not_overwritten(tmp_path):
    """Two processes on the same second: the loser finds the target already
    there and keeps appending. Losing a line to win tidiness is the wrong trade
    for a log whose whole purpose is to be complete.

    Named for what it actually guarantees. It was called
    `..._keeps_appending_rather_than_losing_the_line`, and probing showed it
    also passed with rotation removed altogether - it could not tell "declined
    to overwrite" from "never tried". What it does catch, and what the probe
    confirmed, is the rename clobbering the other process's file. The absence
    of rotation is caught by the test above."""
    path = tmp_path / "events.jsonl"
    jsonlog.append(path, _entry("2026-09-21T10:00:00+00:00"), retention_days=30)
    import os
    yesterday = datetime(2026, 9, 21, tzinfo=timezone.utc).timestamp()
    os.utime(path, (yesterday, yesterday))

    # The winner already renamed into place.
    (tmp_path / "events-2026-09-21.jsonl").write_text("winner\n", encoding="utf-8")

    assert jsonlog.append(path, _entry("2026-09-22T10:00:00+00:00"),
                          retention_days=30) is True
    assert "winner" in (tmp_path / "events-2026-09-21.jsonl").read_text()
    # and the line that would have been lost is in the live file
    assert len(path.read_text().strip().splitlines()) == 2


def test_rotated_files_older_than_the_retention_are_removed(tmp_path):
    path = tmp_path / "events.jsonl"
    for day in ("2026-08-01", "2026-09-20"):
        (tmp_path / f"events-{day}.jsonl").write_text("{}\n", encoding="utf-8")

    jsonlog.prune(tmp_path, "events", ".jsonl", "2026-09-22", retention_days=30)

    assert not (tmp_path / "events-2026-08-01.jsonl").exists()
    assert (tmp_path / "events-2026-09-20.jsonl").exists()


def test_a_file_whose_name_is_not_a_date_is_left_alone(tmp_path):
    """A prune that guessed would delete somebody else's file."""
    (tmp_path / "events-backup.jsonl").write_text("{}\n", encoding="utf-8")
    jsonlog.prune(tmp_path, "events", ".jsonl", "2026-09-22", retention_days=1)
    assert (tmp_path / "events-backup.jsonl").exists()


def test_reading_skips_a_corrupt_line_rather_than_stopping_at_it(tmp_path):
    """A scanner that fell over on one bad line would stop working on exactly
    the day something went wrong, which is the day it is for."""
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(_entry("2026-09-22T10:00:00+00:00", message="first")) + "\n"
        + "{not json at all\n"
        + "\n"
        + "[1, 2, 3]\n"
        + json.dumps(_entry("2026-09-22T11:00:00+00:00", message="second")) + "\n",
        encoding="utf-8")

    found = [row["message"] for row in jsonlog.read(path)]
    assert found == ["first", "second"]


def test_reading_walks_the_rotated_files_oldest_first(tmp_path):
    path = tmp_path / "events.jsonl"
    (tmp_path / "events-2026-09-20.jsonl").write_text(
        json.dumps(_entry("2026-09-20T10:00:00+00:00", message="older")) + "\n")
    (tmp_path / "events-2026-09-21.jsonl").write_text(
        json.dumps(_entry("2026-09-21T10:00:00+00:00", message="middle")) + "\n")
    path.write_text(
        json.dumps(_entry("2026-09-22T10:00:00+00:00", message="live")) + "\n")

    assert [row["message"] for row in jsonlog.read(path)] == [
        "older", "middle", "live"]


def test_a_window_excludes_what_falls_outside_it(tmp_path):
    path = tmp_path / "events.jsonl"
    for hour, name in ((9, "before"), (11, "inside"), (13, "after")):
        jsonlog.append(path, _entry(f"2026-09-22T{hour:02d}:00:00+00:00",
                                    message=name), retention_days=30)

    since = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)
    until = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    assert [row["message"] for row in jsonlog.read(path, since=since, until=until)] == [
        "inside"]


def test_a_read_is_bounded(tmp_path):
    path = tmp_path / "events.jsonl"
    for index in range(20):
        jsonlog.append(path, _entry("2026-09-22T10:00:00+00:00", message=str(index)),
                       retention_days=30)
    assert len(list(jsonlog.read(path, limit=5))) == 5


def test_an_unwritable_path_is_reported_and_not_raised(tmp_path):
    """Telemetry wrapped around what the user is waiting for: a full disk must
    not become a failed answer."""
    blocked = tmp_path / "a-file" / "events.jsonl"
    (tmp_path / "a-file").write_text("not a directory", encoding="utf-8")
    assert jsonlog.append(blocked, _entry("2026-09-22T10:00:00+00:00"),
                          retention_days=30) is False


# =============================================================================
# app/eventlog.py - the handler
# =============================================================================


def test_installing_makes_an_ordinary_warning_durable(tmp_path):
    """The whole point: nineteen existing call sites become scannable without
    one of them being edited."""
    eventlog.install("gateway")
    logging.getLogger("gateway.something").warning("the tunnel restarted")

    found = eventlog.records()
    assert len(found) == 1
    assert found[0]["level"] == "WARNING"
    assert found[0]["logger"] == "gateway.something"
    assert found[0]["service"] == "gateway"
    assert found[0]["message"] == "the tunnel restarted"
    assert found[0]["function"] and found[0]["line"]


def test_an_exception_keeps_its_type_and_message(tmp_path):
    eventlog.install("gateway")
    try:
        raise ValueError("no such capability")
    except ValueError:
        logging.getLogger("x").exception("a tool failed")

    found = eventlog.records()[0]
    assert found["exception"] == "ValueError"
    assert "no such capability" in found["exception_message"]


@pytest.mark.parametrize("message, must_not_contain", [
    ("Authorization: Bearer abc123def456ghi", "abc123def456ghi"),
    ("connecting with token=sk-9f8e7d6c5b4a", "sk-9f8e7d6c5b4a"),
    ("api_key: hunter2hunter2", "hunter2hunter2"),
    ("digest a3f9" + "0" * 40, "a3f9" + "0" * 40),
])
def test_a_secret_shaped_value_does_not_reach_the_file(message, must_not_contain):
    """A log Jarvis scans is a log the model reads. The cost of being wrong
    once is a credential in a file a model reads."""
    eventlog.install("gateway")
    logging.getLogger("x").warning("%s", message)

    written = eventlog.log_path().read_text(encoding="utf-8")
    assert must_not_contain not in written
    assert "redacted" in written


def test_an_ordinary_message_is_not_mangled_by_the_redactor():
    """A redactor that mangles ordinary messages makes the log harder to read,
    and a log nobody can read is what this module exists to prevent."""
    for ordinary in ("could not reach the DBA at 127.0.0.1:8200",
                     "purged 3 expired session(s)",
                     "checkpoint_000012 validated in 41ms"):
        assert eventlog.redact(ordinary) == ordinary


def test_a_very_long_message_is_capped():
    eventlog.install("gateway")
    logging.getLogger("x").warning("%s", "y" * (eventlog.MAX_MESSAGE * 3))
    assert len(eventlog.records()[0]["message"]) == eventlog.MAX_MESSAGE


def test_installing_twice_does_not_write_every_line_twice():
    assert eventlog.install("gateway") is True
    assert eventlog.install("gateway") is False
    logging.getLogger("x").warning("once")
    assert len(eventlog.records()) == 1


def test_a_root_logger_left_at_warning_would_have_dropped_every_info():
    """The bug this guards was found by writing the test: the handler's level
    is not the gate - the root logger's is, and a root at WARNING discards
    every INFO before any handler sees it."""
    logging.getLogger().setLevel(logging.CRITICAL)
    eventlog.install("gateway", force=True)
    logging.getLogger("x").info("routine")
    assert [row["message"] for row in eventlog.records()] == ["routine"]


def test_the_level_is_configurable(monkeypatch):
    monkeypatch.setenv(eventlog.LEVEL_ENV, "ERROR")
    eventlog.install("gateway", force=True)
    logging.getLogger("x").warning("not this one")
    logging.getLogger("x").error("this one")
    assert [row["message"] for row in eventlog.records()] == ["this one"]


def test_it_can_be_switched_off(monkeypatch):
    monkeypatch.setenv(eventlog.ENABLED_ENV, "0")
    assert eventlog.install("gateway", force=True) is False
    logging.getLogger("x").warning("nothing should be written")
    assert eventlog.records() == []


def test_a_failed_write_is_counted_so_a_silent_log_is_visible(monkeypatch):
    """The one failure a logging system cannot afford to hide."""
    eventlog.install("gateway")
    monkeypatch.setattr(jsonlog, "append", lambda *a, **k: False)
    logging.getLogger("x").warning("this will not land")

    assert eventlog.state()["failed"] == 1
    assert eventlog.state()["written"] == 0


def test_a_handler_that_cannot_format_a_record_does_not_raise(monkeypatch):
    eventlog.install("gateway")
    monkeypatch.setattr(eventlog, "build",
                        lambda record, service: (_ for _ in ()).throw(RuntimeError("boom")))
    logging.getLogger("x").warning("anything")   # must not raise
    assert eventlog.state()["failed"] == 1


def test_a_line_carries_the_request_it_happened_in():
    """So a fault found here can be followed into the model calls around it,
    without either side having been designed for the other."""
    eventlog.install("gateway")
    with model_calls.request_context("reconcile september"):
        logging.getLogger("x").warning("something went wrong mid-turn")
        expected = model_calls.current_request_id()

    assert eventlog.records()[0]["request_id"] == expected
    assert expected is not None


def test_the_event_log_lands_beside_the_call_log(tmp_path):
    """Redirected by the same environment variable, so a test that redirects
    one redirects both and neither can write into the checkout."""
    assert eventlog.log_path().parent == model_calls.log_dir()
    assert eventlog.log_path().parent == tmp_path


# =============================================================================
# The machinery has a user
# =============================================================================


def test_the_gateway_installs_it_on_startup(monkeypatch, tmp_path):
    """Everything above is dormant unless a running service installs it. This
    is the whole difference between a logging system and a logging module."""
    from fastapi.testclient import TestClient

    from gateway import main as gateway_main

    monkeypatch.setenv("GATEWAY_DB_PATH", str(tmp_path / "gateway.db"))
    eventlog.reset_for_test()
    with TestClient(gateway_main.app):
        assert eventlog.state()["installed"] is True
        assert eventlog.state()["service"] == "gateway"
        logging.getLogger("gateway.x").warning("during a request")

    assert any(row["message"] == "during a request" for row in eventlog.records())


def test_the_dba_installs_it_too_and_says_which_service_it_is(monkeypatch, tmp_path):
    """One file for the whole system: a fault usually spans both processes, and
    two files would make "what happened at 02:14" a question needing a join."""
    from fastapi.testclient import TestClient

    from dba import main as dba_main

    monkeypatch.setenv("DBA_DB_PATH", str(tmp_path / "dba.db"))
    eventlog.reset_for_test()
    with TestClient(dba_main.app):
        assert eventlog.state()["service"] == "dba"
        logging.getLogger("dba.x").warning("from the other service")

    written = [row for row in eventlog.records()
               if row["message"] == "from the other service"]
    assert written and written[0]["service"] == "dba"
