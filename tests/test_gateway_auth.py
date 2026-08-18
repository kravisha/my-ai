"""Who the Super User is, and the default-closed rule.

The gate itself is asserted here against the real environment variables, rather
than only through the login route with a fixture that has already configured
them - which is the arrangement that lets an auth check rot unnoticed.
"""

import pytest
from conftest import GATEWAY_TEST_PASSWORD, GATEWAY_TEST_PASSWORD_HASH, GATEWAY_TEST_USER

from gateway import auth


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.delenv(auth.SUPER_USER_ENV, raising=False)
    monkeypatch.delenv(auth.PASSWORD_HASH_ENV, raising=False)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(auth.SUPER_USER_ENV, GATEWAY_TEST_USER)
    monkeypatch.setenv(auth.PASSWORD_HASH_ENV, GATEWAY_TEST_PASSWORD_HASH)


def test_an_unconfigured_gateway_admits_nobody(unconfigured):
    """The rule app/admin_auth.py established: unset means refused, not open. An
    auth feature that defaults open is worse than none because it looks
    protected."""
    assert auth.is_configured() is False
    assert auth.verify(GATEWAY_TEST_USER, GATEWAY_TEST_PASSWORD) is False


def test_half_a_credential_is_not_a_configuration(monkeypatch):
    """A username with no hash would otherwise mean 'any password', which is the
    single worst failure this module could have."""
    monkeypatch.setenv(auth.SUPER_USER_ENV, GATEWAY_TEST_USER)
    monkeypatch.delenv(auth.PASSWORD_HASH_ENV, raising=False)

    assert auth.is_configured() is False
    assert auth.verify(GATEWAY_TEST_USER, "anything at all") is False


def test_the_right_credential_verifies(configured):
    assert auth.is_configured() is True
    assert auth.verify(GATEWAY_TEST_USER, GATEWAY_TEST_PASSWORD) is True


def test_the_wrong_password_does_not(configured):
    assert auth.verify(GATEWAY_TEST_USER, GATEWAY_TEST_PASSWORD + "!") is False


def test_another_username_does_not(configured):
    assert auth.verify("someone-else", GATEWAY_TEST_PASSWORD) is False


def test_the_username_is_case_and_space_insensitive(configured):
    """Matches app/admin_auth.py's handling, so a phone keyboard capitalising the
    first letter is not a lockout."""
    assert auth.verify(f"  {GATEWAY_TEST_USER.upper()} ", GATEWAY_TEST_PASSWORD) is True


def test_a_whitespace_only_variable_counts_as_unset(monkeypatch):
    """The shape a half-finished setup takes: the variable is exported, but with
    nothing in it. Treating that as configured would mean bcrypt comparing
    against an empty string, so it has to fail the same way an absent variable
    does."""
    monkeypatch.setenv(auth.SUPER_USER_ENV, GATEWAY_TEST_USER)
    monkeypatch.setenv(auth.PASSWORD_HASH_ENV, "   ")

    assert auth.is_configured() is False
    assert auth.verify(GATEWAY_TEST_USER, "") is False


def test_a_malformed_hash_refuses_rather_than_raising(monkeypatch):
    """A typo in the environment must not become a 500 with a stack trace on an
    externally reachable route."""
    monkeypatch.setenv(auth.SUPER_USER_ENV, GATEWAY_TEST_USER)
    monkeypatch.setenv(auth.PASSWORD_HASH_ENV, "not-a-bcrypt-hash")

    assert auth.verify(GATEWAY_TEST_USER, GATEWAY_TEST_PASSWORD) is False


def test_the_session_ttl_defaults_and_survives_nonsense(monkeypatch):
    monkeypatch.delenv(auth.SESSION_TTL_ENV, raising=False)
    assert auth.session_ttl_seconds() == auth.DEFAULT_SESSION_TTL_SECONDS

    monkeypatch.setenv(auth.SESSION_TTL_ENV, "600")
    assert auth.session_ttl_seconds() == 600

    for nonsense in ("banana", "0", "-5"):
        monkeypatch.setenv(auth.SESSION_TTL_ENV, nonsense)
        assert auth.session_ttl_seconds() == auth.DEFAULT_SESSION_TTL_SECONDS, (
            f"{nonsense!r} must fall back to the default rather than producing a "
            "session that expires immediately or never"
        )
