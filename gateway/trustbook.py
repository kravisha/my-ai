"""Where the trust ladder's record is kept, so a restart does not reset it.

`gateway/anticipation.py` decides what a record means and touches no store. This
is the store, and it exists because the record was living in a Python list: every
restart wiped what Jarvis had earned, which made the ladder as useless as it was
before `rate` existed. A record that evaporates is the same failure as a ladder
nothing can climb, wearing a different hat.

## The guess is his; the verdict is not

Split across two entity types on purpose:

- **`guess`** - what he thought Krish would want, and why. His to write. An
  assistant who cannot record a prediction cannot be judged on one.
- **`guess_verdict`** - whether he was right, and how well he then did it.
  `dba/permissions.OWNER_WRITTEN_TYPES` holds this type, so writing one needs
  `administer`, which only the operator console has.

The refusal that matters here is the DBA's, in another service, over HTTP. The
checks in `anticipation.settle` and `anticipation.rate` are still worth having -
they catch the honest mistake at the call site and say why - but a check inside
the process being judged is advice. This is the part that holds when the advice
is ignored.

## Loading is a join, and a hostile one

`load` reads the guesses and the verdicts separately and matches them up. A guess
with no verdict is unsettled; a verdict naming a guess that does not exist is
reported rather than skipped, because the interesting failure here is not a
missing row - it is an extra one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gateway import anticipation, dbaclient, identity

GUESS = "guess"
VERDICT = "guess_verdict"

OPEN = "open"
SETTLED = "settled"


def _parse(stamp) -> datetime | None:
    if not stamp:
        return None
    try:
        # Coerced to a string first, so a number or a list from a hand-edited
        # row fails as a parse rather than as a type error. Catching TypeError
        # as well looked like belt and braces and was unreachable for exactly
        # that reason.
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _stamp(when: datetime | None) -> str | None:
    """Microseconds, not seconds.

    `standing` orders the faultless run by when work was rated, and two ratings
    a moment apart are common - Krish looks at three results and says yes, yes,
    no. At second granularity those three stamps are identical, the sort is
    arbitrary, and a failure can sort ahead of the successes that followed it.
    `gateway/persistence.py` hit exactly this and for exactly this reason."""
    return when.isoformat(timespec="microseconds") if when else None


def _now_stamp() -> str:
    return _stamp(datetime.now(timezone.utc))


def record(client: dbaclient.DBAClient, guess: anticipation.Guess, *,
           agent: str = identity.AGENT_ID) -> str:
    """Write down a guess, before anybody knows how it turns out."""
    data = {
        "name": f"{guess.domain}: {guess.what}"[:200],
        "agent": agent,
        "domain": guess.domain,
        "what": guess.what,
        "because": guess.because,
        "made_at": _stamp(guess.made_at),
        "status": OPEN,
    }
    if guess.by_when:
        data["by_when"] = _stamp(guess.by_when)
    return client.create(GUESS, data, reason="anticipated what Krish would want")


def settle(client: dbaclient.DBAClient, guess_id: str, *, outcome: str,
           settled_by: str, agent: str = identity.AGENT_ID) -> dict:
    """Record Krish's word on a guess. Refused for Jarvis by the DBA.

    The refusal is the DBA's rather than this function's, deliberately: a check
    here would be code in the process being judged."""
    if outcome not in anticipation.OUTCOMES:
        raise ValueError(f"outcome must be one of {anticipation.OUTCOMES}")
    if not (settled_by or "").strip():
        raise ValueError("a verdict must say who gave it")
    data = {
        "name": f"verdict on {guess_id}"[:200],
        "agent": agent,
        "guess_id": guess_id,
        "outcome": outcome,
        "settled_by": settled_by.strip(),
        "settled_at": _now_stamp(),
        "status": "recorded",
    }
    data["id"] = client.create(VERDICT, data, reason="Krish settled a guess")
    return data


def rate(client: dbaclient.DBAClient, verdict_id: str, *, quality: str,
         rated_by: str) -> dict:
    """Record how the work turned out, on the verdict that settled the guess."""
    if quality not in anticipation.QUALITIES:
        raise ValueError(f"quality must be one of {anticipation.QUALITIES}")
    if not (rated_by or "").strip():
        raise ValueError("a rating must say who gave it")
    changes = {
        "quality": quality,
        "rated_by": rated_by.strip(),
        "rated_at": _now_stamp(),
    }
    client.update(verdict_id, changes, reason="Krish rated the work")
    return changes


def load(client: dbaclient.DBAClient, *, domain: str | None = None,
         agent: str = identity.AGENT_ID, limit: int = 500
         ) -> tuple[list[anticipation.Guess], list[str]]:
    """Rebuild the record. Returns the guesses and anything that did not add up.

    A verdict naming a guess that is not there is **reported**, not skipped. A
    missing row is ordinary - a guess can be archived - but an extra verdict is
    the shape a forged promotion would take, and a loader that quietly dropped
    it would be the one place nobody looks."""
    criteria = {"agent": agent}
    if domain is not None:
        criteria["domain"] = domain
    rows = client.find(GUESS, criteria, limit=limit)
    verdicts = client.find(VERDICT, {"agent": agent}, limit=limit * 2)

    by_guess: dict[str, dict] = {}
    problems: list[str] = []
    known = {row["id"] for row in rows}
    for verdict in verdicts:
        target = verdict.get("guess_id")
        if target not in known:
            problems.append(
                f"verdict {verdict.get('id')} names guess {target!r}, which is "
                f"not in the record. Jarvis cannot write a verdict, so one "
                f"pointing at nothing is either an archived guess or a row that "
                f"should not exist.")
            continue
        if target in by_guess:
            problems.append(
                f"guess {target!r} has more than one verdict. A guess is settled "
                f"once; a second verdict would let a bad week be revised.")
            continue
        by_guess[target] = verdict

    made = []
    for row in rows:
        guess = anticipation.Guess(
            domain=row.get("domain") or "",
            what=row.get("what") or "",
            because=row.get("because") or "",
            made_at=_parse(row.get("made_at")) or datetime.now(timezone.utc),
            by_when=_parse(row.get("by_when")))
        verdict = by_guess.get(row["id"])
        if verdict:
            guess.outcome = verdict.get("outcome")
            guess.settled_at = _parse(verdict.get("settled_at"))
            guess.settled_by = verdict.get("settled_by") or ""
            guess.quality = verdict.get("quality")
            guess.rated_at = _parse(verdict.get("rated_at"))
            guess.rated_by = verdict.get("rated_by") or ""
        made.append(guess)
    return made, problems


def standing(client: dbaclient.DBAClient, domain: str, *,
             agent: str = identity.AGENT_ID) -> anticipation.Standing:
    """What this domain has earned, read from the store rather than memory."""
    made, _ = load(client, agent=agent)
    return anticipation.standing(domain, made)


def describe() -> dict:
    return {
        "guess_written_by": "jarvis",
        "verdict_written_by": "the operator console only",
        "survives_a_restart": True,
    }
