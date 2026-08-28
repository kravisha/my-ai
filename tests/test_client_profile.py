"""The client profile, and the boundary a watchlist sits on
(TQ-98; addendum 51 §4, §13, §15; owner direction §111;
docs/SPEC_RECONCILIATION.md §140 §5, §143).

This is the first client data the *backend* keeps. Everything else client-scoped
there disappears on its own — a request when claimed, a report when collected, a
session's rows on disconnect (§117) — and a preference discarded at disconnect is
not a preference, it is a question asked every session.

It is **not** the first client data the system keeps, which is a claim this file
made and then disproved: see
`test_the_client_scoped_stores_are_the_three_that_are_meant_to_exist`.

So the tests that matter are not the ones showing a profile round-trips. They are
the ones showing **what cannot be stored next to it**, because the way §111 gets
undone is not an argument against it. It is somebody storing helpfully nearby.

`test_the_watchlist_cannot_grow_a_column_that_holds_a_position` is the re-aimed
tripwire (§105: re-aimed, never deleted). §111's guards ask whether a
`portfolios` table exists. They will go on passing forever while a
`client_watchlist` grows a `quantity` column, because the danger moved the day
this module was written.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from backend import client_profile as profile, portfolios

ROOT = Path(__file__).resolve().parent.parent
TREES = ("app", "backend", "agents", "simulation")

CLIENT = portfolios.for_client("avery")
OTHER = portfolios.for_client("blake")


# --- the re-aimed tripwire: what may never sit beside a symbol -------------------------

def test_the_watchlist_cannot_grow_a_column_that_holds_a_position(conn):
    """**The guarantee, and it is structural rather than a convention.**

    A watchlist entry is a symbol and nothing else, so a watchlist assembled
    entirely from a fetched portfolio is still not a portfolio: the facts that
    make positions worth protecting — how much, at what price, where — have
    nowhere to go.

    Asserted against the real initialised schema rather than the source, because
    `init_schema` is where a column would actually arrive."""
    columns = {row["name"] for row in conn.fetchall("PRAGMA table_info(client_watchlist)")}
    forbidden = {
        "quantity", "qty", "shares", "units", "cost_basis", "cost", "price",
        "value", "market_value", "account", "account_id", "broker", "position",
        "as_of", "currency", "weight", "allocation",
    }
    assert not (columns & forbidden), (
        f"client_watchlist has columns that can hold a position: "
        f"{sorted(columns & forbidden)}. A symbol the client typed is a preference; a "
        f"symbol with a quantity beside it is a holding, and this system does not store "
        f"holdings (SPEC_RECONCILIATION §111)."
    )
    assert columns == {"owner_type", "owner_id", "symbol", "source", "stated_at"}, (
        "the watchlist gained a column. Every addition here is a step toward a portfolio "
        "table with a different name — say why in SPEC_RECONCILIATION before widening it."
    )


def test_the_preference_vocabulary_is_closed_and_holds_no_position_field(conn):
    """The other half of the same guard. An open key-value store makes every
    other protection here decorative, because nothing then stops
    `set_preference(owner, "holdings", ...)`."""
    for smuggled in ("holdings", "positions", "portfolio", "quantity", "accounts"):
        with pytest.raises(profile.ProfileRefused) as refusal:
            profile.set_preference(conn, CLIENT, key=smuggled, value="x")
        assert "closed on purpose" in str(refusal.value)


def test_the_preference_list_is_addendum_51_section_15_and_nothing_else():
    """One readable list of everything this system will remember about a person.
    A test over it means widening the list is a deliberate act with a diff."""
    assert profile.PREFERENCES == (
        "preferred_name", "preferred_language", "preferred_tone", "preferred_pacing",
        "preferred_humor", "preferred_visual_style", "preferred_persona_archetype",
        "preferred_topics", "disliked_topics", "explanation_depth", "correction_style",
        "interruption_tolerance", "conversation_style", "entertainment_preferences",
        "consented_reference_material", "accessibility_preferences",
    )


def test_nothing_that_can_read_positions_can_write_a_profile():
    """**Prevention by absence.** Deriving a watchlist from a fetched portfolio
    needs one module able to do both, and this asserts no such module exists —
    in either direction, because either import creates it.

    The `source` column would not catch that: a derived symbol passed as
    `client_stated` is accepted, and saying so is part of the guarantee (§110
    §4.3's rule about not claiming the stronger property)."""
    position_modules = {"holdings", "consolidation", "portfolio_providers"}

    def imports_of(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[-1])
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                names.update(alias.name.split(".")[-1] for alias in node.names)
        return names

    reached = imports_of(ROOT / "backend" / "client_profile.py") & position_modules
    assert not reached, (
        f"backend/client_profile.py imports {sorted(reached)}; a module that can read "
        f"positions and write a profile is one line away from deriving a watchlist."
    )

    for name in position_modules:
        path = ROOT / "backend" / f"{name}.py"
        if not path.exists():
            continue
        assert "client_profile" not in imports_of(path), (
            f"backend/{name}.py imports client_profile; the same module would then be "
            f"able to read positions and write a watchlist."
        )


def test_the_client_scoped_stores_are_the_three_that_are_meant_to_exist():
    """Every table holding a client's data past a session, enumerated with what
    it is for. A new one appearing is the shape §111 was undone by once already —
    a store deleted in one increment and re-added in another under a helpful name.

    **This test found something on its first run.** It was written asserting two
    tables, on the belief that TQ-98 introduced the first persisted client data.
    `client_agents` has existed since addendum 43 §16 and holds the named
    representative a client meets, plus when they were last here and how many
    times. The claim was wrong and the guard is what said so.

    The three are not equivalent and the difference is the boundary:

    - `client_agents` (gateway.db) — **the system's record of serving somebody.**
      The Gateway assigns the name; the client never stated it.
    - `client_preferences` (financial_intelligence.db) — **what the client said.**
    - `client_watchlist` (financial_intelligence.db) — symbols the client typed,
      and nothing else about them.
    """
    declared = {}
    pattern = re.compile(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(client_\w+)", re.IGNORECASE)
    for tree in TREES + ("gateway",):
        for path in sorted((ROOT / tree).rglob("*.py")):
            for name in pattern.findall(path.read_text(encoding="utf-8")):
                declared[name.lower()] = f"{tree}/{path.name}"

    assert set(declared) == {"client_agents", "client_preferences", "client_watchlist"}, (
        f"client-scoped tables changed: {sorted(declared)}. Each of these persists past a "
        f"session, which is the exception §111 grants for what a client stated and for the "
        f"record of having served them — and for nothing else. Adding one means saying in "
        f"SPEC_RECONCILIATION which of those two it is."
    )
    assert declared["client_agents"].startswith("gateway/"), (
        "client_agents moved out of the Gateway. Identity is the Gateway's and business "
        "logic is the backend's (§109); a client's representative is identity."
    )


# --- ownership is evidence ------------------------------------------------------------

def test_a_profile_cannot_be_reached_with_a_client_id(conn):
    """A name is a claim; an `OwnerContext` was built server-side from the session
    (addendum 44 §9.2). Accepting the string would let any agent read or rewrite
    any client's profile by knowing who they are."""
    for impostor in ("avery", None, {"owner_id": "avery"}):
        with pytest.raises(profile.ProfileRefused) as refusal:
            profile.preferences(conn, impostor)
        assert "not a proof" in str(refusal.value)


def test_one_clients_profile_is_not_anothers(conn):
    profile.set_preference(conn, CLIENT, key="preferred_tone", value="dry")
    profile.add_to_watchlist(conn, CLIENT, symbol="SYN1")
    assert profile.preferences(conn, OTHER) == {}
    assert profile.watchlist(conn, OTHER) == []


# --- the watchlist source --------------------------------------------------------------

def test_only_a_client_stated_symbol_enters_a_watchlist(conn):
    """The convention, and the refusal names its reason rather than being
    identical: there is one legitimate source, and a caller holding a derived
    symbol needs to know that carrying it here is what is being refused."""
    for derived in ("fetched", "derived", "consolidation", "broker"):
        with pytest.raises(profile.ProfileRefused) as refusal:
            profile.add_to_watchlist(conn, CLIENT, symbol="SYN1", source=derived)
        assert "does not store" in str(refusal.value)
    assert profile.watchlist(conn, CLIENT) == []


def test_a_watchlist_holds_symbols_and_not_prose(conn):
    """A field that took arbitrary text is a field somebody puts a note in, and
    a note about a holding is a holding."""
    for not_a_symbol in ("100 shares of SYN1", "", "   ", "SYN1 @ $42.10", "x" * 40):
        with pytest.raises(profile.ProfileRefused):
            profile.add_to_watchlist(conn, CLIENT, symbol=not_a_symbol)


def test_a_watchlist_symbol_is_stored_once(conn):
    profile.add_to_watchlist(conn, CLIENT, symbol="syn1")
    profile.add_to_watchlist(conn, CLIENT, symbol="SYN1")
    assert profile.watchlist(conn, CLIENT) == ["SYN1"]


# --- preferences, and the absence of defaults -------------------------------------------

def test_a_preference_nobody_stated_is_absent_and_never_a_default(conn):
    """§100, §104, §118, §132 — and it matters more here than usual. A profile
    returning `preferred_tone='neutral'` for somebody who never said would have
    the agent acting on a preference the client does not hold, indistinguishably
    from one they do."""
    assert profile.preferences(conn, CLIENT) == {}
    assert "preferred_tone" in profile.unstated(conn, CLIENT)

    profile.set_preference(conn, CLIENT, key="preferred_tone", value="dry")
    assert profile.preferences(conn, CLIENT) == {"preferred_tone": "dry"}
    assert "preferred_tone" not in profile.unstated(conn, CLIENT)
    assert len(profile.unstated(conn, CLIENT)) == len(profile.PREFERENCES) - 1


def test_unstated_is_named_so_an_agent_can_ask(conn):
    """Addendum 49's patience rules want an Usher that finds out. A system that
    only exposed what it knew would leave finding out to a guess."""
    assert set(profile.unstated(conn, CLIENT)) == set(profile.PREFERENCES)


def test_a_list_preference_keeps_its_shape(conn):
    profile.set_preference(conn, CLIENT, key="preferred_topics",
                           value=["markets", "science", " "])
    assert profile.preferences(conn, CLIENT)["preferred_topics"] == ["markets", "science"]
    with pytest.raises(profile.ProfileRefused):
        profile.set_preference(conn, CLIENT, key="preferred_topics", value="markets")
    with pytest.raises(profile.ProfileRefused):
        profile.set_preference(conn, CLIENT, key="preferred_tone", value=["dry", "warm"])


def test_restating_a_preference_replaces_it(conn):
    profile.set_preference(conn, CLIENT, key="preferred_tone", value="dry")
    profile.set_preference(conn, CLIENT, key="preferred_tone", value="warm")
    assert profile.preferences(conn, CLIENT) == {"preferred_tone": "warm"}


def test_an_empty_value_is_refused_because_it_is_not_a_removal(conn):
    """An empty string and an unstated preference are different facts, and a
    setter that accepted the first as the second would lose the difference."""
    with pytest.raises(profile.ProfileRefused) as refusal:
        profile.set_preference(conn, CLIENT, key="preferred_tone", value="   ")
    assert "different facts" in str(refusal.value)


def test_forgetting_a_preference_returns_it_to_unstated(conn):
    profile.set_preference(conn, CLIENT, key="preferred_tone", value="dry")
    profile.forget_preference(conn, CLIENT, key="preferred_tone")
    assert profile.preferences(conn, CLIENT) == {}
    assert "preferred_tone" in profile.unstated(conn, CLIENT)


# --- leaving ----------------------------------------------------------------------------

def test_a_client_can_be_forgotten_entirely(conn):
    """**Required rather than convenient.** Every other client store here
    disappears on its own; this one persists by design, so it is the first client
    data that would otherwise outlive the client's interest in it."""
    profile.set_preference(conn, CLIENT, key="preferred_tone", value="dry")
    profile.set_preference(conn, CLIENT, key="preferred_topics", value=["markets"])
    profile.add_to_watchlist(conn, CLIENT, symbol="SYN1")
    profile.set_preference(conn, OTHER, key="preferred_tone", value="warm")

    removed = profile.forget_everything(conn, CLIENT)
    assert removed == {"client_preferences": 2, "client_watchlist": 1}
    assert profile.preferences(conn, CLIENT) == {}
    assert profile.watchlist(conn, CLIENT) == []
    assert profile.preferences(conn, OTHER) == {"preferred_tone": "warm"}, (
        "forgetting one client took another's profile with it")


def test_forgetting_reports_what_it_removed(conn):
    """A caller told *done* cannot tell a successful deletion from a mistyped
    owner, and those need different next actions."""
    assert profile.forget_everything(conn, CLIENT) == {
        "client_preferences": 0, "client_watchlist": 0}


# --- what an agent is told ---------------------------------------------------------------

def test_the_summary_says_what_is_not_held(conn):
    """Said every time. This is the one client store that persists, and a reader
    should never have to infer the boundary from what happens to be absent."""
    profile.set_preference(conn, CLIENT, key="preferred_tone", value="dry")
    profile.add_to_watchlist(conn, CLIENT, symbol="SYN1")
    summary = profile.summary(conn, CLIENT)

    assert summary["stated"] == {"preferred_tone": "dry"}
    assert summary["watchlist"] == ["SYN1"]
    assert "preferred_topics" in summary["unstated"]
    assert any("cost bases" in line for line in summary["not_held"])
    assert any("beyond the symbol itself" in line for line in summary["not_held"])
