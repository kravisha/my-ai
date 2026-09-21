"""§10's checks that can be made without looking at other rows.

    *"Invalid data must be rejected with a clear reason."*

Every failure here carries the field it is about and what would fix it, for the
same reason `app/learning/practice.py` insists a diagnosis be actionable: a
refusal a caller cannot act on teaches it nothing and produces a retry of the
identical request.

## What is here and what is not

Here: required fields, data types, allowed values, identifier validity, and
fields the type does not declare. All of these are answerable from the request
and the type declaration alone, which is what makes them a pure function and
what makes §35's golden tests possible over them.

Not here: uniqueness and duplicate risk (`dba/duplicates.py` - needs other
rows), referential integrity (`dba/operations.py` - needs the target row),
permissions (`dba/permissions.py`), and conflicting state (`dba/askback.py` -
it is a question, not a rejection). §10 lists all ten together; they are
separated by what evidence each one needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dba import entities, ids

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
# Deliberately permissive: digits, spaces, and the punctuation a phone number is
# written with anywhere in the world. A stricter pattern would reject a real
# number, and §4's example A - two people, one phone number to update - is not
# improved by also arguing about the format.
# At least one digit, which the first version did not require - so six spaces
# validated as a phone number, stored, and could then never be matched by a
# duplicate rule or an equality search. A field that is present and
# unmatchable is worse than an absent one.
_PHONE = re.compile(r"^(?=.*[0-9])[+()\-.\s0-9]{6,}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Problem:
    field: str
    problem: str
    detail: str

    def to_dict(self) -> dict:
        return {"field": self.field, "problem": self.problem, "detail": self.detail}


MISSING = "missing_required_field"
WRONG_TYPE = "wrong_type"
NOT_ALLOWED = "value_not_allowed"
UNDECLARED = "undeclared_field"
BAD_IDENTIFIER = "invalid_identifier"


def check_new(entity_type: entities.EntityType, data: dict) -> list[Problem]:
    """Everything wrong with a proposed new record. All of it, not the first.

    Returning every problem rather than raising on the first is the same call
    `app/learning/objective.py` made: a caller told about one missing field at
    a time makes one round trip per field, and each round trip is a chance to
    give up."""
    problems = _undeclared(entity_type, data)
    for name in entity_type.required:
        if _blank(data.get(name)):
            problems.append(Problem(
                name, MISSING,
                f"{entity_type.name} requires {name!r}; it was "
                f"{'absent' if name not in data else 'empty'}."))
    problems += _types_and_values(entity_type, data)
    return problems


def check_change(entity_type: entities.EntityType, data: dict) -> list[Problem]:
    """Everything wrong with a proposed change.

    A required field may be absent - an update names only what changes - but it
    may not be *emptied*, because a required field set to nothing is a row the
    type says cannot exist."""
    problems = _undeclared(entity_type, data)
    for name in entity_type.required:
        if name in data and _blank(data[name]):
            problems.append(Problem(
                name, MISSING,
                f"{name!r} is required on a {entity_type.name} and cannot be "
                f"cleared. Archive the record if it should stop being one."))
    problems += _types_and_values(entity_type, data)
    return problems


def _undeclared(entity_type: entities.EntityType, data: dict) -> list[Problem]:
    """A field the type does not declare is refused, never quietly stored.

    Accepting it would put data in the record that nothing validates, nothing
    indexes and no search can find - which reads as a successful write and is
    a silent loss."""
    return [
        Problem(name, UNDECLARED,
                f"{entity_type.name} declares {sorted(entity_type.fields)}. "
                f"Adding {name!r} is an edit to dba/entities.py, not something "
                f"a write may do for itself.")
        for name in sorted(data) if name not in entity_type.fields
    ]


def _types_and_values(entity_type: entities.EntityType,
                      data: dict) -> list[Problem]:
    problems: list[Problem] = []
    for name, value in sorted(data.items()):
        declared = entity_type.fields.get(name)
        if declared is None or value is None:
            continue
        bad = _type_problem(name, declared, value)
        if bad is not None:
            problems.append(bad)
            continue
        if name == entities.STATUS and entity_type.statuses:
            if value not in entity_type.statuses:
                problems.append(Problem(
                    name, NOT_ALLOWED,
                    f"{value!r} is not a {entity_type.name} status. Allowed: "
                    f"{', '.join(entity_type.statuses)}."))
    return problems


def _type_problem(name: str, declared: str, value) -> Problem | None:
    if declared in (entities.TEXT, entities.EMAIL, entities.PHONE):
        if not isinstance(value, str):
            return Problem(name, WRONG_TYPE,
                           f"expected text, got {type(value).__name__}")
        if declared == entities.EMAIL and not _EMAIL.match(value):
            return Problem(name, WRONG_TYPE,
                           f"{value!r} is not an email address")
        if declared == entities.PHONE and not _PHONE.match(value):
            return Problem(name, WRONG_TYPE,
                           f"{value!r} is not a phone number")
        return None
    if declared == entities.INTEGER:
        # bool is an int in Python and almost never the intended value here.
        if isinstance(value, bool) or not isinstance(value, int):
            return Problem(name, WRONG_TYPE,
                           f"expected a whole number, got {type(value).__name__}")
        return None
    if declared == entities.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return Problem(name, WRONG_TYPE,
                           f"expected a number, got {type(value).__name__}")
        return None
    if declared == entities.BOOLEAN:
        if not isinstance(value, bool):
            return Problem(name, WRONG_TYPE,
                           f"expected true or false, got {type(value).__name__}")
        return None
    if declared == entities.DATE:
        if not isinstance(value, str) or not _DATE.match(value):
            return Problem(name, WRONG_TYPE, f"expected YYYY-MM-DD, got {value!r}")
        return None
    if declared == entities.TIMESTAMP:
        if not isinstance(value, str) or "T" not in value:
            return Problem(name, WRONG_TYPE,
                           f"expected an ISO-8601 timestamp, got {value!r}")
        return None
    return None


def check_identifier(entity_id: str, entity_type: str | None = None) -> list[Problem]:
    """§10's "identifier validity", before any lookup is attempted."""
    if not ids.is_id(entity_id):
        return [Problem("entity_id", BAD_IDENTIFIER,
                        f"{entity_id!r} is not an identifier this system issued.")]
    if entity_type and not ids.belongs_to(entity_id, entity_type):
        return [Problem("entity_id", BAD_IDENTIFIER,
                        f"{entity_id} is a {ids.type_of(entity_id)} id, but the "
                        f"request says entity_type={entity_type!r}.")]
    return []


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def as_details(problems: list[Problem]) -> dict:
    """The `details` payload of a `validation_error` (§23)."""
    return {"problems": [problem.to_dict() for problem in problems]}


def message(problems: list[Problem]) -> str:
    if len(problems) == 1:
        return f"{problems[0].field}: {problems[0].detail}"
    return (f"{len(problems)} problems: "
            + "; ".join(f"{p.field}: {p.detail}" for p in problems))
