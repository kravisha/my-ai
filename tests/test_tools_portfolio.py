"""Regression tests for the two-layer permission model in tools/portfolio.py:
  layer 1 (permissions.py) - may MY AI touch the resource at all
  layer 2 (privacy_preferences.py) - may the shareable data be forwarded

These lock in the exact behavior verified by hand during Milestone 2:
distinct denial wording per layer, LOCAL_ONLY fields never leaking, and
layer 1 taking precedence over layer 2.
"""

import json

from app.tools.portfolio import FORWARDING_KEY, retrieve_portfolio

# Matches conftest.py's mock_portfolio_path fixture data - kept as a local
# constant rather than imported to avoid conftest's import-path being
# ambiguous between "conftest" (as pytest loads it) and "tests.conftest".
TEST_ACCOUNT_ID = "ACCT-TEST-99999"


def test_permission_not_granted_returns_error(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    assert "error" in result
    assert "revoked or was never granted" in result["error"]


def test_permission_not_granted_is_audited_as_denied(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is False
    assert entry["result"] == "denied - permission not granted"


def test_granted_but_no_disposition_returns_needs_consent(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    assert result["status"] == "needs_consent"
    assert result["consent_key"] == FORWARDING_KEY
    assert "prompt" in result


def test_needs_consent_does_not_touch_the_audit_log(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    assert not isolated_audit_log.path.exists()


def test_disposition_never_returns_error(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    assert "error" in result
    assert "asked me not to share" in result["error"]


def test_disposition_never_is_audited_distinctly_from_permission_denial(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is False
    assert entry["result"] == "denied - forwarding disposition is 'never'"


def test_never_and_not_granted_produce_different_error_text(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    """Regression test for the bug where both denial kinds were narrated
    identically to the user - the underlying data must actually differ."""
    not_granted_result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)

    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    never_result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)

    assert not_granted_result["error"] != never_result["error"]


def test_disposition_always_returns_sanitized_holdings(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")
    result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    assert "holdings" in result
    assert len(result["holdings"]) == 2
    assert result["holdings"][0]["ticker"] == "AAPL"


def test_disposition_always_never_leaks_account_id(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")
    result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    assert all("account_id" not in row for row in result["holdings"])
    assert TEST_ACCOUNT_ID not in json.dumps(result)


def test_disposition_always_is_audited_as_authorized(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")
    retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is True
    assert entry["result"] == "returned 2 holdings"


def test_allow_once_returns_holdings_without_persisting_disposition(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log, allow_once=True)
    assert "holdings" in result
    assert len(result["holdings"]) == 2
    assert preferences_store.get(FORWARDING_KEY) is None


def test_allow_once_is_audited_as_authorized_and_not_persisted(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    permissions_store.grant("portfolio")
    retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log, allow_once=True)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is True
    assert "one-time" in entry["result"]


def test_allow_once_is_ignored_once_a_real_disposition_exists(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    """allow_once is only a fallback for the no-disposition-yet case - it must
    not override an existing 'never'."""
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log, allow_once=True)
    assert "error" in result


def test_layer_1_denial_takes_precedence_over_layer_2_disposition(permissions_store, preferences_store, mock_portfolio_path, isolated_audit_log):
    """Even with forwarding explicitly allowed, revoked/missing resource
    permission must still block access - the layers are AND'd, not OR'd."""
    preferences_store.set(FORWARDING_KEY, "always")
    result = retrieve_portfolio(permissions_store, preferences_store, isolated_audit_log)
    assert "error" in result
    assert "revoked or was never granted" in result["error"]
