"""retrieve_portfolio tool: the one action Milestone 1/2 exposes to the model.

Two-layer check before any data reaches the model:
  Layer 1 (permissions.py): may MY AI touch data/portfolio.xlsx at all.
  Layer 2 (privacy_preferences.py): may the SERVICE_SHAREABLE fields already
    read from that file be forwarded to the reasoning model. If no
    disposition is stored yet, this tool returns needs_consent instead of
    data or a denial - main.py's chat loop handles that by pausing and
    asking the user directly, before the model ever sees a result.

account_id is LOCAL_ONLY (data_classification.py) and is stripped by
sanitize_portfolio_rows unconditionally - it never becomes eligible for
layer 2 at all, regardless of disposition.
"""

from openpyxl import load_workbook

from ..audit import AuditLog
from ..permissions import RESOURCE_PATHS, PermissionManager
from ..privacy_filter import sanitize_portfolio_rows
from ..privacy_preferences import PrivacyPreferenceStore

RESOURCE = "portfolio"
FORWARDING_KEY = "portfolio_holdings:reasoning_model"
CONSENT_PROMPT = (
    "I need to share your portfolio holdings (ticker, shares, purchase price, "
    "purchase date) with the reasoning model to answer this. Your account ID "
    "stays local and is never sent. Allow this?"
)


def retrieve_portfolio(
    permissions: PermissionManager,
    preferences: PrivacyPreferenceStore,
    audit_log: AuditLog,
    allow_once: bool = False,
) -> dict:
    if not permissions.is_granted(RESOURCE):
        audit_log.record(
            action="retrieve_portfolio",
            resource=RESOURCE,
            authorized=False,
            result="denied - permission not granted",
        )
        return {"error": "Permission to access the portfolio has been revoked or was never granted."}

    disposition = preferences.get(FORWARDING_KEY)
    if disposition is None:
        if allow_once:
            sanitized = _read_and_sanitize()
            audit_log.record(
                action="retrieve_portfolio",
                resource=RESOURCE,
                authorized=True,
                result=f"returned {len(sanitized)} holdings (one-time consent, not persisted)",
            )
            return {"holdings": sanitized}
        return {"status": "needs_consent", "consent_key": FORWARDING_KEY, "prompt": CONSENT_PROMPT}

    if disposition == "never":
        audit_log.record(
            action="retrieve_portfolio",
            resource=RESOURCE,
            authorized=False,
            result="denied - forwarding disposition is 'never'",
        )
        return {"error": "You've asked me not to share portfolio data with the reasoning model."}

    sanitized = _read_and_sanitize()
    audit_log.record(
        action="retrieve_portfolio",
        resource=RESOURCE,
        authorized=True,
        result=f"returned {len(sanitized)} holdings",
    )
    return {"holdings": sanitized}


def _read_and_sanitize() -> list[dict]:
    path = RESOURCE_PATHS[RESOURCE]
    wb = load_workbook(path, read_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(min_row=2, values_only=True)
    rows = [
        {
            "ticker": r[0],
            "shares": r[1],
            "purchase_price": r[2],
            "purchase_date": r[3],
            "account_id": r[4],
        }
        for r in rows_iter
        if r[0] is not None
    ]
    wb.close()
    return sanitize_portfolio_rows(rows)
