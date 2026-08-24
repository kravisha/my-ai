"""The cost circuit breaker (addendum 28 §19.3, §32 item 18; TASK_QUEUE TQ-10).

Nothing here decides what the model may *say* — it decides whether the next
call may *spend*. The risk this bounds is not exposure-gated: a runaway agent
loop spends real money the moment a real API key exists, and §50's audit found
nothing standing between such a loop and the invoice.

Design decisions, and why:

- **A shared SQLite ledger, not in-memory counters.** The organization is a
  population of separate processes (backend, Controller, every agent, the
  Gateway), each holding its own provider singleton. Per-process counters
  would let the population collectively spend N times the budget; the ledger
  file is the one place they all count against. Its path follows the same
  environment-first convention as the databases (MODEL_BUDGET_DB_PATH),
  resolved at call time so test redirection works without import-order games.
- **Post-hoc accounting, pre-call refusal.** A call's true cost is known only
  from the response's usage report, so the breaker refuses the *next* call
  once recorded spend crosses the limit. Damage is bounded to the limit plus
  one reply — accepted, and stated here rather than implied away. Usage a
  response does not report is recorded as zero, never estimated: the ledger
  holds what the provider said, not what a formula guessed.
- **Refusals are recorded like any other denial.** Every refusal increments
  the day's `refusals` counter before the error is raised, so "the breaker
  fired" is a queryable fact in the ledger, not a log line that scrolled away.
- **The defaults are deliberately real.** A breaker that is off by default
  protects nothing. 500k tokens / 2000 calls per UTC day is generous for this
  deployment and small against a runaway loop; both are raised deliberately
  through the environment, and an unparseable limit is an error, not a
  silent fallback — a typo must not become an unlimited budget.
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DAILY_TOKENS = 500_000
DEFAULT_DAILY_CALLS = 2_000

TOKENS_ENV = "MODEL_BUDGET_DAILY_TOKENS"
CALLS_ENV = "MODEL_BUDGET_DAILY_CALLS"
PATH_ENV = "MODEL_BUDGET_DB_PATH"


class BudgetExceededError(RuntimeError):
    """Raised instead of spending. The message carries today's numbers and the
    environment variable that raises the cap, because the person who hits this
    needs the remedy, not just the fact."""


def _ledger_path() -> Path:
    return Path(os.environ.get(PATH_ENV) or (PROJECT_ROOT / "model_spend.db"))


def _limit(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"{name}={raw!r} is not an integer. Refusing to guess a budget limit - "
            "fix or unset the variable."
        ) from None
    if value < 0:
        raise ValueError(f"{name}={value} is negative; a budget limit cannot be.")
    return value


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_ledger_path(), timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS spend ("
        "  day TEXT PRIMARY KEY,"
        "  calls INTEGER NOT NULL DEFAULT 0,"
        "  input_tokens INTEGER NOT NULL DEFAULT 0,"
        "  output_tokens INTEGER NOT NULL DEFAULT 0,"
        "  refusals INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    return conn


def todays_spend() -> dict:
    """The ledger row for today, zeros if nothing has spent yet."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT calls, input_tokens, output_tokens, refusals FROM spend WHERE day = ?",
            (_today(),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"day": _today(), "calls": 0, "input_tokens": 0, "output_tokens": 0, "refusals": 0}
    return {
        "day": _today(), "calls": row[0], "input_tokens": row[1],
        "output_tokens": row[2], "refusals": row[3],
    }


def record_usage(input_tokens: int | None, output_tokens: int | None) -> None:
    """One completed call: count it, and add what the provider reported.
    None means the response did not say - recorded as zero, never estimated."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO spend (day, calls, input_tokens, output_tokens) VALUES (?, 1, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET calls = calls + 1, "
            "input_tokens = input_tokens + excluded.input_tokens, "
            "output_tokens = output_tokens + excluded.output_tokens",
            (_today(), input_tokens or 0, output_tokens or 0),
        )
        conn.commit()
    finally:
        conn.close()


def check_budget() -> None:
    """Refuse, visibly and on the record, if today's recorded spend has
    crossed either limit. Called before the provider is touched."""
    token_limit = _limit(TOKENS_ENV, DEFAULT_DAILY_TOKENS)
    call_limit = _limit(CALLS_ENV, DEFAULT_DAILY_CALLS)
    spend = todays_spend()
    tokens = spend["input_tokens"] + spend["output_tokens"]

    over_calls = spend["calls"] >= call_limit
    over_tokens = tokens >= token_limit
    if not (over_calls or over_tokens):
        return

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO spend (day, refusals) VALUES (?, 1) "
            "ON CONFLICT(day) DO UPDATE SET refusals = refusals + 1",
            (_today(),),
        )
        conn.commit()
    finally:
        conn.close()

    if over_calls:
        raise BudgetExceededError(
            f"Daily model call budget exhausted: {spend['calls']} calls recorded today "
            f"(limit {call_limit}). Raise {CALLS_ENV} deliberately if this spend is intended."
        )
    raise BudgetExceededError(
        f"Daily model token budget exhausted: {tokens} tokens recorded today "
        f"(limit {token_limit}). Raise {TOKENS_ENV} deliberately if this spend is intended."
    )


def _reported_int(value) -> int | None:
    """Usage as the provider reported it, or None. isinstance rather than a
    cast: a mock, a string, or any other non-integer must become 'not
    reported', never a fabricated number in the ledger."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class BudgetedProvider:
    """A ModelProvider that wraps another and counts. The inner provider is
    never touched once the budget is exhausted - the check runs before the
    call, the accounting after it, and the interface in between is unchanged,
    which is what lets this wrap any vendor the system ever routes to."""

    def __init__(self, inner):
        self.inner = inner

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        check_budget()
        response = self.inner.complete(system, messages, tools, max_tokens=max_tokens)
        usage = getattr(response, "usage", None)
        record_usage(
            _reported_int(getattr(usage, "input_tokens", None)),
            _reported_int(getattr(usage, "output_tokens", None)),
        )
        return response

    def stream(
        self, system: str, messages: list, tools: list, max_tokens: int = 2048
    ) -> Iterator[dict]:
        """Events pass through untouched; accounting happens in the finally so
        a stream abandoned mid-reply still counts as a call - the spend
        happened whether or not the caller finished reading it."""
        check_budget()
        input_tokens = output_tokens = None
        try:
            for event in self.inner.stream(system, messages, tools, max_tokens=max_tokens):
                if event.get("type") == "final":
                    usage = event.get("usage") or {}
                    input_tokens = _reported_int(usage.get("input_tokens"))
                    output_tokens = _reported_int(usage.get("output_tokens"))
                yield event
        finally:
            record_usage(input_tokens, output_tokens)
