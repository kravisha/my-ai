"""What a learned skill is: a recipe, and the fixed interpreter that runs it.

A `Recipe` is an ordered list of `Step`s over a closed set of primitives. It is
data — it serialises to JSON, diffs in a review, versions, and reverts — and it
executes deterministically with no model call at all. That is what makes a
learned skill satisfy Document 2 §3's *"reusable deterministic capability"* and
§6's *"works without an unnecessary external LLM/API dependency"* in the same
object.

## Why primitives are closed, and what happens when one is missing

`OPS` and `TRANSFORMS` below are the vocabulary. Jarvis composes them; it cannot
add one. The reasoning is in `app/learning/__init__.py` and it comes down to
this: a learning engine able to extend its own primitives is a learning engine
able to do anything, and `app/initiative.HARM_WIDENS_ITS_OWN_AUTHORITY` refuses
that at every boldness setting.

So `RecipeError` on an unknown op is not a gap — it is the designed outcome, and
the engine's response is a boundary proposal naming the primitive and what it
would cost. The vocabulary grows when Krish agrees it should.

## Composing these is real work, which is the point

The first exercise maps network connections to owning processes. Doing it with
these primitives requires discovering that `/proc/net/tcp` skips a header row,
that its addresses are **little-endian** hex (so `0100007F` is `127.0.0.1` and
not `1.0.0.127`), that the state column is a hex enum rather than a name, that
the join key is a socket inode found by reading thousands of `/proc/*/fd`
symlinks, and that the process name is a separate per-row file read. Every one
of those is discovered by being wrong first, which is what
`app/learning/practice.py` records.

## Everything a step does is traced

`Result.trace` holds one entry per step with the row count in and out. That is
not logging for its own sake: `practice.diagnose` reads it, and the failure it
most often identifies is *a step that silently produced zero rows*, which is
invisible in a final answer that is merely empty.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# --- transforms `derive` may apply to one field -------------------------------

TRANSFORMS = (
    "hex_int",        # "A23D" -> 41533
    "hex_ipv4",       # "0100007F" -> "127.0.0.1"  (little-endian, as /proc writes it)
    "lookup",         # value -> table[value], needs `table`, optional `default`
    "regex_group",    # first capture group of `pattern`
    "split_index",    # split on `sep`, take `index`
    "path_segment",   # "/proc/417/fd/3" index 1 -> "417"
    "basename",
    "strip",
    "lower",
    "upper",
    "to_int",
    "template",       # "{a}:{b}" over the row's own fields
)

# --- the steps a recipe may contain ------------------------------------------

OPS = (
    # acquisition - every one goes through the sandbox's allow-lists
    "read",           # {path} -> text
    "glob",           # {pattern} -> list[str]
    "read_links",     # {from} -> rows {path, target}
    "read_each",      # {from, path_template, into_field} -> rows + one file's text
    "run",            # {argv} -> text
    # parsing
    "lines",          # {from, skip, drop_empty} -> list[str]
    "fields",         # {from, names, sep, maxsplit} -> rows
    "regex_rows",     # {from, pattern, names} -> rows
    "parse_json",     # {from} -> object
    # shaping
    "derive",         # {from, field, using, into_field, ...}
    "filter",         # {from, field, op, value}
    "join",           # {left, right, left_on, right_on, bring}
    "select",         # {from, fields}
    "sort",           # {from, by, descending}
    "limit",          # {from, n}
    "unique",         # {from, by}
    "count",          # {from} -> int
)

FILTER_OPS = ("eq", "ne", "in", "not_in", "gt", "lt", "ge", "le",
              "contains", "startswith", "endswith", "matches", "truthy")


class RecipeError(ValueError):
    """A recipe that cannot be run, or a step that failed.

    One class for both, deliberately: to a learner they are the same event -
    *the attempt did not work and here is the reason* - and
    `practice.diagnose` classifies them apart by reading the message and the
    trace rather than by catching two types."""


@dataclass(frozen=True)
class Step:
    """One operation. `into` names the binding its result is stored under.

    `note` is carried because a recipe is read by a person during review, and a
    step that says *"addresses here are little-endian, which is why hex_ipv4 and
    not hex_int"* is the difference between a reviewable artifact and a wall of
    JSON. The engine fills it with what it learned at that step."""

    op: str
    into: str
    args: dict = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise RecipeError(
                f"{self.op!r} is not one of the {len(OPS)} primitives a recipe may "
                f"use ({', '.join(OPS)}). The vocabulary is fixed in "
                f"app/learning/recipe.py and cannot be extended from a recipe - if "
                f"a skill genuinely needs a new primitive, that is a boundary "
                f"proposal naming it and what it would cost.")
        if not (self.into or "").strip():
            raise RecipeError(f"step {self.op!r} must name a binding to store into")

    def to_dict(self) -> dict:
        return {"op": self.op, "into": self.into, "args": self.args, "note": self.note}

    @staticmethod
    def from_dict(data: dict) -> "Step":
        return Step(op=data["op"], into=data["into"],
                    args=dict(data.get("args") or {}), note=data.get("note", ""))


@dataclass(frozen=True)
class Recipe:
    """A skill, as data.

    `answer` names the binding that is the skill's output, so a recipe can hold
    intermediate work without a convention about which step is the last one that
    matters. `needs_commands` is declared rather than inferred so the decision to
    open a command-capable sandbox is taken once, visibly, by reading the recipe
    rather than by discovering a `run` step at execution time."""

    name: str
    version: int
    summary: str
    steps: tuple[Step, ...]
    answer: str
    needs_commands: bool = False
    inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.steps:
            raise RecipeError(f"{self.name}: a recipe with no steps does nothing")
        produced = {name for name in self.inputs}
        for position, step in enumerate(self.steps):
            for key in ("from", "left", "right"):
                reference = step.args.get(key)
                if isinstance(reference, str) and reference not in produced:
                    raise RecipeError(
                        f"{self.name} step {position} ({step.op}) reads binding "
                        f"{reference!r}, which nothing before it produced. Known "
                        f"here: {sorted(produced) or 'nothing'}.")
            produced.add(step.into)
        if self.answer not in produced:
            raise RecipeError(
                f"{self.name}: answer {self.answer!r} is not produced by any step")
        declared_run = any(step.op == "run" for step in self.steps)
        if declared_run and not self.needs_commands:
            raise RecipeError(
                f"{self.name}: has a `run` step but does not declare "
                f"needs_commands. A recipe must say it wants a subprocess before "
                f"it gets one.")

    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version, "summary": self.summary,
                "answer": self.answer, "needs_commands": self.needs_commands,
                "inputs": list(self.inputs),
                "steps": [step.to_dict() for step in self.steps]}

    @staticmethod
    def from_dict(data: dict) -> "Recipe":
        return Recipe(
            name=data["name"], version=int(data.get("version", 1)),
            summary=data.get("summary", ""), answer=data["answer"],
            needs_commands=bool(data.get("needs_commands", False)),
            inputs=tuple(data.get("inputs") or ()),
            steps=tuple(Step.from_dict(item) for item in data["steps"]))

    def as_plain_language(self) -> list[str]:
        """The recipe as numbered sentences, for Document 2 §11.

        A person asking "how does this skill work" should not be handed JSON.
        Generated from the steps rather than written alongside them, so it cannot
        drift from what actually runs."""
        lines = [f"{self.name} v{self.version} - {self.summary}"]
        for position, step in enumerate(self.steps, start=1):
            detail = _describe_step(step)
            note = f"  ({step.note})" if step.note else ""
            lines.append(f"{position}. {detail}{note}")
        lines.append(f"The answer is `{self.answer}`.")
        return lines


def _describe_step(step: str) -> str:
    args = step.args
    op = step.op
    if op == "read":
        return f"read the file {args.get('path')}"
    if op == "glob":
        return f"list the paths matching {args.get('pattern')}"
    if op == "read_links":
        return f"follow every symlink in `{args.get('from')}` to see what it points at"
    if op == "read_each":
        return (f"for each row in `{args.get('from')}`, read "
                f"{args.get('path_template')} into `{args.get('into_field')}`")
    if op == "run":
        return f"run the command {' '.join(map(str, args.get('argv') or []))}"
    if op == "lines":
        skip = args.get("skip") or 0
        return (f"split `{args.get('from')}` into lines"
                + (f", skipping the first {skip}" if skip else ""))
    if op == "fields":
        return (f"split each line of `{args.get('from')}` into the columns "
                f"{', '.join(args.get('names') or [])}")
    if op == "regex_rows":
        return f"match `{args.get('from')}` against {args.get('pattern')!r}"
    if op == "parse_json":
        return f"parse `{args.get('from')}` as JSON"
    if op == "derive":
        return (f"turn `{args.get('field')}` into `{args.get('into_field')}` "
                f"using {args.get('using')}")
    if op == "filter":
        return (f"keep rows of `{args.get('from')}` where {args.get('field')} "
                f"{args.get('op')} {args.get('value')!r}")
    if op == "join":
        return (f"join `{args.get('left')}` to `{args.get('right')}` on "
                f"{args.get('left_on')} = {args.get('right_on')}")
    if op == "select":
        return f"keep only the columns {', '.join(args.get('fields') or [])}"
    if op == "sort":
        return f"sort by {args.get('by')}" + (" descending" if args.get("descending") else "")
    if op == "limit":
        return f"keep the first {args.get('n')}"
    if op == "unique":
        return f"remove duplicates by {args.get('by')}"
    if op == "count":
        return f"count the rows in `{args.get('from')}`"
    return op  # pragma: no cover - OPS is closed and checked in Step


@dataclass
class Result:
    """What running a recipe produced, plus enough to diagnose it if wrong."""

    answer: object = None
    bindings: dict = field(default_factory=dict)
    trace: list = field(default_factory=list)
    failed_step: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "answer_rows": len(self.answer) if isinstance(self.answer, list) else None,
            "failed_step": self.failed_step,
            "error": self.error,
            "trace": self.trace,
        }


# --- the interpreter ----------------------------------------------------------


def run(recipe: Recipe, sandbox, inputs: dict | None = None) -> Result:
    """Execute a recipe. Never raises; a failure is a `Result` with an error.

    Never raising is deliberate. This is called from a practice loop whose job is
    to *learn from* failures, and an exception would make the caller responsible
    for turning it back into evidence. The trace up to the failing step is the
    most valuable part of a failed attempt and it survives in the Result."""
    bindings = dict(inputs or {})
    result = Result(bindings=bindings)

    for position, step in enumerate(recipe.steps):
        before = _size(bindings.get(step.args.get("from")))
        try:
            value = _apply(step, bindings, sandbox)
        except RecipeError as bad:
            result.failed_step = position
            result.error = str(bad)
            result.trace.append({"step": position, "op": step.op, "ok": False,
                                 "error": str(bad)})
            return result
        except Exception as bad:  # noqa: BLE001 - any primitive failure is evidence
            result.failed_step = position
            result.error = f"{type(bad).__name__}: {bad}"
            result.trace.append({"step": position, "op": step.op, "ok": False,
                                 "error": result.error})
            return result

        bindings[step.into] = value
        result.trace.append({"step": position, "op": step.op, "into": step.into,
                             "ok": True, "rows_in": before, "rows_out": _size(value)})

    result.answer = bindings.get(recipe.answer)
    return result


def _size(value) -> int | None:
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, str):
        return value.count("\n") + 1 if value else 0
    return None


def _rows(bindings: dict, key: str) -> list:
    value = bindings.get(key)
    if not isinstance(value, list):
        raise RecipeError(f"binding {key!r} is {type(value).__name__}, not rows")
    return value


def _apply(step: Step, bindings: dict, sandbox):
    op, args = step.op, step.args

    if op == "read":
        return sandbox.read_file(str(args["path"]))

    if op == "glob":
        return sandbox.glob(str(args["pattern"]))

    if op == "read_links":
        out = []
        for path in _rows(bindings, args["from"]):
            target = sandbox.read_link(str(path))
            if target is not None:
                out.append({"path": str(path), "target": target})
        return out

    if op == "read_each":
        template, into_field = str(args["path_template"]), str(args["into_field"])
        out = []
        for row in _rows(bindings, args["from"]):
            try:
                path = template.format(**row)
            except (KeyError, IndexError) as bad:
                raise RecipeError(
                    f"path template {template!r} needs a field the row does not "
                    f"have: {bad}. Row keys: {sorted(row)}") from bad
            try:
                text = sandbox.read_file(path)
            except Exception:  # noqa: BLE001 - a vanished process is normal here
                if args.get("skip_missing", True):
                    continue
                raise
            out.append({**row, into_field: text.strip()})
        return out

    if op == "run":
        return sandbox.run(list(args["argv"]))

    if op == "lines":
        text = bindings.get(args["from"])
        if not isinstance(text, str):
            raise RecipeError(f"binding {args['from']!r} is not text")
        found = text.splitlines()[int(args.get("skip") or 0):]
        if args.get("drop_empty", True):
            found = [line for line in found if line.strip()]
        return found

    if op == "fields":
        names = list(args["names"])
        separator = args.get("sep")
        out = []
        for line in _rows(bindings, args["from"]):
            parts = (str(line).split() if separator in (None, "")
                     else str(line).split(separator))
            if len(parts) < len(names):
                if args.get("skip_short", True):
                    continue
                raise RecipeError(
                    f"a line has {len(parts)} fields and {len(names)} names were "
                    f"given: {str(line)[:120]!r}")
            out.append(dict(zip(names, parts[:len(names)])))
        return out

    if op == "regex_rows":
        pattern = re.compile(str(args["pattern"]))
        names = list(args.get("names") or [])
        source = bindings.get(args["from"])
        candidates = source.splitlines() if isinstance(source, str) else _rows(
            bindings, args["from"])
        out = []
        for line in candidates:
            match = pattern.search(str(line))
            if match is None:
                continue
            groups = match.groups()
            out.append(dict(zip(names, groups)) if names
                       else {"match": match.group(0)})
        return out

    if op == "parse_json":
        text = bindings.get(args["from"])
        try:
            return json.loads(text)
        except (TypeError, ValueError) as bad:
            raise RecipeError(f"{args['from']!r} is not JSON: {bad}") from bad

    if op == "derive":
        return [_derive(row, args) for row in _rows(bindings, args["from"])]

    if op == "filter":
        return [row for row in _rows(bindings, args["from"]) if _keep(row, args)]

    if op == "join":
        right_on = str(args["right_on"])
        bring = list(args.get("bring") or [])
        index: dict = {}
        for row in _rows(bindings, args["right"]):
            index.setdefault(str(row.get(right_on)), row)
        left_on = str(args["left_on"])
        out = []
        for row in _rows(bindings, args["left"]):
            match = index.get(str(row.get(left_on)))
            if match is None:
                if args.get("inner", True):
                    continue
                out.append(dict(row))
                continue
            extra = {name: match.get(name) for name in bring} if bring else {
                key: value for key, value in match.items() if key not in row}
            out.append({**row, **extra})
        return out

    if op == "select":
        fields = list(args["fields"])
        return [{name: row.get(name) for name in fields}
                for row in _rows(bindings, args["from"])]

    if op == "sort":
        by = str(args["by"])
        return sorted(_rows(bindings, args["from"]),
                      key=lambda row: _sortable(row.get(by)),
                      reverse=bool(args.get("descending")))

    if op == "limit":
        return _rows(bindings, args["from"])[:int(args["n"])]

    if op == "unique":
        by = str(args["by"])
        seen, out = set(), []
        for row in _rows(bindings, args["from"]):
            key = str(row.get(by))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    if op == "count":
        return len(_rows(bindings, args["from"]))

    raise RecipeError(f"no implementation for {op!r}")  # pragma: no cover


def _sortable(value):
    """Sort key that does not raise on mixed types.

    A recipe mid-learning has fields that are sometimes numbers and sometimes
    the strings they were parsed from, and a `TypeError` there would report
    "cannot compare str and int" where the real finding is "a derive step did
    not run"."""
    if isinstance(value, bool):
        return (1, float(value), "")
    if isinstance(value, (int, float)):
        return (1, float(value), "")
    return (2, 0.0, str(value))


def _derive(row: dict, args: dict) -> dict:
    using = str(args["using"])
    if using not in TRANSFORMS:
        raise RecipeError(
            f"{using!r} is not one of the transforms a derive step may use "
            f"({', '.join(TRANSFORMS)}).")
    into_field = str(args.get("into_field") or args["field"])

    if using == "template":
        try:
            return {**row, into_field: str(args["format"]).format(**row)}
        except KeyError as bad:
            raise RecipeError(f"template needs field {bad} which the row lacks") from bad

    raw = row.get(str(args["field"]))
    if raw is None:
        if args.get("skip_missing", True):
            return dict(row)
        raise RecipeError(f"row has no field {args['field']!r}: keys {sorted(row)}")
    text = str(raw)

    if using == "hex_int":
        try:
            value = int(text, 16)
        except ValueError as bad:
            raise RecipeError(f"{text!r} is not hexadecimal") from bad
    elif using == "hex_ipv4":
        value = _hex_ipv4(text)
    elif using == "lookup":
        table = args.get("table") or {}
        if not isinstance(table, dict):
            raise RecipeError("lookup needs a `table` mapping")
        value = table.get(text, args.get("default", text))
    elif using == "regex_group":
        match = re.search(str(args["pattern"]), text)
        if match is None:
            if args.get("skip_missing", True):
                return dict(row)
            raise RecipeError(f"{args['pattern']!r} did not match {text[:80]!r}")
        value = match.group(int(args.get("group", 1)))
    elif using == "split_index":
        parts = text.split(args["sep"]) if args.get("sep") else text.split()
        index = int(args.get("index", 0))
        if index >= len(parts):
            if args.get("skip_missing", True):
                return dict(row)
            raise RecipeError(f"{text[:80]!r} has no part {index}")
        value = parts[index]
    elif using == "path_segment":
        parts = [part for part in text.split("/") if part]
        index = int(args.get("index", 0))
        if index >= len(parts):
            if args.get("skip_missing", True):
                return dict(row)
            raise RecipeError(f"{text!r} has no segment {index}")
        value = parts[index]
    elif using == "basename":
        value = text.rstrip("/").rsplit("/", 1)[-1]
    elif using == "strip":
        value = text.strip(args["chars"]) if args.get("chars") else text.strip()
    elif using == "lower":
        value = text.lower()
    elif using == "upper":
        value = text.upper()
    elif using == "to_int":
        try:
            value = int(text.strip())
        except ValueError as bad:
            if args.get("skip_missing", True):
                return dict(row)
            raise RecipeError(f"{text!r} is not an integer") from bad
    else:  # pragma: no cover - TRANSFORMS is closed and checked above
        raise RecipeError(f"no implementation for transform {using!r}")

    return {**row, into_field: value}


def _hex_ipv4(text: str) -> str:
    """`/proc/net/tcp`'s address format: four little-endian hex bytes.

    The single most instructive line in the first exercise. `0100007F` is
    `127.0.0.1`, not `1.0.0.127`, because the kernel writes the address in host
    byte order and this machine is little-endian. A recipe that used `hex_int`
    here would produce a plausible number and a wrong answer, which is precisely
    the failure Document 1 §11 means by *documentation tells you what should
    happen, testing tells you what actually happens*."""
    cleaned = text.strip()
    if len(cleaned) != 8:
        raise RecipeError(
            f"{text!r} is not four hex bytes. /proc/net/tcp writes IPv4 as "
            f"exactly 8 hex digits; an IPv6 row has 32 and needs a different "
            f"transform.")
    try:
        octets = [int(cleaned[index:index + 2], 16) for index in (6, 4, 2, 0)]
    except ValueError as bad:
        raise RecipeError(f"{text!r} is not hexadecimal") from bad
    return ".".join(str(octet) for octet in octets)


def describe_vocabulary() -> dict:
    """The primitives, for the learning plan and for `explain_how_i_learn`."""
    return {"ops": list(OPS), "transforms": list(TRANSFORMS),
            "filter_ops": list(FILTER_OPS),
            "note": ("Fixed in app/learning/recipe.py. A recipe composes these "
                     "and cannot add one; a skill needing a new primitive is a "
                     "boundary proposal.")}


def _keep(row: dict, args: dict) -> bool:
    operation = str(args["op"])
    if operation not in FILTER_OPS:
        raise RecipeError(
            f"{operation!r} is not one of the filter comparisons "
            f"({', '.join(FILTER_OPS)}).")
    value = row.get(str(args["field"]))
    wanted = args.get("value")
    if operation == "truthy":
        return bool(value)
    if value is None:
        return False
    if operation == "eq":
        return str(value) == str(wanted)
    if operation == "ne":
        return str(value) != str(wanted)
    if operation == "in":
        return str(value) in [str(item) for item in (wanted or [])]
    if operation == "not_in":
        return str(value) not in [str(item) for item in (wanted or [])]
    if operation in ("gt", "lt", "ge", "le"):
        try:
            left, right = float(value), float(wanted)
        except (TypeError, ValueError):
            left, right = str(value), str(wanted)
        return {"gt": left > right, "lt": left < right,
                "ge": left >= right, "le": left <= right}[operation]
    if operation == "contains":
        return str(wanted) in str(value)
    if operation == "startswith":
        return str(value).startswith(str(wanted))
    if operation == "endswith":
        return str(value).endswith(str(wanted))
    if operation == "matches":
        return re.search(str(wanted), str(value)) is not None
    raise RecipeError(f"no implementation for filter {operation!r}")  # pragma: no cover
