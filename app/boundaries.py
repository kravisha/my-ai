"""Constraints Jarvis has run into, and the case for moving them
(Krish, 2026-09-21).

> *"Give agent the ability to be inquisitive and willing to cross boundaries as
> long as the actions are not harmful in nature."*

## Crossing a boundary is proposing that it move, and the constitution says so

`AI-CONSTITUTION.md`, "Take risks and challenge boundaries":

> Boundaries themselves can be subjects of redesign. An agent may expose why a
> constraint prevents a useful outcome, **propose a better arrangement** and
> help establish the capabilities and authority needed to move beyond it.
> Challenging a boundary must remain a real avenue for progress in the product
> design.

That is the mechanism, already written, with nothing implementing it. Until now
a constraint produced one of two things: a sentence in one conversation that
nobody kept, or silence. Neither is a boundary being challenged; the first is a
complaint and the second is an assistant quietly narrowing itself around a limit
until nobody remembers it was a choice.

This is the third option. A constraint becomes a **dated, repeatable,
evidence-carrying argument** that Krish can act on or dismiss, and dismissing it
leaves a record too.

## What it deliberately is not

**Not a way to widen its own authority.** `app/initiative.HARMS` refuses that at
every boldness setting, and this module does not reach past it - nothing here
grants anything. It writes an argument to a file. Krish moves the boundary or he
does not. The two halves of the constitutional sentence are "propose a better
arrangement" and "help establish the capabilities and authority", and the help
is making the case well, not taking the authority.

That separation is what makes boundary-crossing safe to encourage. An agent that
can argue for more authority and an agent that can take it are different animals,
and only the first one can be told to be bold.

**Not `app/capability_gaps.py`.** They look similar and answer opposite
questions:

| | capability_gaps | boundaries |
|---|---|---|
| Written when | somebody asked for something and it failed | Jarvis judged a constraint is costing something |
| Driven by | the user | the agent |
| Ranked by | how often it was *asked for* | how often it was *hit*, and how cheap it is to try |
| Is | a tally | an argument |

They are connected in one direction: a boundary proposal that can point at a
capability gap hit seven times is a much stronger argument than the same
sentence alone, so `register()` joins them. Frequency of request is the evidence;
the proposal is the case.

## Every proposal states what it costs if it is wrong

`what_it_would_cost` is required, and a proposal without it is refused rather
than stored. The constitution again, same section: *"Leaders make the stakes
explicit, test their ideas, learn from results and take responsibility for the
effects."*

A proposal that only lists the upside is not a boundary challenge, it is a
request. The field is the difference, and making it required is the only way it
survives a hundred entries written quickly.

## It is allowed to disagree with the policy that governs it

`KIND_POLICY_GATE` exists so that `app/initiative.py`'s own refusals can be
argued with. If Jarvis is stopped from the same reversible-looking action twenty
times and each time thought it was fine, that is evidence about the policy and
it belongs somewhere Krish will see it rather than dying in twenty separate
conversations.

Building the register so it can indict its own author is not a flourish. A
constraint system with no channel for "this constraint is wrong" produces an
agent that routes around it instead, and routing around is the failure mode
worth spending a module to avoid.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import capability_gaps, model_calls

SCHEMA_VERSION = 1

BOUNDARIES_FILE_NAME = "boundaries.jsonl"

# What kind of thing is in the way. Closed, because the monthly report groups on
# it and each kind has a different person and a different cost attached.
KIND_MISSING_CAPABILITY = "missing_capability"
KIND_MISSING_TOOL = "missing_tool"
KIND_POLICY_GATE = "policy_gate"
KIND_MISSING_ACCESS = "missing_access"
KIND_DESIGN_ASSUMPTION = "design_assumption"
KINDS = (KIND_MISSING_CAPABILITY, KIND_MISSING_TOOL, KIND_POLICY_GATE,
         KIND_MISSING_ACCESS, KIND_DESIGN_ASSUMPTION)

KIND_MEANING = {
    KIND_MISSING_CAPABILITY: (
        "a capability this role does not hold (gateway/roles.py GRANTS). Moving "
        "it is Krish's decision about authority, not a build"),
    KIND_MISSING_TOOL: (
        "a tool that does not exist. Moving it is a build, and the cost is "
        "somebody's afternoon"),
    KIND_POLICY_GATE: (
        "a rule that stopped an action it permitted in principle - most often "
        "app/initiative.py. Moving it is a decision about the rule itself, and "
        "this is the channel for arguing the rule is wrong"),
    KIND_MISSING_ACCESS: (
        "a credential, a machine, or a file this system cannot reach. Moving it "
        "is usually an account and a key"),
    KIND_DESIGN_ASSUMPTION: (
        "something the system assumes that need not be true. The cheapest kind "
        "to move and the easiest to stop noticing"),
}

STATUS_OPEN = "open"
STATUS_GRANTED = "granted"
STATUS_DECLINED = "declined"
STATUSES = (STATUS_OPEN, STATUS_GRANTED, STATUS_DECLINED)

# How many times one constraint has to be hit before it leads the report and
# reaches the morning brief. Two, for the reason capability_gaps uses the same
# number: the second time is when a thing stops being an incident and starts
# being a pattern.
REPEATED = 2


class BoundaryRefused(ValueError):
    """A proposal that is not yet an argument, refused rather than stored.

    Stored-and-incomplete would be worse: the register is read as a ranked list
    of things worth doing, and an entry with no stated cost sits in that list
    looking exactly like one somebody thought through."""


def boundaries_path() -> Path:
    return model_calls.log_dir() / BOUNDARIES_FILE_NAME


def record(*, constraint: str, kind: str, what_it_prevents: str,
           what_i_would_do: str, what_it_would_cost: str,
           reversible_if_granted: bool = True,
           request_id: str | None = None) -> dict:
    """File the case for moving one constraint.

    Every field is required and each refusal below names what a proposal
    without it would look like in the report, because "be thorough" is not
    something a validator can say."""
    if kind not in KINDS:
        raise BoundaryRefused(
            f"kind={kind!r} is not one of {KINDS}. The report groups on this "
            f"and each kind goes to a different person.")
    for field, value in (("constraint", constraint),
                         ("what_it_prevents", what_it_prevents),
                         ("what_i_would_do", what_i_would_do)):
        if not (value or "").strip():
            raise BoundaryRefused(
                f"{field} is required. A boundary proposal missing it is a "
                f"complaint rather than a case, and reads in the report as one "
                f"somebody already thought through.")
    if not (what_it_would_cost or "").strip():
        raise BoundaryRefused(
            "what_it_would_cost is required. A proposal that lists only the "
            "upside is a request, not a boundary challenge - the constitution's "
            "\"leaders make the stakes explicit\" is the whole difference, and "
            "it is the first field to go when a hundred of these are written "
            "quickly.")

    entry = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id or model_calls.current_request_id() or "unknown",
        "constraint": constraint.strip(),
        "kind": kind,
        "what_it_prevents": what_it_prevents.strip(),
        "what_i_would_do": what_i_would_do.strip(),
        "what_it_would_cost": what_it_would_cost.strip(),
        "reversible_if_granted": bool(reversible_if_granted),
        "status": STATUS_OPEN,
    }
    _append(entry)
    return entry


def decide(constraint: str, status: str, note: str | None = None) -> dict:
    """Krish's answer. Recorded like the proposal, including a decline.

    A declined boundary that left no trace would be re-proposed next month by an
    assistant with no memory of having asked, which is the specific way this
    register would become noise."""
    if status not in (STATUS_GRANTED, STATUS_DECLINED):
        raise BoundaryRefused(f"status={status!r} is not one of "
                              f"{(STATUS_GRANTED, STATUS_DECLINED)}")
    entry = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "constraint": (constraint or "").strip(),
        "status": status,
        "note": note,
    }
    _append(entry)
    return entry


def _append(entry: dict) -> None:
    try:
        path = boundaries_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
    except OSError:  # pragma: no cover - a full or read-only disk
        pass


def entries(since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    path = boundaries_path()
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
        if not isinstance(entry, dict) or not entry.get("constraint"):
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


def _key(constraint: str) -> str:
    return " ".join((constraint or "").lower().split())


def register(rows: list[dict] | None = None) -> list[dict]:
    """Open boundaries, most-argued-for first, with the evidence attached.

    Ranked by how often the constraint was hit and then by whether granting it
    is reversible - **cheap-to-try first among equally-hit constraints**, which
    is the ordering that actually gets things unblocked. A month spent deciding
    the expensive one while three reversible experiments went unrun is the
    failure this sort order is against.

    A constraint whose latest entry is a decision is not listed: a declined
    boundary stays declined until somebody re-proposes it with a new argument,
    which writes a new open entry."""
    rows = entries() if rows is None else rows
    latest_status: dict[str, str] = {}
    proposals: dict[str, list[dict]] = {}
    for entry in rows:
        key = _key(entry["constraint"])
        if entry.get("status") in (STATUS_GRANTED, STATUS_DECLINED):
            latest_status[key] = entry["status"]
            continue
        latest_status[key] = STATUS_OPEN
        proposals.setdefault(key, []).append(entry)

    gap_counts = _gap_evidence()

    out = []
    for key, group in proposals.items():
        if latest_status.get(key) != STATUS_OPEN:
            continue
        newest = group[-1]
        out.append({
            # The FIRST wording, not the latest. Entries group on a normalised
            # key (lower-cased, whitespace collapsed) while the stored text is
            # whatever was typed, so showing the newest made the register
            # display a constraint whose spacing differed from the one it had
            # grouped under - harmless in a report and confusing in a test,
            # which is how it was found. First-raised is also the more useful
            # of the two: it is the wording the earlier entries are filed
            # under, and the one Krish will have seen before.
            "constraint": group[0]["constraint"],
            "kind": newest["kind"],
            "times_hit": len(group),
            "what_it_prevents": newest["what_it_prevents"],
            "what_i_would_do": newest["what_i_would_do"],
            "what_it_would_cost": newest["what_it_would_cost"],
            "reversible_if_granted": bool(newest.get("reversible_if_granted", True)),
            "first_raised": group[0].get("timestamp"),
            "last_raised": newest.get("timestamp"),
            # The join that makes a proposal an argument rather than an opinion.
            "related_requests": _related_requests(newest["constraint"],
                                                  gap_counts),
        })

    return sorted(
        out,
        key=lambda item: (-(item["times_hit"] + item["related_requests"]),
                          not item["reversible_if_granted"],
                          item["last_raised"] or ""))


def _gap_evidence() -> dict[str, int]:
    """How often each constraint also showed up as somebody asking for something.

    Matched loosely - a constraint's words appearing in what was needed - and
    loosely on purpose. This number is evidence in a report a person reads, not
    an index; a miss understates an argument and a false hit is visible to
    anybody reading the two entries side by side."""
    counts: dict[str, int] = {}
    try:
        gaps = capability_gaps.entries()
    except Exception:  # noqa: BLE001 - evidence is optional, the proposal is not
        return counts
    for gap in gaps:
        needed = _key(gap.get("what_was_needed"))
        if not needed:
            continue
        counts[needed] = counts.get(needed, 0) + 1
    return counts


def _related_requests(constraint: str, gap_counts: dict[str, int]) -> int:
    """How many recorded requests this constraint plausibly accounts for.

    Loose, as the docstring above has always said and as the code did not do: it
    was exact string equality, so a constraint worded even slightly differently
    from the gap scored zero and `related_requests` dropped out of the ranking
    key entirely - which removed the one piece of evidence that makes a proposal
    an argument rather than an opinion.

    Containment in either direction, on the normalised forms. A miss understates
    a case; a false hit is visible to anybody reading the two entries side by
    side, which is the trade the original comment described."""
    key = _key(constraint)
    if not key:
        return 0
    total = 0
    for needed, count in gap_counts.items():
        if key == needed or key in needed or needed in key:
            total += count
    return total


# --- what reaches Krish --------------------------------------------------------


def report(month: str | None = None, reports_dir: Path | None = None) -> Path:
    """`reports/boundaries_YYYY-MM.md` - the month's case for moving things."""
    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    open_items = register()
    rows = entries()

    lines = [
        f"# Boundaries worth moving - {month}",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat()} from "
        f"`{boundaries_path()}`.",
        "",
        "Constraints Jarvis ran into and made a case about. Ordered by how often "
        "each was hit, then cheapest-to-try first - a month spent deciding the "
        "expensive one while three reversible experiments went unrun is what "
        "that second key is against.",
        "",
        "Nothing here has been done. Every entry is an argument; moving a "
        "boundary is Krish's decision, and `app/initiative.py` refuses at every "
        "setting to let the assistant grant itself authority.",
        "",
    ]

    if not open_items:
        # Deliberately NOT an early return. The first version returned here,
        # so a month in which every boundary raised had been answered printed
        # "nothing open" and dropped the answers - which reads as a month
        # nobody asked for anything, the opposite of what happened. The
        # "already answered" section below runs either way.
        lines += [
            "## Nothing open",
            "",
            "No boundary was proposed this month, or every one raised has been "
            "answered. An empty register is not evidence of a system with no "
            "limits - it is worth a glance at `logs/boundaries.jsonl` to see "
            "which.",
            "",
        ]

    cheap = [item for item in open_items if item["reversible_if_granted"]]
    costly = [item for item in open_items if not item["reversible_if_granted"]]

    for title, group, preamble in (
        ("Cheap to try - granting these is reversible", cheap,
         "If one of these turns out to be a mistake, it is taken back with a "
         "line of config or a revoked grant. That is the whole reason to try "
         "them rather than deliberate over them."),
        ("Needs a real decision - granting these is not reversible", costly,
         "Each of these hands over something that cannot simply be taken back "
         "afterwards. They are listed separately so they are never skimmed with "
         "the ones above."),
    ):
        if not group:
            continue
        lines += [f"## {title}", "", preamble, ""]
        for position, item in enumerate(group, start=1):
            evidence = (f" · asked for {item['related_requests']} time(s) "
                        f"(logs/capability_gaps.jsonl)"
                        if item["related_requests"] else "")
            lines += [
                f"### {position}. {item['constraint']}",
                "",
                f"`{item['kind']}` · hit **{item['times_hit']}** time(s)"
                f"{evidence}",
                "",
                f"- **What it prevents:** {item['what_it_prevents']}",
                f"- **What I would do instead:** {item['what_i_would_do']}",
                f"- **What it costs if this is the wrong call:** "
                f"{item['what_it_would_cost']}",
                f"- **Kind:** {KIND_MEANING[item['kind']]}",
                f"- First raised {item['first_raised']}, most recently "
                f"{item['last_raised']}",
                "",
            ]

    decided = [row for row in rows
               if row.get("status") in (STATUS_GRANTED, STATUS_DECLINED)]
    if decided:
        lines += ["## Already answered", "",
                  "Kept so a declined boundary is not re-proposed next month by "
                  "an assistant with no memory of having asked.", "",
                  "| Constraint | Answer | Note |", "|---|---|---|"]
        for row in decided[-15:]:
            lines.append(f"| {_cell(row['constraint'])} | {row['status']} | "
                         f"{_cell(row.get('note'))} |")
        lines.append("")

    return _write(month, lines, reports_dir)


def brief_items(since: datetime | None = None, now: datetime | None = None) -> list[dict]:
    """The one line the morning brief gets, when a boundary keeps being hit.

    One item, not one per boundary. The brief has a twelve-item ceiling and a
    register that filled it would push out the organization it is an aside to;
    the report is where the detail lives."""
    end = now or datetime.now(timezone.utc)
    start = since or (end - timedelta(hours=24))
    recent = entries(since=start, until=end)
    if not recent:
        return []

    repeated = [item for item in register() if item["times_hit"] >= REPEATED]
    if not repeated:
        return []

    leader = repeated[0]
    others = (f" and {len(repeated) - 1} other(s)" if len(repeated) > 1 else "")
    return [{
        "category": "needs_attention",
        "text": (f"I have run into \"{leader['constraint']}\" "
                 f"{leader['times_hit']} times{others}. There is a written case "
                 f"for moving it in the boundaries report - "
                 f"{'reversible if you grant it' if leader['reversible_if_granted'] else 'not reversible, so it needs a real decision'}."),
        "view": "alerts",
        "focus": "boundaries",
        "at": leader["last_raised"],
        "count": leader["times_hit"],
    }]


def _cell(text) -> str:
    return (str(text) if text is not None else "").replace(
        "|", "\\|").replace("\n", " ").strip()


def _write(month: str, lines: list[str], reports_dir: Path | None) -> Path:
    directory = reports_dir or (model_calls.PROJECT_ROOT / "reports")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"boundaries_{month}.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def main() -> int:  # pragma: no cover - a script
    print(f"wrote {report()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
