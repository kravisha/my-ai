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
from backend import fi_db
from providers.market_data import EXPIRIES_DAYS, STRIKES, SyntheticMarketDataProvider

ROLE = "explorer"
DETECTOR_TYPE = "iv_surface_peak_ratio"
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

    # Scan every peer-group security independently first, so classification
    # (below) can ask "how many others also triggered this same cycle"
    # without re-scanning anything.
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
