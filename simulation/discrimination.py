"""Can the system tell a developing situation from ordinary noise?

The question priority elevation depends on. A case that absorbs new evidence
needs no discriminator - accumulation is unconditional - but *elevating* one
above another means asserting that something changed materially, and that
assertion has to be defensible.

Measured once already against the memoryless social stream, where every
candidate signal was noise: cycle-to-cycle confidence delta had a p90 of 0.481
across a 0-1 range and the source set changed on 85% of transitions. That was a
property of the fixture, not an answer about the signal, because a stream redrawn
independently each cycle has nothing to find. This measures against a stream that
can actually develop.

**Framed to be capable of returning no.** The test is not "can a threshold be
found" - with enough statistics and window sizes one always can. It is whether a
statistic's distribution on securities that are *not* developing is separated from
its distribution on securities that are, at a window short enough to be useful.
Reporting a discriminator that only works at a 40-cycle window would be reporting
one that notices a situation long after it mattered.

Nothing here sets a threshold. It reports separation and leaves the choice to be
made against the numbers.
"""

from __future__ import annotations

import statistics
from collections import defaultdict


# Statistics that could plausibly move when a situation develops, each computed
# over a window of cycles rather than a single one. Single-cycle comparisons were
# already measured as useless, and an arc is a slow trajectory by design - a
# statistic asked to detect it one cycle at a time is being asked to see a
# gradient through noise several times its size.
STATISTICS = ("mean_confidence", "max_confidence", "post_count", "distinct_authors")

# Window sizes in cycles. 1 is kept deliberately, as the control that reproduces
# the original negative result.
WINDOWS = (1, 5, 10, 20, 40)


def _author_of(raw_ref: str | None) -> str:
    """Speculator stores 'source:author:posted_at' in raw_ref."""
    parts = (raw_ref or "").split(":")
    return parts[1] if len(parts) > 2 else ""


def cycle_series(conn) -> dict[str, list[dict]]:
    """Per-security, per-cycle observations, oldest first.

    A cycle is one second of `created_at`, which is how Speculator's loop lands -
    the synthetic `observed_at` runs on its own faster clock and would group
    several cycles together."""
    rows = conn.fetchall(
        "SELECT created_at, security, confidence, raw_ref FROM evidence_items ORDER BY created_at, id"
    )

    buckets: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        buckets[row["security"]][row["created_at"][:19]].append(row)

    series = {}
    for security, cycles in buckets.items():
        series[security] = [
            {
                "mean_confidence": statistics.mean(r["confidence"] for r in items),
                "max_confidence": max(r["confidence"] for r in items),
                "post_count": float(len(items)),
                "distinct_authors": float(len({_author_of(r["raw_ref"]) for r in items})),
            }
            for _, items in sorted(cycles.items())
        ]
    return series


def windowed_deltas(series: list[dict], statistic: str, window: int) -> list[float]:
    """Absolute change in a statistic between consecutive non-overlapping windows.

    Non-overlapping on purpose: overlapping windows share observations, so their
    deltas are correlated and a distribution built from them would look tighter
    than the evidence supports."""
    values = []
    for start in range(0, len(series) - window + 1, window):
        chunk = series[start:start + window]
        values.append(statistics.mean(point[statistic] for point in chunk))
    return [abs(b - a) for a, b in zip(values, values[1:])]


def measure(conn, developing: set[str]) -> list[dict]:
    """Separation between developing and flat securities, per statistic and window.

    `developing` names the securities given an arc - ground truth the system is
    never told, supplied here only to score the measurement.

    `signal_above_noise` is the fraction of a developing security's window-to-
    window changes that exceed the 95th percentile of the same statistic measured
    on securities that are not developing. It is the number that matters: a
    discriminator is usable when most real developments clear the bar that
    ordinary variation almost never clears."""
    series = cycle_series(conn)
    flat = {s: points for s, points in series.items() if s not in developing}
    arced = {s: points for s, points in series.items() if s in developing}
    if not flat or not arced:
        raise ValueError("need both developing and flat securities to measure separation")

    results = []
    for statistic in STATISTICS:
        for window in WINDOWS:
            noise = [d for points in flat.values() for d in windowed_deltas(points, statistic, window)]
            signal = [d for points in arced.values() for d in windowed_deltas(points, statistic, window)]
            if len(noise) < 5 or not signal:
                continue
            bar = sorted(noise)[int(0.95 * (len(noise) - 1))]
            results.append({
                "statistic": statistic,
                "window": window,
                "noise_median": round(statistics.median(noise), 4),
                "noise_p95": round(bar, 4),
                "signal_median": round(statistics.median(signal), 4),
                "signal_above_noise": round(sum(1 for d in signal if d > bar) / len(signal), 3),
                "samples": f"{len(noise)}/{len(signal)}",
            })
    return results


def level_separation(conn, developing: set[str]) -> list[dict]:
    """The other question: not how much a statistic *moved*, but where it *sits*.

    A trajectory is slow, so a developing security may never show a large change
    between windows while still ending up somewhere ordinary securities never
    reach. That is a different discriminator - a level, not a delta - and it is
    cheaper to compute, needing no history beyond the current window."""
    series = cycle_series(conn)
    results = []
    for statistic in STATISTICS:
        flat_levels, arc_late = [], []
        for security, points in series.items():
            if not points:
                continue
            tail = points[len(points) // 2:]
            level = statistics.mean(p[statistic] for p in tail)
            (arc_late if security in developing else flat_levels).append((security, level))
        if not flat_levels or not arc_late:
            continue
        bar = max(level for _, level in flat_levels)
        results.append({
            "statistic": statistic,
            "flat_max_level": round(bar, 4),
            "flat_levels": {s: round(v, 3) for s, v in sorted(flat_levels)},
            "developing_levels": {s: round(v, 3) for s, v in sorted(arc_late)},
            "developing_above_every_flat": sum(1 for _, v in arc_late if v > bar),
            "developing_count": len(arc_late),
        })
    return results


def peer_outlier_scores(conn, statistic: str = "post_count") -> list[dict]:
    """How far each security sits from its peers, in robust deviations.

    **The result that removes the need for a threshold.** Flat securities cluster
    tightly - measured at 1.875 to 2.064 posts per cycle - while a developing one
    sat at 4.417. So the usable question is not "is this above 0.8", which would
    be a constant to calibrate and recalibrate, but "is this an outlier among its
    peers right now", which calibrates itself.

    Scored in median absolute deviations rather than standard deviations, because
    a single large outlier inflates a standard deviation enough to hide itself -
    the security most worth elevating would be the one that raised the bar past
    its own value.

    A positive score is elevation, a negative one suppression, and both are
    meaningful: a fading story does not need elevating, and the same statistic
    says so without a second mechanism."""
    series = cycle_series(conn)
    levels = {
        security: statistics.mean(point[statistic] for point in points[len(points) // 2:])
        for security, points in series.items() if points
    }
    if len(levels) < 3:
        raise ValueError("peer comparison needs at least three securities")

    median = statistics.median(levels.values())
    deviations = [abs(value - median) for value in levels.values()]
    mad = statistics.median(deviations) or 1e-9

    return sorted(
        (
            {
                "security": security,
                "level": round(value, 3),
                "peer_median": round(median, 3),
                # 0.6745 makes a MAD-based score comparable to a standard score
                # for normally distributed data, so a reader's intuition about
                # "two sigma" still roughly applies.
                "deviations": round(0.6745 * (value - median) / mad, 2),
            }
            for security, value in levels.items()
        ),
        key=lambda row: -row["deviations"],
    )


def open_and_measure(db_path, developing: set[str]) -> dict:
    """Convenience for a finished run directory: open, measure everything, close.

    Takes a connection everywhere else, mirroring simulation/metrics.py, so these
    can be exercised against a constructed database instead of only a real run."""
    from backend import fi_db

    conn = fi_db.get_connection(db_path)
    try:
        return {
            "deltas": measure(conn, developing),
            "levels": level_separation(conn, developing),
            "peers": {stat: peer_outlier_scores(conn, stat) for stat in STATISTICS},
        }
    finally:
        conn.close()
