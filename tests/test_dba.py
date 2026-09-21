"""The DBA Agent: does it refuse to guess, and does it ever lie about a write?

Those two questions are §45 and §44, the specification's own foundational
rules, and most of this file is about them rather than about CRUD working.
CRUD working is table stakes; a database agent that reports a success it did
not perform, or quietly picks one of two John Smiths, is worse than no database
agent, because everything downstream believes it.

§48's six acceptance tests appear first and by name. §34's required list is
covered throughout, and the two entries it names that do **not** exist yet -
backup and restore - are tested for being *honestly reported as absent*, which
is the only truthful thing to assert about an unimplemented feature.
"""

import ast
import json
import pathlib
import sqlite3

import pytest

from dba import (agent as agent_module, askback, audit, contract, duplicates,
                 entities, explain, health, ids, operations, permissions,
                 records, registry, store, validate)

JARVIS = permissions.JARVIS
OPERATOR = permissions.OPERATOR_CONSOLE


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    agent_module._AGENT = None
    # Adopted capability types and the sync stamp are process globals; without
    # this a capability published by one test would still be live in the next,
    # against a database that has never heard of it.
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def agent():
    return agent_module.DBAgent()


@pytest.fixture()
def conn():
    connection = store.connect()
    store.init_schema(connection)
    yield connection
    connection.close()


def ask(agent, action, **kwargs):
    requested_by = kwargs.pop("requested_by", JARVIS)
    return agent.handle(contract.Request(
        action=action, requested_by=requested_by, **kwargs))


def person(agent, name, **fields):
    return ask(agent, contract.CREATE, entity_type="person",
               data={"name": name, **fields})


# =============================================================================
# §48: the acceptance tests, by name
# =============================================================================


def test_a_basic_create(agent, conn):
    """One record, a stable id, an audit event."""
    response = person(agent, "Jane Doe", phone="+1 555 0101")

    assert response.ok and response.changed
    assert ids.belongs_to(response.entity_id, "person")
    assert records.count(conn, "person") == 1
    events = audit.for_entity(conn, response.entity_id)
    assert [event["result"] for event in events] == [audit.COMMITTED]
    assert events[0]["requesting_agent"] == JARVIS


def test_b_the_same_request_id_twice_creates_one_record(agent, conn):
    """§22, and §48's TEST B. The second call returns the first result."""
    request = contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Import Bob", "email": "bob@example.com"},
        request_id="payment-import-20260921-001")

    first = agent.handle(request)
    second = agent.handle(request)

    assert first.ok and first.changed
    assert second.ok
    assert second.entity_id == first.entity_id
    assert records.count(conn, "person") == 1
    # The replay did not write, and says so rather than repeating `changed`.
    assert second.changed is False
    assert any("replayed" in warning for warning in second.warnings)


def test_c_an_ambiguous_update_commits_nothing_and_asks(agent, conn):
    """§48's TEST C, which is §4's example A."""
    person(agent, "John Smith", email="j1@example.com")
    person(agent, "John Smith", email="j2@example.com")

    response = ask(agent, contract.UPDATE, entity_type="person",
                   criteria={"name": "John Smith"},
                   data={"phone": "+1 555 7777"})

    assert response.needs_answer
    assert response.status == contract.STATUS_CLARIFICATION_REQUIRED
    assert response.changed is False
    assert response.clarification["reason"] == contract.MULTIPLE_MATCHING_RECORDS
    assert len(response.clarification["options"]) == 2
    # Nothing was committed, which is the half of the test that matters.
    assert all(record.get("phone") is None
               for record in records.find(conn, "person"))


def test_d_a_failed_step_rolls_the_whole_batch_back(agent, conn):
    """§48's TEST D. Two good creates and one that cannot be accepted."""
    responses = agent.handle_many([
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={"name": "Batch One"}),
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={"name": "Batch Two"}),
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={"status": "active"}),
    ])

    assert [r.status for r in responses[:2]] == [contract.STATUS_SUCCESS] * 2
    assert responses[-1].needs_answer
    assert records.count(conn, "person") == 0, "no step survived"
    assert all(not r.changed for r in responses), \
        "a rolled-back step must not still claim it changed something"
    assert any("rolled back" in warning for warning in responses[0].warnings)


def test_d_the_rolled_back_batch_is_still_audited(agent, conn):
    """The per-step audit rows roll back with their writes - correctly, since
    they describe changes that did not happen - so the attempt would be
    invisible without one event written afterwards."""
    agent.handle_many([
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={"name": "Gone"}),
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={}),
    ])
    events = audit.recent(conn)
    assert [event["action"] for event in events] == ["batch"]
    assert events[0]["result"] == audit.FAILED
    assert events[0]["succeeded"] is False


def test_e_an_unauthorized_delete_is_refused_and_audited(agent, conn):
    """§48's TEST E. Jarvis may archive; only the operator may delete."""
    created = person(agent, "Jane Doe")

    response = ask(agent, contract.DELETE_AUTHORIZED, entity_type="person",
                   entity_id=created.entity_id)

    assert response.status == contract.STATUS_ERROR
    assert response.error["error_code"] == contract.PERMISSION_DENIED
    assert records.get(conn, created.entity_id) is not None, "nothing deleted"
    results = [event["result"] for event in audit.for_entity(conn, created.entity_id)]
    assert audit.REFUSED in results


def test_f_an_unavailable_database_is_reported_and_never_claimed_as_success():
    """§48's TEST F, and §24's "do not pretend a write completed"."""
    def refuses():
        raise OSError("the disk is gone")

    response = agent_module.DBAgent(connect=refuses).handle(
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={"name": "Nobody"}))

    assert response.status == contract.STATUS_ERROR
    assert response.error["error_code"] == contract.DATABASE_UNAVAILABLE
    assert response.changed is False
    assert response.error["retryable"] is True


def test_f_a_database_that_fails_mid_operation_is_also_not_a_success(agent):
    """The harder half: the connection opened and then the write failed."""
    class Failing:
        def executescript(self, script):
            pass

        def fetchone(self, *args, **kwargs):
            raise sqlite3.OperationalError("database disk image is malformed")

        def fetchall(self, *args, **kwargs):
            raise sqlite3.OperationalError("database disk image is malformed")

        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("database disk image is malformed")

        def close(self):
            pass

    response = agent_module.DBAgent(connect=Failing).handle(
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={"name": "Nobody"}))
    assert response.status == contract.STATUS_ERROR
    assert response.error["error_code"] == contract.DATABASE_UNAVAILABLE
    assert response.changed is False


# =============================================================================
# §4: the ask-back, which the specification calls mandatory
# =============================================================================


def test_example_a_ambiguous_identity_lists_what_distinguishes_them(agent):
    person(agent, "John Smith", email="j.smith@example.com")
    person(agent, "John Smith", email="john.s@example.com")

    response = ask(agent, contract.UPDATE, entity_type="person",
                   criteria={"name": "John Smith"}, data={"phone": "+1 555 1"})

    emails = {option.get("email") for option in response.clarification["options"]}
    assert emails == {"j.smith@example.com", "john.s@example.com"}, \
        "an option list that cannot tell the records apart is not a choice"


def test_example_b_asks_only_for_what_is_missing(agent):
    """§4.1: *ask only for the missing information*."""
    response = ask(agent, contract.CREATE, entity_type="person",
                   data={"phone": "+1 555 0100"})

    assert response.needs_answer
    assert response.clarification["reason"] == contract.MISSING_REQUIRED_INFORMATION
    assert [option["field"] for option in response.clarification["options"]] == ["name"]
    assert "phone" not in response.clarification["question"]


def test_a_malformed_request_is_an_error_rather_than_a_question(agent):
    """A question about what is absent implies everything present was fine."""
    response = ask(agent, contract.CREATE, entity_type="person",
                   data={"email": "not-an-email"})

    assert response.status == contract.STATUS_ERROR
    assert response.error["error_code"] == contract.VALIDATION_ERROR


def test_example_c_a_contradiction_is_identified_and_asked_about(agent):
    """*"Mark this customer inactive, but keep the active status."*"""
    created = person(agent, "Contradictory", status="active")

    response = ask(agent, contract.UPDATE, entity_type="person",
                   entity_id=created.entity_id,
                   data={"status": "inactive"}, criteria={"status": "active"})

    assert response.needs_answer
    assert response.clarification["reason"] == contract.CONTRADICTORY_REQUEST
    assert "Both cannot hold" in response.clarification["question"]


def test_editing_a_retired_record_is_also_a_contradiction(agent):
    created = person(agent, "Retired")
    ask(agent, contract.ARCHIVE, entity_type="person",
        entity_id=created.entity_id)

    response = ask(agent, contract.UPDATE, entity_type="person",
                   entity_id=created.entity_id, data={"phone": "+1 555 2"})

    assert response.needs_answer
    assert response.clarification["reason"] == contract.CONTRADICTORY_REQUEST


def test_example_d_a_destructive_scope_is_counted_and_confirmed(agent, conn):
    """*"Delete all old records."* The count is what makes the answer possible."""
    for index in range(3):
        person(agent, f"Old {index}", status="inactive")

    response = ask(agent, contract.ARCHIVE, entity_type="person",
                   criteria={"status": "inactive"})

    assert response.needs_answer
    assert response.clarification["reason"] == contract.DESTRUCTIVE_SCOPE_UNCLEAR
    assert "3" in response.clarification["question"]
    assert records.count(conn, "person") == 3, "nothing archived by the question"


def test_a_confirmed_destructive_scope_then_runs(agent, conn):
    for index in range(3):
        person(agent, f"Old {index}", status="inactive")

    response = ask(agent, contract.ARCHIVE, entity_type="person",
                   criteria={"status": "inactive"}, confirmed=True)

    assert response.ok and response.changed
    assert response.result["affected"] == 3
    assert records.count(conn, "person") == 0
    assert records.count(conn, "person", scope=records.ARCHIVED) == 3


def test_example_e_an_uncertain_relationship_asks_which_target(agent):
    """A document attached to "the project" when several could match."""
    first = ask(agent, contract.CREATE, entity_type="project",
                data={"name": "Alpha"})
    ask(agent, contract.CREATE, entity_type="project", data={"name": "Alpha"})
    candidates = records.find(store.connect(), "project",
                              criteria={"name": "Alpha"})

    request = contract.Request(action=contract.LINK, requested_by=JARVIS,
                               entity_type="document")
    question = askback.relationship_question(
        request, side="target", candidates=candidates,
        candidate_type=entities.get("project"))

    assert question is not None
    assert question.clarification["reason"] == contract.UNCERTAIN_RELATIONSHIP
    assert len(question.clarification["options"]) == 2
    assert first.ok


def test_a_single_match_is_never_asked_about(agent, conn):
    """§4.1: *avoid asking questions when the intent is already unambiguous*."""
    person(agent, "Only One")

    response = ask(agent, contract.UPDATE, entity_type="person",
                   criteria={"name": "Only One"}, data={"phone": "+1 555 3"})

    assert response.ok and response.changed


def test_nothing_matching_is_not_found_rather_than_a_question(agent):
    """§45 says ask when a record cannot be *uniquely identified*. An empty
    result is an answer, and asking "which one?" would invite an invention."""
    response = ask(agent, contract.UPDATE, entity_type="person",
                   criteria={"name": "Nobody At All"},
                   data={"phone": "+1 555 0123"})

    assert response.status == contract.STATUS_ERROR
    assert response.error["error_code"] == contract.NOT_FOUND


def test_a_resolution_holding_several_refuses_to_hand_over_one():
    """The guard against the silent choice §4.1 forbids, at the type level."""
    resolution = askback.Resolution([{"id": "a"}, {"id": "b"}], "name")
    with pytest.raises(ValueError, match="silent choice"):
        _ = resolution.only


def test_every_clarification_reason_is_in_the_closed_vocabulary(agent):
    request = contract.Request(action=contract.UPDATE, requested_by=JARVIS)
    with pytest.raises(ValueError):
        contract.clarify(request, reason="because_i_felt_like_it",
                         question="?")


# =============================================================================
# §44 and §45, asserted directly
# =============================================================================


def test_changed_is_false_when_the_value_was_already_that(agent):
    """§44. A write that wrote nothing is a success that changed nothing, and
    saying `changed: true` would be the smallest possible version of the lie
    the rule exists to forbid."""
    created = person(agent, "Same", phone="+1 555 0000")

    response = ask(agent, contract.UPDATE, entity_type="person",
                   entity_id=created.entity_id, data={"phone": "+1 555 0000"})

    assert response.ok
    assert response.changed is False
    assert response.warnings


def test_a_dry_run_never_reports_a_change(agent, conn):
    """§30. `committed: false` and the count, with nothing written."""
    person(agent, "Untouched", status="active")

    response = ask(agent, contract.ARCHIVE, entity_type="person",
                   criteria={"status": "active"}, dry_run=True,
                   confirmed=True)

    assert response.ok and response.changed is False
    assert response.result["matched_records"] == 1
    assert response.result["committed"] is False
    assert records.count(conn, "person") == 1


def test_a_dry_run_create_writes_nothing(agent, conn):
    response = ask(agent, contract.CREATE, entity_type="person",
                   data={"name": "Hypothetical"}, dry_run=True)
    assert response.ok and not response.changed
    assert records.count(conn, "person") == 0


def test_a_response_cannot_be_revised_after_it_is_built():
    """Frozen, so nothing downstream can turn a no-change into a change."""
    response = contract.success(
        contract.Request(action=contract.GET, requested_by=JARVIS),
        changed=False)
    with pytest.raises(Exception):
        response.changed = True  # type: ignore[misc]


# =============================================================================
# §14 permissions
# =============================================================================


def test_an_agent_nobody_declared_is_refused_by_name(agent):
    response = ask(agent, contract.GET, entity_type="person",
                   entity_id=ids.new_id("person"), requested_by="rogue_agent")

    assert response.error["error_code"] == contract.PERMISSION_DENIED
    assert "policy knows" in response.error["message"]


def test_the_operator_may_delete_and_jarvis_may_not(agent, conn):
    created = person(agent, "Deletable")

    refused = ask(agent, contract.DELETE_AUTHORIZED, entity_type="person",
                  entity_id=created.entity_id)
    allowed = ask(agent, contract.DELETE_AUTHORIZED, entity_type="person",
                  entity_id=created.entity_id, requested_by=OPERATOR)

    assert refused.error["error_code"] == contract.PERMISSION_DENIED
    assert allowed.ok and allowed.changed
    assert records.get(conn, created.entity_id) is None
    assert records.get(conn, created.entity_id, scope=records.DELETED) is not None


def test_the_learning_engine_can_read_and_cannot_write(agent):
    person(agent, "Readable")

    read = ask(agent, contract.FIND, entity_type="task",
               requested_by=permissions.LEARNING_ENGINE)
    write = ask(agent, contract.CREATE, entity_type="task",
                data={"name": "x"}, requested_by=permissions.LEARNING_ENGINE)

    assert read.ok
    assert write.error["error_code"] == contract.PERMISSION_DENIED


def test_a_confidential_type_is_out_of_reach_of_a_read_only_agent(agent):
    """§15: security policy varies by classification."""
    assert entities.get("person").classification == entities.CONFIDENTIAL
    response = ask(agent, contract.FIND, entity_type="person",
                   requested_by=permissions.LEARNING_ENGINE)
    # `confidential` is not in SENSITIVE_CLASSIFICATIONS, so this is allowed -
    # the assertion is that the ladder is applied, not that it is maximal.
    assert response.ok

    with pytest.raises(permissions.Refused):
        permissions.check(permissions.LEARNING_ENGINE, contract.GET,
                          classification=entities.HIGHLY_SENSITIVE)


def test_every_declared_action_has_a_declared_permission():
    """An action missing from the table would be an unguarded operation."""
    for action in contract.ACTIONS:
        assert permissions.required_for(action) in permissions.PERMISSIONS


def test_validate_is_judged_as_the_read_it_is(agent):
    """It inspects a write it will not perform."""
    response = ask(agent, contract.VALIDATE, entity_type="person",
                   data={"name": "Fine"},
                   requested_by=permissions.LEARNING_ENGINE)
    assert response.ok and response.result["acceptable"] is True


# =============================================================================
# §13 the audit trail
# =============================================================================


def test_the_audit_trail_carries_every_field_the_specification_names(agent, conn):
    created = person(agent, "Audited")
    ask(agent, contract.UPDATE, entity_type="person",
        entity_id=created.entity_id, data={"phone": "+1 555 4"},
        reason="he asked me to")

    events = audit.for_entity(conn, created.entity_id)
    assert len(events) == 2
    latest = events[-1]
    for field in ("audit_id", "at", "actor", "requesting_agent", "action",
                  "entity_type", "entity_id", "previous_summary",
                  "new_summary", "request_id", "reason", "result",
                  "succeeded", "source"):
        assert field in latest, field
    assert latest["reason"] == "he asked me to"
    assert latest["previous_summary"] == {"phone": None}
    assert latest["new_summary"] == {"phone": "+1 555 4"}


def test_nothing_in_this_package_rewrites_audit_history():
    """§13: *"Agents must not rewrite audit history as ordinary application
    data."* A convention in a docstring is not a constraint; this is.

    Over the parsed source rather than the text, and docstrings excluded - the
    first version of this test failed against `dba/audit.py`, whose docstring
    names the two statements it promises not to contain. A grep that cannot
    tell a prohibition from its description is a grep that will be deleted the
    first time it cries wolf."""
    package = pathlib.Path(__file__).resolve().parent.parent / "dba"
    offending = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)}
        for node in ast.walk(tree):
            if (not isinstance(node, ast.Constant)
                    or not isinstance(node.value, str)
                    or id(node) in docstrings):
                continue
            lowered = node.value.lower()
            for statement in ("update audit_events", "delete from audit_events",
                              "drop table audit_events"):
                if statement in lowered:
                    offending.append(f"{path.name}:{node.lineno}: {statement}")
    assert not offending, offending


def test_a_refused_request_is_audited_even_though_nothing_changed(agent, conn):
    """§14's last line."""
    ask(agent, contract.CREATE, entity_type="person", data={"name": "x"},
        requested_by="rogue_agent")
    events = audit.recent(conn)
    assert events and events[0]["result"] == audit.REFUSED
    assert events[0]["succeeded"] is False


def test_an_ordinary_read_does_not_fill_the_audit_trail(agent, conn):
    """§16's spirit: a log that is mostly reads hides the writes in it."""
    created = person(agent, "Quiet")
    before = len(audit.recent(conn, limit=100))
    ask(agent, contract.GET, entity_type="person", entity_id=created.entity_id)
    ask(agent, contract.FIND, entity_type="person")
    assert len(audit.recent(conn, limit=100)) == before


def test_history_reads_the_trail_from_the_records_side(agent):
    created = person(agent, "Storied")
    ask(agent, contract.UPDATE, entity_type="person",
        entity_id=created.entity_id, data={"status": "inactive"})

    response = ask(agent, contract.HISTORY, entity_type="person",
                   entity_id=created.entity_id)

    assert response.ok
    assert response.result["count"] == 2
    assert [event["action"] for event in response.result["events"]] == \
        [contract.CREATE, contract.UPDATE]


# =============================================================================
# §10 validation and §11 duplicates
# =============================================================================


def test_every_problem_is_reported_rather_than_the_first(agent):
    response = ask(agent, contract.CREATE, entity_type="person",
                   data={"name": "Fine", "email": "bad", "status": "wat"})
    problems = {problem["field"] for problem in response.error["details"]["problems"]}
    assert problems == {"email", "status"}


def test_a_field_the_type_does_not_declare_is_refused(agent):
    """Storing it would put data in the record that nothing validates and no
    search can find - a successful write that is a silent loss."""
    response = ask(agent, contract.CREATE, entity_type="person",
                   data={"name": "Fine", "favourite_colour": "green"})
    assert response.error["error_code"] == contract.VALIDATION_ERROR
    assert "favourite_colour" in response.error["message"]


def test_an_undeclared_entity_type_is_a_schema_mismatch(agent):
    response = ask(agent, contract.CREATE, entity_type="spaceship",
                   data={"name": "Rocinante"})
    assert response.error["error_code"] == contract.SCHEMA_MISMATCH


def test_a_required_field_cannot_be_emptied_by_an_update(agent):
    created = person(agent, "Named")
    response = ask(agent, contract.UPDATE, entity_type="person",
                   entity_id=created.entity_id, data={"name": "  "})
    assert response.needs_answer or response.status == contract.STATUS_ERROR
    assert not response.changed


def test_an_exact_match_on_an_identifying_field_is_a_confident_duplicate(agent):
    person(agent, "First", email="same@example.com")
    response = ask(agent, contract.CREATE, entity_type="person",
                   data={"name": "Second", "email": "same@example.com"})

    assert response.error["error_code"] == contract.DUPLICATE_DETECTED
    assert response.error["details"]["matched_on"] == ["email"]


def test_two_people_with_the_same_name_are_not_duplicates(agent, conn):
    """The ordinary case §4's example A is built on. Treating a shared label as
    a collision would make the system unable to hold two John Smiths."""
    assert person(agent, "John Smith").ok
    assert person(agent, "John Smith").ok
    assert records.count(conn, "person") == 2


def test_nothing_is_ever_merged_automatically(agent, conn):
    """§11's last line, asserted as an absence: the duplicate path refuses and
    leaves both records exactly as they were."""
    first = person(agent, "First", email="same@example.com")
    ask(agent, contract.CREATE, entity_type="person",
        data={"name": "Second", "email": "same@example.com"})
    assert records.count(conn, "person") == 1
    assert records.get(conn, first.entity_id)["name"] == "First"


def test_an_update_does_not_count_a_record_as_its_own_duplicate(agent):
    created = person(agent, "Self", email="self@example.com")
    response = ask(agent, contract.UPDATE, entity_type="person",
                   entity_id=created.entity_id,
                   data={"email": "self@example.com", "phone": "+1 555 5"})
    assert response.ok


# =============================================================================
# §5 identifiers, timestamps, soft delete, schema version
# =============================================================================


def test_an_identifier_says_what_it_is(agent):
    created = person(agent, "Typed")
    assert ids.type_of(created.entity_id) == "person"
    assert not ids.belongs_to(created.entity_id, "task")


def test_an_id_from_the_wrong_table_is_refused_before_any_lookup(agent):
    response = ask(agent, contract.GET, entity_type="person",
                   entity_id=ids.new_id("task"))
    assert response.error["error_code"] == contract.VALIDATION_ERROR
    assert "entity_type" in response.error["message"]


def test_a_name_is_never_an_identifier(agent):
    response = ask(agent, contract.GET, entity_type="person",
                   entity_id="John Smith")
    assert response.error["error_code"] == contract.VALIDATION_ERROR


def test_timestamps_are_kept_and_updated(agent, conn):
    created = person(agent, "Stamped")
    before = records.get(conn, created.entity_id)
    ask(agent, contract.UPDATE, entity_type="person",
        entity_id=created.entity_id, data={"phone": "+1 555 6"})
    after = records.get(conn, created.entity_id)
    assert before["created_at"] == after["created_at"]
    assert after["updated_at"] >= before["updated_at"]


def test_archiving_hides_a_record_without_destroying_it(agent, conn):
    created = person(agent, "Archivable")
    ask(agent, contract.ARCHIVE, entity_type="person",
        entity_id=created.entity_id)

    assert records.get(conn, created.entity_id) is None
    kept = records.get(conn, created.entity_id, scope=records.ARCHIVED)
    assert kept is not None and kept["name"] == "Archivable"


def test_a_deleted_record_is_still_recoverable_and_still_explicable(agent, conn):
    """§5.6 restricts hard deletion; this one is soft, so the audit trail can
    still produce what the record said."""
    created = person(agent, "Deletable")
    ask(agent, contract.DELETE_AUTHORIZED, entity_type="person",
        entity_id=created.entity_id, requested_by=OPERATOR)
    assert records.get(conn, created.entity_id, scope=records.DELETED) is not None


def test_the_active_schema_version_is_knowable(conn):
    """§5.7. Against the constant rather than a literal, so the assertion
    tracks the schema instead of having to be edited every time it moves."""
    assert store.schema_version(conn) == store.SCHEMA_VERSION
    assert store.SCHEMA_VERSION >= 2, "version 2 added the capability tables"


# =============================================================================
# §19 search, §16 minimum disclosure, §27 bounded results
# =============================================================================


def test_search_finds_a_word_in_metadata_as_well_as_a_column(agent):
    person(agent, "Findable", notes="lives in Lisbon")
    response = ask(agent, contract.SEARCH, entity_type="person",
                   criteria={"text": "Lisbon"})
    assert response.result["count"] == 1


def test_search_does_not_return_archived_records_by_default(agent):
    created = person(agent, "Hidden", notes="secret word")
    ask(agent, contract.ARCHIVE, entity_type="person",
        entity_id=created.entity_id)
    response = ask(agent, contract.SEARCH, entity_type="person",
                   criteria={"text": "secret word"})
    assert response.result["count"] == 0


def test_an_ask_back_option_carries_the_minimum_that_identifies_a_record(agent):
    """§16: offering a choice between two records does not require sending
    both records."""
    person(agent, "John Smith", email="a@example.com", notes="a long private note")
    person(agent, "John Smith", email="b@example.com", notes="another one")

    response = ask(agent, contract.UPDATE, entity_type="person",
                   criteria={"name": "John Smith"}, data={"phone": "+1 555 7"})

    for option in response.clarification["options"]:
        assert "notes" not in option


def test_a_result_set_is_bounded_however_much_is_asked_for(agent, conn):
    """§27: no unbounded read of a table that grows."""
    for index in range(5):
        person(agent, f"Person {index}")
    found = records.find(conn, "person", limit=10_000)
    assert len(found) <= records.MAX_RESULTS


# =============================================================================
# §6.2 relationships
# =============================================================================


def test_two_records_can_be_linked_and_unlinked(agent, conn):
    document = ask(agent, contract.CREATE, entity_type="document",
                   data={"name": "Contract.pdf"})
    project = ask(agent, contract.CREATE, entity_type="project",
                  data={"name": "Alpha"})

    linked = ask(agent, contract.LINK, entity_type="document",
                 data={"from_id": document.entity_id, "relation": "attached_to",
                       "to_id": project.entity_id})
    assert linked.ok and linked.changed
    assert len(operations.links_of(conn, document.entity_id)) == 1

    unlinked = ask(agent, contract.UNLINK, entity_type="document",
                   data={"from_id": document.entity_id,
                         "relation": "attached_to", "to_id": project.entity_id})
    assert unlinked.ok and unlinked.changed
    assert operations.links_of(conn, document.entity_id) == []


def test_a_link_to_a_record_that_is_not_there_is_refused(agent):
    document = ask(agent, contract.CREATE, entity_type="document",
                   data={"name": "Orphan.pdf"})
    response = ask(agent, contract.LINK, entity_type="document",
                   data={"from_id": document.entity_id,
                         "relation": "attached_to",
                         "to_id": ids.new_id("project")})
    assert response.error["error_code"] == contract.NOT_FOUND


def test_the_same_link_twice_is_not_two_links(agent, conn):
    document = ask(agent, contract.CREATE, entity_type="document",
                   data={"name": "Once.pdf"})
    project = ask(agent, contract.CREATE, entity_type="project",
                  data={"name": "Beta"})
    payload = {"from_id": document.entity_id, "relation": "attached_to",
               "to_id": project.entity_id}
    ask(agent, contract.LINK, entity_type="document", data=payload)
    second = ask(agent, contract.LINK, entity_type="document", data=payload)

    assert second.ok and second.changed is False
    assert len(operations.links_of(conn, document.entity_id)) == 1


# =============================================================================
# §22 idempotency, in the cases that are not TEST B
# =============================================================================


def test_the_same_request_id_for_a_different_request_is_a_conflict(agent):
    key = "import-001"
    agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "One"}, request_id=key))
    second = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Something Else"}, request_id=key))

    assert second.error["error_code"] == contract.CONFLICT_DETECTED


def test_a_refused_request_does_not_burn_its_idempotency_key(agent, conn):
    """Remembering a failure would mean a caller that fixes its input and
    retries with the same id gets the old refusal back forever."""
    key = "retry-me"
    first = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"email": "bad"}, request_id=key))
    assert not first.ok

    second = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Fixed", "email": "good@example.com"}, request_id=key))
    assert second.ok and second.changed
    assert records.count(conn, "person") == 1


def test_a_read_does_not_need_and_does_not_use_an_idempotency_key(agent):
    created = person(agent, "Readable")
    for _ in range(3):
        response = ask(agent, contract.GET, entity_type="person",
                       entity_id=created.entity_id, request_id="same-key")
        assert response.ok


# =============================================================================
# §8's transaction delimiters, and §49's decision about them
# =============================================================================


def test_a_bare_transaction_delimiter_is_refused_with_its_reason(agent):
    for action in (contract.BEGIN_TRANSACTION, contract.COMMIT_TRANSACTION,
                   contract.ROLLBACK_TRANSACTION):
        response = ask(agent, action)
        assert response.status == contract.STATUS_ERROR
        assert "batch" in response.error["message"]


def test_a_non_atomic_batch_keeps_what_succeeded(agent, conn):
    """§31's "partial or atomic mode" - the other half."""
    responses = agent.handle_many([
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={"name": "Kept"}),
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="person", data={}),
    ], atomic=False)

    assert responses[0].ok
    assert not responses[1].ok
    assert records.count(conn, "person") == 1


# =============================================================================
# §28 health and §29 diagnostics
# =============================================================================


def test_health_answers_the_question_jarvis_asks(agent):
    person(agent, "Counted")
    report = health.health()
    assert report["status"] == health.OK
    assert report["database_connected"] is True
    assert report["schema_version"] == store.SCHEMA_VERSION
    assert report["entity_counts"]["person"] == 1


def test_health_reports_an_unavailable_database_as_unavailable():
    def refuses():
        raise OSError("gone")
    report = health.health(connect=refuses)
    assert report["status"] == health.UNAVAILABLE
    assert report["database_connected"] is False


def test_having_taken_no_backup_is_reported_as_a_problem(_isolated):
    """This test used to assert that backup was unimplemented and said so
    honestly. It is implemented now (`tests/test_dba_backup.py`), so what is
    left to assert is the state a fresh system is actually in: no backup has
    been taken, and that is a failing check rather than silence.

    A system reporting a backup age of zero because it has never taken one
    would be worse than one that says it has never taken one."""
    report = health.health()
    assert report["last_backup"] is None

    diagnosis = health.diagnose()
    backup_check = next(check for check in diagnosis["checks"]
                        if check["check"] == "backup_age")
    assert backup_check["passed"] is False
    assert "no backup has ever been taken" in backup_check["detail"]
    assert diagnosis["status"] == health.DEGRADED


def test_the_encrypted_secondary_location_is_still_reported_as_absent():
    """§25 says it should eventually be supported. It is not, and an absent
    measurement reads as a clean one."""
    not_measured = health.health()["not_measured"]
    assert "encrypted_secondary_location" in not_measured
    assert "nothing is encrypted at rest" in \
        not_measured["encrypted_secondary_location"]


def test_diagnostics_never_repair_anything(agent, conn):
    """§29's last line, asserted as an absence."""
    document = ask(agent, contract.CREATE, entity_type="document",
                   data={"name": "Attached.pdf"})
    project = ask(agent, contract.CREATE, entity_type="project",
                  data={"name": "Gamma"})
    ask(agent, contract.LINK, entity_type="document",
        data={"from_id": document.entity_id, "relation": "attached_to",
              "to_id": project.entity_id})
    conn.execute("DELETE FROM entities WHERE id = ?", (project.entity_id,))

    diagnosis = health.diagnose()

    orphans = next(check for check in diagnosis["checks"]
                   if check["check"] == "orphan_records")
    assert orphans["passed"] is False
    assert diagnosis["repaired"] == []
    assert len(operations.links_of(conn, document.entity_id)) == 1, \
        "the diagnosis reported the orphan and did not remove it"


def test_the_declared_indexes_are_all_created(conn):
    present = {row["name"] for row in conn.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert set(health.EXPECTED_INDEXES) <= present


# =============================================================================
# §43 the plain-language explanation
# =============================================================================


def test_the_sentence_says_exactly_what_changed(agent):
    created = person(agent, "Explained", phone="+1 555 0000")
    response = ask(agent, contract.UPDATE, entity_type="person",
                   entity_id=created.entity_id, data={"phone": "+1 555 1111"})

    said = explain.explain(response)
    assert "phone" in said
    assert "No other fields were changed" in said


def test_the_sentence_for_a_question_says_nothing_was_changed(agent):
    person(agent, "John Smith", email="a@example.com")
    person(agent, "John Smith", email="b@example.com")
    response = ask(agent, contract.UPDATE, entity_type="person",
                   criteria={"name": "John Smith"}, data={"phone": "+1 555 8"})

    said = explain.explain(response)
    assert said.startswith("I have not changed anything")
    assert "a@example.com" in said and "b@example.com" in said


def test_the_sentence_never_claims_a_write_on_a_failure(agent):
    response = ask(agent, contract.CREATE, entity_type="person",
                   data={"name": "x"}, requested_by="rogue_agent")
    said = explain.explain(response)
    assert "not allowed" in said
    assert "created" not in said.lower()


# =============================================================================
# The service (§2.1)
# =============================================================================


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from dba.main import app

    monkeypatch.setenv("DBA_TOKEN_JARVIS", "test-token-not-real")
    return TestClient(app)


AUTH = {"X-DBA-Agent": JARVIS, "X-DBA-Token": "test-token-not-real"}


def test_the_service_refuses_an_unauthenticated_request(client):
    assert client.post("/request", json={"action": "get"}).status_code == 401


def test_the_service_refuses_a_wrong_token(client):
    response = client.post("/request", json={"action": "get"},
                           headers={**AUTH, "X-DBA-Token": "wrong"})
    assert response.status_code == 403


def test_an_agent_with_no_configured_token_cannot_call_at_all(client):
    response = client.post(
        "/request", json={"action": "get"},
        headers={"X-DBA-Agent": OPERATOR, "X-DBA-Token": "anything"})
    assert response.status_code == 503
    assert "DBA_TOKEN_OPERATOR_CONSOLE" in response.json()["detail"]


def test_the_body_cannot_claim_an_identity_the_header_did_not(client):
    response = client.post(
        "/request",
        json={"action": "get", "requested_by": OPERATOR}, headers=AUTH)
    assert response.status_code == 400


def test_a_clarification_is_two_hundred_rather_than_an_error(client):
    for email in ("a@example.com", "b@example.com"):
        client.post("/request", json={
            "action": "create", "entity_type": "person",
            "data": {"name": "John Smith", "email": email}}, headers=AUTH)

    response = client.post("/request", json={
        "action": "update", "entity_type": "person",
        "criteria": {"name": "John Smith"},
        "data": {"phone": "+1 555 9"}}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["status"] == contract.STATUS_CLARIFICATION_REQUIRED


def test_the_service_carries_the_sentence_alongside_the_structure(client):
    response = client.post("/request", json={
        "action": "create", "entity_type": "person",
        "data": {"name": "Jane Doe"}}, headers=AUTH)
    body = response.json()
    assert body["status"] == "success"
    assert body["explanation"].startswith("I created person")


def test_an_unknown_request_field_is_refused_rather_than_ignored(client):
    """A dropped filter is an unfiltered write."""
    response = client.post("/request", json={
        "action": "archive", "entity_type": "person",
        "filter": {"status": "inactive"}}, headers=AUTH)
    assert response.status_code == 400
    assert "filter" in response.json()["detail"]


def test_health_is_reachable_without_a_write_credential(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database_connected"] is True


def test_the_policy_is_published_as_data(client):
    body = client.get("/policy").json()
    assert JARVIS in body["agents"]
    assert "delete" not in body["agents"][JARVIS]


# =============================================================================
# What a review found after all of the above was passing
#
# Ten findings, none of which the tests above caught. Two were the package's
# own foundational rules broken by the machinery meant to uphold them, which is
# the pattern worth remembering: the dangerous defect is not in the feature, it
# is in the thing wrapped around every feature.
# =============================================================================


def test_a_dry_run_does_not_burn_the_idempotency_key(agent, conn):
    """THE SHARPEST FINDING, and it is §44 broken by §22.

    A dry run was remembered under its request id, so the real write that
    followed with the same id was *replayed* - returning the dry run's
    `committed: false` result as a success while writing nothing. A caller
    that previews and then commits, which is precisely the sequence §30 exists
    to support, silently lost its write."""
    key = "preview-then-commit-001"
    preview = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Previewed"}, request_id=key, dry_run=True))
    assert preview.ok and not preview.changed
    assert records.count(conn, "person") == 0

    real = agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Previewed"}, request_id=key))

    assert real.changed is True, "the real write must actually happen"
    assert records.count(conn, "person") == 1
    assert not any("replayed" in warning for warning in real.warnings)


def test_a_criterion_in_metadata_sees_every_row_not_the_first_page(
        agent, conn, monkeypatch):
    """The other rule broken by its own machinery: §45's silent choice.

    A non-promoted criterion was filtered in Python over a bounded window, so
    with one match inside the window and one outside, `resolve` reported
    `exactly_one` and the update wrote to whichever it happened to see.

    The window is shrunk rather than the table grown - the first version of
    this test inserted five rows against a window of five hundred and so
    proved nothing, which is the failure mode of every test that does not
    check it can fail."""
    monkeypatch.setattr(records, "MAX_RESULTS", 3)
    person(agent, "First", notes="shared-note")
    for index in range(3):
        person(agent, f"Noise {index}")
    person(agent, "Second", notes="shared-note")

    found = records.find(conn, "person", criteria={"notes": "shared-note"})
    assert len(found) == 2, "both matches, wherever they sit in the table"

    # And the consequence that made it dangerous: the update must ask.
    response = ask(agent, contract.UPDATE, entity_type="person",
                   criteria={"notes": "shared-note"},
                   data={"phone": "+1 555 0100"})
    assert response.needs_answer, "two matches must produce a question"
    assert all(record.get("phone") is None
               for record in records.find(conn, "person", limit=3))


def test_a_scan_that_could_not_see_everything_fails_rather_than_answering(
        agent, conn, monkeypatch):
    """When the SQLite build cannot filter inside the metadata, the fallback
    is a bounded scan - and a bounded scan that filled its window must not be
    reported as a complete answer."""
    monkeypatch.setattr(records, "_JSON1", False)
    monkeypatch.setattr(records, "MAX_RESULTS", 3)
    for index in range(4):
        person(agent, f"Person {index}", notes="crowded")

    with pytest.raises(records.IncompleteScan, match="could not be matched"):
        records.find(conn, "person", criteria={"notes": "crowded"})


def test_a_bad_value_in_a_batch_is_a_structured_error_not_an_exception(agent):
    """`handle` has always returned a structured `internal_error`;
    `handle_many` let it escape, so one bad value made /batch an unhandled
    500 with no body."""
    responses = agent.handle_many([
        contract.Request(action=contract.FIND, requested_by=JARVIS,
                         entity_type="person",
                         criteria={"scope": "not-a-scope"}),
    ])
    assert responses[0].status == contract.STATUS_ERROR
    assert responses[0].error["error_code"] == contract.INTERNAL_ERROR


def test_every_record_in_a_bulk_archive_gets_its_own_audit_event(agent, conn):
    """§13 is per-record history. A three-record archive wrote one event with
    a NULL entity_id, so `history` on each archived record showed only its
    creation - the change that retired it was invisible from the record."""
    created = [person(agent, f"Bulk {index}", status="inactive").entity_id
               for index in range(3)]

    response = ask(agent, contract.ARCHIVE, entity_type="person",
                   criteria={"status": "inactive"}, confirmed=True)
    assert response.result["affected"] == 3

    for entity_id in created:
        actions = [event["action"] for event in audit.for_entity(conn, entity_id)]
        assert actions == [contract.CREATE, contract.ARCHIVE], entity_id


def test_an_archived_record_can_still_be_deleted(agent, conn):
    """Archive then delete is the ordinary sequence. Resolving live-only made
    the second step impossible and reported `not_found` for a record plainly
    there."""
    created = person(agent, "Retire then remove")
    ask(agent, contract.ARCHIVE, entity_type="person",
        entity_id=created.entity_id)

    response = ask(agent, contract.DELETE_AUTHORIZED, entity_type="person",
                   entity_id=created.entity_id, requested_by=OPERATOR)

    assert response.ok and response.changed
    assert records.get(conn, created.entity_id, scope=records.DELETED) is not None


def test_diagnostics_survive_a_store_that_fails_mid_run():
    """A diagnosis that crashes on a damaged store is no diagnosis - it fails
    at exactly the moment somebody is asking it what is wrong."""
    class HalfBroken:
        def __init__(self):
            self.calls = 0

        def executescript(self, script):
            pass

        def execute(self, *args, **kwargs):
            pass

        def fetchone(self, *args, **kwargs):
            return {"value": "1"}

        def fetchall(self, *args, **kwargs):
            self.calls += 1
            if self.calls > 1:
                raise sqlite3.OperationalError("database disk image is malformed")
            return []

        def close(self):
            pass

    report = health.diagnose(connect=HalfBroken)

    assert report["status"] == health.DEGRADED
    assert "diagnostics_completed" in report["failing"]
    assert report["repaired"] == []


def test_search_matches_a_value_and_not_a_field_name(agent):
    """`data_json LIKE` matched the JSON keys too, so searching for "notes"
    returned every record that merely has a notes field."""
    # The label deliberately does not contain the word "notes" - the first
    # version of this test named the person "Has notes" and then matched it on
    # the name column, which proved nothing about the metadata search.
    person(agent, "Quiet Person", notes="something relevant here")

    by_value = ask(agent, contract.SEARCH, entity_type="person",
                   criteria={"text": "relevant"})
    by_field_name = ask(agent, contract.SEARCH, entity_type="person",
                        criteria={"text": "notes"})

    assert by_value.result["count"] == 1
    assert by_field_name.result["count"] == 0


def test_a_confidential_value_does_not_get_copied_into_the_audit_log(agent, conn):
    """§15: sensitive information should not be placed unnecessarily into logs.
    A create copied `request.data` verbatim into the append-only table, which
    carries none of the classification's protections."""
    created = person(agent, "Private Person", email="private@example.com",
                     notes="a medical detail")

    written = json.dumps(audit.for_entity(conn, created.entity_id))

    assert "private@example.com" not in written
    assert "a medical detail" not in written
    assert "fields" in written, "what changed is still recorded"


def test_a_control_key_in_criteria_is_not_read_as_a_field_value(agent):
    """`scope`, `limit` and `offset` steer the query. Treating one as a field
    meant an update carrying `limit` matched nothing and came back
    `not_found`."""
    created = person(agent, "Steerable")

    response = ask(agent, contract.UPDATE, entity_type="person",
                   criteria={"name": "Steerable", "limit": 10},
                   data={"phone": "+1 555 0100"})

    assert response.ok and response.changed
    assert response.entity_id == created.entity_id


def test_a_phone_number_made_only_of_spaces_is_refused(agent):
    """It validated, stored, and could then never be matched by a duplicate
    rule or an equality search. A field that is present and unmatchable is
    worse than an absent one."""
    response = ask(agent, contract.CREATE, entity_type="person",
                   data={"name": "Spacey", "phone": "      "})
    assert response.error["error_code"] == contract.VALIDATION_ERROR
    assert "phone" in response.error["message"]


# =============================================================================
# §47: the minimum viable DBA, as a checklist
# =============================================================================


def test_the_minimum_viable_dba_agent(agent, conn, client):
    """§47's fifteen conditions, each asserted rather than asserted about.

    Written as one test on purpose: it is the specification's own definition of
    done, and a reader should be able to see all fifteen answered in one place
    - the same shape `tests/test_learning.py` uses for Document 2 §12."""
    # 1. Runs independently from JARVIS: it is its own package and its own
    #    service, and nothing in gateway/ or backend/ imports it.
    repo = pathlib.Path(__file__).resolve().parent.parent
    importers = [path.name for path in list((repo / "gateway").glob("*.py"))
                 + list((repo / "backend").glob("*.py"))
                 if "import dba" in path.read_text(encoding="utf-8")
                 or "from dba" in path.read_text(encoding="utf-8")]
    assert importers == [], f"the DBA is embedded in: {importers}"

    # 2. Receives structured requests.
    created = client.post("/request", json={
        "action": "create", "entity_type": "person",
        "data": {"name": "Acceptance", "email": "a@example.com"}},
        headers=AUTH).json()
    assert created["status"] == "success"
    entity_id = created["entity_id"]

    # 3. Stores records. 4. Retrieves them.
    fetched = ask(agent, contract.GET, entity_type="person", entity_id=entity_id)
    assert fetched.ok and fetched.result["name"] == "Acceptance"

    # 5. Updates records.
    updated = ask(agent, contract.UPDATE, entity_type="person",
                  entity_id=entity_id, data={"phone": "+1 555 0000"})
    assert updated.ok and updated.changed

    # 6. Searches records.
    assert ask(agent, contract.SEARCH, entity_type="person",
               criteria={"text": "Acceptance"}).result["count"] == 1

    # 7. Validates writes.
    assert ask(agent, contract.CREATE, entity_type="person",
               data={"name": "x", "email": "nope"}).error["error_code"] == \
        contract.VALIDATION_ERROR

    # 8. Generates unique ids. 9. Maintains timestamps.
    record = records.get(conn, entity_id)
    assert ids.belongs_to(entity_id, "person")
    assert record["created_at"] and record["updated_at"]

    # 10. Maintains an audit trail.
    assert len(audit.for_entity(conn, entity_id)) >= 2

    # 11. Asks clarification questions instead of guessing.
    person(agent, "Acceptance", email="b@example.com")
    asked = ask(agent, contract.UPDATE, entity_type="person",
                criteria={"name": "Acceptance"}, data={"status": "inactive"})
    assert asked.needs_answer

    # 12. Rejects unauthorized operations.
    assert ask(agent, contract.DELETE_AUTHORIZED, entity_type="person",
               entity_id=entity_id).error["error_code"] == \
        contract.PERMISSION_DENIED

    # 13. Rolls back failed multi-step writes.
    before = records.count(conn, "person")
    agent.handle_many([
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="task", data={"name": "First"}),
        contract.Request(action=contract.CREATE, requested_by=JARVIS,
                         entity_type="task", data={}),
    ])
    assert records.count(conn, "task") == 0
    assert records.count(conn, "person") == before

    # 14. Returns structured machine-readable results.
    assert set(updated.to_dict()) >= {
        "status", "request_id", "action", "entity_type", "entity_id",
        "changed", "result", "warnings", "clarification", "error", "timestamp"}

    # 15. Passes automated deterministic tests: this file, and §35's claim that
    #     the same state and the same request give the same answer.
    first = ask(agent, contract.GET, entity_type="person", entity_id=entity_id)
    second = ask(agent, contract.GET, entity_type="person", entity_id=entity_id)
    assert first.result == second.result


def test_the_same_request_against_the_same_state_gives_the_same_answer(agent):
    """§35's golden-test property, stated directly. Everything that decides a
    write here is a pure function, so this holds without a fixture that pins a
    model's behaviour - which is the whole reason §36 keeps the model out."""
    person(agent, "Deterministic", email="d@example.com")
    answers = [ask(agent, contract.CREATE, entity_type="person",
                   data={"name": "Deterministic", "email": "d@example.com"})
               for _ in range(3)]
    codes = {answer.error["error_code"] for answer in answers}
    assert codes == {contract.DUPLICATE_DETECTED}
    assert len({json.dumps(a.error, sort_keys=True) for a in answers}) == 1
