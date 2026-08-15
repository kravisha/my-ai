"""Shared config for the Phase C discovery slice (Explorer/Speculator/
Analysis) - one place for the single-security constant and detector/
provider tuning, all env-overridable like agents/base.py's FI_DB_PATH
already is. This increment is deliberately scoped to one security
(addendum_8 §4's own progression: one -> two or three -> ten with peer
groups); the next increment widening past one security has exactly one
place to start from.
"""

import os

SECURITY = os.environ.get("FI_DISCOVERY_SECURITY", "SYN1")

# Peak IV / Local Baseline IV >= this is a candidate (addendum_7 §4,
# configurable per the spec's own wording).
IV_RATIO_THRESHOLD = float(os.environ.get("FI_IV_RATIO_THRESHOLD", "2.0"))

# Local baseline neighborhood radius, in grid-index units (see
# providers/market_data.py's STRIKES/EXPIRIES_DAYS grids).
NEIGHBORHOOD_STRIKE_RADIUS = int(os.environ.get("FI_NEIGHBORHOOD_STRIKE_RADIUS", "1"))
NEIGHBORHOOD_EXPIRY_RADIUS = int(os.environ.get("FI_NEIGHBORHOOD_EXPIRY_RADIUS", "1"))

# Aggregate confidence over newly-seen evidence above which Speculator files
# a report.
SPECULATOR_CONFIDENCE_THRESHOLD = float(os.environ.get("FI_SPECULATOR_CONFIDENCE_THRESHOLD", "0.6"))

MARKET_PROVIDER_SEED = int(os.environ.get("FI_MARKET_PROVIDER_SEED", "42"))
SOCIAL_PROVIDER_SEED = int(os.environ.get("FI_SOCIAL_PROVIDER_SEED", "7"))

# Default False (a realistic, mostly-quiet synthetic market) - set
# FI_FORCE_ANOMALY=true to make Explorer's surface contain a guaranteed
# detectable dislocation, for manual verification or ad hoc runs without
# needing a special test-only code path.
FORCE_ANOMALY = os.environ.get("FI_FORCE_ANOMALY", "").lower() in ("1", "true", "yes")

# How far back (seconds) Analysis looks at its own recent results for the
# same security as a recency/novelty check - not peer analysis, which is
# cross-security and out of scope this increment.
ANALYSIS_RECENCY_WINDOW_SECONDS = float(os.environ.get("FI_ANALYSIS_RECENCY_WINDOW_SECONDS", "300"))
