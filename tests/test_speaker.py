"""The Speaker of the Parliament (TQ-81; addendum 32 §10;
docs/SPEC_RECONCILIATION.md §124).

Owner direction, 2026-08-27: *"the agent should be reporting and not the
system."* Two properties carry that, and both are asserted structurally because
both have a convenient version that looks identical from outside:

1. The console renders **what the Speaker said** and never queries Parliament
   itself. The convenient version answers anyway when the Speaker is dead.
2. The Speaker reports and does not legislate. The convenient version lets a
   spokesperson that already has a database connection close a resolution.
"""

from __future__ import annotations

import inspect

import pytest

from agents import speaker
from backend import fi_db, main as backend_main, parliament, portfolios

OWNER = portfolios.for_superuser("krish")
ROLL = {"broad": ["coo", "explorer", "speculator", "analysis"],
        "representative": ["coo", "analysis"]}


@pytest.fixture
def governed(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    return conn


def test_the_speaker_files_a_report_carrying_its_own_name(governed):
    """A report with no author is a rumour."""
    speaker._speaker_work(governed, "speaker-1")
    spoken = parliament.latest_speaker_report(governed)
    assert spoken["speaker_identity"] == "speaker-1"
    assert spoken["filed_at"]
    assert spoken["report"]["articles_in_force"] is True


def test_a_report_needs_a_speaker(governed):
    with pytest.raises(parliament.ParliamentRefused):
        parliament.record_speaker_report(governed, speaker_identity="  ", report={})


def test_the_speaker_says_what_is_open_by_name_and_not_only_by_count(governed):
    """A count leaves a reader to infer which resolutions are outstanding. The
    Speaker's job is to say."""
    parliament.propose(governed, title="Structured requests", rationale="r",
                       proposed_by="coo", affects="knowledge")
    report = speaker.compose_report(governed)
    assert report["open_resolutions"] == 1
    assert report["open_resolution_titles"] == ["Structured requests"]


def test_the_speaker_reports_an_empty_parliament_as_ready_rather_than_broken(conn):
    """No Articles is a real state with a real explanation, and it is not the
    same as Parliament being absent."""
    report = speaker.compose_report(conn)
    assert report["articles_in_force"] is False
    assert "no Articles" in report["says"] and "cannot" not in report["says"].split(".")[0]


def test_the_speaker_names_what_is_still_unbuilt(governed):
    speaker._speaker_work(governed, "speaker-1")
    report = parliament.latest_speaker_report(governed)["report"]
    assert set(report["not_built"]) == {"elections", "ministers", "committees", "weekly_session"}
    assert "not built" in report["says"]


def test_the_speaker_says_when_a_matter_is_with_the_owner(governed):
    """The escalation queue is the one thing nothing inside the system can
    settle, so a Speaker that failed to mention it would be reporting the part of
    the state that is comfortable."""
    parliament.escalate(governed, summary="an attempt at the Constitution", raised_by="explorer")
    assert "with the owner" in speaker.compose_report(governed)["says"]


# --- the two structural properties ---------------------------------------------------

def test_the_speaker_cannot_legislate():
    """A spokesperson who can also vote is not reporting on a body, it is the
    body. Asserted over the source rather than by attempting each call, because
    the property is *absence of the capability*, not failure of one attempt."""
    source = inspect.getsource(speaker)
    for forbidden in ("propose", "propose_amendment", "cast_vote", "close(",
                      "withdraw", "adopt_genesis_articles", "escalate(",
                      "record_owner_decision"):
        assert f"parliament.{forbidden}" not in source, (
            f"the Speaker reaches parliament.{forbidden}")


def test_the_console_renders_the_speakers_report_and_never_queries_parliament():
    """The convenient version of `_parliament` calls `parliament.summary` when
    the Speaker has filed nothing. It would look correct on every console anyone
    ever opened, and it would be the system speaking for Parliament again - the
    exact thing this exists to replace."""
    source = inspect.getsource(backend_main._overview)
    assert "parliament.latest_speaker_report(conn)" in source
    for querying in ("parliament.summary(", "parliament.current_articles(",
                     "parliament.open_resolutions(", "parliament.tally("):
        assert querying not in source, f"the console queries Parliament directly: {querying}"


def test_a_console_with_no_speakers_report_says_so_rather_than_answering(conn):
    """Silence is information. Rendered as silence."""
    section = _parliament_section(conn)
    assert section["speaker_has_reported"] is False
    assert "has filed nothing" in section["reason"]
    assert "convened" not in section, "an unreported Parliament has no state to show"


def test_a_console_with_a_report_renders_it_with_its_age(governed):
    speaker._speaker_work(governed, "speaker-1")
    section = _parliament_section(governed)
    assert section["speaker_has_reported"] is True
    assert section["speaker"] == "speaker-1"
    assert section["as_of"]
    assert section["says"]
    assert section["convened"] is True


def _parliament_section(conn) -> dict:
    """Call the console's own `_parliament` closure with this connection.

    Reached through the source rather than reimplemented, so this tests the
    function the console actually serves."""
    return backend_main._overview(conn)["parliament"]


# --- the organization knows about it -------------------------------------------------

def test_the_speaker_is_a_declared_role_with_a_charter():
    charter = fi_db.ROLE_CHARTERS["speaker"]
    assert charter["agent_type"] == "spokesperson"
    assert any("not" in rule and "legislat" in rule for rule in charter["not_allowed"])


def test_the_speaker_answers_to_the_articles_and_not_to_an_officer():
    """`reports_to: null` is the claim; this is what makes it a claim rather than
    an omission. A spokesperson whose reports pass through the executive is a
    spokesperson for the executive."""
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "docs" / "organization.yaml").read_text(
        encoding="utf-8")
    block = re.search(r"  - id: speaker\n(.*?)\n\n", text, re.S).group(1)
    assert "reports_to: null" in block
    assert "watched_by: coo" in block, "somebody must still notice if it goes quiet"


# --- what the saturation run found (§128) --------------------------------------------

def test_an_unchanged_report_is_reaffirmed_rather_than_repeated(governed):
    """A three-hundred-second run produced three hundred speaker reports — a row
    a second to say nothing had changed.

    Two facts are worth keeping and they are not the same: when Parliament's
    state last *changed*, and when somebody last *checked*. Filing only on change
    loses the second, and a dead Speaker then looks like a quiet Parliament."""
    first = speaker._speaker_work(governed, "speaker-1")
    for _ in range(5):
        speaker._speaker_work(governed, "speaker-1")

    rows = governed.fetchall("SELECT id, filed_at, reaffirmed_at FROM speaker_reports")
    assert len(rows) == 1, "six identical looks produced six rows"
    assert rows[0]["reaffirmed_at"] >= rows[0]["filed_at"]


def test_a_changed_report_is_a_new_row(governed):
    """The counterpart. Squashing repeats must not squash history."""
    speaker._speaker_work(governed, "speaker-1")
    parliament.propose(governed, title="Something new", rationale="r",
                       proposed_by="coo", affects="knowledge")
    speaker._speaker_work(governed, "speaker-1")

    rows = governed.fetchall("SELECT report FROM speaker_reports ORDER BY id")
    assert len(rows) == 2
    assert rows[0]["report"] != rows[1]["report"]


def test_the_console_distinguishes_last_said_from_last_checked(governed):
    speaker._speaker_work(governed, "speaker-1")
    speaker._speaker_work(governed, "speaker-1")
    section = _parliament_section(governed)
    assert section["as_of"] and section["confirmed_at"]
    assert section["confirmed_at"] >= section["as_of"]
