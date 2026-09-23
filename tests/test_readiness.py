"""Whether Jarvis can run on Krish's PC, check by check.

Everything built in the last two days was tested in a Linux container, and two
of it broke the first time Windows saw it. So *"does it run on my PC"* needs an
answer that is a list rather than a yes.

Four claims, and the tests are grouped by them. The first is the one that has
already gone wrong once in this repository, in the real-machine log check that
passed on a machine with no log:

1. A check that could not be made is never reported as passing.
2. Causes come before symptoms: a dependency's failure blocks what depends on it
   rather than producing a second red line about the same thing.
3. Every red says what to do, because whoever reads it is alone with it.
4. The overall answer is the worst line in it, and "runs" is not the same as
   "is well".

Probed by `tests/probes/readiness_probes.py`.
"""

import ast
import inspect

import pytest

from desktop import readiness
from desktop.readiness import (BLOCKED, GREEN, RED, YELLOW, Machine, look,
                               summary)


def working(**kwargs):
    """A machine where everything is in order, before a test breaks one thing."""
    base = dict(
        python_version=(3, 12), missing_packages=(),
        state_directory_writable=True, jarvis_token=True, operator_token=True,
        dba_answering=True, gateway_answering=True, gateway_reaches_dba=True,
        keystore_state="ready", keystore_because="sealed to this account",
        keystore_next_step="nothing", constitution_installed=True,
        constitution_intact=True, ledger_intact=True,
        checkpoint_age_hours=2.0, supervisor_registered=True,
        log_written_within_hours=0.5, windows=True)
    base.update(kwargs)
    return Machine(**base)


# --- 1. an unchecked thing is never green -----------------------------------

def test_a_machine_nobody_looked_at_is_not_reported_as_working():
    """`Machine()` with nothing filled in describes a machine where nothing is
    running, which is the honest reading of "we did not look"."""
    report = look(Machine())
    assert report.status == RED
    assert not report.runnable
    assert not [one for one in report.results if one.status == GREEN]


def test_every_field_of_a_blank_reading_defaults_to_the_worse_case():
    """A default that reads as working turns a fact nobody supplied into a
    reassurance.

    Written out field by field rather than as a rule about "falsy", for two
    reasons. A rule would have had to decide what `constitution_report=""` is,
    and it is neither - it carries a message, not a verdict. And a field added
    later would slip past a rule while breaking this list, which is the point:
    adding a fact to the reading should cost somebody one deliberate thought
    about what it means when nobody supplied it."""
    expected = {
        "python_version": (0, 0),              # older than any minimum
        "missing_packages": (),                # see below - the one exception
        "state_directory_writable": False,
        "jarvis_token": False,
        "operator_token": False,
        "dba_answering": False,
        "gateway_answering": False,
        "gateway_reaches_dba": False,
        "keystore_state": "absent",
        "keystore_because": "nobody looked",
        "keystore_next_step": "run this on the Windows machine",
        "constitution_installed": False,
        "constitution_intact": None,           # not False: nobody checked
        "constitution_report": "",             # a message, not a verdict
        "ledger_intact": None,
        "checkpoint_age_hours": None,          # not 0.0, which reads as fresh
        "supervisor_registered": False,
        "log_written_within_hours": None,
        "windows": False,
    }
    tree = ast.parse(inspect.getsource(readiness))
    machine = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.ClassDef) and node.name == "Machine")
    actual = {node.target.id: ast.literal_eval(node.value)
              for node in machine.body
              if isinstance(node, ast.AnnAssign) and node.value is not None}
    assert actual == expected, (
        "a field of the reading was added, removed or given a different "
        "default. Each one has to be the answer that is true when nobody "
        "looked, which is almost never the convenient one.")

    # `missing_packages=()` is the exception and it is deliberate: an empty
    # tuple reads as "nothing missing", which is optimistic. It is safe only
    # because `python` is checked first and a blank reading fails it, so the
    # packages check is never reached on a machine nobody looked at. The test
    # below is what holds that.
    assert look(Machine()).of("packages").status in (BLOCKED, RED)


def test_a_check_whose_dependency_failed_is_blocked_and_not_green():
    report = look(working(dba_answering=False))
    assert report.of("dba").status == RED
    for downstream in ("ledger", "checkpoint", "operator_console"):
        assert report.of(downstream).status == BLOCKED
        assert report.of(downstream).blocked_by == "dba"


def test_being_blocked_survives_two_hops():
    """`constitution_intact` depends on `constitution`, which depends on the
    keystore. A one-level check would call the third one green."""
    report = look(working(keystore_state="absent"))
    assert report.of("keystore").status == RED
    assert report.of("constitution").status == BLOCKED
    assert report.of("constitution_intact").status == BLOCKED


def test_every_precondition_names_a_check_that_has_already_run():
    """`_need_met` reads `done[required]` directly, which is only safe while
    every precondition is a check declared earlier. The table and the order are
    written in two different places, so something has to hold them together."""
    order = [one.name for one in look(working()).results]
    assert len(order) == len(set(order)), "a check is declared twice"
    for name, needs in readiness.NEEDS.items():
        assert name in order, f"NEEDS names {name!r}, which is not a check"
        for required in needs:
            assert required in order, (
                f"{name!r} needs {required!r}, which is not a check at all")
            assert order.index(required) < order.index(name), (
                f"{name!r} needs {required!r}, which runs after it")


def test_a_keystore_with_nowhere_to_put_the_key_stops_him_starting():
    """Not the same as a missing escrow, which does not. Without a key the
    constitution cannot be opened, so he would run ungoverned."""
    report = look(working(keystore_state="absent"))
    assert report.of("keystore").status == RED
    assert not report.runnable


def test_no_checkpoint_at_all_is_red_rather_than_fresh():
    """`None` is not zero. An absent checkpoint reported as "0 hours old" would
    be the best-looking line in the report."""
    report = look(working(checkpoint_age_hours=None))
    assert report.of("checkpoint").status == RED
    assert "no checkpoint at all" in report.of("checkpoint").because


def test_no_log_at_all_is_red_and_says_why_that_is_the_point():
    report = look(working(log_written_within_hours=None))
    assert report.of("logs").status == RED
    assert "absent log is not a clean one" in report.of("logs").because


def test_a_silent_log_on_a_running_gateway_is_reported():
    report = look(working(log_written_within_hours=30.0))
    assert report.of("logs").status == YELLOW
    assert "logging stopped" in report.of("logs").because


# --- 2. causes before symptoms ----------------------------------------------

def test_the_report_is_worst_first():
    report = look(working(dba_answering=False, supervisor_registered=False))
    order = [one.status for one in report.worst_first()]
    assert order == sorted(order, key=lambda one: readiness.ORDER[one])
    assert order[0] == RED


def test_a_gateway_that_cannot_reach_its_memory_is_red_not_green():
    """The failure that looks healthiest: he answers, and has no memory."""
    report = look(working(gateway_reaches_dba=False))
    assert report.of("gateway").status == GREEN
    assert report.of("gateway_reaches_dba").status == RED
    assert "looking healthy" in report.of("gateway_reaches_dba").because


def test_a_missing_token_blocks_the_dba_check_rather_than_doubling_the_red():
    """Two red lines about one cause is how a report gets skimmed."""
    report = look(working(jarvis_token=False))
    assert report.of("jarvis_token").status == RED
    assert report.of("dba").status == BLOCKED


# --- 3. every red says what to do -------------------------------------------

def test_every_red_and_yellow_line_carries_a_fix():
    broken = look(Machine())
    for one in broken.results:
        if one.status in (RED, YELLOW):
            assert one.fix, f"{one.name} is {one.status} and says nothing to do"


def test_the_keystore_passes_through_its_own_next_step():
    """`app/keystore.py` owns that decision; repeating it here would give two
    places to update and one of them would be missed."""
    report = look(working(keystore_state="no_escrow",
                          keystore_because="no escrow copy exists",
                          keystore_next_step="--write-escrow"))
    assert report.of("keystore").status == YELLOW
    assert report.of("keystore").fix == "--write-escrow"
    assert report.of("keystore").because == "no escrow copy exists"


def test_a_missing_escrow_does_not_stop_him_starting():
    report = look(working(keystore_state="no_escrow"))
    assert report.of("keystore").status == YELLOW
    assert report.runnable


def test_an_altered_constitution_is_red_and_says_not_to_overwrite_it():
    report = look(working(constitution_intact=False,
                          constitution_report="amendment 2 has changed"))
    assert report.of("constitution_intact").status == RED
    assert "amendment 2 has changed" in report.of("constitution_intact").because
    assert "Do not overwrite" in report.of("constitution_intact").fix


def test_the_summary_puts_the_fix_under_the_line_it_fixes():
    lines = summary(look(working(gateway_answering=False)))
    said = lines.index("[!!] gateway: the Gateway is not answering")
    assert lines[said + 1].strip().startswith("-> powershell")


# --- 4. the overall answer --------------------------------------------------

def test_a_machine_in_order_is_green_and_runnable():
    report = look(working())
    assert report.status == GREEN
    assert report.runnable
    assert [one.name for one in report.results if one.status != GREEN] == []


def test_one_yellow_makes_the_whole_report_yellow_and_still_runnable():
    report = look(working(supervisor_registered=False))
    assert report.status == YELLOW
    assert report.runnable


def test_a_non_blocking_red_does_not_claim_he_cannot_start():
    """The ledger failing to verify is serious and is not a reason to say he
    will not start, because he will."""
    report = look(working(ledger_intact=False))
    assert report.of("ledger").status == RED
    assert report.status == RED
    assert report.runnable


def test_a_blocking_red_says_he_will_not_start():
    assert not look(working(gateway_answering=False)).runnable
    assert not look(working(python_version=(3, 9))).runnable


def test_an_empty_report_is_red_rather_than_green():
    """`min` over nothing is the shape that would otherwise raise or, worse,
    return the best possible answer."""
    assert readiness.Report().status == RED


def test_the_thresholds_are_what_they_are():
    """Written as literals: a test saying `age > CHECKPOINT_STALE_HOURS` holds
    at every value of the constant, including six minutes and six months."""
    assert readiness.CHECKPOINT_STALE_HOURS == 48.0, (
        "two days - long enough that a quiet weekend is not an alarm, short "
        "enough that a restart would not lose a working week")
    assert readiness.LOG_SILENT_HOURS == 24.0
    assert readiness.MINIMUM_PYTHON == (3, 11)

    assert look(working(checkpoint_age_hours=47.0)).of("checkpoint").status == GREEN
    assert look(working(checkpoint_age_hours=49.0)).of("checkpoint").status == YELLOW
    assert look(working(log_written_within_hours=23.0)).of("logs").status == GREEN
    assert look(working(log_written_within_hours=25.0)).of("logs").status == YELLOW
    assert look(working(python_version=(3, 10))).of("python").status == RED
    assert look(working(python_version=(3, 11))).of("python").status == GREEN


def test_every_check_has_a_plain_words_meaning():
    """The name is for the program; `means` is for the person reading it at
    seven in the morning on a phone."""
    for one in look(working()).results:
        assert one.means and " " in one.means
        assert not one.means.startswith(one.name)


def test_asking_for_a_check_that_does_not_exist_is_an_error_not_a_pass():
    with pytest.raises(KeyError):
        look(working()).of("something_nobody_checks")


def test_describe_says_the_rule_this_is_built_on():
    said = readiness.describe()
    assert said["unchecked_is_never_green"] is True
    assert said["minimum_python"] == [3, 11]
    assert set(said["blocking_checks"]) <= {one.name for one in look(working()).results}
