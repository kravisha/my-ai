"""Shared config for the Phase C discovery slice (Explorer/Speculator/
Analysis) - one place for the peer-group definition and detector/provider
tuning, all env-overridable like agents/base.py's FI_DB_PATH already is.

Widened from Phase C v1's single-security scope to a peer group (addendum_7
§5, addendum_8 §4's progression: one security -> two or three -> ten with
peer groups). This increment targets a modest 4-security group to prove the
peer-vs-individual classification mechanism works correctly, not the full
ten-security graduation suite - a later increment changes PEER_GROUP_SIZE-
adjacent defaults, not the classification logic itself.
"""

import os

# Peer groups must be explicit and versioned so tests are reproducible
# (addendum_7 §5, literal requirement) - real config/columns, not just a
# comment. PEER_GROUP_VERSION bumps only when membership changes in a way
# that should be distinguishable from earlier detector_events rows (same
# spirit as fi_db.SCHEMA_VERSION - a producer/semantic version, not tied to
# every tweak).
PEER_GROUP_VERSION = int(os.environ.get("FI_PEER_GROUP_VERSION", "2"))

# Ten securities across **explicit peer groups**, plural - addendum 8 §4 step 3.
# The plural is the substance of that step, not decoration.
#
# With one flat group, "how many others triggered" has a denominator that means
# very little: one co-trigger out of nine is close to noise, and nine out of
# nine is a market-wide event nobody needed a detector to notice. Grouping gives
# co-movement something to be relative to - three names moving together *inside
# a sector* is a common-factor signal; the same three scattered across unrelated
# groups is three idiosyncratic events that happened to coincide.
#
# Set FI_PEER_GROUPS as "group:SEC,SEC;group:SEC,SEC" to override.
DEFAULT_PEER_GROUPS = {
    "synthetic_alpha": ["SYN1", "SYN2", "SYN3", "SYN4"],
    "synthetic_beta": ["SYN5", "SYN6", "SYN7"],
    "synthetic_gamma": ["SYN8", "SYN9", "SYN10"],
}


def _parse_peer_groups(raw: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for chunk in raw.split(";"):
        if ":" not in chunk:
            continue
        name, members = chunk.split(":", 1)
        securities = [s.strip() for s in members.split(",") if s.strip()]
        if name.strip() and securities:
            groups[name.strip()] = securities
    return groups


PEER_GROUPS = _parse_peer_groups(os.environ.get("FI_PEER_GROUPS", "")) or DEFAULT_PEER_GROUPS

# Every security under observation, flattened. Order is stable (group order,
# then membership order) so runs stay reproducible.
PEER_GROUP_SECURITIES = [s for members in PEER_GROUPS.values() for s in members]

_GROUP_OF = {s: name for name, members in PEER_GROUPS.items() for s in members}


def group_of(security: str) -> str | None:
    """Which peer group a security belongs to, or None if it belongs to none.

    A security with no group is not an error - it is simply one whose
    co-movement cannot be assessed, and Explorer classifies it 'individual'
    rather than guessing at a peer relationship it has no basis for."""
    return _GROUP_OF.get(security)


def group_members(security: str) -> list[str]:
    group = group_of(security)
    return list(PEER_GROUPS.get(group, [])) if group else []

# NOTE: the detection thresholds are no longer here. Peak IV / Local Baseline
# IV (addendum_7 §4) and Speculator's confidence bar are the system's
# *intelligence*, not its configuration - "intelligence is about defining how
# to look at things" (owner, 2026-08-16) - so they live in the
# intelligence_artifacts table where they carry provenance, a rationale, and
# validity conditions, and can be marked stale on evidence. Their seed values
# are backend/fi_db.py's LENS_IV_RATIO_SEED / LENS_SPECULATOR_CONFIDENCE_SEED
# (kept there so fi_db can seed them without backend/ importing agents/).
# Agents resolve them per cycle via fi_db.get_active_artifact_value.

# Local baseline neighborhood radius, in grid-index units (see
# providers/market_data.py's STRIKES/EXPIRIES_DAYS grids).
NEIGHBORHOOD_STRIKE_RADIUS = int(os.environ.get("FI_NEIGHBORHOOD_STRIKE_RADIUS", "1"))
NEIGHBORHOOD_EXPIRY_RADIUS = int(os.environ.get("FI_NEIGHBORHOOD_EXPIRY_RADIUS", "1"))

# How many *other* securities in the peer group must also trigger the same
# cycle for a candidate to be classified 'peer' (market/sector/common-
# factor driven) rather than 'individual' (idiosyncratic) - addendum_7 §5.
# Deliberately not hardcoded: this increment's job is proving the
# classification mechanism works at all (addendum_8 §4 step 2's "ensure
# the first success was not luck" framing), not calibrating a final
# threshold - the later ten-security increment changes this default, not
# the classification function.
PEER_MIN_COOCCURRING = int(os.environ.get("FI_PEER_MIN_COOCCURRING", "1"))

MARKET_PROVIDER_SEED = int(os.environ.get("FI_MARKET_PROVIDER_SEED", "42"))
SOCIAL_PROVIDER_SEED = int(os.environ.get("FI_SOCIAL_PROVIDER_SEED", "7"))

# The market regime the synthetic provider generates under - *ground truth*
# the system is never told. Explorer infers a characterization from the
# surfaces it observes instead (fi_db.market_regime), which is what makes
# "intelligence depends on market conditions" testable: change these, restart
# against the same database, and the system should notice the conditions its
# lens was bound to no longer hold. Both default to providers/market_data.py's
# module constants when unset.
MARKET_REGIME = {}
if os.environ.get("FI_MARKET_BASE_LEVEL"):
    MARKET_REGIME["base_level"] = float(os.environ["FI_MARKET_BASE_LEVEL"])
if os.environ.get("FI_MARKET_NOISE_AMPLITUDE"):
    MARKET_REGIME["noise_amplitude"] = float(os.environ["FI_MARKET_NOISE_AMPLITUDE"])

# Which peer-group securities get a guaranteed detectable dislocation
# forced onto their synthetic surface (providers/market_data.py's
# SyntheticMarketDataProvider `anomalies` param) - default empty means a
# realistic, mostly-quiet market (no forced anomalies anywhere). Setting
# two or more securities here is what constructs a co-movement scenario for
# manual verification or ad hoc runs, without needing a special test-only
# code path.
FORCE_ANOMALY_SECURITIES = [
    s.strip() for s in os.environ.get("FI_FORCE_ANOMALY_SECURITIES", "").split(",") if s.strip()
]

# How far back (seconds) Analysis looks at its own recent results for the
# same security as a recency/novelty check against that security's own
# history - a different thing from peer analysis (which compares across
# securities in the same cycle, see agents/explorer.py's classification).
ANALYSIS_RECENCY_WINDOW_SECONDS = float(os.environ.get("FI_ANALYSIS_RECENCY_WINDOW_SECONDS", "300"))

# Per-security social narratives the synthetic stream generates under - ground
# truth the system is never told, exactly like MARKET_REGIME above. Set as
# comma-separated security:narrative pairs, e.g.
# FI_SOCIAL_NARRATIVES="SYN1:corroborating,SYN2:contradicting,SYN3:coordinated".
# Valid narratives are the keys of providers/social_data.py's NARRATIVES.
# Without these the social stream is uncorrelated with the option surface, so a
# cross-check could never meaningfully corroborate or contradict anything.
SOCIAL_NARRATIVES = {}
for _pair in os.environ.get("FI_SOCIAL_NARRATIVES", "").split(","):
    if ":" in _pair:
        _security, _narrative = _pair.split(":", 1)
        SOCIAL_NARRATIVES[_security.strip()] = _narrative.strip()
