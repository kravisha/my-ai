"""Ownership without a store, and the tripwires that keep it that way
(TQ-44 §99, TQ-69 §110; **custody removed by TQ-72, §111**).

This file used to hold fifty-odd tests over a `portfolios` table: resolve by id,
listing by owner, archived rows, the one refusal, the migration. All of it was
correct, and all of it was about a table that no longer exists — owner direction:
*"The portfolios don't live in this system."*

What is here now is the half that was never about storage, plus a half that is
new and matters more:

- **`OwnerContext` still refuses what it always refused.** A bare string is a
  claim, not a proof, and the owner still comes from the session rather than from
  anything a caller sent (addendum 44 §9.2).
- **The removal has to stay removed.** A store deleted in one increment and
  re-added in another as "just a cache" would be the whole of §111 undone by
  somebody being helpful.

The one to read first is `test_no_module_declares_a_portfolio_table`. §110's
tripwire asserted that nothing outside `portfolios.py` *queried* the table; this
asserts that nothing anywhere *creates* one. The old check would go on passing
forever now while saying nothing, because the danger moved — which is the
recurring lesson in this repository (§105, §110): a tripwire aimed where the risk
used to be is not a tripwire.
"""

import ast
import re
from pathlib import Path

import pytest

from backend import holdings, portfolios

ROOT = Path(__file__).resolve().parent.parent
TREES = ("app", "backend", "gateway", "agents", "simulation")


# --- ownership, which outlived the table -------------------------------------------


def test_an_owner_context_needs_an_owner():
    for nobody in (None, "", "   "):
        with pytest.raises(portfolios.UnknownVocabulary):
            portfolios.for_client(nobody)


def test_an_unknown_owner_type_is_refused():
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.OwnerContext("ACCOUNTANT", "avery")


def test_an_owner_id_is_normalised_the_way_a_login_is():
    """One normalisation, shared with `gateway.clients` rather than copied. Two
    that could disagree would make one client into two owners, and **no ownership
    comparison could detect it** - both comparisons would be correct, about
    different people."""
    from gateway import clients

    assert portfolios.for_client("  AVERY ").owner_id == "avery"
    assert clients.normalise("  AVERY ") == portfolios.normalise("  AVERY ") == "avery"


def test_a_raw_client_id_cannot_be_passed_where_an_owner_is_required():
    """A raw id is something a caller might have got from anywhere - a URL, an
    argument, a model's imagination. An `OwnerContext` is the result of resolving
    one."""
    for claim in ("avery", None, {"owner_id": "avery"}):
        with pytest.raises(TypeError):
            portfolios.require_owner(claim)


def test_the_two_owner_domains_are_separate():
    """`SUPERUSER` is a separate owner domain, not a skeleton key (addendum 44
    §5.3). One name in two domains is two owners, and it stays that way with no
    table to compare rows in."""
    assert portfolios.for_client("krish") != portfolios.for_superuser("krish")


def test_a_superuser_owner_needs_an_explicit_id():
    """The default used to be the literal `"operator"`. A literal cannot be wrong
    in a way anybody notices, and this one would have been *nearly* right."""
    import inspect

    parameter = inspect.signature(portfolios.for_superuser).parameters["operator_id"]
    assert parameter.default is inspect.Parameter.empty


def test_an_unknown_vocabulary_value_is_refused():
    for value, vocabulary, field in (
        ("REAL", portfolios.DATA_MODES, "data mode"),
        ("FIDELITY", portfolios.PROVIDER_TYPES, "provider type"),
        ("RETIREMENT", portfolios.PORTFOLIO_TYPES, "portfolio type"),
    ):
        with pytest.raises(portfolios.UnknownVocabulary):
            portfolios.check_vocabulary(value, vocabulary, field)


def test_there_is_one_refusal_and_nothing_formatted_into_it():
    """Addendum 44 §9.3: absent, foreign and unavailable must be
    indistinguishable. One string, no formatting."""
    assert "{" not in portfolios.REFUSAL and "%" not in portfolios.REFUSAL


def test_only_a_live_source_is_priced():
    """§101's one-line rule, unchanged - and §113 has put it on notice rather
    than changed it. The rule moves to the price's provenance when TQ-75 gives it
    one to read; until then a `LIVE` claim is the only thing that unlocks
    market-derived values."""
    assert portfolios.is_priced({"data_mode": portfolios.MODE_LIVE}) is True
    for mode in (portfolios.MODE_SIMULATED, portfolios.MODE_MANUAL, None):
        assert portfolios.is_priced({"data_mode": mode}) is False


# --- the removal has to stay removed (§111) ----------------------------------------


def test_no_module_declares_a_portfolio_table():
    """**The tripwire this increment needs**, and the one §110's could not be.

    §110 asserted that nothing outside `portfolios.py` *queried* the table. That
    was the right check while a table existed. It would go on passing forever
    now, saying nothing, because the danger moved: what must not happen is a
    table being *created* - by anybody, including `portfolios.py`.

    A store deleted in one increment and re-added in another as "just a cache" is
    how §111 gets undone by somebody being helpful, and it would not look like a
    violation. It would look like a performance fix."""
    offenders = []
    pattern = re.compile(
        r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(portfolios|portfolio_holdings)\b",
        re.IGNORECASE)
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob("*.py")):
            found = pattern.search(path.read_text(encoding="utf-8"))
            if found:
                offenders.append(
                    f"{tree}/{path.relative_to(ROOT / tree)}: {found.group(0)}")

    assert not offenders, (
        "these declare a portfolio table:\n  " + "\n  ".join(offenders)
        + "\nThis system stores no portfolio (SPEC_RECONCILIATION §111). Positions are "
          "fetched from the client's own external sources for the life of a session and "
          "discarded when they disconnect."
    )


def test_nothing_writes_to_a_portfolio_table():
    """The other half. A module could write to a table another one created, and
    an INSERT is what actually loses the guarantee.

    The retired `*_pre69` / `*_pre72` archives are a different thing and are
    named differently on purpose - they hold records from before this system
    stopped storing portfolios, and TQ-71 disposes of them."""
    offenders = []
    pattern = re.compile(
        r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+"
        r"(portfolios|portfolio_holdings)\b", re.IGNORECASE)
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob("*.py")):
            text = " ".join(path.read_text(encoding="utf-8").split())
            found = pattern.search(text)
            if found:
                offenders.append(
                    f"{tree}/{path.relative_to(ROOT / tree)}: {found.group(0)}")

    assert not offenders, (
        "these write to a portfolio table:\n  " + "\n  ".join(offenders)
        + "\nNothing about a client's positions is written down (§111)."
    )


def test_the_backend_database_has_no_portfolio_tables(conn):
    """Asserted against a real, fully-initialised database rather than only
    against the source, because `init_schema` is where a table would come back
    and a source scan reads intentions."""
    tables = {row["name"] for row in conn.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert "portfolios" not in tables
    assert "portfolio_holdings" not in tables
    # Fails loudly if the fixture ever stops building a real database and starts
    # passing vacuously.
    assert "agent_registry" in tables


def test_the_gateway_database_has_no_portfolio_tables(gateway_conn):
    tables = {row["name"] for row in gateway_conn.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert "portfolios" not in tables
    assert "portfolio_holdings" not in tables
    assert {"sessions", "clients"} <= tables


def test_no_module_offers_to_store_a_holding():
    """Read from the function names rather than from SQL, because the second way
    a store comes back is a helper called `save_holdings` that writes to a file
    or a cache rather than to a table.

    `record` is the name the old one had, and it is the name the new one would
    have."""
    forbidden = {"record_holding", "save_holdings", "store_holdings",
                 "cache_holdings", "persist_holdings"}
    offenders = []
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob("*.py")):
            parsed = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(parsed):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and node.name in forbidden:
                    offenders.append(
                        f"{tree}/{path.relative_to(ROOT / tree)}: {node.name}")

    assert not offenders, (
        "these offer to store holdings:\n  " + "\n  ".join(offenders)
        + "\nPositions live for the length of a session and are discarded (§115)."
    )


def test_the_holdings_module_offers_no_persistence():
    """The module kept its name and lost its custody. Asserted by absence,
    because the functions that went are the ones a caller would reach for
    first."""
    for gone in ("record", "listing", "one", "forget", "forget_all", "SCHEMA",
                 "migrate_client_holdings", "migrate_holding_field_names"):
        assert not hasattr(holdings, gone), f"holdings.{gone} came back"

    # And the part that was never storage is untouched.
    assert callable(holdings.concentration)


def test_the_portfolios_module_offers_no_custody():
    for gone in ("SCHEMA", "create", "resolve", "owned", "listing", "primary_for",
                 "archive", "mark_synced", "purge_owner", "record_source",
                 "simulated_client_ids", "simulated_portfolio_ids"):
        assert not hasattr(portfolios, gone), f"portfolios.{gone} came back"

    assert callable(portfolios.for_client)
    assert callable(portfolios.is_priced)
