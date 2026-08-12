"""Shared fixtures. The env var must be set before anything imports
app.model_gateway, since it constructs the Anthropic client at import time
(`_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`) - without
this, merely importing app.main would crash in a clean environment with no
.env file. No real network call is ever made in these tests; call_reasoning_model
itself is always mocked out, so the key's value never matters, only its presence.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import pytest
from openpyxl import Workbook

from app import permissions as permissions_module
from app.audit import AuditLog
from app.permissions import PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.session import SessionStore
from app.users import UserStore

TEST_ACCOUNT_ID = "ACCT-TEST-99999"

TEST_ROWS = [
    ("AAPL", 10, 100.0, "2023-01-01", TEST_ACCOUNT_ID),
    ("MSFT", 5, 200.0, "2023-02-02", TEST_ACCOUNT_ID),
]


@pytest.fixture
def permissions_store(tmp_path):
    return PermissionManager(path=tmp_path / "permissions.json")


@pytest.fixture
def preferences_store(tmp_path):
    return PrivacyPreferenceStore(path=tmp_path / "privacy_preferences.json")


@pytest.fixture
def isolated_audit_log(tmp_path):
    return AuditLog(path=tmp_path / "audit_log.jsonl")


@pytest.fixture
def users_store(tmp_path):
    return UserStore(path=tmp_path / "users.json")


@pytest.fixture
def session_store(tmp_path):
    return SessionStore(path=tmp_path / "session.json")


@pytest.fixture
def mock_portfolio_path(tmp_path, monkeypatch):
    """Writes a small real .xlsx with known rows and redirects
    permissions.RESOURCE_PATHS["portfolio"] to it, so tools/portfolio.py
    reads test data instead of the real data/portfolio.xlsx."""
    path = tmp_path / "portfolio.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Ticker", "Shares", "Purchase Price", "Purchase Date", "Account ID"])
    for row in TEST_ROWS:
        ws.append(list(row))
    wb.save(path)

    monkeypatch.setitem(permissions_module.RESOURCE_PATHS, "portfolio", path)
    return path
