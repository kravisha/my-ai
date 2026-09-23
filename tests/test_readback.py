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

from datetime import datetime, timedelta, timezone

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
        proceed(mandate, email(), mandate.scope())


def test_a_call_that_omits_a_confirmed_particular_is_out_of_scope():
    """Krish, 2026-09-23: *"Confirmation licenses the exact action for which the
    permission was granted in the first place."*

    Set equality, not a subset check. The first version only compared the
    particulars a caller happened to pass, so passing none matched on the name
    alone - and the name is identical between sending one email and sending
    three."""
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    with pytest.raises(OutOfScope, match="does not state"):
        proceed(mandate, email(), {"to": "accounts@acme.example"})
    with pytest.raises(OutOfScope, match="does not state"):
        proceed(mandate, email())
    proceed(mandate, email(), mandate.scope())


def test_confirming_one_thing_is_not_confirming_the_next():
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    with pytest.raises(OutOfScope, match="is not what was confirmed"):
        proceed(mandate, email(name="delete_mailbox"))


def test_the_same_action_with_a_different_particular_is_out_of_scope():
    """Confirmed to send one email and sending three is the failure this exists
    for, and the action's name is identical in both."""
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    with pytest.raises(OutOfScope, match="was confirmed as"):
        proceed(mandate, email(), {**mandate.scope(),
                                   "to": "everyone@acme.example"})


def test_a_particular_added_after_the_fact_is_out_of_scope():
    mandate = confirm(understood(), confirmed_by="krish", agent=AGENT)
    with pytest.raises(OutOfScope, match="never part of what was confirmed"):
        proceed(mandate, email(), {**mandate.scope(),
                                   "bcc": "someone.else@example.com"})


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


# =============================================================================
# Wired into the tool loop
# =============================================================================
#
# Krish, 2026-09-23: *"Give him all the capabilities... the user will decide what
# help he needs."* A module with no caller is this repository's commonest
# failure, so these are the tests for the call site rather than the policy.


def test_a_consequential_tool_call_stops_and_reads_back(gateway_conn):
    from gateway import roles, tools
    result = tools.execute(
        gateway_conn, "publish_document",
        {"path": "docs/x.md", "content": "hello", "confirm_public": True},
        role=roles.ROLE_OPERATOR)
    read_back = result["needs_confirmation"]["read_back"]
    assert read_back[-1] == "Have I got that right?"
    assert any("content" in line for line in read_back)


def test_a_tool_argument_cannot_carry_a_persons_consent(gateway_conn):
    """The hole this closed. `confirm_public` is a boolean the *model* sets after
    relaying a proposal, so the thing being asked was answering on behalf of the
    person being asked. `confirmed_by` comes from the session instead - the same
    property `subject` already had, for a sharper reason."""
    from gateway import roles, tools
    arguments = {"path": "docs/x.md", "content": "hello", "confirm_public": True}
    assert "needs_confirmation" in tools.execute(
        gateway_conn, "publish_document", arguments, role=roles.ROLE_OPERATOR)
    assert "needs_confirmation" not in tools.execute(
        gateway_conn, "publish_document", arguments, role=roles.ROLE_OPERATOR,
        confirmed_by="krish")


def test_jarvis_naming_himself_as_the_confirmer_does_not_count(gateway_conn):
    from gateway import identity, roles, tools
    result = tools.execute(
        gateway_conn, "publish_document",
        {"path": "docs/x.md", "content": "hello", "confirm_public": True},
        role=roles.ROLE_OPERATOR, confirmed_by=identity.AGENT_ID)
    assert "needs_confirmation" in result


def test_the_gate_argument_is_what_makes_this_call_consequential(gateway_conn):
    """Not a second check to satisfy - the thing that changes the classification.

    Without `confirm_public`, `publish_document` writes to a local branch and
    pushes nothing, so it is recoverable and never reaches the read-back. With
    it, the destination is public and irreversible and it does. A first version
    of the wiring had a separate branch for "confirmed by a human but missing
    the tool's own flag", which no call can reach."""
    from gateway import tools
    private, _ = tools._risk_for("publish_document", {"path": "docs/x.md"})
    public, _ = tools._risk_for("publish_document", {"path": "docs/x.md",
                                                     "confirm_public": True})
    assert needs_readback(private)[0] is False
    assert needs_readback(public)[0] is True


def test_a_trivial_tool_call_never_asks(gateway_conn):
    from gateway import roles, tools
    result = tools.execute(gateway_conn, "machine_status", {},
                           role=roles.ROLE_OPERATOR)
    assert "needs_confirmation" not in result


def test_the_model_s_own_arguments_are_marked_as_its_own():
    """The default is `inferred`, because the model chose those values. A
    read-back that calls Jarvis's own choice "you said" confirms nothing."""
    from gateway import tools
    understanding = tools.understanding_for(
        "publish_document",
        {"repository": "public-notes", "title": "Q3", "body": "..."})
    by_label = {item.label: item.source for item in understanding.particulars}
    assert by_label["title"] == INFERRED
    assert by_label["body"] == INFERRED
    # The destination is the one thing Krish must have named himself.
    assert by_label["repository"] == TOLD


def test_a_new_tool_is_covered_without_anybody_listing_its_arguments():
    """Particulars are built from the arguments themselves, so a tool added
    tomorrow reads back tomorrow rather than when somebody remembers it."""
    from gateway import tools
    made = tools.particulars_for("a_tool_nobody_has_written",
                                 {"amount": "5000", "to": "someone"})
    assert {item.label for item in made} == {"amount", "to"}
    assert all(item.source == INFERRED for item in made)


def test_the_confirmation_flag_is_not_read_back_as_a_particular():
    """It says something about the call, not about what happens in the world,
    and six lines of machinery bury the three that matter."""
    from gateway import tools
    made = tools.particulars_for("publish_document",
                                 {"title": "Q3", "confirm_public": True})
    assert {item.label for item in made} == {"title"}


def test_empty_arguments_are_not_read_back():
    from gateway import tools
    made = tools.particulars_for("anything", {"title": "Q3", "cc": "", "bcc": None})
    assert {item.label for item in made} == {"title"}


# =============================================================================
# Across turns: the register
# =============================================================================
#
# A read-back is offered on one turn and answered on the next. Until this, the
# mandate was built and spent inside one call, so `Mandate.covers` was a check
# that could only pass. Here it can fail.


@pytest.fixture(autouse=True)
def _fresh_register():
    from gateway import readback as module, tools
    tools.REGISTER = module.Register()
    yield
    tools.REGISTER = module.Register()


def _register(at=None):
    from gateway import readback as module
    clock = at or (lambda: datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc))
    return module.Register(now=clock)


def test_an_answer_on_the_next_turn_licenses_the_call(gateway_conn):
    """The whole point of the register. Turn one proposes, turn two confirms,
    turn three acts - and nothing the model wrote carried the authority."""
    from gateway import roles, tools
    arguments = {"path": "docs/x.md", "content": "hello", "confirm_public": True}

    first = tools.execute(gateway_conn, "publish_document", arguments,
                          role=roles.ROLE_OPERATOR)
    assert "needs_confirmation" in first

    tools.confirm_pending(confirmed_by="krish")

    third = tools.execute(gateway_conn, "publish_document", arguments,
                          role=roles.ROLE_OPERATOR)
    assert "needs_confirmation" not in third


def test_a_call_whose_arguments_drifted_is_proposed_again(gateway_conn):
    """Where `covers` stops being a check that can only pass. Krish confirmed
    one document; the model comes back with a different one under the same
    name."""
    from gateway import roles, tools
    tools.execute(gateway_conn, "publish_document",
                  {"path": "docs/x.md", "content": "hello",
                   "confirm_public": True}, role=roles.ROLE_OPERATOR)
    tools.confirm_pending(confirmed_by="krish")

    again = tools.execute(gateway_conn, "publish_document",
                          {"path": "docs/x.md", "content": "something else",
                           "confirm_public": True}, role=roles.ROLE_OPERATOR)
    assert "needs_confirmation" in again


def test_yes_to_one_email_is_not_yes_to_four(gateway_conn):
    """*"Confirmation licenses the exact action"* - singular. A mandate that
    survived its own use would say otherwise."""
    from gateway import roles, tools
    arguments = {"path": "docs/x.md", "content": "hello", "confirm_public": True}
    tools.execute(gateway_conn, "publish_document", arguments,
                  role=roles.ROLE_OPERATOR)
    tools.confirm_pending(confirmed_by="krish")

    assert "needs_confirmation" not in tools.execute(
        gateway_conn, "publish_document", arguments, role=roles.ROLE_OPERATOR)
    assert "needs_confirmation" in tools.execute(
        gateway_conn, "publish_document", arguments, role=roles.ROLE_OPERATOR)


def test_the_model_never_handles_a_token(gateway_conn):
    """There is nothing for it to replay. The mandate is found by what the call
    *is*, and `confirm_pending` is a module function rather than a tool -
    a tool is something the model can call, and the point is that it cannot."""
    from gateway import tools
    assert "confirm_pending" not in {tool["name"] for tool in tools.TOOLS}
    assert "token" not in str(tools.execute.__doc__ or "")
    first = tools.execute(gateway_conn, "publish_document",
                          {"path": "docs/x.md", "content": "hello",
                           "confirm_public": True}, role="operator")
    assert "token" not in str(first["needs_confirmation"])


def test_answering_with_nothing_outstanding_is_refused():
    from gateway.readback import NotConfirmed as Refused
    register = _register()
    with pytest.raises(Refused, match="no read-back waiting"):
        register.answer(confirmed_by="krish", agent=AGENT)


def test_a_yes_into_a_room_with_two_questions_is_refused():
    register = _register()
    register.offer(understood(email("send_email")))
    register.offer(understood(email("wire_money")))
    with pytest.raises(NotConfirmed, match="more than one read-back"):
        register.answer(confirmed_by="krish", agent=AGENT)

    mandate = register.answer(confirmed_by="krish", agent=AGENT,
                              action_name="wire_money")
    assert mandate.understanding.action.name == "wire_money"


def test_re_proposing_the_same_action_replaces_the_earlier_ask():
    """So an answer cannot land on a question the user has stopped looking at."""
    register = _register()
    register.offer(understood())
    register.offer(understood(particulars=(
        Particular("to", "someone.else@acme.example", TOLD),)))
    assert len(register.outstanding()) == 1

    mandate = register.answer(confirmed_by="krish", agent=AGENT)
    assert mandate.scope() == {"to": "someone.else@acme.example"}


def test_an_unanswered_read_back_lapses():
    """A question nobody has answered in ten minutes has been overtaken by the
    conversation."""
    from gateway import readback as module
    now = [datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)]
    register = module.Register(now=lambda: now[0])
    register.offer(understood())
    assert register.outstanding()

    now[0] += timedelta(minutes=module.OFFER_MINUTES + 1)
    assert register.outstanding() == []
    with pytest.raises(NotConfirmed):
        register.answer(confirmed_by="krish", agent=AGENT)


def test_an_unused_confirmation_lapses():
    """A yes still lying around later is not consent to something happening
    now."""
    from gateway import readback as module
    now = [datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)]
    register = module.Register(now=lambda: now[0])
    register.offer(understood())
    register.answer(confirmed_by="krish", agent=AGENT)
    assert register.mandate_for(email(), {"to": "accounts@acme.example",
                                          "attachment": "Q3-statement.pdf",
                                          "subject": "Late invoice - Q3"})

    now[0] += timedelta(minutes=module.MANDATE_MINUTES + 1)
    assert register.mandate_for(email(), {"to": "accounts@acme.example",
                                          "attachment": "Q3-statement.pdf",
                                          "subject": "Late invoice - Q3"}) is None


def test_spending_a_confirmation_twice_says_it_was_already_used():
    """Different from "never here", and a different mistake with a different
    answer. Deleting spent entries on use lost that distinction and made
    `mandate_for`'s own check dead code."""
    register = _register()
    register.offer(understood())
    mandate = register.answer(confirmed_by="krish", agent=AGENT)
    register.spend(mandate)

    # A lookup in between, because that is what sweeps - and a sweep that threw
    # spent entries away would turn the second refusal below into "never in this
    # register", which sends the reader looking for a different bug.
    assert register.mandate_for(email(), mandate.scope()) is None
    with pytest.raises(NotConfirmed, match="already used"):
        register.spend(mandate)


def test_spending_something_that_was_never_offered_is_refused():
    from gateway.readback import Mandate as _Mandate
    register = _register()
    stranger = _Mandate(understanding=understood(), confirmed_by="krish")
    with pytest.raises(NotConfirmed, match="never in"):
        register.spend(stranger)


def test_the_register_still_refuses_a_self_confirmation():
    register = _register()
    register.offer(understood())
    with pytest.raises(NotConfirmed, match="cannot confirm its own"):
        register.answer(confirmed_by=AGENT, agent=AGENT)


def test_a_read_back_that_confirms_nothing_is_never_offered():
    register = _register()
    with pytest.raises(NotStated):
        register.offer(Understanding(action=email(), particulars=()))
    assert register.outstanding() == []


def test_describe_says_the_model_handles_no_token():
    assert readback.describe()["the_model_handles_no_token"] is True
    assert "once" in readback.describe()["a_confirmation_licenses"]


# =============================================================================
# The constitution says it, and something enforces it
# =============================================================================


def test_the_constitution_forbids_answering_for_the_user():
    """Krish, 2026-09-23: *"Please explicitly forbid this in the constitution."*

    Asserted here rather than left as prose, because this repository's whole
    doctrine is that a rule stated only in words is a rule that holds until the
    moment it matters. The section names the mechanisms; this test is the thing
    that notices if the section and the mechanisms stop agreeing."""
    from pathlib import Path

    # In the AMENDMENTS file, never in the constitution itself. Krish,
    # 2026-09-23: *"add only as amendment which means additional to the
    # constitution."* A first version wrote it straight into the constitution,
    # which is the one document nothing may edit.
    charter_text = Path("AI-CONSTITUTION-AMENDMENTS.md").read_text()
    assert "Never answer for the person you are asking" in charter_text
    assert "must never supply the permission it is asking for" in charter_text
    assert "Never answer for the person you are asking" not in \
        Path("AI-CONSTITUTION.md").read_text()
    # And the mechanisms it names still exist and still refuse.
    assert "gateway/readback.py" in charter_text
    assert "dba/permissions.py" in charter_text

    with pytest.raises(NotConfirmed):
        confirm(understood(), confirmed_by=AGENT, agent=AGENT)

    from dba import permissions
    assert permissions.OWNER_WRITTEN_TYPES
    assert permissions.ADMINISTER not in permissions.permissions_of(
        permissions.JARVIS)


def test_certainty_is_not_a_reason_to_skip_it():
    """*"An agent certain the user would say yes must still wait."* There is no
    argument, flag or confidence level that reaches past this."""
    import inspect as inspect_module

    parameters = inspect_module.signature(confirm).parameters
    assert "force" not in parameters
    assert "assume" not in parameters
    assert "confidence" not in parameters
    assert not [name for name, parameter in parameters.items()
                if isinstance(parameter.default, bool)]
