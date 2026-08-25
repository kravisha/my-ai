"""Per-caller spend attribution (app/model_budget.py; TQ-18,
SPEC_RECONCILIATION §66).

§52 built the breaker and deferred "who spent it" until something needed the
answer; addendum 37 §3.1's "measure organizational resource use" is that
consumer. These tests cover what the attribution promises: every recorded
call and every refusal lands against a declared caller, the per-caller rows
reconcile with the day's totals, an undeclared process is bucketed honestly
rather than guessed at, and the breaker's own behaviour is unchanged - the
limit stays organization-wide, because this increment measures rather than
rations.

Every test redirects the ledger to a temporary file and resets the
process-wide caller label; nothing here touches the real model_spend.db.
"""

from types import SimpleNamespace

import pytest

from app import model_budget
from app.model_budget import BudgetedProvider, BudgetExceededError


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv(model_budget.PATH_ENV, str(tmp_path / "spend.db"))
    monkeypatch.delenv(model_budget.TOKENS_ENV, raising=False)
    monkeypatch.delenv(model_budget.CALLS_ENV, raising=False)
    monkeypatch.delenv(model_budget.CALLER_ENV, raising=False)
    monkeypatch.setattr(model_budget, "_caller", None)


class FakeInner:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.calls = 0
        self._usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)

    def complete(self, system, messages, tools, max_tokens=2048):
        self.calls += 1
        return SimpleNamespace(usage=self._usage, content=[], stop_reason="end_turn")

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls += 1
        yield {"type": "text", "text": "hi"}
        yield {"type": "final", "usage": {"input_tokens": 100, "output_tokens": 50}, "content": []}


def _by_caller():
    return {row["caller"]: row for row in model_budget.spend_by_caller()}


# --- declaring a caller -----------------------------------------------------------


def test_undeclared_spend_is_bucketed_not_guessed():
    """An honest bucket beats a clever wrong label - and a growing
    'unattributed' row is itself the finding that a spending path forgot to
    declare itself."""
    assert model_budget.current_caller() == model_budget.UNATTRIBUTED
    model_budget.record_usage(10, 5)
    rows = _by_caller()
    assert set(rows) == {model_budget.UNATTRIBUTED}
    assert rows[model_budget.UNATTRIBUTED]["tokens"] == 15


def test_set_caller_labels_this_processes_spend():
    model_budget.set_caller("explorer-1")
    assert model_budget.current_caller() == "explorer-1"
    model_budget.record_usage(100, 50)
    rows = _by_caller()
    assert rows["explorer-1"]["calls"] == 1
    assert rows["explorer-1"]["input_tokens"] == 100
    assert rows["explorer-1"]["output_tokens"] == 50


def test_environment_labels_a_process_that_never_declares(monkeypatch):
    """A spawned process inherits the variable and is attributed before it
    runs a line of its own."""
    monkeypatch.setenv(model_budget.CALLER_ENV, "analysis-1")
    assert model_budget.current_caller() == "analysis-1"
    model_budget.record_usage(1, 1)
    assert set(_by_caller()) == {"analysis-1"}


def test_an_explicit_declaration_beats_the_environment(monkeypatch):
    monkeypatch.setenv(model_budget.CALLER_ENV, "inherited")
    model_budget.set_caller("declared")
    assert model_budget.current_caller() == "declared"


# --- the ledger reconciles --------------------------------------------------------


def test_per_caller_rows_sum_to_the_days_totals():
    """The property that makes attribution trustworthy: the two tables are
    written in one transaction, so they cannot disagree."""
    model_budget.set_caller("explorer-1")
    model_budget.record_usage(100, 50)
    model_budget.set_caller("analysis-1")
    model_budget.record_usage(4000, 900)
    model_budget.record_usage(None, None)  # unreported usage, still a call

    total = model_budget.todays_spend()
    rows = model_budget.spend_by_caller()
    assert sum(r["calls"] for r in rows) == total["calls"] == 3
    assert sum(r["input_tokens"] for r in rows) == total["input_tokens"] == 4100
    assert sum(r["output_tokens"] for r in rows) == total["output_tokens"] == 950


def test_rows_are_ranked_by_tokens_not_call_count():
    """A thousand stance reads cost less than forty deep passes; ranking by
    calls would point optimization at the wrong caller."""
    model_budget.set_caller("chatty")
    for _ in range(5):
        model_budget.record_usage(1, 1)
    model_budget.set_caller("expensive")
    model_budget.record_usage(5000, 5000)

    rows = model_budget.spend_by_caller()
    assert [r["caller"] for r in rows] == ["expensive", "chatty"]
    assert rows[0]["calls"] < rows[1]["calls"]


def test_a_day_with_no_spend_reads_empty():
    assert model_budget.spend_by_caller() == []
    assert model_budget.spend_by_caller(day="1999-01-01") == []


# --- refusals ---------------------------------------------------------------------


def test_refusals_are_attributed_to_whoever_was_refused(monkeypatch):
    """Addendum 37 §3.3, identifying waste: a breaker that fired 400 times
    says less than one that fired 400 times at a single runaway caller."""
    monkeypatch.setenv(model_budget.CALLS_ENV, "1")
    model_budget.set_caller("explorer-1")
    model_budget.record_usage(10, 10)  # the day's one allowed call

    model_budget.set_caller("runaway-1")
    for _ in range(3):
        with pytest.raises(BudgetExceededError):
            model_budget.check_budget()

    rows = _by_caller()
    assert rows["runaway-1"]["refusals"] == 3
    assert rows["runaway-1"]["calls"] == 0  # refused, so it never spent
    assert rows["explorer-1"]["refusals"] == 0
    assert model_budget.todays_spend()["refusals"] == 3


# --- the breaker is unchanged -----------------------------------------------------


def test_the_limit_stays_organization_wide(monkeypatch):
    """This increment measures; it does not ration. Two callers share one
    budget - a per-caller cap would let the population collectively spend N
    times the limit, which is exactly what §52's shared ledger prevents."""
    monkeypatch.setenv(model_budget.CALLS_ENV, "2")
    model_budget.set_caller("explorer-1")
    model_budget.record_usage(1, 1)
    model_budget.set_caller("speculator-1")
    model_budget.record_usage(1, 1)

    model_budget.set_caller("analysis-1")  # a caller that has spent nothing
    with pytest.raises(BudgetExceededError):
        model_budget.check_budget()


def test_provider_calls_are_attributed_through_the_wrapper():
    model_budget.set_caller("gateway")
    provider = BudgetedProvider(FakeInner())
    provider.complete("s", [], [])
    list(provider.stream("s", [], []))

    rows = _by_caller()
    assert rows["gateway"]["calls"] == 2
    assert rows["gateway"]["tokens"] == 2 * 150


def test_attribution_starts_empty_on_a_pre_existing_ledger(tmp_path, monkeypatch):
    """Not retroactive: a ledger written before attribution existed keeps
    every total it held, gains the new table on first open, and simply has
    no per-caller history to show."""
    import sqlite3

    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE spend (day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0, "
        "input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, "
        "refusals INTEGER NOT NULL DEFAULT 0)"
    )
    legacy.execute(
        "INSERT INTO spend (day, calls, input_tokens, output_tokens) VALUES (?, 7, 700, 300)",
        (model_budget._today(),),
    )
    legacy.commit()
    legacy.close()

    monkeypatch.setenv(model_budget.PATH_ENV, str(path))
    assert model_budget.todays_spend()["calls"] == 7      # history intact
    assert model_budget.spend_by_caller() == []           # attribution starts now

    model_budget.set_caller("explorer-1")
    model_budget.record_usage(10, 10)
    assert model_budget.todays_spend()["calls"] == 8
    assert _by_caller()["explorer-1"]["calls"] == 1
