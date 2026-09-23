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


# =============================================================================
# The half built on 2026-09-23, which has never started on this machine
# =============================================================================
#
# Seven subsystems were written and merged in one day against a Linux container.
# Two of them broke the first time Windows saw them, in ways no local run could
# show. Everything below asks the only question that settles it: is this thing
# actually working *here*.
#
# Each failure says what it means and what to do, because whoever runs these is
# alone with the output - possibly on a phone, possibly on holiday.


def _charter_key() -> bytes:
    """The key, or a sentence saying why not.

    Every test below needs it, and `FileNotFoundError` on a path is not a
    finding - it is a stack trace standing where an instruction should be."""
    from app import dpapi, keystore
    from desktop import machine

    where = keystore.key_path(machine.state_directory())
    if not where.exists():
        pytest.fail(f"no charter key at {where}. "
                    f"python -m desktop.bringup --make-key")
    try:
        return dpapi.unprotect(where.read_bytes())
    except Exception as refused:  # noqa: BLE001
        pytest.fail(f"the charter key is there and this Windows account "
                    f"cannot open it ({refused}). "
                    f"python -m desktop.bringup --restore-key")


def test_the_bring_up_report_is_not_red():
    """The whole of `desktop/readiness.py`, run for real. If this is red the
    rest of this section will be too, and this one says which thing to fix."""
    from desktop import machine, readiness

    report = readiness.look(machine.read())
    assert report.status != readiness.RED, (
        "bring-up reports RED:\n  "
        + "\n  ".join(readiness.summary(report)))


def test_the_charter_key_is_where_it_should_be_and_has_a_backup():
    """DPAPI ties the key to this Windows account. Without an escrow copy, a
    reinstall makes every amendment unreadable for ever, by anybody."""
    from app import keystore
    from desktop import machine

    said = machine.read_keystore()
    assert said.state != keystore.UNREADABLE, (
        f"{said.because}. {said.next_step}")
    assert said.state != keystore.ABSENT, (
        f"{said.because}. {said.next_step}")
    assert said.state == keystore.READY, (
        f"{said.because}. {said.next_step}")


def test_the_constitution_is_installed_and_opens_with_that_key():
    """A sealed constitution nobody can open is not a constitution, and the only
    way to know is to open it."""
    from gateway import constitution

    assert constitution.installed(), (
        "no sealed constitution on this machine, so nothing Jarvis does is "
        "governed by the document he was given. "
        "python -m desktop.bringup --install-constitution")
    key = _charter_key()
    text = constitution.read(key=key)
    assert text.strip(), "the constitution opened and was empty"


def test_no_amendment_has_been_altered_or_removed():
    """The one in this file that should never fail. If it does, keep everything
    and read the report before touching anything."""
    from gateway import constitution, dbaclient

    key = _charter_key()
    try:
        found = constitution.verify(dbaclient.DBAClient(), key=key)
    except Exception as unreachable:  # noqa: BLE001
        pytest.fail(f"could not check the amendments: {unreachable}")
    assert found.get("intact"), f"the amendment chain does not verify: {found}"


def test_the_trust_record_survives_a_restart():
    """`gateway/trustbook.py` keeps the ladder in the DBA precisely so that it
    is not lost with the conversation. Nothing proves that but reading it back
    from a process that did not write it."""
    from gateway import dbaclient, trustbook

    try:
        guesses, problems = trustbook.load(dbaclient.DBAClient())
    except Exception as unreachable:  # noqa: BLE001
        pytest.fail(f"could not read the trust record: {unreachable}")
    assert not problems, (
        "the trust record reports problems, which means a verdict names a "
        f"guess that is not there: {problems}")
    assert isinstance(guesses, list)


def test_krishs_console_can_authenticate_as_itself():
    """It refuses to run on Jarvis's token on purpose - a verdict written in the
    name of the agent being judged is not a verdict."""
    from gateway import console

    try:
        client = console.operator_client()
    except console.NoToken as refused:
        pytest.fail(f"{refused}")
    assert client.requested_by.lower() == "operator_console", (
        f"the console authenticated as {client.requested_by!r}, not as the "
        f"operator. Jarvis must not be able to settle his own guesses.")


def test_the_upkeep_loop_is_actually_sweeping():
    """The noticing and the memory collection both hang off it. A thread that
    died takes both with it and says nothing - which is the failure
    `app/crashlog.py` exists for, seen from the other side.

    Read from the DBA rather than from a file: the sweep records when it last
    ran through `persistence`, and the first version of this test asserted
    against a directory nothing has ever written to. That would have failed on
    Krish's machine for ever, about nothing."""
    from datetime import datetime, timezone

    from gateway import dbaclient, persistence, upkeep

    try:
        client = dbaclient.DBAClient()
        stamp = persistence.get(client, persistence.SELF_ASSESSMENT,
                                upkeep._LAST_NOTICING)
    except Exception as unreachable:  # noqa: BLE001
        pytest.fail(f"could not read the upkeep record: {unreachable}")

    assert stamp, (
        "the upkeep loop has never recorded a noticing sweep on this machine, "
        "so nothing is noticing anything. Either he has not been up for four "
        "hours yet, or the thread raised and died - check the log.")
    when = datetime.fromisoformat(str(stamp))
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600.0
    assert hours < 24.0, (
        f"the last noticing sweep was {hours:.0f} hours old, against a cadence "
        f"of {upkeep.NOTICE_EVERY_HOURS} hours. Check the log for a thread "
        f"that raised and died.")


def test_dates_render_on_this_machine():
    """`%-d` is a glibc extension and Windows raises on it. It took out every
    noticing there is, and it looked fine everywhere it was written."""
    from datetime import datetime, timezone

    from gateway import noticing

    said = noticing._day(datetime(2026, 10, 3, tzinfo=timezone.utc))
    assert said == "3 October", f"dates render as {said!r} on this machine"


def test_the_sealed_documents_read_back_as_utf8_here():
    """cp1252 is the locale on this machine. A file written as UTF-8 and read
    without saying so comes back mangled, and the amendment headings are where
    that showed."""
    amendments = PROJECT_ROOT / "AI-CONSTITUTION-AMENDMENTS.md"
    if not amendments.exists():
        pytest.skip("no amendments file in this checkout")
    text = amendments.read_text(encoding="utf-8")
    assert "�" not in text, "the amendments file has replacement characters in it"
    headings = [line for line in text.splitlines()
                if line.startswith("## Amendment ")]
    assert headings, "no amendment headings found at all"
    for line in headings:
        assert "�" not in line, f"this heading came back mangled: {line}"
