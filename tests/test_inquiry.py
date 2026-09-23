"""Jarvis investigating something, and the shape of the reasoning being audited.

Krish, 2026-09-23: *"please at least build as much of inquisitive and deep
reasoning abilities without biases as you possibly can."*

`gateway/inquiry.py` does not claim to reason without bias - nothing can claim
that about itself. It keeps a record whose *shape* is computable and refuses to
conclude when the shape is bad. These tests are therefore mostly about the
refusals, because a bias check that never blocks anything is decoration.

Written to the standing rule of the same day - *"tests working fine initially is
not good testing at all"* - so every behaviour asserted here was run against
`gateway/inquiry.py` with that behaviour removed, and failed there first. The
mutations used are listed in `tests/probes/inquiry_probes.py`.
"""

import inspect
from pathlib import Path

import pytest

from gateway import inquiry
from gateway.inquiry import (
    ADVISORY, ANCHORED, BLOCKING, CONFIRMED, ELIMINATED, INCONCLUSIVE, NEUTRAL,
    NO_OBSERVATIONS, NO_REFUTATION_ATTEMPTED, NOTHING, OBJECTIONS,
    ONE_HYPOTHESIS, ONLY_CONFIRMING, OPEN, REFUTES, SINGLE_SOURCE, SUPPORTS,
    SURVIVED, UNSUPPORTED, Inquiry, ShapeRefused)


def well_shaped() -> Inquiry:
    """An inquiry with nothing wrong with it, which every other test breaks.

    Two explanations, one of them killed by evidence, the survivor looked at
    for the thing that would have killed *it*, and three separate sources. It
    audits clean; that is what makes it useful as a starting point, because a
    test that breaks one thing about it has isolated exactly one thing."""
    asking = Inquiry("why did the backup fail on Tuesday?")
    asking.hypothesise("disk", "the disk was full",
                       refuted_by="free space at the time of the backup")
    asking.hypothesise("lock", "another process held the database",
                       refuted_by="no other process held the database then")
    asking.observe("df reported 2GB free at 02:00", source="df",
                   finding=REFUTES, about="disk")
    asking.observe("postgres held backup.db from 01:58", source="fuser",
                   finding=SUPPORTS, about="lock")
    asking.observe("looked for a window with no holder; found none",
                   source="pg_locks", finding=NOTHING, about="lock")
    return asking


# --- what cannot be built at all ----------------------------------------------

@pytest.mark.parametrize("question", ["", "   ", "\n"])
def test_an_inquiry_needs_a_question(question):
    with pytest.raises(ValueError, match="needs a question"):
        Inquiry(question)


@pytest.mark.parametrize("refuted_by", ["", "   "])
def test_a_hypothesis_must_say_what_would_refute_it(refuted_by):
    """The one field that cannot be filled in later.

    Asked afterwards, the question goes to somebody who already believes the
    answer, and that is the question they are worst at."""
    asking = Inquiry("why is it slow?")
    with pytest.raises(ValueError, match="what would refute it"):
        asking.hypothesise("gc", "garbage collection", refuted_by=refuted_by)
    assert asking.hypotheses == []


def test_a_hypothesis_key_cannot_be_reused():
    asking = Inquiry("why is it slow?")
    asking.hypothesise("gc", "garbage collection", refuted_by="no gc pauses")
    with pytest.raises(ValueError, match="already in this inquiry"):
        asking.hypothesise("gc", "something else entirely", refuted_by="anything")
    assert len(asking.hypotheses) == 1


def test_an_observation_must_say_where_it_came_from():
    """Without a source, `single_source` cannot be computed at all."""
    asking = Inquiry("why is it slow?")
    with pytest.raises(ValueError, match="where it came from"):
        asking.observe("it felt slow", source="  ", finding=SUPPORTS)
    assert asking.observations == []


def test_findings_are_a_closed_set():
    asking = Inquiry("why is it slow?")
    with pytest.raises(ValueError, match="finding must be one of"):
        asking.observe("it felt slow", source="me", finding="probably")


def test_an_observation_cannot_be_about_a_hypothesis_nobody_proposed():
    """Otherwise a typo in `about` silently detaches evidence from the thing it
    bears on, and the audit sees an inquiry with no refutation attempted."""
    asking = Inquiry("why is it slow?")
    asking.hypothesise("gc", "garbage collection", refuted_by="no gc pauses")
    with pytest.raises(ValueError, match="not a hypothesis in this inquiry"):
        asking.observe("no pauses in the log", source="gc.log",
                       finding=NOTHING, about="gcc")
    assert asking.observations == []


def test_a_refuting_observation_eliminates_the_hypothesis_and_says_why():
    asking = well_shaped()
    disk = asking.hypotheses[0]
    assert disk.state == ELIMINATED
    assert disk.because == "df reported 2GB free at 02:00"
    assert asking.hypotheses[1].state == OPEN


def test_a_refuting_observation_with_no_subject_eliminates_nothing():
    """`about` is what connects evidence to a claim; without it the observation
    is on the record but has not killed anything."""
    asking = Inquiry("why is it slow?")
    asking.hypothesise("gc", "garbage collection", refuted_by="no gc pauses")
    asking.observe("the machine was fine", source="uptime", finding=REFUTES)
    assert asking.hypotheses[0].state == OPEN


# --- the five computable biases, one test each --------------------------------

def test_the_objection_sets_partition_cleanly():
    """Every objection is either blocking or advisory, and never both.

    An objection in neither set is computed and then discarded, which is worse
    than not computing it - it reads as a check that exists."""
    assert set(BLOCKING) | set(ADVISORY) == set(OBJECTIONS)
    assert not set(BLOCKING) & set(ADVISORY)


def test_an_inquiry_with_nothing_observed_is_blocked():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "one thing", refuted_by="x")
    asking.hypothesise("b", "another", refuted_by="y")
    assert NO_OBSERVATIONS in asking.audit()
    assert NO_OBSERVATIONS in asking.blocking()


def test_a_single_explanation_is_blocked():
    """Nothing was compared, so the answer could not have come out differently."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "one thing", refuted_by="x")
    asking.observe("it failed", source="log", finding=SUPPORTS, about="a")
    assert ONE_HYPOTHESIS in asking.blocking()

    asking.hypothesise("b", "another", refuted_by="y")
    assert ONE_HYPOTHESIS not in asking.audit()


def test_an_answer_nothing_looked_to_refute_is_blocked():
    asking = well_shaped()
    assert NO_REFUTATION_ATTEMPTED not in asking.audit(answer="lock")
    # `disk` had a refutation attempted too - it was refuted. The objection is
    # about the hypothesis nobody went at: neither observation is about it.
    asking.hypothesise("dns", "name resolution stalled", refuted_by="fast lookups")
    assert NO_REFUTATION_ATTEMPTED in asking.audit(answer="dns")


def test_supporting_evidence_alone_never_counts_as_a_refutation_attempt():
    """Piling up agreement is the thing this objection exists to catch."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "one thing", refuted_by="x")
    asking.hypothesise("b", "another", refuted_by="y")
    for index in range(5):
        asking.observe(f"more agreement {index}", source=f"s{index}",
                       finding=SUPPORTS, about="a")
    assert NO_REFUTATION_ATTEMPTED in asking.audit(answer="a")


def test_finding_nothing_is_what_clears_the_refutation_objection():
    """An absence is evidence. §12's `unsupported` depends on it being sayable."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "one thing", refuted_by="x")
    asking.hypothesise("b", "another", refuted_by="y")
    asking.observe("agreement", source="s1", finding=SUPPORTS, about="a")
    assert NO_REFUTATION_ATTEMPTED in asking.audit(answer="a")
    asking.observe("looked for x; found none", source="s2",
                   finding=NOTHING, about="a")
    assert NO_REFUTATION_ATTEMPTED not in asking.audit(answer="a")


def test_an_all_supporting_record_is_flagged_as_a_search_for_agreement():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "one thing", refuted_by="x")
    asking.hypothesise("b", "another", refuted_by="y")
    asking.observe("agrees", source="s1", finding=SUPPORTS, about="a")
    asking.observe("also agrees", source="s2", finding=SUPPORTS, about="a")
    assert ONLY_CONFIRMING in asking.audit(answer="a")
    assert ONLY_CONFIRMING in ADVISORY

    asking.observe("looked for x; found none", source="s3",
                   finding=NOTHING, about="a")
    assert ONLY_CONFIRMING not in asking.audit(answer="a")


def test_a_neutral_observation_also_clears_only_confirming():
    """`neutral` exists so that looking at something inconclusive is recordable;
    an inquiry holding one is not a search for agreement."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "one thing", refuted_by="x")
    asking.observe("agrees", source="s1", finding=SUPPORTS, about="a")
    asking.observe("could not tell", source="s2", finding=NEUTRAL, about="a")
    assert ONLY_CONFIRMING not in asking.audit()


def test_everything_from_one_place_is_flagged():
    """An error in that place is then indistinguishable from a fact."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "one thing", refuted_by="x")
    asking.hypothesise("b", "another", refuted_by="y")
    asking.observe("agrees", source="the same log", finding=SUPPORTS, about="a")
    asking.observe("looked for x; none", source="the same log",
                   finding=NOTHING, about="a")
    assert SINGLE_SOURCE in asking.audit(answer="a")

    asking.observe("second opinion", source="a different log",
                   finding=SUPPORTS, about="a")
    assert SINGLE_SOURCE not in asking.audit(answer="a")


def test_one_observation_is_not_a_single_source_complaint():
    """One observation trivially has one source. Reporting that as an objection
    would make the check fire on every young inquiry and teach nobody
    anything."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "one thing", refuted_by="x")
    asking.observe("looked for x; none", source="only", finding=NOTHING, about="a")
    assert SINGLE_SOURCE not in asking.audit(answer="a")


def test_the_first_guess_surviving_untested_is_flagged_as_anchoring():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "the first thing that came to mind", refuted_by="x")
    asking.hypothesise("b", "the afterthought", refuted_by="y")
    asking.observe("looked for x; none", source="s1", finding=NOTHING, about="a")
    assert ANCHORED in asking.audit(answer="a")
    # Not raised against the answer that was not written down first.
    assert ANCHORED not in asking.audit(answer="b")


def test_anchoring_clears_once_an_alternative_is_actually_eliminated():
    """The complaint is not "you thought of it first" - it is "you thought of it
    first and never ruled anything else out"."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "the first thing", refuted_by="x")
    asking.hypothesise("b", "the afterthought", refuted_by="y")
    asking.observe("looked for x; none", source="s1", finding=NOTHING, about="a")
    assert ANCHORED in asking.audit(answer="a")
    asking.observe("y happened", source="s2", finding=REFUTES, about="b")
    assert ANCHORED not in asking.audit(answer="a")


def test_a_well_shaped_inquiry_raises_nothing_at_all():
    asking = well_shaped()
    assert asking.audit(answer="lock") == []


# --- concluding, and refusing to -----------------------------------------------

def test_a_bad_shape_refuses_to_conclude():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "the only idea", refuted_by="x")
    with pytest.raises(ShapeRefused) as raised:
        asking.conclude(outcome=CONFIRMED, answer="a")
    assert set(raised.value.objections) == {NO_OBSERVATIONS, ONE_HYPOTHESIS,
                                            NO_REFUTATION_ATTEMPTED}
    assert asking.conclusion is None


def test_the_refusal_names_every_objection_and_what_to_do():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "the only idea", refuted_by="x")
    with pytest.raises(ShapeRefused) as raised:
        asking.conclude(outcome=CONFIRMED, answer="a")
    message = str(raised.value)
    for name in (NO_OBSERVATIONS, ONE_HYPOTHESIS, NO_REFUTATION_ATTEMPTED):
        assert name in message
        assert OBJECTIONS[name] in message
    assert "accepting=" in message


def test_advisory_objections_never_block():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "first", refuted_by="x")
    asking.hypothesise("b", "second", refuted_by="y")
    asking.observe("agrees", source="only", finding=SUPPORTS, about="a")
    asking.observe("looked for x; none", source="only", finding=NOTHING, about="a")
    assert set(asking.advisories(answer="a")) == {SINGLE_SOURCE, ANCHORED}
    assert asking.blocking(answer="a") == []
    said = asking.conclude(outcome=CONFIRMED, answer="a")
    assert set(said.advisories) == {SINGLE_SOURCE, ANCHORED}
    assert said.objections_overridden == ()


def test_overriding_requires_naming_each_objection_and_records_them_forever():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "the only idea", refuted_by="x")
    asking.observe("agrees", source="s1", finding=SUPPORTS, about="a")
    said = asking.conclude(
        outcome=CONFIRMED, answer="a", reasoning="shipping anyway",
        accepting=[ONE_HYPOTHESIS, NO_REFUTATION_ATTEMPTED])
    assert set(said.objections_overridden) == {ONE_HYPOTHESIS,
                                               NO_REFUTATION_ATTEMPTED}
    assert said.to_dict()["objections_overridden"]
    assert "OVERRODE" in "\n".join(asking.narrate())


def test_accepting_one_objection_does_not_wave_away_the_others():
    """The whole reason there is no `force=True`: overriding five objections has
    to cost five times what overriding one costs."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "the only idea", refuted_by="x")
    asking.observe("agrees", source="s1", finding=SUPPORTS, about="a")
    with pytest.raises(ShapeRefused) as raised:
        asking.conclude(outcome=CONFIRMED, answer="a", accepting=[ONE_HYPOTHESIS])
    assert raised.value.objections == [NO_REFUTATION_ATTEMPTED]


def test_accepting_an_objection_nobody_raised_is_refused():
    """So that a typo cannot stand in for an override."""
    asking = well_shaped()
    with pytest.raises(ValueError, match="unknown objection"):
        asking.conclude(outcome=CONFIRMED, answer="lock",
                        accepting=["one_hypotheses"])


def test_there_is_no_single_flag_that_overrides_everything():
    """Asserted against the signature and the source, not the docstring.

    A module that only *says* it has no escape hatch is the failure mode this
    repository keeps finding in its own tests."""
    parameters = inspect.signature(Inquiry.conclude).parameters
    assert "force" not in parameters
    assert not [name for name, parameter in parameters.items()
                if isinstance(parameter.default, bool)]
    source = Path(inquiry.__file__).read_text()
    assert "force=True" not in source.replace(
        "There is deliberately no `force=True`", "").replace(
        "is no\n        `force=True`", "")


def test_a_confirmed_inquiry_must_name_what_it_confirmed():
    asking = well_shaped()
    with pytest.raises(ValueError, match="which hypothesis"):
        asking.conclude(outcome=CONFIRMED)


def test_outcomes_are_a_closed_set():
    asking = well_shaped()
    with pytest.raises(ValueError, match="outcome must be one of"):
        asking.conclude(outcome="probably", answer="lock")


def test_the_answer_must_be_a_hypothesis_of_this_inquiry():
    asking = well_shaped()
    with pytest.raises(ValueError, match="not a hypothesis"):
        asking.conclude(outcome=CONFIRMED, answer="gremlins")


def test_an_answer_the_record_eliminated_cannot_be_concluded_at_all():
    """Not an objection to be weighed - a contradiction with the record, so
    `accepting` deliberately does not reach it."""
    asking = well_shaped()
    with pytest.raises(ValueError, match="was eliminated by"):
        asking.conclude(outcome=CONFIRMED, answer="disk")
    with pytest.raises(ValueError, match="was eliminated by"):
        asking.conclude(outcome=INCONCLUSIVE, answer="disk",
                        accepting=list(OBJECTIONS))
    assert asking.conclusion is None


def test_looking_and_finding_nothing_concludes_unsupported():
    """§12's `unsupported`: there is no answer, so "nothing refuted the answer"
    is not an objection that can apply."""
    asking = Inquiry("is the cache corrupting rows?")
    asking.hypothesise("cache", "the cache corrupts rows", refuted_by="clean rows")
    asking.hypothesise("driver", "the driver truncates", refuted_by="full writes")
    asking.observe("10k rows compared; all clean", source="checksum",
                   finding=NOTHING, about="cache")
    said = asking.conclude(outcome=UNSUPPORTED, reasoning="looked properly")
    assert said.outcome == UNSUPPORTED
    assert said.answer is None
    assert said.objections_overridden == ()


def test_unsupported_needs_an_absence_or_an_elimination_on_the_record():
    """Otherwise "I looked and there was nothing there" is indistinguishable
    from "I did not look", which is `inconclusive` and says so."""
    asking = Inquiry("is the cache corrupting rows?")
    asking.hypothesise("cache", "the cache corrupts rows", refuted_by="clean rows")
    asking.hypothesise("driver", "the driver truncates", refuted_by="full writes")
    # A refutation with no `about` passes the shape audit - something refuted
    # something - while eliminating nothing. It is the one record that reaches
    # this check, and it is a real mistake rather than a contrived one.
    asking.observe("the rows were not truncated", source="checksum",
                   finding=REFUTES)
    assert asking.audit() == []
    with pytest.raises(ValueError, match="must hold either an observation"):
        asking.conclude(outcome=UNSUPPORTED)
    # `inconclusive` is what that record actually supports, and it is allowed.
    assert asking.conclude(outcome=INCONCLUSIVE).outcome == INCONCLUSIVE

    # Saying what it refuted is all that was missing.
    said = Inquiry("is the cache corrupting rows?")
    said.hypothesise("cache", "the cache corrupts rows", refuted_by="clean rows")
    said.hypothesise("driver", "the driver truncates", refuted_by="full writes")
    said.observe("the rows were not truncated", source="checksum",
                 finding=REFUTES, about="driver")
    assert said.conclude(outcome=UNSUPPORTED).outcome == UNSUPPORTED


def test_everything_being_ruled_out_also_earns_unsupported():
    """The other way to have looked properly: no absences recorded, but nothing
    survived either."""
    asking = Inquiry("is the cache corrupting rows?")
    asking.hypothesise("cache", "the cache corrupts rows", refuted_by="clean rows")
    asking.hypothesise("driver", "the driver truncates", refuted_by="full writes")
    asking.observe("rows are clean", source="checksum", finding=REFUTES,
                   about="cache")
    asking.observe("writes are full length", source="wal", finding=REFUTES,
                   about="driver")
    assert asking.conclude(outcome=UNSUPPORTED).outcome == UNSUPPORTED


def test_unsupported_still_needs_more_than_one_explanation():
    """The waiver is narrow: it removes exactly the objection that cannot apply,
    not the other two."""
    asking = Inquiry("is the cache corrupting rows?")
    asking.hypothesise("cache", "the cache corrupts rows", refuted_by="clean rows")
    asking.observe("10k rows clean", source="checksum", finding=NOTHING,
                   about="cache")
    with pytest.raises(ShapeRefused) as raised:
        asking.conclude(outcome=UNSUPPORTED)
    assert raised.value.objections == [ONE_HYPOTHESIS]


def test_unsupported_with_nothing_observed_is_still_blocked():
    asking = Inquiry("is the cache corrupting rows?")
    asking.hypothesise("cache", "corruption", refuted_by="clean rows")
    asking.hypothesise("driver", "truncation", refuted_by="full writes")
    with pytest.raises(ShapeRefused) as raised:
        asking.conclude(outcome=UNSUPPORTED)
    assert raised.value.objections == [NO_OBSERVATIONS, NO_REFUTATION_ATTEMPTED]


def test_concluding_marks_the_surviving_hypothesis():
    asking = well_shaped()
    asking.conclude(outcome=CONFIRMED, answer="lock")
    assert asking.hypotheses[1].state == SURVIVED
    assert asking.hypotheses[0].state == ELIMINATED


# --- confidence is earned -------------------------------------------------------

def test_confidence_cannot_be_supplied_by_the_caller():
    """Nothing in the API accepts a number for it. A model's estimate of its own
    certainty is the least reliable number available and is not collected."""
    assert "confidence" not in inspect.signature(Inquiry.conclude).parameters
    assert "confidence" not in inspect.signature(Inquiry.observe).parameters
    assert "confidence" not in inspect.signature(Inquiry.hypothesise).parameters


def test_confidence_is_zero_with_nothing_observed():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "an idea", refuted_by="x")
    assert asking.confidence("a") == 0.0


def test_confidence_collapses_when_anything_refutes_the_answer():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "an idea", refuted_by="x")
    asking.hypothesise("b", "another", refuted_by="y")
    asking.observe("agrees", source="s1", finding=SUPPORTS, about="a")
    asking.observe("agrees", source="s2", finding=SUPPORTS, about="a")
    assert asking.confidence("a") > 0
    asking.observe("x happened", source="s3", finding=REFUTES, about="a")
    assert asking.confidence("a") == 0.0


def test_agreement_is_counted_by_source_not_by_volume():
    """Three readings of one log are one reading."""
    repeated = well_shaped()
    for index in range(3):
        repeated.observe(f"same log again {index}", source="fuser",
                         finding=SUPPORTS, about="lock")
    assert repeated.confidence("lock") == well_shaped().confidence("lock")

    independent = well_shaped()
    independent.observe("the application log agrees", source="app.log",
                        finding=SUPPORTS, about="lock")
    assert independent.confidence("lock") > repeated.confidence("lock")


def test_surviving_a_refutation_is_worth_more_than_more_agreement():
    """The central claim of the whole module, stated as a number comparison."""
    survived = well_shaped()

    agreed = Inquiry("why did the backup fail on Tuesday?")
    agreed.hypothesise("disk", "the disk was full",
                       refuted_by="free space at the time of the backup")
    agreed.hypothesise("lock", "another process held the database",
                       refuted_by="no other process held the database then")
    agreed.observe("df reported 2GB free at 02:00", source="df",
                   finding=REFUTES, about="disk")
    agreed.observe("postgres held backup.db from 01:58", source="fuser",
                   finding=SUPPORTS, about="lock")
    agreed.observe("the application log agrees", source="pg_locks",
                   finding=SUPPORTS, about="lock")

    assert survived.confidence("lock") > agreed.confidence("lock")


def test_eliminating_an_alternative_raises_confidence():
    """Isolated from the clean-shape bonus on purpose.

    The first version of this test answered with the first hypothesis, so the
    elimination also cleared `anchored` and the number moved for that reason
    instead. It passed with the eliminated-alternatives term deleted, which is
    what `tests/probes/inquiry_probes.py` is for. Answering with the hypothesis
    that was *not* written down first keeps `anchored` out of it, so the shape
    is already clean before the elimination and only one term can move."""
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "the first idea", refuted_by="x")
    asking.hypothesise("b", "the second", refuted_by="y")
    asking.observe("agrees", source="s1", finding=SUPPORTS, about="b")
    asking.observe("looked for y; none", source="s2", finding=NOTHING, about="b")
    assert asking.audit(answer="b") == []
    before = asking.confidence("b")

    asking.observe("x happened", source="s3", finding=REFUTES, about="a")
    assert asking.audit(answer="b") == []
    assert asking.confidence("b") > before


def test_independent_agreement_saturates():
    """Twenty sources are not five times better than four.

    Each term of `confidence` is capped, and the caps are what stop a conclusion
    from being talked up by volume. The first version of the bound test only
    exercised the final clamp, which turns out to be unreachable - see
    `tests/probes/inquiry_probes.py`."""
    two = well_shaped()
    two.observe("the application log agrees", source="app.log",
                finding=SUPPORTS, about="lock")

    many = well_shaped()
    for index in range(19):
        many.observe(f"and so does {index}", source=f"source-{index}",
                     finding=SUPPORTS, about="lock")

    assert two.confidence("lock") == many.confidence("lock")


def test_confidence_is_bounded_and_the_conclusion_records_what_was_derived():
    asking = well_shaped()
    for index in range(20):
        asking.observe(f"independent agreement {index}", source=f"source-{index}",
                       finding=SUPPORTS, about="lock")
    assert 0.0 <= asking.confidence("lock") <= 1.0
    said = asking.conclude(outcome=CONFIRMED, answer="lock")
    assert said.confidence == asking.confidence("lock")


# --- a conclusion is withdrawn, never overwritten --------------------------------

def test_an_inquiry_cannot_quietly_conclude_twice():
    asking = well_shaped()
    asking.conclude(outcome=CONFIRMED, answer="lock")
    with pytest.raises(ValueError, match="already concluded"):
        asking.conclude(outcome=INCONCLUSIVE)
    assert asking.conclusion.answer == "lock"


def test_reopening_keeps_the_conclusion_it_withdrew_and_why():
    asking = well_shaped()
    first = asking.conclude(outcome=CONFIRMED, answer="lock")
    asking.reopen(because="the fuser output was from the wrong host")
    assert asking.conclusion is None
    assert len(asking.superseded) == 1
    assert asking.superseded[0]["conclusion"] == first.to_dict()
    assert "wrong host" in asking.superseded[0]["because"]
    assert "WITHDRAWN" in "\n".join(asking.narrate())


@pytest.mark.parametrize("because", ["", "  "])
def test_withdrawing_a_conclusion_must_say_why(because):
    asking = well_shaped()
    asking.conclude(outcome=CONFIRMED, answer="lock")
    with pytest.raises(ValueError, match="must say why"):
        asking.reopen(because=because)
    assert asking.conclusion is not None
    assert asking.superseded == []


def test_reopening_an_inquiry_that_never_concluded_is_refused():
    asking = well_shaped()
    with pytest.raises(ValueError, match="nothing to withdraw"):
        asking.reopen(because="second thoughts")


def test_a_reopened_inquiry_concludes_again_with_both_on_the_record():
    asking = well_shaped()
    asking.conclude(outcome=CONFIRMED, answer="lock")
    asking.reopen(because="the fuser output was from the wrong host")
    asking.observe("no holder on the right host", source="fuser@backup01",
                   finding=REFUTES, about="lock")
    again = asking.conclude(outcome=INCONCLUSIVE,
                            reasoning="both explanations are now dead")
    assert again.outcome == INCONCLUSIVE
    assert asking.evidence()["superseded"][0]["conclusion"]["answer"] == "lock"


# --- what it hands to gaps.confirm ----------------------------------------------

def test_the_evidence_bundle_keeps_what_lost_as_well_as_what_won():
    """§12 asks for the evidence that caused a classification. A bundle holding
    only the winning line is a story, not a record."""
    asking = well_shaped()
    asking.conclude(outcome=CONFIRMED, answer="lock")
    bundle = asking.evidence()

    keys = [item["key"] for item in bundle["hypotheses"]]
    assert keys == ["disk", "lock"]
    eliminated = [item for item in bundle["hypotheses"]
                  if item["state"] == ELIMINATED]
    assert [item["because"] for item in eliminated] == \
        ["df reported 2GB free at 02:00"]

    findings = [item["finding"] for item in bundle["observations"]]
    assert sorted(findings) == sorted([REFUTES, SUPPORTS, NOTHING])
    assert bundle["conclusion"]["answer"] == "lock"
    assert bundle["question"] == "why did the backup fail on Tuesday?"


def test_the_evidence_bundle_carries_the_audit_of_the_answer_it_names():
    asking = Inquiry("why did it fail?")
    asking.hypothesise("a", "the first idea", refuted_by="x")
    asking.hypothesise("b", "the second", refuted_by="y")
    asking.observe("agrees", source="only", finding=SUPPORTS, about="a")
    asking.observe("looked for x; none", source="only", finding=NOTHING, about="a")
    asking.conclude(outcome=CONFIRMED, answer="a")
    assert set(asking.evidence()["audit"]) == {SINGLE_SOURCE, ANCHORED}


def test_narration_reads_the_losers_out_too():
    lines = "\n".join(well_shaped().narrate())
    assert "the disk was full" in lines
    assert "eliminated by: df reported 2GB free at 02:00" in lines
    assert "would be refuted by:" in lines


def test_describe_reports_the_sets_the_code_actually_uses():
    described = inquiry.describe()
    assert described["blocking_objections"] == list(BLOCKING)
    assert described["advisory_objections"] == list(ADVISORY)
    assert described["objections"] == dict(OBJECTIONS)
    assert described["confidence_is_derived"] is True
    assert described["no_force_flag"] is True
