"""§34's failure states, in one place, with what each one obliges.

    *"Failures must be visible and not silently swallowed."*

A list of strings would have satisfied the letter of §34 and nothing else. What
makes this worth a module is the second column: for each state, whether Jarvis
may go on operating, whether he must tell Krish, and what the next honest
action is. Those are the things a caller actually needs at the moment a failure
happens, and deriving them at each call site is how two call sites come to
disagree about whether a broken ledger is fatal.

Nothing here raises or handles anything. It is a declaration, read by
`gateway/rehydrate.py`, `gateway/selfmod.py` and the conversation surface.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- restore and persistence --------------------------------------------------

RESTORE_FAILED = "RESTORE_FAILED"
PARTIAL_RESTORE = "PARTIAL_RESTORE"
CHECKPOINT_INVALID = "CHECKPOINT_INVALID"
DBA_UNAVAILABLE = "DBA_UNAVAILABLE"
LEDGER_WRITE_FAILED = "LEDGER_WRITE_FAILED"

# --- capability gaps and approval ---------------------------------------------

GAP_UNCONFIRMED = "GAP_UNCONFIRMED"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
APPROVAL_DENIED = "APPROVAL_DENIED"

# --- self-modification --------------------------------------------------------

CHANGE_TEST_FAILED = "CHANGE_TEST_FAILED"
BUILD_FAILED = "BUILD_FAILED"
RELAUNCH_FAILED = "RELAUNCH_FAILED"
POST_VALIDATION_FAILED = "POST_VALIDATION_FAILED"
ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
ROLLBACK_COMPLETED = "ROLLBACK_COMPLETED"


@dataclass(frozen=True)
class State:
    """One failure state and what it obliges.

    `may_continue` is about *operating*, not about pretending. Jarvis may keep
    answering questions with an unavailable DBA; what he may not do is answer
    them as though he remembered anything."""

    name: str
    means: str
    may_continue: bool
    must_tell_user: bool
    next_action: str


STATES: dict[str, State] = {
    RESTORE_FAILED: State(
        RESTORE_FAILED,
        "nothing could be restored; this runtime knows only what it was told "
        "in this session",
        may_continue=True, must_tell_user=True,
        next_action="say so before answering anything from memory, and do not "
                    "take a checkpoint over the top of the state that failed "
                    "to load"),
    PARTIAL_RESTORE: State(
        PARTIAL_RESTORE,
        "some of the persistent state came back and some did not",
        may_continue=True, must_tell_user=True,
        next_action="name what is missing when it is relevant, rather than "
                    "once at the start and never again"),
    CHECKPOINT_INVALID: State(
        CHECKPOINT_INVALID,
        "the newest checkpoint did not verify and was rejected",
        may_continue=True, must_tell_user=True,
        next_action="fall back to the most recent valid checkpoint and report "
                    "the rollback, including which checkpoint was skipped"),
    DBA_UNAVAILABLE: State(
        DBA_UNAVAILABLE,
        "the DBA Agent could not be reached, so there is no persistent memory "
        "and no way to write one",
        may_continue=True, must_tell_user=True,
        next_action="operate without memory and say so; retry on the next "
                    "request rather than caching a failure"),
    LEDGER_WRITE_FAILED: State(
        LEDGER_WRITE_FAILED,
        "an event that mattered was not recorded",
        may_continue=True, must_tell_user=True,
        next_action="tell the user the event was not durably recorded, so they "
                    "can repeat it; never report it as remembered"),
    GAP_UNCONFIRMED: State(
        GAP_UNCONFIRMED,
        "a suspected capability gap has not been confirmed by evidence",
        may_continue=True, must_tell_user=False,
        next_action="investigate; do not propose a change for it yet"),
    APPROVAL_REQUIRED: State(
        APPROVAL_REQUIRED,
        "a confirmed gap needs a decision before anything is changed",
        may_continue=True, must_tell_user=True,
        next_action="present the proposal and stop"),
    APPROVAL_DENIED: State(
        APPROVAL_DENIED,
        "the user declined the proposed change",
        may_continue=True, must_tell_user=False,
        next_action="record the denial and make no modification; do not "
                    "re-propose the same change without new evidence"),
    CHANGE_TEST_FAILED: State(
        CHANGE_TEST_FAILED,
        "the candidate change did not pass its tests",
        may_continue=True, must_tell_user=True,
        next_action="do not commit it; report which tests failed"),
    BUILD_FAILED: State(
        BUILD_FAILED,
        "the build/relaunch controller could not build the approved change",
        may_continue=True, must_tell_user=True,
        next_action="stay on the current build and report the failure"),
    RELAUNCH_FAILED: State(
        RELAUNCH_FAILED,
        "the new runtime did not come up",
        may_continue=False, must_tell_user=True,
        next_action="the supervisor restores the previous build; this runtime "
                    "is not the one to decide that"),
    POST_VALIDATION_FAILED: State(
        POST_VALIDATION_FAILED,
        "the relaunched runtime came up but failed its post-change checks",
        may_continue=True, must_tell_user=True,
        next_action="mark the change degraded or failed and request rollback"),
    ROLLBACK_REQUIRED: State(
        ROLLBACK_REQUIRED,
        "the previous known-good code and state need to be put back",
        may_continue=True, must_tell_user=True,
        next_action="request it from the controller; Jarvis does not relaunch "
                    "himself (§19)"),
    ROLLBACK_COMPLETED: State(
        ROLLBACK_COMPLETED,
        "the previous known-good build is running again",
        may_continue=True, must_tell_user=True,
        next_action="record what failed, which version failed, and whether any "
                    "learning after the checkpoint needs reconciling"),
}


def get(name: str) -> State:
    if name not in STATES:
        raise KeyError(
            f"{name!r} is not a declared failure state. Declared: "
            f"{', '.join(sorted(STATES))}. Adding one is an edit here, so that "
            f"its obligations are declared with it rather than invented at the "
            f"call site.")
    return STATES[name]


def must_tell_user(name: str) -> bool:
    return get(name).must_tell_user


def sentence(name: str, detail: str = "") -> str:
    """One line Jarvis can say. The failure, then what he will do about it."""
    state = get(name)
    body = f"{state.means}{f' ({detail})' if detail else ''}"
    return f"{body}. {state.next_action[0].upper()}{state.next_action[1:]}."


def describe() -> dict:
    return {name: {"means": state.means,
                   "may_continue": state.may_continue,
                   "must_tell_user": state.must_tell_user,
                   "next_action": state.next_action}
            for name, state in sorted(STATES.items())}
