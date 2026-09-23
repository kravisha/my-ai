"""Jarvis reading his own logs, looking for faults and patterns.

Krish, 2026-09-23: *"the habit of frequently scanning them and seeking faults
and behavior patterns and using these logs to understand about himself and
figure out ways to improve ... What changes he needs to make - that he will know
when he inspects his own logs."*

This is the reading half. `app/eventlog.py` writes; this groups, ranks, and
hands the result to `gateway/gaps.py`, where a recurring fault becomes a
*suspected* capability gap and has to survive investigation before anything is
proposed. Nothing here proposes a change and nothing here is trusted: a log
line is evidence, not a finding.

## Grouping is the whole problem

Two occurrences of the same fault never have the same message - one says
`checkpoint_000012` and the next says `checkpoint_000013`. Group on the raw text
and every fault ranks at one occurrence, and the scan reports, truthfully and
uselessly, that nothing ever happens twice.

So a **signature** is (level, logger, module, line, exception type, normalised
message), and `normalise` replaces the parts that vary: numbers, quoted
strings, paths, hex digests, identifiers. It is coarse on purpose, the same
choice `app/capability_gaps.py` made for the same reason - over-splitting breaks
the ranking, and over-merging is something a reader can see and correct.

The line number is in the signature deliberately. Two warnings from one module
are usually two different problems, and the same warning moving line is a
change Jarvis should notice rather than a new fault.

## Frequency first, and severity above it

An ERROR that happened once outranks a WARNING that happened forty times,
because the one is a failure and the other is usually a shape of a failure. But
within a level it is frequency, for the reason the capability-gap report
already gives: the point is to fix what actually keeps happening, not what is
interesting to read about.

## The clean-log standard

*"His beauty lies in the beauty of these log files with no error messages or
unnecessary warnings."*

That is treated here as a measurable invariant rather than an aspiration.
`config/log_noise_baseline.yaml` lists the signatures that are accepted, each
with a reason and the date it was accepted. Anything not on that list is
**unaccepted noise**, and `unaccepted()` is what the upkeep sweep raises as a
suspected gap. The list can only grow by somebody editing it and saying why,
which is the ratchet: noise is either fixed or justified in writing, and never
merely tolerated.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from app import eventlog, jsonlog

PROJECT_ROOT = Path(__file__).resolve().parent.parent

BASELINE_PATH = PROJECT_ROOT / "config" / "log_noise_baseline.yaml"

# Severity order, worst first. A level the log produces that is not here sorts
# last rather than crashing the scan - a scanner that fell over on an unexpected
# level would stop working the day somebody logged something new.
LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")

# Anything at or above this is a fault worth ranking. INFO is behaviour, and
# behaviour is what `patterns` is for.
FAULT_LEVELS = ("CRITICAL", "ERROR", "WARNING")

# How many times a signature must appear before it is worth raising as a
# suspicion. One WARNING is a Tuesday; the same one every hour is a defect.
# Errors are raised on the first occurrence - an exception that happened at all
# is a thing that should not have.
RECURRENCE_THRESHOLD = 3

# The window a routine scan looks at. A day, because the sweep runs daily and a
# fault that recurs matters more than one that happened last week.
DEFAULT_WINDOW_HOURS = 24

# What `normalise` replaces. Order matters: paths before numbers, or a path with
# a digit in it becomes two substitutions.
_NOISE = (
    (re.compile(r"\b[0-9a-f]{8,}\b"), "<hex>"),
    (re.compile(r"[A-Za-z]:\\\\[^\s'\"]+|(?<![\w.])/[^\s'\":]{2,}"), "<path>"),
    (re.compile(r"\b\w+[-_]\d+\b"), "<id>"),
    (re.compile(r"'[^']*'|\"[^\"]*\""), "<str>"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<n>"),
    (re.compile(r"\s+"), " "),
)


def normalise(message: str) -> str:
    """One fault's message with the parts that vary taken out.

    Coarse deliberately. Over-splitting makes every fault rank at one
    occurrence and breaks the ranking this exists for; over-merging produces a
    group a reader can see is wrong and correct."""
    out = str(message or "").strip().lower()
    for pattern, placeholder in _NOISE:
        out = pattern.sub(placeholder, out)
    return out.strip()


def signature(record: dict) -> str:
    """A stable short id for "the same fault again"."""
    parts = "|".join(str(record.get(field) or "") for field in
                     ("level", "logger", "module", "line", "exception"))
    return hashlib.sha256(
        f"{parts}|{normalise(record.get('message'))}".encode("utf-8")
    ).hexdigest()[:16]


@dataclass
class Finding:
    """One fault, however many times it happened."""

    signature: str
    level: str
    logger: str
    module: str
    line: int
    exception: str | None
    template: str
    count: int
    first_seen: str
    last_seen: str
    example: str
    services: tuple[str, ...] = ()
    request_ids: tuple[str, ...] = ()

    @property
    def severity(self) -> int:
        return LEVELS.index(self.level) if self.level in LEVELS else len(LEVELS)

    @property
    def recurring(self) -> bool:
        """Worth raising. An error counts once; a warning has to repeat."""
        if self.level in ("CRITICAL", "ERROR"):
            return True
        return self.count >= RECURRENCE_THRESHOLD

    def title(self) -> str:
        """The line a gap record is keyed on. Stable across occurrences, which
        is what lets `gaps.suspect` recognise the same one and count it rather
        than filing a second."""
        where = f"{self.module}:{self.line}"
        what = self.exception or self.template[:100]
        return f"log {self.level.lower()} at {where}: {what}"[:200]

    def to_dict(self) -> dict:
        return {
            "signature": self.signature, "level": self.level,
            "logger": self.logger, "module": self.module, "line": self.line,
            "exception": self.exception, "template": self.template,
            "count": self.count, "first_seen": self.first_seen,
            "last_seen": self.last_seen, "example": self.example,
            "services": list(self.services),
            "request_ids": list(self.request_ids),
        }


# --- scanning -----------------------------------------------------------------


def scan(*, since: datetime | None = None, until: datetime | None = None,
         records: list[dict] | None = None,
         levels: tuple[str, ...] = FAULT_LEVELS) -> list[Finding]:
    """Group the window's faults and rank them. Severity first, then frequency."""
    if records is None:
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_WINDOW_HOURS)
        records = eventlog.records(since=since, until=until)

    grouped: dict[str, list[dict]] = {}
    for record in records:
        if record.get("level") not in levels:
            continue
        grouped.setdefault(signature(record), []).append(record)

    findings = []
    for key, group in grouped.items():
        first, last = group[0], group[-1]
        findings.append(Finding(
            signature=key,
            level=str(first.get("level")),
            logger=str(first.get("logger") or ""),
            module=str(first.get("module") or ""),
            line=int(first.get("line") or 0),
            exception=first.get("exception"),
            template=normalise(first.get("message")),
            count=len(group),
            first_seen=str(first.get("at") or ""),
            last_seen=str(last.get("at") or ""),
            example=str(first.get("message") or "")[:500],
            services=tuple(sorted({str(row.get("service")) for row in group
                                   if row.get("service")})),
            request_ids=tuple(sorted({str(row.get("request_id")) for row in group
                                      if row.get("request_id")})[:5]),
        ))
    return sorted(findings, key=lambda item: (item.severity, -item.count))


def patterns(*, since: datetime | None = None,
             records: list[dict] | None = None) -> list[dict]:
    """Behaviour, not faults: things that are not errors but are shapes.

    §11 lists "repeated need for manual intervention" and "contradiction
    between intended and observed behaviour" among the signals of a gap, and
    neither shows up as an exception. These are the three that can be computed
    from the log alone without guessing."""
    if records is None:
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_WINDOW_HOURS)
        records = eventlog.records(since=since)

    out: list[dict] = []

    # 1. One request producing the same fault several times: a retry that is
    # not working, which looks healthy from outside because it finished.
    per_request: dict[tuple[str, str], int] = Counter()
    for record in records:
        if record.get("level") in FAULT_LEVELS and record.get("request_id"):
            per_request[(str(record["request_id"]), signature(record))] += 1
    for (request_id, key), count in per_request.items():
        if count >= RECURRENCE_THRESHOLD:
            out.append({
                "kind": "repeated_within_one_request",
                "signature": key, "request_id": request_id, "count": count,
                "why_it_matters": (
                    "the same fault several times inside one request is a retry "
                    "that is not working; the turn may have finished, which is "
                    "why nothing else would report it")})

    # 2. A fault seen in one service only. Either the other service is fine, or
    # it is failing silently - and which of those it is, is worth knowing.
    by_signature: dict[str, set[str]] = {}
    for record in records:
        if record.get("level") in FAULT_LEVELS:
            by_signature.setdefault(signature(record), set()).add(
                str(record.get("service") or "unknown"))
    services_seen = {str(record.get("service") or "unknown") for record in records}
    if len(services_seen) > 1:
        for key, services in by_signature.items():
            if len(services) == 1:
                out.append({
                    "kind": "one_service_only", "signature": key,
                    "service": next(iter(services)),
                    "why_it_matters": (
                        "this fault appears in one service and not the others "
                        "that run the same code path - either they are fine or "
                        "they are failing quietly")})

    # 3. Silence. A service that logged nothing at all in the window has either
    # not run or has stopped saying anything, and both are worth a look.
    for service in ("gateway", "dba"):
        if service not in services_seen:
            out.append({
                "kind": "silent_service", "service": service,
                "why_it_matters": (
                    f"{service} wrote nothing in this window - it either did "
                    f"not run or has stopped logging, and a component that has "
                    f"stopped logging cannot be observed at all")})
    return out


# --- the clean-log standard ---------------------------------------------------


def baseline(path: Path | None = None) -> dict[str, dict]:
    """The accepted-noise list, keyed by signature.

    A missing or unreadable file means **nothing is accepted**, not everything.
    A scanner that treated an absent baseline as blanket permission would go
    quiet the moment the file was deleted, which is the wrong direction to fail
    for a guard against noise."""
    target = path or BASELINE_PATH
    try:
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    entries = loaded.get("accepted") if isinstance(loaded, dict) else None
    if not isinstance(entries, list):
        return {}
    return {str(entry.get("signature")): entry for entry in entries
            if isinstance(entry, dict) and entry.get("signature")}


def unaccepted(findings: list[Finding], *,
               path: Path | None = None) -> list[Finding]:
    """The findings nobody has justified in writing.

    This is the ratchet. The baseline can only grow by somebody editing a file
    and saying why, so noise is either fixed or explained, and never merely
    tolerated because it has always been there."""
    accepted = baseline(path)
    return [finding for finding in findings
            if finding.signature not in accepted and finding.recurring]


def accepted_reason(finding: Finding, *, path: Path | None = None) -> str | None:
    entry = baseline(path).get(finding.signature)
    return str(entry.get("reason")) if entry else None


# --- handing findings to the lifecycle ----------------------------------------


def raise_suspicions(client, findings: list[Finding] | None = None, *,
                     path: Path | None = None, agent: str | None = None) -> list[dict]:
    """Turn unaccepted faults into suspected gaps. Suspected, and no further.

    §11's whole point: a perceived lack is not a confirmed lack. What this does
    is put the evidence where the lifecycle can see it; confirming it needs a
    test, and changing anything needs Krish."""
    from gateway import gaps, identity

    findings = scan() if findings is None else findings
    raised = []
    for finding in unaccepted(findings, path=path):
        raised.append(gaps.suspect(
            client,
            title=finding.title(),
            description=(
                f"{finding.count} occurrence(s) between {finding.first_seen} "
                f"and {finding.last_seen} in {', '.join(finding.services) or 'an unnamed service'}. "
                f"Example: {finding.example}"),
            detected_by="logscan",
            evidence=finding.to_dict(),
            affected_capability=finding.logger or finding.module,
            severity=finding.level.lower(),
            frequency=finding.count,
            agent=agent or identity.AGENT_ID))
    return raised


def report(*, since: datetime | None = None) -> dict:
    """What a scan found, for a diagnostics page or a brief."""
    findings = scan(since=since)
    return {
        "faults": [finding.to_dict() for finding in findings],
        "unaccepted": [finding.signature for finding in unaccepted(findings)],
        "patterns": patterns(since=since),
        "accepted_count": len(baseline()),
        "clean": not unaccepted(findings),
    }
