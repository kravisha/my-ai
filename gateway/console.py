"""Krish's side of the loop: seeing what Jarvis noticed, and answering it.

`gateway/noticing.py` notices, `gateway/trustbook.py` records, and until this
nothing closed the loop - the sweep wrote guesses that nothing could ever settle,
so every one of them would have aged quietly into a wrong answer. A record that
only ever accumulates failures is worse than no record, because it looks like
evidence.

## Why this is a separate module, and authenticates separately

It writes `guess_verdict` records, which `dba/permissions.OWNER_WRITTEN_TYPES`
reserves for `operator_console`. That is the whole point: the agent being judged
must not hold the pen. So this runs as **Krish's** console with **Krish's**
token - the same arrangement `scripts/deploy_jarvis.py` already uses - and the
Gateway process does not have one.

The practical consequence is worth stating plainly rather than discovering later:
**a "yes" typed into a conversation with Jarvis does not settle a guess.** It
settles the *action* - `gateway/readback.py`'s mandate, which is in-process and
needs no store - and that is enough to get the work done. The durable verdict
that moves the trust ladder is a separate, slower thing that Krish records here.
Those two being different is not an oversight; if the conversation could write
verdicts then the Gateway would hold the operator's token, and there would be no
separation at all.

## Lapsing is the clock's verdict, and it still is not Jarvis's

A mention Krish never answered is settled `not_now` after
`noticing.QUIET_DAYS` - he did not want it then, which is a real answer and a
different one from *the need never existed*. It is written here rather than by
the sweep for the same reason everything else is: Jarvis does not write the
records that judge him, and "no answer" is still a judgement.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from gateway import (anticipation, dbaclient, identity, noticing, taskrun,
                     trustbook)

OPERATOR = "operator_console"
TOKEN_ENV = "DBA_TOKEN_OPERATOR_CONSOLE"
SERVICE_ENV = "DBA_SERVICE_URL"


class NoToken(RuntimeError):
    """The operator's token is not configured, so this is not Krish's console."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def operator_client(transport=None) -> dbaclient.DBAClient:
    """A client that speaks as the operator console.

    Refuses rather than falling back to Jarvis's identity: a console that
    quietly ran as the agent would write verdicts in his name, which is the one
    thing this module exists to prevent."""
    if transport is None and not (os.environ.get(TOKEN_ENV, "") or "").strip():
        raise NoToken(
            f"{TOKEN_ENV} is not set, so this is not Krish's console. Refusing "
            f"rather than running as Jarvis - a verdict written in the name of "
            f"the agent being judged is not a verdict.")
    return dbaclient.DBAClient(transport=transport, requested_by=OPERATOR,
                               actor=OPERATOR)


def mentions(client: dbaclient.DBAClient, *,
             agent: str = identity.AGENT_ID) -> list[dict]:
    """What Jarvis noticed and the ladder let him say."""
    return trustbook.pending_mentions(client, agent=agent)


def answer(client: dbaclient.DBAClient, guess_id: str, *, outcome: str,
           by: str = "krish", agent: str = identity.AGENT_ID) -> dict:
    """Krish's word on one thing Jarvis noticed.

    Three answers, because two would hide the interesting one: he wanted it, he
    did not want it *then*, or the need was not there at all."""
    # `trustbook.settle` validates this too. Kept here for the sentence rather
    # than for the check: the console is where Krish is choosing, and the answer
    # worth explaining to him is `not_now`.
    if outcome not in anticipation.OUTCOMES:
        raise ValueError(
            f"outcome must be one of {anticipation.OUTCOMES}. "
            f"{anticipation.NOT_NOW!r} is the one worth having: it says the "
            f"noticing was right and the moment was wrong, which is a different "
            f"instruction from 'stop noticing'.")
    verdict = trustbook.settle(client, guess_id, outcome=outcome, settled_by=by,
                               agent=agent)
    return verdict


def rate(client: dbaclient.DBAClient, verdict_id: str, *, quality: str,
         by: str = "krish") -> dict:
    """How the work turned out, once Krish has seen it."""
    return trustbook.rate(client, verdict_id, quality=quality, rated_by=by)


def lapse(client: dbaclient.DBAClient, *, agent: str = identity.AGENT_ID,
          now: datetime | None = None) -> list[str]:
    """Settle the mentions Krish never answered, as `not_now`.

    Not `wrong`: he may well have needed the thing and simply not wanted it
    raised then. Recording silence as a bad guess teaches Jarvis to stop
    noticing, when the lesson available is to wait."""
    when = now or _now()
    cutoff = when - timedelta(days=noticing.QUIET_DAYS)
    lapsed = []
    for row in mentions(client, agent=agent):
        said = trustbook._parse(row.get("said_at")) or \
            trustbook._parse(row.get("made_at"))
        if said is not None and said <= cutoff:
            trustbook.settle(client, row["id"], outcome=anticipation.NOT_NOW,
                             settled_by="no answer", agent=agent)
            lapsed.append(row["id"])
    return lapsed


def standing(client: dbaclient.DBAClient, domain: str, *,
             agent: str = identity.AGENT_ID):
    return trustbook.standing(client, domain, agent=agent)


# --- questions from work in progress (TQ-119) -----------------------------------
#
# `gateway/taskrun.py` parks a question when it cannot find something and
# carries on with the rest. This is where Krish sees them and answers. The
# answer goes back through `Need.answered`, so it is refused unless it comes
# from the person the question was put to, and the run is saved before this
# returns - an answer that lived only in this process would be lost the moment
# the console closed.


def questions(client: dbaclient.DBAClient) -> tuple[list[dict], dict[str, str]]:
    """Every open question across every stored run, and every run that would
    not load. The second is shown, not hidden: its questions are in it."""
    runs, corrupt = taskrun.stored_runs(client)
    waiting = []
    for name in sorted(runs):
        for asked in runs[name].open_questions():
            waiting.append({"run": name, "goal": runs[name].goal,
                            "line": asked.about, "asked": asked.asked,
                            "tried": asked.tried, "of": asked.of})
    return waiting, corrupt


def _stored(client: dbaclient.DBAClient, run: str) -> taskrun.Run:
    found = taskrun.load(client, run)
    if found is None:
        raise taskrun.NotFound(f"no stored run called {run!r}")
    return found


def reply(client: dbaclient.DBAClient, run: str, line: str, value: str, *,
          by: str = "krish") -> taskrun.Need:
    """Answer one parked question and save the run."""
    work = _stored(client, run)
    need = work.need(line).answered(value, by=by)
    taskrun.save(client, run, work, reason=f"{by} answered {line!r}")
    return need


def leave_out(client: dbaclient.DBAClient, run: str, line: str, *,
              because: str, by: str = "krish") -> taskrun.Need:
    """Krish's decision that a line does not belong this time."""
    work = _stored(client, run)
    need = work.need(line).waive(by=by, because=because)
    taskrun.save(client, run, work, reason=f"{by} left out {line!r}")
    return need


def describe() -> dict:
    return {
        "speaks_as": OPERATOR,
        "writes": ["guess_verdict", "answers to parked task questions"],
        "a_conversational_yes_settles_a_guess": False,
        "silence_is": anticipation.NOT_NOW,
    }


def main(argv=None) -> int:
    """`python -m gateway.console` - Krish's side, from a terminal."""
    parser = argparse.ArgumentParser(
        description="See what Jarvis noticed, and answer it.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("mentions", help="what Jarvis noticed and may say")

    answered = commands.add_parser("answer", help="settle one")
    answered.add_argument("guess_id")
    answered.add_argument("--outcome", required=True,
                          choices=list(anticipation.OUTCOMES))
    answered.add_argument("--by", default="krish")

    judged = commands.add_parser("rate", help="say how the work turned out")
    judged.add_argument("verdict_id")
    judged.add_argument("--quality", required=True,
                        choices=list(anticipation.QUALITIES))
    judged.add_argument("--by", default="krish")

    commands.add_parser("lapse", help="settle what was never answered")

    commands.add_parser("questions", help="what work in progress is asking")

    replied = commands.add_parser("reply", help="answer one of those")
    replied.add_argument("run")
    replied.add_argument("line")
    replied.add_argument("answer")
    replied.add_argument("--by", default="krish")

    left = commands.add_parser("leave-out", help="drop a line from this run")
    left.add_argument("run")
    left.add_argument("line")
    left.add_argument("--because", required=True)
    left.add_argument("--by", default="krish")

    shown = commands.add_parser("standing", help="what a domain has earned")
    shown.add_argument("domain")

    args = parser.parse_args(argv)
    try:
        client = operator_client()
    except NoToken as refused:
        print(refused, file=sys.stderr)
        return 2

    if args.command == "mentions":
        rows = mentions(client)
        if not rows:
            print("Nothing waiting.")
        for row in rows:
            print(f"{row['id']}  [{row.get('domain')}] {row.get('what')}")
            print(f"    because {row.get('because')}")
        return 0
    if args.command == "answer":
        verdict = answer(client, args.guess_id, outcome=args.outcome,
                         by=args.by)
        print(f"recorded {verdict['id']}")
        return 0
    if args.command == "rate":
        rate(client, args.verdict_id, quality=args.quality, by=args.by)
        print("recorded")
        return 0
    if args.command == "lapse":
        print(f"{len(lapse(client))} mention(s) settled as "
              f"{anticipation.NOT_NOW}")
        return 0
    if args.command == "questions":
        waiting, corrupt = questions(client)
        for name, why in sorted(corrupt.items()):
            print(f"CANNOT LOAD {name}: {why}")
        if not waiting and not corrupt:
            print("Nothing waiting.")
        for one in waiting:
            print(f"{one['run']} / {one['line']}: {one['asked']}")
            print(f"    already tried: {one['tried']}")
        return 1 if corrupt else 0
    if args.command in ("reply", "leave-out"):
        try:
            if args.command == "reply":
                reply(client, args.run, args.line, args.answer, by=args.by)
            else:
                leave_out(client, args.run, args.line, because=args.because,
                          by=args.by)
        except (taskrun.NotFound, taskrun.NotYours, taskrun.Corrupt) as refused:
            print(refused, file=sys.stderr)
            return 2
        print("recorded")
        return 0
    earned = standing(client, args.domain)
    print(f"{args.domain}: {earned.rung}")
    print(f"  {earned.because}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
