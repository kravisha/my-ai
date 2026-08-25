"""The client registry: who may log in as a client, and as whom (TASK_QUEUE
TQ-43, docs/SPEC_RECONCILIATION.md §98).

Everything downstream of a client session has been per-client for days —
conversations (§93), the representative's identity (§93), holdings (§96) — and
all of it keys off a `subject` that, until now, only one person could ever be.
The Gateway had one credential per **role**, so every client shared a password
and therefore shared a subject. The isolation was real and tested; the doorway
that would let two clients actually be two people did not exist.

## Why clients are a registry and roles are not

`gateway/auth.py` keeps the operator's and internal credentials in the process
environment, for reasons it states at length: a route that could grant that
privilege would be an escalation surface worth not having, and whoever controls
the process already controls its data.

That reasoning holds for a role that is **one person by definition**. It does not
survive contact with a role that is many. A shared environment variable for
"every client" is not a credential, it is a group password — and the whole point
of TQ-43 is that the thing it protects is somebody's money.

So the line is drawn by cardinality rather than by convenience:

- **operator, internal** — one each, environment, out of band. Unchanged.
- **client** — many, registered here, one credential and one identity apiece.

`ROLE_CREDENTIAL_ENV` no longer carries an entry for the client role at all.
Leaving it configurable "for compatibility" would have left the shared password
available, which is the hole this exists to close rather than a migration path.

## Provisioning is a command, not a route

Clients are created by `python -m gateway.clients add`, the same shape as
`backend/migrations` and `gateway.demo_clients`. A route that mints credentials
is an escalation surface; a command runs as whoever controls the process, who
already controls the database.

The password is **generated, printed once, and stored only as a bcrypt hash**.
There is no path that recovers it, including for the operator — a registry that
could show a client's password would be a registry worth stealing.

## Ownership before capability, at the door

Addendum 44 §2.1 wants two separate questions answered, and this file answers the
half the session begins with: *whose* session is this. `authenticate` returns a
`client_id`, and that id becomes the session's subject — never the string the
caller typed, which is only ever a claim.

## §9.3, applied to the login itself

Addendum 44 §9.3 says an error must not reveal that another client exists. A
username that is not registered is compared against a decoy hash anyway, so a
wrong name and a wrong password cost the same time. Rate limiting is the real
defence and already exists; this closes the cheaper oracle beside it.
"""

from __future__ import annotations

import re
import secrets

import bcrypt

from backend.db import Database, now_iso

SCHEMA_VERSION = 1

# A closed vocabulary. An unrecognised status denies rather than defaulting,
# because a status this build cannot interpret is not one it may act on.
STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUSES = (STATUS_ACTIVE, STATUS_SUSPENDED)

# Client ids are the login handle and the ownership key, so they are constrained
# rather than free text: they end up in log lines, audit rows and error
# messages, and a handle containing a newline or a quote is a formatting bug
# waiting to be an injection one.
_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")

# Compared against when no client matches, so a wrong username and a wrong
# password take the same time (addendum 44 §9.3). Not a secret: it is the hash
# of 32 random bytes nobody kept.
_DECOY_HASH = "$2b$12$zWRr4AJH6.lhrsjtjlJUqeAknEH9faqOVzEXLO6Xua5w3JZqEHGeC"

# Long enough that the generated password is not the weak link, short enough to
# read aloud once.
GENERATED_PASSWORD_BYTES = 18

SCHEMA = """
-- Who may log in as a client (TQ-43). One row per client: the id is both the
-- login handle and the ownership key every other client-scoped table joins on
-- (conversations.owner, client_agents.client_id, client_holdings.client_id).
--
-- The password is stored only as a bcrypt hash and never recoverable. A
-- registry that could show a client's password would be a registry worth
-- stealing.
--
-- `simulated` marks demo clients, so gateway/demo_clients.py can clear exactly
-- what it created (§96).
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    simulated INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL DEFAULT 1
);
"""


class ClientRefused(ValueError):
    """A client this registry will not create, with the reason."""


class UnknownStatus(ValueError):
    """A stored status outside the vocabulary. Fail closed: a status this build
    cannot interpret is not one it may act on."""


def normalise(raw: str) -> str:
    """The canonical form of a client id.

    Lowercased and trimmed, because a login handle that differs only by case is
    two identities to the database and one to the person typing it - and two
    identities means two sets of holdings, which is the failure this whole area
    exists to prevent."""
    return (raw or "").strip().lower()


def _validate_id(raw: str) -> str:
    client_id = normalise(raw)
    if not _CLIENT_ID.fullmatch(client_id):
        raise ClientRefused(
            f"{raw!r} is not a usable client id. Use 2-63 characters: lowercase letters, "
            "digits, dot, underscore or hyphen, starting with a letter or digit."
        )
    return client_id


def _reserved_names() -> set[str]:
    """Names a client may not take, because a role already answers to them.

    Registering a client called the same thing as the operator would create a
    genuine ambiguity at the login route, and the safe resolution of an
    ambiguity about *who somebody is* is to refuse it at creation rather than to
    pick a winner at authentication."""
    from gateway import auth

    reserved = set()
    for user_env, _ in auth.ROLE_CREDENTIAL_ENV.values():
        import os

        configured = normalise(os.environ.get(user_env, ""))
        if configured:
            reserved.add(configured)
    return reserved


def generate_password() -> str:
    return secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def register(conn: Database, client_id: str, *, display_name: str | None = None,
             password: str | None = None, simulated: bool = False) -> tuple[dict, str]:
    """Create a client. Returns the record and the password, which is the only
    time the password exists in readable form.

    Generated by default rather than chosen: a provisioning command that accepts
    a password invites a memorable one, and these are credentials to somebody
    else's financial data."""
    identifier = _validate_id(client_id)
    if identifier in _reserved_names():
        raise ClientRefused(
            f"{identifier!r} is already a configured role credential. A client and a role "
            "answering to one name is an ambiguity about who somebody is, and it is "
            "refused here rather than resolved at the login route."
        )
    if conn.fetchone("SELECT client_id FROM clients WHERE client_id = ?", (identifier,)):
        raise ClientRefused(f"{identifier!r} is already registered.")

    secret = password or generate_password()
    now = now_iso()
    conn.execute(
        "INSERT INTO clients (client_id, display_name, password_hash, status, created_at, "
        "updated_at, simulated, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (identifier, (display_name or identifier).strip(), hash_password(secret),
         STATUS_ACTIVE, now, now, 1 if simulated else 0, SCHEMA_VERSION),
    )
    return get(conn, identifier), secret


def get(conn: Database, client_id: str) -> dict | None:
    row = conn.fetchone(
        "SELECT client_id, display_name, status, created_at, updated_at, simulated "
        "FROM clients WHERE client_id = ?", (normalise(client_id),))
    return dict(row) if row else None


def listing(conn: Database) -> list[dict]:
    """Every registered client. Never the hashes - nothing outside this module
    has a reason to hold one, and a listing that carried them would put them in
    whatever printed it."""
    return conn.fetchall(
        "SELECT client_id, display_name, status, created_at, updated_at, simulated "
        "FROM clients ORDER BY client_id")


def authenticate(conn: Database, name: str, password: str) -> str | None:
    """The client id this credential belongs to, or None.

    Returns the **id**, not a boolean, because the id is what becomes the
    session's subject. A caller that verified a credential and then trusted the
    typed name would be taking a claim as an identity at precisely the moment
    the answer is known (addendum 44 §9.2).

    A username that is not registered is still compared against a decoy hash, so
    that a wrong name and a wrong password cost the same time - addendum 44 §9.3
    applied to the login itself."""
    identifier = normalise(name)
    row = conn.fetchone(
        "SELECT client_id, password_hash, status FROM clients WHERE client_id = ?",
        (identifier,))

    digest = row["password_hash"] if row else _DECOY_HASH
    try:
        matched = bcrypt.checkpw((password or "").encode("utf-8"), digest.encode("utf-8"))
    except ValueError:
        # A malformed stored hash is a data problem, not a failed login - but it
        # must refuse rather than raise, or one bad row becomes a 500 that
        # leaks a stack trace to an external caller.
        return None

    if row is None or not matched:
        return None
    if row["status"] not in STATUSES:
        raise UnknownStatus(
            f"client {identifier!r} has status {row['status']!r}, which this build does not "
            "recognise; refusing rather than guessing what it permits.")
    if row["status"] != STATUS_ACTIVE:
        return None
    return row["client_id"]


def set_status(conn: Database, client_id: str, status: str) -> dict:
    if status not in STATUSES:
        raise UnknownStatus(f"unknown client status {status!r}; known are {list(STATUSES)}")
    identifier = normalise(client_id)
    if get(conn, identifier) is None:
        raise ClientRefused(f"{identifier!r} is not registered.")
    conn.execute("UPDATE clients SET status = ?, updated_at = ? WHERE client_id = ?",
                 (status, now_iso(), identifier))
    return get(conn, identifier)


def set_password(conn: Database, client_id: str, password: str | None = None) -> str:
    """Replace a client's password and return the new one, once."""
    identifier = normalise(client_id)
    if get(conn, identifier) is None:
        raise ClientRefused(f"{identifier!r} is not registered.")
    secret = password or generate_password()
    conn.execute("UPDATE clients SET password_hash = ?, updated_at = ? WHERE client_id = ?",
                 (hash_password(secret), now_iso(), identifier))
    return secret


def remove(conn: Database, client_id: str) -> bool:
    """Remove a client's ability to log in.

    Deliberately does **not** remove their holdings, conversations or agent.
    Deleting somebody's financial records as a side effect of revoking a login
    is not a decision this function is entitled to make; `gateway.demo_clients`
    is where clearing data lives, and it says what it is doing."""
    return conn.execute_returning_rowcount(
        "DELETE FROM clients WHERE client_id = ?", (normalise(client_id),)) > 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    from gateway import store

    parser = argparse.ArgumentParser(
        prog="python -m gateway.clients",
        description="The Gateway's client registry (TQ-43, §98). Passwords are generated "
                    "and shown once; nothing here can recover one.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="register a client and print their password once")
    p_add.add_argument("client_id")
    p_add.add_argument("--name", default=None, help="display name (defaults to the id)")

    sub.add_parser("list", help="every registered client")

    p_pw = sub.add_parser("passwd", help="issue a new password, shown once")
    p_pw.add_argument("client_id")

    p_sus = sub.add_parser("suspend", help="stop a client logging in, keeping their data")
    p_sus.add_argument("client_id")
    p_act = sub.add_parser("activate", help="let a suspended client log in again")
    p_act.add_argument("client_id")

    p_rm = sub.add_parser("remove", help="remove the login; keeps holdings and conversations")
    p_rm.add_argument("client_id")
    p_rm.add_argument("--yes", action="store_true", help="required: confirm")

    args = parser.parse_args(argv)
    conn = store.get_connection()
    store.init_schema(conn)
    try:
        if args.command == "add":
            try:
                client, password = register(conn, args.client_id, display_name=args.name)
            except ClientRefused as refusal:
                print(f"refused: {refusal}")
                return 1
            print(f"registered {client['client_id']} ({client['display_name']})")
            print(f"password: {password}")
            print("This is the only time it is shown. Nothing here can recover it.")
            return 0

        if args.command == "list":
            rows = listing(conn)
            if not rows:
                print("no clients registered")
                return 0
            for row in rows:
                mark = " [simulated]" if row["simulated"] else ""
                print(f"  {row['client_id']:<20} {row['status']:<10} "
                      f"{row['display_name']}{mark}")
            return 0

        if args.command == "passwd":
            try:
                print(f"new password: {set_password(conn, args.client_id)}")
            except ClientRefused as refusal:
                print(f"refused: {refusal}")
                return 1
            print("Shown once.")
            return 0

        if args.command in ("suspend", "activate"):
            status = STATUS_SUSPENDED if args.command == "suspend" else STATUS_ACTIVE
            try:
                client = set_status(conn, args.client_id, status)
            except ClientRefused as refusal:
                print(f"refused: {refusal}")
                return 1
            print(f"{client['client_id']} is now {client['status']}")
            return 0

        if args.command == "remove":
            if not args.yes:
                print("This removes the login only; holdings and conversations stay. "
                      "Re-run with --yes.")
                return 1
            if remove(conn, args.client_id):
                print(f"removed the login for {normalise(args.client_id)}")
                print("Their holdings and conversations are untouched - use "
                      "`python -m gateway.demo_clients clear` for demo data.")
                return 0
            print("no such client")
            return 1

        raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
