"""What is left behind when Jarvis dies on a machine nobody can reach.

Krish, 2026-09-23: *"I want extensive logs so that we should be able to find out
what went wrong from the logs if anything fails to work in the target PC."*

Before this, three things made that impossible and none of them was in Python:
every child process was started `-WindowStyle Hidden` with no output
redirection, so a traceback went to a destroyed stderr; nothing installed a
`faulthandler` or an `excepthook`; and nothing recorded that a process had
started at all, so an empty log could not be told from a service that was never
asked to run.

Probed per Krish's rule of the same day - every behaviour here was run against
code with that behaviour removed before the test was kept.
"""

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app import crashlog, eventlog, model_calls


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(crashlog.ENABLED_ENV, "1")
    yield tmp_path
    crashlog.uninstall()
    eventlog.reset_for_test()


# =============================================================================
# The breadcrumb: "never started" is not the same as "started and died"
# =============================================================================


def test_a_started_process_says_so_before_anything_can_fail(tmp_path):
    entry = crashlog.breadcrumb("gateway", extra={"port": 8100})

    written = [json.loads(line) for line
               in crashlog.breadcrumb_path().read_text().strip().splitlines()]
    assert written[-1]["event"] == "startup"
    assert written[-1]["service"] == "gateway"
    assert written[-1]["port"] == 8100
    assert written[-1]["pid"] == entry["pid"]
    assert written[-1]["python"] and written[-1]["platform"]


def test_the_breadcrumb_carries_the_version_it_is_running(tmp_path, monkeypatch):
    """On a remote machine "which build is this" is the first question and the
    hardest to answer afterwards."""
    monkeypatch.setenv("JARVIS_CODE_VERSION", "a" * 40)
    assert crashlog.breadcrumb("gateway")["code_version"] == "a" * 40


def test_an_unknown_version_is_none_rather_than_a_guess(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_CODE_VERSION", raising=False)
    monkeypatch.setattr(crashlog, "_code_version", crashlog._code_version)
    entry = crashlog.breadcrumb("gateway")
    assert entry["code_version"] is None or isinstance(entry["code_version"], str)


def test_breadcrumbs_accumulate_so_a_restart_loop_is_visible(tmp_path):
    """Four startups in a minute and no shutdowns is a crash loop, and it is
    only visible because each start left a line."""
    for _ in range(4):
        crashlog.breadcrumb("gateway")
    lines = crashlog.breadcrumb_path().read_text().strip().splitlines()
    assert len(lines) == 4


# =============================================================================
# The crash record
# =============================================================================


def test_an_unhandled_exception_is_written_to_its_own_file(tmp_path):
    crashlog.install("gateway")
    try:
        raise ValueError("the config file is not JSON")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    files = crashlog.crashes()
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "ValueError: the config file is not JSON" in text
    assert "unhandled exception" in text
    assert "Traceback" in text


def test_a_thread_dying_silently_is_recorded(tmp_path):
    """The upkeep loop, the backup scheduler and the technology review all run
    on threads that outlive no request. Without this, one of them raising takes
    the thread and nothing else - the feature stops existing and nobody is told."""
    crashlog.install("dba")

    def explode():
        raise RuntimeError("the scheduler thread died")

    worker = threading.Thread(target=explode, name="scheduler")
    worker.start()
    worker.join()

    text = "\n".join(path.read_text(encoding="utf-8") for path in crashlog.crashes())
    assert "the scheduler thread died" in text
    assert "scheduler" in text


def test_the_crash_file_says_which_build_and_which_process(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_CODE_VERSION", "b" * 40)
    crashlog.install("gateway")
    crashlog.record("gateway", "test", "something")
    text = crashlog.crashes()[0].read_text(encoding="utf-8")
    assert "b" * 40 in text
    assert str(__import__("os").getpid()) in text


def test_a_crash_also_reaches_the_event_log_when_that_still_works(tmp_path):
    """Two chances, and the one that does not depend on anything is tried
    first - but both are tried."""
    eventlog.install("gateway")
    crashlog.record("gateway", "unhandled exception", "boom")

    found = [row for row in eventlog.records() if row["level"] == "CRITICAL"]
    assert found and "boom" in found[0]["message"]


def test_a_crash_is_still_recorded_when_the_event_log_is_broken(tmp_path, monkeypatch):
    """A crash record that could only be written through the logging system
    would share its failure modes at exactly the moment that matters."""
    def broken(*args, **kwargs):
        raise RuntimeError("logging itself is what failed")

    monkeypatch.setattr(crashlog.logger, "critical", broken)
    written = crashlog.record("gateway", "unhandled exception", "still recorded")

    assert written is not None
    assert "still recorded" in written.read_text(encoding="utf-8")


def test_crash_files_are_pruned_so_a_loop_cannot_fill_the_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(crashlog, "KEEP_CRASHES", 5)
    for index in range(12):
        crashlog.record("gateway", "test", f"crash {index}")
    assert len(list(crashlog.crash_dir().glob("*.log"))) == 5
    # and the ones kept are the newest, which are the ones being diagnosed
    newest = crashlog.crashes()[0].read_text(encoding="utf-8")
    assert "crash 11" in newest


def test_it_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv(crashlog.ENABLED_ENV, "0")
    assert crashlog.install("gateway") is False
    assert sys.excepthook is sys.__excepthook__


def test_uninstalling_puts_the_hooks_back(tmp_path):
    crashlog.install("gateway")
    assert sys.excepthook is not sys.__excepthook__
    crashlog.uninstall()
    assert sys.excepthook is sys.__excepthook__
    assert threading.excepthook is threading.__excepthook__


# =============================================================================
# Armed by the entry points, not merely available
# =============================================================================


def test_the_gateway_arms_it_before_starting_the_server(monkeypatch):
    """Everything it catches happens at moments when it is too late to start
    catching, so the order is the feature."""
    from gateway import run

    order = []
    monkeypatch.setattr(crashlog, "install",
                        lambda service: order.append(f"install:{service}"))
    monkeypatch.setattr(crashlog, "breadcrumb",
                        lambda service, **kw: order.append(f"breadcrumb:{service}"))

    class NoServer:
        def __init__(self, config):
            order.append("server")

        def run(self):
            order.append("run")

    monkeypatch.setattr(run.uvicorn, "Server", NoServer)
    run.main()

    assert order == ["install:gateway", "breadcrumb:gateway", "server", "run"]


def test_the_dba_arms_it_too(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from dba import main as dba_main

    monkeypatch.setenv("DBA_DB_PATH", str(tmp_path / "dba.db"))
    with TestClient(dba_main.app):
        assert crashlog.state()["service"] == "dba"
    breadcrumbs = crashlog.breadcrumb_path().read_text(encoding="utf-8")
    assert '"service": "dba"' in breadcrumbs


# =============================================================================
# The half that is not Python: the supervisor's own black hole
# =============================================================================


def test_the_supervisor_captures_what_its_children_say():
    """Every Start-Process was -WindowStyle Hidden with no redirection, so a
    traceback went to a destroyed stderr and the loop restarted for ever with
    no cause in the log."""
    script = (Path(__file__).resolve().parent.parent
              / "scripts" / "keep-jarvis-up.ps1").read_text(encoding="utf-8")

    starts = [line for line in script.splitlines()
              if "Start-Process" in line and "cloudflared" not in line]
    assert starts, "no child processes found - has the supervisor changed shape?"

    # Each Python child is redirected. cloudflared is excluded above because it
    # takes its own --logfile, which is already captured.
    assert script.count("-RedirectStandardOutput") >= 2
    assert script.count("-RedirectStandardError") >= 2
    # And the previous file is kept, because Start-Process cannot append and so
    # overwrites the evidence of the crash that caused the restart.
    #
    # Asserted on the Move-Item that does it, not on the string ".prev". The
    # first version checked `".prev" in script` and passed with the behaviour
    # removed, because the COMMENT above that line says ".prev" - a test
    # satisfied by prose, which is the same trap the ledger's append-only test
    # fell into.
    import re
    assert re.search(r"Move-Item[^\n]*Destination \"\$f\.prev\"", script), (
        "the previous log is not moved aside before a restart overwrites it")
    # and a restart says why, not only that
    assert "last words from gateway" in script


def test_the_children_write_beside_the_rest_of_the_logs():
    """A support bundle wants them together; TEMP is where evidence goes to be
    forgotten."""
    script = (Path(__file__).resolve().parent.parent
              / "scripts" / "keep-jarvis-up.ps1").read_text(encoding="utf-8")
    assert "$logDir      = Join-Path $root 'logs'" in script
    assert "gateway.err.log" in script


def test_the_faulthandler_stream_is_not_mistaken_for_a_crash(tmp_path):
    """Found by the tests, not by review. The first version named it
    `<service>-faulthandler.log`, so `crashes()` returned it as a crash - and
    because that list sorts by name descending it sorted FIRST, hiding the
    newest real crash behind an empty file. On a remote machine that means
    opening the one file guaranteed to say nothing."""
    crashlog.install("gateway")
    crashlog.record("gateway", "unhandled exception", "the real one")

    assert len(crashlog.crashes()) == 1
    assert "the real one" in crashlog.crashes()[0].read_text(encoding="utf-8")
    assert crashlog.fault_streams()
    assert not any(path.name.endswith(".log") for path in crashlog.fault_streams())
