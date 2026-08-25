"""Boot configuration (backend/boot_config.py, addenda 38 §2 / 39 §2·§4·§17;
TQ-22, SPEC_RECONCILIATION §71).

Two things this suite exists to hold. First, the shipped `boot_config.json`
must actually describe this system — a scope document that disagrees with the
engine it configures is worse than none, because it is still believed.
Second, every malformed configuration must be refused loudly: there is no
"sensible default" path, for the same reason the budget breaker refuses a
typo'd limit rather than quietly using the default."""

import json

import pytest

from backend import boot_config
from backend.boot_config import BootConfigError
from backend.reference_data import ASSET_CLASSES

VALID = {
    "lifecycle_stage": "PRE_ALPHA",
    "global_asset_classes": ["stock", "stock_option", "etf"],
    "implemented_asset_classes": ["stock", "stock_option"],
    "current_focus": ["PRE_ALPHA_STARTUP_OBSERVABILITY"],
    "simulation_focus": ["OPTIONS_ON_EQUITIES_PRICING"],
}


def _write(tmp_path, **overrides):
    data = {**VALID, **overrides}
    for key, value in list(data.items()):
        if value is None:
            del data[key]
    path = tmp_path / "boot_config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- the shipped file must describe the real system -------------------------------


def test_shipped_config_loads_and_is_pre_alpha():
    """The repository's own boot_config.json, loaded through the real path
    resolution - Milestone 1 requires PRE_ALPHA to be the active stage."""
    config = boot_config.load()
    assert config.lifecycle_stage == boot_config.STAGE_PRE_ALPHA
    assert config.is_pre_alpha is True


def test_shipped_config_implements_exactly_equities_and_equity_options():
    """Addendum 39 §10: "Nothing else should be falsely marked implemented."
    In this system's vocabulary that is stock + stock_option (§70
    disposition 2's recorded mapping)."""
    config = boot_config.load()
    assert set(config.implemented_asset_classes) == {"stock", "stock_option"}


def test_shipped_config_names_only_asset_classes_the_engine_knows():
    """The integrity link that makes this file a description rather than a
    wish: every class named here exists in reference_data's own list."""
    config = boot_config.load()
    known = {code for code, _ in ASSET_CLASSES}
    assert set(config.global_asset_classes) <= known
    assert set(config.implemented_asset_classes) <= set(config.global_asset_classes)


def test_shipped_config_declares_the_option_pricing_simulation_focus():
    """Addendum 39 §6 requires the simulation focus to be explicit rather
    than implied."""
    config = boot_config.load()
    assert "OPTIONS_ON_EQUITIES_PRICING" in config.simulation_focus
    assert config.current_focus  # 39 §11's focus list is not empty


# --- fail loud, never fall back ---------------------------------------------------


def test_missing_file_refuses_rather_than_defaulting(tmp_path):
    with pytest.raises(BootConfigError, match="does not exist"):
        boot_config.load(tmp_path / "absent.json")


def test_malformed_json_names_the_file(tmp_path):
    path = tmp_path / "boot_config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(BootConfigError, match="not valid JSON"):
        boot_config.load(path)


def test_missing_required_field_is_named(tmp_path):
    with pytest.raises(BootConfigError, match="simulation_focus"):
        boot_config.load(_write(tmp_path, simulation_focus=None))


def test_unknown_lifecycle_stage_is_refused(tmp_path):
    """A stage nobody defined cannot be run at - the system would have no
    idea what behavior it implies."""
    with pytest.raises(BootConfigError, match="unknown lifecycle_stage"):
        boot_config.load(_write(tmp_path, lifecycle_stage="SUPER_ALPHA"))


def test_every_declared_stage_is_accepted(tmp_path):
    """A promotion should be a value change, not a code change."""
    for stage in boot_config.LIFECYCLE_STAGES:
        assert boot_config.load(_write(tmp_path, lifecycle_stage=stage)).lifecycle_stage == stage


def test_invented_asset_class_is_refused_with_the_vocabulary_note(tmp_path):
    """The failure a reader of addendum 39 §4 would most likely cause: using
    the spec's EQUITIES/OPTIONS_ON_EQUITIES labels. The message points at
    §70's recorded mapping rather than just saying 'unknown'."""
    with pytest.raises(BootConfigError, match="reference_data.py does not know"):
        boot_config.load(_write(tmp_path, global_asset_classes=["EQUITIES", "OPTIONS_ON_EQUITIES"],
                                implemented_asset_classes=["EQUITIES"]))


def test_implemented_must_be_a_subset_of_global(tmp_path):
    """The registry's own containment rule (in_capability subseteq
    in_universe), enforced at the boot layer too: a class cannot be
    implemented without being architecturally known."""
    with pytest.raises(BootConfigError, match="absent from"):
        boot_config.load(_write(tmp_path, global_asset_classes=["stock"],
                                implemented_asset_classes=["stock", "stock_option"]))


def test_wrong_types_and_duplicates_are_refused(tmp_path):
    with pytest.raises(BootConfigError, match="list of strings"):
        boot_config.load(_write(tmp_path, current_focus="not a list"))
    with pytest.raises(BootConfigError, match="duplicates"):
        boot_config.load(_write(tmp_path, implemented_asset_classes=["stock", "stock"]))
    with pytest.raises(BootConfigError, match="must not be empty"):
        boot_config.load(_write(tmp_path, global_asset_classes=[], implemented_asset_classes=[]))


def test_a_json_array_is_not_a_config(tmp_path):
    path = tmp_path / "boot_config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(BootConfigError, match="JSON object"):
        boot_config.load(path)


# --- plumbing ---------------------------------------------------------------------


def test_path_is_environment_first_resolved_at_call_time(tmp_path, monkeypatch):
    monkeypatch.delenv(boot_config.PATH_ENV, raising=False)
    assert boot_config.config_path() == boot_config.DEFAULT_PATH
    redirected = _write(tmp_path)
    monkeypatch.setenv(boot_config.PATH_ENV, str(redirected))
    assert boot_config.config_path() == redirected
    assert boot_config.load().source_path == str(redirected)


def test_config_is_frozen(tmp_path):
    """A component that could edit the boot configuration it was handed
    would make the file a suggestion rather than a declaration."""
    config = boot_config.load(_write(tmp_path))
    with pytest.raises(Exception):
        config.lifecycle_stage = "ALPHA"


def test_summary_carries_the_fields_the_feed_will_show(tmp_path):
    line = boot_config.summary(boot_config.load(_write(tmp_path)))
    assert "stage=PRE_ALPHA" in line
    assert "stock_option" in line
    assert "OPTIONS_ON_EQUITIES_PRICING" in line
