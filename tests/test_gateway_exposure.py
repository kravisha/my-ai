"""What changes when the Gateway is reachable from the internet (addendum 16 §12).

Two properties carry the weight here, and both are the kind that look fine until
somebody actually tries them:

- a forged `X-Forwarded-For` must not let an attacker pick which rate-limit bucket
  they land in, and
- the WebSocket must not be an unlimited oracle sitting beside a limited door.
"""

import pytest
from conftest import GATEWAY_TEST_PASSWORD, GATEWAY_TEST_USER
from starlette.websockets import WebSocketDisconnect

from gateway import exposure


@pytest.fixture(autouse=True)
def clear_limiter():
    import gateway.main as gateway_main

    gateway_main.login_limiter.forget_everything()
    yield
    gateway_main.login_limiter.forget_everything()


# --- Whose address is it ---


def test_a_direct_caller_cannot_choose_its_own_address(monkeypatch):
    """The forgery case. `X-Forwarded-For` from someone who is not a declared
    proxy is a claim about themselves, and believing it would let an attacker
    rotate buckets by rotating a header."""
    monkeypatch.setenv(exposure.TRUSTED_PROXIES_ENV, "10.0.0.1")

    assert exposure.client_address("203.0.113.9", "1.2.3.4") == "203.0.113.9"
    assert exposure.client_address("203.0.113.9", "1.2.3.4, 5.6.7.8") == "203.0.113.9"


def test_a_trusted_proxy_is_believed(monkeypatch):
    monkeypatch.setenv(exposure.TRUSTED_PROXIES_ENV, "10.0.0.1")

    assert exposure.client_address("10.0.0.1", "203.0.113.9") == "203.0.113.9"


def test_the_rightmost_untrusted_hop_wins(monkeypatch):
    """A client may prepend anything it likes to the header; only the entries a
    trusted proxy appended can be believed, so the search runs from the right."""
    monkeypatch.setenv(exposure.TRUSTED_PROXIES_ENV, "10.0.0.1,10.0.0.2")

    assert exposure.client_address("10.0.0.1", "1.1.1.1, 203.0.113.9, 10.0.0.2") == "203.0.113.9"


def test_loopback_is_trusted_by_default(monkeypatch):
    """Which is exactly the tunnel arrangement: cloudflared or Tailscale Funnel
    terminates TLS and forwards from 127.0.0.1."""
    monkeypatch.delenv(exposure.TRUSTED_PROXIES_ENV, raising=False)

    assert exposure.client_address("127.0.0.1", "203.0.113.9") == "203.0.113.9"


def test_a_header_of_nothing_but_proxies_falls_back_to_the_peer(monkeypatch):
    monkeypatch.setenv(exposure.TRUSTED_PROXIES_ENV, "10.0.0.1,10.0.0.2")

    assert exposure.client_address("10.0.0.1", "10.0.0.2, 10.0.0.1") == "10.0.0.1"


def test_a_missing_peer_is_not_an_exception():
    assert exposure.client_address(None, None) == "unknown"


# --- The limiter itself ---


def test_failures_accumulate_and_then_block():
    clock = [1000.0]
    limiter = exposure.AttemptLimiter(limit=3, window_seconds=60, clock=lambda: clock[0])

    for _ in range(2):
        limiter.record_failure("caller")
    assert limiter.is_blocked("caller") is False

    limiter.record_failure("caller")
    assert limiter.is_blocked("caller") is True


def test_the_window_slides():
    clock = [1000.0]
    limiter = exposure.AttemptLimiter(limit=2, window_seconds=60, clock=lambda: clock[0])
    limiter.record_failure("caller")
    limiter.record_failure("caller")
    assert limiter.is_blocked("caller") is True

    clock[0] += 61
    assert limiter.is_blocked("caller") is False, "old failures must age out"


def test_success_clears_the_record():
    """What is being limited is guessing, not use. Someone typing their own
    password correctly has done nothing wrong."""
    limiter = exposure.AttemptLimiter(limit=2, window_seconds=60)
    limiter.record_failure("caller")
    limiter.record_success("caller")
    limiter.record_failure("caller")

    assert limiter.is_blocked("caller") is False


def test_callers_are_limited_separately():
    limiter = exposure.AttemptLimiter(limit=1, window_seconds=60)
    limiter.record_failure("attacker")

    assert limiter.is_blocked("attacker") is True
    assert limiter.is_blocked("the owner") is False


def test_retry_after_counts_down():
    clock = [1000.0]
    limiter = exposure.AttemptLimiter(limit=1, window_seconds=60, clock=lambda: clock[0])
    limiter.record_failure("caller")
    first = limiter.retry_after_seconds("caller")

    clock[0] += 30
    assert 0 < limiter.retry_after_seconds("caller") < first


def test_configuration_survives_nonsense(monkeypatch):
    monkeypatch.setenv(exposure.LOGIN_ATTEMPTS_ENV, "banana")
    assert exposure.login_attempt_limit() == exposure.DEFAULT_LOGIN_ATTEMPTS

    monkeypatch.setenv(exposure.LOGIN_ATTEMPTS_ENV, "0")
    assert exposure.login_attempt_limit() == exposure.DEFAULT_LOGIN_ATTEMPTS, (
        "a limit of zero would lock the owner out permanently and silently"
    )

    monkeypatch.setenv(exposure.LOGIN_ATTEMPTS_ENV, "3")
    assert exposure.login_attempt_limit() == 3


# --- The service ---


def test_every_response_carries_the_security_headers(gateway_client):
    response = gateway_client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_hsts_is_sent_only_when_the_request_arrived_over_tls(gateway_client):
    """Announcing HSTS on a plain HTTP response is how a developer locks
    themselves out of their own localhost."""
    plain = gateway_client.get("/health")
    assert "strict-transport-security" not in plain.headers

    tunnelled = gateway_client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert tunnelled.headers["strict-transport-security"].startswith("max-age=")


def test_repeated_failed_logins_are_refused_with_a_retry_after(gateway_client, monkeypatch):
    import gateway.main as gateway_main

    monkeypatch.setattr(gateway_main.login_limiter, "limit", 3)

    for _ in range(3):
        assert gateway_client.post(
            "/auth/login", json={"username": GATEWAY_TEST_USER, "password": "wrong"}
        ).status_code == 401

    blocked = gateway_client.post(
        "/auth/login", json={"username": GATEWAY_TEST_USER, "password": "wrong"}
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0

    # And the correct password is refused too, while the block stands - otherwise
    # the limit would only slow down an attacker who was already wrong.
    assert gateway_client.post(
        "/auth/login", json={"username": GATEWAY_TEST_USER, "password": GATEWAY_TEST_PASSWORD}
    ).status_code == 429


def test_a_successful_login_clears_the_count(gateway_client, monkeypatch):
    import gateway.main as gateway_main

    monkeypatch.setattr(gateway_main.login_limiter, "limit", 3)
    gateway_client.post("/auth/login", json={"username": GATEWAY_TEST_USER, "password": "wrong"})
    gateway_client.post(
        "/auth/login", json={"username": GATEWAY_TEST_USER, "password": GATEWAY_TEST_PASSWORD}
    )

    for _ in range(2):
        assert gateway_client.post(
            "/auth/login", json={"username": GATEWAY_TEST_USER, "password": "wrong"}
        ).status_code == 401


def test_the_socket_counts_against_the_same_limit(gateway_client, monkeypatch):
    """The property worth having: a socket that accepted unlimited token guesses
    would be an oracle sitting beside a rate-limited door."""
    import gateway.main as gateway_main

    monkeypatch.setattr(gateway_main.login_limiter, "limit", 2)

    for _ in range(2):
        with gateway_client.websocket_connect("/ws") as socket:
            socket.send_json({"type": "auth", "token": "guess"})
            assert socket.receive_json()["error"] == "unauthorized"

    blocked = gateway_client.post(
        "/auth/login", json={"username": GATEWAY_TEST_USER, "password": GATEWAY_TEST_PASSWORD}
    )
    assert blocked.status_code == 429, "socket guesses must count towards the login limit"


def test_a_blocked_caller_is_turned_away_at_the_socket_too(gateway_client, monkeypatch):
    import gateway.main as gateway_main

    monkeypatch.setattr(gateway_main.login_limiter, "limit", 1)
    gateway_client.post("/auth/login", json={"username": GATEWAY_TEST_USER, "password": "wrong"})

    with gateway_client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": "anything"})
        assert socket.receive_json() == {"type": "error", "error": "too many attempts"}
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()


def test_a_valid_session_still_connects_after_someone_elses_failures(
    gateway_client, gateway_token, monkeypatch
):
    """Limiting is per caller. A test client shares one address, so this is the
    closest the suite gets to proving the owner is not locked out by an attacker -
    the per-key separation itself is asserted directly above."""
    with gateway_client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": gateway_token})
        assert socket.receive_json()["type"] == "ready"


# --- How the server itself is configured (the defect a live run found) ---


def test_the_server_does_not_let_uvicorn_rewrite_the_client_address():
    """The bypass that made every guard above ineffective.

    Uvicorn's `proxy_headers` defaults to on and trusts loopback, so behind a
    tunnel it replaces `request.client` with whatever `X-Forwarded-For` claimed -
    before any application code runs. gateway/exposure.py's entire job is deciding
    whether to believe that header, and it was being handed a decision already
    made by a less careful implementation.

    Measured, not theorised: with the trusted-proxy list set to a non-loopback
    address, three requests from loopback claiming three different addresses each
    got their own rate-limit bucket, and uvicorn's access log printed a client of
    `1.1.1.1:0` - an address no socket came from. Every unit test passed, because
    the test scope carries the peer this module expects.
    """
    from gateway import run

    settings = run.config()

    assert settings.proxy_headers is False, (
        "uvicorn must not resolve the client address; gateway/exposure.py does, "
        "with rules that check who is entitled to make the claim"
    )
    assert not settings.forwarded_allow_ips, (
        "a trust list left configured while claiming not to use it is what starts "
        "working again after a refactor"
    )


def test_the_server_binds_to_loopback_only():
    """The tunnel is the only way in. Binding to 0.0.0.0 would be the
    forwarded-port arrangement the owner's decision rejected, with no TLS in front
    of it."""
    from gateway import run

    assert run.config().host == "127.0.0.1"


def test_the_port_is_configurable_and_survives_nonsense(monkeypatch):
    from gateway import run

    monkeypatch.delenv(run.PORT_ENV, raising=False)
    assert run.port() == run.DEFAULT_PORT

    monkeypatch.setenv(run.PORT_ENV, "9000")
    assert run.port() == 9000

    for nonsense in ("banana", "0", "70000"):
        monkeypatch.setenv(run.PORT_ENV, nonsense)
        assert run.port() == run.DEFAULT_PORT
