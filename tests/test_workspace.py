"""The living workspace (backend/workspace.py; addendum 40 §5, §15;
TQ-31, SPEC_RECONCILIATION §83).

The centrepiece is §5.3, the sharpest requirement in the specification: "If
the user types half a sentence and the machine crashes before Send, the same
text must be present in the same field after recovery." It is tested here the
only honest way — write the draft, throw the connection away without any
shutdown, reopen the database, and look.

Everything else follows from the same idea: saving is continuous rather than
on close (§5.1), a write is one transaction so a torn save cannot destroy the
last good state (§15), and a workspace that cannot be read must not stop the
console from opening.
"""

import json

import pytest

from backend import fi_db, workspace


@pytest.fixture
def db(tmp_path):
    """File-backed, because half of this suite is about surviving a process
    that never got to clean up - which an in-memory database cannot express."""
    path = tmp_path / "fi.db"
    conn = fi_db.get_connection(str(path))
    fi_db.init_schema(conn)
    yield conn, path
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


# --- §5.3, the requirement that drives the design ---------------------------------


def test_a_half_typed_sentence_survives_a_crash(db):
    """The specification's own acceptance test, run literally.

    No clean shutdown, no flush, no close: the connection is abandoned exactly
    as a killed process would abandon it, and a *new* connection to the same
    file has to find the text."""
    conn, path = db
    workspace.save(conn, {"drafts": {"cooQuestion": "what is happening with Expl"}})

    del conn                                   # the crash: nothing is closed

    recovered = fi_db.get_connection(str(path))
    try:
        assert workspace.drafts(recovered)["cooQuestion"] == "what is happening with Expl"
    finally:
        recovered.close()


def test_the_draft_comes_back_in_the_same_field(db):
    """"the same text must be present in the same field" - the field
    identity matters, not just the text."""
    conn, _ = db
    workspace.save(conn, {"drafts": {"cooQuestion": "half a question", "notes": "and a note"}})
    assert workspace.drafts(conn) == {"cooQuestion": "half a question", "notes": "and a note"}


def test_each_checkpoint_replaces_the_last_rather_than_accumulating(db):
    """Continuous saving (§5.1) must not mean an unbounded table."""
    conn, _ = db
    for i in range(25):
        workspace.save(conn, {"drafts": {"cooQuestion": f"typing {i}"}})
    assert conn.fetchone("SELECT COUNT(*) AS n FROM workspace_state")["n"] == 1
    assert workspace.drafts(conn)["cooQuestion"] == "typing 24"
    # The revision count is how an operator can see saving is happening at all.
    assert workspace.load(conn)["revision"] == 25


# --- what else must persist (§5.2) ------------------------------------------------


def test_view_state_round_trips(db):
    conn, _ = db
    state = {
        "activeTab": "chatterbox", "source": "explorer-1", "attention": True,
        "follow": False, "language": "ta", "voice": "Some Voice", "speak": True,
        "feedScroll": 4210, "drafts": {"cooQuestion": ""},
    }
    workspace.save(conn, state)
    restored = workspace.load(conn)
    assert restored["restored"] is True
    assert restored["workspace"] == state


def test_surfaces_are_separate_workspaces(db):
    """40 §2: one organization, many windows. The Gateway's workspace is not
    the console's, and neither should overwrite the other."""
    conn, _ = db
    workspace.save(conn, {"activeTab": "finance"}, surface="console")
    workspace.save(conn, {"activeTab": "inbox"}, surface="gateway")
    assert workspace.load(conn, surface="console")["workspace"]["activeTab"] == "finance"
    assert workspace.load(conn, surface="gateway")["workspace"]["activeTab"] == "inbox"


# --- §15: recovery must be honest about what it recovered -------------------------


def test_a_fresh_surface_says_so_rather_than_pretending(db):
    conn, _ = db
    state = workspace.load(conn)
    assert state["restored"] is False
    assert state["workspace"] == {}
    assert "no workspace" in state["reason"]


def test_unreadable_state_starts_fresh_without_breaking_the_console(db):
    """The operator loses a tab selection, not their application."""
    conn, _ = db
    workspace.save(conn, {"activeTab": "finance"})
    conn.execute("UPDATE workspace_state SET payload = ? WHERE surface = ?",
                 ("{not json", workspace.SURFACE_CONSOLE))

    state = workspace.load(conn)
    assert state["restored"] is False
    assert state.get("corrupt") is True
    assert state["workspace"] == {}          # usable, not an exception


def test_state_from_a_newer_build_is_refused_not_discarded(db):
    """§15's forward-migration metadata, used. Reading unknown state
    optimistically is how an upgrade silently eats a workspace - and
    *deleting* it would be worse."""
    conn, _ = db
    workspace.save(conn, {"activeTab": "finance"})
    conn.execute("UPDATE workspace_state SET schema_version = ? WHERE surface = ?",
                 (workspace.SCHEMA_VERSION + 5, workspace.SURFACE_CONSOLE))

    state = workspace.load(conn)
    assert state["restored"] is False
    assert state.get("stale_build") is True
    assert "upgrade" in state["reason"]
    # Still there, untouched, for the build that understands it.
    assert conn.fetchone("SELECT payload FROM workspace_state")["payload"]


def test_a_torn_write_cannot_destroy_the_last_good_workspace(db):
    """§15: "atomic checkpoints ... so a partial save cannot corrupt the last
    known good state". A save that raises must leave the previous one
    intact."""
    conn, _ = db
    workspace.save(conn, {"activeTab": "finance", "drafts": {"cooQuestion": "keep me"}})

    with pytest.raises(workspace.WorkspaceTooLarge):
        workspace.save(conn, {"drafts": {"cooQuestion": "x" * (workspace.MAX_PAYLOAD_BYTES + 10)}})

    survived = workspace.load(conn)
    assert survived["restored"] is True
    assert survived["workspace"]["drafts"]["cooQuestion"] == "keep me"


def test_a_workspace_is_not_a_document_store(db):
    conn, _ = db
    with pytest.raises(workspace.WorkspaceTooLarge, match="not documents"):
        workspace.save(conn, {"blob": "x" * (workspace.MAX_PAYLOAD_BYTES + 1)})
    with pytest.raises(ValueError):
        workspace.save(conn, ["not", "an", "object"])


def test_clearing_is_deliberate_and_reports_whether_there_was_one(db):
    conn, _ = db
    assert workspace.clear(conn) is False
    workspace.save(conn, {"activeTab": "alerts"})
    assert workspace.clear(conn) is True
    assert workspace.load(conn)["restored"] is False


# --- §5.4: declarative only -------------------------------------------------------


def test_the_payload_stays_small_enough_to_checkpoint_continuously(db):
    """§5.4 keeps only what cannot be reconstructed. A realistic workspace
    should be well under a kilobyte, which is what makes saving every
    keystroke-ish affordable."""
    conn, _ = db
    realistic = {
        "activeTab": "newsroom", "source": "", "attention": False, "follow": True,
        "language": "en-IN", "voice": "Microsoft David - English (United States)",
        "speak": False, "feedScroll": 1200,
        "drafts": {"cooQuestion": "what changed while I was away?"},
        "savedAt": "2026-08-25T12:00:00+00:00",
    }
    assert workspace.save(conn, realistic)["bytes"] < 1024
