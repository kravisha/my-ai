"""Mutations that `tests/test_console.py` must notice.

The failure to worry about here is quiet and looks like tidiness: a console that
falls back to Jarvis's identity when the operator's token is missing still works,
still writes verdicts, and has silently removed the only separation in the
scheme. Several of these probes are that, from different angles.

The other one is arithmetic dressed as kindness. Silence settled as `wrong`
rather than `not_now` teaches Jarvis to stop noticing, which is the opposite of
what a week of no reply actually means.

The third is the task questions. `reply` and `leave_out` go through
`taskrun.Need`'s own methods so that its refusals hold; a console that assigned
the fields instead would still work, still save, and would let Jarvis answer
his own question by typing it here.

Run it directly:

    python tests/probes/console_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

CONSOLE = "gateway/console.py"
TRUSTBOOK = "gateway/trustbook.py"
SUITES = {CONSOLE: TESTS / "test_console.py",
          TRUSTBOOK: TESTS / "test_console.py"}

PROBES: list[harness.Probe] = [
    # --- the console is Krish's -----------------------------------------------
    (
        CONSOLE,
        "a console with no operator token falls back to Jarvis",
        '    if transport is None and not (os.environ.get(TOKEN_ENV, "") or "").strip():',
        "    if False:",
        ("test_a_console_with_no_operator_token_refuses_to_run",),
    ),
    (
        CONSOLE,
        "the console speaks as Jarvis",
        "    return dbaclient.DBAClient(transport=transport, requested_by=OPERATOR,\n"
        "                               actor=OPERATOR)",
        "    return dbaclient.DBAClient(transport=transport)",
        ("test_krish_settles_a_guess_from_his_console",
         "test_a_domain_climbs_once_krish_starts_answering"),
    ),
    (
        CONSOLE,
        "`describe` claims a conversational yes settles a guess",
        '        "a_conversational_yes_settles_a_guess": False,',
        '        "a_conversational_yes_settles_a_guess": True,',
        ("test_a_conversational_yes_does_not_settle_a_guess",),
    ),
    # --- what Krish is shown ---------------------------------------------------
    (
        TRUSTBOOK,
        "everything noticed is put in front of Krish, including the quiet ones",
        '            if row.get("to_say") in (True, 1)',
        "            if True",
        ("test_only_the_guesses_the_ladder_allowed_are_shown",
         "test_a_guess_that_was_never_meant_to_be_said_does_not_lapse"),
    ),
    (
        TRUSTBOOK,
        "a mention already shown is shown again for ever",
        '            and not row.get("said_at")',
        "            and True",
        ("test_a_mention_already_shown_is_not_shown_again",),
    ),
    (
        TRUSTBOOK,
        "a mention already answered keeps coming back",
        "            and row[\"id\"] not in settled]",
        "            ]",
        ("test_a_mention_already_answered_is_not_shown_again",),
    ),
    (
        TRUSTBOOK,
        "saying something is recorded as a judgement rather than a fact",
        '    client.update(guess_id, {"said_at": _now_stamp()},',
        '    client.update(guess_id, {"said_at": None},',
        ("test_a_mention_already_shown_is_not_shown_again",),
    ),
    (
        TRUSTBOOK,
        "a guess is recorded without saying whether it may be spoken",
        '        "to_say": bool(to_say),',
        '        "to_say": False,',
        ("test_only_the_guesses_the_ladder_allowed_are_shown",),
    ),
    # --- answering -------------------------------------------------------------
    (
        CONSOLE,
        "the console loses the sentence and leans on the store's check",
        "    if outcome not in anticipation.OUTCOMES:",
        "    if False:",
        ("test_the_refusal_explains_why_not_now_is_worth_having",),
    ),
    (
        CONSOLE,
        "the refusal does not explain what not-now is for",
        '            f"noticing was right and the moment was wrong, which is a different "\n'
        '            f"instruction from \'stop noticing\'.")',
        '            f"pick one.")',
        ("test_the_refusal_explains_why_not_now_is_worth_having",),
    ),
    (
        CONSOLE,
        "the answer is attributed to whoever asked rather than to Krish",
        "    verdict = trustbook.settle(client, guess_id, outcome=outcome, settled_by=by,\n"
        "                               agent=agent)",
        '    verdict = trustbook.settle(client, guess_id, outcome=outcome,\n'
        '                               settled_by="jarvis", agent=agent)',
        ("test_krish_settles_a_guess_from_his_console",),
    ),
    # --- silence is not "wrong" ------------------------------------------------
    (
        CONSOLE,
        "silence is recorded as a wrong guess",
        "            trustbook.settle(client, row[\"id\"], outcome=anticipation.NOT_NOW,",
        "            trustbook.settle(client, row[\"id\"], outcome=anticipation.WRONG,",
        ("test_a_mention_krish_never_answered_lapses_to_not_now",),
    ),
    (
        CONSOLE,
        "a mention lapses the moment it is raised",
        "        if said is not None and said <= cutoff:",
        "        if said is not None:",
        ("test_a_mention_inside_the_window_is_left_alone",),
    ),
    (
        CONSOLE,
        "nothing ever lapses, so unanswered guesses age into wrong answers",
        "        if said is not None and said <= cutoff:",
        "        if False:",
        ("test_a_mention_krish_never_answered_lapses_to_not_now",),
    ),
    (
        CONSOLE,
        "the quiet window is measured from the wrong end",
        "    cutoff = when - timedelta(days=noticing.QUIET_DAYS)",
        "    cutoff = when + timedelta(days=noticing.QUIET_DAYS)",
        ("test_a_mention_inside_the_window_is_left_alone",),
    ),
    (
        CONSOLE,
        "a lapsed guess is not attributed to the silence",
        '                             settled_by="no answer", agent=agent)',
        '                             settled_by="krish", agent=agent)',
        ("test_a_mention_krish_never_answered_lapses_to_not_now",),
    ),
    # --- the questions a task parked -------------------------------------------
    (
        CONSOLE,
        "an answer is assigned rather than answered, so anybody may give it",
        "    run.need(about).answered(answer, by=by)",
        "    line = run.need(about)\n"
        "    line.question.answer = answer\n"
        "    line.question.answered_by = by\n"
        "    line.value = answer\n"
        "    line.source = f\"{by} said so\"\n"
        "    line.state = taskrun.ANSWERED",
        ("test_jarvis_cannot_use_the_console_to_answer_his_own_question",),
    ),
    (
        CONSOLE,
        "the answer is given and then not saved",
        '    taskrun.save(client, run, agent=agent,\n'
        '                 reason=f"{by} answered the question about {about!r}")',
        '    pass',
        ("test_krish_answers_a_task_question_from_his_console",),
    ),
    (
        CONSOLE,
        "a question already answered is put to Krish again",
        "        for one in run.open_questions():",
        "        for one in (line.question for line in run.needs\n"
        "                    if line.question is not None):",
        ("test_nothing_is_waiting_when_no_run_asked_anything",),
    ),
    (
        CONSOLE,
        "the newest question is put first, so the oldest waits longest",
        '    found.sort(key=lambda one: one["at"])',
        '    found.sort(key=lambda one: one["at"], reverse=True)',
        ("test_questions_from_every_run_are_listed_oldest_first",),
    ),
    (
        CONSOLE,
        "a line is left out by assignment, so Jarvis may leave one out",
        "    run.need(about).waive(by=by, because=because)",
        "    line = run.need(about)\n"
        "    line.state = taskrun.WAIVED\n"
        "    line.source = f\"{by} left it out: {because}\"",
        ("test_jarvis_cannot_leave_a_line_out_through_the_console",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
