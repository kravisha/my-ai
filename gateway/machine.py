"""What is happening on this PC, for the owner who is not sitting at it.

Krish's ask: *"what is happening on my PC ... given all the applications
concerning how much space they are taking, is anything to be concerned about."*
The last clause is the whole point. A wall of numbers is not an answer to "should
I be concerned"; it is the raw material someone else has to interpret. So this
module returns measurements **and** a plain verdict, with the thresholds written
down here rather than left to a model's intuition.

## Read-only, and structurally so

Nothing here writes, deletes, starts or stops anything. Every call is an
observation. That is not a promise in a docstring — there is no code path in this
file that mutates the machine, and the tool that exposes it declares
`system:status`, which is operator-only and grants nothing else.

## Why the thresholds live in code

A model asked "is 12% free disk a problem?" will answer plausibly and
inconsistently. Fixed thresholds make the verdict reproducible and reviewable: you
can disagree with `< 10% free is critical` and change it, which you cannot do with
a judgement that happens invisibly inside a prompt each time.

## What it deliberately does not do

No per-application space accounting. Krish asked for it and it is the one part
that cannot be done honestly here: attributing disk usage to an "application"
means walking Program Files, ProgramData, AppData and the installer registry and
still missing caches and user data. A number produced that way looks authoritative
and is wrong, and a wrong number about disk space is exactly what causes someone
to delete the wrong thing. Largest *folders* is the honest version of that
question, and it is what this returns.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Thresholds. Visible, arguable, and applied the same way every time.
DISK_CRITICAL_PCT = 10.0     # below this free, say so plainly
DISK_WARN_PCT = 20.0
MEM_WARN_PCT = 85.0          # in use
TOP_N = 8
BIG_FOLDER_MIN_GB = 5.0
RECENT_HOURS = 4


def _run_ps(script: str, timeout: int = 25) -> str:
    """PowerShell, never raising. A status report that dies because one probe
    failed is worse than one that reports the failure and carries on."""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return (proc.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return f"(timed out after {timeout}s)"
    except Exception as exc:  # pragma: no cover - defensive
        return f"(failed: {exc!r})"


def disks() -> list[dict]:
    out = []
    for part in ("C:", "D:", "E:"):
        try:
            usage = shutil.disk_usage(part + "\\")
        except OSError:
            continue
        free_pct = usage.free / usage.total * 100 if usage.total else 0.0
        out.append({
            "drive": part,
            "total_gb": round(usage.total / 1e9, 1),
            "used_gb": round(usage.used / 1e9, 1),
            "free_gb": round(usage.free / 1e9, 1),
            "free_pct": round(free_pct, 1),
            "state": ("critical" if free_pct < DISK_CRITICAL_PCT
                      else "low" if free_pct < DISK_WARN_PCT else "ok"),
        })
    return out


def memory() -> dict:
    raw = _run_ps(
        "$o = Get-CimInstance Win32_OperatingSystem;"
        "'{0},{1}' -f $o.TotalVisibleMemorySize, $o.FreePhysicalMemory"
    )
    try:
        total_kb, free_kb = (int(x) for x in raw.split(","))
    except (ValueError, AttributeError):
        return {"available": False, "reason": raw or "no output"}
    used_pct = (total_kb - free_kb) / total_kb * 100 if total_kb else 0.0
    return {
        "available": True,
        "total_gb": round(total_kb / 1048576, 1),
        "free_gb": round(free_kb / 1048576, 1),
        "used_pct": round(used_pct, 1),
        "state": "high" if used_pct > MEM_WARN_PCT else "ok",
    }


def top_processes() -> dict:
    cpu = _run_ps(
        f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {TOP_N} "
        "| ForEach-Object { '{0}|{1:N0}|{2:N0}' -f $_.ProcessName, $_.CPU, ($_.WorkingSet64/1MB) }"
    )
    mem = _run_ps(
        f"Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First {TOP_N} "
        "| ForEach-Object { '{0}|{1:N0}' -f $_.ProcessName, ($_.WorkingSet64/1MB) }"
    )

    def parse(text: str, fields: int) -> list[dict]:
        rows = []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != fields:
                continue
            rows.append(parts)
        return rows

    return {
        "by_cpu": [{"name": r[0], "cpu_seconds": r[1], "ram_mb": r[2]}
                   for r in parse(cpu, 3)],
        "by_memory": [{"name": r[0], "ram_mb": r[1]} for r in parse(mem, 2)],
    }


def large_folders(root: str = "C:\\Users\\Krish") -> list[dict]:
    """Largest immediate subfolders of one root. Bounded on purpose: a full-disk
    walk takes minutes and this is answering a question, not auditing."""
    script = (
        f"Get-ChildItem -LiteralPath '{root}' -Directory -Force -ErrorAction SilentlyContinue | "
        "ForEach-Object { "
        "  $s = (Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue "
        "        | Measure-Object Length -Sum).Sum; "
        "  if ($s -gt 0) { '{0}|{1:N1}' -f $_.Name, ($s/1GB) } "
        "} | Sort-Object { [double]($_ -split '\\|')[1] } -Descending | Select-Object -First 10"
    )
    out = []
    for line in _run_ps(script, timeout=120).splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 2:
            continue
        try:
            gb = float(parts[1].replace(",", ""))
        except ValueError:
            continue
        if gb >= BIG_FOLDER_MIN_GB:
            out.append({"folder": parts[0], "size_gb": gb})
    return out


def recent_changes(root: str = "C:\\Users\\Krish\\ClaudeStuff", hours: int = RECENT_HOURS) -> dict:
    cutoff = datetime.now() - timedelta(hours=hours)
    count, newest = 0, []
    started = datetime.now()
    truncated = False
    try:
        for path in Path(root).rglob("*"):
            if count > 4000 or (datetime.now() - started).total_seconds() > 8:
                truncated = True             # bounded by BOTH count and clock
                break
            try:
                if not path.is_file():
                    continue
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if mtime >= cutoff:
                count += 1
                newest.append((mtime, str(path.relative_to(root))))
    except OSError as exc:
        return {"available": False, "reason": str(exc)}
    newest.sort(reverse=True)
    return {
        "available": True,
        "root": root,
        "hours": hours,
        "changed": count,
        "most_recent": [{"at": m.strftime("%H:%M"), "path": p} for m, p in newest[:10]],
        "truncated": truncated,
    }


def verdict(snapshot: dict) -> list[str]:
    """The answer to "should I be concerned", derived from the thresholds above.

    Returns concerns only. An empty list means nothing crossed a line, and the
    caller says that positively rather than leaving silence to be interpreted."""
    concerns = []
    for disk in snapshot.get("disks", []):
        if disk["state"] == "critical":
            concerns.append(
                f"{disk['drive']} has only {disk['free_gb']} GB free "
                f"({disk['free_pct']}%). Below {DISK_CRITICAL_PCT}% Windows itself "
                "starts having problems.")
        elif disk["state"] == "low":
            concerns.append(
                f"{disk['drive']} is down to {disk['free_gb']} GB free "
                f"({disk['free_pct']}%). Worth watching, not urgent.")
    mem = snapshot.get("memory", {})
    if mem.get("available") and mem.get("state") == "high":
        concerns.append(
            f"Memory is {mem['used_pct']}% used, {mem['free_gb']} GB free.")
    return concerns


def snapshot(include_folders: bool = False) -> dict:
    """Everything cheap, in one call, with the verdict attached.

    `large_folders` is OFF by default and that is a measured decision, not a
    preference: recursively sizing every subtree of the profile exceeded a
    180-second budget on this machine. A question asked by voice has to be
    answered in seconds, so the expensive probe is opt-in and the caller is
    told it was skipped rather than left to assume it was empty."""
    data = {
        "at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "host": os.environ.get("COMPUTERNAME", "unknown"),
        "disks": disks(),
        "memory": memory(),
        "processes": top_processes(),
        "recent_changes": recent_changes(),
    }
    if include_folders:
        data["large_folders"] = large_folders()
    else:
        data["large_folders"] = "not measured - slow probe, ask for it explicitly"
    concerns = verdict(data)
    data["concerns"] = concerns
    data["overall"] = "nothing crossed a threshold" if not concerns else "see concerns"
    # Said explicitly so the agent does not invent one.
    data["not_measured"] = (
        "Per-application disk usage is deliberately absent: attributing space to an "
        "application would require guessing across Program Files, AppData and caches, "
        "and a confident wrong number about disk space is what makes someone delete "
        "the wrong thing. Largest folders is the honest form of that question."
    )
    return data
