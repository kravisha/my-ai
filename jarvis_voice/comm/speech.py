"""Speech eligibility tokens (Arya 5825957209 item 2, refined 5825988607; agreed 5825984993).

Comm owns ELIGIBILITY: at most one token per eligible terminal turn, bound to the request,
the epoch and the cancellation generation at issue. The host owns PLAYBACK and reports
through idempotent callbacks that must present the token id AND the epoch AND the
cancellation generation; a stale or mismatched triple is refused. A Stop bumps the
cancellation generation and invalidates every outstanding token, so a delayed ``onend``
can never revive ``spoken``. Restored, late, duplicate and cancelled turns never get a token.

States: eligible -> started -> spoken | error(<type>) | unknown
        eligible -> spoken only through a callback, or synchronously when the speaker declares
        ``blocking_completion = True`` (an explicit verified contract; None-return proves nothing)
        eligible | started -> cancelled_before_completion (Stop)
Terminal states never change again; a further callback is ``ignored``.
"""

from __future__ import annotations

import re
import uuid

TERMINAL = ("spoken", "unknown", "cancelled_before_completion")
_ERROR_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")


class SpeechLedger:
    def __init__(self, clock):
        self.clock = clock
        self.tokens: dict[str, dict] = {}
        self.cancel_generation = 0

    def issue(self, *, request_id: str, epoch: str, text: str) -> dict:
        for t in self.tokens.values():
            if t["request_id"] == request_id and t["epoch"] == epoch:
                raise ValueError("a token for this request and epoch was already issued")
        tok = {"token_id": str(uuid.uuid4()), "request_id": request_id, "epoch": epoch,
               "cancel_generation": self.cancel_generation, "text": text,
               "state": "eligible", "history": [{"at": self.clock.iso(), "state": "eligible"}]}
        self.tokens[tok["token_id"]] = tok
        return tok

    def _check(self, token_id: str, epoch: str | None, cancel_generation: int | None) -> dict | str:
        tok = self.tokens.get(token_id)
        if tok is None:
            return "refused"
        if epoch is not None and epoch != tok["epoch"]:
            return "refused"
        if cancel_generation is not None and cancel_generation != tok["cancel_generation"]:
            return "refused"
        return tok

    def _move(self, token_id: str, state: str, *, allowed_from: tuple[str, ...], epoch=None, cancel_generation=None) -> str:
        tok = self._check(token_id, epoch, cancel_generation)
        if isinstance(tok, str):
            return tok
        if tok["state"] in TERMINAL or tok["state"].startswith("error"):
            return "ignored"
        if tok["state"] not in allowed_from:
            return "ignored"
        tok["state"] = state
        tok["history"].append({"at": self.clock.iso(), "state": state})
        return "applied"

    def started(self, token_id: str, *, epoch=None, cancel_generation=None) -> str:
        return self._move(token_id, "started", allowed_from=("eligible",), epoch=epoch, cancel_generation=cancel_generation)

    def completed(self, token_id: str, *, epoch=None, cancel_generation=None) -> str:
        return self._move(token_id, "spoken", allowed_from=("eligible", "started"), epoch=epoch, cancel_generation=cancel_generation)

    def error(self, token_id: str, error_type: str, *, epoch=None, cancel_generation=None) -> str:
        if not isinstance(error_type, str) or not _ERROR_TYPE.match(error_type):
            error_type = "UnknownError"  # empty or free-text errors become a typed, bounded outcome
        return self._move(token_id, f"error({error_type})", allowed_from=("eligible", "started"), epoch=epoch, cancel_generation=cancel_generation)

    def unknown(self, token_id: str, *, epoch=None, cancel_generation=None) -> str:
        return self._move(token_id, "unknown", allowed_from=("eligible", "started"), epoch=epoch, cancel_generation=cancel_generation)

    def invalidate_all(self) -> list[str]:
        """Stop: bump the cancellation generation and cancel every outstanding token."""
        self.cancel_generation += 1
        out = []
        for tid, tok in self.tokens.items():
            if tok["state"] in ("eligible", "started"):
                tok["state"] = "cancelled_before_completion"
                tok["history"].append({"at": self.clock.iso(), "state": "cancelled_before_completion"})
                out.append(tid)
        return out

    def state(self, token_id: str) -> str | None:
        tok = self.tokens.get(token_id)
        return tok["state"] if tok else None

    def descriptor(self, token_id: str) -> dict | None:
        """What the host gets: the identity triple plus the text; never the history."""
        tok = self.tokens.get(token_id)
        if tok is None:
            return None
        return {"token_id": tok["token_id"], "request_id": tok["request_id"], "epoch": tok["epoch"],
                "cancel_generation": tok["cancel_generation"], "text": tok["text"], "state": tok["state"]}
