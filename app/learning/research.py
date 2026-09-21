"""Where knowledge comes from, how much it is trusted, and what is missing
(Document 1 §9-§11).

## The honest version of §10's hierarchy

§10 lists ten tiers, from *existing verified Jarvis code* down to *community
discussion*. Six of them require fetching a document, and **nothing in this
repository can fetch anything.** Network egress is stooq, FRED, tailnet peers and
the Kimi API; there is no web tool and no documentation corpus.

So `SOURCES` below records all ten tiers and marks six `available=False` with the
reason. That is deliberately more useful than implementing four and implying the
rest: a learning record that said "researched" when it meant "the model
remembered something" would be the exact failure §11 is about.

What is left is strong enough to learn with, and one of the four is the best tier
on the list:

| Tier | Source | Here |
|---|---|---|
| 1 | verified Jarvis code and tests | `available` - read the repository |
| 2 | local system documentation | `available` - `docs/`, the addenda |
| 3-8 | specifications, vendor docs, authoritative source | **unavailable** - needs the web |
| 9 | multiple independent sources agreeing | **unavailable** - needs the web |
| 10 | community discussion | **unavailable** - needs the web |
| — | **empirical probe of this machine** | `available`, and trusted above all of them |

The last row is not on §10's list and sits above it, which needs saying rather
than sneaking in. §11 gives the reason in its own words: *"Documentation tells
Jarvis what should happen. Testing tells Jarvis what actually happens."* A
`/proc/net/tcp` read on this machine is not a claim about `/proc/net/tcp`; it is
the thing itself. Where a probe and a document disagree, the probe wins, and the
disagreement is recorded as a finding of its own.

## Confirmation debt

Every finding starts unconfirmed. §11 means a finding only becomes knowledge
when a test that depended on it passed, so `confirmation_debt()` reports what a
skill is still resting on unverified, and the narration says so. A skill that
reached mastery with debt outstanding would have learned from assertions.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.learning import store

# --- the sources, all ten of §10's tiers plus the one it does not list ---------

PROBE = "empirical_probe"
JARVIS_CODE = "jarvis_code_and_tests"
LOCAL_DOCS = "local_documentation"
OFFICIAL_SPEC = "official_specification"
OFFICIAL_API = "official_api_documentation"
VENDOR_DOCS = "vendor_documentation"
AUTHORITATIVE_SOURCE = "authoritative_source_code"
MAINTAINER_DOCS = "maintainer_documentation"
REPUTABLE_REFERENCE = "reputable_technical_reference"
CORROBORATED = "multiple_independent_sources"
COMMUNITY = "community_discussion"
MODEL_KNOWLEDGE = "model_recollection"

# `tier` is §10's ordering, lower is stronger. `PROBE` is tier 0 because it is
# not a report about the world, it is the world - see the module docstring.
SOURCES = {
    PROBE: {"tier": 0, "available": True,
            "what": "ran it on this machine and observed the result",
            "verification": "none needed; this is the verification"},
    JARVIS_CODE: {"tier": 1, "available": True,
                  "what": "existing verified code and tests in this repository",
                  "verification": "confirm the code is reached at runtime, not merely present"},
    LOCAL_DOCS: {"tier": 2, "available": True,
                 "what": "docs/ and the addenda on this machine",
                 "verification": "confirm against a probe; a spec can describe an intention"},
    OFFICIAL_SPEC: {"tier": 3, "available": False,
                    "what": "an official specification",
                    "unavailable_because": "no web access exists in this repository"},
    OFFICIAL_API: {"tier": 4, "available": False, "what": "official API documentation",
                   "unavailable_because": "no web access exists in this repository"},
    VENDOR_DOCS: {"tier": 5, "available": False, "what": "platform or vendor documentation",
                  "unavailable_because": "no web access exists in this repository"},
    AUTHORITATIVE_SOURCE: {"tier": 6, "available": False,
                           "what": "the authoritative source code of the thing itself",
                           "unavailable_because": "no web access exists in this repository"},
    MAINTAINER_DOCS: {"tier": 7, "available": False, "what": "maintainer documentation",
                      "unavailable_because": "no web access exists in this repository"},
    REPUTABLE_REFERENCE: {"tier": 8, "available": False,
                          "what": "a highly reputable technical reference",
                          "unavailable_because": "no web access exists in this repository"},
    CORROBORATED: {"tier": 9, "available": False,
                   "what": "several independent sources agreeing",
                   "unavailable_because": "needs more than one fetchable source"},
    COMMUNITY: {"tier": 10, "available": False, "what": "community discussion",
                "unavailable_because": "no web access exists in this repository"},
    MODEL_KNOWLEDGE: {"tier": 9, "available": True,
                      "what": "what the reasoning model recalled, with no document behind it",
                      "verification": "MUST be confirmed by a probe before it is relied on"},
}

# Sources whose findings may not be relied on until a probe has confirmed them.
# §10: *"Information acquired from weaker sources should receive greater
# verification."* Here that is a rule rather than an adjective.
NEEDS_CONFIRMATION = tuple(
    name for name, meta in SOURCES.items()
    if meta["available"] and meta["tier"] >= 2)


def available_sources() -> list[str]:
    return [name for name, meta in SOURCES.items() if meta["available"]]


def unavailable_sources() -> dict:
    """What §10 asks for and this system cannot reach, with the reason.

    Reported rather than omitted, for the reason `demonstration/capabilities.py`
    gives about its own ABSENT half: a list of what is missing is never
    exercised by anything, so it rots into a lie unless something states it."""
    return {name: meta["unavailable_because"]
            for name, meta in SOURCES.items() if not meta["available"]}


@dataclass(frozen=True)
class Finding:
    """One answer, and where it came from."""

    question: str
    answer: str
    source_kind: str
    source_ref: str = ""

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCES:
            raise ValueError(
                f"source_kind={self.source_kind!r} is not one of {sorted(SOURCES)}. "
                f"An unlabelled source is a finding nobody can weigh.")
        if not SOURCES[self.source_kind]["available"]:
            raise ValueError(
                f"{self.source_kind!r} is not reachable from this system "
                f"({SOURCES[self.source_kind]['unavailable_because']}), so a "
                f"finding cannot honestly claim it.")

    @property
    def tier(self) -> int:
        return int(SOURCES[self.source_kind]["tier"])

    @property
    def needs_confirmation(self) -> bool:
        return self.source_kind in NEEDS_CONFIRMATION


def questions_for(objective) -> list[str]:
    """The specific questions §9 asks for, derived from the objective.

    Derived rather than free-form, because "what do I not know" answered in the
    abstract produces a paragraph and answered against the objective's own
    fields produces a list somebody can work through."""
    asked = [
        f"How is {objective.cannot_do} done at all on {objective.environment}?",
        f"What produces {', '.join(objective.outputs) or 'the output'}, and in "
        f"what format?",
    ]
    for item in objective.competencies:
        if not item.already_have:
            asked.append(f"How do I {item.name}?")
    for dependency in objective.dependencies:
        asked.append(f"Is {dependency} present on this machine, and what does it "
                     f"return here rather than in its documentation?")
    if objective.deterministic_possible:
        asked.append("Which of the recipe primitives compose to do this without "
                     "a model call?")
    for mode in objective.known_failure_modes:
        asked.append(f"What actually happens when {mode}?")
    return asked


def record(episode_id: int, finding: Finding) -> int:
    return store.record_knowledge(
        episode_id, question=finding.question, answer=finding.answer,
        source_kind=finding.source_kind, source_ref=finding.source_ref or None,
        trust_tier=finding.tier,
        confirmed_by_test=not finding.needs_confirmation)


def confirm_all(episode_id: int) -> int:
    """Mark every finding confirmed, once a test that rested on them has passed.

    Coarse on purpose: tracking which finding a given test depended on would
    need the recipe to cite its findings step by step, which is more bookkeeping
    than the evidence is worth. What matters is that confirmation happens
    *because something was observed to work*, and never because a finding was
    written down confidently."""
    confirmed = 0
    for item in store.knowledge(episode_id):
        if not item["confirmed_by_test"]:
            store.confirm_knowledge(item["id"])
            confirmed += 1
    return confirmed


def confirmation_debt(episode_id: int) -> list[dict]:
    """Findings the skill rests on that nothing has yet confirmed (§11)."""
    return [{"question": item["question"], "answer": item["answer"],
             "source": item["source_kind"], "tier": item["trust_tier"]}
            for item in store.knowledge(episode_id)
            if not item["confirmed_by_test"]]


def provenance(episode_id: int) -> dict:
    """Where this skill's knowledge came from, for the demonstration."""
    items = store.knowledge(episode_id)
    by_source: dict[str, int] = {}
    for item in items:
        by_source[item["source_kind"]] = by_source.get(item["source_kind"], 0) + 1
    return {
        "findings": len(items),
        "by_source": by_source,
        "unconfirmed": len([item for item in items if not item["confirmed_by_test"]]),
        "strongest_tier": min([item["trust_tier"] for item in items], default=None),
        "weakest_tier": max([item["trust_tier"] for item in items], default=None),
        "sources_unavailable": unavailable_sources(),
    }
