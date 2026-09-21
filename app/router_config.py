"""The router's policy, read from `config/router.yaml` rather than compiled in
(Task 01 §4.3).

## Why a file and not the environment

Every other knob on the model path is an environment variable, and this one is
deliberately not. The difference is what the value *is*: `KIMI_BASE_URL` is a
property of one machine's deployment, while a confidence threshold is a
judgement about how this system should behave, arrived at from a report and
changed deliberately. A judgement belongs in a file that can be reviewed in a
diff and carries the reasoning beside it; `config/router.yaml` carries three
paragraphs of it.

## A missing file is a default; a broken file is an error

If the file is absent the documented defaults below apply, because the
application has to start on a machine that has not been configured yet and
refusing would make the router's existence conditional on a file nobody has
written.

If the file is present and cannot be read, or holds a value outside its range,
this raises. That asymmetry is the one `app/model_budget._limit` already uses
and for the same reason: a typo must not quietly become a different policy. The
failure mode being defended against is a threshold of `0,65` parsing as a string
and comparing greater than every score.

## Read at call time, cached by file identity

Cached on the resolved path and the file's modification time, so a test that
writes a config and then another does not get the first one back, and a running
process picks up an edit without a restart. Not cached on content: hashing a
file on every model call to save a parse of forty lines would be the wrong
trade in both directions.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PATH_ENV = "ROUTER_CONFIG_PATH"
DEFAULT_PATH = PROJECT_ROOT / "config" / "router.yaml"

# The documented defaults, applied when no file exists. They are the same
# values config/router.yaml ships with, restated here rather than read from it:
# the file is what an operator edits, and a default that could only be found by
# reading the file it replaces is not a default.
DEFAULTS = {
    "schema_version": 1,
    "router": {
        "confidence_threshold": 0.65,
        "escalate_on_low_confidence": True,
        "permitted_escalations": ["low_confidence", "tool_required",
                                  "context_length", "local_error"],
    },
    "quota": {"retry_after_seconds": 900, "max_retries": 3},
    "self_diagnosis": {"hour": 3, "weekly_weekday": 0, "weekly_days": 7},
    "logging": {"retention_days": 30},
}

_CACHE: dict = {}


class RouterConfigError(ValueError):
    """The configuration file exists and cannot be trusted.

    Raised rather than defaulted, because a router that silently ignored the
    policy it was handed would be worse than one that refused to start: the
    first is discovered from a bill, the second from a stack trace."""


def config_path() -> Path:
    configured = (os.environ.get(PATH_ENV, "") or "").strip()
    return Path(configured) if configured else DEFAULT_PATH


def _merge(defaults: dict, loaded: dict) -> dict:
    """Section by section, so a file that sets one key does not erase the rest.

    A whole-document replacement would mean every operator who wanted to change
    the threshold had to restate the retention policy, and the first one to
    forget would silently turn off pruning."""
    merged = {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            section = loaded.get(key) or {}
            if not isinstance(section, dict):
                raise RouterConfigError(
                    f"{key!r} in {config_path()} must be a mapping, not "
                    f"{type(section).__name__}.")
            merged[key] = {**value, **section}
        else:
            merged[key] = loaded.get(key, value)
    for key, value in loaded.items():
        merged.setdefault(key, value)
    return merged


def load() -> dict:
    """The effective configuration. Cached on path and modification time."""
    path = config_path()
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = None

    key = (str(path), stamp)
    if _CACHE.get("key") == key:
        return _CACHE["value"]

    if stamp is None:
        value = _validated(_merge(DEFAULTS, {}))
    else:
        import yaml

        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as bad:
            raise RouterConfigError(
                f"{path} could not be read as YAML: {bad}. Refusing rather than "
                f"running on defaults nobody chose - a router whose policy file "
                f"is ignored is a router with no policy.") from bad
        if not isinstance(loaded, dict):
            raise RouterConfigError(
                f"{path} must hold a mapping at the top level, not "
                f"{type(loaded).__name__}.")
        value = _validated(_merge(DEFAULTS, loaded))

    _CACHE["key"] = key
    _CACHE["value"] = value
    return value


def _number(section: dict, field: str, where: str, *, low: float, high: float) -> float:
    value = section.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RouterConfigError(
            f"{where}.{field} must be a number, got {value!r}. A quoted number is "
            f"a string and would compare in the wrong direction against every score.")
    if not (low <= value <= high):
        raise RouterConfigError(
            f"{where}.{field}={value} is outside {low}-{high}.")
    return value


def _validated(config: dict) -> dict:
    router = config["router"]
    _number(router, "confidence_threshold", "router", low=0.0, high=1.0)
    if not isinstance(router.get("escalate_on_low_confidence"), bool):
        raise RouterConfigError(
            "router.escalate_on_low_confidence must be true or false.")
    permitted = router.get("permitted_escalations")
    if not isinstance(permitted, list) or not all(isinstance(x, str) for x in permitted):
        raise RouterConfigError(
            "router.permitted_escalations must be a list of escalation reason names.")

    _number(config["quota"], "retry_after_seconds", "quota", low=0, high=86_400)
    _number(config["quota"], "max_retries", "quota", low=0, high=100)
    _number(config["self_diagnosis"], "hour", "self_diagnosis", low=0, high=23)
    _number(config["self_diagnosis"], "weekly_weekday", "self_diagnosis", low=0, high=6)
    _number(config["self_diagnosis"], "weekly_days", "self_diagnosis", low=1, high=90)
    _number(config["logging"], "retention_days", "logging", low=1, high=3650)
    return config


# --- the questions callers actually ask ---------------------------------------


def confidence_threshold() -> float:
    return float(load()["router"]["confidence_threshold"])


def escalate_on_low_confidence() -> bool:
    return bool(load()["router"]["escalate_on_low_confidence"])


def permitted_escalations() -> tuple[str, ...]:
    return tuple(load()["router"]["permitted_escalations"])


def retry_after_seconds() -> int:
    return int(load()["quota"]["retry_after_seconds"])


def max_retries() -> int:
    return int(load()["quota"]["max_retries"])


def self_diagnosis_hour() -> int:
    return int(load()["self_diagnosis"]["hour"])


def weekly_weekday() -> int:
    return int(load()["self_diagnosis"]["weekly_weekday"])


def weekly_days() -> int:
    return int(load()["self_diagnosis"]["weekly_days"])


def retention_days() -> int:
    return int(load()["logging"]["retention_days"])


def describe() -> dict:
    """The effective policy and where it came from, for the status surface.

    "Which threshold is this process actually using" should be answerable
    without reading a file off a machine Krish is not sitting at."""
    path = config_path()
    return {
        "path": str(path),
        "present": path.exists(),
        "source": "config/router.yaml" if path.exists() else "built-in defaults",
        "config": load(),
    }
