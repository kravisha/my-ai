"""Parliament: how a proposal becomes authority (TASK_QUEUE TQ-81; addendum 32;
addendum 46 §5, §6, §17; docs/SPEC_RECONCILIATION.md §119, §120, §122, §123).

Until now this system answered honestly that it had no such thing:

    "No parliament, committee or voting body exists yet."

Addendum 46 routes every authorized change through one, so it was the
load-bearing organ of the newest specification and the one that was missing.

## What is here, and what is deliberately not

Here: **the Articles**, the organization's own highest instrument; resolutions
carrying the provenance addendum 46 §17 requires; a vote with a quorum and a
threshold; and the level-0 refusal that keeps the Constitution out of reach.

Not here, and not queued: elections, ministers, committees, the weekly session,
the State-of-the-Union event. Addendum 32 specifies all of them and **none is
required for a directive to be authorized**. They enter when something needs
them, which is the same rule that kept the Portfolio Analyst from acquiring a
department.

## The rule for changing the rules is not changeable by the rules

The Articles carry the electorate, the quorum and the ordinary threshold - as
data, which is the whole point of addendum 46 §2. What they do **not** carry is
the threshold for amending themselves. That lives here, in code, as
`ARTICLES_AMENDMENT_THRESHOLD`, because an instrument that could lower its own
amendment bar by ordinary vote has no amendment bar at all.

This is §120's mechanism one level down. The Constitution is enforced by a test
that fails; the Articles' amendment rule is enforced by a constant a vote cannot
reach. Neither is a permission that could be granted.

## Level 0, and the honest limit

A proposal declares what it `affects`. A proposal declaring `constitution` is
refused and escalated to the owner; so is one declaring a level this module does
not know, because an undetermined target is not a safe one (§100's rule, applied
to governance).

**What this cannot do is detect a level-0 change wearing a lower label.** The
system does not hold the Constitution - deliberately, §120 - so nothing here can
read it and notice that a proposed "policy" contradicts it. The refusal covers
what is declared. Saying so is part of the guarantee; a governance layer that
implied it could catch a disguised amendment would be the falsely-written charter
`backend/charter.py` exists to avoid.

## Escalations nothing in this system can clear

Every other escalation in this organization ends somewhere inside it. A level-0
escalation ends at a person, and **no function here closes one**. The owner
records a decision through `record_owner_decision`, which needs an `OwnerContext`
built from a session subject and never from caller input (addendum 44 §9.2) - so
an agent cannot manufacture one. A queue that accumulates until the owner reads
it is the correct behaviour, not a leak (§120).

Sits below `fi_db` (`fi_db.init_schema` creates these tables), so it must not
import it - the same layering as `register.py`, `risk.py` and `strategy.py`.
"""

from __future__ import annotations

import json
from fractions import Fraction

from backend import portfolios
from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS constitution (
    version INTEGER PRIMARY KEY,
    adopted_at TEXT NOT NULL,
    adopted_by TEXT NOT NULL,
    -- 'genesis' once, from the owner; 'amendment' thereafter, from a vote.
    adopted_via TEXT NOT NULL,
    resolution_id INTEGER,
    text TEXT NOT NULL
    -- **No roll, no quorum, no threshold here.** The electorate is the Articles'
    -- (level 1), because there is only one organization and a second roll would
    -- be a second answer to who may vote. The amendment threshold is
    -- CONSTITUTIONAL_AMENDMENT_THRESHOLD, in code, for the reason §123 gives.
    --
    -- The consequence is real and is recorded rather than guarded against: a
    -- supermajority can amend the Articles' roll, and the roll decides who
    -- amends the Constitution. Addendum 32 §19.3 explicitly permits a
    -- constitutional amendment to require "new voting rights" and "removal of
    -- voting rights", so a countermeasure here would contradict the
    -- specification it was protecting. See SPEC_RECONCILIATION §142.
);

CREATE TABLE IF NOT EXISTS articles (
    version INTEGER PRIMARY KEY,
    adopted_at TEXT NOT NULL,
    adopted_by TEXT NOT NULL,
    -- How it came into force: 'genesis' once, 'amendment' thereafter.
    adopted_via TEXT NOT NULL,
    -- The resolution that amended it. NULL for the genesis text only.
    resolution_id INTEGER,
    text TEXT NOT NULL,
    -- The electorate and the arithmetic, as data (addendum 46 §2). The
    -- amendment threshold is NOT here; see ARTICLES_AMENDMENT_THRESHOLD.
    roll TEXT NOT NULL,
    quorum TEXT NOT NULL,
    ordinary_threshold TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    -- Addendum 46 §17's provenance questions, one column each.
    title TEXT NOT NULL,             -- what changed
    rationale TEXT NOT NULL,         -- why did it change
    proposed_by TEXT NOT NULL,       -- who proposed it
    evidence TEXT,                   -- what evidence supported it
    affects TEXT NOT NULL,           -- which level of the hierarchy
    replaces INTEGER,                -- what previous version it replaces
    tier TEXT NOT NULL,              -- which electorate decides (32 §5)
    approved_by TEXT,                -- the tally, snapshotted at enactment
    became_active_at TEXT,           -- when it became active
    articles_text TEXT,              -- the proposed Articles, for an amendment
    -- The proposed Constitution, for a constitutional amendment. A SEPARATE
    -- column rather than one shared "proposed text": two instruments at two
    -- levels, and separate columns make it structurally impossible to apply a
    -- text meant for one as the other. `close` would otherwise have to infer it
    -- from `affects`, which is inference where a refusal is available.
    constitution_text TEXT,
    closed_reason TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS resolutions_by_status ON resolutions (status, id);

CREATE TABLE IF NOT EXISTS resolution_votes (
    resolution_id INTEGER NOT NULL,
    voter TEXT NOT NULL,
    value TEXT NOT NULL,
    cast_at TEXT NOT NULL,
    PRIMARY KEY (resolution_id, voter)
);

CREATE TABLE IF NOT EXISTS owner_escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raised_at TEXT NOT NULL,
    -- What was attempted, in the words of whoever attempted it.
    summary TEXT NOT NULL,
    raised_by TEXT NOT NULL,
    -- Set only by record_owner_decision, which needs an OwnerContext.
    decided_at TEXT,
    decided_by TEXT,
    record_reference TEXT
);
CREATE INDEX IF NOT EXISTS owner_escalations_open ON owner_escalations (decided_at, id);

CREATE TABLE IF NOT EXISTS speaker_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filed_at TEXT NOT NULL,
    -- Which Speaker said it. A report with no author is a rumour.
    speaker_identity TEXT NOT NULL,
    report TEXT NOT NULL,
    -- When the Speaker last looked and found this still true. A saturation run
    -- showed it filing three hundred identical reports in three hundred seconds
    -- (§128) - a table growing at a row a second to say nothing had changed.
    --
    -- Two facts are worth keeping and they are not the same: when Parliament's
    -- state last *changed*, and when somebody last *checked*. Collapsing them
    -- either loses the second (file only on change, and a dead Speaker looks
    -- like a quiet Parliament) or floods on the first.
    reaffirmed_at TEXT,
    -- How many times the Speaker looked and found this still true. Rows count
    -- CHANGES now, so a row count no longer measures whether anybody is
    -- watching - this does. Separating them was forced by a scenario property
    -- that read "the Speaker reported: 1 >= 3" and was measuring the wrong
    -- thing the moment repeats stopped being rows (§128).
    reaffirmations INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS speaker_reports_recent ON speaker_reports (id DESC);
"""

SCHEMA_VERSION = 1

# Addendum 46 §5's hierarchy, most authoritative first, with §120's level 0 at
# the head. It is the one place the precedence lives; `_RESERVED_LEVELS` and
# `_RESTRICTED_LEVELS` below are drawn from it rather than restating it.
LEVEL_CONSTITUTION = "constitution"
LEVEL_CONSTITUTION_AMENDMENT = "constitution_amendment"
LEVELS = (
    LEVEL_CONSTITUTION,
    LEVEL_CONSTITUTION_AMENDMENT,
    "articles",
    "articles_amendment",
    "law",
    "organization_policy",
    "department_policy",
    "procedure",
    "strategy",
    "operational_directive",
    "project_instruction",
    "knowledge",
    "observation",
    "suggestion",
)

# The levels an ordinary `propose` may not reach. `constitution` and `articles`
# are the documents themselves and are never what a resolution *affects*; the two
# `_amendment` levels are reachable only through their own entry points, which
# set them - a caller naming one directly is trying to route an amendment through
# the ordinary path and its ordinary threshold.
_RESERVED_LEVELS = (LEVEL_CONSTITUTION, LEVEL_CONSTITUTION_AMENDMENT,
                    "articles", "articles_amendment")

# 32 §5's two tiers. Which one applies is decided by `_tier_for`, not by the
# proposer, because a proposer choosing its own electorate chooses its own odds.
TIER_BROAD = "broad"
TIER_REPRESENTATIVE = "representative"
TIERS = (TIER_BROAD, TIER_REPRESENTATIVE)

# 32 §6.3: authority, rights, risk, multiple departments, long-term strategy.
# Anything on this list is a restricted vote whatever the proposer wanted.
_RESTRICTED_LEVELS = (
    LEVEL_CONSTITUTION_AMENDMENT,
    "articles_amendment", "law", "organization_policy", "strategy",
)

VOTE_FOR = "for"
VOTE_AGAINST = "against"
VOTE_ABSTAIN = "abstain"
VOTES = (VOTE_FOR, VOTE_AGAINST, VOTE_ABSTAIN)

STATUS_OPEN = "open"
STATUS_ENACTED = "enacted"
STATUS_REJECTED = "rejected"
STATUS_WITHDRAWN = "withdrawn"
STATUSES = (STATUS_OPEN, STATUS_ENACTED, STATUS_REJECTED, STATUS_WITHDRAWN)

# 32 §19.1: "A supermajority such as two-thirds MAY be required."
#
# Fixed here rather than in the Articles, and that is the design. An instrument
# whose amendment threshold is one of its own clauses can be amended down to
# nothing by a simple majority in two steps: lower the bar, then walk through it.
ARTICLES_AMENDMENT_THRESHOLD = Fraction(2, 3)

# Owner decision, 2026-08-28: *"yes, the organization can amend it at
# supermajority"* (§142). Two-thirds is 32 §19.1's own number - *"a supermajority
# such as two-thirds MAY be required"* - and the only one the corpus specifies.
# A higher bar would read as measured and would be invented.
#
# In code for the same reason as the Articles', and it matters more here: a
# constitutional amendment threshold written into the Constitution could be
# lowered by one supermajority and then everything below it walked through.
CONSTITUTIONAL_AMENDMENT_THRESHOLD = Fraction(2, 3)

# Level 0 must never be cheaper to amend than level 1. If it were, a majority
# wanting an Articles change could take the constitutional route instead and
# arrive with a *higher-order* directive (32 §19.2) for the same price, which
# inverts the hierarchy while every individual rule still looks correct.
#
# Asserted at import rather than tested, because the failure is a
# misconfiguration that must not be able to start.
assert CONSTITUTIONAL_AMENDMENT_THRESHOLD >= ARTICLES_AMENDMENT_THRESHOLD, (
    "the Constitution may not be easier to amend than the Articles")

# One refusal for every reason a proposal cannot proceed (addendum 44 §9.3). A
# refusal that distinguished "unconstitutional" from "unknown level" from "no
# Articles yet" would be a way to read the governance state without being
# entitled to it.
REFUSAL = "Refused. This proposal cannot proceed, and it has been escalated."


class ParliamentRefused(PermissionError):
    """A proposal, vote or enactment the machinery will not perform."""


class NoArticles(LookupError):
    """No Articles are in force, so there is no electorate and no arithmetic."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


# --- the Constitution ---------------------------------------------------------------

def adopt_genesis_constitution(conn: Database, *, owner, text: str) -> int:
    """The first Constitution, authored by the owner rather than voted.

    **Owner decision, 2026-08-28: the organization may amend the Constitution at
    supermajority** (§142), which reverses §120's *"no table, no protected row,
    no admin route"*. Amending something requires holding it, and a vote on a
    document nobody can read is theatre.

    Genesis is still the owner's, on `adopt_genesis_articles`' argument one level
    up: a vote needs an electorate, and the electorate is defined by the Articles,
    which are defined below the Constitution. Something has to be first.

    **This machinery holds no text until the owner puts one here.** Addendum 49 is
    the Constitution and is held privately; nothing in this repository seeds it,
    and `financial_intelligence.db` is not versioned. The capability exists and
    the document is the owner's to place.
    """
    context = _require_superuser(owner)
    if current_constitution(conn) is not None:
        raise ParliamentRefused(
            "A Constitution is already in force. Changing it is an amendment, which is voted.")
    if not (text or "").strip():
        raise ParliamentRefused("A Constitution with no text governs nothing.")
    conn.execute(
        "INSERT INTO constitution (version, adopted_at, adopted_by, adopted_via,"
        " resolution_id, text) VALUES (1, ?, ?, 'genesis', NULL, ?)",
        (now_iso(), context.owner_id, text.strip()))
    return 1


def current_constitution(conn: Database) -> dict | None:
    return conn.fetchone(
        "SELECT version, adopted_at, adopted_by, adopted_via, resolution_id, text"
        " FROM constitution ORDER BY version DESC LIMIT 1")


def constitution_history(conn: Database) -> list[dict]:
    """Every version, oldest first. Nothing is overwritten.

    The text is deliberately not returned: a history is for answering *when did
    this change and under what resolution*, and a caller wanting a superseded
    constitutional text should have to ask for that version by name."""
    return conn.fetchall(
        "SELECT version, adopted_at, adopted_by, adopted_via, resolution_id"
        " FROM constitution ORDER BY version")


def propose_constitutional_amendment(
    conn: Database,
    *,
    title: str,
    rationale: str,
    proposed_by: str,
    constitution_text: str,
    evidence: str | None = None,
) -> int:
    """Propose a new Constitution. The only route to `constitution_amendment`.

    Separate from `propose` and from `propose_amendment` for the reason the
    latter is separate: the level is not a parameter anybody can pass, so it
    cannot be passed wrongly. It clears `CONSTITUTIONAL_AMENDMENT_THRESHOLD`,
    which is in code and cannot be amended by what it governs.

    Carries the **whole replacement text**, not a diff. Addendum 32 §19.2 makes a
    passed amendment a highest-order directive immediately; a diff would mean the
    thing in force is the result of applying something to something else, and
    what was voted on would be neither."""
    constitution = current_constitution(conn)
    if constitution is None:
        raise ParliamentRefused(
            "There is no Constitution to amend. The genesis text is the owner's.")
    if not (constitution_text or "").strip():
        raise ParliamentRefused("An amendment must carry the text it proposes.")
    return _insert(conn, title=title, rationale=rationale, proposed_by=proposed_by,
                   affects=LEVEL_CONSTITUTION_AMENDMENT, evidence=evidence,
                   replaces=constitution["version"],
                   constitution_text=constitution_text.strip())


# --- the Articles -------------------------------------------------------------------

def adopt_genesis_articles(
    conn: Database,
    *,
    owner,
    text: str,
    roll: dict,
    quorum: str,
    ordinary_threshold: str,
) -> int:
    """The first Articles, authored by the owner rather than voted.

    There is no bootstrap by vote: a vote needs an electorate, a quorum and a
    threshold, and until the Articles say what those are the organization has no
    way to decide anything - including what they should be. So the genesis text
    comes from level 0's holder and everything after it is amendment by vote.

    Refused if Articles already exist. Genesis happens once; a second one would
    be an amendment wearing a different name and skipping the threshold.
    """
    context = _require_superuser(owner)
    if current_articles(conn) is not None:
        raise ParliamentRefused(
            "Articles are already in force. Changing them is an amendment, which is voted.")
    _check_arithmetic(roll, quorum, ordinary_threshold)
    conn.execute(
        "INSERT INTO articles (version, adopted_at, adopted_by, adopted_via, resolution_id,"
        " text, roll, quorum, ordinary_threshold) VALUES (1, ?, ?, 'genesis', NULL, ?, ?, ?, ?)",
        (now_iso(), context.owner_id, text.strip(), json.dumps(roll), quorum, ordinary_threshold),
    )
    return 1


def current_articles(conn: Database) -> dict | None:
    article = conn.fetchone(
        "SELECT version, adopted_at, adopted_by, adopted_via, resolution_id, text,"
        " roll, quorum, ordinary_threshold FROM articles ORDER BY version DESC LIMIT 1")
    if article is None:
        return None
    article["roll"] = json.loads(article["roll"])
    return article


def articles_history(conn: Database) -> list[dict]:
    """Every version, oldest first.

    Nothing is ever overwritten: an amendment inserts a new version. Addendum 46
    §18 - *"nothing about rollback should erase history"* - and a governance
    record that could lose a superseded text could not answer what a resolution
    replaced."""
    return conn.fetchall(
        "SELECT version, adopted_at, adopted_by, adopted_via, resolution_id"
        " FROM articles ORDER BY version")


# --- proposing ----------------------------------------------------------------------

def propose(
    conn: Database,
    *,
    title: str,
    rationale: str,
    proposed_by: str,
    affects: str,
    evidence: str | None = None,
    replaces: int | None = None,
) -> int:
    """File a resolution for a vote.

    Refuses - and escalates - anything aimed at level 0 or at a level this module
    does not know. Both get the same words, because a refusal that told the
    caller *which* rule caught it would let an agent map the boundary by probing
    it."""
    if affects in _RESERVED_LEVELS or affects not in LEVELS:
        escalate(
            conn,
            summary=(f"Proposal {title!r} declared affects={affects!r}, which no vote may reach."),
            raised_by=proposed_by,
        )
        raise ParliamentRefused(REFUSAL)
    return _insert(conn, title=title, rationale=rationale, proposed_by=proposed_by,
                   affects=affects, evidence=evidence, replaces=replaces)


def propose_amendment(
    conn: Database,
    *,
    title: str,
    rationale: str,
    proposed_by: str,
    articles_text: str,
    evidence: str | None = None,
) -> int:
    """Propose new Articles. The only route to `articles_amendment`.

    Separate from `propose` on purpose: an amendment carries a replacement text
    and clears a higher bar, and a single entry point taking a level as an
    argument would make the difference a parameter somebody could pass wrongly.
    """
    articles = current_articles(conn)
    if articles is None:
        raise NoArticles("There are no Articles to amend.")
    if not (articles_text or "").strip():
        raise ParliamentRefused("An amendment must carry the text it proposes.")
    return _insert(conn, title=title, rationale=rationale, proposed_by=proposed_by,
                   affects="articles_amendment", evidence=evidence,
                   replaces=articles["version"], articles_text=articles_text.strip())


def _insert(conn: Database, *, title, rationale, proposed_by, affects, evidence,
            replaces, articles_text=None, constitution_text=None) -> int:
    for name, value in (("title", title), ("rationale", rationale),
                        ("proposed_by", proposed_by)):
        if not (value or "").strip():
            raise ParliamentRefused(f"A resolution needs a {name}.")
    if current_articles(conn) is None:
        raise NoArticles(
            "No Articles are in force, so there is no electorate to put this to.")
    stamp = now_iso()
    return conn.execute_returning_id(
        "INSERT INTO resolutions (created_at, updated_at, status, title, rationale,"
        " proposed_by, evidence, affects, replaces, tier, articles_text, constitution_text)"
        " VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (stamp, stamp, title.strip(), rationale.strip(), proposed_by.strip(),
         evidence, affects, replaces, _tier_for(affects), articles_text, constitution_text),
    )


def _tier_for(affects: str) -> str:
    """32 §6: voting rights proportional to the impact of the decision.

    Decided here from the level, never supplied by the proposer - 32 §6.3 lists
    what must go through representative structures, and a proposer who picked its
    own electorate would be picking its own odds."""
    return TIER_REPRESENTATIVE if affects in _RESTRICTED_LEVELS else TIER_BROAD


# --- voting -------------------------------------------------------------------------

def cast_vote(conn: Database, resolution_id: int, *, voter: str, value: str) -> None:
    """One voter, one vote, and only while the resolution is open.

    The roll comes from the Articles. A voter not on the roll for this tier is
    refused rather than counted-and-ignored: a tally that silently dropped
    ineligible votes would report a quorum it did not have."""
    if value not in VOTES:
        raise ParliamentRefused(f"unknown vote {value!r}; known are {list(VOTES)}")
    resolution = get_resolution(conn, resolution_id)
    if resolution is None or resolution["status"] != STATUS_OPEN:
        raise ParliamentRefused(REFUSAL)
    roll = _roll_for(conn, resolution["tier"])
    normalised = (voter or "").strip().lower()
    if normalised not in roll:
        raise ParliamentRefused(REFUSAL)
    existing = conn.fetchone(
        "SELECT value FROM resolution_votes WHERE resolution_id = ? AND voter = ?",
        (resolution_id, normalised))
    if existing is not None:
        raise ParliamentRefused(
            f"{normalised} has already voted on resolution {resolution_id}.")
    conn.execute(
        "INSERT INTO resolution_votes (resolution_id, voter, value, cast_at) VALUES (?, ?, ?, ?)",
        (resolution_id, normalised, value, now_iso()))


def tally(conn: Database, resolution_id: int) -> dict:
    """Count the votes and say whether the bar was cleared.

    Two rules worth stating because both are choices:

    - **Abstentions count toward the quorum and not toward the threshold.**
      Turning up and declining to decide is participation; treating it as
      opposition would make abstaining a way of voting against without saying so.
    - **The threshold is measured against `for + against`**, not against the
      whole roll, once quorum is met.
    """
    resolution = get_resolution(conn, resolution_id)
    if resolution is None:
        raise ParliamentRefused(REFUSAL)
    roll = _roll_for(conn, resolution["tier"])
    rows = conn.fetchall(
        "SELECT value FROM resolution_votes WHERE resolution_id = ?", (resolution_id,))
    counts = {value: sum(1 for r in rows if r["value"] == value) for value in VOTES}
    turnout = sum(counts.values())
    articles = current_articles(conn)
    quorum = _fraction(articles["quorum"])
    threshold = _threshold_for(resolution["affects"], articles)
    decided = counts[VOTE_FOR] + counts[VOTE_AGAINST]
    quorum_met = len(roll) > 0 and Fraction(turnout, len(roll)) >= quorum
    carried = quorum_met and decided > 0 and Fraction(counts[VOTE_FOR], decided) >= threshold
    return {
        "resolution_id": resolution_id,
        "tier": resolution["tier"],
        "roll_size": len(roll),
        "turnout": turnout,
        "for": counts[VOTE_FOR],
        "against": counts[VOTE_AGAINST],
        "abstain": counts[VOTE_ABSTAIN],
        "quorum": str(quorum),
        "quorum_met": quorum_met,
        "threshold": str(threshold),
        # Named so a reader can tell an amendment's fixed bar from an ordinary
        # one read out of the Articles.
        # Named so a reader can tell an amendment's fixed bar from an ordinary
        # one read out of the Articles. Both amendment bars are in code, and
        # saying so is what makes "a rule a vote can reach is not a rule"
        # checkable from the tally rather than only from the source.
        "threshold_source": ("code" if resolution["affects"] in _CODE_THRESHOLD_LEVELS
                             else "articles"),
        "carried": carried,
    }


# The levels whose threshold is a constant here rather than a clause in the
# document being amended (§123, §142). Derived once so `tally` and its reported
# `threshold_source` cannot disagree about which those are.
_CODE_THRESHOLD_LEVELS = (LEVEL_CONSTITUTION_AMENDMENT, "articles_amendment")


def _threshold_for(affects: str, articles: dict) -> Fraction:
    if affects == LEVEL_CONSTITUTION_AMENDMENT:
        return CONSTITUTIONAL_AMENDMENT_THRESHOLD
    if affects == "articles_amendment":
        return ARTICLES_AMENDMENT_THRESHOLD
    return _fraction(articles["ordinary_threshold"])


def close(conn: Database, resolution_id: int) -> dict:
    """Close the vote and apply the result.

    A carried amendment inserts a new Articles version here rather than in a
    separate call, because an amendment that passed but was not applied is a
    governance state nobody can read correctly."""
    resolution = get_resolution(conn, resolution_id)
    if resolution is None or resolution["status"] != STATUS_OPEN:
        raise ParliamentRefused(REFUSAL)
    result = tally(conn, resolution_id)
    stamp = now_iso()
    if not result["carried"]:
        conn.execute(
            "UPDATE resolutions SET status = ?, updated_at = ?, approved_by = ?,"
            " closed_reason = ? WHERE id = ?",
            (STATUS_REJECTED, stamp, json.dumps(result),
             "quorum not met" if not result["quorum_met"] else "threshold not met",
             resolution_id))
        return result

    if resolution["affects"] == LEVEL_CONSTITUTION_AMENDMENT:
        previous = current_constitution(conn)
        conn.execute(
            "INSERT INTO constitution (version, adopted_at, adopted_by, adopted_via,"
            " resolution_id, text) VALUES (?, ?, 'parliament', 'amendment', ?, ?)",
            (previous["version"] + 1, stamp, resolution_id,
             resolution["constitution_text"]))
    if resolution["affects"] == "articles_amendment":
        previous = current_articles(conn)
        conn.execute(
            "INSERT INTO articles (version, adopted_at, adopted_by, adopted_via,"
            " resolution_id, text, roll, quorum, ordinary_threshold)"
            " VALUES (?, ?, 'parliament', 'amendment', ?, ?, ?, ?, ?)",
            (previous["version"] + 1, stamp, resolution_id, resolution["articles_text"],
             json.dumps(previous["roll"]), previous["quorum"],
             previous["ordinary_threshold"]))
    conn.execute(
        "UPDATE resolutions SET status = ?, updated_at = ?, approved_by = ?,"
        " became_active_at = ? WHERE id = ?",
        (STATUS_ENACTED, stamp, json.dumps(result), stamp, resolution_id))
    return result


def withdraw(conn: Database, resolution_id: int, *, reason: str) -> None:
    if not (reason or "").strip():
        raise ParliamentRefused("Withdrawing a resolution needs a reason.")
    changed = conn.execute_returning_rowcount(
        "UPDATE resolutions SET status = ?, updated_at = ?, closed_reason = ?"
        " WHERE id = ? AND status = ?",
        (STATUS_WITHDRAWN, now_iso(), reason.strip(), resolution_id, STATUS_OPEN))
    if not changed:
        raise ParliamentRefused(REFUSAL)


def get_resolution(conn: Database, resolution_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM resolutions WHERE id = ?", (resolution_id,))


def open_resolutions(conn: Database) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM resolutions WHERE status = ? ORDER BY id", (STATUS_OPEN,))


# --- level 0 ------------------------------------------------------------------------

def escalate(conn: Database, *, summary: str, raised_by: str) -> int:
    """Raise something to the owner. Nothing in this system can answer it.

    There is deliberately no `resolve`, no `dismiss` and no expiry. The only
    function that writes a terminal state is `record_owner_decision`, and it
    needs an `OwnerContext` - which is built from a session subject and never
    from anything a caller sent."""
    return conn.execute_returning_id(
        "INSERT INTO owner_escalations (raised_at, summary, raised_by) VALUES (?, ?, ?)",
        (now_iso(), (summary or "").strip() or "unspecified", (raised_by or "unknown").strip()))


def outstanding_escalations(conn: Database) -> list[dict]:
    return conn.fetchall(
        "SELECT id, raised_at, summary, raised_by FROM owner_escalations"
        " WHERE decided_at IS NULL ORDER BY id")


def record_owner_decision(
    conn: Database, escalation_id: int, *, owner, record_reference: str
) -> None:
    """The owner's answer, recorded as this system's own.

    **Not "arriving from outside the system"**, which is what this docstring said
    until §141 and which the function has never done. The owner is part of the
    system (owner correction, 2026-08-28): `_require_superuser` authenticates
    them from a session subject, `decided_by` records which owner, and the row
    lives in the organization's own table where its Speaker can report it. The
    prose described the behaviour incorrectly while the code implemented it
    correctly - §120's framing leaking into a function that never shared it.

    `record_reference` is required for the reason `register.set_status` requires
    one on a completed entry: the pointer *is* the verification. An escalation
    closed with no record of what was decided has been silenced rather than
    answered."""
    context = _require_superuser(owner)
    if not (record_reference or "").strip():
        raise ParliamentRefused(
            "Closing an escalation needs the reference that records what was decided.")
    changed = conn.execute_returning_rowcount(
        "UPDATE owner_escalations SET decided_at = ?, decided_by = ?, record_reference = ?"
        " WHERE id = ? AND decided_at IS NULL",
        (now_iso(), context.owner_id, record_reference.strip(), escalation_id))
    if not changed:
        raise ParliamentRefused(REFUSAL)


# --- helpers ------------------------------------------------------------------------

def _require_superuser(owner) -> portfolios.OwnerContext:
    context = portfolios.require_owner(owner)
    if context.owner_type != portfolios.OWNER_SUPERUSER:
        raise ParliamentRefused(REFUSAL)
    return context


def _roll_for(conn: Database, tier: str) -> tuple[str, ...]:
    articles = current_articles(conn)
    if articles is None:
        raise NoArticles("No Articles are in force, so there is no electorate.")
    return tuple(articles["roll"].get(tier, ()))


def _fraction(value: str) -> Fraction:
    return Fraction(str(value))


def _check_arithmetic(roll: dict, quorum: str, ordinary_threshold: str) -> None:
    if not isinstance(roll, dict) or set(roll) - set(TIERS):
        raise ParliamentRefused(f"The roll names tiers; known are {list(TIERS)}.")
    if not any(roll.get(tier) for tier in TIERS):
        raise ParliamentRefused("Articles with an empty roll would create a body that cannot vote.")
    for name, value in (("quorum", quorum), ("ordinary threshold", ordinary_threshold)):
        try:
            fraction = _fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ParliamentRefused(f"The {name} must be a fraction, e.g. '1/2'.") from error
        if not (0 < fraction <= 1):
            raise ParliamentRefused(f"The {name} must be above 0 and at most 1.")


SPEAKER_ROLE = "speaker"


def record_speaker_report(conn: Database, *, speaker_identity: str, report: dict) -> int:
    """File what the Speaker has to say about Parliament.

    Owner direction, 2026-08-27: *"the agent should be reporting and not the
    system."* Before this, `/console/overview` read these tables itself and
    rendered them, which meant the organization's account of its own governance
    was produced by the web server - a narrator with no role in the story and no
    accountability for it.

    Now Parliament has a Speaker, and a status surface reads **what the Speaker
    said**. The difference is not cosmetic: a report has an author, a time, and a
    silence that can be noticed. A query has none of those, and a query that
    always answers cannot tell anyone that nobody is watching."""
    if not (speaker_identity or "").strip():
        raise ParliamentRefused("A report needs the Speaker who filed it.")
    stated = json.dumps(report, sort_keys=True)
    standing = conn.fetchone(
        "SELECT id, report FROM speaker_reports ORDER BY id DESC LIMIT 1")
    if standing is not None and standing["report"] == stated:
        # Nothing has changed. The Speaker looked, and saying so is worth
        # recording; saying it again in a new row is not.
        conn.execute(
            "UPDATE speaker_reports SET reaffirmed_at = ?, reaffirmations = reaffirmations + 1"
            " WHERE id = ?", (now_iso(), standing["id"]))
        return int(standing["id"])
    return conn.execute_returning_id(
        "INSERT INTO speaker_reports (filed_at, speaker_identity, report, reaffirmed_at)"
        " VALUES (?, ?, ?, ?)",
        (now_iso(), speaker_identity.strip(), stated, now_iso()))


def latest_speaker_report(conn: Database) -> dict | None:
    """The Speaker's most recent account, or `None` if it has not spoken.

    `None` is the answer a surface must render as *the Speaker has not reported*
    rather than quietly falling back to querying the tables. A fallback would
    restore exactly what the owner objected to, and would do it invisibly - the
    console would look identical whether the Speaker was working or dead."""
    row = conn.fetchone(
        "SELECT id, filed_at, speaker_identity, report, reaffirmed_at, reaffirmations"
        " FROM speaker_reports"
        " ORDER BY id DESC LIMIT 1")
    if row is None:
        return None
    row["report"] = json.loads(row["report"])
    return row


def summary(conn: Database) -> dict:
    """The state of Parliament, **for the Speaker to read**.

    Not for a status surface. This is the material the Speaker turns into a
    report; a surface calling it directly is the system speaking for Parliament
    again, and `tests/test_speaker.py` asserts the console does not.

    It replaced the sentence `/health` and the COO's answer carried since
    addendum 32 was assimilated - *"No parliament, committee or voting body
    exists yet"* - which was true and is not any more."""
    articles = current_articles(conn)
    constitution = current_constitution(conn)
    return {
        # The Constitution is amendable by the organization at supermajority
        # (owner decision 2026-08-28, §142), so its version is something that can
        # *change* while the system runs - which makes reporting it necessary
        # rather than decorative. An amendment nobody can see is §130's quiet
        # market at level 0.
        #
        # The version and never the text: the Speaker reports the state of
        # Parliament, and a spokesperson that recited the Constitution on every
        # cycle would put it in every log and every console that renders a report.
        "constitution_in_force": constitution is not None,
        "constitution_version": constitution["version"] if constitution else None,
        "articles_in_force": articles is not None,
        "articles_version": articles["version"] if articles else None,
        "roll": articles["roll"] if articles else None,
        "open_resolutions": len(open_resolutions(conn)),
        "outstanding_owner_escalations": len(outstanding_escalations(conn)),
        # Named so nobody reads a working vote as a complete addendum 32.
        "not_built": ["elections", "ministers", "committees", "weekly_session"],
    }
