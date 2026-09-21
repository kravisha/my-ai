"""Jarvis reads his own call log and reports on himself (Task 01, Deliverable C).

## What this is for, which is not "observability"

A dashboard shows you numbers when you go and look. This writes a paragraph
about its own behaviour, every night, to a file, and puts the two lines that
matter into the morning brief. The difference is who has to remember: a
dashboard requires Krish to suspect something first, which is how he came to be
reading a bill instead of a report.

## The one rule it will not break

> *"A suggested threshold adjustment, with the reasoning, if the data supports
> one. **Suggested only - Jarvis does not tune his own threshold without
> approval.**"*

Nothing here writes `config/router.yaml`. `suggest_threshold` returns a
sentence and a number; applying it is an edit a person makes. That is not
timidity about automation - a system that adjusts the threshold it is judged by,
on the evidence it collected itself, has no independent check left anywhere in
the loop.

## What "avoidable" means, stated before it is counted

An escalation is avoidable when the local tier could plausibly have taken the
request:

1. `routed_by: direct_call` - local-first never got a say, because the router
   was never asked. Always avoidable, and always a bug.
2. An `escalation_reason` outside `config/router.yaml`'s
   `permitted_escalations`. §4.1 lists four; anything else is a path that
   escalated for a reason nobody sanctioned.
3. `low_confidence` where the score sits within `MARGINAL_BAND` of the
   threshold. Not a bug - a judgement call that went one way and could as
   easily have gone the other, which is precisely the evidence a threshold
   suggestion is made of.
4. An escalated request in which no local call was ever recorded, where the
   reason given was not one that explains the absence. If the local tier was
   skipped and the reason does not say it was unusable, something skipped it.

**And the number this produces today is zero, for a reason the report says out
loud.** Every escalation on this machine is `local_error`, because there is no
local model (`docs/CURRENT_ARCHITECTURE.md` §4). A report that printed
"0 avoidable escalations" and stopped would read as a clean bill of health for a
system that sends one hundred per cent of its traffic to a paid API. So
`_unavoidable_note` exists, and it is the loudest paragraph in the file.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import capability_gaps, confidence, model_calls, retry_queue, router_config

SCHEMA_VERSION = 1

# How close to the threshold a low-confidence escalation has to be before it
# counts as a judgement call rather than a clear-cut one. A tenth of the range,
# which is wide enough to collect evidence and narrow enough that a genuinely
# poor answer is not counted as nearly good.
MARGINAL_BAND = 0.10

# A call is a latency outlier if it took this many times the median. Three,
# because two catches ordinary variance on a network call and four catches
# almost nothing - and this is a figure to be argued with from data, which is
# why it is a named constant rather than a literal inside a comprehension.
OUTLIER_FACTOR = 3.0

# The reasons that explain why no local call appears in a request. Escalating
# without a local attempt is only legitimate when the local tier said it could
# not serve this request.
_EXPLAINS_NO_LOCAL_CALL = (
    model_calls.REASON_LOCAL_ERROR,
    model_calls.REASON_TOOL_REQUIRED,
    model_calls.REASON_CONTEXT_LENGTH,
)


def reports_dir() -> Path:
    return model_calls.PROJECT_ROOT / "reports"


# --- the analysis, separate from the prose it becomes -------------------------


def analyse(records: list[dict]) -> dict:
    """Everything the report says, as data.

    Separate from the rendering so the brief, the report and the suite can all
    read the same conclusions rather than three parsers of one Markdown file."""
    by_request: dict[str, list[dict]] = {}
    for record in records:
        by_request.setdefault(record.get("request_id", "unknown"), []).append(record)

    local = [r for r in records if r.get("handler") == model_calls.HANDLER_LOCAL]
    remote = [r for r in records if r.get("handler") == model_calls.HANDLER_KIMI]
    direct = [r for r in records if r.get("routed_by") == model_calls.ROUTED_BY_DIRECT]
    quota = [r for r in records
             if r.get("outcome") == model_calls.OUTCOME_QUOTA_EXHAUSTED]
    errors = [r for r in records if r.get("outcome") == model_calls.OUTCOME_ERROR]
    timeouts = [r for r in records if r.get("outcome") == model_calls.OUTCOME_TIMEOUT]

    latencies = [r.get("latency_ms") for r in records
                 if isinstance(r.get("latency_ms"), (int, float))]
    median = statistics.median(latencies) if latencies else 0
    outliers = ([r for r in records
                 if isinstance(r.get("latency_ms"), (int, float))
                 and r["latency_ms"] > median * OUTLIER_FACTOR and r["latency_ms"] > 0]
                if median else [])

    return {
        "calls": len(records),
        "requests": len(by_request),
        "local_calls": len(local),
        "remote_calls": len(remote),
        "escalations": [r for r in remote
                        if r.get("escalation_reason") != model_calls.REASON_NOT_APPLICABLE],
        "avoidable": avoidable_escalations(records, by_request),
        "direct_calls": direct,
        "quota_events": quota,
        "errors": errors,
        "timeouts": timeouts,
        "latency_median_ms": median,
        "latency_p95_ms": _percentile(latencies, 95),
        "latency_outliers": sorted(outliers, key=lambda r: -r["latency_ms"])[:10],
        "reasons": _counts(records, "escalation_reason"),
        "callers": _counts(records, "caller_module"),
        "tokens_prompt": sum(r.get("prompt_tokens") or 0 for r in records),
        "tokens_completion": sum(r.get("completion_tokens") or 0 for r in records),
        "threshold_suggestion": suggest_threshold(records),
    }


def _counts(records: list[dict], field: str) -> list[tuple[str, int]]:
    tally: dict[str, int] = {}
    for record in records:
        tally[record.get(field) or "unknown"] = tally.get(record.get(field) or "unknown", 0) + 1
    return sorted(tally.items(), key=lambda item: -item[1])


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1))))
    return float(ordered[position])


def avoidable_escalations(records: list[dict],
                          by_request: dict[str, list[dict]] | None = None) -> list[dict]:
    """The four rules from the module docstring, applied. Each entry carries
    the summary, the stated reason, and why it looks avoidable - §5.1's three
    columns, because a list of ids is not a finding."""
    if by_request is None:
        by_request = {}
        for record in records:
            by_request.setdefault(record.get("request_id", "unknown"), []).append(record)

    permitted = set(router_config.permitted_escalations())
    threshold = router_config.confidence_threshold()
    found = []

    for record in records:
        if record.get("handler") != model_calls.HANDLER_KIMI:
            continue
        reason = record.get("escalation_reason") or model_calls.REASON_NOT_APPLICABLE
        why = None

        if record.get("routed_by") == model_calls.ROUTED_BY_DIRECT:
            why = ("it never reached the router, so local-first had no say at "
                   "all - this is a bug, not a routing decision")
        elif reason == model_calls.REASON_NOT_APPLICABLE:
            why = ("it went to the remote model with no escalation reason "
                   "recorded, which means nothing decided it should")
        elif reason not in permitted and reason != model_calls.REASON_QUOTA_RETRY:
            why = (f"{reason!r} is not one of the escalations config/router.yaml "
                   f"permits ({', '.join(sorted(permitted))})")
        elif reason == model_calls.REASON_LOW_CONFIDENCE:
            score = record.get("confidence_score")
            limit = record.get("confidence_threshold") or threshold
            if isinstance(score, (int, float)) and limit - MARGINAL_BAND <= score < limit:
                why = (f"the local answer scored {score:.2f} against a threshold of "
                       f"{limit:.2f} - within {MARGINAL_BAND:.2f}, so this is a "
                       f"judgement that could as easily have gone the other way")
        if why is None and reason not in _EXPLAINS_NO_LOCAL_CALL:
            siblings = by_request.get(record.get("request_id", "unknown"), [])
            if not any(s.get("handler") == model_calls.HANDLER_LOCAL for s in siblings):
                why = ("no local call was recorded for this request, and the "
                       f"reason given ({reason}) does not say the local tier "
                       "was unable to serve it")

        if why is not None:
            found.append({
                "request_id": record.get("request_id"),
                "summary": record.get("user_request_summary"),
                "reason": reason,
                "why_avoidable": why,
                "caller": record.get("caller_module"),
                "timestamp": record.get("timestamp"),
            })
    return found


def suggest_threshold(records: list[dict]) -> dict:
    """A suggestion and its reasoning, or an honest refusal to make one.

    Refusing is the common case and the correct one: with no confidence
    mechanism there are no scores, and a number produced from no scores would
    be the report inventing the thing it exists to measure."""
    scored = [r for r in records
              if isinstance(r.get("confidence_score"), (int, float))]
    current = router_config.confidence_threshold()

    if not scored:
        return {
            "suggested": None,
            "current": current,
            "reasoning": (
                "No call carried a confidence score, so there is nothing to "
                "suggest from. That is not a quiet night: the confidence "
                f"mechanism is `{confidence.mechanism()}` - nothing on this "
                "system scores a local answer (docs/CONFIDENCE.md). Until "
                "something does, the threshold in config/router.yaml is a "
                "configured number that never fires, and adjusting it would "
                "change nothing."),
        }

    escalated = [r for r in scored
                 if r.get("escalation_reason") == model_calls.REASON_LOW_CONFIDENCE]
    if not escalated:
        return {
            "suggested": None, "current": current,
            "reasoning": (f"{len(scored)} calls carried a score and none escalated "
                          f"for low confidence. Nothing in the data argues for "
                          f"moving the threshold."),
        }

    marginal = [r for r in escalated
                if current - MARGINAL_BAND <= r["confidence_score"] < current]
    share = len(marginal) / len(escalated)
    if share < 0.3:
        return {
            "suggested": None, "current": current,
            "reasoning": (
                f"{len(marginal)} of {len(escalated)} low-confidence escalations "
                f"({share:.0%}) were within {MARGINAL_BAND:.2f} of the threshold. "
                f"Below the 30% that would suggest the threshold is set too high, "
                f"so the escalations look like genuine ones."),
        }

    floor = round(min(r["confidence_score"] for r in marginal) - 0.01, 2)
    return {
        "suggested": max(0.0, floor),
        "current": current,
        "reasoning": (
            f"{len(marginal)} of {len(escalated)} low-confidence escalations "
            f"({share:.0%}) scored within {MARGINAL_BAND:.2f} of the threshold, "
            f"which is the shape of a threshold set slightly too high - each of "
            f"those was a paid remote call for an answer that was nearly kept. "
            f"Lowering to {max(0.0, floor):.2f} would have kept them local. "
            f"SUGGESTION ONLY: config/router.yaml is edited by Krish, never by "
            f"this report."),
    }


def _unavoidable_note(analysis: dict) -> list[str]:
    """The paragraph that stops a zero reading as good news."""
    reasons = dict(analysis["reasons"])
    if not analysis["escalations"]:
        return []
    if reasons.get(model_calls.REASON_LOCAL_ERROR, 0) < len(analysis["escalations"]):
        return []
    return [
        "> **Read the zero above carefully.** Every escalation in this window "
        "was recorded as `local_error`, which on this machine means there is no "
        "local model to attempt anything - `app/local_ai.NoLocalModelsService` "
        "reports zero models and the router's local tier is `None`. So none of "
        "these escalations was avoidable *by the router*, and all of them were "
        "avoidable by installing a local runtime (TQ-57). A clean avoidable-"
        "escalation count on a system sending 100% of its traffic to a paid API "
        "is not a clean bill of health.",
        "",
    ]


# --- the reports --------------------------------------------------------------


def nightly(day: datetime | None = None, directory: Path | None = None) -> Path:
    """§5.1's report for the 24 hours ending at `day` (default: now)."""
    end = day or datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    records = model_calls.read_records(since=start, until=end)
    analysis = analyse(records)
    lines = _render(analysis, records, start, end,
                    title=f"Self-diagnosis - {end.date().isoformat()}",
                    window="the previous 24 hours")
    return _write(directory, f"self_diagnosis_{end.date().isoformat()}.md", lines)


def weekly(day: datetime | None = None, directory: Path | None = None) -> Path:
    """§5.2's roll-up, with the day-by-day trend the nightly cannot show."""
    end = day or datetime.now(timezone.utc)
    days = router_config.weekly_days()
    start = end - timedelta(days=days)
    records = model_calls.read_records(since=start, until=end)
    analysis = analyse(records)

    lines = _render(analysis, records, start, end,
                    title=f"Self-diagnosis, week ending {end.date().isoformat()}",
                    window=f"the previous {days} days")

    lines += ["## Trend across the week", "",
              "| Day | Calls | Local | Remote | Errors | Quota | Direct |",
              "|---|---|---|---|---|---|---|"]
    for offset in range(days - 1, -1, -1):
        day_end = end - timedelta(days=offset)
        day_start = day_end - timedelta(days=1)
        slice_ = [r for r in records
                  if day_start.isoformat() <= r.get("timestamp", "") < day_end.isoformat()]
        day_analysis = analyse(slice_)
        lines.append(
            f"| {day_end.date().isoformat()} | {day_analysis['calls']} | "
            f"{day_analysis['local_calls']} | {day_analysis['remote_calls']} | "
            f"{len(day_analysis['errors'])} | {len(day_analysis['quota_events'])} | "
            f"{len(day_analysis['direct_calls'])} |")
    lines.append("")

    week = end.isocalendar()
    return _write(directory, f"self_diagnosis_weekly_{week[0]}-W{week[1]:02d}.md", lines)


def _render(analysis: dict, records: list[dict], start: datetime, end: datetime,
            *, title: str, window: str) -> list[str]:
    total = analysis["calls"]
    local_share = (analysis["local_calls"] / total * 100) if total else 0.0
    remote_share = (analysis["remote_calls"] / total * 100) if total else 0.0

    lines = [
        f"# {title}",
        "",
        f"Covering {window}: `{start.isoformat()}` to `{end.isoformat()}`.",
        f"Read from `{model_calls.log_path()}`.",
        "",
        "## Traffic",
        "",
        "| | Count | Share |",
        "|---|---|---|",
        f"| Requests | {analysis['requests']} | |",
        f"| Model calls | {total} | |",
        f"| Handled locally | {analysis['local_calls']} | {local_share:.1f}% |",
        f"| Escalated to the remote model | {analysis['remote_calls']} | {remote_share:.1f}% |",
        "",
    ]
    if not total:
        lines += [
            "No model call was recorded in this window. That is either a quiet "
            "period or an instrumentation path that stopped writing - "
            "`logs/model_calls.jsonl` is the file to check. An empty report is "
            "not evidence of a well-behaved router.",
            "",
        ]
        return lines

    lines += [f"Prompt tokens reported: {analysis['tokens_prompt']}. "
              f"Completion tokens reported: {analysis['tokens_completion']}. "
              f"(Operator figures. Nothing in this paragraph is ever said to a "
              f"user - see `app/user_messages.py`.)", ""]

    # --- direct calls, loudly -------------------------------------------------
    lines += ["## Calls that skipped the router", ""]
    if not analysis["direct_calls"]:
        lines += ["None. Every model call in this window went through "
                  "`app/model_routing.LocalFirstRouter`.", ""]
    else:
        lines += [
            f"### {len(analysis['direct_calls'])} CALL(S) DID NOT GO THROUGH THE ROUTER",
            "",
            "These are bugs. A call that skipped the router skipped local-first, "
            "the escalation rules and the quota fallback along with it.",
            "",
            "| When | Caller | Outcome | Request |", "|---|---|---|---|",
        ]
        for record in analysis["direct_calls"][:25]:
            lines.append(f"| {record.get('timestamp')} | `{record.get('caller_module')}` "
                         f"| {record.get('outcome')} | {_cell(record.get('user_request_summary'))} |")
        lines.append("")

    # --- avoidable escalations ------------------------------------------------
    lines += ["## Avoidable escalations", ""]
    if not analysis["avoidable"]:
        lines += [f"None of the {len(analysis['escalations'])} escalation(s) in "
                  f"this window looks avoidable on the recorded evidence.", ""]
        lines += _unavoidable_note(analysis)
    else:
        lines += [f"{len(analysis['avoidable'])} of {len(analysis['escalations'])} "
                  f"escalation(s) could plausibly have stayed local.", "",
                  "| Request | Stated reason | Why it looks avoidable |",
                  "|---|---|---|"]
        for entry in analysis["avoidable"][:25]:
            lines.append(f"| {_cell(entry['summary']) or '*(no user text)*'} | "
                         f"`{entry['reason']}` | {_cell(entry['why_avoidable'])} |")
        lines.append("")

    # --- quota ---------------------------------------------------------------
    lines += ["## Exhausted capacity", ""]
    if not analysis["quota_events"]:
        lines += ["The remote model did not report exhausted capacity in this "
                  "window.", ""]
    else:
        queue = retry_queue.summary(since=start)
        lines += [
            f"{len(analysis['quota_events'])} call(s) were refused for capacity.",
            "",
            "**What the user saw:** the assistant's own sentence and nothing "
            "else - either the local model's best attempt, or "
            f"\"{_cell(_capacity_sentence())}\". No user-facing string in this "
            "system mentions the vendor's accounting; "
            "`tests/test_user_facing_language.py` is what keeps that true.",
            "",
            f"**Queued for retry:** {queue['queued']} waiting, "
            f"{queue['retried']} retried, {queue['abandoned']} abandoned.",
            "",
        ]

    # --- failures ------------------------------------------------------------
    lines += ["## Errors, timeouts and latency", "",
              f"- Errors: {len(analysis['errors'])}",
              f"- Timeouts: {len(analysis['timeouts'])}",
              f"- Median latency: {analysis['latency_median_ms']:.0f} ms",
              f"- 95th percentile: {analysis['latency_p95_ms']:.0f} ms",
              f"- Outliers (over {OUTLIER_FACTOR:.0f}x the median): "
              f"{len(analysis['latency_outliers'])}",
              ""]
    if analysis["latency_outliers"]:
        lines += ["| When | Handler | Latency | Caller |", "|---|---|---|---|"]
        for record in analysis["latency_outliers"]:
            lines.append(f"| {record.get('timestamp')} | {record.get('handler')} | "
                         f"{record.get('latency_ms')} ms | `{record.get('caller_module')}` |")
        lines.append("")
    if analysis["errors"]:
        lines += ["Most recent error details (operator-facing):", ""]
        for record in analysis["errors"][-5:]:
            lines.append(f"- `{record.get('timestamp')}` {record.get('handler')}: "
                         f"{_cell(record.get('error_detail'))}")
        lines.append("")

    # --- reasons and callers --------------------------------------------------
    lines += ["## Why calls escalated", "", "| Reason | Calls |", "|---|---|"]
    for reason, count in analysis["reasons"]:
        lines.append(f"| `{reason}` | {count} |")
    lines += ["", "## Who asked", "", "| Caller | Calls |", "|---|---|"]
    for caller, count in analysis["callers"][:15]:
        lines.append(f"| `{caller}` | {count} |")
    lines.append("")

    # --- the suggestion -------------------------------------------------------
    suggestion = analysis["threshold_suggestion"]
    lines += ["## Threshold", "",
              f"Current: **{suggestion['current']:.2f}** "
              f"(`config/router.yaml`, mechanism: `{confidence.mechanism()}`).", ""]
    if suggestion["suggested"] is None:
        lines += [f"**No adjustment suggested.** {suggestion['reasoning']}", ""]
    else:
        lines += [f"**Suggested: {suggestion['suggested']:.2f}** - "
                  f"{suggestion['reasoning']}", ""]
    lines += ["Jarvis does not tune his own threshold. This section is a "
              "suggestion to Krish and the file is edited by hand.", ""]

    return lines


def _capacity_sentence() -> str:
    from app import user_messages

    return user_messages.MESSAGES[user_messages.CATEGORY_CAPACITY]


def _cell(text) -> str:
    return (str(text) if text is not None else "").replace(
        "|", "\\|").replace("\n", " ").strip()


def _write(directory: Path | None, name: str, lines: list[str]) -> Path:
    target = directory or reports_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


# --- the nightly job ----------------------------------------------------------


def due(now: datetime | None = None, last_run: datetime | None = None) -> bool:
    """Whether the nightly report should run.

    Hour-based rather than cron-based because this runs inside whatever process
    happens to be up - the Gateway, the Controller, a scheduled script - and a
    scheduler that assumes it is running is a scheduler that silently stops on
    a machine that was asleep at 03:00. `last_run` is passed in by the caller
    that knows, and a report already written today is not written twice."""
    moment = now or datetime.now()
    if moment.hour < router_config.self_diagnosis_hour():
        return False
    if last_run is not None and last_run.date() >= moment.date():
        return False
    return True


def run_if_due(now: datetime | None = None, directory: Path | None = None) -> list[Path]:
    """Write whatever is due: the nightly always, the weekly on its weekday.

    Idempotent through the filesystem - a report for a date that already exists
    is not rewritten - so a caller that invokes this every hour gets one report
    a day without having to remember anything."""
    moment = now or datetime.now(timezone.utc)
    target = directory or reports_dir()
    written = []

    nightly_path = target / f"self_diagnosis_{moment.date().isoformat()}.md"
    if not nightly_path.exists() and due(moment):
        written.append(nightly(moment, target))

    if moment.weekday() == router_config.weekly_weekday():
        week = moment.isocalendar()
        weekly_path = target / f"self_diagnosis_weekly_{week[0]}-W{week[1]:02d}.md"
        if not weekly_path.exists() and due(moment):
            written.append(weekly(moment, target))

    month = moment.strftime("%Y-%m")
    audit_path = target / f"skills_audit_{month}.md"
    if moment.day == 1 and not audit_path.exists() and due(moment):
        written.append(capability_gaps.monthly_report(month, target))

    # Close out requests that have had their attempts. Done here rather than
    # in the queue itself because something has to run on a clock for a queue
    # to have a lifecycle at all, and this is the thing that does. An entry
    # left `queued` forever would make the brief's "3 requests waiting" a
    # number that only ever grows.
    retry_queue.abandon_exhausted()

    return written


# --- what reaches the morning brief -------------------------------------------


def brief_items(since: datetime | None = None, now: datetime | None = None) -> list[dict]:
    """The two or three sentences from last night that Krish should hear.

    §4.2.4 and §5.2: *"Notify Krish through the normal brief, not
    mid-conversation."* This is the whole of that - the router says nothing to
    him while he is talking to it, and says this at the start of the day.

    Deliberately short. The brief has a twelve-item ceiling for a reason, and
    a self-report that filled it would have pushed out the organization it is
    supposed to be an aside to. Anything longer lives in the file."""
    end = now or datetime.now(timezone.utc)
    start = since or (end - timedelta(hours=24))
    records = model_calls.read_records(since=start, until=end)
    if not records:
        return []

    analysis = analyse(records)
    items = []

    if analysis["direct_calls"]:
        callers = sorted({r.get("caller_module") for r in analysis["direct_calls"]})
        items.append({
            "category": "needs_attention",
            "text": (f"{len(analysis['direct_calls'])} model call(s) bypassed the "
                     f"router in the last day, from {', '.join(callers[:3])}. "
                     f"That is a bug in the routing path."),
            "view": "alerts", "focus": "model-routing",
            "at": analysis["direct_calls"][-1].get("timestamp"),
            "count": len(analysis["direct_calls"]),
        })

    if analysis["quota_events"]:
        queue = retry_queue.summary(since=start)
        items.append({
            "category": "needs_attention",
            "text": (f"The remote model ran out of capacity {len(analysis['quota_events'])} "
                     f"time(s) yesterday. {queue['queued']} request(s) are queued to "
                     f"retry. You were not told about it at the time, by design."),
            "view": "alerts", "focus": "model-routing",
            "at": analysis["quota_events"][-1].get("timestamp"),
            "count": len(analysis["quota_events"]),
        })

    if analysis["avoidable"]:
        items.append({
            "category": "needs_attention",
            "text": (f"{len(analysis['avoidable'])} of {len(analysis['escalations'])} "
                     f"escalations yesterday look like they could have stayed local. "
                     f"The nightly self-diagnosis has each one."),
            "view": "alerts", "focus": "model-routing",
            "at": analysis["avoidable"][-1].get("timestamp"),
            "count": len(analysis["avoidable"]),
        })

    return items


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - a script
    import argparse

    parser = argparse.ArgumentParser(description="Jarvis's report on himself.")
    parser.add_argument("--nightly", action="store_true")
    parser.add_argument("--weekly", action="store_true")
    parser.add_argument("--monthly", action="store_true", help="the skills audit")
    parser.add_argument("--if-due", action="store_true",
                        help="write whatever the configured schedule says is due")
    arguments = parser.parse_args(argv)

    written: list[Path] = []
    if arguments.if_due or not any(
            (arguments.nightly, arguments.weekly, arguments.monthly)):
        written += run_if_due()
    if arguments.nightly:
        written.append(nightly())
    if arguments.weekly:
        written.append(weekly())
    if arguments.monthly:
        written.append(capability_gaps.monthly_report())

    for path in written:
        print(f"wrote {path}")
    if not written:
        print("nothing was due")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
