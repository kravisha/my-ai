"""Stable unique identifiers (§5.4).

*"Human-readable names must not be used as the only primary key."* The reason
is the whole of §4's example A: two people called John Smith are two records,
and a system keyed on the name has already lost the ability to tell them apart
by the time anybody asks it to.

## Shape, and why it is not a bare UUID

`person-3f9a1c2e4b6d8a70`. A type prefix and sixteen hex characters of
randomness. The prefix costs nothing and buys two things that matter when
somebody is reading a log at the wrong end of a bad day: an id says what it is
without a lookup, and an id used against the wrong table is visible as a
mistake rather than as a `not_found`.

Random rather than sequential, because a sequential id leaks how many records
exist and lets one be guessed from another. Sixteen hex characters is 64 bits;
at this system's scale a collision is not a thing that happens, and
`assign` still checks rather than assuming - see its docstring.
"""

from __future__ import annotations

import re
import secrets

# Long enough that collisions are not a practical concern, short enough to be
# read aloud and typed into a search box, which is a real thing Krish will do.
RANDOM_HEX_CHARACTERS = 16

_SLUG = re.compile(r"^[a-z][a-z0-9_]*$")
_ID = re.compile(r"^([a-z][a-z0-9_]*)-([0-9a-f]{%d})$" % RANDOM_HEX_CHARACTERS)


class IdRefused(ValueError):
    """An identifier that cannot be produced or parsed, said as such."""


def new_id(entity_type: str) -> str:
    """A fresh identifier for one entity type."""
    if not _SLUG.match(entity_type or ""):
        raise IdRefused(
            f"entity_type={entity_type!r} must be a lower-case slug - it becomes "
            f"the readable half of every id of this type, and a space or a "
            f"capital in it makes an id that cannot be round-tripped.")
    return f"{entity_type}-{secrets.token_hex(RANDOM_HEX_CHARACTERS // 2)}"


def type_of(entity_id: str) -> str:
    """The entity type an id declares. Raises if it declares nothing."""
    match = _ID.match(entity_id or "")
    if match is None:
        raise IdRefused(
            f"{entity_id!r} is not an identifier this system issued. They are "
            f"'<entity_type>-<{RANDOM_HEX_CHARACTERS} hex characters>'.")
    return match.group(1)


def is_id(value: object) -> bool:
    """Whether this looks like an id at all, for the branch that has to decide
    between an identifier and a name before it looks anything up."""
    return isinstance(value, str) and _ID.match(value) is not None


def belongs_to(entity_id: str, entity_type: str) -> bool:
    """Whether an id is of the type the caller expected.

    Separate from `type_of` because the caller that asks this wants a boolean
    for a refusal message, not an exception it has to catch to build one."""
    try:
        return type_of(entity_id) == entity_type
    except IdRefused:
        return False
