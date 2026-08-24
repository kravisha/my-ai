"""Explorer: the Discovery Slice's deterministic-detection role (addendum_7
§2, addendum_10 §5). Each cycle, scans an option implied-volatility surface
for every security in the configured peer group (agents/discovery_config.py's
PEER_GROUP_SECURITIES), runs the Peak IV / Local Baseline IV >= threshold
detector (addendum_7 §4) independently per security, then classifies each
triggering candidate as 'peer' (at least PEER_MIN_COOCCURRING other
securities in the group also triggered this cycle - addendum_7 §5:
"potentially market/sector/common-factor driven") or 'individual'
(isolated - "idiosyncratic, investigate security-specific causes"). Only
after the deterministic detector produces a candidate does a lightweight
LLM judgment gate run before filing a report (addendum_7 §2 last bullet).

One Explorer process loops over the whole peer group rather than one
process per security - multi-instance-per-role scaling is explicitly
deferred project-wide (see agents/coo.py's BASELINE_ROLES /
backend/controller.py's _slot_identity, both hard-assume exactly one
identity per role).

Run directly as: python -m agents.explorer <identity>
Normally launched by backend/controller.py as a subprocess, not by hand.
"""

import json
import statistics
import sys

from agents import discovery_config as config
from agents.base import run_agent
from app.model_gateway import call_reasoning_model
from backend import fi_db, reference_data
from backend.arbitrage import CostConfig, Opportunity, scan_calendar, scan_chain
from providers.market_data import EXPIRIES_DAYS, STRIKES, SyntheticMarketDataProvider
from providers.stored_data import StoredChainProvider, chain_snapshots

ROLE = "explorer"
DETECTOR_TYPE = "iv_surface_peak_ratio"
# The arbitrage-library path's own routing tag - the requester_finding
# ['detector'] value _file_cross_checked_reports keys off of to tell a
# parity/library lead from an IV-surface one. The name is historical (it
# predates Phase 1's other detectors, backend/arbitrage.py's SS45 addition);
# it now routes every scan_chain detection, ARB-001 included, not only
# ARB-001's own - the actual detector fired is carried per-finding in
# requester_finding['detector_id'] instead.
PARITY_DETECTOR_TYPE = "arb001_parity"
JUDGMENT_MAX_TOKENS = 300


def _local_baseline(grid: dict, si: int, ei: int, strike_radius: int, expiry_radius: int) -> float | None:
    """Mean IV of the neighborhood around (si, ei), excluding the cell
    itself - addendum_7 §4: "the local baseline must come from an
    appropriate neighborhood on the volatility surface, not an arbitrary
    global average." Returns None if the cell has no neighbors (shouldn't
    happen with this module's grid sizes, but a defensive edge case)."""
    neighbors = []
    for nsi in range(si - strike_radius, si + strike_radius + 1):
        for nei in range(ei - expiry_radius, ei + expiry_radius + 1):
            if (nsi, nei) == (si, ei) or (nsi, nei) not in grid:
                continue
            neighbors.append(grid[(nsi, nei)])
    if not neighbors:
        return None
    return sum(neighbors) / len(neighbors)


def scan_for_anomaly(surface) -> tuple[float, int, int, float, float] | None:
    """Scans every grid cell, returns (ratio, strike_idx, expiry_idx,
    peak_iv, baseline_iv) for the single highest-ratio cell, or None if the
    surface is empty. Pure function of the surface - no threshold applied
    here, that's the caller's job (see _explorer_work)."""
    grid = {}
    for pt in surface.points:
        grid[(STRIKES.index(pt.strike), EXPIRIES_DAYS.index(pt.expiry_days))] = pt.iv

    best = None
    for (si, ei), iv in grid.items():
        baseline = _local_baseline(grid, si, ei, config.NEIGHBORHOOD_STRIKE_RADIUS, config.NEIGHBORHOOD_EXPIRY_RADIUS)
        if baseline is None or baseline <= 0:
            continue
        ratio = iv / baseline
        if best is None or ratio > best[0]:
            best = (ratio, si, ei, iv, baseline)
    return best


def _extract_text(response) -> str:
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _judgment_gate(security: str, ratio: float, peak_iv: float, baseline_iv: float) -> tuple[bool, str | None]:
    """Lightweight LLM coherence check (addendum_7 §2 last bullet) - not
    the final investment thesis, just "is this candidate coherent enough to
    justify handing to deep Analysis." A parse failure counts as not
    passing (fail closed - a malformed judgment shouldn't silently become a
    filed report)."""
    system = (
        "You are Explorer's lightweight judgment gate for an options "
        "volatility-anomaly detector. A deterministic detector already "
        "found a candidate; your only job is a quick coherence check "
        "before it's handed to deep Analysis - not a final investment "
        "thesis. Reply with strict JSON only, no other text: "
        '{"passed": true or false, "note": "one short sentence"}'
    )
    user_content = (
        f"Security: {security}\n"
        f"Peak IV / Local Baseline IV ratio: {ratio:.3f}\n"
        f"Peak IV: {peak_iv:.4f}\n"
        f"Local baseline IV: {baseline_iv:.4f}\n"
        "Is this candidate coherent enough to justify deep analysis?"
    )
    response = call_reasoning_model(
        system=system,
        messages=[{"role": "user", "content": user_content}],
        tools=[],
        max_tokens=JUDGMENT_MAX_TOKENS,
    )
    text = _extract_text(response)
    try:
        parsed = json.loads(text)
        return bool(parsed.get("passed", False)), parsed.get("note")
    except (json.JSONDecodeError, AttributeError, TypeError):
        return False, f"judgment parse failure: {text[:200]}"


def _file_cross_checked_reports(conn, identity: str, spawned_at: str) -> None:
    """Turn answered cross-checks into reports, carrying **both** findings.

    The report deliberately does not say whether the two agree. Explorer is
    procedural and Speculator is procedural; whether a quiet, broadly-sourced
    crowd corroborates an IV dislocation - or whether a loud crowd from three
    accounts undercuts it - is a reasoning judgment, and reasoning is Analysis's
    job alone. What is preserved here is the disagreement itself: two findings,
    unreconciled, both attributable (addendum 12 §14).

    Escalation is unconditional on the *content* of the answer for the same
    reason. A contradicting answer is not grounds for silently dropping the
    lead - that would be the gatekeeper reasoning about its own gate, the
    suppression failure mode the gap analysis §4.2 already flags. It is filed
    with the dissent attached, and Analysis decides what it is worth."""
    for request in fi_db.fetch_resolved_cross_checks(conn, identity):
        finding = json.loads(request["requester_finding"])
        responder_finding = json.loads(request["responder_finding"]) if request["responder_finding"] else None
        security = request["security"]

        if not fi_db.has_pending_report(conn, identity, security):
            if finding.get("detector") == PARITY_DETECTOR_TYPE:
                # The arbitrage library's own lead (agents/explorer.py's
                # _parity_work below) - a parity_event_id, not a
                # detector_event_id, backs this report; discovery_reports
                # carries both columns precisely so neither detector's rows
                # are mistaken for the other's (see backend/fi_db.py's SCHEMA
                # comment on parity_event_id). detector_id/strike2/strike3
                # default for findings recorded before the cross-strike
                # training increment (SS45) added them to requester_finding.
                detector_id = finding.get("detector_id", "ARB-001")
                strikes_text = _opportunity_strikes_text(
                    finding["strike"], finding.get("strike2"), finding.get("strike3"),
                )
                fi_db.enqueue_report(
                    conn, identity, spawned_at, "explorer", security,
                    summary=(
                        f"Executable {detector_id} {finding['direction']} on {security}: "
                        f"net edge ${finding['net_edge_per_share']:.2f}/share at K={strikes_text} "
                        f"{finding['expiry_days']}d (class {finding['classification']}); "
                        f"cross-check {request['outcome']}"
                    ),
                    detector_event_id=None,
                    evidence_ids=[], judgment_confidence=None,
                    lens_artifact_id=finding.get("lens_artifact_id"),
                    cross_check_id=request["id"],
                    parity_event_id=finding["parity_event_id"],
                )
            else:
                fi_db.enqueue_report(
                    conn, identity, spawned_at, "explorer", security,
                    summary=(
                        f"IV surface anomaly on {security}: ratio {finding['ratio']:.2f} "
                        f"(peak {finding['peak_iv']:.4f} vs baseline {finding['baseline_iv']:.4f}), "
                        f"scope={finding['scope']}; cross-check {request['outcome']}"
                    ),
                    detector_event_id=finding.get("detector_event_id"),
                    evidence_ids=[], judgment_confidence=None,
                    lens_artifact_id=finding.get("lens_artifact_id"),
                    cross_check_id=request["id"],
                )
        # Consumed either way - a duplicate-suppressed lead must not leave the
        # request open forever, or this security could never be asked about again.
        fi_db.consume_cross_check(conn, request["id"])


def _answer_pending_cross_checks(conn, identity: str, spawned_at: str, provider, threshold: float) -> None:
    """Answer Speculator's request for quantitative corroboration.

    Deterministic - Explorer reports what its detector saw on that security and
    nothing more. It does not judge whether that supports Speculator's social
    evidence, for the same reason Speculator does not judge the converse."""
    request = fi_db.fetch_next_pending_cross_check(conn, ROLE)
    if request is None:
        return

    security = request["security"]
    best = scan_for_anomaly(provider.get_option_surface(security))
    if best is None:
        fi_db.answer_cross_check(
            conn, request["id"], identity, spawned_at, fi_db.CROSS_CHECK_NO_EVIDENCE,
            {"detector": DETECTOR_TYPE, "reason": "no usable surface for this security"},
        )
        return

    ratio, _si, _ei, peak_iv, baseline_iv = best
    fi_db.answer_cross_check(
        conn, request["id"], identity, spawned_at, fi_db.CROSS_CHECK_EVIDENCE,
        {
            "detector": DETECTOR_TYPE,
            "ratio": round(ratio, 4),
            "peak_iv": round(peak_iv, 4),
            "baseline_iv": round(baseline_iv, 4),
            "threshold": threshold,
            # The bare fact, not an opinion about what it means for the asker.
            "cleared_threshold": ratio >= threshold,
        },
        responder_confidence=None,
    )


def _opportunity_strikes(opportunity: Opportunity) -> tuple[float, float | None, float | None]:
    """(strike, strike2, strike3) for a parity_events row - the package's
    primary strike (k1 for a multi-leg package, the lone strike for a
    same-strike one) plus whatever else `Opportunity.inputs` carries."""
    strike = opportunity.inputs.get("strike", opportunity.inputs.get("k1"))
    return strike, opportunity.inputs.get("k2"), opportunity.inputs.get("k3")


def _opportunity_strikes_text(strike: float, strike2: float | None, strike3: float | None) -> str:
    strikes = [strike] + [k for k in (strike2, strike3) if k is not None]
    return "/".join(str(k) for k in strikes)


def _parity_work(conn, identity: str, spawned_at: str) -> None:
    """Explorer as the arbitrage library's own chain scanner
    (SPEC_RECONCILIATION.md §39-§41/§45, addendum 25/27): reads whatever
    option_chain observations a stored mission world has left behind
    (providers/stored_data.py) and runs backend/arbitrage.py's `scan_chain`
    over them directly - ARB-001 alongside every cross-strike detector the
    same scan already knows how to run, not a per-row detect_arb001 loop
    that only ever saw the parity relation. §45 deferred this exact wiring
    ("Explorer wiring ... for the cross-strike detectors" pending "training
    scenarios the world can pose") - simulation/parity_world.py's
    cross-strike variants are that missing scenario design.

    Activation is data presence, not a flag (providers/stored_data.py's
    module docstring): reference_data.list_focus_assets always returns
    something once reference data is READY, but latest_chain returns None
    for every asset until a mission has actually stored a world - so with
    nothing stored, this whole function is a no-op cycle after cycle."""
    # Same market-session gate as the IV path, mirrored rather than shared:
    # an option chain does not exist while the market is shut, for the same
    # reason an IV surface doesn't (see _explorer_work's own comment on
    # market_is_open) - just checked against "option_chain"'s own cadence
    # rather than "option_surface"'s.
    if not fi_db.market_is_open(conn, "option_chain"):
        return

    # The lens name (arb001_min_net_edge) is historical - it was seeded
    # before Phase 1 existed, when ARB-001 was the only detector Explorer
    # ran. Its scope is now the whole library scan: every Phase 1 direction's
    # net edge is compared against the same bar, ARB-001's included, rather
    # than inventing a second lens for the same "any positive executable
    # edge clears" convention (§46 will record the rename this comment
    # stands in for).
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_PARITY_MIN_EDGE_NAME)
    lens_artifact_id = lens["id"] if lens else None
    min_net_edge = json.loads(lens["value"]) if lens else fi_db.LENS_PARITY_MIN_EDGE_SEED

    provider = StoredChainProvider(conn)
    costs = CostConfig()

    # list_focus_assets, not PEER_GROUP_SECURITIES - addendum 25/40's work-
    # discovery consumer this lens was always meant to have: Explorer scans
    # whatever the Reference Data Engine has certified as in focus, not a
    # hand-maintained peer-group list that has nothing to do with the parity
    # mission's own universe.
    for asset in reference_data.list_focus_assets(conn):
        entity_id, security = asset["entity_id"], asset["primary_identifier"]
        observation = provider.latest_chain(entity_id)
        if observation is None:
            continue

        candidates = []
        chains = list(chain_snapshots(observation))
        for chain in chains:
            for result in scan_chain(chain, costs):
                if result.net_edge_per_share >= min_net_edge:
                    candidates.append(result)
        # The cross-expiry scan (ARB-012, §56) over the same chains, behind
        # the same min-edge lens - one bar for the whole library until
        # grades distinguish detector families (§46's own deferral).
        for result in scan_calendar(chains, costs):
            if result.net_edge_per_share >= min_net_edge:
                candidates.append(result)
        if not candidates:
            continue

        # The single best opportunity per security, not every package that
        # cleared the bar - one escalation per security per cycle, the same
        # shape has_pending_report/has_open_cross_check below dedup against
        # (both keyed on security, not on strike/expiry/detector).
        #
        # ARB-001 preferred when present, net edge the tiebreak otherwise:
        # a classic genuine scenario's one-legged shift is this mission's
        # own deliberately-planted training signal, and it also, as an
        # accepted side effect of that same shift, breaks cross-strike
        # bounds against the neighboring strike
        # (docs/SPEC_RECONCILIATION.md SS45's second finding;
        # tests/test_arbitrage_phase1.py already characterizes this as the
        # world generator's own property, not a detector bug) - a box or
        # vertical package born from that side effect can carry a larger net
        # edge than the parity edge itself without being what this security's
        # world was built to teach. This preference is a no-op for every
        # cross-strike scenario (simulation/parity_world.py's
        # cross_strike_bump/dip injectors preserve parity exactly, so no
        # ARB-001 candidate ever exists there to prefer).
        arb001_candidates = [c for c in candidates if c.detector_id == "ARB-001"]
        pool = arb001_candidates or candidates
        opportunity = max(pool, key=lambda o: o.net_edge_per_share)
        strike, strike2, strike3 = _opportunity_strikes(opportunity)
        expiry_days = opportunity.inputs["expiry_days"]

        parity_event_id = fi_db.record_parity_event(
            conn, identity, spawned_at, entity_id, security,
            strike, expiry_days, opportunity.direction,
            opportunity.gross_edge_per_share, opportunity.net_edge_per_share,
            opportunity.classification, opportunity.capacity_units,
            observed_at=observation.observed_at,
            run_id=observation.provenance.run_id, scenario_id=observation.provenance.scenario_id,
            lens_artifact_id=lens_artifact_id,
            detector_id=opportunity.detector_id, strike2=strike2, strike3=strike3,
            expiry2_days=opportunity.inputs.get("expiry2_days"),
        )

        if fi_db.has_pending_report(conn, identity, security):
            # A report from this producer+security is still unconsumed.
            continue
        if fi_db.has_open_cross_check(conn, identity, security):
            # A question is already out on this security.
            continue
        # The mission's world is static per run - the same stored chain
        # answers scan_chain identically every cycle, so without this guard
        # a security Analysis has already judged would re-open a cross-check
        # (and trigger a fresh, paid Analysis pass) every single remaining
        # cycle of the mission's life. The IV path needs no equivalent
        # guard: its synthetic surface only repeats when a caller
        # deliberately forces an anomaly, where a stored parity world always
        # does.
        if fi_db.list_recent_analysis_results(conn, security, config.ANALYSIS_RECENCY_WINDOW_SECONDS):
            continue

        # No LLM judgment gate here, unlike the IV path's _judgment_gate.
        # Every Phase 1 detector's own hard stops (stale quote, crossed
        # market, invalid bid, non-European style) and its executable-
        # price-only edge computation are already the precision filter
        # (backend/arbitrage.py's module docstring: "there is no code path
        # in this module that reads a mid price") - a coherence check on
        # deterministic arithmetic that already cleared its own cost-plus-
        # buffer model would be an LLM call with nothing left to judge.
        strikes_text = _opportunity_strikes_text(strike, strike2, strike3)
        # A calendar package's identity is its expiry PAIR - presenting only
        # the near leg made the first live ARB-012 thesis (correctly) doubt
        # the structure existed at all: "only one expiry_days is reported
        # for both legs ... evidence that the 'calendar' structure is
        # misidentified" (SPEC_RECONCILIATION §57's live finding, caught by
        # the analysis model itself, unprompted).
        expiry2_days = opportunity.inputs.get("expiry2_days")
        expiry_text = f"{expiry_days}d" if expiry2_days is None else f"{expiry_days}d vs {expiry2_days}d"
        fi_db.open_cross_check(
            conn, identity, spawned_at, ROLE, "speculator", security,
            question=(
                f"Explorer detected an executable {opportunity.detector_id} {opportunity.direction} on "
                f"{security} at strike(s) {strikes_text} expiring in {expiry_text} "
                f"(net edge ${opportunity.net_edge_per_share:.2f}/share). "
                "Is there contextual evidence of unusual attention on this security?"
            ),
            requester_finding={
                "detector": PARITY_DETECTOR_TYPE,
                "parity_event_id": parity_event_id,
                "detector_id": opportunity.detector_id,
                "direction": opportunity.direction,
                "net_edge_per_share": round(opportunity.net_edge_per_share, 4),
                "gross_edge_per_share": round(opportunity.gross_edge_per_share, 4),
                "classification": opportunity.classification,
                "strike": strike,
                "strike2": strike2,
                "strike3": strike3,
                "expiry_days": expiry_days,
                "expiry2_days": expiry2_days,
                "lens_artifact_id": lens_artifact_id,
            },
            requester_confidence=None,
        )


def _explorer_work(conn, identity: str, spawned_at: str, provider) -> None:
    neighborhood_desc = f"strike idx ±{config.NEIGHBORHOOD_STRIKE_RADIUS}, expiry idx ±{config.NEIGHBORHOOD_EXPIRY_RADIUS}"

    # The threshold is intelligence, not configuration - it is resolved from
    # the intelligence_artifacts store each cycle rather than read from a
    # constant, so that it carries provenance, can be attributed from the
    # grades of the reports it produces, and can be marked stale on evidence.
    #
    # Falling back to the seed when there is no active artifact is deliberate:
    # get_active_artifact returns None for a lens that has been marked stale,
    # and a stale lens is a signal for review, not a reason to stop detecting.
    # Explorer keeps working with the seed value and lets COO's flag stand.
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    lens_artifact_id = lens["id"] if lens else None
    threshold = json.loads(lens["value"]) if lens else fi_db.LENS_IV_RATIO_SEED

    # Stop waiting on questions nobody answered, before collecting answers -
    # so a request that just timed out is picked up in the same cycle rather
    # than the next one. Silence becomes an 'unanswered' outcome that reaches
    # Analysis, not a lead that quietly evaporates.
    fi_db.expire_stale_cross_checks(conn)
    _file_cross_checked_reports(conn, identity, spawned_at)
    _answer_pending_cross_checks(conn, identity, spawned_at, provider, threshold)

    # ARB-001, addendum 25/27's parity mission (SPEC_RECONCILIATION.md
    # §39-§41): a separate detector over a separate stored feed, called here
    # rather than after the IV surface work's own early return below - that
    # return is gated on "option_surface"'s session, and _parity_work has
    # its own independent "option_chain" gate (see its docstring), so it
    # must not be skipped just because the IV surface market happens to be
    # shut. The two detectors share nothing but the ROLE and the
    # cross-check/report plumbing they both escalate through.
    _parity_work(conn, identity, spawned_at)

    # Scan every peer-group security independently first, so classification
    # (below) can ask "how many others also triggered this same cycle"
    # without re-scanning anything.
    # An options surface does not exist while the market is shut, so scanning
    # one would be reading a quote nobody could trade. Speculator deliberately
    # does not do this: message boards have no closing bell, and an organization
    # that went quiet with the exchange would miss the overnight chatter that is
    # often the most informative part of the day.
    #
    # Off unless a scenario enables it - see fi_db.market_is_open.
    if not fi_db.market_is_open(conn, "option_surface"):
        return

    results = {}
    for security in config.PEER_GROUP_SECURITIES:
        surface = provider.get_option_surface(security)
        results[security] = scan_for_anomaly(surface)

        # Observe market conditions from every surface, triggering or not -
        # the regime is a property of the whole market, so sampling only the
        # anomalous names would characterize anomalies rather than conditions.
        # This is pure observation; whether the conditions have drifted far
        # enough to invalidate a lens is COO's judgment, not Explorer's.
        #
        # A forced anomaly does inflate both statistics slightly (a +0.40 bump
        # across 45 cells adds ~0.009 to the mean, more to dispersion). That is
        # correct - an anomalous market genuinely is different - but it is
        # visible in the numbers and is not a bug.
        ivs = [point.iv for point in surface.points]
        if len(ivs) > 1:
            fi_db.update_market_regime(conn, security, statistics.mean(ivs), statistics.stdev(ivs))

    triggering = {
        security: best for security, best in results.items()
        if best is not None and best[0] >= threshold
    }

    for security, (ratio, _si, _ei, peak_iv, baseline_iv) in triggering.items():
        # Co-movement is judged **within the security's own peer group**
        # (addendum 8 §4 step 3). Counting every triggering security across all
        # groups would call three unrelated names moving on three unrelated
        # causes a "common factor", which is the opposite of what the
        # classification is for.
        group_name = config.group_of(security)
        members = set(config.group_members(security))
        co_triggering = [s for s in triggering if s != security and s in members]
        scope = "peer" if len(co_triggering) >= config.PEER_MIN_COOCCURRING else "individual"
        peer_context = json.dumps({
            "peer_group_name": group_name,
            "peer_group_version": config.PEER_GROUP_VERSION,
            "co_triggering": co_triggering,
            "group_size": len(members),
            # Across every group, for context. Deliberately separate from
            # co_triggering: a market-wide day and a sector event look
            # identical if you only record one of these numbers.
            "triggering_count": len(triggering),
            "triggering_across_all_groups": sorted(triggering),
        })

        event_id = fi_db.record_detector_event(
            conn, identity, spawned_at, security, DETECTOR_TYPE,
            peak_iv, baseline_iv, ratio, threshold,
            neighborhood_desc=neighborhood_desc, surface_seed=str(config.MARKET_PROVIDER_SEED),
            scope=scope, peer_group_name=group_name,
            peer_group_version=config.PEER_GROUP_VERSION, peer_context=peer_context,
            lens_artifact_id=lens_artifact_id,
        )

        if fi_db.has_pending_report(conn, identity, security):
            # A report from this producer+security is still unconsumed -
            # don't spend an LLM call on the judgment gate for nothing.
            continue
        if fi_db.has_open_cross_check(conn, identity, security):
            # Likewise for a question already out on this security. Checked
            # *before* the judgment gate, not after: a static forced-anomaly
            # surface re-triggers every cycle, so guarding after the call would
            # burn an LLM call per cycle for a lead already in flight.
            continue

        # A fresh heartbeat immediately before *each* judgment-gate call,
        # not just once at the start of this cycle - with a peer group,
        # multiple securities can trigger (and each need their own LLM
        # call) in the same cycle, and each individual gap must stay under
        # agents/coo.py's HEALTH_STALE_THRESHOLD_SECONDS, not the
        # cumulative sum across the whole loop. See that constant's
        # docstring for the concurrency bug this guards against.
        fi_db.record_heartbeat(conn, identity)
        passed, note = _judgment_gate(security, ratio, peak_iv, baseline_iv)
        fi_db.record_detector_judgment(conn, event_id, passed, note)
        if not passed:
            continue

        # The candidate does not become a report here. Addendum 12 §14 requires
        # a lead to be cross-checked before escalation, so Explorer asks
        # Speculator for contextual corroboration and files on a later cycle
        # once an answer (or a timeout) comes back - see _file_cross_checked_reports.
        #
        # The finding recorded here is Explorer's own, formed with no knowledge
        # of what Speculator will say. That ordering is the point: "investigate
        # independently first, then cross-check."
        fi_db.open_cross_check(
            conn, identity, spawned_at, ROLE, "speculator", security,
            question=(
                f"Explorer detected an IV surface dislocation on {security} "
                f"(peak/local-baseline ratio {ratio:.2f} against threshold {threshold}). "
                "Is there contextual evidence of unusual attention on this security, "
                "and how broadly is it sourced?"
            ),
            requester_finding={
                "detector": DETECTOR_TYPE,
                "ratio": round(ratio, 4),
                "peak_iv": round(peak_iv, 4),
                "baseline_iv": round(baseline_iv, 4),
                "threshold": threshold,
                "scope": scope,
                "co_triggering": co_triggering,
                "detector_event_id": event_id,
                "lens_artifact_id": lens_artifact_id,
            },
            requester_confidence=None,
        )


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.explorer <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]
    anomalies = {security: {} for security in config.FORCE_ANOMALY_SECURITIES}
    anomalies.update(config.ANOMALY_SPEC)
    provider = SyntheticMarketDataProvider(
        seed=config.MARKET_PROVIDER_SEED, anomalies=anomalies, regime=config.MARKET_REGIME,
    )
    spawned_at_cache: dict = {}

    def work_fn(conn) -> None:
        if "value" not in spawned_at_cache:
            agent = fi_db.get_agent(conn, identity)
            spawned_at_cache["value"] = agent["spawned_at"] if agent else None
        _explorer_work(conn, identity, spawned_at_cache["value"], provider)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":
    main()
