"""The assistant's tools: the dispatcher, and the promises the schemas make.

Every test here exercises `tools.execute` directly rather than through a model,
because what matters is that a plausible-but-wrong call comes back as something
the model can read and correct itself from. A tool that raises ends the turn; a
tool that returns `{"error": ...}` lets the assistant try again.
"""

from gateway import scoreboard, tools


def test_filing_through_a_tool_returns_the_item_it_created(gateway_conn):
    result = tools.execute(
        gateway_conn,
        "file_scoreboard_item",
        {
            "question": "Should the Gateway own retry policy?",
            "importance": "important",
            "blocking": True,
            "related_spec": "addendum 16 §11",
        },
    )

    assert result["filed"]["question"] == "Should the Gateway own retry policy?"
    assert result["filed"]["importance"] == "important"
    assert result["filed"]["blocking"] is True
    assert result["filed"]["id"] > 0


def test_the_model_cannot_choose_its_own_provenance(gateway_conn):
    """Source is set by the dispatcher. A model able to name its own source could
    file an item as though a monitoring agent had raised it, and provenance that
    the filer controls is not provenance."""
    assert "source" not in _schema("file_scoreboard_item")["properties"]

    result = tools.execute(
        gateway_conn, "file_scoreboard_item", {"question": "q", "source": "technology-agent"}
    )

    assert result["filed"]["source"] == tools.CONVERSATION_SOURCE


def test_importance_defaults_to_informational(gateway_conn):
    """The safe default. An assistant that omits the field is not asserting
    urgency, and treating an omission as urgent would make the level meaningless
    within a day."""
    result = tools.execute(gateway_conn, "file_scoreboard_item", {"question": "q"})

    assert result["filed"]["importance"] == "informational"


def test_a_refused_write_comes_back_as_a_readable_error(gateway_conn):
    result = tools.execute(
        gateway_conn, "file_scoreboard_item", {"question": "q", "importance": "critical"}
    )

    assert "error" in result
    assert "urgent" in result["error"], "the message has to name the values, not only reject one"
    assert scoreboard.list_items(gateway_conn) == []


def test_a_malformed_call_does_not_raise(gateway_conn):
    """The turn survives a bad tool call. Anything that escapes here kills the
    conversation instead of correcting it."""
    for name, arguments in [
        ("get_scoreboard_item", {}),
        ("get_scoreboard_item", {"item_id": "not-a-number"}),
        ("add_scoreboard_note", {"item_id": 1}),
        ("resolve_scoreboard_item", {"item_id": None, "resolution": "x"}),
    ]:
        result = tools.execute(gateway_conn, name, arguments)
        assert "error" in result, f"{name} {arguments} should have been reported, not raised"


def test_an_unknown_tool_is_reported(gateway_conn):
    assert "error" in tools.execute(gateway_conn, "delete_everything", {})


def test_listing_carries_the_open_counts(gateway_conn):
    """So the assistant can answer "what is outstanding" without a second call,
    and so its answer and the client's badge come from the same source."""
    tools.execute(gateway_conn, "file_scoreboard_item", {"question": "a", "importance": "urgent"})

    result = tools.execute(gateway_conn, "list_scoreboard_items", {})

    assert len(result["items"]) == 1
    assert result["open_counts"]["urgent"] == 1


def test_reading_an_item_includes_its_discussion(gateway_conn):
    item_id = tools.execute(gateway_conn, "file_scoreboard_item", {"question": "q"})["filed"]["id"]
    tools.execute(gateway_conn, "add_scoreboard_note", {"item_id": item_id, "note": "a thought"})

    result = tools.execute(gateway_conn, "get_scoreboard_item", {"item_id": item_id})

    assert [note["note"] for note in result["item"]["notes"]] == ["a thought"]


def test_resolving_through_a_tool_closes_the_item(gateway_conn):
    item_id = tools.execute(gateway_conn, "file_scoreboard_item", {"question": "q"})["filed"]["id"]

    result = tools.execute(
        gateway_conn,
        "resolve_scoreboard_item",
        {"item_id": item_id, "resolution": "Tunnel, not a forwarded port."},
    )

    assert result["resolved"]["status"] == "resolved"
    assert result["resolved"]["resolution"] == "Tunnel, not a forwarded port."


def test_resolving_with_no_stated_decision_is_refused(gateway_conn):
    item_id = tools.execute(gateway_conn, "file_scoreboard_item", {"question": "q"})["filed"]["id"]

    result = tools.execute(
        gateway_conn, "resolve_scoreboard_item", {"item_id": item_id, "resolution": ""}
    )

    assert "error" in result
    assert scoreboard.get_item(gateway_conn, item_id)["status"] == "open"


def test_every_declared_tool_is_dispatchable(gateway_conn):
    """A schema with no branch behind it is a tool the model will call and always
    fail at - and it would fail as 'Unknown tool', which reads like a bug in the
    model rather than a gap in the dispatcher."""
    for tool in tools.TOOLS:
        result = tools.execute(gateway_conn, tool["name"], {})
        assert result.get("error", "") != f"Unknown tool {tool['name']!r}."


def test_the_schemas_offer_only_values_the_store_accepts():
    """The enums are generated from the store's own vocabularies rather than
    retyped, so this asserts they stayed generated."""
    assert _schema("file_scoreboard_item")["properties"]["importance"]["enum"] == list(
        scoreboard.IMPORTANCE_LEVELS
    )
    assert _schema("list_scoreboard_items")["properties"]["status"]["enum"] == list(
        scoreboard.STATUSES
    )


def _schema(name: str) -> dict:
    return next(tool for tool in tools.TOOLS if tool["name"] == name)["input_schema"]
