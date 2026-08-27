"""The rest of the organization reads what governs it (TQ-87; addendum 46 §3;
docs/SPEC_RECONCILIATION.md §126, §127).

TQ-86 wired one code path. This wires the ones the working agents actually use —
Explorer and Speculator filing discovery reports — and adds the obligation kind
that behaviour needs.

The tripwire at the end is the part that keeps it wired. A filing site that
stopped naming its filer would be ungoverned again, silently, and the suite would
stay green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend import (fi_db, governed_knowledge as governed,
                     operating_context as context, parliament, portfolios)

ROOT = Path(__file__).resolve().parents[1]
OWNER = portfolios.for_superuser("krish")
ROLL = {"broad": ["coo", "explorer", "speculator", "analysis"],
        "representative": ["coo", "analysis"]}


@pytest.fixture
def governed_conn(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    return conn


def _enact(conn, level: str, title: str = "A resolution") -> int:
    resolution = parliament.propose(conn, title=title, rationale="r",
                                    proposed_by="coo", affects=level)
    tier = parliament.get_resolution(conn, resolution)["tier"]
    for voter in ROLL["representative" if tier == parliament.TIER_REPRESENTATIVE else "broad"]:
        parliament.cast_vote(conn, resolution, voter=voter, value="for")
    parliament.close(conn, resolution)
    return resolution


def _file(conn, role="speculator", **overrides):
    payload = {"summary": "A lead.", "evidence_ids": [1, 2],
               "judgment_confidence": 0.8, "filed_by": role}
    payload.update(overrides)
    return fi_db.enqueue_report(conn, f"{role}-1", "2026-01-01T00:00:00+00:00",
                                role, "SYN1", **payload)


# --- a rule the working agents obey -------------------------------------------------

def test_a_vote_changes_what_a_report_must_carry(governed_conn):
    """The same demonstration as TQ-86's, on the path the discovery agents
    actually use. Nothing in `enqueue_report` differs between the halves."""
    assert _file(governed_conn, evidence_ids=[])

    governed.adopt(
        governed_conn, subject=fi_db.REPORT_SUBJECT, level="organization_policy",
        text="No lead is filed on fewer than two pieces of evidence.", adopted_by="coo",
        resolution_id=_enact(governed_conn, "organization_policy"), binds="*",
        requires={"kind": "minimum_count", "field": "evidence_ids", "at_least": 2})

    with pytest.raises(fi_db.GovernedRefusal) as refusal:
        _file(governed_conn, evidence_ids=[7])
    assert "has 1, needs 2" in str(refusal.value)

    assert _file(governed_conn, evidence_ids=[7, 8])


def test_a_refused_filing_has_its_own_type(governed_conn):
    """*"The organization said no"* is a different thing from a malformed
    argument, and an agent that wants to respond differently to the two needs
    them to be distinguishable."""
    governed.adopt(
        governed_conn, subject=fi_db.REPORT_SUBJECT, level="organization_policy",
        text="Two pieces of evidence.", adopted_by="coo",
        resolution_id=_enact(governed_conn, "organization_policy"), binds="*",
        requires={"kind": "minimum_count", "field": "evidence_ids", "at_least": 2})
    with pytest.raises(fi_db.GovernedRefusal):
        _file(governed_conn, evidence_ids=[])
    assert issubclass(fi_db.GovernedRefusal, ValueError), "existing callers still catch it"


def test_the_report_records_what_it_was_filed_under(governed_conn):
    item = governed.adopt(
        governed_conn, subject=fi_db.REPORT_SUBJECT, level="organization_policy",
        text="A summary is required.", adopted_by="coo",
        resolution_id=_enact(governed_conn, "organization_policy"), binds="*",
        requires={"kind": "required_fields", "fields": ["summary"]})
    report = _file(governed_conn)
    row = governed_conn.fetchone(
        "SELECT governed_by FROM discovery_reports WHERE id = ?", (report,))
    assert row["governed_by"] == str(item)


def test_an_instrument_binding_one_agent_leaves_the_other_alone(governed_conn):
    """A department policy that bound everybody would be a law, and the store
    cannot tell them apart — so `binds` has to actually bind."""
    governed.adopt(
        governed_conn, subject=fi_db.REPORT_SUBJECT, level="department_policy",
        text="Speculator leads carry two pieces of evidence.", adopted_by="coo",
        resolution_id=_enact(governed_conn, "department_policy"), binds="speculator",
        requires={"kind": "minimum_count", "field": "evidence_ids", "at_least": 2})

    with pytest.raises(fi_db.GovernedRefusal):
        _file(governed_conn, role="speculator", evidence_ids=[])
    assert _file(governed_conn, role="explorer", evidence_ids=[])


# --- the obligation kind ------------------------------------------------------------

def test_a_minimum_of_zero_is_not_a_rule(governed_conn):
    for bad in ({"kind": "minimum_count", "field": "evidence_ids", "at_least": 0},
                {"kind": "minimum_count", "field": "evidence_ids", "at_least": True},
                {"kind": "minimum_count", "field": "", "at_least": 2},
                {"kind": "minimum_count", "at_least": 2}):
        with pytest.raises(governed.AdoptionRefused):
            governed.adopt(governed_conn, subject=fi_db.REPORT_SUBJECT,
                           level="organization_policy", text="t", adopted_by="coo",
                           resolution_id=_enact(governed_conn, "organization_policy",
                                                title=f"r{bad}"),
                           binds="*", requires=bad)


def test_a_stated_confidence_of_zero_counts_as_stated(governed_conn):
    """The regression the second consumer found.

    `RequiredFields` first asked whether `str(value or "").strip()` was empty,
    which was right for the one caller it had. A report with
    `judgment_confidence=0.0` has stated its confidence, and would have been
    refused for not stating it — a rule written against one example, wrong the
    moment a second arrived."""
    governed.adopt(
        governed_conn, subject=fi_db.REPORT_SUBJECT, level="organization_policy",
        text="Every report states a confidence.", adopted_by="coo",
        resolution_id=_enact(governed_conn, "organization_policy"), binds="*",
        requires={"kind": "required_fields", "fields": ["judgment_confidence"]})

    assert _file(governed_conn, judgment_confidence=0.0)
    with pytest.raises(fi_db.GovernedRefusal):
        _file(governed_conn, judgment_confidence=None)


def test_an_empty_list_is_still_absent(governed_conn):
    """Present-but-empty is not present. The counterpart to the rule above, so
    fixing one did not break the other."""
    governed.adopt(
        governed_conn, subject=fi_db.REPORT_SUBJECT, level="organization_policy",
        text="Every report carries evidence.", adopted_by="coo",
        resolution_id=_enact(governed_conn, "organization_policy"), binds="*",
        requires={"kind": "required_fields", "fields": ["evidence_ids"]})
    with pytest.raises(fi_db.GovernedRefusal):
        _file(governed_conn, evidence_ids=[])


# --- the tripwire that keeps it wired -----------------------------------------------

# The names that file something the organization may govern. `_file_lead` is the
# agents' wrapper around `enqueue_report`; it is on the list because it is the
# call a future filing site will copy, and its own forwarding call is exempted
# below rather than by leaving it off.
GOVERNED_CALLS = {"enqueue_report": "filed_by", "file_entry": "filed_by",
                  "_file_lead": "filed_by"}
SITES = ("agents", "backend/main.py", "gateway")


def _call_sites():
    for target in SITES:
        path = ROOT / target
        files = path.rglob("*.py") if path.is_dir() else [path]
        for source_file in files:
            tree = ast.parse(source_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name in GOVERNED_CALLS:
                    yield source_file, node, GOVERNED_CALLS[name]


def test_every_filing_site_names_its_filer():
    """The guarantee TQ-87 actually buys.

    `filed_by` is optional in the signature so that fixtures filing a report to
    set up some other test do not all have to change. That convenience is exactly
    how a real filing site loses its filer later, becomes ungoverned, and leaves
    the suite green — so the requirement lives here instead of in the signature.

    A site that genuinely should file ungoverned belongs on an explicit exception
    list with a reason, not omitted quietly."""
    ungoverned = []
    for source_file, node, keyword in _call_sites():
        if any(kw.arg is None for kw in node.keywords):
            # A wrapper forwarding `**fields` cannot be judged here - whatever it
            # was handed is what goes through. Its own callers are on this list,
            # which is where the filer either exists or does not.
            continue
        if not any(kw.arg == keyword for kw in node.keywords):
            ungoverned.append(f"{source_file.relative_to(ROOT)}:{node.lineno}")
    assert not ungoverned, (
        f"filing sites that name no filer, and are therefore governed by nothing: {ungoverned}")


def test_the_tripwire_is_looking_at_something():
    """A scanner that found no call sites would pass this file for the wrong
    reason and keep passing after somebody moved the code."""
    sites = list(_call_sites())
    assert len(sites) >= 4
    # And at least one of them is a real filing site rather than only wrappers,
    # so a refactor that hid every call behind forwarding would not empty this
    # test while leaving it green.
    assert any(any(kw.arg == keyword for kw in node.keywords)
               for _, node, keyword in sites)


# --- a rule obeyed must not look like a fault ----------------------------------------

def test_an_agent_treats_a_refusal_as_a_decision_rather_than_a_crash():
    """Found by asking what happens when this runs, not by a failing test.

    `enqueue_report` now raises inside a live agent's cycle. `agents/base.py`
    catches everything, so the agent survives - and prints it as a `work_fn
    error`, which is true of a broken agent and false of one obeying the
    organization. Anything reading the error stream would learn the wrong thing,
    and **an organization whose policies make its agents appear broken will have
    its policies removed by whoever is watching that stream.**
    """
    import inspect
    from agents import base, explorer, speculator

    for module in (explorer, speculator):
        source = inspect.getsource(module._file_lead)
        assert "except fi_db.GovernedRefusal" in source
        assert "note_governed_refusal" in source

    notice = inspect.getsource(base.note_governed_refusal)
    assert "error" not in notice.split('"""')[2], "a refusal is not reported as an error"


def test_the_cycle_continues_after_a_refusal(governed_conn, capsys):
    """The rest of the agent's work is not the organization's to stop."""
    from agents import speculator
    governed.adopt(
        governed_conn, subject=fi_db.REPORT_SUBJECT, level="organization_policy",
        text="Two pieces of evidence.", adopted_by="coo",
        resolution_id=_enact(governed_conn, "organization_policy"), binds="*",
        requires={"kind": "minimum_count", "field": "evidence_ids", "at_least": 2})

    filed = speculator._file_lead(
        governed_conn, "speculator-1", "2026-01-01T00:00:00+00:00", "speculator", "SYN1",
        summary="A lead.", evidence_ids=[], judgment_confidence=0.5, filed_by="speculator")

    assert filed is None, "nothing was filed"
    said = capsys.readouterr().out
    assert "not filed" in said and "instrument in force" in said
