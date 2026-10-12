"""Thin real client for the R2 GitHub plane, over the existing authenticated ``gh`` CLI.

Why ``gh``: it already holds the account's authentication; this code never reads, stores or logs a
token. The process runner is injected, so the fake stage runs without any subprocess (the suite's C1
boundary refuses real ones); the real runner is ``SubprocessRunner`` below and is used only under its
own GO.

Exactly the two calls ``plane_github.GitHubPlane`` expects:

    get(etag)             -> (status, etag, blob_sha, text | None)      304 carries no body
    put(sha, text, msg)   -> (status, commit_sha, new_blob_sha)          PUT with the blob sha = compare-and-swap

Everything is bounded: one timeout per call, a size cap on the body, strict JSON validation of what
``gh`` returns; anything unexpected is a typed exception, never a guess.
"""

from __future__ import annotations

import base64
import json
from typing import Protocol

MAX_BODY_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_S = 20.0


class GhError(RuntimeError):
    """gh exited non-zero for a reason that is not an HTTP status (auth missing, binary missing)."""


class GhProtocolError(ValueError):
    """gh answered, but not in the shape this client validates."""


class Runner(Protocol):
    def run(self, args: list[str], *, stdin: str | None, timeout_s: float) -> tuple[int, str, str]: ...


class SubprocessRunner:
    """The real runner. Not used by any test; the suite's boundary refuses subprocesses."""

    def run(self, args: list[str], *, stdin: str | None, timeout_s: float) -> tuple[int, str, str]:
        import subprocess
        p = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                           timeout=timeout_s)
        return p.returncode, p.stdout, p.stderr


def _split_response(raw: str) -> tuple[int, dict[str, str], str]:
    """Parse `gh api -i` output: status line, headers, blank line, body."""
    head, sep, body = raw.partition("\n\n")
    if not sep:
        head, sep, body = raw.partition("\r\n\r\n")
    lines = head.splitlines()
    if not lines or not lines[0].upper().startswith("HTTP/"):
        raise GhProtocolError("no HTTP status line")
    parts = lines[0].split()
    if len(parts) < 2 or not parts[1].isdigit():
        raise GhProtocolError("unparseable status line")
    status = int(parts[1])
    headers: dict[str, str] = {}
    for ln in lines[1:]:
        k, s, v = ln.partition(":")
        if s:
            headers[k.strip().lower()] = v.strip()
    return status, headers, body


class GitHubClient:
    def __init__(self, runner: Runner, *, repo: str = "kravisha/jarvis-internal",
                 path: str = "coordination/cloud-claude-coordination.md", branch: str = "master",
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        self.runner = runner
        self.repo = repo
        self.path = path
        self.branch = branch
        self.timeout_s = timeout_s
        self.calls: list[dict] = []   # what was asked, never what was answered in full (no bodies kept)

    def _endpoint(self) -> str:
        return f"repos/{self.repo}/contents/{self.path}"

    def _run(self, args: list[str], stdin: str | None) -> tuple[int, dict[str, str], str]:
        self.calls.append({"args": [a for a in args if not a.startswith("If-None-Match")], "stdin_bytes": len(stdin or "")})
        rc, out, err = self.runner.run(args, stdin=stdin, timeout_s=self.timeout_s)
        if not out.strip():
            # gh prints nothing on stdout when it could not reach the API at all
            raise GhError(f"gh exit {rc}, no response")
        status, headers, body = _split_response(out)
        return status, headers, body

    # ------------------------------------------------------------------ GET
    def get(self, etag: str | None):
        args = ["api", "-i", f"{self._endpoint()}?ref={self.branch}"]
        if etag:
            args += ["-H", f"If-None-Match: {etag}"]
        status, headers, body = self._run(args, None)
        if status == 304:
            return 304, headers.get("etag", etag), None, None
        if status != 200:
            return status, headers.get("etag"), None, None
        if len(body.encode("utf-8")) > MAX_BODY_BYTES:
            raise GhProtocolError("body exceeds the size cap")
        try:
            obj = json.loads(body)
        except ValueError:
            raise GhProtocolError("GET body is not JSON") from None
        if not isinstance(obj, dict) or obj.get("encoding") != "base64" or not isinstance(obj.get("content"), str) \
                or not isinstance(obj.get("sha"), str) or obj.get("path") != self.path:
            raise GhProtocolError("GET body lacks the contents shape (sha, path, base64 content)")
        try:
            text = base64.b64decode(obj["content"], validate=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise GhProtocolError("content is not valid base64 UTF-8") from None
        return 200, headers.get("etag"), obj["sha"], text

    # ------------------------------------------------------------------ CREATE (new file only; the CAS scratch fixture)
    def create(self, text: str, message: str):
        """Create a file that does NOT exist yet. Deliberately separate from put(): it first proves the path
        is absent (GET must answer 404) and never sends a sha, so it can never overwrite anything."""
        status, _headers, _body = self._run(["api", "-i", f"{self._endpoint()}?ref={self.branch}"], None)
        if status != 404:
            raise GhProtocolError(f"create refused: path exists or is unreadable (GET {status})")
        payload = {"message": message or "R2 scratch create", "branch": self.branch,
                   "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        args = ["api", "-i", "-X", "PUT", self._endpoint(), "--input", "-"]
        status, _headers, body = self._run(args, json.dumps(payload))
        if status not in (200, 201):
            return status, None, None
        try:
            obj = json.loads(body)
            return status, obj["commit"]["sha"], obj["content"]["sha"]
        except (ValueError, KeyError, TypeError):
            raise GhProtocolError("create body lacks commit.sha / content.sha") from None

    # ------------------------------------------------------------------ PUT (compare-and-swap)
    def put(self, sha: str | None, text: str, message: str):
        if not isinstance(sha, str) or not sha:
            raise GhProtocolError("PUT requires the blob sha from a prior GET (compare-and-swap)")
        payload = {"message": message or "R2 append", "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
                   "branch": self.branch, "sha": sha}
        args = ["api", "-i", "-X", "PUT", self._endpoint(), "--input", "-"]
        status, headers, body = self._run(args, json.dumps(payload))
        if status in (200, 201):
            try:
                obj = json.loads(body)
            except ValueError:
                raise GhProtocolError("PUT body is not JSON") from None
            try:
                return status, obj["commit"]["sha"], obj["content"]["sha"]
            except (KeyError, TypeError):
                raise GhProtocolError("PUT body lacks commit.sha / content.sha") from None
        return status, None, None
