"""Server Superuser authentication and the login-gated workforce
(app/server_auth.py + backend/main.py; addendum 39 §3, addendum 38 §3;
TQ-25, SPEC_RECONCILIATION §74).

Three things held here. **Separation** (39 §3): the server credential is not
the Gateway's and not an ordinary application account — conflating them would
mean a phone-session compromise starts the workforce. **Fail-closed**: unset
means nobody logs in, and a plaintext credential is a PRE_ALPHA-only
convenience the code refuses to let outlive its stage. **The gate** (38 §3.3):
the workforce does not start before an operator authenticates, with automation
having an honest, recorded path rather than a silent bypass.
"""

import json

import bcrypt
import pytest

from app import server_auth
from backend import boot_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in (server_auth.SUPERUSER_ENV, server_auth.PASSWORD_HASH_ENV,
                server_auth.PASSWORD_PLAINTEXT_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv(boot_config.PATH_ENV, raising=False)


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _stage(monkeypatch, tmp_path, stage: str):
    """Point boot configuration at a config declaring `stage`."""
    data = {
        "lifecycle_stage": stage,
        "global_asset_classes": ["stock", "stock_option"],
        "implemented_asset_classes": ["stock", "stock_option"],
        "current_focus": ["X"],
        "simulation_focus": ["Y"],
    }
    path = tmp_path / "boot_config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(boot_config.PATH_ENV, str(path))


# --- unset means closed -----------------------------------------------------------


def test_unconfigured_refuses_everything():
    """An auth feature that defaults open is worse than none, because it
    looks protected."""
    assert server_auth.is_configured() is False
    assert server_auth.verify("anyone", "anything") is False
    assert server_auth.SUPERUSER_ENV in server_auth.configuration_problem()


def test_id_without_a_password_is_not_configured(monkeypatch):
    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "krish")
    assert server_auth.is_configured() is False
    assert server_auth.verify("krish", "") is False


# --- the hash path, which always works --------------------------------------------


def test_hash_credential_verifies(monkeypatch):
    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "krish")
    monkeypatch.setenv(server_auth.PASSWORD_HASH_ENV, _hash("correct horse"))
    assert server_auth.is_configured() is True
    assert server_auth.configuration_problem() is None
    assert server_auth.verify("krish", "correct horse") is True
    assert server_auth.verify("krish", "wrong") is False
    assert server_auth.verify("someone-else", "correct horse") is False


def test_username_comparison_is_case_insensitive(monkeypatch):
    """Matching app/admin_auth.py and gateway/auth.py."""
    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "Krish")
    monkeypatch.setenv(server_auth.PASSWORD_HASH_ENV, _hash("pw"))
    assert server_auth.verify("  KRISH ", "pw") is True


def test_malformed_hash_refuses_rather_than_raising(monkeypatch):
    """A typo in the variable must not become a 500 with a stack trace."""
    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "krish")
    monkeypatch.setenv(server_auth.PASSWORD_HASH_ENV, "not-a-bcrypt-hash")
    assert server_auth.verify("krish", "pw") is False


# --- plaintext is a PRE_ALPHA-only convenience ------------------------------------


def test_plaintext_works_at_pre_alpha_and_warns(monkeypatch, tmp_path, capsys):
    """Addendum 39 §3 names SERVER_SUPERUSER_PASSWORD; this repository refuses
    plaintext credentials in general. The resolution is that it works only
    while the stage that justified it is current — and says so every time."""
    _stage(monkeypatch, tmp_path, "PRE_ALPHA")
    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "krish")
    monkeypatch.setenv(server_auth.PASSWORD_PLAINTEXT_ENV, "dev-password")

    assert server_auth.is_configured() is True
    assert server_auth.verify("krish", "dev-password") is True
    assert "WARNING" in capsys.readouterr().out
    assert server_auth.verify("krish", "nope") is False


@pytest.mark.parametrize("stage", ["ALPHA", "BETA", "PRODUCTION"])
def test_plaintext_is_refused_past_pre_alpha(monkeypatch, tmp_path, stage):
    """The convenience cannot outlive the stage that justified it. This is
    also the lifecycle stage's first behavioral consumer — addendum 38 §2
    wanted a persisted stage precisely so components could alter behavior by
    it."""
    _stage(monkeypatch, tmp_path, stage)
    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "krish")
    monkeypatch.setenv(server_auth.PASSWORD_PLAINTEXT_ENV, "dev-password")

    assert server_auth.is_configured() is False
    assert server_auth.verify("krish", "dev-password") is False
    assert server_auth.PASSWORD_HASH_ENV in server_auth.configuration_problem()


def test_a_hash_still_works_past_pre_alpha(monkeypatch, tmp_path):
    _stage(monkeypatch, tmp_path, "PRODUCTION")
    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "krish")
    monkeypatch.setenv(server_auth.PASSWORD_HASH_ENV, _hash("pw"))
    assert server_auth.verify("krish", "pw") is True


def test_unreadable_boot_config_is_not_permission(monkeypatch, tmp_path):
    """Fail-closed: a broken configuration narrows what is accepted rather
    than widening it."""
    monkeypatch.setenv(boot_config.PATH_ENV, str(tmp_path / "absent.json"))
    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "krish")
    monkeypatch.setenv(server_auth.PASSWORD_PLAINTEXT_ENV, "dev-password")
    assert server_auth.verify("krish", "dev-password") is False


# --- separation from the other credentials ----------------------------------------


def test_server_credential_is_not_the_gateway_credential(monkeypatch, tmp_path):
    """39 §3: "Server authentication and Gateway authentication must not be
    accidentally conflated." Configuring one must not authenticate the
    other."""
    from gateway import auth as gateway_auth

    _stage(monkeypatch, tmp_path, "PRE_ALPHA")
    monkeypatch.setenv(gateway_auth.SUPER_USER_ENV, "gwuser")
    monkeypatch.setenv(gateway_auth.PASSWORD_HASH_ENV, _hash("gwpass"))
    monkeypatch.delenv(server_auth.SUPERUSER_ENV, raising=False)

    assert gateway_auth.verify("gwuser", "gwpass") is True
    assert server_auth.verify("gwuser", "gwpass") is False  # separate doors

    monkeypatch.setenv(server_auth.SUPERUSER_ENV, "srvuser")
    monkeypatch.setenv(server_auth.PASSWORD_HASH_ENV, _hash("srvpass"))
    assert server_auth.verify("srvuser", "srvpass") is True
    assert gateway_auth.verify("srvuser", "srvpass") is False


def test_env_variable_names_are_distinct():
    from gateway import auth as gateway_auth

    assert server_auth.SUPERUSER_ENV != gateway_auth.SUPER_USER_ENV
    assert server_auth.PASSWORD_HASH_ENV != gateway_auth.PASSWORD_HASH_ENV


# --- the gate (38 §3.3) -----------------------------------------------------------


def test_autostart_is_off_by_default(monkeypatch):
    """The whole point of TQ-25: absent a deliberate opt-in, the workforce
    waits for a human."""
    from backend import main as backend_main

    monkeypatch.delenv(backend_main.AUTOSTART_ENV, raising=False)
    assert backend_main.autostart_requested() is False


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("maybe", False),
])
def test_autostart_flag_parsing(monkeypatch, value, expected):
    from backend import main as backend_main

    monkeypatch.setenv(backend_main.AUTOSTART_ENV, value)
    assert backend_main.autostart_requested() is expected


def test_the_harness_starts_unattended_deliberately():
    """simulation/harness.py launches a real backend with no operator, so it
    must declare the unattended start rather than silently coming up with a
    dormant organization that looks like a mission finding nothing."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "simulation" / "harness.py").read_text(
        encoding="utf-8"
    )
    assert "SERVER_AUTOSTART_WORKFORCE" in source


def test_startup_sequence_is_extracted_from_lifespan():
    """`_operational_startup` exists so that *when* the sequence runs is a
    separate question from *what* it does — the change that let a login
    trigger it without altering the order of the sequence itself."""
    from backend import main as backend_main

    assert callable(backend_main._operational_startup)
    source = backend_main._operational_startup.__doc__ or ""
    assert "38 §5" in source or "startup sequence" in source
