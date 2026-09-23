"""Mutations that the inquiry machinery's tests must notice.

Krish, 2026-09-23: *"Tests working fine initially is not good testing at all -
please use this ideology when you do testing. Code being perfect the first time
around is a fantasy that you should not buy into."*

Every other test in this repository was probed by hand: break the code, watch
the test fail, put it back. That works exactly once, and then the evidence is
gone - a later refactor can quietly turn any of those tests into one that cannot
fail, and nobody finds out. This file is that discipline written down and made
re-runnable, and it earned its keep on the first run: `tests/test_inquiry.py`
was green, and three of these mutations went straight past it.

Each probe names a module, an exact snippet of it, what to replace the snippet
with, and which tests must go red as a result. A probe whose snippet no longer
appears exactly once is a **hard failure, not a skip**, because a probe that
silently stopped applying is worse than no probe at all - it reports success.

Three modules are covered, which is the shape of the thing being defended:

- `gateway/inquiry.py` - the reasoning, and the five computable biases it will
  refuse to conclude over.
- `gateway/gaps.py` - the wiring that makes `investigating` a state something
  actually investigates, and carries the result into the lifecycle.
- `gateway/introspect.py` - the governance list that keeps Jarvis from editing
  either of the above, which is the short loop the whole arrangement closes.

Run it directly. It is deliberately not named `test_*` so that pytest never
collects it, because it edits source files and runs pytest inside itself:

    python tests/probes/inquiry_probes.py

Each file is restored immediately after its own probe and again in an outer
`finally`, and the restoration is verified by hash before exit. If this ever
reports DIRTY, `git checkout` the modules listed above.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402  - the shared runner; see its docstring

TESTS = Path(__file__).resolve().parents[1]

# Which module a probe edits, and the suite that must notice. Two modules are
# covered: the reasoning itself, and the lifecycle wiring that makes
# `gaps.investigating` a state something actually investigates.
INQUIRY = "gateway/inquiry.py"
GAPS = "gateway/gaps.py"
INTROSPECT = "gateway/introspect.py"
SUITES = {INQUIRY: TESTS / "test_inquiry.py",
          GAPS: TESTS / "test_jarvis_gaps.py",
          INTROSPECT: TESTS / "test_jarvis_selfmod.py"}

# (module, what it breaks, snippet, replacement, tests that must fail)
PROBES: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    (
        INQUIRY,
        "an inquiry accepts an empty question",
        'if not (question or "").strip():',
        "if False:",
        ("test_an_inquiry_needs_a_question",),
    ),
    (
        INQUIRY,
        "a hypothesis need not say what would refute it",
        'if not (refuted_by or "").strip():',
        "if False:",
        ("test_a_hypothesis_must_say_what_would_refute_it",),
    ),
    (
        INQUIRY,
        "a hypothesis key can be reused",
        "if any(existing.key == key for existing in self.hypotheses):",
        "if False:",
        ("test_a_hypothesis_key_cannot_be_reused",),
    ),
    (
        INQUIRY,
        "an observation need not say where it came from",
        'if not (source or "").strip():',
        "if False:",
        ("test_an_observation_must_say_where_it_came_from",),
    ),
    (
        INQUIRY,
        "findings are open",
        "if finding not in FINDINGS:",
        "if False:",
        ("test_findings_are_a_closed_set",),
    ),
    (
        INQUIRY,
        "`about` may name a hypothesis nobody proposed",
        "if about is not None and not self._get(about):",
        "if False:",
        ("test_an_observation_cannot_be_about_a_hypothesis_nobody_proposed",),
    ),
    (
        INQUIRY,
        "a refuting observation eliminates nothing",
        "if finding == REFUTES and about:",
        "if False and about:",
        ("test_a_refuting_observation_eliminates_the_hypothesis_and_says_why",
         "test_the_evidence_bundle_keeps_what_lost_as_well_as_what_won",
         "test_narration_reads_the_losers_out_too"),
    ),
    (
        INQUIRY,
        "an elimination does not record what killed it",
        "self._get(about).because = what",
        'self._get(about).because = ""',
        ("test_a_refuting_observation_eliminates_the_hypothesis_and_says_why",),
    ),
    (
        INQUIRY,
        "observing nothing at all is not an objection",
        "        if not self.observations:\n            found.append(NO_OBSERVATIONS)",
        "        if False:\n            found.append(NO_OBSERVATIONS)",
        ("test_an_inquiry_with_nothing_observed_is_blocked",
         "test_unsupported_with_nothing_observed_is_still_blocked"),
    ),
    (
        INQUIRY,
        "one explanation counts as having compared explanations",
        "if len(self.hypotheses) < 2:",
        "if len(self.hypotheses) < 1:",
        ("test_a_single_explanation_is_blocked",
         "test_unsupported_still_needs_more_than_one_explanation"),
    ),
    (
        INQUIRY,
        "supporting evidence counts as an attempt to refute",
        "                and observation.finding in (REFUTES, NOTHING)",
        "                and observation.finding in (REFUTES, NOTHING, SUPPORTS)",
        ("test_supporting_evidence_alone_never_counts_as_a_refutation_attempt",),
    ),
    (
        INQUIRY,
        "a hypothesis with no stated refutation is still treated as tested",
        "if candidate is None or not candidate.refuted_by or not addressed:",
        "if candidate is None or not addressed:",
        (),  # documented as unreachable: `refuted_by` cannot be empty. See below.
    ),
    (
        INQUIRY,
        "an inconclusive observation counts as confirming",
        "        if self.observations and all(observation.finding == SUPPORTS",
        "        if self.observations and all(observation.finding != REFUTES",
        ("test_a_neutral_observation_also_clears_only_confirming",),
    ),
    (
        INQUIRY,
        "a refutation with no subject eliminates the first hypothesis",
        "        if finding == REFUTES and about:",
        "        if finding == REFUTES:",
        ("test_a_refuting_observation_with_no_subject_eliminates_nothing",),
    ),
    (
        INQUIRY,
        "an all-supporting record is not flagged",
        "        if self.observations and all(observation.finding == SUPPORTS",
        "        if False and all(observation.finding == SUPPORTS",
        ("test_an_all_supporting_record_is_flagged_as_a_search_for_agreement",),
    ),
    (
        INQUIRY,
        "a single observation is reported as a single source",
        "if len(self.observations) > 1 and len(sources) == 1:",
        "if len(self.observations) > 0 and len(sources) == 1:",
        ("test_one_observation_is_not_a_single_source_complaint",),
    ),
    (
        INQUIRY,
        "everything coming from one place is not flagged",
        "            found.append(SINGLE_SOURCE)",
        "            pass",
        ("test_everything_from_one_place_is_flagged",),
    ),
    (
        INQUIRY,
        "anchoring is not flagged",
        "            found.append(ANCHORED)",
        "            pass",
        ("test_the_first_guess_surviving_untested_is_flagged_as_anchoring",),
    ),
    (
        INQUIRY,
        "anchoring stands even after an alternative was eliminated",
        "                and not any(item.state == ELIMINATED for item in self.hypotheses)):",
        "                ):",
        ("test_anchoring_clears_once_an_alternative_is_actually_eliminated",
         "test_a_well_shaped_inquiry_raises_nothing_at_all"),
    ),
    (
        INQUIRY,
        "not having tried to refute the answer is only advice",
        "BLOCKING = (NO_OBSERVATIONS, ONE_HYPOTHESIS, NO_REFUTATION_ATTEMPTED)\nADVISORY = (ONLY_CONFIRMING, SINGLE_SOURCE, ANCHORED)",
        "BLOCKING = (NO_OBSERVATIONS, ONE_HYPOTHESIS)\nADVISORY = (ONLY_CONFIRMING, SINGLE_SOURCE, ANCHORED, NO_REFUTATION_ATTEMPTED)",
        ("test_a_bad_shape_refuses_to_conclude",
         "test_accepting_one_objection_does_not_wave_away_the_others",
         "test_the_refusal_names_every_objection_and_what_to_do"),
    ),
    (
        INQUIRY,
        "an objection is computed and then belongs to neither set",
        "ADVISORY = (ONLY_CONFIRMING, SINGLE_SOURCE, ANCHORED)",
        "ADVISORY = (ONLY_CONFIRMING, SINGLE_SOURCE)",
        ("test_the_objection_sets_partition_cleanly",),
    ),
    (
        INQUIRY,
        "a bad shape concludes anyway",
        "        if standing:\n            raise ShapeRefused(standing)",
        "        if False:\n            raise ShapeRefused(standing)",
        ("test_a_bad_shape_refuses_to_conclude",
         "test_accepting_one_objection_does_not_wave_away_the_others",
         "test_unsupported_still_needs_more_than_one_explanation"),
    ),
    (
        INQUIRY,
        "there is one flag that overrides every objection",
        "    def conclude(self, *, outcome: str, answer: str | None = None,\n"
        "                 reasoning: str = \"\", accepting: list[str] | None = None\n"
        "                 ) -> Conclusion:",
        "    def conclude(self, *, outcome: str, answer: str | None = None,\n"
        "                 reasoning: str = \"\", accepting: list[str] | None = None,\n"
        "                 force: bool = False) -> Conclusion:",
        ("test_there_is_no_single_flag_that_overrides_everything",),
    ),
    (
        INQUIRY,
        "naming one objection accepts all of them",
        "        standing = [name for name in self.blocking(answer=answer)\n"
        "                    if name not in accepted]",
        "        standing = [] if accepted else list(self.blocking(answer=answer))",
        ("test_accepting_one_objection_does_not_wave_away_the_others",),
    ),
    (
        INQUIRY,
        "an objection nobody raised can be accepted",
        "        if unknown:",
        "        if False:",
        ("test_accepting_an_objection_nobody_raised_is_refused",),
    ),
    (
        INQUIRY,
        "an override is not recorded on the conclusion",
        "objections_overridden=tuple(sorted(accepted & set(self.blocking(answer=answer)))),",
        "objections_overridden=(),",
        ("test_overriding_requires_naming_each_objection_and_records_them_forever",),
    ),
    (
        INQUIRY,
        "advisories are not carried onto the conclusion",
        "advisories=tuple(self.advisories(answer=answer)))",
        "advisories=())",
        ("test_advisory_objections_never_block",
         "test_the_evidence_bundle_carries_the_audit_of_the_answer_it_names"),
    ),
    (
        INQUIRY,
        "a confirmed inquiry need not say what it confirmed",
        "if outcome == CONFIRMED and not answer:",
        "if False:",
        ("test_a_confirmed_inquiry_must_name_what_it_confirmed",),
    ),
    (
        INQUIRY,
        "outcomes are open",
        "if outcome not in OUTCOMES:",
        "if False:",
        ("test_outcomes_are_a_closed_set",),
    ),
    (
        INQUIRY,
        "the answer need not be a hypothesis of this inquiry",
        "if answer is not None and not self._get(answer):",
        "if False:",
        ("test_the_answer_must_be_a_hypothesis_of_this_inquiry",),
    ),
    (
        INQUIRY,
        "an answer the record eliminated can be concluded",
        "if answer is not None and self._get(answer).state == ELIMINATED:",
        "if False:",
        ("test_an_answer_the_record_eliminated_cannot_be_concluded_at_all",),
    ),
    (
        INQUIRY,
        "`unsupported` is available without having found anything",
        "        if outcome == UNSUPPORTED and not (",
        "        if False and not (",
        ("test_unsupported_needs_an_absence_or_an_elimination_on_the_record",),
    ),
    (
        INQUIRY,
        "an absence on the record no longer earns `unsupported`",
        "any(item.finding == NOTHING for item in self.observations)",
        "False",
        ("test_looking_and_finding_nothing_concludes_unsupported",),
    ),
    (
        INQUIRY,
        "an elimination no longer earns `unsupported`",
        "                or any(item.state == ELIMINATED for item in self.hypotheses)):",
        "                or False):",
        ("test_everything_being_ruled_out_also_earns_unsupported",),
    ),
    (
        INQUIRY,
        "the surviving hypothesis is not marked",
        "            if candidate.state == OPEN:\n                candidate.state = SURVIVED",
        "            pass",
        ("test_concluding_marks_the_surviving_hypothesis",),
    ),
    (
        INQUIRY,
        "agreement is counted by volume rather than by source",
        "score += min(0.4, 0.2 * len({item.source for item in supporting}))",
        "score += min(0.4, 0.2 * len(supporting))",
        ("test_agreement_is_counted_by_source_not_by_volume",),
    ),
    (
        INQUIRY,
        "confidence survives evidence against the answer",
        "        if against:\n            return 0.0",
        "        if False:\n            return 0.0",
        ("test_confidence_collapses_when_anything_refutes_the_answer",),
    ),
    (
        INQUIRY,
        "surviving a refutation earns nothing",
        "            score += 0.3",
        "            score += 0.0",
        ("test_surviving_a_refutation_is_worth_more_than_more_agreement",),
    ),
    (
        INQUIRY,
        "eliminating alternatives earns nothing",
        "score += min(0.2, 0.1 * eliminated)",
        "score += 0.0",
        ("test_eliminating_an_alternative_raises_confidence",),
    ),
    (
        INQUIRY,
        "independent agreement does not saturate",
        "        score += min(0.4, 0.2 * len({item.source for item in supporting}))",
        "        score += 0.2 * len({item.source for item in supporting})",
        ("test_independent_agreement_saturates",),
    ),
    (
        INQUIRY,
        "the final clamp is removed",
        "return round(min(1.0, score), 2)",
        "return round(score, 2)",
        (),  # documented as unreachable: the terms cap at exactly 1.0. See below.
    ),
    (
        INQUIRY,
        "the caller can supply a confidence",
        "    def conclude(self, *, outcome: str, answer: str | None = None,\n"
        "                 reasoning: str = \"\", accepting: list[str] | None = None\n"
        "                 ) -> Conclusion:",
        "    def conclude(self, *, outcome: str, answer: str | None = None,\n"
        "                 reasoning: str = \"\", accepting: list[str] | None = None,\n"
        "                 confidence: float = 0.0) -> Conclusion:",
        ("test_confidence_cannot_be_supplied_by_the_caller",),
    ),
    (
        INQUIRY,
        "confidence is not derived from the record at conclusion time",
        "            confidence=self.confidence(answer),",
        "            confidence=0.5,",
        ("test_confidence_is_bounded_and_the_conclusion_records_what_was_derived",),
    ),
    (
        INQUIRY,
        "an inquiry concludes twice, erasing the first answer",
        "        if self.conclusion is not None:\n            raise ValueError(\n"
        "                \"this inquiry has already concluded.",
        "        if False:\n            raise ValueError(\n"
        "                \"this inquiry has already concluded.",
        ("test_an_inquiry_cannot_quietly_conclude_twice",),
    ),
    (
        INQUIRY,
        "withdrawing a conclusion discards it",
        "        self.superseded.append({\"conclusion\": withdrawn.to_dict(),",
        "        [].append({\"conclusion\": withdrawn.to_dict(),",
        ("test_reopening_keeps_the_conclusion_it_withdrew_and_why",
         "test_a_reopened_inquiry_concludes_again_with_both_on_the_record"),
    ),
    (
        INQUIRY,
        "withdrawing a conclusion need not say why",
        'if not (because or "").strip():',
        "if False:",
        ("test_withdrawing_a_conclusion_must_say_why",),
    ),
    (
        INQUIRY,
        "withdrawing without a conclusion is allowed",
        "        if self.conclusion is None:\n            raise ValueError(\"this inquiry has not concluded",
        "        if False:\n            raise ValueError(\"this inquiry has not concluded",
        ("test_reopening_an_inquiry_that_never_concluded_is_refused",),
    ),
    (
        INQUIRY,
        "the evidence bundle keeps only what survived",
        '"hypotheses": [item.to_dict() for item in self.hypotheses],',
        '"hypotheses": [item.to_dict() for item in self.hypotheses\n'
        '                           if item.state != ELIMINATED],',
        ("test_the_evidence_bundle_keeps_what_lost_as_well_as_what_won",),
    ),
    (
        INQUIRY,
        "the evidence bundle keeps only the observations that agreed",
        '"observations": [item.to_dict() for item in self.observations],',
        '"observations": [item.to_dict() for item in self.observations\n'
        '                             if item.finding == SUPPORTS],',
        ("test_the_evidence_bundle_keeps_what_lost_as_well_as_what_won",),
    ),
    (
        INQUIRY,
        "the evidence bundle drops withdrawn conclusions",
        '"superseded": list(self.superseded),',
        '"superseded": [],',
        ("test_a_reopened_inquiry_concludes_again_with_both_on_the_record",),
    ),
    (
        INQUIRY,
        "the evidence bundle drops the audit",
        '"audit": self.audit(answer=self.conclusion.answer if self.conclusion else None),',
        '"audit": [],',
        ("test_the_evidence_bundle_carries_the_audit_of_the_answer_it_names",),
    ),
    (
        INQUIRY,
        "narration skips the hypotheses that lost",
        "        for item in self.hypotheses:",
        "        for item in [h for h in self.hypotheses if h.state != ELIMINATED]:",
        ("test_narration_reads_the_losers_out_too",),
    ),
    (
        INQUIRY,
        "narration does not say a conclusion was withdrawn",
        "        for withdrawn in self.superseded:",
        "        for withdrawn in []:",
        ("test_reopening_keeps_the_conclusion_it_withdrew_and_why",),
    ),
    (
        INQUIRY,
        "narration does not say which objections were overridden",
        "            for name in self.conclusion.objections_overridden:",
        "            for name in []:",
        ("test_overriding_requires_naming_each_objection_and_records_them_forever",),
    ),
    (
        INQUIRY,
        "`describe` reports a set the code does not use",
        '        "blocking_objections": list(BLOCKING),',
        '        "blocking_objections": ["one_hypothesis"],',
        ("test_describe_reports_the_sets_the_code_actually_uses",),
    ),
    # --- the wiring: `gaps.investigating` is a state that investigates --------
    (
        GAPS,
        "a gap leaves `investigating` on an inquiry that never concluded",
        "    if asking.conclusion is None:",
        "    if False:",
        ("test_a_gap_cannot_leave_investigating_without_a_concluded_inquiry",),
    ),
    (
        GAPS,
        "the investigation seeds the first hypothesis for the investigator",
        "    return moved, inquiry.Inquiry(asked, opened_by=agent)",
        "    asking = inquiry.Inquiry(asked, opened_by=agent)\n"
        "    asking.hypothesise('no_gap', 'the capability is there',\n"
        "                       refuted_by='a run that fails')\n"
        "    return moved, asking",
        ("test_the_investigation_seeds_no_hypotheses_of_its_own",
         "test_investigating_opens_an_inquiry_about_the_gap"),
    ),
    (
        GAPS,
        "a caller's own question is ignored",
        'asked = question.strip() or (',
        'asked = "" or (',
        ("test_a_caller_may_ask_its_own_question",),
    ),
    (
        GAPS,
        "a confirmed inquiry picks its own remedy",
        "        if remedy is None:",
        "        remedy = remedy or REMEDY_CODE\n        if remedy is None:",
        ("test_confirming_a_gap_from_an_inquiry_still_needs_a_remedy",),
    ),
    (
        GAPS,
        "`unsupported` and `inconclusive` land in the same place",
        "    if said.outcome == inquiry.UNSUPPORTED:",
        "    if False:",
        ("test_an_inquiry_that_found_nothing_leaves_the_gap_unsupported",
         "test_every_inquiry_outcome_has_exactly_one_destination"),
    ),
    (
        GAPS,
        "an inconclusive investigation closes the gap instead of deferring it",
        "    return transition(client, gap, DEFERRED, evidence=bundle,",
        "    return transition(client, gap, UNSUPPORTED, evidence=bundle,",
        ("test_an_inconclusive_inquiry_defers_the_gap_rather_than_closing_it",
         "test_every_inquiry_outcome_has_exactly_one_destination"),
    ),
    (
        GAPS,
        "a confirmed inquiry does not confirm the gap",
        "    if said.outcome == inquiry.CONFIRMED:\n"
        "        return confirm(client, gap, evidence=bundle,",
        "    if False:\n"
        "        return confirm(client, gap, evidence=bundle,",
        ("test_a_confirmed_inquiry_confirms_the_gap_with_its_whole_record",
         "test_every_inquiry_outcome_has_exactly_one_destination"),
    ),
    (
        GAPS,
        "only the winning line of reasoning reaches the gap",
        "    bundle = _text(asking.evidence())",
        "    bundle = _text({'answer': asking.conclusion.answer})",
        ("test_a_confirmed_inquiry_confirms_the_gap_with_its_whole_record",),
    ),
    (
        GAPS,
        "an overridden objection is buried in the nested conclusion",
        "    if said.objections_overridden:",
        "    if False:",
        ("test_an_overridden_objection_is_the_first_thing_on_the_evidence",),
    ),
    (
        GAPS,
        "the override warning is appended rather than put first",
        '        bundle = (f"{OVERRIDDEN_WARNING}: "',
        '        bundle = (bundle + f"\\n\\n{OVERRIDDEN_WARNING}: "',
        ("test_an_overridden_objection_is_the_first_thing_on_the_evidence",),
    ),
    (
        GAPS,
        "a clean investigation is warned about anyway",
        "    if said.objections_overridden:",
        "    if True:",
        ("test_a_clean_investigation_carries_no_warning",),
    ),
    (
        GAPS,
        "a write happens before the remedy is checked",
        "    if said.outcome == inquiry.CONFIRMED:\n        if remedy is None:",
        "    if False:\n        if remedy is None:",
        ("test_a_settle_that_is_refused_writes_nothing_at_all",),
    ),
    (
        GAPS,
        "an undeclared remedy is only caught after the confidence is written",
        "        _check_remedy(remedy)\n",
        "",
        ("test_a_settle_that_is_refused_writes_nothing_at_all",),
    ),
    (
        GAPS,
        "the derived confidence never reaches the gap",
        '    client.update(gap["id"], {"confidence": said.confidence},',
        '    client.update(gap["id"], {},',
        ("test_the_gaps_confidence_is_the_one_the_inquiry_derived",),
    ),
    (
        GAPS,
        "the gap carries a confidence nobody derived",
        '{"confidence": said.confidence}',
        '{"confidence": 0.9}',
        ("test_the_gaps_confidence_is_the_one_the_inquiry_derived",
         "test_a_gap_confirmed_over_objections_carries_a_lower_confidence",
         "test_an_unsupported_investigation_records_its_confidence_too"),
    ),
    (
        INTROSPECT,
        "the reasoning the approval gate turns on is modifiable",
        '    "gateway/inquiry.py",',
        "",
        ("test_the_gate_and_the_reasoning_it_turns_on_are_both_out_of_reach",
         "test_jarvis_cannot_widen_his_own_authority"),
    ),
    (
        INTROSPECT,
        "the §13 gate itself is modifiable",
        '    "gateway/gaps.py",',
        "",
        ("test_the_gate_and_the_reasoning_it_turns_on_are_both_out_of_reach",
         "test_jarvis_cannot_widen_his_own_authority"),
    ),
    (
        GAPS,
        "entering an investigation leaves no trace in the life ledger",
        "    _note(client, ledger.STATE_TRANSITION,",
        "    _skip_note = lambda *a, **k: None\n    _skip_note(",
        ("test_the_investigation_is_in_the_life_ledger",),
    ),
]

# Probes with an empty expectation are recorded, not asserted. Two exist, and
# both are defensive code that no test can reach through the public API. Listing
# them here is the honest alternative to writing tests that pretend to cover
# them, or to deleting guards that are cheap and correct:
#
# - `not candidate.refuted_by` in `audit` - `hypothesise` refuses an empty
#   `refuted_by`, so only a caller constructing `Hypothesis` directly gets there.
# - `min(1.0, score)` in `confidence` - the four terms cap at 0.4, 0.3, 0.2 and
#   0.1, which sum to exactly 1.0, so the clamp can never fire. It is the guard
#   that keeps the contract true if a term is ever added or a cap raised, and
#   `test_independent_agreement_saturates` is what actually holds the per-term
#   caps in place.



if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
