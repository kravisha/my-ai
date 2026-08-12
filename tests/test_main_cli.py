from app.main import handle_grant_revoke, handle_preference_commands, resolve_consent
from app.tools.portfolio import FORWARDING_KEY


def test_grant_command_grants_and_is_handled(permissions_store, capsys):
    handled = handle_grant_revoke("grant portfolio", permissions_store)
    assert handled is True
    assert permissions_store.is_granted("portfolio") is True
    assert "Granted" in capsys.readouterr().out


def test_revoke_command_revokes_and_is_handled(permissions_store, capsys):
    permissions_store.grant("portfolio")
    handled = handle_grant_revoke("revoke portfolio", permissions_store)
    assert handled is True
    assert permissions_store.is_granted("portfolio") is False
    assert "Revoked" in capsys.readouterr().out


def test_grant_unknown_resource_is_handled_without_granting(permissions_store, capsys):
    handled = handle_grant_revoke("grant not_a_resource", permissions_store)
    assert handled is True
    assert "Unknown resource" in capsys.readouterr().out


def test_ordinary_question_is_not_handled_as_grant_revoke(permissions_store):
    assert handle_grant_revoke("What stocks do I own?", permissions_store) is False


def test_show_preferences_empty(preferences_store, capsys):
    handled = handle_preference_commands("show preferences", preferences_store)
    assert handled is True
    assert "No privacy preferences" in capsys.readouterr().out


def test_show_preferences_lists_entries(preferences_store, capsys):
    preferences_store.set(FORWARDING_KEY, "always")
    handle_preference_commands("show preferences", preferences_store)
    out = capsys.readouterr().out
    assert FORWARDING_KEY in out
    assert "always" in out


def test_reset_preference_found(preferences_store, capsys):
    preferences_store.set(FORWARDING_KEY, "always")
    handled = handle_preference_commands(f"reset preference {FORWARDING_KEY}", preferences_store)
    assert handled is True
    assert preferences_store.get(FORWARDING_KEY) is None
    assert "Forgot preference" in capsys.readouterr().out


def test_reset_preference_not_found(preferences_store, capsys):
    handled = handle_preference_commands("reset preference nonexistent_key", preferences_store)
    assert handled is True
    assert "No preference stored" in capsys.readouterr().out


def test_ordinary_question_is_not_handled_as_preference_command(preferences_store):
    assert handle_preference_commands("What stocks do I own?", preferences_store) is False


def test_resolve_consent_always_persists_disposition(preferences_store, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "always")
    result = {"prompt": "Share holdings?", "consent_key": FORWARDING_KEY}

    answer = resolve_consent(result, preferences_store)

    assert answer == "always"
    assert preferences_store.get(FORWARDING_KEY) == "always"
    assert "Recorded" in capsys.readouterr().out


def test_resolve_consent_never_persists_disposition(preferences_store, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "never")
    result = {"prompt": "Share holdings?", "consent_key": FORWARDING_KEY}

    answer = resolve_consent(result, preferences_store)

    assert answer == "never"
    assert preferences_store.get(FORWARDING_KEY) == "never"


def test_resolve_consent_once_does_not_persist(preferences_store, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "once")
    result = {"prompt": "Share holdings?", "consent_key": FORWARDING_KEY}

    answer = resolve_consent(result, preferences_store)

    assert answer == "once"
    assert preferences_store.get(FORWARDING_KEY) is None


def test_resolve_consent_reprompts_on_invalid_answer(preferences_store, monkeypatch):
    answers = iter(["maybe", "always"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    result = {"prompt": "Share holdings?", "consent_key": FORWARDING_KEY}

    resolve_consent(result, preferences_store)

    assert preferences_store.get(FORWARDING_KEY) == "always"
