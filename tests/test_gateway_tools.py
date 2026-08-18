"""The assistant's tools: the dispatcher, and the promises the schemas make.

Every test here exercises `tools.execute` directly rather than through a model,
because what matters is that a plausible-but-wrong call comes back as something
the model can read and correct itself from. A tool that raises ends the turn; a
tool that returns `{"error": ...}` lets the assistant try again.
"""

from gateway import repositories, scoreboard, tools


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

# --- Git (G4) ---
#
# The repository machinery itself is covered in tests/test_gateway_repositories.py
# against real git repositories. What matters here is the dispatcher's half: that
# a refusal reaches the model as something it can read, and that the confirmation
# a public publish requires cannot be produced by the model's own reasoning about
# the document.


def test_the_git_tools_report_that_nothing_is_configured(gateway_conn, monkeypatch):
    """Default closed. An unconfigured Gateway must say so rather than reaching
    for a repository nobody named."""
    monkeypatch.delenv(repositories.PRIVATE_REPO_ENV, raising=False)
    monkeypatch.delenv(repositories.PUBLIC_REPO_ENV, raising=False)

    for name in ("list_repository_files", "read_repository_file", "publish_document"):
        result = tools.execute(gateway_conn, name, {"path": "docs/x.md", "content": "c", "message": "m"})
        assert repositories.PRIVATE_REPO_ENV in result["error"]


def test_reading_a_file_through_a_tool(gateway_conn, private_repo):
    listed = tools.execute(gateway_conn, "list_repository_files", {"prefix": "docs"})
    assert listed["files"] == ["docs/existing.md"]
    assert listed["visibility"] == "private"

    read = tools.execute(gateway_conn, "read_repository_file", {"path": "docs/existing.md"})
    assert "Some text." in read["content"]


def test_an_untracked_file_is_refused_through_the_tool(gateway_conn, private_repo):
    """The .env case, reached the way the model would reach it."""
    result = tools.execute(gateway_conn, "read_repository_file", {"path": "secret.env"})

    assert "not tracked" in result["error"]


def test_publishing_through_a_tool_defaults_to_the_private_repository(
    gateway_conn, private_repo, public_repo
):
    result = tools.execute(
        gateway_conn,
        "publish_document",
        {"path": "docs/spec.md", "content": "# Spec\n", "message": "Add the spec"},
    )

    assert result["published"]["repository"] == private_repo.name
    assert result["published"]["visibility"] == "private"
    assert result["published"]["pushed"] is False


def test_a_public_publish_without_confirmation_is_refused_readably(
    gateway_conn, private_repo, public_repo
):
    """The model gets told why, in terms that tell it what to do next: ask."""
    result = tools.execute(
        gateway_conn,
        "publish_document",
        {
            "path": "docs/spec.md",
            "content": "Technical content.\n",
            "message": "Add",
            "repository": public_repo.name,
        },
    )

    assert "explicit confirmation" in result["error"]
    assert "ask" in result["error"]


def test_private_material_bound_for_the_public_repository_is_refused(
    gateway_conn, private_repo, public_repo
):
    result = tools.execute(
        gateway_conn,
        "publish_document",
        {
            "path": "docs/principles.md",
            "content": "The constitution's axioms govern how agents are judged.\n",
            "message": "Add principles",
            "repository": public_repo.name,
            "confirm_public": True,
        },
    )

    assert "constitution" in result["error"]
    assert "do not work around this check" in result["error"]


def test_the_publish_schema_makes_the_confirmation_a_deliberate_act():
    """confirm_public is not required, so its absence is the safe path, and its
    description tells the model the only condition under which it may be set."""
    schema = _schema("publish_document")

    assert "confirm_public" not in schema["required"]
    assert "explicitly" in schema["properties"]["confirm_public"]["description"]



def _schema(name: str) -> dict:
    return next(tool for tool in tools.TOOLS if tool["name"] == name)["input_schema"]
