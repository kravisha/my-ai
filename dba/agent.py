"""The DBA Agent itself: one entry point, and everything that must happen
around every request (§8, §14, §22, §24, §44).

## Why the cross-cutting work is here and not in the operations

Permissions, idempotency, the transaction boundary and the audit event apply to
every operation identically. Putting them in each one would mean seventeen
places to forget the audit event, and the one that forgot it would be the one
nobody noticed until an investigation needed it. So `dba/operations.py` holds
only what is different between actions, and this module wraps all of them the
same way.

## The transaction boundary, and §49's open question about sessions

§8 lists `begin_transaction` / `commit_transaction` / `rollback_transaction`,
and §49 leaves the transport open. Those two interact: a transaction held open
*across* requests needs server-side session state, which pins a connection and
leaves the database locked when a caller dies mid-unit. So atomicity is offered
as a **batch** - `handle_many`, which runs a list of requests in one
transaction and rolls the whole list back if any step fails (§48's TEST D, and
§31's atomic mode). The three transaction actions are the batch's explicit
delimiters and are refused outside one, with a message saying so.

That is a real decision rather than an omission, and it is recorded in
`docs/DBA_AGENT.md` as one.

## §24, which is the rule that decides what this module catches

    *"do not fabricate a successful response ... do not pretend a write
    completed"*

So the outermost handler catches database failure and returns
`database_unavailable`, and it catches everything else as `internal_error` -
but neither ever returns a `success`. An exception escaping to a caller that
treats exceptions as failures would be *safe*; an exception swallowed into a
cheerful response would not be, and that is the direction this code is written
against.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from backend.db import Contended, Database, now_iso
from dba import (askback, audit, contract, entities, ids, operations,
                 permissions, records, store)


class _Rollback(RuntimeError):
    """Raised to unwind an atomic batch. Never leaves this module."""

    def __init__(self, responses: list[contract.Response]):
        super().__init__("batch rolled back")
        self.responses = responses


class DBAgent:
    """The agent. Holds no request state between calls on purpose.

    A connection per call rather than one held open, for the reason
    `gateway/main.py` gives about its own: a long-lived sqlite3 connection
    shared across threads is a defect waiting for concurrency, and this agent
    will be called from a web handler."""

    def __init__(self, connect=None):
        self._connect = connect or store.connect

    # --- the entry point ------------------------------------------------------

    def handle(self, request: contract.Request) -> contract.Response:
        """One request in, one structured response out. Never raises."""
        try:
            conn = self._connect()
        except (sqlite3.Error, OSError) as bad:
            return contract.failure(
                request, code=contract.DATABASE_UNAVAILABLE,
                message=(f"the database could not be opened: {bad}. Nothing was "
                         f"read and nothing was written."),
                details={"retry_safe": True})
        try:
            store.init_schema(conn)
            return self._guarded(conn, request)
        except Contended as bad:
            return contract.failure(
                request, code=contract.DATABASE_UNAVAILABLE,
                message=f"the database was busy and the request was not applied: {bad}")
        except (sqlite3.Error, OSError) as bad:
            return self._report_failure(conn, request, bad,
                                        code=contract.DATABASE_UNAVAILABLE)
        except Exception as bad:  # noqa: BLE001 - see the module docstring
            return self._report_failure(conn, request, bad,
                                        code=contract.INTERNAL_ERROR)
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - a close that fails is not the answer
                pass

    def handle_many(self, requests: list[contract.Request], *,
                    atomic: bool = True) -> list[contract.Response]:
        """A unit of work (§31, §48 TEST D).

        In atomic mode the first step that does not succeed unwinds every
        change the batch made, including the audit rows describing them -
        which is correct, because an audit row for a change that was rolled
        back is §44's failure in the one table that must be trustworthy. A
        single event recording the failed batch is written afterwards, outside
        the transaction, so the attempt is not invisible."""
        if not requests:
            return []
        try:
            conn = self._connect()
        except (sqlite3.Error, OSError) as bad:
            return [contract.failure(
                request, code=contract.DATABASE_UNAVAILABLE,
                message=f"the database could not be opened: {bad}")
                for request in requests]
        try:
            store.init_schema(conn)
            if not atomic:
                return [self._guarded(conn, request) for request in requests]

            responses: list[contract.Response] = []
            try:
                with conn.transaction():
                    for request in requests:
                        response = self._guarded(conn, request,
                                                 own_transaction=False)
                        responses.append(response)
                        if not response.ok:
                            raise _Rollback(responses)
            except _Rollback as unwound:
                responses = list(unwound.responses)
                failed = responses[-1]
                audit.record(
                    conn, requesting_agent=requests[0].requested_by,
                    actor=requests[0].actor, action="batch",
                    result=audit.FAILED, succeeded=False,
                    request_id=requests[0].request_id,
                    reason=(f"step {len(responses)} of {len(requests)} did not "
                            f"succeed; the whole batch was rolled back"),
                    new={"failed_step": len(responses),
                         "status": failed.status,
                         "error": (failed.error or {}).get("error_code")})
                rolled_back = tuple(
                    [f"rolled back: step {len(responses)} of {len(requests)} "
                     f"did not succeed, so no step in this batch was applied."])
                return [contract.Response(
                    status=r.status, action=r.action, request_id=r.request_id,
                    entity_type=r.entity_type, entity_id=r.entity_id,
                    changed=False, result=r.result,
                    warnings=r.warnings + rolled_back,
                    clarification=r.clarification, error=r.error)
                    for r in responses]
            return responses
        except (sqlite3.Error, OSError) as bad:
            return [contract.failure(
                request, code=contract.DATABASE_UNAVAILABLE,
                message=f"the batch did not run: {bad}") for request in requests]
        except Exception as bad:  # noqa: BLE001 - same rule as `handle`
            # `handle` has always returned a structured `internal_error`; this
            # method did not, so one bad value in a caller's criteria became an
            # unhandled 500 with no body on /batch. A batch must fail the same
            # way a single request does.
            return [contract.failure(
                request, code=contract.INTERNAL_ERROR,
                message=(f"{type(bad).__name__}: {bad}. The batch was not "
                         f"applied."),
                details={"exception": type(bad).__name__})
                for request in requests]
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    # --- the wrapper every operation goes through -----------------------------

    def _guarded(self, conn: Database, request: contract.Request, *,
                 own_transaction: bool = True) -> contract.Response:
        # Adopt whatever is published before anything looks a type up, so a
        # capability published a second ago serves and one retired a second
        # ago does not.
        from dba import registry

        registry.sync_entities(conn)

        entity_type = None
        if request.entity_type is not None:
            if not entities.known(request.entity_type):
                return self._refuse(
                    conn, request, code=contract.SCHEMA_MISMATCH,
                    message=(f"{request.entity_type!r} is not a declared entity "
                             f"type. Declared: "
                             f"{', '.join(t.name for t in entities.all_types())}."))
            entity_type = entities.get(request.entity_type)

        # --- §14, before anything is read or written --------------------------
        try:
            permissions.check(
                request.requested_by, request.action,
                classification=entity_type.classification if entity_type else None,
                writing=False if request.action == contract.VALIDATE else None,
                entity_type=request.entity_type,
                capability_grants=registry.grants_for(request.entity_type)
                if request.entity_type else None)
        except permissions.Refused as refused:
            return self._refuse(conn, request, code=contract.PERMISSION_DENIED,
                                message=str(refused),
                                details={"permission": refused.permission})

        # --- §22, before the operation runs at all ----------------------------
        replay = self._replay(conn, request)
        if replay is not None:
            return replay

        if request.action in (contract.BEGIN_TRANSACTION,
                              contract.COMMIT_TRANSACTION,
                              contract.ROLLBACK_TRANSACTION):
            return self._refuse(
                conn, request, code=contract.VALIDATION_ERROR,
                message=(f"{request.action} is a batch delimiter, not a standalone "
                         f"request. Atomicity is offered as a batch - send the "
                         f"whole unit of work together and it lands or rolls "
                         f"back together. A transaction held open across "
                         f"requests would pin a connection and lock the "
                         f"database when a caller stops talking."))

        run = (lambda: self._dispatch(conn, entity_type, request))
        if request.writes and not request.dry_run and own_transaction:
            with conn.transaction():
                response = run()
                if not response.ok:
                    # A refusal or a question inside its own transaction: the
                    # audit row belongs, the (absent) change does not.
                    self._audit(conn, request, response)
                    return response
                self._audit(conn, request, response)
                self._remember(conn, request, response)
                return response
        response = run()
        self._audit(conn, request, response)
        if request.writes:
            self._remember(conn, request, response)
        return response

    def _dispatch(self, conn: Database, entity_type, request):
        action = request.action
        needs_type = action in (contract.CREATE, contract.GET, contract.FIND,
                                contract.UPDATE, contract.ARCHIVE,
                                contract.DELETE_AUTHORIZED, contract.HISTORY,
                                contract.VALIDATE, contract.LIST,
                                contract.RECONCILE)
        if needs_type and entity_type is None:
            return contract.failure(
                request, code=contract.VALIDATION_ERROR,
                message=f"{action} needs an entity_type.")

        if action == contract.CREATE:
            return operations.create(conn, entity_type, request)
        if action == contract.GET:
            return operations.get(conn, entity_type, request)
        if action in (contract.FIND, contract.LIST):
            return operations.find(conn, entity_type, request)
        if action == contract.SEARCH:
            return operations.search(conn, entity_type, request)
        if action == contract.COUNT:
            return operations.count(conn, entity_type, request)
        if action == contract.HISTORY:
            return operations.history(conn, entity_type, request)
        if action == contract.VALIDATE:
            return operations.validate_only(conn, entity_type, request)
        if action == contract.UPDATE:
            return operations.update(conn, entity_type, request)
        if action == contract.ARCHIVE:
            return operations.archive(conn, entity_type, request)
        if action == contract.DELETE_AUTHORIZED:
            return operations.delete_authorized(conn, entity_type, request)
        if action == contract.LINK:
            return operations.link(conn, request)
        if action == contract.UNLINK:
            return operations.unlink(conn, request)
        if action == contract.RECONCILE:
            return contract.failure(
                request, code=contract.UNKNOWN_ACTION,
                message=("reconcile is specified (§12) and not implemented yet. "
                         "It is Phase 2 in §46, and saying so is better than a "
                         "stub that appears to reconcile something."))
        return contract.failure(
            request, code=contract.UNKNOWN_ACTION,
            message=f"{action!r} has no handler.")

    # --- §22 idempotency ------------------------------------------------------

    @staticmethod
    def fingerprint(request: contract.Request) -> str:
        """What makes two requests the same request.

        Deliberately excludes `requested_by`, `actor` and `reason`: replaying
        an import from a different process is still the same import, and it is
        the *effect* an idempotency key protects, not the provenance."""
        payload = json.dumps({
            "action": request.action, "entity_type": request.entity_type,
            "entity_id": request.entity_id, "data": request.data,
            "criteria": request.criteria,
        }, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _replay(self, conn: Database,
                request: contract.Request) -> contract.Response | None:
        # A DRY RUN IS NOT AN EFFECT. It neither replays nor is remembered, and
        # the first version got this exactly backwards: `_remember` stored the
        # dry run's `committed: false` result under the request id, so the real
        # write that followed was replayed as a success and never happened.
        # That is precisely the §44 lie this package exists to prevent, and it
        # arrived through the one mechanism whose whole job is to make a repeat
        # harmless.
        if not request.request_id or not request.writes or request.dry_run:
            return None
        row = conn.fetchone(
            "SELECT * FROM handled_requests WHERE request_id = ?",
            (request.request_id,))
        if row is None:
            return None

        if row["fingerprint"] != self.fingerprint(request):
            return self._refuse(
                conn, request, code=contract.CONFLICT_DETECTED,
                message=(f"request_id {request.request_id!r} was already used "
                         f"for a different {row['action']}. An idempotency key "
                         f"identifies one operation; reusing it for another "
                         f"would make replay protection meaningless."),
                details={"first_seen": row["at"], "first_action": row["action"]})

        stored = json.loads(row["response_json"])
        audit.record(conn, requesting_agent=request.requested_by,
                     actor=request.actor, action=request.action,
                     entity_type=request.entity_type,
                     entity_id=stored.get("entity_id"),
                     request_id=request.request_id, result=audit.REPLAYED,
                     succeeded=True, reason="same request_id, same request")
        return contract.Response(
            status=stored["status"], action=stored["action"],
            request_id=stored.get("request_id"),
            entity_type=stored.get("entity_type"),
            entity_id=stored.get("entity_id"),
            # NOT the stored `changed`: this call changed nothing. Reporting
            # the original's `true` would say a write happened that did not.
            changed=False,
            result=stored.get("result"),
            warnings=tuple(stored.get("warnings", [])) + (
                f"replayed: request_id {request.request_id!r} was already "
                f"handled at {row['at']}; the original result is returned and "
                f"nothing was written again.",),
            clarification=stored.get("clarification"),
            error=stored.get("error"))

    def _remember(self, conn: Database, request: contract.Request,
                  response: contract.Response) -> None:
        """Record a handled write so a replay returns it (§22).

        Only successes. A failed or questioned request has not happened, and
        remembering it would mean a caller that fixes its input and retries with
        the same id gets the old refusal back forever."""
        if not request.request_id or not response.ok or request.dry_run:
            return
        conn.execute(
            "INSERT OR IGNORE INTO handled_requests (request_id, fingerprint, "
            "action, entity_type, entity_id, response_json, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (request.request_id, self.fingerprint(request), request.action,
             request.entity_type, response.entity_id,
             json.dumps(response.to_dict(), ensure_ascii=False, default=str),
             now_iso()))

    # --- audit ----------------------------------------------------------------

    def _audit(self, conn: Database, request: contract.Request,
               response: contract.Response) -> None:
        if response.needs_answer:
            result = audit.CLARIFICATION_REQUESTED
        elif response.status == contract.STATUS_ERROR:
            code = (response.error or {}).get("error_code")
            result = (audit.REFUSED if code == contract.PERMISSION_DENIED
                      else audit.FAILED)
        elif response.changed:
            result = audit.COMMITTED
        else:
            result = audit.NO_CHANGE

        # §16: a read that changed nothing is not an audit event worth a row -
        # the log would be mostly reads and the writes would be invisible in it.
        # A *refused* read is, because §14 requires it.
        if not request.writes and result == audit.NO_CHANGE:
            return

        changed_fields = None
        affected: list[str | None] = [response.entity_id or request.entity_id]
        if isinstance(response.result, dict):
            changed_fields = response.result.get("changed_fields")
            # A BULK ARCHIVE AFFECTED N RECORDS AND AUDITED NONE OF THEM.
            # `_retire` only names an entity_id when exactly one row moved, so
            # a three-record archive wrote one event with entity_id NULL and
            # `audit.for_entity` on each archived record showed only its
            # creation. §13 is per-record history; one row per record is what
            # makes it that.
            ids_affected = response.result.get("ids")
            if isinstance(ids_affected, list) and ids_affected:
                affected = list(ids_affected)

        previous = {name: value["from"]
                    for name, value in (changed_fields or {}).items()} or None
        if changed_fields:
            new_summary = {name: value["to"]
                           for name, value in changed_fields.items()}
        elif request.writes and response.ok:
            # THE FIELD NAMES, NOT THE VALUES. A create used to copy
            # `request.data` verbatim, so a confidential person's email, phone
            # and notes were duplicated into an append-only table that carries
            # none of the classification's protections - which is the exact
            # thing `dba/audit.py`'s docstring says summaries exist to avoid.
            new_summary = {"fields": sorted(request.data)} if request.data else None
        else:
            new_summary = None

        previous, new_summary = self._redact(request, previous, new_summary)

        for entity_id in affected:
            audit.record(
                conn, requesting_agent=request.requested_by,
                actor=request.actor, action=request.action,
                entity_type=request.entity_type, entity_id=entity_id,
                previous=previous, new=new_summary,
                request_id=request.request_id, reason=request.reason,
                result=result, succeeded=response.ok,
                source=audit.SOURCE_AGENT_REQUEST)

    @staticmethod
    def _redact(request: contract.Request, previous: dict | None,
                new: dict | None) -> tuple[dict | None, dict | None]:
        """§15: sensitive values do not go into the log.

        The field names still do, because an investigation needs to know *what*
        changed even when it may not read the value from here - the record
        itself is still the place to look, with the permission that requires."""
        if request.entity_type is None or not entities.known(request.entity_type):
            return previous, new
        classification = entities.get(request.entity_type).classification
        if classification not in permissions.SENSITIVE_CLASSIFICATIONS:
            return previous, new
        hide = lambda values: (  # noqa: E731 - one expression, used twice
            {name: "[redacted: %s]" % classification for name in values}
            if values else values)
        return hide(previous), hide(new)

    # --- refusals -------------------------------------------------------------

    def _refuse(self, conn: Database, request: contract.Request, *, code: str,
                message: str, details: dict | None = None) -> contract.Response:
        """A refusal, audited (§14's last line) and never partially applied."""
        response = contract.failure(request, code=code, message=message,
                                    details=details)
        try:
            audit.record(
                conn, requesting_agent=request.requested_by, actor=request.actor,
                action=request.action, entity_type=request.entity_type,
                entity_id=request.entity_id, request_id=request.request_id,
                reason=request.reason,
                result=audit.REFUSED if code == contract.PERMISSION_DENIED
                else audit.FAILED,
                succeeded=False, new={"error_code": code})
        except Exception:  # noqa: BLE001 - the refusal stands even unaudited
            pass
        return response

    def _report_failure(self, conn: Database, request: contract.Request,
                        bad: BaseException, *, code: str) -> contract.Response:
        return self._refuse(
            conn, request, code=code,
            message=(f"{type(bad).__name__}: {bad}. Nothing was reported as "
                     f"written that was not written."),
            details={"exception": type(bad).__name__})


_AGENT: DBAgent | None = None


def default_agent() -> DBAgent:
    """The process-wide agent. Named `default_agent` rather than `agent` so it
    cannot collide with the module of that name - a lesson from
    `app/learning/engine.py`, where exactly that shadowing happened."""
    global _AGENT
    if _AGENT is None:
        _AGENT = DBAgent()
    return _AGENT


def handle(request: contract.Request) -> contract.Response:
    return default_agent().handle(request)
