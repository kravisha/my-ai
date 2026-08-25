"""Boot configuration: the non-secret declaration of what this system is
currently scoped to do (addendum 39 §2/§4/§17, addendum 38 §2; TASK_QUEUE
TQ-22, docs/SPEC_RECONCILIATION.md §71).

## Why a file rather than more environment variables

Addendum 39 §2 draws the line and this module enforces it: `.env` holds
secrets and environment-specific values; *lifecycle and business scope* is
neither, and forcing it into `.env` is what makes later production
hardening painful. So `boot_config.json` is committed to the repository —
that is the point of it being non-secret — and read here.

## It speaks the vocabulary the system already has

Addendum 39 §4 writes asset classes as `EQUITIES` and `OPTIONS_ON_EQUITIES`,
insisting on the latter over a generic `OPTIONS` because options on other
underlyings will come. This system already draws that distinction more
finely (`stock_option`, `etf_option`, `future_option`, ...) and has since
the Reference Data Engine was built, so the spec's requirement is already
met and its labels are not adopted: the mapping is `EQUITIES` = `stock`,
`OPTIONS_ON_EQUITIES` = `stock_option`, recorded in §70 disposition 2. A
second naming scheme for the same eleven classes would be two models of one
fact, which the Conflict Rule forbids.

That is also why validation is not merely structural: every asset class
named here must be one `backend/reference_data.py` actually knows. A boot
configuration free to invent asset classes would be a config file
disagreeing with the engine it configures.

## Fail loud, never fall back

A malformed or absent boot configuration raises. There is deliberately no
"sensible default" path: a system whose declared scope silently became
something other than what the file says is one whose operator is reading a
document that does not govern anything - the same reasoning
`app/model_budget._limit` gives for refusing a typo'd budget rather than
quietly using the default, and `backend/continuity._positive_setting` for
refusing a typo'd continuity policy.

## The lifecycle stage

Addendum 38 §2 requires the stage to be persisted rather than live only in
memory, so the COO can read it at startup and alter behavior by it. This
file is that persistence: it is on disk, it survives restart, and it is
version-controlled, which makes a stage change a reviewable commit rather
than an untraceable mutation. If stage *transitions* ever need to be
recorded as events (who promoted PRE_ALPHA to ALPHA, and when), that is a
different mechanism and belongs with the status event stream (TQ-24), not
here.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PATH_ENV = "BOOT_CONFIG_PATH"
DEFAULT_PATH = PROJECT_ROOT / "boot_config.json"

# Addendum 38 §2's example stages. PRE_ALPHA is the required active stage for
# Milestone 1; the rest are declared so a future promotion is a value change
# rather than a code change, and so an unknown stage is refused rather than
# accepted as some new thing nobody defined.
STAGE_PRE_ALPHA = "PRE_ALPHA"
STAGE_ALPHA = "ALPHA"
STAGE_BETA = "BETA"
STAGE_PRODUCTION = "PRODUCTION"
LIFECYCLE_STAGES = (STAGE_PRE_ALPHA, STAGE_ALPHA, STAGE_BETA, STAGE_PRODUCTION)

_REQUIRED_FIELDS = (
    "lifecycle_stage",
    "global_asset_classes",
    "implemented_asset_classes",
    "current_focus",
    "simulation_focus",
)


class BootConfigError(ValueError):
    """A boot configuration that cannot be trusted to describe this system.

    Its own class rather than a bare ValueError because startup catches it to
    report the failure through the COO's feed (addendum 38 §12: a failed
    component must be visible, not silently absent)."""


@dataclass(frozen=True)
class BootConfig:
    """What the system is scoped to do right now. Frozen: a component that
    could edit the boot configuration it was handed would make the file a
    suggestion rather than a declaration."""

    lifecycle_stage: str
    global_asset_classes: tuple[str, ...]
    implemented_asset_classes: tuple[str, ...]
    current_focus: tuple[str, ...]
    simulation_focus: tuple[str, ...]
    source_path: str

    @property
    def is_pre_alpha(self) -> bool:
        return self.lifecycle_stage == STAGE_PRE_ALPHA


def config_path() -> Path:
    """Environment first, project-root default second - the convention
    FI_DB_PATH and CONTINUITY_BACKUP_ROOT already follow, resolved at call
    time so a test or a reconfigured process sees the current value."""
    return Path(os.environ.get(PATH_ENV) or DEFAULT_PATH)


def _known_asset_classes() -> set[str]:
    """The classes the Reference Data Engine actually knows. Imported inside
    the function to keep this module's import free of the schema module's
    weight, and because nothing here needs it until validation runs."""
    from backend.reference_data import ASSET_CLASSES

    return {code for code, _ in ASSET_CLASSES}


def _string_tuple(raw, field: str, path: Path) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise BootConfigError(f"{path}: {field} must be a list of strings; got {raw!r}")
    if len(set(raw)) != len(raw):
        raise BootConfigError(f"{path}: {field} contains duplicates; got {raw!r}")
    return tuple(raw)


def load(path: str | Path | None = None) -> BootConfig:
    """Read, validate, and return the boot configuration.

    Every failure raises BootConfigError naming the file and the problem -
    an operator fixing a boot configuration needs to know which value is
    wrong, not that "startup failed"."""
    path = Path(path) if path is not None else config_path()
    if not path.exists():
        raise BootConfigError(
            f"{path} does not exist. Boot configuration is non-secret and belongs in the "
            "repository (addendum 39 §2); it is not optional and has no default."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BootConfigError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise BootConfigError(f"{path} must contain a JSON object; got {type(raw).__name__}")

    missing = [field for field in _REQUIRED_FIELDS if field not in raw]
    if missing:
        raise BootConfigError(f"{path} is missing required field(s): {', '.join(missing)}")

    stage = raw["lifecycle_stage"]
    if stage not in LIFECYCLE_STAGES:
        raise BootConfigError(
            f"{path}: unknown lifecycle_stage {stage!r}; known stages are {LIFECYCLE_STAGES}. "
            "Refusing to run at a stage nobody defined."
        )

    global_classes = _string_tuple(raw["global_asset_classes"], "global_asset_classes", path)
    implemented = _string_tuple(raw["implemented_asset_classes"], "implemented_asset_classes", path)
    current_focus = _string_tuple(raw["current_focus"], "current_focus", path)
    simulation_focus = _string_tuple(raw["simulation_focus"], "simulation_focus", path)

    if not global_classes:
        raise BootConfigError(f"{path}: global_asset_classes must not be empty")

    # The config may not invent asset classes the engine does not know
    # (module docstring). Checked against reference_data's own list, so the
    # two cannot drift into disagreeing about what exists.
    known = _known_asset_classes()
    unknown = sorted(set(global_classes) - known)
    if unknown:
        raise BootConfigError(
            f"{path}: global_asset_classes names {unknown}, which backend/reference_data.py does "
            f"not know. Known codes: {sorted(known)}. Note this system's vocabulary is "
            "'stock'/'stock_option', not addendum 39 §4's EQUITIES/OPTIONS_ON_EQUITIES "
            "(SPEC_RECONCILIATION §70 disposition 2)."
        )

    # The same containment the registry enforces on its own flags
    # (in_focus subseteq in_capability subseteq in_universe): a class cannot
    # be implemented without being architecturally known.
    not_global = sorted(set(implemented) - set(global_classes))
    if not_global:
        raise BootConfigError(
            f"{path}: implemented_asset_classes names {not_global}, absent from "
            "global_asset_classes. Implemented must be a subset of what the architecture knows."
        )

    return BootConfig(
        lifecycle_stage=stage,
        global_asset_classes=global_classes,
        implemented_asset_classes=implemented,
        current_focus=current_focus,
        simulation_focus=simulation_focus,
        source_path=str(path),
    )


def summary(config: BootConfig) -> str:
    """One line for the COO's status feed (addendum 39 §18) - the shape the
    Metadata Engine will publish once TQ-23 gives it a voice."""
    return (
        f"stage={config.lifecycle_stage} "
        f"implemented={','.join(config.implemented_asset_classes) or 'none'} "
        f"focus={','.join(config.current_focus) or 'none'} "
        f"simulation_focus={','.join(config.simulation_focus) or 'none'}"
    )
