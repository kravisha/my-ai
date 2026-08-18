"""How to start the Gateway, and why it is not a bare `uvicorn` command.

    python -m gateway.run

**Uvicorn rewrites the client address from `X-Forwarded-For` by itself.**
`proxy_headers` defaults to on, trusting loopback, so behind a tunnel - or from
anything else on loopback - the address the application sees is already whatever
the caller claimed. `gateway/exposure.py` then has nothing left to check: its
whole job is deciding whether to *believe* that header, and by then the decision
has been made for it by a less careful implementation.

Found by running it. With `GATEWAY_TRUSTED_PROXIES` deliberately set to an
address that was not loopback, three requests from loopback claiming three
different `X-Forwarded-For` values each got their own rate-limit bucket - so the
per-caller limit was dodgeable by rotating a header. Uvicorn's own access log was
the tell: it printed the client as `1.1.1.1:0`, an address no socket ever came
from. Every unit test passed, because in the tests the ASGI scope carries the peer
this module expects rather than one uvicorn has already replaced.

So the server is started with proxy-header handling **off**, and the application
does it - in one place, with the rules written down. This module exists so that
the safe configuration is the documented way to run the service rather than a flag
somebody has to remember.

The Gateway binds to loopback and stays there. The tunnel (cloudflared or
Tailscale Funnel, owner decision 2026-08-18) is the only path in from outside;
binding to 0.0.0.0 instead would be the forwarded-port arrangement that decision
rejected, with no TLS in front of it.
"""

import os

import uvicorn

PORT_ENV = "GATEWAY_PORT"
DEFAULT_PORT = 8100

# Loopback, always. See the module docstring: the tunnel terminates TLS and
# forwards here, and there is no configuration for exposing this socket directly
# because there is no version of that which is a good idea.
HOST = "127.0.0.1"


def port() -> int:
    raw = os.environ.get(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return value if 0 < value < 65536 else DEFAULT_PORT


def config(**overrides) -> uvicorn.Config:
    """The server configuration, separated from running it so a test can assert
    the two settings that matter rather than trusting a comment about them."""
    settings = {
        "app": "gateway.main:app",
        "host": HOST,
        "port": port(),
        # The two that matter. `forwarded_allow_ips` is emptied as well as
        # disabling the middleware, because leaving a trust list configured while
        # claiming not to use it is the kind of half-measure that survives a
        # refactor and quietly starts working again.
        "proxy_headers": False,
        "forwarded_allow_ips": [],
        "log_level": "info",
    }
    settings.update(overrides)
    return uvicorn.Config(**settings)


def main() -> None:
    uvicorn.Server(config()).run()


if __name__ == "__main__":
    main()
