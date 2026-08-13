"""Unit tests for backend/transcripts.py's TranscriptStore - the in-memory
per-user conversation log the server monitor (monitor/app.py) polls."""

from datetime import datetime

from backend.transcripts import TranscriptStore


def test_list_clients_starts_empty():
    store = TranscriptStore()
    assert store.list_clients() == []


def test_get_transcript_for_unknown_user_returns_empty_list():
    store = TranscriptStore()
    assert store.get_transcript("alice") == []


def test_record_adds_an_entry_and_lists_the_client():
    store = TranscriptStore()
    store.record("alice", "user", "hi")
    assert store.list_clients() == ["alice"]
    entries = store.get_transcript("alice")
    assert len(entries) == 1
    assert entries[0]["role"] == "user"
    assert entries[0]["text"] == "hi"


def test_record_timestamp_is_parseable_iso():
    store = TranscriptStore()
    store.record("alice", "user", "hi")
    datetime.fromisoformat(store.get_transcript("alice")[0]["timestamp"])


def test_multiple_records_append_in_order():
    store = TranscriptStore()
    store.record("alice", "user", "What stocks do I own?")
    store.record("alice", "assistant", "Here's your portfolio...")
    entries = store.get_transcript("alice")
    assert [e["role"] for e in entries] == ["user", "assistant"]
    assert [e["text"] for e in entries] == ["What stocks do I own?", "Here's your portfolio..."]


def test_two_users_transcripts_are_isolated():
    store = TranscriptStore()
    store.record("alice", "user", "alice's question")
    store.record("bob", "user", "bob's question")

    assert [e["text"] for e in store.get_transcript("alice")] == ["alice's question"]
    assert [e["text"] for e in store.get_transcript("bob")] == ["bob's question"]
    assert store.list_clients() == ["alice", "bob"]


def test_list_clients_is_sorted():
    store = TranscriptStore()
    store.record("zoe", "user", "hi")
    store.record("alice", "user", "hi")
    assert store.list_clients() == ["alice", "zoe"]
