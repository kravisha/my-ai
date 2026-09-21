"""The DBA as a data developer: can it design, and will it refuse to guess?

The expectations document asks for something larger than the requirements
specification did — an agent that reasons from a task sentence to a data model,
builds the API for it, tests what it built, and learns from having done it. So
this file is mostly about two things:

- **Does the design actually reason?** §8 lists twelve questions a design must
  answer, and `Design.reasoning` answers all twelve. A design that produced a
  workable schema without being able to say why it has that shape would pass a
  CRUD test and be unreviewable.
- **Does it stop when it does not know?** §19 names eight cases. Each one is a
  test here, and every one of them asserts that *nothing was built* — a DBA
  that asks the question and designs the table anyway has not asked anything.

§33's twelve first goals and §34's fifteen demonstration steps each appear once,
by name, as a checklist.
"""

import json

import pytest

from dba import (agent as agent_module, apispec, capability, contract,
                 design as design_module, develop, entities, experience,
                 explain, patterns, permissions, records, registry, selfcheck,
                 store, tamil)

JARVIS = permissions.JARVIS
KRISH = permissions.OPERATOR_CONSOLE
COO = permissions.COO

HANDOFF_TASK = ("Create a persistent task handoff system so one agent can "
                "assign work to another")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def conn():
    connection = store.connect()
    store.init_schema(connection)
    yield connection
    connection.close()


def _requirement(**overrides):
    fields = dict(
        task=HANDOFF_TASK, requested_by=JARVIS,
        writers=(JARVIS, COO), readers=(permissions.LEARNING_ENGINE,),
        retention=capability.Retention(capability.KEEP_FOREVER,
                                       why="work history is auditable"))
    fields.update(overrides)
    return design_module.Requirement(**fields)


def _staged(conn=None):
    outcome = develop.request_capability(_requirement(), conn)
    assert outcome["status"] == "staged", outcome
    return outcome


# =============================================================================
# §8: reasoning from a task to a data model
# =============================================================================


def test_the_design_answers_all_twelve_of_the_questions_section_eight_asks(conn):
    """A design that cannot say why it has its shape is unreviewable, and §30's
    whole loop depends on a correction having something to correct."""
    result = design_module.design(_requirement(), conn)
    assert result.ready

    for question in ("entities", "attributes", "relationships", "unique",
                     "can_change", "never_changes", "history_preserved",
                     "searched_by", "indexed", "audited", "retained",
                     "expires"):
        assert question in result.reasoning, question
        assert result.reasoning[question], question


def test_the_shape_comes_from_the_task_and_not_from_a_template(conn):
    """The same designer produces different schemas for different sentences,
    which is the difference between reasoning and a fixed table."""
    handoff = design_module.design(_requirement(), conn).capability
    log = design_module.design(_requirement(
        task="Keep a log of every deployment event that occurred",
        name="deployment_event"), conn).capability

    assert "assigned_to" in handoff.entity_type.fields
    assert "assigned_to" not in log.entity_type.fields
    assert "occurred_at" in log.entity_type.fields
    # The log declares no update. That is the claim its archetype makes.
    assert contract.UPDATE in handoff.operations
    assert contract.UPDATE not in log.operations


def test_an_append_only_class_gets_no_update_endpoint(conn):
    log = design_module.design(_requirement(
        task="Keep a log of every deployment event that occurred",
        name="deployment_event"), conn).capability
    paths = {operation["operation"]
             for operation in apispec.contract_for(log)["operations"]}
    assert contract.UPDATE not in paths
    assert contract.CREATE in paths


def test_the_index_carries_the_reason_it_exists(conn):
    """An index nobody can justify is an index nobody will dare remove."""
    result = design_module.design(_requirement(), conn)
    assert result.capability.indexes == ("assigned_to", "status")
    assert "waiting for me" in result.reasoning["indexed"]


def test_the_name_comes_from_the_requirements_own_words(conn):
    assert design_module.design(_requirement(), conn).capability.name == \
        "task_handoff"


# =============================================================================
# §19: the eight things it will not decide on its own
# =============================================================================


def test_an_unclear_requirement_asks_rather_than_reaching_for_a_default(conn):
    result = design_module.design(
        _requirement(task="I need somewhere to put stuff"), conn)
    assert result.capability is None
    assert [q.reason for q in result.questions] == [design_module.UNCLEAR_ENTITY]
    assert not result.ready


def test_no_stated_permissions_is_a_question_and_not_a_guessed_grant(conn):
    result = design_module.design(
        _requirement(readers=(), writers=()), conn)
    reasons = {question.reason for question in result.questions}
    assert design_module.INSUFFICIENT_PERMISSIONS in reasons
    assert result.capability is None


def test_readers_but_no_writer_is_asked_about(conn):
    result = design_module.design(
        _requirement(writers=(), readers=(JARVIS,)), conn)
    reasons = {question.reason for question in result.questions}
    assert design_module.UNKNOWN_OWNERSHIP in reasons


def test_nobody_saying_how_long_is_not_the_same_as_keep_forever(conn):
    """§8 asks what should eventually expire. A table that grows until somebody
    notices is what the silent default produces."""
    result = design_module.design(_requirement(retention=None), conn)
    reasons = {question.reason for question in result.questions}
    assert design_module.UNCLEAR_RETENTION in reasons
    assert result.capability is None
    question = next(q for q in result.questions
                    if q.reason == design_module.UNCLEAR_RETENTION)
    assert {option["rule"] for option in question.options} == set(
        capability.RETENTION_RULES)


def test_an_unknown_agent_cannot_be_granted_anything(conn):
    result = design_module.design(
        _requirement(writers=("an_agent_that_does_not_exist",)), conn)
    reasons = {question.reason for question in result.questions}
    assert design_module.INSUFFICIENT_PERMISSIONS in reasons


def test_a_relationship_to_a_type_that_is_not_there_is_asked_about(conn):
    result = design_module.design(
        _requirement(relates_to=(("belongs_to", "nonexistent_type"),)), conn)
    reasons = {question.reason for question in result.questions}
    assert design_module.UNCERTAIN_RELATIONSHIP in reasons


def test_a_field_type_that_does_not_exist_is_a_conflict(conn):
    result = design_module.design(
        _requirement(extra_fields={"budget": "currency"}), conn)
    reasons = {question.reason for question in result.questions}
    assert design_module.CONFLICTING_REQUIREMENTS in reasons


def test_redeclaring_an_immutable_field_is_a_conflict(conn):
    result = design_module.design(
        _requirement(extra_fields={"requested_by": entities.TEXT}), conn)
    reasons = {question.reason for question in result.questions}
    assert design_module.CONFLICTING_REQUIREMENTS in reasons


def test_deleting_on_demand_is_asked_about_separately_from_expiry(conn):
    """§19's unsafe deletion. A retention rule that removes records and an
    agent that may remove one are different powers."""
    result = design_module.design(_requirement(
        retention=capability.Retention(capability.DELETE_AFTER_DAYS, days=30,
                                       why="short-lived")), conn)
    reasons = {question.reason for question in result.questions}
    assert design_module.UNSAFE_DELETION in reasons


def test_every_question_reason_is_in_the_closed_vocabulary():
    with pytest.raises(ValueError):
        design_module.Question(reason="because_i_felt_like_it", question="?")


def test_a_requirement_that_asks_builds_nothing(conn):
    """The property that makes an ask-back an ask-back."""
    before = len(registry.inventory(conn))
    outcome = develop.request_capability(_requirement(retention=None), conn)
    assert outcome["status"] == "clarification_required"
    assert len(registry.inventory(conn)) == before


# =============================================================================
# §27 and §28: it tests what it builds, before offering it
# =============================================================================


def test_the_generated_tests_actually_run_against_a_real_database(conn):
    result = design_module.design(_requirement(), conn)
    report = selfcheck.run_tests(result.capability)

    assert report["passed"], [case for case in report["cases"]
                              if not case["passed"]]
    assert report["total"] >= 12
    names = {case["case"] for case in report["cases"]}
    assert {"data_creation", "retrieval", "updates", "duplicate_handling",
            "permissions_are_enforced", "audit_records",
            "transactions_roll_back", "failure_recovery"} <= names


def test_the_generated_tests_write_nothing_to_the_live_store(conn):
    before = records.count(conn, "person", scope=records.ANY)
    result = design_module.design(_requirement(), conn)
    selfcheck.run_tests(result.capability)
    assert records.count(conn, "person", scope=records.ANY) == before
    assert registry.inventory(conn) == [], \
        "the battery must not leave a capability in the real registry"


def test_the_twelve_pre_publish_checks_are_all_asked(conn):
    result = design_module.design(_requirement(), conn)
    report = selfcheck.run_tests(result.capability)
    checks = selfcheck.self_check(result.capability, test_report=report,
                                  reuse=None)
    assert len(selfcheck.QUESTIONS) == 12
    assert len(checks["checks"]) == 12
    assert checks["passed"], checks["failing"]


def test_a_capability_whose_tests_fail_is_never_offered(conn, monkeypatch):
    """"Staged" means the DBA has done its part. Offering a failing design
    would put the decision in front of Krish with the work half done."""
    def failing(_designed):
        return {"passed": False, "total": 3, "failed": 1, "skipped": 0,
                "cases": [{"case": "data_creation", "passed": False,
                           "detail": "invented failure", "skipped": False}]}

    monkeypatch.setattr(selfcheck, "run_tests", failing)
    outcome = develop.request_capability(_requirement(), conn)

    assert outcome["status"] == "not_ready"
    assert registry.record(conn, outcome["capability"])["status"] == \
        capability.DRAFT
    assert registry.published(conn) == []


def test_a_failed_generated_test_becomes_a_lesson(conn, monkeypatch):
    def failing(_designed):
        return {"passed": False, "total": 1, "failed": 1, "skipped": 0,
                "cases": [{"case": "duplicate_handling", "passed": False,
                           "detail": "did not catch the collision",
                           "skipped": False}]}

    monkeypatch.setattr(selfcheck, "run_tests", failing)
    develop.request_capability(_requirement(), conn)

    failures = experience.lessons(conn, experience.TEST_FAILURE)
    assert any("duplicate_handling" in lesson["pattern"] for lesson in failures)


# =============================================================================
# §31: the DBA designs; Krish publishes
# =============================================================================


def test_the_designing_agent_cannot_publish_its_own_work(conn):
    staged = _staged(conn)
    refused = develop.publish(staged["capability"],
                              accepted_by=permissions.DBA, conn=conn)
    assert refused["status"] == "refused"
    assert "administer" in refused["why"]
    assert registry.published(conn) == []


def test_jarvis_cannot_publish_either(conn):
    staged = _staged(conn)
    refused = develop.publish(staged["capability"], accepted_by=JARVIS,
                              conn=conn)
    assert refused["status"] == "refused"
    assert registry.published(conn) == []


def test_the_dba_does_not_hold_the_permission_publishing_needs():
    """Structural rather than procedural: there is no flag to flip, and
    granting is not an operation the DBA has."""
    assert permissions.ADMINISTER not in permissions.permissions_of(permissions.DBA)
    assert permissions.ADMINISTER in permissions.permissions_of(KRISH)


def test_krish_publishing_brings_it_into_service(conn):
    staged = _staged(conn)
    published = develop.publish(staged["capability"], accepted_by=KRISH,
                                conn=conn)

    assert published["status"] == "published"
    assert published["serving_at"] == "/api/v1/task_handoff"
    assert entities.known("task_handoff")
    assert [c.key for c in registry.published(conn)] == ["task_handoff@1"]


def test_an_unpublished_capability_is_not_a_live_type(conn):
    _staged(conn)
    assert not entities.known("task_handoff")


def test_a_rejection_is_kept_as_learning_material(conn):
    """§30: the objective is not to fix one schema."""
    staged = _staged(conn)
    outcome = develop.reject(staged["capability"],
                             why="payload should be structured, not text",
                             rejected_by=KRISH, conn=conn)

    assert outcome["status"] == "rejected"
    corrections = experience.lessons(conn, experience.CORRECTION)
    assert any("payload should be structured" in lesson["lesson"]
               for lesson in corrections)


def test_a_retired_capability_stops_serving(conn):
    staged = _staged(conn)
    develop.publish(staged["capability"], accepted_by=KRISH, conn=conn)
    assert entities.known("task_handoff")

    registry.retire(conn, staged["capability"], accepted_by=KRISH)

    assert not entities.known("task_handoff")
    assert registry.published(conn) == []


# =============================================================================
# The finding the DBA's own generated tests produced
# =============================================================================


def test_a_capability_grant_is_enforced_and_not_merely_declared(conn):
    """THE DBA'S OWN TESTS FOUND THIS.

    A capability declared grants and nothing read them, so any agent holding
    global `create` could write to a capability that had granted it nothing.
    Permissions defined and not enforced are worse than permissions not
    defined, because the declaration tells anybody reading it otherwise."""
    staged = _staged(conn)
    develop.publish(staged["capability"], accepted_by=KRISH, conn=conn)
    agent = agent_module.DBAgent()

    # `dba` holds global create, and this capability granted it nothing.
    assert permissions.CREATE in permissions.permissions_of(permissions.DBA)
    assert permissions.DBA not in registry.grants_for("task_handoff")

    refused = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=permissions.DBA,
        entity_type="task_handoff",
        data={"name": "x", "requested_by": "dba", "assigned_to": "coo"}))

    assert refused.error["error_code"] == contract.PERMISSION_DENIED
    assert "not the same as being granted it here" in refused.error["message"]
    assert records.count(conn, "task_handoff") == 0


def test_a_granted_agent_is_still_allowed(conn):
    """The other half: enforcement that refused everybody would also pass the
    test above."""
    staged = _staged(conn)
    develop.publish(staged["capability"], accepted_by=KRISH, conn=conn)
    agent = agent_module.DBAgent()

    allowed = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="task_handoff",
        data={"name": "Do the thing", "requested_by": "JARVIS",
              "assigned_to": "coo"}))

    assert allowed.ok and allowed.changed


def test_a_read_only_grant_cannot_write(conn):
    staged = _staged(conn)
    develop.publish(staged["capability"], accepted_by=KRISH, conn=conn)
    agent = agent_module.DBAgent()

    read = agent.handle(contract.Request(
        action=contract.COUNT, requested_by=permissions.LEARNING_ENGINE,
        entity_type="task_handoff"))
    write = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=permissions.LEARNING_ENGINE,
        entity_type="task_handoff",
        data={"name": "x", "requested_by": "l", "assigned_to": "c"}))

    assert read.ok
    assert write.error["error_code"] == contract.PERMISSION_DENIED


def test_a_built_in_type_is_not_governed_by_capability_grants(conn):
    """None and `{}` mean different things: a built-in has no grant table, and
    conflating that with "granted nobody anything" would deny everything."""
    assert registry.grants_for("person") is None
    agent = agent_module.DBAgent()
    assert agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Still works"})).ok


# =============================================================================
# What a second review found
# =============================================================================


def test_a_link_cannot_reach_a_capability_that_granted_nothing(conn):
    """A relationship is a write to both records, and the agent's grant check
    reads `entity_type` - which a link does not carry. So any agent holding
    global `update` could relate records of a capability that had granted it
    nothing."""
    staged = develop.request_capability(_requirement(
        task="Create a persistent task handoff system so one agent can assign "
             "work to another",
        relates_to=(("concerns", "project"),)), conn)
    develop.publish(staged["capability"], accepted_by=KRISH, conn=conn)
    agent = agent_module.DBAgent()

    handoff = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="task_handoff",
        data={"name": "work", "requested_by": JARVIS, "assigned_to": COO}))
    project = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="project",
        data={"name": "Alpha"}))

    # `dba` holds global update and was granted nothing on this capability.
    refused = agent.handle(contract.Request(
        action=contract.LINK, requested_by=permissions.DBA,
        data={"from_id": handoff.entity_id, "relation": "concerns",
              "to_id": project.entity_id}))

    assert refused.error["error_code"] == contract.PERMISSION_DENIED
    assert "from_id is a task_handoff" in refused.error["message"]


def test_a_declared_delete_operation_is_actually_granted_to_somebody(conn):
    """An operation that is published, documented, and refused for every agent
    alive is a lie in the contract."""
    staged = develop.request_capability(_requirement(
        deletable=True,
        retention=capability.Retention(capability.DELETE_AFTER_DAYS, days=30,
                                       why="short-lived")), conn)
    declared = registry.get(conn, staged["capability"])

    assert contract.DELETE_AUTHORIZED in declared.operations
    # The WRITERS specifically, not merely somebody. Asserting "somebody" was
    # satisfied by the owner grant that is added to every capability, so the
    # test passed against the defect it was written for.
    assert permissions.DELETE in declared.grants[JARVIS]
    assert permissions.DELETE in declared.grants[COO]


def test_the_owner_is_never_locked_out_of_their_own_data(conn):
    """Capability grants are checked on top of the global policy, so a
    capability that did not name Krish's console made his own records
    unreadable to him - by a rule the DBA wrote for him."""
    staged = _staged(conn)
    develop.publish(staged["capability"], accepted_by=KRISH, conn=conn)
    agent = agent_module.DBAgent()

    assert agent.handle(contract.Request(
        action=contract.COUNT, requested_by=KRISH,
        entity_type="task_handoff")).ok


def test_a_capability_may_not_be_named_after_a_built_in_type(conn):
    """Publishing one would make `sync_entities` raise on every request from
    then on."""
    result = design_module.design(
        _requirement(task="Store agent state so it survives a restart",
                     name="agent_state"), conn)

    assert result.capability is None
    reasons = {question.reason for question in result.questions}
    assert design_module.CONFLICTING_REQUIREMENTS in reasons


def test_an_old_database_is_not_stamped_as_current(conn):
    """With the version written on every connection there was no state in
    which this could be behind, and a check that cannot fail is not a check."""
    conn.execute("UPDATE dba_meta SET value = '1' WHERE key = 'schema_version'")
    reopened = store.connect()
    try:
        store.init_schema(reopened)
        assert store.schema_version(reopened) == 1
        assert store.behind(reopened) is True
    finally:
        reopened.close()


def test_a_rejection_does_not_destroy_the_test_evidence(conn):
    """§30 keeps the correction as learning material; the first version
    overwrote the staged test report with the rejection reason."""
    staged = _staged(conn)
    develop.reject(staged["capability"], why="wrong shape", rejected_by=KRISH,
                   conn=conn)

    record = registry.record(conn, staged["capability"])

    assert record["test_report"]["rejected_because"] == "wrong shape"
    assert record["test_report"]["total"] >= 12, "the evidence survived"
    assert record["test_report"]["passed"] is True


def test_a_publication_is_recorded_as_an_episode(conn):
    """`meta_report` counts outcomes, so a state nothing ever writes is a
    claim that can never be true however many capabilities are published."""
    staged = _staged(conn)
    develop.publish(staged["capability"], accepted_by=KRISH, conn=conn)

    outcomes = {episode["outcome"] for episode in experience.episodes(conn)}
    assert experience.PUBLISHED in outcomes


# =============================================================================
# §26: versioning and compatibility
# =============================================================================


def test_a_breaking_change_is_identified_by_rule_and_not_by_judgement():
    first = design_module.design(_requirement()).capability
    narrowed = capability.Capability.from_dict({
        **first.to_dict(),
        "operations": [contract.CREATE],
        # `required`, `identifying` and `indexes` all narrow with the fields.
        # The declaration refuses to require or index a field it does not
        # declare, which is itself correct and is what the first two versions
        # of this test tripped over - twice, which is the useful part: the
        # guards fire in the order a careless edit would hit them.
        "indexes": [],
        "entity_type": {**first.entity_type.to_dict(),
                        "fields": {"name": "text"},
                        "required": ["name"], "identifying": []}})

    difference = capability.compare(first, narrowed)

    assert difference["verdict"] == capability.BREAKING
    assert any("was removed" in reason for reason in difference["breaking"])


def test_adding_an_optional_field_is_additive():
    first = design_module.design(_requirement()).capability
    widened = capability.Capability.from_dict({
        **first.to_dict(),
        "entity_type": {**first.entity_type.to_dict(),
                        "fields": {**first.entity_type.fields,
                                   "note": entities.TEXT}}})
    assert capability.compare(first, widened)["verdict"] == capability.ADDITIVE


def test_a_published_version_is_never_rewritten(conn):
    staged = _staged(conn)
    with pytest.raises(registry.RegistryRefused, match="written once"):
        registry.save_draft(conn, registry.get(conn, staged["capability"]))


def test_a_second_design_of_the_same_name_becomes_a_new_version(conn):
    first = _staged(conn)
    develop.publish(first["capability"], accepted_by=KRISH, conn=conn)

    second = develop.request_capability(
        _requirement(extra_fields={"note": entities.TEXT}), conn)

    assert second["capability"] == "task_handoff@2"
    assert registry.current(conn, "task_handoff").version == 1, \
        "v1 keeps serving until v2 is accepted"


def test_the_old_version_keeps_serving_while_the_new_one_waits(conn):
    first = _staged(conn)
    develop.publish(first["capability"], accepted_by=KRISH, conn=conn)
    develop.request_capability(_requirement(extra_fields={"note": entities.TEXT}),
                               conn)

    agent = agent_module.DBAgent()
    assert agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="task_handoff",
        data={"name": "Still works", "requested_by": "JARVIS",
              "assigned_to": "coo"})).ok


# =============================================================================
# §29: reuse before duplication
# =============================================================================


def test_an_existing_capability_of_the_same_name_is_offered_for_reuse(conn):
    first = _staged(conn)
    develop.publish(first["capability"], accepted_by=KRISH, conn=conn)

    again = design_module.design(_requirement(), conn)

    assert again.reuse is not None
    assert again.reuse["capability"] == "task_handoff@1"
    assert "extend it" in again.reuse["recommendation"]


def test_reuse_is_noted_in_the_pre_publish_checks(conn):
    """A genuinely different second design still gets told what exists."""
    first = _staged(conn)
    develop.publish(first["capability"], accepted_by=KRISH, conn=conn)

    again = develop.request_capability(
        _requirement(extra_fields={"note": entities.TEXT}), conn)

    check = next(item for item in again["self_check"]["checks"]
                 if item["check"] == "reuse_considered")
    assert "task_handoff@1" in check["detail"]


def test_asking_twice_for_the_same_thing_does_not_build_it_twice(conn):
    """§29 applied to the DBA's own output first. The fingerprint was stored
    and never read, so an identical requirement designed, tested and staged a
    byte-identical v2 beside the v1 already serving it."""
    first = _staged(conn)
    develop.publish(first["capability"], accepted_by=KRISH, conn=conn)

    again = develop.request_capability(_requirement(), conn)

    assert again.get("already_exists") is True
    assert again["capability"] == "task_handoff@1"
    assert [row["capability_key"] for row in registry.inventory(conn)] == \
        ["task_handoff@1"]


def test_a_rejected_design_is_not_offered_back_as_if_it_were_built(conn):
    """A rejected design was looked at and turned down. Answering the next
    identical request with it would be handing back the answer somebody
    already refused."""
    first = _staged(conn)
    develop.reject(first["capability"], why="payload should be structured",
                   rejected_by=KRISH, conn=conn)

    again = develop.request_capability(_requirement(), conn)

    assert again["status"] == "staged"
    assert again.get("already_exists") is None
    assert again["capability"] == "task_handoff@2"


# =============================================================================
# §10, §11, §30: the experience persists and is used
# =============================================================================


def test_every_design_attempt_is_recorded_including_the_ones_that_asked(conn):
    develop.request_capability(_requirement(retention=None), conn)
    develop.request_capability(_requirement(), conn)

    episodes = experience.episodes(conn)
    outcomes = {episode["outcome"] for episode in episodes}
    assert experience.ASKED in outcomes
    assert experience.STAGED in outcomes


def test_a_question_asked_repeatedly_becomes_advice_asked_up_front(conn):
    """The useful half of §10, and it is mechanical rather than aspirational."""
    for _ in range(experience.MIN_EPISODES_FOR_TREND):
        develop.request_capability(_requirement(retention=None), conn)

    advice = experience.advice_for(conn, "handoff_queue")

    assert any("unclear retention" in line for line in advice), advice
    assert any("up front" in line for line in advice)


def test_that_advice_reaches_the_next_design(conn):
    for _ in range(experience.MIN_EPISODES_FOR_TREND):
        develop.request_capability(_requirement(retention=None), conn)
    outcome = develop.request_capability(_requirement(retention=None), conn)
    assert outcome["advice_from_experience"]


def test_a_lesson_seen_twice_is_counted_rather_than_duplicated(conn):
    for _ in range(2):
        develop.request_capability(_requirement(retention=None), conn)
    recurring = [lesson for lesson in experience.lessons(conn,
                                                         experience.RECURRING_QUESTION)
                 if lesson["pattern"].endswith(design_module.UNCLEAR_RETENTION)]
    assert len(recurring) == 1
    assert recurring[0]["times_seen"] == 2


def test_meta_learning_refuses_to_generalise_from_one_design(conn):
    develop.request_capability(_requirement(), conn)
    report = experience.meta_report(conn)
    assert report["claims"] == []
    assert "one anecdote" in report["note"]


def test_the_experience_survives_because_it_is_in_the_database(conn):
    """§11: the DBA's learning must itself be persisted, not held in a process."""
    develop.request_capability(_requirement(), conn)
    reopened = store.connect()
    try:
        assert experience.episodes(reopened)
    finally:
        reopened.close()


# =============================================================================
# §25: the API contract
# =============================================================================


def test_the_contract_defines_all_ten_things_section_twenty_five_names(conn):
    result = design_module.design(_requirement(), conn)
    spec = apispec.contract_for(result.capability)

    assert spec["purpose"]
    assert spec["request"]["shape"]
    assert spec["response"]["shape"]
    assert spec["request"]["required_fields"]
    assert spec["request"]["optional_fields"]
    assert spec["validation"]
    assert spec["permissions"]
    assert spec["errors"]
    assert spec["version"] == 1
    assert spec["examples"]


def test_the_contract_cannot_describe_a_field_the_schema_does_not_have(conn):
    """Generated, so it cannot drift from the declaration it documents."""
    result = design_module.design(_requirement(), conn)
    spec = apispec.contract_for(result.capability)
    assert set(spec["request"]["field_types"]) == \
        set(result.capability.entity_type.fields)


def test_the_documentation_is_generated_from_the_same_declaration(conn):
    result = design_module.design(_requirement(), conn)
    text = apispec.markdown(result.capability)
    assert "# task_handoff — v1" in text
    assert "/api/v1/task_handoff/create" in text
    assert "assigned_to" in text
    assert "clarification_required" in text.lower()


# =============================================================================
# §12 and §13: Jarvis's state, and another agent's
# =============================================================================


def test_agent_state_is_available_without_waiting_for_a_capability(conn):
    """§12: Jarvis must survive a restart. State that only works once somebody
    publishes something is missing on the first restart that matters."""
    assert entities.known("agent_state")
    agent = agent_module.DBAgent()
    stored = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="agent_state",
        data={"name": "current_goals", "agent": "JARVIS", "kind": "goals",
              "value": json.dumps(["finish the DBA", "pass Krish's test"]),
              "status": "current"}))
    assert stored.ok and stored.changed


def test_jarvis_state_survives_a_restart(conn):
    """The actual claim, tested the only way it can be: write it, throw the
    process's agent away, read it back through a new one."""
    first = agent_module.DBAgent()
    first.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="agent_state",
        data={"name": "current_plan", "agent": "JARVIS", "kind": "plan",
              "value": "design the handoff capability", "status": "current"}))

    agent_module._AGENT = None
    registry.reset_sync()
    restarted = agent_module.DBAgent()

    found = restarted.handle(contract.Request(
        action=contract.FIND, requested_by=JARVIS, entity_type="agent_state",
        criteria={"agent": "JARVIS", "kind": "plan"}))
    assert found.result["count"] == 1
    assert found.result["matches"][0]["value"] == "design the handoff capability"


def test_a_second_agents_state_is_kept_apart_from_jarvis(conn):
    """§13. Two agents, one shape, no confusion about whose is whose."""
    agent = agent_module.DBAgent()
    for who in (JARVIS, COO):
        agent.handle(contract.Request(
            action=contract.CREATE, requested_by=who,
            entity_type="agent_state",
            data={"name": "config", "agent": who, "kind": "configuration",
                  "value": f"{who}-settings", "status": "current"}))

    coo_state = agent.handle(contract.Request(
        action=contract.FIND, requested_by=COO, entity_type="agent_state",
        criteria={"agent": COO}))
    assert coo_state.result["count"] == 1
    assert coo_state.result["matches"][0]["value"] == "coo-settings"


def test_agent_state_has_the_shape_the_designer_would_produce():
    """The honest link: this type is shipped rather than designed on demand,
    and this asserts it is still the designer's own output."""
    archetype = patterns.AGENT_STATE
    built_in = entities.get("agent_state")
    assert set(built_in.fields) == set(archetype.fields)
    assert built_in.required == archetype.required
    assert built_in.statuses == archetype.statuses


# =============================================================================
# §16: Tamil
# =============================================================================


def test_the_audit_trail_term_is_the_one_the_specification_gives():
    assert tamil.AUDIT_TRAIL == "தணிக்கைத் தடம்"
    assert tamil.TERMS["audit_trail"] == tamil.AUDIT_TRAIL


def test_the_explanation_is_available_in_tamil(conn):
    agent = agent_module.DBAgent()
    created = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Jane Doe"}))
    said = tamil.say(created)
    assert said["translated"] is True
    assert "உருவாக்கினேன்" in said["text"]


def test_a_shape_with_no_tamil_rendering_falls_back_rather_than_guessing(conn):
    """Half-translated output would be worse than English, and the sentence is
    the part a person actually reads."""
    response = contract.Response(status=contract.STATUS_SUCCESS,
                                 action=contract.RECONCILE, changed=True)
    said = tamil.say(response)
    assert said["translated"] is False
    assert said["text"] == explain.explain(response)
    assert "half-translated" in said["why"]


def test_tamil_is_honest_about_what_it_does_not_cover():
    described = tamil.describe()
    assert "Jarvis's other surfaces" in described["does_not_cover"]
    assert described["falls_back_to_english"] is True


# =============================================================================
# §34: the acceptance demonstration, through the service
# =============================================================================


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from dba.main import app

    monkeypatch.setenv("DBA_TOKEN_JARVIS", "jarvis-token-not-real")
    monkeypatch.setenv("DBA_TOKEN_OPERATOR_CONSOLE", "krish-token-not-real")
    monkeypatch.setenv("DBA_TOKEN_COO", "coo-token-not-real")
    return TestClient(app)


AS_JARVIS = {"X-DBA-Agent": JARVIS, "X-DBA-Token": "jarvis-token-not-real"}
AS_KRISH = {"X-DBA-Agent": KRISH, "X-DBA-Token": "krish-token-not-real"}
AS_COO = {"X-DBA-Agent": COO, "X-DBA-Token": "coo-token-not-real"}


def test_the_acceptance_demonstration(client, conn):
    """§34's fifteen steps, in order, over HTTP.

    *"If this complete flow works, the core concept has been demonstrated."*

    One test rather than fifteen, because the claim is that the **flow** works:
    a step that passes in isolation while the one before it left the wrong
    state behind has demonstrated nothing."""
    # 1. Jarvis asks for a new persistent capability.
    asked = client.post("/capabilities/design", json={"task": HANDOFF_TASK},
                        headers=AS_JARVIS).json()

    # 2 & 3. The DBA analyses it, and asks for what it will not decide.
    assert asked["status"] == "clarification_required"
    assert asked["match"]["archetype"] == "handoff_queue"
    reasons = {question["reason"] for question in asked["questions"]}
    assert design_module.UNCLEAR_RETENTION in reasons
    assert registry.inventory(conn) == [], "nothing was built by a question"

    # 4, 5, 6, 7. Answered: it designs the schema, creates it, builds the APIs
    # and generates the tests.
    built = client.post("/capabilities/design", json={
        "task": HANDOFF_TASK, "writers": [JARVIS, COO],
        "readers": [permissions.LEARNING_ENGINE],
        "retention": {"rule": "keep_forever", "why": "work history is auditable"},
    }, headers=AS_JARVIS).json()
    assert built["status"] == "staged"
    key = built["capability"]

    # 8. The tests pass.
    assert built["tests"]["passed"]
    assert built["tests"]["failed"] == 0
    assert built["self_check"]["passed"]

    # 9. The API contract is published - and not by the DBA or by Jarvis.
    assert client.post(f"/capabilities/{key}/publish",
                       headers=AS_JARVIS).status_code == 403
    published = client.post(f"/capabilities/{key}/publish", headers=AS_KRISH)
    assert published.status_code == 200
    base = published.json()["serving_at"]
    assert base == "/api/v1/task_handoff"
    assert client.get("/capabilities/task_handoff",
                      headers=AS_JARVIS).status_code == 200
    assert "assigned_to" in client.get("/capabilities/task_handoff/docs",
                                       headers=AS_JARVIS).text

    # 10. Agent A creates a work request through the API.
    created = client.post(f"{base}/create", json={"data": {
        "name": "Reconcile September statements", "requested_by": JARVIS,
        "assigned_to": COO, "payload": '{"month": "2026-09"}',
        "correlation_id": "handoff-001", "status": "queued"}},
        headers=AS_JARVIS)
    assert created.status_code == 200 and created.json()["changed"]
    work_id = created.json()["entity_id"]

    # 11. Agent B retrieves the work request through the API.
    waiting = client.post(f"{base}/find", json={
        "criteria": {"assigned_to": COO, "status": "queued"}},
        headers=AS_COO).json()
    assert waiting["result"]["count"] == 1
    assert waiting["result"]["matches"][0]["id"] == work_id

    # 12. Agent B updates the work status.
    finished = client.post(f"{base}/update", json={
        "entity_id": work_id,
        "data": {"status": "done", "result": "3 statements reconciled"},
        "reason": "finished the reconciliation"}, headers=AS_COO).json()
    assert finished["changed"]
    assert "status" in finished["explanation"]
    assert finished["explanation_ta"], "§16: answerable in Tamil too"

    # 13. The complete interaction is persisted.
    read_back = client.post(f"{base}/get", json={"entity_id": work_id},
                            headers=AS_JARVIS).json()
    assert read_back["result"]["status"] == "done"
    assert read_back["result"]["result"] == "3 statements reconciled"

    # 14. The complete audit trail is available.
    history = client.post(f"{base}/history", json={"entity_id": work_id},
                          headers=AS_JARVIS).json()
    events = history["result"]["events"]
    assert [event["action"] for event in events] == [contract.CREATE,
                                                     contract.UPDATE]
    assert [event["requesting_agent"] for event in events] == [JARVIS, COO]
    assert events[1]["new_summary"] == {"status": "done",
                                        "result": "3 statements reconciled"}
    assert events[1]["reason"] == "finished the reconciliation"

    # 15. The DBA stored what it learned from creating this capability.
    learned = client.get("/experience", headers=AS_KRISH).json()
    assert learned["meta"]["episodes"] >= 2
    assert learned["recent_designs"]
    assert any(lesson["kind"] == experience.ARCHETYPE_FIT
               for lesson in learned["lessons"])


def test_an_operation_the_capability_did_not_declare_is_not_a_path(client, conn):
    """A 404 on that path rather than a 422 on a shared one: an append-only log
    has no update endpoint, and that is a statement about the capability."""
    built = client.post("/capabilities/design", json={
        "task": "Keep a log of every deployment event that occurred",
        "name": "deployment_event", "writers": [JARVIS],
        "retention": {"rule": "keep_forever", "why": "it is the record"},
    }, headers=AS_JARVIS).json()
    client.post(f"/capabilities/{built['capability']}/publish", headers=AS_KRISH)

    created = client.post("/api/v1/deployment_event/create", json={"data": {
        "name": "release 1.4", "occurred_at": "2026-09-21T09:00:00+00:00"}},
        headers=AS_JARVIS)
    updated = client.post("/api/v1/deployment_event/update", json={
        "entity_id": created.json()["entity_id"], "data": {"name": "edited"}},
        headers=AS_JARVIS)

    assert created.status_code == 200
    assert updated.status_code == 404
    assert "does not offer" in updated.json()["detail"]


def test_a_capability_that_is_not_published_has_no_endpoint(client, conn):
    built = client.post("/capabilities/design", json={
        "task": HANDOFF_TASK, "writers": [JARVIS],
        "retention": {"rule": "keep_forever", "why": "x"}},
        headers=AS_JARVIS).json()
    assert built["status"] == "staged"
    response = client.post("/api/v1/task_handoff/create",
                           json={"data": {"name": "x"}}, headers=AS_JARVIS)
    assert response.status_code == 404


def test_the_published_list_says_where_each_capability_lives(client, conn):
    built = client.post("/capabilities/design", json={
        "task": HANDOFF_TASK, "writers": [JARVIS],
        "retention": {"rule": "keep_forever", "why": "x"}},
        headers=AS_JARVIS).json()
    client.post(f"/capabilities/{built['capability']}/publish", headers=AS_KRISH)

    listed = client.get("/capabilities", headers=AS_JARVIS).json()["published"]

    assert [item["base_path"] for item in listed] == ["/api/v1/task_handoff"]
    assert listed[0]["contract"] == "/capabilities/task_handoff"


def test_the_catalogue_is_not_readable_without_a_credential(client, conn):
    """Every other route authenticates; these three did not, so an
    unauthenticated caller could read the whole inventory - including the
    declarations of designs that were rejected, which are kept on purpose
    (§30) and are nobody else's business."""
    for path in ("/capabilities", "/capabilities/task_handoff",
                 "/capabilities/task_handoff/docs"):
        assert client.get(path).status_code == 401, path


def test_a_draft_declaration_is_not_served_as_a_contract(client, conn):
    """Reading by key ignores status, so `?version=` served a design nobody
    had accepted to anyone who guessed the number. A contract is a promise
    about what is serving."""
    built = client.post("/capabilities/design", json={
        "task": HANDOFF_TASK, "writers": [JARVIS],
        "retention": {"rule": "keep_forever", "why": "x"}},
        headers=AS_JARVIS).json()
    assert built["status"] == "staged"

    response = client.get("/capabilities/task_handoff?version=1",
                          headers=AS_JARVIS)

    assert response.status_code == 404


def test_an_older_version_keeps_serving_after_a_newer_one_is_published(
        client, conn):
    """§26, and the registry's own docstring: both serve until the old one is
    retired. Serving only the newest turned every existing v1 caller's path
    into a 404 the moment v2 was accepted."""
    first = client.post("/capabilities/design", json={
        "task": HANDOFF_TASK, "writers": [JARVIS],
        "retention": {"rule": "keep_forever", "why": "x"}},
        headers=AS_JARVIS).json()
    client.post(f"/capabilities/{first['capability']}/publish", headers=AS_KRISH)

    second = client.post("/capabilities/design", json={
        "task": HANDOFF_TASK, "writers": [JARVIS],
        "retention": {"rule": "keep_forever", "why": "x"},
        "extra_fields": {"note": "text"}}, headers=AS_JARVIS).json()
    assert second["capability"] == "task_handoff@2"
    client.post(f"/capabilities/{second['capability']}/publish", headers=AS_KRISH)

    still_v1 = client.post("/api/v1/task_handoff/create", json={"data": {
        "name": "written by an old caller", "requested_by": JARVIS,
        "assigned_to": COO}}, headers=AS_JARVIS)
    now_v2 = client.post("/api/v2/task_handoff/create", json={"data": {
        "name": "written by a new caller", "requested_by": JARVIS,
        "assigned_to": COO, "note": "v2 only"}}, headers=AS_JARVIS)

    assert still_v1.status_code == 200, still_v1.json()
    assert now_v2.status_code == 200, now_v2.json()


def test_a_rejection_needs_a_reason(client, conn):
    built = client.post("/capabilities/design", json={
        "task": HANDOFF_TASK, "writers": [JARVIS],
        "retention": {"rule": "keep_forever", "why": "x"}},
        headers=AS_JARVIS).json()
    response = client.post(f"/capabilities/{built['capability']}/reject",
                           json={}, headers=AS_KRISH)
    assert response.status_code == 400
    assert "teaches nothing" in response.json()["detail"]


def test_gateway_and_backend_know_nothing_about_this_schema():
    """§36: they should know the DBA Agent's published interface, and that is
    all. Asserted as an absence, which is the only way to assert it."""
    import pathlib

    repo = pathlib.Path(__file__).resolve().parent.parent
    for folder in ("gateway", "backend"):
        for path in (repo / folder).glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "task_handoff" not in text, path
            assert "from dba" not in text and "import dba" not in text, path


# =============================================================================
# §33: the twelve first goals, as a checklist
# =============================================================================


def test_the_twelve_first_practical_goals(conn):
    """§33, each asserted rather than asserted about."""
    # 1. Operates as a separate DBA Agent.
    import pathlib

    repo = pathlib.Path(__file__).resolve().parent.parent
    embedded = [path.name for path in
                list((repo / "gateway").glob("*.py")) + list((repo / "backend").glob("*.py"))
                if "from dba" in path.read_text(encoding="utf-8")
                or "import dba" in path.read_text(encoding="utf-8")]
    assert embedded == [], embedded

    # 2. A stable API interface for Jarvis.
    assert apispec.contract_for(design_module.design(_requirement(), conn).capability)

    # 3 & 4. Jarvis's state, and another agent's.
    agent = agent_module.DBAgent()
    for who in (JARVIS, COO):
        assert agent.handle(contract.Request(
            action=contract.CREATE, requested_by=who, entity_type="agent_state",
            data={"name": "state", "agent": who, "kind": "configuration",
                  "value": "x", "status": "current"})).ok

    # 6 & 7. A schema designed from a requirement, and its APIs.
    staged = _staged(conn)
    published = develop.publish(staged["capability"], accepted_by=KRISH,
                                conn=conn)
    assert published["serving_at"] == "/api/v1/task_handoff"

    # 5. Agent-to-agent work storage and retrieval, through that capability.
    handed = agent_module.DBAgent().handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="task_handoff",
        data={"name": "Reconcile statements", "requested_by": "JARVIS",
              "assigned_to": COO, "status": "queued"}))
    waiting = agent_module.DBAgent().handle(contract.Request(
        action=contract.FIND, requested_by=COO, entity_type="task_handoff",
        criteria={"assigned_to": COO, "status": "queued"}))
    assert handed.ok and waiting.result["count"] == 1

    # 8. A complete audit trail.
    from dba import audit

    assert audit.for_entity(conn, handed.entity_id)

    # 9. Permissions enforced.
    assert agent_module.DBAgent().handle(contract.Request(
        action=contract.CREATE, requested_by=permissions.LEARNING_ENGINE,
        entity_type="task_handoff",
        data={"name": "x", "requested_by": "l", "assigned_to": "c"})
    ).error["error_code"] == contract.PERMISSION_DENIED

    # 10. Clarification when ambiguous.
    assert develop.request_capability(
        _requirement(task="I need somewhere to put stuff", name=None),
        conn)["status"] == "clarification_required"

    # 11. Automated tests created and run for the generated schema.
    record = registry.record(conn, staged["capability"])
    assert record["test_report"]["passed"]
    assert record["test_report"]["total"] >= 12

    # 12. The design experience stored for later learning.
    assert experience.episodes(conn)
    assert experience.lessons(conn)
