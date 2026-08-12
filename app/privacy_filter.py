"""Sanitizes local data before it is ever included in a prompt to the external model.

Field inclusion is driven by data_classification.py's placement registry, not
a hand-maintained allow-list: only SERVICE_SHAREABLE/GENERAL fields pass
through. LOCAL_ONLY fields (e.g. account_id) are dropped unconditionally,
regardless of any forwarding disposition in privacy_preferences.py - that
store governs whether shareable data may go out, not whether local-only
data ever becomes eligible to.
"""

from .data_classification import PORTFOLIO_FIELD_CLASSES, DataClass

_PORTFOLIO_SHAREABLE_FIELDS = tuple(
    field for field, cls in PORTFOLIO_FIELD_CLASSES.items()
    if cls in (DataClass.SERVICE_SHAREABLE, DataClass.GENERAL)
)


def sanitize_portfolio_rows(rows: list[dict]) -> list[dict]:
    return [{field: row[field] for field in _PORTFOLIO_SHAREABLE_FIELDS if field in row} for row in rows]
