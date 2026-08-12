"""My AI - Milestone 1/2 CLI.

Interactive loop: `grant <resource>` / `revoke <resource>` / `show
preferences` / `reset preference <key>` are handled directly (permission and
disposition intent are not parsed from freeform text - deliberately out of
scope, see the milestone plans). Everything else is routed through the
tool-use loop, where the model decides if/when it needs a tool, and the tool
itself enforces layer-1 permission. If the tool reports that a layer-2
forwarding disposition is still needed, this loop pauses *before* telling
the model anything, asks the user directly, stores the answer, and only
then continues - the model never participates in the consent negotiation.
"""

import json

from .model_gateway import call_reasoning_model
from .permissions import RESOURCE_PATHS, PermissionManager
from .privacy_preferences import PrivacyPreferenceStore
from .tools import TOOLS, execute_tool

SYSTEM_PROMPT = (
    "You are My AI, a personal assistant with access to the user's local data "
    "only through explicit, revocable permissions. You have a retrieve_portfolio "
    "tool for the user's investment holdings. Permissions can change at any time "
    "during the conversation, so you MUST call retrieve_portfolio fresh for every "
    "question about the portfolio, even if you already retrieved it earlier in "
    "this conversation - never answer a portfolio question from memory of an "
    "earlier tool result. If a tool call is denied, the tool result's 'error' "
    "field explains exactly why - relay that specific reason to the user in "
    "your own words, do not assume it means permission was revoked unless the "
    "error text actually says so. There are two distinct kinds of denial: the "
    "resource permission being revoked/not granted, and the user having said "
    "'never' to sharing this data with you specifically - these are different "
    "and must not be described the same way. Do not guess or fabricate data. "
    "You never have access to the user's account ID - if asked, say so plainly "
    "rather than inventing one."
)


def handle_grant_revoke(command: str, permissions: PermissionManager) -> bool:
    parts = command.strip().split()
    if len(parts) != 2 or parts[0] not in ("grant", "revoke"):
        return False
    action, resource = parts
    if resource not in RESOURCE_PATHS:
        print(f"Unknown resource: {resource}")
        return True
    if action == "grant":
        permissions.grant(resource)
        print(f"Granted: {resource} ({RESOURCE_PATHS[resource]})")
    else:
        permissions.revoke(resource)
        print(f"Revoked: {resource}")
    return True


def handle_preference_commands(command: str, preferences: PrivacyPreferenceStore) -> bool:
    stripped = command.strip()
    if stripped == "show preferences":
        entries = preferences.list_all()
        if not entries:
            print("No privacy preferences set yet.")
        for key, entry in entries.items():
            print(f"{key}: {entry['disposition']} (set {entry['set_at']})")
        return True

    parts = stripped.split(maxsplit=2)
    if len(parts) == 3 and parts[0] == "reset" and parts[1] == "preference":
        key = parts[2]
        if preferences.forget(key):
            print(f"Forgot preference: {key}")
        else:
            print(f"No preference stored for: {key}")
        return True

    return False


def resolve_consent(result: dict, preferences: PrivacyPreferenceStore) -> str:
    print(f"[My AI] {result['prompt']}")
    while True:
        answer = input("[always/once/never] > ").strip().lower()
        if answer in ("always", "never"):
            preferences.set(result["consent_key"], answer)
            print(f"Recorded: {result['consent_key']} = {answer}")
            return answer
        if answer == "once":
            print("Allowing once - I'll ask again next time.")
            return answer
        print("Please answer 'always', 'once', or 'never'.")


def chat_turn(user_input: str, messages: list, permissions: PermissionManager, preferences: PrivacyPreferenceStore) -> None:
    messages.append({"role": "user", "content": user_input})

    while True:
        response = call_reasoning_model(SYSTEM_PROMPT, messages, TOOLS)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            print(text)
            return

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = execute_tool(block.name, permissions, preferences)
            if result.get("status") == "needs_consent":
                answer = resolve_consent(result, preferences)
                result = execute_tool(block.name, permissions, preferences, allow_once=(answer == "once"))
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                    "is_error": "error" in result,
                }
            )
        messages.append({"role": "user", "content": tool_results})


def main() -> None:
    permissions = PermissionManager()
    preferences = PrivacyPreferenceStore()
    messages: list = []
    print("My AI (Milestone 2). Commands: 'grant portfolio', 'revoke portfolio', "
          "'show preferences', 'reset preference <key>', or ask a question. Ctrl+C to quit.")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if handle_grant_revoke(user_input, permissions):
            continue
        if handle_preference_commands(user_input, preferences):
            continue
        chat_turn(user_input, messages, permissions, preferences)


if __name__ == "__main__":
    main()
