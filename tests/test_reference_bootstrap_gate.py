"""Unit test for backend/main.py's `_reference_allows_bootstrap` - the pure
decision behind the lifespan gate that stopped calling `controller.
bootstrap_coo()` when reference data certification is not READY
(docs/SPEC_RECONCILIATION.md SS40's disposition, made real once Explorer's
parity path gave reference data a real consumer - agents/explorer.py's
_parity_work, backend/reference_data.py's list_focus_assets).

Deliberately not a `with TestClient(...)` lifespan test - this repo's
TestClient has a known lifespan-thread quirk (see backend/main.py's own
lifespan docstring and tests/conftest.py's backend_client fixture, which is
built specifically to avoid entering lifespan). Testing the pure helper
directly is what the increment asked for, and is the whole point of pulling
the decision out of lifespan in the first place."""

from backend.main import _reference_allows_bootstrap


def test_ready_status_allows_bootstrap():
    readiness = {"status": "READY", "checks": [{"check": "focus_nonempty", "ok": True, "detail": "..."}]}
    assert _reference_allows_bootstrap(readiness) is True


def test_failed_status_refuses_bootstrap():
    readiness = {
        "status": "FAILED",
        "checks": [
            {"check": "focus_nonempty", "ok": False, "detail": "no asset class is in focus"},
            {"check": "focus_coverage", "ok": True, "detail": "..."},
        ],
    }
    assert _reference_allows_bootstrap(readiness) is False


def test_an_unrecognized_status_refuses_rather_than_assumes_safe():
    """Fail closed on anything that is not the literal 'READY' string -
    including a status this function has never seen, not just 'FAILED'."""
    assert _reference_allows_bootstrap({"status": "PENDING", "checks": []}) is False
    assert _reference_allows_bootstrap({"checks": []}) is False  # missing status entirely
