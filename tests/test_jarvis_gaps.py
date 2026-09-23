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
from gateway import dbaclient, gaps, identity, inquiry, ledger

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
        def transport(method, path, payload):
            response = service.request(
                method, path, json=payload if method != "GET" else None,
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


# =============================================================================
# §12: `investigating` is a state that investigates
# =============================================================================
#
# Before `gateway/inquiry.py` existed, a gap left `investigating` for
# `confirmed` because somebody called `confirm`. These tests are about the only
# thing that changed: the exit from that state now needs a concluded inquiry,
# and an inquiry refuses to conclude when the shape of its reasoning is bad.
#
# Probed by `tests/probes/inquiry_probes.py` for the reasoning half; the wiring
# half was probed by hand, by deleting `settle`'s refusal and each of its three
# destinations in turn.


def _investigated(client, asking):
    """Fill an inquiry in so that it will conclude - two explanations, one of
    them killed, the survivor looked at for the thing that would kill it."""
    asking.hypothesise("no_gap", "the capability is there and was misused",
                       refuted_by="a run that fails with the capability used "
                                  "correctly")
    asking.hypothesise("no_reader", "there is no PDF reader wired up at all",
                       refuted_by="a PDF read end to end")
    asking.observe("ran it correctly and it still failed", source="transcript",
                   finding=inquiry.REFUTES, about="no_gap")
    asking.observe("no pdf dependency in requirements", source="requirements.txt",
                   finding=inquiry.SUPPORTS, about="no_reader")
    asking.observe("searched for any pdf entry point; found none",
                   source="grep", finding=inquiry.NOTHING, about="no_reader")
    return asking


def test_investigating_opens_an_inquiry_about_the_gap(client):
    gap = _suspicion(client)
    moved, asking = gaps.investigate(client, gap)
    assert moved["status"] == gaps.INVESTIGATING
    assert "read a PDF" in asking.question
    assert asking.hypotheses == []
    assert asking.conclusion is None


def test_a_caller_may_ask_its_own_question(client):
    _, asking = gaps.investigate(client, _suspicion(client),
                                 question="  which library is missing?  ")
    assert asking.question == "which library is missing?"


def test_the_investigation_seeds_no_hypotheses_of_its_own(client):
    """A framework that writes the first hypothesis has chosen the anchor, and
    `inquiry.ANCHORED` could then never fire against a real explanation."""
    _, asking = gaps.investigate(client, _suspicion(client))
    assert asking.hypotheses == []
    assert inquiry.ONE_HYPOTHESIS in asking.blocking()


def test_a_gap_cannot_leave_investigating_without_a_concluded_inquiry(client):
    gap, asking = gaps.investigate(client, _suspicion(client))
    _investigated(client, asking)
    with pytest.raises(ValueError, match="has not concluded"):
        gaps.settle(client, gap, asking, remedy=gaps.REMEDY_TOOL)
    assert client.get(gap["id"])["status"] == gaps.INVESTIGATING


def test_a_confirmed_inquiry_confirms_the_gap_with_its_whole_record(client):
    gap, asking = gaps.investigate(client, _suspicion(client))
    _investigated(client, asking)
    asking.conclude(outcome=inquiry.CONFIRMED, answer="no_reader",
                    reasoning="nothing in the tree reads PDFs")
    settled = gaps.settle(client, gap, asking, remedy=gaps.REMEDY_TOOL,
                          impact="Krish cannot read statements")

    assert settled["status"] == gaps.CONFIRMED
    gaps.ready_for_review(client, settled)
    evidence = client.get(gap["id"])["evidence"]
    # The losing explanation and the absence are both in what Krish will read.
    assert "the capability is there and was misused" in evidence
    assert "found_nothing" in evidence
    assert "no_reader" in evidence


def test_confirming_a_gap_from_an_inquiry_still_needs_a_remedy(client):
    """§23. The mapping is total, but it does not get to pick the remedy."""
    gap, asking = gaps.investigate(client, _suspicion(client))
    _investigated(client, asking)
    asking.conclude(outcome=inquiry.CONFIRMED, answer="no_reader")
    with pytest.raises(ValueError, match="which of"):
        gaps.settle(client, gap, asking)
    assert client.get(gap["id"])["status"] == gaps.INVESTIGATING


def test_an_inquiry_that_found_nothing_leaves_the_gap_unsupported(client):
    gap, asking = gaps.investigate(client, _suspicion(client))
    asking.hypothesise("no_gap", "the capability is there",
                       refuted_by="a run that fails when used correctly")
    asking.hypothesise("no_reader", "nothing reads PDFs",
                       refuted_by="a PDF read end to end")
    asking.observe("read three PDFs end to end", source="run",
                   finding=inquiry.REFUTES, about="no_reader")
    asking.conclude(outcome=inquiry.UNSUPPORTED, reasoning="it reads PDFs fine")
    settled = gaps.settle(client, gap, asking)

    assert settled["status"] == gaps.UNSUPPORTED
    assert "unsupported" in client.get(gap["id"])["resolution"]
    with pytest.raises(gaps.NotConfirmed):
        gaps.ready_for_review(client, client.get(gap["id"]))


def test_an_inconclusive_inquiry_defers_the_gap_rather_than_closing_it(client):
    """Not answered, so not closed either - and `deferred` can go back to
    `investigating`, which is the point of sending it there."""
    gap, asking = gaps.investigate(client, _suspicion(client))
    _investigated(client, asking)
    asking.conclude(outcome=inquiry.INCONCLUSIVE,
                    reasoning="the transcript is missing the relevant turn")
    settled = gaps.settle(client, gap, asking)

    assert settled["status"] == gaps.DEFERRED
    assert "inconclusive" in client.get(gap["id"])["resolution"]
    assert gaps.INVESTIGATING in gaps.TRANSITIONS[gaps.DEFERRED]


def test_an_overridden_objection_is_the_first_thing_on_the_evidence(client):
    """§13 takes a confirmed gap to Krish. That its reasoning was overridden is
    the single most important thing on that page, so it is not left nested in a
    dictionary under `conclusion`."""
    gap, asking = gaps.investigate(client, _suspicion(client))
    asking.hypothesise("no_reader", "nothing reads PDFs", refuted_by="a PDF read")
    asking.observe("no pdf dependency", source="requirements.txt",
                   finding=inquiry.SUPPORTS, about="no_reader")
    asking.conclude(outcome=inquiry.CONFIRMED, answer="no_reader",
                    accepting=[inquiry.ONE_HYPOTHESIS,
                               inquiry.NO_REFUTATION_ATTEMPTED])
    gaps.settle(client, gap, asking, remedy=gaps.REMEDY_TOOL)

    evidence = client.get(gap["id"])["evidence"]
    assert gaps.OVERRIDDEN_WARNING in evidence
    assert evidence.index(gaps.OVERRIDDEN_WARNING) < evidence.index("hypotheses")
    for name in (inquiry.ONE_HYPOTHESIS, inquiry.NO_REFUTATION_ATTEMPTED):
        assert name in evidence


def test_a_clean_investigation_carries_no_warning(client):
    gap, asking = gaps.investigate(client, _suspicion(client))
    _investigated(client, asking)
    asking.conclude(outcome=inquiry.CONFIRMED, answer="no_reader")
    gaps.settle(client, gap, asking, remedy=gaps.REMEDY_TOOL)
    assert gaps.OVERRIDDEN_WARNING not in client.get(gap["id"])["evidence"]


def test_every_inquiry_outcome_has_exactly_one_destination(client):
    """A mapping with a hole in it would default, and every default available
    here is a lie about what was established."""
    reached = {}
    for outcome in inquiry.OUTCOMES:
        gap, asking = gaps.investigate(client, _suspicion(
            client, title=f"missing_tool: {outcome}"))
        _investigated(client, asking)
        asking.conclude(outcome=outcome,
                        answer="no_reader" if outcome != inquiry.UNSUPPORTED
                        else None)
        settled = gaps.settle(client, gap, asking, remedy=gaps.REMEDY_TOOL)
        reached[outcome] = settled["status"]

    assert reached == {inquiry.CONFIRMED: gaps.CONFIRMED,
                       inquiry.UNSUPPORTED: gaps.UNSUPPORTED,
                       inquiry.INCONCLUSIVE: gaps.DEFERRED}
    assert set(reached) == set(inquiry.OUTCOMES)


def test_the_investigation_is_in_the_life_ledger(client):
    gap = _suspicion(client)
    gaps.investigate(client, gap)
    moves = [row for row in ledger.events(client, limit=50)
             if row["event_type"] == ledger.STATE_TRANSITION]
    assert moves, "entering investigation left no trace in the ledger"
    # The summary is stored as the record's `name`; see ledger.append.
    assert any("read a PDF" in row["name"] for row in moves)
    assert any(asked in row["observation"] for row in moves
               for asked in ["real capability gap"])
    assert ledger.replay(client)["intact"] is True


def test_the_gaps_confidence_is_the_one_the_inquiry_derived(client):
    """§28 declared `confidence` and nothing had ever written it.

    The number is `Inquiry.confidence()`, which is computed from independent
    sources, surviving a refutation and eliminated alternatives. Nothing can
    set it, here or anywhere."""
    gap, asking = gaps.investigate(client, _suspicion(client))
    _investigated(client, asking)
    asking.conclude(outcome=inquiry.CONFIRMED, answer="no_reader")
    gaps.settle(client, gap, asking, remedy=gaps.REMEDY_TOOL)

    derived = asking.confidence("no_reader")
    assert derived > 0
    assert client.get(gap["id"])["confidence"] == derived


def test_a_gap_confirmed_over_objections_carries_a_lower_confidence(client):
    """The two records that reach Krish differ in the number as well as in the
    warning, and neither of them was chosen by anybody."""
    clean, asking = gaps.investigate(client, _suspicion(client))
    _investigated(client, asking)
    asking.conclude(outcome=inquiry.CONFIRMED, answer="no_reader")
    gaps.settle(client, clean, asking, remedy=gaps.REMEDY_TOOL)

    thin, forced = gaps.investigate(
        client, _suspicion(client, title="missing_tool: forced"))
    forced.hypothesise("no_reader", "nothing reads PDFs", refuted_by="a PDF read")
    forced.observe("no pdf dependency", source="requirements.txt",
                   finding=inquiry.SUPPORTS, about="no_reader")
    forced.conclude(outcome=inquiry.CONFIRMED, answer="no_reader",
                    accepting=[inquiry.ONE_HYPOTHESIS,
                               inquiry.NO_REFUTATION_ATTEMPTED])
    gaps.settle(client, thin, forced, remedy=gaps.REMEDY_TOOL)

    assert (client.get(thin["id"])["confidence"]
            < client.get(clean["id"])["confidence"])


def test_an_unsupported_investigation_records_its_confidence_too(client):
    """Not only the confirmations. A gap closed as unsupported on a weak look is
    a gap that will be suspected again, and the number is how a reader tells."""
    gap, asking = gaps.investigate(client, _suspicion(client))
    asking.hypothesise("no_gap", "the capability is there", refuted_by="a fail")
    asking.hypothesise("no_reader", "nothing reads PDFs", refuted_by="a read")
    asking.observe("read three PDFs end to end", source="run",
                   finding=inquiry.REFUTES, about="no_reader")
    asking.conclude(outcome=inquiry.UNSUPPORTED, reasoning="it reads PDFs fine")
    gaps.settle(client, gap, asking)
    assert client.get(gap["id"])["confidence"] == asking.confidence(None)


def test_a_settle_that_is_refused_writes_nothing_at_all(client):
    """Every check before every write. A caller who forgot the remedy used to
    leave a derived confidence on a gap that never moved."""
    gap, asking = gaps.investigate(client, _suspicion(client))
    _investigated(client, asking)
    asking.conclude(outcome=inquiry.CONFIRMED, answer="no_reader")
    before = client.get(gap["id"])

    with pytest.raises(ValueError):
        gaps.settle(client, gap, asking)
    with pytest.raises(ValueError, match="is not one of"):
        gaps.settle(client, gap, asking, remedy="rewrite everything")

    after = client.get(gap["id"])
    assert after["status"] == gaps.INVESTIGATING
    assert after.get("confidence") == before.get("confidence")
    assert after["evidence"] == before["evidence"]
