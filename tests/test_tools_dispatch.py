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


def test_execute_tool_dispatches_retrieve_portfolio(portfolio_conn, permissions_store,
                                                   preferences_store, isolated_audit_log):
    permissions_store.grant("portfolio")
    result = execute_tool("retrieve_portfolio", portfolio_conn, "krish", permissions_store,
                          preferences_store, isolated_audit_log)
    assert result["status"] == "needs_consent"


def test_execute_tool_unknown_name_raises(portfolio_conn, permissions_store,
                                          preferences_store, isolated_audit_log):
    with pytest.raises(ValueError):
        execute_tool("not_a_real_tool", portfolio_conn, "krish", permissions_store,
                     preferences_store, isolated_audit_log)


def test_the_dispatcher_requires_an_owner():
    """§16.7 enforced where it is cheapest: an owner that is optional is an owner
    somebody forgets to pass, so both the connection and the username are
    positional and required."""
    import inspect

    parameters = inspect.signature(execute_tool).parameters
    for required in ("conn", "username"):
        assert required in parameters, f"execute_tool lost its {required!r} argument"
        assert parameters[required].default is inspect.Parameter.empty, (
            f"execute_tool's {required!r} has a default; an ownerless call must not be "
            "constructible")
