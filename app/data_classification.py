"""Data placement classification (Master Spec §8 / Addendum 1 §10).

Every field of a resource is deliberately classified for where it's allowed
to go. LOCAL_ONLY fields are stripped by privacy_filter before the data ever
leaves this process - unconditionally, with no user prompt, because this is
a hard rule MY AI enforces rather than a trust decision the user negotiates.
SERVICE_SHAREABLE fields are eligible to be sent to an external reasoning
model, but only once the user has granted a forwarding disposition (see
privacy_preferences.py) - that's the trust decision.
"""

from enum import Enum


class DataClass(Enum):
    LOCAL_ONLY = "local_only"
    PRIVATE_SYNCHRONIZED = "private_synchronized"
    SERVICE_SHAREABLE = "service_shareable"
    GENERAL = "general"


PORTFOLIO_FIELD_CLASSES = {
    "ticker": DataClass.SERVICE_SHAREABLE,
    "shares": DataClass.SERVICE_SHAREABLE,
    "purchase_price": DataClass.SERVICE_SHAREABLE,
    "purchase_date": DataClass.SERVICE_SHAREABLE,
    "account_id": DataClass.LOCAL_ONLY,
}
