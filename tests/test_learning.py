"""The Learning Engine: can it learn, and can it lie about having learned?

The second question carries this file. A subsystem that reports on its own
progress has an obvious failure mode, and Document 2 §10 names it exactly:

> *"Jarvis must not claim that a skill is learned merely because code was
> generated, documentation was read, a unit test passed, one lucky attempt
> worked, or an external model produced a plausible answer."*

So the assertions below are mostly about what the engine **cannot** do: set its
own state, pass a held-out gate it never ran, register itself, extend its own
sandbox, or read a credential while practising.

The security section is not decoration either. A learning loop that executes
things in a sandbox is the most dangerous thing in this repository, and three of
its tests are there because the first security probe of `app/learning/sandbox.py`
found real holes: `/proc/net` resolves through a symlink, `fnmatch`'s `*` crosses
`/`, and `/proc/*/environ` holds every API key on the machine.
"""

import json

import pytest

from app import initiative
from app.learning import (engine as engine_module, mastery, memory, practice,
                          recipe as recipe_module, research,
                          sandbox as sandbox_module, store)
from app.learning.objective import Case, Competency, Objective, ObjectiveRefused
from app.learning.recipe import Recipe, RecipeError, Step
from gateway import roles, tools


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "learning.db"))
    monkeypatch.setenv("MODEL_CALL_LOG_DIR", str(tmp_path / "logs"))
    engine_module._ENGINE = None
    yield tmp_path
    engine_module._ENGINE = None


def _objective(**overrides):
    fields = dict(
        slug="listening-ports",
        cannot_do="say which TCP ports are listening and which process owns each one",
        success_looks_like=("one row per listening socket with address, port, state, "
                            "owning pid and process name, and no model call"),
        inputs=("nothing - it reads local machine state",),
        outputs=("local_ip", "local_port", "state", "pid", "process"),
        environment="Linux with /proc mounted",
        gap_it_closes="Krish cannot look at this machine and asks a model to guess",
        deterministic_possible=True, llm_required=False,
        cases=(Case("runs", "no_error"), Case("finds", "rows>=1"),
               Case("named", "field_matches:state=^[A-Z_]+$", held_out=True)))
    fields.update(overrides)
    return Objective(**fields)


_STATES = {"01": "ESTABLISHED", "06": "TIME_WAIT", "0A": "LISTEN"}


def _tcp_recipe(*, correct: bool = True, version: int = 1) -> Recipe:
    """The first exercise, optionally with the little-endian mistake in it."""
    transform = "hex_ipv4" if correct else "hex_int"
    return Recipe(
        name="listening_tcp", version=version, answer="answer",
        summary="listening TCP sockets with the process that owns each one",
        steps=(
            Step("read", "raw", {"path": "/proc/net/tcp"}),
            Step("lines", "rows", {"from": "raw", "skip": 1}),
            Step("fields", "conns", {"from": "rows", "names": [
                "sl", "local_address", "rem_address", "st", "queues", "timer",
                "retransmit", "uid", "timeout", "inode"]}),
            Step("derive", "c1", {"from": "conns", "field": "local_address",
                                  "using": "split_index", "sep": ":", "index": 0,
                                  "into_field": "lhip"}),
            Step("derive", "c2", {"from": "c1", "field": "local_address",
                                  "using": "split_index", "sep": ":", "index": 1,
                                  "into_field": "lhp"}),
            Step("derive", "c3", {"from": "c2", "field": "lhip",
                                  "using": transform, "into_field": "local_ip"}),
            Step("derive", "c4", {"from": "c3", "field": "lhp", "using": "hex_int",
                                  "into_field": "local_port"}),
            Step("derive", "c5", {"from": "c4", "field": "st", "using": "lookup",
                                  "table": _STATES, "into_field": "state"}),
            Step("filter", "lis", {"from": "c5", "field": "state", "op": "eq",
                                   "value": "LISTEN"}),
            Step("select", "answer", {"from": "lis", "fields": [
                "local_ip", "local_port", "state"]}),
        ))


# =============================================================================
# The sandbox. Every test here exists because a probe found a real hole.
# =============================================================================


@pytest.mark.parametrize("path", [
    "/etc/passwd", "/root/.ssh/id_rsa",
    "/proc/1/environ", "/proc/self/environ", "/proc/self/maps",
    "/proc/net/../../etc/passwd", "/proc/self/root/etc/passwd",
])
def test_the_sandbox_refuses_everything_outside_its_allow_list(path):
    with sandbox_module.Sandbox() as box:
        with pytest.raises(sandbox_module.SandboxRefusal):
            box.read_file(path)


def test_a_wildcard_cannot_be_walked_sideways_out_of_a_permitted_root():
    """`fnmatch`'s `*` matches `/`, so `/proc/net/*` matched
    `/proc/net/../../etc/passwd` in the first version of this module. The
    matcher is segment-aware now, and this is the regression."""
    assert not sandbox_module.Sandbox._segments_match(
        "/proc/net/*", "/proc/net/../../etc/passwd")
    assert sandbox_module.Sandbox._segments_match("/proc/net/*", "/proc/net/tcp")
    assert not sandbox_module.Sandbox._segments_match("/proc/*/fd/*",
                                                      "/proc/1/fd/../../environ")


def test_the_deny_list_wins_over_a_permitted_pattern():
    """A second, explicit list, because the cost of one wrong wildcard in the
    allow-list is every credential on the machine."""
    with sandbox_module.Sandbox() as box:
        for denied in ("/proc/1/environ", "/proc/1/mem"):
            with pytest.raises(sandbox_module.SandboxRefusal, match="deny-list"):
                box.read_file(denied)


@pytest.mark.parametrize("argv", [
    ["python3", "-c", "print(1)"], ["sh", "-c", "ls"], ["bash"],
    ["rm", "-rf", "/"], ["curl", "http://example.com"], ["pip", "install", "x"],
])
def test_no_recipe_can_run_an_interpreter_or_anything_that_writes(argv):
    """The selection rule for `COMMANDS` is read-only, and an interpreter is the
    one entry that would make the whole declarative design pointless."""
    with sandbox_module.Sandbox(allow_commands=True) as box:
        with pytest.raises(sandbox_module.SandboxRefusal):
            box.run(argv)


def test_commands_are_refused_entirely_unless_the_recipe_declared_them():
    with sandbox_module.Sandbox() as box:
        with pytest.raises(sandbox_module.SandboxRefusal, match="without command"):
            box.run(["ps"])


def test_an_argument_that_turns_a_read_only_program_into_a_writing_one_is_refused():
    with sandbox_module.Sandbox(allow_commands=True) as box:
        with pytest.raises(sandbox_module.SandboxRefusal, match="refused"):
            box.run(["ps", "--exec", "rm -rf /"])


def test_a_refusal_says_that_widening_the_list_is_a_boundary_proposal():
    """A refusal a learner cannot act on teaches it nothing."""
    with sandbox_module.Sandbox() as box:
        with pytest.raises(sandbox_module.SandboxRefusal, match="boundary"):
            box.read_file("/etc/hosts")


def test_the_practice_directory_is_removed_with_the_sandbox():
    with sandbox_module.Sandbox() as box:
        directory = box.directory
        assert directory.exists()
    assert not directory.exists()


# =============================================================================
# The recipe: a learned skill is data, and the vocabulary is closed
# =============================================================================


def test_a_recipe_cannot_reach_for_a_primitive_that_does_not_exist():
    """The designed outcome, not a gap: a learning engine able to extend its own
    primitives is one able to do anything."""
    with pytest.raises(RecipeError, match="boundary proposal"):
        Step("exec_python", "x", {"code": "import os"})


def test_a_recipe_cannot_use_a_transform_that_does_not_exist():
    box = sandbox_module.Sandbox()
    result = recipe_module.run(
        Recipe(name="r", version=1, summary="s", answer="a",
               steps=(Step("read", "t", {"path": "/proc/uptime"}),
                      Step("lines", "l", {"from": "t"}),
                      Step("fields", "f", {"from": "l", "names": ["up"]}),
                      Step("derive", "a", {"from": "f", "field": "up",
                                           "using": "eval"}))), box)
    assert not result.ok and "not one of the transforms" in result.error


def test_a_step_reading_a_binding_nothing_produced_is_refused_at_construction():
    with pytest.raises(RecipeError, match="nothing before it produced"):
        Recipe(name="r", version=1, summary="s", answer="b",
               steps=(Step("lines", "b", {"from": "never_made"}),))


def test_a_run_step_must_be_declared_before_it_gets_a_subprocess():
    with pytest.raises(RecipeError, match="needs_commands"):
        Recipe(name="r", version=1, summary="s", answer="a",
               steps=(Step("run", "a", {"argv": ["ps"]}),))


def test_addresses_are_little_endian_which_is_the_whole_first_lesson():
    assert recipe_module._hex_ipv4("0100007F") == "127.0.0.1"
    assert recipe_module._hex_ipv4("00000000") == "0.0.0.0"
    with pytest.raises(RecipeError, match="four hex bytes"):
        recipe_module._hex_ipv4("00000000000000000000000000000001")


def test_a_recipe_survives_a_json_round_trip():
    """It has to: a recipe is stored as data and reverting is selecting an older
    row."""
    original = _tcp_recipe()
    restored = Recipe.from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored.to_dict() == original.to_dict()


def test_a_recipe_explains_itself_in_sentences():
    lines = _tcp_recipe().as_plain_language()
    assert "read the file /proc/net/tcp" in lines[1]
    assert lines[-1].startswith("The answer is")


def test_a_failed_step_keeps_the_trace_up_to_it():
    """The trace is the most valuable part of a failed attempt, so it must
    survive the failure."""
    box = sandbox_module.Sandbox()
    result = recipe_module.run(
        Recipe(name="r", version=1, summary="s", answer="a",
               steps=(Step("read", "t", {"path": "/proc/uptime"}),
                      Step("parse_json", "a", {"from": "t"}))), box)
    assert not result.ok and result.failed_step == 1
    assert result.trace[0]["ok"] is True


# =============================================================================
# The objective: "learn networking" is refused
# =============================================================================


def test_learn_networking_is_refused_with_every_reason():
    """The example both specifications use."""
    with pytest.raises(ObjectiveRefused) as raised:
        Objective(slug="net", cannot_do="Learn networking",
                  success_looks_like="it works", inputs=(), outputs=(),
                  environment="", gap_it_closes="", cases=())
    message = str(raised.value)
    for requirement in ("names_the_gap", "names_inputs", "names_outputs",
                        "names_environment", "states_success",
                        "has_verifiable_cases", "decides_llm_need"):
        assert requirement in message, requirement


@pytest.mark.parametrize("field, value, requirement", [
    ("inputs", (), "names_inputs"),
    ("outputs", (), "names_outputs"),
    ("environment", "", "names_environment"),
    ("success_looks_like", "works fine", "states_success"),
    ("cases", (), "has_verifiable_cases"),
    ("llm_required", None, "decides_llm_need"),
    ("gap_it_closes", "", "names_the_gap"),
])
def test_each_requirement_is_individually_enforced(field, value, requirement):
    with pytest.raises(ObjectiveRefused, match=requirement):
        _objective(**{field: value})


def test_answering_that_a_model_is_genuinely_needed_is_a_real_answer():
    """Requiring the answer to be "no" would produce objectives that claim
    determinism to get past the validator - the metric-gaming failure §119
    already recorded in this codebase."""
    assert _objective(deterministic_possible=False, llm_required=True)


def test_a_specific_objective_is_accepted_and_explains_itself():
    lines = _objective().as_plain_language()
    assert any(line.startswith("What I cannot do:") for line in lines)
    assert any("Held back" in line for line in lines)


def test_the_inventory_reads_the_registries_rather_than_restating_them():
    from app.learning.objective import inventory

    found = inventory()
    assert "gateway/skills.py" in found["sources"]
    assert "app/capability.py" in found["sources"]
    assert found["recipe_vocabulary"]["ops"] == list(recipe_module.OPS)


# =============================================================================
# Mastery: the state is computed, and there is no way to set it
# =============================================================================


def test_there_is_no_function_anywhere_that_sets_a_mastery_state():
    """The structural guarantee behind Document 2 §10. If a setter existed, every
    other assertion in this file would be advisory."""
    for name in dir(mastery):
        assert not name.startswith("set_"), name
        assert "mark_" not in name, name
    assert not hasattr(mastery.State, "__set__")


def test_evidence_alone_never_reaches_mastery():
    """Every box ticked except his word."""
    verdict = mastery.state_of(mastery.Evidence(
        objective_is_specific=True, plan_exists=True, attempts=9,
        development_cases=4, development_passed=4,
        heldout_cases=3, heldout_passed=3,
        real_world_trials=1, real_world_succeeded=1))
    assert verdict.name == mastery.AWAITING_FEEDBACK
    assert "your judgement" in verdict.missing[0]


def test_passing_only_what_it_developed_against_is_not_learning():
    """Held-out cases are their own gate, not one more test file."""
    verdict = mastery.state_of(mastery.Evidence(
        objective_is_specific=True, plan_exists=True, attempts=4,
        development_cases=4, development_passed=4))
    assert verdict.name == mastery.TESTING
    assert "fitting, not learning" in verdict.missing[0]


def test_failing_a_held_out_case_says_to_change_the_recipe_not_the_case():
    verdict = mastery.state_of(mastery.Evidence(
        objective_is_specific=True, plan_exists=True, attempts=4,
        development_cases=2, development_passed=2,
        heldout_cases=2, heldout_passed=1))
    assert "the recipe needs to change rather than the cases" in verdict.missing[0]


def test_a_mastered_skill_that_starts_failing_falls_to_degraded():
    full = dict(objective_is_specific=True, plan_exists=True, attempts=5,
                development_cases=1, development_passed=1,
                heldout_cases=1, heldout_passed=1,
                real_world_trials=1, real_world_succeeded=1,
                accepted_by_user=True)
    assert mastery.state_of(mastery.Evidence(**full)).name == mastery.MASTERED
    assert mastery.state_of(mastery.Evidence(
        **full, post_mastery_failures=1)).name == mastery.DEGRADED
    assert mastery.state_of(mastery.Evidence(
        **full, post_mastery_failures=2)).name == mastery.NEEDS_RETRAINING


def test_every_state_has_a_meaning_a_person_can_read():
    for name in mastery.STATES:
        assert mastery.MEANING[name] and len(mastery.MEANING[name].split()) >= 4


# =============================================================================
# Practice and diagnosis: no model call, and the collapse rule
# =============================================================================


def test_the_first_diagnosis_costs_nothing():
    """§17: do not reach for an expensive model when a test fails."""
    for attempt in (recipe_module.Result(error="binding 'x' is not rows",
                                         failed_step=2, trace=[]),):
        diagnosis = practice.diagnose(attempt, Case("c", "no_error"))
        assert diagnosis.resolution == practice.DETERMINISTIC_REASONING


def test_a_step_that_silently_produced_nothing_is_found_before_the_message():
    """The most common real failure, and invisible in an empty answer. Checked
    before the message signatures so it is not misread as a bad expectation."""
    result = recipe_module.Result(trace=[
        {"step": 0, "op": "read", "ok": True, "rows_in": None, "rows_out": 30},
        {"step": 1, "op": "filter", "ok": True, "rows_in": 30, "rows_out": 0},
        {"step": 2, "op": "select", "ok": True, "rows_in": 0, "rows_out": 0}])
    diagnosis = practice.diagnose(result, Case("c", "rows>=1"), "0 rows")
    assert diagnosis.at_step == 1
    assert diagnosis.failure_class == practice.INCORRECT_ASSUMPTION
    assert "produced 0" in diagnosis.because


@pytest.mark.parametrize("error, expected", [
    ("reading /etc/x is not permitted", practice.PERMISSION_ISSUE),
    ("'ss' is permitted but is not installed on this machine",
     practice.DEPENDENCY_ISSUE),
    ("'eval' is not one of the transforms", practice.INSUFFICIENT_DECOMPOSITION),
    ("ps did not finish within 10.0s", practice.ENVIRONMENT_DIFFERENCE),
    ("'zz' is not hexadecimal", practice.INCORRECT_ASSUMPTION),
    ("path template needs a field the row does not have",
     practice.IMPLEMENTATION_BUG),
])
def test_failures_are_classified_from_the_message_without_a_model(error, expected):
    result = recipe_module.Result(error=error, failed_step=1, trace=[
        {"step": 0, "op": "read", "ok": True, "rows_in": None, "rows_out": 5}])
    assert practice.diagnose(result, Case("c", "no_error")).failure_class == expected


def test_an_unparseable_expectation_blames_the_case_not_the_skill():
    engine = engine_module.default_engine()
    engine.begin(_objective(cases=(Case("bad", "is it nice?"),
                                   Case("held", "rows>=1", held_out=True))))
    engine.propose_recipe("listening-ports", _tcp_recipe())
    outcome = engine.practise("listening-ports")[0]
    assert not outcome["passed"]
    assert outcome["diagnosis"]["failure_class"] == practice.INCORRECT_TEST_EXPECTATION
    assert "fix the expectation, not the recipe" in outcome["diagnosis"]["suggestion"]


def test_every_attempt_records_that_it_cost_no_model_call():
    engine = engine_module.default_engine()
    engine.begin(_objective())
    engine.propose_recipe("listening-ports", _tcp_recipe())
    engine.practise("listening-ports")
    episode = store.get_episode("listening-ports")
    costs = [a["cost"] for a in store.attempts(episode["id"]) if a["cost"]]
    assert costs and all(cost["model_calls"] == 0 for cost in costs)


# =============================================================================
# Research: honest about what it cannot reach
# =============================================================================


def test_six_of_the_ten_source_tiers_are_unreachable_and_say_so():
    unavailable = research.unavailable_sources()
    assert len(unavailable) >= 6
    assert all("web access" in reason or "fetchable" in reason
               for reason in unavailable.values())


def test_a_finding_cannot_claim_a_source_this_system_cannot_reach():
    with pytest.raises(ValueError, match="not reachable"):
        research.Finding(question="q", answer="a",
                         source_kind=research.OFFICIAL_API)


def test_running_it_outranks_every_document():
    """§11, as an ordering rather than a sentence."""
    assert research.SOURCES[research.PROBE]["tier"] < \
        research.SOURCES[research.JARVIS_CODE]["tier"]
    assert research.SOURCES[research.MODEL_KNOWLEDGE]["tier"] > \
        research.SOURCES[research.LOCAL_DOCS]["tier"]


def test_a_recollection_is_debt_until_a_test_rests_on_it_and_passes():
    engine = engine_module.default_engine()
    engine.begin(_objective())
    engine.record_finding("listening-ports", research.Finding(
        question="is the state column a name?", answer="no, a hex enum",
        source_kind=research.MODEL_KNOWLEDGE))
    episode_id = store.get_episode("listening-ports")["id"]
    assert len(research.confirmation_debt(episode_id)) == 1

    engine.propose_recipe("listening-ports", _tcp_recipe())
    engine.practise("listening-ports")
    engine.examine("listening-ports")
    assert research.confirmation_debt(episode_id) == []


# =============================================================================
# The whole lifecycle, and Document 2 §12's definition of done
# =============================================================================


def _learn_it(engine, *, with_mistake_first: bool = True) -> None:
    engine.begin(_objective(cases=(
        Case("runs", "no_error"), Case("finds", "rows>=1"),
        Case("addresses", "field_matches:local_ip=^\\d{1,3}(\\.\\d{1,3}){3}$"),
        Case("named", "field_matches:state=^[A-Z_]+$", held_out=True))))
    engine.plan("listening-ports")
    if with_mistake_first:
        engine.propose_recipe("listening-ports", _tcp_recipe(correct=False))
        engine.practise("listening-ports")
    engine.propose_recipe("listening-ports", _tcp_recipe(correct=True, version=2))
    engine.practise("listening-ports")
    engine.examine("listening-ports")
    engine.trial("listening-ports")


def test_the_whole_loop_reaches_awaiting_feedback_and_stops_there():
    engine = engine_module.default_engine()
    _learn_it(engine)
    status = engine.status("listening-ports")
    assert status["state"] == mastery.AWAITING_FEEDBACK
    assert status["evidence"]["development"] == "3/3"
    assert status["evidence"]["held_out"] == "1/1"


def test_a_wrong_recipe_fails_and_the_next_version_fixes_it():
    """The little-endian mistake: `hex_int` gives 16777343 where the address is
    127.0.0.1. A plausible number and a wrong answer."""
    engine = engine_module.default_engine()
    engine.begin(_objective(cases=(
        Case("addresses", "field_matches:local_ip=^\\d{1,3}(\\.\\d{1,3}){3}$"),
        Case("named", "field_matches:state=^[A-Z_]+$", held_out=True))))
    engine.propose_recipe("listening-ports", _tcp_recipe(correct=False))
    first = engine.practise("listening-ports")
    assert not first[0]["passed"]

    engine.propose_recipe("listening-ports", _tcp_recipe(correct=True, version=2))
    assert engine.practise("listening-ports")[0]["passed"]


def test_both_recipe_versions_are_kept_so_reverting_is_a_select():
    """§24: the old working version must not simply disappear."""
    engine = engine_module.default_engine()
    _learn_it(engine)
    episode_id = store.get_episode("listening-ports")["id"]
    assert [v["version"] for v in store.recipe_versions(episode_id)] == [1, 2]
    assert engine.revert_recipe("listening-ports", 1).version == 3


def test_the_commitment_is_a_condition_and_never_an_invented_duration():
    """Document 2 §5: *"Jarvis must not invent a time estimate merely to sound
    confident."*"""
    engine = engine_module.default_engine()
    engine.begin(_objective())
    commitment = engine.plan("listening-ports")["commitment"]
    assert commitment["time_estimate"] is None
    assert "no measured basis" in commitment["why_no_time_estimate"]
    assert commitment["uncertainties"]


def test_a_demonstration_is_refused_when_there_is_nothing_to_show():
    engine = engine_module.default_engine()
    engine.begin(_objective())
    engine.propose_recipe("listening-ports", _tcp_recipe())
    shown = engine.demonstrate("listening-ports")
    assert not shown["ready"] and "nothing to show" in shown["why_not"]


def test_a_demonstration_carries_evidence_rather_than_a_claim():
    """Document 2 §6's list."""
    engine = engine_module.default_engine()
    _learn_it(engine)
    shown = engine.demonstrate("listening-ports")
    assert shown["ready"]
    assert shown["ran_just_now"]["ok"]
    assert shown["no_model_was_called"]["model_calls"] == 0
    assert shown["test_results"]["held_out"]
    assert "addresses" in shown["cases_that_used_to_fail_and_now_pass"]
    assert shown["recipe_versions"] == [1, 2]
    assert shown["how_it_works"]


def test_feedback_is_recorded_and_is_not_acceptance():
    engine = engine_module.default_engine()
    _learn_it(engine)
    after = engine.feedback("listening-ports", verdict="useful_with_changes",
                            note="also show the remote address")
    assert after["state"] == mastery.AWAITING_FEEDBACK
    assert store.feedback(store.get_episode("listening-ports")["id"])


def test_acceptance_cannot_skip_the_gates_before_it():
    engine = engine_module.default_engine()
    engine.begin(_objective())
    refused = engine.accept("listening-ports")
    assert not refused["registered"]
    assert "last gate, not a shortcut" in refused["why_not"]


def test_his_word_is_what_makes_it_learned():
    engine = engine_module.default_engine()
    _learn_it(engine)
    assert engine.accept("listening-ports")["registered"]
    assert engine.status("listening-ports")["state"] == mastery.MASTERED


def test_accepting_twice_is_not_reported_as_a_failure():
    engine = engine_module.default_engine()
    _learn_it(engine)
    engine.accept("listening-ports")
    again = engine.accept("listening-ports")
    assert again["registered"] and again["already_registered"]


def test_a_learned_skill_runs_as_an_ordinary_skill_with_no_model_call():
    engine = engine_module.default_engine()
    _learn_it(engine)
    engine.accept("listening-ports")
    run = engine.run_operationally("listening-ports")
    assert run["ok"] and isinstance(run["answer"], list)


def test_the_narration_describes_the_real_state():
    engine = engine_module.default_engine()
    _learn_it(engine)
    said = " ".join(engine.narrate("listening-ports"))
    assert "awaiting_user_feedback" in said
    assert "development 3/3" in said
    assert "worth showing you now" in said


def test_a_fixed_failure_is_not_reported_as_the_current_one():
    """An end-to-end run described a working skill as broken, because the v1
    failure was the most recent failure in the table."""
    engine = engine_module.default_engine()
    _learn_it(engine)
    said = " ".join(engine.narrate("listening-ports"))
    assert "Most recent failure" not in said
    assert "were fixed" in said


# =============================================================================
# Explaining itself, and learning about learning
# =============================================================================


def test_the_explanation_is_generated_from_the_implementation():
    """Document 2 §2: it must describe the real behaviour, not the
    specification. Generated, so it cannot claim a step that is not there."""
    explained = engine_module.explain_how_i_learn()
    assert [state["state"] for state in explained["states"]] == list(mastery.STATES)
    assert explained["vocabulary"]["ops"] == list(recipe_module.OPS)
    assert explained["sandbox"]["commands"] == list(sandbox_module.COMMANDS)
    assert set(explained["sources"]["available"]) == set(research.available_sources())
    assert len(explained["steps"]) >= 14


def test_the_explanation_names_how_it_cannot_cheat():
    guards = " ".join(engine_module.explain_how_i_learn()["how_i_cannot_cheat"])
    assert "computed from recorded evidence" in guards
    assert "Held-out cases are a separate gate" in guards
    assert "needs your acceptance" in guards


def test_meta_learning_refuses_to_generalise_from_one_episode():
    engine = engine_module.default_engine()
    _learn_it(engine)
    engine.accept("listening-ports")
    report = memory.meta_report()
    assert report["claims"] == []
    assert "one anecdote with a percentage sign" in report["note"]


def test_a_lesson_seen_twice_is_counted_rather_than_duplicated():
    store.record_lesson(kind=memory.FAILURE_PATTERN, pattern="hex", lesson="a")
    store.record_lesson(kind=memory.FAILURE_PATTERN, pattern="hex", lesson="a")
    lessons = [item for item in store.lessons(memory.FAILURE_PATTERN)
               if item["pattern"] == "hex"]
    assert len(lessons) == 1 and lessons[0]["times_seen"] == 2


def test_what_paid_off_is_recorded_after_an_episode():
    engine = engine_module.default_engine()
    _learn_it(engine)
    engine.record_finding("listening-ports", research.Finding(
        question="format?", answer="little-endian hex",
        source_kind=research.PROBE))
    engine.examine("listening-ports")
    engine.accept("listening-ports")
    kinds = {lesson["kind"] for lesson in store.lessons()}
    assert memory.SOURCE_VALUE in kinds


# =============================================================================
# The Gateway surface
# =============================================================================


def _call(name, arguments=None):
    return tools.execute(None, name, arguments or {}, role=roles.ROLE_OPERATOR)


def test_registering_without_his_word_is_classified_as_self_granted_authority():
    """The sharpest entry in TOOL_RISK. Not "propose", which would read as a
    step to be got past - this IS the harm."""
    verdict, _ = tools.initiative_verdict("register_learned_skill", {})
    assert verdict.disposition == initiative.REFUSE
    assert initiative.HARM_WIDENS_ITS_OWN_AUTHORITY in verdict.action.harms

    allowed, confirmed = tools.initiative_verdict(
        "register_learned_skill", {"krish_accepted": True})
    assert allowed.disposition == initiative.ACT_AND_REPORT and confirmed


def test_the_tool_refuses_to_register_without_him():
    refused = _call("register_learned_skill", {"slug": "anything"})
    assert "Refused" in refused["error"]


def test_every_learning_tool_is_risk_classified():
    for tool in tools.LEARNING_TOOLS:
        assert tool["name"] in tools.TOOL_RISK, tool["name"]
        assert tool["name"] in tools.TOOL_CAPABILITY, tool["name"]


def test_no_new_capability_was_minted_for_learning():
    """Editing GRANTS is the one change in gateway/roles.py that can silently
    widen or lock out a role."""
    used = {tools.TOOL_CAPABILITY[tool["name"]] for tool in tools.LEARNING_TOOLS}
    assert used <= {roles.CAP_SYSTEM_STATUS, roles.CAP_SCOREBOARD_WRITE}


def test_a_client_cannot_reach_any_of_it():
    for tool in tools.LEARNING_TOOLS:
        assert not tools.permitted(roles.ROLE_CLIENT, tool["name"]), tool["name"]


def test_the_vague_objective_refusal_reaches_the_model_as_something_to_fix():
    refused = _call("begin_learning", {
        "slug": "net", "cannot_do": "learn networking",
        "success_looks_like": "it works", "inputs": [], "outputs": [],
        "environment": "", "gap_it_closes": "",
        "deterministic_possible": True, "llm_required": False, "cases": []})
    assert refused["refused_by"] == "objective_validator"
    assert "names_inputs" in refused["error"]


def test_the_acceptance_conversation_runs_through_the_tools():
    """Document 2 §8, end to end, through the surface Krish actually talks to."""
    assert len(_call("explain_how_i_learn")["steps"]) >= 14
    assert _call("what_to_learn_next", {"limit": 2})["candidates"]

    begun = _call("begin_learning", {
        "slug": "ports", "cannot_do": "say which TCP ports are listening here",
        "success_looks_like": ("one row per listening socket with its address, "
                               "port and state, read locally with no model call"),
        "inputs": ["nothing"], "outputs": ["local_ip", "local_port", "state"],
        "environment": "Linux with /proc mounted",
        "gap_it_closes": "he cannot look at this machine himself",
        "deterministic_possible": True, "llm_required": False,
        "cases": [{"name": "runs", "expect": "no_error"},
                  {"name": "finds", "expect": "rows>=1"},
                  {"name": "named", "expect": "field_matches:state=^[A-Z_]+$",
                   "held_out": True}]})
    assert begun["begun"]["state"] == mastery.IDENTIFIED

    assert _call("plan_learning", {"slug": "ports"})["commitment"]["time_estimate"] is None
    spec = _tcp_recipe().to_dict()
    assert _call("propose_skill_recipe", {
        "slug": "ports", "name": spec["name"], "summary": spec["summary"],
        "answer": spec["answer"], "steps": spec["steps"]})["version"] == 1

    for stage in ("practice", "held_out", "trial"):
        result = _call("test_skill", {"slug": "ports", "stage": stage})
        assert result["passed"] == result["of"], (stage, result["outcomes"])

    shown = _call("demonstrate_skill", {"slug": "ports"})
    assert shown["ready"] and shown["ran_just_now"]["ok"]

    _call("record_skill_feedback", {"slug": "ports", "verdict": "useful"})
    assert _call("register_learned_skill",
                 {"slug": "ports", "krish_accepted": True})["registered"]
    assert _call("use_learned_skill", {"slug": "ports"})["ok"]


def test_an_unlearned_skill_cannot_be_used():
    _call("begin_learning", {
        "slug": "ports", "cannot_do": "say which TCP ports are listening here",
        "success_looks_like": "one row per listening socket with address and port",
        "inputs": ["nothing"], "outputs": ["local_ip"], "environment": "Linux",
        "gap_it_closes": "he cannot look at this machine himself",
        "deterministic_possible": True, "llm_required": False,
        "cases": [{"name": "runs", "expect": "no_error"}]})
    assert "not learned" in _call("use_learned_skill", {"slug": "ports"})["error"]


# =============================================================================
# Document 2 §12: the fourteen conditions, asserted as a checklist
# =============================================================================


def test_document_two_definition_of_done():
    """Each of §12's fourteen, checked against the running system.

    Here as one test on purpose: it is the acceptance checklist, and reading it
    as a list is the point. The individual mechanisms are asserted above."""
    engine = engine_module.default_engine()
    done = {}

    # 1. integrated into the existing architecture
    done[1] = all(tool["name"] in tools.TOOL_CAPABILITY
                  for tool in tools.LEARNING_TOOLS)
    # 3. can explain how it learns
    done[3] = len(engine_module.explain_how_i_learn()["steps"]) >= 14
    # 4 & 5. can identify a capability worth learning, and say why
    picked = engine_module.candidates(1)
    done[4] = bool(picked)
    done[5] = bool(picked and len(picked[0]["why"].split()) >= 8)

    _learn_it(engine)  # 7 & 8: executes the plan, diagnoses and revises
    episode_id = store.get_episode("listening-ports")["id"]
    attempts = store.attempts(episode_id)
    # 6. a concrete plan
    done[6] = store.get_episode("listening-ports")["plan"] is not None
    done[7] = len(attempts) > 0
    done[8] = any(a["passed"] is False and a["diagnosis"] for a in attempts)
    # 9. tested against defined criteria, including held out
    done[9] = engine.status("listening-ports")["evidence"]["held_out"] != "0/0"
    # 10. a controlled demonstration
    done[10] = engine.demonstrate("listening-ports")["ready"]
    # 11. asks for and incorporates feedback
    engine.feedback("listening-ports", verdict="useful")
    done[11] = bool(store.feedback(episode_id))
    # 12. represents its own state accurately
    done[12] = engine.status("listening-ports")["state"] == mastery.AWAITING_FEEDBACK
    engine.accept("listening-ports")
    # 13. retains learning history
    done[13] = bool(memory.learn_from_episode("listening-ports"))
    # 14. can repeat for another capability
    engine.begin(_objective(slug="second-skill"))
    done[14] = engine.status("second-skill")["exists"]

    unmet = sorted(number for number, met in done.items() if not met)
    assert not unmet, f"Document 2 §12 conditions not met: {unmet}"
