"""Jarvis survives being stopped: identity, durable state, checkpoints, ledger.

Phases 2 and 3 of the Persistence specification's §37.

**Every test here runs against the real DBA service.** `DBAClient` takes a
transport, and the fixture wires it to a `TestClient` over `dba.main:app` - the
same routes, the same authentication, the same policy, the same validator. A
suite that posted JSON at a fake and asserted the shape it expected would keep
passing the day the DBA changed its contract, which is the single failure this
whole boundary exists to catch early.
"""

import json
import re

import pytest
from fastapi.testclient import TestClient

from dba import agent as agent_module, entities, main as dba_main, registry, store
from gateway import (checkpoint as checkpoint_module, dbaclient, failures,
                     identity, ledger, persistence, rehydrate)

TOKEN = "test-token-for-jarvis"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "a" * 40)
    agent_module._AGENT = None
    registry.reset_sync()
    yield
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def service():
    with TestClient(dba_main.app) as client:
        yield client


@pytest.fixture()
def client(service):
    """A real `DBAClient` speaking to the real DBA over a test transport."""

    def transport(method, path, payload):
        response = service.request(
            method, path, json=payload if method != "GET" else None,
            headers={"X-DBA-Agent": "JARVIS", "X-DBA-Token": TOKEN})
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    return dbaclient.DBAClient(transport=transport)


# =============================================================================
# The client speaks the DBA's actual contract
# =============================================================================


def test_the_client_round_trips_a_record_through_the_real_service(client):
    entity_id = client.create("agent_state",
                              {"name": "n", "agent": "jarvis", "kind": "identity",
                               "value": "\"v\"", "status": "current",
                               "revision": 1})
    assert client.get(entity_id)["name"] == "n"
    assert client.count("agent_state", {"agent": "jarvis"}) == 1
    assert [row["name"] for row in client.find("agent_state", {"agent": "jarvis"})] == ["n"]


def test_a_refusal_is_a_refusal_and_not_an_empty_result(client):
    """A `find` that returns [] and a refusal that returns [] are the same
    value and opposite facts. The client must not conflate them.

    Uses a permission refusal rather than a missing field: a missing field
    makes the DBA *ask a question* (§45), which is a third thing again and is
    covered below."""
    with pytest.raises(dbaclient.Refused) as raised:
        client.request("delete_authorized", entity_type="agent_state",
                       entity_id="agent_state-0123456789abcdef", confirmed=True)
    assert raised.value.code == "permission_denied"


def test_a_question_from_the_dba_is_carried_up_not_answered_for_krish(client):
    """§45. A missing required field is not a refusal - the DBA asks. Jarvis
    must not invent the answer, so it arrives as its own exception type."""
    with pytest.raises(dbaclient.NeedsAnswer) as raised:
        client.create("agent_state", {"agent": "jarvis", "kind": "identity"})
    assert "name" in str(raised.value)
    assert raised.value.clarification


def test_an_unreachable_dba_raises_unavailable_rather_than_returning_nothing():
    def dead_transport(method, path, payload):
        raise dbaclient.Unavailable("connection refused")

    made = dbaclient.DBAClient(transport=dead_transport)
    with pytest.raises(dbaclient.Unavailable):
        made.find("agent_state", {})


def test_the_service_answering_503_is_unavailable_not_refused(client, service):
    made = dbaclient.DBAClient(
        transport=lambda method, path, payload: (503, {"detail": "down"}))
    with pytest.raises(dbaclient.Unavailable):
        made.count("agent_state", {})


def test_missing_token_is_reported_as_unavailable_not_as_silence(monkeypatch):
    monkeypatch.delenv(dbaclient.TOKEN_ENV, raising=False)
    assert not dbaclient.is_configured()
    with pytest.raises(dbaclient.Unavailable):
        dbaclient.DBAClient().find("agent_state", {})


# =============================================================================
# §4.1 durable state: revised, never overwritten
# =============================================================================


def test_a_second_write_adds_a_revision_and_keeps_the_first(client):
    persistence.put(client, persistence.PREFERENCE, "tea", "green")
    persistence.put(client, persistence.PREFERENCE, "tea", "black")

    assert persistence.get(client, persistence.PREFERENCE, "tea") == "black"
    revisions = persistence.history(client, persistence.PREFERENCE, "tea")
    assert [row["revision"] for row in revisions] == [1, 2]
    assert [persistence.decode(row) for row in revisions] == ["green", "black"]
    # §22 has something to roll back to only because the first value is still there.
    assert revisions[0]["status"] == persistence.SUPERSEDED


def test_state_as_of_an_earlier_moment_ignores_later_revisions(client):
    persistence.put(client, persistence.GOAL, "ship", "phase 2")
    first = persistence.history(client, persistence.GOAL, "ship")[0]["effective_from"]
    persistence.put(client, persistence.GOAL, "ship", "phase 3")

    then = persistence.as_of(client, first)
    assert [persistence.decode(row) for row in then] == ["phase 2"]
    now = persistence.current(client)
    assert [persistence.decode(row) for row in now] == ["phase 3"]


def test_two_live_revisions_resolve_the_same_way_for_every_reader(client):
    """A crash between the write and the retirement leaves two `current` rows.
    Built directly, because that is the state a crash leaves behind."""
    for revision in (1, 2):
        client.create("agent_state",
                      {"name": "split", "agent": "jarvis", "kind": "goal",
                       "value": json.dumps(f"r{revision}"), "status": "current",
                       "revision": revision})

    assert persistence.get(client, persistence.GOAL, "split") == "r2"
    retired = persistence.reconcile(client)
    assert [row["revision"] for row in retired] == [1]
    assert persistence.get(client, persistence.GOAL, "split") == "r2"


def test_an_undeclared_kind_is_refused(client):
    with pytest.raises(persistence.UnknownKind):
        persistence.put(client, "vibes", "x", 1)


def test_the_persistence_tier_is_declared_not_guessed():
    """§9 names the immediate list. If this drifts, an approval could start
    waiting for a periodic flush."""
    for kind in (persistence.CORRECTION, persistence.COMMITMENT,
                 persistence.IDENTITY, persistence.POLICY):
        assert persistence.tier(kind) == persistence.IMMEDIATE
    assert persistence.tier(persistence.INTERMEDIATE_RESULT) == persistence.PERIODIC
    assert set(persistence.TIER) == set(persistence.KINDS)


# =============================================================================
# §4.3 the life ledger
# =============================================================================


def test_events_are_numbered_from_one_and_chain_to_their_predecessor(client):
    first = ledger.append(client, event_type=ledger.USER_REQUEST, summary="hello")
    second = ledger.append(client, event_type=ledger.DECISION, summary="chose A")

    assert first["sequence_number"] == 1
    assert second["sequence_number"] == 2
    assert first["previous_event_hash"] == ledger.GENESIS_HASH
    assert second["previous_event_hash"] == first["integrity_hash"]
    assert ledger.replay(client)["intact"] is True


def test_replay_names_the_event_whose_content_was_changed(client):
    ledger.append(client, event_type=ledger.USER_REQUEST, summary="one")
    victim = ledger.append(client, event_type=ledger.OBSERVATION, summary="two")
    ledger.append(client, event_type=ledger.LESSON, summary="three")

    # Edit the stored event behind the ledger's back, which is exactly what the
    # chain exists to detect and what the DBA's own audit trail cannot see.
    client.update(victim["id"], {"observation": "quietly rewritten"})

    verdict = ledger.replay(client)
    assert verdict["intact"] is False
    assert verdict["breaks"][0]["sequence_number"] == 2
    assert verdict["breaks"][0]["problem"] == "content_changed"
    assert verdict["verified_through"] == 1


def test_replay_notices_a_missing_event(client):
    ledger.append(client, event_type=ledger.USER_REQUEST, summary="one")
    second = ledger.append(client, event_type=ledger.OBSERVATION, summary="two")
    ledger.append(client, event_type=ledger.LESSON, summary="three")

    # Archiving takes it out of the live scope the ledger reads.
    client.archive(second["id"])

    verdict = ledger.replay(client)
    assert verdict["intact"] is False
    assert verdict["breaks"][0]["problem"] in ("missing", "previous_hash_mismatch")


def test_a_losing_race_for_a_sequence_number_retries_rather_than_forking(client):
    """Two appends that both believe they are event 2. The DBA refuses the
    second on the identifying field, and `append` takes the next number."""
    ledger.append(client, event_type=ledger.USER_REQUEST, summary="one")

    real_tip = ledger.tip
    calls = {"n": 0}

    def stale_tip(c, agent=identity.AGENT_ID):
        calls["n"] += 1
        if calls["n"] == 1:
            # Pretend nothing has been written: forces a collision on key 1.
            return None
        return real_tip(c, agent)

    ledger.tip = stale_tip
    try:
        written = ledger.append(client, event_type=ledger.DECISION, summary="two")
    finally:
        ledger.tip = real_tip

    assert written["sequence_number"] == 2
    assert ledger.replay(client)["intact"] is True


def test_an_undeclared_event_type_is_refused(client):
    with pytest.raises(ValueError):
        ledger.append(client, event_type="vibes", summary="x")


def test_a_reinterpretation_adds_a_layer_and_leaves_the_original(client):
    original = ledger.append(
        client, event_type=ledger.LESSON, summary="local models are always slower",
        verification_state=ledger.INFERRED)

    later = ledger.reinterpret(
        client, original_event_id=original["id"],
        lesson="local models are slower only above 8k context",
        why_changed="measured it on short prompts and they won")

    stored_original = client.get(original["id"])
    assert stored_original["name"] == "local models are always slower"
    assert stored_original.get("supersedes_event_id") is None
    assert later["supersedes_event_id"] == original["id"]
    assert ledger.replay(client)["intact"] is True


def test_reinterpreting_an_event_that_does_not_exist_is_refused(client):
    with pytest.raises(ValueError):
        ledger.reinterpret(client, original_event_id="ledger_event_nope",
                           lesson="x", why_changed="y")


def test_the_clients_id_parser_agrees_with_the_dbas_own(client):
    """Two copies of one rule, held together by a test rather than by hope."""
    from dba import ids

    entity_id = client.create("agent_state",
                              {"name": "n", "agent": "jarvis", "kind": "identity",
                               "value": "\"v\""})
    assert dbaclient.type_of(entity_id) == ids.type_of(entity_id) == "agent_state"
    with pytest.raises(ValueError):
        dbaclient.type_of("not-an-id")


def test_this_module_contains_no_update_or_delete_of_a_ledger_event():
    """Append-only enforced as an absence, over the parsed code.

    The first version of this grepped the file and passed on the *docstring*,
    which explains that there is no update or delete in it. A test that can be
    satisfied by prose is not guarding anything."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "gateway" / "ledger.py").read_text(encoding="utf-8")
    mutating = {"update", "archive", "delete", "delete_authorized"}
    called = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    assert called & mutating == set(), sorted(called & mutating)

    # And the probe: the same check over a module that *does* mutate must fail,
    # or the assertion above is only ever true because nothing calls anything.
    other = (pathlib.Path(__file__).resolve().parent.parent
             / "gateway" / "persistence.py").read_text(encoding="utf-8")
    other_called = {node.func.attr for node in ast.walk(ast.parse(other))
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)}
    assert other_called & mutating


def test_a_ledger_write_that_fails_is_raised_not_swallowed(client):
    def refusing(method, path, payload):
        return 503, {"detail": "store is down"}

    dead = dbaclient.DBAClient(transport=refusing)
    with pytest.raises(ledger.LedgerWriteFailed):
        ledger.append(dead, event_type=ledger.USER_CORRECTION, summary="important")


# =============================================================================
# §8 checkpoints
# =============================================================================


def test_a_checkpoint_validates_before_it_becomes_authoritative(client):
    persistence.put(client, persistence.GOAL, "ship", "phase 2")
    ledger.append(client, event_type=ledger.DECISION, summary="decided")

    record = checkpoint_module.take(client, reason=checkpoint_module.MILESTONE)

    assert record["name"] == "checkpoint_000001"
    assert record["status"] == checkpoint_module.VALID
    assert record["ledger_tip_sequence"] == 1
    assert checkpoint_module.validate(client, client.get(record["id"]))["valid"]


def test_a_checkpoint_whose_state_was_altered_behind_it_is_rejected(client):
    persistence.put(client, persistence.GOAL, "ship", "phase 2")
    record = checkpoint_module.take(client)

    # Rewrite the value of the revision the checkpoint hashed.
    row = persistence.history(client, persistence.GOAL, "ship")[0]
    client.update(row["id"], {"value": json.dumps("tampered")})

    verdict = checkpoint_module.validate(client, client.get(record["id"]))
    assert verdict["valid"] is False
    assert "hashes to" in verdict["why"]


def test_the_fallback_skips_the_damaged_checkpoint_and_says_which(client):
    """TEST C. The newest checkpoint is damaged; the older one is intact."""
    persistence.put(client, persistence.GOAL, "ship", "phase 2")
    good = checkpoint_module.take(client)
    persistence.put(client, persistence.GOAL, "ship", "phase 3")
    bad = checkpoint_module.take(client)

    client.update(bad["id"], {"contents_hash": "0" * 64})

    usable, skipped = checkpoint_module.newest_usable(client)
    assert usable["name"] == good["name"]
    assert [record["name"] for record in skipped] == [bad["name"]]
    assert client.get(bad["id"])["status"] == checkpoint_module.INVALID
    assert client.get(bad["id"])["invalid_reason"]


def test_a_checkpoint_left_mid_write_is_rejected_not_trusted(client):
    persistence.put(client, persistence.GOAL, "ship", "phase 2")
    good = checkpoint_module.take(client)

    # What a process that died between `create` and `validate` leaves behind.
    client.create("checkpoint",
                  {"name": "checkpoint_000002",
                   "external_id": checkpoint_module.sequence_key("jarvis", 2),
                   "status": checkpoint_module.WRITING, "agent": "jarvis",
                   "sequence_number": 2, "taken_at": "2026-09-22T00:00:00+00:00"})

    usable, skipped = checkpoint_module.newest_usable(client)
    assert usable["name"] == good["name"]
    assert skipped[0]["name"] == "checkpoint_000002"
    assert "did not finish" in skipped[0]["invalid_reason"]


def test_restoring_a_checkpoint_names_the_interval_that_came_after(client):
    """TEST B's "identifies any potentially lost interval"."""
    persistence.put(client, persistence.TASK, "invoice", {"step": 1})
    record = checkpoint_module.take(client)
    ledger.append(client, event_type=ledger.USER_REQUEST, summary="after the checkpoint")
    ledger.append(client, event_type=ledger.ACTION_FAILED, summary="crashed here")

    view = checkpoint_module.restore(client, client.get(record["id"]))
    assert view["interval_at_risk"]["events"] == 2
    assert "crashed here" in view["interval_at_risk"]["summaries"]


def test_restore_reads_the_revision_that_was_current_then(client):
    persistence.put(client, persistence.TASK, "invoice", {"step": 1})
    record = checkpoint_module.take(client)
    persistence.put(client, persistence.TASK, "invoice", {"step": 9})

    view = checkpoint_module.restore(client, client.get(record["id"]))
    assert [persistence.decode(row) for row in view["items"]] == [{"step": 1}]
    # and the present is untouched: §6's later layer, not a rewrite
    assert persistence.get(client, persistence.TASK, "invoice") == {"step": 9}


def test_restoring_an_invalid_checkpoint_raises_rather_than_returning_a_guess(client):
    persistence.put(client, persistence.GOAL, "ship", "phase 2")
    record = checkpoint_module.take(client)
    client.update(record["id"], {"contents_hash": "0" * 64})

    with pytest.raises(checkpoint_module.CheckpointInvalid):
        checkpoint_module.restore(client, client.get(record["id"]))


# =============================================================================
# §3 bootstrap, §10 no false memory
# =============================================================================


def test_a_clean_boot_restores_everything_and_says_nothing(client):
    persistence.put(client, persistence.IDENTITY, "name", "Jarvis")
    persistence.put(client, persistence.COMMITMENT, "vacation-report",
                    "send Krish the weekly summary")
    checkpoint_module.take(client)

    restoration = rehydrate.bootstrap(client)

    assert restoration.status == rehydrate.RESTORED_OK
    assert restoration.complete
    assert restoration.sentences() == []
    assert restoration.assert_fact(persistence.IDENTITY, "name") == "Jarvis"


def test_bootstrap_without_a_token_reports_it_rather_than_pretending(monkeypatch):
    monkeypatch.delenv(dbaclient.TOKEN_ENV, raising=False)
    restoration = rehydrate.bootstrap()

    assert restoration.status == failures.RESTORE_FAILED
    assert failures.DBA_UNAVAILABLE in restoration.failure_states
    assert restoration.must_tell_user()
    assert restoration.items == []


def test_asserting_something_that_was_not_restored_raises(client):
    persistence.put(client, persistence.IDENTITY, "name", "Jarvis")
    restoration = rehydrate.bootstrap(client)

    with pytest.raises(rehydrate.NotRemembered):
        restoration.assert_fact(persistence.COMMITMENT, "a promise never made")


def test_a_time_sensitive_item_comes_back_flagged_for_re_verification(client):
    persistence.put(client, persistence.KNOWLEDGE, "krish-address",
                    {"value": "12 Elm St", rehydrate.TIME_SENSITIVE_FLAG: True})

    restoration = rehydrate.bootstrap(client)

    assert "knowledge/krish-address" in restoration.needs_reverification
    assert any("re-check" in line for line in restoration.sentences())


def test_a_broken_ledger_makes_the_restore_partial_and_visible(client):
    ledger.append(client, event_type=ledger.USER_REQUEST, summary="one")
    victim = ledger.append(client, event_type=ledger.LESSON, summary="two")
    client.update(victim["id"], {"observation": "rewritten"})

    restoration = rehydrate.bootstrap(client)

    assert restoration.status == failures.PARTIAL_RESTORE
    assert failures.PARTIAL_RESTORE in restoration.failure_states
    assert restoration.ledger_verdict["intact"] is False
    assert restoration.must_tell_user()
    assert any("life ledger" in entry["what"] for entry in restoration.unavailable)


def test_bootstrap_records_itself_in_the_ledger(client):
    persistence.put(client, persistence.IDENTITY, "name", "Jarvis")
    rehydrate.bootstrap(client)

    tip = ledger.tip(client)
    assert tip["event_type"] == ledger.RESTORE_REPORT
    assert "restored 1 state item" in tip["name"]


def test_bootstrap_reports_a_rejected_checkpoint(client):
    persistence.put(client, persistence.GOAL, "ship", "phase 2")
    good = checkpoint_module.take(client)
    persistence.put(client, persistence.GOAL, "ship", "phase 3")
    bad = checkpoint_module.take(client)
    client.update(bad["id"], {"contents_hash": "0" * 64})

    restoration = rehydrate.bootstrap(client)

    assert failures.CHECKPOINT_INVALID in restoration.failure_states
    assert restoration.checkpoint["name"] == good["name"]
    assert any("skipped" in line or "fall back" in line
               for line in restoration.sentences())


# =============================================================================
# Identity and §34
# =============================================================================


def test_identity_is_a_constant_and_not_derived_from_the_machine():
    """§38 q12. An identity that changes when the machine does cannot satisfy
    §36's "fresh model, fresh machine, same Jarvis"."""
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "gateway" / "identity.py").read_text(encoding="utf-8")
    assert re.search(r'^AGENT_ID = "jarvis"$', source, re.MULTILINE)
    for derived in ("gethostname", "uuid", "getpass", "platform.node"):
        assert derived not in source


def test_an_undeterminable_code_version_is_none_not_a_plausible_string(monkeypatch, tmp_path):
    monkeypatch.delenv(identity.VERSION_ENV, raising=False)
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    assert identity.code_version() is None


def test_every_failure_state_in_the_specification_is_declared():
    """§34's list, verbatim. A state the system cannot name is one it cannot
    report, which is what §34 exists to prevent."""
    required = {
        "RESTORE_FAILED", "PARTIAL_RESTORE", "CHECKPOINT_INVALID",
        "DBA_UNAVAILABLE", "LEDGER_WRITE_FAILED", "GAP_UNCONFIRMED",
        "APPROVAL_REQUIRED", "APPROVAL_DENIED", "CHANGE_TEST_FAILED",
        "BUILD_FAILED", "RELAUNCH_FAILED", "POST_VALIDATION_FAILED",
        "ROLLBACK_REQUIRED", "ROLLBACK_COMPLETED",
    }
    assert required <= set(failures.STATES)
    for name in required:
        state = failures.get(name)
        assert state.means and state.next_action


def test_an_undeclared_failure_state_is_refused():
    with pytest.raises(KeyError):
        failures.get("EVERYTHING_IS_FINE")


# =============================================================================
# The boundary
# =============================================================================


def test_the_entity_types_this_needs_are_built_in_not_waiting_to_be_published():
    """§12's reason, applied: state that needs a capability published before it
    works is state that is missing on the first restart."""
    for name in ("ledger_event", "checkpoint", "agent_state", "knowledge_item",
                 "skill_state", "commitment", "capability_gap",
                 "change_proposal", "approval_decision"):
        assert entities.is_built_in(name), name


def test_jarvis_cannot_administer_the_database(client):
    """§16, already structural in the DBA's policy. Asserted here because this
    is the milestone that would have been tempted to widen it."""
    from dba import permissions

    assert "administer" not in permissions.permissions_of("JARVIS")
    assert "delete" not in permissions.permissions_of("JARVIS")
