"""The universe becomes authoritative-by-assertion.

security_universe was fully wired (versioned, seeded, queryable) and consumed
by nothing, while a hardcoded peer-group list in agents/discovery_config.py
drove what Explorer actually scans - two parallel universes, one of them
decorative. These tests are the minimal true linkage: the universe is
authoritative, the peer groups are a *grouping* of it, and every universe
member has an entity the moment the universe is seeded.
"""

from backend import fi_db, identifiers
from agents import discovery_config


def test_peer_groups_are_a_grouping_of_the_universe(conn):
    """security_universe was fully wired and consumed by nothing while a
    hardcoded peer-group list drove what Explorer actually scans - two
    parallel universes, one of them decorative. This containment is the
    minimal true linkage: the universe is authoritative, the peer groups are a
    grouping of it, and a symbol scanned but not in the universe fails here
    instead of drifting silently. Rewiring Explorer to read the universe
    directly is peer-group design work (co-occurrence semantics live in the
    groups), deliberately not done here."""
    universe = {row["symbol"] for row in fi_db.list_security_universe(conn)}

    assert set(discovery_config.PEER_GROUP_SECURITIES) <= universe


def test_every_universe_member_has_an_entity(conn):
    """Every universe member gets an entity the moment the universe is seeded,
    so symbol-space and entity-space cannot drift apart at the root."""
    for symbol in fi_db.SECURITY_UNIVERSE_SEED:
        assert identifiers.resolve(conn, "symbol", symbol) is not None


def test_an_interrupted_entities_rebuild_is_completed_not_stranded(tmp_path):
    """The crash window the clean-path migration left open. Database.execute
    commits per statement, so the rename-recreate-copy-drop is four
    transactions - a death between any two leaves entities_legacy_check
    orphaned while the guard sees a fresh CHECK-less table and skips,
    stranding every row out of view. Recovery runs before detection, so the
    sequence is resumable from any crash point."""
    import sqlite3

    from backend import identifiers
    from backend.db import Database

    db_path = tmp_path / "interrupted.db"
    raw = sqlite3.connect(str(db_path))
    # The exact post-crash state: a fresh new-shape entities (empty) beside the
    # renamed holding pen still holding the data.
    raw.execute(
        "CREATE TABLE entities_legacy_check (entity_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, "
        "display_name TEXT, created_at TEXT NOT NULL, note TEXT, schema_version INTEGER NOT NULL DEFAULT 1)"
    )
    raw.execute(
        "INSERT INTO entities_legacy_check VALUES ('JE-000001', 'security', 'Stranded Corp', 'x', NULL, 1)"
    )
    raw.commit()
    raw.close()

    conn = Database(db_path)
    identifiers.init_schema(conn)

    recovered = identifiers.get_entity(conn, "JE-000001")
    assert recovered is not None and recovered["display_name"] == "Stranded Corp"
    assert conn.fetchone(
        "SELECT 1 FROM sqlite_master WHERE name = 'entities_legacy_check'"
    ) is None, "the holding pen is dropped once its rows are safe"
    conn.close()
