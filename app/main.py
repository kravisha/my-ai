"""My AI - CLI, now a thin HTTP client (Milestone 4: client-server split).

All business logic (permissions, preferences, audit, the tool-use loop)
moved to backend/main.py - this module only handles terminal I/O and talks
to it via api_client.APIClient, the same shape desktop/ uses. SYSTEM_PROMPT
stays here since backend/main.py imports it from this module - the actual
prompt text belongs with the rest of My AI's "personality," not the HTTP
plumbing.

Consent prompts (always/once/never) still show up exactly as before -
they're just driven by the `needs_consent` field in a /chat response now,
answered here via input(), then resolved with a follow-up /chat call
instead of a local pause.
"""

import getpass
from pathlib import Path

from api_client import APIClient, APIError
from app.users import normalize_username

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

CLI_SESSION_PATH = Path(__file__).resolve().parent.parent / ".cli_session"


def _load_cached_token() -> str | None:
    if not CLI_SESSION_PATH.exists():
        return None
    token = CLI_SESSION_PATH.read_text(encoding="utf-8").strip()
    return token or None


def _save_token(token: str) -> None:
    CLI_SESSION_PATH.write_text(token, encoding="utf-8")


def _clear_cached_token() -> None:
    CLI_SESSION_PATH.unlink(missing_ok=True)


def handle_auth(client: APIClient) -> str:
    cached_token = _load_cached_token()
    if cached_token is not None:
        client.token = cached_token
        try:
            username = client.me()
            print(f"Welcome back, {username}.")
            return username
        except APIError:
            client.token = None
            _clear_cached_token()

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
                    client.register(reg_username, password)
                except APIError as e:
                    print(f"Could not register: {e}")
                    continue
                _save_token(client.token)
                normalized = normalize_username(reg_username)
                print(f"Registered and logged in as {normalized}.")
                return normalized
            if choice == "login":
                login_username = input("Username: ").strip()
                password = getpass.getpass("Password: ")
                try:
                    client.login(login_username, password)
                except APIError:
                    print("Invalid username or password.")
                    continue
                _save_token(client.token)
                normalized = normalize_username(login_username)
                print(f"Logged in as {normalized}.")
                return normalized
            print("Please answer 'login' or 'register'.")
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)


def handle_grant_revoke(command: str, client: APIClient) -> bool:
    parts = command.strip().split()
    if len(parts) != 2 or parts[0] not in ("grant", "revoke"):
        return False
    action, resource = parts
    try:
        if action == "grant":
            client.grant(resource)
            print(f"Granted: {resource}")
        else:
            client.revoke(resource)
            print(f"Revoked: {resource}")
    except APIError as e:
        print(f"Error: {e}")
    return True


def handle_preference_commands(command: str, client: APIClient) -> bool:
    stripped = command.strip()
    if stripped == "show preferences":
        entries = client.list_preferences()
        if not entries:
            print("No privacy preferences set yet.")
        for key, entry in entries.items():
            print(f"{key}: {entry['disposition']} (set {entry['set_at']})")
        return True

    parts = stripped.split(maxsplit=2)
    if len(parts) == 3 and parts[0] == "reset" and parts[1] == "preference":
        key = parts[2]
        if client.reset_preference(key):
            print(f"Forgot preference: {key}")
        else:
            print(f"No preference stored for: {key}")
        return True

    return False


def send_chat_message(client: APIClient, messages: list, user_input: str) -> str:
    """Sends user_input (appending it to the shared `messages` list first),
    resolving any consent pause(s) via input() before returning the model's
    final reply. `messages` is mutated in place to stay in sync with
    whatever the server considers the conversation's current state - the
    server is stateless, so its response is always the source of truth."""
    messages.append({"role": "user", "content": user_input})
    body = client.chat(messages)

    while "needs_consent" in body:
        messages[:] = body["messages"]
        prompt = body["needs_consent"]["prompt"]
        consent_key = body["needs_consent"]["consent_key"]
        print(f"[My AI] {prompt}")
        answer = ""
        while answer not in ("always", "once", "never"):
            answer = input("[always/once/never] > ").strip().lower()
            if answer not in ("always", "once", "never"):
                print("Please answer 'always', 'once', or 'never'.")
        if answer == "once":
            print("Allowing once - I'll ask again next time.")
        else:
            print(f"Recorded: {consent_key} = {answer}")
        body = client.chat(messages, consent_answer=answer, consent_key=consent_key)

    messages[:] = body["messages"]
    return body["reply"]


def main() -> None:
    client = APIClient()
    username = handle_auth(client)

    messages: list = []
    print(f"My AI (Milestone 4). Logged in as {username}. Commands: 'grant portfolio', "
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
            client.logout()
            _clear_cached_token()
            print("Logged out.")
            break
        if handle_grant_revoke(user_input, client):
            continue
        if handle_preference_commands(user_input, client):
            continue
        try:
            print(send_chat_message(client, messages, user_input))
        except APIError as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
