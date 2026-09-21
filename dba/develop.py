"""The DBA doing its job end to end (§32, §33, §34).

    *"I need persistent information for this new task."*

and the DBA independently understands the requirement, asks any necessary
questions, designs the schema, creates it, designs and implements the API,
validates, creates and runs tests, publishes, documents, preserves the audit
trail, and makes the data available to authorized agents.

This module is that sequence. Each step lives in its own module; this one is
the order they happen in and the evidence carried between them.

    requirement
        -> advice from past designs           (experience.advice_for)
        -> design, or questions               (design.design)
        -> draft recorded                     (registry.save_draft)
        -> its own tests, actually run        (selfcheck.run_tests)
        -> the twelve pre-publish checks      (selfcheck.self_check)
        -> staged, with the evidence attached (registry.stage)
        -> [ Krish accepts ]                  (develop.publish)
        -> serving, documented, audited       (routes, apispec)

## The one step the DBA does not take

`publish`. Everything up to it is the DBA's; bringing a new data surface into
service is Krish's, because `dba/permissions.POLICY` does not give the DBA
`administer` and `registry.publish` requires it. §31 calls that stage 2, and it
is structural rather than procedural - there is no flag to flip, and the DBA
cannot grant itself the permission because granting is not an operation it has.

## Every attempt is recorded, including the ones that asked

§11 says the DBA's experience must itself be persisted. An episode is written
whether the design succeeded, stopped to ask, or failed its own tests - the
ones that asked are the most useful, because they are what `advice_for` turns
into a question asked up front next time.
"""

from __future__ import annotations

from backend.db import Database
from dba import (apispec, audit, capability, design as design_module,
                 experience, permissions, registry, selfcheck, store)


def request_capability(requirement: design_module.Requirement,
                       conn: Database | None = None) -> dict:
    """§34's steps 2 to 8. Returns a proposal, or the questions in the way."""
    own_connection = conn is None
    conn = conn or store.connect()
    try:
        store.init_schema(conn)
        registry.sync_entities(conn)

        matched = design_module.patterns.match(requirement.task)
        advice = experience.advice_for(
            conn, matched.archetype.name if matched.archetype else None)

        result = design_module.design(requirement, conn)

        if not result.ready:
            experience.record_design(
                conn, requirement=requirement, design_result=result,
                outcome=experience.ASKED,
                detail=f"{len(result.questions)} question(s)")
            audit.record(
                conn, requesting_agent=requirement.requested_by,
                action="design_capability", result=audit.CLARIFICATION_REQUESTED,
                succeeded=False, entity_type=result.capability.name
                if result.capability else None,
                reason=requirement.task[:200],
                new={"questions": [q.reason for q in result.questions]})
            return {
                "status": "clarification_required",
                "questions": [question.to_dict() for question in result.questions],
                "advice_from_experience": advice,
                "match": result.match.to_dict(),
                "reasoning": result.reasoning,
                "reuse": result.reuse,
            }

        designed = result.capability

        # ALREADY BUILT? `fingerprint` was stored and never read, so asking
        # twice for the same thing designed, tested and staged a byte-identical
        # v2 beside the v1 already serving it.
        existing = registry.identical(conn, designed)
        if existing is not None:
            return {
                "status": existing["status"],
                "capability": existing["capability_key"],
                "already_exists": True,
                "why": (f"this is byte-for-byte the capability already "
                        f"{existing['status']} as "
                        f"{existing['capability_key']}. Nothing was designed "
                        f"again; §29 says reuse before duplication and that "
                        f"applies to the DBA's own output first."),
            }

        # A second version of an existing capability rather than a clash.
        version = registry.next_version(conn, designed.name)
        if version != designed.version:
            designed = capability.Capability.from_dict(
                {**designed.to_dict(), "version": version})

        registry.save_draft(conn, designed, requirement=requirement.task,
                            designed_by=permissions.DBA)

        test_report = selfcheck.run_tests(designed)
        previous = registry.current(conn, designed.name)
        checks = selfcheck.self_check(designed, test_report=test_report,
                                      reuse=result.reuse, previous=previous)

        if not (test_report["passed"] and checks["passed"]):
            for case in test_report["cases"]:
                if not case["passed"]:
                    experience.record_test_failure(
                        conn, capability_name=designed.name,
                        case=case["case"], detail=case["detail"])
            experience.record_design(
                conn, requirement=requirement, design_result=result,
                outcome=experience.FAILED,
                detail=f"tests: {test_report['failed']} failed; "
                       f"checks: {', '.join(checks['failing'])}")
            audit.record(
                conn, requesting_agent=requirement.requested_by,
                action="design_capability", result=audit.FAILED, succeeded=False,
                entity_type=designed.name, reason=requirement.task[:200],
                new={"failing_checks": checks["failing"],
                     "failed_tests": test_report["failed"]})
            return {
                "status": "not_ready",
                "capability": designed.key,
                "why": "the DBA's own tests or pre-publish checks did not pass, "
                       "so it is not being offered for publication",
                "tests": test_report,
                "self_check": checks,
            }

        registry.stage(conn, designed.key, self_check=checks,
                       test_report=test_report)
        experience.record_design(
            conn, requirement=requirement, design_result=result,
            outcome=experience.STAGED, detail=designed.key)
        audit.record(
            conn, requesting_agent=requirement.requested_by,
            action="design_capability", result=audit.COMMITTED, succeeded=True,
            entity_type=designed.name, reason=requirement.task[:200],
            new={"staged": designed.key,
                 "tests_passed": test_report["total"] - test_report["failed"]})

        return {
            "status": "staged",
            "capability": designed.key,
            "awaiting": ("Krish's acceptance. The DBA designed, built and "
                         "tested this; it cannot publish it - that needs "
                         "'administer', which the designing agent does not "
                         "hold."),
            "declaration": designed.to_dict(),
            "api_contract": apispec.contract_for(designed),
            "documentation": apispec.markdown(designed),
            "tests": test_report,
            "self_check": checks,
            "reasoning": result.reasoning,
            "reuse": result.reuse,
            "advice_from_experience": advice,
        }
    finally:
        if own_connection:
            conn.close()


def publish(key: str, *, accepted_by: str,
            conn: Database | None = None) -> dict:
    """§34's step 9. Krish's hand, not the DBA's."""
    own_connection = conn is None
    conn = conn or store.connect()
    try:
        store.init_schema(conn)
        try:
            declared = registry.publish(conn, key, accepted_by=accepted_by)
        except registry.RegistryRefused as refused:
            audit.record(conn, requesting_agent=accepted_by,
                         action="publish_capability", result=audit.REFUSED,
                         succeeded=False, entity_type=key.split("@")[0],
                         new={"refused": str(refused)[:300]})
            return {"status": "refused", "why": str(refused)}

        experience.record_lesson(
            conn, kind=experience.ARCHETYPE_FIT,
            pattern=f"{declared.name}:published",
            lesson=f"{declared.key} was accepted and published",
            capability=declared.name)
        # AND AN EPISODE. Without one, `meta_report`'s "N designs reached
        # publication" counted a state nothing ever wrote, so the claim could
        # never fire however many capabilities were published - a statistic
        # that is always zero and always wrong.
        experience.record_publication(
            conn, capability_name=declared.name, version=declared.version,
            requirement=declared.requirement, accepted_by=accepted_by)
        audit.record(conn, requesting_agent=accepted_by, actor=accepted_by,
                     action="publish_capability", result=audit.COMMITTED,
                     succeeded=True, entity_type=declared.name,
                     new={"published": declared.key,
                          "serving_at": declared.route_prefix})
        return {
            "status": "published",
            "capability": declared.key,
            "serving_at": declared.route_prefix,
            "api_contract": apispec.contract_for(declared),
        }
    finally:
        if own_connection:
            conn.close()


def reject(key: str, *, why: str, rejected_by: str,
           conn: Database | None = None) -> dict:
    """Krish said no. §30: the correction is kept as learning material."""
    own_connection = conn is None
    conn = conn or store.connect()
    try:
        store.init_schema(conn)
        try:
            registry.reject(conn, key, why=why)
        except registry.RegistryRefused as refused:
            return {"status": "refused", "why": str(refused)}
        experience.record_correction(
            conn, capability_name=key.split("@")[0],
            what=why, found_by=rejected_by)
        audit.record(conn, requesting_agent=rejected_by, actor=rejected_by,
                     action="reject_capability", result=audit.REFUSED,
                     succeeded=True, entity_type=key.split("@")[0],
                     reason=why[:300])
        return {"status": "rejected", "capability": key,
                "kept_as_learning": True}
    finally:
        if own_connection:
            conn.close()


def proposals(conn: Database | None = None) -> list[dict]:
    """Everything staged and waiting for Krish."""
    own_connection = conn is None
    conn = conn or store.connect()
    try:
        store.init_schema(conn)
        return [registry.record(conn, row["capability_key"])
                for row in registry.inventory(conn)
                if row["status"] == capability.STAGED]
    finally:
        if own_connection:
            conn.close()
