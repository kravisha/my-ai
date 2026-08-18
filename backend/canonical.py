"""The one shape every observation arrives in, whatever produced it.

Addendum 20 §3: simulation, historical replay and live market data "should emit
the same canonical internal event/data format", and consumers "should not need to
know whether the source is synthetic, historical, or live, except through explicit
provenance metadata".

The Manifesto's §15 is the harder half of that: **data must never lie about what
it is.** Synthetic data must never silently masquerade as historical or live.

Those two requirements pull against each other, and the tension is the design.
Uniform shape means a consumer cannot tell the difference by looking; that is the
point, and it is also exactly how a training fixture ends up in a production
conclusion. So the shape is uniform and the *provenance is mandatory* - there is
no default origin, no "unknown", and no way to build an observation without saying
where it came from.

## Why this exists before any engine does

There is one producer today (the synthetic provider) and two consumers (Explorer
and Speculator), so the contract currently lives implicitly in a function
signature. Addendum 20 §5 and §13 together would have four engines built against
that implicit contract in parallel; the checkpoint's own Foundation First
principle says stabilize the contract first, which is why this is the first thing
built from that document rather than the first engine.

## What is deliberately not here

**No storage.** §4's Data Store is real work and belongs with the first engine
that has something to store - historical ingest. A table written by nothing would
be the empty schema this project keeps refusing.

**No numeric payload schema.** An option surface, a yield curve and a news item do
not share a value shape, and inventing a union of them now - before the historical
engine has shown what real data looks like - would be guessing with a straight
face. `payload` is a dict, `data_class` says how to read it, and the day two
engines disagree about a payload is the day that constraint earns its place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from backend.fi_db import _now, parse_timestamp
from simulation.cadences import CADENCES

# Where an observation came from. There is no fourth value and no default: §15's
# rule is that these never blur, and an "unknown" origin is the blur.
ORIGINS = ("synthetic", "historical", "live")


class ContractError(ValueError):
    """A refusal to build an observation that would misrepresent itself."""


@dataclass(frozen=True)
class Provenance:
    """Where this came from, who produced it, and when it was captured.

    Frozen, because provenance that can be edited after the fact is a claim rather
    than a record. A consumer that needs different provenance is looking at a
    different observation."""

    origin: str
    source: str
    captured_at: str = field(default_factory=_now)
    # Set only for synthetic data: which run and which scenario produced it. This
    # is what lets a conclusion drawn in simulation be traced back to the world it
    # was drawn in, rather than being indistinguishable from one drawn from the
    # market.
    run_id: str | None = None
    scenario_id: str | None = None

    def __post_init__(self) -> None:
        if self.origin not in ORIGINS:
            raise ContractError(
                f"origin must be one of {', '.join(ORIGINS)}; got {self.origin!r}. There is no "
                f"default and no unknown - an observation that cannot say where it came from is "
                f"the thing §15 forbids."
            )
        if not (self.source or "").strip():
            raise ContractError("provenance needs a source: which provider produced this, and which version")
        if self.origin != "synthetic" and (self.run_id or self.scenario_id):
            raise ContractError(
                f"{self.origin} data carries no run_id or scenario_id - those describe a simulated "
                f"world, and attaching them to real data would make it look simulated"
            )

    @property
    def is_synthetic(self) -> bool:
        return self.origin == "synthetic"


@dataclass(frozen=True)
class Observation:
    """One thing observed about one entity, at one moment, from one source.

    `observed_at` is when the fact was true in the world. `knowable_at` is when the
    organization could first have known it, which for anything measured rather than
    traded is later - a home price index describes a month that ended two months
    earlier. Keeping them apart is what makes a lookahead guard possible, and
    `simulation/cadences.py` already carries the lag per data class, so the default
    is derived rather than guessed.
    """

    entity_id: str
    data_class: str
    observed_at: str
    payload: dict
    provenance: Provenance
    knowable_at: str = ""

    def __post_init__(self) -> None:
        if not (self.entity_id or "").strip():
            raise ContractError(
                "an observation needs an entity_id - a Jarvis-owned internal id, not a symbol. "
                "See backend/identifiers.py for why the symbol is not the identity."
            )
        if self.data_class not in CADENCES:
            raise ContractError(
                f"unknown data_class {self.data_class!r}. The taxonomy is simulation/cadences.py, "
                f"which also carries this class's sampling interval and publication lag - a data "
                f"class that is not in it has no declared rhythm and nothing can say when it is late."
            )
        if not isinstance(self.provenance, Provenance):
            raise ContractError("provenance is required, and must be a Provenance")

        object.__setattr__(self, "knowable_at", self.knowable_at or self._default_knowable_at())

        if parse_timestamp(self.knowable_at) < parse_timestamp(self.observed_at):
            raise ContractError(
                f"knowable_at ({self.knowable_at}) precedes observed_at ({self.observed_at}): this "
                f"observation claims to have been knowable before it was true"
            )

    def _default_knowable_at(self) -> str:
        """observed_at plus this data class's publication lag."""
        lag: timedelta = CADENCES[self.data_class].publication_lag
        return (parse_timestamp(self.observed_at) + lag).isoformat()

    @property
    def sampling_interval(self) -> timedelta | None:
        """How often this class of data arrives. None for anything continuous,
        which is not a gap - a traded price has no interval, it has a session."""
        return CADENCES[self.data_class].interval

    def known_by(self, moment: str) -> bool:
        """Whether the organization could have had this at that moment.

        The lookahead guard, as a question an observation can answer about itself
        rather than a rule every consumer has to remember."""
        return parse_timestamp(self.knowable_at) <= parse_timestamp(moment)

    def as_record(self) -> dict:
        """A flat dict, for a manifest or a log. Provenance is inlined rather than
        nested so that a record cannot be passed on with the origin dropped."""
        return {
            "entity_id": self.entity_id,
            "data_class": self.data_class,
            "observed_at": self.observed_at,
            "knowable_at": self.knowable_at,
            "payload": self.payload,
            "origin": self.provenance.origin,
            "source": self.provenance.source,
            "captured_at": self.provenance.captured_at,
            "run_id": self.provenance.run_id,
            "scenario_id": self.provenance.scenario_id,
        }


def require_origin(observations, allowed) -> None:
    """Refuse a batch that mixes origins a caller did not expect.

    §15 permits combining domains "deliberately and transparently"; this is what
    makes the deliberate case say so. A consumer that has no business seeing
    synthetic data calls this with `{"historical", "live"}` and finds out at the
    boundary rather than in a conclusion."""
    allowed = set(allowed)
    unexpected = {obs.provenance.origin for obs in observations} - allowed
    if unexpected:
        raise ContractError(
            f"observations of origin {sorted(unexpected)} in a batch that accepts only "
            f"{sorted(allowed)}. Mixing domains is allowed, but only where somebody said so."
        )
