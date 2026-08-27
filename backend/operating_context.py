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
from backend.db import Database


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
        return [name for name in requires["fields"]
                if not str(submission.get(name) or "").strip()]


# Obligation kinds this system knows how to obey, each naming the code that
# obeys it. Written as a registry rather than a chain of `if`s for the reason
# `app/capability.py` gives about its own: **an obligation that claims a
# mechanism which does not exist would route work to nothing.**
UNDERSTOOD_OBLIGATIONS = {
    RequiredFields.kind: RequiredFields,
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
    return {"governed": True, "enforced": True, "fingerprint": context.fingerprint,
            "instrument": governing["id"], "unmet_fields": unmet, "complies": not unmet}
