"""What an agent is currently governed by, and what it must do about it
(TASK_QUEUE TQ-86; addendum 46 §3, §8; addendum 30 §12;
docs/SPEC_RECONCILIATION.md §125, §126).

TQ-82 built the store. **Nothing read it.** The organization could carry a
resolution, adopt an instrument, and have every agent go on behaving exactly as
its code said - which made the governed layer a filing cabinet and addendum 46's
central claim untrue here:

> §3: *"An agent may read new information, interpret it, incorporate it into its
> operating context, and modify its decisions and behavior accordingly…
> A behavioral change does not automatically imply a software change."*

This is the incorporating. An agent asks what governs it, gets a context, and
acts under it - and what it produces carries which instruments it acted under, so
*claimed to follow* and *did follow* are different things on the record.

## The thing this increment found, and it is the important part

**Code cannot obey prose.**

Addendum 46 §3 imagines an agent reading a rule and interpreting it. Interpreting
text needs something that reads text; this system has no model in the loop for
agent work, and will not until addendum 45's local intelligence lands. Writing
`if "acceptance criteria" in policy_text` would be a parser pretending to be a
reader, and it would fail silently the first time somebody phrased a policy
differently.

So an instrument carries two things: `text`, which is for people, and an optional
`requires` payload, which is the **machine-obeyable** part. The distinction is
made visible rather than hidden:

- an instrument with a `requires` this system understands is **enforced**;
- an instrument without one is **prose only** - real, in force, binding on
  whoever reads it, and *not* enforced by code. `Context.prose_only` lists them
  by name so nobody believes the machinery is checking something it is not.

That is not a workaround. It is the honest shape of data-driven behaviour in a
system whose obeying is done by code: **the data has to be structured for the
mechanism that obeys it.** When a local model can read the text, a new obligation
kind can be understood by something that interprets, and the same store serves
both.

## The rule that stops this from being decoration

**An obligation nothing understands is refused, never skipped.**

The tempting behaviour - accept the instrument, fail to recognise the obligation,
carry on - produces the worst state available: a rule that was proposed,
debated, voted through, is reported as in force, and changes nobody's behaviour.
Everyone would believe the organization had changed.

So an unknown obligation kind is refused at adoption (`governed_knowledge`), and
`Context.unmet` reports one that arrived any other way - a migration, a restore,
a future writer. `require_understood()` turns that into a refusal at the point of
work. **Silently ignoring an instrument you did not understand is the failure
that makes the whole layer ornamental**, and it is the one this module exists to
prevent.

## Evidence, not claims

A context has a `fingerprint`: the ids of the instruments it was built from.
Whatever an agent produces under it records that fingerprint, so an artifact
carries the authority it was made under.

The alternative is an agent asserting it complied, which is TQ-80's defect in a
new costume - *absence of complaint is not evidence of competence*. A fingerprint
that no longer matches what is in force is a visible fact; a claim of compliance
is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from backend import governed_knowledge as governed
from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS governed_refusals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refused_at TEXT NOT NULL,
    -- Who was refused, and what they were trying to do.
    role TEXT NOT NULL,
    subject TEXT NOT NULL,
    instrument_id INTEGER,
    -- WHICH obligations were unmet, by name. Never the values.
    --
    -- A submission's field names are the organization's own vocabulary; its
    -- field contents are whatever somebody was filing, and a register entry can
    -- carry anything. Recording names lets the organization count and diagnose
    -- its refusals; recording values would put arbitrary content in a table
    -- nobody would think to look in for it (§111's reasoning, one room along).
    unmet TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS governed_refusals_recent ON governed_refusals (refused_at);
"""

SCHEMA_VERSION = 1


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


class Ungovernable(PermissionError):
    """Work that cannot proceed because an instrument binding it is not
    understood."""


@dataclass(frozen=True)
class RequiredFields:
    """Obligation: a submission must carry these fields, non-empty.

    Addendum 46 §39's worked example is exactly this shape - *"all
    interdepartmental requests shall contain requester, objective, priority,
    deadline, dependencies, and acceptance criteria"* - which is why it is the
    first obligation kind implemented rather than a hypothetical one."""

    kind: str = "required_fields"

    @staticmethod
    def check_shape(requires: dict) -> None:
        fields = requires.get("fields")
        if not isinstance(fields, (list, tuple)) or not fields:
            raise governed.AdoptionRefused(
                "A required_fields obligation needs a non-empty 'fields' list.")
        if not all(isinstance(name, str) and name.strip() for name in fields):
            raise governed.AdoptionRefused("Every required field needs a name.")

    @staticmethod
    def unmet_by(requires: dict, submission: dict) -> list[str]:
        return [name for name in requires["fields"] if _absent(submission.get(name))]


@dataclass(frozen=True)
class MinimumCount:
    """Obligation: a field must carry at least N things.

    A different *shape* from `RequiredFields` rather than a variation on it -
    presence and sufficiency are different questions, and an organization that
    says *"no lead is filed on fewer than two pieces of evidence"* is saying the
    second one. Added with a real consumer (a discovery report's evidence) rather
    than on speculation: a registry entry with nothing that obeys it is the
    mechanism-that-does-not-exist problem `app/capability.py` names."""

    kind: str = "minimum_count"

    @staticmethod
    def check_shape(requires: dict) -> None:
        field_name = requires.get("field")
        at_least = requires.get("at_least")
        if not isinstance(field_name, str) or not field_name.strip():
            raise governed.AdoptionRefused(
                "A minimum_count obligation needs the 'field' it counts.")
        if not isinstance(at_least, int) or isinstance(at_least, bool) or at_least < 1:
            raise governed.AdoptionRefused(
                "A minimum_count obligation needs 'at_least' as a whole number above zero. "
                "A minimum of zero is not a rule.")

    @staticmethod
    def unmet_by(requires: dict, submission: dict) -> list[str]:
        value = submission.get(requires["field"])
        try:
            count = len(value)
        except TypeError:
            count = 0 if value is None else 1
        if count >= requires["at_least"]:
            return []
        return [f"{requires['field']} (has {count}, needs {requires['at_least']})"]


def _absent(value) -> bool:
    """Whether a submission is missing this field.

    `None`, whitespace, and an empty collection are missing. **A zero is not.**
    The first version of this asked whether `str(value or "").strip()` was empty,
    which was fine for the one caller it had and wrong the moment a second
    arrived: a report with `judgment_confidence=0.0` had stated its confidence,
    and would have been refused for not stating it.

    The second consumer found the first one's rule too narrow, which is the
    ordinary way a rule written against one example goes wrong."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    return False


# Obligation kinds this system knows how to obey, each naming the code that
# obeys it. Written as a registry rather than a chain of `if`s for the reason
# `app/capability.py` gives about its own: **an obligation that claims a
# mechanism which does not exist would route work to nothing.**
UNDERSTOOD_OBLIGATIONS = {
    RequiredFields.kind: RequiredFields,
    MinimumCount.kind: MinimumCount,
}


@dataclass(frozen=True)
class Context:
    """What governs this role right now.

    Frozen for the reason `OwnerContext` is (addendum 44 §9.2): it is evidence.
    Something that could be reassigned between the check and the work is not a
    record of what the work was done under."""

    role: str
    instruments: tuple = ()
    # Instruments binding this role whose obligation nothing understands. Work
    # under this context is refused rather than performed - see the module
    # docstring.
    unmet: tuple = ()
    # In force, binding, and **not enforced by code**. Named so that nobody reads
    # a green run as evidence that these were followed.
    prose_only: tuple = ()

    @property
    def fingerprint(self) -> str:
        """What this context was built from, as a stable string.

        Instrument ids rather than a hash of the text: a fingerprint a reader can
        resolve back to rows is worth more than one that only proves equality."""
        return ",".join(str(item["id"]) for item in self.instruments) or "ungoverned"

    def obligation(self, subject: str) -> dict | None:
        for item in self.instruments:
            if item["subject"] == subject and item["requires"]:
                return json.loads(item["requires"])
        return None

    def governing(self, subject: str) -> dict | None:
        for item in self.instruments:
            if item["subject"] == subject:
                return item
        return None


def for_role(conn: Database, role: str) -> Context:
    """Build the operating context for a role.

    Reads the governed layer through `binding_on`, which applies precedence per
    subject, so a context never contains an instrument that something above it
    has superseded on the same subject."""
    instruments, unmet, prose = [], [], []
    for item in governed.binding_on(conn, role):
        if not item["requires"]:
            prose.append(item)
            instruments.append(item)
            continue
        try:
            kind = json.loads(item["requires"]).get("kind")
        except (TypeError, ValueError):
            kind = None
        if kind not in UNDERSTOOD_OBLIGATIONS:
            unmet.append(item)
        else:
            instruments.append(item)
    return Context(role=role, instruments=tuple(instruments),
                   unmet=tuple(unmet), prose_only=tuple(prose))


def require_understood(context: Context) -> Context:
    """Refuse to work under a context containing something unintelligible.

    The alternative is proceeding as though unbound, which is indistinguishable
    from the instrument never having been adopted - and would mean a vote of the
    Parliament had no effect that anybody could see."""
    if context.unmet:
        raise Ungovernable(
            f"{context.role} is bound by {len(context.unmet)} instrument(s) it cannot obey: "
            f"{', '.join(str(item['id']) + ' on ' + item['subject'] for item in context.unmet)}. "
            f"Refusing the work rather than acting as if ungoverned.")
    return context


def check(conn: Database, role: str, subject: str, submission: dict) -> dict:
    """Check a submission against whatever governs `role` on `subject`.

    Returns what was checked and under what authority - a record, not a boolean,
    because *what it was checked against* is the part worth keeping."""
    context = require_understood(for_role(conn, role))
    obligation = context.obligation(subject)
    governing = context.governing(subject)
    if obligation is None:
        return {"governed": governing is not None, "enforced": False,
                "fingerprint": context.fingerprint,
                # An ungoverned subject and a prose-only one are different states
                # and are reported differently. Collapsing them would hide the
                # case where a rule exists and code is not checking it.
                "note": ("nothing governs this subject" if governing is None
                         else "governed by prose this system cannot enforce")}
    unmet = UNDERSTOOD_OBLIGATIONS[obligation["kind"]].unmet_by(obligation, submission)
    if unmet:
        # **Recorded here rather than at the call sites**, which makes `check`
        # impure and is the right trade. A check that noticed a breach and left
        # writing it down to whoever called it is how an organization ends up
        # unable to count its own refusals - and a new call site would inherit
        # the enforcement and not the record.
        record_refusal(conn, role=role, subject=subject,
                       instrument=governing["id"], unmet=unmet)
    return {"governed": True, "enforced": True, "fingerprint": context.fingerprint,
            "instrument": governing["id"], "unmet_fields": unmet, "complies": not unmet}


def record_refusal(conn: Database, *, role: str, subject: str,
                   instrument: int | None, unmet: list) -> int:
    """Write down that an instrument in force refused something.

    Until this existed the refusal was said on stdout and kept nowhere: the
    organization could not count its own refusals, no metric could assert on
    them, and no scenario could require one.

    **The case that makes it matter is not the single refusal.** It is a badly
    drafted instrument that refuses everything - which, with no record, looks
    exactly like a quiet market. Discovery goes silent, the queue stays empty,
    every property about crashes and orphans passes, and the organization reports
    excellent health while producing nothing because it forbade itself."""
    return conn.execute_returning_id(
        "INSERT INTO governed_refusals (refused_at, role, subject, instrument_id, unmet)"
        " VALUES (?, ?, ?, ?, ?)",
        (now_iso(), (role or "").strip().lower(), subject, instrument,
         json.dumps(list(unmet))))


def refusals(conn: Database, *, since: str | None = None) -> list[dict]:
    rows = conn.fetchall(
        "SELECT id, refused_at, role, subject, instrument_id, unmet FROM governed_refusals"
        + (" WHERE refused_at >= ?" if since else "") + " ORDER BY id",
        (since,) if since else ())
    for row in rows:
        row["unmet"] = json.loads(row["unmet"])
    return rows


def refusals_by_instrument(conn: Database) -> dict:
    """How many times each instrument has refused something.

    The shape a reader needs to spot the misdrafted one: a single instrument
    accounting for every refusal in the organization is a rule that forbids its
    own subject, not a workforce behaving badly."""
    return {row["instrument_id"]: row["n"] for row in conn.fetchall(
        "SELECT instrument_id, COUNT(*) AS n FROM governed_refusals"
        " GROUP BY instrument_id ORDER BY n DESC")}
