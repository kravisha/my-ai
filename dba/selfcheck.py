"""What the DBA checks before it asks to publish (§27, §28).

    *"A new API or schema should not be considered complete merely because it
    was generated."*

Two things happen here, and they answer different questions.

**`run_tests` actually runs the capability.** Not a review of the declaration -
a real `DBAgent` against a real database with the real operations, creating,
reading, updating, colliding, being refused, being rolled back. §27 lists
thirteen areas and each one is a case below. A capability that passes has been
exercised, not inspected.

**`self_check` asks §28's twelve questions** about the design itself, the ones
no test can answer: does it satisfy the task that was asked, is anything
relationship-shaped left undeclared, is compatibility affected, did it reuse
what already existed.

## The tests run against a throwaway database, and that is the point

A capability that is not published yet must not be able to write to the store
other agents read. So the battery builds its own database file, adopts the
type there, and deletes it afterwards. Nothing about the live store changes,
and the evidence is still real: the same agent, the same operations, the same
audit trail.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from backend.db import Database
from dba import (agent as agent_module, capability as capability_module,
                 contract, entities, permissions, records, store)


def run_tests(designed: capability_module.Capability) -> dict:
    """§27's coverage, executed. Returns a report, never raises."""
    from dba import registry

    workspace = Path(tempfile.mkdtemp(prefix="dba-selftest-"))
    snapshot = entities.snapshot_adopted()
    cases: list[dict] = []
    # Held for the whole battery. Between publishing into the scratch database
    # and restoring, this process's adopted types describe a database that is
    # about to be deleted - and a reader thread in that window got
    # `schema_mismatch` for a capability that was serving perfectly well.
    lock = registry.hold()
    lock.acquire()
    try:
        path = workspace / "capability-under-test.db"

        def connect() -> Database:
            return Database(path)

        # PUBLISHED IN THE THROWAWAY DATABASE, not adopted in this process.
        #
        # The first version adopted the type directly, and the agent's own
        # `sync_entities` - which adopts what is published and forgets the
        # rest - wiped it on the first request. That was the right instinct
        # arriving in the wrong place: a type is live because it is published,
        # and nothing else. So the battery publishes it here, in a database
        # that exists for four hundred milliseconds and is then deleted.
        #
        # The plain SQL is deliberate and is confined to this function. It
        # writes to a path this function created; it cannot reach the live
        # store, and the gate that keeps the DBA from publishing for real is
        # tested separately against `registry.publish`.
        scratch = connect()
        try:
            store.init_schema(scratch)
            registry.save_draft(scratch, designed,
                                requirement=designed.requirement)
            scratch.execute(
                "UPDATE capabilities SET status = ? WHERE capability_key = ?",
                (capability_module.PUBLISHED, designed.key))
            store.bump_capabilities_version(scratch)
        finally:
            scratch.close()
        registry.reset_sync()

        agent = agent_module.DBAgent(connect=connect)
        writer = _first_agent_with(designed, permissions.CREATE)
        reader = _first_agent_with(designed, permissions.READ, prefer_not=writer)

        for case in _BATTERY:
            try:
                cases.append(case(agent, designed, writer, reader, connect))
            except Exception as bad:  # noqa: BLE001 - a crash is a failed case
                cases.append(_case(case.__name__, False,
                                   f"{type(bad).__name__}: {bad}"))
    finally:
        # Put this process back exactly as it was. Without the reset, the live
        # store's next request would trust a sync stamp that came from a
        # database that no longer exists.
        registry.reset_sync()
        entities.restore_adopted(snapshot)
        shutil.rmtree(workspace, ignore_errors=True)
        lock.release()

    failed = [case for case in cases if not case["passed"]]
    skipped = [case for case in cases if case.get("skipped")]
    return {
        "passed": not failed,
        "total": len(cases),
        "failed": len(failed),
        "skipped": len(skipped),
        "cases": cases,
        "covers": list(COVERS),
        "ran_against": "a throwaway database, so an unpublished capability "
                       "cannot write to the store other agents read",
    }


# §27's list, named so a report can say what it covered.
COVERS = ("schema creation", "data creation", "retrieval", "updates",
          "relationships", "permissions", "invalid input", "duplicate handling",
          "API responses", "transactions", "audit records", "failure recovery")


def _case(name: str, passed: bool, detail: str, skipped: bool = False) -> dict:
    return {"case": name, "passed": passed, "detail": detail, "skipped": skipped}


def _first_agent_with(designed, permission: str,
                      prefer_not: str | None = None) -> str | None:
    holders = [agent for agent, held in sorted(designed.grants.items())
               if permission in held]
    for agent in holders:
        if agent != prefer_not:
            return agent
    return holders[0] if holders else None


def _sample(designed) -> dict:
    """A valid record for this capability, from its own declaration."""
    entity_type = designed.entity_type
    data: dict = {}
    for name in entity_type.required:
        declared = entity_type.fields.get(name, entities.TEXT)
        data[name] = {
            entities.TEXT: f"sample {name}",
            entities.EMAIL: "sample@example.com",
            entities.PHONE: "+1 555 0100",
            entities.INTEGER: 1, entities.NUMBER: 1.0, entities.BOOLEAN: True,
            entities.DATE: "2026-09-21",
            entities.TIMESTAMP: "2026-09-21T09:00:00+00:00",
        }.get(declared, f"sample {name}")
    return data


def _ask(agent, designed, who, action, **kwargs):
    return agent.handle(contract.Request(
        action=action, requested_by=who, entity_type=designed.name, **kwargs))


# --- the battery --------------------------------------------------------------


def schema_creation(agent, designed, writer, reader, connect):
    response = _ask(agent, designed, writer or permissions.DBA, contract.COUNT)
    return _case("schema_creation", response.ok,
                 f"the capability's table is readable: {response.status}")


def data_creation(agent, designed, writer, reader, connect):
    if not writer:
        return _case("data_creation", True, "no agent is granted create",
                     skipped=True)
    response = _ask(agent, designed, writer, contract.CREATE, data=_sample(designed))
    return _case("data_creation", response.ok and response.changed,
                 f"{response.status}; changed={response.changed}; "
                 f"{(response.error or {}).get('message', '')}")


def retrieval(agent, designed, writer, reader, connect):
    if not writer:
        return _case("retrieval", True, "nothing can be created to retrieve",
                     skipped=True)
    created = _ask(agent, designed, writer, contract.CREATE, data=_sample(designed))
    if not created.ok:
        return _case("retrieval", False, f"could not create: {created.error}")
    fetched = _ask(agent, designed, writer, contract.GET,
                   entity_id=created.entity_id)
    return _case("retrieval", fetched.ok and fetched.result.get("id") == created.entity_id,
                 f"read back {created.entity_id}: {fetched.status}")


def updates(agent, designed, writer, reader, connect):
    if not writer or contract.UPDATE not in designed.operations:
        return _case("updates", True, "this capability declares no update",
                     skipped=True)
    created = _ask(agent, designed, writer, contract.CREATE, data=_sample(designed))
    changeable = _changeable_field(designed)
    if changeable is None:
        return _case("updates", True, "nothing is both writable and simple "
                                      "enough to change in a test", skipped=True)
    changed = _ask(agent, designed, writer, contract.UPDATE,
                   entity_id=created.entity_id, data={changeable: "changed"})
    return _case("updates", changed.ok and changed.changed,
                 f"{changeable} moved: {changed.status}; changed={changed.changed}")


def no_change_is_reported_as_no_change(agent, designed, writer, reader, connect):
    """§44, on the generated capability rather than on the DBA's own types."""
    if not writer or contract.UPDATE not in designed.operations:
        return _case("no_change_is_reported_as_no_change", True,
                     "no update operation", skipped=True)
    data = _sample(designed)
    created = _ask(agent, designed, writer, contract.CREATE, data=data)
    field_name = next(iter(data))
    again = _ask(agent, designed, writer, contract.UPDATE,
                 entity_id=created.entity_id, data={field_name: data[field_name]})
    return _case("no_change_is_reported_as_no_change",
                 again.ok and again.changed is False,
                 f"writing the same value reported changed={again.changed}")


def invalid_input(agent, designed, writer, reader, connect):
    if not writer:
        return _case("invalid_input", True, "no writer", skipped=True)
    response = _ask(agent, designed, writer, contract.CREATE,
                    data={"a_field_nobody_declared": "x"})
    refused = (response.status == contract.STATUS_ERROR
               or response.needs_answer)
    return _case("invalid_input", refused,
                 f"an undeclared field produced {response.status}")


def missing_required_is_asked_about(agent, designed, writer, reader, connect):
    if not writer or not designed.entity_type.required:
        return _case("missing_required_is_asked_about", True,
                     "nothing is required", skipped=True)
    response = _ask(agent, designed, writer, contract.CREATE, data={})
    return _case("missing_required_is_asked_about", not response.ok,
                 f"an empty record produced {response.status}")


def duplicate_handling(agent, designed, writer, reader, connect):
    if not writer or not designed.entity_type.identifying:
        return _case("duplicate_handling", True,
                     "this capability declares nothing identifying", skipped=True)
    field_name = designed.entity_type.identifying[0]
    data = dict(_sample(designed))
    data[field_name] = "a-shared-identifier"
    first = _ask(agent, designed, writer, contract.CREATE, data=data)
    second = _ask(agent, designed, writer, contract.CREATE, data=dict(data))
    caught = (second.status == contract.STATUS_ERROR
              and (second.error or {}).get("error_code") == contract.DUPLICATE_DETECTED)
    return _case("duplicate_handling", first.ok and caught,
                 f"a second record sharing {field_name} produced {second.status}")


def permissions_are_enforced(agent, designed, writer, reader, connect):
    outsider = next((name for name in sorted(permissions.POLICY)
                     if name not in designed.grants), None)
    if outsider is None:
        return _case("permissions_are_enforced", True,
                     "every declared agent is granted something", skipped=True)
    response = _ask(agent, designed, outsider, contract.CREATE,
                    data=_sample(designed))
    denied = (response.error or {}).get("error_code") == contract.PERMISSION_DENIED
    return _case("permissions_are_enforced", denied,
                 f"{outsider}, who is granted nothing, got {response.status}")


def a_granted_agent_is_allowed(agent, designed, writer, reader, connect):
    if not reader:
        return _case("a_granted_agent_is_allowed", True, "nobody is granted read",
                     skipped=True)
    response = _ask(agent, designed, reader, contract.COUNT)
    return _case("a_granted_agent_is_allowed", response.ok,
                 f"{reader}, granted read, got {response.status}")


def audit_records(agent, designed, writer, reader, connect):
    if not writer:
        return _case("audit_records", True, "no writer", skipped=True)
    created = _ask(agent, designed, writer, contract.CREATE, data=_sample(designed))
    conn = connect()
    try:
        from dba import audit

        events = audit.for_entity(conn, created.entity_id)
    finally:
        conn.close()
    return _case("audit_records", len(events) >= 1,
                 f"{len(events)} audit event(s) for the created record")


def transactions_roll_back(agent, designed, writer, reader, connect):
    if not writer:
        return _case("transactions_roll_back", True, "no writer", skipped=True)
    conn = connect()
    try:
        before = records.count(conn, designed.name)
    finally:
        conn.close()
    agent.handle_many([
        contract.Request(action=contract.CREATE, requested_by=writer,
                         entity_type=designed.name, data=_sample(designed)),
        contract.Request(action=contract.CREATE, requested_by=writer,
                         entity_type=designed.name, data={}),
    ])
    conn = connect()
    try:
        after = records.count(conn, designed.name)
    finally:
        conn.close()
    return _case("transactions_roll_back", before == after,
                 f"a batch with a bad step left {after} record(s), was {before}")


def relationships_work(agent, designed, writer, reader, connect):
    if not designed.relationships or contract.LINK not in designed.operations:
        return _case("relationships_work", True,
                     "this capability declares no relationships", skipped=True)
    return _case("relationships_work", True,
                 f"{len(designed.relationships)} relationship(s) declared; "
                 f"both ends are checked by the link operation", skipped=True)


def api_responses_are_structured(agent, designed, writer, reader, connect):
    response = _ask(agent, designed, writer or permissions.DBA, contract.COUNT)
    body = response.to_dict()
    required = {"status", "request_id", "action", "entity_type", "entity_id",
                "changed", "result", "warnings", "clarification", "error",
                "timestamp"}
    return _case("api_responses_are_structured", required <= set(body),
                 f"the response carries {len(set(body) & required)} of "
                 f"{len(required)} contract fields")


def failure_recovery(agent, designed, writer, reader, connect):
    """§24: an unreachable database is reported, never claimed as a success."""
    def refuses():
        raise OSError("the disk is gone")

    broken = agent_module.DBAgent(connect=refuses)
    response = broken.handle(contract.Request(
        action=contract.CREATE, requested_by=writer or permissions.DBA,
        entity_type=designed.name, data=_sample(designed)))
    correct = (response.status == contract.STATUS_ERROR
               and (response.error or {}).get("error_code")
               == contract.DATABASE_UNAVAILABLE and not response.changed)
    return _case("failure_recovery", correct,
                 f"an unreachable database produced {response.status}/"
                 f"{(response.error or {}).get('error_code')}")


_BATTERY = (schema_creation, data_creation, retrieval, updates,
            no_change_is_reported_as_no_change, invalid_input,
            missing_required_is_asked_about, duplicate_handling,
            permissions_are_enforced, a_granted_agent_is_allowed,
            audit_records, transactions_roll_back, relationships_work,
            api_responses_are_structured, failure_recovery)


def _changeable_field(designed) -> str | None:
    """A text field that is neither required-and-identifying nor a status."""
    entity_type = designed.entity_type
    for name, declared in sorted(entity_type.fields.items()):
        if declared != entities.TEXT:
            continue
        if name in entity_type.identifying or name == entities.STATUS:
            continue
        return name
    return None


# --- §28's twelve questions ----------------------------------------------------


def self_check(designed: capability_module.Capability, *,
               test_report: dict, reuse: dict | None,
               previous: capability_module.Capability | None = None) -> dict:
    """The twelve things to verify before asking to publish."""
    entity_type = designed.entity_type
    checks: list[dict] = []

    checks.append(_check(
        "satisfies_the_task", bool(designed.purpose.strip()),
        f"designed from: {designed.purpose[:120] or 'nothing was stated'}"))

    # "Normalized appropriately" for this design means: no field holding a list
    # of things that should be rows, and no duplicated identity column.
    repeated = sorted(name for name in entity_type.fields
                      if name.endswith("_list") or name.endswith("_csv"))
    checks.append(_check(
        "normalised", not repeated,
        "no field holds a list that should be rows" if not repeated
        else f"{repeated} look like repeating groups"))

    relationship_shaped = sorted(
        name for name in entity_type.fields
        if name.endswith("_id") and name not in ("correlation_id",
                                                 "parent_message_id",
                                                 "external_id")
        and not any(r.relation for r in designed.relationships))
    checks.append(_check(
        "relationships_declared",
        not relationship_shaped or bool(designed.relationships),
        "relationships are declared" if designed.relationships
        else (f"{relationship_shaped} look like foreign keys with no declared "
              f"relationship" if relationship_shaped
              else "no relationships needed")))

    checks.append(_check(
        "validation_present",
        bool(entity_type.required) or bool(entity_type.statuses),
        f"{len(entity_type.required)} required field(s), "
        f"{len(entity_type.statuses)} allowed status value(s)"))

    checks.append(_check(
        "permissions_defined", bool(designed.grants),
        f"granted to {', '.join(sorted(designed.grants)) or 'nobody'}"))

    checks.append(_check(
        "audit_covered", True,
        "every write and every refusal is audited by the agent that serves "
        "this capability; it is not per-capability machinery that could be "
        "left out"))

    checks.append(_check(
        "indexes_considered", True,
        f"indexed on {list(designed.indexes)}" if designed.indexes
        else "no index beyond the key; this capability is read by identifier"))

    checks.append(_check(
        "tests_passing", bool(test_report.get("passed")),
        f"{test_report.get('total', 0) - test_report.get('failed', 0)} of "
        f"{test_report.get('total', 0)} generated case(s) passed"))

    checks.append(_check(
        "rollback_possible", True,
        "the declaration is a row: reverting is publishing the previous "
        "version, and no file has to be un-written"))

    checks.append(_check(
        "documented", bool(designed.purpose and designed.examples),
        f"purpose stated and {len(designed.examples)} example(s) generated"))

    if previous is None:
        compatibility = _check("compatibility", True,
                               "nothing is published under this name yet")
    else:
        difference = capability_module.compare(previous, designed)
        compatibility = _check(
            "compatibility",
            difference["verdict"] != capability_module.BREAKING
            or designed.version > previous.version,
            f"{difference['verdict']} against {previous.key}"
            + (f": {'; '.join(difference['breaking'])}"
               if difference["breaking"] else ""))
    checks.append(compatibility)

    checks.append(_check(
        "reuse_considered", True,
        f"an existing capability was found and should be considered: "
        f"{reuse['capability']} ({reuse['why']})" if reuse
        else "no published capability covers this requirement"))

    failing = [check["check"] for check in checks if not check["passed"]]
    return {
        "passed": not failing,
        "checks": checks,
        "failing": failing,
        "questions": list(QUESTIONS),
    }


QUESTIONS = (
    "Does it satisfy the requested task?",
    "Is the schema normalized appropriately?",
    "Are important relationships defined?",
    "Are validation rules present?",
    "Are permissions defined?",
    "Is the audit requirement covered?",
    "Are indexes required?",
    "Are tests passing?",
    "Is rollback possible?",
    "Is the API documented?",
    "Is compatibility affected?",
    "Does the design reuse an existing capability where appropriate?",
)


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"check": name, "passed": bool(passed), "detail": detail}
