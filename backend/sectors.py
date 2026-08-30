"""Sectors nobody is looking at, and why they are worth looking at
(docs/SPEC_RECONCILIATION.md §162).

Every other programme on this station reports the organization's own record: what
the Explorer detected, what the desk traded, what a department did. This one
reports on **subjects** - overlooked areas where low-cost, locally-buildable
technology delivers disproportionate benefit.

That is a different kind of claim and it needs the same rule. A story with no
source is something somebody made up, so the catalogue *is* the record: each
sector is a row, the programme quotes the row, and the story carries
`source_table='emerging_sectors'` like every other. **The station never
improvises a subject it has no entry for.**

## Curated now, researched later

The seed below is the owner's own list, entered as the organization's starting
view. It is deliberately a catalogue rather than a research agent: what Stage 1
needs is that the capability exists, is connected and can be exercised, and an
agent that discovers new sectors is Stage 3 work with a real dependency - nothing
here reads the outside world.

So `added_by` records who entered a sector, and `evidence_note` says plainly what
standing the entry has. The current entries are **premises worth investigating,
not findings**, and the column says so rather than letting a confident sentence
on air imply the organization has verified anything.

## Why these are not investment tips

The station reports the *case* for a sector - what it does, who it helps, why it
is overlooked. It does not price anything, recommend anything or connect a sector
to the desk's book. This system has no real prices (§113), and a programme that
drifted from "here is an overlooked idea" to "here is what to buy" would be
making a claim the organization cannot support.
"""

from __future__ import annotations

from backend.db import Database, now_iso

SCHEMA = """
-- An area the organization thinks is under-examined, and the case for it.
CREATE TABLE IF NOT EXISTS emerging_sectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    added_at TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    -- Roughly what field this sits in, so a programme can vary its subject
    -- rather than reading the same entry every day.
    field TEXT NOT NULL,
    -- What the thing actually is, in one sentence a presenter can read.
    premise TEXT NOT NULL,
    -- Who it helps and how. The reason the sector is on this list at all.
    benefit TEXT NOT NULL,
    -- Why it is overlooked, which is the part that makes it a story rather than
    -- a catalogue entry.
    why_overlooked TEXT NOT NULL,
    -- What standing this entry has. 'premise' means somebody thinks it is worth
    -- investigating and nothing here has verified it - stated in the row so a
    -- confident sentence on air cannot imply otherwise.
    evidence_note TEXT NOT NULL,
    added_by TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
"""

SCHEMA_VERSION = 1

# What standing an entry has. A closed vocabulary because the difference between
# a hunch and a finding is the whole of what makes the programme honest.
STANDING_PREMISE = "premise"
STANDING_INVESTIGATED = "investigated"
STANDINGS = (STANDING_PREMISE, STANDING_INVESTIGATED)

# The owner's list, entered as the organization's starting view (2026-08-30).
# Every one carries `premise` standing: these are areas somebody thinks are
# under-examined, and this system has investigated none of them.
SEED = (
    {
        "slug": "micro_hydro",
        "name": "Micro hydroelectric",
        "field": "distributed energy",
        "premise": "Small run-of-river turbines generating a few kilowatts for a "
                   "single household, farm or hamlet, built and maintained locally.",
        "benefit": "Continuous power where a grid connection is uneconomic, from a "
                   "resource that is already flowing past the door.",
        "why_overlooked": "Too small to interest utility-scale developers and too "
                          "unglamorous for energy coverage that follows capital.",
    },
    {
        "slug": "local_wind",
        "name": "Low-cost locally manufactured wind turbines",
        "field": "distributed energy",
        "premise": "Turbines built from locally available materials by local "
                   "workshops, sized for one building rather than for a farm.",
        "benefit": "Keeps both the power and the manufacturing in the community, so "
                   "the money and the repair skills stay put.",
        "why_overlooked": "The industry optimises for cost per megawatt, which is "
                          "the wrong measure entirely at this scale.",
    },
    {
        "slug": "solar_hot_water_storage",
        "name": "Outdoor solar water heating with insulated storage",
        "field": "thermal energy",
        "premise": "Heat water outdoors with sunlight, store it separately, and "
                   "insulate the store well enough that it is still hot when wanted.",
        "benefit": "Removes one of the largest electrical loads in a household "
                   "entirely, rather than making it more efficient.",
        "why_overlooked": "Storage is unfashionable next to generation, and the "
                          "engineering is insulation rather than electronics.",
    },
    {
        "slug": "evaporative_clay_cooling",
        "name": "Clay-pot refrigeration",
        "field": "food preservation",
        "premise": "Evaporative cooling in unglazed earthenware, keeping produce "
                   "usable for days with no power at all.",
        "benefit": "Cuts food waste where refrigeration is unaffordable or the "
                   "supply is intermittent.",
        "why_overlooked": "It is old, cheap and unpatentable, so nobody is funded "
                          "to improve it.",
    },
    {
        "slug": "underground_cellars",
        "name": "Underground cellars for long-term preservation",
        "field": "food preservation",
        "premise": "Using the stable temperature a few metres down to store food "
                   "for months without machinery.",
        "benefit": "Season-long storage with no running cost and nothing to fail.",
        "why_overlooked": "It is a building decision rather than a product, so no "
                          "supply chain advocates for it.",
    },
    {
        "slug": "passive_cooling_architecture",
        "name": "Architecture as air conditioning",
        "field": "built environment",
        "premise": "Orientation, thermal mass, shading and stack effect designed to "
                   "cool a building without a compressor.",
        "benefit": "Removes a load that grows exactly when the grid is most "
                   "stressed, for the cost of designing the building properly.",
        "why_overlooked": "The saving accrues to the occupant and the cost falls on "
                          "the builder, and those are rarely the same party.",
    },
    {
        "slug": "unpowered_extraction",
        "name": "Self-driven exhaust and ventilation",
        "field": "built environment",
        "premise": "Extractors driven by wind and by the temperature difference "
                   "they are removing, with no motor.",
        "benefit": "Ventilation that keeps working through a power cut, which is "
                   "when a building most needs it.",
        "why_overlooked": "Nothing is metered, so nothing is measured, so nothing "
                          "is sold.",
    },
)


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)
    for entry in SEED:
        conn.execute(
            "INSERT OR IGNORE INTO emerging_sectors (added_at, slug, name, field, premise,"
            " benefit, why_overlooked, evidence_note, added_by, schema_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now_iso(), entry["slug"], entry["name"], entry["field"], entry["premise"],
             entry["benefit"], entry["why_overlooked"], STANDING_PREMISE, "owner",
             SCHEMA_VERSION))


def add(conn: Database, *, slug: str, name: str, field: str, premise: str, benefit: str,
        why_overlooked: str, added_by: str,
        evidence_note: str = STANDING_PREMISE) -> int | None:
    """Enter a sector. Refuses an unknown standing rather than defaulting one.

    An entry whose standing nobody stated would be read on air with the same
    confidence as one that had been investigated, which is the difference this
    column exists to keep."""
    if evidence_note not in STANDINGS:
        raise ValueError(f"unknown standing {evidence_note!r}; known are {list(STANDINGS)}")
    if conn.fetchone("SELECT id FROM emerging_sectors WHERE slug = ?", (slug,)):
        return None
    return conn.execute_returning_id(
        "INSERT INTO emerging_sectors (added_at, slug, name, field, premise, benefit,"
        " why_overlooked, evidence_note, added_by, schema_version)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), slug, name, field, premise, benefit, why_overlooked, evidence_note,
         added_by, SCHEMA_VERSION))


def all_sectors(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM emerging_sectors ORDER BY id")


def fields(conn: Database) -> list[str]:
    return [row["field"] for row in conn.fetchall(
        "SELECT DISTINCT field FROM emerging_sectors ORDER BY field")]
