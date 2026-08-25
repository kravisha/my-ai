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

## Per-caller attribution (TQ-18, SPEC_RECONCILIATION §66)

§52 deferred "who spent it" until something needed the answer; addendum 37
§3.1's "measure organizational resource use" is that consumer, so every
call is now also counted against a **caller label** in a second table.
Three things this deliberately is not:

- **Not a second budget.** The limit stays organization-wide. A per-caller
  cap is a policy change nobody has asked for, and it would break §52's
  damage bound (the population collectively spending N caps). This
  increment measures; it does not ration.
- **Not inferred.** A process declares itself through `set_caller` (agents
  do it in `agents/base.py`'s run loop, the two chat surfaces at startup).
  A process that never declares is counted as `unattributed` rather than
  guessed at from a stack walk — an honest bucket beats a clever wrong
  label, and a growing `unattributed` row is itself the finding that
  someone forgot to declare.
- **Not retroactive.** Ledger rows written before this existed carry no
  caller, and the per-caller table simply starts empty; the totals in
  `spend` remain the authority on what was spent.
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
CALLER_ENV = "MODEL_BUDGET_CALLER"

# The label spend is attributed to when nobody declared one. A real bucket,
# not a null: a growing 'unattributed' row is the finding that some spending
# path never called set_caller.
UNATTRIBUTED = "unattributed"

# Process-wide, like the provider singleton it accounts for: one process is
# one caller. Set once at startup (agents/base.py's run loop, the chat
# surfaces' own entry points) rather than threaded through every call site -
# the alternative is a parameter on an interface (ModelProvider.complete)
# that exists precisely so callers do not know what is behind it.
_caller: str | None = None


def set_caller(label: str) -> None:
    """Declare who this process's model spend belongs to."""
    global _caller
    _caller = label


def current_caller() -> str:
    """Environment second, `unattributed` last - so a spawned process that
    inherits MODEL_BUDGET_CALLER is labelled even before it declares, and a
    process that does neither is honestly bucketed rather than guessed."""
    return _caller or os.environ.get(CALLER_ENV) or UNATTRIBUTED


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
    # Additive (TQ-18): an existing ledger gains this table on first open and
    # keeps every total it already held. Same columns as `spend`, keyed by
    # (day, caller) - so the per-caller rows sum to the day's totals for
    # everything recorded since attribution existed, and no earlier.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS spend_by_caller ("
        "  day TEXT NOT NULL,"
        "  caller TEXT NOT NULL,"
        "  calls INTEGER NOT NULL DEFAULT 0,"
        "  input_tokens INTEGER NOT NULL DEFAULT 0,"
        "  output_tokens INTEGER NOT NULL DEFAULT 0,"
        "  refusals INTEGER NOT NULL DEFAULT 0,"
        "  PRIMARY KEY (day, caller)"
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


def spend_by_caller(day: str | None = None) -> list[dict]:
    """One row per caller for `day` (today by default), heaviest spender
    first - the read side addendum 37 §3.1's "measure organizational
    resource use" asks for, so an optimization finding like §58's is a
    query rather than a manual trace.

    Ordered by tokens rather than calls: a thousand stance reads cost less
    than forty deep-analysis passes, and ranking by call count would point
    optimization at the wrong caller."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT caller, calls, input_tokens, output_tokens, refusals FROM spend_by_caller "
            "WHERE day = ? ORDER BY (input_tokens + output_tokens) DESC, caller",
            (day or _today(),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "caller": row[0], "calls": row[1], "input_tokens": row[2],
            "output_tokens": row[3], "tokens": row[2] + row[3], "refusals": row[4],
        }
        for row in rows
    ]


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
        # Same transaction as the total it belongs to: the two tables commit
        # together or not at all, so attribution can never disagree with the
        # spend it attributes.
        conn.execute(
            "INSERT INTO spend_by_caller (day, caller, calls, input_tokens, output_tokens) "
            "VALUES (?, ?, 1, ?, ?) "
            "ON CONFLICT(day, caller) DO UPDATE SET calls = calls + 1, "
            "input_tokens = input_tokens + excluded.input_tokens, "
            "output_tokens = output_tokens + excluded.output_tokens",
            (_today(), current_caller(), input_tokens or 0, output_tokens or 0),
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
        # Who got refused is the more useful half of a refusal: a breaker
        # that fired 400 times says less than one that fired 400 times at
        # one runaway caller (addendum 37 §3.3, identifying waste).
        conn.execute(
            "INSERT INTO spend_by_caller (day, caller, refusals) VALUES (?, ?, 1) "
            "ON CONFLICT(day, caller) DO UPDATE SET refusals = refusals + 1",
            (_today(), current_caller()),
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
