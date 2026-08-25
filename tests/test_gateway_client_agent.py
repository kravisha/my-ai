"""The client's personal agent, and the memory that is finally theirs
(gateway/client_agent.py + gateway/store.py; addendum 43 §16, addendum 41 §24;
TQ-39, SPEC_RECONCILIATION §93).

The first section is about a breach, not a feature.

Until TQ-39 the Gateway had **one conversation for the whole database** -
`current_conversation_id` was "newest wins" with no owner. That was correct
while there was exactly one credential, and became a leak the moment TQ-34 added
two more: a client connecting to the socket received the operator's entire
transcript in the opening frame. It was reproduced against a running Gateway
before it was fixed, which is why it is stated here as fact rather than as risk.

Everything after that is addendum 43 §16's actual request: a client should feel
they are speaking with a familiar representative. Familiar is the requirement,
and the tests are mostly about not claiming familiarity that has not been
earned.
"""

import json

import pytest

from gateway import client_agent, roles, store


# --- the leak, closed ---------------------------------------------------------------


def test_two_subjects_do_not_share_a_conversation(gateway_conn):
    """The breach, as one assertion.

    A client's socket opened onto whatever conversation was newest in the
    database - which, on any Gateway an operator had used, was the operator's."""
    operator_conversation = store.current_conversation_id(gateway_conn, "boss")
    store.append_message(gateway_conn, operator_conversation, "user",
                         "the Q4 position and the key rotation plan")

    client_conversation = store.current_conversation_id(gateway_conn, "customer")

    assert client_conversation != operator_conversation
    assert store.history(gateway_conn, client_conversation) == []


def test_two_clients_sharing_a_role_do_not_share_a_memory(gateway_conn):
    """Owner is the *subject*, not the role. §16's relationship continuity is
    with a person, and a Gateway that scoped by role would give every client one
    shared representative and one shared transcript."""
    first = store.current_conversation_id(gateway_conn, "alice")
    store.append_message(gateway_conn, first, "user", "my portfolio")
    second = store.current_conversation_id(gateway_conn, "bob")

    assert first != second
    assert store.history(gateway_conn, second) == []


def test_a_conversation_must_belong_to_somebody(gateway_conn):
    """No default owner, and no anonymous conversations. A blank owner would
    become a shared bucket by another name."""
    for nobody in ("", "   ", None):
        with pytest.raises(ValueError):
            store.current_conversation_id(gateway_conn, nobody)
        with pytest.raises(ValueError):
            store.start_conversation(gateway_conn, nobody)


def test_a_conversation_predating_owners_is_not_handed_to_the_next_caller(gateway_conn):
    """The upgrade case. A row whose owner is NULL is one whose owner is
    genuinely unknown, and giving it to whoever asks next is exactly the leak
    this column closes."""
    orphan = store.start_conversation(gateway_conn, "boss")
    store.append_message(gateway_conn, orphan, "user", "something private")
    gateway_conn.execute("UPDATE conversations SET owner = NULL")

    fresh = store.current_conversation_id(gateway_conn, "customer")

    assert fresh != orphan
    assert store.history(gateway_conn, fresh) == []


def test_a_session_remembers_who_logged_in_not_only_what_they_are(gateway_conn):
    token, _ = store.create_session(gateway_conn, 60, roles.ROLE_CLIENT, subject="customer")
    assert store.session_subject(gateway_conn, token) == "customer"
    assert store.session_role(gateway_conn, token) == roles.ROLE_CLIENT


def test_a_session_without_a_subject_has_none(gateway_conn):
    """Fail closed, like the role column beside it: an old session is refused
    rather than resolved to somebody."""
    token, _ = store.create_session(gateway_conn, 60, roles.ROLE_CLIENT, subject="customer")
    gateway_conn.execute("UPDATE sessions SET subject = NULL")
    assert store.session_subject(gateway_conn, token) is None


def test_an_expired_session_has_no_subject(gateway_conn):
    token, _ = store.create_session(gateway_conn, -1, roles.ROLE_CLIENT, subject="customer")
    assert store.session_subject(gateway_conn, token) is None


def test_the_socket_scopes_the_transcript_to_the_session(gateway_conn):
    """Asserted at the source, because this is the line that leaked: the ready
    frame is built from the session's own subject rather than from the
    database's newest row."""
    import inspect

    from gateway import main

    source = inspect.getsource(main.conversation_socket)
    assert "session_subject" in source
    assert "current_conversation_id(conn, subject)" in source


# --- a representative, and a familiar one -------------------------------------------


def test_a_client_gets_an_agent_with_a_name(gateway_conn):
    agent = client_agent.ensure(gateway_conn, "customer")
    assert agent["name"] in client_agent.NAME_POOL
    assert agent["created_at"]
    assert agent["client_id"] == "customer"


def test_the_same_client_meets_the_same_agent(gateway_conn):
    """The whole point of §16. An assistant that introduces itself afresh every
    session is a search box with manners."""
    first = client_agent.ensure(gateway_conn, "customer")
    for _ in range(4):
        again = client_agent.ensure(gateway_conn, "customer")
        assert again["name"] == first["name"]
        assert again["created_at"] == first["created_at"]
    assert gateway_conn.fetchone("SELECT COUNT(*) AS n FROM client_agents")["n"] == 1


def test_different_clients_get_different_agents(gateway_conn):
    names = {client_agent.ensure(gateway_conn, f"client-{i}")["name"] for i in range(12)}
    assert len(names) == 12, "two clients were handed the same representative"


def test_the_name_is_deterministic_from_the_client(gateway_conn, tmp_path):
    """Deterministic so the same person gets the same name even in the window
    before the row is written - and persisted anyway, because §16 asks for an
    identity rather than for a hash function."""
    other = store.get_connection(tmp_path / "other.db")
    store.init_schema(other)
    try:
        assert (client_agent.ensure(gateway_conn, "customer")["name"]
                == client_agent.ensure(other, "customer")["name"])
    finally:
        other.close()


def test_the_pool_running_out_suffixes_rather_than_repeats(gateway_conn):
    """A second Ada is a confusion; an "Ada 2" is only plain."""
    for i in range(len(client_agent.NAME_POOL) + 3):
        client_agent.ensure(gateway_conn, f"crowd-{i}")
    names = [row["agent_name"] for row in
             gateway_conn.fetchall("SELECT agent_name FROM client_agents")]
    assert len(names) == len(set(names)), "a name was handed out twice"


# --- familiarity is earned, never claimed --------------------------------------------


def test_a_first_meeting_is_not_greeted_as_a_reunion(gateway_conn):
    """A system that claimed to remember somebody it had never met would be the
    fastest possible way to stop feeling like a familiar representative."""
    met = client_agent.greet(gateway_conn, "customer")
    assert met["returning"] is False
    assert met["meetings"] == 1
    text = client_agent.introduction(met)
    assert "again" not in text.lower()
    assert met["name"] in text


def test_a_returning_client_is_greeted_as_one(gateway_conn):
    client_agent.greet(gateway_conn, "customer")
    second = client_agent.greet(gateway_conn, "customer")

    assert second["returning"] is True
    assert second["meetings"] == 2
    assert "again" in client_agent.introduction(second).lower()


def test_the_greeting_names_the_last_visit_only_when_there_was_one(gateway_conn):
    first = client_agent.greet(gateway_conn, "customer")
    assert first["last_seen_at"] is None
    second = client_agent.greet(gateway_conn, "customer")
    assert second["last_seen_at"] is not None
    assert second["last_seen_at"][:4] in client_agent.introduction(second)


def test_meetings_are_counted_per_client(gateway_conn):
    client_agent.greet(gateway_conn, "alice")
    client_agent.greet(gateway_conn, "alice")
    bob = client_agent.greet(gateway_conn, "bob")
    assert bob["meetings"] == 1 and bob["returning"] is False


# --- honesty about what does not exist ------------------------------------------------


def test_the_agent_has_no_face_and_says_so(gateway_conn):
    """43 §16 asks for a stable face. Nothing renders one for the COO either,
    and §85 recorded why a still image standing in for an animated presenter
    fails the specification rather than approximating it."""
    agent = client_agent.ensure(gateway_conn, "customer")
    assert agent["visual"]["rendered"] is False
    assert agent["visual"]["rendered_note"]
    assert agent["visual"]["source"]


def test_the_voice_record_does_not_promise_a_voice(gateway_conn):
    """Which voices exist is the browser's answer, the same line the console
    already draws."""
    voice = client_agent.ensure(gateway_conn, "customer")["voice"]
    assert "browser-provided" in voice["synthesis"]


def test_an_agent_from_a_newer_build_is_refused_not_replaced(gateway_conn):
    """The rule §88 applies to Kumbhakarnan, applied to somebody's
    representative: recreating an identity because this build could not read it
    is a silent replacement."""
    client_agent.ensure(gateway_conn, "customer")
    gateway_conn.execute("UPDATE client_agents SET schema_version = ?",
                         (client_agent.SCHEMA_VERSION + 1,))

    with pytest.raises(client_agent.AgentFromTheFuture):
        client_agent.load(gateway_conn, "customer")

    assert gateway_conn.fetchone(
        "SELECT agent_name FROM client_agents")["agent_name"] in client_agent.NAME_POOL


def test_an_agent_needs_a_client(gateway_conn):
    for nobody in ("", "  ", None):
        with pytest.raises(ValueError):
            client_agent.ensure(gateway_conn, nobody)


def test_stored_json_is_valid_json(gateway_conn):
    client_agent.ensure(gateway_conn, "customer")
    row = gateway_conn.fetchone("SELECT voice, visual FROM client_agents")
    for column in ("voice", "visual"):
        json.loads(row[column])


def test_scoped_memory_is_not_a_field_on_this_table(gateway_conn):
    """§16 lists "scoped memory", and it is deliberately enforced in
    `conversations.owner` rather than here. Storing it on the agent would make
    it something this module could get wrong; owning the conversation means a
    client cannot reach another's transcript even if this module were absent."""
    columns = {row["name"] for row in
               gateway_conn.fetchall("PRAGMA table_info(client_agents)")}
    assert not any("memory" in column or "message" in column for column in columns)


def test_a_client_with_no_tools_sends_no_tools_parameter():
    """"No tools" and "an empty tools array" are different requests, and the API
    is entitled to reject the second.

    Academic until the Gateway began scoping tools by role: a client is offered
    none, and conversing is their only capability - so an empty array becoming a
    400 would break the one thing they can do, and only for them."""
    from app.model_provider import _tool_argument

    assert _tool_argument([]) == {}
    assert _tool_argument(None) == {}
    assert _tool_argument([{"name": "x"}]) == {"tools": [{"name": "x"}]}
