"""The Strategic Priority Register (backend/register.py, addendum 31 §3/§5,
addendum 32 §12/§15; TQ-05). Fail-closed vocabulary, reasons on every parking
transition, a record reference on every completion, and a queue ordered by the
doctrine's own rules rather than a score.
"""

import pytest

from backend import register


def _file(conn, title, category="want", **kwargs):
    defaults = {"origin": "test", "rationale": "because"}
    defaults.update(kwargs)
    return register.file_entry(conn, title, category, **defaults)


def test_filing_stores_the_entry_queued(conn):
    entry_id = _file(conn, "Better roads", category="want", quick_win=True,
                     source_reference="addendum 31 §2.3")
    entry = register.get_entry(conn, entry_id)
    assert entry["status"] == "queued"
    assert entry["category"] == "want"
    assert entry["quick_win"] == 1
    assert entry["origin"] == "test"
    assert entry["source_reference"] == "addendum 31 §2.3"
    assert entry["need_flag"] is None


def test_a_want_cannot_carry_a_priority_flag(conn):
    """31 §2.2: a flag is an escalation property of necessity. Rejected, not
    silently dropped - a stored entry must mean what its filer said."""
    with pytest.raises(ValueError, match="want cannot carry one"):
        _file(conn, "Faster response", category="want", need_flag="red")


def test_vocabulary_is_fail_closed(conn):
    with pytest.raises(ValueError, match="category"):
        _file(conn, "Something", category="aspiration")
    with pytest.raises(ValueError, match="need_flag"):
        _file(conn, "Something", category="need", need_flag="purple")
    with pytest.raises(ValueError, match="requires a title"):
        _file(conn, "   ")
    with pytest.raises(ValueError, match="requires a title"):
        _file(conn, "Something", rationale="")


def test_duplicate_open_titles_are_consolidated_not_duplicated(conn):
    """31 §5.4. The refusal names the existing entry so the filer can go
    support it instead of splitting attention across two rows."""
    first = _file(conn, "Scaling wall", category="need", need_flag="orange")
    with pytest.raises(ValueError, match=f"id {first}"):
        _file(conn, "Scaling wall", category="need", need_flag="red")

    # A closed entry frees the title: re-raising a done concern is a new
    # proposal, not a duplicate of a finished one.
    register.set_status(conn, first, "done", record_reference="§99")
    assert _file(conn, "Scaling wall", category="need", need_flag="red") != first


def test_parking_transitions_require_reasons(conn):
    entry_id = _file(conn, "More compute")
    for status in ("blocked", "deferred", "declined"):
        with pytest.raises(ValueError, match="requires a reason"):
            register.set_status(conn, entry_id, status)
    register.set_status(conn, entry_id, "deferred", reason="no capacity this cycle")
    assert register.get_entry(conn, entry_id)["status_reason"] == "no capacity this cycle"


def test_done_requires_the_record_reference(conn):
    """G14: passing is not implementation. The reference is the pointer to
    where completion is recorded and verifiable."""
    entry_id = _file(conn, "More automation")
    with pytest.raises(ValueError, match="record_reference"):
        register.set_status(conn, entry_id, "done")
    register.set_status(conn, entry_id, "done", record_reference="SPEC_RECONCILIATION.md §54")
    assert register.get_entry(conn, entry_id)["record_reference"] == "SPEC_RECONCILIATION.md §54"


def test_transitioning_a_missing_entry_is_an_error(conn):
    with pytest.raises(ValueError, match="no register entry"):
        register.set_status(conn, 4242, "in_progress")


def test_queue_order_follows_the_doctrine_not_a_score(conn):
    """Needs before Wants; Needs by stated severity with unflagged below
    green (urgency someone stated outranks urgency nobody did); Quick-Win
    Wants before other Wants; filing order breaks ties. Closed and parked-
    for-good entries are not in the queue; blocked ones are - parked is not
    finished."""
    plain_want = _file(conn, "More model options")
    quick_want = _file(conn, "Rename a confusing constant", quick_win=True)
    green_need = _file(conn, "Backlog is growing", category="need", need_flag="green")
    unflagged_need = _file(conn, "Something feels off", category="need")
    red_need = _file(conn, "Provider obsolescence", category="need", need_flag="red")
    done = _file(conn, "Already handled")
    register.set_status(conn, done, "done", record_reference="§0")
    declined = _file(conn, "Not doing this")
    register.set_status(conn, declined, "declined", reason="want-based, no support")
    blocked_need = _file(conn, "Needs the forward leg", category="need", need_flag="yellow")
    register.set_status(conn, blocked_need, "blocked", reason="world has no futures")

    ordered = [entry["id"] for entry in register.queue_order(conn)]

    assert ordered == [red_need, blocked_need, green_need, unflagged_need,
                       quick_want, plain_want]


def test_list_register_validates_its_filter(conn):
    with pytest.raises(ValueError, match="status"):
        register.list_register(conn, status="everything")


def test_register_routes_file_read_and_order(panel_client):
    filed = panel_client.post("/admin/register", json={
        "title": "Improved user experience", "category": "want",
        "rationale": "addendum 31 §2.3's example want",
    })
    assert filed.status_code == 200
    assert filed.json()["entry"]["origin"] == "test-admin"

    need = panel_client.post("/admin/register", json={
        "title": "Unacceptable operating cost", "category": "need",
        "need_flag": "orange", "rationale": "31 §2.1's example need",
    })
    assert need.status_code == 200

    body = panel_client.get("/admin/register").json()
    assert len(body["entries"]) == 2
    # The queue view leads with the Need despite later filing.
    assert body["queue"] == [need.json()["id"], filed.json()["id"]]


def test_register_routes_surface_refusals_as_400(panel_client):
    response = panel_client.post("/admin/register", json={
        "title": "Faster everything", "category": "want",
        "need_flag": "red", "rationale": "speed",
    })
    assert response.status_code == 400
    assert "want cannot carry one" in response.json()["detail"]

    entry = panel_client.post("/admin/register", json={
        "title": "A real want", "category": "want", "rationale": "r",
    }).json()
    response = panel_client.post(f"/admin/register/{entry['id']}/status", json={"status": "declined"})
    assert response.status_code == 400
    assert "requires a reason" in response.json()["detail"]
