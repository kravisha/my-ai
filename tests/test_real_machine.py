"""The tests that cannot pass here, and are meant to be run on the target PC.

Krish, 2026-09-23, on a plane: *"We can also write new tests tomorrow that may
not work today here."* This is that, written today so tomorrow is a pass/fail
list rather than an afternoon of poking at things.

    pytest -m real_machine -q

Everything in this file needs the real machine: Windows, the services running,
real installed programs, a real screen. None of it can pass in CI or in the
development container and **none of it is meant to** - the marker keeps them out
of the default run for the same reason `real_llm` and `simulation` are kept out.

## Two rules these are written to

**Every failure says what it means and what to do.** Whoever runs these is
alone with the output. `assert x` tells him nothing; `assert x, "the DBA is not
running - start it with ..."` tells him the next move.

**No test may pass vacuously.** These cannot be probed by mutating the code the
way the rest of the suite is, because the thing they exercise is a machine that
is not here. So each one is written to fail when the feature is absent *and*
when the feature is merely untouched - a log file that exists but is empty is a
failure, because an empty log is exactly what the broken case produces.

## What is deliberately not here

Anything needing eyes. "Does the window cover the screen", "did the menu
appear", "did the microphone hear me" are real questions that a test asserting
them would be lying about. They live in `python -m desktop.verify`, which shows
the thing and asks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_machine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS = PROJECT_ROOT / "logs"

GATEWAY = os.environ.get("JARVIS_GATEWAY_URL", "http://127.0.0.1:8100")
DBA = os.environ.get("JARVIS_DBA_URL", "http://127.0.0.1:8200")


def _get(url: str, path: str, **kwargs):
    import requests

    return requests.get(f"{url.rstrip('/')}{path}", timeout=10, **kwargs)


def _jsonl(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


# =============================================================================
# The machine itself
# =============================================================================


def test_this_is_actually_windows():
    assert sys.platform == "win32", (
        f"this ran on {sys.platform}, not Windows. These tests assert things "
        f"about the target PC; running them anywhere else proves nothing and "
        f"the passes would be meaningless.")


def test_pywebview_is_installed():
    """The shell cannot open a window without it, and `shell.available()`
    degrades to printing a URL - which is correct behaviour and not a shell."""
    try:
        import webview  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"pywebview is not importable ({exc}). The shell will fall back to "
            f"printing a URL instead of opening a window. Install it with:\n"
            f"    pip install -r requirements-desktop.txt")


def test_a_desktop_is_running():
    """Explorer. If the kiosk has killed it, Escape's "exit to the desktop"
    exits to nothing - which is the failure the escape hatch exists to prevent."""
    try:
        listed = subprocess.run(["tasklist", "/FI", "IMAGENAME eq explorer.exe"],
                                capture_output=True, text=True, timeout=20,
                                check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.fail(f"could not run tasklist ({exc}) - this is not a Windows "
                    f"machine, so nothing here proves anything about the target")
    assert "explorer.exe" in (listed.stdout or "").lower(), (
        "Explorer is not running. Exiting the shell would leave no desktop. "
        "Start it with: explorer.exe")


# =============================================================================
# The services
# =============================================================================


def test_the_gateway_is_up():
    try:
        response = _get(GATEWAY, "/health")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"the Gateway at {GATEWAY} did not answer ({exc}). Start it with "
            f"`python -m gateway.run`, or run scripts/keep-jarvis-up.ps1 which "
            f"starts everything. If it is supposed to be running, the cause is "
            f"in logs/gateway.err.log.")
    assert response.status_code == 200, (
        f"the Gateway answered {response.status_code}. See logs/gateway.err.log.")


def test_the_dba_is_up_and_the_gateway_can_reach_it():
    """§3 step 3. A Gateway that came up before the DBA reports DBA_UNAVAILABLE
    and operates with no memory - honest, and useless when the memory was there."""
    try:
        response = _get(DBA, "/health")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"the DBA at {DBA} did not answer ({exc}). The supervisor starts it "
            f"before the Gateway; if it is not up, Jarvis has no memory. The "
            f"cause is in logs/dba.err.log.")
    assert response.status_code == 200, f"the DBA answered {response.status_code}"


def test_the_tokens_the_system_needs_are_configured():
    """Each one disables something specific, and each failure names what."""
    missing = []
    if not (os.environ.get("DBA_TOKEN_JARVIS") or "").strip():
        missing.append("DBA_TOKEN_JARVIS - without it Jarvis has no memory at "
                       "all: no ledger, no checkpoints, no restore")
    if not (os.environ.get("DBA_TOKEN_OPERATOR_CONSOLE") or "").strip():
        missing.append("DBA_TOKEN_OPERATOR_CONSOLE - without it the build "
                       "controller refuses every deploy, so self-modification "
                       "cannot complete")
    assert not missing, "missing configuration:\n  - " + "\n  - ".join(missing)


def test_the_shell_can_save_work_when_it_closes():
    """The open question from the design: the closing sequence sits behind
    session auth, so without a credential the shell exits reporting "not
    everything was saved". Honest, and not what anybody wants."""
    from desktop import shell

    token = (os.environ.get(shell.SHELL_TOKEN_ENV) or "").strip()
    assert token, (
        f"{shell.SHELL_TOKEN_ENV} is not set. Pressing Escape and exiting will "
        f"still close the window, but it will report that the last few minutes "
        f"were not saved - because it could not authenticate to ask the Gateway "
        f"to checkpoint. Set it to a Gateway session token.")


# =============================================================================
# The logs he asked for
# =============================================================================


def test_the_event_log_is_being_written():
    """Not "the file exists" - an empty file is what the broken case produces."""
    from app import eventlog

    path = eventlog.log_path()
    rows = _jsonl(path)
    assert rows, (
        f"{path} has no entries. Either the services have not run since the "
        f"event log was added, or `eventlog.install` is not being reached. "
        f"Restart the Gateway and look again.")
    assert any(row.get("service") for row in rows), (
        "entries exist but none names a service, so the handler is writing a "
        "different shape than the scanner reads")


def test_both_services_have_left_a_startup_breadcrumb():
    """Without these an empty log cannot be told from a service nobody started,
    and on a remote machine those have different causes and different fixes."""
    from app import crashlog

    rows = _jsonl(crashlog.breadcrumb_path())
    services = {row.get("service") for row in rows}
    assert "gateway" in services, (
        f"no gateway startup was recorded in {crashlog.breadcrumb_path()}. The "
        f"Gateway has either never started since this was added, or it is "
        f"dying before `crashlog.breadcrumb` runs - which would itself be the "
        f"finding.")
    assert "dba" in services, "no DBA startup was recorded"


def test_the_supervisor_is_capturing_what_its_children_say():
    """The fix that made everything else possible. If these files do not exist,
    a traceback is still going to a destroyed stderr and a failure tomorrow will
    be undiagnosable."""
    expected = [LOGS / "gateway.err.log", LOGS / "gateway.out.log"]
    missing = [path for path in expected if not path.exists()]
    assert not missing, (
        "the supervisor is not redirecting its children's output: "
        + ", ".join(str(path) for path in missing)
        + ".\nEither keep-jarvis-up.ps1 has not run since the redirect was "
          "added, or the Gateway was started by hand. Start it through the "
          "supervisor.")


def test_a_crash_in_a_child_actually_reaches_a_file(tmp_path):
    """TQ-122's real question, exercised rather than assumed: break something on
    purpose and see whether the log tells you what happened.

    Runs the same Start-Process redirection the supervisor uses, against a child
    that raises a recognisable exception, and asserts the traceback arrives."""
    out = tmp_path / "child.out.log"
    err = tmp_path / "child.err.log"
    marker = "JarvisDeliberateCrashForVerification"
    child = f"raise RuntimeError('{marker}')"

    command = (
        f"Start-Process -FilePath '{sys.executable}' "
        f"-ArgumentList '-c','{child}' -WindowStyle Hidden -Wait "
        f"-RedirectStandardOutput '{out}' -RedirectStandardError '{err}'")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", command],
                       capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.fail(f"could not run PowerShell ({exc}) - this is not a Windows "
                    f"machine, so the supervisor's redirection is untested here")

    assert err.exists(), (
        "the redirected stderr file was not created at all, so the technique "
        "the supervisor relies on does not work on this machine")
    text = err.read_text(encoding="utf-8", errors="replace")
    assert marker in text, (
        f"a child raised {marker} and the traceback did not reach the log. "
        f"What arrived was: {text[:400]!r}. Every diagnosis of a failure on "
        f"this PC depends on this working.")
    assert "Traceback" in text, "the exception arrived without its traceback"


def test_the_crash_directory_is_writable():
    """Named for what it proves. It CREATES the directory, so "exists" is free
    and asserting it would be theatre. What it actually establishes is that a
    crash would have somewhere to go - which a full or read-only disk would
    deny, and which is worth knowing before a crash rather than after."""
    from app import crashlog

    directory = crashlog.crash_dir()
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ".writable"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError as exc:
        pytest.fail(f"{directory} is not writable ({exc}), so a crash would be "
                    f"recorded nowhere")
    finally:
        probe.unlink(missing_ok=True)


# =============================================================================
# Memory, end to end, against the real store
# =============================================================================


def test_jarvis_has_actually_been_remembering_things():
    """Not that the machinery exists - that it has run. An empty ledger on a
    machine that has been used means the producers are not wired up."""
    from gateway import dbaclient, ledger

    if not dbaclient.is_configured():
        pytest.fail("DBA_TOKEN_JARVIS is not set, so nothing has been remembered")
    client = dbaclient.DBAClient(actor="verification")
    length = ledger.length(client)
    assert length > 0, (
        "the life ledger is empty. Either Jarvis has not run since the "
        "producers were added, or every write is failing - check "
        "logs/events.jsonl for LEDGER_WRITE_FAILED.")


def test_the_ledger_has_not_been_tampered_with():
    """The hash chain, verified against the real store rather than a fixture."""
    from gateway import dbaclient, ledger

    if not dbaclient.is_configured():
        pytest.skip("no DBA token configured; covered by the test above")
    verdict = ledger.replay(dbaclient.DBAClient(actor="verification"))
    assert verdict["intact"], (
        f"the life ledger does not verify. First break: {verdict['breaks'][:1]}. "
        f"Events after it cannot be trusted as a record of what happened.")


def test_there_is_a_checkpoint_to_go_back_to():
    """§9's whole point. A system whose only known-good point is the one before
    a code change has no known-good point on the ordinary days."""
    from gateway import checkpoint as checkpoint_module
    from gateway import dbaclient

    if not dbaclient.is_configured():
        pytest.skip("no DBA token configured; covered above")
    latest = checkpoint_module.latest_valid(dbaclient.DBAClient(actor="verification"))
    assert latest is not None, (
        "there is no valid checkpoint. Nothing can be restored to a known-good "
        "point. The upkeep loop takes one every six hours - if it has been "
        "longer than that, the loop is not running.")


def test_a_restart_would_restore_what_jarvis_knows():
    """Rehydration against the real store. This is the one that answers "would
    he come back as himself?" without restarting anything."""
    from gateway import dbaclient, rehydrate

    if not dbaclient.is_configured():
        pytest.skip("no DBA token configured; covered above")
    restoration = rehydrate.bootstrap(verify_ledger=True)
    assert restoration.status != "RESTORE_FAILED", (
        f"a restart would restore nothing: {restoration.unavailable}")
    assert restoration.items, (
        "a restart would restore no state at all. The machinery works and "
        "nothing has been written to it - check that the memory tools are "
        "being used.")
    for line in restoration.sentences():
        print(f"  [restore] {line}")


# =============================================================================
# The log he wants to be beautiful
# =============================================================================


def test_the_log_has_no_unexplained_noise_in_it():
    """Krish, 2026-09-23: *"His beauty lies in the beauty of these log files
    with no error messages or unnecessary warnings."*

    Not a style check - a scan of what the machine has actually been saying.
    Anything recurring and not written down in config/log_noise_baseline.yaml
    is either a defect to fix or an entry to add, and this is the moment to
    decide which."""
    from gateway import logscan

    from app import eventlog

    # A scan of nothing returns nothing, and "no faults" and "no log" are
    # indistinguishable in the result. On a container with no log at all this
    # test passed, reporting a beautiful log where there was none - which is
    # the exact shape of failure the whole logging effort exists to prevent.
    recent = eventlog.records(
        since=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc)
        - __import__("datetime").timedelta(hours=logscan.DEFAULT_WINDOW_HOURS))
    assert recent, (
        f"there is nothing in the log to scan ({eventlog.log_path()}). That is "
        f"not a clean log, it is an absent one - and it means every other claim "
        f"about diagnosing this machine is untested. Run the services, use "
        f"Jarvis for a minute, and try again.")

    findings = logscan.scan()
    noise = logscan.unaccepted(findings)
    if noise:
        report = "\n".join(
            f"  {item.level:<8} x{item.count:<4} {item.module}:{item.line}  "
            f"{item.example[:110]}" for item in noise)
        pytest.fail(
            f"{len(noise)} unexplained fault(s) in the log:\n{report}\n\n"
            f"Each one is either a defect to fix or an entry to add to "
            f"config/log_noise_baseline.yaml with a reason. Signatures: "
            f"{[item.signature for item in noise]}")
