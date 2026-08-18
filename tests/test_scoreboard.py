"""The Project Scoreboard's own rules: what an item is, what it refuses, and the
order the board comes back in.

The ordering is tested rather than eyeballed because it *is* the routing policy
addendum 17 §6 puts on the Gateway - "the Gateway determines how the information
is presented according to severity". A sort that quietly degrades to insertion
order would still return every item and still look right in a screenshot.
"""

import pytest

from gateway import scoreboard


def test_a_filed_item_keeps_everything_it_was_given(gateway_conn):
    item_id = scoreboard.file_item(
        gateway_conn,
        source="super-user-conversation",
        question="Does the Gateway own retry policy, or the caller?",
        importance="important",
        blocking=True,
        related_spec="addendum 16 §11",
        related_component="gateway/streaming.py",
    )

    item = scoreboard.get_item(gateway_conn, item_id)
    assert item["question"] == "Does the Gateway own retry policy, or the caller?"
    assert item["importance"] == "important"
    assert item["blocking"] is True
    assert item["status"] == "open"
    assert item["related_spec"] == "addendum 16 §11"
    assert item["related_component"] == "gateway/streaming.py"
    assert item["source"] == "super-user-conversation"
    assert item["resolution"] is None
    assert item["notes"] == []


def test_importance_and_blocking_are_independent(gateway_conn):
    """§16 lists them separately and §17 turns on the difference: an urgent
    question can be non-blocking, and a trivial one can stop work. One field
    could not say both."""
    urgent_not_blocking = scoreboard.file_item(
        gateway_conn, source="s", question="TLS story for G2?", importance="urgent", blocking=False
    )
    trivial_blocker = scoreboard.file_item(
        gateway_conn, source="s", question="Which port?", importance="informational", blocking=True
    )

    assert scoreboard.get_item(gateway_conn, urgent_not_blocking)["blocking"] is False
    assert scoreboard.get_item(gateway_conn, trivial_blocker)["blocking"] is True


def test_an_item_needs_a_question_and_a_source(gateway_conn):
    with pytest.raises(scoreboard.ScoreboardError, match="question"):
        scoreboard.file_item(gateway_conn, source="s", question="   ")
    with pytest.raises(scoreboard.ScoreboardError, match="provenance"):
        scoreboard.file_item(gateway_conn, source="  ", question="a real question")


def test_an_unknown_importance_is_refused_with_the_options(gateway_conn):
    """The message is read by the model as a tool result, so it has to name the
    values rather than only reject the one given."""
    with pytest.raises(scoreboard.ScoreboardError) as refused:
        scoreboard.file_item(gateway_conn, source="s", question="q", importance="critical")

    for level in scoreboard.IMPORTANCE_LEVELS:
        assert level in str(refused.value)


def test_the_board_puts_open_before_resolved_then_severity_then_age(gateway_conn):
    informational = scoreboard.file_item(
        gateway_conn, source="s", question="informational, filed first", importance="informational"
    )
    older_urgent = scoreboard.file_item(
        gateway_conn, source="s", question="urgent, filed second", importance="urgent"
    )
    newer_urgent = scoreboard.file_item(
        gateway_conn, source="s", question="urgent, filed third", importance="urgent"
    )
    important = scoreboard.file_item(
        gateway_conn, source="s", question="important, filed fourth", importance="important"
    )
    resolved_urgent = scoreboard.file_item(
        gateway_conn, source="s", question="urgent but settled", importance="urgent"
    )
    scoreboard.resolve_item(gateway_conn, resolved_urgent, "decided: no")

    order = [item["id"] for item in scoreboard.list_items(gateway_conn)]

    assert order == [older_urgent, newer_urgent, important, informational, resolved_urgent], (
        "open before resolved, most severe first, and among equals the oldest "
        "first - the queue exists to stop things being forgotten, so age has to "
        "count against the newest rather than for it"
    )


def test_the_board_can_be_filtered(gateway_conn):
    urgent = scoreboard.file_item(gateway_conn, source="s", question="u", importance="urgent")
    informational = scoreboard.file_item(
        gateway_conn, source="s", question="i", importance="informational"
    )
    settled = scoreboard.file_item(gateway_conn, source="s", question="s", importance="urgent")
    scoreboard.resolve_item(gateway_conn, settled, "done")

    ids = lambda **kwargs: [item["id"] for item in scoreboard.list_items(gateway_conn, **kwargs)]

    assert ids(status="open") == [urgent, informational]
    assert ids(status="resolved") == [settled]
    # Both urgent items, the open one first - the filter narrows the board
    # without abandoning its order.
    assert ids(importance="urgent") == [urgent, settled]
    assert ids(status="open", importance="urgent") == [urgent]


def test_the_limit_is_applied_after_ordering(gateway_conn):
    """Otherwise a board with fifty informational items could push an urgent one
    off a limited view - the exact failure the ordering exists to prevent."""
    for index in range(5):
        scoreboard.file_item(
            gateway_conn, source="s", question=f"informational {index}", importance="informational"
        )
    urgent = scoreboard.file_item(
        gateway_conn, source="s", question="the urgent one, filed last", importance="urgent"
    )

    assert [item["id"] for item in scoreboard.list_items(gateway_conn, limit=1)] == [urgent]


def test_a_filter_it_does_not_understand_is_refused(gateway_conn):
    with pytest.raises(scoreboard.ScoreboardError):
        scoreboard.list_items(gateway_conn, status="pending")
    with pytest.raises(scoreboard.ScoreboardError):
        scoreboard.list_items(gateway_conn, importance="whenever")


def test_notes_accumulate_in_order_and_belong_to_their_item(gateway_conn):
    first = scoreboard.file_item(gateway_conn, source="s", question="first item")
    second = scoreboard.file_item(gateway_conn, source="s", question="second item")

    scoreboard.add_note(gateway_conn, first, author="super-user", note="one consideration")
    scoreboard.add_note(gateway_conn, first, author="assistant", note="and another")
    scoreboard.add_note(gateway_conn, second, author="super-user", note="unrelated")

    notes = scoreboard.get_item(gateway_conn, first)["notes"]
    assert [(note["author"], note["note"]) for note in notes] == [
        ("super-user", "one consideration"),
        ("assistant", "and another"),
    ]


def test_an_empty_note_or_a_missing_item_is_refused(gateway_conn):
    item_id = scoreboard.file_item(gateway_conn, source="s", question="q")

    with pytest.raises(scoreboard.ScoreboardError):
        scoreboard.add_note(gateway_conn, item_id, author="a", note="  ")
    with pytest.raises(scoreboard.ScoreboardError, match="No Scoreboard item"):
        scoreboard.add_note(gateway_conn, 9999, author="a", note="into the void")


def test_resolving_requires_saying_what_was_decided(gateway_conn):
    """The failure this guards against is the one the board exists to prevent: a
    question that stops being visible without anybody able to say what happened
    to it."""
    item_id = scoreboard.file_item(gateway_conn, source="s", question="q")

    with pytest.raises(scoreboard.ScoreboardError, match="what was decided"):
        scoreboard.resolve_item(gateway_conn, item_id, "   ")
    assert scoreboard.get_item(gateway_conn, item_id)["status"] == "open"


def test_resolving_records_the_decision_and_the_time(gateway_conn):
    item_id = scoreboard.file_item(gateway_conn, source="s", question="q")

    resolved = scoreboard.resolve_item(gateway_conn, item_id, "Use a tunnel; no forwarded port.")

    assert resolved["status"] == "resolved"
    assert resolved["resolution"] == "Use a tunnel; no forwarded port."
    assert resolved["resolved_at"] is not None


def test_resolving_twice_is_refused_rather_than_overwriting(gateway_conn):
    """A second attempt usually means somebody is working from a stale list, and
    the first resolution is the one that was actually decided."""
    item_id = scoreboard.file_item(gateway_conn, source="s", question="q")
    scoreboard.resolve_item(gateway_conn, item_id, "the real decision")

    with pytest.raises(scoreboard.ScoreboardError, match="already resolved"):
        scoreboard.resolve_item(gateway_conn, item_id, "a later, different decision")

    assert scoreboard.get_item(gateway_conn, item_id)["resolution"] == "the real decision"


def test_resolving_something_that_does_not_exist_says_so(gateway_conn):
    with pytest.raises(scoreboard.ScoreboardError, match="No Scoreboard item 4242"):
        scoreboard.resolve_item(gateway_conn, 4242, "whatever")


def test_open_counts_report_every_level_even_at_zero(gateway_conn):
    """A stable shape, so the header does not change layout as items are
    resolved."""
    assert scoreboard.open_counts(gateway_conn) == {
        "urgent": 0,
        "important": 0,
        "informational": 0,
    }

    scoreboard.file_item(gateway_conn, source="s", question="a", importance="urgent")
    scoreboard.file_item(gateway_conn, source="s", question="b", importance="urgent")
    settled = scoreboard.file_item(gateway_conn, source="s", question="c", importance="important")
    scoreboard.resolve_item(gateway_conn, settled, "done")

    assert scoreboard.open_counts(gateway_conn) == {
        "urgent": 2,
        "important": 0,
        "informational": 0,
    }


def test_getting_something_that_does_not_exist_returns_none(gateway_conn):
    assert scoreboard.get_item(gateway_conn, 1) is None
