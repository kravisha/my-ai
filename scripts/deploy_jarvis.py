"""The build/relaunch controller's working half. §19.

    *"JARVIS must not assume he can safely terminate and launch himself
    directly. A separate launcher, supervisor, build service ... should perform
    controlled rebuild/relaunch."*

`scripts/keep-jarvis-up.ps1` is that supervisor. It already restarts the
Gateway when `/health` stops answering; this script is the part that deploys an
approved change, and it is deliberately Python rather than more PowerShell so
that it can be tested on every platform CI runs on.

## Why this file is in `scripts/` and not in `gateway/`

Because `gateway/` is what Jarvis may propose changes to. A build controller
that lived there would be a build controller Jarvis could rewrite by getting
one proposal approved - §16's *"bypass source control"* and *"relaunch an
unapproved build"* reached in a single step. `gateway/introspect.py` refuses
any path outside `gateway/` and `app/`, so this file is readable by Jarvis and
modifiable only by a person.

## The request file is not trusted

Jarvis writes `deploy-request.json` and this script reads it. On its own that
would mean anything able to write that file could have an arbitrary commit
deployed. So the request is **verified against the DBA** before anything is
checked out: the named change proposal must exist, must carry
`approval_state: approve`, and its `commit_id` must be the commit the request
asks for. The controller authenticates as `operator_console`, not as Jarvis -
it is acting for Krish, and the agent whose code is being replaced should not
be the agent whose credentials authorise replacing it.

A request that does not verify is refused and the result says why. The
previous build keeps running, which is the correct outcome for every unclear
case.

## Tests run before the restart, never after

A change that fails its tests is never the running build. The sequence is
fetch, check out, test, and only then let the supervisor restart - so a red
suite costs a restart that never happened rather than an outage.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REQUEST_FILE = "deploy-request.json"
RESULT_FILE = "deploy-result.json"
DEPLOYED_COMMIT_FILE = "DEPLOYED-COMMIT.txt"

DEPLOY_DIR_ENV = "JARVIS_DEPLOY_DIR"
DBA_URL_ENV = "JARVIS_DBA_URL"
OPERATOR_TOKEN_ENV = "DBA_TOKEN_OPERATOR_CONSOLE"

DEFAULT_DBA_URL = "http://127.0.0.1:8200"

# Long enough for the real suite, bounded so a hung test cannot leave the
# controller wedged with the old build stopped and the new one untested.
TEST_TIMEOUT_SECONDS = 3600

DEPLOY = "deploy"
ROLLBACK = "rollback"

OK = "ok"
REFUSED = "refused"
TESTS_FAILED = "tests_failed"
BUILD_FAILED = "build_failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deploy_dir() -> Path:
    return Path(os.environ.get(DEPLOY_DIR_ENV) or PROJECT_ROOT)


def read_request(directory: Path | None = None) -> dict | None:
    path = (directory or deploy_dir()) / REQUEST_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_result(result: dict, directory: Path | None = None) -> Path:
    target = directory or deploy_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / RESULT_FILE
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return path


def clear_request(directory: Path | None = None) -> None:
    """Remove a handled request so the next poll does not redeploy it.

    Deleting rather than marking it: a request file that is still there after
    being acted on is one a restarted supervisor will act on again, and
    "deployed twice" is only harmless until one of the two is a rollback."""
    path = (directory or deploy_dir()) / REQUEST_FILE
    try:
        path.unlink()
    except OSError:
        pass


# --- verification -------------------------------------------------------------


def verify_approved(request: dict, *, fetch=None) -> tuple[bool, str]:
    """Ask the DBA whether this change really was approved, and for this commit.

    `fetch` is injected so the tests exercise this against the real DBA service
    rather than against a description of it."""
    change_id = (request or {}).get("change_id")
    if not change_id:
        return False, "the request names no change_id"

    token = (os.environ.get(OPERATOR_TOKEN_ENV) or "").strip()
    if not token:
        return False, (
            f"{OPERATOR_TOKEN_ENV} is not set, so the controller cannot check "
            f"with the DBA whether this change was approved. Refusing: an "
            f"unverifiable deploy request is not a safer one for being urgent.")

    caller = fetch or _ask_dba
    try:
        status, body = caller(change_id, token)
    except Exception as exc:  # noqa: BLE001 - any transport failure is a refusal
        return False, f"could not reach the DBA to verify approval: {exc}"

    if status != 200 or (body or {}).get("status") != "success":
        return False, (f"the DBA did not confirm {change_id}: "
                       f"{(body or {}).get('error') or status}")

    proposal = (body or {}).get("result") or {}
    if proposal.get("approval_state") != "approve":
        return False, (
            f"{change_id} is {proposal.get('approval_state') or 'undecided'}, "
            f"not approved. §13: the user is the final authority, and a "
            f"request file is not a decision.")

    wanted = request.get("commit") or request.get("to_version")
    recorded = (proposal.get("commit_id") if request.get("action") != ROLLBACK
                else proposal.get("baseline_version"))
    if wanted and recorded and wanted != recorded:
        return False, (
            f"the request asks for {wanted} but {change_id} records "
            f"{recorded}. Refusing rather than picking one - a deploy request "
            f"that disagrees with the approved record is the case this check "
            f"exists for.")
    return True, ""


def _ask_dba(change_id: str, token: str):  # pragma: no cover - needs a network
    import requests

    url = (os.environ.get(DBA_URL_ENV) or DEFAULT_DBA_URL).rstrip("/")
    response = requests.post(
        f"{url}/request",
        json={"action": "get", "requested_by": "operator_console",
              "actor": "build_controller", "entity_type": "change_proposal",
              "entity_id": change_id},
        headers={"X-DBA-Agent": "operator_console", "X-DBA-Token": token},
        timeout=(2, 10))
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {}


# --- git ----------------------------------------------------------------------


def _git(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(PROJECT_ROOT), *args],
                          capture_output=True, text=True, timeout=timeout,
                          check=False)


def current_commit() -> str | None:
    result = _git("rev-parse", "HEAD")
    commit = (result.stdout or "").strip()
    return commit if result.returncode == 0 and commit else None


def checkout(commit: str) -> tuple[bool, str]:
    """Put the working tree on one commit. Reports rather than raises."""
    for args in (("fetch", "--all", "--prune"), ("checkout", "--force", commit)):
        result = _git(*args)
        if result.returncode != 0:
            # A fetch failure is survivable when the commit is already local;
            # a checkout failure is not.
            if args[0] == "fetch":
                continue
            return False, f"git {' '.join(args)}: {(result.stderr or '').strip()[:400]}"
    return True, ""


def run_tests(timeout_seconds: int = TEST_TIMEOUT_SECONDS) -> dict:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"], cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        return {"passed": False, "ran": False,
                "why": f"the suite did not finish within {timeout_seconds}s",
                "summary": ""}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"passed": False, "ran": False, "why": f"could not run: {exc}",
                "summary": ""}
    lines = (result.stdout or "").splitlines()
    return {"passed": result.returncode == 0, "ran": True,
            "why": "" if result.returncode == 0 else f"pytest exit {result.returncode}",
            "summary": "\n".join(lines[-20:])}


def stamp_deployed(commit: str) -> None:
    """Write the commit the runtime should report as its own.

    `gateway/identity.code_version()` reads this before it asks git, because
    the relaunched runtime in §21 step 6 must be able to say what it is running
    even from a checkout it did not make."""
    (PROJECT_ROOT / DEPLOYED_COMMIT_FILE).write_text(
        f"{commit}\n", encoding="utf-8")


# --- the controller -----------------------------------------------------------


def handle(request: dict, *, directory: Path | None = None,
           verify=verify_approved, tester=run_tests) -> dict:
    """Carry out one deploy or rollback request and return the result written.

    Every path writes a result. A supervisor that acted and left no record
    would give the relaunched Jarvis nothing to validate against, and §21 step
    11 asks him to mark the change accepted, degraded, failed or rolled back."""
    action = (request or {}).get("action") or DEPLOY
    was = current_commit()
    result: dict = {"handled_at": _now(), "action": action,
                    "change_id": (request or {}).get("change_id"),
                    "previous_commit": was}

    approved, why = verify(request)
    if not approved:
        result.update({"status": REFUSED, "why": why, "commit": was})
        write_result(result, directory)
        clear_request(directory)
        return result

    target = ((request or {}).get("to_version") if action == ROLLBACK
              else (request or {}).get("commit"))
    if not target:
        result.update({"status": REFUSED, "commit": was,
                       "why": "the request names no commit to move to"})
        write_result(result, directory)
        clear_request(directory)
        return result

    moved, problem = checkout(target)
    if not moved:
        result.update({"status": BUILD_FAILED, "why": problem, "commit": was})
        write_result(result, directory)
        clear_request(directory)
        return result

    outcome = tester()
    result["tests"] = outcome

    if not outcome.get("passed"):
        # Back to what was running. A red suite must not become the live build,
        # and the machine Krish reaches from his phone must not be left on a
        # commit nobody validated.
        restored, restore_problem = checkout(was) if was else (False, "no previous commit")
        result.update({
            "status": TESTS_FAILED,
            "why": outcome.get("why") or "the tests did not pass",
            "commit": was if restored else target,
            "restored_previous": restored,
            "restore_problem": restore_problem,
        })
        write_result(result, directory)
        clear_request(directory)
        return result

    stamp_deployed(target)
    result.update({"status": OK, "commit": target, "why": ""})
    write_result(result, directory)
    clear_request(directory)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/deploy_jarvis.py",
        description="Deploy an approved Jarvis change, or roll one back. "
                    "Run by the supervisor; not by Jarvis.")
    parser.add_argument("--dir", default=None,
                        help="where the request and result files live")
    parser.add_argument("--check", action="store_true",
                        help="report whether a request is waiting and exit")
    args = parser.parse_args(argv)
    directory = Path(args.dir) if args.dir else deploy_dir()

    request = read_request(directory)
    if request is None:
        if args.check:
            print("no deploy request")
        return 0
    if args.check:
        print(json.dumps(request, indent=2, sort_keys=True))
        return 0

    result = handle(request, directory=directory)
    print(json.dumps(result, indent=2, sort_keys=True))
    # 0 means "the supervisor should restart the Gateway". Every other outcome
    # leaves the previous build running and needs no restart.
    return 0 if result["status"] == OK else 1


if __name__ == "__main__":  # pragma: no cover - a script
    raise SystemExit(main())
