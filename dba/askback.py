"""The ask-back (§4), which the specification calls mandatory and §45 calls
foundational.

    *"The DBA Agent must not guess when a database-changing request is
    ambiguous."*

## The five cases in §4, and how each arrives as structure

§4's examples are sentences, because that is how Krish will say them. By the
time one reaches this module it is a `Request`, and something upstream did the
translation - which §36 explicitly allows a model to do. What must not be a
model's judgement is the *decision*, so every function here is a pure function
of the request and the stored rows, and `tests/test_dba.py` asserts each of
§4's five examples against it.

- **A, ambiguous identity.** `resolve` returns every live record the request
  could mean. Two means a question, and `dba/records.summary` builds the
  options from the fields that actually distinguish them.
- **B, missing information.** `dba/validate.py` produces the list; this module
  turns *only the missing required fields* into a question, because §4.1 says
  to ask only for the missing information and a question that also relitigates
  a bad phone format is two conversations at once.
- **C, contradictory information.** A request that sets a field and, in the
  same breath, asserts that field must keep its current value. That is the
  structured form of *"mark this customer inactive, but keep the active
  status"*, and it is detectable without understanding English.
- **D, destructive scope.** An archive or a delete that names criteria rather
  than an id does not run until somebody has seen how many rows it matches.
  The question carries the count, which is the fact that makes the answer
  possible.
- **E, uncertain relationship.** `link` resolves its target the same way `A`
  resolves its subject, so attaching a document to "the project" asks which
  project for the same reason and through the same code.

## §4.1's rules, and where each one is enforced

*Ask the minimum number of questions necessary* - each checker returns at most
one question, and `first_question` takes the first that fires in a fixed order
rather than assembling several. *Be specific* - every question names the field
or the records at issue. *Avoid asking when the intent is unambiguous* - a
single match never asks, and a request carrying `confirmed=True` has already
answered the scope question. *Never invent missing facts* - nothing here
supplies a default for anything. *Never silently choose between plausible
records* - `resolve` has no branch that picks one.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.db import Database
from dba import contract, entities, ids, records, validate


@dataclass(frozen=True)
class Resolution:
    """Which stored records a request could be about."""

    matches: list[dict]
    looked_up_by: str

    @property
    def exactly_one(self) -> bool:
        return len(self.matches) == 1

    @property
    def none(self) -> bool:
        return not self.matches

    @property
    def ambiguous(self) -> bool:
        return len(self.matches) > 1

    @property
    def only(self) -> dict:
        if not self.exactly_one:
            raise ValueError(
                f"only one record may be taken from a resolution holding "
                f"{len(self.matches)} - this is the guard against the silent "
                f"choice §4.1 forbids.")
        return self.matches[0]


def resolve(conn: Database, entity_type: entities.EntityType,
            request: contract.Request,
            scope: str = records.LIVE) -> Resolution:
    """Every live record this request could mean (§4, examples A and E).

    An explicit id wins and is not searched for: a caller that supplies one has
    already answered the question. Otherwise the criteria are matched, and
    whatever comes back comes back - including nothing, and including four."""
    if request.entity_id:
        found = records.get(conn, request.entity_id, scope=scope)
        return Resolution([found] if found else [], "entity_id")

    # Only the parts that describe a record. `scope`, `limit` and `offset`
    # steer the query, and treating one as a field value meant an update
    # carrying `limit` matched nothing and came back `not_found`.
    criteria = records.field_criteria(request.criteria)
    if not criteria:
        return Resolution([], "nothing")
    matches = records.find(conn, entity_type.name, criteria=criteria,
                           scope=scope)
    return Resolution(matches, ", ".join(sorted(criteria)))


def ambiguity_question(entity_type: entities.EntityType,
                       request: contract.Request,
                       resolution: Resolution) -> contract.Response | None:
    """§4 example A. `Which John do you mean?`, with the records to choose from."""
    if not resolution.ambiguous:
        return None
    return contract.clarify(
        request,
        reason=contract.MULTIPLE_MATCHING_RECORDS,
        question=(f"{len(resolution.matches)} {entity_type.name} records match "
                  f"{resolution.looked_up_by}. Which one do you mean?"),
        options=[records.summary(record, entity_type)
                 for record in resolution.matches])


def missing_information_question(entity_type: entities.EntityType,
                                 request: contract.Request,
                                 problems: list[validate.Problem],
                                 ) -> contract.Response | None:
    """§4 example B, and §4.1's *ask only for the missing information*.

    Only fires when every problem is a missing required field. A request that
    is also malformed gets a `validation_error` instead, because a question
    about what is absent implies everything present was fine."""
    if not problems or any(p.problem != validate.MISSING for p in problems):
        return None
    absent = sorted(p.field for p in problems)
    return contract.clarify(
        request,
        reason=contract.MISSING_REQUIRED_INFORMATION,
        question=(f"To {request.action} a {entity_type.name} I still need "
                  f"{_and_list(absent)}. What should it be?"
                  if len(absent) == 1 else
                  f"To {request.action} a {entity_type.name} I still need "
                  f"{_and_list(absent)}. What should they be?"),
        options=[{"field": name,
                  "type": entity_type.fields.get(name, entities.TEXT)}
                 for name in absent])


def contradiction_question(entity_type: entities.EntityType,
                           request: contract.Request,
                           existing: dict | None) -> contract.Response | None:
    """§4 example C.

    Two shapes, both structural:

    1. The request sets a field and simultaneously asserts, through `criteria`,
       that the same field holds a different value. *"Mark this customer
       inactive, but keep the active status."* Both cannot be true afterwards.
    2. The request changes a record that is archived or deleted. The stored
       state and the requested one disagree about whether this record is in
       use at all, and quietly editing a retired row is the silent choice §4.1
       forbids wearing a different hat.
    """
    conflicting = sorted(
        name for name, value in request.data.items()
        if name in request.criteria and request.criteria[name] != value)
    if conflicting:
        name = conflicting[0]
        return contract.clarify(
            request,
            reason=contract.CONTRADICTORY_REQUEST,
            question=(f"This asks to set {name} to "
                      f"{request.data[name]!r} while also requiring that "
                      f"{name} stays {request.criteria[name]!r}. Both cannot "
                      f"hold. Which state is intended?"),
            options=[{"field": name, "set_to": request.data[name]},
                     {"field": name, "keep": request.criteria[name]}])

    if existing and request.writes and request.action != contract.ARCHIVE:
        retired = existing.get("deleted_at") or existing.get("archived_at")
        if retired:
            state = "deleted" if existing.get("deleted_at") else "archived"
            return contract.clarify(
                request,
                reason=contract.CONTRADICTORY_REQUEST,
                question=(f"{existing['id']} was {state} on {retired}. Changing "
                          f"a {state} {entity_type.name} would leave it {state} "
                          f"and edited. Restore it first, or is the change "
                          f"meant for a different record?"),
                options=[{"id": existing["id"], "state": state}])
    return None


def destructive_scope_question(entity_type: entities.EntityType,
                               request: contract.Request,
                               resolution: Resolution,
                               ) -> contract.Response | None:
    """§4 example D. *"Delete all old records."*

    A destructive action that names criteria rather than one id does not run
    until the count has been shown and confirmed. The count is the whole point:
    *twelve* is a different decision from *twelve thousand*, and §30's dry-run
    exists for the same reason. A request carrying `confirmed=True` has already
    been through this and is not asked twice."""
    if request.action not in (contract.ARCHIVE, contract.DELETE_AUTHORIZED):
        return None
    if request.entity_id or request.confirmed or resolution.none:
        return None
    verb = "archive" if request.action == contract.ARCHIVE else "delete"
    return contract.clarify(
        request,
        reason=contract.DESTRUCTIVE_SCOPE_UNCLEAR,
        question=(f"This would {verb} {len(resolution.matches)} "
                  f"{entity_type.name} record(s) matched by "
                  f"{resolution.looked_up_by}. Confirm that scope, or narrow "
                  f"it. Nothing has been {verb}d."),
        options=[records.summary(record, entity_type)
                 for record in resolution.matches[:25]])


def relationship_question(request: contract.Request, *, side: str,
                          candidates: list[dict],
                          candidate_type: entities.EntityType,
                          ) -> contract.Response | None:
    """§4 example E. Which project should this document attach to?"""
    if len(candidates) <= 1:
        return None
    return contract.clarify(
        request,
        reason=contract.UNCERTAIN_RELATIONSHIP,
        question=(f"{len(candidates)} {candidate_type.name} records could be "
                  f"the {side} of this link. Which one?"),
        options=[records.summary(record, candidate_type)
                 for record in candidates])


def not_found_detail(entity_type: entities.EntityType,
                     request: contract.Request,
                     resolution: Resolution) -> str:
    """The message for a lookup that matched nothing.

    Not a question: §45 says ask when a record *cannot be uniquely identified*,
    and nothing matching is not ambiguity - it is an answer. Asking "which one
    did you mean?" about an empty list would be inviting the caller to invent
    one."""
    if request.entity_id:
        if not ids.is_id(request.entity_id):
            return (f"{request.entity_id!r} is not an identifier this system "
                    f"issued.")
        return (f"no live {entity_type.name} has id {request.entity_id}. It may "
                f"have been archived or deleted; ask with scope to see.")
    return (f"no live {entity_type.name} matches {resolution.looked_up_by}"
            f" ({_criteria_text(request.criteria)}).")


def _criteria_text(criteria: dict) -> str:
    return ", ".join(f"{name}={value!r}" for name, value in sorted(criteria.items()))


def _and_list(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"
