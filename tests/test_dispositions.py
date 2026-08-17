"""What the organization decided about a compliance finding.

G3 was queued as "violation and evidence schema". Checking the premise moved it:
**a violation is recomputable and a judgment is not.** The compliance check
derives findings from live records whenever asked, so storing one would duplicate
state that goes stale - a stored "report 42 is ungraded" row survives report 42
being graded. What cannot be recomputed is that somebody looked at a finding and
decided it was the check's own false positive.

So findings stay computed and dispositions get the table. The consequence worth
naming: there is no 'fixed' disposition, because fixed work stops being found.

The danger the design guards against is that `false_positive` becomes a
universal off switch. Dispositions therefore hide nothing - the check keeps
reporting every finding and marks the ones ruled on.
"""

import pytest

from backend import compliance, fi_db, governance

RULE = "discovery report (analysed)"


def rule_out(conn, item=1, disposition=fi_db.FALSE_POSITIVE, rationale="the rule follows the "
             "carrying report, which was graded", by="owner"):
    return fi_db.record_disposition(
        conn, rule=RULE, item=item, disposition=disposition,
        rationale=rationale, decided_by=by,
    )


# -- recording a judgment -----------------------------------------------------

def test_a_disposition_must_be_one_of_the_known_kinds(conn):
    with pytest.raises(ValueError, match="unknown disposition"):
        rule_out(conn, disposition="ignore_this_one")


def test_a_disposition_must_carry_a_rationale(conn):
    """Ruling a finding out without saying why is how a compliance check stops
    covering things while still passing."""
    with pytest.raises(ValueError, match="rationale"):
        rule_out(conn, rationale="   ")


def test_there_is_no_fixed_disposition():
    """Fixed work stops being found, so resolution needs no record. A 'fixed'
    disposition would be a claim about the records that the records already
    answer, and the two could disagree."""
    assert "fixed" not in fi_db.DISPOSITIONS
    assert "resolved" not in fi_db.DISPOSITIONS


def test_the_active_ruling_is_the_one_returned(conn):
    rule_out(conn, item=7, rationale="the carrying report was graded after all")
    assert fi_db.get_disposition(conn, RULE, 7)["disposition"] == fi_db.FALSE_POSITIVE


def test_an_unruled_finding_has_no_disposition(conn):
    assert fi_db.get_disposition(conn, RULE, 999) is None


# -- changing your mind leaves a record --------------------------------------

def test_a_new_ruling_supersedes_rather_than_overwrites(conn):
    """The knowledge_records pattern. A finding ruled a false positive and later
    accepted is a different story from one always accepted, and only the history
    distinguishes them."""
    first = rule_out(conn, item=3, rationale="believed to be the check misreading the rule")
    second = rule_out(conn, item=3, disposition=fi_db.ACCEPTED,
                      rationale="on review the report really was never graded")

    history = fi_db.disposition_history(conn, RULE, 3)

    assert [row["id"] for row in history] == [first, second]
    assert history[0]["status"] == "superseded"
    assert history[0]["superseded_by"] == second
    assert fi_db.get_disposition(conn, RULE, 3)["disposition"] == fi_db.ACCEPTED


def test_superseded_rulings_stay_readable(conn):
    rule_out(conn, item=4, rationale="first call, later revised")
    rule_out(conn, item=4, disposition=fi_db.WONT_FIX, rationale="real, and not worth fixing")

    assert len(fi_db.list_dispositions(conn, include_superseded=True)) == 2
    assert len(fi_db.list_dispositions(conn)) == 1


# -- a disposition marks a finding; it never hides one ------------------------

def test_a_dispositioned_finding_is_still_reported(conn):
    """The load-bearing property. If ruling on a finding made it disappear,
    'false positive' would be a universal off switch and the check would report
    clean while covering nothing."""
    report_id = _ungraded_report(conn)
    assert compliance.check(conn)["unevaluated"], "fixture produced no finding to rule on"

    fi_db.record_disposition(
        conn, rule=RULE, item=report_id, disposition=fi_db.WONT_FIX,
        rationale="the producing agent is retired and the work will not be redone",
        decided_by="owner",
    )
    after = compliance.check(conn)

    assert after["unevaluated"], "the finding vanished when it was ruled on"
    assert after["unevaluated"][0]["disposition"] == fi_db.WONT_FIX


def test_open_findings_exclude_ruled_ones_while_the_total_does_not(conn):
    """Two numbers because they answer different questions: what still needs a
    decision, and what the check found at all."""
    report_id = _ungraded_report(conn)
    before = compliance.check(conn)
    assert before["open_findings"] == 1 and before["dispositioned"] == 0

    fi_db.record_disposition(
        conn, rule=RULE, item=report_id, disposition=fi_db.ACCEPTED,
        rationale="real violation, corrective work queued", decided_by="owner",
    )
    after = compliance.check(conn)

    assert after["open_findings"] == 0
    assert after["dispositioned"] == 1
    assert after["total_findings"] == before["total_findings"]


def test_a_ruling_on_one_item_does_not_cover_another(conn):
    """Dispositions are per finding, never blanket. A rule-wide off switch is
    what `exempt` is for, and that is pinned by a count."""
    first = _ungraded_report(conn)
    _ungraded_report(conn)

    fi_db.record_disposition(
        conn, rule=RULE, item=first, disposition=fi_db.FALSE_POSITIVE,
        rationale="this particular report was graded under a superseded id", decided_by="owner",
    )

    assert compliance.check(conn)["open_findings"] == 1


# -- the guard on the guard ---------------------------------------------------

def test_thin_rationales_are_reported_as_a_concern(conn):
    """A required field satisfied by a single word is a required field in name
    only, and that is how a governance record becomes unauditable without ever
    being empty."""
    rule_out(conn, item=11, rationale="nope")

    assert governance.disposition_health(conn)["thin_rationales"] == 1
    assert any("too short to review" in c for c in governance.concerns(conn))


def test_a_reasoned_rationale_raises_no_concern(conn):
    """The control, without which the test above would pass on a function that
    complained about every rationale."""
    rule_out(conn, item=12, rationale="the cross-check was carried into report 88, which was "
             "graded by analysis-1 on the same cycle")

    assert governance.disposition_health(conn)["thin_rationales"] == 0
    assert not any("too short to review" in c for c in governance.concerns(conn))


def test_the_false_positive_share_is_reported_without_a_threshold(conn):
    """A check finding real problems and a check that is badly written both
    produce false positives, and telling them apart needs the rationales read -
    which is a person's job."""
    rule_out(conn, item=20, rationale="the rule looked for a grade keyed directly to the item")
    rule_out(conn, item=21, disposition=fi_db.ACCEPTED,
             rationale="genuinely never graded, corrective work queued")

    health = governance.disposition_health(conn)

    assert health["false_positive_share"] == 0.5
    assert not any("false positive" in c.lower() for c in governance.concerns(conn))


def test_revisions_are_counted(conn):
    rule_out(conn, item=30, rationale="first assessment, since revised")
    rule_out(conn, item=30, disposition=fi_db.ACCEPTED, rationale="second assessment on review")

    assert governance.disposition_health(conn)["revised"] == 1


def test_disposition_health_is_empty_before_anything_is_ruled(conn):
    health = governance.disposition_health(conn)
    assert health["total"] == 0
    assert health["false_positive_share"] is None


# -- helpers ------------------------------------------------------------------

_next_id = iter(range(1000, 2000))


def _ungraded_report(conn) -> int:
    """A completed, analysed report that nobody graded - the shape the first
    evaluation rule looks for. Inserted directly, as tests/test_compliance.py
    does, because the point is the record's shape rather than the path to it."""
    report_id = next(_next_id)
    conn.execute(
        "INSERT INTO discovery_reports_completed (id, created_at, producer_identity, "
        "producer_spawned_at, report_type, security, summary, completed_at, outcome, "
        "schema_version) VALUES (?, '2026-08-17T00:00:00+00:00', 'speculator-1', "
        "'2026-08-17T00:00:00+00:00', 'social', 'SYN1', 's', '2026-08-17T00:01:00+00:00', "
        "'analyzed', 1)",
        (report_id,),
    )
    return report_id
