"""Bootstrap and rehydration: how a fresh Jarvis process becomes *this* Jarvis.

§3's sequence, in order, with one deliberate difference. The specification's
step 3 is *"bring the DBA Agent online"*; this module **verifies** the DBA is
online and does not start it. Starting it is the supervisor's job, for §19's
reason - the runtime that could start and stop the service holding its own
memory is the runtime that can destroy the thing responsible for its recovery.
`scripts/keep-jarvis-up.ps1` starts the DBA first and the Gateway second.

## The rule this module exists to enforce

    §10: "JARVIS must never claim to remember something that was not
    successfully restored."

That is not a rule a docstring can keep. So restoration does not return a
dictionary of values - it returns a `Restoration`, and every value inside it
carries how it got there: `restored`, `reconstructed`, `inferred`,
`re_verified` or `unavailable`. `Restoration.assert_fact()` raises on anything
that is not first-hand, which means a caller that wants to state something as
remembered has to have it as remembered. A caller can still lie, but it can no
longer do so by accident, and the accident is the failure mode that was worth
engineering against.

## A failed restore is a state, not an exception

An unreachable DBA does not stop Jarvis from operating. It stops him from
*claiming memory*, which is a different thing, and §34 wants the difference
represented. `Restoration.failure_states` carries the §34 names, and
`gateway/failures.py` says for each one whether Krish has to be told.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from gateway import checkpoint as checkpoint_module
from gateway import dbaclient, failures, identity, ledger, persistence

# §3 step 9. A state item whose stored value carries this flag is one whose
# truth decays - an address, a price, a schedule. It comes back as
# `re_verify_first` rather than as plain memory, because the specification asks
# Jarvis to re-verify time-sensitive facts *when relevant* and he cannot do
# that if nothing remembers which ones they are.
TIME_SENSITIVE_FLAG = "time_sensitive"

RESTORED_OK = "restored"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Item:
    """One restored thing, and how Jarvis came to have it."""

    kind: str
    name: str
    value: Any
    memory_state: str
    revision: int = 0
    note: str = ""

    @property
    def first_hand(self) -> bool:
        return self.memory_state in (persistence.RESTORED, persistence.RE_VERIFIED)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name, "value": self.value,
                "memory_state": self.memory_state, "revision": self.revision,
                "note": self.note}


class NotRemembered(LookupError):
    """§10, enforced. Something was asserted as memory that is not memory."""


@dataclass
class Restoration:
    """What came back, what did not, and what Jarvis is therefore allowed to say."""

    status: str = RESTORED_OK
    at: str = field(default_factory=_now)
    code_version: str | None = None
    agent_id: str = identity.AGENT_ID
    items: list[Item] = field(default_factory=list)
    unavailable: list[dict] = field(default_factory=list)
    needs_reverification: list[str] = field(default_factory=list)
    failure_states: list[str] = field(default_factory=list)
    checkpoint: dict | None = None
    skipped_checkpoints: list[dict] = field(default_factory=list)
    ledger_verdict: dict | None = None
    interval_at_risk: dict | None = None
    reconciled: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # --- what Jarvis may say --------------------------------------------------

    def recall(self, kind: str, name: str) -> Item | None:
        for item in self.items:
            if item.kind == kind and item.name == name:
                return item
        return None

    def assert_fact(self, kind: str, name: str) -> Any:
        """The value, if it is genuinely remembered. Otherwise raise.

        The raise is the feature. A caller that wanted a default could have
        asked `recall`; this one said it was about to state something as
        remembered."""
        item = self.recall(kind, name)
        if item is None:
            raise NotRemembered(
                f"{kind}/{name} was not restored, so Jarvis does not remember "
                f"it. §10: missing memory is not filled with confident "
                f"fabrication.")
        if not item.first_hand:
            raise NotRemembered(
                f"{kind}/{name} came back as {item.memory_state!r}, not as "
                f"restored memory. Say how it was obtained, or re-verify it "
                f"before stating it.")
        return item.value

    def of_kind(self, kind: str) -> list[Item]:
        return [item for item in self.items if item.kind == kind]

    @property
    def complete(self) -> bool:
        return self.status == RESTORED_OK and not self.unavailable

    def must_tell_user(self) -> bool:
        return any(failures.must_tell_user(name) for name in self.failure_states)

    def sentences(self) -> list[str]:
        """What to say out loud about this restoration, in plain English.

        Empty when there is nothing to report - a clean restore does not need
        announcing, and announcing it every time is how a real warning gets
        ignored."""
        said = []
        for name in self.failure_states:
            if failures.must_tell_user(name):
                said.append(failures.sentence(name, self._detail_for(name)))
        if self.needs_reverification:
            said.append(
                f"{len(self.needs_reverification)} remembered item(s) are "
                f"time-sensitive and should be re-checked before being relied "
                f"on: {', '.join(sorted(self.needs_reverification)[:5])}.")
        return said

    def _detail_for(self, name: str) -> str:
        if name == failures.PARTIAL_RESTORE:
            return (f"{len(self.items)} item(s) restored, "
                    f"{len(self.unavailable)} unavailable")
        if name == failures.CHECKPOINT_INVALID:
            return ", ".join(
                f"{record.get('name')}: {record.get('invalid_reason')}"
                for record in self.skipped_checkpoints) or "no reason recorded"
        if name == failures.DBA_UNAVAILABLE and self.unavailable:
            return str(self.unavailable[0].get("why", ""))[:200]
        return ""

    def to_dict(self) -> dict:
        return {
            "status": self.status, "at": self.at, "agent_id": self.agent_id,
            "code_version": self.code_version,
            "items": [item.to_dict() for item in self.items],
            "unavailable": self.unavailable,
            "needs_reverification": self.needs_reverification,
            "failure_states": self.failure_states,
            "checkpoint": (self.checkpoint or {}).get("name"),
            "skipped_checkpoints": [record.get("name")
                                    for record in self.skipped_checkpoints],
            "ledger_verdict": self.ledger_verdict,
            "interval_at_risk": self.interval_at_risk,
            "reconciled": len(self.reconciled),
            "notes": self.notes,
        }


# --- §3's sequence ------------------------------------------------------------


def bootstrap(client: dbaclient.DBAClient | None = None, *,
              agent: str = identity.AGENT_ID,
              verify_ledger: bool = True) -> Restoration:
    """Run §3's startup sequence and return an honest account of it.

    Never raises for a missing or broken store. The one thing this function
    must not do is fail in a way that leaves the caller with no report, because
    a caller with no report is a Jarvis with no idea what he does or does not
    know."""
    restoration = Restoration(code_version=identity.code_version(), agent_id=agent)

    # Step 2: the minimum bootstrap configuration. Deliberately just enough to
    # find the DBA - everything else is supposed to come *from* the DBA, and
    # config that shortcuts that is config that can disagree with the store.
    if not dbaclient.is_configured():
        restoration.status = failures.RESTORE_FAILED
        restoration.failure_states.append(failures.DBA_UNAVAILABLE)
        restoration.unavailable.append({
            "what": "all persistent state",
            "why": f"no DBA token is configured ({dbaclient.TOKEN_ENV} is "
                   f"unset), so this runtime has never been able to reach the "
                   f"store."})
        return restoration

    client = client or dbaclient.DBAClient()

    # Steps 3 and 4: the DBA is up, and its store is healthy.
    try:
        health = client.health()
    except dbaclient.Unavailable as exc:
        restoration.status = failures.RESTORE_FAILED
        restoration.failure_states.append(failures.DBA_UNAVAILABLE)
        restoration.unavailable.append({"what": "all persistent state",
                                        "why": str(exc)})
        return restoration
    restoration.notes.append(
        f"DBA reported {health.get('status', 'no status')}")

    # A crash part-way through a `put` can leave two live revisions. Resolve it
    # once, here, rather than letting every later read resolve it again.
    try:
        restoration.reconciled = persistence.reconcile(client, agent=agent)
    except (dbaclient.Unavailable, dbaclient.Refused) as exc:
        restoration.notes.append(f"could not reconcile state revisions: {exc}")

    # Step 5: the most recent state the DBA can vouch for.
    try:
        record, skipped = checkpoint_module.newest_usable(client, agent=agent)
    except (dbaclient.Unavailable, dbaclient.Refused) as exc:
        record, skipped = None, []
        restoration.notes.append(f"could not read checkpoints: {exc}")
    restoration.checkpoint = record
    restoration.skipped_checkpoints = skipped
    if skipped:
        restoration.failure_states.append(failures.CHECKPOINT_INVALID)

    # Step 6: restore. The live state is what Jarvis resumes from; the
    # checkpoint says which part of it was last known good, and names the
    # interval that came after.
    try:
        rows = persistence.current(client, agent=agent, limit=500)
    except (dbaclient.Unavailable, dbaclient.Refused) as exc:
        restoration.status = failures.RESTORE_FAILED
        restoration.failure_states.append(failures.RESTORE_FAILED)
        restoration.unavailable.append({"what": "durable state", "why": str(exc)})
        rows = []

    for row in rows:
        value = persistence.decode(row)
        state = persistence.RESTORED
        note = ""
        if isinstance(value, dict) and value.get(TIME_SENSITIVE_FLAG):
            note = "time-sensitive: re-verify before relying on it"
            restoration.needs_reverification.append(
                f"{row.get('kind')}/{row.get('name')}")
        restoration.items.append(Item(
            kind=row.get("kind") or "unknown",
            name=row.get("name") or "unnamed",
            value=value, memory_state=state,
            revision=int(row.get("revision") or 0), note=note))

    # Step 8, and the reason the ledger is verified rather than trusted: an
    # unverified ledger is a memory Jarvis would quote with confidence.
    if verify_ledger:
        try:
            restoration.ledger_verdict = ledger.replay(client, agent=agent)
        except (dbaclient.Unavailable, dbaclient.Refused, ledger.ChainBroken) as exc:
            restoration.ledger_verdict = {"intact": False, "breaks": [
                {"problem": "unreadable", "detail": str(exc)}]}
        if not restoration.ledger_verdict.get("intact", False):
            restoration.unavailable.append({
                "what": "part of the life ledger",
                "why": "the hash chain did not verify; events after the first "
                       "break cannot be trusted as a record of what happened"})

    if record is not None:
        try:
            restoration.interval_at_risk = checkpoint_module.interval_at_risk(
                client, record, agent=agent)
        except (dbaclient.Unavailable, dbaclient.Refused) as exc:
            restoration.notes.append(f"could not measure the interval: {exc}")
    elif rows:
        restoration.notes.append(
            "no valid checkpoint, so there is no known-good point to fall back "
            "to; the live state was restored as it stands")

    # Steps 8 and 10: say what this adds up to.
    if restoration.status != failures.RESTORE_FAILED:
        if restoration.unavailable:
            restoration.status = failures.PARTIAL_RESTORE
            restoration.failure_states.append(failures.PARTIAL_RESTORE)
        else:
            restoration.status = RESTORED_OK

    _record_restoration(client, restoration, agent=agent)
    return restoration


def _record_restoration(client: dbaclient.DBAClient, restoration: Restoration,
                        *, agent: str) -> None:
    """Write the restoration into the ledger, and survive not being able to.

    A boot that could not record itself is worth a note in the report; it is
    not worth failing the boot, which would make an unwritable ledger into an
    outage."""
    try:
        ledger.append(
            client, event_type=ledger.RESTORE_REPORT,
            summary=(f"restored {len(restoration.items)} state item(s) as "
                     f"{restoration.status}"),
            observation=(f"unavailable: {len(restoration.unavailable)}; "
                         f"checkpoint: "
                         f"{(restoration.checkpoint or {}).get('name')}"),
            assessment=restoration.status,
            verification_state=ledger.VERIFIED,
            checkpoint_id=(restoration.checkpoint or {}).get("id"),
            actor="bootstrap", agent=agent)
    except (ledger.LedgerWriteFailed, ledger.ChainBroken, ValueError) as exc:
        restoration.notes.append(f"restoration was not recorded in the ledger: {exc}")
        if failures.LEDGER_WRITE_FAILED not in restoration.failure_states:
            restoration.failure_states.append(failures.LEDGER_WRITE_FAILED)
