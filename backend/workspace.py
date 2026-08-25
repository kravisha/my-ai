"""The Workspace Manager (addendum 40 §5, §6.2; TASK_QUEUE TQ-31,
docs/SPEC_RECONCILIATION.md §83).

What the operator had open, and what they had half-written. §6.2 gives this
component one job: "owns user-visible tabs, panels, view state, drafts, and
resume position."

## Server-side, because the workspace is part of the organization

It would be easier to keep this in the browser's `localStorage`, and wrong.
Addendum 40 §4.1 makes rehydrating the workspace a step of *the COO's* wake
sequence, §20's reference experience has the COO greeting an operator whose
half-typed question is still there, and §5.2 lists the workspace beside the
agent registry as state the system restores. A workspace only the browser
knows is a workspace the COO cannot speak about, cannot restore onto a second
machine, and that `continuity` does not back up.

## The draft requirement is the sharpest thing in the specification

§5.3: "If the user types half a sentence and the machine crashes before Send,
the same text must be present in the same field after recovery." Unambiguous,
and impossible to satisfy by accident. It drives three decisions here:

1. **Saving is continuous, not on close.** §5.1: "The user should not need to
   press Save." A crash gets no chance to flush, so anything that only writes
   on exit fails the requirement by construction.
2. **A write is one transaction.** §15 wants atomic checkpoints "so a partial
   save cannot corrupt the last known good state". One row, one UPSERT — a
   torn write cannot leave half a workspace.
3. **A read never fails.** A workspace that will not parse must not stop the
   console from opening; the operator loses their tab selection, not their
   application. Corruption is reported and the surface starts fresh.

## Versioned, because this shape will change

§15 asks for "schema/version metadata for forward migrations". Every payload
carries the version that wrote it, and a payload from a *newer* version than
this code understands is refused rather than guessed at — reading unknown
state optimistically is how an upgrade silently eats a workspace.

## Durable versus reconstructed (§5.4)

Only declarative state lives here: which tab, which filter, what text, where
the scroll sat. Nothing that can be rebuilt from it — no rendered DOM, no
sockets, no process handles. §5.4's rule, and the reason a payload stays small
enough to write every second without anybody noticing.
"""

from __future__ import annotations

import json

from backend.db import Database, now_iso

SCHEMA_VERSION = 1

# One row per surface. 'console' is the desktop/browser command centre; the
# Gateway and any future mobile surface get their own key rather than sharing,
# because they are different workspaces belonging to the same organization
# (addendum 40 §2's "one organization, many windows").
SURFACE_CONSOLE = "console"

# A ceiling on what one surface may store. Drafts are text and view state is a
# handful of fields; anything approaching this is a surface trying to use the
# workspace as a database, which is a different conversation.
MAX_PAYLOAD_BYTES = 256 * 1024

SCHEMA = """
-- The living workspace (addendum 40 §5). One row per surface; the payload is
-- declarative view state and draft text only - never anything reconstructable
-- (§5.4), which is what keeps it small enough to checkpoint continuously.
CREATE TABLE IF NOT EXISTS workspace_state (
    surface TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    -- Counts checkpoints rather than timing them: it is the cheap way to see
    -- whether continuous saving is actually happening, and it survives into
    -- the restore report the operator sees.
    revision INTEGER NOT NULL DEFAULT 1
);
"""


class WorkspaceTooLarge(ValueError):
    """A surface tried to store more than a workspace should hold."""


class WorkspaceFromTheFuture(ValueError):
    """State written by a newer version than this code understands.

    Its own class because the remedy is different from corruption: the
    operator should upgrade rather than start fresh, and silently discarding
    it would eat a workspace an upgrade could have migrated."""


def save(conn: Database, payload: dict, *, surface: str = SURFACE_CONSOLE) -> dict:
    """Checkpoint one surface's workspace. One transaction, one row (§15).

    Returns the stored record's metadata so a caller can show that saving is
    genuinely happening - a persistence feature nobody can observe is one
    nobody trusts."""
    if not isinstance(payload, dict):
        raise ValueError(f"workspace payload must be an object; got {type(payload).__name__}")

    encoded = json.dumps(payload, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise WorkspaceTooLarge(
            f"workspace payload is {len(encoded)} bytes, over the {MAX_PAYLOAD_BYTES} limit. "
            "The workspace holds view state and drafts, not documents."
        )

    conn.execute(
        "INSERT INTO workspace_state (surface, payload, schema_version, updated_at, revision) "
        "VALUES (?, ?, ?, ?, 1) "
        "ON CONFLICT(surface) DO UPDATE SET payload = excluded.payload, "
        "schema_version = excluded.schema_version, updated_at = excluded.updated_at, "
        "revision = workspace_state.revision + 1",
        (surface, encoded, SCHEMA_VERSION, now_iso()),
    )
    row = conn.fetchone(
        "SELECT updated_at, revision FROM workspace_state WHERE surface = ?", (surface,))
    return {"surface": surface, "updated_at": row["updated_at"], "revision": row["revision"],
            "bytes": len(encoded)}


def load(conn: Database, *, surface: str = SURFACE_CONSOLE) -> dict:
    """Restore one surface, or report honestly why it could not be.

    Always returns a dict with `restored`: True when there was a workspace to
    come back to, False when this is a fresh surface or the stored state was
    unusable. §15 asks recovery to "clearly distinguish successfully resumed
    work from work that must be retried" - so the reason is carried, not
    swallowed."""
    row = conn.fetchone(
        "SELECT payload, schema_version, updated_at, revision FROM workspace_state WHERE surface = ?",
        (surface,),
    )
    if row is None:
        return {"restored": False, "reason": "no workspace has been saved for this surface yet",
                "workspace": {}, "surface": surface}

    if row["schema_version"] > SCHEMA_VERSION:
        # Refused, not discarded: an upgrade could migrate this, and starting
        # fresh would destroy a workspace the operator could have kept.
        return {
            "restored": False,
            "reason": f"the saved workspace was written by schema version {row['schema_version']}, "
                      f"newer than this build understands ({SCHEMA_VERSION}). It has been left "
                      "untouched - upgrade rather than losing it.",
            "workspace": {}, "surface": surface, "stale_build": True,
        }

    try:
        workspace = json.loads(row["payload"])
        if not isinstance(workspace, dict):
            raise ValueError("payload is not an object")
    except Exception as exc:  # noqa: BLE001 - a bad workspace must not stop the console
        return {"restored": False, "reason": f"the saved workspace could not be read ({exc}); "
                                             "starting fresh",
                "workspace": {}, "surface": surface, "corrupt": True}

    return {
        "restored": True,
        "workspace": workspace,
        "surface": surface,
        "updated_at": row["updated_at"],
        "revision": row["revision"],
        "reason": None,
    }


def drafts(conn: Database, *, surface: str = SURFACE_CONSOLE) -> dict:
    """Just the unsent text, for anyone who wants to ask about it without
    parsing a whole workspace - the COO answering "what was I in the middle
    of?" being the obvious caller (§20's reference experience)."""
    state = load(conn, surface=surface)
    return dict(state["workspace"].get("drafts") or {}) if state["restored"] else {}


def clear(conn: Database, *, surface: str = SURFACE_CONSOLE) -> bool:
    """Forget a surface deliberately. Returns whether there was one."""
    existed = conn.fetchone(
        "SELECT 1 FROM workspace_state WHERE surface = ?", (surface,)) is not None
    conn.execute("DELETE FROM workspace_state WHERE surface = ?", (surface,))
    return existed
