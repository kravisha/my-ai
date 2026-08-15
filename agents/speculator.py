"""Speculator: the Discovery Slice's social-evidence role (addendum_7 §3,
addendum_10 §5). Searches a synthetic social/context stream for one
security (this increment - see agents/discovery_config.py), normalizes
observations into structured evidence with source/timestamp/confidence, and
files a report when new evidence's confidence clears a threshold.

Deliberately no LLM call here - normalization and the report-filing gate
stay deterministic (Explorer/Speculator stay procedural; deep reasoning is
Analysis's job alone, addendum_7 §6). "Corroboration" beyond a single
post's own confidence isn't built this increment - narrower than what a
later increment (more securities, a real Reddit provider) would want to
design properly, so left alone rather than guessed at now.

Run directly as: python -m agents.speculator <identity>
Normally launched by backend/coordinator.py as a subprocess, not by hand.
"""

import sys

from agents import discovery_config as config
from agents.base import run_agent
from backend import fi_db
from providers.social_data import SyntheticSocialDataProvider

ROLE = "speculator"


def _speculator_work(conn, identity: str, spawned_at: str, provider, cursor_state: dict) -> None:
    security = config.SECURITY
    posts = provider.fetch_recent(security, since=cursor_state.get("since"))
    if not posts:
        return

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

    cursor_state["since"] = posts[-1].posted_at

    if max_confidence < config.SPECULATOR_CONFIDENCE_THRESHOLD:
        return
    if fi_db.has_pending_report(conn, identity, security):
        return

    fi_db.enqueue_report(
        conn, identity, spawned_at, "speculator", security,
        summary=f"Social evidence on {security}: {len(new_evidence_ids)} new post(s), max confidence {max_confidence:.2f}",
        detector_event_id=None, evidence_ids=new_evidence_ids, judgment_confidence=max_confidence,
    )


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.speculator <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]
    provider = SyntheticSocialDataProvider(seed=config.SOCIAL_PROVIDER_SEED)
    spawned_at_cache: dict = {}
    cursor_state: dict = {}

    def work_fn(conn) -> None:
        if "value" not in spawned_at_cache:
            agent = fi_db.get_agent(conn, identity)
            spawned_at_cache["value"] = agent["spawned_at"] if agent else None
        _speculator_work(conn, identity, spawned_at_cache["value"], provider, cursor_state)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":
    main()
