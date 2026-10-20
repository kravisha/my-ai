"""Mutations that `tests/test_taskrun.py` must notice.

Krish, 2026-09-23: *"ask me questions while you are working on the account so
that we don't have any confusion about what needs to be done. Also use last
year's statement as a model and ask me questions when you can't find the data
that you seek."*

This module fails silently in four directions, which is why it is probed rather
than reviewed:

- **A figure arrives with no provenance.** Drop the `source` requirement and
  every statement still comes out looking finished. That is the forgery
  Amendment 3 is about, and it is invisible in the output.
- **Jarvis answers his own question.** Drop one comparison and the run gets
  faster, the questions all resolve, and the answers are his guesses wearing
  Krish's name.
- **A hole is reported as a finished line.** The most dangerous failure in the
  whole module looks exactly like success.
- **A saved run is believed on the way back.** The bundle in the store is
  editable by anything that can reach the store, and a value restored without
  a source, or an answer restored under somebody else's name, is afterwards
  indistinguishable from one that was found or given. Every refusal above has
  to hold on the restore path too, and each of these drops one there.

Run it directly:

    python tests/probes/taskrun_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

TASKRUN = "gateway/taskrun.py"
SUITES = {TASKRUN: TESTS / "test_taskrun.py"}

PROBES: list[harness.Probe] = [

    # --- the model gives shape, never values --------------------------------
    (
        TASKRUN,
        "the model grows a field that can carry last year's number",
        "    name: str\n    means: str\n\n    def __post_init__(self) -> None:\n"
        "        for label, value in",
        "    name: str\n    means: str\n    value: str = \"\"\n\n"
        "    def __post_init__(self) -> None:\n"
        "        for label, value in",
        ("test_a_model_cannot_carry_a_value",),
    ),
    (
        TASKRUN,
        "a model hands every run the same needs, so one run's figures appear "
        "in the next",
        "    def needs(self) -> list[\"Need\"]:\n"
        "        return [Need(name=one.name, means=one.means) for one in self.fields]",
        "    def needs(self) -> list[\"Need\"]:\n"
        "        cached = getattr(Model.needs, \"_cache\", None)\n"
        "        if cached is None:\n"
        "            cached = Model.needs._cache = [\n"
        "                Need(name=one.name, means=one.means) for one in self.fields]\n"
        "        return cached",
        ("test_two_runs_of_the_same_model_do_not_share_their_needs",),
    ),
    (
        TASKRUN,
        "a model with no fields is accepted and says nothing about a finished "
        "statement",
        "        if not self.fields:\n            raise NotFound(",
        "        if False:\n            raise NotFound(",
        ("test_a_model_with_no_fields_says_nothing_about_a_finished_statement",),
    ),
    (
        TASKRUN,
        "a model field with no meaning is accepted",
        "            if not (value or \"\").strip():\n"
        "                raise NotFound(f\"a model field needs a {label}\")",
        "            if False:\n"
        "                raise NotFound(f\"a model field needs a {label}\")",
        ("test_a_field_without_a_meaning_is_refused",),
    ),
    (
        TASKRUN,
        "a line nobody's model mentions is invented on demand",
        "        raise NotFound(\n"
        "            f\"{name!r} is not part of {self.model.name!r}. The model is what a \"",
        "        self.needs.append(Need(name=name, means=name))\n"
        "        return self.needs[-1]\n"
        "        raise NotFound(\n"
        "            f\"{name!r} is not part of {self.model.name!r}. The model is what a \"",
        ("test_a_line_not_in_the_model_is_not_part_of_this_statement",),
    ),

    # --- a value needs a source ---------------------------------------------
    (
        TASKRUN,
        "a figure may be filled in with no source",
        "        if not (source or \"\").strip():\n            raise NotFound(\n"
        "                f\"{self.name}: a value needs a source.",
        "        if False:\n            raise NotFound(\n"
        "                f\"{self.name}: a value needs a source.",
        ("test_a_value_with_no_source_is_refused",),
    ),
    (
        TASKRUN,
        "the source is taken and then not kept",
        "        self.source = source.strip()\n        self.state = FOUND",
        "        self.source = \"\"\n        self.state = FOUND",
        ("test_a_found_value_records_where_it_came_from",),
    ),
    (
        TASKRUN,
        "a need that can never be filled without a source gains a method that "
        "fills it without one",
        "    def ask(self, question: str, *, tried: str, of: str) -> Question:",
        "    def assume(self, value: str) -> \"Need\":\n"
        "        self.value = value\n"
        "        self.state = FOUND\n"
        "        return self\n\n"
        "    def ask(self, question: str, *, tried: str, of: str) -> Question:",
        ("test_there_is_no_method_that_fills_a_need_without_saying_where_from",),
    ),
    (
        TASKRUN,
        "`source` becomes optional, so a caller who forgets it is not stopped",
        "    def found(self, value: str, *, source: str) -> \"Need\":",
        "    def found(self, value: str, *, source: str = \"unknown\") -> \"Need\":",
        ("test_there_is_no_method_that_fills_a_need_without_saying_where_from",),
    ),

    # --- a question is answerable, and put to somebody -----------------------
    (
        TASKRUN,
        "a question need not say what was already tried, so it asks Krish to do "
        "the looking",
        "        if not (tried or \"\").strip():\n            raise NotFound(\n"
        "                f\"{self.name}: a question must say what was already tried, or \"",
        "        if False:\n            raise NotFound(\n"
        "                f\"{self.name}: a question must say what was already tried, or \"",
        ("test_a_question_must_say_what_was_already_tried",),
    ),
    (
        TASKRUN,
        "an empty question is asked",
        "        if not (question or \"\").strip():\n"
        "            raise NotFound(f\"{self.name}: ask what?\")",
        "        if False:\n"
        "            raise NotFound(f\"{self.name}: ask what?\")",
        ("test_a_question_with_nothing_in_it_is_refused",),
    ),
    (
        TASKRUN,
        "the work is asked of whoever the run hard-wires rather than whoever it "
        "is for",
        "        return self.need(name).ask(question, tried=tried, of=self.for_whom)",
        "        return self.need(name).ask(question, tried=tried, of=\"krish\")",
        ("test_a_run_for_somebody_else_puts_its_questions_to_them",),
    ),
    (
        TASKRUN,
        "Jarvis may put a question to himself",
        "        if _same(of, identity.AGENT_ID):\n            raise NotYours(",
        "        if False:\n            raise NotYours(",
        ("test_a_question_cannot_be_addressed_to_jarvis_himself",),
    ),
    (
        TASKRUN,
        "two spellings of the same name are two different people",
        "    return (one or \"\").strip().lower() == (other or \"\").strip().lower()",
        "    return (one or \"\") == (other or \"\")",
        ("test_a_question_cannot_be_addressed_to_jarvis_in_different_letters",),
    ),
    (
        TASKRUN,
        "a name with a space around it is a different person",
        "    return (one or \"\").strip().lower() == (other or \"\").strip().lower()",
        "    return (one or \"\").lower() == (other or \"\").lower()",
        ("test_a_question_cannot_be_addressed_to_jarvis_in_different_letters",),
    ),
    (
        TASKRUN,
        "the work can be for Jarvis, so its questions go to him",
        "        if _same(for_whom, identity.AGENT_ID):\n            raise NotYours(",
        "        if False:\n            raise NotYours(",
        ("test_a_task_cannot_be_for_jarvis",),
    ),

    # --- only the one who was asked may answer -------------------------------
    (
        TASKRUN,
        "anybody at all may answer a question put to Krish",
        "        if not _same(by, self.question.of):\n            raise NotYours(",
        "        if False:\n            raise NotYours(",
        ("test_jarvis_cannot_answer_his_own_question",
         "test_somebody_the_question_was_never_put_to_cannot_answer_it"),
    ),
    (
        TASKRUN,
        "the answer is checked against Jarvis rather than against the person "
        "asked, so a bystander's guess passes",
        "        if not _same(by, self.question.of):",
        "        if _same(by, identity.AGENT_ID):",
        ("test_somebody_the_question_was_never_put_to_cannot_answer_it",),
    ),
    (
        TASKRUN,
        "an answer to a question nobody asked fills the line",
        "        if self.question is None:\n"
        "            raise NotFound(f\"{self.name}: nothing was asked about this\")",
        "        if self.question is None:\n            return self",
        ("test_answering_something_nobody_asked_is_refused",),
    ),
    (
        TASKRUN,
        "an anonymous answer is accepted",
        "        if not (by or \"\").strip():\n"
        "            raise NotFound(f\"{self.name}: who answered?\")",
        "        if False:\n"
        "            raise NotFound(f\"{self.name}: who answered?\")",
        ("test_an_answer_needs_a_name_on_it",),
    ),
    (
        TASKRUN,
        "who answered is not written down",
        "        self.question.answered_by = by.strip()",
        "        self.question.answered_by = \"\"",
        ("test_krishs_answer_fills_the_need_and_says_he_said_it",),
    ),
    (
        TASKRUN,
        "Jarvis may decide a line is not needed",
        "        if _same(by, identity.AGENT_ID):\n            raise NotYours(\n"
        "                f\"{self.name}: {identity.AGENT_ID!r} cannot waive",
        "        if False:\n            raise NotYours(\n"
        "                f\"{self.name}: {identity.AGENT_ID!r} cannot waive",
        ("test_jarvis_cannot_leave_a_line_out_himself",),
    ),
    (
        TASKRUN,
        "a line may be left out with no reason given",
        "        if not (by or \"\").strip() or not (because or \"\").strip():",
        "        if not (by or \"\").strip():",
        ("test_waiving_a_line_needs_a_reason",),
    ),
    (
        TASKRUN,
        "waiving does not record whose decision it was",
        "        self.source = f\"{by.strip()} left it out: {because.strip()}\"",
        "        self.source = f\"left out: {because.strip()}\"",
        ("test_krish_may_leave_a_line_out_and_it_is_recorded_as_his",),
    ),

    # --- parking a question does not stop the work --------------------------
    (
        TASKRUN,
        "a line whose question is still open is worked on anyway",
        "            if one.settled or one.state == ASKED:\n                continue",
        "            if one.settled:\n                continue",
        ("test_the_rest_of_the_work_carries_on_while_a_question_waits",),
    ),
    (
        TASKRUN,
        "a line already filled is offered for work again",
        "            if one.settled or one.state == ASKED:\n                continue",
        "            if one.state == ASKED:\n                continue",
        ("test_a_line_already_filled_is_not_offered_again",),
    ),
    (
        TASKRUN,
        "what a line is waiting on is ignored, so the blocked work is attempted",
        "            if one.blocked_by is not None and not self.need(one.blocked_by).settled:\n"
        "                continue",
        "            if False:\n                continue",
        ("test_a_line_waiting_on_an_unanswered_one_is_not_attempted",),
    ),
    (
        TASKRUN,
        "a line waiting on an *asked* one is released before the answer comes",
        "            if one.blocked_by is not None and not self.need(one.blocked_by).settled:",
        "            if one.blocked_by is not None and self.need(one.blocked_by).state == UNMET:",
        ("test_a_line_waiting_on_an_unanswered_one_is_not_attempted",),
    ),
    (
        TASKRUN,
        "an answered blocker never releases the work behind it, so settling a "
        "question buys nothing",
        "            ready.append(one)",
        "            if one.blocked_by is None:\n                ready.append(one)",
        ("test_answering_the_blocker_releases_the_work_behind_it",),
    ),
    (
        TASKRUN,
        "a line may wait on itself",
        "        if one is other:\n"
        "            raise NotFound(f\"{name!r} cannot depend on itself\")",
        "        if False:\n"
        "            raise NotFound(f\"{name!r} cannot depend on itself\")",
        ("test_a_line_cannot_wait_on_itself",),
    ),
    (
        TASKRUN,
        "a loop of waiting is allowed, and the run stalls while looking busy",
        "            if walk.blocked_by == one.name:\n                raise NotFound(",
        "            if False:\n                raise NotFound(",
        ("test_a_loop_of_waiting_is_refused_when_it_is_closed",
         "test_a_loop_of_two_is_refused"),
    ),
    (
        TASKRUN,
        "only a loop of two is looked for, so a longer one gets through",
        "        walk = other\n        while walk.blocked_by is not None:",
        "        walk = other\n        if walk.blocked_by is not None:",
        ("test_a_loop_of_waiting_is_refused_when_it_is_closed",),
    ),
    (
        TASKRUN,
        "waiting on a line the model does not have is allowed",
        "        one, other = self.need(name), self.need(on)",
        "        one = self.need(name)\n"
        "        other = next((each for each in self.needs if each.name == on),\n"
        "                     Need(name=on, means=on))",
        ("test_waiting_on_a_line_that_is_not_in_the_model_is_refused",),
    ),

    # --- finishing is a claim, so it is checked ------------------------------
    (
        TASKRUN,
        "a statement finishes with a silent hole in it",
        "        missing = self.holes()\n        if missing:",
        "        missing = self.holes()\n        if False:",
        ("test_finishing_with_a_silent_hole_is_refused",),
    ),
    (
        TASKRUN,
        "an open question counts as a filled line, so the hole is never named",
        "        return [one for one in self.needs\n"
        "                if not one.settled and one.state != ASKED]",
        "        return []",
        ("test_finishing_with_a_silent_hole_is_refused",),
    ),
    (
        TASKRUN,
        "a line with a question open is reported as a hole rather than as "
        "waiting on Krish",
        "        return [one for one in self.needs\n"
        "                if not one.settled and one.state != ASKED]",
        "        return [one for one in self.needs if not one.settled]",
        ("test_finishing_while_a_question_is_open_says_it_is_waiting",),
    ),
    (
        TASKRUN,
        "the statement is called finished while Krish has not answered",
        "        waiting = self.open_questions()\n        if waiting:",
        "        waiting = self.open_questions()\n        if False:",
        ("test_finishing_while_a_question_is_open_says_it_is_waiting",),
    ),
    (
        TASKRUN,
        "an answered question is still counted as open, so nothing ever finishes",
        "        return [one.question for one in self.needs\n"
        "                if one.question is not None and one.question.open]",
        "        return [one.question for one in self.needs\n"
        "                if one.question is not None]",
        ("test_a_statement_finished_on_krishs_answers_is_finished",),
    ),
    (
        TASKRUN,
        "a line Krish left out is treated as still missing",
        "SETTLED = (FOUND, ANSWERED, WAIVED)",
        "SETTLED = (FOUND, ANSWERED)",
        ("test_a_waived_line_lets_the_statement_finish",),
    ),
    (
        TASKRUN,
        "an asked line counts as settled, so questions stop being holes at all",
        "SETTLED = (FOUND, ANSWERED, WAIVED)",
        "SETTLED = (FOUND, ANSWERED, WAIVED, ASKED)",
        ("test_every_state_a_need_can_be_in_is_either_settled_or_not",),
    ),
    (
        TASKRUN,
        "the refusal names the missing lines without saying what they are",
        "                + \", \".join(f\"{one.name} ({one.means})\" for one in missing)",
        "                + \", \".join(one.name for one in missing)",
        ("test_finishing_with_a_silent_hole_is_refused",),
    ),
    (
        TASKRUN,
        "a task with no goal is started",
        "        if not (goal or \"\").strip():\n            raise NotFound(\"a task needs a goal\")",
        "        if False:\n            raise NotFound(\"a task needs a goal\")",
        ("test_a_task_needs_a_goal",),
    ),

    # --- what a person and a caller see --------------------------------------
    (
        TASKRUN,
        "the report says where a figure came from only sometimes",
        "            \"settled\": [{\"name\": one.name, \"value\": one.value,\n"
        "                         \"source\": one.source}",
        "            \"settled\": [{\"name\": one.name, \"value\": one.value,\n"
        "                         \"source\": \"\"}",
        ("test_the_report_separates_what_is_done_from_what_is_asked_and_missing",),
    ),
    (
        TASKRUN,
        "the report does not say who a question is waiting on",
        "                           \"tried\": one.tried, \"of\": one.of}",
        "                           \"tried\": one.tried, \"of\": \"\"}",
        ("test_the_report_separates_what_is_done_from_what_is_asked_and_missing",),
    ),
    (
        TASKRUN,
        "a line whose blocker is long settled is still reported as blocked",
        "                        if one.blocked_by is not None\n"
        "                        and not self.need(one.blocked_by).settled],",
        "                        if one.blocked_by is not None],",
        ("test_a_blocked_line_stops_being_blocked_once_its_blocker_settles",),
    ),
    (
        TASKRUN,
        "the narration shows the question without the work behind it",
        "                lines.append(f\"        already tried: {one.question.tried}\")",
        "                lines.append(\"        already tried: several things\")",
        ("test_the_narration_shows_the_question_and_the_work_behind_it",),
    ),
    (
        TASKRUN,
        "the narration shows a figure without its source",
        "                lines.append(f\"  [x] {one.name}: {one.value}  - {one.source}\")",
        "                lines.append(f\"  [x] {one.name}: {one.value}\")",
        ("test_the_narration_shows_the_question_and_the_work_behind_it",),
    ),
    (
        TASKRUN,
        "the narration says nothing about what a line is waiting on",
        "                lines.append(f\"  [ ] {one.name}: waiting on {one.blocked_by}\")",
        "                lines.append(f\"  [ ] {one.name}: not yet\")",
        ("test_the_narration_shows_the_question_and_the_work_behind_it",),
    ),

    # --- a saved run is a claim like any other ------------------------------
    (
        TASKRUN,
        "a restored value with no source is given one",
        '            need.found(kept.get("value"), source=kept.get("source") or "")',
        '            need.found(kept.get("value"), source=kept.get("source") or "restored")',
        ("test_a_saved_value_with_no_source_is_refused_on_the_way_back",),
    ),
    (
        TASKRUN,
        "a value on a line that was never filled is restored quietly",
        '        elif state == UNMET and kept.get("value") is not None:',
        '        elif False:',
        ("test_a_saved_value_on_an_unfilled_line_is_refused",),
    ),
    (
        TASKRUN,
        "a restored answer is assigned rather than answered, so anybody's name "
        "is accepted on it",
        '                need.answered(asked["answer"], by=asked.get("answered_by") or "")',
        '                question.answer = asked["answer"]\n'
        '                question.answered_by = asked.get("answered_by") or ""\n'
        '                need.value = asked["answer"]\n'
        '                need.source = f"{question.answered_by} said so"\n'
        '                need.state = ANSWERED',
        ("test_a_saved_answer_from_somebody_else_is_refused_on_the_way_back",),
    ),
    (
        TASKRUN,
        "a waiver comes back with nobody's name on it",
        '            if not need.source:\n'
        '                raise NotFound(\n'
        '                    f"{need.name}: saved as left out with nobody\'s name on it")',
        '            if False:\n'
        '                raise NotFound(\n'
        '                    f"{need.name}: saved as left out with nobody\'s name on it")',
        ("test_a_saved_waiver_with_nobody_s_name_on_it_is_refused",),
    ),
    (
        TASKRUN,
        "a saved state the record cannot support is believed",
        '        if need.state != state:',
        '        if False:',
        ("test_a_saved_state_the_record_does_not_support_is_refused",),
    ),
    (
        TASKRUN,
        "anything shaped like a dict is restored as a run",
        '    if not isinstance(bundle, dict) or not bundle.get(MARKER):\n'
        '        raise NotFound("this is not a saved run")',
        '    if not isinstance(bundle, dict):\n'
        '        raise NotFound("this is not a saved run")',
        ("test_a_bundle_that_is_not_a_run_is_refused",),
    ),
    (
        TASKRUN,
        "a note saved by `record_task_state` is loaded as a run with nothing "
        "to do",
        '    if not isinstance(kept, dict) or not kept.get(MARKER):\n'
        '        return None\n'
        '    return restore({**kept, "key": key})',
        '    if not isinstance(kept, dict):\n'
        '        return None\n'
        '    return restore({**kept, MARKER: 1, "key": key})',
        ("test_a_note_saved_by_record_task_state_is_not_mistaken_for_a_run",),
    ),
    (
        TASKRUN,
        "`open_runs` hands back the notes as well",
        '        if isinstance(kept, dict) and kept.get(MARKER):\n'
        '            runs.append(restore({**kept, "key": row.get("name") or ""}))',
        '        if isinstance(kept, dict):\n'
        '            runs.append(restore({**kept, MARKER: 1, "key": row.get("name") or ""}))',
        ("test_a_note_saved_by_record_task_state_is_not_mistaken_for_a_run",),
    ),
    (
        TASKRUN,
        "what a line was waiting on is not restored",
        '            run.depends(need.name, on=kept["blocked_by"])',
        '            pass',
        ("test_a_restored_run_remembers_what_waits_on_what",),
    ),
    (
        TASKRUN,
        "the key comes from the clock, so every restart is a new run and the "
        "old one an orphan with Krish's answers in it",
        '        self.key = (key or "").strip() or _key_for(self.goal)',
        '        self.key = (key or "").strip() or f"run:{_now().isoformat()}"',
        ("test_a_run_has_a_stable_key_made_from_its_goal",),
    ),
    (
        TASKRUN,
        "why the work stopped is lost on the way back",
        '    run.paused_because = bundle.get("paused_because") or None',
        '    run.paused_because = None',
        ("test_the_shell_closing_pauses_a_saved_run_and_the_restore_says_so",),
    ),
    (
        TASKRUN,
        "a run is saved in a state the shell's pause does not look for",
        '            "state": RUNNING,',
        '            "state": "in_progress",',
        ("test_the_shell_closing_pauses_a_saved_run_and_the_restore_says_so",),
    ),
    (
        TASKRUN,
        "`describe` claims a restored value needs a source when it no longer "
        "checks",
        '        "restored_value_needs_a_source": True,',
        '        "restored_value_needs_a_source": False,',
        ("test_describe_says_what_this_module_refuses",),
    ),
    (
        TASKRUN,
        "`describe` claims a protection the module does not give",
        '        "model_carries_values": False,',
        '        "model_carries_values": True,',
        ("test_describe_says_what_this_module_refuses",),
    ),
    (
        TASKRUN,
        "`describe` says loops are refused when they are not",
        '        "dependency_loops": "refused",',
        '        "dependency_loops": "allowed",',
        ("test_describe_says_what_this_module_refuses",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
