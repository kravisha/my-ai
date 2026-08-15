"""Explorer: the Discovery Slice's deterministic-detection role (addendum_7
§2, addendum_10 §5). Constructs/inspects an option implied-volatility
surface for one security (this increment - addendum_8 §4's own progression
starts at one, see agents/discovery_config.py), runs the Peak IV / Local
Baseline IV >= threshold detector (addendum_7 §4), and - only after the
deterministic detector produces a candidate - uses a lightweight LLM
judgment gate before filing a report (addendum_7 §2 last bullet: "Use
lightweight LLM judgment only after a deterministic detector has produced a
candidate and superficial interpretation is needed before filing a
report").

Individual analysis only - peer analysis (addendum_7 §5) needs multiple
securities and explicit peer groups, out of scope for this increment
(detector_events.scope is always 'individual').

Run directly as: python -m agents.explorer <identity>
Normally launched by backend/coordinator.py as a subprocess, not by hand.
"""

import json
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


def _explorer_work(conn, identity: str, spawned_at: str, provider) -> None:
    security = config.SECURITY
    surface = provider.get_option_surface(security)
    best = scan_for_anomaly(surface)
    if best is None:
        return
    ratio, _si, _ei, peak_iv, baseline_iv = best
    if ratio < config.IV_RATIO_THRESHOLD:
        return

    neighborhood_desc = f"strike idx ±{config.NEIGHBORHOOD_STRIKE_RADIUS}, expiry idx ±{config.NEIGHBORHOOD_EXPIRY_RADIUS}"
    event_id = fi_db.record_detector_event(
        conn, identity, spawned_at, security, DETECTOR_TYPE,
        peak_iv, baseline_iv, ratio, config.IV_RATIO_THRESHOLD,
        neighborhood_desc=neighborhood_desc, surface_seed=str(config.MARKET_PROVIDER_SEED),
    )

    if fi_db.has_pending_report(conn, identity, security):
        # A report from this producer+security is still unconsumed - don't
        # spend an LLM call on the judgment gate for nothing this cycle.
        return

    # A fresh heartbeat right before the one network call in this cycle -
    # see agents/coo.py's HEALTH_STALE_THRESHOLD_SECONDS docstring for why
    # (the same false-crash-detection bug applies here too, even though
    # this call's max_tokens is much smaller and usually faster).
    fi_db.record_heartbeat(conn, identity)
    passed, note = _judgment_gate(security, ratio, peak_iv, baseline_iv)
    fi_db.record_detector_judgment(conn, event_id, passed, note)
    if not passed:
        return

    fi_db.enqueue_report(
        conn, identity, spawned_at, "explorer", security,
        summary=f"IV surface anomaly on {security}: ratio {ratio:.2f} (peak {peak_iv:.4f} vs baseline {baseline_iv:.4f})",
        detector_event_id=event_id, evidence_ids=[], judgment_confidence=None,
    )


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.explorer <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]
    provider = SyntheticMarketDataProvider(seed=config.MARKET_PROVIDER_SEED, force_anomaly=config.FORCE_ANOMALY)
    spawned_at_cache: dict = {}

    def work_fn(conn) -> None:
        if "value" not in spawned_at_cache:
            agent = fi_db.get_agent(conn, identity)
            spawned_at_cache["value"] = agent["spawned_at"] if agent else None
        _explorer_work(conn, identity, spawned_at_cache["value"], provider)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":
    main()
