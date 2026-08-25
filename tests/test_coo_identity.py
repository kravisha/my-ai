"""Kumbhakarnan, as state rather than as a string (backend/coo_identity.py;
addendum 42 §3, §4, §11, §19, §20; TQ-35, SPEC_RECONCILIATION §88).

The requirement this suite exists for is one sentence of addendum 42 §19:
"Changing implementation versions must not silently replace the COO's
identity." Every assertion here is a way that could go wrong.

The interesting ones are not about storing a name. They are about the *seams*:
a second process starting at the same moment, a build that reads state written
by a newer one, a redeploy that arrives looking like a change of person, and an
interface that introduces a COO the database has never heard of.
"""

import json

import pytest

from backend import coo_identity, fi_db
from backend.coo_identity import (
    CHANGE_CREATED, CHANGE_RENAMED, CHANGE_SOFTWARE_VERSION,
    DEFAULT_NAME, IdentityFromTheFuture, UnknownChange,
)


@pytest.fixture
def conn(tmp_path):
    connection = fi_db.get_connection(str(tmp_path / "fi.db"))
    fi_db.init_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


# --- the identity exists, once ---------------------------------------------------


def test_the_coo_is_created_with_a_name_and_a_birthday(conn):
    identity = coo_identity.load(conn)
    assert identity is not None, "init_schema should have created the COO"
    assert identity["name"] == DEFAULT_NAME
    assert identity["role"] == "coo"
    assert identity["created_at"]
    assert identity["coo_id"].startswith("coo-")


def test_ensure_is_idempotent_across_calls(conn):
    """`fi_db.init_schema` runs in every agent process, so "created once" has to
    survive being asked repeatedly rather than being guarded by an import."""
    first = coo_identity.ensure(conn)
    for _ in range(5):
        again = coo_identity.ensure(conn)
        assert again["coo_id"] == first["coo_id"]
        assert again["created_at"] == first["created_at"]

    rows = conn.fetchall("SELECT coo_id FROM coo_identity")
    assert len(rows) == 1, "there must be exactly one Kumbhakarnan"


def test_two_processes_starting_at_once_produce_one_coo(conn, tmp_path):
    """The real shape of the race: two agents calling init_schema against the
    same file. Guarded by the UNIQUE on organization_id and a re-read, rather
    than a check-then-write that the second process could interleave with."""
    other = fi_db.get_connection(str(tmp_path / "fi.db"))
    try:
        fi_db.init_schema(other)
        assert coo_identity.ensure(other)["coo_id"] == coo_identity.ensure(conn)["coo_id"]
        assert len(conn.fetchall("SELECT coo_id FROM coo_identity")) == 1
    finally:
        other.close()


# --- §19: a new build must not become a new person -------------------------------


def test_a_software_upgrade_carries_the_identity_rather_than_replacing_it(conn, monkeypatch):
    """The requirement itself. The COO's id, name and creation moment survive a
    change of implementation; only the observation of *which* build is running
    moves."""
    original = coo_identity.ensure(conn)

    monkeypatch.setattr(coo_identity, "code_version", lambda: "deadbeef" * 5)
    upgraded = coo_identity.ensure(conn)

    assert upgraded["coo_id"] == original["coo_id"]
    assert upgraded["name"] == original["name"]
    assert upgraded["created_at"] == original["created_at"]
    assert upgraded["software_version_at_creation"] == original["software_version_at_creation"]
    assert upgraded["software_version_last_seen"] == "deadbeef" * 5


def test_carrying_the_identity_forward_is_recorded(conn, monkeypatch):
    """§15 wants an audit trail. It is also what lets the system *state* that
    this is the same COO rather than merely assert it."""
    coo_identity.ensure(conn)
    monkeypatch.setattr(coo_identity, "code_version", lambda: "cafe" * 10)
    coo_identity.ensure(conn)

    changes = [entry["change"] for entry in coo_identity.history(conn)]
    assert changes == [CHANGE_CREATED, CHANGE_SOFTWARE_VERSION]
    assert coo_identity.summary(conn)["software_versions_survived"] == 1


def test_an_unchanged_build_writes_no_history(conn):
    """Otherwise every process start would add a row and the audit trail would
    be noise. History rows have to mean something to be worth reading."""
    coo_identity.ensure(conn)
    for _ in range(4):
        coo_identity.ensure(conn)
    assert [e["change"] for e in coo_identity.history(conn)] == [CHANGE_CREATED]


# --- §4: three versions, never collapsed ------------------------------------------


def test_software_drift_is_not_a_migration(conn, monkeypatch):
    """§4: "Do not assume software version and persistence schema version are
    the same." A deploy changes one and not the other, and reading the first as
    the second is how a routine upgrade starts looking like a data problem."""
    coo_identity.ensure(conn)
    monkeypatch.setattr(coo_identity, "code_version", lambda: "0123456789" * 4)

    report = coo_identity.versions(conn)
    assert report["software"]["changed"] is True
    assert report["schema"]["stored"] == report["schema"]["code"]
    assert report["migration_needed"] is False, "a new build is not a schema migration"


def test_a_stale_schema_is_reported_as_needing_migration(conn):
    """What TQ-36's pipeline will read. Asserted now so that the field exists
    and means something before anything depends on it."""
    conn.execute("UPDATE coo_identity SET schema_version = 0")
    assert coo_identity.versions(conn)["migration_needed"] is True


def test_state_from_a_newer_build_is_refused_not_overwritten(conn):
    """§22: a snapshot that fails validation is preserved for diagnosis, never
    destroyed. Silently recreating the COO because this build could not read his
    row would be the worst thing this module could do - it is precisely the
    silent replacement §19 forbids, arrived at by a different route."""
    conn.execute("UPDATE coo_identity SET schema_version = ?", (coo_identity.SCHEMA_VERSION + 1,))

    with pytest.raises(IdentityFromTheFuture):
        coo_identity.load(conn)

    row = conn.fetchone("SELECT name, schema_version FROM coo_identity")
    assert row["name"] == DEFAULT_NAME, "the stored identity must be left untouched"
    assert row["schema_version"] == coo_identity.SCHEMA_VERSION + 1


def test_versions_before_any_identity_exists_says_so(conn):
    conn.execute("DELETE FROM coo_identity")
    report = coo_identity.versions(conn)
    assert report["exists"] is False
    assert report["software"]["stored"] is None
    assert report["migration_needed"] is False


# --- renaming is possible, but never silent ---------------------------------------


def test_a_rename_is_deliberate_reasoned_and_recorded(conn):
    """§19's requirement is not that the name is immutable - it is that it never
    changes by accident. So the path exists, and it costs a reason."""
    coo_identity.rename(conn, "Kumbhakarnan the Second", reason="owner decision, 2026-08-25")

    assert coo_identity.load(conn)["name"] == "Kumbhakarnan the Second"
    latest = coo_identity.history(conn)[-1]
    assert latest["change"] == CHANGE_RENAMED
    assert "owner decision" in latest["detail"]


def test_renaming_without_a_reason_is_refused(conn):
    """An unexplained entry in the history would satisfy the letter of "not
    silent" and miss the point."""
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="reason"):
            coo_identity.rename(conn, "Someone Else", reason=bad)
    assert coo_identity.load(conn)["name"] == DEFAULT_NAME


def test_a_blank_name_is_refused(conn):
    with pytest.raises(ValueError):
        coo_identity.rename(conn, "   ", reason="a real reason")


def test_renaming_to_the_same_name_writes_no_history(conn):
    coo_identity.rename(conn, DEFAULT_NAME, reason="no-op")
    assert [e["change"] for e in coo_identity.history(conn)] == [CHANGE_CREATED]


def test_an_unknown_change_kind_is_refused(conn):
    """Fail closed, the house rule for anything read back and reasoned about: a
    silently accepted typo is a gap in an audit trail that still looks
    complete."""
    identity = coo_identity.load(conn)
    with pytest.raises(UnknownChange):
        coo_identity._record(conn, identity["coo_id"], "vanished", "how?")


# --- §20 and §11: specified, not invented ----------------------------------------


def test_the_visual_identity_carries_its_own_constraint(conn):
    """§20 forbids copying a specific film, television, comic, game or
    commercial depiction. That constraint is stored *with* the identity rather
    than left in a document, so whoever eventually renders the presenter reads
    it from the state they are rendering."""
    visual = coo_identity.load(conn)["visual_identity"]
    assert "original visual interpretation" in visual["direction"]
    assert "distinctive crown" in visual["direction"]
    must_not = visual["must_not"].lower()
    for medium in ("film", "television", "comic", "game", "commercial"):
        assert medium in must_not
    assert visual["rendered"] is False, "no animated presenter exists yet"


def test_nothing_about_the_identity_is_fabricated(conn):
    """§11: structural defaults are fine, invented facts are not.

    The personality, voice and visual entries are the owner's own
    specifications and each carries the section it came from. Relationship
    history starts empty because none has been recorded - which is accurate,
    and different from the `needs_reconstruction` vocabulary §11 reserves for
    facts that were *lost*."""
    identity = coo_identity.load(conn)
    assert identity["relationship_history"] == []
    for field in ("personality", "voice_identity", "visual_identity"):
        assert identity[field]["source"], f"{field} does not say where it came from"


def test_the_software_version_is_never_guessed(conn, monkeypatch):
    """`code_version()`'s contract is "a true answer or 'unknown'". A fabricated
    version on an identity record would be a lie in the one place built to
    outlive every other record."""
    monkeypatch.setattr(coo_identity, "code_version", lambda: "unknown")
    conn.execute("DELETE FROM coo_identity")
    identity = coo_identity.ensure(conn)
    assert identity["software_version_at_creation"] == "unknown"


# --- the integrations that stop this being an unused table ------------------------


def test_the_name_is_reserved_so_no_agent_can_be_handed_it(conn):
    """A real collision, closed by the same mechanism the CEO name uses: without
    the reservation the pool could assign "Kumbhakarnan" to an ordinary agent
    and the organization would contain two of him."""
    row = conn.fetchone("SELECT reserved FROM agent_names WHERE name = ?", (DEFAULT_NAME,))
    assert row is not None and row["reserved"] == 1

    # Drained rather than sampled: with 40 names in the pool, handing out five
    # and finding no collision would prove nothing. Every name the pool will
    # ever give out is checked.
    handed_out = []
    while True:
        name = fi_db.assign_agent_name(conn, f"dummy-{len(handed_out)}", role="dummy")
        if name is None:
            break
        handed_out.append(name)
    assert handed_out, "the pool handed out nothing, so this test proved nothing"
    assert DEFAULT_NAME not in handed_out


def test_a_rename_moves_the_reservation(conn):
    """Otherwise the pool would go on protecting a name nobody answers to while
    handing out the one the COO now uses."""
    coo_identity.rename(conn, "Vibhishana", reason="owner decision")
    fi_db.init_schema(conn)   # what the next process start does

    row = conn.fetchone("SELECT reserved FROM agent_names WHERE name = 'Vibhishana'")
    assert row is not None and row["reserved"] == 1


def test_the_coo_speaks_under_the_persisted_name(conn):
    """The prompt is built from the stored identity, so renaming the COO renames
    the one answering rather than only the label above the answer."""
    from backend import coo_chat

    system, _ = coo_chat.prepare(conn, "what is happening?")
    assert DEFAULT_NAME in system

    coo_identity.rename(conn, "Vibhishana", reason="owner decision")
    system, _ = coo_chat.prepare(conn, "what is happening?")
    assert "Vibhishana" in system


def test_the_summary_is_what_a_surface_needs_and_no_more(conn):
    """The console renders from this. It carries identity and presentation, and
    deliberately not the internals a page has no business holding."""
    summary = coo_identity.summary(conn)
    assert summary["exists"] is True
    assert summary["name"] == DEFAULT_NAME
    assert "visual_identity" in summary and "voice_identity" in summary
    assert "personality" not in summary, "the persona is not the console's business"
    assert "relationship_history" not in summary


def test_the_summary_says_so_when_there_is_no_identity(conn):
    """Never a fabricated name: a surface must be able to tell a fresh database
    from a restored one."""
    conn.execute("DELETE FROM coo_identity")
    summary = coo_identity.summary(conn)
    assert summary["exists"] is False and summary["name"] is None
    assert summary["reason"]


def test_stored_json_is_valid_json(conn):
    """Cheap, and it catches the one way a JSON column silently rots: something
    writing a Python repr into it."""
    row = conn.fetchone(
        "SELECT personality, voice_identity, visual_identity, preferences, "
        "relationship_history FROM coo_identity")
    for column in row.keys():
        json.loads(row[column])
