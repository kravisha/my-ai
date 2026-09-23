"""What a turn writes into the life ledger, and what it deliberately does not.

Until this module existed, everything in `gateway/ledger.py` was real and
almost nothing wrote to it: after a restart the ledger held a series of boot
reports and nothing else. The mechanism passed its tests because the tests
wrote the events; in a conversation nothing did. This is the producer.

## §5 is the design constraint, not an afterthought

    *"The life ledger is not intended to be a dump of every generated token."*

So this records **transactions**, and the list is short and deterministic:

- one `user_request` per turn, as a 200-character summary;
- `action_failed` for every tool call that errored;
- `action_succeeded` only for tools that *changed something*, decided by
  reading `gateway/tools.TOOL_RISK` rather than by a second list here - a tool
  whose declared reach is `self` and whose reversibility is `reversible` did
  not change the world and does not belong in a history of what happened;
- the partial-answer case, where the turn ran out of tool rounds.

Everything else a turn produces - the prose, the intermediate model calls, the
reads - is in `gateway.db` and `logs/model_calls.jsonl` already, and copying it
here would produce exactly the dump §5 rules out.

## The summary, not the sentence

§8 asks what retention the raw conversation references should have. The answer
taken here is that the ledger holds a *reference and a summary*, never the
text: `model_calls.summarise` is the same 200-character function the call log
has used all along, so the two agree about what a request looked like. The full
text stays in `gateway.db`, which is where the conversation lives and where the
privacy boundary already applies.

## Operator turns only

A client's turn is not recorded here. Every record this system writes is keyed
`agent="jarvis"`, so a client's request summary would land in Jarvis's own life
ledger, readable by Krish through his own memory tools. That is a privacy
regression arriving by the back door of a feature about continuity. Client
conversations stay in `gateway.db` where they already are, and this is a
decision to revisit when client agents have identities of their own.

## A failure here never costs a turn, and is never silent

The DBA can be down. A turn must still work - Jarvis operating without memory
is the honest degraded state, and killing the user's request over it would be
the worst possible trade. So every write is guarded, and a failure is
**counted, logged, and recorded as a capability gap**, which puts it in the
monthly ranked report Krish already reads rather than in a log nobody opens.
"""

from __future__ import annotations

import logging
from typing import Any

from app import capability_gaps, model_calls
from gateway import dbaclient, identity, ledger

logger = logging.getLogger("gateway.recording")

# The ceiling on anything derived from what Krish typed. The same number the
# call log has used all along, reused rather than chosen again so the two agree
# about what a request looked like.
#
# Applied HERE and not left to `ledger.append`'s own truncation, which happens
# to be the same 200 today. Relying on that would make this module's promise -
# that the ledger holds a summary and never the sentence - depend on a constant
# in another module that nobody would think to check before raising.
SUMMARY_CHARS = model_calls.SUMMARY_CHARS


def summarise(text: str | None) -> str:
    """What goes in the ledger in place of what was said."""
    return (model_calls.summarise(text) or "")[:SUMMARY_CHARS]

# Which tools are worth an `action_succeeded` event. Derived from the risk
# declaration every tool already carries, so a new tool is classified by the
# same statement that decides whether it needs confirming - and a tool added
# without a risk entry is refused by `tools.execute` long before it reaches
# here.
def _changed_something(name: str) -> bool:
    from app import initiative
    from gateway import tools

    declared = tools.TOOL_RISK.get(name)
    if declared is None:
        return False
    return (declared.get("reach") != initiative.SELF
            or declared.get("reversibility") != initiative.REVERSIBLE)


class Recorder:
    """Records one turn. Created per turn, holds nothing between them.

    `enabled` is False when no DBA token is configured, and then every method
    is a no-op that says so once rather than raising on each call. That is the
    developer-checkout case, and a Gateway that refused to answer because it
    could not write its diary would be useless for the reason least worth
    being useless for."""

    def __init__(self, *, role: str, subject: str | None,
                 conversation_id: int | None = None,
                 client: dbaclient.DBAClient | None = None) -> None:
        from gateway import roles

        self.role = role
        self.subject = subject
        self.session_id = (f"conversation:{conversation_id}"
                           if conversation_id is not None else None)
        self.problems: list[str] = []
        self.written = 0
        # Operator turns only - see the module docstring.
        self.enabled = (role == roles.ROLE_OPERATOR
                        and dbaclient.is_configured())
        self._client = client
        if client is not None:
            self.enabled = role == roles.ROLE_OPERATOR

    # --- the one place a write happens ---------------------------------------

    def _append(self, **fields: Any) -> None:
        if not self.enabled:
            return
        try:
            client = self._client or dbaclient.DBAClient(actor="conversation")
            self._client = client
            ledger.append(client, session_id=self.session_id,
                          actor=self.subject or "operator",
                          agent=identity.AGENT_ID, **fields)
            self.written += 1
        except (ledger.LedgerWriteFailed, ledger.ChainBroken,
                dbaclient.Unavailable, dbaclient.Refused, ValueError) as exc:
            self._failed(fields.get("event_type", "event"), exc)

    def _failed(self, what: str, exc: BaseException) -> None:
        """A missed write is a capability gap, not a swallowed exception.

        Filed against the detector `app/capability_gaps.py` because that is
        what produces the ranked monthly report Krish reads. A warning in a log
        is a thing nobody sees; a gap that recurs is a line in a report sorted
        by how often it happened."""
        message = f"could not record a {what} in the life ledger: {exc}"
        self.problems.append(message)
        logger.warning("%s", message)
        capability_gaps.record(
            gap_type=capability_gaps.GAP_MISSING_INTEGRATION,
            what_was_needed="a reachable DBA Agent to record this turn's "
                            "events in the life ledger",
            user_visible_outcome="the turn worked; it was not remembered",
            request_summary=message[:200])

    # --- what a turn records --------------------------------------------------

    def request(self, text: str) -> None:
        """One event per turn, carrying a summary and never the sentence."""
        self._append(event_type=ledger.USER_REQUEST,
                     summary=summarise(text) or "(an empty request)",
                     verification_state=ledger.ASSERTED_BY_USER,
                     origin="gateway", origin_id=self.session_id)

    def tool_failed(self, name: str, detail: str) -> None:
        self._append(event_type=ledger.ACTION_FAILED,
                     summary=f"{name} failed",
                     observation=str(detail)[:1000],
                     verification_state=ledger.VERIFIED,
                     risk_level="medium")

    def tool_succeeded(self, name: str) -> None:
        """Only for tools that changed something - see `_changed_something`."""
        if not _changed_something(name):
            return
        self._append(event_type=ledger.ACTION_SUCCEEDED,
                     summary=f"{name} succeeded",
                     verification_state=ledger.VERIFIED)

    def answered_only_partially(self, detail: str) -> None:
        self._append(event_type=ledger.ACTION_FAILED,
                     summary="ran out of tool rounds without reaching an answer",
                     observation=str(detail)[:1000],
                     verification_state=ledger.VERIFIED,
                     risk_level="high")

    # --- what the caller can say about it ------------------------------------

    def report(self) -> dict:
        return {"enabled": self.enabled, "written": self.written,
                "problems": list(self.problems)}
