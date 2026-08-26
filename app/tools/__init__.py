"""Tool schema list + dispatcher, same shape as vibe-agent's backend/tools.py
and cinema's app/assistant.py tool wiring.

`execute_tool` takes a connection and a username since TQ-46: the one tool here
reads an **owned** portfolio now, and an owner that is optional is an owner
somebody forgets to pass. Both are required arguments for the same reason
`portfolios.resolve` refuses a bare string — a signature is where this kind of
mistake is cheapest to prevent.
"""

from ..audit import AuditLog
from ..permissions import PermissionManager
from ..privacy_preferences import PrivacyPreferenceStore
from .portfolio import retrieve_portfolio

TOOLS = [
    {
        "name": "retrieve_portfolio",
        "description": (
            "Retrieve this user's own Superuser Portfolio holdings (symbol, "
            "quantity, average cost, acquisition date). Requires that the user has "
            "granted permission to the 'portfolio' resource; if not granted, returns "
            "a denial explaining that access is not authorized. It reports no market "
            "value, gain or loss, because this system has no real market prices."
        ),
        "input_schema": {"type": "object", "properties": {}},
    }
]


def execute_tool(
    name: str,
    conn,
    username: str,
    permissions: PermissionManager,
    preferences: PrivacyPreferenceStore,
    audit_log: AuditLog,
    allow_once: bool = False,
) -> dict:
    if name == "retrieve_portfolio":
        return retrieve_portfolio(
            conn, username, permissions, preferences, audit_log, allow_once=allow_once)
    raise ValueError(f"Unknown tool: {name}")
