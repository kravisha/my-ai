"""retrieve_portfolio: the one action `/chat` exposes to the model — now with an
owner (TASK_QUEUE TQ-46, addendum 44 §16.7).

## What changed, and what deliberately did not

This function used to take a permission manager, a preference store and an audit
log, and **no owner**. It read `data/portfolio.xlsx` and returned whatever was in
it. Addendum 44 §16.7 says to remove *"any global get_current_portfolio()
behavior that has no owner argument"*, and that sentence was written about this
function.

**The ownerlessness is gone; the tool is not.** TQ-46 §11 Q1 measured the
alternative before choosing it: `app/tools.TOOLS` has exactly one entry, so
retiring this would take `/chat` to zero tools — and it is the only consumer of
the consent subsystem, so the pause-and-resume flow in `backend/main.py`,
`PrivacyPreferenceStore`'s dispositions, the CLI prompts and the desktop's
handling of them would all have been left with nothing exercising them. A working
privacy guarantee whose *absence* nobody would notice is not one to delete as a
side effect of an ownership fix.

So it keeps its two layers, and gains a third fact it never had: whose portfolio.

  Layer 1 (`permissions.py`) — may My AI reach this account's portfolio at all.
  Layer 2 (`privacy_preferences.py`) — may those holdings be forwarded to the
    reasoning model. With no stored disposition this returns `needs_consent`
    rather than data or a denial, and `/chat` pauses and asks.
  **The owner** (`backend/superuser_portfolio.py`) — the holdings come from the
    caller's own `SUPERUSER` portfolio, through `portfolios.resolve`.

## Layer 2 is the only control, and that was measured rather than assumed

TQ-46 §11 Q2 asked whether the consent flow is redundant now that §108 refuses a
`LOCAL_ONLY` task rather than forwarding it. It is not, and the check inverted the
expectation: `PORTFOLIO_FIELD_CLASSES` marks only `account_id` as `LOCAL_ONLY`,
and that field is not carried into the migrated holdings **at all**. The rows that
reach a model therefore contain no `LOCAL_ONLY` field, `privacy_floor_for()`
returns `None`, and `PATH_REFUSED` never fires.

**This prompt is the whole guarantee.** Removing it as duplicated would have left
nothing.

## The spreadsheet is legacy and is not read here

`data/portfolio.xlsx` stays on disk and is read by exactly one thing:
`superuser_portfolio.migrate_spreadsheet`, once (§16.1's habit, matching
`client_holdings_legacy` and `portfolio_holdings_pre45`). No runtime path opens
it. `test_no_runtime_path_reads_the_legacy_spreadsheet` is what keeps that true.
"""

from ..audit import AuditLog
from ..permissions import PermissionManager
from ..privacy_preferences import PrivacyPreferenceStore

RESOURCE = "portfolio"
FORWARDING_KEY = "portfolio_holdings:reasoning_model"
CONSENT_PROMPT = (
    "I need to share your portfolio holdings (symbol, quantity, average cost, "
    "acquisition date) with the reasoning model to answer this. Allow this?"
)


def retrieve_portfolio(
    conn,
    username: str,
    permissions: PermissionManager,
    preferences: PrivacyPreferenceStore,
    audit_log: AuditLog,
    allow_once: bool = False,
) -> dict:
    """This account's own Superuser Portfolio holdings.

    `username` is required and comes from `Depends(get_current_user)` — the value
    `/chat` was already resolving and handing nowhere near this function (TQ-69
    spec §3). §16.7's "ownerless retrieval" was never a missing identity
    mechanism; it was one being discarded.

    There is no argument here that could name somebody else's portfolio. The
    owner is the caller, always, so "read another account's holdings" is not a
    call the model can construct — the same property `gateway/tools.py` has for
    clients, arriving on the other side of the boundary."""
    from backend import superuser_portfolio

    if not permissions.is_granted(RESOURCE):
        audit_log.record(
            action="retrieve_portfolio",
            resource=RESOURCE,
            authorized=False,
            result="denied - permission not granted",
        )
        return {"error": "Permission to access the portfolio has been revoked or was never granted."}

    disposition = preferences.get(FORWARDING_KEY)
    if disposition is None and not allow_once:
        return {"status": "needs_consent", "consent_key": FORWARDING_KEY, "prompt": CONSENT_PROMPT}

    if disposition == "never":
        audit_log.record(
            action="retrieve_portfolio",
            resource=RESOURCE,
            authorized=False,
            result="denied - forwarding disposition is 'never'",
        )
        return {"error": "You've asked me not to share portfolio data with the reasoning model."}

    try:
        held = superuser_portfolio.holdings_for(
            conn, username, superuser_portfolio.granted_for(permissions))
    except superuser_portfolio.NotPermitted as refusal:
        # The module's own fail-closed guard, reached only if layer 1 and this
        # ever disagree. Recorded rather than swallowed: the two are supposed to
        # come from the same grant, so a disagreement is a fact worth having in
        # the audit log.
        audit_log.record(
            action="retrieve_portfolio",
            resource=RESOURCE,
            authorized=False,
            result=f"denied - {refusal}",
        )
        return {"error": str(refusal)}

    audit_log.record(
        action="retrieve_portfolio",
        resource=RESOURCE,
        authorized=True,
        result=(f"returned {len(held)} holdings"
                + (" (one-time consent, not persisted)" if disposition is None else "")),
    )
    return {"holdings": held}
