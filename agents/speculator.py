"""Speculator: the Discovery Slice's social-evidence role (addendum_7 §3,
addendum_10 §5). Each cycle, searches a synthetic social/context stream for
every security in the configured peer group (agents/discovery_config.py's
PEER_GROUP_SECURITIES - the same group Explorer scans, so all three agents
operate over consistent scope), normalizes observations into structured
evidence with source/timestamp/confidence, and files a report per security
when that security's new evidence confidence clears a threshold.

No peer-comparison logic of its own - addendum_7 §5 ("Individual vs Peer
Analysis") is written entirely in surface/spike language, Explorer's
domain. Speculator's reports never carry a detector_event_id, so there's no
row for peer/scope fields to attach to even if the spec asked for it.

Normalization and the report-filing gate stay deterministic. There is now
one small LLM call, `_read_stance`, used only when answering a cross-check -
the same shape and spirit as agents/explorer.py's `_judgment_gate`, and for
the same reason. A message board is a verbal medium: post counts invert the
answer outright, since a crowd loudly explaining a move away generates more
traffic than a quiet crowd confirming it. Reading is the only way to tell
those apart, and no amount of counting substitutes for it.

Speculator still does not reason. It reports what the crowd appears to be
saying and how broadly it is sourced; whether that corroborates a
quantitative dislocation is Analysis's judgment alone (addendum_7 §6).

Run directly as: python -m agents.speculator <identity>
Normally launched by backend/controller.py as a subprocess, not by hand.
"""

import json
import sys

from agents import discovery_config as config
from agents.base import run_agent
from app.model_gateway import call_reasoning_model
from backend import fi_db, reference_data
from providers.social_data import SyntheticSocialDataProvider
from providers.stored_data import StoredSocialProvider

ROLE = "speculator"

# How many posts the stance read is shown. Batched into one call covering the
# highest-engagement posts rather than one call per post: Speculator sees up to
# a few posts per security per cycle across the whole peer group, and
# classifying every one of them individually would be thousands of calls for a
# question that a handful of representative posts answers.
STANCE_SAMPLE_SIZE = 8
STANCE_MAX_TOKENS = 300

# How many recently observed posts to retain per security for answering
# cross-checks. Bounded so a long-lived process cannot grow without limit.
SEEN_WINDOW = 40


def _extract_text(response) -> str:
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _file_cross_checked_reports(conn, identity: str, spawned_at: str, lens_artifact_id) -> None:
    """File Speculator-originated leads once Explorer has answered.

    Filed whatever the answer says, for the same reason Explorer does: dropping
    a lead because the other side disagreed would let the originator adjudicate
    its own case, and the dissent is exactly what Analysis needs to see."""
    for request in fi_db.fetch_resolved_cross_checks(conn, identity):
        finding = json.loads(request["requester_finding"])
        security = request["security"]

        if not fi_db.has_pending_report(conn, identity, security):
            fi_db.enqueue_report(
                conn, identity, spawned_at, "speculator", security,
                summary=(
                    f"Social evidence on {security}: max confidence "
                    f"{finding['max_confidence']:.2f} across {finding.get('posts', 0)} post(s) "
                    f"from {finding.get('distinct_authors', 0)} author(s); "
                    f"cross-check {request['outcome']}"
                ),
                detector_event_id=None,
                evidence_ids=finding.get("evidence_ids", []),
                judgment_confidence=finding["max_confidence"],
                lens_artifact_id=finding.get("lens_artifact_id", lens_artifact_id),
                cross_check_id=request["id"],
            )
        fi_db.consume_cross_check(conn, request["id"])


def _source_dispersion(posts: list) -> dict:
    """How many distinct voices the chatter came from.

    Deterministic and model-free by design: ten posts from three accounts are
    textually indistinguishable from ten from ten, so this signal is a count
    rather than a reading. It is the second, independent frame alongside stance.

    Internal rationale: INT-PHIL-0011"""
    if not posts:
        return {"posts": 0, "distinct_authors": 0, "posts_per_author": 0.0}
    authors = len(set(post.author for post in posts))
    return {
        "posts": len(posts),
        "distinct_authors": authors,
        "posts_per_author": round(len(posts) / authors, 2),
    }


def _read_stance(security: str, posts: list, question: str) -> dict:
    """Read what the chatter is actually saying about the security.

    A message board is a verbal medium, so the information is in the words. Post
    counts invert the answer outright: a crowd loudly explaining a move away
    generates *more* traffic than a quiet crowd confirming it, so ranking by
    volume promotes exactly the wrong lead. Only reading resolves that.

    Mirrors agents/explorer.py's `_judgment_gate` in shape and spirit - one
    small, cheap, tightly-scoped call inside an otherwise procedural agent, not
    deep reasoning. Speculator reports what the crowd appears to be saying; what
    that *means* alongside quantitative evidence stays with Analysis.

    A parse failure degrades to 'unclear' rather than raising: an unreadable
    stance must still let the cross-check be answered from the deterministic
    signals, never stall the requester."""
    sample = sorted(posts, key=lambda p: p.engagement_score, reverse=True)[:STANCE_SAMPLE_SIZE]
    system = (
        "You read retail investor message-board chatter about one security and "
        "report what the crowd appears to be claiming. You are not judging "
        "whether they are right, and not producing an investment view. Reply "
        "with strict JSON only, no other text: "
        '{"stance": "supports" or "undercuts" or "unclear", '
        '"summary": "one short sentence", "strength": <0.0-1.0>}. '
        '"supports" means the chatter is consistent with something genuinely '
        'unusual happening; "undercuts" means it explains the activity away as '
        'ordinary, mistaken, or already resolved; "unclear" means the posts do '
        "not settle it. strength is how clearly the posts point that way."
    )
    user_content = "\n".join(
        [f"Security: {security}", f"Question being answered: {question}", "", "Posts:"]
        + [f"- ({post.engagement_score:.2f}) {post.text}" for post in sample]
    )
    try:
        response = call_reasoning_model(
            system=system,
            messages=[{"role": "user", "content": user_content}],
            tools=[],
            max_tokens=STANCE_MAX_TOKENS,
        )
        parsed = json.loads(_extract_text(response))
        stance = parsed.get("stance")
        if stance not in ("supports", "undercuts", "unclear"):
            return {"stance": "unclear", "summary": f"unexpected stance {stance!r}", "strength": None}
        return {
            "stance": stance,
            "summary": parsed.get("summary"),
            "strength": parsed.get("strength"),
        }
    except Exception as exc:
        return {"stance": "unclear", "summary": f"stance read unavailable: {exc}", "strength": None}


def _answer_pending_cross_checks(conn, identity: str, spawned_at: str, seen: dict) -> None:
    """Answer Explorer's request for contextual corroboration.

    Answers from evidence already recorded in the database rather than from a
    fresh provider fetch, so the response describes what Speculator genuinely
    observed on its own schedule - the independent investigation §14 asks for,
    rather than a lookup performed on Explorer's behalf.

    Reports both frames and reconciles neither. Whether 'a quiet, broadly
    sourced crowd saying supports' corroborates an IV dislocation is a reasoning
    judgment, and Speculator is procedural."""
    request = fi_db.fetch_next_pending_cross_check(conn, ROLE)
    if request is None:
        return

    security = request["security"]
    posts = seen.get(security, [])
    if not posts:
        # Looked and found nothing. A real answer, and a different finding from
        # disagreement - which is why 'no_evidence' is its own outcome.
        fi_db.answer_cross_check(
            conn, request["id"], identity, spawned_at, fi_db.CROSS_CHECK_NO_EVIDENCE,
            {"posts": 0, "note": "no social evidence observed for this security"},
        )
        return

    fi_db.record_heartbeat(conn, identity)
    dispersion = _source_dispersion(posts)
    stance = _read_stance(security, posts, request["question"])
    fi_db.answer_cross_check(
        conn, request["id"], identity, spawned_at, fi_db.CROSS_CHECK_EVIDENCE,
        {
            **dispersion,
            "max_confidence": round(max(p.engagement_score for p in posts), 3),
            "stance": stance["stance"],
            "stance_summary": stance["summary"],
            "stance_strength": stance["strength"],
            "sample": [p.text for p in sorted(posts, key=lambda p: p.engagement_score, reverse=True)[:3]],
        },
        responder_confidence=stance["strength"],
    )


def _speculator_work(
    conn, identity: str, spawned_at: str, provider, cursor_state: dict, seen: dict | None = None,
    stored_cursor: dict | None = None,
) -> None:
    """cursor_state is a flat dict keyed by security (not nested) - each
    security in the peer group tracks its own "since" cursor independently.

    seen is the same shape: the rolling window of posts this process has
    observed per security, which is what cross-check answers are drawn from.

    stored_cursor is cursor_state's counterpart for the Data Store's stored
    mission chatter (SPEC_RECONCILIATION.md SS39-SS41) - a second, keyed-by-
    symbol "since" cursor, independent of the synthetic provider's own, so
    reading one feed's cursor never advances past what the other has
    actually consumed."""
    seen = {} if seen is None else seen
    stored_cursor = {} if stored_cursor is None else stored_cursor
    # Resolved from the intelligence store rather than a constant, for the
    # same reasons as agents/explorer.py's threshold - see that comment. The
    # confidence bar is what decides which social evidence is worth escalating,
    # so it is intelligence and needs to be attributable and expirable.
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_SPECULATOR_CONFIDENCE_NAME)
    lens_artifact_id = lens["id"] if lens else None
    confidence_threshold = json.loads(lens["value"]) if lens else fi_db.LENS_SPECULATOR_CONFIDENCE_SEED

    fi_db.expire_stale_cross_checks(conn)
    _file_cross_checked_reports(conn, identity, spawned_at, lens_artifact_id)

    for security in config.PEER_GROUP_SECURITIES:
        posts = provider.fetch_recent(security, since=cursor_state.get(security))
        if not posts:
            continue

        # A bounded rolling window of what this process has actually observed,
        # used to answer cross-checks. Process-local like cursor_state, and
        # resets on respawn for the same reason: it represents what *this life*
        # of the agent has seen. A freshly respawned Speculator answers
        # 'no_evidence' until it has observed a cycle or two, which is honest -
        # it genuinely has not looked yet.
        seen[security] = (seen.get(security, []) + posts)[-SEEN_WINDOW:]

        new_evidence_ids = []
        max_confidence = 0.0
        for post in posts:
            evidence_id = fi_db.record_evidence_item(
                conn, identity, spawned_at, "social", security,
                source=post.source, observed_at=post.posted_at, content=post.text,
                confidence=post.engagement_score, raw_ref=f"{post.source}:{post.author}:{post.posted_at}",
            )
            new_evidence_ids.append(evidence_id)
            max_confidence = max(max_confidence, post.engagement_score)

        cursor_state[security] = posts[-1].posted_at

        if max_confidence < confidence_threshold:
            continue

        # An existing case is enriched rather than blocking this observation.
        #
        # Skipping here was the defect: the case sits unjudged for as long as the
        # queue takes to reach it - measured at ~235s - and for that entire window
        # this agent could see the situation developing and had no way to say so.
        # A case is a request for judgment, so bringing it up to date discards
        # nothing; the observations are already recorded in evidence_items
        # regardless of what happens to the case.
        #
        # Deduplication is preserved: still one case per security, so the queue
        # depth ceiling that keeps this system predictable is untouched.
        case = fi_db.open_case_for(conn, identity, security)
        if case is not None:
            outcome = fi_db.enrich_case(
                conn, case["id"], new_evidence_ids,
                judgment_confidence=max_confidence,
                summary=(
                    f"Social evidence on {security}: max confidence {max_confidence:.2f}, "
                    f"updated as the situation developed"
                ),
            )
            if outcome != "gone":
                print(f"[speculator] {outcome} case #{case['id']} ({security}) "
                      f"with {len(new_evidence_ids)} new item(s)")
                continue
            # 'gone' means judgment finished it while this cycle was running, so
            # there is no open case after all and a fresh one is correct.

        if fi_db.has_open_cross_check(conn, identity, security):
            continue
        # The origination cooldown (SPEC_RECONCILIATION §58): a security whose
        # analysis chain completed recently is not re-originated on routinely
        # similar evidence - the synthetic stream clears the confidence bar
        # nearly every cycle, so without this the loop re-purchases the whole
        # cross-check -> stance-read -> report -> Analysis chain the moment
        # the previous one finishes. Evidence recording and case enrichment
        # above are deliberately NOT gated: observing is free and cases stay
        # current; it is the paid judgment chain that waits its turn.
        if fi_db.list_recent_analysis_results(conn, security, config.ORIGINATION_COOLDOWN_SECONDS):
            continue

        # Speculator originates too (§14: "Speculator may originate a lead from
        # contextual evidence and ask Explorer for quantitative corroboration").
        # Its own finding is captured now, before Explorer answers.
        fi_db.open_cross_check(
            conn, identity, spawned_at, ROLE, "explorer", security,
            question=(
                f"Speculator observed social evidence on {security} clearing its confidence "
                f"bar ({max_confidence:.2f} against {confidence_threshold}). "
                "Is there quantitative evidence of an IV surface dislocation on this security?"
            ),
            requester_finding={
                "max_confidence": round(max_confidence, 3),
                "threshold": confidence_threshold,
                "evidence_ids": new_evidence_ids,
                **_source_dispersion(seen.get(security, [])),
                "lens_artifact_id": lens_artifact_id,
            },
            requester_confidence=max_confidence,
        )

    # ARB-001's mission chatter (SPEC_RECONCILIATION.md SS39-SS41): a second,
    # independent read of the Data Store's stored social_post observations
    # (providers/stored_data.py's StoredSocialProvider), so a cross-check
    # Explorer opens for a parity detection can be answered from mission
    # chatter too. A no-op with nothing stored - fetch_recent returns []
    # for every entity until a mission has actually stored a world.
    #
    # Deliberately does NOT open a speculator-originated cross-check from
    # this feed, unlike the loop above. The parity mission's originator is
    # Explorer (agents/explorer.py's _parity_work); Speculator's role here
    # is corroboration only - recording what the mission's chatter says so
    # _answer_pending_cross_checks below can read it out of `seen`, the same
    # way it already does regardless of which feed populated that entry.
    # Speculator's own origination from chatter stays on the loop above,
    # untouched.
    stored_provider = StoredSocialProvider(conn)
    for asset in reference_data.list_focus_assets(conn):
        entity_id, symbol = asset["entity_id"], asset["primary_identifier"]
        stored_posts = stored_provider.fetch_recent(entity_id, since=stored_cursor.get(symbol))
        if not stored_posts:
            continue

        seen[symbol] = (seen.get(symbol, []) + stored_posts)[-SEEN_WINDOW:]

        for post in stored_posts:
            fi_db.record_evidence_item(
                conn, identity, spawned_at, "social", symbol,
                source=post.source, observed_at=post.posted_at, content=post.text,
                confidence=post.engagement_score, raw_ref=f"{post.source}:{post.author}:{post.posted_at}",
            )

        stored_cursor[symbol] = stored_posts[-1].posted_at

    _answer_pending_cross_checks(conn, identity, spawned_at, seen)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.speculator <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]
    provider = SyntheticSocialDataProvider(
        seed=config.SOCIAL_PROVIDER_SEED,
        narratives=config.SOCIAL_NARRATIVES,
        arcs=config.SOCIAL_ARCS,
    )
    spawned_at_cache: dict = {}
    cursor_state: dict = {}
    seen: dict = {}
    stored_cursor: dict = {}

    def work_fn(conn) -> None:
        if "value" not in spawned_at_cache:
            agent = fi_db.get_agent(conn, identity)
            spawned_at_cache["value"] = agent["spawned_at"] if agent else None
        _speculator_work(
            conn, identity, spawned_at_cache["value"], provider, cursor_state, seen,
            stored_cursor=stored_cursor,
        )

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":
    main()
