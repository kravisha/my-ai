"""Saying back what was understood, before doing what cannot be undone.

Krish, 2026-09-23: *"the command that he cannot change is that user will decide
what help he needs from Jarvis and Jarvis should reiterate his understanding back
to the user for critical tasks that are important such as sending emails as
opposed to raising volume on the radio - the later shouldn't need a confirmation.
When user confirms Jarvis will act and complete execution."*

Four separable claims, and the tests are grouped by them. The one that carries
the most weight is the third: a read-back that reads back only what it was told
confirms nothing, because the error lives in what was inferred.

Probed by `tests/probes/readback_probes.py`.
"""

import pytest

from app import initiative
from gateway import readback
from gateway.readback import (DEFAULTED, INFERRED, TOLD, Mandate, NotConfirmed,
                              NotStated, OutOfScope, Particular, Understanding,
                              confirm, needs_readback, proceed)

AGENT = "jarvis"


def email(name="send_email"):
    """Krish's own example of the consequential end."""
    return initiative.Action(
        name=name, reversibility=initiative.IRREVERSIBLE,
        reach=initiative.PEER, summary="email the Acme accounts team")


def radio():
    """And of the trivial end."""
    return initiative.Action(
        name="set_volume", reversibility=initiative.REVERSIBLE,
        reach=initiative.SELF, summary="turn the radio up")


def understood(action=None, **kwargs):
    return Understanding(
        action=action or email(),
        particulars=kwargs.pop("particulars", (
            Particular("to", "accounts@acme.example", TOLD),
            Particular("attachment", "Q3-statement.pdf", TOLD),
            Particular("subject", "Late invoice - Q3", INFERRED))),
        **kwargs)


# --- 1. which actions need it, and who decides that ---------------------------

def test_sending_an_email_needs_the_read_back():
    required, why = needs_readback(email())
    assert required is True
    assert why


def test_turning_up_the_radio_does_not():
    """Requiring a confirmation for this would train the user to say yes without
    listening, which costs the confirmations that matter."""
    assert needs_readback(radio())[0] is False


def test_the_line_is_drawn_by_the_policy_that_already_owns_it():
    """Not by a list of verbs kept here. `app/initiative.py` ranks actions by
    reversibility and reach, so a new consequential action is covered without
    anybody remembering to add it."""
    unheard_of = initiative.Action(
        name="wire_the_money", reversibility=initiative.IRREVERSIBLE,
        reach=initiative.PUBLIC, summary="a verb nobody listed anywhere")
    assert needs_readback(unheard_of)[0] is True

    harmless = initiative.Action(
        name="also_unheard_of", reversibility=initiative.REVERSIBLE,
        reach=initiative.SELF, summary="likewise")
    assert needs_readback(harmless)[0] is False


def test_a_refused_action_has_nothing_to_confirm():
    """Offering a confirmation for something that will not happen either way is
    a question whose answer changes nothing."""
    forbidden = initiative.Action(
        name="widen_my_own_authority", reversibility=initiative.RECOVERABLE,
        reach=initiative.SELF, summary="edit the approval gate",
        harms=(initiative.HARM_WIDENS_ITS_OWN_AUTHORITY,))
    required, why = needs_readback(forbidden)
    assert required is False
    assert "refused outright" in why


# --- 2. the user decides; Jarvis cannot answer for him -------------------------

def test_jarvis_cannot_confirm_his_own_understanding():
    """*"The user will decide what help he needs from Jarvis."* Structural, not
    a rule Jarvis is asked to follow - a rule he is asked to follow is exactly
    what stops holding in the case it is for."""
    with pytest.raises(NotConfirmed) as raised:
        confirm(understood(), confirmed_by=AGENT, agent=AGENT)
    assert "cannot confirm its own" in str(raised.value)


def test_the_check_is_not_case_sensitive():
    with pytest.raises(NotConfirmed):
        confirm(understood(), confirmed_by="  JARVIS ", agent="jarvis")


def test_a_confirmation_must_say_who_gave_it():
    with pytest.raises(NotConfirmed, match="who gave it"):
        confirm(understood(), confirmed_by="   ", agent=AGENT)


def test_krish_can_confirm():
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    assert mandate.confirmed_by == "krish"
    assert mandate.scope()["to"] == "accounts@acme.example"


# --- 3. a read-back is particulars, and says which are Jarvis's ---------------

def test_a_read_back_with_no_particulars_is_refused():
    """"Shall I send the email?" catches nothing: the misunderstanding is never
    in the verb."""
    with pytest.raises(NotStated, match="catches nothing"):
        Understanding(action=email(), particulars=()).spoken()


def test_a_trivial_action_needs_no_particulars():
    assert Understanding(action=radio(), particulars=()).spoken()


def test_the_inferred_particulars_are_marked_in_place_and_counted():
    """The part that does the work. A person's ear catches "I worked that out"
    and skates over "you said"."""
    lines = "\n".join(understood().spoken())
    assert "subject: Late invoice - Q3 - I worked that out" in lines
    assert "accounts@acme.example - you said" in lines
    assert "1 of those is mine rather than yours: subject" in lines


def test_a_read_back_of_only_what_it_was_told_confirms_nothing_and_says_so():
    told_only = understood(particulars=(
        Particular("to", "accounts@acme.example", TOLD),))
    lines = "\n".join(told_only.spoken())
    assert "mine rather than yours" not in lines


def test_a_defaulted_particular_reads_as_a_convention_not_a_fact():
    """Three sources, not two: "nobody said" and "I worked it out" invite
    different corrections."""
    lines = "\n".join(understood(particulars=(
        Particular("send_at", "now", DEFAULTED),)).spoken())
    assert "nobody said, so I used the usual" in lines
    assert "mine rather than yours" in lines


def test_an_unlabelled_particular_is_refused():
    """An unlabelled value cannot be corrected, because nobody knows what it is."""
    with pytest.raises(NotStated, match="needs a label"):
        Particular("  ", "something", TOLD)


def test_the_sources_are_a_closed_set():
    with pytest.raises(NotStated, match="is not one of"):
        Particular("to", "somebody", "probably")


def test_the_read_back_ends_by_asking():
    assert understood().spoken()[-1] == "Have I got that right?"


# --- corrections return to the read-back ---------------------------------------

def test_a_correction_becomes_something_krish_said():
    revised = understood().corrected("subject", "Q3 invoice query")
    subject = next(item for item in revised.particulars if item.label == "subject")
    assert subject.value == "Q3 invoice query"
    assert subject.source == TOLD


def test_a_correction_is_said_back_again_rather_than_acted_on():
    """The thing being corrected is the evidence that the understanding was
    wrong, and a wrong understanding corrected once is not obviously right."""
    revised = understood().corrected("to", "ap@acme.example")
    assert needs_readback(revised.action)[0] is True
    with pytest.raises(NotConfirmed):
        proceed(None, revised.action)


def test_a_correction_can_add_something_nobody_had_mentioned():
    """"Also copy me" is a correction, not a new request."""
    revised = understood().corrected("cc", "krish@example.com")
    added = next(item for item in revised.particulars if item.label == "cc")
    assert added.value == "krish@example.com" and added.source == TOLD
    assert len(revised.particulars) == len(understood().particulars) + 1


def test_correcting_an_unknown_resolves_it():
    with_unknown = understood(unknowns=("which quarter",))
    assert with_unknown.corrected("which quarter", "Q3").unknowns == ()


# --- unknowns ------------------------------------------------------------------

def test_an_unresolved_unknown_blocks_confirmation():
    with pytest.raises(NotStated, match="were not resolved"):
        confirm(understood(unknowns=("which quarter", "which address")),
                confirmed_by="krish", agent=AGENT)


def test_each_unknown_must_be_named_to_proceed_without_it():
    """A single flag waving away five unknowns costs the same as waving away
    one."""
    understanding = understood(unknowns=("which quarter", "which address"))
    with pytest.raises(NotStated, match="which address"):
        confirm(understanding, confirmed_by="krish", agent=AGENT,
                accepting_unknowns=["which quarter"])

    mandate = confirm(understanding, confirmed_by="krish", agent=AGENT,
                      accepting_unknowns=["which quarter", "which address"])
    assert mandate.accepted_unknowns == ("which address", "which quarter")


def test_accepting_an_unknown_nobody_raised_is_refused():
    with pytest.raises(NotStated, match="nobody raised"):
        confirm(understood(), confirmed_by="krish", agent=AGENT,
                accepting_unknowns=["which quarter"])


def test_unknowns_are_read_out():
    lines = "\n".join(understood(unknowns=("which quarter",)).spoken())
    assert "I could not work out: which quarter" in lines


# --- 4. on confirmation, act and complete --------------------------------------

def test_a_trivial_action_proceeds_with_no_mandate_at_all():
    proceed(None, radio())


def test_a_consequential_action_without_confirmation_is_refused():
    with pytest.raises(NotConfirmed, match="needs the user's confirmation"):
        proceed(None, email())


def test_a_confirmed_action_proceeds_without_asking_again():
    """*"When user confirms Jarvis will act and complete execution."* Re-asking
    halfway is not caution, it is nagging, and it is what makes a person stop
    granting anything."""
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    for _ in range(5):
        proceed(mandate, email(), {"to": "accounts@acme.example"})


def test_confirming_one_thing_is_not_confirming_the_next():
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    with pytest.raises(OutOfScope, match="is not what was confirmed"):
        proceed(mandate, email(name="delete_mailbox"))


def test_the_same_action_with_a_different_particular_is_out_of_scope():
    """Confirmed to send one email and sending three is the failure this exists
    for, and the action's name is identical in both."""
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    with pytest.raises(OutOfScope, match="was confirmed as"):
        proceed(mandate, email(), {"to": "everyone@acme.example"})


def test_a_particular_added_after_the_fact_is_out_of_scope():
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    with pytest.raises(OutOfScope, match="never part of what was confirmed"):
        proceed(mandate, email(), {"bcc": "someone.else@example.com"})


def test_the_mandate_records_what_was_agreed():
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    assert mandate.scope() == {
        "to": "accounts@acme.example",
        "attachment": "Q3-statement.pdf",
        "subject": "Late invoice - Q3"}
    assert mandate.at and mandate.understanding.action.name == "send_email"


def test_a_mandate_cannot_be_edited_into_a_wider_one():
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    with pytest.raises(Exception):
        mandate.confirmed_by = "jarvis"


def test_describe_says_what_a_confirmation_licenses():
    described = readback.describe()
    assert described["self_confirmation"] == "refused"
    assert described["decided_by"] == "app/initiative.py"
    assert described["trivial_actions_need_confirmation"] is False
