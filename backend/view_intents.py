"""Natural language as a control surface, not a second reporting system
(addendum 40 §10, §11; TASK_QUEUE TQ-32, docs/SPEC_RECONCILIATION.md §84).

§10 states the requirement and the principle in one line: the COO "interprets
the request, queries the same underlying organizational data, changes the
visual focus, and answers conversationally... Natural language is not a
separate reporting system. It is another control surface over the same source
of truth."

The answering half exists (`backend/coo_chat.py`, §77). This is the *control*
half: "show that tab", "go back", "open the agent conversation", "just show me
errors".

## Deterministic first, model second

§11's own examples are the kind a model should never be asked to handle:
"show that tab" has one meaning, needs no reasoning, and should not cost a
token or a second of latency. So this layer matches them directly and returns
a directive; anything it does not recognise falls through to the model
untouched.

That ordering is not only about cost. A deterministic matcher is *testable* —
every phrase this accepts is pinned by a test, and the set of things that can
move the operator's screen is a list somebody can read.

## Certainty is the bar, because this moves the screen

An ambiguous phrase falls through rather than guessing. Yanking the display to
the wrong desk mid-sentence is worse than answering in prose, and a control
surface that acts on a maybe teaches an operator to distrust it. `interpret`
returns None whenever it is not sure, and None is the safe direction.

## What this deliberately cannot do

No writes, no lifecycle, no spending. §11 lists "issue tasks in outcome
language" and §12's intent-based work model; both need an authorization story
that does not exist yet (§81 records the deferral). Every directive here
changes what the operator is *looking at* and nothing else, which is why it
needs no confirmation step.
"""

from __future__ import annotations

import re

# The desks, named once. The console renders these; the COO steers by them.
# Aliases are what an operator would actually say - "conversations" and
# "collaboration" both mean Chatterbox, and refusing them because the tab is
# spelled differently would be the interface insisting on its own vocabulary.
VIEWS: dict[str, tuple[str, ...]] = {
    "newsroom": ("newsroom", "news", "feed", "front page", "narration", "log", "events"),
    "finance": ("finance", "market", "markets", "prices", "tickers", "movers", "financial"),
    "chatterbox": ("chatterbox", "conversations", "agent conversations", "collaboration",
                   "who is talking", "chatter", "threads"),
    "organization": ("organization", "organisation", "agents", "org", "roster", "staff",
                     "who is running", "workforce"),
    "strategy": ("strategy", "register", "priorities", "strategic register", "proposals"),
    "simulation": ("simulation", "missions", "mission", "training worlds", "sim"),
    "alerts": ("alerts", "errors", "warnings", "problems", "exceptions", "attention",
               "what needs attention", "failures"),
    "parliament": ("parliament", "governance", "sessions", "voting"),
}

# Verbs that mean "put this in front of me". Deliberately narrow: an operator
# asking "what is the finance desk showing?" wants an answer, not a jump, and
# the model handles that better than a keyword ever will.
_SHOW = r"(?:show|open|go to|switch to|take me to|bring up|display|jump to|pull up|let'?s see)"

ACTION_SHOW_VIEW = "show_view"
ACTION_BACK = "back"
ACTION_FILTER_ATTENTION = "filter_attention"
ACTION_CLEAR_FILTERS = "clear_filters"
ACTION_FOLLOW = "follow"
ACTION_PAUSE = "pause"


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9\s']", " ", (text or "").lower()).strip()


def _match_view(text: str) -> str | None:
    """The view an operator named, or None if they named none or several.

    Longest alias first, so "agent conversations" is not shadowed by
    "agents". Several matches means ambiguity, and ambiguity falls through -
    see the module docstring on why certainty is the bar."""
    hits = []
    for view, aliases in VIEWS.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", text):
                hits.append(view)
                break
    unique = set(hits)
    return hits[0] if len(unique) == 1 else None


def interpret(text: str) -> dict | None:
    """Turn an operator's phrase into a view directive, or None.

    None means "this is not a view command I am sure about" - the caller
    should let the model answer it. Never a guess."""
    normalised = _normalise(text)
    if not normalised:
        return None

    # "go back" / "previous view"
    if re.search(r"\b(go back|back to (the )?(previous|last)|previous (view|tab|desk))\b", normalised):
        return {"action": ACTION_BACK, "say": "Going back."}

    # Feed following, which is the one live control that is not a view.
    if re.search(rf"\b(pause|stop|freeze|hold)\b.*\b(feed|scroll|newsroom|following)\b", normalised):
        return {"action": ACTION_PAUSE, "say": "Paused the feed."}
    if re.search(rf"\b(resume|follow|unpause|keep up|continue)\b.*\b(feed|scroll|newsroom|following)\b",
                 normalised):
        return {"action": ACTION_FOLLOW, "say": "Following the feed again."}

    # Attention filter: "just show me errors", "only warnings", "clear the filter"
    if re.search(r"\b(clear|reset|remove|drop)\b.*\bfilters?\b", normalised):
        return {"action": ACTION_CLEAR_FILTERS, "say": "Filters cleared."}
    if re.search(r"\b(only|just|filter to|filter for)\b.*\b(errors?|warnings?|problems?|failures?)\b",
                 normalised):
        return {"action": ACTION_FILTER_ATTENTION,
                "say": "Showing only what needs attention."}

    # "show me the chatterbox" - a naming verb plus exactly one view.
    if re.search(rf"\b{_SHOW}\b", normalised):
        view = _match_view(normalised)
        if view:
            return {"action": ACTION_SHOW_VIEW, "view": view,
                    "say": f"Opening {view.replace('_', ' ')}."}

    # A bare view name on its own is a command too: an operator who says
    # "chatterbox" while looking at the console means show it. Bounded to
    # short utterances so a sentence *about* a desk is not hijacked.
    if len(normalised.split()) <= 3:
        view = _match_view(normalised)
        if view:
            return {"action": ACTION_SHOW_VIEW, "view": view,
                    "say": f"Opening {view.replace('_', ' ')}."}

    return None


def followed_by_view(text: str) -> str | None:
    """The view a *question* is plainly about, for focusing the display while
    the COO answers in prose (§10's "changes the visual focus, and answers
    conversationally" - both, not either).

    Weaker than `interpret` on purpose: this never suppresses the model, it
    only suggests where to look while the answer arrives. A wrong suggestion
    costs a tab change during an answer that still comes; a wrong `interpret`
    would swallow the question entirely."""
    normalised = _normalise(text)
    return _match_view(normalised) if normalised else None
