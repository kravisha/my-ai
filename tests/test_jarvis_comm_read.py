"""T06 304/unchanged, T07 own publication never advances the read cursor, T08 malformed retained,
sequence gaps retained, duplicate/conflict on read."""

from __future__ import annotations

import pytest

from jarvis_voice.comm import entry as entry_mod, ledger as ledger_mod, outbox as outbox_mod
from jarvis_voice.comm import plane_github, publisher as pub_mod, reader as reader_mod
from tests.test_jarvis_comm_support import *  # noqa: F401,F403


@pytest.fixture
def world(tmp_path):
    clock = FakeClock()
    client = FakeGitHubClient(text="# legacy\n")
    plane = plane_github.GitHubPlane(client, path="coordination/cloud-claude-coordination.md")
    ob = outbox_mod.Outbox(tmp_path / "ob")
    lg = ledger_mod.Ledger(tmp_path / "lg.json")
    pub = pub_mod.Publisher(plane, ob, lg, sleep=clock.sleep, clock=clock)
    rd = reader_mod.Reader(plane, lg, self_id=SELF["id"], clock=clock)
    return clock, client, plane, ob, lg, pub, rd


def test_T06_304_is_unchanged_cursor_and_obligations_untouched(world):
    clock, client, plane, ob, lg, pub, rd = world
    q = peer_entry(clock, type_="QUESTION", body="q1")
    client.text += entry_mod.render(q)
    r1 = rd.read()
    assert r1.status == "changed" and [e["message_id"] for e in r1.new_entries] == [q["message_id"]]
    assert lg.pending_unread() == [q["message_id"]]
    cursor_after = lg.cursor()
    r2 = rd.read()
    assert r2.status == "unchanged" and r2.new_entries == []
    assert lg.cursor() == cursor_after
    assert lg.pending_unread() == [q["message_id"]]  # a 304 clears nothing


def test_T07_own_publication_does_not_advance_the_read_cursor_past_unseen_peer_entries(world):
    clock, client, plane, ob, lg, pub, rd = world
    peer_q = peer_entry(clock, type_="QUESTION", body="arrived while we were writing")
    client.peer_appends = [entry_mod.render(peer_q)]
    mine = peer_entry(clock, type_="PROGRESS", body="mine", from_=SELF["id"], epoch=SELF["epoch"], to=[PEER["id"]])
    r = pub.publish(mine)
    assert r.status.startswith("delivered")
    # The publisher read the file (GET + readback) and saw the peer entry, but reading is not consuming.
    assert peer_q["message_id"] not in lg.accounted_ids()
    rr = rd.read()
    ids = [e["message_id"] for e in rr.new_entries]
    assert ids == [peer_q["message_id"]]           # the peer entry is delivered to the reader once
    assert mine["message_id"] not in ids           # my own entry is never "new" to me
    assert mine["message_id"] in lg.own_ids()


def test_read_dedups_and_flags_same_id_different_content_as_conflict(world):
    clock, client, plane, ob, lg, pub, rd = world
    q = peer_entry(clock, type_="QUESTION", body="q1")
    client.text += entry_mod.render(q) + entry_mod.render(q)  # exact duplicate
    r = rd.read()
    assert [e["message_id"] for e in r.new_entries] == [q["message_id"]]
    client.text += entry_mod.render(dict(q, body="q1 altered"))
    r2 = rd.read()
    assert r2.new_entries == []
    assert [c["message_id"] for c in r2.conflicts] == [q["message_id"]]
    assert lg.conflicts()[0]["message_id"] == q["message_id"]


def test_T08_malformed_is_retained_in_ledger_and_not_returned_as_input(world):
    clock, client, plane, ob, lg, pub, rd = world
    client.text += "### 11111111-1111-4111-8111-111111111111\n```json\n{\"type\": \"TASK_ASSIGN\", oops\n```\n"
    r = rd.read()
    assert r.new_entries == [] and len(r.malformed) == 1
    assert lg.malformed()[0]["heading_id"] == "11111111-1111-4111-8111-111111111111"


def test_sequence_gaps_are_retained_not_filled(world):
    clock, client, plane, ob, lg, pub, rd = world
    conv = "22222222-2222-4222-8222-222222222222"
    a = peer_entry(clock, type_="PROGRESS", body="s1", conversation_id=conv, sequence=1)
    c = peer_entry(clock, type_="PROGRESS", body="s3", conversation_id=conv, sequence=3)
    client.text += entry_mod.render(a) + entry_mod.render(c)
    r = rd.read()
    assert r.gaps == [{"from": PEER["id"], "session_id": PEER["session"], "conversation_id": conv, "missing": [2]}]
    assert lg.gaps() == r.gaps
    assert [e["message_id"] for e in r.new_entries] == [a["message_id"], c["message_id"]]


def test_ack_records_read_time_and_clears_pending(world):
    clock, client, plane, ob, lg, pub, rd = world
    q = peer_entry(clock, type_="QUESTION", body="q1")
    client.text += entry_mod.render(q)
    rd.read()
    rd.ack([q["message_id"]])
    assert lg.pending_unread() == []
    assert lg.receipts()[q["message_id"]]["read_at"] == clock.iso()
    with pytest.raises(KeyError):
        rd.ack(["not-a-seen-id"])  # unread ids are never blanket-acknowledged
