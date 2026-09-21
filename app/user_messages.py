"""What Jarvis says when the machinery underneath him fails (Task 01 §4.2).

## The fault this exists to close

Krish saw Jarvis answer him with, in effect, *"I don't have any more tokens."*
That sentence is `app/model_budget.py`'s:

    Daily model token budget exhausted: 512334 tokens recorded today
    (limit 500000). Raise MODEL_BUDGET_DAILY_TOKENS deliberately if this
    spend is intended.

It reached him because four handlers put `str(exc)` on the wire - two in the
Gateway and the backend chat, two in the COO console (`docs/CALL_SITES.md` §6).
None of them was wrong to report the failure. They were wrong about *whose
sentence* to report: an operator's accounting message became an assistant's
answer.

The fix is not four edited f-strings. It is this module, which is the only
vocabulary those handlers are allowed to speak in, plus
`tests/test_user_facing_language.py`, which fails if any of them stops using it.

## The rule

**An internal plumbing state is never an answer.** The user is told what it
means for them - whether to wait, whether to rephrase, whether it is gone - in
the assistant's own terms. The operator's sentence still exists, at WARN, in a
log, in the brief. It is not deleted; it is addressed to the person whose
problem it is.

## Why the classification is by exception and not by message text

Matching on words would make the guarantee depend on nobody ever rewording an
error, which is exactly the kind of promise this codebase ends up breaking.
`classify()` looks at the exception's type and at an attribute the raiser sets,
so a new failure mode has to *choose* a category and defaults to the cautious
one.
"""

from __future__ import annotations

# Words that must never appear in anything a user reads. §7's acceptance
# criterion, as data, so the test and the code share one list.
#
# "budget" is here even though it is the honest word for the ledger: to Krish,
# reading it in a reply from his own assistant, it says the same thing "tokens"
# said.
FORBIDDEN_WORDS = (
    "token", "tokens", "quota", "rate limit", "rate-limit", "ratelimit",
    "api credit", "api credits", "credits", "billing", "budget",
    "insufficient balance", "429", "402",
)

# --- the categories -----------------------------------------------------------

CATEGORY_CAPACITY = "capacity"
CATEGORY_UNAVAILABLE = "unavailable"
CATEGORY_FAILED = "failed"
CATEGORIES = (CATEGORY_CAPACITY, CATEGORY_UNAVAILABLE, CATEGORY_FAILED)

# An exception names its own category through this attribute. `classify` falls
# back to the cautious reading for anything that does not.
CATEGORY_ATTRIBUTE = "user_message_category"

# §4.2.3's wording, kept verbatim because Krish wrote it: "I can't do that
# reliably right now - I'll retry shortly".
MESSAGES = {
    CATEGORY_CAPACITY: (
        "I can't do that reliably right now - I'll retry shortly."),
    CATEGORY_UNAVAILABLE: (
        "I can't reach my own reasoning at the moment, so I'd rather not answer "
        "than answer badly. I'll pick this up as soon as I can."),
    CATEGORY_FAILED: (
        "Something went wrong while I was working on that, and I'd rather tell "
        "you than hand you a half-answer. It's on my list and I'll come back "
        "to you."),
}

# What each category means for the request, for the caller that has to decide
# whether to queue a retry.
RETRYABLE = (CATEGORY_CAPACITY, CATEGORY_UNAVAILABLE)


def classify(exc: BaseException) -> str:
    """Which of the three things happened, from the exception's own account.

    Deferred imports, and a `try` around them, because this module is reached
    from exception handlers in two services and must not itself fail on an
    import - a failure in the failure path is how a user ends up seeing a
    traceback instead of a sentence."""
    declared = getattr(exc, CATEGORY_ATTRIBUTE, None)
    if declared in CATEGORIES:
        return declared

    try:
        from app.model_budget import BudgetExceededError

        if isinstance(exc, BudgetExceededError):
            return CATEGORY_CAPACITY
    except Exception:  # pragma: no cover - defensive, see the docstring
        pass

    try:
        from app.model_routing import ModelRoutingFailure

        if isinstance(exc, ModelRoutingFailure):
            return CATEGORY_UNAVAILABLE
    except Exception:  # pragma: no cover
        pass

    return CATEGORY_FAILED


def for_user(exc: BaseException) -> str:
    """The sentence the user sees. Never derived from the exception's text."""
    return MESSAGES[classify(exc)]


def should_retry(exc: BaseException) -> bool:
    """Whether this is worth queueing for another attempt (§4.2.3)."""
    return classify(exc) in RETRYABLE


def for_operator(exc: BaseException) -> str:
    """The sentence that goes in the log and the brief, where the accounting
    belongs. Krish still gets the number; he gets it as the operator."""
    return f"{type(exc).__name__}: {exc}"


def is_clean(text: str) -> bool:
    """Whether a string is safe to show a user, by §7's criterion.

    Word-boundary-ish rather than substring: "budget" must fail, and so must
    "tokens", but a sentence containing the word "credit" in its ordinary sense
    should not - so the list holds "api credit" and "credits" rather than
    "credit"."""
    lowered = (text or "").lower()
    return not any(word in lowered for word in FORBIDDEN_WORDS)


def sanitise(text: str, exc: BaseException | None = None) -> str:
    """A last line of defence for a string assembled somewhere else.

    Returns the text when it is clean, and the category's message when it is
    not. Deliberately not the only defence - a handler that calls `for_user`
    never needs this - but the Gateway forwards text from a tool loop that
    other code writes, and one guard at the door costs nothing.

    A string is *replaced* rather than redacted. Blanking the offending word
    would leave "I don't have any more ." on Krish's screen, which tells him
    something went wrong and nothing about what to do."""
    if is_clean(text):
        return text
    if exc is not None:
        return for_user(exc)
    return MESSAGES[CATEGORY_FAILED]
