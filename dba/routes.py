"""The APIs the DBA publishes, and the endpoints for asking it to build one.

    *"the agent seeking this service will seek to use the API provided by the
    DBA, and therefore the DBA is in charge of creating the APIs to be used by
    clients for storage and retrieval."* — Krish, 2026-09-21

So a consuming agent calls `/api/v1/task_handoff/create`. Not a generic
endpoint with a type parameter: a real, named, versioned path that exists
because the DBA designed that capability and Krish published it, and that did
not exist the day before. §36's *"they should know the DBA Agent's published
interface"* is literally true - `gateway/` and `backend/` contain no knowledge
of this schema, and nothing about the database is visible through it.

## How the path exists without a file being written

One parameterised route resolves `{capability}/{operation}` against the
published declarations on every request. The alternative - mutating FastAPI's
routing table as capabilities are published - buys an identical URL surface and
costs a process whose behaviour depends on the order things happened in, which
is a debugging problem nobody should inherit. What a client sees is the same
either way, and what a client sees is the contract.

An operation the capability did not declare is a **404 on that path**, not a
422 on a shared one: an event log that declares no `update` has no
`/update` endpoint, which is the claim that archetype makes about itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from dba import (agent as agent_module, apispec, capability as capability_module,
                 contract, design as design_module, develop, explain,
                 permissions, registry, store, tamil)

router = APIRouter()


def _authenticate(agent: str | None, token: str | None) -> str:
    """The same check `/request` makes. Imported rather than duplicated so the
    two cannot drift into two different ideas of who is calling."""
    from dba.main import _authenticate as authenticate

    return authenticate(agent, token)


# --- the published capabilities -----------------------------------------------


@router.get("/capabilities")
def list_capabilities(x_dba_agent: str | None = Header(default=None),
                      x_dba_token: str | None = Header(default=None)):
    """What the DBA currently serves, and where (§5, §36).

    Authenticated like everything else. The first version was not, and an
    unauthenticated caller could read the whole inventory - including the
    declarations of capabilities that were designed and rejected, which are
    kept on purpose (§30) and are nobody else's business."""
    _authenticate(x_dba_agent, x_dba_token)
    conn = store.connect()
    try:
        store.init_schema(conn)
        registry.sync_entities(conn)
        return {
            "published": [
                {
                    "capability": declared.name,
                    "version": declared.version,
                    "purpose": declared.purpose,
                    "base_path": declared.route_prefix,
                    "operations": list(declared.operations),
                    "contract": f"/capabilities/{declared.name}",
                    "documentation": f"/capabilities/{declared.name}/docs",
                }
                for declared in registry.published(conn)
            ],
            "inventory": registry.inventory(conn),
        }
    finally:
        conn.close()


@router.get("/capabilities/{name}")
def capability_contract(name: str, version: int | None = None,
                        x_dba_agent: str | None = Header(default=None),
                        x_dba_token: str | None = Header(default=None)):
    """§25's contract, generated from the declaration."""
    _authenticate(x_dba_agent, x_dba_token)
    conn = store.connect()
    try:
        store.init_schema(conn)
        declared = _published(conn, name, version)
        return apispec.contract_for(declared)
    finally:
        conn.close()


def _published(conn, name: str, version: int | None):
    """A published declaration, or a 404.

    Goes through `registry.published` rather than `registry.get`, which reads
    by key and ignores status - so `?version=` on the first version of this
    handler would serve a draft or a rejected design to anyone who guessed the
    number. A contract is a promise about what is serving."""
    candidates = [item for item in registry.published(conn) if item.name == name]
    if version is not None:
        candidates = [item for item in candidates if item.version == version]
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=(f"no published capability {name!r}"
                    + (f" at v{version}" if version else "") + "."))
    return max(candidates, key=lambda item: item.version)


@router.get("/capabilities/{name}/docs", response_class=PlainTextResponse)
def capability_docs(name: str, version: int | None = None,
                    x_dba_agent: str | None = Header(default=None),
                    x_dba_token: str | None = Header(default=None)):
    """§5's "document APIs", generated so it cannot describe a field that is
    not there."""
    _authenticate(x_dba_agent, x_dba_token)
    conn = store.connect()
    try:
        store.init_schema(conn)
        return apispec.markdown(_published(conn, name, version))
    finally:
        conn.close()


# --- calling one --------------------------------------------------------------


@router.post("/api/v{version}/{name}/{operation}")
def call_capability(version: int, name: str, operation: str,
                    payload: dict = Body(default=None),
                    x_dba_agent: str | None = Header(default=None),
                    x_dba_token: str | None = Header(default=None)):
    """One operation on one published capability.

    This is the endpoint §4's diagram means by "DBA API". A consuming agent
    knows this path and the contract at `/capabilities/{name}`; it does not
    know the database, the schema behind it, or that the DBA exists as a
    process."""
    agent = _authenticate(x_dba_agent, x_dba_token)

    conn = store.connect()
    try:
        store.init_schema(conn)
        registry.sync_entities(conn)
        # THE VERSION THE CALLER ASKED FOR, not the newest one.
        #
        # Serving `current` meant publishing v2 turned every existing v1
        # caller's path into a 404 - which is the exact failure §26 exists to
        # prevent, arriving from the code that was supposed to prevent it.
        # Both versions serve until the old one is retired.
        declared = None
        for candidate in registry.published(conn):
            if candidate.name == name and candidate.version == version:
                declared = candidate
                break
        if declared is None:
            serving = sorted(item.version for item in registry.published(conn)
                             if item.name == name)
            raise HTTPException(
                status_code=404,
                detail=(f"no capability {name!r} at v{version} is published."
                        + (f" Published version(s): "
                           f"{', '.join(f'v{v}' for v in serving)}."
                           if serving else "")))
        if operation not in declared.operations:
            raise HTTPException(
                status_code=404,
                detail=(f"{name} v{version} does not offer {operation!r}. It "
                        f"offers: {', '.join(declared.operations)}. That is a "
                        f"statement about this capability rather than a "
                        f"rejected request - an append-only log has no update "
                        f"endpoint."))
    finally:
        conn.close()

    body = dict(payload or {})
    claimed = body.pop("requested_by", None)
    if claimed is not None and claimed != agent:
        raise HTTPException(
            status_code=400,
            detail=f"requested_by={claimed!r} does not match the authenticated "
                   f"agent {agent!r}.")
    body.pop("action", None)
    body.pop("entity_type", None)
    try:
        request = contract.Request.from_dict(
            {**body, "action": operation, "entity_type": name,
             "requested_by": agent})
    except (ValueError, TypeError) as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad

    response = agent_module.default_agent().handle(request)
    from dba.main import _http_status

    out = response.to_dict()
    out["explanation"] = explain.explain(response)
    out["explanation_ta"] = tamil.explain(response)
    out["capability"] = f"{name}@{version}"
    return JSONResponse(status_code=_http_status(response), content=out)


# --- asking for a new one -----------------------------------------------------


@router.post("/capabilities/design")
def design_capability(payload: dict = Body(...),
                      x_dba_agent: str | None = Header(default=None),
                      x_dba_token: str | None = Header(default=None)):
    """§34 step 1: *"I need persistent information for this new task."*

    Returns either the questions the DBA will not answer for itself, or a
    staged capability with its contract, its documentation and the evidence
    that its own tests pass."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    task = (payload.get("task") or "").strip()
    if not task:
        raise HTTPException(status_code=400,
                            detail="a requirement needs a 'task' - the sentence "
                                   "describing what must be stored.")
    retention = payload.get("retention")
    try:
        requirement = design_module.Requirement(
            task=task,
            requested_by=agent,
            name=payload.get("name"),
            readers=tuple(payload.get("readers") or ()),
            writers=tuple(payload.get("writers") or ()),
            retention=(capability_module.Retention.from_dict(retention)
                       if retention else None),
            sensitive=bool(payload.get("sensitive", False)),
            extra_fields=dict(payload.get("extra_fields") or {}),
            relates_to=tuple(tuple(pair)
                             for pair in payload.get("relates_to") or ()),
            deletable=payload.get("deletable"),
            answers=dict(payload.get("answers") or {}))
    except (ValueError, TypeError) as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad

    outcome = develop.request_capability(requirement)
    status = {"clarification_required": 200, "staged": 200,
              "not_ready": 409}.get(outcome["status"], 200)
    return JSONResponse(status_code=status, content=outcome)


@router.get("/capabilities/proposals/waiting")
def waiting_proposals(x_dba_agent: str | None = Header(default=None),
                      x_dba_token: str | None = Header(default=None)):
    """What the DBA has built and is waiting on Krish for."""
    _authenticate(x_dba_agent, x_dba_token)
    return {"waiting": develop.proposals()}


@router.post("/capabilities/{key}/publish")
def publish_capability(key: str, payload: dict = Body(default=None),
                       x_dba_agent: str | None = Header(default=None),
                       x_dba_token: str | None = Header(default=None)):
    """§34 step 9. Refused for any agent without `administer`, which the DBA
    deliberately does not hold."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    outcome = develop.publish(key, accepted_by=agent)
    return JSONResponse(
        status_code=200 if outcome["status"] == "published" else 403,
        content=outcome)


@router.post("/capabilities/{key}/reject")
def reject_capability(key: str, payload: dict = Body(...),
                      x_dba_agent: str | None = Header(default=None),
                      x_dba_token: str | None = Header(default=None)):
    agent = _authenticate(x_dba_agent, x_dba_token)
    why = (payload.get("why") or "").strip()
    if not why:
        raise HTTPException(
            status_code=400,
            detail="a rejection needs a reason - §30 keeps it as learning "
                   "material, and 'no' teaches nothing.")
    if permissions.ADMINISTER not in permissions.permissions_of(agent):
        raise HTTPException(status_code=403,
                            detail=f"{agent!r} cannot reject a capability.")
    return develop.reject(key, why=why, rejected_by=agent)


# --- backup and restore (§25, §26) -------------------------------------------


def _require_administer(agent: str) -> None:
    if permissions.ADMINISTER not in permissions.permissions_of(agent):
        raise HTTPException(
            status_code=403,
            detail=f"{agent!r} cannot operate backups: that needs "
                   f"{permissions.ADMINISTER!r}.")


@router.get("/backups")
def list_backups(x_dba_agent: str | None = Header(default=None),
                 x_dba_token: str | None = Header(default=None)):
    """The catalogue, and §26's documentation: how to restore, which backup is
    current, the recovery point, the schema version, the validation
    procedure."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    _require_administer(agent)
    from dba import backup

    return {
        **backup.describe(),
        "backups": [item.to_dict() for item in backup.catalogue()],
    }


@router.post("/backups")
def take_backup(payload: dict = Body(default=None),
                x_dba_agent: str | None = Header(default=None),
                x_dba_token: str | None = Header(default=None)):
    """§25: take a full, timestamped, verified backup now.

    Verified means restored: the response carries the checks, and a backup
    that failed them comes back as a 409 rather than as a cheerful id."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    _require_administer(agent)
    from dba import audit as audit_module, backup

    try:
        taken = backup.take(reason=backup.REQUESTED)
    except backup.BackupRefused as refused:
        _audit_backup(agent, "take_backup", str(refused), succeeded=False)
        return JSONResponse(status_code=409,
                            content={"status": "refused", "why": str(refused)})
    _audit_backup(agent, "take_backup",
                  f"{taken.backup_id} ({taken.bytes} bytes, {taken.status})",
                  succeeded=True)
    del audit_module
    # Nested rather than flattened: a Backup carries its own `status`
    # (verified / unverified / failed), and spreading it here silently
    # overwrote the response's. Two different meanings under one key is a
    # field nobody can read correctly.
    return {"status": "taken", "backup": taken.to_dict()}


@router.post("/backups/run-if-due")
def backup_if_due(x_dba_agent: str | None = Header(default=None),
                  x_dba_token: str | None = Header(default=None)):
    """§25's scheduled backup, for whatever actually does the scheduling.

    Nothing in this repository runs on a timer by itself, so this is the
    endpoint a cron entry or a timer calls - the same posture
    `app/self_diagnosis.py` takes about its own schedule. Idempotent through
    the catalogue: a backup already taken today is not taken twice."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    _require_administer(agent)
    from dba import backup

    try:
        taken = backup.run_if_due()
    except backup.BackupRefused as refused:
        return JSONResponse(status_code=409,
                            content={"status": "refused", "why": str(refused)})
    if taken is None:
        return {"status": "not_due",
                "why": "today's backup already exists, or it is before the "
                       "hour config/dba.yaml schedules"}
    _audit_backup(agent, "take_backup", f"{taken.backup_id} (scheduled)",
                  succeeded=True)
    return {"status": "taken", "backup": taken.to_dict()}


@router.get("/backups/{backup_id}")
def one_backup(backup_id: str,
               x_dba_agent: str | None = Header(default=None),
               x_dba_token: str | None = Header(default=None)):
    agent = _authenticate(x_dba_agent, x_dba_token)
    _require_administer(agent)
    from dba import backup

    found = backup.get(backup_id)
    if found is None:
        raise HTTPException(status_code=404,
                            detail=f"no backup {backup_id!r} is on disk.")
    return found.to_dict()


@router.post("/backups/{backup_id}/verify")
def verify_backup(backup_id: str,
                  x_dba_agent: str | None = Header(default=None),
                  x_dba_token: str | None = Header(default=None)):
    """§26: restore it somewhere harmless and check it is really there.

    Available on demand as well as at backup time, because a file that was
    good a month ago is not evidence about the disk it is sitting on today."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    _require_administer(agent)
    from dba import backup

    found = backup.get(backup_id)
    if found is None:
        raise HTTPException(status_code=404,
                            detail=f"no backup {backup_id!r} is on disk.")
    verification = backup.verify(found)
    _audit_backup(agent, "verify_backup",
                  f"{backup_id}: {verification['why']}",
                  succeeded=verification["passed"])
    return JSONResponse(status_code=200 if verification["passed"] else 409,
                        content={"backup_id": backup_id, **verification})


@router.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: str, payload: dict = Body(default=None),
                   x_dba_agent: str | None = Header(default=None),
                   x_dba_token: str | None = Header(default=None)):
    """§26: replace the live database with a backup.

    The most destructive operation this service has. It needs `administer`,
    an explicit `confirmed`, and a verified backup - and it backs the current
    state up before replacing anything, so a restore that was a mistake is
    itself undoable."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    _require_administer(agent)
    from dba import backup

    body = payload or {}
    try:
        outcome = backup.restore(
            backup_id, accepted_by=agent,
            confirmed=bool(body.get("confirmed", False)),
            allow_unverified=bool(body.get("allow_unverified", False)))
    except backup.BackupRefused as refused:
        _audit_backup(agent, "restore_backup", str(refused), succeeded=False)
        return JSONResponse(status_code=409,
                            content={"status": "refused", "why": str(refused)})
    _audit_backup(agent, "restore_backup",
                  f"restored {backup_id} to {outcome['recovery_point']}",
                  succeeded=True)
    return {"status": "restored", **outcome}


def _audit_backup(agent: str, action: str, detail: str, *,
                  succeeded: bool) -> None:
    """Record a backup operation in the audit trail.

    Written after the operation, on its own connection, because a restore
    replaces the database underneath any connection opened before it - an
    audit row written into the file that is about to be overwritten is a row
    that never happened."""
    from dba import audit

    conn = store.connect()
    try:
        store.init_schema(conn)
        audit.record(conn, requesting_agent=agent, actor=agent, action=action,
                     result=audit.COMMITTED if succeeded else audit.REFUSED,
                     succeeded=succeeded, source=audit.SOURCE_MAINTENANCE,
                     new={"detail": detail[:400]})
    except Exception:  # noqa: BLE001 - the operation stands even unaudited
        pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


@router.get("/experience")
def dba_experience(x_dba_agent: str | None = Header(default=None),
                   x_dba_token: str | None = Header(default=None)):
    """§11: what the DBA has learned from designing (its own, persisted)."""
    _authenticate(x_dba_agent, x_dba_token)
    from dba import experience

    conn = store.connect()
    try:
        store.init_schema(conn)
        return {
            "meta": experience.meta_report(conn),
            "lessons": experience.lessons(conn),
            "recent_designs": experience.episodes(conn, limit=20),
        }
    finally:
        conn.close()
