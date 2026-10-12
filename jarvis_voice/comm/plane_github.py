"""The R2 message plane over the GitHub Contents API, with an injectable client.

The client has two calls, and the tests supply a fake:

    get(etag) -> (status, etag, blob_sha, text|None)      # 304 carries no body
    put(blob_sha, text, message) -> (status, commit_sha, new_blob_sha)

A real client (not written here: no live transport is authorized in C1) would call
``GET /repos/{repo}/contents/{path}?ref=master`` with ``If-None-Match`` and
``PUT`` the same path with ``sha`` set to the GET's blob SHA. That ``sha`` is what makes
the append a compare-and-swap. The cursor is ``{"etag": e, "sha": blob}``.
"""

from __future__ import annotations

from . import plane as P


class GitHubPlane:
    name = "github-contents"

    def __init__(self, client, *, path: str, repo: str = "kravisha/jarvis-internal", branch: str = "master"):
        self.client = client
        self.path = path
        self.repo = repo
        self.branch = branch

    def fetch(self, cursor: dict | None) -> P.FetchResult:
        etag = cursor.get("etag") if cursor else None
        try:
            status, new_etag, blob, text = self.client.get(etag)
        except Exception as e:  # network failure is FAILED, never "empty"
            return P.FetchResult(P.FAILED, detail=type(e).__name__)
        if status == 304:
            return P.FetchResult(P.UNCHANGED, cursor=cursor)
        if status != 200 or text is None:
            return P.FetchResult(P.FAILED, detail=f"http {status}")
        return P.FetchResult(P.CHANGED, cursor={"etag": new_etag, "sha": blob}, text=text)

    def put(self, expected_cursor: dict | None, new_text: str, message: str = "") -> P.PutResult:
        sha = expected_cursor.get("sha") if expected_cursor else None
        try:
            status, commit, new_blob = self.client.put(sha, new_text, message or "R2 append")
        except Exception as e:  # lost response: the server may have applied it
            return P.PutResult(P.PUT_UNKNOWN, detail=type(e).__name__)
        if status in (409, 412, 422):
            return P.PutResult(P.PUT_CONFLICT, detail=f"http {status}")
        if status in (200, 201):
            return P.PutResult(P.PUT_OK, cursor={"etag": None, "sha": new_blob}, commit=commit)
        if status in (401, 403):
            return P.PutResult(P.PUT_FAILED, detail=f"http {status}: authentication/permission - a concrete blocker")
        return P.PutResult(P.PUT_FAILED, detail=f"http {status}")
