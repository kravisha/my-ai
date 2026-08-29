"""How much write contention this storage engine has left in it
(ARCHITECTURE_READINESS_REVIEW.md N2, R3; directive §19; SPEC_RECONCILIATION §157).

SQLite in WAL mode admits many concurrent readers and **one writer**. Every agent
in this organization is a separate OS process sharing one database file, so the
write path is a queue whose depth nobody had measured. At the eight agents that
run today it is invisible. Providence's roughly fifteen personal agents plus a
newsroom is a different load, and directive §19 says an infrastructure change
needs *"evidence for the change"* rather than a preference.

This is that evidence, and only that. **Nothing here changes how the system
behaves under contention** - no retry, no backoff, no pooling. Those would be
answers to a question that has not been asked yet, and picking one before the
number exists is how a system acquires machinery it cannot justify.

## What it measures, and why through the production class

Each writer is a real subprocess opening its own `backend.db.Database` against
one file - the same class, the same PRAGMAs, the same 5-second `busy_timeout` the
agents use. A harness that opened its own connections would measure the harness.

Three numbers per configuration:

- **landed** - rows that are actually in the table afterwards. Compared against
  attempted, so a lost write is arithmetic rather than a judgement.
- **contended** - writes that raised `Database.Contended`, which is the named
  condition rather than a generic OperationalError (see backend/db.py).
- **wall** - how long the whole set took, which is what turns "it works" into a
  throughput figure somebody can extrapolate.

The failure this is aimed at is not "SQLite is slow". It is that a lock timeout
reaching an agent looks exactly like that agent being broken, so contention at
scale would present as several unrelated agents becoming unreliable at once -
diagnosed as an agent defect, at length. §93 made the same argument for liveness
against progress: *one number cannot tell those apart and two can.*
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The table this writes into. Its own, created here, and deliberately not one the
# organization uses: a measurement that wrote into `discovery_reports` would be
# seeding work nobody asked for, and §128's rule that seeds go through the
# production API exists precisely so nothing gets to bypass it for convenience.
TABLE = "contention_probe"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    writer INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    written_at TEXT NOT NULL,
    UNIQUE (writer, sequence)
);
"""


def _writer_main(db_path: str, writer: int, writes: int) -> int:
    """One writer process. Prints its own tally as JSON on stdout."""
    from backend.db import Contended, Database, now_iso

    db = Database(db_path)
    landed = contended = 0
    for sequence in range(writes):
        try:
            db.execute(
                f"INSERT INTO {TABLE} (writer, sequence, written_at) VALUES (?, ?, ?)",
                (writer, sequence, now_iso()))
            landed += 1
        except Contended:
            # Counted, never retried. A retry here would measure the retry.
            contended += 1
    db.close()
    print(json.dumps({"writer": writer, "landed": landed, "contended": contended}))
    return 0


def measure(db_path: str | Path, *, writers: int, writes: int) -> dict:
    """Run `writers` concurrent processes, each attempting `writes` inserts."""
    from backend.db import Database

    db_path = str(db_path)
    db = Database(db_path)
    db.executescript(SCHEMA)
    db.execute(f"DELETE FROM {TABLE}")
    db.close()

    started = time.monotonic()
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "simulation.contention", "--writer", str(writer),
             "--db", db_path, "--writes", str(writes)],
            cwd=PROJECT_ROOT, stdout=subprocess.PIPE, text=True)
        for writer in range(writers)
    ]
    tallies = []
    for proc in procs:
        out, _ = proc.communicate()
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                tallies.append(json.loads(line))
    wall = time.monotonic() - started

    db = Database(db_path)
    rows = db.fetchone(f"SELECT COUNT(*) AS n FROM {TABLE}")["n"]
    distinct = db.fetchone(
        f"SELECT COUNT(*) AS n FROM (SELECT DISTINCT writer, sequence FROM {TABLE})")["n"]
    db.close()

    attempted = writers * writes
    landed = sum(t["landed"] for t in tallies)
    contended = sum(t["contended"] for t in tallies)
    return {
        "writers": writers,
        "writes_per_writer": writes,
        "attempted": attempted,
        "reported_landed": landed,
        "rows_in_table": rows,
        "distinct_rows": distinct,
        "contended": contended,
        # Attempted, minus what landed, minus what was refused outright. Anything
        # left is a write that neither succeeded nor said it failed, which is the
        # only genuinely alarming outcome here.
        "unaccounted": attempted - landed - contended,
        "duplicates": rows - distinct,
        "wall_seconds": round(wall, 2),
        "writes_per_second": round(rows / wall, 1) if wall else None,
    }


def sweep(db_path: str | Path, *, sizes: tuple[int, ...], writes: int) -> list[dict]:
    return [measure(db_path, writers=n, writes=writes) for n in sizes]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m simulation.contention")
    parser.add_argument("--writer", type=int, help="internal: run as one writer process")
    parser.add_argument("--db", required=True)
    parser.add_argument("--writes", type=int, default=200)
    parser.add_argument("--writers", type=str, default="8,16,24",
                        help="comma-separated writer counts to sweep")
    args = parser.parse_args(argv)

    if args.writer is not None:
        return _writer_main(args.db, args.writer, args.writes)

    sizes = tuple(int(n) for n in args.writers.split(","))
    for result in sweep(args.db, sizes=sizes, writes=args.writes):
        print(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
