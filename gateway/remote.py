"""Diagnosing a machine that is not this one, read-only.

Krish, 2026-09-16 18:12, by phone from abroad: *"Jarvis must eventually be able
to diagnose services and agents running on other authorized machines, not only
its own machine ... For this phase, build the diagnostic capability first.
Prefer read-only inspection ... Report findings before taking corrective
action."* His attached plan makes that Phase 1 and names Phase 3 - recovery - as
a separate thing to be built later.

So this module observes and nothing else. There is no code path here that
starts, stops, writes to or deletes anything on any machine, local or remote.
That is not a promise in a docstring: the only outbound calls are a TCP connect,
an HTTP GET, `tailscale status`, and an SSH command taken verbatim from a
configuration file a person wrote. The tool that exposes it declares
`system:status`, the same operator-only capability as `machine_status`, and
grants nothing else.

## Where the machines come from, and why not from here

Rule 4 of the same message: *"Do not hardcode names such as 'Jarvis,' 'Claude
Dev,' 'Claude Deploy,' machine names, usernames, paths ... into application
logic."* Every target, address, port, path and remote command in a diagnosis
comes out of a JSON file named by `REMOTE_TARGETS_FILE`, falling back to
`config/remote-targets.json` beside the code. This file contains the rules for
reading that document and no knowledge of what is in it.

The model cannot name a host either. `diagnose()` takes the *name of a
configured target*, never an address - so there is no shape of tool call that
points this at a machine nobody authorised, and no way for a conversation to
turn the Gateway into a port scanner.

**A missing configuration file is reported, never guessed around.** It returns
`available=false` naming the path it looked at. The alternative - a built-in
default list of machines - is the exact failure `gateway/main.py`'s relay
fallbacks already demonstrated on this project: a wrong default that looks
identical to working, and here it would mean confidently reporting on a machine
nobody asked about.

## What it can honestly see today, and what it cannot

Without a credential on the far end, four things are observable and they are
genuinely useful:

  * **Whether the peer exists and is up**, from `tailscale status --json` - the
    tailnet's own view, including how long ago it was last seen.
  * **Whether a named port accepts a connection**, by connecting to it.
  * **Whether a service answers**, by fetching a health path over HTTP.
  * **Whether a shared file the remote agent writes is still growing.** This is
    the only evidence available for an *agent* as opposed to a service, and it
    is labelled `observed_on: this host` everywhere it appears, because reading
    a synced file here is not the same act as inspecting the remote disk and a
    report that blurred the two would be worse than no report.

Four things on Krish's list are **not** observable without a credential: the
remote directory structure, its log locations, its process table, and a PID.
Every one of them comes back inside `not_measured` with the reason, rather than
being omitted - an absent field reads as "nothing wrong there" to both a model
and a person, and that is the specific way a diagnosis lies.

## SSH is built, and deliberately carries no commands of its own

When a target has an `ssh` block, each entry in its `checks` list is run with
`BatchMode=yes` - so a host that wants a password fails in seconds instead of
hanging a conversation forever - and its output is reported verbatim. The
commands themselves live in the configuration file. None are built in, and that
is the point: a default like `Get-Process` assumes the far end is Windows, a
default like `ps aux` assumes it is not, and a diagnostic that guesses the
remote operating system is a diagnostic that will one day report confidently
about a machine it never understood.

No target on this machine has an `ssh` block today, because the outbound key and
the account to use it are Krish's to authorise and not mine to create. Until he
does, `ssh` reports `configured: false` and the report says which fields that
costs.

## The verdict, and why it is computed here

`assess()` turns the evidence into the vocabulary Krish asked for - reachable,
answering, alive, hung, absent - plus a probable cause, a confidence and a
recommended next action. The same reasoning as `gateway/machine.py`'s
thresholds: a model asked to judge "is this agent hung or just idle" answers
plausibly and differently each time, and the one place that must be reproducible
is the sentence that decides whether somebody restarts a service. Every verdict
here is derived from a stated rule you can read, disagree with, and change.

`unknown` is a first-class answer. It is returned whenever the evidence does not
distinguish between two states, and the recommended action in that case is
always to obtain the missing evidence rather than to act.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Where the authorised machines are described. Environment first, so a second
# deployment of this Gateway describes a different fleet without a code change.
TARGETS_FILE_ENV = "REMOTE_TARGETS_FILE"
DEFAULT_TARGETS_FILE = Path(__file__).resolve().parent.parent / "config" / "remote-targets.json"

# The tailnet client. Found by configuration, then by PATH, and never by
# guessing at an install directory - a wrong path here would report "the tailnet
# cannot be read" on a machine where it can.
TAILSCALE_EXE_ENV = "TAILSCALE_EXE"

# Budgets. Every probe is bounded, because this runs inside a turn somebody is
# waiting through on a phone. A diagnosis that takes ninety seconds is not a
# diagnosis, it is a hang with a good excuse.
TCP_TIMEOUT = 4.0
HTTP_TIMEOUT = 6.0
PEER_TIMEOUT = 15
SSH_TIMEOUT = 20
SSH_CONNECT_TIMEOUT = 8
BODY_SNIPPET = 400

# How long a shared file may go unwritten before the agent behind it is not
# obviously alive. Overridable per channel in the configuration; this is only
# the default for one that does not say.
DEFAULT_STALE_MINUTES = 60


# There is deliberately no exception type in this module. Every failure a
# diagnosis can hit - an unreadable config, a host that will not answer, a
# missing tailscale binary - is itself a finding, and a finding belongs in the
# report rather than in a traceback that ends the turn and tells Krish nothing.


# --------------------------------------------------------------------- config


def targets_file() -> Path:
    """Resolved per call, not at import.

    The same property `gateway/devchannel.py` needed and for the same reason: a
    module-level constant captured at import cannot be pointed at a temporary
    file by a test, so the suite would either not cover this or would run
    against the real fleet."""
    configured = os.environ.get(TARGETS_FILE_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_TARGETS_FILE


def load_targets() -> dict:
    """The configured machines, or a plain account of why there are none.

    Never raises and never invents a target. A malformed file is reported with
    the parser's own complaint, because "your JSON has a trailing comma on line
    12" is actionable and "no targets configured" is not."""
    path = targets_file()
    if not path.exists():
        return {
            "available": False,
            "path": str(path),
            "targets": [],
            "reason": (
                f"No machines are configured. Nothing is wrong - this file has "
                f"simply not been written yet: {path}. It lists the machines this "
                f"one is allowed to look at. Set {TARGETS_FILE_ENV} to put it "
                f"elsewhere."
            ),
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "path": str(path),
            "targets": [],
            "reason": f"The machine list at {path} could not be read: {exc}",
        }

    entries = raw.get("targets") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return {
            "available": False,
            "path": str(path),
            "targets": [],
            "reason": (
                f"The machine list at {path} is not in the expected shape: it "
                f"should be an object with a 'targets' array."
            ),
        }

    targets, problems = [], []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"entry {index} is not an object")
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            problems.append(f"entry {index} has no name")
            continue
        targets.append(entry)

    return {
        "available": True,
        "path": str(path),
        "tailscale_exe": (raw.get("tailscale_exe") if isinstance(raw, dict) else None),
        "targets": targets,
        "names": [t["name"] for t in targets],
        "problems": problems,
    }


# --------------------------------------------------------------------- probes


def _tailscale_exe(configured: str | None = None) -> str | None:
    for candidate in (configured, os.environ.get(TAILSCALE_EXE_ENV)):
        if candidate and Path(candidate).exists():
            return candidate
    return shutil.which("tailscale")


def peer_status(host: str, *, exe: str | None = None) -> dict:
    """What the tailnet says about one peer.

    The only probe here that reports on a machine without touching it, which
    makes it the one worth having first: a peer the coordination plane has not
    seen for two days is a different problem from a peer that is up and refusing
    a port, and no amount of connecting to ports distinguishes them."""
    binary = _tailscale_exe(exe)
    if not binary:
        return {
            "available": False,
            "reason": (
                "The tailscale client was not found on PATH. Set "
                f"{TAILSCALE_EXE_ENV}, or 'tailscale_exe' in the machine list, "
                "to its full path."
            ),
        }
    try:
        proc = subprocess.run(
            [binary, "status", "--json"],
            capture_output=True, text=True, timeout=PEER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": f"tailscale status timed out after {PEER_TIMEOUT}s"}
    except OSError as exc:
        return {"available": False, "reason": f"tailscale status could not run: {exc}"}

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        return {"available": False, "reason": f"tailscale status exited {proc.returncode}: {detail}"}
    try:
        status = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"available": False, "reason": f"tailscale status returned something unreadable: {exc}"}

    wanted = host.strip().lower()
    for peer in (status.get("Peer") or {}).values():
        names = {str(peer.get("HostName", "")).lower(),
                 str(peer.get("DNSName", "")).rstrip(".").lower()}
        names.add(str(peer.get("DNSName", "")).split(".")[0].lower())
        ips = [str(ip) for ip in (peer.get("TailscaleIPs") or [])]
        if wanted in names or wanted in {ip.lower() for ip in ips}:
            return {
                "available": True,
                "found": True,
                "hostname": peer.get("HostName"),
                "dns_name": str(peer.get("DNSName", "")).rstrip("."),
                "ips": ips,
                "os": peer.get("OS"),
                "online": bool(peer.get("Online")),
                "last_seen": peer.get("LastSeen"),
                "last_handshake": peer.get("LastHandshake"),
            }
    return {
        "available": True,
        "found": False,
        "reason": f"No peer on this tailnet matches {host!r}.",
    }


def tcp_probe(host: str, port: int, *, timeout: float = TCP_TIMEOUT) -> dict:
    """Does something accept a connection there.

    Preferred over ICMP on purpose, and the difference matters for the verdict:
    a host answers ping while every service on it is dead, and a host that
    filters ICMP looks dead while serving perfectly. A TCP connect to a port
    somebody named is evidence about the thing actually being asked about."""
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
    except OSError as exc:
        return {
            "port": int(port),
            "open": False,
            "ms": round((time.monotonic() - started) * 1000),
            "error": str(exc),
        }
    return {
        "port": int(port),
        "open": True,
        "ms": round((time.monotonic() - started) * 1000),
    }


def http_probe(url: str, *, timeout: float = HTTP_TIMEOUT) -> dict:
    """A GET, and the status is the point rather than the body.

    A 401 is a *pass* for liveness: it means the service is running and
    authorising, which is exactly what `ship-attachments.ps1` learned to assert
    about a route. Only the caller decides whether that is the answer it wanted,
    so this reports the number and does not judge it."""
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "gateway-remote-diagnostics"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(BODY_SNIPPET).decode("utf-8", "replace")
            return {
                "url": url,
                "status": int(response.status),
                "reachable": True,
                "ms": round((time.monotonic() - started) * 1000),
                "body_snippet": body.strip(),
            }
    except urllib.error.HTTPError as exc:
        return {
            "url": url,
            "status": int(exc.code),
            "reachable": True,
            "ms": round((time.monotonic() - started) * 1000),
            "body_snippet": "",
            "note": "answered with an error status, which still proves it is running",
        }
    except Exception as exc:  # URLError, socket.timeout, ssl errors, malformed url
        return {
            "url": url,
            "status": None,
            "reachable": False,
            "ms": round((time.monotonic() - started) * 1000),
            "error": str(exc),
        }


def file_activity(path: str, *, stale_minutes: int = DEFAULT_STALE_MINUTES) -> dict:
    """Is a file still being written, and how long since it last was.

    This is how an *agent* is observed rather than a service. An agent with no
    port to connect to leaves exactly one trace an outsider can read: the file
    it appends to. The result carries `observed_on: this host` because that is
    what it is - a local stat of a shared or synced path - and the difference
    between that and looking at the remote disk is the whole honesty of the
    report."""
    target = Path(path)
    try:
        stat = target.stat()
    except OSError as exc:
        return {
            "path": str(target),
            "observed_on": "this host",
            "exists": False,
            "state": "missing",
            "error": str(exc),
        }
    modified = datetime.fromtimestamp(stat.st_mtime).astimezone()
    age_minutes = max(0.0, (datetime.now().astimezone() - modified).total_seconds() / 60)
    return {
        "path": str(target),
        "observed_on": "this host",
        "exists": True,
        "size_bytes": stat.st_size,
        "modified": modified.isoformat(timespec="seconds"),
        "age_minutes": round(age_minutes, 1),
        "stale_after_minutes": int(stale_minutes),
        "state": "fresh" if age_minutes <= stale_minutes else "stale",
    }


def ssh_probe(target: dict, *, runner=None) -> dict:
    """The read-only commands a person wrote for this host, run over SSH.

    `runner` exists so the suite can exercise this without a second machine. It
    is a parameter rather than a patch point because the alternative - tests
    that monkeypatch `subprocess` - end up asserting how this module calls SSH
    instead of what it does with the answer.

    `BatchMode=yes` is not a preference. Without it, a host that has lost its
    key prompts for a password, and there is no one at this keyboard to type
    one; the probe would hang until its timeout on every single call."""
    config = target.get("ssh")
    if not isinstance(config, dict):
        return {
            "configured": False,
            "reason": (
                "No SSH is configured for this machine, so nothing inside it can "
                "be inspected - only whether it is reachable and whether its "
                "services answer. Adding an 'ssh' block with a key and a list of "
                "read-only checks is what unlocks processes, PIDs and logs."
            ),
        }
    checks = config.get("checks")
    if not isinstance(checks, list) or not checks:
        return {
            "configured": True,
            "ran": 0,
            "reason": (
                "SSH is configured for this machine but no checks are listed, so "
                "nothing was run. Each check is a name and a read-only command; "
                "none are built in, because a built-in one would assume which "
                "operating system is on the far end."
            ),
        }

    host = config.get("host") or target.get("host")
    user = config.get("user")
    if not host or not user:
        return {"configured": True, "ran": 0,
                "reason": "The SSH block needs both a user and a host."}

    base = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}"]
    if config.get("port"):
        base += ["-p", str(config["port"])]
    if config.get("key"):
        base += ["-i", str(config["key"])]
    if config.get("strict_host_key_checking") is False:
        base += ["-o", "StrictHostKeyChecking=no"]
    base.append(f"{user}@{host}")

    def run(command: list[str]) -> dict:
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=SSH_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "exit_code": None, "error": f"timed out after {SSH_TIMEOUT}s"}
        except OSError as exc:
            return {"ok": False, "exit_code": None, "error": f"ssh could not run: {exc}"}
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": (proc.stdout or "").strip()[:2000],
            "error": (proc.stderr or "").strip()[:400],
        }

    execute = runner or run
    results = []
    for check in checks:
        if not isinstance(check, dict) or not check.get("command"):
            continue
        outcome = execute(base + [str(check["command"])])
        outcome["name"] = check.get("name") or str(check["command"])[:40]
        results.append(outcome)
    return {"configured": True, "ran": len(results), "checks": results}


# -------------------------------------------------------------------- verdict


def _service_state(service: dict, tcp: dict, http: dict | None) -> dict:
    """One service, in four words and the evidence for whichever one it got."""
    if http and http.get("reachable"):
        return {
            "state": "answering",
            "why": f"it answered HTTP {http.get('status')} on {service.get('health_path', '/')}",
        }
    if tcp.get("open") and http and not http.get("reachable"):
        return {
            "state": "listening but not answering",
            "why": (
                "the port accepted a connection but the health request did not "
                f"complete: {http.get('error')}"
            ),
        }
    if tcp.get("open"):
        return {"state": "listening", "why": "the port accepted a connection"}
    return {
        "state": "not listening",
        "why": f"nothing accepted a connection on port {tcp.get('port')}: {tcp.get('error')}",
    }


def assess(target: dict, evidence: dict) -> dict:
    """Krish's Phase 2 report, derived from stated rules rather than judgement.

    The rules, in the order they are applied, because the order is the whole
    reasoning:

      1. If the tailnet knows the peer and says it is offline, the machine is
         down and nothing about its services means anything. Say so and stop -
         listing four dead ports underneath that is noise.
      2. If any port accepts a connection, the machine is up, whatever the
         tailnet thinks. A live connection outranks a coordination plane's
         opinion, which can lag.
      3. A service is judged only on its own probes, never on a sibling's.
      4. An agent is judged on its file, and only ever as 'alive', 'quiet' or
         'unknown' - never 'hung'. Hung and idle are indistinguishable from
         outside, and naming the worse one would get a working session killed.
    """
    peer = evidence.get("peer") or {}
    services = evidence.get("services") or []
    channels = evidence.get("channels") or []

    any_port_open = any(s.get("tcp", {}).get("open") for s in services)
    any_answering = any(s.get("verdict", {}).get("state") == "answering" for s in services)

    if any_port_open:
        connectivity = "reachable"
        connectivity_why = "a service on it accepted a connection from here"
    elif peer.get("available") and peer.get("found") and peer.get("online"):
        connectivity = "reachable"
        connectivity_why = "the tailnet reports the peer online, though nothing was probed successfully"
    elif peer.get("available") and peer.get("found") and not peer.get("online"):
        connectivity = "unreachable"
        connectivity_why = f"the tailnet reports the peer offline; last seen {peer.get('last_seen')}"
    elif peer.get("available") and not peer.get("found"):
        connectivity = "unknown"
        connectivity_why = "no peer with that name or address is on this tailnet at all"
    elif services:
        connectivity = "unreachable"
        connectivity_why = "nothing accepted a connection, and the tailnet's view could not be read"
    else:
        connectivity = "unknown"
        connectivity_why = "nothing was probed: this machine has no services and no channels configured"

    # The agent half. Deliberately three states and no fourth.
    agent_lines = []
    for channel in channels:
        activity = channel.get("activity", {})
        label = channel.get("name") or activity.get("path")
        if activity.get("state") == "missing":
            agent_lines.append({
                "channel": label,
                "state": "no evidence",
                "why": f"the file it would write is not there: {activity.get('error')}",
            })
        elif activity.get("state") == "fresh":
            agent_lines.append({
                "channel": label,
                "state": "alive",
                "why": (f"it was written {activity.get('age_minutes')} minutes ago, "
                        f"within the {activity.get('stale_after_minutes')} minute window"),
            })
        else:
            agent_lines.append({
                "channel": label,
                "state": "quiet",
                "why": (f"nothing has been written for {activity.get('age_minutes')} minutes. "
                        "Quiet is not the same as hung: an agent with nothing to say "
                        "looks exactly like one that has stopped, and only something "
                        "inside that machine can tell them apart"),
            })

    quiet = [a for a in agent_lines if a["state"] in ("quiet", "no evidence")]

    if connectivity == "unreachable":
        cause = "The machine itself is not reachable, so nothing on it can be expected to answer."
        confidence = "high" if peer.get("found") else "medium"
        action = ("Confirm it is powered on and connected. Nothing here can do that "
                  "remotely, and no service should be touched until it is back.")
    elif services and not any_answering and any_port_open:
        cause = "The machine is up and something is listening, but no service completed a health request."
        confidence = "medium"
        action = "Look at the service's own logs on that machine. That needs SSH, which is not configured here."
    elif services and not any_port_open and connectivity == "reachable":
        cause = "The machine is up but the services asked about are not listening."
        confidence = "medium"
        action = "The service is probably stopped rather than broken. Confirm before restarting anything."
    elif quiet and any_answering:
        cause = ("The machine and its services are healthy; only the agent is quiet. "
                 "That points at the agent or its channel rather than at the host.")
        confidence = "medium"
        action = ("Check whether the agent's session is still running on that machine. "
                  "It cannot be told apart from an idle one from out here.")
    elif quiet and not services:
        cause = ("The only evidence available for this one is a file it writes, and that "
                 "file has not moved. Nothing here distinguishes stopped from idle.")
        confidence = "low"
        action = ("Get evidence from inside that machine before acting - an SSH check, or "
                  "someone at the keyboard. A restart decided on this alone could kill a working session.")
    elif any_answering and not quiet:
        cause = "Nothing is wrong that can be seen from here."
        # High, but bounded by what was looked at: without SSH this says the
        # outside of the machine is healthy, which is not the same sentence as
        # "the machine is healthy" and must not be reported as though it were.
        confidence = "high"
        action = "No action. Re-run this if the symptom persists, and say what the symptom is."
    else:
        cause = "The evidence does not settle it."
        confidence = "low"
        action = "Collect the missing evidence named in not_measured before acting."

    return {
        "machine": target.get("label") or target.get("name"),
        "target": target.get("name"),
        "connectivity": connectivity,
        "connectivity_why": connectivity_why,
        "services": [
            {"service": s.get("name"), **s.get("verdict", {})} for s in services
        ],
        "agents": agent_lines,
        "probable_cause": cause,
        "confidence": confidence,
        "recommended_next_action": action,
        "corrective_action_taken": "none - this is a read-only diagnosis",
    }


def _not_measured(ssh: dict) -> dict:
    """The four things Krish asked for that cannot be seen from outside.

    Stated as a field rather than left out. An omitted measurement reads as a
    clean one, and every wrong confident sentence this project has produced came
    from something absent being taken for something fine."""
    if ssh.get("configured") and ssh.get("ran"):
        return {}
    reason = ssh.get("reason", "no SSH access to this machine")
    return {
        "process_table": reason,
        "pid": reason,
        "directory_structure": reason,
        "remote_log_locations_and_freshness": reason,
        "note": (
            "These four are on the plan and they are genuinely not measured, not "
            "measured-and-clean. Anything said about them would be invented. ICMP "
            "is also deliberately unused: a host can filter ping while serving "
            "perfectly, and can answer ping with everything on it dead."
        ),
    }


# ------------------------------------------------------------------- the call


def diagnose_target(target: dict, *, tailscale_exe: str | None = None, ssh_runner=None) -> dict:
    """Every probe this machine is configured for, then the verdict."""
    host = str(target.get("host") or target.get("hostname") or "").strip()
    evidence: dict = {"target": target.get("name"), "host": host or None}

    evidence["peer"] = (
        peer_status(str(target.get("hostname") or host), exe=tailscale_exe)
        if (target.get("hostname") or host)
        else {"available": False, "reason": "this machine has no host or hostname configured"}
    )

    services = []
    for service in target.get("services") or []:
        if not isinstance(service, dict) or not service.get("port"):
            continue
        if not host:
            services.append({"name": service.get("name"),
                             "verdict": {"state": "unknown",
                                         "why": "no address is configured for this machine"}})
            continue
        tcp = tcp_probe(host, int(service["port"]))
        http = None
        if service.get("health_path"):
            scheme = service.get("scheme") or "http"
            http = http_probe(f"{scheme}://{host}:{int(service['port'])}{service['health_path']}")
        record = {"name": service.get("name") or f"port {service['port']}", "tcp": tcp}
        if http is not None:
            record["http"] = http
        record["verdict"] = _service_state(service, tcp, http)
        services.append(record)
    evidence["services"] = services

    channels = []
    for channel in target.get("channels") or []:
        if not isinstance(channel, dict) or not channel.get("path"):
            continue
        channels.append({
            "name": channel.get("name") or channel["path"],
            "what_it_is": channel.get("description"),
            "activity": file_activity(
                str(channel["path"]),
                stale_minutes=int(channel.get("stale_minutes") or DEFAULT_STALE_MINUTES),
            ),
        })
    evidence["channels"] = channels

    evidence["ssh"] = ssh_probe(target, runner=ssh_runner)

    report = assess(target, evidence)
    not_measured = _not_measured(evidence["ssh"])
    return {
        "at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "observed_from": os.environ.get("COMPUTERNAME", "unknown"),
        "report": report,
        "evidence": evidence,
        "not_measured": not_measured,
        "read_only": True,
    }


def diagnose(name: str | None = None, *, ssh_runner=None) -> dict:
    """One configured machine, or all of them.

    The argument is a *configured name*, never an address. A model that could
    supply a host could point this anywhere reachable from this machine, and
    "read-only" is not much comfort when the thing being read is somebody
    else's network."""
    catalogue = load_targets()
    if not catalogue["available"]:
        return {"available": False, "reason": catalogue["reason"], "path": catalogue["path"]}

    targets = catalogue["targets"]
    if not targets:
        return {
            "available": False,
            "path": catalogue["path"],
            "reason": f"The machine list at {catalogue['path']} has no usable entries.",
            "problems": catalogue.get("problems") or [],
        }

    if name:
        wanted = str(name).strip().lower()
        chosen = [t for t in targets if str(t["name"]).lower() == wanted]
        if not chosen:
            return {
                "available": False,
                "reason": (
                    f"There is no configured machine called {name!r}. "
                    f"Configured: {', '.join(catalogue['names'])}. Only these can be "
                    "looked at, and that is deliberate."
                ),
                "configured": catalogue["names"],
            }
    else:
        chosen = targets

    exe = catalogue.get("tailscale_exe")
    return {
        "available": True,
        "configured": catalogue["names"],
        "diagnosed": [
            diagnose_target(t, tailscale_exe=exe, ssh_runner=ssh_runner) for t in chosen
        ],
        "read_only": (
            "Nothing was started, stopped, written or deleted, on this machine or "
            "any other. Recovery is a separate capability and it is not built yet."
        ),
    }
