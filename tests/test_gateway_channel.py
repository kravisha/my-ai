"""The channel between Jarvis and the Claude session on this machine.

Krish, 2026-09-16 12:03, by phone from abroad: *"I would like a more direct
communication channel between you and Jarvis. Perhaps he can be allowed to send
you messages on this channel but on the condition that he identifies himself as
Jarvis explicitly and so you can know."*

The condition is the thing worth a suite, and it is a property of the *file*
rather than of the model's manners. So these tests assert the header, and they
assert the two properties that make an unattended machine safe to leave with an
assistant that can write to disk: a rate ceiling and a size ceiling.

Three groups, and they fail for different reasons:

**The record says who spoke.** Every entry carries one of two speaker headers,
and neither of them is `KRISH-VIA-JARVIS`. That last one is not pedantry: it is
the header the gateway writes when Krish presses send, it is what wakes the
Claude session, and a machine able to produce it could wake an agent in his name.

**The channel cannot run away.** Rate and size are refused as data, so a model
that hits one reads a sentence and stops instead of the turn collapsing.

**The channel is not the other two files.** `KRISH-TO-CLAUDE-DEPLOY.md` wakes
this session and every line of it is attributed to Krish; the shared
`Arya-Claude` conversation is polled by size by another engineer's wake task. A
write that landed in either would be a bug with a blast radius outside this
repository, so it is asserted here rather than left to the path constant looking
right.
"""

from datetime import datetime, timedelta

import pytest

from gateway import conversation, devchannel, roles, tools


@pytest.fixture
def channel(tmp_path, monkeypatch):
    """The channel pointed at a tmp file. Every test in this module uses it.

    `devchannel.channel_path` resolves the environment per call precisely so this
    is possible; without the fixture a test run on this machine would append to
    the real channel, and the real channel is read by a scheduled task.
    """
    path = tmp_path / "JARVIS-CLAUDE-CHANNEL.md"
    monkeypatch.setenv("JARVIS_DEV_CHANNEL", str(path))
    return path


def claude_said(path, text, *, at=None):
    """Put a CLAUDE-DEPLOY-TO-JARVIS entry in the file, as the wake task would."""
    stamp = at or datetime.now().astimezone().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {stamp} | {devchannel.SPEAKER_CLAUDE}\n\n{text}\n")


def send(gateway_conn, text):
    """One `message_claude` call as the operator, through `tools.execute`.

    Through the dispatcher rather than calling `devchannel.append_message`
    directly, because the capability check and the refusal-as-data conversion are
    both in `execute` and both are part of what is being tested."""
    return tools.execute(gateway_conn, "message_claude", {"text": text},
                         role=roles.ROLE_OPERATOR)


# --- the record says who spoke ------------------------------------------------------


def test_a_sent_message_is_headed_as_coming_from_jarvis(channel, gateway_conn):
    """The condition Krish attached to the whole feature, asserted on the bytes."""
    outcome = send(gateway_conn, "The backend is refusing my login.")

    assert "error" not in outcome
    written = channel.read_text(encoding="utf-8")
    assert f"| {devchannel.SPEAKER_JARVIS}" in written
    assert "The backend is refusing my login." in written


def test_the_speaker_header_is_never_krishs(channel, gateway_conn):
    """`KRISH-VIA-JARVIS` is what the gateway writes when he presses send, and it
    is what wakes the Claude session. A machine able to write it could wake an
    agent under an attribution that had stopped being true."""
    send(gateway_conn, "anything at all")
    written = channel.read_text(encoding="utf-8")
    assert "KRISH" not in written
    assert "at Krish's direction" not in written


def test_the_two_speakers_are_distinguishable_in_the_file(channel, gateway_conn):
    """One parser reads this file, and it decides who spoke from the header alone.
    Two speakers sharing a header word would make the channel unreadable in the
    one direction that matters: Claude answering Jarvis."""
    claude_said(channel, "I have fixed the credential. Try again.")
    send(gateway_conn, "Still refusing.")

    entries = devchannel.parse_entries(channel.read_text(encoding="utf-8"))
    assert [entry["speaker"] for entry in entries] == [
        devchannel.SPEAKER_CLAUDE, devchannel.SPEAKER_JARVIS]
    assert devchannel.SPEAKER_JARVIS != devchannel.SPEAKER_CLAUDE


def test_an_entry_whose_body_contains_a_heading_survives(channel):
    """Bodies here quote logs, and a log line starting '## ' is not hypothetical.
    Splitting on '##' rather than on the header would cut a message in half and
    invent a speakerless entry."""
    claude_said(channel, "From the log:\n## 2026-09-16 restart\nthat is the line.")

    entries = devchannel.parse_entries(channel.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert "## 2026-09-16 restart" in entries[0]["text"]


def test_appending_never_rewrites_what_is_there(channel, gateway_conn):
    """Append-only, like the other two files, and for the same reason: this is the
    only account of what was said on a machine nobody is sitting at."""
    claude_said(channel, "first, from me")
    send(gateway_conn, "second, from him")
    send(gateway_conn, "third, from him")

    written = channel.read_text(encoding="utf-8")
    for expected in ("first, from me", "second, from him", "third, from him"):
        assert expected in written


# --- reading, which is the direction that did not exist -----------------------------


def test_reading_returns_claudes_messages(channel, gateway_conn):
    claude_said(channel, "The credential was empty. Fixed at 11:40.")

    outcome = tools.execute(gateway_conn, "read_claude", {}, role=roles.ROLE_OPERATOR)

    assert outcome["total"] == 1
    assert outcome["messages"][0]["text"] == "The credential was empty. Fixed at 11:40."
    assert outcome["messages"][0]["speaker"] == devchannel.SPEAKER_CLAUDE


def test_reading_does_not_return_jarviss_own_messages(channel, gateway_conn):
    """Otherwise the assistant reads its own report back as Claude's status and
    tells Krish that Claude said it - which is the exact failure the channel was
    built to end, in a new costume."""
    send(gateway_conn, "The backend is refusing my login.")

    outcome = tools.execute(gateway_conn, "read_claude", {}, role=roles.ROLE_OPERATOR)

    assert outcome["messages"] == []
    assert outcome["total"] == 0


def test_an_empty_channel_reads_as_empty_rather_than_failing(channel, gateway_conn):
    """Nothing written yet is a fact, not an error. A model handed an error here
    reports a broken channel to Krish on the day it is switched on."""
    outcome = tools.execute(gateway_conn, "read_claude", {}, role=roles.ROLE_OPERATOR)

    assert "error" not in outcome
    assert outcome["messages"] == []
    assert "not written anything" in outcome["note"]


def test_reading_a_file_that_does_not_exist_yet_is_not_an_error(channel, gateway_conn):
    assert not channel.exists()
    outcome = tools.execute(gateway_conn, "read_claude", {}, role=roles.ROLE_OPERATOR)
    assert "error" not in outcome


def test_reading_is_capped_and_newest_last(channel, gateway_conn):
    """Newest last, like /voice/inbox, because these are read in order and the
    last thing said is the current answer."""
    for index in range(30):
        claude_said(channel, f"message {index}")

    outcome = tools.execute(gateway_conn, "read_claude", {"limit": 500},
                            role=roles.ROLE_OPERATOR)

    assert len(outcome["messages"]) == 20
    assert outcome["messages"][-1]["text"] == "message 29"
    assert outcome["total"] == 30


def test_a_nonsense_limit_reads_rather_than_failing(channel, gateway_conn):
    claude_said(channel, "only one")
    for bad in ({"limit": 0}, {"limit": -5}, {"limit": "lots"}):
        outcome = tools.execute(gateway_conn, "read_claude", bad,
                                role=roles.ROLE_OPERATOR)
        assert "error" not in outcome, bad
        assert outcome["total"] == 1


# --- the channel cannot run away ----------------------------------------------------


def test_the_rate_limit_refuses_the_fourth_message_in_a_window(channel, gateway_conn):
    """This machine is unattended for a week and the wake task will poll this
    file. Without the ceiling, an assistant in a loop is both a disk filler and an
    unbounded generator of Claude sessions."""
    for index in range(devchannel.MAX_PER_WINDOW):
        assert "error" not in send(gateway_conn, f"report {index}")

    refused = send(gateway_conn, "one more")

    assert "error" in refused
    assert str(devchannel.MAX_PER_WINDOW) in refused["error"]
    assert "one more" not in channel.read_text(encoding="utf-8")


def test_the_rate_limit_is_a_window_and_not_a_total(channel, gateway_conn):
    """A ceiling that never resets would silence him after three messages for the
    whole week, which is a worse failure than the one it prevents."""
    old = (datetime.now().astimezone()
           - timedelta(minutes=devchannel.WINDOW_MINUTES + 1)
           ).isoformat(timespec="seconds")
    with channel.open("a", encoding="utf-8") as handle:
        for index in range(devchannel.MAX_PER_WINDOW):
            handle.write(f"\n## {old} | {devchannel.SPEAKER_JARVIS}\n\nold {index}\n")

    assert "error" not in send(gateway_conn, "a new one, the window has passed")


def test_claudes_own_messages_do_not_consume_the_rate(channel, gateway_conn):
    """The limit exists because Jarvis writing wakes Claude. Claude writing wakes
    nobody, so a busy reply from him must not spend the assistant's budget."""
    for index in range(10):
        claude_said(channel, f"from me {index}")

    assert "error" not in send(gateway_conn, "and one from him")


def test_an_undateable_entry_does_not_jam_the_channel_forever(channel, gateway_conn):
    """The conservative reading - refuse what cannot be dated - would let one
    hand-edited line silence the assistant permanently, with nobody on this
    machine able to clear it while Krish is abroad. The case the limit exists for
    is a loop, and a loop writes stamps this module generated itself."""
    with channel.open("a", encoding="utf-8") as handle:
        for index in range(devchannel.MAX_PER_WINDOW):
            handle.write(f"\n## sometime | {devchannel.SPEAKER_JARVIS}\n\nundated {index}\n")

    assert "error" not in send(gateway_conn, "still able to speak")


def test_a_message_past_the_size_ceiling_is_refused_before_it_is_written(
        channel, gateway_conn):
    refused = send(gateway_conn, "x" * (devchannel.MAX_CHARS + 1))

    assert "error" in refused
    assert str(devchannel.MAX_CHARS) in refused["error"]
    assert not channel.exists(), "a refused message was written anyway"


def test_a_message_at_the_size_ceiling_is_accepted(channel, gateway_conn):
    assert "error" not in send(gateway_conn, "x" * devchannel.MAX_CHARS)


def test_an_empty_message_is_refused_as_data(channel, gateway_conn):
    for empty in ("", "   ", "\n"):
        refused = send(gateway_conn, empty)
        assert "error" in refused
        assert "sent" not in refused


def test_a_missing_argument_is_refused_the_same_way(channel, gateway_conn):
    """`test_gateway_tools.test_every_declared_tool_is_dispatchable` calls every
    tool with no arguments. This is that call, asserted for what it says."""
    refused = tools.execute(gateway_conn, "message_claude", {},
                            role=roles.ROLE_OPERATOR)
    assert "error" in refused


def test_the_file_ceiling_stops_writes_rather_than_growing_unwatched(
        channel, gateway_conn, monkeypatch):
    """The rate limit bounds a loop; this bounds a year of honest use on a disk
    nobody is looking at. The refusal says who can clear it, because nothing on
    this machine deletes files by itself."""
    monkeypatch.setattr(devchannel, "MAX_FILE_BYTES", 200)
    claude_said(channel, "y" * 400)

    refused = send(gateway_conn, "a short one")

    assert "error" in refused
    assert "ceiling" in refused["error"]
    assert "a short one" not in channel.read_text(encoding="utf-8")


def test_a_missing_channel_directory_is_reported_and_not_created(
        tmp_path, monkeypatch, gateway_conn):
    """A path typo on a machine being set up should say so, not silently start a
    second channel nobody polls."""
    absent = tmp_path / "not-there" / "JARVIS-CLAUDE-CHANNEL.md"
    monkeypatch.setenv("JARVIS_DEV_CHANNEL", str(absent))

    refused = send(gateway_conn, "hello")

    assert "error" in refused
    assert not absent.parent.exists()


# --- the channel is not the other two files -----------------------------------------


def test_sending_does_not_touch_the_file_that_wakes_claude(
        channel, tmp_path, monkeypatch, gateway_conn):
    """`KRISH-TO-CLAUDE-DEPLOY.md` is polled by size by the scheduled task, and
    every entry in it is attributed to Krish's direction. A write here would wake
    a session in his name - which is the one thing this whole design exists to
    make impossible."""
    krish_channel = tmp_path / "KRISH-TO-CLAUDE-DEPLOY.md"
    krish_channel.write_text("# Krish -> Claude Deploy\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(krish_channel))
    before = krish_channel.read_text(encoding="utf-8")

    send(gateway_conn, "The backend is refusing my login.")

    assert krish_channel.read_text(encoding="utf-8") == before
    assert channel.exists()


def test_the_channel_defaults_beside_the_other_two_and_is_neither(channel):
    """The default path is what a machine with no configuration uses, so it has to
    be right without anybody checking. Sharing a filename with either of the
    other two would be a bug whose blast radius is another engineer's wake task."""
    default = devchannel.DEFAULT_PATH
    assert default.endswith("JARVIS-CLAUDE-CHANNEL.md")
    assert "Aria-Claude-Communications" in default
    assert "KRISH-TO-CLAUDE-DEPLOY" not in default
    assert "Ongoing Conversation" not in default


# --- what the model is told, and who is told it -------------------------------------


def test_both_tools_are_declared_and_dispatchable():
    assert {"message_claude", "read_claude"} <= tools.TOOL_NAMES


def test_the_channel_is_operator_only(gateway_conn, channel):
    """A client meets a representative with no business knowing an engineer
    session exists on this machine, let alone being able to write to it. Checked
    at the boundary as well as in the offered list, because a model can name a
    tool nobody offered it."""
    for name in ("message_claude", "read_claude"):
        assert tools.TOOL_CAPABILITY[name] == roles.CAP_PUBLISH
        assert tools.permitted(roles.ROLE_OPERATOR, name)
        assert not tools.permitted(roles.ROLE_CLIENT, name)
        assert not tools.permitted(roles.ROLE_INTERNAL, name)

        refused = tools.execute(gateway_conn, name, {"text": "sneaking in"},
                                role=roles.ROLE_CLIENT)
        assert "Not permitted" in refused["error"]
    assert not channel.exists(), "a refused client write reached the file"


def test_the_offered_tool_list_matches_the_boundary():
    offered = {tool["name"] for tool in tools.for_role(roles.ROLE_CLIENT)}
    assert "message_claude" not in offered
    assert "read_claude" not in offered
    operator = {tool["name"] for tool in tools.for_role(roles.ROLE_OPERATOR)}
    assert {"message_claude", "read_claude"} <= operator


def test_the_operator_prompt_describes_the_channel_and_its_real_limits():
    """Generated from the constants that enforce it. A prompt promising three
    messages a window against a module that allows two is a model being called a
    liar by its own tools."""
    prompt = conversation.operator_prompt()

    assert "message_claude" in prompt
    assert "read_claude" in prompt
    assert str(devchannel.MAX_PER_WINDOW) in prompt
    assert str(devchannel.WINDOW_MINUTES) in prompt
    assert devchannel.SPEAKER_JARVIS in prompt


def test_the_prompt_separates_the_channel_from_box_two():
    """These are the two acts the assistant will confuse if nobody separates
    them, and confusing them means telling Krish a message is sent when it is
    sitting in a box, or that it needs his tap when it has already gone."""
    paragraph = devchannel.prompt_paragraph()

    assert "Box 2" in paragraph
    assert "he presses send" in paragraph
    assert "no tap from anybody" in paragraph


def test_the_client_prompt_does_not_mention_the_channel():
    """The operator's page description is withheld from clients for this reason
    and the channel is more sensitive than the page: it carries what is broken on
    this machine."""
    prompt = conversation.client_prompt("Nadim", roles.ROLE_CLIENT)

    assert "message_claude" not in prompt
    assert "read_claude" not in prompt
    assert devchannel.SPEAKER_JARVIS not in prompt


def test_the_sent_note_does_not_claim_an_answer(channel, gateway_conn):
    """The model speaks from this string. "Claude has dealt with it" is the
    sentence here that would be a lie with a consequence: Krish would stop asking
    about a problem nobody had read yet."""
    outcome = send(gateway_conn, "The backend is refusing my login.")

    assert "sent" in outcome
    assert "minutes away" in outcome["note"]
    assert "not that he has answered" in outcome["note"]
