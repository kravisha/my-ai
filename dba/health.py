"""§28 observability and §29 self-diagnostics.

    *"JARVIS should be able to ask: 'DBA, are you healthy?' and receive a
    structured health response."*

## Honest about what is not built

Backup (§25) and restore (§26) belong to Phase 2 in §46 and do not exist yet.
`last_backup` therefore reports `None` **and says why** rather than being left
out of the response. An absent measurement reads as a clean one - the same
mistake `gateway/remote.py` records making with its four unmeasurable checks,
and the reason it now returns them inside `not_measured` with a reason each.

So a health response here has three kinds of field: a measurement, a `None`
with a stated reason, and a check that ran. Nothing is silently omitted.

## §29's last line, enforced by there being no repair code

    *"Diagnostics must not automatically perform destructive repair unless
    authorized."*

Nothing in this module writes. `diagnose` reports orphaned edges; it does not
delete them. The repair for anything found here is a request through the normal
contract, audited like any other change, which is the point.
"""

from __future__ import annotations

import os
import re
import sqlite3

from backend.db import Database
from dba import audit, entities, permissions, records, store

OK = "ok"
DEGRADED = "degraded"
UNAVAILABLE = "unavailable"

# Index names the schema declares, read from the schema text rather than
# repeated here - a second list would drift from the first, and the drift would
# be invisible until a query got slow.
EXPECTED_INDEXES = tuple(sorted(set(
    re.findall(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)", store.SCHEMA))))

EXPECTED_TABLES = tuple(sorted(set(
    re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", store.SCHEMA))))


def health(connect=None) -> dict:
    """The structured answer to "DBA, are you healthy?" (§28)."""
    connect = connect or store.connect
    try:
        conn = connect()
    except (sqlite3.Error, OSError) as bad:
        return {
            "status": UNAVAILABLE,
            "database_connected": False,
            "detail": f"{type(bad).__name__}: {bad}",
            "schema_version": None,
            "note": "nothing was read; this is a connection failure, not an "
                    "empty database.",
        }
    try:
        store.init_schema(conn)
        path = store.database_path()
        counts = audit.counts(conn)
        failed = counts.get(audit.FAILED, 0) + counts.get(audit.REFUSED, 0)
        total = sum(counts.values()) or 0
        return {
            "status": OK,
            "database_connected": True,
            "engine": "sqlite",
            "path": str(path),
            "schema_version": store.schema_version(conn),
            "storage_bytes": _size(path),
            "entity_counts": _entity_counts(conn),
            "relationships": _one(conn, "SELECT COUNT(*) AS n FROM relationships "
                                        "WHERE archived_at IS NULL"),
            "audit_events": total,
            "failed_operations": failed,
            "error_rate": round(failed / total, 4) if total else 0.0,
            "open_clarifications": _one(
                conn, "SELECT COUNT(*) AS n FROM pending_clarifications "
                      "WHERE resolved_at IS NULL"),
            "handled_requests": _one(conn, "SELECT COUNT(*) AS n FROM handled_requests"),
            "pending_migrations": [],
            "last_backup": _last_backup(),
            "not_measured": {
                "query_latency_ms": "not instrumented yet; §27 asks for "
                                    "correctness before optimisation and "
                                    "nothing has asked this question.",
                "encrypted_secondary_location":
                    "§25 says this should eventually be supported. There is no "
                    "second location configured and nothing is encrypted at "
                    "rest. Reported rather than omitted.",
            },
            "policy": permissions.describe(),
        }
    except (sqlite3.Error, OSError) as bad:
        return {"status": DEGRADED, "database_connected": True,
                "detail": f"{type(bad).__name__}: {bad}"}
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def diagnose(connect=None) -> dict:
    """§29's controlled diagnostics. Reads only; repairs nothing."""
    connect = connect or store.connect
    checks: list[dict] = []
    try:
        conn = connect()
    except (sqlite3.Error, OSError) as bad:
        return {
            "status": UNAVAILABLE,
            "checks": [_check("connectivity", False,
                              f"{type(bad).__name__}: {bad}")],
            "repaired": [],
            "note": "no repair is ever performed automatically (§29).",
        }
    try:
        store.init_schema(conn)
        checks.append(_check("connectivity", True, "opened and readable"))

        present_tables = {row["name"] for row in conn.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing_tables = [name for name in EXPECTED_TABLES
                          if name not in present_tables]
        checks.append(_check(
            "schema_consistency", not missing_tables,
            "every declared table is present" if not missing_tables
            else f"missing table(s): {', '.join(missing_tables)}"))

        present_indexes = {row["name"] for row in conn.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        missing_indexes = [name for name in EXPECTED_INDEXES
                           if name not in present_indexes]
        checks.append(_check(
            "indexes", not missing_indexes,
            f"{len(EXPECTED_INDEXES)} declared index(es) present"
            if not missing_indexes
            else f"missing index(es): {', '.join(missing_indexes)}"))

        orphans = conn.fetchall(
            "SELECT r.id, r.from_id, r.to_id FROM relationships r "
            "LEFT JOIN entities a ON a.id = r.from_id "
            "LEFT JOIN entities b ON b.id = r.to_id "
            "WHERE r.archived_at IS NULL AND (a.id IS NULL OR b.id IS NULL)")
        checks.append(_check(
            "orphan_records", not orphans,
            "every live relationship has both ends" if not orphans
            else f"{len(orphans)} relationship(s) point at a record that is "
                 f"not there; unlink them through the contract so the removal "
                 f"is audited",
            orphans=[dict(row) for row in orphans[:25]]))

        unknown_types = conn.fetchall(
            "SELECT DISTINCT entity_type FROM entities")
        stray = [row["entity_type"] for row in unknown_types
                 if not entities.known(row["entity_type"])]
        checks.append(_check(
            "declared_types", not stray,
            "every stored record has a declared type" if not stray
            else f"stored type(s) nobody declares: {', '.join(sorted(stray))}. "
                 f"That is a row from another build, not a corruption."))

        integrity = conn.fetchone("PRAGMA integrity_check")
        verdict = (list(integrity.values())[0] if integrity else "unknown")
        checks.append(_check("integrity_check", verdict == "ok", str(verdict)))

        checks.append(_check(
            "migration_status", True,
            f"schema version {store.schema_version(conn)}; no migration steps "
            f"are declared because the schema has not changed shape yet"))

        checks.append(_backup_check())

        checks.append(_check(
            "disk_usage", True,
            f"{_size(store.database_path())} bytes in the store file"))

        failing = [check for check in checks if not check["passed"]]
        return {
            "status": OK if not failing else DEGRADED,
            "checks": checks,
            "failing": [check["check"] for check in failing],
            "repaired": [],
            "note": "no repair is ever performed automatically (§29).",
        }
    except (sqlite3.Error, OSError) as bad:
        # A DIAGNOSIS THAT CRASHES ON A DAMAGED STORE IS NO DIAGNOSIS. This
        # method had a try/finally and no except, so a mid-run failure
        # propagated and /diagnostics returned an unhandled 500 - at exactly
        # the moment somebody was asking it what was wrong. It reports what it
        # managed to check and why it stopped.
        checks.append(_check("diagnostics_completed", False,
                             f"{type(bad).__name__}: {bad}"))
        return {
            "status": DEGRADED,
            "checks": checks,
            "failing": [check["check"] for check in checks
                        if not check["passed"]],
            "repaired": [],
            "note": "the diagnosis stopped early; the checks above are the "
                    "ones that ran. No repair is ever performed automatically "
                    "(§29).",
        }
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _check(name: str, passed: bool, detail: str, **extra) -> dict:
    return {"check": name, "passed": bool(passed), "detail": detail, **extra}


# How old the newest verified backup may be before this reads as a problem.
# The schedule is daily, so two days means a run was missed rather than that
# one is merely due.
STALE_BACKUP_DAYS = 2


def _last_backup() -> dict | None:
    """§28's `last_backup`, from the catalogue on disk.

    Reads the manifests rather than a table, for the reason `dba/backup.py`
    gives: a record of your backups kept inside the database you are restoring
    is a record you have lost when you need it."""
    try:
        from dba import backup

        latest = backup.current()
        if latest is None:
            everything = backup.catalogue()
            if not everything:
                return None
            newest = everything[0]
            return {"backup_id": newest.backup_id, "taken_at": newest.taken_at,
                    "status": newest.status, "verified": False,
                    "note": "the newest backup has not passed verification, so "
                            "it is not the current one (§26)"}
        return {"backup_id": latest.backup_id, "taken_at": latest.taken_at,
                "status": latest.status, "verified": True,
                "recovery_point": latest.recovery_point,
                "schema_version": latest.schema_version}
    except Exception as bad:  # noqa: BLE001 - health never fails on a sub-check
        return {"error": f"{type(bad).__name__}: {bad}"}


def _backup_check() -> dict:
    """§29's backup age, answered from what is actually on disk.

    It used to fail on purpose because backup did not exist. It now fails for
    real reasons only: nothing taken, nothing verified, or nothing recent."""
    from datetime import datetime, timedelta, timezone

    try:
        from dba import backup

        everything = backup.catalogue()
        if not everything:
            return _check("backup_age", False,
                          "no backup has ever been taken. Take one: "
                          "POST /backups, or dba.backup.take().")
        latest = backup.current()
        if latest is None:
            return _check(
                "backup_age", False,
                f"{len(everything)} backup(s) on disk and none verified. An "
                f"untested backup is a belief rather than a backup (§26).")
        taken = datetime.fromisoformat(latest.taken_at)
        if taken.tzinfo is None:
            taken = taken.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - taken
        fresh = age <= timedelta(days=STALE_BACKUP_DAYS)
        return _check(
            "backup_age", fresh,
            f"the current verified backup {latest.backup_id} is "
            f"{age.days} day(s) old"
            + ("" if fresh else f", past the {STALE_BACKUP_DAYS}-day limit; a "
                                f"scheduled run has been missed"))
    except Exception as bad:  # noqa: BLE001
        return _check("backup_age", False, f"{type(bad).__name__}: {bad}")


def _entity_counts(conn: Database) -> dict[str, int]:
    return {entity_type.name: records.count(conn, entity_type.name)
            for entity_type in entities.all_types()}


def _one(conn: Database, sql: str) -> int:
    row = conn.fetchone(sql)
    return int(row["n"]) if row else 0


def _size(path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
