from app.privacy_filter import sanitize_portfolio_rows


def test_strips_local_only_account_id():
    rows = [{"ticker": "AAPL", "shares": 10, "purchase_price": 100.0,
              "purchase_date": "2023-01-01", "account_id": "ACCT-SECRET"}]
    sanitized = sanitize_portfolio_rows(rows)
    assert "account_id" not in sanitized[0]


def test_keeps_all_shareable_fields():
    rows = [{"ticker": "AAPL", "shares": 10, "purchase_price": 100.0,
              "purchase_date": "2023-01-01", "account_id": "ACCT-SECRET"}]
    sanitized = sanitize_portfolio_rows(rows)
    assert sanitized[0] == {
        "ticker": "AAPL", "shares": 10, "purchase_price": 100.0, "purchase_date": "2023-01-01",
    }


def test_drops_unlisted_fields_not_just_account_id():
    rows = [{"ticker": "AAPL", "shares": 10, "purchase_price": 100.0,
              "purchase_date": "2023-01-01", "internal_notes": "should never appear"}]
    sanitized = sanitize_portfolio_rows(rows)
    assert "internal_notes" not in sanitized[0]


def test_empty_input_returns_empty_list():
    assert sanitize_portfolio_rows([]) == []


def test_row_missing_a_shareable_field_does_not_raise():
    rows = [{"ticker": "AAPL"}]
    sanitized = sanitize_portfolio_rows(rows)
    assert sanitized[0] == {"ticker": "AAPL"}


def test_multiple_rows_all_sanitized():
    rows = [
        {"ticker": "AAPL", "shares": 10, "purchase_price": 100.0, "purchase_date": "2023-01-01", "account_id": "A"},
        {"ticker": "MSFT", "shares": 5, "purchase_price": 200.0, "purchase_date": "2023-02-02", "account_id": "A"},
    ]
    sanitized = sanitize_portfolio_rows(rows)
    assert len(sanitized) == 2
    assert all("account_id" not in row for row in sanitized)
