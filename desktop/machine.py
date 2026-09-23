"""Looking the facts up on the real machine. One effect per function.

The adapter half of `desktop/readiness.py`. Everything here touches something
that does not exist in the container this was written in - a port, a registry,
a Windows API, a file on Krish's disk - and so none of it can be tested there.
Which is exactly why it must contain no judgement: every function answers one
question with a fact and swallows nothing.

The rule this follows, from `docs/JARVIS_SHELL.md` §0: if it can be decided, it
is decided in tested code. A branch here is a branch nobody can exercise until
it is already on the machine that matters.

**Failures are facts too.** A port that refuses a connection is reported as "not
answering" rather than raised, because half the point of this module is to run
on a machine where most of it is broken. What it never does is report a thing it
could not check as working - that judgement belongs to `readiness`, which has
`BLOCKED` for the purpose.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path

from app import dpapi, keystore, secretbox
from desktop import readiness

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# What the Gateway and the DBA listen on, matching keep-jarvis-up.ps1.
GATEWAY_PORT = 8100
DBA_PORT = 8200
TIMEOUT_SECONDS = 5

# Imported for their side effect of existing. `cryptography` is the one that
# matters most here: without it nothing can open the constitution.
NEEDED = ("fastapi", "uvicorn", "requests", "cryptography", "yaml", "anthropic")


def python_version() -> tuple[int, int]:
    return sys.version_info[:2]


def missing_packages() -> tuple[str, ...]:
    absent = []
    for name in NEEDED:
        try:
            importlib.import_module(name)
        except ImportError:
            absent.append(name)
    return tuple(absent)


def state_directory() -> Path:
    """Where the sealed documents and the key live. Outside the git tree, so a
    `git checkout` of a candidate build cannot touch them."""
    from gateway import constitution

    return constitution.directory()


def state_directory_writable(directory: Path | None = None) -> bool:
    where = Path(directory or state_directory())
    try:
        where.mkdir(parents=True, exist_ok=True)
        probe = where / ".writable-probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def answering(port: int, path: str = "/health") -> bool:
    import requests

    try:
        return requests.get(f"http://127.0.0.1:{port}{path}",
                            timeout=TIMEOUT_SECONDS).status_code < 500
    except Exception:  # noqa: BLE001 - every failure here means "not answering"
        return False


def gateway_reaches_dba() -> bool:
    """Asked of the Gateway rather than of the DBA, because the question is
    whether *he* can get at his memory - a DBA that answers this process and
    refuses his token is the failure that looks healthiest."""
    import requests

    try:
        said = requests.get(f"http://127.0.0.1:{GATEWAY_PORT}/health",
                            timeout=TIMEOUT_SECONDS).json()
    except Exception:  # noqa: BLE001
        return False
    return bool(said.get("dba_reachable") or said.get("dba") == "ok")


def read_keystore() -> keystore.Verdict:
    """The keystore's state, as `app/keystore.py` judges it."""
    directory = state_directory()
    key_file = keystore.key_path(directory)
    escrow_file = keystore.escrow_path(directory)

    opens, print_of_key = False, None
    if key_file.exists():
        try:
            opened = dpapi.unprotect(key_file.read_bytes())
            opens, print_of_key = True, secretbox.fingerprint(opened)
        except Exception:  # noqa: BLE001 - any failure means it does not open
            opens = False

    return keystore.verdict(keystore.Reading(
        windows=sys.platform == "win32",
        dpapi=dpapi.available(),
        key_present=key_file.exists(),
        key_opens=opens,
        escrow_present=escrow_file.exists(),
        # Deliberately not read: unwrapping it needs the passphrase, and asking
        # for it on every status check would teach him to type it without
        # looking. `readiness` treats `None` as "nobody looked", not as a
        # mismatch.
        escrow_fingerprint=None,
        key_fingerprint=print_of_key))


def token_set(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def newest_file_age_hours(directory: Path, pattern: str) -> float | None:
    """How long ago the newest matching file was written, or `None` if there is
    none. `None` is not zero and must never be rendered as fresh."""
    try:
        found = list(Path(directory).glob(pattern))
    except OSError:
        return None
    if not found:
        return None
    newest = max(one.stat().st_mtime for one in found)
    return max(0.0, (time.time() - newest) / 3600.0)


def supervisor_registered() -> bool:
    """Whether the logon task exists. Windows only; False elsewhere, which is
    true rather than convenient - there is no task on a machine with no Task
    Scheduler."""
    import subprocess

    if sys.platform != "win32":
        return False
    found = subprocess.run(["schtasks", "/query", "/tn", "KeepJarvisUp"],
                           capture_output=True, text=True, check=False)
    return found.returncode == 0


def read() -> readiness.Machine:
    """One reading of this machine, for `readiness.look`."""
    said = read_keystore()
    gateway_up = answering(GATEWAY_PORT)
    directory = state_directory()
    return readiness.Machine(
        python_version=python_version(),
        missing_packages=missing_packages(),
        state_directory_writable=state_directory_writable(directory),
        jarvis_token=token_set("DBA_TOKEN_JARVIS"),
        operator_token=token_set("DBA_TOKEN_OPERATOR_CONSOLE"),
        dba_answering=answering(DBA_PORT),
        gateway_answering=gateway_up,
        gateway_reaches_dba=gateway_reaches_dba() if gateway_up else False,
        keystore_state=said.state,
        keystore_because=said.because,
        keystore_next_step=said.next_step,
        constitution_installed=_constitution_installed(),
        constitution_intact=None,
        checkpoint_age_hours=newest_file_age_hours(
            directory / "checkpoints", "*.json"),
        supervisor_registered=supervisor_registered(),
        log_written_within_hours=newest_file_age_hours(
            PROJECT_ROOT / "logs", "*.jsonl"),
        windows=sys.platform == "win32")


def _constitution_installed() -> bool:
    from gateway import constitution

    try:
        return constitution.installed()
    except Exception:  # noqa: BLE001
        return False
