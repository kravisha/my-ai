from app.data_classification import DataClass, PORTFOLIO_FIELD_CLASSES


def test_portfolio_fields_are_exactly_the_expected_five():
    assert set(PORTFOLIO_FIELD_CLASSES.keys()) == {
        "ticker", "shares", "purchase_price", "purchase_date", "account_id",
    }


def test_account_id_is_local_only():
    assert PORTFOLIO_FIELD_CLASSES["account_id"] is DataClass.LOCAL_ONLY


def test_holdings_fields_are_service_shareable():
    for field in ("ticker", "shares", "purchase_price", "purchase_date"):
        assert PORTFOLIO_FIELD_CLASSES[field] is DataClass.SERVICE_SHAREABLE
