"""Regression tests for the two-layer permission model in tools/portfolio.py:
  layer 1 (permissions.py) - may MY AI touch the resource at all
  layer 2 (privacy_preferences.py) - may the shareable data be forwarded

These lock in the exact behavior verified by hand during Milestone 2:
distinct denial wording per layer, LOCAL_ONLY fields never leaking, and
layer 1 taking precedence over layer 2.

**Both layers survive TQ-46 unchanged, and that was the point of Q1's reading
B.** What changed underneath them is where the holdings come from: an owned
`SUPERUSER` portfolio rather than `data/portfolio.xlsx`, reached through
`portfolios.resolve` like everything else. So every call now names a `conn` and
a `username`, which is §16.7's "ownerless retrieval" fixed in the one place it
cannot be forgotten - the signature.

Q2 is why layer 2 is still here at all: measured rather than assumed, the rows
that reach a model carry no `LOCAL_ONLY` field, so §108's `PATH_REFUSED` never
fires and **this consent prompt is the only control on forwarding the operator's
holdings externally.**
"""

import json

import pytest

from app.tools.portfolio import FORWARDING_KEY, retrieve_portfolio
from backend import holdings, superuser_portfolio

OPERATOR = "krish"


@pytest.fixture
def owned_portfolio(portfolio_conn):
    """The operator's own portfolio, with holdings, in the database.

    Replaces the `mock_portfolio_path` spreadsheet these tests used to read.
    That fixture redirected a *file path*; this one seeds an *owned entity*,
    which is the whole change TQ-46 makes."""
    portfolio = superuser_portfolio.ensure(portfolio_conn, OPERATOR)
    holdings.record(portfolio_conn, portfolio, symbol="AAPL", quantity=25,
                    average_cost=172.34, acquired_on="2023-03-14")
    holdings.record(portfolio_conn, portfolio, symbol="MSFT", quantity=15,
                    average_cost=310.12, acquired_on="2023-06-02")
    return portfolio


def test_permission_not_granted_returns_error(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    assert "error" in result
    assert "revoked or was never granted" in result["error"]


def test_permission_not_granted_is_audited_as_denied(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is False
    assert entry["result"] == "denied - permission not granted"


def test_granted_but_no_disposition_returns_needs_consent(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    permissions_store.grant("portfolio")
    result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    assert result["status"] == "needs_consent"
    assert result["consent_key"] == FORWARDING_KEY
    assert "prompt" in result


def test_needs_consent_does_not_touch_the_audit_log(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    permissions_store.grant("portfolio")
    retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    assert not isolated_audit_log.path.exists()


def test_disposition_never_returns_error(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    assert "error" in result
    assert "asked me not to share" in result["error"]


def test_disposition_never_is_audited_distinctly_from_permission_denial(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is False
    assert entry["result"] == "denied - forwarding disposition is 'never'"


def test_never_and_not_granted_produce_different_error_text(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    """Regression test for the bug where both denial kinds were narrated
    identically to the user - the underlying data must actually differ."""
    not_granted_result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)

    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    never_result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)

    assert not_granted_result["error"] != never_result["error"]


def test_disposition_always_returns_sanitized_holdings(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")
    result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    assert "holdings" in result
    assert len(result["holdings"]) == 2
    # The canonical shape (TQ-45a), not the spreadsheet's column names.
    assert result["holdings"][0]["symbol"] == "AAPL"
    assert result["holdings"][0]["quantity"] == 25
    assert result["holdings"][0]["average_cost"] == 172.34


def test_no_account_id_can_leak_because_none_is_stored(permissions_store, preferences_store,
                                                       owned_portfolio, portfolio_conn,
                                                       isolated_audit_log):
    """The same guarantee as before, now made structurally instead of by
    filtering.

    This test used to assert that `sanitize_portfolio_rows` had stripped
    `account_id` on the way out — correct for a filter over a file whose schema
    we do not own. TQ-46 moved the holdings into a table that **has no account
    column at all**, which is the stronger form §96 chose deliberately: *a field
    that does not exist cannot be leaked by a future reader who forgets to
    sanitize.*

    So the assertion is now about the schema, not about the output. An output
    check would keep passing if somebody added the column back and a caller
    happened not to select it."""
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")
    result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)

    assert all("account_id" not in row for row in result["holdings"])
    assert "account" not in json.dumps(result).lower()

    columns = {row["name"] for row in
               portfolio_conn.fetchall("PRAGMA table_info(portfolio_holdings)")}
    assert not any("account" in column for column in columns), (
        f"portfolio_holdings grew an account column: {sorted(columns)}. There is "
        "deliberately nowhere for an account id to be stored.")


def test_disposition_always_is_audited_as_authorized(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")
    retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is True
    assert entry["result"] == "returned 2 holdings"


def test_allow_once_returns_holdings_without_persisting_disposition(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    permissions_store.grant("portfolio")
    result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log, allow_once=True)
    assert "holdings" in result
    assert len(result["holdings"]) == 2
    assert preferences_store.get(FORWARDING_KEY) is None


def test_allow_once_is_audited_as_authorized_and_not_persisted(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    permissions_store.grant("portfolio")
    retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log, allow_once=True)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is True
    assert "one-time" in entry["result"]


def test_allow_once_is_ignored_once_a_real_disposition_exists(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    """allow_once is only a fallback for the no-disposition-yet case - it must
    not override an existing 'never'."""
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log, allow_once=True)
    assert "error" in result


def test_layer_1_denial_takes_precedence_over_layer_2_disposition(permissions_store, preferences_store, owned_portfolio, portfolio_conn, isolated_audit_log):
    """Even with forwarding explicitly allowed, revoked/missing resource
    permission must still block access - the layers are AND'd, not OR'd."""
    preferences_store.set(FORWARDING_KEY, "always")
    result = retrieve_portfolio(portfolio_conn, OPERATOR, permissions_store,
                            preferences_store, isolated_audit_log)
    assert "error" in result
    assert "revoked or was never granted" in result["error"]
