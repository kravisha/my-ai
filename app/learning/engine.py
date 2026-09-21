"""The lifecycle, and the plain language it explains itself in
(Document 1 §3, §12, §20-§23; Document 2 §2-§8, §11).

## `explain_how_i_learn` is generated, not written

Document 2 §2: *"The explanation must describe the real implemented behavior, not
merely repeat this specification."*

A hand-written paragraph would describe the specification, which is the same
sentence whether the code does it or not. So the explanation is **assembled from
the implementation**: the states come from `mastery.STATES`, the sources from
`research.SOURCES`, the primitives from `recipe.OPS`, the failure classes from
`practice.CLASSES`, the surface from `sandbox.describe()`. It cannot claim a step
that is not there, and it changes when the code does. Same discipline as
`gateway/devchannel.prompt_paragraph`, and for the same stated reason.

## The commitment is a condition, never an invented time

Document 2 §5: *"Jarvis must not invent a time estimate merely to sound
confident."* So `commit()` records a **completion condition** — the specific
states and cases that must hold — and the uncertainties that could prevent it. A
duration is accepted only if a caller supplies one, and nothing here generates
one.

## Registration proposes; Krish accepts

`accept()` is the only function whose effect is a person's decision, and it is
the only way an episode reaches `MASTERED`. Everything else computes state from
evidence. That resolves the conflict named in the package docstring: a skill that
promoted itself on its own test results would be
`app/initiative.HARM_WIDENS_ITS_OWN_AUTHORITY`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.learning import (mastery, memory, practice, recipe as recipe_module,
                          research, sandbox as sandbox_module, store)
from app.learning.objective import Objective, coverage, inventory

ORIGIN_USER = "user_request"
ORIGIN_GAP = "capability_gap"
ORIGIN_BOUNDARY = "boundary"
ORIGIN_SELF = "self_analysis"
ORIGINS = (ORIGIN_USER, ORIGIN_GAP, ORIGIN_BOUNDARY, ORIGIN_SELF)


def explain_how_i_learn() -> dict:
    """Document 2 §2, assembled from the code that implements it."""
    return {
        "summary": (
            "I learn by turning a thing I cannot do into a recipe - a list of "
            "steps over a fixed set of primitives - then running it against "
            "checkable properties until it works, on cases I held back as well "
            "as the ones I built against, and finally on the real machine. A "
            "learned skill runs with no model call at all."),
        "steps": [
            {"step": 1, "what": "receive or detect a capability gap",
             "how": ("app/capability_gaps.py records what was asked for and "
                     "failed; app/boundaries.py records limits I judged were "
                     "costing something; app/self_diagnosis.py flags escalations "
                     "that looked avoidable")},
            {"step": 2, "what": "define the objective specifically",
             "how": ("app/learning/objective.py refuses one that is not "
                     "checkable. It enforces seven requirements, so 'learn "
                     "networking' is rejected with all of the reasons rather "
                     "than accepted and stalled later")},
            {"step": 3, "what": "break it into competencies",
             "how": "each one named with why it is needed and whether I have it"},
            {"step": 4, "what": "check what I already have",
             "how": (f"objective.inventory() reads the registries that own the "
                     f"answer: the Gateway's skills, the deterministic-capability "
                     f"registry, the demonstration registry, the recipe "
                     f"vocabulary and skills I have already learned")},
            {"step": 5, "what": "ask what is missing, and from where",
             "how": (f"{len(research.available_sources())} sources are reachable "
                     f"here and {len(research.unavailable_sources())} of the ten "
                     f"the specification lists are not, because nothing in this "
                     f"system can fetch a document. Running it on this machine "
                     f"outranks every document anyway")},
            {"step": 6, "what": "write a learning plan and commit to a condition",
             "how": ("stored, inspectable, and the commitment is a condition "
                     "rather than a made-up duration")},
            {"step": 7, "what": "practise in a sandbox",
             "how": (f"{len(sandbox_module.COMMANDS)} read-only programs and "
                     f"{len(sandbox_module.READ_PATTERNS)} readable path patterns, "
                     f"no shell, no network, a temporary directory that is deleted. "
                     f"I cannot widen either list")},
            {"step": 8, "what": "test against checkable properties",
             "how": ("a property rather than a fixed expected value, because live "
                     "machine state has no fixed right answer and a value test "
                     "would only pass where it was written")},
            {"step": 9, "what": "diagnose failures without spending anything",
             "how": (f"{len(practice.CLASSES)} failure classes, identified from "
                     f"the recipe's own step trace. The rule that earns its place: "
                     f"a step that took rows in and produced none is the failure, "
                     f"even when the recipe reported success")},
            {"step": 10, "what": "revise and retry",
             "how": ("each recipe version is kept, so reverting is selecting an "
                     "earlier one rather than a mechanism")},
            {"step": 11, "what": "test on cases I held back",
             "how": ("its own state transition, not one more test file. Passing "
                     "only what I built against shows fitting, not learning")},
            {"step": 12, "what": "trial it on the real machine",
             "how": "read-only, bounded, logged, and reversible by construction"},
            {"step": 13, "what": "ask you, when tests cannot tell",
             "how": ("the last gate is yours. Nothing here can promote a skill to "
                     "operational on its own evidence")},
            {"step": 14, "what": "register it as an ordinary skill",
             "how": "on your acceptance, with its version history and provenance"},
            {"step": 15, "what": "keep what I learned about learning",
             "how": ("app/learning/memory.py counts failure patterns and which "
                     "sources paid off across episodes, and refuses to generalise "
                     "from one")},
        ],
        "states": [{"state": name, "means": mastery.MEANING[name]}
                   for name in mastery.STATES],
        "how_i_cannot_cheat": [
            "The state is computed from recorded evidence. There is no function "
            "that sets it, so I cannot claim a skill is learned.",
            "Held-out cases are a separate gate from the ones I developed against.",
            "Mastery needs your acceptance; evidence alone stops at "
            "awaiting_user_feedback.",
            "A learned skill is data, not code I wrote. The primitives and the "
            "sandbox's allow-lists are fixed and I cannot extend them.",
            "Every finding records where it came from, and one that no test has "
            "confirmed is reported as debt rather than as knowledge.",
        ],
        "vocabulary": recipe_module.describe_vocabulary(),
        "sandbox": sandbox_module.describe(),
        "sources": {"available": research.available_sources(),
                    "unavailable": research.unavailable_sources()},
    }


# Candidates that do not come from a log, because on a fresh machine the logs are
# empty and an engine with nothing to propose fails Document 2 §3 on its first
# day. Each one is **derived from a fact in this repository**, named here so the
# claim is checkable, and marked `declared` so it is never mistaken for observed
# demand.
#
# They are deliberately few. A long list of things somebody thought would be nice
# is the backlog-by-enthusiasm that `app/boundaries.py` was built to replace.
SEED_CANDIDATES = (
    {
        "what": "list listening TCP ports with the process that owns each one",
        "origin": ORIGIN_SELF,
        "why": ("I can report what is running (gateway/machine.py) but not what is "
                "listening on a port or which process owns it. Krish operates this "
                "machine remotely and cannot look at it, so 'what is listening and "
                "who owns it' is a question he has to ask a model to guess at "
                "today - and it is answerable deterministically from the kernel's "
                "own tables."),
        "evidence": "gateway/machine.py reports processes and disks, not sockets",
        "deterministic": True,
        "note": ("The route differs by platform and the skill needs a version "
                 "per platform, not a ported one. On posix it is the kernel's "
                 "own tables (/proc/net/tcp joined to /proc/*/fd). On Windows "
                 "those do not exist and the route is `netstat -ano` joined to "
                 "`tasklist`; the sandbox says so if you reach for /proc there, "
                 "and that refusal is an environment difference rather than "
                 "something to propose a boundary about."),
    },
    {
        "what": "summarise my own model-call log without calling a model",
        "origin": ORIGIN_SELF,
        "why": ("app/self_diagnosis.py writes a nightly report, but a question "
                "asked mid-conversation - 'how many calls did that cost' - "
                "currently goes to the model that is being asked about. The log is "
                "JSONL on this disk and the answer is arithmetic."),
        "evidence": "logs/model_calls.jsonl exists; nothing reads it in a turn",
        "deterministic": True,
    },
    {
        "what": "report which network interfaces exist and their addresses",
        "origin": ORIGIN_SELF,
        "why": ("gateway/remote.py diagnoses other machines but cannot say what "
                "this one's own interfaces are, which is the first thing anybody "
                "asks when a tailnet peer is unreachable."),
        "evidence": "gateway/remote.py has no local-interface probe",
        "deterministic": True,
    },
)


def candidates(limit: int = 5) -> list[dict]:
    """What is worth learning next, and why (Document 2 §3).

    Ranked from evidence this system already collects rather than from a
    judgement made fresh each time: how often something was asked for
    (`capability_gaps`), how often a limit was hit (`boundaries`), and whether a
    deterministic replacement is plausible - which is the whole reason Krish
    wants skills learned rather than escalated."""
    found: list[dict] = []

    try:
        from app import capability_gaps

        for gap in capability_gaps.ranked(capability_gaps.entries()):
            found.append({
                "what": gap["what_was_needed"],
                "origin": ORIGIN_GAP,
                "asked_for": gap["count"],
                "hit": 0,
                "why": (f"asked for {gap['count']} time(s) and refused each time "
                        f"({gap['gap_type']})"),
                "evidence": "logs/capability_gaps.jsonl",
            })
    except Exception:  # noqa: BLE001 - a candidate list must not fail on a log
        pass

    try:
        from app import boundaries

        for item in boundaries.register():
            found.append({
                "what": item["constraint"],
                "origin": ORIGIN_BOUNDARY,
                "asked_for": item["related_requests"],
                "hit": item["times_hit"],
                "why": (f"I hit this {item['times_hit']} time(s): "
                        f"{item['what_it_prevents']}"),
                "evidence": "logs/boundaries.jsonl",
            })
    except Exception:  # noqa: BLE001
        pass

    for seed in SEED_CANDIDATES:
        found.append({**seed, "asked_for": 0, "hit": 0, "declared": True,
                      "evidence": seed["evidence"]})

    already = {episode["slug"] for episode in store.list_episodes()}
    for item in found:
        item["already_an_episode"] = _slugify(item["what"]) in already
        # Observed demand outranks a declared candidate, always. A seed exists
        # so the engine has something to offer on a fresh machine, not so it can
        # compete with something Krish actually asked for.
        item["score"] = item["asked_for"] * 2 + item["hit"] + (
            0 if item.get("declared") else 1)

    return sorted([item for item in found if not item["already_an_episode"]],
                  key=lambda item: -item["score"])[:limit]


def _slugify(text: str) -> str:
    return "-".join("".join(character if character.isalnum() else " "
                            for character in (text or "").lower()).split())[:60]


@dataclass
class LearningEngine:
    """The lifecycle. Every method records; none of them sets a state."""

    def begin(self, objective: Objective, *, origin: str = ORIGIN_USER) -> dict:
        if origin not in ORIGINS:
            raise ValueError(f"origin={origin!r} is not one of {ORIGINS}")
        episode_id = store.create_episode(objective.slug, objective.to_dict(), origin)
        return self.status(objective.slug)

    # --- §12: the plan, and §5's commitment ---------------------------------

    def plan(self, slug: str, *, commitment_condition: str | None = None,
             uncertainties: tuple[str, ...] = (),
             ready_when: str | None = None) -> dict:
        """Write the learning plan and the commitment, and store both."""
        episode = self._require(slug)
        objective = Objective.from_dict(episode["objective"])

        plan = {
            "objective": objective.to_dict(),
            "competencies": [item.name for item in objective.competencies],
            "already_have": coverage(objective),
            "questions": research.questions_for(objective),
            "sources_in_preference_order": [
                {"source": name, "tier": research.SOURCES[name]["tier"],
                 "what": research.SOURCES[name]["what"]}
                for name in sorted(research.available_sources(),
                                   key=lambda name: research.SOURCES[name]["tier"])],
            "sources_unavailable": research.unavailable_sources(),
            "sandbox": sandbox_module.describe(),
            "development_cases": [{"name": case.name, "expect": case.expect}
                                  for case in objective.development_cases],
            "held_out_cases": [{"name": case.name, "expect": case.expect}
                               for case in objective.held_out_cases],
            "expected_failures": list(objective.known_failure_modes),
            "failure_classes_i_can_diagnose": list(practice.CLASSES),
            "resolution_ladder": list(practice.RESOLUTIONS),
            "partial_success_means": mastery.MEANING[mastery.PARTIAL],
            "mastery_means": (
                "every development case passes, every held-out case passes, a "
                "real-world trial succeeded, and you accepted it"),
            "rollback": ("every recipe version is kept in the learning store; "
                         "reverting is selecting an earlier version"),
            "user_feedback_required": True,
            "advice_from_past_episodes": memory.advice_for(objective),
        }

        condition = commitment_condition or (
            f"I will come back when every one of the "
            f"{len(objective.development_cases)} development case(s) and "
            f"{len(objective.held_out_cases)} held-out case(s) passes and a "
            f"real-world trial has succeeded - not before, and I will tell you if "
            f"I get stuck instead of going quiet.")
        commitment = {
            "will_attempt": objective.cannot_do,
            "success_looks_like": objective.success_looks_like,
            "demonstration": (
                "I will run the skill on this machine in front of you and show "
                "the output, the test results, and the step trace proving no "
                "model was called."),
            "ready_when": ready_when or condition,
            "uncertainties": list(uncertainties) or [
                "the machine may not expose what the skill needs, which is a "
                "finding rather than a failure",
                "a needed primitive may not exist, in which case I will propose "
                "the boundary rather than work around it",
            ],
            "time_estimate": None,
            "why_no_time_estimate": (
                "I have no measured basis for one, and inventing a duration to "
                "sound confident is worse than a condition you can check."),
        }
        store.set_plan(episode["id"], plan, commitment)
        return {"plan": plan, "commitment": commitment, **self.status(slug)}

    # --- §9: findings -------------------------------------------------------

    def record_finding(self, slug: str, finding: research.Finding) -> int:
        return research.record(self._require(slug)["id"], finding)

    # --- the recipe under construction --------------------------------------

    def propose_recipe(self, slug: str, recipe: recipe_module.Recipe,
                       why: str = "") -> int:
        return store.save_recipe(self._require(slug)["id"], recipe.to_dict(), why)

    def current_recipe(self, slug: str) -> recipe_module.Recipe | None:
        stored = store.latest_recipe(self._require(slug)["id"])
        return recipe_module.Recipe.from_dict(stored["spec"]) if stored else None

    def revert_recipe(self, slug: str, version: int) -> recipe_module.Recipe:
        """§24: return to a known-good version. A SELECT, not a mechanism."""
        episode = self._require(slug)
        for stored in store.recipe_versions(episode["id"]):
            if int(stored["version"]) == int(version):
                reverted = recipe_module.Recipe.from_dict(stored["spec"])
                # Reverting stores the old steps as a NEW version rather than
                # rewinding, so the history stays append-only and "we went back"
                # is itself an event. The object returned carries the new version
                # number, because what a caller needs to know is what is in play
                # now - returning the old number described a state that no longer
                # existed, which a test caught.
                new_version = store.save_recipe(
                    episode["id"], {**reverted.to_dict(), "version": None},
                    why=f"reverted to v{version}")
                return recipe_module.Recipe.from_dict(
                    {**reverted.to_dict(), "version": new_version})
        raise ValueError(f"{slug} has no recipe version {version}")

    # --- §14-§16: practice, test, held-out ----------------------------------

    def practise(self, slug: str, case_name: str | None = None) -> list[dict]:
        episode, objective, recipe = self._loaded(slug)
        cases = [case for case in objective.development_cases
                 if case_name is None or case.name == case_name]
        return [_outcome(o) for o in practice.run_cases(
            episode["id"], recipe, cases, kind=store.KIND_DEVELOPMENT)]

    def examine(self, slug: str) -> list[dict]:
        """Run the held-out cases. Its own gate; see `mastery.py`."""
        episode, objective, recipe = self._loaded(slug)
        outcomes = practice.run_cases(episode["id"], recipe,
                                      objective.held_out_cases,
                                      kind=store.KIND_HELDOUT)
        if outcomes and all(outcome.passed for outcome in outcomes):
            # §11: a finding becomes knowledge when something that rested on it
            # was observed to work, never because it was written down.
            research.confirm_all(episode["id"])
        return [_outcome(o) for o in outcomes]

    def trial(self, slug: str) -> list[dict]:
        """§20's controlled real-world trial.

        The same recipe on the same machine, recorded as a trial rather than a
        test. It is read-only and bounded by construction - every primitive it
        can use is - so "minimise irreversible effects" is a property of the
        sandbox rather than a promise made here."""
        episode, objective, recipe = self._loaded(slug)
        return [_outcome(o) for o in practice.run_cases(
            episode["id"], recipe, objective.cases, kind=store.KIND_TRIAL)]

    def run_operationally(self, slug: str) -> dict:
        """Run a mastered skill as an ordinary skill, and record the result.

        Recorded, because a skill that stops working must be able to fall to
        `DEGRADED` - and it can only do that if its operational runs are
        evidence like any other."""
        episode, objective, recipe = self._loaded(slug)
        with sandbox_module.Sandbox(allow_commands=recipe.needs_commands) as box:
            result = recipe_module.run(recipe, box)
        passed = result.ok
        store.record_attempt(episode["id"], kind=store.KIND_OPERATIONAL,
                             passed=passed, case_name="operational",
                             recipe_version=recipe.version,
                             observed=("ran" if passed else str(result.error)),
                             trace=result.trace,
                             cost={"model_calls": 0, "tokens": 0})
        return {"ok": passed, "answer": result.answer, "error": result.error,
                "trace": result.trace}

    # --- §6 of Document 2: the demonstration --------------------------------

    def demonstrate(self, slug: str) -> dict:
        """Evidence, not a claim.

        Document 2 §6 lists what a demonstration may contain and this returns as
        many of them as the episode has: the skill actually run, its output, the
        test results, the cases that used to fail and now pass, the step trace,
        and the zero-model-call accounting. A refusal when there is nothing worth
        showing, rather than an empty flourish."""
        episode, objective, recipe = self._loaded(slug)
        state = self._state(slug)
        if not state.may_demonstrate:
            return {"ready": False, "state": state.name,
                    "why_not": (f"there is nothing to show yet. {state.meaning}. "
                                f"Missing: {'; '.join(state.missing)}")}

        live = self.run_operationally(slug)
        attempts = store.attempts(episode["id"])
        previously_failed = sorted({
            attempt["case_name"] for attempt in attempts
            if attempt["passed"] is False and attempt["case_name"]})
        now_passing = sorted({
            attempt["case_name"] for attempt in attempts
            if attempt["passed"] and attempt["case_name"]})

        return {
            "ready": True,
            "state": state.name,
            "skill": recipe.name,
            "summary": recipe.summary,
            "how_it_works": recipe.as_plain_language(),
            "ran_just_now": {"ok": live["ok"], "output": live["answer"],
                             "error": live["error"]},
            "step_trace": live["trace"],
            "test_results": {
                "development": store.latest_case_results(
                    episode["id"], store.KIND_DEVELOPMENT),
                "held_out": store.latest_case_results(
                    episode["id"], store.KIND_HELDOUT),
                "real_world_trial": store.latest_case_results(
                    episode["id"], store.KIND_TRIAL),
            },
            "cases_that_used_to_fail_and_now_pass": sorted(
                set(previously_failed) & set(now_passing)),
            "no_model_was_called": {
                "model_calls": 0,
                "how_that_is_known": (
                    "a recipe is executed by app/learning/recipe.py, which has no "
                    "provider, no network primitive and no path to "
                    "app/model_gateway. Every attempt records model_calls=0 and "
                    "app/model_calls.py would have logged one if it had happened."),
            },
            "provenance": research.provenance(episode["id"]),
            "unconfirmed_findings": research.confirmation_debt(episode["id"]),
            "recipe_versions": [version["version"]
                                for version in store.recipe_versions(episode["id"])],
            "what_i_still_need": list(state.missing),
        }

    # --- §7 of Document 2: feedback ------------------------------------------

    def feedback(self, slug: str, *, verdict: str, note: str | None = None) -> dict:
        """Record Krish's judgement. `accept` is a separate, explicit act."""
        episode = self._require(slug)
        feedback_id = store.record_feedback(episode["id"], verdict=verdict, note=note)
        return {"recorded": feedback_id, "verdict": verdict, "note": note,
                **self.status(slug)}

    def accept(self, slug: str) -> dict:
        """The one transition evidence cannot make. See the module docstring."""
        episode = self._require(slug)
        state = self._state(slug)
        if episode.get("accepted_by_user"):
            # Already registered. Reporting this as a refusal was the first
            # thing an end-to-end run got wrong: "registered: False" on a skill
            # that is registered reads as a failure, and the operator's next move
            # is to try again.
            return {"registered": True, "already_registered": True,
                    **self.status(slug)}
        if state.name not in (mastery.AWAITING_FEEDBACK, mastery.DEGRADED):
            return {"registered": False, "state": state.name,
                    "why_not": (f"acceptance is the last gate, not a shortcut past "
                                f"the others. Still missing: "
                                f"{'; '.join(state.missing)}")}
        store.accept_episode(episode["id"])
        # Once, here, and nowhere else. A second caller incrementing the same
        # lessons would corrupt the only numbers meta-learning has; the
        # already-accepted branch above is what makes a repeat call harmless.
        memory.learn_from_episode(slug)
        return {"registered": True, **self.status(slug)}

    # --- §11: what is going on -----------------------------------------------

    def status(self, slug: str) -> dict:
        episode = store.get_episode(slug)
        if not episode:
            return {"exists": False, "slug": slug}
        objective = Objective.from_dict(episode["objective"])
        evidence = mastery.Evidence(
            objective_is_specific=not objective.unmet_requirements(),
            plan_exists=episode.get("plan") is not None,
            accepted_by_user=episode.get("accepted_by_user", False),
            **practice.evidence_for(episode["id"], objective))
        described = mastery.describe(evidence)
        stored_recipe = store.latest_recipe(episode["id"])
        return {
            "exists": True,
            "slug": slug,
            "origin": episode["origin"],
            "objective": objective.to_dict(),
            "has_plan": episode.get("plan") is not None,
            "commitment": episode.get("commitment"),
            "recipe_version": stored_recipe["version"] if stored_recipe else None,
            "feedback": store.feedback(episode["id"]),
            "unconfirmed_findings": len(research.confirmation_debt(episode["id"])),
            **described,
        }

    def narrate(self, slug: str) -> list[str]:
        """Document 2 §11: the state of the engine, in sentences."""
        status = self.status(slug)
        if not status.get("exists"):
            return [f"I have no learning episode called {slug!r}."]
        objective = Objective.from_dict(status["objective"])
        lines = [f"Learning: {objective.cannot_do}",
                 f"Why: {objective.gap_it_closes}",
                 f"State: {status['state']} - {status['means']}"]
        if status["missing"]:
            lines.append("What I still need: " + "; ".join(status["missing"]))
        evidence = status["evidence"]
        lines.append(
            f"Evidence so far: {evidence['attempts']} attempt(s), development "
            f"{evidence['development']}, held-out {evidence['held_out']}, "
            f"real-world trials {evidence['real_world_trials']}.")
        recipe = self.current_recipe(slug)
        if recipe is not None:
            lines.append(f"Current approach (v{recipe.version}): {recipe.summary}")
        # Only failures against the recipe *currently* in play. A failure that a
        # later version fixed is history, and reporting it as "most recent
        # failure" on a working skill - which an end-to-end run did - describes
        # the skill as broken when it is not.
        current_version = recipe.version if recipe is not None else None
        failures = [attempt for attempt in
                    store.attempts(store.get_episode(slug)["id"])
                    if attempt["passed"] is False
                    and attempt.get("recipe_version") == current_version]
        if failures:
            newest = failures[-1]
            diagnosis = newest.get("diagnosis") or {}
            lines.append(
                f"Most recent failure: {newest['case_name']} - "
                f"{newest['observed']}. I classified it as "
                f"{diagnosis.get('failure_class', 'unclassified')} and "
                f"{diagnosis.get('suggestion') or 'am revising the recipe'}.")
        else:
            fixed = [attempt for attempt in
                     store.attempts(store.get_episode(slug)["id"])
                     if attempt["passed"] is False]
            if fixed:
                lines.append(
                    f"{len(fixed)} earlier attempt(s) failed and were fixed; the "
                    f"current version has not failed a case.")
        if status["unconfirmed_findings"]:
            lines.append(
                f"{status['unconfirmed_findings']} thing(s) I am relying on have "
                f"not yet been confirmed by a test.")
        if status["may_demonstrate"]:
            lines.append("There is something worth showing you now.")
        return lines

    # --- internals ------------------------------------------------------------

    def _require(self, slug: str) -> dict:
        episode = store.get_episode(slug)
        if not episode:
            raise ValueError(f"no learning episode {slug!r}. Begin one first.")
        return episode

    def _state(self, slug: str) -> mastery.State:
        status = self.status(slug)
        return mastery.State(status["state"], status["means"],
                             tuple(status["missing"]), status["next_state"])

    def _loaded(self, slug: str):
        episode = self._require(slug)
        objective = Objective.from_dict(episode["objective"])
        recipe = self.current_recipe(slug)
        if recipe is None:
            raise ValueError(
                f"{slug} has no recipe yet. Propose one before practising - "
                f"there is nothing to attempt.")
        return episode, objective, recipe


def _outcome(outcome) -> dict:
    return {"case": outcome.case_name, "passed": outcome.passed,
            "observed": outcome.observed, "expected": outcome.expected,
            "diagnosis": outcome.diagnosis.to_dict() if outcome.diagnosis else None}


_ENGINE: LearningEngine | None = None


def default_engine() -> LearningEngine:
    """The process-wide engine, following `app/model_gateway.default_provider`.

    A function rather than a module-level instance for the reason that bit
    immediately: a variable named `engine` inside a module named `engine`, re-
    exported from the package, shadows the module for anybody who writes
    `from app.learning import engine`. Named `default_engine` so the collision
    cannot happen at all."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = LearningEngine()
    return _ENGINE
