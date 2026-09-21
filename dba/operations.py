"""§8's logical operations, one function each.

Every one takes an open connection and returns a `Response`; none of them
opens a transaction, writes an audit event or thinks about idempotency. Those
are cross-cutting and belong to `dba/agent.py`, which wraps all of them
identically - the arrangement that makes it impossible for one operation to
forget the audit event, which is the failure a per-operation `record()` call
invites.

## The order of checks is the specification's, and it is deliberate

Validate, then look up, then ask, then write. A request that is malformed is
told so before the DBA goes looking for records it might be about, because a
`not_found` for a request that was never valid sends the caller after the wrong
problem. And every question is produced **before** anything is written, which
is what makes §4's *"no update is committed"* true by construction rather than
by discipline.

## Dry run (§30)

`dry_run` is honoured by every writing operation and reports what would happen
with `changed: false`. It is not a separate code path: the operation does all
its checks and stops at the write, so a dry run that comes back clean is
evidence about the real thing rather than about a simulation of it.
"""

from __future__ import annotations

from backend.db import Database
from dba import (askback, audit, contract, duplicates, entities, ids, records,
                 validate)


# --- create -------------------------------------------------------------------


def create(conn: Database, entity_type: entities.EntityType,
           request: contract.Request) -> contract.Response:
    problems = validate.check_new(entity_type, request.data)
    question = askback.missing_information_question(
        entity_type, request, problems)
    if question is not None:
        return question
    if problems:
        return contract.failure(
            request, code=contract.VALIDATION_ERROR,
            message=validate.message(problems),
            details=validate.as_details(problems))

    collisions = duplicates.colliding(conn, entity_type, request.data)
    if collisions:
        field, existing = collisions[0]
        return contract.failure(
            request, code=contract.DUPLICATE_DETECTED,
            message=(f"a {entity_type.name} with {field}="
                     f"{request.data[field]!r} already exists as "
                     f"{existing['id']}. Update that record rather than "
                     f"creating a second one."),
            details=duplicates.describe(entity_type, collisions))

    if request.dry_run:
        return contract.success(
            request, changed=False,
            result={"would_create": entity_type.name, "committed": False,
                    "data": dict(request.data)})

    entity_id = records.insert(
        conn, entity_type, request.data,
        source_agent=request.requested_by,
        source_type=request.data.get("source_type") or "user_provided")
    return contract.success(
        request, changed=True, entity_id=entity_id,
        result=records.get(conn, entity_id))


# --- read ---------------------------------------------------------------------


def get(conn: Database, entity_type: entities.EntityType,
        request: contract.Request) -> contract.Response:
    if not request.entity_id:
        return contract.failure(
            request, code=contract.VALIDATION_ERROR,
            message="get needs an entity_id. Use find or search to look one up "
                    "by its fields.")
    problems = validate.check_identifier(request.entity_id, entity_type.name)
    if problems:
        return contract.failure(
            request, code=contract.VALIDATION_ERROR,
            message=validate.message(problems),
            details=validate.as_details(problems))
    scope = request.criteria.get("scope", records.LIVE)
    found = records.get(conn, request.entity_id, scope=scope)
    if found is None:
        return contract.failure(
            request, code=contract.NOT_FOUND,
            message=askback.not_found_detail(
                entity_type, request, askback.Resolution([], "entity_id")))
    return contract.success(request, changed=False, result=found,
                            entity_id=found["id"])


def find(conn: Database, entity_type: entities.EntityType,
         request: contract.Request) -> contract.Response:
    criteria = dict(request.criteria)
    scope = criteria.pop("scope", records.LIVE)
    limit = criteria.pop("limit", records.DEFAULT_LIMIT)
    offset = criteria.pop("offset", 0)
    found = records.find(conn, entity_type.name, criteria=criteria,
                         scope=scope, limit=limit, offset=offset)
    return contract.success(request, changed=False,
                            result={"matches": found, "count": len(found)})


def search(conn: Database, entity_type: entities.EntityType | None,
           request: contract.Request) -> contract.Response:
    text = request.criteria.get("text") or request.criteria.get("q") or ""
    if not str(text).strip():
        return contract.failure(
            request, code=contract.VALIDATION_ERROR,
            message="search needs criteria.text - the words to look for.")
    found = records.search(
        conn, str(text), entity_type=entity_type.name if entity_type else None,
        scope=request.criteria.get("scope", records.LIVE),
        limit=request.criteria.get("limit", records.DEFAULT_LIMIT))
    return contract.success(request, changed=False,
                            result={"matches": found, "count": len(found)})


def list_records(conn: Database, entity_type: entities.EntityType,
                 request: contract.Request) -> contract.Response:
    return find(conn, entity_type, request)


def count(conn: Database, entity_type: entities.EntityType | None,
          request: contract.Request) -> contract.Response:
    total = records.count(
        conn, entity_type.name if entity_type else None,
        scope=request.criteria.get("scope", records.LIVE))
    return contract.success(request, changed=False, result={"count": total})


def history(conn: Database, entity_type: entities.EntityType,
            request: contract.Request) -> contract.Response:
    """§8's `history`, which is the audit trail read from the record's side."""
    if not request.entity_id:
        return contract.failure(
            request, code=contract.VALIDATION_ERROR,
            message="history needs an entity_id - it is the story of one record.")
    events = audit.for_entity(conn, request.entity_id,
                              limit=request.criteria.get("limit", 50))
    if not events and records.get(conn, request.entity_id,
                                  scope=records.ANY) is None:
        return contract.failure(
            request, code=contract.NOT_FOUND,
            message=f"no record and no history for {request.entity_id}.")
    return contract.success(request, changed=False,
                            result={"events": events, "count": len(events)},
                            entity_id=request.entity_id)


def validate_only(conn: Database, entity_type: entities.EntityType,
                  request: contract.Request) -> contract.Response:
    """§8's `validate`: would this write be accepted? Nothing is written.

    A read, and classified as one by `dba/permissions.py`, because the caller
    is asking a question about a record rather than changing it."""
    existing = records.get(conn, request.entity_id) if request.entity_id else None
    problems = (validate.check_change(entity_type, request.data) if existing
                else validate.check_new(entity_type, request.data))
    collisions = duplicates.colliding(
        conn, entity_type, request.data,
        excluding=existing["id"] if existing else None)
    return contract.success(
        request, changed=False,
        result={
            "acceptable": not problems and not collisions,
            "problems": [problem.to_dict() for problem in problems],
            "duplicates": duplicates.describe(entity_type, collisions)
            if collisions else None,
        })


# --- change -------------------------------------------------------------------


def update(conn: Database, entity_type: entities.EntityType,
           request: contract.Request) -> contract.Response:
    if not request.data:
        return contract.failure(
            request, code=contract.VALIDATION_ERROR,
            message="update needs data - the fields to change.")

    problems = validate.check_change(entity_type, request.data)
    if problems and any(p.problem != validate.MISSING for p in problems):
        return contract.failure(
            request, code=contract.VALIDATION_ERROR,
            message=validate.message(problems),
            details=validate.as_details(problems))

    resolution = askback.resolve(conn, entity_type, request)
    question = askback.ambiguity_question(entity_type, request, resolution)
    if question is not None:
        return question
    if resolution.none:
        # A record that exists but is retired is NOT a `not_found`. It is
        # there, and saying it is not sends the caller off to re-create it -
        # which is how a duplicate of an archived record gets made. §4's
        # example C is the right answer: name the state and ask.
        retired = (records.get(conn, request.entity_id, scope=records.ANY)
                   if request.entity_id else None)
        if retired is not None:
            question = askback.contradiction_question(
                entity_type, request, retired)
            if question is not None:
                return question
        return contract.failure(
            request, code=contract.NOT_FOUND,
            message=askback.not_found_detail(entity_type, request, resolution))

    existing = resolution.only
    question = askback.contradiction_question(entity_type, request, existing)
    if question is not None:
        return question
    if problems:
        question = askback.missing_information_question(
            entity_type, request, problems)
        if question is not None:
            return question

    collisions = duplicates.colliding(conn, entity_type, request.data,
                                      excluding=existing["id"])
    if collisions:
        field, other = collisions[0]
        return contract.failure(
            request, code=contract.DUPLICATE_DETECTED,
            message=(f"{field}={request.data[field]!r} already belongs to "
                     f"{other['id']}. Two {entity_type.name} records cannot "
                     f"share it."),
            details=duplicates.describe(entity_type, collisions))

    if request.dry_run:
        would = {name: (existing.get(name), value)
                 for name, value in request.data.items()
                 if existing.get(name) != value}
        return contract.success(
            request, changed=False, entity_id=existing["id"],
            result={"would_change": would, "committed": False})

    moved = records.apply_changes(conn, entity_type, existing["id"],
                                  request.data)
    return contract.success(
        request, changed=bool(moved), entity_id=existing["id"],
        result={"changed_fields": {name: {"from": before, "to": after}
                                   for name, (before, after) in moved.items()},
                "record": records.get(conn, existing["id"], scope=records.ANY)},
        warnings=() if moved else
        ("every field already held the value requested; nothing was written.",))


def archive(conn: Database, entity_type: entities.EntityType,
            request: contract.Request) -> contract.Response:
    return _retire(conn, entity_type, request, hard=False)


def delete_authorized(conn: Database, entity_type: entities.EntityType,
                      request: contract.Request) -> contract.Response:
    return _retire(conn, entity_type, request, hard=True)


def _retire(conn: Database, entity_type: entities.EntityType,
            request: contract.Request, *, hard: bool) -> contract.Response:
    # A hard delete looks past the archive. `archive` retires a live record;
    # `delete_authorized` has to be able to reach one that was already
    # archived, which is the ordinary sequence - retire it, then later remove
    # it. Resolving live-only made that second step impossible and reported
    # `not_found` for a record plainly there.
    resolution = askback.resolve(
        conn, entity_type, request,
        scope=records.ARCHIVED_OR_LIVE if hard else records.LIVE)
    if resolution.none:
        return contract.failure(
            request, code=contract.NOT_FOUND,
            message=askback.not_found_detail(entity_type, request, resolution))

    question = askback.destructive_scope_question(
        entity_type, request, resolution)
    if question is not None:
        return question
    question = askback.ambiguity_question(entity_type, request, resolution) \
        if not request.confirmed else None
    if question is not None:
        return question

    targets = [record["id"] for record in resolution.matches]
    if request.dry_run:
        return contract.success(
            request, changed=False,
            result={"matched_records": len(targets),
                    "estimated_changes": len(targets), "committed": False,
                    "ids": targets[:25]})

    apply = records.soft_delete if hard else records.archive
    done = [entity_id for entity_id in targets if apply(conn, entity_id)]
    return contract.success(
        request, changed=bool(done),
        entity_id=done[0] if len(done) == 1 else None,
        result={"affected": len(done), "ids": done,
                "already_in_that_state": len(targets) - len(done)})


# --- relationships (§6.2) -----------------------------------------------------


def link(conn: Database, request: contract.Request) -> contract.Response:
    return _edge(conn, request, making=True)


def unlink(conn: Database, request: contract.Request) -> contract.Response:
    return _edge(conn, request, making=False)


def _edge(conn: Database, request: contract.Request, *,
          making: bool) -> contract.Response:
    from_id = request.data.get("from_id")
    to_id = request.data.get("to_id")
    relation = request.data.get("relation")
    missing = [name for name, value in
               (("from_id", from_id), ("to_id", to_id), ("relation", relation))
               if not value]
    if missing:
        return contract.failure(
            request, code=contract.VALIDATION_ERROR,
            message=(f"{request.action} needs {', '.join(missing)} in data. A "
                     f"relationship is two identified records and the name of "
                     f"what holds between them."))

    # §10's referential integrity: both ends must exist as live records.
    for label, entity_id in (("from_id", from_id), ("to_id", to_id)):
        if not ids.is_id(entity_id):
            return contract.failure(
                request, code=contract.VALIDATION_ERROR,
                message=f"{label}={entity_id!r} is not an identifier this "
                        f"system issued.")
        if records.get(conn, entity_id) is None:
            return contract.failure(
                request, code=contract.NOT_FOUND,
                message=f"{label}={entity_id} is not a live record, so nothing "
                        f"can be linked to it.")

    existing = conn.fetchone(
        "SELECT * FROM relationships WHERE from_id = ? AND relation = ? "
        "AND to_id = ? AND archived_at IS NULL", (from_id, relation, to_id))

    if request.dry_run:
        return contract.success(
            request, changed=False,
            result={"would": request.action, "already_present": existing is not None,
                    "committed": False})

    if making:
        if existing is not None:
            return contract.success(
                request, changed=False, entity_id=existing["id"],
                result={"relationship_id": existing["id"], "already_present": True},
                warnings=("that link already exists; nothing was written.",))
        from backend.db import now_iso

        relationship_id = ids.new_id("link")
        conn.execute(
            "INSERT INTO relationships (id, from_id, relation, to_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (relationship_id, from_id, relation, to_id, now_iso()))
        return contract.success(
            request, changed=True, entity_id=relationship_id,
            result={"relationship_id": relationship_id})

    if existing is None:
        return contract.failure(
            request, code=contract.NOT_FOUND,
            message=f"no live {relation!r} link from {from_id} to {to_id}.")
    from backend.db import now_iso

    conn.execute("UPDATE relationships SET archived_at = ? WHERE id = ?",
                 (now_iso(), existing["id"]))
    return contract.success(request, changed=True, entity_id=existing["id"],
                            result={"relationship_id": existing["id"]})


def links_of(conn: Database, entity_id: str) -> list[dict]:
    """Every live edge touching a record, either way round."""
    rows = conn.fetchall(
        "SELECT * FROM relationships WHERE (from_id = ? OR to_id = ?) "
        "AND archived_at IS NULL ORDER BY created_at ASC", (entity_id, entity_id))
    return [dict(row) for row in rows]
