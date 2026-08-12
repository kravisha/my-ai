import pytest

from app.tools import TOOLS, execute_tool


def test_tools_schema_has_retrieve_portfolio():
    names = [t["name"] for t in TOOLS]
    assert "retrieve_portfolio" in names


def test_tools_schema_entries_have_required_keys():
    for tool in TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


def test_execute_tool_dispatches_retrieve_portfolio(permissions_store, preferences_store, mock_portfolio_path):
    permissions_store.grant("portfolio")
    result = execute_tool("retrieve_portfolio", permissions_store, preferences_store)
    assert result["status"] == "needs_consent"


def test_execute_tool_unknown_name_raises(permissions_store, preferences_store):
    with pytest.raises(ValueError):
        execute_tool("not_a_real_tool", permissions_store, preferences_store)
