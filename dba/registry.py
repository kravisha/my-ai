"""Where capabilities live, and the gate they pass through to serve traffic.

## The one rule this module exists to enforce

**The agent that designs a capability cannot be the one that publishes it.**

`publish` requires an accepting agent holding `administer`, and `dba/permissions.POLICY`
does not give the DBA that permission. So the sequence is structural rather
than procedural: the DBA designs, stages and self-tests; Krish accepts; only
then does anything serve. §31 calls that stage 2, and the same shape already
guards `register_learned_skill` - a system that can bring its own new surfaces
into service has granted itself authority, however good its tests were.

## Published declarations are immutable

A published row is never updated except to retire it. A change publishes a new
version beside the old one (§26), and both serve until the old one is retired,
so an agent written against v1 does not break because the DBA improved
something. `capability.compare` decides whether a change is breaking; this
module refuses to publish a breaking change under the same version number.
"""

from __future__ import annotations

import json
import threading

from backend.db import Database, now_iso
from dba import capability, entities, ids, permissions, store


class RegistryRefused(RuntimeError):
    """A lifecycle move that is not allowed, carrying why."""


def save_draft(conn: Database, designed: capability.Capability, *,
               requirement: str = "", designed_by: str = permissions.DBA) -> str:
    """Record a newly designed capability. Serves nothing."""
    key = designed.key
    if conn.fetchone("SELECT capability_key FROM capabilities WHERE capability_key = ?",
                     (key,)):
        raise RegistryRefused(
            f"{key} already exists. A capability version is written once; a "
            f"change is a new version (§26).")
    conn.execute(
        "INSERT INTO capabilities (capability_key, name, version, status, "
        "declaration_json, fingerprint, requirement, designed_at, designed_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, designed.name, designed.version, capability.DRAFT,
         json.dumps(designed.to_dict(), ensure_ascii=False),
         designed.fingerprint(), requirement or designed.requirement,
         now_iso(), designed_by))
    return key


def stage(conn: Database, key: str, *, self_check: dict,
          test_report: dict) -> None:
    """Move a draft to staged, carrying the evidence that it works.

    Refused unless both the self-check and the tests passed, because "staged"
    is the state that says the DBA has done its part - a staged capability with
    failing tests would put the decision to publish in front of Krish with the
    work half done."""
    row = _row(conn, key)
    if row["status"] != capability.DRAFT:
        raise RegistryRefused(f"{key} is {row['status']}, not a draft.")
    if not self_check.get("passed"):
        raise RegistryRefused(
            f"{key} did not pass its own design self-check (§28): "
            f"{', '.join(self_check.get('failing', [])) or 'unknown'}")
    if not test_report.get("passed"):
        raise RegistryRefused(
            f"{key} did not pass its generated tests (§27): "
            f"{test_report.get('failed', 0)} of {test_report.get('total', 0)} "
            f"failed")
    conn.execute(
        "UPDATE capabilities SET status = ?, staged_at = ?, self_check_json = ?, "
        "test_report_json = ? WHERE capability_key = ?",
        (capability.STAGED, now_iso(),
         json.dumps(self_check, ensure_ascii=False, default=str),
         json.dumps(test_report, ensure_ascii=False, default=str), key))


def publish(conn: Database, key: str, *, accepted_by: str) -> capability.Capability:
    """Bring a staged capability into service. Krish's step, not the DBA's."""
    row = _row(conn, key)
    if row["status"] != capability.STAGED:
        raise RegistryRefused(
            f"{key} is {row['status']}. Only a staged capability - one whose "
            f"self-check and tests have passed - can be published.")
    if permissions.ADMINISTER not in permissions.permissions_of(accepted_by):
        raise RegistryRefused(
            f"{accepted_by!r} cannot publish a capability: that needs "
            f"{permissions.ADMINISTER!r}, which the designing agent "
            f"deliberately does not hold. The DBA designs and tests; bringing "
            f"a new data surface into service is a separate hand.")

    declared = capability.Capability.from_dict(json.loads(row["declaration_json"]))
    live = current(conn, declared.name)
    if live is not None:
        difference = capability.compare(live, declared)
        if difference["verdict"] == capability.BREAKING \
                and declared.version <= live.version:
            raise RegistryRefused(
                f"{key} changes {live.key} in ways that break an existing "
                f"caller ({'; '.join(difference['breaking'])}) without a new "
                f"version number. Publish it as v{live.version + 1} and retire "
                f"the old one when nothing needs it (§26).")

    conn.execute(
        "UPDATE capabilities SET status = ?, published_at = ?, accepted_by = ? "
        "WHERE capability_key = ?",
        (capability.PUBLISHED, now_iso(), accepted_by, key))
    store.bump_capabilities_version(conn)
    sync_entities(conn)
    return declared


def reject(conn: Database, key: str, *, why: str) -> None:
    """Krish said no. Kept rather than deleted: §30 calls a correction learning
    material, and a rejected design nobody can read teaches nothing."""
    row = _row(conn, key)
    if row["status"] not in (capability.DRAFT, capability.STAGED):
        raise RegistryRefused(f"{key} is {row['status']} and cannot be rejected.")
    # MERGED, NOT OVERWRITTEN. The first version replaced `test_report_json`
    # with the rejection reason and destroyed the staged test evidence - which
    # is the material §30 says to keep, thrown away by the function whose
    # docstring says it keeps it.
    try:
        report = json.loads(row["test_report_json"] or "{}")
    except (TypeError, ValueError):
        report = {}
    report["rejected_because"] = why
    conn.execute(
        "UPDATE capabilities SET status = ?, test_report_json = ? "
        "WHERE capability_key = ?",
        (capability.REJECTED, json.dumps(report, ensure_ascii=False,
                                         default=str), key))


def retire(conn: Database, key: str, *, accepted_by: str) -> None:
    """Stop serving a published version (§5's "retire or replace safely")."""
    row = _row(conn, key)
    if row["status"] != capability.PUBLISHED:
        raise RegistryRefused(f"{key} is {row['status']}, not published.")
    if permissions.ADMINISTER not in permissions.permissions_of(accepted_by):
        raise RegistryRefused(
            f"{accepted_by!r} cannot retire a capability: that needs "
            f"{permissions.ADMINISTER!r}. Withdrawing a surface other agents "
            f"call is as consequential as publishing one.")
    conn.execute(
        "UPDATE capabilities SET status = ?, retired_at = ? WHERE capability_key = ?",
        (capability.RETIRED, now_iso(), key))
    store.bump_capabilities_version(conn)
    sync_entities(conn)


# --- reading ------------------------------------------------------------------


def _row(conn: Database, key: str) -> dict:
    row = conn.fetchone("SELECT * FROM capabilities WHERE capability_key = ?",
                        (key,))
    if row is None:
        raise RegistryRefused(f"no capability {key!r} has been designed.")
    return row


def get(conn: Database, key: str) -> capability.Capability:
    return capability.Capability.from_dict(
        json.loads(_row(conn, key)["declaration_json"]))


def record(conn: Database, key: str) -> dict:
    """The stored row: status, evidence, who accepted it and when."""
    row = dict(_row(conn, key))
    for field_name in ("declaration_json", "self_check_json", "test_report_json"):
        if row.get(field_name):
            try:
                row[field_name[:-5]] = json.loads(row[field_name])
            except (TypeError, ValueError):
                pass
        row.pop(field_name, None)
    return row


def published(conn: Database) -> list[capability.Capability]:
    rows = conn.fetchall(
        "SELECT declaration_json FROM capabilities WHERE status = ? "
        "ORDER BY name ASC, version ASC", (capability.PUBLISHED,))
    return [capability.Capability.from_dict(json.loads(row["declaration_json"]))
            for row in rows]


def current(conn: Database, name: str) -> capability.Capability | None:
    """The highest published version of one capability."""
    row = conn.fetchone(
        "SELECT declaration_json FROM capabilities WHERE name = ? AND status = ? "
        "ORDER BY version DESC LIMIT 1", (name, capability.PUBLISHED))
    return (capability.Capability.from_dict(json.loads(row["declaration_json"]))
            if row else None)


def versions(conn: Database, name: str) -> list[dict]:
    rows = conn.fetchall(
        "SELECT capability_key, version, status, designed_at, published_at, "
        "retired_at, accepted_by FROM capabilities WHERE name = ? "
        "ORDER BY version ASC", (name,))
    return [dict(row) for row in rows]


def inventory(conn: Database) -> list[dict]:
    """Everything designed, in any state. What §29's reuse check reads, and
    what a person looks at to see what the DBA has built."""
    rows = conn.fetchall(
        "SELECT capability_key, name, version, status, requirement, "
        "designed_at, published_at, accepted_by FROM capabilities "
        "ORDER BY name ASC, version ASC")
    return [dict(row) for row in rows]


def identical(conn: Database, designed: capability.Capability) -> dict | None:
    """An existing staged or published version with the same declaration.

    By fingerprint, which is a hash of the whole declaration - so this is
    "exactly this, already built", not "something like it". A draft or a
    rejected design does not count: a draft never got as far as evidence, and
    a rejected one was looked at and turned down, so offering it back would be
    answering a question with the answer somebody already refused."""
    row = conn.fetchone(
        "SELECT capability_key, status FROM capabilities "
        "WHERE name = ? AND fingerprint = ? AND status IN (?, ?) "
        "ORDER BY version DESC LIMIT 1",
        (designed.name, designed.fingerprint(), capability.PUBLISHED,
         capability.STAGED))
    return dict(row) if row else None


def next_version(conn: Database, name: str) -> int:
    row = conn.fetchone("SELECT MAX(version) AS v FROM capabilities WHERE name = ?",
                        (name,))
    return int(row["v"] or 0) + 1


# --- keeping the live type registry in step -----------------------------------

# THE ADOPTED TYPES ARE PROCESS-GLOBAL AND THE DBA IS A THREADED SERVICE.
#
# `sync_entities` clears and refills them, and `selfcheck.run_tests` repoints
# them at a throwaway database for the length of a battery. A review reproduced
# the consequence: a reader thread hitting that window got `schema_mismatch`
# for a capability that was published and serving, and `grants_for` could
# return None - which fails *open*, because None means "built-in, the global
# policy is the whole answer".
#
# Reentrant because `selfcheck` holds it across calls that sync again.
_LOCK = threading.RLock()
_SYNCED_AT: int | None = None
# name -> {agent: frozenset(permissions)} for every published capability.
# Held beside the adopted types because they are read on the same path: a
# request names an entity type, and the answer to "may you?" needs both the
# global policy and this capability's own grant.
_GRANTS: dict[str, dict[str, frozenset[str]]] = {}


def grants_for(name: str) -> dict[str, frozenset[str]] | None:
    """What one published capability grants, or None if it is not one.

    None and `{}` mean different things and the caller must tell them apart:
    None is "this is a built-in type, the global policy is the whole answer",
    and `{}` is "this capability granted nobody anything", which denies.

    Read under the lock, because the half-second during which the table is
    empty is exactly when None would be returned for a capability that has a
    grant table - and that answer fails open."""
    with _LOCK:
        return _GRANTS.get(name)


def hold():
    """The lock, for a caller that must keep the adopted registry still.

    `selfcheck.run_tests` points it at a throwaway database and puts it back;
    nothing may read it in between."""
    return _LOCK


def sync_entities(conn: Database, *, force: bool = False) -> int:
    """Adopt every published capability's type, and drop the rest.

    Called on every request through a version counter rather than a table scan,
    so a capability retired one second ago stops serving on the next call
    rather than when a process happens to restart."""
    global _SYNCED_AT
    with _LOCK:
        stamp = store.capabilities_version(conn)
        if not force and _SYNCED_AT == stamp:
            return stamp
        entities.forget_adopted()
        _GRANTS.clear()
        for declared in published(conn):
            # A published capability that shadowed a built-in would make this
            # raise on every request from here on. `dba/design.py` refuses to
            # design one; this skips it rather than taking the process down if
            # one ever arrives from an older build.
            if entities.is_built_in(declared.name):
                continue
            entities.adopt(declared.entity_type)
            _GRANTS[declared.name] = {
                agent: frozenset(held)
                for agent, held in declared.grants.items()}
        _SYNCED_AT = stamp
        return stamp


def reset_sync() -> None:
    """Forget that anything was synced. For test isolation, where two tests
    share a process but not a database."""
    global _SYNCED_AT
    with _LOCK:
        _SYNCED_AT = None
        _GRANTS.clear()
        entities.forget_adopted()
