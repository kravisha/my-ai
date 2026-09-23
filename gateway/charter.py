"""Krish's explicit permission, as a record rather than an argument.

Krish, 2026-09-23:

> *"Things such as the constitution need the explicit permission of the human to
> be changed. They are read only principles to act by. Ideally intelligent and
> coherent AI will not indulge in such abominations such as changing the
> constitution illegally. However, we do need to put the necessary safeguards
> from rogue or hallucinating AI - so the explicit rule as the safe safeguard
> that owner permissions necessary to change the constitution."*

The first version of the keyed tiers in `gateway/introspect.py` took the keys as
a **function argument** to `selfmod.propose`. Jarvis is the caller, so Jarvis
could hand himself the charter key. That is fine for an agent that is working
correctly and worthless against the two cases this is for: a rogue one, and a
confused one. A safeguard that only holds while the thing it guards against is
behaving is not a safeguard.

So a key is a `charter_grant` record, and `dba/permissions.OWNER_WRITTEN_TYPES`
makes **every write** to that type need `administer`, which only the operator
console holds. Jarvis can read his grants. He cannot write one, cannot revive a
revoked one, and cannot move an expiry - because moving it is a write.

## Why the expiry cannot be a status Jarvis flips

A one-shot grant needs somebody to mark it spent, and Jarvis holds `update` on
every ordinary type. If spending were a status change he could unspend it. So
validity is computed from `expires_at`, which is set once at grant time by the
only agent that can set it, and read here. Nothing Jarvis does moves it.

## What this is not

It is not a claim that Jarvis is prevented from changing the constitution by
other means. He runs as a process with a filesystem. What it does is make the
*sanctioned* path require the owner, and make the unsanctioned one leave the
record: an amendment with no matching grant is detectable, and
`verify_amendments` is what detects it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gateway import dbaclient, identity, introspect, ledger

ENTITY_TYPE = "charter_grant"

ACTIVE = "active"
REVOKED = "revoked"

# How long a grant lasts unless the owner says otherwise. Short: a standing
# permission to amend the constitution is most of the way to no permission at
# all, and Krish is present when he grants it.
DEFAULT_MINUTES = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp) -> datetime | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def grant(client: dbaclient.DBAClient, *, key: str, granted_by: str,
          minutes: int = DEFAULT_MINUTES, scope: str = "", note: str = "",
          interface: str = "cli", agent: str = identity.AGENT_ID) -> dict:
    """Record the owner's permission. Refused unless the caller is the operator.

    The refusal is the DBA's, not this function's, and that is deliberate: a
    check here would be code Jarvis can propose changes to, while the DBA's
    permission table is a different service reached over HTTP."""
    if key not in introspect.KEYS:
        raise ValueError(f"{key!r} is not one of {introspect.KEYS}")
    if not (granted_by or "").strip():
        raise ValueError("a grant must say who granted it; an unattributed "
                         "permission is indistinguishable from one nobody gave")
    now = _now()
    data = {
        "name": f"{key} key for {granted_by}"[:200],
        "agent": agent,
        "key": key,
        "granted_by": granted_by.strip(),
        "granted_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(minutes=max(1, int(minutes)))
                       ).isoformat(timespec="seconds"),
        "scope": scope,
        "note": note,
        "interface": interface,
        "status": ACTIVE,
    }
    data["id"] = client.create(ENTITY_TYPE, data, reason="owner granted a key")
    return data


def grants(client: dbaclient.DBAClient, *,
           agent: str = identity.AGENT_ID) -> list[dict]:
    return client.find(ENTITY_TYPE, {"agent": agent}, limit=50)


def keys_in_force(client: dbaclient.DBAClient, *,
                  agent: str = identity.AGENT_ID,
                  now: datetime | None = None) -> tuple[str, ...]:
    """Which keys the owner has granted and not yet let lapse.

    Read from the store on every call rather than cached. A cached answer would
    be one Jarvis's own process holds, and the point of the record is that the
    answer lives somewhere he cannot write."""
    when = now or _now()
    held = set()
    for row in grants(client, agent=agent):
        if (row.get("status") or ACTIVE) != ACTIVE:
            continue
        expires = _parse(row.get("expires_at"))
        if expires is None or expires <= when:
            continue
        if row.get("key") in introspect.KEYS:
            held.add(row["key"])
    return tuple(sorted(held))


def explain(client: dbaclient.DBAClient, key: str, *,
            agent: str = identity.AGENT_ID, now: datetime | None = None) -> str:
    """Why a key is or is not in force, in words a proposal can carry.

    Separate from `keys_in_force` because a bare "no" sends the reader looking
    for a bug, and the reasons - never granted, lapsed, revoked - have different
    next steps. `now` is taken rather than read so that this and the check it
    explains can never disagree about the time, which is exactly how an
    explanation comes to contradict the decision it is explaining.

    The branches are ordered and total. A first version had no branch for "in
    force" and fell through to "revoked", so a live grant was explained as a
    revoked one - a default that asserted something false rather than saying
    nothing."""
    when = now or _now()
    rows = [row for row in grants(client, agent=agent) if row.get("key") == key]
    if not rows:
        return (f"no {key!r} key has ever been granted. Krish grants one from "
                f"the operator console; Jarvis cannot write the record, which "
                f"is the safeguard rather than an inconvenience.")

    live = [row for row in rows
            if (row.get("status") or ACTIVE) == ACTIVE
            and (_parse(row.get("expires_at")) or when) > when]
    if live:
        newest = max(live, key=lambda row: str(row.get("expires_at")))
        return (f"the {key!r} key is in force until {newest.get('expires_at')}, "
                f"granted by {newest.get('granted_by')}.")

    unrevoked = [row for row in rows
                 if (row.get("status") or ACTIVE) != REVOKED]
    if unrevoked:
        newest = max(unrevoked, key=lambda row: str(row.get("expires_at")))
        return (f"the {key!r} key lapsed at {newest.get('expires_at')}. Grants "
                f"are short on purpose - a standing permission to amend the "
                f"constitution is most of the way to no permission at all.")
    return (f"the {key!r} key was revoked. Krish can grant another; nothing "
            f"here can.")


def note_amendment(client: dbaclient.DBAClient, *, what: str, why: str,
                   granted_by: str, agent: str = identity.AGENT_ID) -> None:
    """Record that the charter changed, and on whose authority."""
    ledger.append(client, event_type=ledger.DECISION,
                  summary=f"charter amended: {what}"[:200],
                  observation=f"{why} | authorised by {granted_by}",
                  actor="charter", verification_state=ledger.ASSERTED_BY_USER,
                  agent=agent)


def describe() -> dict:
    return {
        "entity_type": ENTITY_TYPE,
        "keys": list(introspect.KEYS),
        "default_minutes": DEFAULT_MINUTES,
        "written_by": "operator console only",
        "read_by": "jarvis",
    }
