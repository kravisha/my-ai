"""§11-§13: a suspected weakness is not a confirmed weakness.

Phase 4 of §37. These are the tests behind acceptance TEST F (a suspicion that
testing disproves) and the first half of TEST G (a confirmed gap that stops at
the approval gate).

Like `test_jarvis_persistence.py`, everything runs against the real DBA
service. The lifecycle is only worth anything if the records it writes are
records the DBA would actually accept.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import capability_gaps as detector
from app import model_calls
from dba import agent as agent_module, main as dba_main, registry, store
from gateway import dbaclient, gaps, identity, ledger

TOKEN = "test-token-for-jarvis"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "b" * 40)
    monkeypatch.setattr(model_calls, "log_dir", lambda: tmp_path)
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def client():
    with TestClient(dba_main.app) as service:
        def transport(path, payload):
            response = service.post(
                path, json=payload,
                headers={"X-DBA-Agent": "JARVIS", "X-DBA-Token": TOKEN})
            try:
                return response.status_code, response.json()
            except ValueError:
                return response.status_code, {}

        yield dbaclient.DBAClient(transport=transport)


def _suspicion(client, title="missing_tool: read a PDF"):
    return gaps.suspect(
        client, title=title,
        description="Krish asked twice and got an apology both times",
        detected_by="test", evidence={"occurrences": 2})


# =============================================================================
# §11: suspecting is cheap, and leads nowhere on its own
# =============================================================================


def test_a_suspicion_starts_suspected_and_nothing_else(client):
    gap = _suspicion(client)
    assert gap["status"] == gaps.SUSPECTED
    assert gap["user_review_required"] is True
    with pytest.raises(gaps.NotConfirmed):
        gaps.ready_for_review(client, gap)


def test_a_suspicion_cannot_jump_straight_to_approved(client):
    """The one transition this lifecycle exists to forbid."""
    gap = _suspicion(client)
    with pytest.raises(gaps.IllegalTransition) as raised:
        gaps.transition(client, gap, gaps.APPROVED_FOR_REMEDIATION)
    assert "investigating" in str(raised.value)


def test_suspecting_the_same_thing_again_raises_its_frequency(client):
    """Two records would halve the count of the thing most worth fixing, which
    is the ranking rule `app/capability_gaps.py` exists to protect."""
    first = _suspicion(client)
    again = _suspicion(client)
    assert again["id"] == first["id"]
    assert again["frequency"] == 2
    assert len(gaps.all_gaps(client)) == 1


def test_the_detector_feeds_the_lifecycle_and_keeps_its_threshold(client):
    """Extends `app/capability_gaps.py` rather than re-detecting alongside it."""
    for _ in range(3):
        detector.record(gap_type=detector.GAP_MISSING_TOOL,
                        what_was_needed="read a PDF",
                        user_visible_outcome="apologised")
    detector.record(gap_type=detector.GAP_MISSING_KNOWLEDGE,
                    what_was_needed="the 2026 tax bands",
                    user_visible_outcome="guessed and said so")

    raised = gaps.suspect_from_detector(client)

    # The once-only gap is below the detector's own threshold and is not
    # promoted: "asked for often" and "asked for once" stay separate.
    assert [row["name"] for row in raised] == ["missing_tool: read a PDF"]
    assert raised[0]["frequency"] == 3
    assert all(row["status"] == gaps.SUSPECTED for row in raised)


# =============================================================================
# §12: confirming and rejecting, both with evidence
# =============================================================================


def test_confirming_without_evidence_is_refused(client):
    gap = _suspicion(client)
    investigating = gaps.transition(client, gap, gaps.INVESTIGATING)
    with pytest.raises(ValueError) as raised:
        gaps.confirm(client, investigating, evidence="   ", impact="high",
                     remedy=gaps.REMEDY_CODE)
    assert "evidence" in str(raised.value)


def test_a_confirmed_gap_keeps_its_evidence_and_reaches_the_gate(client):
    gap = _suspicion(client)
    gap = gaps.transition(client, gap, gaps.INVESTIGATING,
                          evidence="ran the PDF case; it failed")
    gap = gaps.confirm(client, gap,
                       evidence={"test": "heldout_pdf", "passed": False},
                       impact="Krish cannot use Jarvis for statements",
                       remedy=gaps.REMEDY_CODE)

    stored = client.get(gap["id"])
    assert stored["status"] == gaps.CONFIRMED
    assert "ran the PDF case" in stored["evidence"]
    assert "heldout_pdf" in stored["evidence"]
    assert gaps.needs_code_change(stored)
    gaps.ready_for_review(client, stored)  # does not raise


def test_a_rejected_gap_keeps_the_evidence_against_it(client):
    """TEST F: testing proves the capability already works."""
    gap = _suspicion(client)
    gap = gaps.transition(client, gap, gaps.INVESTIGATING)
    gap = gaps.reject(client, gap,
                      counter_evidence="the pdf skill exists and passed 5/5")

    stored = client.get(gap["id"])
    assert stored["status"] == gaps.REJECTED
    assert "5/5" in stored["counter_evidence"]
    assert stored["resolved_at"]
    # and no remediation is reachable from here
    with pytest.raises(gaps.NotConfirmed):
        gaps.ready_for_review(client, stored)


def test_rejecting_without_counter_evidence_is_refused(client):
    gap = gaps.transition(client, _suspicion(client), gaps.INVESTIGATING)
    with pytest.raises(ValueError):
        gaps.reject(client, gap, counter_evidence="")


def test_evidence_is_appended_never_replaced(client):
    gap = _suspicion(client)
    gap = gaps.transition(client, gap, gaps.INVESTIGATING, evidence="first look")
    gap = gaps.transition(client, gap, gaps.DEFERRED, evidence="second look")
    stored = client.get(gap["id"])
    assert "first look" in stored["evidence"]
    assert "second look" in stored["evidence"]


def test_a_resolved_gap_is_final(client):
    gap = _suspicion(client)
    for state in (gaps.INVESTIGATING,):
        gap = gaps.transition(client, gap, state, evidence="x")
    gap = gaps.confirm(client, gap, evidence="x", impact="y",
                       remedy=gaps.REMEDY_KNOWLEDGE)
    gap = gaps.transition(client, gap, gaps.APPROVED_FOR_REMEDIATION)
    gap = gaps.transition(client, gap, gaps.REMEDIATING)
    gap = gaps.transition(client, gap, gaps.RESOLVED)
    with pytest.raises(gaps.IllegalTransition):
        gaps.transition(client, gap, gaps.INVESTIGATING)


# =============================================================================
# §23: a gap is not automatically a code change
# =============================================================================


def test_only_one_remedy_means_changing_code(client):
    """§23's list. If every remedy implied code, the approval gate would be the
    only thing standing between a suspicion and an edit."""
    assert gaps.NEEDS_CODE_CHANGE == (gaps.REMEDY_CODE,)
    assert len(gaps.REMEDIES) > 1

    gap = gaps.transition(client, _suspicion(client), gaps.INVESTIGATING)
    gap = gaps.confirm(client, gap, evidence="measured", impact="small",
                       remedy=gaps.REMEDY_USE_EXISTING)
    assert not gaps.needs_code_change(client.get(gap["id"]))


def test_an_undeclared_remedy_is_refused(client):
    gap = gaps.transition(client, _suspicion(client), gaps.INVESTIGATING)
    with pytest.raises(ValueError):
        gaps.confirm(client, gap, evidence="x", impact="y", remedy="just wing it")


# =============================================================================
# The ledger records how the gap got where it is
# =============================================================================


def test_each_lifecycle_move_is_in_the_life_ledger(client):
    gap = gaps.transition(client, _suspicion(client), gaps.INVESTIGATING)
    gaps.confirm(client, gap, evidence="measured", impact="high",
                 remedy=gaps.REMEDY_CODE)

    types = [row["event_type"] for row in ledger.events(client, limit=50)]
    assert ledger.GAP_SUSPECTED in types
    assert ledger.GAP_CONFIRMED in types
    assert ledger.replay(client)["intact"] is True


def test_a_failed_ledger_write_lands_on_the_gaps_own_evidence(client, monkeypatch):
    """It must not stop the gap being confirmed, and it must not be silent."""
    gap = gaps.transition(client, _suspicion(client), gaps.INVESTIGATING)

    def refuse(*args, **kwargs):
        raise ledger.LedgerWriteFailed("the store went away")

    monkeypatch.setattr(ledger, "append", refuse)
    gaps.confirm(client, gap, evidence="measured", impact="high",
                 remedy=gaps.REMEDY_CODE)

    stored = client.get(gap["id"])
    assert stored["status"] == gaps.CONFIRMED
    assert "LEDGER_WRITE_FAILED" in stored["evidence"]


# =============================================================================
# The gate itself
# =============================================================================


def test_a_gap_marked_confirmed_without_going_through_confirm_is_refused(client):
    """Someone setting the status directly does not open the gate."""
    gap = _suspicion(client)
    client.update(gap["id"], {"status": gaps.CONFIRMED, "evidence": ""})
    with pytest.raises(gaps.NotConfirmed) as raised:
        gaps.ready_for_review(client, client.get(gap["id"]))
    assert "no evidence" in str(raised.value)


def test_every_state_in_the_specification_is_declared():
    """§12's list, verbatim."""
    required = {"suspected", "investigating", "unsupported", "confirmed",
                "rejected", "deferred", "approved_for_remediation",
                "remediating", "resolved", "unresolved"}
    assert required == set(gaps.STATES)
    assert required == set(gaps.TRANSITIONS)
