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
PEER_GROUP_NAME = os.environ.get("FI_PEER_GROUP_NAME", "synthetic_peer_group_v1")
PEER_GROUP_VERSION = int(os.environ.get("FI_PEER_GROUP_VERSION", "1"))
PEER_GROUP_SECURITIES = [
    s.strip() for s in os.environ.get("FI_PEER_GROUP_SECURITIES", "SYN1,SYN2,SYN3,SYN4").split(",") if s.strip()
]

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
