"""Turning "I want to learn networking" into something learnable
(Document 1 §5-§8; Document 2 §3).

> *"Jarvis must avoid vague learning objectives such as 'Learn networking.'"*

A rule telling it to be specific would be honoured on the turns it happened to
remember. So specificity is **structural**: an `Objective` cannot be constructed
without the fields that make it testable, and `ObjectiveRefused` names which one
is missing. "Learn networking" fails six of the seven requirements below and the
refusal lists all six, which is more useful than failing on the first.

## The seven requirements, and why each is one

Each of these is a thing that, absent, makes the rest of the loop unable to run
rather than merely untidy:

| Requirement | Without it |
|---|---|
| `names_inputs` | `practice.py` has nothing to run the recipe on |
| `names_outputs` | no test can compare anything |
| `names_environment` | a recipe passes here and fails on his machine |
| `states_success` | `mastery.py` cannot say whether it is done |
| `has_verifiable_cases` | there is no development set, so no state past `LEARNING` |
| `decides_llm_need` | the whole point (a deterministic skill) is left open |
| `names_the_gap` | there is no way to tell whether the skill was needed |

`decides_llm_need` deserves a note. It is satisfied by answering *either* way,
including "yes, this genuinely needs a model". Requiring the answer to be "no"
would produce objectives that claim determinism to get past the validator, which
is the metric-gaming failure `backend/engineering.py` §119 already recorded in
this codebase.

## Decomposition, and why it reuses the curriculum's words

§7 asks for the objective to be broken into competencies. `backend/curriculum.py`
already has a competency vocabulary in this system, so `Competency` here carries
the same shape rather than a second one. A skill decomposed into words nothing
else uses would be a skill nothing else can report on.

## The inventory is read, never assumed

§8 asks what Jarvis already knows *before* acquiring anything. Four registries in
this repository already answer that and each is kept honest by its own test, so
`inventory()` reads them rather than restating them: the Gateway's skills, the
deterministic-capability registry, the demonstration registry's present/absent
halves, and the recipe vocabulary itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class ObjectiveRefused(ValueError):
    """The objective is not specific enough to learn against.

    Refused rather than accepted-with-a-warning: an unlearnable objective
    accepted here becomes an episode that can never leave `LEARNING`, and the
    reason will be three modules away by the time anybody looks."""


# The minimum words in a free-text field before it is treated as having said
# something. Eight, because that is roughly where "inspect TCP connections"
# (three) becomes "list listening TCP sockets with the process that owns each"
# (ten) - the difference between a topic and a task.
MIN_WORDS = 8

# A phrase that is a subject area rather than a capability. Matched to give a
# better refusal than "too short", because "learn networking" is the exact
# example Document 1 and Document 2 both use.
_BARE_TOPIC = re.compile(
    r"^\s*(learn|understand|know|study|master|get better at)?\s*"
    r"[\w\- ]{0,24}$", re.IGNORECASE)


@dataclass(frozen=True)
class Case:
    """One thing that must be true of the output for the skill to work.

    Deliberately a *property* rather than an expected value. A skill that reads
    live machine state has no fixed correct answer - the listening ports differ
    between runs and machines - so `expect` names a checkable property and
    `practice.py` evaluates it. An expected-value test here would be a test that
    only passes on the machine it was written on, which is the opposite of
    evidence."""

    name: str
    expect: str
    detail: str = ""
    held_out: bool = False


@dataclass(frozen=True)
class Competency:
    """One thing that must be known or doable before the skill exists (§7)."""

    name: str
    why: str
    already_have: bool = False
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class Objective:
    """§6's list, with the seven structural requirements enforced.

    Frozen, because an objective that changed mid-episode would invalidate every
    attempt recorded against it. Revising one means a new version, which is what
    `store.create_episode` does when a slug is re-used."""

    slug: str
    cannot_do: str
    success_looks_like: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    environment: str
    gap_it_closes: str
    cases: tuple[Case, ...]
    deterministic_possible: bool | None = None
    llm_required: bool | None = None
    dependencies: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    known_failure_modes: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    required_reliability: str = ""
    competencies: tuple[Competency, ...] = ()

    def __post_init__(self) -> None:
        missing = self.unmet_requirements()
        if missing:
            raise ObjectiveRefused(
                f"this is not yet a learnable objective. Missing: "
                + "; ".join(missing)
                + ". A vague objective is not a smaller version of a specific one - "
                  "it produces an episode that can never leave 'currently_learning', "
                  "because nothing can say whether it worked.")

    def unmet_requirements(self) -> list[str]:
        """Every requirement not satisfied, not merely the first.

        All of them, because the caller is usually a model filling in a form and
        one-at-a-time refusals turn that into six round trips."""
        missing = []
        if _words(self.cannot_do) < 3 or _BARE_TOPIC.match(self.cannot_do or ""):
            missing.append(
                f"names_the_gap: {self.cannot_do!r} is a subject area rather than "
                f"something you cannot do. Say what specific thing fails, in whose "
                f"terms, with what input")
        if not self.inputs:
            missing.append("names_inputs: what does the skill receive")
        if not self.outputs:
            missing.append("names_outputs: what does it produce, field by field")
        if _words(self.environment) < 2:
            missing.append("names_environment: which machine, OS, and what must "
                           "be installed")
        if _words(self.success_looks_like) < MIN_WORDS:
            missing.append(f"states_success: describe the successful behaviour in "
                           f"at least {MIN_WORDS} words, observably")
        if not self.cases:
            missing.append("has_verifiable_cases: at least one checkable property "
                           "of the output")
        if self.deterministic_possible is None or self.llm_required is None:
            missing.append("decides_llm_need: answer both - can this be done "
                           "deterministically, and does it genuinely need a model "
                           "(answering yes to the second is a real answer)")
        if _words(self.gap_it_closes) < 4:
            missing.append("names_the_gap: why is this worth learning now rather "
                           "than later")
        return missing

    # --- what the engine and the narration read --------------------------------

    @property
    def development_cases(self) -> tuple[Case, ...]:
        return tuple(case for case in self.cases if not case.held_out)

    @property
    def held_out_cases(self) -> tuple[Case, ...]:
        return tuple(case for case in self.cases if case.held_out)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "cannot_do": self.cannot_do,
            "success_looks_like": self.success_looks_like,
            "inputs": list(self.inputs), "outputs": list(self.outputs),
            "environment": self.environment, "gap_it_closes": self.gap_it_closes,
            "deterministic_possible": self.deterministic_possible,
            "llm_required": self.llm_required,
            "dependencies": list(self.dependencies),
            "constraints": list(self.constraints),
            "known_failure_modes": list(self.known_failure_modes),
            "permissions": list(self.permissions), "risks": list(self.risks),
            "required_reliability": self.required_reliability,
            "cases": [{"name": c.name, "expect": c.expect, "detail": c.detail,
                       "held_out": c.held_out} for c in self.cases],
            "competencies": [{"name": c.name, "why": c.why,
                              "already_have": c.already_have,
                              "depends_on": list(c.depends_on)}
                             for c in self.competencies],
        }

    @staticmethod
    def from_dict(data: dict) -> "Objective":
        return Objective(
            slug=data["slug"], cannot_do=data["cannot_do"],
            success_looks_like=data["success_looks_like"],
            inputs=tuple(data.get("inputs") or ()),
            outputs=tuple(data.get("outputs") or ()),
            environment=data.get("environment", ""),
            gap_it_closes=data.get("gap_it_closes", ""),
            deterministic_possible=data.get("deterministic_possible"),
            llm_required=data.get("llm_required"),
            dependencies=tuple(data.get("dependencies") or ()),
            constraints=tuple(data.get("constraints") or ()),
            known_failure_modes=tuple(data.get("known_failure_modes") or ()),
            permissions=tuple(data.get("permissions") or ()),
            risks=tuple(data.get("risks") or ()),
            required_reliability=data.get("required_reliability", ""),
            cases=tuple(Case(name=c["name"], expect=c["expect"],
                             detail=c.get("detail", ""),
                             held_out=bool(c.get("held_out")))
                        for c in data.get("cases") or ()),
            competencies=tuple(Competency(
                name=c["name"], why=c.get("why", ""),
                already_have=bool(c.get("already_have")),
                depends_on=tuple(c.get("depends_on") or ()))
                for c in data.get("competencies") or ()))

    def as_plain_language(self) -> list[str]:
        """Document 2 §4: the objective, understandable to a person."""
        lines = [
            f"What I cannot do: {self.cannot_do}",
            f"What success looks like: {self.success_looks_like}",
            f"Why it is worth learning now: {self.gap_it_closes}",
            f"Input: {', '.join(self.inputs)}",
            f"Output: {', '.join(self.outputs)}",
            f"Environment: {self.environment}",
            ("Can be done without a model: "
             f"{'yes' if self.deterministic_possible else 'no'}; "
             f"needs a model: {'yes' if self.llm_required else 'no'}"),
        ]
        if self.competencies:
            lines.append("Competencies it breaks into:")
            for item in self.competencies:
                have = "already have" if item.already_have else "to learn"
                lines.append(f"  - {item.name} ({have}) - {item.why}")
        if self.development_cases:
            lines.append("How I will know it works:")
            for case in self.development_cases:
                lines.append(f"  - {case.name}: {case.expect}")
        if self.held_out_cases:
            lines.append("Held back, so passing shows learning rather than fitting:")
            for case in self.held_out_cases:
                lines.append(f"  - {case.name}: {case.expect}")
        if self.known_failure_modes:
            lines.append("Where I expect it to go wrong: "
                         + "; ".join(self.known_failure_modes))
        return lines


def _words(text: str | None) -> int:
    return len((text or "").split())


# --- §8: what do I already have ------------------------------------------------


def inventory() -> dict:
    """Everything this system can already do, read from the registries that own it.

    Read rather than restated, and each source is already asserted against the
    codebase by its own test - so this cannot claim a capability that is not
    there, which is the one way an inventory would be worse than none."""
    from app.learning import recipe, sandbox, store

    found: dict = {"sources": [], "reusable": []}

    try:
        from gateway import roles, skills as gateway_skills

        available = [s.name for s in gateway_skills.available_for(roles.ROLE_OPERATOR)]
        unbuilt = [(s.name, s.blocked_reason)
                   for s in gateway_skills.unbuilt_for(roles.ROLE_OPERATOR)]
        found["sources"].append("gateway/skills.py")
        found["gateway_skills_available"] = available
        found["gateway_skills_unbuilt"] = [name for name, _ in unbuilt]
        found["reusable"] += available
    except Exception as bad:  # noqa: BLE001 - an inventory reports, never fails
        found["gateway_skills_error"] = str(bad)

    try:
        from app import capability

        # A tuple of dataclasses, not of names - so the operation is pulled out
        # rather than the tuple sorted. The first version sorted it directly,
        # the TypeError was swallowed by the guard below, and the inventory
        # silently reported one fewer source than it had. A guard that hides a
        # bug is worth a test, which is why
        # test_the_inventory_reads_the_registries_rather_than_restating_them
        # asserts the source is present rather than that the call did not raise.
        deterministic = sorted(
            str(getattr(item, "operation", None) or getattr(item, "name", item))
            for item in capability.DETERMINISTIC_CAPABILITIES)
        found["sources"].append("app/capability.py")
        found["deterministic_capabilities"] = deterministic
        found["reusable"] += deterministic
    except Exception as bad:  # noqa: BLE001
        found["deterministic_error"] = str(bad)

    try:
        from demonstration import capabilities as demo

        found["sources"].append("demonstration/capabilities.py")
        found["demonstrable"] = list(demo.demonstrable_ids())
        found["declared_absent"] = list(demo.absent_ids())
    except Exception as bad:  # noqa: BLE001
        found["demonstration_error"] = str(bad)

    found["sources"] += ["app/learning/recipe.py", "app/learning/sandbox.py"]
    found["recipe_vocabulary"] = recipe.describe_vocabulary()
    found["sandbox_surface"] = sandbox.describe()

    try:
        learned = [episode["slug"] for episode in store.list_episodes()
                   if episode.get("accepted_by_user")]
        found["skills_already_learned"] = learned
        found["reusable"] += learned
    except Exception as bad:  # noqa: BLE001
        found["learned_error"] = str(bad)

    found["reusable"] = sorted(set(found["reusable"]))
    return found


def coverage(objective: Objective) -> dict:
    """How much of this objective is already covered (§8's question).

    Deliberately crude - a name match against the inventory - and honest about
    it. The value is in asking before building rather than in the precision of
    the answer, and a false miss costs a paragraph of research while a clever
    fuzzy match that wrongly claimed coverage would cost a skill that was never
    built."""
    have = set(inventory()["reusable"])
    covered, missing = [], []
    for item in objective.competencies:
        if item.already_have or item.name in have:
            covered.append(item.name)
        else:
            missing.append(item.name)
    total = len(objective.competencies) or 1
    return {
        "competencies": len(objective.competencies),
        "already_have": covered,
        "to_learn": missing,
        "share_covered": round(len(covered) / total, 2),
        "note": ("Matched by name against the registries in inventory(). A miss "
                 "here costs some research; a false hit would cost a skill that "
                 "was never built, so this errs toward reporting a gap."),
    }
