"""T02 outbox-before-publish, T03 CAS conflict, T04 exhaustion, T05 duplicate/conflict,
T16 750 KiB pause, C2 detector control, and the local spool's CAS. GitHub is a fake client."""

from __future__ import annotations

import uuid

import pytest

from jarvis_voice.comm import canon, entry as entry_mod, ledger as ledger_mod, outbox as outbox_mod
from jarvis_voice.comm import plane as plane_mod, plane_github, plane_local, publisher as pub_mod
from tests.test_jarvis_comm_support import *  # noqa: F401,F403


@pytest.fixture
def world(tmp_path):
    clock = FakeClock()
    client = FakeGitHubClient(text="# legacy\n\nprose\n")
    plane = plane_github.GitHubPlane(client, path="coordination/cloud-claude-coordination.md")
    ob = outbox_mod.Outbox(tmp_path / "outbox")
    lg = ledger_mod.Ledger(tmp_path / "ledger.json")
    pub = pub_mod.Publisher(plane, ob, lg, sleep=clock.sleep, clock=clock)
    return clock, client, plane, ob, lg, pub


def _q(clock, **kw):
    return peer_entry(clock, type_="QUESTION", body="fixture question", from_=SELF["id"], epoch=SELF["epoch"], to=[PEER["id"]], **kw)


# ---------------------------------------------------------------- T02
def test_T02_outbox_holds_entry_when_response_is_lost_and_rerun_reconciles_without_second_append(world):
    clock, client, plane, ob, lg, pub = world
    e = _q(clock)
    client.lose_next_response = True
    r1 = pub.publish(e)
    assert r1.status == plane_mod.DELIVERY_UNKNOWN
    rec = ob.get(e["message_id"])
    assert rec["status"] == "unknown" and rec["sha256"] == canon.fingerprint(e)
    assert client.text.count("### " + e["message_id"]) == 1  # the server applied it once
    r2 = pub.publish(e)  # reconcile: GET finds the ID+hash, no second PUT
    assert r2.status == plane_mod.DELIVERED_VERIFIED
    assert client.put_calls == 1
    assert client.text.count("### " + e["message_id"]) == 1
    assert ob.get(e["message_id"])["status"] == "delivered"


def test_T02_outbox_is_written_before_the_first_network_call(world, monkeypatch):
    clock, client, plane, ob, lg, pub = world
    e = _q(clock)
    seen = {}

    real_get = client.get

    def spy_get(etag):
        seen["outbox_at_get"] = ob.get(e["message_id"])
        return real_get(etag)

    monkeypatch.setattr(client, "get", spy_get)
    pub.publish(e)
    assert seen["outbox_at_get"] is not None and seen["outbox_at_get"]["status"] == "staged"


# ---------------------------------------------------------------- T03 / T04
def test_T03_two_conflicts_then_success_lands_after_peer_entries_with_every_prior_byte_as_prefix(world):
    clock, client, plane, ob, lg, pub = world
    e = _q(clock)
    peer = peer_entry(clock, type_="PROGRESS", body="peer landed first")
    client.peer_appends = [entry_mod.render(peer)]
    client.conflicts_before_ok = 2  # two 409s (the peer append lands during the first PUT), third PUT succeeds
    before = client.text
    r = pub.publish(e)
    assert r.status == plane_mod.DELIVERED_VERIFIED
    assert r.attempts == 3
    assert client.text.startswith(before)
    assert client.text.index(peer["message_id"]) < client.text.index(e["message_id"])
    assert clock.sleeps == [1, 2]


def test_T04_three_conflicts_exhaust_with_visible_pending_conflict_and_no_fourth_attempt(world):
    clock, client, plane, ob, lg, pub = world
    e = _q(clock)
    client.conflicts_before_ok = 10
    r = pub.publish(e)
    assert r.status == plane_mod.CONFLICT and r.attempts == 3
    assert client.put_calls == 3
    assert ob.get(e["message_id"])["status"] == "pending_conflict"
    assert e["message_id"] not in client.text


# ---------------------------------------------------------------- T05
def test_T05_same_id_same_hash_reconciles_as_delivered(world):
    clock, client, plane, ob, lg, pub = world
    e = _q(clock)
    client.text += entry_mod.render(e)  # already there
    r = pub.publish(e)
    assert r.status == plane_mod.DELIVERED_VERIFIED and client.put_calls == 0


def test_T05_same_id_different_hash_is_a_conflict_not_applied(world):
    clock, client, plane, ob, lg, pub = world
    e = _q(clock)
    other = dict(e, body="different content, same id")
    client.text += entry_mod.render(other)
    r = pub.publish(e)
    assert r.status == plane_mod.CONFLICT and client.put_calls == 0
    assert "same message_id" in r.detail
    assert ob.get(e["message_id"])["status"] == "id_conflict"


# ---------------------------------------------------------------- C2 positive control
def test_control_C2_conflict_detector_fires_on_a_crafted_conflict(world):
    """The check can fail: a crafted conflicting entry makes the conflict path fire."""
    clock, client, plane, ob, lg, pub = world
    e = _q(clock)
    client.text += entry_mod.render(dict(e, body="crafted"))
    assert pub.publish(e).status == plane_mod.CONFLICT


# ---------------------------------------------------------------- T16
def test_T16_at_750KiB_publish_is_blocked_with_owner_decision_state(world):
    clock, client, plane, ob, lg, pub = world
    client.text = "x" * (750 * 1024)
    e = _q(clock)
    r = pub.publish(e)
    assert r.status == plane_mod.BLOCKED and "retention" in r.detail
    assert client.put_calls == 0
    assert ob.get(e["message_id"])["status"] == "blocked"


def test_T16_invalid_entry_is_refused_before_the_outbox(world):
    clock, client, plane, ob, lg, pub = world
    e = _q(clock)
    e["body"] = "ghp_" + "a" * 40
    r = pub.publish(e)
    assert r.status == plane_mod.BLOCKED and ob.get(e["message_id"]) is None and client.get_calls == 0


# ---------------------------------------------------------------- malformed history blocks the write
def test_malformed_R2_history_blocks_the_write(world):
    clock, client, plane, ob, lg, pub = world
    client.text += f"### {uuid.uuid4()}\n```json\n{{not json\n```\n"
    r = pub.publish(_q(clock))
    assert r.status == plane_mod.BLOCKED and "malformed" in r.detail and client.put_calls == 0


# ---------------------------------------------------------------- local spool CAS (same publisher, other plane)
def test_local_spool_publish_readback_and_stale_expectation_conflict(tmp_path):
    clock = FakeClock()
    spool = tmp_path / "spool.md"
    plane = plane_local.LocalSpoolPlane(spool)
    ob = outbox_mod.Outbox(tmp_path / "ob")
    lg = ledger_mod.Ledger(tmp_path / "lg.json")
    pub = pub_mod.Publisher(plane, ob, lg, sleep=clock.sleep, clock=clock)
    e = _q(clock)
    assert pub.publish(e).status == plane_mod.DELIVERED_VERIFIED
    assert spool.read_text(encoding="utf-8").count("### " + e["message_id"]) == 1
    # a stale expectation (someone appended in between) is a CONFLICT at the plane level
    cur = plane.fetch(None).cursor
    spool.write_text(spool.read_text(encoding="utf-8") + "\npeer bytes\n", encoding="utf-8")
    put = plane.put(cur, "would overwrite")
    assert put.status == plane_mod.PUT_CONFLICT
    assert "peer bytes" in spool.read_text(encoding="utf-8")
