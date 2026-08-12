"""Tool schema list + dispatcher, same shape as vibe-agent's backend/tools.py
and cinema's app/assistant.py tool wiring."""

from ..permissions import PermissionManager
from ..privacy_preferences import PrivacyPreferenceStore
from .portfolio import retrieve_portfolio

TOOLS = [
    {
        "name": "retrieve_portfolio",
        "description": (
            "Retrieve the user's investment portfolio holdings (ticker, shares, "
            "purchase price, purchase date). Requires that the user has granted "
            "permission to the 'portfolio' resource; if not granted, returns a "
            "denial explaining that access is not authorized."
        ),
        "input_schema": {"type": "object", "properties": {}},
    }
]


def execute_tool(name: str, permissions: PermissionManager, preferences: PrivacyPreferenceStore) -> dict:
    if name == "retrieve_portfolio":
        return retrieve_portfolio(permissions, preferences)
    raise ValueError(f"Unknown tool: {name}")
