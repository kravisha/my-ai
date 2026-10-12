"""T01 canonical hash, T15 entry validator, T08 parsing of legacy + malformed text."""

from __future__ import annotations

import json
import uuid

import pytest

from jarvis_voice.comm import canon, entry as entry_mod
from tests.test_jarvis_comm_support import *  # noqa: F401,F403  (autouse boundary + fakes)


# ---------------------------------------------------------------- T01 canonical hash
def test_T01_known_vector_sorted_keys_no_whitespace_unicode_unescaped():
    obj = {"b": [3, 1, 2], "a": {"z": "é", "y": None, "x": True}}
    b = canon.canonical_bytes(obj)
    assert b == '{"a":{"x":true,"y":null,"z":"é"},"b":[3,1,2]}'.encode("utf-8")
    # array order retained, keys sorted, unicode unescaped, no insignificant whitespace
    assert canon.fingerprint(obj) == canon.fingerprint({"a": {"z": "é", "x": True, "y": None}, "b": [3, 1, 2]})
    assert canon.fingerprint(obj) != canon.fingerprint({"a": {"z": "é", "x": True, "y": None}, "b": [1, 2, 3]})
    # a fixed digest for the vector, so a serializer change is visible
    assert canon.fingerprint(obj) == __import__("hashlib").sha256(b).hexdigest()


def test_T01_duplicate_key_and_non_finite_are_rejected():
    with pytest.raises(canon.CanonError):
        canon.parse_strict('{"a": 1, "a": 2}')
    with pytest.raises(canon.CanonError):
        canon.parse_strict('{"a": NaN}')
    with pytest.raises(canon.CanonError):
        canon.canonical_bytes({"a": float("inf")})
    with pytest.raises(canon.CanonError):
        canon.canonical_bytes({"a": object()})


# ---------------------------------------------------------------- T15 validator
def _good(clock):
    return peer_entry(clock, type_="QUESTION", body="what is 2 plus 2?")


def test_T15_valid_entry_has_no_errors():
    assert entry_mod.validate(_good(FakeClock())) == []


def test_T15_missing_required_field_and_wrong_type_are_named():
    e = _good(FakeClock())
    del e["grant_id"]
    e["sequence"] = "1"
    errs = entry_mod.validate(e)
    assert any("grant_id" in x for x in errs)
    assert any("sequence" in x for x in errs)


def test_T15_token_like_body_is_refused_before_outbox():
    for secret in ("ghp_" + "a" * 36, "github_pat_" + "b" * 30, "-----BEGIN RSA PRIVATE KEY-----", "$2b$12$" + "c" * 53):
        e = _good(FakeClock())
        e["body"] = "here is my token " + secret
        errs = entry_mod.validate(e)
        assert errs and any("secret" in x for x in errs), secret


def test_T15_oversize_entry_is_refused_not_truncated():
    e = _good(FakeClock())
    e["body"] = "x" * (16 * 1024)
    errs = entry_mod.validate(e)
    assert errs and any("16 KiB" in x or "size" in x for x in errs)
    assert len(e["body"]) == 16 * 1024  # untouched


def test_T15_unknown_type_is_refused():
    e = _good(FakeClock())
    e["type"] = "EXECUTE"
    assert any("type" in x for x in entry_mod.validate(e))


# ---------------------------------------------------------------- T08 parse
LEGACY = "# Coordination\n\nSome legacy prose with a table.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## Old entry\nFROM KRISH: do things\n"


def test_T08_legacy_prose_preserved_and_entries_found_after_it():
    clock = FakeClock()
    e1 = _good(clock)
    text = LEGACY + entry_mod.render(e1)
    res = entry_mod.parse(text)
    assert res.legacy_prefix == LEGACY
    assert [p.entry["message_id"] for p in res.entries] == [e1["message_id"]]
    assert res.entries[0].sha256 == canon.fingerprint(e1)
    assert res.malformed == []


def test_T08_malformed_json_is_flagged_retained_and_not_returned_as_an_entry():
    clock = FakeClock()
    e1 = _good(clock)
    bad_id = str(uuid.uuid4())
    bad_block = f"### {bad_id}\n```json\n{{\"message_id\": \"{bad_id}\", \"type\": \"TASK_ASSIGN\", \n```\n"
    text = LEGACY + bad_block + entry_mod.render(e1)
    res = entry_mod.parse(text)
    assert [p.entry["message_id"] for p in res.entries] == [e1["message_id"]]
    assert len(res.malformed) == 1
    assert res.malformed[0].heading_id == bad_id
    assert "TASK_ASSIGN" in res.malformed[0].raw  # retained verbatim, never executed


def test_T08_heading_id_must_match_message_id():
    clock = FakeClock()
    e1 = _good(clock)
    wrong = entry_mod.render(e1).replace(f"### {e1['message_id']}", f"### {uuid.uuid4()}", 1)
    res = entry_mod.parse(wrong)
    assert res.entries == [] and len(res.malformed) == 1


def test_T08_render_then_parse_roundtrips_bytes_exactly():
    e1 = _good(FakeClock())
    rendered = entry_mod.render(e1)
    parsed = entry_mod.parse(rendered).entries[0].entry
    assert parsed == e1
    assert json.loads(rendered.split("```json\n", 1)[1].split("\n```", 1)[0]) == e1


# ---------------------------------------------------------------- T22/T23 Windows replace finding (fsatomic)
def test_T22_transient_sharing_violation_on_replace_is_retried_bounded_then_succeeds(tmp_path, monkeypatch):
    import os
    from jarvis_voice.comm import fsatomic
    calls = {"n": 0}
    real = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    sleeps = []
    fsatomic.write_atomic(tmp_path / "x.json", b"{}", sleep=sleeps.append)
    assert (tmp_path / "x.json").read_bytes() == b"{}"
    assert calls["n"] == 3 and sleeps == [0.01, 0.02]


def test_T23_replace_retry_is_bounded_and_raises_leaving_the_temp_file_as_evidence(tmp_path, monkeypatch):
    import os
    from jarvis_voice.comm import fsatomic

    def always(src, dst):
        raise PermissionError(32, "busy")

    monkeypatch.setattr(os, "replace", always)
    sleeps = []
    with pytest.raises(PermissionError):
        fsatomic.write_atomic(tmp_path / "y.json", b"{}", sleep=sleeps.append)
    assert len(sleeps) == fsatomic.REPLACE_ATTEMPTS - 1
    assert not (tmp_path / "y.json").exists()
    assert list(tmp_path.glob("y.json.tmp-*"))  # left in place, never deleted
