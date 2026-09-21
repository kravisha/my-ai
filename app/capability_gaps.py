"""What Jarvis was asked for and could not do (Task 01, Deliverable D).

> *"Gaps ranked by frequency of request, not by how interesting they are to
> build. ... The ranking rule matters: the point is to build what Krish
> actually keeps asking for."*

That sentence is the whole module. Everything below exists to make frequency
the axis, because the failure mode it guards against is the ordinary one: a
backlog sorted by what was fun to think about, with the thing asked for
weekly sitting under it.

## Capture is on the failure paths, not in a review

§6.1 says a record is written "whenever a request fails, is refused for lack of
capability, or is answered only partially". All three are moments the code
already knows about and nobody is watching:

- the Gateway's model-turn handler (`gateway/main.py`)
- the backend chat's refusal (`backend/main.py`)
- the tool-round ceiling in `gateway/conversation.run_turn`, which is the
  "answered only partially" case and the one a human reviewer would never
  think to write down
- `app/local_ai`'s refusals, which are capability gaps by construction

A gap recorded by a person at the end of a week is a gap they remembered. This
records the ones they did not.

## `gap_type` is classified from the failure, and `unclear` is a real answer

The vocabulary is §6.1's five. `unclear` is not a dumping ground - it is the
honest classification for a turn that failed without saying why, and a report
where `unclear` is the largest bucket is itself the finding that the failure
paths need better reasons. Guessing a specific type to avoid it would put a
confident wrong label on the thing the ranking is computed from.

## Ranking groups by need, not by wording

Two requests for the same missing capability are phrased differently every
time. Grouping on the raw summary would rank every gap at one occurrence and
report, truthfully and uselessly, that nothing is ever asked for twice. So the
key is `(gap_type, what_was_needed)` normalised to lower case with runs of
whitespace collapsed - coarse, deliberately, because over-splitting is the
failure that breaks the ranking rule and over-merging is one a reader can see
and correct.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app import model_calls

SCHEMA_VERSION = 1

GAPS_FILE_NAME = "capability_gaps.jsonl"

# §6.1's closed vocabulary.
GAP_MISSING_TOOL = "missing_tool"
GAP_MISSING_INTEGRATION = "missing_integration"
GAP_MISSING_KNOWLEDGE = "missing_knowledge"
GAP_INSUFFICIENT_PERMISSIONS = "insufficient_permissions"
GAP_UNCLEAR = "unclear"
GAP_TYPES = (GAP_MISSING_TOOL, GAP_MISSING_INTEGRATION, GAP_MISSING_KNOWLEDGE,
             GAP_INSUFFICIENT_PERMISSIONS, GAP_UNCLEAR)

# §6.2: "Explicitly separate 'asked for often' from 'asked for once'." The line
# is drawn at two, because the distinction Krish named is between a thing that
# recurs and a thing that happened, and the second time is when it recurs.
OFTEN_THRESHOLD = 2


def gaps_path() -> Path:
    return model_calls.log_dir() / GAPS_FILE_NAME


def record(*, gap_type: str, what_was_needed: str, user_visible_outcome: str,
           request_summary: str | None = None,
           request_id: str | None = None) -> dict:
    """Write one gap. Returns the record.

    Never raises on a write failure, for the reason the call log gives: this
    runs inside a handler for a turn that has already gone wrong for the user,
    and a second exception there is how a failure becomes a crash."""
    if gap_type not in GAP_TYPES:
        raise ValueError(
            f"gap_type={gap_type!r} is not one of {GAP_TYPES}. The monthly "
            f"report groups on this field; a free-form value would rank as its "
            f"own gap forever.")
    entry = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id or model_calls.current_request_id() or "unknown",
        "request_summary": request_summary,
        "gap_type": gap_type,
        "what_was_needed": what_was_needed,
        "user_visible_outcome": user_visible_outcome,
    }
    try:
        path = gaps_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
    except OSError:  # pragma: no cover - a full or read-only disk
        pass
    return entry


def record_failure(exc: BaseException, *, user_visible_outcome: str,
                   request_summary: str | None = None) -> dict:
    """The convenience the failure handlers actually call.

    Classifies from the exception so that four handlers in two services cannot
    drift into four different vocabularies."""
    return record(
        gap_type=classify(exc),
        what_was_needed=_needed_for(exc),
        user_visible_outcome=user_visible_outcome,
        request_summary=request_summary,
    )


def classify(exc: BaseException) -> str:
    """Which kind of gap an exception represents. `unclear` when it does not say."""
    declared = getattr(exc, "capability_gap_type", None)
    if declared in GAP_TYPES:
        return declared
    name = type(exc).__name__
    if name in ("PermissionError", "HTTPException") or "Permission" in name:
        return GAP_INSUFFICIENT_PERMISSIONS
    if "Credential" in name or "Unauthorized" in name:
        return GAP_INSUFFICIENT_PERMISSIONS
    if "LocalServiceUnavailable" in name or "ModelRoutingFailure" in name:
        return GAP_MISSING_INTEGRATION
    return GAP_UNCLEAR


def _needed_for(exc: BaseException) -> str:
    """A plain-language description of what was missing.

    The exception's own sentence, because these are operator-facing records
    rather than user-facing ones and the original wording is the most specific
    thing available. Truncated, because a stack-trace-length string in a
    ranking key would split every occurrence into its own gap."""
    text = str(exc).strip() or type(exc).__name__
    return text[:200]


def entries(since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    path = gaps_path()
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover
        return []
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or "gap_type" not in entry:
            continue
        moment = _parse(entry.get("timestamp", ""))
        if moment is None:
            continue
        if since is not None and moment < since:
            continue
        if until is not None and moment >= until:
            continue
        found.append(entry)
    return sorted(found, key=lambda item: item.get("timestamp", ""))


def _parse(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _key(entry: dict) -> tuple[str, str]:
    return (entry.get("gap_type", GAP_UNCLEAR),
            " ".join((entry.get("what_was_needed") or "").lower().split()))


def ranked(rows: list[dict]) -> list[dict]:
    """Gaps by frequency of request, most-asked first. §6.2's ranking rule."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    for entry in rows:
        grouped.setdefault(_key(entry), []).append(entry)
    out = []
    for (gap_type, needed), group in grouped.items():
        out.append({
            "gap_type": gap_type,
            "what_was_needed": group[0].get("what_was_needed") or needed,
            "count": len(group),
            "first_seen": group[0].get("timestamp"),
            "last_seen": group[-1].get("timestamp"),
            "examples": [row.get("request_summary") for row in group[:3]
                         if row.get("request_summary")],
            "user_visible_outcomes": sorted({
                row.get("user_visible_outcome") for row in group
                if row.get("user_visible_outcome")}),
        })
    # Frequency first, then recency. Never by gap_type: the alternative sort
    # this module exists to refuse is one where an interesting category floats.
    return sorted(out, key=lambda item: (-item["count"], item["last_seen"] or ""),
                  reverse=False)


# --- what would close each gap ------------------------------------------------
#
# §6.2 asks, for each top gap, "what capability would close it, roughly what it
# would take, and what it depends on". These are the standing answers for the
# five types. They are deliberately generic and deliberately honest about being
# so: a per-gap estimate invented by the report generator would be a number
# nobody measured, and this project's rule is that such a number is worse than
# an absence.
REMEDIES = {
    GAP_MISSING_TOOL: (
        "A new tool in gateway/tools.py, declared for the roles that may call "
        "it (gateway/roles.py) and covered by a test that a wrong argument is "
        "refused. Depends on: nothing outside this repository."),
    GAP_MISSING_INTEGRATION: (
        "An adapter behind an existing interface - providers/ for data, "
        "app/model_provider.ModelProvider for a model. Depends on: credentials "
        "and, for a model, a measured probe of the endpoint before the default "
        "is written down (app/kimi_provider.py is the worked example)."),
    GAP_MISSING_KNOWLEDGE: (
        "Either reference data this system can look up, or a local model that "
        "knows it. Depends on: TQ-57's local runtime for the second, which is "
        "also what makes local-first mean anything."),
    GAP_INSUFFICIENT_PERMISSIONS: (
        "A capability grant in gateway/roles.py, or a consent flow. Depends on: "
        "Krish deciding the grant - this is the one type that is a decision "
        "rather than a build."),
    GAP_UNCLEAR: (
        "Nothing yet. An unclear gap is a failure path that did not say why it "
        "failed; the work is to give that path a reason, not to build a "
        "capability. A large unclear bucket is a finding about this log."),
}


def monthly_report(month: str | None = None, reports_dir: Path | None = None) -> Path:
    """§6.2's report, written to `reports/skills_audit_YYYY-MM.md`."""
    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    start = datetime.fromisoformat(f"{month}-01T00:00:00+00:00")
    end = (datetime.fromisoformat(f"{int(month[:4]) + 1}-01-01T00:00:00+00:00")
           if month[5:7] == "12"
           else datetime.fromisoformat(f"{month[:4]}-{int(month[5:7]) + 1:02d}-01T00:00:00+00:00"))

    rows = entries(since=start, until=end)
    order = ranked(rows)
    often = [gap for gap in order if gap["count"] >= OFTEN_THRESHOLD]
    once = [gap for gap in order if gap["count"] < OFTEN_THRESHOLD]

    lines = [
        f"# Skills audit - {month}",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat()} from "
        f"`{gaps_path()}`.",
        "",
        f"**{len(rows)}** requests in {month} hit something Jarvis could not do, "
        f"across **{len(order)}** distinct gaps.",
        "",
        "Ranked by how often the thing was asked for, not by how interesting it "
        "would be to build. That ordering is the point of this report.",
        "",
    ]

    if not rows:
        lines += [
            "## Nothing recorded",
            "",
            "No capability gap was logged this month. That is either a quiet "
            "month or a capture path that stopped writing - `logs/capability_"
            "gaps.jsonl` is the file to check, and an empty report is not "
            "evidence of a capable assistant.",
            "",
        ]
        return _write(month, lines, reports_dir)

    lines += ["## Asked for often (two or more times)", ""]
    if not often:
        lines += ["Nothing was asked for twice this month.", ""]
    else:
        lines += ["| Rank | Asked | Type | What was needed |",
                  "|---|---|---|---|"]
        for position, gap in enumerate(often, start=1):
            lines.append(
                f"| {position} | **{gap['count']}x** | `{gap['gap_type']}` | "
                f"{_cell(gap['what_was_needed'])} |")
        lines.append("")
        lines.append("### What would close each of these")
        lines.append("")
        for position, gap in enumerate(often, start=1):
            lines += [
                f"**{position}. {_cell(gap['what_was_needed'])}** "
                f"({gap['count']} requests, `{gap['gap_type']}`)",
                "",
                f"- *Capability that would close it:* {REMEDIES[gap['gap_type']]}",
                f"- *First asked:* {gap['first_seen']}",
                f"- *Last asked:* {gap['last_seen']}",
            ]
            if gap["examples"]:
                lines.append("- *Asked as:* " + "; ".join(
                    f"\"{_cell(example)}\"" for example in gap["examples"]))
            if gap["user_visible_outcomes"]:
                lines.append("- *What Jarvis said:* " + "; ".join(
                    f"\"{_cell(outcome)}\"" for outcome in gap["user_visible_outcomes"][:3]))
            lines.append("")

    lines += ["## Asked for once", "",
              "Kept separate on purpose. A single request is not a backlog item "
              "yet; it is a thing to notice if it comes back.", ""]
    if not once:
        lines += ["Nothing appeared only once.", ""]
    else:
        lines += ["| Type | What was needed | When |", "|---|---|---|"]
        for gap in once:
            lines.append(f"| `{gap['gap_type']}` | {_cell(gap['what_was_needed'])} "
                         f"| {gap['last_seen']} |")
        lines.append("")

    counts = Counter(row.get("gap_type") for row in rows)
    lines += ["## By type", "", "| Type | Requests |", "|---|---|"]
    for gap_type in GAP_TYPES:
        if counts.get(gap_type):
            lines.append(f"| `{gap_type}` | {counts[gap_type]} |")
    lines.append("")
    if counts.get(GAP_UNCLEAR, 0) > len(rows) / 2:
        lines += [
            "> More than half of this month's gaps are `unclear`. That is a "
            "finding about the failure paths rather than about capability: a "
            "handler that records a gap without a reason has recorded that "
            "something went wrong, which the call log already knew.",
            "",
        ]
    return _write(month, lines, reports_dir)


def _cell(text: str | None) -> str:
    """One table cell. Pipes escaped, newlines flattened - a report that breaks
    its own table is a report nobody reads to the end."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _write(month: str, lines: list[str], reports_dir: Path | None) -> Path:
    directory = reports_dir or (model_calls.PROJECT_ROOT / "reports")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"skills_audit_{month}.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def main() -> int:  # pragma: no cover - exercised as a script
    path = monthly_report()
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
