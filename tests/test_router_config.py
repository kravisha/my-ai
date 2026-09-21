"""The router's policy file (§4.3).

The interesting cases are all about what happens when the file is wrong,
because the failure this defends against is silent: a threshold that parsed as
a string compares greater than every float score and escalates everything,
and the symptom is a bill rather than an error.
"""

import pytest

from app import router_config


@pytest.fixture(autouse=True)
def _fresh_cache():
    router_config._CACHE.clear()
    yield
    router_config._CACHE.clear()


def _write(tmp_path, monkeypatch, text):
    path = tmp_path / "router.yaml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv(router_config.PATH_ENV, str(path))
    return path


def test_the_shipped_file_is_valid_and_is_what_the_router_reads():
    assert router_config.config_path().exists()
    assert router_config.confidence_threshold() == 0.65
    assert router_config.describe()["source"] == "config/router.yaml"


def test_a_missing_file_falls_back_to_the_documented_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv(router_config.PATH_ENV, str(tmp_path / "absent.yaml"))
    assert router_config.confidence_threshold() == 0.65
    assert router_config.describe()["source"] == "built-in defaults"


def test_a_file_that_sets_one_key_keeps_the_rest(tmp_path, monkeypatch):
    """An operator changing the threshold must not have to restate the
    retention policy - and the first one to forget would silently turn off
    pruning."""
    _write(tmp_path, monkeypatch, "router:\n  confidence_threshold: 0.4\n")
    assert router_config.confidence_threshold() == 0.4
    assert router_config.retention_days() == 30
    assert router_config.max_retries() == 3


def test_a_quoted_number_is_refused_rather_than_compared(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, 'router:\n  confidence_threshold: "0.65"\n')
    with pytest.raises(router_config.RouterConfigError, match="must be a number"):
        router_config.confidence_threshold()


def test_a_threshold_outside_the_range_is_refused(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, "router:\n  confidence_threshold: 7\n")
    with pytest.raises(router_config.RouterConfigError, match="outside 0.0-1.0"):
        router_config.confidence_threshold()


def test_unparseable_yaml_is_an_error_not_a_silent_default(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, "router:\n  confidence_threshold: [0.6\n")
    with pytest.raises(router_config.RouterConfigError, match="could not be read"):
        router_config.load()


def test_a_section_of_the_wrong_shape_is_refused(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, "router: 0.65\n")
    with pytest.raises(router_config.RouterConfigError, match="must be a mapping"):
        router_config.load()


def test_an_edit_takes_effect_without_a_restart(tmp_path, monkeypatch):
    path = _write(tmp_path, monkeypatch, "router:\n  confidence_threshold: 0.4\n")
    assert router_config.confidence_threshold() == 0.4

    import os
    path.write_text("router:\n  confidence_threshold: 0.8\n", encoding="utf-8")
    os.utime(path, (0, 0))  # force a different mtime rather than racing the clock
    assert router_config.confidence_threshold() == 0.8


def test_the_permitted_escalations_are_the_four_the_task_names():
    assert set(router_config.permitted_escalations()) == {
        "low_confidence", "tool_required", "context_length", "local_error"}


def test_the_schedule_is_configurable(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, "self_diagnosis:\n  hour: 6\n  weekly_weekday: 4\n")
    assert router_config.self_diagnosis_hour() == 6
    assert router_config.weekly_weekday() == 4
