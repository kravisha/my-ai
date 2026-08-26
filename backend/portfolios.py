"""Portfolios as owned entities, and the guard that makes owning one mean
something (TASK_QUEUE TQ-44, docs/SPEC_RECONCILIATION.md §99; moved here by
TQ-69, §110).

Source: addendum 44 §2, §3.3, §5, §9, §12, §15.1, §15.5.

## Why this is in `backend/` and not `gateway/`

It was written at the Gateway, and owner direction on 2026-08-26 (§109) says why
it does not belong there: *"Gateway is for establishing identity — Gateway only
does authentication. Back end does authorization and all business logic."*
Everything below this line is authorization. It is now in the process specified
to do it, and the Gateway reaches it over HTTP the way `gateway/jarvis.py`
already reaches `/admin`.

Nothing about the guard changed in the move, and that is the claim worth
checking rather than trusting: `resolve()` is the same function, with the same
ordering, the same single ownership comparison and the same one refusal. What
changed is that a Gateway request for a client's holdings now passes **this**
check as well as the Gateway's own route gate — two checks where there was one,
which is the entire point of the move (spec §9.1).

## `owner_id` is opaque here, deliberately (spec §4.2)

This module compares owner strings; it does not know what they name. A Gateway
client, the operator, and whatever TQ-70 decides identity should look like are
all the same thing to `_owned_by`: a pair of strings that either matches or does
not.

That is what keeps the trust boundary honest and small. The Gateway
authenticates somebody and asserts a subject; this process authorizes *that
subject* against *that portfolio*. It does not defend against a compromised
Gateway, which can assert any owner it likes — spec §4.3 says so at length
rather than implying otherwise — and it does defend against a buggy one, which
is the failure this project has actually had twice (§93, §106).

## Why the entity and the guard are one file

Holdings were keyed directly by client id (§96). That is flat but safe: there is
no portfolio identity, so **there is nothing to guess**. Addendum 44 §5.2 lists
four attacks — requesting another client's portfolio by id, reusing a stale URL,
a mismatched client/portfolio pair, an agent retaining a previous client's
context — and every one of them becomes possible only once an id exists.

So the id and the check ship together, in one increment and one review. An entity
that exists a week before its guard is a week of exactly the exposure addendum 44
was written to prevent. Splitting this file would be splitting that.

## `resolve()` is the one gate

Every read of portfolio-scoped data goes through it. One place answers "whose
data is this?", so there is one place to audit and one place a mistake can be.
The tripwire in tests/test_backend_portfolios.py fails if any other module
queries the `portfolios` table directly, because the single-gate property is
worth exactly as much as the discipline that maintains it.

## There is no superuser branch

Addendum 44 §5.3 forbids `if superuser: skip all ownership checks`, and this file
takes that literally rather than approximately. `SUPERUSER` is a **separate owner
domain, not a skeleton key**: a superuser context resolves superuser-owned
portfolios and nothing else, through the identical comparison a client context
uses. There is one ownership comparison in this module. A second one is where a
bypass eventually gets written, so there is not a second one.

The operator reaching a *client's* portfolio is deliberately not implemented.
§10 permits it only through explicitly authorized administrative workflows; none
exists, and building the permission before the workflow would be an
authorization surface with no consumer.

## One refusal, whatever the reason

`NotAuthorized` is raised identically when a portfolio does not exist, belongs to
somebody else, or is archived — same type, same message, no detail. Addendum 44
§9.3: an error must not reveal that another client exists or owns a requested id.
Distinguishing those cases leaks precisely that, and the caller's remedy is the
same in all three.

The ordering inside `resolve` is part of that promise. Ownership is compared
*before* the row is interpreted, so a row this build cannot read raises its
fail-closed error only for the person who actually owns it. Interpreting first
would turn "that id exists but its data is corrupt" into an existence oracle for
everybody else.

## Ownership is resolved server-side, never received

`OwnerContext` is built from the session's `subject` (§93, §98) and from nothing
a caller sent — addendum 44 §9.2: *"A client_id received from the front end is
not sufficient proof of ownership."* `resolve()` and `listing()` refuse a bare
string, so an unresolved id cannot be passed by accident where a proven owner is
required.

## Nothing here is priced

`is_priced()` is the whole rule, and it is one line: only `data_mode == LIVE`.
Every price this organization produces is simulated (addendum 25), which is why
§96 refused market value and why `portfolio_valuation` stands declared-and-unbuilt
in gateway/skills.py. Addendum 44 supplied the missing field; it did not supply
prices. One function means the answer cannot drift between callers, and a
`market_price` column existing is not permission to fill it in.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from backend.db import Database, now_iso

SCHEMA_VERSION = 1

# --- closed vocabularies -----------------------------------------------------------
#
# The house rule (backend/status_events.py, gateway/clients.py): a value this
# build does not recognise denies rather than defaulting. Enforced on read as
# well as on write, because a portfolio whose owner_type cannot be interpreted is
# not one that may be handed to anybody.

OWNER_CLIENT = "CLIENT"
OWNER_SUPERUSER = "SUPERUSER"
OWNER_TYPES = (OWNER_CLIENT, OWNER_SUPERUSER)

TYPE_PRIMARY = "PRIMARY"
TYPE_SECONDARY = "SECONDARY"
TYPE_SIMULATION = "SIMULATION"
TYPE_BROKERAGE_IMPORTED = "BROKERAGE_IMPORTED"
PORTFOLIO_TYPES = (TYPE_PRIMARY, TYPE_SECONDARY, TYPE_SIMULATION, TYPE_BROKERAGE_IMPORTED)

PROVIDER_SIMULATED = "SIMULATED"
PROVIDER_SCHWAB = "SCHWAB"
PROVIDER_MANUAL = "MANUAL"
PROVIDER_TYPES = (PROVIDER_SIMULATED, PROVIDER_SCHWAB, PROVIDER_MANUAL)

MODE_SIMULATED = "SIMULATED"
MODE_LIVE = "LIVE"
MODE_MANUAL = "MANUAL"
DATA_MODES = (MODE_SIMULATED, MODE_LIVE, MODE_MANUAL)

STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUSES = (STATUS_ACTIVE, STATUS_ARCHIVED)

# The only thing a refused caller is ever told. Addendum 44 §9.3: absent,
# foreign and archived must be indistinguishable, so there is one string and no
# formatting into it.
REFUSAL = "Not authorized or resource unavailable."


def normalise(raw: str) -> str:
    """The canonical form of an owner id, and **the only implementation of it**
    (TQ-69).

    Lowercased and trimmed, because an identifier that differs only by case is
    two identities to the database and one to the person typing it - and two
    identities means two sets of holdings, which is the failure this whole area
    exists to prevent.

    It lives here rather than in `gateway/clients.py`, where it was written,
    because this module is now the one that decides whether two owner strings are
    the same person. `gateway.clients.normalise` imports this one rather than
    keeping a copy: a second normalisation that could disagree would let the same
    client be two owners, which no ownership comparison can detect - both
    comparisons would be correct, about different people.

    Deliberately unaware of what an owner id *means* (spec §4.2). This
    lowercases and trims a string; it does not know whether that string is a
    Gateway client, an operator, or something TQ-70 has not invented yet."""
    return (raw or "").strip().lower()

# What a portfolio is called when nobody named it (§3.8). Deliberately dull: it
# is the client's own portfolio, shown to the client, and a generated name would
# only be something to explain.
DEFAULT_DISPLAY_NAME = "Portfolio"

_FIELDS = ("portfolio_id", "owner_type", "owner_id", "portfolio_type", "display_name",
           "provider_type", "provider_account_ref", "data_mode", "status", "created_at",
           "updated_at", "last_synced_at", "simulated", "schema_version")
_SELECT = f"SELECT {', '.join(_FIELDS)} FROM portfolios"

SCHEMA = """
-- Portfolios, each with an explicit owner (TQ-44, addendum 44 §3.3).
--
-- owner_type and owner_id are NOT NULL deliberately. §2.3 says a missing owner
-- denies, and a nullable column would make that a runtime hope rather than a
-- schema fact: the database itself refuses to hold an unowned portfolio.
--
-- portfolio_id is random rather than sequential (§3.5). The guard makes
-- enumeration useless; random ids make it pointless. A sequential id leaks a
-- portfolio count from any single id - information about other clients even
-- when their data is unreachable.
--
-- `simulated` follows the §96 convention so demo portfolios are removable
-- exactly rather than guessed at from a naming convention.
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    portfolio_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    provider_account_ref TEXT,
    data_mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_synced_at TEXT,
    simulated INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS portfolios_by_owner ON portfolios (owner_type, owner_id);
"""


class NotAuthorized(PermissionError):
    """The one refusal (§3.4). Raised identically for absent, foreign and
    archived, because telling those apart tells a caller that somebody else's
    portfolio exists - and the remedy is the same in all three."""


class UnknownVocabulary(ValueError):
    """A value outside a closed vocabulary, on write or on read. Fail closed: a
    portfolio this build cannot interpret is not one it may act on."""


@dataclass(frozen=True)
class OwnerContext:
    """Who is asking, resolved server-side.

    Frozen because it is evidence, not a variable: something that could be
    reassigned between the check and the read is not a proof of ownership.

    **Never assembled from anything a caller sent** (addendum 44 §9.2). The
    Gateway resolves `subject` from the session (§93, §98); this is built from
    that and nothing else."""

    owner_type: str
    owner_id: str

    def __post_init__(self) -> None:
        if self.owner_type not in OWNER_TYPES:
            raise UnknownVocabulary(
                f"unknown owner type {self.owner_type!r}; known are {list(OWNER_TYPES)}")
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise UnknownVocabulary("an owner context needs an owner id")
        # One normalisation, defined above and imported by the Gateway's client
        # registry rather than copied there. Two that could disagree are two
        # identities for one person, which is the failure this whole area exists
        # to prevent.
        object.__setattr__(self, "owner_id", normalise(self.owner_id))


def for_client(client_id: str) -> OwnerContext:
    return OwnerContext(OWNER_CLIENT, client_id)


def for_superuser(operator_id: str) -> OwnerContext:
    """The operator's own owner domain - not a master key over the client one.

    A superuser context reaches superuser-owned portfolios through the same
    comparison a client uses, and reaches no client's. See §3.3, and the test
    named for §15.5.

    ## Which "Superuser" this is (TQ-46 §4.2, §97)

    Three near-synonyms exist in this codebase and they are **not** the same
    person:

    - the **Server Superuser** (`app/server_auth.py`), whose credential starts
      the workforce;
    - the **Gateway Super User** (`gateway/auth.py`, `GATEWAY_SUPER_USER`), the
      operator's credential at the door; and
    - **`ROLE_OPERATOR`** (`gateway/roles.py`), the role a Gateway session is
      issued under.

    `OWNER_SUPERUSER` is **none of those three**. It is the system's own
    principal - the backend user in `users.json`, the account `/chat` resolves
    with `Depends(get_current_user)` - decided by the owner on 2026-08-26 (TQ-46
    §11 Q4). The first two are credentials, which is authentication; this is
    ownership, which is authorization, and §109 put those in different processes
    on purpose.

    Three near-synonyms drifting is how somebody eventually grants the wrong one
    a portfolio, so the sentence lives here, next to the constant, rather than in
    a specification somebody would have to know to go and read.

    ## The id is required, and used to be `"operator"`

    A default was the wrong shape for the same reason `for_client` never had one:
    it puts a literal where a resolved identity belongs, and a literal cannot be
    wrong in a way anybody notices. It would also have been *nearly right* here -
    `GATEWAY_SUPER_USER` and the backend username both happen to read `krish`
    today - and a value that is nearly right is the one that survives review and
    fails later, when somebody renames one of them and the operator's portfolio
    silently becomes empty rather than erroring."""
    return OwnerContext(OWNER_SUPERUSER, operator_id)


def _require_owner(owner) -> OwnerContext:
    """Refuse a bare string where a proven owner is required.

    A raw id is a claim; an `OwnerContext` is the result of resolving one. Taking
    a string here would let a caller pass something a user typed into the
    position that decides whose money is visible - and it would look correct."""
    if not isinstance(owner, OwnerContext):
        raise TypeError(
            f"ownership needs an OwnerContext resolved from the session, not "
            f"{type(owner).__name__}. Use portfolios.for_client(subject).")
    return owner


def _check(value, vocabulary: tuple[str, ...], field: str) -> str:
    if value not in vocabulary:
        raise UnknownVocabulary(
            f"unknown {field} {value!r}; known are {list(vocabulary)}")
    return value


def _interpret(row) -> dict:
    """A stored row, validated against every closed vocabulary (§3.6).

    Raises on **read**, not only on write. A row whose `data_mode` this build
    does not recognise is one whose pricing rule it cannot apply, and guessing
    which side of `is_priced` it falls on is the guess that shows somebody a
    simulated number as though it were their money."""
    portfolio = dict(row)
    _check(portfolio["owner_type"], OWNER_TYPES, "owner type")
    _check(portfolio["portfolio_type"], PORTFOLIO_TYPES, "portfolio type")
    _check(portfolio["provider_type"], PROVIDER_TYPES, "provider type")
    _check(portfolio["data_mode"], DATA_MODES, "data mode")
    _check(portfolio["status"], STATUSES, "status")
    portfolio["simulated"] = bool(portfolio["simulated"])
    return portfolio


def _owned_by(row, owner: OwnerContext) -> bool:
    """The single ownership comparison in this module.

    Identical for both owner domains, which is what makes §5.3 structural rather
    than a promise: there is no branch here for a superuser to be excused from.
    An unrecognised stored owner_type simply matches nobody, so a row this build
    cannot interpret fails closed before anything else looks at it."""
    return (row["owner_type"], row["owner_id"]) == (owner.owner_type, owner.owner_id)


def create(conn: Database, owner, *, display_name: str,
           portfolio_type: str = TYPE_PRIMARY,
           provider_type: str = PROVIDER_MANUAL,
           data_mode: str = MODE_MANUAL,
           provider_account_ref: str | None = None,
           simulated: bool = False) -> dict:
    """A new portfolio, owned from the moment it exists.

    There is no code path that creates one without an owner: the argument is
    required, it must be an `OwnerContext`, and the column is NOT NULL. §2.3's
    "a missing owner denies" is enforced three times over because the alternative
    is a portfolio somebody has to be assigned later, and "later" is where the
    unowned row lives."""
    owner = _require_owner(owner)
    _check(portfolio_type, PORTFOLIO_TYPES, "portfolio type")
    _check(provider_type, PROVIDER_TYPES, "provider type")
    _check(data_mode, DATA_MODES, "data mode")
    name = (display_name or "").strip()
    if not name:
        raise UnknownVocabulary("a portfolio needs a display name")

    portfolio_id = f"pf-{secrets.token_hex(16)}"
    now = now_iso()
    conn.execute(
        "INSERT INTO portfolios (portfolio_id, owner_type, owner_id, portfolio_type, "
        "display_name, provider_type, provider_account_ref, data_mode, status, "
        "created_at, updated_at, last_synced_at, simulated, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (portfolio_id, owner.owner_type, owner.owner_id, portfolio_type, name,
         provider_type, provider_account_ref, data_mode, STATUS_ACTIVE,
         now, now, None, 1 if simulated else 0, SCHEMA_VERSION),
    )
    # Read back through the gate rather than returning what was just built, so
    # even creation cannot hand out a portfolio the guard would not.
    return resolve(conn, portfolio_id, owner)


def resolve(conn: Database, portfolio_id: str, owner) -> dict:
    """**The one gate.** This owner's portfolio, or one refusal.

    Every read of portfolio-scoped data goes through here. A second retrieval
    path that skipped it would be the failure mode §9.2 names, and it would not
    look like one - it would look like a convenience.

    The order matters and is not incidental:

    1. no such row -> refuse
    2. not this owner's -> refuse, *before* the row is interpreted, so a corrupt
       row cannot become an existence oracle for anybody but its owner
    3. uninterpretable -> fail closed, to its owner only
    4. not active -> refuse, with the same words as (1) and (2)
    """
    owner = _require_owner(owner)
    row = conn.fetchone(f"{_SELECT} WHERE portfolio_id = ?",
                        (str(portfolio_id or "").strip(),))
    if row is None:
        raise NotAuthorized(REFUSAL)
    if not _owned_by(row, owner):
        raise NotAuthorized(REFUSAL)
    portfolio = _interpret(row)
    if portfolio["status"] != STATUS_ACTIVE:
        raise NotAuthorized(REFUSAL)
    return portfolio


def owned(conn: Database, owner) -> list[dict]:
    """Every portfolio belonging to this owner, archived ones included.

    Owner-scoped **in the query**, which is what makes it safe to exist beside
    `resolve` rather than being a second way around it: it takes no id, so there
    is no id it could be tricked into returning. The dangerous shape is
    retrieval *by id* without a check, and that shape has exactly one
    implementation (`resolve`).

    Archived rows are included here and excluded by `listing`, because the two
    callers want opposite things: a client reading their portfolios should not
    see retired ones, and demo clearing must not leave one behind."""
    owner = _require_owner(owner)
    rows = conn.fetchall(
        f"{_SELECT} WHERE owner_type = ? AND owner_id = ? ORDER BY created_at, portfolio_id",
        (owner.owner_type, owner.owner_id))
    return [_interpret(row) for row in rows]


def listing(conn: Database, owner) -> list[dict]:
    """This owner's active portfolios, and only ever this owner's.

    Filtered by status in Python rather than in SQL, deliberately: an
    unrecognised status must reach `_interpret` and raise rather than being
    quietly dropped by a `WHERE status = 'active'` that would make a row this
    build cannot read look like a row that is not there."""
    return [p for p in owned(conn, owner) if p["status"] == STATUS_ACTIVE]


def primary_for(conn: Database, owner, *, display_name: str | None = None,
                simulated: bool = False,
                provider_type: str = PROVIDER_MANUAL,
                data_mode: str = MODE_MANUAL) -> dict:
    """This owner's primary portfolio, created on first use (§3.8).

    §5.1 allows one owner many portfolios and most have exactly one. Requiring
    somebody to name a portfolio before they can tell their representative about
    a holding would be ceremony, and the entity is equally real either way -
    this decides only who names it.

    Oldest-first when several exist, so the answer does not change under a caller
    who created a second one.

    `provider_type` and `data_mode` default to MANUAL because that is what a
    client speaking to their representative produces, and it is the only thing
    ordinary use creates. They are arguments rather than constants because a
    seeder building a SIMULATED portfolio needs to say so at creation (§6.2) -
    **and only at creation**: they describe where a portfolio's rows come from,
    so changing them later would relabel data that is already there. An existing
    portfolio is returned as it stands and these are ignored, which is the
    behaviour to keep."""
    owner = _require_owner(owner)
    for portfolio in listing(conn, owner):
        if portfolio["portfolio_type"] == TYPE_PRIMARY:
            return portfolio
    return create(conn, owner, display_name=display_name or DEFAULT_DISPLAY_NAME,
                  portfolio_type=TYPE_PRIMARY, provider_type=provider_type,
                  data_mode=data_mode, simulated=simulated)


def archive(conn: Database, portfolio_id: str, owner) -> dict:
    """Retire a portfolio. Goes through `resolve` first, so it refuses for
    exactly the reasons a read does - including refusing to archive one that is
    already archived, which is the same "not yours to act on" answer."""
    portfolio = resolve(conn, portfolio_id, owner)
    now = now_iso()
    conn.execute(
        "UPDATE portfolios SET status = ?, updated_at = ? WHERE portfolio_id = ?",
        (STATUS_ARCHIVED, now, portfolio["portfolio_id"]))
    return {**portfolio, "status": STATUS_ARCHIVED, "updated_at": now}


def mark_synced(conn: Database, portfolio_id: str, owner, *, at: str | None = None) -> dict:
    """Record that this portfolio's data was actually fetched, just now.

    Called only by a provider whose `refresh` succeeded (TQ-45b). Addendum 44 §17
    is the whole reason it is a separate function rather than a line inside
    `refresh`: *"mark it stale, do not silently claim it is current."* A
    `last_synced_at` that moved on a **failed** sync would be worse than the NULL
    it replaced - a NULL says "never synced", which is true, while a fresh
    timestamp asserts a freshness nothing has.

    Goes through `resolve` first, like `archive`, so it refuses for exactly the
    reasons a read does. A sync is a write about somebody's money, and there is
    no version of it that should skip the ownership comparison."""
    portfolio = resolve(conn, portfolio_id, owner)
    stamp = at or now_iso()
    conn.execute(
        "UPDATE portfolios SET last_synced_at = ?, updated_at = ? WHERE portfolio_id = ?",
        (stamp, stamp, portfolio["portfolio_id"]))
    return {**portfolio, "last_synced_at": stamp, "updated_at": stamp}


def record_source(conn: Database, portfolio_id: str, owner, ref: str) -> dict:
    """Record where this portfolio's rows were loaded from, once (TQ-46).

    `provider_account_ref` is "the source's own reference" - a broker account
    number for a brokerage portfolio, and for the operator's it is the
    spreadsheet the holdings were migrated out of. Using the field for exactly
    what it means is what lets TQ-46's migration be idempotent **without a new
    mechanism**: a portfolio that already names a source has already been
    migrated, so a second run finds nothing to do.

    That matters more than a flag would. Re-running the migration would re-upsert
    every spreadsheet row - overwriting edits the operator had made to those
    symbols, and resurrecting the ones they had deleted. "Idempotent" here is not
    tidiness, it is not undoing somebody's corrections.

    **Set once and refused afterwards.** A source that could be changed would let
    a second migration point the same portfolio at a different file, which is a
    portfolio quietly becoming a different portfolio. Goes through `resolve`
    first, like `archive` and `mark_synced`, because it is a write about
    somebody's money."""
    portfolio = resolve(conn, portfolio_id, owner)
    if portfolio["provider_account_ref"]:
        raise UnknownVocabulary(
            f"portfolio {portfolio['portfolio_id']!r} already names a source "
            f"({portfolio['provider_account_ref']!r}); refusing to point it at "
            f"{ref!r} instead. A portfolio that changed source would be a different "
            "portfolio wearing the same id.")
    now = now_iso()
    conn.execute(
        "UPDATE portfolios SET provider_account_ref = ?, updated_at = ? "
        "WHERE portfolio_id = ?", (ref, now, portfolio["portfolio_id"]))
    return {**portfolio, "provider_account_ref": ref, "updated_at": now}


def is_priced(portfolio: dict) -> bool:
    """Whether anything derived from a market price may be shown. The entire
    condition, in one place, for every caller.

    §96 refused market value because every price this system produces is
    simulated; addendum 44 supplied the field that could one day say otherwise
    and §97 drew the line at `LIVE`. `SIMULATED` and `MANUAL` are never priced -
    a simulated price applied to somebody's real positions is synthetic output
    presented as their money."""
    return portfolio.get("data_mode") == MODE_LIVE


def purge_owner(conn: Database, owner) -> int:
    """Remove every portfolio belonging to this owner. Returns how many went.

    For demo clearing (§96), which is the only caller that should ever want
    this. Ownership-scoped like everything else here: there is no "delete by id"
    that skips knowing whose it was."""
    owner = _require_owner(owner)
    return conn.execute_returning_rowcount(
        "DELETE FROM portfolios WHERE owner_type = ? AND owner_id = ?",
        (owner.owner_type, owner.owner_id))


def simulated_portfolio_ids(conn: Database) -> list[str]:
    """Which portfolios are demo data, from the flag rather than from a naming
    convention (§96)."""
    return [row["portfolio_id"] for row in conn.fetchall(
        "SELECT portfolio_id FROM portfolios WHERE simulated = 1 ORDER BY portfolio_id")]


def simulated_client_ids(conn: Database) -> list[str]:
    """Client ids that own a simulated portfolio.

    Client-owned only: a simulated *superuser* portfolio is not a demo customer,
    and returning its owner id here would have `demo_clients.clear()` looking for
    a client registration that was never going to exist."""
    return [row["owner_id"] for row in conn.fetchall(
        "SELECT DISTINCT owner_id FROM portfolios WHERE simulated = 1 AND owner_type = ? "
        "ORDER BY owner_id", (OWNER_CLIENT,))]
