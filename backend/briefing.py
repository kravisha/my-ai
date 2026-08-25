"""The live briefing: what the COO says when you walk in (addendum 41 §8, §9,
§16, §21, §22; TASK_QUEUE TQ-37, docs/SPEC_RECONCILIATION.md §90).

## What this is

§8 asks the COO to brief the operator continuously and gives four examples:

    "Three tasks completed while you were away."
    "The simulation team is waiting on market data."
    "Two agents are collaborating on TQ-27."
    "This item needs your approval."

This module compiles that briefing from real state. It is the presenter's
*behaviour* without its body - the animated figure stays deferred (§85
disposition 4), and none of §8's communicative value depends on it. What a
briefing needs is something true to say and a display that follows along.

## Every line is a fact or it is not said

The hard rule, and the one that shapes everything below. §8's examples are all
counts and names, which means every one of them can be wrong in a way the
operator cannot check. So:

- "while you were away" is computed from when the operator was *actually* last
  here (the workspace checkpoint, §83). With no checkpoint there is no window,
  and the briefing says so rather than inventing one - "since you were last
  here" over an unknown interval is a fabricated claim wearing a helpful phrase.
- Counts come from queries, never from estimates.
- An empty organization gets "nothing has happened", which is a briefing. §8
  does not ask for something to be found.

**One of §8's four examples is deliberately not implemented.** "This item needs
your approval" has no source: nothing in this system records that the owner's
approval is pending. The Strategic Priority Register has `blocked`, which is a
different fact and is reported as itself. Manufacturing an approval queue to
satisfy an example would be exactly the fabrication the rest of this module
exists to prevent.

## The rhythm (§16)

§16 wants a broadcast order: main story, then supporting material. So the
briefing leads with whatever is *most* true rather than with a fixed category -
attention if anything wants it, otherwise the largest thing that changed,
otherwise what is underway. A briefing that always opened with "completed"
would be a report, not a broadcast.

## The display follows the narration (§8)

Every item names the view it is about and, where there is one, the specific
thing to bring forward. That is what turns §8's "relevant panel comes into
focus" from a stylesheet into behaviour: the console already has `.card.focus`
and `.dimmed` from TQ-33, and this is what drives them.

## Failure isolation (§22)

Nothing here owns state. `compile()` is a pure read; the presenter's position in
a briefing lives in the workspace payload (declarative view state, §5.4's own
category) rather than in a store of its own. A presenter that dies loses the
operator's place in a sentence and nothing else, which is §22's requirement
stated as an implementation rather than an intention.
"""

from __future__ import annotations

from backend import chatterbox, register as strategic_register, status_events, workspace
from backend.db import Database, now_iso, parse_timestamp

# §8's four questions. A closed vocabulary, because the console renders each
# differently and an unknown category would render as nothing at all.
CATEGORY_ATTENTION = "needs_attention"
CATEGORY_COMPLETED = "completed"
CATEGORY_UNDERWAY = "underway"
CATEGORY_BLOCKED = "blocked"
CATEGORIES = (CATEGORY_ATTENTION, CATEGORY_COMPLETED, CATEGORY_UNDERWAY, CATEGORY_BLOCKED)

# How many items one briefing may contain. A briefing is spoken; past a dozen
# lines it stops being a briefing and becomes the feed read aloud, which the
# operator already has a scrollable version of.
MAX_ITEMS = 12

# Statuses that mean work is happening, and work is stalled. Named here rather
# than inlined so the two lists cannot silently overlap.
_RUNNING = (status_events.STATUS_RUNNING, status_events.STATUS_STARTING)
_STALLED = (status_events.STATUS_WAITING,)


def _source(event: dict) -> str:
    return (event.get("source_agent") or event.get("source_engine")
            or event.get("source_department") or "something")


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def last_seen(conn: Database) -> str | None:
    """When the operator was actually last at the console, or None.

    The workspace checkpoint (§83) is the honest answer: it is written
    continuously while somebody is here and not at all while nobody is. None is
    a real answer and callers must handle it - a briefing that assumed a window
    would be inventing the very thing "while you were away" claims to measure."""
    state = workspace.load(conn)
    return state.get("updated_at") if state.get("restored") else None


def _away_seconds(since: str | None, now: str) -> float | None:
    if since is None:
        return None
    try:
        return (parse_timestamp(now) - parse_timestamp(since)).total_seconds()
    except Exception:  # noqa: BLE001 - an unparseable checkpoint is no window at all
        return None


def _describe_absence(seconds: float | None) -> str | None:
    """"while you were away", in units a person uses.

    None when the interval is unknown, and deliberately nothing at all for a
    very short one: telling an operator what changed in the eleven seconds they
    spent switching windows is noise dressed as attentiveness."""
    if seconds is None or seconds < 90:
        return None
    if seconds < 3600:
        return f"{_plural(int(seconds // 60), 'minute')}"
    if seconds < 86400:
        return f"{_plural(int(seconds // 3600), 'hour')}"
    return f"{_plural(int(seconds // 86400), 'day')}"


def _attention(conn: Database, since: str | None) -> list[dict]:
    """What failed. ERROR and CRITICAL only - a WARNING is worth seeing, not
    worth leading with."""
    failures = status_events.failures(conn, limit=MAX_ITEMS, after=since)
    if not failures:
        return []
    by_source: dict[str, list[dict]] = {}
    for event in failures:
        by_source.setdefault(_source(event), []).append(event)

    items = []
    for source, events in by_source.items():
        newest = events[0]
        extra = "" if len(events) == 1 else f" ({_plural(len(events), 'failure')} in total)"
        items.append({
            "category": CATEGORY_ATTENTION,
            "text": f"{source} failed: {newest['message']}{extra}.",
            "view": "alerts",
            "focus": source,
            "at": newest["timestamp"],
            "count": len(events),
        })
    return items


def _completed(conn: Database, since: str | None, absence: str | None) -> list[dict]:
    """§8's first example, and the one that needs a real window most.

    Without `since` there is nothing to say: "three tasks completed" is only
    news relative to the last time somebody looked."""
    if since is None:
        return []
    # `after` is exclusive, so the boundary is handled at the source rather than
    # compensated for here (TQ-41, §94). This used to filter `> since` in Python
    # while the sibling call in `_attention` did not, which meant a failure
    # stamped exactly at the checkpoint was re-announced on every visit and a
    # completion was not. One meaning, one place.
    done = [event for event in status_events.recent(conn, limit=200, after=since)
            if event["status"] == status_events.STATUS_COMPLETED]
    if not done:
        return []

    sources = sorted({_source(event) for event in done})
    named = ", ".join(sources[:3]) + ("" if len(sources) <= 3 else f" and {len(sources) - 3} more")
    when = f" while you were away ({absence})" if absence else ""
    return [{
        "category": CATEGORY_COMPLETED,
        "text": f"{_plural(len(done), 'thing')} completed{when}: {named}.",
        "view": "newsroom",
        "focus": sources[0] if len(sources) == 1 else None,
        "at": done[0]["timestamp"],
        "count": len(done),
    }]


def _underway(conn: Database, now) -> list[dict]:
    """What is happening right now: components reporting work, and agents
    actually talking to each other (§8's "Two agents are collaborating")."""
    items = []
    running = [event for event in status_events.current_status(conn)
               if event["status"] in _RUNNING]
    if running:
        sources = sorted({_source(event) for event in running})
        items.append({
            "category": CATEGORY_UNDERWAY,
            "text": f"{_plural(len(sources), 'component')} working: {', '.join(sources[:4])}"
                    + ("" if len(sources) <= 4 else f" and {len(sources) - 4} more") + ".",
            "view": "organization",
            "focus": sources[0] if len(sources) == 1 else None,
            "at": running[0]["timestamp"],
            "count": len(sources),
        })

    live = chatterbox.living_map(conn, now=now)
    active = [c for c in live.get("conversations", []) if c["state"] == chatterbox.STATE_ACTIVE]
    if active:
        first = active[0]
        detail = (f"{first['from']} and {first['to']}"
                  + (f" on {first['about']}" if first.get("about") else ""))
        more = "" if len(active) == 1 else f", and {_plural(len(active) - 1, 'other exchange')}"
        items.append({
            "category": CATEGORY_UNDERWAY,
            "text": f"{detail} are mid-conversation{more}.",
            "view": "chatterbox",
            "focus": first["from"],
            "at": first.get("asked_at"),
            "count": len(active),
        })
    return items


def _blocked(conn: Database, now) -> list[dict]:
    """§8's second example. Three genuinely different kinds of stuck, kept
    apart because the remedy differs: a component waiting on input, a question
    nobody answered, and a proposal the organization has filed as blocked."""
    items = []

    waiting = [event for event in status_events.current_status(conn)
               if event["status"] in _STALLED]
    for event in waiting[:3]:
        items.append({
            "category": CATEGORY_BLOCKED,
            "text": f"{_source(event)} is waiting: {event['message']}.",
            "view": "newsroom",
            "focus": _source(event),
            "at": event["timestamp"],
            "count": 1,
        })

    live = chatterbox.living_map(conn, now=now)
    silent = [c for c in live.get("conversations", []) if c["state"] == chatterbox.STATE_SILENT]
    if silent:
        first = silent[0]
        items.append({
            "category": CATEGORY_BLOCKED,
            "text": f"{_plural(len(silent), 'question')} timed out with no reply — "
                    f"{first['from']} asked {first['to']} and heard nothing.",
            "view": "chatterbox",
            "focus": first["to"],
            "at": first.get("asked_at"),
            "count": len(silent),
        })

    try:
        blocked_entries = strategic_register.list_register(conn, status="blocked")
    except Exception:  # noqa: BLE001 - a briefing must not fail on one section
        blocked_entries = []
    if blocked_entries:
        items.append({
            "category": CATEGORY_BLOCKED,
            "text": f"{_plural(len(blocked_entries), 'register entry', 'register entries')} "
                    f"blocked, including {blocked_entries[0]['title']}.",
            "view": "strategy",
            "focus": blocked_entries[0]["title"],
            "at": None,
            "count": len(blocked_entries),
        })
    return items


def _order(items: list[dict]) -> list[dict]:
    """§16's rhythm: the main story first, then supporting material.

    Deliberately not a fixed category order. Leading with "completed" every
    time would make this a report; a broadcast leads with whatever is most
    true today, which is attention when anything wants it and otherwise the
    largest thing that changed."""
    rank = {CATEGORY_ATTENTION: 0, CATEGORY_BLOCKED: 1,
            CATEGORY_COMPLETED: 2, CATEGORY_UNDERWAY: 3}
    if not any(item["category"] == CATEGORY_ATTENTION for item in items):
        # Nothing is broken, so the news is what changed. Completed leads,
        # then what is happening now, then what is stuck.
        rank = {CATEGORY_COMPLETED: 0, CATEGORY_UNDERWAY: 1, CATEGORY_BLOCKED: 2}
    return sorted(items, key=lambda item: (rank.get(item["category"], 9),
                                           -item.get("count", 0)))


def compile(conn: Database, *, since: str | None = None, now: str | None = None) -> dict:
    """The briefing, as an ordered sequence of things that are true.

    `since` defaults to the operator's last workspace checkpoint. Pass it
    explicitly to ask "what has happened since X" for some other X - the
    console does not, but a test does, and so would a scheduled digest.

    Never raises on an empty organization: "nothing has happened" is a
    briefing, and a presenter that only works when there is news is a presenter
    that fails on a quiet morning."""
    stamp = now or now_iso()
    since = last_seen(conn) if since is None else since
    absence = _describe_absence(_away_seconds(since, stamp))

    items = (_attention(conn, since) + _completed(conn, since, absence)
             + _underway(conn, stamp) + _blocked(conn, stamp))
    items = _order(items)[:MAX_ITEMS]

    return {
        "items": items,
        "since": since,
        "away": absence,
        "quiet": not items,
        "generated_at": stamp,
        # Both facts, never collapsed into one. "Nothing has happened" and "I
        # could not tell what was new" are different answers and only one of
        # them is reassuring - and an empty briefing with no window is *both*,
        # which the first version of this reported as the reassuring one alone.
        "note": " ".join(part for part in (
            ("I do not know when you were last here, so nothing below is described as new."
             if since is None else None),
            ("Nothing has happened that is worth reporting. The organization is quiet."
             if not items else None),
        ) if part) or None,
    }


def spoken(briefing: dict) -> str:
    """The briefing as one block of prose, for the voice path and for a COO
    answer that wants to open with it.

    Separate from `compile` because the console renders items one at a time
    with the display following each - the text and the choreography are the
    same briefing addressed to two different senses."""
    if briefing["quiet"]:
        return briefing["note"] or "Nothing to report."
    lines = [item["text"] for item in briefing["items"]]
    if briefing.get("note"):
        lines.insert(0, briefing["note"])
    return " ".join(lines)
