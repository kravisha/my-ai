"""Rev A: atomic execution approval.

Contract: claude-dev/REVA-DBA-CONTRACT-v1.md, §0-§4b, agreed on hub issue 2
with Arya (5817683027, 5817725747, 5817747006) and Claude Deploy (5817660216,
5817735838).

## Why this module exists

`gateway/selfmod.decide()` records a decision and then updates the proposal in
a second, separate call, and nothing ties the approval to the bytes that later
run: `commit_id` is an ordinary field anyone can rewrite. So an approval could
be granted for one thing and used to launch another. Here every step that
matters is ONE transaction, opened with BEGIN IMMEDIATE before anything
authoritative is read, and the approval is bound to a content digest and a
frozen git tree.

## The lifecycle

    approved (planning) --freeze_candidate--> awaiting_execution_approval
      --approve_change--> approved_for_execution | denied
      --claim_attempt--> attempt 'claimed' --finish_attempt--> launched
      --validate_attempt--> attempt 'completed', proposal accepted|degraded|failed

Narrowing is never an edit: `revise_proposal` writes a NEW proposal in the same
change family and moves the old one to `superseded`, keeping its decisions.

## What a refusal does

Nothing. Every refusal is raised inside the transaction, so a partly written
decision or claim rolls back with it. The one exception is deliberate and
outside the rejected transition: a BLOCKED validation leaves a single
diagnostic audit row, labelled in its reason, once per request_id - so "nothing
was changed" can be told apart from "nothing ran".
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.db import Contended, Database, now_iso

# --- codes --------------------------------------------------------------------

VALIDATION_ERROR = "VALIDATION_ERROR"
DIGEST_MISMATCH = "DIGEST_MISMATCH"
WRONG_STATE = "WRONG_STATE"
STALE_WRITE = "STALE_WRITE"
CONTENDED = "CONTENDED"
REPLAY_CONFLICT = "REPLAY_CONFLICT"
ATTEMPT_EXISTS = "ATTEMPT_EXISTS"
ARTIFACT_MISMATCH = "ARTIFACT_MISMATCH"
STALE_VALIDATION = "STALE_VALIDATION"
DIRTY_DEPLOYMENT = "DIRTY_DEPLOYMENT"
UNVERIFIED_RUNTIME = "UNVERIFIED_RUNTIME"

# Validation refusals learn nothing about the candidate, so they are BLOCKED,
# never FAILED (Deploy 5817660216, Arya 5817683027).
BLOCKED_CODES = (STALE_VALIDATION, DIRTY_DEPLOYMENT, UNVERIFIED_RUNTIME)

# --- states -------------------------------------------------------------------

PLANNING_APPROVED = "approved"
AWAITING_EXECUTION = "awaiting_execution_approval"
APPROVED_FOR_EXECUTION = "approved_for_execution"
DENIED = "denied"
SUPERSEDED = "superseded"

# Statuses only this module may set; the generic update path refuses them.
EXECUTION_STATUSES = (AWAITING_EXECUTION, APPROVED_FOR_EXECUTION, SUPERSEDED)

PROPOSAL_TYPE = "change_proposal"

# Fields only this module may write (§6).
PROTECTED_FIELDS = ("candidate_artifact", "approved_digest", "approved_decision_id",
                    "rejected_decision_id", "change_id", "supersedes", "superseded_by")
# NOT post_validation_state: contract §6 never listed it, and the existing
# selfmod.post_relaunch_validate writes it through the generic path. Moving that
# writer onto validate_attempt is Deploy's seam; until it lands, protecting the
# field only breaks the legacy path (16-test full-suite regression, 12:26).

CLAIMED, LAUNCHED, UNCERTAIN, FAILED, COMPLETED = (
    "claimed", "launched", "uncertain", "failed", "completed")
UNRESOLVED = (CLAIMED, LAUNCHED, UNCERTAIN)
ATTEMPT_STATES = (CLAIMED, LAUNCHED, UNCERTAIN, FAILED, COMPLETED)
# The launcher owns these; only validate_attempt sets COMPLETED (§4b.5).
LAUNCHER_TRANSITIONS = {LAUNCHED: (CLAIMED,), FAILED: (CLAIMED, LAUNCHED),
                        UNCERTAIN: (CLAIMED, LAUNCHED)}

RESULTS = ("accepted", "degraded", "failed")

# Runtime inputs no evidence this module receives can speak to, so no verdict
# may imply them. Reported on every validation, not only when something failed.
NEVER_MEASURED = ("process memory", "code outside the declared distributions "
                  "(base interpreter paths, .pth additions, non-pip installs)",
                  "same-name same-version source changes", "host configuration")
UNVERIFIED = "UNVERIFIED"

# --- §5 the digest ---------------------------------------------------------------

DIGEST_FIELDS = ("gap_id", "proposal_version", "reason", "scope", "affected_components",
                 "affected_files", "risk", "expected_benefit", "test_plan",
                 "rollback_plan", "baseline_version", "target_branch",
                 "candidate_artifact")

_ARTIFACT = re.compile(r"^git-tree:[0-9a-f]{40}@base:[0-9a-f]{40}$")
_DIGEST = re.compile(r"^digest_v1:[0-9a-f]{64}$")
_DECISION = re.compile(r"^dec-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ATTEMPT = re.compile(r"^att-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ApprovalError(ValueError):
    def __init__(self, code: str, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


@dataclass(frozen=True)
class Result:
    ok: bool
    code: str | None = None
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    replayed: bool = False


def _digest_value(name: str, value: Any) -> Any:
    # bool is an int subclass in Python; a True where a version belongs is a
    # bug upstream, not the number 1.
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return sorted(value)
    raise ApprovalError(VALIDATION_ERROR,
                        f"{name}={value!r}: digest values are str, int, list[str] or null; "
                        f"anything else is refused rather than coerced")


def content_digest(proposal: dict) -> str:
    """sha256 over canonical JSON of exactly DIGEST_FIELDS. Computed here, never
    by a client: a digest the caller supplies is a digest the caller chose."""
    canonical = {name: _digest_value(name, proposal.get(name)) for name in DIGEST_FIELDS}
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "digest_v1:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- schema ---------------------------------------------------------------------

SCHEMA = """
-- Replay is keyed (operation, request_id) GLOBALLY, with the authenticated
-- principal stored beside it: a second principal reusing an id is a conflict,
-- not a separate namespace (Arya 5817683027 item 3).
CREATE TABLE IF NOT EXISTS approval_requests (
    operation TEXT NOT NULL,
    request_id TEXT NOT NULL,
    principal TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    response_json TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (operation, request_id)
);

CREATE TABLE IF NOT EXISTS change_attempts (
    attempt_id TEXT PRIMARY KEY,
    -- One decision gives at most one attempt. A retry needs a fresh approval.
    decision_id TEXT NOT NULL UNIQUE,
    proposal_id TEXT NOT NULL,
    change_id TEXT NOT NULL,
    state TEXT NOT NULL,
    candidate_artifact TEXT NOT NULL,
    environment_at_claim TEXT NOT NULL,
    -- Observed by the launcher at launch; validation must re-observe the same.
    pid INTEGER,
    start_ticks INTEGER,
    launched_artifact TEXT,
    -- WHO reported the launch: the authenticated caller and the launcher it
    -- declares itself to be. pid + start_ticks correlate a process instance;
    -- they do not prove who started it (Arya 5817901489), so the trust is
    -- recorded rather than implied.
    launch_reported_by TEXT,
    launcher TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- At most one unresolved attempt per change FAMILY, not per revision: a new
-- revision must not be a way round an attempt nobody has resolved (Arya
-- 5817725747). Schema-backed, so it holds under a race the code did not foresee.
CREATE UNIQUE INDEX IF NOT EXISTS idx_attempts_one_unresolved_per_change
    ON change_attempts(change_id) WHERE state IN ('claimed', 'launched', 'uncertain');
CREATE INDEX IF NOT EXISTS idx_attempts_proposal ON change_attempts(proposal_id);
"""


def protected_writes(data: dict, existing: dict | None = None,
                     existing_status: str | None = None) -> list[str]:
    """What in a generic create/update of a change_proposal only this module
    may write.

    Always: the binding fields, and any status in the execution lifecycle.
    Additionally, once a proposal is EXECUTION-MANAGED (it has a frozen
    candidate or belongs to a change family): `post_validation_state` and ANY
    status. Before that, the legacy selfmod path keeps writing both, so an
    unfrozen proposal behaves exactly as it did (Arya 5818046448: a generic
    write must not overwrite a validated RevA result)."""
    data = data or {}
    hits = sorted(f for f in PROTECTED_FIELDS if f in data)
    if data.get("status") in EXECUTION_STATUSES:
        hits.append("status=" + data["status"])
    managed = bool(existing) and bool(existing.get("candidate_artifact")
                                      or existing.get("change_id"))         or existing_status in EXECUTION_STATUSES
    if managed:
        if "post_validation_state" in data:
            hits.append("post_validation_state (execution-managed proposal)")
        if "status" in data and not data["status"] in EXECUTION_STATUSES:
            hits.append(f"status={data['status']} (execution-managed proposal)")
    return hits


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


# --- plumbing -------------------------------------------------------------------


class _Refusal(Exception):
    """Raised inside the transaction so the rollback takes any partial write
    with it; turned into a Result outside."""

    def __init__(self, code: str, message: str, data: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data or {}


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Refusal(VALIDATION_ERROR, f"{name} must be a non-empty string, got {value!r}")
    return value


def _require_match(name: str, value: Any, pattern: re.Pattern) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise _Refusal(VALIDATION_ERROR, f"{name}={value!r} is not a well-formed {name}")
    return value


def _require_int(name: str, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Refusal(VALIDATION_ERROR, f"{name} must be an integer, got {value!r}")
    return value


def _fingerprint(payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run(conn: Database, operation: str, principal: Any, request_id: Any,
         payload: dict, body) -> Result:
    """One operation: validate ids, BEGIN IMMEDIATE, replay check, body, store.

    The replay check is INSIDE the write lock, so two identical requests racing
    cannot both miss the stored outcome and both write."""
    try:
        _require_text("principal", principal)
        _require_text("request_id", request_id)
        fingerprint = _fingerprint(payload)
        with conn.transaction():
            conn.execute("BEGIN IMMEDIATE")
            stored = conn.fetchone(
                "SELECT principal, payload_fingerprint, response_json FROM approval_requests "
                "WHERE operation = ? AND request_id = ?", (operation, request_id))
            if stored is not None:
                if stored["principal"] != principal or stored["payload_fingerprint"] != fingerprint:
                    raise _Refusal(REPLAY_CONFLICT,
                                   f"request_id {request_id!r} was already used for a different "
                                   f"{operation} request or by a different principal")
                return Result(ok=True, data=json.loads(stored["response_json"]), replayed=True)
            data = body()
            conn.execute(
                "INSERT INTO approval_requests (operation, request_id, principal, "
                "payload_fingerprint, response_json, at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation, request_id, principal, fingerprint,
                 json.dumps(data, sort_keys=True), now_iso()))
            _audit(conn, principal, operation, data.get("proposal_id"), request_id,
                   "committed", True, operation)
            return Result(ok=True, data=data)
    except _Refusal as refusal:
        return Result(ok=False, code=refusal.code, message=refusal.message, data=refusal.data)
    except ApprovalError as err:
        return Result(ok=False, code=err.code, message=str(err), data=err.data)
    except Contended as exc:
        return Result(ok=False, code=CONTENDED,
                      message=f"the write lock was not obtained ({exc}); nothing was written. "
                              f"Maps to DATABASE_UNAVAILABLE: fail closed, no implicit retry")


def _audit(conn: Database, principal: str, action: str, proposal_id: str | None,
           request_id: str, result: str, succeeded: bool, reason: str) -> None:
    conn.execute(
        "INSERT INTO audit_events (audit_id, at, actor, requesting_agent, action, "
        "entity_type, entity_id, request_id, reason, result, succeeded, source) "
        "VALUES (?, ?, ?, ?, ?, 'change_proposal', ?, ?, ?, ?, ?, 'agent_request')",
        ("aud-" + uuid.uuid4().hex, now_iso(), principal, principal, action, proposal_id,
         request_id, reason, result, int(succeeded)))


def _proposal(conn: Database, proposal_id: str) -> tuple[dict, str, str]:
    """(data, status, raw data_json) of a change_proposal, read under the lock."""
    row = conn.fetchone("SELECT status, data_json FROM entities WHERE id = ? AND "
                        "entity_type = 'change_proposal' AND deleted_at IS NULL",
                        (proposal_id,))
    if row is None:
        raise _Refusal(WRONG_STATE, f"no change_proposal {proposal_id!r}")
    return json.loads(row["data_json"]), row["status"], row["data_json"]


def _write_proposal(conn: Database, proposal_id: str, *, expect_status: str,
                    expect_json: str, status: str, data: dict) -> None:
    """Guarded UPDATE: the row must still be exactly what was read. Under
    BEGIN IMMEDIATE this cannot lose, so rowcount 0 means an assumption in this
    module is wrong - refused rather than papered over."""
    n = conn.execute_returning_rowcount(
        "UPDATE entities SET status = ?, data_json = ?, updated_at = ? "
        "WHERE id = ? AND status = ? AND data_json = ?",
        (status, json.dumps(data), now_iso(), proposal_id, expect_status, expect_json))
    if n != 1:
        raise _Refusal(STALE_WRITE, f"guarded update of {proposal_id} matched {n} rows, not 1")


def _unresolved(conn: Database, change_id: str, decision_id: str) -> dict | None:
    return conn.fetchone(
        "SELECT attempt_id, state FROM change_attempts WHERE decision_id = ? "
        "OR (change_id = ? AND state IN ('claimed', 'launched', 'uncertain')) "
        "ORDER BY created_at LIMIT 1", (decision_id, change_id))


# --- §1 freeze -------------------------------------------------------------------


def freeze_candidate(conn: Database, *, principal, request_id, proposal_id,
                     candidate_artifact) -> Result:
    def body():
        _require_text("proposal_id", proposal_id)
        _require_match("candidate_artifact", candidate_artifact, _ARTIFACT)
        data, status, raw = _proposal(conn, proposal_id)
        if status != PLANNING_APPROVED or data.get("candidate_artifact"):
            raise _Refusal(WRONG_STATE,
                           f"freeze needs a planning-approved proposal with no frozen "
                           f"candidate; this one is {status!r}"
                           + (" and already frozen" if data.get("candidate_artifact") else ""))
        new = {**data, "candidate_artifact": candidate_artifact,
               "change_id": data.get("change_id") or proposal_id}
        digest = content_digest(new)
        _write_proposal(conn, proposal_id, expect_status=status, expect_json=raw,
                        status=AWAITING_EXECUTION, data=new)
        return {"proposal_id": proposal_id, "candidate_artifact": candidate_artifact,
                "content_digest": digest}

    return _run(conn, "freeze_candidate", principal, request_id,
                {"proposal_id": proposal_id, "candidate_artifact": candidate_artifact}, body)


# --- §4b.4 revision ----------------------------------------------------------------

_REVISABLE = (PLANNING_APPROVED, AWAITING_EXECUTION, APPROVED_FOR_EXECUTION, DENIED)


def revise_proposal(conn: Database, *, principal, request_id, proposal_id, changes) -> Result:
    """A narrowed or corrected proposal is a NEW revision in the same change
    family. The old one keeps its content and decisions and becomes superseded;
    any attempt it has keeps its state - changing a proposal's status does not
    cancel a process, and must not look as if it did.

    The new revision inherits PLANNING approval only (status `approved`): it
    still needs its own freeze and its own execution approval, so no old
    execution approval can be repurposed."""
    def body():
        _require_text("proposal_id", proposal_id)
        if not isinstance(changes, dict) or not changes:
            raise _Refusal(VALIDATION_ERROR, "changes must be a non-empty dict")
        allowed = set(DIGEST_FIELDS) - {"candidate_artifact", "proposal_version"}
        bad = sorted(set(changes) - allowed)
        if bad:
            raise _Refusal(VALIDATION_ERROR, f"a revision may change only content fields; "
                                             f"refused: {', '.join(bad)}")
        for name, value in changes.items():
            _digest_value(name, value)
        data, status, raw = _proposal(conn, proposal_id)
        if status not in _REVISABLE:
            raise _Refusal(WRONG_STATE, f"a {status!r} proposal cannot be revised")
        new_id = "ent-" + uuid.uuid4().hex
        change_id = data.get("change_id") or proposal_id
        revision = {k: v for k, v in data.items() if k not in PROTECTED_FIELDS}
        revision.update(changes)
        revision.update({"supersedes": proposal_id, "change_id": change_id,
                         "proposal_version": int(data.get("proposal_version") or 1) + 1})
        now = now_iso()
        conn.execute(
            "INSERT INTO entities (id, entity_type, name, status, data_json, "
            "classification, created_at, updated_at) "
            "SELECT ?, entity_type, name, ?, ?, classification, ?, ? FROM entities WHERE id = ?",
            (new_id, PLANNING_APPROVED, json.dumps(revision), now, now, proposal_id))
        _write_proposal(conn, proposal_id, expect_status=status, expect_json=raw,
                        status=SUPERSEDED,
                        data={**data, "change_id": change_id, "superseded_by": new_id})
        return {"proposal_id": new_id, "supersedes": proposal_id, "change_id": change_id}

    return _run(conn, "revise_proposal", principal, request_id,
                {"proposal_id": proposal_id, "changes": changes}, body)


# --- §2 approve_change ----------------------------------------------------------------


def approve_change(conn: Database, *, principal, request_id, proposal_id, confirmed_digest,
                   decision, note="") -> Result:
    def body():
        _require_text("proposal_id", proposal_id)
        _require_match("confirmed_digest", confirmed_digest, _DIGEST)
        if decision not in ("approve", "reject"):
            raise _Refusal(VALIDATION_ERROR, f"decision={decision!r}; approve or reject. A "
                                             f"narrower scope is a new revision, not an answer")
        if not isinstance(note, str):
            raise _Refusal(VALIDATION_ERROR, "note must be a string")
        data, status, raw = _proposal(conn, proposal_id)
        if status != AWAITING_EXECUTION or not data.get("candidate_artifact"):
            raise _Refusal(WRONG_STATE, f"execution approval needs a frozen candidate "
                                        f"awaiting approval; this proposal is {status!r}")
        digest = content_digest(data)
        if digest != confirmed_digest:
            raise _Refusal(DIGEST_MISMATCH, "the proposal changed since it was shown; it needs "
                                            "a fresh confirmation",
                           {"current_digest": digest})
        decision_id = "dec-" + str(uuid.uuid4())
        now = now_iso()
        conn.execute(
            "INSERT INTO entities (id, entity_type, name, status, data_json, "
            "classification, created_at, updated_at) VALUES "
            "(?, 'approval_decision', ?, 'recorded', ?, 'confidential', ?, ?)",
            (decision_id, f"{decision} execution of {proposal_id}"[:200], json.dumps({
                "proposal_id": proposal_id, "decided_by": principal, "decided_at": now,
                "decision": decision, "content_digest": digest,
                "candidate_artifact": data["candidate_artifact"], "note": note,
                "stage": "execution"}), now, now))
        if decision == "approve":
            new = {**data, "approved_digest": digest, "approved_decision_id": decision_id}
            outcome, new_status = "approved", APPROVED_FOR_EXECUTION
        else:
            new = {**data, "rejected_decision_id": decision_id}
            outcome, new_status = "denied", DENIED
        _write_proposal(conn, proposal_id, expect_status=status, expect_json=raw,
                        status=new_status, data=new)
        return {"proposal_id": proposal_id, "outcome": outcome, "decision_id": decision_id,
                "approved_digest": digest if decision == "approve" else None,
                "candidate_artifact": data["candidate_artifact"]}

    return _run(conn, "approve_change", principal, request_id,
                {"proposal_id": proposal_id, "confirmed_digest": confirmed_digest,
                 "decision": decision, "note": note}, body)


# --- §3 claim_attempt -----------------------------------------------------------------


def claim_attempt(conn: Database, *, principal, request_id, proposal_id, decision_id,
                  candidate_artifact, environment_fingerprint=UNVERIFIED) -> Result:
    def body():
        _require_text("proposal_id", proposal_id)
        _require_match("decision_id", decision_id, _DECISION)
        _require_match("candidate_artifact", candidate_artifact, _ARTIFACT)
        _require_text("environment_fingerprint", environment_fingerprint)
        data, status, _ = _proposal(conn, proposal_id)
        if status != APPROVED_FOR_EXECUTION or data.get("approved_decision_id") != decision_id:
            raise _Refusal(WRONG_STATE, f"no execution approval {decision_id} in force on "
                                        f"this proposal (status {status!r})")
        if content_digest(data) != data.get("approved_digest"):
            raise _Refusal(DIGEST_MISMATCH, "the proposal changed after approval; the "
                                            "approval does not cover what it now says")
        if candidate_artifact != data.get("candidate_artifact"):
            raise _Refusal(ARTIFACT_MISMATCH, "the bytes about to run are not the frozen "
                                              "candidate that was approved")
        change_id = data.get("change_id") or proposal_id
        existing = _unresolved(conn, change_id, decision_id)
        if existing:
            raise _Refusal(ATTEMPT_EXISTS, f"attempt {existing['attempt_id']} is "
                                           f"{existing['state']}; it must be resolved first",
                           {"existing_attempt_id": existing["attempt_id"],
                            "existing_state": existing["state"]})
        attempt_id = "att-" + str(uuid.uuid4())
        now = now_iso()
        try:
            conn.execute(
                "INSERT INTO change_attempts (attempt_id, decision_id, proposal_id, change_id, "
                "state, candidate_artifact, environment_at_claim, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'claimed', ?, ?, ?, ?)",
                (attempt_id, decision_id, proposal_id, change_id, candidate_artifact,
                 environment_fingerprint, now, now))
        except sqlite3.IntegrityError as exc:
            raise _Refusal(ATTEMPT_EXISTS, f"the schema refused a second attempt ({exc})")
        return {"proposal_id": proposal_id, "attempt_id": attempt_id, "state": CLAIMED}

    return _run(conn, "claim_attempt", principal, request_id,
                {"proposal_id": proposal_id, "decision_id": decision_id,
                 "candidate_artifact": candidate_artifact,
                 "environment_fingerprint": environment_fingerprint}, body)


# --- §4 finish_attempt ----------------------------------------------------------------


def finish_attempt(conn: Database, *, principal, request_id, attempt_id, to_state,
                   launch_observation=None) -> Result:
    def body():
        _require_match("attempt_id", attempt_id, _ATTEMPT)
        if to_state not in ATTEMPT_STATES:
            raise _Refusal(VALIDATION_ERROR, f"to_state={to_state!r} is not an attempt state")
        if to_state not in LAUNCHER_TRANSITIONS:
            raise _Refusal(WRONG_STATE, f"the launcher does not set {to_state!r}")
        row = conn.fetchone("SELECT * FROM change_attempts WHERE attempt_id = ?", (attempt_id,))
        if row is None:
            raise _Refusal(WRONG_STATE, f"no attempt {attempt_id}")
        if row["state"] not in LAUNCHER_TRANSITIONS[to_state]:
            raise _Refusal(WRONG_STATE, f"{row['state']} -> {to_state} is not a transition")
        sets, params = "state = ?, updated_at = ?", [to_state, now_iso()]
        if to_state == LAUNCHED:
            obs = launch_observation
            if not isinstance(obs, dict):
                raise _Refusal(VALIDATION_ERROR, "a launch must record what was observed: "
                                                 "pid, start_ticks, launched_artifact, launcher")
            pid = _require_int("pid", obs.get("pid"))
            ticks = _require_int("start_ticks", obs.get("start_ticks"))
            launched = _require_match("launched_artifact", obs.get("launched_artifact"),
                                      _ARTIFACT)
            launcher = _require_text("launcher", obs.get("launcher"))
            if launched != row["candidate_artifact"]:
                raise _Refusal(ARTIFACT_MISMATCH, "the launched artifact is not the claimed one")
            sets += (", pid = ?, start_ticks = ?, launched_artifact = ?, "
                     "launch_reported_by = ?, launcher = ?")
            params += [pid, ticks, launched, principal, launcher]
        n = conn.execute_returning_rowcount(
            f"UPDATE change_attempts SET {sets} WHERE attempt_id = ? AND state = ?",
            (*params, attempt_id, row["state"]))
        if n != 1:
            raise _Refusal(STALE_WRITE, f"attempt {attempt_id} moved underneath the update")
        return {"proposal_id": row["proposal_id"], "attempt_id": attempt_id, "state": to_state}

    return _run(conn, "finish_attempt", principal, request_id,
                {"attempt_id": attempt_id, "to_state": to_state,
                 "launch_observation": launch_observation}, body)


# --- §4 / §4b validate_attempt --------------------------------------------------------


def validate_attempt(conn: Database, *, principal, request_id, proposal_id, attempt_id,
                     decision_id, approved_digest, candidate_artifact, runtime_evidence,
                     result) -> Result:
    """ONE compare-and-set over attempt, proposal and decision.

    `candidate_artifact == repo_tree` says the tracked repository is what was
    frozen. It does not say the running process loaded it: that is what the
    launch observation (pid, start_ticks) re-observed at validation adds, and
    even that binds against staleness and mix-ups, not against a launcher that
    lies - the launcher is part of what is being replaced (Deploy 5817735838).
    Environment and untracked inputs are recorded; when either is UNVERIFIED the
    verdict is never an unqualified pass (`runtime_confidence: partial`)."""
    def body():
        _require_text("proposal_id", proposal_id)
        _require_match("attempt_id", attempt_id, _ATTEMPT)
        _require_match("decision_id", decision_id, _DECISION)
        _require_match("approved_digest", approved_digest, _DIGEST)
        _require_match("candidate_artifact", candidate_artifact, _ARTIFACT)
        if result not in RESULTS:
            raise _Refusal(VALIDATION_ERROR, f"result={result!r}; one of {RESULTS}")
        ev = runtime_evidence
        if not isinstance(ev, dict):
            raise _Refusal(VALIDATION_ERROR, "runtime_evidence must be a dict")
        repo_tree = _require_match("repo_tree", ev.get("repo_tree"), _ARTIFACT)
        clean = ev.get("repo_tracked_clean")
        if not isinstance(clean, bool):
            raise _Refusal(VALIDATION_ERROR, "repo_tracked_clean must be a bool")
        env = _require_text("environment_fingerprint", ev.get("environment_fingerprint"))
        untracked = ev.get("untracked_executables")
        if not (untracked == UNVERIFIED or (isinstance(untracked, list)
                                            and all(isinstance(u, str) for u in untracked))):
            raise _Refusal(VALIDATION_ERROR, "untracked_executables: UNVERIFIED or list[str]")

        data, status, raw = _proposal(conn, proposal_id)
        att = conn.fetchone("SELECT * FROM change_attempts WHERE attempt_id = ?", (attempt_id,))
        joined = (att is not None
                  and status == APPROVED_FOR_EXECUTION
                  and att["proposal_id"] == proposal_id
                  and att["decision_id"] == decision_id == data.get("approved_decision_id")
                  and att["state"] == LAUNCHED
                  and content_digest(data) == data.get("approved_digest") == approved_digest
                  and candidate_artifact == data.get("candidate_artifact")
                  == att["candidate_artifact"] == repo_tree)
        if not joined:
            raise _Refusal(STALE_VALIDATION, "the approval, attempt or content no longer "
                                             "matches what is being validated")
        if not clean:
            raise _Refusal(DIRTY_DEPLOYMENT, "tracked content differs from the committed tree")
        prov = ev.get("launch_provenance")
        if not (isinstance(prov, dict) and prov.get("attempt_id") == attempt_id
                and prov.get("pid") == att["pid"] and not isinstance(prov.get("pid"), bool)
                and prov.get("start_ticks") == att["start_ticks"]
                and not isinstance(prov.get("start_ticks"), bool)
                and prov.get("launched_artifact") == att["launched_artifact"]):
            raise _Refusal(UNVERIFIED_RUNTIME, "the running process is not the one this "
                                               "attempt launched, or cannot be shown to be")

        # A match is "observed inputs match", never "verified": the fingerprint
        # covers only what its producer declares (Deploy's env-manifest/1:
        # distribution identities + interpreter), and several runtime inputs are
        # outside ANY of this evidence (Arya 5818279752, 5818337475). The value is
        # opaque here; the producer sends UNVERIFIED for an unnameable_count > 0
        # or an unknown schema, and a schema change compares unequal by design.
        inputs_match = (env != UNVERIFIED and env == att["environment_at_claim"]
                        and untracked == [])
        unmeasured = list(NEVER_MEASURED)
        if env == UNVERIFIED:
            unmeasured.insert(0, "environment")
        if untracked == UNVERIFIED:
            unmeasured.insert(0, "untracked executables")
        new = {**data, "post_validation_state": result}
        _write_proposal(conn, proposal_id, expect_status=status, expect_json=raw,
                        status=result, data=new)
        n = conn.execute_returning_rowcount(
            "UPDATE change_attempts SET state = 'completed', updated_at = ? "
            "WHERE attempt_id = ? AND state = 'launched'", (now_iso(), attempt_id))
        if n != 1:
            raise _Refusal(STALE_WRITE, f"attempt {attempt_id} moved underneath the update")
        return {"proposal_id": proposal_id, "attempt_id": attempt_id,
                "artifact_verdict": result,
                "runtime_confidence": "observed_inputs_match" if inputs_match else "partial",
                "unmeasured": unmeasured,
                "launch_source": {"reported_by": att["launch_reported_by"],
                                  "launcher": att["launcher"],
                                  "assurance_basis": "correlation, not proof of origin"},
                "environment_matches_claim": (env == att["environment_at_claim"]
                                              if env != UNVERIFIED else None)}

    outcome = _run(conn, "validate_attempt", principal, request_id,
                   {"proposal_id": proposal_id, "attempt_id": attempt_id,
                    "decision_id": decision_id, "approved_digest": approved_digest,
                    "candidate_artifact": candidate_artifact,
                    "runtime_evidence": runtime_evidence, "result": result}, body)
    if not outcome.ok and outcome.code in BLOCKED_CODES:
        _diagnose(conn, principal, request_id, proposal_id, outcome)
        return Result(ok=False, code=outcome.code, message=outcome.message,
                      data={**outcome.data, "verdict": "BLOCKED"})
    return outcome


def _diagnose(conn: Database, principal, request_id, proposal_id, outcome: Result) -> None:
    """The single diagnostic row for a BLOCKED validation, written AFTER the
    rejected transition rolled back and once per request_id: a replay of the
    same stale request is the same event, not a second one."""
    label = {STALE_VALIDATION: "stale", DIRTY_DEPLOYMENT: "dirty",
             UNVERIFIED_RUNTIME: "unverified_runtime"}[outcome.code]
    try:
        with conn.transaction():
            conn.execute("BEGIN IMMEDIATE")
            seen = conn.fetchone("SELECT 1 AS x FROM audit_events WHERE request_id = ? AND "
                                 "action = 'validate_attempt' AND reason LIKE ?",
                                 (request_id, label + ":%"))
            if seen is None:
                _audit(conn, principal, "validate_attempt", proposal_id, request_id,
                       "refused", False, f"{label}: {outcome.message}"[:500])
    except Contended:
        pass    # the refusal stands without its diagnostic; nothing changed either way


# --- the transport: POST /approval/{operation} (Arya 5818448805) --------------------

PERMISSION_DENIED = "PERMISSION_DENIED"
UNKNOWN_OPERATION = "UNKNOWN_OPERATION"


def _roles() -> dict[str, frozenset[str]]:
    """Who may call which operation. Least privilege, one line per operation.

    Execution approval is Krish's console ONLY: Jarvis must not be able to
    approve a change to itself. The launcher holds exactly the two attempt
    operations and nothing in the generic policy. Imported lazily because
    permissions imports nothing from here and must stay that way."""
    from dba import permissions as p
    return {
        "approve_change": frozenset({p.OPERATOR_CONSOLE}),
        "freeze_candidate": frozenset({p.JARVIS, p.OPERATOR_CONSOLE}),
        "revise_proposal": frozenset({p.JARVIS, p.OPERATOR_CONSOLE}),
        "claim_attempt": frozenset({p.LAUNCHER}),
        "finish_attempt": frozenset({p.LAUNCHER}),
        "validate_attempt": frozenset({p.JARVIS}),
    }


# The fixed allowlist: operation -> (function, required fields, optional fields).
# A literal table, not reflection, so nothing outside it is reachable by name.
OPERATIONS = {
    "freeze_candidate": (freeze_candidate, ("request_id", "proposal_id", "candidate_artifact"), ()),
    "revise_proposal": (revise_proposal, ("request_id", "proposal_id", "changes"), ()),
    "approve_change": (approve_change, ("request_id", "proposal_id", "confirmed_digest",
                                        "decision"), ("note",)),
    "claim_attempt": (claim_attempt, ("request_id", "proposal_id", "decision_id",
                                      "candidate_artifact"), ("environment_fingerprint",)),
    "finish_attempt": (finish_attempt, ("request_id", "attempt_id", "to_state"),
                       ("launch_observation",)),
    "validate_attempt": (validate_attempt, ("request_id", "proposal_id", "attempt_id",
                                            "decision_id", "approved_digest",
                                            "candidate_artifact", "runtime_evidence",
                                            "result"), ()),
}

# A body that names an identity is refused, not ignored: silently dropping it
# would hide an attempt to speak as someone else.
IDENTITY_FIELDS = ("principal", "requested_by", "actor", "decided_by")

_HTTP_STATUS = {PERMISSION_DENIED: 403, UNKNOWN_OPERATION: 404, VALIDATION_ERROR: 400,
                CONTENDED: 503}


def http_call(operation: str, principal: str, payload: Any, connect=None) -> tuple[int, dict]:
    """One authenticated call. `principal` comes from the route's
    authentication and nowhere else. Returns (status, body) for every outcome
    the operations know: success, refusal, contention.

    It does NOT promise never to raise (Arya 5818622167 caught the earlier
    docstring saying so). An unexpected fault in schema set-up or an operation
    propagates and the service answers HTTP 500 - an outcome of UNKNOWN effect,
    which the client reports as Unavailable, never as a structured refusal.
    Each operation's own transaction means such a fault rolled its writes back."""
    def answer(result: Result) -> tuple[int, dict]:
        body = {"ok": result.ok, "code": result.code, "message": result.message,
                "data": result.data, "replayed": result.replayed}
        return (200 if result.ok else _HTTP_STATUS.get(result.code, 409)), body

    if operation not in OPERATIONS:
        return answer(Result(ok=False, code=UNKNOWN_OPERATION,
                             message=f"{operation!r} is not an approval operation"))
    if principal not in _roles()[operation]:
        return answer(Result(ok=False, code=PERMISSION_DENIED,
                             message=f"{principal} may not call {operation}"))
    if not isinstance(payload, dict):
        return answer(Result(ok=False, code=VALIDATION_ERROR, message="body must be an object"))
    spoofed = sorted(set(payload) & set(IDENTITY_FIELDS))
    if spoofed:
        return answer(Result(ok=False, code=VALIDATION_ERROR,
                             message=f"identity comes from authentication; the body may not "
                                     f"set {', '.join(spoofed)}"))
    function, required, optional = OPERATIONS[operation]
    missing = [f for f in required if f not in payload]
    extra = sorted(set(payload) - set(required) - set(optional))
    if missing or extra:
        return answer(Result(ok=False, code=VALIDATION_ERROR,
                             message=f"missing {missing or 'nothing'}; unexpected "
                                     f"{extra or 'nothing'}"))
    from dba import store
    try:
        conn = (connect or store.connect)()
    except (sqlite3.Error, OSError) as bad:
        return answer(Result(ok=False, code=CONTENDED,
                             message=f"the database could not be opened: {bad}"))
    try:
        try:
            store.init_schema(conn)
            init_schema(conn)
        except Contended as exc:
            return answer(Result(ok=False, code=CONTENDED,
                                 message=f"schema set-up could not take the lock ({exc})"))
        return answer(function(conn, principal=principal, **payload))
    finally:
        conn.close()