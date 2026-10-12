"""T39-T46: the thin gh-based client, fake stage. A fake runner plays `gh api -i`; no subprocess runs
(the C1 boundary refuses one); no token is ever seen by the client. The last case drives the real
GitHubPlane + Publisher through this client against a fake server kept in the runner."""

from __future__ import annotations

import base64
import json

import pytest

from jarvis_voice.comm import entry as entry_mod, github_client as gc, ledger as ledger_mod, outbox as outbox_mod
from jarvis_voice.comm import plane as plane_mod, plane_github, publisher as pub_mod
from tests.test_jarvis_comm_support import *  # noqa: F401,F403

PATH = "coordination/cloud-claude-coordination.md"


class FakeGh:
    """Plays `gh api -i` for the two calls; keeps a tiny server state (text, blob, etag)."""

    def __init__(self, text="# legacy\n"):
        self.text = text
        self.version = 0
        self.script: list = []      # optional forced responses: ("timeout",) | ("exit", rc) | ("raw", str)
        self.seen: list[dict] = []

    @property
    def blob(self):
        return f"blob{self.version}"

    def _resp(self, status_line, headers, body):
        return status_line + "\n" + "\n".join(f"{k}: {v}" for k, v in headers.items()) + "\n\n" + body

    def run(self, args, *, stdin, timeout_s):
        self.seen.append({"args": list(args), "stdin": stdin, "timeout_s": timeout_s})
        if self.script:
            kind = self.script.pop(0)
            if kind[0] == "timeout":
                raise TimeoutError("gh timed out")
            if kind[0] == "exit":
                return kind[1], "", "gh: auth required"
            if kind[0] == "raw":
                return 0, kind[1], ""
        if "-X" in args and "PUT" in args:
            payload = json.loads(stdin)
            if "sha" not in payload:            # create: the fake trusts the client's prior 404 check
                self.text = base64.b64decode(payload["content"]).decode("utf-8")
                self.version += 1
                body = json.dumps({"content": {"sha": self.blob, "path": PATH}, "commit": {"sha": f"commit{self.version}"}})
                return 0, self._resp("HTTP/2.0 201 Created", {"etag": f'"{self.blob}"'}, body), ""
            if payload.get("sha") != self.blob:
                return 1, self._resp("HTTP/2.0 409 Conflict", {"x-github-request-id": "r"}, '{"message":"is at ' + self.blob + ' but expected"}'), ""
            self.text = base64.b64decode(payload["content"]).decode("utf-8")
            self.version += 1
            body = json.dumps({"content": {"sha": self.blob, "path": PATH}, "commit": {"sha": f"commit{self.version}"}})
            return 0, self._resp("HTTP/2.0 200 OK", {"etag": f'"{self.blob}"'}, body), ""
        # GET
        etag = None
        for i, a in enumerate(args):
            if a == "-H" and args[i + 1].startswith("If-None-Match:"):
                etag = args[i + 1].split(":", 1)[1].strip()
        if etag == f'"{self.blob}"':
            return 0, self._resp("HTTP/2.0 304 Not Modified", {"etag": f'"{self.blob}"'}, ""), ""
        body = json.dumps({"sha": self.blob, "path": PATH, "encoding": "base64", "size": len(self.text.encode()),
                           "content": base64.b64encode(self.text.encode("utf-8")).decode("ascii")})
        return 0, self._resp("HTTP/2.0 200 OK", {"etag": f'"{self.blob}"', "x-ratelimit-remaining": "3611"}, body), ""


@pytest.fixture
def client():
    gh = FakeGh()
    return gh, gc.GitHubClient(gh, path=PATH, timeout_s=7.5)


def test_T39_get_parses_status_etag_sha_and_decodes_utf8_content(client):
    gh, c = client
    gh.text = "# legacy\n\nprose é\n"
    status, etag, sha, text = c.get(None)
    assert (status, etag, sha, text) == (200, '"blob0"', "blob0", "# legacy\n\nprose é\n")
    assert gh.seen[-1]["args"][:3] == ["api", "-i", f"repos/kravisha/jarvis-internal/contents/{PATH}?ref=master"]
    assert gh.seen[-1]["timeout_s"] == 7.5


def test_T40_conditional_get_sends_if_none_match_and_returns_304_without_body(client):
    gh, c = client
    status, etag, sha, text = c.get('"blob0"')
    assert status == 304 and text is None and sha is None and etag == '"blob0"'
    assert any(a.startswith("If-None-Match: ") for a in gh.seen[-1]["args"])
    assert not any("If-None-Match" in a for a in c.calls[-1]["args"])   # the client's own log never keeps the header


def test_T41_put_is_a_compare_and_swap_with_sha_branch_and_base64_and_parses_commit(client):
    gh, c = client
    status, commit, new_blob = c.put("blob0", "# legacy\n### x\n", "R2 append")
    assert (status, commit, new_blob) == (200, "commit1", "blob1")
    payload = json.loads(gh.seen[-1]["stdin"])
    assert payload == {"message": "R2 append", "branch": "master", "sha": "blob0",
                       "content": base64.b64encode(b"# legacy\n### x\n").decode("ascii")}
    assert gh.seen[-1]["args"][:4] == ["api", "-i", "-X", "PUT"] and "--input" in gh.seen[-1]["args"]
    assert gh.text == "# legacy\n### x\n"


def test_T42_put_with_a_stale_sha_is_409_and_put_without_sha_is_refused(client):
    gh, c = client
    c.put("blob0", "a\n", "m")
    assert c.put("blob0", "b\n", "m") == (409, None, None)
    with pytest.raises(gc.GhProtocolError):
        c.put(None, "c\n", "m")
    assert gh.text == "a\n"


def test_T43_timeout_exit_and_malformed_answers_are_typed(client):
    gh, c = client
    gh.script = [("timeout",)]
    with pytest.raises(TimeoutError):
        c.get(None)
    gh.script = [("exit", 4)]
    with pytest.raises(gc.GhError):
        c.get(None)
    gh.script = [("raw", "HTTP/2.0 200 OK\netag: x\n\n{not json")]
    with pytest.raises(gc.GhProtocolError):
        c.get(None)
    gh.script = [("raw", "HTTP/2.0 200 OK\netag: x\n\n" + json.dumps({"sha": "s", "path": "other/file.md", "encoding": "base64", "content": ""}))]
    with pytest.raises(gc.GhProtocolError):
        c.get(None)
    gh.script = [("raw", "garbage without status line")]
    with pytest.raises(gc.GhProtocolError):
        c.get(None)


def test_T44_body_over_the_size_cap_is_refused(client, monkeypatch):
    gh, c = client
    monkeypatch.setattr(gc, "MAX_BODY_BYTES", 64)
    gh.text = "x" * 200
    with pytest.raises(gc.GhProtocolError):
        c.get(None)


def test_T45_plane_maps_client_answers_lost_response_is_put_unknown(client):
    gh, c = client
    plane = plane_github.GitHubPlane(c, path=PATH)
    f = plane.fetch(None)
    assert f.status == plane_mod.CHANGED and f.cursor == {"etag": '"blob0"', "sha": "blob0"}
    assert plane.fetch(f.cursor).status == plane_mod.UNCHANGED
    gh.script = [("timeout",)]
    assert plane.put(f.cursor, "x\n").status == plane_mod.PUT_UNKNOWN
    gh.script = [("exit", 4)]
    assert plane.fetch(None).status == plane_mod.FAILED


def test_T46_publisher_end_to_end_through_the_thin_client_append_cas_readback(client, tmp_path):
    gh, c = client
    clock = FakeClock()
    plane = plane_github.GitHubPlane(c, path=PATH)
    pub = pub_mod.Publisher(plane, outbox_mod.Outbox(tmp_path / "ob"), ledger_mod.Ledger(tmp_path / "lg.json"), sleep=clock.sleep, clock=clock)
    e = peer_entry(clock, type_="CHECK_IN", body="fixture", from_=SELF["id"], epoch=SELF["epoch"], to=[PEER["id"]])
    r = pub.publish(e)
    assert r.status == plane_mod.DELIVERED_VERIFIED and r.commit == "commit1"
    assert gh.text.startswith("# legacy\n") and gh.text.count("### " + e["message_id"]) == 1
    # a peer wrote in between: the next publish sees a 409 once, rereads and lands after the peer
    peer = peer_entry(clock, type_="PROGRESS", body="peer")
    seq = [gh.run]

    def run_with_peer_race(args, *, stdin, timeout_s):
        if "-X" in args and not getattr(run_with_peer_race, "raced", False):
            run_with_peer_race.raced = True
            gh.text += entry_mod.render(peer)
            gh.version += 1
        return seq[0](args, stdin=stdin, timeout_s=timeout_s)

    c.runner = type("R", (), {"run": staticmethod(run_with_peer_race)})()
    e2 = peer_entry(clock, type_="PROGRESS", body="mine", from_=SELF["id"], epoch=SELF["epoch"], to=[PEER["id"]])
    r2 = pub.publish(e2)
    assert r2.status == plane_mod.DELIVERED_VERIFIED and r2.attempts == 2
    assert gh.text.index(peer["message_id"]) < gh.text.index(e2["message_id"])


def test_control_real_runner_is_refused_by_the_boundary():
    with pytest.raises(Exception):
        gc.SubprocessRunner().run(["--version"], stdin=None, timeout_s=1)


def test_T47b_create_only_when_the_path_is_absent_and_never_with_a_sha(client):
    gh, c = client
    with pytest.raises(gc.GhProtocolError):           # the file exists (fake answers 200): create refused
        c.create("x\n", "m")
    gh.script = [("raw", "HTTP/2.0 404 Not Found\n\n{\"message\":\"Not Found\"}")]
    status, commit, blob = c.create("### scratch\n", "R2 scratch create")
    assert (status, commit) == (201, "commit1")
    payload = json.loads(gh.seen[-1]["stdin"])
    assert "sha" not in payload and payload["branch"] == "master"
