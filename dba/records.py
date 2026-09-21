"""Rows in, records out - and the only module that names a column (§9).

§6.3's split lives here and nowhere else: the promoted fields go to their own
columns, everything else to `data_json`, and a caller never has to know which
is which. A record read back is one flat dictionary, the same shape it was
written as, because a store whose read shape differs from its write shape makes
every caller do the translation and one of them will do it differently.

## Live, archived, deleted

§5.6 prefers archival to deletion, so three states rather than two. `archived_at`
is the ordinary retirement; `deleted_at` is the soft form of the restricted,
auditable hard delete. Every read defaults to live rows only, and asking for the
others is an explicit argument - a search that silently returned archived rows
would produce the duplicate a user just archived.
"""

from __future__ import annotations

import json
from typing import Any

from backend.db import Database, now_iso
from dba import entities, ids

# Columns that exist for every entity, in addition to the promoted fields.
SYSTEM_COLUMNS = ("id", "entity_type", "data_json", "classification",
                  "source_type", "source_agent", "confidence", "verified",
                  "created_at", "updated_at", "archived_at", "deleted_at",
                  "schema_version")

LIVE = "live"
ARCHIVED = "archived"
DELETED = "deleted"
# Everything not yet deleted. What a hard delete resolves in: archiving is a
# step on the way to removal, so a record must not become unreachable by being
# retired first.
ARCHIVED_OR_LIVE = "archived_or_live"
ANY = "any"
SCOPES = (LIVE, ARCHIVED, DELETED, ARCHIVED_OR_LIVE, ANY)

# A hard ceiling on any result set (§27's "bounded query results"). A caller may
# ask for less and cannot ask for more; an unbounded read of a table that grows
# is the architectural dead end §27 names.
MAX_RESULTS = 500
DEFAULT_LIMIT = 50

# Keys in `criteria` that steer the query rather than describe a record. Named
# once and shared, because `askback.resolve` not stripping them meant an update
# carrying `limit` matched nothing and came back `not_found` - a control knob
# silently read as a field value.
CONTROL_KEYS = ("scope", "limit", "offset", "text", "q")


class IncompleteScan(RuntimeError):
    """A filtered read that could not see every candidate row.

    Raised rather than returning a short list, and that is the whole point. The
    metadata-criteria path below scans a bounded window; if the window filled,
    rows outside it were never examined, and a caller that treated the result
    as complete could conclude "exactly one match" about a name that has two.
    That is §4.1's silent choice arriving through the back door, so the read
    fails loudly instead."""


def field_criteria(criteria: dict) -> dict:
    """Just the parts of `criteria` that describe a record."""
    return {name: value for name, value in (criteria or {}).items()
            if name not in CONTROL_KEYS and value is not None}


_JSON1: bool | None = None


def _json1(conn: Database) -> bool:
    """Whether this SQLite can filter inside `data_json`.

    Probed once per process rather than assumed. json1 has been compiled in by
    default since SQLite 3.38, but "almost certainly present" is not a thing to
    build a correctness guarantee on, and the fallback below is materially
    weaker - so which one ran must be knowable."""
    global _JSON1
    if _JSON1 is None:
        try:
            conn.fetchone("SELECT json_extract('{\"a\":1}', '$.a') AS probe")
            _JSON1 = True
        except Exception:  # noqa: BLE001 - any failure means fall back
            _JSON1 = False
    return _JSON1


def _scope_sql(scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"scope={scope!r} is not one of {SCOPES}")
    return {
        LIVE: " AND archived_at IS NULL AND deleted_at IS NULL",
        ARCHIVED: " AND archived_at IS NOT NULL AND deleted_at IS NULL",
        DELETED: " AND deleted_at IS NOT NULL",
        ARCHIVED_OR_LIVE: " AND deleted_at IS NULL",
        ANY: "",
    }[scope]


def to_columns(entity_type: entities.EntityType, data: dict) -> tuple[dict, dict]:
    """Split a flat record into (promoted columns, everything else)."""
    promoted = {name: data[name] for name in entity_type.promoted_fields()
                if name in data}
    extra = {name: value for name, value in data.items()
             if name in entity_type.fields and name not in entities.PROMOTED}
    return promoted, extra


def from_row(row: dict) -> dict[str, Any]:
    """One database row as the flat record a caller wrote."""
    record: dict[str, Any] = {}
    try:
        record.update(json.loads(row.get("data_json") or "{}"))
    except (TypeError, ValueError):
        # A row whose JSON will not parse is a real problem, but losing the
        # promoted columns as well would turn one damaged field into an
        # unreadable record. Surface it as a field rather than raising.
        record["_unreadable_metadata"] = row.get("data_json")
    for name in entities.PROMOTED:
        if row.get(name) is not None:
            record[name] = row[name]
    record["id"] = row["id"]
    record["entity_type"] = row["entity_type"]
    record["classification"] = row["classification"]
    record["created_at"] = row["created_at"]
    record["updated_at"] = row["updated_at"]
    if row.get("archived_at"):
        record["archived_at"] = row["archived_at"]
    if row.get("deleted_at"):
        record["deleted_at"] = row["deleted_at"]
    return record


def insert(conn: Database, entity_type: entities.EntityType, data: dict, *,
           source_agent: str, source_type: str = "user_provided",
           confidence: float | None = None, verified: bool = False,
           classification: str | None = None) -> str:
    """Write one new record and return its id."""
    promoted, extra = to_columns(entity_type, data)
    entity_id = ids.new_id(entity_type.name)
    stamp = now_iso()
    columns = ["id", "entity_type", "data_json", "classification",
               "source_type", "source_agent", "confidence", "verified",
               "created_at", "updated_at", "schema_version"]
    values: list[Any] = [
        entity_id, entity_type.name, json.dumps(extra, ensure_ascii=False),
        classification or entity_type.classification, source_type, source_agent,
        confidence, int(bool(verified)), stamp, stamp, 1]
    for name, value in promoted.items():
        columns.append(name)
        values.append(value)
    conn.execute(
        f"INSERT INTO entities ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})", tuple(values))
    return entity_id


def get(conn: Database, entity_id: str, *, scope: str = LIVE) -> dict | None:
    row = conn.fetchone(
        f"SELECT * FROM entities WHERE id = ?{_scope_sql(scope)}", (entity_id,))
    return from_row(row) if row else None


def apply_changes(conn: Database, entity_type: entities.EntityType,
                  entity_id: str, data: dict) -> dict:
    """Write a change and return {field: (before, after)} for what moved.

    Returns what *actually* changed rather than what was asked for, which is
    what `changed` in the response is computed from (§44). A request setting a
    field to the value it already holds is a successful no-change, and saying
    so is more useful than claiming an update that did nothing."""
    row = conn.fetchone("SELECT * FROM entities WHERE id = ?", (entity_id,))
    if row is None:
        raise LookupError(entity_id)
    before = from_row(row)

    moved = {name: (before.get(name), value) for name, value in data.items()
             if before.get(name) != value}
    if not moved:
        return {}

    promoted, extra = to_columns(entity_type, {k: v for k, v in data.items()})
    assignments = [f"{name} = ?" for name in promoted]
    values: list[Any] = list(promoted.values())
    if extra:
        try:
            stored = json.loads(row.get("data_json") or "{}")
        except (TypeError, ValueError):
            stored = {}
        stored.update(extra)
        assignments.append("data_json = ?")
        values.append(json.dumps(stored, ensure_ascii=False))
    assignments.append("updated_at = ?")
    values.append(now_iso())
    values.append(entity_id)
    conn.execute(f"UPDATE entities SET {', '.join(assignments)} WHERE id = ?",
                 tuple(values))
    return moved


def archive(conn: Database, entity_id: str) -> bool:
    """§5.6's ordinary retirement. False if it was already archived."""
    changed = conn.execute_returning_rowcount(
        "UPDATE entities SET archived_at = ?, updated_at = ? "
        "WHERE id = ? AND archived_at IS NULL AND deleted_at IS NULL",
        (now_iso(), now_iso(), entity_id))
    return bool(changed)


def soft_delete(conn: Database, entity_id: str) -> bool:
    """The restricted, auditable delete (§5.6). Still recoverable on purpose:
    the audit trail can say a record was deleted and the row can still be
    produced when somebody asks what it said."""
    changed = conn.execute_returning_rowcount(
        "UPDATE entities SET deleted_at = ?, updated_at = ? "
        "WHERE id = ? AND deleted_at IS NULL", (now_iso(), now_iso(), entity_id))
    return bool(changed)


def find(conn: Database, entity_type: str | None = None, *,
         criteria: dict | None = None, scope: str = LIVE,
         limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[dict]:
    """§19's exact lookup and filtered search over the promoted columns.

    A criterion naming a field that is not promoted is applied in Python after
    the query rather than refused, because §6.3 allows a type to keep minor
    fields in metadata and a caller should not have to know which is which. It
    is slower and it is bounded by `MAX_RESULTS`, so the cost is visible."""
    criteria = field_criteria(criteria)
    where = ["1=1"]
    values: list[Any] = []
    if entity_type:
        where.append("entity_type = ?")
        values.append(entity_type)

    in_columns = {name: criteria.pop(name) for name in list(criteria)
                  if name in entities.PROMOTED}
    for name, value in in_columns.items():
        where.append(f"{name} = ?")
        values.append(value)

    limit = max(1, min(int(limit), MAX_RESULTS))
    offset = max(0, int(offset))

    if criteria and _json1(conn):
        # In SQL, so the filter runs over every row rather than over the first
        # page of them. The parameter is the JSON path; the column name is
        # never interpolated.
        for name, value in sorted(criteria.items()):
            where.append("json_extract(data_json, ?) = ?")
            values += [f"$.{name}", value]
        criteria = {}

    sql = (f"SELECT * FROM entities WHERE {' AND '.join(where)}"
           f"{_scope_sql(scope)} ORDER BY created_at ASC, rowid ASC")
    if not criteria:
        sql += " LIMIT ? OFFSET ?"
        values += [limit, offset]
        return [from_row(row) for row in conn.fetchall(sql, tuple(values))]

    # No json1: the bounded scan, which may not have seen everything. If the
    # window filled, say so rather than answering from a partial view.
    sql += " LIMIT ?"
    values.append(MAX_RESULTS)
    rows = conn.fetchall(sql, tuple(values))
    if len(rows) >= MAX_RESULTS:
        raise IncompleteScan(
            f"more than {MAX_RESULTS} candidate rows and no JSON support in "
            f"this SQLite build, so {sorted(criteria)} could not be matched "
            f"over all of them. Narrow the request with a promoted field "
            f"({', '.join(entities.PROMOTED)}).")
    matched = [record for record in (from_row(row) for row in rows)
               if all(record.get(name) == value
                      for name, value in criteria.items())]
    return matched[offset:offset + limit]


def search(conn: Database, text: str, *, entity_type: str | None = None,
           scope: str = LIVE, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """§19C's text search, over the promoted text columns and the metadata blob.

    `LIKE` rather than FTS5: the corpus is small, the behaviour is identical on
    every SQLite build, and an index that has to be kept in step with writes is
    a thing to add when a measurement asks for it rather than in advance."""
    needle = f"%{(text or '').strip()}%"
    if not (text or "").strip():
        return []
    values: list[Any] = [needle, needle, needle, needle, needle]
    # `data_json LIKE` matched the JSON **keys** as well as the values, so
    # searching for "notes" returned every record that merely has a notes
    # field. json_each walks the values only.
    metadata = ("EXISTS (SELECT 1 FROM json_each(entities.data_json) "
                "WHERE json_each.value LIKE ?)" if _json1(conn)
                else "data_json LIKE ?")
    where = (f"(name LIKE ? OR email LIKE ? OR phone LIKE ? OR external_id LIKE ? "
             f"OR {metadata})")
    sql = f"SELECT * FROM entities WHERE {where}"
    if entity_type:
        sql += " AND entity_type = ?"
        values.append(entity_type)
    sql += _scope_sql(scope) + " ORDER BY created_at ASC, rowid ASC LIMIT ?"
    values.append(max(1, min(int(limit), MAX_RESULTS)))
    return [from_row(row) for row in conn.fetchall(sql, tuple(values))]


def count(conn: Database, entity_type: str | None = None, *,
          scope: str = LIVE) -> int:
    sql = "SELECT COUNT(*) AS n FROM entities WHERE 1=1"
    values: list[Any] = []
    if entity_type:
        sql += " AND entity_type = ?"
        values.append(entity_type)
    sql += _scope_sql(scope)
    row = conn.fetchone(sql, tuple(values))
    return int(row["n"]) if row else 0


def summary(record: dict, entity_type: entities.EntityType) -> dict:
    """The minimum that identifies a record in an ask-back option (§4.2, §16).

    §16's minimum-disclosure rule applied to the place it is most tempting to
    ignore: offering a choice between two records does not require sending both
    records. The label, the id, and the fields that distinguish them."""
    out = {"id": record["id"], entity_type.label: record.get(entity_type.label)}
    for name in entity_type.identifying:
        if record.get(name) is not None:
            out[name] = record[name]
    return out
