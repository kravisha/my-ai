"""The verifier that asks the questions a test cannot answer.

`desktop/verify.py` is interactive, so most of it looks untestable. Most of it
is not: what it asks, in what order, what it does with each answer and what it
writes down are all decisions, and they are the part that would be wrong.

Probed per Krish's rule - every behaviour was run against code with that
behaviour removed before the test was kept.
"""

import pytest

from desktop import verify


def _answers(*replies):
    """A prompt that returns each reply in turn, and raises if asked again."""
    queue = list(replies)

    def prompt(_question):
        if not queue:
            raise AssertionError("the verifier asked more questions than expected")
        return queue.pop(0)

    return prompt


def test_the_first_question_is_whether_he_can_get_out():
    """If Escape does not work he is looking at a fullscreen window he was told
    he could leave. Asking about legibility next would be asking him to review
    a screen he cannot get off."""
    assert verify.CHECKS[0].key == "escape"
    assert "Escape" in verify.CHECKS[0].do


def test_a_failed_escape_stops_the_rest():
    said = []
    answers = verify.run_checks(prompt=_answers("n", ""), say=said.append)

    assert len(answers) == 1, "it carried on after the way out had failed"
    assert answers[0].attested is False
    assert any("Alt+F4" in line for line in said)


def test_a_working_escape_carries_on():
    replies = []
    for _ in verify.CHECKS:
        replies.append("y")
    answers = verify.run_checks(prompt=_answers(*replies), say=lambda _: None)
    assert len(answers) == len(verify.CHECKS)
    assert all(answer.attested for answer in answers)


def test_a_no_explains_what_it_means_there_and_then():
    """Written in advance, because the moment somebody answers no is the moment
    they are tired and want to move on."""
    said = []
    verify.ask(verify.CHECKS[2], prompt=_answers("n", "the taskbar showed"),
               say=said.append)
    assert any(verify.CHECKS[2].if_no in line for line in said)


def test_a_note_is_kept_with_the_failure():
    answer = verify.ask(verify.CHECKS[2],
                        prompt=_answers("n", "the taskbar was still visible"),
                        say=lambda _: None)
    assert answer.note == "the taskbar was still visible"


def test_an_ambiguous_answer_is_asked_again_rather_than_guessed():
    """A verification that interprets an unclear answer is worth less than one
    that stops."""
    said = []
    answer = verify.ask(verify.CHECKS[0], prompt=_answers("maybe", "dunno", "y"),
                        say=said.append)
    assert answer.attested is True
    assert any("please answer" in line for line in said)


def test_skipping_is_recorded_as_neither_pass_nor_fail():
    answer = verify.ask(verify.CHECKS[0], prompt=_answers("s"), say=lambda _: None)
    assert answer.attested is None


def test_every_check_says_what_a_no_means():
    for check in verify.CHECKS:
        assert check.if_no and len(check.if_no) > 30, check.key
        assert check.do and check.ask.endswith("?"), check.key


def test_the_report_says_attested_and_never_passed():
    """Six months from now the difference between "the machine verified this"
    and "somebody said yes" is the difference between evidence and a memory."""
    answers = [verify.Answer(verify.CHECKS[0], True),
               verify.Answer(verify.CHECKS[1], False, "nothing happened"),
               verify.Answer(verify.CHECKS[2], None, "skipped")]

    text = verify.report(answers, when="2026-09-24T09:00:00+00:00")

    assert "ATTESTED" in text
    assert "human attested" in text
    assert "passed" not in text.lower().replace("not reached", "")
    assert "nothing happened" in text
    assert verify.CHECKS[1].if_no in text
    assert "1 attested, 1 failed, 1 skipped" in text
    assert f"{len(verify.CHECKS) - 3} not reached" in text


def test_the_report_counts_what_was_never_reached():
    """A run that stopped at the first question must not read as one that
    checked everything and found one problem."""
    text = verify.report([verify.Answer(verify.CHECKS[0], False)])
    assert f"{len(verify.CHECKS) - 1} not reached" in text


def test_the_report_is_written_where_he_can_find_it(tmp_path):
    path = verify.write_report("hello", directory=tmp_path)
    assert path.name == verify.REPORT_NAME
    assert path.read_text(encoding="utf-8") == "hello"


def test_the_checks_cover_each_rule_the_escape_hatch_promises():
    """The design makes five promises about Escape. A verifier that asked about
    three of them would leave two unverified and look complete."""
    keys = {check.key for check in verify.CHECKS}
    assert {"escape", "escape_default", "minimise", "exit_saves",
            "exit_leaves_desktop", "fullscreen"} <= keys
