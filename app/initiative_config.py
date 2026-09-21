"""The boldness setting, read from `config/initiative.yaml`.

Its own file rather than a section of `config/router.yaml`, and its own loader
rather than a shared one, for reasons worth stating because the duplication is
otherwise the obvious thing to remove:

- **Its own file** because the two are edited by different people at different
  times for different reasons. `router.yaml` is a performance and cost policy
  tuned from the nightly report; this is a statement about how much latitude
  Jarvis has. Putting a question about autonomy in the same file as a token
  threshold invites somebody to change one while meaning the other.
- **Its own loader** because sharing one would mean `app/router_config` growing
  a notion of "which document am I", and the first thing that would break is
  its cache key. Forty lines repeated is cheaper than a generic loader nobody
  can hold in their head, and the two files are small enough that the repetition
  is visible rather than hidden.

The asymmetry from `router_config` is kept deliberately: a **missing** file
falls back to the documented default, because a machine that has not been
configured yet must still start; a **present but broken** file raises, because a
typo must not quietly become a different policy. The failure being defended
against is `boldness: Bold` silently reading as an unknown setting and being
rounded to something.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PATH_ENV = "INITIATIVE_CONFIG_PATH"
DEFAULT_PATH = PROJECT_ROOT / "config" / "initiative.yaml"

# Restated here rather than read from the file it replaces, for the reason
# router_config gives: a default that could only be found by reading the file it
# stands in for is not a default.
DEFAULTS = {"schema_version": 1, "boldness": "bold"}

_CACHE: dict = {}

# Set by `override` for the duration of a test or a deliberate experiment. A
# process-wide variable rather than a parameter on every call, matching
# `app/model_gateway.set_provider`: how bold this deployment is, is a deployment
# decision and not a caller's.
_OVERRIDE: str | None = None


class InitiativeConfigError(ValueError):
    """The file exists and cannot be trusted, so nothing runs on a guess."""


def config_path() -> Path:
    configured = (os.environ.get(PATH_ENV, "") or "").strip()
    return Path(configured) if configured else DEFAULT_PATH


def override(level: str | None) -> None:
    """Force a setting for this process, or clear it with None."""
    global _OVERRIDE
    if level is not None:
        _validate(level)
    _OVERRIDE = level


def _validate(level) -> str:
    from app.initiative import BOLDNESS_LEVELS

    if not isinstance(level, str) or level not in BOLDNESS_LEVELS:
        raise InitiativeConfigError(
            f"boldness={level!r} is not one of {sorted(BOLDNESS_LEVELS)}. "
            f"Refusing rather than rounding to the nearest: an unrecognised "
            f"setting silently treated as the cautious one would look like the "
            f"assistant losing its nerve, and treated as the bold one would be "
            f"worse.")
    return level


def load() -> dict:
    """The effective configuration. Cached on path and modification time."""
    if _OVERRIDE is not None:
        return {**DEFAULTS, "boldness": _OVERRIDE}

    path = config_path()
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = None

    key = (str(path), stamp)
    if _CACHE.get("key") == key:
        return _CACHE["value"]

    if stamp is None:
        value = dict(DEFAULTS)
    else:
        import yaml

        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as bad:
            raise InitiativeConfigError(
                f"{path} could not be read as YAML: {bad}. Refusing rather than "
                f"running on a default nobody chose - how much latitude this "
                f"assistant has is not something to fall back into.") from bad
        if not isinstance(loaded, dict):
            raise InitiativeConfigError(
                f"{path} must hold a mapping at the top level, not "
                f"{type(loaded).__name__}.")
        value = {**DEFAULTS, **loaded}

    _validate(value.get("boldness"))
    _CACHE["key"] = key
    _CACHE["value"] = value
    return value


def boldness() -> str:
    return str(load()["boldness"])


def describe() -> dict:
    path = config_path()
    return {
        "path": str(path),
        "present": path.exists(),
        "source": ("override" if _OVERRIDE is not None
                   else "config/initiative.yaml" if path.exists()
                   else "built-in default"),
        "boldness": boldness(),
    }
