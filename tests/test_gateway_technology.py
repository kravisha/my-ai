"""The Technology and Architecture function: what it measures, what it refuses to
claim, and what reaches the Super User's board.

The check most worth reading here is the one about SQLite. Addendum 17 §9 uses
SQLite-to-PostgreSQL as its worked example, which makes it exactly the
recommendation a monitoring function is most likely to make enthusiastically and
wrongly. What this one must do instead is report the concurrency it can see, admit
that nothing counts SQLITE_BUSY, and decline to recommend a migration on the
strength of an unmeasured absence.
"""

import subprocess

import pytest

from gateway import scoreboard, store, technology


def healthy_status(agents=2):
    return {
        "available": True,
        "agents": [
            {
                "identity": f"agent-{index}",
                "process_state": "running",
                "heartbeat_age_seconds": 0.5,
            }
            for index in range(agents)
        ],
    }


# --- The SQLite question ---


def test_sqlite_is_called_suitable_without_claiming_contention_was_measured():
    """The honest form of a negative recommendation: it says what it saw, says
    what it could not see, and does not convert the second into confidence."""
    finding = technology.check_sqlite_concurrency(healthy_status(agents=6))

    assert finding["verdict"] == "suitable"
    assert finding["evidence"]["processes_sharing_the_database"] == 6
    assert finding["evidence"]["recorded_sqlite_busy_errors"] is None
    assert "unmeasured rather than observed" in finding["evidence"]["measurement_limit"]
    assert finding["recommendation"]["candidate_replacement"] == "None recommended."
    assert "instrument" in finding["recommendation"]["expected_future_risk"].lower()


def test_a_suitable_verdict_never_reaches_the_board(gateway_conn):
    """A board that filed an item every time something was fine would bury the
    ones that are not."""
    report = {"findings": [technology.check_sqlite_concurrency(healthy_status())]}

    assert technology.file_findings(gateway_conn, report) == []
    assert scoreboard.list_items(gateway_conn) == []


def test_stale_heartbeats_raise_a_recommendation_with_every_field_9_asks_for():
    status = healthy_status()
    status["agents"][0]["heartbeat_age_seconds"] = 120

    finding = technology.check_sqlite_concurrency(status)

    assert finding["verdict"] == "watch"
    assert finding["importance"] == "important"
    assert finding["evidence"]["agents_with_a_stale_heartbeat"] == ["agent-0"]
    for field in (
        "candidate_replacement",
        "benefits",
        "costs_and_tradeoffs",
        "migration_implications",
        "expected_future_risk",
        "suggested_priority",
    ):
        assert finding["recommendation"][field], f"§9 requires {field}"
    assert "instrument" in finding["recommendation"]["suggested_priority"].lower(), (
        "even when it raises a concern, it asks for measurement before migration"
    )


def test_an_unreachable_backend_is_no_evidence_rather_than_a_verdict():
    """"We cannot answer this" is a finding. Guessing would be worse than
    silence, and silence would be worse than saying so."""
    finding = technology.check_sqlite_concurrency({"available": False, "reason": "down"})

    assert finding["verdict"] == "no_evidence"
    assert finding["recommendation"] is None


# --- The other checks ---


def test_dependency_pinning_reads_the_real_file(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("anthropic\nfastapi==0.1.0\n", encoding="utf-8")
    monkeypatch.setattr(technology, "PROJECT_ROOT", tmp_path)

    finding = technology.check_dependency_pinning()

    assert finding["verdict"] == "watch"
    assert finding["evidence"]["unpinned"] == ["anthropic"]
    assert finding["evidence"]["declared"] == 2


def test_fully_pinned_dependencies_are_suitable(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("anthropic==1.0\nfastapi>=0.1\n", encoding="utf-8")
    monkeypatch.setattr(technology, "PROJECT_ROOT", tmp_path)

    assert technology.check_dependency_pinning()["verdict"] == "suitable"


def test_a_growing_wal_is_noticed(monkeypatch, tmp_path):
    """The first real symptom of a SQLite deployment under more write pressure
    than checkpointing is absorbing."""
    database = tmp_path / "financial_intelligence.db"
    database.write_bytes(b"x" * 1024)
    (tmp_path / "financial_intelligence.db-wal").write_bytes(b"y" * 2048)
    monkeypatch.setattr(technology, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "gateway.db")
    monkeypatch.setattr(technology, "WAL_WATCH_BYTES", 1024)

    finding = technology.check_database_growth()

    assert finding["verdict"] == "watch"
    assert "checkpointing is behind" in finding["summary"]


def test_an_unsupported_python_is_unsuitable(monkeypatch):
    monkeypatch.setattr(technology, "MINIMUM_SUPPORTED_PYTHON", (99, 0))

    finding = technology.check_python_runtime()

    assert finding["verdict"] == "unsuitable"
    assert finding["importance"] == "important"


def test_a_full_disk_is_a_capacity_finding(monkeypatch):
    monkeypatch.setattr(
        technology.shutil, "disk_usage", lambda path: type("U", (), {"free": 1, "total": 100})()
    )

    finding = technology.check_disk_headroom()

    assert finding["verdict"] == "watch"
    assert finding["importance"] == "important"


def test_a_missing_git_binary_is_urgent(monkeypatch):
    """The capability is simply absent until fixed, and nothing else would
    notice until a publish failed at the moment it was needed."""

    def missing(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", missing)

    finding = technology.check_git_available()

    assert finding["verdict"] == "unsuitable"
    assert finding["importance"] == "urgent"


def test_git_present_is_reported_with_its_version():
    finding = technology.check_git_available()

    assert finding["verdict"] == "suitable"
    assert "git version" in finding["summary"]


# --- The review as a whole ---


def test_a_review_covers_every_check_and_counts_the_verdicts():
    report = technology.review(status=healthy_status())

    assert {finding["key"] for finding in report["findings"]} == {
        "sqlite_concurrency",
        "database_growth",
        "dependency_pinning",
        "python_runtime",
        "disk_headroom",
        "git_available",
    }
    assert sum(report["counts"].values()) == len(report["findings"])
    assert report["reviewed_at"]


def test_the_review_is_read_only(monkeypatch):
    """§9: the monitoring function does not perform the migration. It has no way
    to: nothing in a review writes anything, which is why running it is safe at
    any time and why filing is a separate, opt-in step."""
    forbidden = ("file_item", "resolve_item", "add_note")
    for name in forbidden:
        monkeypatch.setattr(
            scoreboard, name, lambda *a, **k: pytest.fail(f"a review called scoreboard.{name}")
        )

    technology.review(status=healthy_status())


# --- What reaches the board ---


def test_a_filed_finding_carries_9s_required_shape(gateway_conn, monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("anthropic\n", encoding="utf-8")
    monkeypatch.setattr(technology, "PROJECT_ROOT", tmp_path)
    report = {"findings": [technology.check_dependency_pinning()]}

    [filed] = technology.file_findings(gateway_conn, report)
    item = scoreboard.get_item(gateway_conn, filed["item_id"])

    assert item["source"] == "technology-and-architecture"
    assert item["related_spec"] == "addendum 17 §7-§9"
    for required in (
        "Evidence:",
        "Expected future risk:",
        "Candidate replacement:",
        "Benefits:",
        "Costs and tradeoffs:",
        "Migration implications:",
        "Suggested priority:",
    ):
        assert required in item["question"], f"§9 requires {required}"
    assert "It does not act." in item["question"]


def test_a_repeat_finding_is_not_filed_twice(gateway_conn, monkeypatch, tmp_path):
    """A periodic producer without this would repeat itself every interval until
    the board was useless."""
    (tmp_path / "requirements.txt").write_text("anthropic\n", encoding="utf-8")
    monkeypatch.setattr(technology, "PROJECT_ROOT", tmp_path)
    report = {"findings": [technology.check_dependency_pinning()]}

    [first] = technology.file_findings(gateway_conn, report)
    [second] = technology.file_findings(gateway_conn, report)

    assert second["skipped"] == "already open"
    assert second["item_id"] == first["item_id"]
    assert len(scoreboard.list_items(gateway_conn)) == 1


def test_a_finding_that_returns_after_being_resolved_is_filed_again(
    gateway_conn, monkeypatch, tmp_path
):
    """Suppressing a recurrence because it was once dealt with is how a board
    starts lying."""
    (tmp_path / "requirements.txt").write_text("anthropic\n", encoding="utf-8")
    monkeypatch.setattr(technology, "PROJECT_ROOT", tmp_path)
    report = {"findings": [technology.check_dependency_pinning()]}

    [first] = technology.file_findings(gateway_conn, report)
    scoreboard.resolve_item(gateway_conn, first["item_id"], "Pinned them; closing.")

    [second] = technology.file_findings(gateway_conn, report)

    assert "skipped" not in second
    assert second["item_id"] != first["item_id"]


def test_items_from_people_carry_no_signature_and_never_deduplicate(gateway_conn):
    """A person filing the same concern twice usually means something, so only the
    periodic producer's items are keyed."""
    first = scoreboard.file_item(gateway_conn, source="super-user", question="the same worry")
    second = scoreboard.file_item(gateway_conn, source="super-user", question="the same worry")

    assert first != second
    assert len(scoreboard.list_items(gateway_conn)) == 2


# --- Configuration and storage ---


def test_the_review_interval_is_configurable_and_can_be_switched_off(monkeypatch):
    monkeypatch.delenv(technology.REVIEW_INTERVAL_ENV, raising=False)
    assert technology.review_interval_hours() == technology.DEFAULT_REVIEW_INTERVAL_HOURS

    monkeypatch.setenv(technology.REVIEW_INTERVAL_ENV, "0")
    assert technology.review_interval_hours() == 0

    monkeypatch.setenv(technology.REVIEW_INTERVAL_ENV, "banana")
    assert technology.review_interval_hours() == technology.DEFAULT_REVIEW_INTERVAL_HOURS


def test_an_older_database_gains_the_signature_column(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so
    without the additive migration an existing gateway.db would keep the old shape
    and every insert would fail - on a developer's machine only, which is the
    worst place to find out."""
    path = tmp_path / "gateway.db"
    conn = store.get_connection(path)
    conn.executescript(store.SCHEMA)
    conn.executescript(
        """
        CREATE TABLE scoreboard_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL, source TEXT NOT NULL, question TEXT NOT NULL,
            importance TEXT NOT NULL CHECK (importance IN ('urgent','important','informational')),
            blocking INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
            related_spec TEXT, related_component TEXT, resolution TEXT, resolved_at TEXT
        );
        """
    )
    conn.close()

    conn = store.get_connection(path)
    store.init_schema(conn)
    try:
        item_id = scoreboard.file_item(conn, source="s", question="q", signature="tech:x")
        assert scoreboard.open_item_with_signature(conn, "tech:x")["id"] == item_id
    finally:
        conn.close()


# --- The route ---


def test_the_review_route_requires_a_session(gateway_client):
    assert gateway_client.get("/technology").status_code == 401


def test_the_route_reviews_without_filing_unless_asked(gateway_client, gateway_token, gateway_conn):
    """Reading the review is a question; putting items on somebody's board is an
    act. Opt-in even here."""
    headers = {"Authorization": f"Bearer {gateway_token}"}

    body = gateway_client.get("/technology", headers=headers).json()
    assert "findings" in body
    assert "filed" not in body
    assert scoreboard.list_items(gateway_conn) == []

    filed = gateway_client.get("/technology?file_findings=true", headers=headers).json()
    assert "filed" in filed


def test_a_periodic_pass_opens_its_own_connection_in_its_own_thread(tmp_path, monkeypatch):
    """The defect a live run found and the suite did not.

    The periodic loop opened its connection on the event loop and handed it to a
    worker thread, which sqlite3 refuses: "SQLite objects created in a thread can
    only be used in that same thread." It failed on *every* pass, survivably -
    the loop catches everything so the service stayed up - and therefore
    silently. Nothing in the suite crossed a thread boundary, so nothing saw it.

    `review_and_file` takes a path for the same reason `conversation.run_turn`
    does, and this runs it off the main thread to prove it."""
    import threading

    (tmp_path / "requirements.txt").write_text("anthropic\n", encoding="utf-8")
    monkeypatch.setattr(technology, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        technology.jarvis.JarvisClient, "status", lambda self: {"available": False, "reason": "down"}
    )

    db_path = tmp_path / "gateway.db"
    conn = store.get_connection(db_path)
    store.init_schema(conn)
    conn.close()

    outcome = {}

    def pass_on_a_worker_thread():
        try:
            outcome["result"] = technology.review_and_file(db_path)
        except BaseException as failure:  # noqa: BLE001 - reported, not raised into nothing
            outcome["failure"] = failure

    worker = threading.Thread(target=pass_on_a_worker_thread)
    worker.start()
    worker.join()

    assert "failure" not in outcome, f"a periodic pass raised off-thread: {outcome.get('failure')}"
    report, filed = outcome["result"]
    assert report["counts"]["watch"] >= 1
    assert [entry["key"] for entry in filed] == ["dependency_pinning"]

    conn = store.get_connection(db_path)
    try:
        assert len(scoreboard.list_items(conn)) == 1
    finally:
        conn.close()
