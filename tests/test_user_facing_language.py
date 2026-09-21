"""No user-facing string mentions the plumbing (Task 01 §4.2, §7).

> *"No user-facing string anywhere in the codebase mentions tokens, quota,
> rate limits, or API credits."*

"Anywhere in the codebase" cannot be a literal grep: `max_tokens` is a
parameter name on every model call, `prompt_tokens` is the vendor's own field,
and `app/model_budget.py` is *about* the token ledger and has to be. A grep
that flagged those would be turned off within a day, and a turned-off check
proves nothing.

So this scans the **sinks** instead - the places a string becomes something a
person reads - and holds three lines:

1. Every string literal handed to a user-facing sink in `app/`, `backend/` and
   `gateway/` is clean. Found by walking the AST, so a rename of the handler
   does not hide it.
2. The four handlers `docs/CALL_SITES.md` §6 identified go through
   `app/user_messages.py` rather than assembling their own sentence.
3. Behaviourally: a `BudgetExceededError` pushed through each surface produces
   a clean string. That is the one that actually caught the original fault, and
   the one that would catch it coming back through a fifth handler nobody
   listed.
"""

import ast
from pathlib import Path

import pytest

from app import user_messages

REPO = Path(__file__).resolve().parent.parent
PACKAGES = ("app", "backend", "gateway", "agents")

# Modules whose *own* vocabulary is the accounting. They are operator-facing by
# construction and their strings never reach a user - the handlers in §2 below
# are what guarantee that, which is why this exemption is safe rather than a
# hole. `user_messages.py` is here because it holds the forbidden list itself.
_OPERATOR_MODULES = {
    "app/model_budget.py",       # the ledger. Its sentence is addressed to Krish.
    "app/model_routing.py",      # routing failures, logged and never shown
    "app/kimi_provider.py",      # HTTP statuses and vendor bodies
    "app/user_messages.py",      # the list of forbidden words lives here
    "app/self_diagnosis.py",     # the nightly report, an operator document
    "app/model_calls.py",        # the call log's field names
    "app/router_config.py",      # policy validation messages
}


def _python_files():
    for package in PACKAGES:
        for path in sorted((REPO / package).rglob("*.py")):
            relative = path.relative_to(REPO).as_posix()
            if relative in _OPERATOR_MODULES:
                continue
            yield relative, path


# --- 1. every literal that reaches a user-facing sink ----------------------------


def _user_facing_literals(tree: ast.AST):
    """String literals that become something a person reads.

    Three shapes, which are the three this codebase actually uses: an
    `HTTPException(detail=...)`, a dict with an `"error"` or `"answer"` key,
    and anything passed to `websocket.send_json`."""
    found = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "HTTPException":
                for keyword in node.keywords:
                    if keyword.arg == "detail" and isinstance(keyword.value, ast.Constant) \
                            and isinstance(keyword.value.value, str):
                        found.append((node.lineno, keyword.value.value))
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and key.value in ("error", "answer")):
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.append((node.lineno, value.value))
                elif isinstance(value, ast.JoinedStr):
                    for part in value.values:
                        if isinstance(part, ast.Constant) and isinstance(part.value, str):
                            found.append((node.lineno, part.value))
    return found


def test_no_user_facing_literal_mentions_the_plumbing():
    offences = []
    for relative, path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, literal in _user_facing_literals(tree):
            if not user_messages.is_clean(literal):
                offences.append(f"{relative}:{line}: {literal!r}")
    assert offences == [], (
        "a string a user reads mentions the model plumbing:\n  "
        + "\n  ".join(offences))


def _visible_text(html: str) -> str:
    """What a person actually reads on the page.

    Scripts and styles are stripped first, and that is not a convenience: both
    pages hold the session bearer token in JavaScript, so `token` appears
    dozens of times as a variable name. Checking the raw file would fail on
    identifiers nobody sees and would be switched off - which is how a check
    that matters stops running."""
    import re

    without_code = re.sub(r"<(script|style)\b.*?</\1>", " ", html,
                          flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"<[^>]+>", " ", without_code)


def test_the_page_the_user_looks_at_says_nothing_about_it():
    for path in sorted((REPO / "gateway" / "static").glob("*.html")):
        visible = _visible_text(path.read_text(encoding="utf-8"))
        assert user_messages.is_clean(visible), path.name


def test_the_assistants_own_vocabulary_is_clean():
    for category, message in user_messages.MESSAGES.items():
        assert user_messages.is_clean(message), category


# --- 2. the four handlers go through the vocabulary ---------------------------------


@pytest.mark.parametrize("relative, marker", [
    ("gateway/main.py", 'user_messages.for_user(exc)'),
    ("backend/main.py", 'user_messages.for_user(exc)'),
    ("backend/coo_chat.py", 'user_messages.for_user(exc)'),
])
def test_each_leaking_handler_now_speaks_the_assistants_vocabulary(relative, marker):
    """The four sites `docs/CALL_SITES.md` §6 found. A handler that went back
    to `str(exc)` would fail here before anybody saw it on a screen."""
    text = (REPO / relative).read_text(encoding="utf-8")
    assert marker in text


# The handlers a model exception can actually reach, from docs/CALL_SITES.md §6.
# Declared by name rather than by file, because `backend/main.py` also holds
# desk handlers that report their own failures to an operator console - those
# are outside this task's scope (§8) and are recorded in the PR description
# rather than changed here.
MODEL_PATH_HANDLERS = {
    ("gateway/main.py", "conversation_socket"),
    ("backend/main.py", "chat"),
    ("backend/coo_chat.py", "answer"),
    ("backend/coo_chat.py", "stream_answer"),
}


def test_no_model_path_handler_puts_a_raw_exception_on_a_user_facing_wire():
    """The *shape* of the original fault, independent of its wording.

    `f"...{exc}"` inside a dict under an "error" or "detail" key is how any
    future exception reaches a user - including ones that do not exist yet and
    therefore cannot be word-matched."""
    offences = []
    for relative, handler in sorted(MODEL_PATH_HANDLERS):
        tree = ast.parse((REPO / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != handler:
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Dict):
                    continue
                for key, value in zip(inner.keys, inner.values):
                    if not (isinstance(key, ast.Constant)
                            and key.value in ("error", "detail")):
                        continue
                    if not isinstance(value, ast.JoinedStr):
                        continue
                    for part in value.values:
                        if isinstance(part, ast.FormattedValue) and _names_an_exception(part):
                            offences.append(f"{relative}:{handler}:{inner.lineno}")
    assert offences == [], (
        "an exception's own text is being sent to a user; use "
        "app.user_messages.for_user instead:\n  " + "\n  ".join(offences))


def test_every_declared_handler_still_exists_under_that_name():
    """A rename must not quietly empty the check above."""
    for relative, handler in sorted(MODEL_PATH_HANDLERS):
        tree = ast.parse((REPO / relative).read_text(encoding="utf-8"))
        names = {node.name for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert handler in names, f"{relative} no longer defines {handler}()"


def test_no_other_module_both_reaches_a_model_and_reports_to_a_user():
    """A fifth leaking handler would have to appear in a fifth file, and this
    is what notices.

    Four of them existed because each service reported model failures in its
    own way and nobody had the list. The list is `MODEL_PATH_HANDLERS`; this
    asserts nothing else has joined it unnoticed."""
    declared_files = {relative for relative, _ in MODEL_PATH_HANDLERS}
    found = set()
    for relative, path in _python_files():
        if relative in ("app/model_gateway.py", "gateway/conversation.py"):
            continue  # the funnel itself, and the turn loop, report nothing
        text = path.read_text(encoding="utf-8")
        reaches_model = ("call_reasoning_model(" in text or "default_provider()" in text)
        reports_to_user = ('"error"' in text or "HTTPException(" in text)
        if reaches_model and reports_to_user:
            found.add(relative)

    assert found == declared_files, (
        f"a module reaches a model and reports to a user without being "
        f"declared in MODEL_PATH_HANDLERS: {sorted(found - declared_files)}")


def _names_an_exception(node: ast.FormattedValue) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id in ("exc", "error", "bad", "e"):
            return True
    return False


# --- 3. behaviourally, through each surface -----------------------------------------


def _exhausted():
    from app.model_budget import BudgetExceededError

    return BudgetExceededError(
        "Daily model token budget exhausted: 512334 tokens recorded today "
        "(limit 500000). Raise MODEL_BUDGET_DAILY_TOKENS deliberately if this "
        "spend is intended.")


def test_the_exact_sentence_krish_saw_is_not_clean_by_this_standard():
    """The control. If this passed, the check would be measuring nothing."""
    assert not user_messages.is_clean(str(_exhausted()))


def test_the_backend_chat_turns_it_into_something_he_can_read(backend_client, monkeypatch):
    from unittest.mock import MagicMock

    token = backend_client.post(
        "/auth/register", json={"username": "ada", "password": "hunter2"}
    ).json()["token"]
    monkeypatch.setattr("backend.main.call_reasoning_model",
                        MagicMock(side_effect=_exhausted()))

    response = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {token}"})

    assert user_messages.is_clean(response.json()["detail"])


def test_the_operator_console_turns_it_into_something_he_can_read(conn):
    from backend import coo_chat

    class _Failing:
        def complete(self, *args, **kwargs):
            raise _exhausted()

        def stream(self, *args, **kwargs):
            raise _exhausted()

    result = coo_chat.answer(conn, "what is happening?", provider=_Failing())
    assert user_messages.is_clean(result["error"])

    system, messages = coo_chat.prepare(conn, "what is happening?")
    events = list(coo_chat.stream_answer(system, messages, provider=_Failing()))
    assert user_messages.is_clean(events[-1]["error"])


def test_the_operator_still_gets_the_number():
    """Nothing was deleted. The accounting is re-addressed, not suppressed -
    a check that made the failure invisible to Krish would have replaced one
    bug with a worse one."""
    operator = user_messages.for_operator(_exhausted())
    assert "512334" in operator
    assert "MODEL_BUDGET_DAILY_TOKENS" in operator
