"""The Scoreboard over HTTP, and the Scoreboard reached by talking.

Two surfaces onto one board, which is the point: addendum 17 §6 has Jarvis
departments publishing findings into the Gateway rather than inventing their own
notification channels, and §10 has the Super User reviewing them. A department
will use the routes; the Super User uses the conversation. Both have to land in
the same place, and the last test here is what says they do.
"""

import pytest

from app import model_gateway
from gateway import scoreboard
from test_gateway_service import FakeProvider, authenticated_socket


@pytest.fixture
def auth_headers(gateway_token):
    return {"Authorization": f"Bearer {gateway_token}"}


# --- The routes ---


def test_every_scoreboard_route_refuses_an_anonymous_caller(gateway_client, gateway_conn):
    """The board holds the project's open questions, including the security ones.
    Enumerated route by route rather than assumed from one example, because an
    unauthenticated route is only ever discovered by someone looking."""
    item_id = scoreboard.file_item(gateway_conn, source="s", question="q")

    responses = {
        "list": gateway_client.get("/scoreboard"),
        "file": gateway_client.post("/scoreboard", json={"question": "q"}),
        "get": gateway_client.get(f"/scoreboard/{item_id}"),
        "note": gateway_client.post(f"/scoreboard/{item_id}/notes", json={"note": "n"}),
        "resolve": gateway_client.post(f"/scoreboard/{item_id}/resolve", json={"resolution": "r"}),
    }

    assert {name: response.status_code for name, response in responses.items()} == {
        "list": 401,
        "file": 401,
        "get": 401,
        "note": 401,
        "resolve": 401,
    }


def test_filing_over_http_records_the_callers_own_attribution(gateway_client, auth_headers):
    """Unlike the assistant's tool, the route takes a source: a caller holding
    the Super User session is trusted to name itself, and a finding from a
    monitoring agent should not be filed as though a human raised it."""
    response = gateway_client.post(
        "/scoreboard",
        headers=auth_headers,
        json={
            "question": "SQLite write contention under 48 workers?",
            "importance": "important",
            "blocking": False,
            "source": "technology-and-architecture",
            "related_component": "backend/fi_db.py",
        },
    )

    assert response.status_code == 201
    item = response.json()
    assert item["source"] == "technology-and-architecture"
    assert item["related_component"] == "backend/fi_db.py"
    assert item["status"] == "open"


def test_a_source_is_supplied_when_the_caller_does_not_name_one(gateway_client, auth_headers):
    response = gateway_client.post("/scoreboard", headers=auth_headers, json={"question": "q"})

    assert response.json()["source"] == "api"


def test_the_listing_comes_back_in_board_order_with_counts(gateway_client, auth_headers):
    for question, importance in [
        ("informational one", "informational"),
        ("urgent one", "urgent"),
        ("important one", "important"),
    ]:
        gateway_client.post(
            "/scoreboard",
            headers=auth_headers,
            json={"question": question, "importance": importance},
        )

    body = gateway_client.get("/scoreboard", headers=auth_headers).json()

    assert [item["question"] for item in body["items"]] == [
        "urgent one",
        "important one",
        "informational one",
    ]
    assert body["open_counts"] == {"urgent": 1, "important": 1, "informational": 1}


def test_a_bad_filter_is_a_400_not_a_500(gateway_client, auth_headers):
    response = gateway_client.get("/scoreboard?status=pending", headers=auth_headers)

    assert response.status_code == 400
    assert "open" in response.json()["detail"]


def test_a_missing_item_is_a_404(gateway_client, auth_headers):
    assert gateway_client.get("/scoreboard/4242", headers=auth_headers).status_code == 404


def test_notes_and_resolution_over_http(gateway_client, auth_headers):
    item_id = gateway_client.post(
        "/scoreboard", headers=auth_headers, json={"question": "Which exposure mechanism?"}
    ).json()["id"]

    noted = gateway_client.post(
        f"/scoreboard/{item_id}/notes",
        headers=auth_headers,
        json={"note": "A tunnel needs no forwarded port.", "author": "super-user"},
    )
    assert noted.status_code == 201
    assert [note["note"] for note in noted.json()["notes"]] == ["A tunnel needs no forwarded port."]

    resolved = gateway_client.post(
        f"/scoreboard/{item_id}/resolve",
        headers=auth_headers,
        json={"resolution": "Tunnel. Decided 2026-08-18."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    again = gateway_client.post(
        f"/scoreboard/{item_id}/resolve", headers=auth_headers, json={"resolution": "something else"}
    )
    assert again.status_code == 400, "a second resolution must not overwrite the first"


def test_resolving_with_nothing_stated_is_refused_over_http(gateway_client, auth_headers):
    item_id = gateway_client.post(
        "/scoreboard", headers=auth_headers, json={"question": "q"}
    ).json()["id"]

    response = gateway_client.post(
        f"/scoreboard/{item_id}/resolve", headers=auth_headers, json={"resolution": "  "}
    )

    assert response.status_code == 400
    assert gateway_client.get(f"/scoreboard/{item_id}", headers=auth_headers).json()["status"] == "open"


# --- The board reached by talking (addendum 16 §10, one hop) ---


def test_the_assistant_files_an_item_during_a_turn(
    gateway_client, gateway_token, gateway_conn, auth_headers
):
    """The one-hop requirement: saying "put that on the board" files it. A reply
    describing an item the user then has to file somewhere would be exactly the
    manual relay §26 exists to remove."""
    provider = FakeProvider(
        fragments=("Filed as item 1.",),
        tool_calls=[(
            "file_scoreboard_item",
            {
                "question": "Does the Gateway own retry policy?",
                "importance": "important",
                "blocking": True,
                "related_spec": "addendum 16 §11",
            },
        )],
    )
    model_gateway.set_provider(provider)
    try:
        socket, _ = authenticated_socket(gateway_client, gateway_token)
        try:
            socket.send_json({"type": "message", "text": "put the retry question on the board"})

            frames = []
            while True:
                frame = socket.receive_json()
                frames.append(frame)
                if frame["type"] == "done":
                    break
        finally:
            socket.__exit__(None, None, None)
    finally:
        model_gateway.set_provider(None)

    # The user sees the action happen, not only its result.
    assert {"type": "tool", "name": "file_scoreboard_item", "ok": True} in frames
    assert frames[-1]["open_counts"]["important"] == 1

    [item] = scoreboard.list_items(gateway_conn)
    assert item["question"] == "Does the Gateway own retry policy?"
    assert item["blocking"] is True
    assert item["source"] == "super-user-conversation"

    # And the same board is what the routes serve.
    assert gateway_client.get("/scoreboard", headers=auth_headers).json()["items"][0]["id"] == item["id"]


def test_the_tool_result_goes_back_to_the_model(gateway_client, gateway_token):
    """The loop is real: after a tool runs, the model is called again with the
    result, which is how it can say what it filed rather than guessing."""
    provider = FakeProvider(
        fragments=("Done.",),
        tool_calls=[("file_scoreboard_item", {"question": "a question worth keeping"})],
    )
    model_gateway.set_provider(provider)
    try:
        socket, _ = authenticated_socket(gateway_client, gateway_token)
        try:
            socket.send_json({"type": "message", "text": "file it"})
            while socket.receive_json()["type"] != "done":
                pass
        finally:
            socket.__exit__(None, None, None)
    finally:
        model_gateway.set_provider(None)

    assert len(provider.calls) == 2, "the model must be called again with the tool result"
    tool_result_turn = provider.calls[1]["messages"][-1]
    assert tool_result_turn["role"] == "user"
    assert tool_result_turn["content"][0]["type"] == "tool_result"
    assert "a question worth keeping" in tool_result_turn["content"][0]["content"]
    assert tool_result_turn["content"][0]["is_error"] is False


def test_a_refused_tool_call_is_shown_as_failed_and_told_to_the_model(
    gateway_client, gateway_token, gateway_conn
):
    """A rejected write must not look like a successful one, and the model must
    get the reason so it can correct itself instead of the turn dying."""
    provider = FakeProvider(
        fragments=("That importance level does not exist.",),
        tool_calls=[("file_scoreboard_item", {"question": "q", "importance": "critical"})],
    )
    model_gateway.set_provider(provider)
    try:
        socket, _ = authenticated_socket(gateway_client, gateway_token)
        try:
            socket.send_json({"type": "message", "text": "file it as critical"})
            frames = []
            while True:
                frame = socket.receive_json()
                frames.append(frame)
                if frame["type"] == "done":
                    break
        finally:
            socket.__exit__(None, None, None)
    finally:
        model_gateway.set_provider(None)

    assert {"type": "tool", "name": "file_scoreboard_item", "ok": False} in frames
    assert scoreboard.list_items(gateway_conn) == []

    tool_result = provider.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "urgent" in tool_result["content"]


def test_the_ready_frame_carries_the_board_state(gateway_client, gateway_token, gateway_conn):
    """So a client that has just reconnected can show what is outstanding without
    a second round trip - and, on a phone, before the user asks."""
    scoreboard.file_item(gateway_conn, source="s", question="q", importance="urgent")

    socket, ready = authenticated_socket(gateway_client, gateway_token)
    try:
        assert ready["open_counts"] == {"urgent": 1, "important": 0, "informational": 0}
    finally:
        socket.__exit__(None, None, None)
