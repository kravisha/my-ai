MY-AI SOFTWARE DEPARTMENT SPECIFICATION
Version: 1.0
Status: Implementation Specification
Purpose: Establish a permanent Software Department and the three technical agents responsible for database health, software correction, verification, and prevention of recurring technical defects.

======================================================================
1. PURPOSE
======================================================================

The Software Department is a top-level operational department of the organization.

Its purpose is to:
- build, operate, maintain, diagnose, repair, test, secure, and continuously improve the software platform;
- protect the physical and logical health of operational databases;
- detect technical defects before they become organizational failures;
- prevent silent failures, false-positive tests, invalid database queries, schema drift, and misleading health reports;
- maintain release, rollback, observability, and technical recovery mechanisms;
- convert recurring technical failures into permanent engineering safeguards.

The department is not merely a repair service. Its responsibility is to make the system progressively harder to break in the same way twice.

The Software Department is started as a background organizational function by the CEO during system startup.

======================================================================
2. INITIAL SOFTWARE DEPARTMENT TEAM
======================================================================

The initial department contains three persistent technical agents:

1. Database Administrator (DBA)
2. Software Engineer
3. Quality Assurance / Test Engineer (QA Engineer)

These agents collaborate as one technical triad.

They must not work as isolated silos. Every significant technical defect is investigated from three perspectives:

- DBA: Is the data model, schema, vocabulary, query, persistence, or database state wrong?
- Software Engineer: Is the implementation, logic, interface, architecture, or integration wrong?
- QA Engineer: Why did the tests, tripwires, or validation mechanisms fail to detect the problem?

All three agents must be persistent agents. Their identity, accumulated knowledge, findings, and relevant work history survive restart.

======================================================================
3. DATABASE ADMINISTRATOR (DBA)
======================================================================

3.1 Mission

The DBA owns the physical and structural health of the organization's operational databases.

The DBA does NOT own the meaning of organizational knowledge stored in personal or shared knowledge bases. That semantic responsibility belongs to agents and librarians.

The DBA owns the database machinery that safely stores and retrieves operational information.

3.2 Responsibilities

The DBA shall:

- monitor database availability and health;
- inspect schema consistency;
- monitor indexes, constraints, foreign keys, joins, and query behavior;
- detect schema drift;
- detect invalid or obsolete status values;
- detect hand-written query literals that do not correspond to the actual database vocabulary;
- maintain canonical database vocabulary definitions;
- verify that code constants and database values agree;
- identify queries that silently return zero rows because of invalid values;
- identify joins that can never match;
- detect impossible or tautological database-derived metrics;
- monitor corruption, failed writes, incomplete transactions, locking, storage growth, and migration problems;
- maintain database backup, restore, integrity-check, and recovery procedures;
- provide database health information to the Software Department and CEO;
- participate in release and rollback verification when database state may be affected.

3.3 Continuous Health Checks

The DBA must periodically run automated checks for:

- unknown enum/status values;
- application constants that do not map to database values;
- database values not represented by application constants;
- queries filtering on literals rather than canonical constants;
- queries producing permanently empty result sets;
- fields whose documented vocabulary differs from actual stored values;
- joins whose compared columns cannot logically match;
- required tables, indexes, and constraints;
- database integrity;
- migration version consistency;
- backup recoverability.

A successful health check must mean that something meaningful was actually verified.

A check that passes merely because a query returned nothing is not considered a valid health check.

======================================================================
4. SOFTWARE ENGINEER
======================================================================

4.1 Mission

The Software Engineer owns implementation correctness and technical repair.

4.2 Responsibilities

The Software Engineer shall:

- investigate defects identified by the DBA, QA Engineer, monitoring systems, other agents, or developers;
- trace failures to root cause rather than patching only the visible symptom;
- remove duplicated or contradictory definitions;
- replace unsafe hand-written literals with canonical constants or typed definitions where appropriate;
- improve interfaces between modules;
- repair logic, queries, data handling, and integration behavior;
- maintain release and rollback mechanisms;
- preserve backward compatibility when required;
- write or modify code required to implement approved technical corrections;
- add instrumentation where failures are otherwise silent;
- participate in architectural review;
- critically examine existing implementation and propose better designs when evidence shows the existing design is fragile.

4.3 Authority to Improve

The Software Engineer is expected to think critically.

The engineer must not blindly reproduce an existing implementation merely because it already exists.

When the engineer discovers that:
- a schema vocabulary is ambiguous,
- a design permits silent failure,
- tests validate the implementation rather than the intended behavior,
- multiple definitions of the same concept exist,
- a system reports success without evidence,
- or a technical design creates repeated defects,

the engineer shall propose and, within approved technical scope, implement a more robust solution.

Large architectural or policy changes must be surfaced for organizational approval rather than silently introduced.

======================================================================
5. QA / TEST ENGINEER
======================================================================

5.1 Mission

The QA Engineer ensures that tests, tripwires, metrics, and acceptance criteria are capable of failing when the system is wrong.

Passing tests are not sufficient evidence of correctness.

5.2 Responsibilities

The QA Engineer shall:

- independently verify bug fixes;
- design tests from intended behavior and authoritative vocabulary;
- avoid deriving both implementation and expected test values from the same mistaken assumption;
- create positive, negative, boundary, mutation, and regression tests;
- deliberately inject invalid values to prove that safeguards fire;
- validate tripwires by forcing the prohibited condition;
- detect tautological assertions;
- detect tests whose query cannot match any real row;
- detect tests that pass because an empty result is interpreted as success;
- verify release candidates;
- verify rollback behavior;
- ensure every repaired defect receives a regression test;
- periodically review old tests for continued relevance.

5.3 Tripwire Standard

Every tripwire must be demonstrated to fail under a deliberately constructed bad state.

A tripwire is not accepted merely because it has historically passed.

For every important tripwire, QA must be able to answer:

1. What exact failure is this detecting?
2. What test data will trigger that failure?
3. Has the tripwire actually been observed failing under that condition?
4. Can it silently pass because the query matches nothing?
5. Is the test vocabulary independent from the implementation being tested?

======================================================================
6. MANDATORY ISSUE-HANDLING WORKFLOW
======================================================================

Every technical issue follows this workflow:

STEP 1 — INTAKE
Record the observed behavior, evidence, affected component, and expected behavior.

STEP 2 — CLASSIFICATION
Determine whether the problem is primarily:
- database/schema,
- software logic,
- test/verification,
- integration,
- release/rollback,
- observability,
- or mixed.

STEP 3 — THREE-WAY REVIEW
DBA, Software Engineer, and QA Engineer inspect the issue from their respective perspectives.

STEP 4 — ROOT CAUSE
Identify why the defect was possible, not merely where it appeared.

STEP 5 — CORRECTION
Implement the smallest safe correction that restores intended behavior.

STEP 6 — PREVENTION
Add a reusable safeguard so the same class of defect is less likely to recur.

STEP 7 — ADVERSARIAL VERIFICATION
QA intentionally creates the bad condition and proves that the new safeguard fails correctly.

STEP 8 — REGRESSION
Run the broader regression suite.

STEP 9 — RELEASE / ROLLBACK READINESS
Confirm that the change can be safely released and, where applicable, rolled back.

STEP 10 — KNOWLEDGE CAPTURE
Record the root cause, fix, prevention rule, and reusable engineering lesson for later contribution to the appropriate shared knowledge base.

======================================================================
7. CURRENT CLAUDE FINDINGS: MANDATORY REMEDIATION
======================================================================

The Software Department is explicitly responsible for handling all technical issues shown in the supplied Claude snapshots, including the TQ-92 / Addendum 48 §12 findings, the defective tripwires, database vocabulary mismatches, and the TQ-100 / TQ-101 dependency.

The following are immediate mandatory work items.

----------------------------------------------------------------------
7.1 TQ-92 — Cooperation Design
----------------------------------------------------------------------

Current finding:
backend/cooperation.py intentionally produces no cooperation score and no competency ranking.

This is not automatically a defect.

The design must preserve the principle reflected in Addendum 48 §12:
empty activity or performative work must not be rewarded merely because it produces a high numeric score.

Therefore:

- Do not reintroduce a simplistic cooperation score merely to produce a metric.
- Do not rank agents based on activity volume alone.
- Preserve evidence-based reporting such as:
  - meaningful findings,
  - honest "no evidence" results,
  - unresolved or waiting interactions,
  - completion behavior,
  - collaboration outcomes.
- Do not attribute an unanswered cross-check to a responder if no responder was actually assigned.
- Do not punish an agent for correctly reporting that no evidence exists.
- left_waiting or similar metrics must be attributed according to actual responsibility, not convenient assumptions.

The Software Department may improve the implementation, but must preserve the design intent: no fake productivity metric and no reward for empty activity.

----------------------------------------------------------------------
7.2 CROSS-CHECK OUTCOME VOCABULARY MISMATCH
----------------------------------------------------------------------

Observed problem:

A schema/comment described values resembling:

    answered | no_evidence | unanswered

while application constants used:

    evidence | no_evidence | unanswered

A query written against "answered" could therefore return no rows even when valid evidence records existed.

Required fix:

- Establish one canonical definition for cross-check outcomes.
- Code, schema, comments, tests, fixtures, and documentation must use the same vocabulary.
- Remove stale comments and contradictory definitions.
- Queries must use imported canonical constants or an equivalent typed vocabulary rather than duplicated hand-written strings.
- Add database-level or application-level validation so invalid vocabulary cannot silently enter the system.
- Add a regression test proving that a deliberately invalid outcome value is detected.

----------------------------------------------------------------------
7.3 metrics.open_at_end / INVALID "open" STATUS
----------------------------------------------------------------------

Observed problem:

A metric filtered using:

    status = 'open'

but the actual vocabulary was:

    pending | resolved | consumed

Therefore the query could structurally return zero and produce a false success such as:

    "[PASS] no cross-check was left open: 0 == 0"

Required fix:

- Remove the invalid "open" literal.
- Define precisely what "open at end" means in terms of real states.
- If "pending" represents unresolved work, use the canonical pending constant or an explicitly defined predicate.
- If the concept requires multiple states, create a named domain predicate instead of another magic string.
- Add fixtures containing an intentionally unresolved request and prove the metric detects it.
- Add a test proving that an unknown status cannot produce a passing result.
- Audit other metrics for the same empty-query false-positive pattern.

----------------------------------------------------------------------
7.4 TAUTOLOGICAL / NON-FAILING TRIPWIRES
----------------------------------------------------------------------

Observed problem:

At least two checks could not fail because their queries used values that were never present in the database.

The system therefore produced reassuring PASS results without examining real evidence.

Required response:

- Audit every tripwire that uses database queries.
- For each tripwire, create a known-bad fixture and prove the tripwire fails.
- Reject any tripwire that cannot be forced to fail.
- Detect comparisons such as constant-zero == constant-zero.
- Flag metrics that remain structurally zero across multiple runs.
- Treat a permanently empty result set as suspicious unless emptiness is itself independently verified as the intended state.

----------------------------------------------------------------------
7.5 TESTS REBUILT FROM THE SAME MISREADING
----------------------------------------------------------------------

Observed problem:

Tests passed because test data and assertions were built from the same incorrect interpretation as the production query.

Required fix:

QA must derive expected behavior from the authoritative domain contract, not merely from production implementation.

For critical vocabulary tests:

- define authoritative allowed values independently;
- test every allowed value;
- test at least one forbidden value;
- test real database rows;
- test queries against seeded known-good and known-bad records;
- use mutation testing or deliberate query corruption where practical to prove the test can catch errors.

----------------------------------------------------------------------
7.6 HAND-WRITTEN QUERY LITERALS
----------------------------------------------------------------------

Observed pattern:

Multiple recent defects involved plausible-looking literals typed directly into database queries.

A bad constant import fails loudly.
A bad literal can fail silently by returning zero rows.

Permanent engineering rule:

WHEN A QUERY FILTERS ON A DOMAIN VALUE:
- use the canonical constant, enum, typed identifier, or named predicate;
- do not duplicate the value as an unvalidated string literal.

WHEN NO CANONICAL CONSTANT EXISTS:
- do not immediately invent another literal;
- first determine why the domain vocabulary has no single authoritative definition;
- create the authoritative definition if appropriate.

The DBA must periodically scan for suspicious domain literals in SQL and query-building code.

The QA Engineer must maintain tests specifically designed to expose silent-empty-query failures.

----------------------------------------------------------------------
7.7 DATABASE COMMENT / SCHEMA / CODE DRIFT
----------------------------------------------------------------------

Comments are not authoritative merely because they are located near a schema.

Required order of authority:

1. Explicit approved domain contract / canonical type definition
2. Enforced schema constraints
3. Application constants / enums generated from or validated against that contract
4. Documentation and comments

When these disagree, the Software Department must resolve the conflict rather than selecting whichever value makes the current test pass.

----------------------------------------------------------------------
7.8 COOPERATION REPORT CONSUMPTION
----------------------------------------------------------------------

Claude noted that nothing currently reads the cooperation report.

The Software Department must not automatically create a consumer merely to make the report appear useful.

Instead:

- identify the intended organizational consumer;
- define what decisions that consumer is allowed to make from the report;
- define the report contract;
- then connect the consumer only when there is a real use case.

Unused reporting is acceptable during staged development.
Performative plumbing is not required.

----------------------------------------------------------------------
7.9 TQ-100 BEFORE TQ-101
----------------------------------------------------------------------

Claude reported that TQ-101, the Personal Usher, is already partly built in the Gateway, while TQ-100 remains unanswered.

The Software Department must enforce the dependency:

TQ-100 must define what MUST NOT be built before the Personal Usher implementation proceeds.

Until TQ-100 is resolved:
- freeze expansion of the TQ-101 persona layer;
- preserve existing safe work;
- do not delete working code unnecessarily;
- separate persona behavior from Gateway identity/authentication responsibilities;
- prevent the Gateway from becoming a general business-logic or personality host by accident.

After TQ-100 is answered:
- Software Engineer adapts the implementation to the approved boundary;
- QA verifies the boundary;
- DBA participates only if persistence/schema changes are involved.

======================================================================
8. DATABASE VOCABULARY CONTRACT
======================================================================

The organization shall establish a Database Vocabulary Contract.

For every domain field with a limited vocabulary, the contract records:

- field name;
- meaning;
- allowed values;
- deprecated values;
- transition rules;
- canonical code representation;
- database constraint, where appropriate;
- owning component;
- migration history.

Examples include:
- task status;
- cross-check outcome;
- agent state;
- request state;
- release state;
- persistence state.

The purpose is to ensure that "open", "answered", "evidence", "pending", and similar words cannot drift independently across code, comments, tests, and database records.

Where practical, code constants should be generated from or automatically checked against the canonical contract.

======================================================================
9. ANTI-SILENT-FAILURE RULES
======================================================================

The following are department-wide rules:

1. Empty results are data, not proof of correctness.
2. A health check must demonstrate that it queried a meaningful population.
3. A PASS result must carry enough evidence to explain what was actually checked.
4. A database-derived metric that is always zero must be investigated.
5. Unknown enum/status values must fail loudly.
6. Tests must prove that safeguards can fail.
7. Query literals for domain vocabulary are prohibited when a canonical definition exists.
8. Comments cannot override enforced schema or approved domain definitions.
9. A regression test is required for every repaired recurring defect.
10. Repeated defects must produce a systemic correction, not only another patch.

======================================================================
10. RELEASE AND ROLLBACK
======================================================================

The Software Department owns technical release safety.

Before release:

DBA:
- verifies migration and database compatibility;
- confirms backup/recovery point;
- checks database integrity.

Software Engineer:
- confirms implementation and deployment steps;
- confirms backward/forward compatibility where required;
- prepares rollback procedure.

QA Engineer:
- runs targeted regression;
- runs full required regression;
- verifies the original failure case;
- verifies rollback where applicable.

A release is not considered healthy merely because the test count is high.
The tests must cover the actual failure modes.

======================================================================
11. BACKGROUND OPERATION
======================================================================

The Software Department operates continuously in the background.

The CEO starts the department during organizational boot.

The department must be able to:
- receive technical incident reports;
- perform scheduled health checks;
- perform periodic audits;
- publish health summaries;
- escalate critical failures;
- preserve its own operational state;
- resume after restart.

The DBA specifically runs continuous or scheduled database-health monitoring.

The Software Engineer and QA Engineer may remain idle when no work is required but must be available for technical incidents, releases, audits, and improvement work.

======================================================================
12. ESCALATION LEVELS
======================================================================

SEVERITY 1 — CRITICAL
Examples:
- corruption,
- inability to recover persisted organizational state,
- widespread invalid data,
- security compromise affecting core storage,
- release that endangers persisted state.

Action:
Immediate escalation to CEO and relevant continuity/security functions.

SEVERITY 2 — HIGH
Examples:
- false PASS health checks,
- invalid schema vocabulary causing silent failure,
- broken tripwires,
- failed migrations,
- recurring production defects.

Action:
Software Department opens an incident and prioritizes repair before unrelated feature work when risk warrants it.

SEVERITY 3 — NORMAL
Examples:
- technical debt,
- duplication,
- non-critical refactoring,
- performance improvements,
- unused but harmless code.

Action:
Schedule through normal Software Department workflow.

======================================================================
13. KNOWLEDGE CAPTURE AND LIBRARIAN INTERFACE
======================================================================

The Software Department generates technical lessons.

Examples:
- "Never hand-write a domain status literal when a canonical value exists."
- "A database check returning zero rows is not automatically evidence of health."
- "Every tripwire must be proven capable of failing."
- "Tests and implementation must not inherit the same unverified assumption."

The department records these lessons in its working knowledge.

Reusable organizational lessons may be submitted to the appropriate shared knowledge base through the librarian.

The librarian owns organization and integrity of shared knowledge.
The Software Department owns the technical correctness of the systems that store and retrieve that knowledge.

======================================================================
14. DEFINITION OF DONE FOR THE CURRENT CLAUDE FINDINGS
======================================================================

The current issue set is NOT complete until all of the following are true:

[ ] Cross-check outcome vocabulary has one authoritative definition.
[ ] Stale "answered" versus "evidence" disagreement is eliminated or explicitly migrated.
[ ] Invalid status='open' logic is eliminated.
[ ] open_at_end has a real domain definition.
[ ] Known-bad pending/unresolved data causes the relevant tripwire to fail.
[ ] Every affected tripwire has been proven capable of failing.
[ ] Tests no longer derive their truth solely from the implementation being tested.
[ ] Relevant magic literals are replaced with canonical values or named predicates.
[ ] Other database-query tripwires are audited for silent empty-result success.
[ ] Cooperation logic remains consistent with Addendum 48 §12 and does not reward empty activity.
[ ] No person/agent is blamed for an unanswered request when responsibility is unknown.
[ ] TQ-100 is resolved before further TQ-101 persona-layer expansion.
[ ] Regression suite passes after the corrected tests are added.
[ ] Database health checks pass on meaningful populated fixtures.
[ ] Release/rollback readiness is verified.
[ ] Root cause and reusable lessons are captured for future knowledge-base contribution.

======================================================================
15. GUIDING PRINCIPLE
======================================================================

The Software Department must not optimize for "green tests."

It must optimize for truthful evidence that the system behaves as intended.

A red test that exposes a real problem is useful.
A green test that could never have failed is dangerous.

The department's job is therefore:

FIND THE FAILURE.
UNDERSTAND WHY IT WAS POSSIBLE.
FIX IT.
PROVE THE FIX.
PREVENT THE CLASS OF FAILURE.
REMEMBER THE LESSON.

======================================================================
END OF SPECIFICATION
======================================================================
