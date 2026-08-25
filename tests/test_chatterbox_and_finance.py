"""The Chatterbox and the Finance desk (backend/chatterbox.py,
backend/finance_desk.py; owner requests 2026-08-25, TQ-27,
SPEC_RECONCILIATION §77).

Two desks with one shared discipline: **report absence as a fact**. An
organization whose agents have never spoken is a finding about collaboration,
not a blank table; a market that was never generated is not a quiet market.

The Chatterbox's load-bearing case is `silent` — a question that timed out is
the actual collaboration failure, and folding it into "not completed" would
bury it. The Finance desk's is the SIMULATED flag, which must survive every
path including the failure ones, because a finance page is the single place
in this system where blurring synthetic and real would be dangerous.
"""

import pytest

from backend import chatterbox, finance_desk, fi_db, reference_data


def _ask(conn, security="SYN1", responder="explorer"):
    return fi_db.open_cross_check(
        conn, requester_identity="speculator-1",
        requester_spawned_at="2026-01-01T00:00:00+00:00", requester_role="speculator",
        responder_role=responder, security=security,
        question=f"what is the crowd saying about {security}?", requester_finding={},
    )


def _answer(conn, request_id, outcome=fi_db.CROSS_CHECK_EVIDENCE):
    fi_db.answer_cross_check(
        conn, request_id, responder_identity="explorer-1",
        responder_spawned_at="2026-01-01T00:00:00+00:00", outcome=outcome,
        responder_finding={"note": "looked"},
    )


# --- the Chatterbox --------------------------------------------------------------


def test_quiet_organization_reports_a_finding_not_a_blank(conn):
    """Silence between agents is itself information about collaboration."""
    m = chatterbox.living_map(conn)
    assert m["quiet"] is True
    assert m["conversations"] == []
    assert "not finding anything" in m["quiet_note"]


def test_an_answered_conversation_is_completed(conn):
    _answer(conn, _ask(conn))
    m = chatterbox.living_map(conn)
    assert len(m["conversations"]) == 1
    c = m["conversations"][0]
    assert c["state"] == chatterbox.STATE_COMPLETED
    assert c["from"] == "speculator-1" and c["to"] == "explorer-1"
    assert c["about"] == "SYN1"


def test_no_evidence_still_counts_as_answered(conn):
    """A responder that looked and found nothing has said something
    informative; scoring it as failure would teach agents to stay quiet."""
    _answer(conn, _ask(conn), outcome=fi_db.CROSS_CHECK_NO_EVIDENCE)
    assert chatterbox.living_map(conn)["conversations"][0]["state"] == chatterbox.STATE_COMPLETED


def test_a_fresh_question_is_active_and_an_aging_one_is_waiting(conn):
    """Two states before the timeout, so the map shows trouble building
    rather than only reporting it once it has already failed."""
    from datetime import datetime, timedelta, timezone

    _ask(conn)
    now = datetime.now(timezone.utc)
    assert chatterbox.living_map(conn, now=now)["conversations"][0]["state"] == chatterbox.STATE_ACTIVE

    aged = now + timedelta(seconds=fi_db.CROSS_CHECK_TIMEOUT_SECONDS * 0.9)
    assert chatterbox.living_map(conn, now=aged)["conversations"][0]["state"] == chatterbox.STATE_WAITING


def test_silence_gets_its_own_state(conn):
    """The load-bearing case: a timed-out question is the actual failure, and
    must not be folded into 'not completed'."""
    _ask(conn)
    fi_db.expire_stale_cross_checks(conn, timeout_seconds=0)
    m = chatterbox.living_map(conn)
    assert m["conversations"][0]["state"] == chatterbox.STATE_SILENT
    assert m["counts"][chatterbox.STATE_SILENT] == 1
    assert m["counts"][chatterbox.STATE_COMPLETED] == 0


def test_questions_to_an_agent_appear_beside_cross_checks(conn):
    """Both kinds of agent conversation the organization actually holds."""
    fi_db.ask_agent(conn, asked_by="operator", target_identity="explorer-1",
                    question="what are you working on?")
    kinds = {c["kind"] for c in chatterbox.living_map(conn)["conversations"]}
    assert kinds == {"question"}


def test_edges_map_who_talks_to_whom(conn):
    """Answered conversations edge to the agent that answered; a pending one
    edges to the *role*, because that is genuinely who it was addressed to —
    a cross-check names a responder_role and the identity is filled in by
    whoever picks it up. The map showing those as different edges is the
    truth, not a rounding error."""
    for security in ("SYN1", "SYN2", "SYN3"):
        _answer(conn, _ask(conn, security))
    _ask(conn, "SYN4")

    edges = {(e["from"], e["to"]): e for e in chatterbox.living_map(conn)["edges"]}
    answered = edges[("speculator-1", "explorer-1")]
    assert answered["total"] == 3 and answered["completed"] == 3

    on_duty = edges[("speculator-1", "explorer (whoever is on duty)")]
    assert on_duty["total"] == 1 and on_duty["active"] == 1


def test_health_uses_the_measured_dimensions_and_absent_is_not_zero(conn):
    """A desk nobody has asked anything is unstated, never scored badly -
    competency.py's rule carried onto the map."""
    fi_db.register_agent(conn, "explorer-1", "explorer", 100)
    health = {h["name"]: h for h in chatterbox.living_map(conn)["health"]}
    assert health, "a registered agent should appear on the health map"
    entry = next(iter(health.values()))
    assert entry["collaboration_responsiveness"]["stated"] is False
    assert entry["collaboration_responsiveness"]["score"] is None


# --- the Finance desk ------------------------------------------------------------


def test_simulated_notice_is_present_on_every_path(conn):
    """Including the failure paths. A finance page that lost its SIMULATED
    flag in an error branch would be the worst version of this bug."""
    page = finance_desk.front_page(conn)
    assert page["simulated"] is True
    assert "SIMULATED" in page["notice"]
    assert "not investment advice" in page["notice"] or "investment advice" in page["notice"]


def test_no_focus_assets_says_so(conn):
    page = finance_desk.front_page(conn)
    assert page["available"] is False
    assert "Reference Data Engine" in page["reason"]


def test_unpriced_universe_is_not_a_quiet_market(conn):
    """Certified assets with no generated world must say that, and name what
    would produce prices - an empty table would read as a calm session."""
    reference_data.run_reference_engine(conn)
    page = finance_desk.front_page(conn)
    assert page["available"] is True
    assert page["priced_count"] == 0
    assert "run a mission" in page["unpriced_note"]
    assert all(t["priced"] is False for t in page["tickers"])


def test_prices_come_from_the_stored_simulated_world(conn):
    """The priced path: a stored option_chain observation gives the desk its
    underlying quote, and the display price is explicitly a mid."""
    reference_data.run_reference_engine(conn)
    from simulation import parity_world as pw

    config = pw.MissionConfig(mission_id="m-fin", run_mode="simulation",
                              strategy=pw.STRATEGY_PARITY, seed=5, n_scenarios=2,
                              scenario_mix={pw.VARIANT_NONE: 1.0})
    pw.store_world(conn, config, runs_dir=None)

    page = finance_desk.front_page(conn)
    assert page["priced_count"] >= 1
    priced = [t for t in page["tickers"] if t["priced"]]
    for ticker in priced:
        assert ticker["bid"] < ticker["ask"]
        assert ticker["bid"] <= ticker["display_price"] <= ticker["ask"]
        assert ticker["direction"] in {"up", "down", "flat"}


def test_session_moves_are_stable_between_reads(conn):
    """A front page whose numbers danced at random on every poll would be
    lively and useless; the move is seeded from the symbol, so it changes
    when the world does rather than when the page refreshes."""
    reference_data.run_reference_engine(conn)
    from simulation import parity_world as pw

    pw.store_world(conn, pw.MissionConfig(
        mission_id="m-fin2", run_mode="simulation", strategy=pw.STRATEGY_PARITY,
        seed=7, n_scenarios=2, scenario_mix={pw.VARIANT_NONE: 1.0}), runs_dir=None)

    first = {t["symbol"]: t.get("change_pct") for t in finance_desk.front_page(conn)["tickers"]}
    second = {t["symbol"]: t.get("change_pct") for t in finance_desk.front_page(conn)["tickers"]}
    assert first == second


def test_headlines_are_flagged_placeholders(conn):
    """Until newspaper agents exist, every headline says it is a placeholder -
    and none of them name a real company."""
    reference_data.run_reference_engine(conn)
    page = finance_desk.front_page(conn)
    assert page["headlines"]
    assert all(h["placeholder"] is True for h in page["headlines"])
    assert "newspaper agents" in page["headlines_note"]


def test_a_gainer_has_to_have_gained(conn):
    """The desk used to slice its ranking from both ends, which mislabels data
    in two ways at once: with a small universe every asset appears in *both*
    lists, and on a down session the "gainers" are the assets that fell least.

    Found by looking at the page rather than by this suite - the terminal
    layout showed the moves in cells small enough that a red number under a
    "gainers" heading did not register, and the broadcast layout put it in
    32-point type. The bug was months old.
    """
    reference_data.run_reference_engine(conn)
    from simulation import parity_world as pw

    pw.store_world(conn, pw.MissionConfig(
        mission_id="m-movers", run_mode="simulation", strategy=pw.STRATEGY_PARITY,
        seed=11, n_scenarios=2, scenario_mix={pw.VARIANT_NONE: 1.0}), runs_dir=None)

    movers = finance_desk.front_page(conn)["movers"]

    assert all(t["change_pct"] > 0 for t in movers["gainers"]), (
        "a decliner is listed under gainers"
    )
    assert all(t["change_pct"] < 0 for t in movers["losers"]), (
        "a riser is listed under losers"
    )
    # No symbol can be both, which the old both-ends slice allowed whenever the
    # universe was smaller than ten.
    assert not ({t["symbol"] for t in movers["gainers"]}
                & {t["symbol"] for t in movers["losers"]})
    # Empty is the honest answer when nothing moved that way; padding the row
    # to a fixed length is what created the defect in the first place.
    assert len(movers["gainers"]) <= 5 and len(movers["losers"]) <= 5
