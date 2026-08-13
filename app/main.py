"""My AI - Milestone 1/2/3 CLI.

Interactive loop: `grant <resource>` / `revoke <resource>` / `show
preferences` / `reset preference <key>` / `logout` are handled directly
(permission and disposition intent are not parsed from freeform text -
deliberately out of scope, see the milestone plans). Everything else is
routed through the tool-use loop, where the model decides if/when it needs a
tool, and the tool itself enforces layer-1 permission. If the tool reports
that a layer-2 forwarding disposition is still needed, this loop pauses
*before* telling the model anything, asks the user directly, stores the
answer, and only then continues - the model never participates in the
consent negotiation.

Milestone 3 adds a login/register step before any of the above: every
resource is now scoped to the authenticated user (see users.py/session.py),
so two accounts never share permission, preference, or audit state even
though they may read the same underlying demo file.
"""

import getpass
import json

from .audit import AuditLog
from .model_gateway import call_reasoning_model
from .permissions import RESOURCE_PATHS, PermissionManager
from .privacy_preferences import PrivacyPreferenceStore
from .session import SessionStore
from .tools import TOOLS, execute_tool
from .users import UserStore, ensure_user_data_dir, normalize_username

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


def handle_auth(users: UserStore, sessions: SessionStore) -> str:
    username = sessions.validate()
    if username is not None:
        print(f"Welcome back, {username}.")
        return username

    try:
        while True:
            choice = input("[My AI] Login or register? [login/register] > ").strip().lower()
            if choice == "register":
                reg_username = input("Choose a username: ").strip()
                password = getpass.getpass("Choose a password: ")
                confirm = getpass.getpass("Confirm password: ")
                if password != confirm:
                    print("Passwords did not match, please try again.")
                    continue
                try:
                    normalized = users.register(reg_username, password)
                except ValueError as e:
                    print(f"Could not register: {e}")
                    continue
                sessions.create(normalized)
                print(f"Registered and logged in as {normalized}.")
                return normalized
            if choice == "login":
                login_username = input("Username: ").strip()
                password = getpass.getpass("Password: ")
                if not users.authenticate(login_username, password):
                    print("Invalid username or password.")
                    continue
                normalized = normalize_username(login_username)
                sessions.create(normalized)
                print(f"Logged in as {normalized}.")
                return normalized
            print("Please answer 'login' or 'register'.")
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)


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


def chat_turn(
    user_input: str,
    messages: list,
    permissions: PermissionManager,
    preferences: PrivacyPreferenceStore,
    audit_log: AuditLog,
    resolve_consent_fn=resolve_consent,
) -> str:
    """Runs one turn of the tool-use loop and returns the model's final reply
    text (the caller decides how to display it - printed by the CLI,
    inserted into a widget by the desktop GUI). resolve_consent_fn is
    injectable so a GUI can swap in a thread-safe dialog instead of the real
    input() builtin; it defaults to the CLI's real resolve_consent."""
    messages.append({"role": "user", "content": user_input})

    while True:
        response = call_reasoning_model(SYSTEM_PROMPT, messages, TOOLS)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = execute_tool(block.name, permissions, preferences, audit_log)
            if result.get("status") == "needs_consent":
                answer = resolve_consent_fn(result, preferences)
                result = execute_tool(
                    block.name, permissions, preferences, audit_log, allow_once=(answer == "once")
                )
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
    users = UserStore()
    sessions = SessionStore()
    username = handle_auth(users, sessions)

    user_dir = ensure_user_data_dir(username)
    permissions = PermissionManager(path=user_dir / "permissions.json")
    preferences = PrivacyPreferenceStore(path=user_dir / "privacy_preferences.json")
    audit_log = AuditLog(path=user_dir / "audit_log.jsonl")
    messages: list = []
    print(f"My AI (Milestone 3). Logged in as {username}. Commands: 'grant portfolio', "
          "'revoke portfolio', 'show preferences', 'reset preference <key>', 'logout', "
          "or ask a question. Ctrl+C to quit.")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input == "logout":
            sessions.revoke()
            print("Logged out.")
            break
        if handle_grant_revoke(user_input, permissions):
            continue
        if handle_preference_commands(user_input, preferences):
            continue
        print(chat_turn(user_input, messages, permissions, preferences, audit_log))


if __name__ == "__main__":
    main()
