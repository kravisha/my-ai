"""The two-layer permission model in tools/portfolio.py, and the per-account
source it now reads (TQ-72; §111, §112).

  layer 1 (permissions.py) - may MY AI touch the resource at all
  layer 2 (privacy_preferences.py) - may the shareable data be forwarded

These lock in the exact behaviour verified by hand during Milestone 2: distinct
denial wording per layer, and layer 1 taking precedence over layer 2.

**Both layers survived every reshaping of what sits underneath them**, which is
the interesting part. The data has been a shared spreadsheet, then a stored
`SUPERUSER` portfolio (TQ-46), and is now a per-account external source fetched
at request time (§112) — and the consent model has not changed once, because it
was never about where the positions were kept. It is about whether they may be
sent to a reasoning model.

TQ-46 §11 Q2 established that layer 2 is not redundant with §108's
`PATH_REFUSED`: nothing reaching a model here carries a `LOCAL_ONLY`
classification, so the floor is never raised and **this prompt is the only
control**.
"""

import json

import pytest
from openpyxl import Workbook

from app.tools.portfolio import FORWARDING_KEY, SOURCE_FILENAME, retrieve_portfolio

OPERATOR = "krish"

ROWS = [
    ("AAPL", 25, 172.34, "2023-03-14", "ACCT-88421"),
    ("MSFT", 15, 310.12, "2023-06-02", "ACCT-88421"),
]


@pytest.fixture
def user_sources(tmp_path, monkeypatch):
    """Per-account portfolio sources, under a temporary user-data root.

    Returns a function that writes a source for one account. There is no way to
    write "the" source, because there is no shared one any more — which is the
    property `test_one_accounts_source_is_not_another_accounts` exists for."""
    import app.tools.portfolio as tool

    def _write(username, rows=ROWS):
        directory = tmp_path / username
        directory.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Ticker", "Shares", "Purchase Price", "Purchase Date", "Account ID"])
        for row in rows:
            sheet.append(list(row))
        workbook.save(directory / SOURCE_FILENAME)
        return directory / SOURCE_FILENAME

    monkeypatch.setattr(tool, "ensure_user_data_dir",
                        lambda username: (tmp_path / username).resolve())
    (tmp_path / OPERATOR).mkdir(parents=True, exist_ok=True)
    return _write


def _retrieve(permissions, preferences, audit_log, *, username=OPERATOR, allow_once=False):
    return retrieve_portfolio(None, username, permissions, preferences, audit_log,
                              allow_once=allow_once)


# --- layer 1: the permission grant --------------------------------------------------


def test_permission_not_granted_returns_error(permissions_store, preferences_store,
                                              user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    result = _retrieve(permissions_store, preferences_store, isolated_audit_log)
    assert "error" in result
    assert "revoked or was never granted" in result["error"]


def test_permission_not_granted_is_audited_as_denied(permissions_store, preferences_store,
                                                     user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    _retrieve(permissions_store, preferences_store, isolated_audit_log)
    entry = json.loads(isolated_audit_log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["authorized"] is False
    assert entry["result"] == "denied - permission not granted"


def test_layer_1_denial_takes_precedence_over_layer_2_disposition(
        permissions_store, preferences_store, user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    preferences_store.set(FORWARDING_KEY, "always")
    result = _retrieve(permissions_store, preferences_store, isolated_audit_log)
    assert "revoked or was never granted" in result["error"]


# --- layer 2: the forwarding disposition --------------------------------------------


def test_granted_but_no_disposition_returns_needs_consent(
        permissions_store, preferences_store, user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    permissions_store.grant("portfolio")
    result = _retrieve(permissions_store, preferences_store, isolated_audit_log)
    assert result["status"] == "needs_consent"
    assert result["consent_key"] == FORWARDING_KEY
    assert "prompt" in result


def test_needs_consent_does_not_touch_the_audit_log(
        permissions_store, preferences_store, user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    permissions_store.grant("portfolio")
    _retrieve(permissions_store, preferences_store, isolated_audit_log)
    assert not isolated_audit_log.path.exists()


def test_disposition_never_returns_error(permissions_store, preferences_store,
                                         user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    result = _retrieve(permissions_store, preferences_store, isolated_audit_log)
    assert "asked me not to share" in result["error"]


def test_never_and_not_granted_produce_different_error_text(
        permissions_store, preferences_store, user_sources, isolated_audit_log):
    """Two layers, two remedies. An operator told the same sentence for both
    would not know which one to go and change."""
    user_sources(OPERATOR)
    ungranted = _retrieve(permissions_store, preferences_store, isolated_audit_log)

    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    refused = _retrieve(permissions_store, preferences_store, isolated_audit_log)

    assert ungranted["error"] != refused["error"]


def test_disposition_always_returns_the_positions(permissions_store, preferences_store,
                                                  user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")

    result = _retrieve(permissions_store, preferences_store, isolated_audit_log)

    assert [h["symbol"] for h in result["holdings"]] == ["AAPL", "MSFT"]
    assert result["holdings"][0]["quantity"] == 25
    assert result["holdings"][0]["average_cost"] == 172.34
    assert result["holdings"][0]["acquired_on"] == "2023-03-14"


def test_allow_once_returns_positions_without_persisting_a_disposition(
        permissions_store, preferences_store, user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    permissions_store.grant("portfolio")

    result = _retrieve(permissions_store, preferences_store, isolated_audit_log,
                       allow_once=True)

    assert len(result["holdings"]) == 2
    assert preferences_store.get(FORWARDING_KEY) is None


def test_allow_once_is_ignored_once_a_real_disposition_exists(
        permissions_store, preferences_store, user_sources, isolated_audit_log):
    user_sources(OPERATOR)
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")

    result = _retrieve(permissions_store, preferences_store, isolated_audit_log,
                       allow_once=True)

    assert "asked me not to share" in result["error"]


# --- the source itself ---------------------------------------------------------------


def test_one_accounts_source_is_not_another_accounts(permissions_store, preferences_store,
                                                     user_sources, isolated_audit_log):
    """**The test that could not have been written before TQ-72.**

    The source path is derived from the authenticated username and is never an
    argument, so "read the other account's file" is not a call that can be
    constructed. This file used to record the opposite as deliberate — *"a single
    shared file by design"* — which was the ownerless retrieval wearing a second
    hat."""
    user_sources("alice", [("AAPL", 25, 172.34, "2023-03-14", "ACCT-1")])
    user_sources("bob", [("TSLA", 4, 900.00, "2024-01-01", "ACCT-2")])
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")

    alice = _retrieve(permissions_store, preferences_store, isolated_audit_log,
                      username="alice")
    bob = _retrieve(permissions_store, preferences_store, isolated_audit_log,
                    username="bob")

    assert [h["symbol"] for h in alice["holdings"]] == ["AAPL"]
    assert [h["symbol"] for h in bob["holdings"]] == ["TSLA"]


def test_a_missing_source_refuses_rather_than_answering_emptily(
        permissions_store, preferences_store, user_sources, isolated_audit_log):
    """An empty list would read as "you hold nothing" — a false statement about
    somebody's money in the voice of a true one. §110 §4.5's rule, one domain
    over, and it is also what stops a fallback to a shared file ever looking
    attractive."""
    user_sources(OPERATOR)
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")

    result = _retrieve(permissions_store, preferences_store, isolated_audit_log,
                       username="nobody-with-a-source")

    assert "holdings" not in result
    assert "no portfolio source configured" in result["error"]
    assert "anybody else's" in result["error"]


def test_no_account_id_can_leak_because_none_is_read(
        permissions_store, preferences_store, user_sources, isolated_audit_log):
    """The same guarantee as before, made by not picking the value up rather than
    by filtering it out afterwards.

    `app/privacy_filter.py` strips `account_id` on egress because it does not own
    that file's schema. This reader owns what it picks up, so the column is never
    read — and a value that was never read cannot be leaked by a future caller
    who forgets to sanitize."""
    user_sources(OPERATOR)
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")

    result = _retrieve(permissions_store, preferences_store, isolated_audit_log)

    assert "ACCT-88421" not in json.dumps(result)
    assert all("account" not in key for row in result["holdings"] for key in row)


def test_nothing_is_written_anywhere(permissions_store, preferences_store, user_sources,
                                     isolated_audit_log, tmp_path):
    """§111: the system holds no information of the portfolios.

    Asserted as a property of the filesystem rather than of the code path,
    because that is the version a future caching change cannot pass.

    **The audit log is the one permitted write, and what it may contain is the
    point.** §111 says every durable writer owes the audit `routing_decisions`
    already passed: it records *that* a read happened and *how many* positions
    came back. A count is not a position. The day somebody logs the symbols "for
    debugging", this fails."""
    source = user_sources(OPERATOR)
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    _retrieve(permissions_store, preferences_store, isolated_audit_log)

    written = {p for p in tmp_path.rglob("*") if p.is_file()} - before
    assert written <= {isolated_audit_log.path}, (
        f"the read wrote something other than the audit log: "
        f"{sorted(written - {isolated_audit_log.path})}")
    assert source.exists(), "the source itself must be left alone"

    audited = isolated_audit_log.path.read_text(encoding="utf-8")
    assert "returned 2 holdings" in audited
    for leaked in ("AAPL", "MSFT", "172.34", "ACCT-88421"):
        assert leaked not in audited, (
            f"the audit log recorded {leaked!r} - it may record that a read happened "
            "and how many positions came back, never the positions themselves")
