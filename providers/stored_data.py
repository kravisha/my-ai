"""Read-side providers translating the Data Store's stored Observations
(backend/observations.py) back into the shapes agents/explorer.py and
agents/speculator.py's existing flows already expect.

Pure translation, no detection here. Explorer runs backend/arbitrage.py's
detect_arb001 itself over the ParitySnapshots this module reconstructs
(agents/explorer.py's `_parity_work`) - StoredChainProvider only rebuilds the
snapshot, it never judges whether a row is an opportunity.

## Activation is data presence

There is no flag that turns this on. With no mission world ever stored,
`latest_chain` returns None and `fetch_recent` returns [] for every entity -
every downstream code path in Explorer/Speculator that only triggers on
their output is a no-op by construction (SPEC_RECONCILIATION.md SS41's
design), the same "empty machinery is refused, not gated" precedent
backend/reference_data.py's module docstring states for its own adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend import observations as observation_store
from backend.arbitrage import ChainSnapshot, ParitySnapshot, Quote, StrikeQuotes
from backend.canonical import Observation

# StoredPost carries no source label of its own in the stored chatter payload
# (simulation/parity_world.py's build_chatter_observations does not stamp
# one - see that module's docstring on ground-truth isolation for why the
# payload only carries what a real chatter feed would). A constant stands in
# rather than inventing per-post sources the mission never generated.
MISSION_CHATTER_SOURCE = "mission_chatter"


def _quote_from_leg(leg: dict) -> Quote:
    return Quote(
        bid=leg["bid"], ask=leg["ask"], bid_size=leg["bid_size"], ask_size=leg["ask_size"],
        quoted_at=leg["quoted_at"],
    )


class StoredChainProvider:
    """Explorer's parity read side: the most recently stored option_chain
    observation for an entity, and the ParitySnapshots it decodes into."""

    def __init__(self, conn):
        self._conn = conn

    def latest_chain(self, entity_id: str) -> Observation | None:
        """The newest stored option_chain observation for this entity, or
        None if nothing has ever been stored for it (the dormant path - no
        mission world stored, module docstring)."""
        rows = observation_store.replay(self._conn, entity_id, "option_chain")
        return rows[-1] if rows else None

    def snapshots(self, observation: Observation) -> list[ParitySnapshot]:
        """One ParitySnapshot per (strike, expiry) row in the chain -
        reconstructed from exactly the fields
        simulation/parity_world.py's build_option_chain_observation payload
        carries, so this is a pure translation with nothing to compute."""
        payload = observation.payload
        underlying = _quote_from_leg(payload["underlying"])
        carry = payload["carry"]
        pv_div_by_expiry = {row["expiry_days"]: row["pv_div"] for row in carry["pv_div_by_expiry"]}
        return [
            ParitySnapshot(
                entity_id=observation.entity_id,
                symbol=payload["symbol"],
                strike=row["strike"],
                expiry_days=row["expiry_days"],
                style=payload["style"],
                as_of=payload["as_of"],
                underlying=underlying,
                call=_quote_from_leg(row["call"]),
                put=_quote_from_leg(row["put"]),
                r=carry["r"],
                pv_div=pv_div_by_expiry[row["expiry_days"]],
                borrow_fee_annual=carry["borrow_fee_annual"],
            )
            for row in payload["chain"]
        ]


def chain_snapshots(observation: Observation) -> list[ChainSnapshot]:
    """One backend/arbitrage.py ChainSnapshot per expiry in a stored
    option_chain observation - the multi-strike shape backend/arbitrage.py's
    ARB-006 through ARB-011 need (a full strike ladder for one expiry),
    beside StoredChainProvider.snapshots' existing per-(strike,expiry)
    ParitySnapshot reconstruction above. Pure translation, same fields,
    grouped by expiry_days and sorted by strike within each group (the order
    ChainSnapshot.__post_init__ requires) rather than trusting the payload's
    own row order."""
    payload = observation.payload
    underlying = _quote_from_leg(payload["underlying"])
    carry = payload["carry"]
    pv_div_by_expiry = {row["expiry_days"]: row["pv_div"] for row in carry["pv_div_by_expiry"]}

    rows_by_expiry: dict[int, list[dict]] = {}
    for row in payload["chain"]:
        rows_by_expiry.setdefault(row["expiry_days"], []).append(row)

    chains = []
    for expiry_days in sorted(rows_by_expiry):
        rows_sorted = sorted(rows_by_expiry[expiry_days], key=lambda r: r["strike"])
        strikes = tuple(
            StrikeQuotes(strike=row["strike"], call=_quote_from_leg(row["call"]), put=_quote_from_leg(row["put"]))
            for row in rows_sorted
        )
        chains.append(ChainSnapshot(
            entity_id=observation.entity_id,
            symbol=payload["symbol"],
            expiry_days=expiry_days,
            style=payload["style"],
            as_of=payload["as_of"],
            underlying=underlying,
            r=carry["r"],
            pv_div=pv_div_by_expiry[expiry_days],
            borrow_fee_annual=carry["borrow_fee_annual"],
            strikes=strikes,
        ))
    return chains


@dataclass(frozen=True)
class StoredPost:
    """Same attribute surface as providers/social_data.py's SocialPost
    (source, author, posted_at, text, engagement_score) - deliberately, so
    agents/speculator.py's `seen` window, `_source_dispersion` and
    `_read_stance` work against a StoredPost exactly as they do against a
    SocialPost, with nothing in that code needing to know which kind it
    holds."""

    source: str
    author: str
    posted_at: str
    text: str
    engagement_score: float


class StoredSocialProvider:
    """Speculator's parity read side: mission social_post observations for
    an entity, oldest first - mirroring
    providers/social_data.py's SocialDataProvider.fetch_recent shape so it
    slots into the same call site."""

    def __init__(self, conn):
        self._conn = conn

    def fetch_recent(self, entity_id: str, since: str | None = None) -> list[StoredPost]:
        """Observations with observed_at strictly after `since`, oldest
        first - replay() already orders by observed_at; the `> since` cut is
        applied here rather than passed as replay's inclusive `start` bound,
        so a caller re-passing its own last-seen cursor never re-fetches that
        exact post (matching SyntheticSocialDataProvider's own cursor
        semantics)."""
        rows = observation_store.replay(self._conn, entity_id, "social_post")
        return [
            StoredPost(
                source=MISSION_CHATTER_SOURCE,
                author=obs.payload["author"],
                posted_at=obs.observed_at,
                text=obs.payload["text"],
                engagement_score=obs.payload["engagement_score"],
            )
            for obs in rows
            if since is None or obs.observed_at > since
        ]
