"""Two halves of the queue-freshness fix: a stream that can develop, and a case
that stays current.

**The defect.** A report waits ~235s to be judged, and for that whole window the
producing agent could see the situation changing and had no way to say so - a
pending case blocked any further report about that security. So judgment ran on
a snapshot minutes old while newer observations sat unreferenced.

**Why the fixture came first.** Measured against the previous social stream,
every candidate signal for "materially new information" was noise: cycle-to-cycle
confidence delta had a p90 of 0.481 across a 0-1 range and the source set changed
on 85% of transitions. The cause was that the stream drew each cycle
independently, so it had no memory and nothing to find. An arc gives it a
direction.

**Why the fix needs no threshold.** Accumulation is unconditional. A case absorbs
whatever arrives while it waits, so nothing is silenced and no "materially
different" judgement has to be made. Only *priority elevation* needs a
discriminator, and that is deliberately not built here.
"""

import json

import pytest

from backend import fi_db
from providers.social_data import ARC_SHAPES, SyntheticSocialDataProvider


@pytest.fixture
def db(conn):
    fi_db.init_schema(conn)
    return conn


def file_case(conn, security="SYN1", producer="speculator-1", evidence_ids=(1, 2)) -> int:
    return fi_db.enqueue_report(
        conn, producer_identity=producer, producer_spawned_at="2026-08-17T00:00:00+00:00",
        report_type="social", security=security, summary="initial",
        evidence_ids=list(evidence_ids), judgment_confidence=0.62,
    )


# -- the stream can now develop ----------------------------------------------

class Stream:
    """Cycles a provider the way Speculator does, tracking a `since` cursor.

    Written as a cursor rather than by slicing the cumulative list, because
    slicing needs a running offset that is easy to reset by accident - which it
    was, making a second observation window re-count every post from the first
    and report a flat stream as though it had tripled."""

    def __init__(self, provider, security):
        self.provider, self.security, self.cursor = provider, security, None

    def cycles(self, count):
        batches = []
        for _ in range(count):
            new = self.provider.fetch_recent(self.security, since=self.cursor)
            if new:
                self.cursor = new[-1].posted_at
            batches.append(new)
        return batches


def observe(provider, security, cycles):
    return Stream(provider, security).cycles(cycles)


def summarise(batches):
    posts = [p for batch in batches for p in batch]
    return {
        "posts": len(posts),
        "mean_engagement": sum(p.engagement_score for p in posts) / len(posts) if posts else 0.0,
        "authors": len({p.author for p in posts}),
    }


def test_a_flat_stream_stays_flat():
    """The control. If the baseline drifted, an arc would prove nothing."""
    stream = Stream(SyntheticSocialDataProvider(seed=7), "SYN1")
    first = summarise(stream.cycles(30))
    second = summarise(stream.cycles(30))

    assert abs(second["mean_engagement"] - first["mean_engagement"]) < 0.15
    assert 0.5 < second["posts"] / first["posts"] < 2.0, (
        f"a flat stream changed volume from {first['posts']} to {second['posts']}"
    )


def test_an_escalating_arc_raises_volume_engagement_and_dispersion_together():
    """All three, because one alone would be indistinguishable from noise.

    Volume, engagement and the breadth of the crowd are separate observables, and
    a developing story moves all of them - which is what gives a detector
    something to find that a single noisy statistic could not provide."""
    provider = SyntheticSocialDataProvider(seed=7, arcs={"SYN1": ("escalating", 60)})
    early = summarise(observe(provider, "SYN1", 20))
    late = summarise(observe(provider, "SYN1", 40)[20:])

    assert late["posts"] > early["posts"]
    assert late["mean_engagement"] > early["mean_engagement"]
    assert late["authors"] > early["authors"]


def test_engagement_rises_without_saturating_at_one():
    """Intensity closes the gap toward 1.0 proportionally.

    An additive lift pushed high-base templates against the ceiling, flattening
    exactly the securities that were escalating hardest."""
    provider = SyntheticSocialDataProvider(seed=3, arcs={"SYN1": ("escalating", 40)})
    posts = [p for batch in observe(provider, "SYN1", 40) for p in batch]

    assert max(p.engagement_score for p in posts) <= 1.0
    assert len({p.engagement_score for p in posts}) > 5, "scores collapsed to a single clamped value"


def test_a_fading_arc_declines():
    provider = SyntheticSocialDataProvider(seed=7, arcs={"SYN1": ("fading", 60)})
    early = summarise(observe(provider, "SYN1", 20))
    late = summarise(observe(provider, "SYN1", 40)[20:])

    assert late["mean_engagement"] < early["mean_engagement"]


def test_a_spike_arc_subsides_rather_than_only_growing():
    """A detector must not pass by assuming everything escalates."""
    provider = SyntheticSocialDataProvider(seed=7, arcs={"SYN1": ("spike", 60)})
    batches = observe(provider, "SYN1", 60)
    middle = summarise(batches[20:35])
    end = summarise(batches[45:])

    assert end["mean_engagement"] < middle["mean_engagement"]


def test_an_arc_applies_only_to_its_own_security():
    """One developing story must not lift the whole universe.

    Asserted on intensity rather than on the resulting posts: all securities
    share one generator, so SYN1's extra draws do shift SYN2's sequence. That is
    a property of a single seeded RNG, not of the arc, and asserting the streams
    are byte-identical would be asserting something untrue."""
    provider = SyntheticSocialDataProvider(seed=7, arcs={"SYN1": ("escalating", 30)})
    for _ in range(30):
        provider.fetch_recent("SYN1")
        provider.fetch_recent("SYN2")

    assert provider._intensity("SYN1") == pytest.approx(1.0)
    assert provider._intensity("SYN2") == 0.0


def test_every_arc_shape_stays_within_zero_and_one():
    for name, shape in ARC_SHAPES.items():
        for step in range(0, 21):
            value = shape(step / 20)
            assert 0.0 <= value <= 1.0, f"{name} produced {value} at progress {step / 20}"


def test_a_silent_security_still_advances_through_its_arc():
    """Otherwise a stream that starts silent could never reach the part of its
    arc where it stops being silent."""
    provider = SyntheticSocialDataProvider(
        seed=7, narratives={"SYN1": "silent"}, arcs={"SYN1": ("escalating", 10)}
    )
    for _ in range(10):
        provider.fetch_recent("SYN1")
    assert provider._intensity("SYN1") == pytest.approx(1.0)


# -- a pending case stays current --------------------------------------------

def test_new_evidence_enriches_a_waiting_case(db):
    report_id = file_case(db, evidence_ids=[1, 2])

    assert fi_db.enrich_case(db, report_id, [3, 4], judgment_confidence=0.88) == "enriched"

    row = db.fetchone("SELECT evidence_ids, judgment_confidence, updated_at FROM discovery_reports WHERE id = ?", (report_id,))
    assert json.loads(row["evidence_ids"]) == [1, 2, 3, 4]
    assert row["judgment_confidence"] == 0.88
    assert row["updated_at"] is not None


def test_evidence_order_is_preserved_because_the_sequence_is_the_information(db):
    """'chatter broadening across three channels over four minutes' and the same
    observations shuffled are different findings."""
    report_id = file_case(db, evidence_ids=[1])
    fi_db.enrich_case(db, report_id, [2])
    fi_db.enrich_case(db, report_id, [3])

    stored = json.loads(db.fetchone("SELECT evidence_ids FROM discovery_reports WHERE id = ?", (report_id,))["evidence_ids"])
    assert stored == [1, 2, 3]


def test_duplicate_evidence_cannot_inflate_a_case(db):
    report_id = file_case(db, evidence_ids=[1, 2])
    fi_db.enrich_case(db, report_id, [2, 3])

    stored = json.loads(db.fetchone("SELECT evidence_ids FROM discovery_reports WHERE id = ?", (report_id,))["evidence_ids"])
    assert stored == [1, 2, 3]


def test_a_claimed_case_is_not_changed_under_its_judge(db):
    """§6: a claimed case belongs to its judge.

    Changing it mid-analysis wastes an expensive model call and judges a target
    that moved."""
    report_id = file_case(db, evidence_ids=[1])
    fi_db.claim_next_report(db, "analysis-1", "spawn-1")

    assert fi_db.enrich_case(db, report_id, [2]) == "deferred"

    row = db.fetchone("SELECT evidence_ids, deferred_evidence_ids FROM discovery_reports WHERE id = ?", (report_id,))
    assert json.loads(row["evidence_ids"]) == [1], "the judge's evidence set changed"
    assert json.loads(row["deferred_evidence_ids"]) == [2]


def test_deferred_evidence_accumulates_for_follow_up(db):
    report_id = file_case(db, evidence_ids=[1])
    fi_db.claim_next_report(db, "analysis-1", "spawn-1")
    fi_db.enrich_case(db, report_id, [2])
    fi_db.enrich_case(db, report_id, [3])

    row = db.fetchone("SELECT deferred_evidence_ids FROM discovery_reports WHERE id = ?", (report_id,))
    assert json.loads(row["deferred_evidence_ids"]) == [2, 3]


def test_enriching_a_completed_case_reports_it_gone(db):
    """So the caller files a fresh case rather than silently losing the evidence."""
    report_id = file_case(db)
    fi_db.complete_report(db, report_id, "analyzed")

    assert fi_db.enrich_case(db, report_id, [9]) == "gone"


def test_accumulation_does_not_raise_the_queue_depth_ceiling(db):
    """The bound that keeps this system predictable is one case per security.

    Enrichment must keep it - if a developing story produced a new case per
    cycle instead, the queue would grow without limit."""
    report_id = file_case(db)
    for batch in ([2], [3], [4]):
        fi_db.enrich_case(db, report_id, batch)

    assert db.fetchone("SELECT COUNT(*) AS n FROM discovery_reports")["n"] == 1


def test_observations_survive_regardless_of_what_happens_to_the_case(db):
    """A case is a request for judgment, not a record of observation.

    Enriching, deferring or completing a case touches nothing in evidence_items,
    which is what makes keeping the case current safe."""
    for _ in range(3):
        fi_db.record_evidence_item(
            db, "speculator-1", "2026-08-17T00:00:00+00:00", "social", "SYN1",
            source="reddit", observed_at="2026-08-17T00:00:00+00:00", content="c", confidence=0.5,
        )
    report_id = file_case(db, evidence_ids=[1])
    fi_db.enrich_case(db, report_id, [2, 3])
    fi_db.complete_report(db, report_id, "analyzed")

    assert db.fetchone("SELECT COUNT(*) AS n FROM evidence_items")["n"] == 3


def test_open_case_for_finds_a_claimed_case_too(db):
    """A claimed case is still that security's open case - the producer must not
    conclude there is none and file a duplicate."""
    file_case(db)
    fi_db.claim_next_report(db, "analysis-1", "spawn-1")

    assert fi_db.open_case_for(db, "speculator-1", "SYN1") is not None


# -- the judge's prompt stays bounded -----------------------------------------

def evidence_series(count, start=0.6, end=0.95):
    """Synthetic evidence rising steadily, oldest first."""
    return [
        {
            "confidence": round(start + (end - start) * (i / max(1, count - 1)), 3),
            "source": "reddit",
            "content": f"post {i}",
            "observed_at": f"2026-08-17T00:{i // 60:02d}:{i % 60:02d}+00:00",
        }
        for i in range(count)
    ]


def test_a_short_case_is_shown_verbatim(db):
    from agents import analysis

    lines = analysis._evidence_lines(db, evidence_series(5))
    assert len(lines) == 5
    assert all("confidence" in line for line in lines)
    assert not any("timeline" in line for line in lines)


def test_a_long_case_is_summarised_as_a_timeline(db):
    from agents import analysis

    lines = analysis._evidence_lines(db, evidence_series(400))
    assert any("summarised as a timeline" in line for line in lines)
    assert any("most recent" in line for line in lines)


def test_the_prompt_stays_bounded_however_much_the_case_accumulates(db):
    """Regression for a defect this change introduced.

    A case carrying 1,023 observations produced a 40,114-token prompt against
    the ~490 a single-snapshot case used - eighty times the cost per judgment,
    growing for as long as the case waited."""
    from agents import analysis

    small = "\n".join(analysis._evidence_lines(db, evidence_series(50)))
    huge = "\n".join(analysis._evidence_lines(db, evidence_series(5000)))

    assert len(huge) < 3 * len(small), (
        f"a 100x larger case produced a {len(huge) / len(small):.1f}x larger prompt"
    )
    assert len(huge) < 4000


def test_the_digest_preserves_the_direction_of_travel(db):
    """The shape is the finding.

    Confidence rising from 0.6 to 0.95 across broadening sources is a different
    claim from a flat 0.95, so a digest that sampled at random or kept only the
    tail would discard the thing worth judging."""
    from agents import analysis

    lines = analysis._evidence_lines(db, evidence_series(600, start=0.4, end=0.95))
    means = [
        float(line.split("confidence mean ")[1].split()[0])
        for line in lines if "confidence mean " in line
    ]

    assert len(means) >= 5
    assert means == sorted(means), f"the digest lost the rising trajectory: {means}"
    assert means[-1] - means[0] > 0.2


def test_the_most_recent_observations_stay_verbatim(db):
    """A judgment mostly rests on the current state, so the tail is not summarised."""
    from agents import analysis

    lines = analysis._evidence_lines(db, evidence_series(300))
    tail = lines[lines.index(next(l for l in lines if "most recent" in l)) + 1:]

    assert len(tail) == analysis.DIGEST_RECENT_VERBATIM
    assert "post 299" in tail[-1]
