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


def _cross_check_lines(conn, report: dict) -> list[str]:
    """Both sides of the cross-check, presented unreconciled.

    Neither discovery agent judges whether the two findings agree; both are
    handed over as stated, and this role forms that judgment. Do not add a
    computed agree/disagree verdict here or upstream.

    Internal rationale: INT-PHIL-0010"""
    if report.get("cross_check_id") is None:
        return []
    request = fi_db.get_cross_check(conn, report["cross_check_id"])
    if request is None:
        return []

    lines = [
        "",
        "Cross-check (independent second opinion, addendum_12 §14):",
        f"  Question asked: {request['question']}",
        f"  Asked by {request['requester_role']}, answered by {request['responder_role'] } "
        f"- outcome: {request['outcome']}",
        f"  {request['requester_role']} found: {request['requester_finding']}",
    ]
    if request["responder_finding"]:
        lines.append(f"  {request['responder_role']} found: {request['responder_finding']}")

    if request["outcome"] == fi_db.CROSS_CHECK_UNANSWERED:
        lines.append(
            "  NOTE: nobody answered before the request timed out. Absence of a second opinion is "
            "not evidence either way - treat this lead as uncorroborated rather than contradicted."
        )
    elif request["outcome"] == fi_db.CROSS_CHECK_NO_EVIDENCE:
        lines.append(
            "  NOTE: the responder looked and found nothing. That is a real finding, distinct from "
            "disagreement, and distinct from never having been asked."
        )

    lines.append(
        "  These two findings have NOT been reconciled by anyone. Neither agent judged whether they "
        "agree - that judgment is yours. Weigh them against each other explicitly, and say so in "
        "thesis and uncertainty if they point in different directions. Note especially that a high "
        "post count from very few distinct authors is coordinated noise rather than a crowd, and "
        "that loud chatter explaining an anomaly away is evidence against it, not for it."
    )
    return lines


def _assemble_context(conn, report: dict) -> str:
    """Detector event (Explorer's quantitative evidence, including its
    addendum_7 §5 peer-vs-individual classification and peer_context) if
    present, normalized social evidence (Speculator's) if present, and a
    recency note against this security's own recent analysis history - a
    novelty signal distinct from peer analysis (which compares across
    securities in the same cycle, not across time for the same security)."""
    lines = [f"Security: {report['security']}", f"Report type: {report['report_type']}", f"Summary: {report['summary']}"]
    lines += _cross_check_lines(conn, report)

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
            lines.append(
                f"  - [confidence {item['confidence']:.2f}]"
                f"{_source_note(conn, item['source'])} {item['content']}"
            )
        lines.append(
            "  Source standings above are earned from how past reports built on each source were "
            "graded - they are not assigned reputations. Weigh them; do not treat a low standing as "
            "grounds to ignore an item, and do not treat a high one as grounds to accept it."
        )

    novelty = fi_db.assess_report_novelty(conn, report)
    if novelty["is_novel"]:
        lines.append("")
        lines.append(f"NOVELTY: this lead has no precedent - {novelty['summary']}.")
        lines.append(
            "  That is a structural fact about the system's records, not a judgment that the lead is "
            "important. Nothing here has been seen before, so there is less to pattern-match against "
            "and more reason to reason from first principles. Weigh it yourself, and set "
            "novelty_score on what you conclude rather than on this note."
        )

    questions = fi_db.open_questions_for(conn, report["security"])
    if questions:
        lines.append("")
        lines.append("Open questions the organization has already raised about this security:")
        lines += [f"  [#{q['id']}] {q['statement']}" for q in questions]
        lines.append(
            "  These are unresolved, not settled. If - and only if - your analysis genuinely answers "
            "one, list its number in resolved_question_ids. Leave it open when you are unsure: "
            "carrying a settled question costs little, while closing a live one loses it. Do not "
            "silently drop a question you did not answer."
        )

    recent = fi_db.list_recent_analysis_results(conn, report["security"], config.ANALYSIS_RECENCY_WINDOW_SECONDS)
    if recent:
        lines.append(
            f"Note: {len(recent)} analysis result(s) already produced for this security in the "
            f"last {config.ANALYSIS_RECENCY_WINDOW_SECONDS:.0f}s - factor this into your novelty_score."
        )

    return "\n".join(lines)


def _source_note(conn, source) -> str:
    """How this evidence item's source has been graded historically.

    Labelled, never filtered: a poorly-rated source still has its evidence
    collected and still reaches this role. Nothing in the evidence path may
    consult the standing to decide what to gather.

    An unearned standing is reported as such rather than as a middling number.

    Internal rationale: INT-PHIL-0008"""
    if not source:
        return ""
    standing = fi_db.source_standing(conn, source)
    if standing is None or not standing["stated"]:
        return f" [source {source}: standing not yet earned]"
    return (
        f" [source {source}: mean evidence quality {standing['mean_evidence_quality']:.2f}"
        f" over {standing['graded_contributions']} graded contributions]"
    )


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
        '"resolved_question_ids": [<numbers of any open questions listed in the context that this '
        'analysis genuinely answers - use [] when in doubt, since carrying a settled question costs '
        'little and closing a live one loses it>], '
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


def _record_open_question(conn, identity: str, security: str, result: dict, analysis_result_id: int) -> None:
    """Preserve what this analysis said might make it wrong.

    `uncertainty` has always been recorded and never read again - written into
    analysis_results and left there. Gap analysis §4.1 lists "unresolved
    questions" as one of the things a knowledge store must hold, and this is the
    system's only real source of them.

    Deliberately not written for every analysis. A question the organization
    should carry forward is worth recording; boilerplate hedging on a lead the
    grader itself judged not worth the compute is not, and recording it would
    bury the real questions under the routine ones."""
    uncertainty = (result.get("uncertainty") or "").strip()
    if not uncertainty or not result.get("worth_the_compute"):
        return
    if fi_db.knowledge_exists(conn, fi_db.KNOWLEDGE_OPEN_QUESTION, uncertainty):
        return
    fi_db.record_knowledge(
        conn, fi_db.KNOWLEDGE_OPEN_QUESTION, uncertainty, recorded_by=identity,
        subject=security, rationale=result.get("thesis"),
        evidence_ref=f"analysis_results:{analysis_result_id}",
        confidence=result.get("confidence"),
    )


def _resolve_answered_questions(conn, security: str, result: dict, analysis_result_id: int) -> None:
    """Close the open questions this analysis says it answered.

    Two guards, both about not trusting a model's bookkeeping:

    - **Only questions that were actually shown can be closed.** The ids are
      re-read from the store and intersected with what the model was given, so a
      hallucinated or stale id cannot retire a question the analysis never saw.
      Without this, one malformed response could silently empty the store.
    - **What closed it is recorded.** A question retired with no trace of what
      answered it is worse than one left open, because the organization would
      have stopped carrying it while being unable to say why.

    A model that resolves nothing is behaving correctly; the prompt asks it to
    leave questions open when unsure, since carrying a settled question costs
    little and closing a live one loses it."""
    claimed = result.get("resolved_question_ids") or []
    if not claimed:
        return
    presented = {q["id"] for q in fi_db.open_questions_for(conn, security)}
    for question_id in claimed:
        if question_id in presented:
            fi_db.resolve_knowledge(
                conn, question_id, resolved_by_ref=f"analysis_results:{analysis_result_id}"
            )


def _analysis_work(conn, identity: str, spawned_at: str) -> None:
    # Prioritised rather than FIFO: at ten securities detection outpaces
    # reasoning (gap analysis §4.3b), so which lead gets the one deep-reasoning
    # call per cycle stops being an accident of arrival order and becomes a
    # stated choice - with the reason recorded, since an unexplained ordering
    # is not auditable.
    # Claims before working rather than after. The claim is what makes a second
    # judgment agent safe: reading the queue and analysing without one leaves a
    # twenty-second window in which two agents own the same report.
    #
    # Released claims come first, so a report abandoned by an agent that died
    # mid-analysis is back in this pass's queue rather than stuck out of
    # circulation - and stuck matters more than it sounds, because
    # has_pending_report still counts it, so that security would go silent.
    reclaimed = fi_db.release_stale_claims(conn)
    if reclaimed:
        print(f"[analysis] returned {reclaimed} abandoned report(s) to the queue")

    report = fi_db.claim_next_report(conn, identity, spawned_at)
    if report is None:
        return  # idle - the signal a later increment's starvation scaling will consume
    print(f"[analysis] taking report #{report['id']} ({report['security']}): {report['triage_reason']}")

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
        _record_open_question(conn, identity, report["security"], result, analysis_result_id)
        _resolve_answered_questions(conn, report["security"], result, analysis_result_id)
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
