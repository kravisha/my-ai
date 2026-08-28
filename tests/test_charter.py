"""The charter, checked rather than read.

A charter is the easiest document in a governance system to write falsely. Every
clause sounds true when written, nothing checks it, and the gap between promise
and machinery opens silently. So the central test here resolves every mechanism
the charter names: a protection whose enforcement does not exist fails the suite.

That test has already earned itself once - the first draft claimed
`fi_db.retire_agent`, and the function is `request_retirement`.
"""

import importlib

import pytest

from backend import charter, competency, compliance, fi_db


def resolve(path: str):
    module_path, _, attribute = path.rpartition(".")
    return getattr(importlib.import_module(module_path), attribute)


# -- the charter cannot promise what does not exist ---------------------------

def test_every_enforced_protection_names_a_mechanism_that_exists():
    """The test that makes this a charter rather than a wish."""
    for protection in charter.enforced():
        assert protection.enforced_by, f"{protection.name!r} claims enforcement but names nothing"
        for path in protection.enforced_by:
            try:
                resolve(path)
            except (ImportError, AttributeError) as exc:
                pytest.fail(f"{protection.name!r} is enforced by {path}, which does not resolve: {exc}")


def test_a_protection_is_either_enforced_or_says_what_is_missing():
    """No third state. A protection with neither a mechanism nor a stated gap is
    the exact thing this file exists to prevent."""
    for protection in charter.PROTECTIONS:
        assert bool(protection.enforced_by) != bool(protection.aspirational), (
            f"{protection.name!r} must either name its enforcement or say what is missing"
        )


def test_unenforced_protections_are_counted():
    """A charter grows by promising, and promises are free."""
    assert len(charter.aspirational()) == charter.UNENFORCED_COUNT


def test_every_aspirational_protection_says_what_would_close_it():
    """Naming the gap is the difference between a deferred decision and an
    oversight nobody owns."""
    for protection in charter.aspirational():
        assert len(protection.aspirational) > 60, f"{protection.name!r} names no concrete gap"


# -- the protections that matter most, checked behaviourally ------------------

def test_no_agent_is_faulted_where_compliance_was_impossible():
    """The charter's first clause, and the one the evidence most demanded: every
    finding this organization has produced has been systemic."""
    from backend import remediation

    assert remediation.classify(findings=10, opportunities=10) == remediation.SYSTEMIC
    assert any(rule.blocked for rule in compliance.EVALUATION_RULES)


def test_declining_work_is_not_recorded_as_a_failure(conn):
    """A charter clause is worth nothing if the record still counts refusal
    against the refuser."""
    directive_id = fi_db.enqueue_directive(
        conn, directive_type="retire", requested_by="coo-1", target_identity="explorer-404",
    )
    fi_db.file_objection(
        conn, directive_id, filed_by="controller-1", ground="missing dependency",
        evidence="no such agent", remedy="spawn it first, or withdraw",
    )

    archived = conn.fetchone(
        "SELECT outcome FROM coo_directives_completed WHERE id = ?", (directive_id,)
    )
    assert archived["outcome"] == "objected" != "failure"


def test_a_quiet_agent_is_not_reported_as_a_poor_one():
    """'Not yet known' and 'poor' are different answers, and collapsing them
    would punish a new agent for being new."""
    thin = competency.profile({"grades": [{"overall_score": 0.9}]})
    stated = thin["dimensions"]["analytical_quality"]

    assert stated["stated"] is False
    assert stated["score"] is None, "a single grade produced a score"
    assert stated["reason"] == competency.UNSTATED_REASON
    assert thin["stated_dimensions"] == []


def test_recognition_cannot_reach_a_qualification_decision():
    """Enforced in the signature rather than by a convention someone has to
    remember. A rule enforced by convention has a decay rate."""
    assert "commendation" not in competency.evaluate_qualification.__code__.co_varnames


# -- the tripwire for the cover-up incentive ----------------------------------
#
# §28's asymmetry - self-reporting treated more favourably than concealment -
# cannot be built yet, because nothing an agent does affects its standing through
# a finding, so there is no leniency to grant. It also must not be forgotten,
# because it is cheap now and expensive once concealment already pays.
#
# So the charter records it as preventive and this test watches for the moment it
# becomes live.

# Tables that record something going wrong. If an agent's standing ever starts
# reading one of these, disclosure begins to cost something.
GOVERNANCE_TABLES = ("objections", "finding_dispositions")


def test_a_finding_cannot_reach_an_agents_standing():
    """The tripwire. If a finding ever starts affecting competence, rank or
    qualification, the incentive to conceal is created at that moment - and the
    self-report asymmetry has to exist before it, not after.

    Aimed at `competency_evidence`, which is the single gate: it is what gathers
    everything an agent is assessed on. Checked by the tables it reads rather
    than by words in the source, so it fires on a real wiring and not on a
    comment mentioning compliance.

    Deliberately a failing test rather than a note in a document. A note would be
    read once, by whoever wrote it."""
    import inspect

    source = inspect.getsource(fi_db.competency_evidence)
    for table in GOVERNANCE_TABLES:
        assert table not in source, (
            f"competency_evidence now reads {table!r}, so a finding can affect an agent's standing "
            "and concealing one now pays. Build the self-reporting asymmetry (charter protection "
            "'self-reporting is treated more favourably than concealment') before this ships, and "
            "update charter.UNENFORCED_COUNT."
        )


def test_declining_work_does_not_reduce_an_agents_session_count():
    """The cover-up incentive in miniature, and the reason the tripwire is
    needed rather than merely tidy.

    `competency_evidence` reads completed directives. If it counted anything
    other than success against an agent, G5's objections would already have made
    refusing costly - and an agent that learns refusing is costly stops refusing
    and starts failing quietly."""
    import inspect

    source = inspect.getsource(fi_db.competency_evidence)
    assert "outcome = 'success'" in source, "the directive query no longer filters on success alone"
    assert "'objected'" not in source and "'failure'" not in source, (
        "competency_evidence now distinguishes non-success directive outcomes; check that objecting "
        "has not become something an agent pays for"
    )


def test_the_cover_up_clause_is_recorded_as_preventive():
    """It is listed as unenforced with the reason, rather than omitted because it
    cannot be built yet. Omitting it is how a known hazard becomes a surprise."""
    clause = next(p for p in charter.PROTECTIONS if "self-reporting" in p.name)

    assert clause.aspirational
    assert "no consequence path exists" in clause.aspirational


def test_summarise_marks_the_unenforced_ones():
    """Derived from `UNENFORCED_COUNT` rather than repeating it. The literal `3`
    stood here until TQ-102 discharged one, and a number written in two places is
    one that eventually disagrees with itself - which in a charter would mean the
    summary claiming a promise was kept while the list still owed it."""
    text = charter.summarise()
    assert f"{charter.UNENFORCED_COUNT} not yet" in text
    assert text.count("missing:") == charter.UNENFORCED_COUNT


def test_appeal_is_enforced_and_notification_is_still_not():
    """TQ-102 moved one and deliberately left the other.

    **The right to appeal is enforced**: an agent can file, nobody can file on its
    behalf, and neither the author nor the appellant may hear it.

    **"An agent is told what is found about it" is not**, though the read path it
    needed now exists. Nothing in `agents/` consults it, and a function tested in
    isolation is not a function that runs (§134). Being told is passive from the
    agent's side in a way that having a right is not - so marking it enforced
    would be the charter claiming something the agent would not experience.

    Pinned as a pair because moving the count down is the easiest way to make a
    charter look better than it is."""
    appeal_clause = next(p for p in charter.PROTECTIONS if "appealed" in p.name)
    assert appeal_clause.enforced_by and not appeal_clause.aspirational
    assert "backend.appeal.hear" in appeal_clause.enforced_by

    told = next(p for p in charter.PROTECTIONS if "is told what is found" in p.name)
    assert told.aspirational and not told.enforced_by
    assert "nothing reads it" in told.aspirational


# -- duties ------------------------------------------------------------------

def test_every_duty_names_a_mechanism_that_exists():
    """Duties are held to the same standard as protections. An unenforced duty is
    a reprimand waiting for an occasion rather than a rule."""
    for duty in charter.DUTIES:
        assert duty.enforced_by, f"duty {duty.name!r} is not enforced by anything"
        assert not duty.aspirational, f"duty {duty.name!r} is aspirational; do not levy it yet"
        for path in duty.enforced_by:
            resolve(path)


def test_a_refusal_without_a_remedy_is_rejected(conn):
    """The manifesto's fifth principle as a duty, enforced at the point of
    refusal rather than asserted in a document."""
    directive_id = fi_db.enqueue_directive(
        conn, directive_type="retire", requested_by="coo-1", target_identity="explorer-404",
    )
    with pytest.raises(ValueError, match="remedy"):
        fi_db.file_objection(
            conn, directive_id, filed_by="controller-1", ground="missing dependency",
            evidence="no such agent", remedy="",
        )


def test_nothing_would_make_this_safe_is_an_acceptable_remedy(conn):
    """The bound on the duty. A system requiring every refusal to come with a way
    forward would have quietly abolished refusal."""
    directive_id = fi_db.enqueue_directive(
        conn, directive_type="retire", requested_by="coo-1", target_identity="explorer-404",
    )
    objection_id = fi_db.file_objection(
        conn, directive_id, filed_by="controller-1", ground="integrity or safety concern",
        evidence="executing this would destroy the record it is meant to correct",
        remedy="nothing would make this safe to perform",
    )
    assert fi_db.get_objection(conn, objection_id)["remedy"]
