"""The request and response contract (§8, §23, §42, §4.2).

§42's closing line is the rule: *"Avoid free-form prose as the only
machine-to-machine response."* So both directions are dataclasses with a fixed
vocabulary, and the plain-language sentence §43 asks for is generated **from**
the structured result rather than being the result.

## Why `changed` is not a field anybody sets

§44 says the DBA must never report success unless the persistent change
actually succeeded. A boolean that any code path can assign is a boolean that
some path will eventually assign optimistically - before the commit, inside the
branch that was going to work. So `Response.changed` is only ever produced by
`success()`, which takes it from what the operation observed the database do,
and the dataclass is frozen so nothing can revise it afterwards.

## Why `clarification_required` is a status and not an error

§23 lists it among the error codes and §4.2 shows it as a status. It is the
status. A question is not a failure - the request was well-formed, the DBA
understood it, and the honest answer is that it needs one more fact. Reporting
it as an error would put it in the same bucket as `internal_error` in every
caller's error handling, which is the bucket you retry or give up on rather
than the one you answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# --- actions (§8) -------------------------------------------------------------

CREATE = "create"
GET = "get"
FIND = "find"
SEARCH = "search"
UPDATE = "update"
ARCHIVE = "archive"
DELETE_AUTHORIZED = "delete_authorized"
LINK = "link"
UNLINK = "unlink"
LIST = "list"
COUNT = "count"
HISTORY = "history"
VALIDATE = "validate"
RECONCILE = "reconcile"
BEGIN_TRANSACTION = "begin_transaction"
COMMIT_TRANSACTION = "commit_transaction"
ROLLBACK_TRANSACTION = "rollback_transaction"

ACTIONS = (
    CREATE, GET, FIND, SEARCH, UPDATE, ARCHIVE, DELETE_AUTHORIZED,
    LINK, UNLINK, LIST, COUNT, HISTORY, VALIDATE, RECONCILE,
    BEGIN_TRANSACTION, COMMIT_TRANSACTION, ROLLBACK_TRANSACTION,
)

# Actions that can change persistent state. The split matters in three places -
# permissions, idempotency and the audit trail - and deriving it from a single
# tuple means a new write action cannot be added as a read by omission.
WRITING_ACTIONS = (CREATE, UPDATE, ARCHIVE, DELETE_AUTHORIZED, LINK, UNLINK,
                   RECONCILE)

# --- statuses (§42) -----------------------------------------------------------

STATUS_SUCCESS = "success"
STATUS_CLARIFICATION_REQUIRED = "clarification_required"
STATUS_ERROR = "error"
STATUSES = (STATUS_SUCCESS, STATUS_CLARIFICATION_REQUIRED, STATUS_ERROR)

# --- error codes (§23) --------------------------------------------------------

VALIDATION_ERROR = "validation_error"
PERMISSION_DENIED = "permission_denied"
NOT_FOUND = "not_found"
DUPLICATE_DETECTED = "duplicate_detected"
CONFLICT_DETECTED = "conflict_detected"
TRANSACTION_FAILED = "transaction_failed"
DATABASE_UNAVAILABLE = "database_unavailable"
TIMEOUT = "timeout"
SCHEMA_MISMATCH = "schema_mismatch"
INTERNAL_ERROR = "internal_error"
UNKNOWN_ACTION = "unknown_action"

ERROR_CODES = (
    VALIDATION_ERROR, PERMISSION_DENIED, NOT_FOUND, DUPLICATE_DETECTED,
    CONFLICT_DETECTED, TRANSACTION_FAILED, DATABASE_UNAVAILABLE, TIMEOUT,
    SCHEMA_MISMATCH, INTERNAL_ERROR, UNKNOWN_ACTION,
)

# Which failures a caller may safely try again, stated here rather than decided
# per call site (§23's `retryable`, §24's "identify whether retry is safe").
#
# `duplicate_detected` and `conflict_detected` are deliberately absent: retrying
# them unchanged produces the same answer, and the fix is a different request
# rather than the same one later. `transaction_failed` is absent for a sharper
# reason - the DBA knows the transaction rolled back, but a caller that retries
# a multi-step write without re-reading state is the shape §44 exists against.
RETRYABLE_CODES = (DATABASE_UNAVAILABLE, TIMEOUT)

# --- ask-back reasons (§4.2) --------------------------------------------------

MULTIPLE_MATCHING_RECORDS = "multiple_matching_records"
MISSING_REQUIRED_INFORMATION = "missing_required_information"
CONTRADICTORY_REQUEST = "contradictory_request"
DESTRUCTIVE_SCOPE_UNCLEAR = "destructive_scope_unclear"
UNCERTAIN_RELATIONSHIP = "uncertain_relationship"
POSSIBLE_DUPLICATE = "possible_duplicate"
UNRESOLVED_CONFLICT = "unresolved_conflict"

CLARIFICATION_REASONS = (
    MULTIPLE_MATCHING_RECORDS, MISSING_REQUIRED_INFORMATION,
    CONTRADICTORY_REQUEST, DESTRUCTIVE_SCOPE_UNCLEAR, UNCERTAIN_RELATIONSHIP,
    POSSIBLE_DUPLICATE, UNRESOLVED_CONFLICT,
)


def _check(value: str, allowed: tuple, what: str) -> str:
    """Fail closed on an unknown member of a closed vocabulary.

    Raising rather than passing it through, for the reason `gateway/roles.py`
    already gives about unknown capabilities: the value can only come from this
    package's own code, so raising surfaces a typo in the test suite instead of
    writing an unreadable row that a report later groups under its own name."""
    if value not in allowed:
        raise ValueError(f"{what}={value!r} is not one of {allowed}")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Request:
    """One structured request (§8).

    `requested_by` and `actor` are both required to be *stated*, because §14
    says each request should identify who is asking and which agent is asking,
    and they are different questions: Jarvis acting on Krish's instruction is
    not the same actor as Jarvis acting on its own initiative, and an audit
    trail that cannot tell them apart cannot answer the only question anybody
    asks of it afterwards."""

    action: str
    requested_by: str
    actor: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    criteria: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    dry_run: bool = False
    reason: str | None = None
    # When this request answers an earlier `clarification_required`, the id of
    # the pending request it resolves (§4.1's "preserve the pending request").
    answers: str | None = None
    # Explicit confirmation for an operation the DBA refused to infer, such as
    # the scope of a destructive action (§4, example D).
    confirmed: bool = False

    def __post_init__(self) -> None:
        _check(self.action, ACTIONS, "action")
        if not (self.requested_by or "").strip():
            raise ValueError(
                "requested_by is required: §14 asks which agent is asking, and "
                "an unattributed write is one the audit trail cannot explain.")

    @property
    def writes(self) -> bool:
        return self.action in WRITING_ACTIONS

    def to_dict(self) -> dict:
        return {
            "action": self.action, "requested_by": self.requested_by,
            "actor": self.actor, "entity_type": self.entity_type,
            "entity_id": self.entity_id, "data": dict(self.data),
            "criteria": dict(self.criteria), "request_id": self.request_id,
            "dry_run": self.dry_run, "reason": self.reason,
            "answers": self.answers, "confirmed": self.confirmed,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Request":
        """Build one from a decoded JSON body, ignoring nothing silently.

        An unexpected key raises rather than being dropped, because the caller
        that sent `filter=` when the contract says `criteria=` would otherwise
        get a successful unfiltered operation - which for `archive` is the
        difference between archiving one record and archiving all of them."""
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(payload) - known)
        if unknown:
            raise ValueError(
                f"unknown request field(s): {', '.join(unknown)}. The contract "
                f"is {sorted(known)}. Refusing rather than ignoring them - a "
                f"dropped filter is an unfiltered write.")
        return cls(**payload)


@dataclass(frozen=True)
class Response:
    """One structured response (§42). Build it with the three constructors
    below rather than directly, so that no path can assemble a success that
    claims a change the database did not make."""

    status: str
    action: str
    request_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    changed: bool = False
    result: Any = None
    warnings: tuple[str, ...] = ()
    clarification: dict | None = None
    error: dict | None = None
    timestamp: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _check(self.status, STATUSES, "status")

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SUCCESS

    @property
    def needs_answer(self) -> bool:
        return self.status == STATUS_CLARIFICATION_REQUIRED

    def to_dict(self) -> dict:
        return {
            "status": self.status, "request_id": self.request_id,
            "action": self.action, "entity_type": self.entity_type,
            "entity_id": self.entity_id, "changed": self.changed,
            "result": self.result, "warnings": list(self.warnings),
            "clarification": self.clarification, "error": self.error,
            "timestamp": self.timestamp,
        }


def success(request: Request, *, changed: bool, result: Any = None,
            entity_id: str | None = None,
            warnings: tuple[str, ...] = ()) -> Response:
    """A success, with `changed` reporting what the database actually did.

    `changed` is a required keyword rather than defaulting to anything: §44 is
    the rule this package is most likely to break by accident, and a default
    would let a new operation inherit an answer it never computed."""
    return Response(
        status=STATUS_SUCCESS, action=request.action,
        request_id=request.request_id, entity_type=request.entity_type,
        entity_id=entity_id or request.entity_id, changed=changed,
        result=result, warnings=warnings)


def clarify(request: Request, *, reason: str, question: str,
            options: list | None = None,
            pending_action: str | None = None) -> Response:
    """A question back (§4.2), and never a partial write.

    Nothing is committed on this path. That is not enforced by convention: the
    operations that can ask build their clarification *before* opening a
    transaction, and `tests/test_dba.py` asserts the row count is unchanged
    after every clarification the suite can provoke."""
    _check(reason, CLARIFICATION_REASONS, "reason")
    return Response(
        status=STATUS_CLARIFICATION_REQUIRED, action=request.action,
        request_id=request.request_id, entity_type=request.entity_type,
        entity_id=request.entity_id, changed=False,
        clarification={
            "reason": reason,
            "question": question,
            "options": options or [],
            "pending_action": pending_action or _describe(request),
        })


def failure(request: Request, *, code: str, message: str,
            details: dict | None = None) -> Response:
    """A structured error (§23). `retryable` is derived from the code rather
    than passed in, so two call sites cannot disagree about whether the same
    failure is safe to try again."""
    _check(code, ERROR_CODES, "error_code")
    return Response(
        status=STATUS_ERROR, action=request.action,
        request_id=request.request_id, entity_type=request.entity_type,
        entity_id=request.entity_id, changed=False,
        error={
            "error_code": code,
            "message": message,
            "retryable": code in RETRYABLE_CODES,
            "details": details or {},
        })


def _describe(request: Request) -> str:
    """The pending action, in the plain words §4.2's example uses."""
    what = request.entity_type or "record"
    if request.action == UPDATE:
        fields = ", ".join(sorted(request.data)) or "fields"
        return f"Update {fields} on {what}"
    if request.action == CREATE:
        return f"Create {what}"
    if request.action in (ARCHIVE, DELETE_AUTHORIZED):
        return f"{request.action.split('_')[0].capitalize()} {what}"
    if request.action in (LINK, UNLINK):
        return f"{request.action.capitalize()} {what}"
    return f"{request.action} {what}"
