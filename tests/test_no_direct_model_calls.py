"""The single choke point, enforced statically (§4.1, docs/CALL_SITES.md §7).

Two halves guard the same rule and neither covers the other:

- The **runtime guard** (`app/model_calls.guard`) refuses a call that reached a
  model without the router, but only when that call actually happens. A path
  exercised once a month is a path this finds once a month.
- **This file** reads the source. It finds a bypass the day it is written,
  including one nothing has run yet - which is the case `docs/CALL_SITES.md`
  §3.3 is specifically about.

Written in the shape `tests/test_local_ai_contract.py`'s runtime tripwire
already uses, because that one has been right about this codebase before.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Where the router and the providers live. Everything else is a caller.
_ROUTER = "app/model_routing.py"
_PROVIDER_MODULES = {"app/kimi_provider.py", "app/model_provider.py",
                     "app/model_tiering.py"}
_PLUMBING = {_ROUTER, "app/model_gateway.py", "app/model_calls.py",
             "app/model_budget.py"} | _PROVIDER_MODULES

_PACKAGES = ("app", "agents", "backend", "gateway", "providers", "simulation",
             "demonstration", "desktop")

# Class names that talk to a vendor. A caller that names one of these is
# building its own path to a model.
_PROVIDER_CLASSES = {"KimiProvider", "AnthropicProvider", "TieredProvider"}


def _sources():
    for package in _PACKAGES:
        directory = REPO / package
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(REPO).as_posix()
            yield relative, path.read_text(encoding="utf-8")


def test_only_the_router_constructs_a_provider():
    """`docs/CALL_SITES.md` §1's headline, as an assertion.

    The whole repository holds one construction of `KimiProvider` outside the
    suite, and it is inside `build_router`. A second one anywhere would be a
    second path to the vendor, with its own idea of local-first."""
    offences = []
    for relative, text in _sources():
        if relative in _PLUMBING:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in _PROVIDER_CLASSES:
                offences.append(f"{relative}:{node.lineno}: {node.func.id}(...)")
    assert offences == [], (
        "a module outside the routing layer constructs a model provider; call "
        "app.model_gateway.default_provider() instead:\n  " + "\n  ".join(offences))


def test_the_router_is_the_only_thing_that_builds_the_remote_tier():
    tree = ast.parse((REPO / _ROUTER).read_text(encoding="utf-8"))
    constructions = [node for node in ast.walk(tree)
                     if isinstance(node, ast.Call)
                     and getattr(node.func, "attr", None) == "KimiProvider"]
    assert len(constructions) == 1, (
        "the remote tier should be constructed exactly once, in build_router")


def test_nothing_outside_the_providers_imports_the_http_client_for_a_model():
    """`httpx` is a legitimate dependency - the test client uses it - but a
    module that imports it *and* names the model endpoint is building its own
    wire."""
    offences = []
    for relative, text in _sources():
        if relative in _PLUMBING:
            continue
        if "httpx" in text and ("api.kimi.com" in text or "chat/completions" in text):
            offences.append(relative)
    assert offences == [], (
        "a module outside the provider layer speaks to a model endpoint "
        "directly:\n  " + "\n  ".join(offences))


def test_the_guard_covers_every_runtime_package():
    """The runtime guard refuses a direct call from application code. This
    asserts the package list it checks has not drifted from the packages that
    actually hold application code."""
    from app import model_calls

    assert set(model_calls.RUNTIME_PACKAGES) == {"agents", "backend", "gateway", "app"}
    for package in model_calls.RUNTIME_PACKAGES:
        assert (REPO / package).is_dir()


def test_the_documented_call_sites_still_match_the_code():
    """`docs/CALL_SITES.md` is a document, so it rots. This is the part of it
    that can be checked: the count of call sites reaching the model funnel."""
    reaching = set()
    for relative, text in _sources():
        if relative in _PLUMBING:
            continue
        if "call_reasoning_model(" in text or "default_provider()" in text:
            reaching.add(relative)

    assert reaching == {
        "agents/analysis.py", "agents/explorer.py", "agents/introspection.py",
        "agents/speculator.py", "backend/main.py", "backend/coo_chat.py",
        "gateway/main.py",
    }, ("the set of modules reaching the model funnel has changed; update "
        "docs/CALL_SITES.md §2 in the same commit")
