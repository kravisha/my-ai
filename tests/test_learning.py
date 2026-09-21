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
import os
import pathlib
import shutil

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


# WHY THERE ARE TWO RECIPES BELOW, and it is not convenience.
#
# The first version of this file drove every lifecycle test with the /proc
# recipe, and Windows CI failed seventeen of them - because `/proc` is not a
# Windows thing and `os.path.abspath("/proc/net/tcp")` there is
# `D:\proc\net\tcp`. Skipping them on Windows would have left the engine's
# whole loop untested on the platform Krish actually runs.
#
# So the lifecycle is exercised by `_portable_recipe`, which reads a file
# committed to this repository and therefore behaves identically everywhere, and
# `_tcp_recipe` is kept for the posix-specific tests that are genuinely about
# reading kernel state. The Windows route has its own test that needs no Windows
# to run.
_STATES = {"01": "ESTABLISHED", "06": "TIME_WAIT", "0A": "LISTEN"}


def _portable_recipe(*, correct: bool = True, version: int = 1) -> Recipe:
    """Reads `config/router.yaml`, which exists on every checkout of this repo.

    `correct=False` makes the same mistake in kind as the little-endian one: a
    pattern that matches nothing, so the recipe runs cleanly to an empty answer.
    That is the failure shape `practice._collapse` exists to catch, which makes
    it the right wrong-answer to test the loop with."""
    pattern = r"^([a-z_]+):" if correct else r"^([A-Z]+):"
    return Recipe(
        name="config_keys", version=version, answer="answer",
        summary="the top-level keys of the router policy file, read locally",
        steps=(Step("read", "raw", {"path": "config/router.yaml"}),
               Step("regex_rows", "rows", {"from": "raw", "pattern": pattern,
                                           "names": ["key"]}),
               Step("unique", "answer", {"from": "rows", "by": "key"})))


def _portable_objective(**overrides):
    fields = dict(
        slug="router-policy-keys",
        cannot_do="list the top-level settings in my own router policy file",
        success_looks_like=("one row per top-level key in config/router.yaml, read "
                            "from the file itself with no model call"),
        inputs=("nothing - it reads a file in this repository",),
        outputs=("key",),
        environment="any machine with this repository checked out",
        gap_it_closes="answering what my own policy says currently costs a model call",
        deterministic_possible=True, llm_required=False,
        cases=(Case("runs", "no_error"), Case("finds", "rows>=3"),
               Case("named", "field_matches:key=^[a-z_]+$", held_out=True)))
    fields.update(overrides)
    return Objective(**fields)


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
    allow-list is every credential on the machine.

    `.env` and `*.db` are used rather than `/proc/*/environ` so the assertion is
    about the deny-list on every platform - on Windows a `/proc` path is refused
    earlier, for being absent, and would not reach this check."""
    root = sandbox_module.PROJECT_ROOT
    with sandbox_module.Sandbox() as box:
        for denied in (root / "docs" / ".env", root / "logs" / "model_spend.db"):
            with pytest.raises(sandbox_module.SandboxRefusal, match="deny-list"):
                box.read_file(str(denied))


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


@pytest.mark.parametrize("denied", [
    r"D:\a\my-ai\my-ai\docs\.env",
    r"D:\a\my-ai\my-ai\logs\model_spend.db",
    r"D:\a\my-ai\my-ai\config\server.key",
    r"D:\a\my-ai\my-ai\logs\id_rsa",
])
def test_the_deny_list_fires_on_a_windows_path_too(denied):
    """Windows CI found that it did not, and the failing assertion was the
    smaller half of the news.

    `_segments_match` split on `/` only, so a Windows path was a single
    segment: `**/.env` had nothing to match its two parts against and the
    deny-list never fired at all. The project's own `logs/`, `docs/` and
    `config/` are readable by design, so on the platform Krish actually runs
    the one list standing between a recipe and every credential in this project
    was inert.

    Asserted with an explicit platform so it holds from a posix machine - the
    same device `_platform_surface_for` already uses."""
    assert any(
        sandbox_module.Sandbox._segments_match(pattern, denied, platform="nt")
        for pattern in sandbox_module.DENIED_PATTERNS), denied


def test_a_wildcard_cannot_be_walked_sideways_across_a_backslash_either():
    """The other half, and it is the first probe's hole reopened by the
    platform. The project patterns are built with `Path`, so on Windows the
    pattern was one segment too - and `fnmatch` on one segment is exactly the
    whole-string match whose `*` crosses separators."""
    match = sandbox_module.Sandbox._segments_match
    assert not match(r"D:\p\docs\*", r"D:\p\docs\nested\deep.txt", platform="nt")
    assert not match(r"D:\p\docs\*", r"D:\p\docs\..\..\etc\passwd", platform="nt")
    assert match(r"D:\p\docs\*", r"D:\p\docs\ARCHITECTURE.md", platform="nt")


def test_a_backslash_is_an_ordinary_character_in_a_posix_filename():
    """The fix must not become a second bug wearing the first one's clothes:
    on posix a backslash is a legal character in a name, not a separator."""
    assert sandbox_module.Sandbox._split(r"a\b", platform="posix") == [r"a\b"]
    assert sandbox_module.Sandbox._split(r"a\b", platform="nt") == ["a", "b"]


def test_a_descriptor_is_not_a_readable_file_however_permitted_the_link_is():
    """The second security probe of this module found this, and none of the
    tests above did.

    `/proc/<pid>/fd/<n>` has to be reachable: it is the only way to map a socket
    to the process that owns it, which is the first exercise. But reading it as
    a *file* returns the contents of whatever the descriptor points at, so
    `read_file("/proc/self/fd/3")` returned a `.env` that `read_file` had just
    refused by name. The deny-list was intact and had been walked around."""
    assert not any(pattern.startswith("/proc/*/fd")
                   for pattern in sandbox_module.READ_PATTERNS)
    assert "/proc/*/fd/*" in sandbox_module.LINK_ONLY_PATTERNS


@pytest.mark.skipif(not pathlib.Path("/proc/self/fd").is_dir(),
                    reason="the descriptor route only exists where /proc is")
def test_the_descriptor_route_is_closed_and_the_socket_mapping_still_works(tmp_path):
    """Both halves matter. Closing the hole by removing the pattern entirely
    would have taken the socket-to-process join with it, which is the skill."""
    secret = tmp_path / ".env"
    secret.write_text("KIMI_API_KEY=sk-not-a-real-key\n", encoding="utf-8")

    with sandbox_module.Sandbox() as box:
        with pytest.raises(sandbox_module.SandboxRefusal):
            box.read_file(str(secret))
        with secret.open("rb") as handle:
            descriptor = f"/proc/self/fd/{handle.fileno()}"
            with pytest.raises(sandbox_module.SandboxRefusal, match="descriptor"):
                box.read_file(descriptor)
            assert pathlib.Path(box.read_link(descriptor)).resolve() == \
                secret.resolve(), "the link target is still readable"


@pytest.mark.parametrize("named", [
    "/tmp/planted/ss", "./ss", "../bin/ps", "subdir/netstat",
])
def test_a_program_may_be_named_but_never_pathed(named):
    """The other hole from the same probe. The allow-list checked
    `basename(argv[0])` and then executed `argv` as written, so
    `run(["/tmp/anywhere/ss"])` ran a planted script and returned its output -
    "read-only programs only" defeated by naming a file after one of them."""
    with sandbox_module.Sandbox(allow_commands=True) as box:
        with pytest.raises(sandbox_module.SandboxRefusal, match="names a path"):
            box.run([named])


@pytest.mark.skipif(os.name != "posix", reason="plants an executable script")
def test_a_file_named_after_an_allowed_program_does_not_get_to_be_it(tmp_path):
    """The repro, kept. `ps` is on the allow-list; a file called `ps` is not."""
    planted = tmp_path / "ps"
    planted.write_text("#!/bin/sh\necho PWNED\n", encoding="utf-8")
    planted.chmod(0o755)

    with sandbox_module.Sandbox(allow_commands=True) as box:
        with pytest.raises(sandbox_module.SandboxRefusal):
            box.run([str(planted)])
        if shutil.which("ps"):
            assert "PWNED" not in box.run(["ps"]), \
                "PATH resolution decides which ps runs, not the caller"


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
               steps=(Step("read", "t", {"path": "config/router.yaml"}),
                      Step("lines", "l", {"from": "t"}),
                      Step("fields", "f", {"from": "l", "names": ["word"]}),
                      Step("derive", "a", {"from": "f", "field": "word",
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
               steps=(Step("read", "t", {"path": "config/router.yaml"}),
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
    engine.begin(_portable_objective(cases=(
        Case("bad", "is it nice?"), Case("held", "rows>=1", held_out=True))))
    engine.propose_recipe(SLUG, _portable_recipe())
    outcome = engine.practise(SLUG)[0]
    assert not outcome["passed"]
    assert outcome["diagnosis"]["failure_class"] == practice.INCORRECT_TEST_EXPECTATION
    assert "fix the expectation, not the recipe" in outcome["diagnosis"]["suggestion"]


def test_every_attempt_records_that_it_cost_no_model_call():
    engine = engine_module.default_engine()
    engine.begin(_portable_objective())
    engine.propose_recipe(SLUG, _portable_recipe())
    engine.practise(SLUG)
    episode = store.get_episode(SLUG)
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
    engine.begin(_portable_objective())
    engine.record_finding(SLUG, research.Finding(
        question="are the top-level keys lower case?", answer="yes, all of them",
        source_kind=research.MODEL_KNOWLEDGE))
    episode_id = store.get_episode(SLUG)["id"]
    assert len(research.confirmation_debt(episode_id)) == 1

    engine.propose_recipe(SLUG, _portable_recipe())
    engine.practise(SLUG)
    engine.examine(SLUG)
    assert research.confirmation_debt(episode_id) == []


# =============================================================================
# The whole lifecycle, and Document 2 §12's definition of done
# =============================================================================


SLUG = "router-policy-keys"


def _learn_it(engine, *, with_mistake_first: bool = True) -> None:
    """The whole loop, on a recipe that behaves the same on every platform."""
    engine.begin(_portable_objective())
    engine.plan(SLUG)
    if with_mistake_first:
        engine.propose_recipe(SLUG, _portable_recipe(correct=False))
        engine.practise(SLUG)
    engine.propose_recipe(SLUG, _portable_recipe(correct=True, version=2))
    engine.practise(SLUG)
    engine.examine(SLUG)
    engine.trial(SLUG)


def test_the_whole_loop_reaches_awaiting_feedback_and_stops_there():
    engine = engine_module.default_engine()
    _learn_it(engine)
    status = engine.status(SLUG)
    assert status["state"] == mastery.AWAITING_FEEDBACK
    assert status["evidence"]["development"] == "2/2"
    assert status["evidence"]["held_out"] == "1/1"


def test_a_wrong_recipe_fails_and_the_next_version_fixes_it():
    """A recipe that runs cleanly to an empty answer - the failure shape
    `practice._collapse` exists for, and the one an empty result hides. The
    posix equivalent is the little-endian mistake, where `hex_int` gives
    16777343 for an address that is 127.0.0.1: a plausible number and a wrong
    answer. That one is `test_addresses_are_little_endian...`."""
    engine = engine_module.default_engine()
    engine.begin(_portable_objective())
    engine.propose_recipe(SLUG, _portable_recipe(correct=False))
    first = {outcome["case"]: outcome for outcome in engine.practise(SLUG)}
    assert not first["finds"]["passed"]
    assert first["finds"]["diagnosis"]["failure_class"] == \
        practice.INCORRECT_ASSUMPTION

    engine.propose_recipe(SLUG, _portable_recipe(correct=True, version=2))
    assert all(outcome["passed"] for outcome in engine.practise(SLUG))


def test_both_recipe_versions_are_kept_so_reverting_is_a_select():
    """§24: the old working version must not simply disappear."""
    engine = engine_module.default_engine()
    _learn_it(engine)
    episode_id = store.get_episode(SLUG)["id"]
    assert [v["version"] for v in store.recipe_versions(episode_id)] == [1, 2]
    assert engine.revert_recipe(SLUG, 1).version == 3


def test_the_commitment_is_a_condition_and_never_an_invented_duration():
    """Document 2 §5: *"Jarvis must not invent a time estimate merely to sound
    confident."*"""
    engine = engine_module.default_engine()
    engine.begin(_portable_objective())
    commitment = engine.plan(SLUG)["commitment"]
    assert commitment["time_estimate"] is None
    assert "no measured basis" in commitment["why_no_time_estimate"]
    assert commitment["uncertainties"]


def test_a_demonstration_is_refused_when_there_is_nothing_to_show():
    engine = engine_module.default_engine()
    engine.begin(_portable_objective())
    engine.propose_recipe(SLUG, _portable_recipe())
    shown = engine.demonstrate(SLUG)
    assert not shown["ready"] and "nothing to show" in shown["why_not"]


def test_a_demonstration_carries_evidence_rather_than_a_claim():
    """Document 2 §6's list."""
    engine = engine_module.default_engine()
    _learn_it(engine)
    shown = engine.demonstrate(SLUG)
    assert shown["ready"]
    assert shown["ran_just_now"]["ok"]
    assert shown["no_model_was_called"]["model_calls"] == 0
    assert shown["test_results"]["held_out"]
    assert "finds" in shown["cases_that_used_to_fail_and_now_pass"]
    assert shown["recipe_versions"] == [1, 2]
    assert shown["how_it_works"]


def test_feedback_is_recorded_and_is_not_acceptance():
    engine = engine_module.default_engine()
    _learn_it(engine)
    after = engine.feedback(SLUG, verdict="useful_with_changes",
                            note="also show the remote address")
    assert after["state"] == mastery.AWAITING_FEEDBACK
    assert store.feedback(store.get_episode(SLUG)["id"])


def test_acceptance_cannot_skip_the_gates_before_it():
    engine = engine_module.default_engine()
    engine.begin(_portable_objective())
    refused = engine.accept(SLUG)
    assert not refused["registered"]
    assert "last gate, not a shortcut" in refused["why_not"]


def test_his_word_is_what_makes_it_learned():
    engine = engine_module.default_engine()
    _learn_it(engine)
    assert engine.accept(SLUG)["registered"]
    assert engine.status(SLUG)["state"] == mastery.MASTERED


def test_accepting_twice_is_not_reported_as_a_failure():
    engine = engine_module.default_engine()
    _learn_it(engine)
    engine.accept(SLUG)
    again = engine.accept(SLUG)
    assert again["registered"] and again["already_registered"]


def test_a_learned_skill_runs_as_an_ordinary_skill_with_no_model_call():
    engine = engine_module.default_engine()
    _learn_it(engine)
    engine.accept(SLUG)
    run = engine.run_operationally(SLUG)
    assert run["ok"] and isinstance(run["answer"], list)


def test_the_narration_describes_the_real_state():
    engine = engine_module.default_engine()
    _learn_it(engine)
    said = " ".join(engine.narrate(SLUG))
    assert "awaiting_user_feedback" in said
    assert "development 2/2" in said
    assert "worth showing you now" in said


def test_a_fixed_failure_is_not_reported_as_the_current_one():
    """An end-to-end run described a working skill as broken, because the v1
    failure was the most recent failure in the table."""
    engine = engine_module.default_engine()
    _learn_it(engine)
    said = " ".join(engine.narrate(SLUG))
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
    engine.accept(SLUG)
    report = memory.meta_report()
    assert report["claims"] == []
    assert "one anecdote with a percentage sign" in report["note"]


def test_a_lesson_seen_twice_is_counted_rather_than_duplicated():
    store.record_lesson(kind=memory.FAILURE_PATTERN, pattern="hex", lesson="a")
    store.record_lesson(kind=memory.FAILURE_PATTERN, pattern="hex", lesson="a")
    lessons = [item for item in store.lessons(memory.FAILURE_PATTERN)
               if item["pattern"] == "hex"]
    assert len(lessons) == 1 and lessons[0]["times_seen"] == 2


def test_the_cheapest_rung_reported_is_the_cheapest_on_the_ladder():
    """`list(rungs).index` is insertion order, not cost order, so an episode
    whose *first* failure had to escalate reported `external_model` as its
    cheapest rung - the exact opposite of what this lesson is for."""
    episode_id = store.create_episode("rungs", {"slug": "rungs"}, origin="test")
    for resolution in (practice.EXTERNAL_MODEL, practice.DETERMINISTIC_REASONING):
        store.record_attempt(
            episode_id, kind=store.KIND_PRACTICE, passed=False, case_name="c",
            diagnosis={"failure_class": practice.IMPLEMENTATION_BUG,
                       "resolution": resolution})
    store.record_attempt(episode_id, kind=store.KIND_PRACTICE, passed=True,
                         case_name="c")

    lesson = next(item for item in memory.learn_from_episode("rungs")
                  if item["pattern"] == "diagnosis_resolution")
    assert lesson["lesson"].endswith(
        f"Cheapest rung used: {practice.DETERMINISTIC_REASONING}")


def test_what_paid_off_is_recorded_after_an_episode():
    engine = engine_module.default_engine()
    _learn_it(engine)
    engine.record_finding(SLUG, research.Finding(
        question="format?", answer="little-endian hex",
        source_kind=research.PROBE))
    engine.examine(SLUG)
    engine.accept(SLUG)
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

    objective = _portable_objective().to_dict()
    begun = _call("begin_learning", objective)
    assert begun["begun"]["state"] == mastery.IDENTIFIED

    assert _call("plan_learning", {"slug": SLUG})["commitment"]["time_estimate"] is None
    spec = _portable_recipe().to_dict()
    assert _call("propose_skill_recipe", {
        "slug": SLUG, "name": spec["name"], "summary": spec["summary"],
        "answer": spec["answer"], "steps": spec["steps"]})["version"] == 1

    for stage in ("practice", "held_out", "trial"):
        result = _call("test_skill", {"slug": SLUG, "stage": stage})
        assert result["passed"] == result["of"], (stage, result["outcomes"])

    shown = _call("demonstrate_skill", {"slug": SLUG})
    assert shown["ready"] and shown["ran_just_now"]["ok"]

    _call("record_skill_feedback", {"slug": SLUG, "verdict": "useful"})
    assert _call("register_learned_skill",
                 {"slug": SLUG, "krish_accepted": True})["registered"]
    assert _call("use_learned_skill", {"slug": SLUG})["ok"]


def test_registering_through_the_tool_counts_each_lesson_once():
    """`meta_report` is entirely frequency claims - *"this has come up 14
    times"* - so a lesson incremented twice per registration made the one thing
    meta-learning says wrong by a factor of two. `engine.accept` writes the
    lessons; the tool reads them back rather than re-deriving them."""
    engine = engine_module.default_engine()
    _learn_it(engine)

    registered = _call("register_learned_skill",
                       {"slug": SLUG, "krish_accepted": True})

    assert registered["registered"]
    assert registered["lessons_kept"], "the tool still reports what was learned"
    assert all(lesson["times_seen"] == 1 for lesson in store.lessons()), \
        [(item["pattern"], item["times_seen"]) for item in store.lessons()]


def test_an_unlearned_skill_cannot_be_used():
    _call("begin_learning", _portable_objective().to_dict())
    assert "not learned" in _call("use_learned_skill", {"slug": SLUG})["error"]


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
    episode_id = store.get_episode(SLUG)["id"]
    attempts = store.attempts(episode_id)
    # 6. a concrete plan
    done[6] = store.get_episode(SLUG)["plan"] is not None
    done[7] = len(attempts) > 0
    done[8] = any(a["passed"] is False and a["diagnosis"] for a in attempts)
    # 9. tested against defined criteria, including held out
    done[9] = engine.status(SLUG)["evidence"]["held_out"] != "0/0"
    # 10. a controlled demonstration
    done[10] = engine.demonstrate(SLUG)["ready"]
    # 11. asks for and incorporates feedback
    engine.feedback(SLUG, verdict="useful")
    done[11] = bool(store.feedback(episode_id))
    # 12. represents its own state accurately
    done[12] = engine.status(SLUG)["state"] == mastery.AWAITING_FEEDBACK
    engine.accept(SLUG)
    # 13. retains learning history
    done[13] = bool(memory.learn_from_episode(SLUG))
    # 14. can repeat for another capability
    engine.begin(_portable_objective(slug="second-skill"))
    done[14] = engine.status("second-skill")["exists"]

    unmet = sorted(number for number, met in done.items() if not met)
    assert not unmet, f"Document 2 §12 conditions not met: {unmet}"


# =============================================================================
# Windows. The platform Krish runs, and the one that found the last real defect.
# =============================================================================

# Captured shapes of real Windows output, so the Windows route can be proven from
# any platform. `netstat -ano` prints four lines of preamble and omits the State
# column for UDP; `tasklist /fo csv /nh` quotes every field and its image name
# contains spaces.
_NETSTAT_ANO = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1084
  TCP    0.0.0.0:445            0.0.0.0:0              LISTENING       4
  TCP    127.0.0.1:50505        0.0.0.0:0              LISTENING       8724
  TCP    127.0.0.1:50506        127.0.0.1:50505        ESTABLISHED     8724
  TCP    [::]:135               [::]:0                 LISTENING       1084
  UDP    0.0.0.0:500            *:*                                    1234
"""
_TASKLIST_CSV = (
    '"System","4","Services","0","1,234 K"\n'
    '"svchost.exe","1084","Services","0","12,345 K"\n'
    '"jarvis-gateway.exe","8724","Console","1","98,765 K"\n')


def _windows_recipe() -> Recipe:
    """The Windows route to the first skill, parse half, over injected output.

    Injected rather than run, so the assertion holds on any platform: what is
    being proven is that the **primitives suffice** for Windows, which is the
    thing that decides whether the engine can learn anything there at all. The
    two `run` steps are asserted separately by
    `test_the_windows_route_only_needs_allow_listed_commands`."""
    return Recipe(
        name="listening_tcp_windows", version=1, answer="answer",
        summary="listening TCP sockets with owning process, from netstat and tasklist",
        inputs=("netstat_out", "tasklist_out"),
        steps=(
            Step("lines", "nrows", {"from": "netstat_out", "skip": 4},
                 "netstat prints four lines of preamble"),
            Step("fields", "conns", {"from": "nrows", "names": [
                "proto", "local", "foreign", "state", "pid"]},
                 "UDP rows have no State column, so skip_short drops them - wanted"),
            Step("filter", "tcp", {"from": "conns", "field": "proto", "op": "eq",
                                   "value": "TCP"}),
            Step("filter", "lis", {"from": "tcp", "field": "state", "op": "eq",
                                   "value": "LISTENING"}),
            Step("derive", "a1", {"from": "lis", "field": "local",
                                  "using": "regex_group",
                                  "pattern": r"^(.*):(\d+)$", "group": 1,
                                  "into_field": "local_ip"},
                 "greedy .* then digits, so [::]:135 splits and split_index would not"),
            Step("derive", "a2", {"from": "a1", "field": "local",
                                  "using": "regex_group",
                                  "pattern": r"^(.*):(\d+)$", "group": 2,
                                  "into_field": "port_text"}),
            Step("derive", "a3", {"from": "a2", "field": "port_text",
                                  "using": "to_int", "into_field": "local_port"}),
            Step("derive", "a4", {"from": "a3", "field": "state", "using": "lookup",
                                  "table": {"LISTENING": "LISTEN"},
                                  "into_field": "state"},
                 "renamed so both platform versions answer in one vocabulary"),
            Step("lines", "trows", {"from": "tasklist_out"}),
            Step("fields", "tasks", {"from": "trows", "sep": ",", "names": [
                "image", "tpid", "session", "snum", "mem"]}),
            Step("derive", "t1", {"from": "tasks", "field": "image",
                                  "using": "strip", "chars": '"',
                                  "into_field": "process"}),
            Step("derive", "t2", {"from": "t1", "field": "tpid", "using": "strip",
                                  "chars": '"', "into_field": "task_pid"}),
            Step("join", "owned", {"left": "a4", "right": "t2", "left_on": "pid",
                                   "right_on": "task_pid", "bring": ["process"]}),
            Step("select", "picked", {"from": "owned", "fields": [
                "local_ip", "local_port", "state", "pid", "process"]}),
            Step("sort", "answer", {"from": "picked", "by": "local_port"}),
        ))


def test_the_windows_route_is_expressible_with_the_existing_primitives():
    """The test that decides whether Krish's acceptance test can succeed at all.

    He runs Windows. `/proc` is not there, so the skill has to be learnable from
    `netstat -ano` and `tasklist` - and if the primitives could not express that
    join, his test would fail for a reason that is mine rather than a failure of
    learning. No new primitive was needed."""
    with sandbox_module.Sandbox() as box:
        result = recipe_module.run(_windows_recipe(), box, {
            "netstat_out": _NETSTAT_ANO, "tasklist_out": _TASKLIST_CSV})

    assert result.ok, result.error
    answer = result.answer
    assert len(answer) == 4
    assert sorted(answer[0]) == sorted(
        ["local_ip", "local_port", "state", "pid", "process"]), \
        "the Windows version must answer in the same fields as the posix one"
    assert any(row["local_ip"] == "[::]" for row in answer), "IPv6 handled"
    assert all(row["state"] == "LISTEN" for row in answer), "ESTABLISHED excluded"
    assert {row["process"] for row in answer} == {
        "System", "svchost.exe", "jarvis-gateway.exe"}


def test_the_windows_route_only_needs_allow_listed_commands():
    for program in ("netstat", "tasklist"):
        assert program in sandbox_module.COMMANDS


def test_a_posix_path_on_windows_is_absent_rather_than_forbidden():
    """The defect Windows CI found, and the reason it mattered.

    `os.path.abspath("/proc/net/tcp")` on Windows is `D:\\proc\\net\\tcp`,
    which matched no declared pattern - so a recipe written for Linux was refused
    as a **permission** problem, and the diagnosis sent the learner off to
    propose an allow-list change for a file that does not exist."""
    absent = sandbox_module._platform_surface_for("/proc/net/tcp", platform="nt")
    assert absent is not None
    assert "netstat" in absent["instead"]
    assert sandbox_module._platform_surface_for("/proc/net/tcp",
                                                platform="posix") is None


def test_that_refusal_is_diagnosed_as_an_environment_difference():
    """Not `permission_issue`, and the signature order in `practice._SIGNATURES`
    is what guarantees it - the message contains both phrases."""
    message = ("/proc/net/tcp is a posix surface and this machine is nt. It is "
               "not forbidden - it is not there. Do not propose a boundary for "
               "it: on Windows the same information comes from commands.")
    diagnosis = practice.diagnose(
        recipe_module.Result(error=message, failed_step=0, trace=[]),
        Case("runs", "no_error"))
    assert diagnosis.failure_class == practice.ENVIRONMENT_DIFFERENCE
    assert "Do not propose a boundary" in diagnosis.suggestion


def test_the_sandbox_reports_which_surfaces_this_platform_lacks():
    """So a learning plan says it up front rather than discovering it in a
    failed attempt."""
    described = sandbox_module.describe()
    assert "platform" in described
    assert "platform_surfaces_absent_here" in described
