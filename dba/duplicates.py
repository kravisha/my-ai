"""§11, and the line in it that decides the design.

    *"The DBA must not automatically merge uncertain records."*

So nothing here merges anything. It finds candidates and hands them back, and
the caller either gets a refusal naming the record it collided with or a
question naming the ones it might have meant.

## Confident versus uncertain, and why they end differently

A declared **identifying** field matching exactly - the same email address, the
same document hash, the same external id - is a confident duplicate. §11 lists
those exact signals. It is refused with `duplicate_detected` and the existing
id, because the honest answer is "that record exists, update it" and a question
would only be asking the caller to agree with something already established.

A match on the **label** alone - two people called John Smith - is not a
duplicate at all. It is the ordinary case §4's example A is built on, and
treating it as a collision would make the system unable to hold two people with
the same name. It becomes a question only when something later has to pick one.
"""

from __future__ import annotations

from backend.db import Database
from dba import entities, records


def colliding(conn: Database, entity_type: entities.EntityType, data: dict,
              *, excluding: str | None = None) -> list[tuple[str, dict]]:
    """Live records that collide with this one on a declared identifying field.

    Returns (field, record) pairs so a refusal can say *which* field collided,
    which is the difference between a message a caller can act on and one that
    just says no. `excluding` is the record being updated, which must not be
    reported as a duplicate of itself."""
    found: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for field in entity_type.identifying:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        for candidate in records.find(conn, entity_type.name,
                                      criteria={field: value}):
            if candidate["id"] == excluding or candidate["id"] in seen:
                continue
            seen.add(candidate["id"])
            found.append((field, candidate))
    return found


def describe(entity_type: entities.EntityType,
             collisions: list[tuple[str, dict]]) -> dict:
    """The `details` of a `duplicate_detected` error (§23)."""
    return {
        "matched_on": sorted({field for field, _ in collisions}),
        "existing": [records.summary(record, entity_type)
                     for _, record in collisions],
    }
