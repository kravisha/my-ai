"""How one turn behaves: what it says it said, and what stops it running forever.

`run_turn` is tested directly here rather than through the socket, because these
are properties of the turn itself and the socket would only obscure them.
"""

import threading

from gateway import conversation, roles, scoreboard, store


class ScriptedProvider:
    """Replays a list of turns. Each is either a string (a final text reply) or a
    (tool_name, arguments) pair, optionally preceded by text - which is what a
    real model does when it says "let me check" and calls a tool in the same
    message."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = 0

    def complete(self, *args, **kwargs):
        raise AssertionError("not used")

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls += 1
        turn = self.turns.pop(0) if self.turns else "and that is all."

        if isinstance(turn, tuple):
            # ("name", {...}) is a bare call; ("said first", ("name", {...})) is
            # one preceded by text. Told apart by the second element, since both
            # forms have two.
            if isinstance(turn[1], tuple):
                preamble, (name, arguments) = turn
            else:
                preamble, (name, arguments) = "", turn
            content = []
            if preamble:
                yield {"type": "text", "text": preamble}
                content.append({"type": "text", "text": preamble})
            content.append(
                {"type": "tool_use", "id": f"tu_{self.calls}", "name": name, "input": arguments}
            )
            yield {"type": "final", "content": content, "stop_reason": "tool_use"}
            return

        yield {"type": "text", "text": turn}
        yield {
            "type": "final",
            "content": [{"type": "text", "text": turn}],
            "stop_reason": "end_turn",
        }


def events_of(db_path, history, provider, role=roles.ROLE_OPERATOR):
    """Defaults to the operator, because these tests are about the turn's
    mechanics rather than about who is having it. What a client's turn can and
    cannot reach is asserted in tests/test_gateway_roles.py."""
    return list(conversation.run_turn(db_path, history, provider, role=role))


def test_the_reply_includes_text_said_before_a_tool_call(tmp_path, gateway_conn):
    """A turn that says "let me check" and then answers must persist both halves:
    the transcript should match the conversation the user actually saw, not only
    its final paragraph."""
    provider = ScriptedProvider([
        ("Let me check the board. ", ("list_scoreboard_items", {})),
        "Nothing is open.",
    ])

    events = events_of(tmp_path / "gateway.db", [{"role": "user", "text": "what is open?"}], provider)

    assert [event["text"] for event in events if event["type"] == "text"] == [
        "Let me check the board. ",
        "Nothing is open.",
    ]
    assert {"type": "tool", "name": "list_scoreboard_items", "ok": True} in events
    assert events[-1] == {"type": "reply", "text": "Let me check the board. Nothing is open."}


def test_a_tool_call_writes_to_the_database_the_path_names(tmp_path):
    """The turn opens its own connection from the path, on whatever thread it is
    running on. This is what makes the worker-thread arrangement safe, so it is
    asserted rather than assumed."""
    db_path = tmp_path / "gateway.db"
    conn = store.get_connection(db_path)
    store.init_schema(conn)
    conn.close()

    provider = ScriptedProvider([("file_scoreboard_item", {"question": "filed from a turn"}), "Filed."])
    events_of(db_path, [{"role": "user", "text": "file it"}], provider)

    conn = store.get_connection(db_path)
    try:
        assert [item["question"] for item in scoreboard.list_items(conn)] == ["filed from a turn"]
    finally:
        conn.close()


def test_a_turn_runs_entirely_on_its_own_thread(tmp_path, gateway_conn):
    """Which is the reason it takes a path: a connection made here could not be
    used there."""
    seen = []

    class ThreadWatcher(ScriptedProvider):
        def stream(self, system, messages, tools, max_tokens=2048):
            seen.append(threading.get_ident())
            yield from super().stream(system, messages, tools, max_tokens)

    provider = ThreadWatcher(["done"])
    worker = threading.Thread(
        target=lambda: events_of(tmp_path / "gateway.db", [{"role": "user", "text": "hi"}], provider)
    )
    worker.start()
    worker.join()

    assert seen and seen[0] != threading.get_ident()


def test_a_looping_turn_stops_and_says_so(tmp_path, gateway_conn):
    """A model that keeps asking for tools is either working or looping, and
    nothing here can tell which. The cap ends it as a visible failure rather than
    an unbounded bill - and the user is told, instead of being given an answer
    that was never reached."""
    provider = ScriptedProvider([("list_scoreboard_items", {})] * 50)

    events = events_of(tmp_path / "gateway.db", [{"role": "user", "text": "go"}], provider)

    tool_events = [event for event in events if event["type"] == "tool"]
    assert len(tool_events) == conversation.MAX_TOOL_ROUNDS
    assert provider.calls == conversation.MAX_TOOL_ROUNDS
    assert "stopped after" in events[-1]["text"]


def test_the_history_becomes_the_model_messages(tmp_path, gateway_conn):
    provider = ScriptedProvider(["fine"])
    history = [
        {"role": "user", "text": "first"},
        {"role": "assistant", "text": "second"},
        {"role": "user", "text": "third"},
    ]

    captured = {}

    class Recording(ScriptedProvider):
        def stream(self, system, messages, tools, max_tokens=2048):
            captured["messages"] = [dict(message) for message in messages]
            yield from super().stream(system, messages, tools, max_tokens)

    events_of(tmp_path / "gateway.db", history, Recording(["fine"]))

    assert captured["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
