"""The Learning Engine: the skill of learning a skill (Krish, 2026-09-21).

Documents 1 and 2 ask for a repeatable method by which Jarvis moves from *"I
cannot do this"* to *"I have demonstrated that I can do this reliably"*, and
which gets better at that with use.

## The one decision the whole design rests on

**A learned skill is a `Recipe`: a declarative specification executed by a fixed
interpreter — not generated Python.**

Document 1 §2 asks for demonstrated capability. Document 2 §3's own worked
example asks for a capability that runs *"without relying on an external LLM"*
and is *"a reusable deterministic capability"*. Both are satisfied by a recipe:
it really executes, it really is deterministic, and running it costs no tokens.

What a recipe is not is arbitrary code, and three separate things in this
repository made that the right call rather than a timid one:

1. `backend/engineering.py` §8's ladder puts code last and says an engineer that
   reaches it *"names the gap and stops"*. A learning engine that wrote Python
   would cross a documented architectural boundary on its own initiative.
2. `app/initiative.HARM_WIDENS_ITS_OWN_AUTHORITY` refuses self-granted authority
   at every boldness setting. Code that Jarvis wrote and then ran is exactly
   that, wearing a feature's clothes.
3. Addendum 46 §2's architecture is *stable machinery, evolving data*. A recipe
   is data. It versions, diffs, reverts and is inspectable by a person, which is
   what makes §24's rollback requirement trivial instead of a build.

The interpreter's primitives are fixed in `recipe.py` and the command and path
allow-lists are fixed in `sandbox.py`. **Jarvis composes primitives; it cannot
add one.** When a skill genuinely needs a primitive that does not exist, the
honest outcome is a boundary proposal (`app/boundaries.py`), which is the
mechanism Krish asked for on the same day and which closes this loop exactly.

## What learning actually consists of here

Composing a recipe is not trivial and is not guessing. The first exercise —
Document 2 §3's own example, mapping network connections to owning processes —
requires discovering that `/proc/net/tcp` exists, that its addresses are
little-endian hex, that its state column is a hex enum, that the socket inode
has to be joined against `/proc/<pid>/fd` symlinks, and that the process name
lives in `/proc/<pid>/comm`. Every one of those is learned by probing the
machine and being wrong first. That is the loop.

## The honest limits, stated here rather than discovered

- **There is no web access.** Nothing in this repository can fetch a document.
  Document 1 §10's source hierarchy is therefore implemented over the sources
  that do exist — this codebase, its tests and docs, and *empirical probing of
  the machine* — with the missing tier recorded rather than faked.
  `research.py` says so in its provenance rather than implying a document was
  read.
- **There is no local model.** Every model call goes to Kimi. So "learn to stop
  using an LLM for this" can currently mean *deterministic* replacement only,
  which is real and is what the first exercise does.
- **Registration proposes; Krish accepts.** Document 2 §7 makes feedback part of
  completion, and the harm floor forbids self-granted authority. A skill reaches
  `MASTERED` on evidence and becomes operational on his word.

## Reading order

`objective` (what) → `research` (what I don't know) → `recipe` (the thing being
built) → `sandbox` (where it runs) → `practice` (attempt/diagnose/retry) →
`mastery` (am I done) → `memory` (what I learned about learning) → `engine`
(the lifecycle and the plain-language narration Document 2 §2 and §11 require).
"""

from app.learning.engine import (
    LearningEngine,
    candidates,
    default_engine,
    explain_how_i_learn,
)
from app.learning.mastery import STATES, State
from app.learning.objective import Objective, ObjectiveRefused
from app.learning.recipe import Recipe, RecipeError, Step

__all__ = [
    "LearningEngine", "default_engine", "explain_how_i_learn", "candidates",
    "Objective", "ObjectiveRefused",
    "Recipe", "RecipeError", "Step",
    "State", "STATES",
]
