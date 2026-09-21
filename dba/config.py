"""The DBA's externalised configuration (expectations §32).

    *"Database configuration should be externalized ... backup location,
    retention period ... Secrets must not be hard-coded."*

Same shape as `app/router_config.py`, deliberately: cached on path and
modification time, merged section by section so a file that sets one key does
not erase the rest, and **refusing rather than defaulting** when the file
exists and cannot be read. A system that silently ignored the policy it was
handed is discovered from its consequences; one that refuses is discovered from
a stack trace.

Secrets are not here. Agent tokens are `DBA_TOKEN_<AGENT>` environment
variables, because a credential in a committed file is a credential in the
repository's history for ever.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PATH_ENV = "DBA_CONFIG_PATH"
DEFAULT_PATH = PROJECT_ROOT / "config" / "dba.yaml"

# The documented defaults, applied when no file exists. The same values
# config/dba.yaml ships with, restated rather than read from it: the file is
# what an operator edits, and a default that could only be found by reading the
# file it replaces is not a default.
DEFAULTS = {
    "schema_version": 1,
    "backup": {
        "directory": "backups/dba",
        "keep": 14,
        "hour": 2,
        "verify_by_restoring": True,
        "minimum_free_megabytes": 50,
    },
}

_CACHE: dict = {}


class DBAConfigError(ValueError):
    """The configuration exists and cannot be trusted."""


def config_path() -> Path:
    configured = (os.environ.get(PATH_ENV, "") or "").strip()
    return Path(configured) if configured else DEFAULT_PATH


def _merge(defaults: dict, loaded: dict) -> dict:
    merged: dict = {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            section = loaded.get(key)
            if section is not None and not isinstance(section, dict):
                # Silently replacing it with the defaults is exactly the
                # behaviour this module's docstring promises not to have: a
                # `backup:` written as a list would have run the whole policy
                # on defaults nobody chose, and looked fine.
                raise DBAConfigError(
                    f"{key!r} must be a mapping of settings, not a "
                    f"{type(section).__name__}. Refusing rather than falling "
                    f"back to the defaults - a policy that is ignored is a "
                    f"policy that does not exist.")
            merged[key] = {**value, **(section or {})}
        else:
            merged[key] = loaded.get(key, value)
    for key, value in loaded.items():
        merged.setdefault(key, value)
    return merged


def _validated(config: dict) -> dict:
    backup = config["backup"]
    keep = backup.get("keep")
    if not isinstance(keep, int) or keep < 1:
        raise DBAConfigError(
            f"backup.keep must be a whole number of backups to retain, at "
            f"least 1, not {keep!r}. Zero would mean deleting the backup you "
            f"just took.")
    hour = backup.get("hour")
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        raise DBAConfigError(f"backup.hour must be 0-23, not {hour!r}")
    free = backup.get("minimum_free_megabytes")
    if not isinstance(free, (int, float)) or free < 0:
        raise DBAConfigError(
            f"backup.minimum_free_megabytes must not be negative, not {free!r}")
    if not isinstance(backup.get("directory"), str) or not backup["directory"].strip():
        raise DBAConfigError("backup.directory must be a path")
    if not isinstance(backup.get("verify_by_restoring"), bool):
        raise DBAConfigError(
            f"backup.verify_by_restoring must be true or false, not "
            f"{backup.get('verify_by_restoring')!r}")
    return config


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
            raise DBAConfigError(
                f"{path} could not be read as YAML: {bad}. Refusing rather "
                f"than running on defaults nobody chose - a backup policy that "
                f"is ignored is a backup policy that does not exist.") from bad
        if not isinstance(loaded, dict):
            raise DBAConfigError(
                f"{path} must hold a mapping at the top level, not "
                f"{type(loaded).__name__}.")
        value = _validated(_merge(DEFAULTS, loaded))

    _CACHE["key"] = key
    _CACHE["value"] = value
    return value


def backup_directory() -> Path:
    """Where backups live. A relative path resolves against the project root so
    the meaning does not depend on which directory a process was started in."""
    configured = Path(load()["backup"]["directory"])
    override = (os.environ.get("DBA_BACKUP_DIR", "") or "").strip()
    if override:
        return Path(override)
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def keep() -> int:
    return int(load()["backup"]["keep"])


def backup_hour() -> int:
    return int(load()["backup"]["hour"])


def verify_by_restoring() -> bool:
    return bool(load()["backup"]["verify_by_restoring"])


def minimum_free_bytes() -> int:
    return int(float(load()["backup"]["minimum_free_megabytes"]) * 1024 * 1024)


def describe() -> dict:
    """The effective policy, for §28's health response."""
    return {
        "path": str(config_path()),
        "exists": config_path().exists(),
        "backup": {
            "directory": str(backup_directory()),
            "keep": keep(),
            "hour": backup_hour(),
            "verify_by_restoring": verify_by_restoring(),
            "minimum_free_megabytes": load()["backup"]["minimum_free_megabytes"],
        },
    }
