"""Analysis: the Discovery Slice's deep-reasoning role (addendum_7 §6,
addendum_10 §5). Consumes the report queue Explorer/Speculator file into,
performs the one real deep-reasoning LLM call per report (thesis, evidence,
uncertainty, confidence, reasons the idea could be wrong - addendum_7 §6
step 6), and in the same call grades the upstream report that produced it
(relevance, novelty, evidence quality, worth-the-compute - addendum_7 §8) -
closing the loop addendum_10 §10's Developer Guiding Rule asks for: who
evaluates this, what's the score, where is it persisted, how does feedback
return to the producer.

Grading and analysis are always produced together, not conditionally -
addendum_7 §6 steps 4-5 treat "perform deep reasoning" and "grade the
upstream report" as one handoff, not two separate passes.

Run directly as: python -m agents.analysis <identity>
Normally launched by backend/controller.py as a subprocess, not by hand.
"""

import json
import sys

from agents import discovery_config as config
from agents.base import run_agent
from app.model_gateway import call_reasoning_model
from backend import fi_db

ROLE = "analysis"
ANALYSIS_MAX_TOKENS = 4096

REQUIRED_FIELDS = (
    "thesis", "evidence_summary", "confidence", "uncertainty",
    "relevance_score", "novelty_score", "evidence_quality_score",
    "worth_the_compute", "rationale", "peer_classification",
)

PEER_CLASSIFICATIONS = ("common_factor", "idiosyncratic", "not_applicable")


def _extract_text(response) -> str:
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _assemble_context(conn, report: dict) -> str:
    """Detector event (Explorer's quantitative evidence, including its
    addendum_7 §5 peer-vs-individual classification and peer_context) if
    present, normalized social evidence (Speculator's) if present, and a
    recency note against this security's own recent analysis history - a
    novelty signal distinct from peer analysis (which compares across
    securities in the same cycle, not across time for the same security)."""
    lines = [f"Security: {report['security']}", f"Report type: {report['report_type']}", f"Summary: {report['summary']}"]

    if report["detector_event_id"] is not None:
        event = fi_db.get_detector_event(conn, report["detector_event_id"])
        if event is not None:
            lines.append(
                f"Detector event: {event['detector_type']}, ratio {event['ratio']:.3f} "
                f"(peak {event['peak_iv']:.4f} vs baseline {event['baseline_iv']:.4f}, "
                f"threshold {event['threshold']:.2f})"
            )
            if event["judgment_note"]:
                lines.append(f"Explorer judgment note: {event['judgment_note']}")
            if event["scope"] == "peer" and event["peer_context"]:
                peer_context = json.loads(event["peer_context"])
                lines.append(
                    f"Peer analysis (addendum_7 §5): {len(peer_context['co_triggering'])} other "
                    f"security(ies) in peer group '{peer_context['peer_group_name']}' v{peer_context['peer_group_version']} "
                    f"also triggered this same cycle: {', '.join(peer_context['co_triggering'])}. "
                    "This looks potentially market/sector/common-factor driven, not isolated to this "
                    "security - factor this into peer_classification (favor 'common_factor')."
                )
            elif event["scope"] == "individual":
                lines.append(
                    "Peer analysis (addendum_7 §5): no other security in the peer group triggered this "
                    "cycle - this anomaly is isolated. Investigate security-specific causes; factor this "
                    "into peer_classification (favor 'idiosyncratic')."
                )

    evidence_ids = json.loads(report["evidence_ids"] or "[]")
    if evidence_ids:
        evidence = fi_db.list_evidence_items(conn, evidence_ids)
        lines.append(f"Social evidence ({len(evidence)} item(s)):")
        for item in evidence:
            lines.append(f"  - [confidence {item['confidence']:.2f}] {item['content']}")

    recent = fi_db.list_recent_analysis_results(conn, report["security"], config.ANALYSIS_RECENCY_WINDOW_SECONDS)
    if recent:
        lines.append(
            f"Note: {len(recent)} analysis result(s) already produced for this security in the "
            f"last {config.ANALYSIS_RECENCY_WINDOW_SECONDS:.0f}s - factor this into your novelty_score."
        )

    return "\n".join(lines)


def _run_analysis(report_context: str) -> dict:
    system = (
        "You are Analysis, the deep-reasoning role in a financial-opportunity "
        "discovery pipeline. You receive one queued report (from a "
        "deterministic Explorer detector or a Speculator social-evidence "
        "scan) and must produce both a client-facing analysis and a grade "
        "of the upstream report in a single response. This is informational "
        "only - no trade is executed. Reply with strict JSON only, no other "
        "text, with exactly these fields: "
        '{"thesis": "...", "evidence_summary": "...", "confidence": <0.0-1.0>, '
        '"uncertainty": "...", "relevance_score": <0.0-1.0>, "novelty_score": <0.0-1.0>, '
        '"evidence_quality_score": <0.0-1.0>, "worth_the_compute": <true or false>, '
        '"rationale": "...", "peer_classification": "common_factor" or "idiosyncratic" or '
        '"not_applicable"}. thesis should include reasons the idea could be wrong. '
        'peer_classification: "common_factor" if the context says peers also triggered '
        '(market/sector-wide), "idiosyncratic" if the context says the anomaly is isolated, '
        '"not_applicable" if the context has no peer-analysis information at all (e.g. a '
        "Speculator-sourced report with no detector event)."
    )
    response = call_reasoning_model(
        system=system,
        messages=[{"role": "user", "content": report_context}],
        tools=[],
        max_tokens=ANALYSIS_MAX_TOKENS,
    )
    text = _extract_text(response)
    parsed = json.loads(text)
    missing = [f for f in REQUIRED_FIELDS if f not in parsed]
    if missing:
        raise ValueError(f"analysis response missing fields: {missing}")
    if parsed["peer_classification"] not in PEER_CLASSIFICATIONS:
        raise ValueError(f"analysis response has invalid peer_classification: {parsed['peer_classification']!r}")
    return parsed


def _overall_score(result: dict) -> float:
    return round((result["relevance_score"] + result["novelty_score"] + result["evidence_quality_score"]) / 3, 4)


def _analysis_work(conn, identity: str, spawned_at: str) -> None:
    report = fi_db.fetch_next_pending_report(conn)
    if report is None:
        return  # idle - the signal a later increment's starvation scaling will consume

    try:
        context = _assemble_context(conn, report)
        # A fresh heartbeat right before the one genuinely slow step in this
        # cycle - agents/base.py's run_agent only heartbeats after work_fn
        # returns, and this LLM call alone can take longer than that gap
        # comfortably allows for. See agents/coo.py's
        # HEALTH_STALE_THRESHOLD_SECONDS docstring for the bug this was
        # found fixing: without this, a slow-but-alive Analysis agent could
        # get wrongly marked 'crashed' and duplicated mid-call.
        fi_db.record_heartbeat(conn, identity)
        result = _run_analysis(context)
        analysis_result_id = fi_db.record_analysis_result(
            conn, identity, spawned_at, report["id"], report["security"],
            result["thesis"], result["evidence_summary"], result["confidence"], result["uncertainty"],
            peer_classification=result["peer_classification"],
        )
        fi_db.record_grade(
            conn, identity, spawned_at, report["id"], analysis_result_id,
            result["relevance_score"], result["novelty_score"], result["evidence_quality_score"],
            result["worth_the_compute"], _overall_score(result), result["rationale"],
        )
    except Exception as exc:
        fi_db.complete_report(conn, report["id"], "failed", detail=str(exc))
        return

    fi_db.complete_report(conn, report["id"], "analyzed", handled_by_identity=identity, handled_by_spawned_at=spawned_at)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.analysis <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]
    spawned_at_cache: dict = {}

    def work_fn(conn) -> None:
        if "value" not in spawned_at_cache:
            agent = fi_db.get_agent(conn, identity)
            spawned_at_cache["value"] = agent["spawned_at"] if agent else None
        _analysis_work(conn, identity, spawned_at_cache["value"])

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":
    main()
