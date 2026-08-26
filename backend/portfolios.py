"""Whose portfolio this is — the vocabulary and the owner context (TASK_QUEUE
TQ-44, docs/SPEC_RECONCILIATION.md §99; **custody removed by TQ-72, §111**).

## What this module used to be

It was the portfolio *store*: a `portfolios` table, and `resolve()` as the one
gate every read went through. Owner direction removed the store (§111):

> *"The portfolios don't live in this system. The portfolios are the personal
> property of the clients."*

So `create`, `resolve`, `owned`, `listing`, `primary_for`, `archive`,
`mark_synced`, `purge_owner` and the schema are gone. There is no row to resolve.

## What that does **not** mean

**It does not mean isolation is gone.** It means the question moved, and the new
one is harder rather than easier.

`resolve()` answered *"whose stored row is this?"*. With nothing stored, the
question addendum 44 §9.4 asks is the one that remains, and §112 made it the
normal case rather than an edge:

> *"an internal agent accidentally retaining Client B portfolio context while
> serving Client A"*

A consolidating analyst holds several portfolios in memory at once **by design**.
Isolation is now a property of a request's lifetime, not of a table — which is
why `OwnerContext` survives the table it used to guard. It is still the answer to
"who is this work for", and it is still built from a resolved session subject
rather than from anything a caller sent (addendum 44 §9.2).

## What survives, and why each piece earns it

- **`OwnerContext`** — who a session's work is for. Frozen, because it is
  evidence rather than a variable: something that could be reassigned between the
  check and the read is not a proof of anything.
- **`normalise`** — the single definition of when two owner ids are the same
  person (TQ-69). `gateway/clients.normalise` delegates here; two normalisations
  that could disagree would make one client into two owners, and **no ownership
  comparison could detect it**, because both comparisons would be correct about
  different people.
- **The closed vocabularies** — `owner_type`, provider types, data modes. A
  fetched portfolio still comes from somewhere and still arrives in some mode,
  and a value this build cannot interpret still denies rather than defaulting.
- **`REFUSAL` and `NotAuthorized`** — one identical refusal, whatever the reason
  (addendum 44 §9.3). Still needed the moment anything refuses.
- **`is_priced`** — see below.

## `is_priced` is on notice, and deliberately not changed here

It reads one thing: `data_mode == LIVE`. §113 says that rule has to move — from
the *portfolio's* data mode to the *price's* provenance — because prices now come
from the market data store while positions come from a broker, so a portfolio can
be entirely real while the only available price is synthetic. `data_mode` cannot
express that; it describes where the positions came from.

**That change belongs with the thing that makes it necessary** (TQ-73/TQ-75),
not here. Moving it now would leave a rule keyed to a provenance nothing yet
reads, which is machinery with no user — and this increment is about removing
machinery, not adding it. What is recorded here is that the rule is known to be
wrong-shaped, so nobody re-derives that discovery.
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1

# --- closed vocabularies -----------------------------------------------------------
#
# The house rule (backend/status_events.py, gateway/clients.py): a value this
# build does not recognise denies rather than defaulting.

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

# The only thing a refused caller is ever told. Addendum 44 §9.3: absent, foreign
# and unavailable must be indistinguishable, so there is one string and nothing
# formatted into it.
REFUSAL = "Not authorized or resource unavailable."


class NotAuthorized(PermissionError):
    """The one refusal. Raised identically whatever the reason, because telling
    those apart tells a caller that somebody else's data exists - and the remedy
    is the same in every case."""


class UnknownVocabulary(ValueError):
    """A value outside a closed vocabulary. Fail closed: something this build
    cannot interpret is not something it may act on."""


def normalise(raw: str) -> str:
    """The canonical form of an owner id, and **the only implementation of it**
    (TQ-69).

    Lowercased and trimmed, because an identifier that differs only by case is
    two identities to the system and one to the person typing it - and two
    identities means two sets of holdings, which is the failure this whole area
    exists to prevent.

    `gateway.clients.normalise` imports this one rather than keeping a copy: a
    second normalisation that could disagree would let the same client be two
    owners, which no ownership comparison can detect - both comparisons would be
    correct, about different people.

    Deliberately unaware of what an owner id *means* (§110 §4.2). This lowercases
    and trims a string; it does not know whether that string is a Gateway client,
    the operator, or something TQ-70 has not invented yet."""
    return (raw or "").strip().lower()


@dataclass(frozen=True)
class OwnerContext:
    """Who this work is for, resolved server-side.

    Frozen because it is evidence, not a variable: something that could be
    reassigned between the check and the read is not a proof of ownership.

    **Never assembled from anything a caller sent** (addendum 44 §9.2). The
    Gateway resolves `subject` from the session (§93, §98); this is built from
    that and nothing else.

    It outlived the table it used to guard, and that is the point of §111's
    correction: with nothing stored, the question is no longer "whose row is
    this" but "whose work is this session doing" - which a consolidating analyst
    holding several portfolios in memory has to answer continuously rather than
    once."""

    owner_type: str
    owner_id: str

    def __post_init__(self) -> None:
        if self.owner_type not in OWNER_TYPES:
            raise UnknownVocabulary(
                f"unknown owner type {self.owner_type!r}; known are {list(OWNER_TYPES)}")
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise UnknownVocabulary("an owner context needs an owner id")
        object.__setattr__(self, "owner_id", normalise(self.owner_id))


def for_client(client_id: str) -> OwnerContext:
    return OwnerContext(OWNER_CLIENT, client_id)


def for_superuser(operator_id: str) -> OwnerContext:
    """The operator's own owner domain - not a master key over the client one.

    ## Which "Superuser" this is (§97, TQ-46 §4.2)

    Three near-synonyms exist in this codebase and they are **not** the same
    thing: the Server Superuser (`app/server_auth.py`), whose credential starts
    the workforce; the Gateway Super User (`gateway/auth.py`), the operator's
    credential at the door; and `ROLE_OPERATOR`, the role a session is issued
    under.

    `OWNER_SUPERUSER` is none of those three. It is the system's own principal -
    the backend user in `users.json` - decided by the owner on 2026-08-26. The
    first two are credentials, which is authentication; this is ownership, which
    is authorization.

    Reaffirmed the same day: builder, architect, owner and Superuser are **one
    identity**, not four roles that happen to coincide. `GATEWAY_SUPER_USER` and
    the backend username naming the same person is intentional design, held in
    place by `gateway.auth.subject_for` rather than by a convention.

    ## The id is required, and used to be `"operator"`

    A default was the wrong shape for the same reason `for_client` never had one:
    it puts a literal where a resolved identity belongs, and a literal cannot be
    wrong in a way anybody notices. It would also have been *nearly* right here,
    which is worse - a value that survives review and fails later."""
    return OwnerContext(OWNER_SUPERUSER, operator_id)


def require_owner(owner) -> OwnerContext:
    """Refuse a bare string where a proven owner is required.

    A raw id is a claim; an `OwnerContext` is the result of resolving one. Taking
    a string here would let a caller pass something a user typed into the
    position that decides whose money is visible - and it would look correct."""
    if not isinstance(owner, OwnerContext):
        raise TypeError(
            f"ownership needs an OwnerContext resolved from the session, not "
            f"{type(owner).__name__}. Use portfolios.for_client(subject).")
    return owner


def check_vocabulary(value, vocabulary: tuple[str, ...], field: str) -> str:
    if value not in vocabulary:
        raise UnknownVocabulary(
            f"unknown {field} {value!r}; known are {list(vocabulary)}")
    return value


def is_priced(portfolio: dict) -> bool:
    """Whether anything derived from a market price may be shown.

    **Known to be wrong-shaped, and deliberately unchanged here** — see the
    module docstring. §113 moves this from the portfolio's data mode to the
    price's provenance, because prices now come from the market data store while
    positions come from a broker, and a portfolio can be entirely real while the
    only available price is synthetic.

    Left as it is until TQ-73/TQ-75 give the new rule something to read. A rule
    keyed to a provenance nothing yet supplies would be machinery with no user,
    and this increment removes machinery rather than adding it."""
    return portfolio.get("data_mode") == MODE_LIVE
