import json
from datetime import datetime

from app import audit


def test_record_appends_one_json_line(isolated_audit_log):
    audit.record(action="retrieve_portfolio", resource="portfolio", authorized=True, result="returned 2 holdings")

    lines = isolated_audit_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["action"] == "retrieve_portfolio"
    assert entry["resource"] == "portfolio"
    assert entry["authorized"] is True
    assert entry["result"] == "returned 2 holdings"


def test_record_timestamp_is_parseable_iso(isolated_audit_log):
    audit.record(action="a", resource="r", authorized=False, result="x")
    entry = json.loads(isolated_audit_log.read_text(encoding="utf-8").splitlines()[0])
    datetime.fromisoformat(entry["timestamp"])


def test_multiple_records_append_multiple_lines(isolated_audit_log):
    audit.record(action="a", resource="r", authorized=True, result="1")
    audit.record(action="a", resource="r", authorized=False, result="2")
    audit.record(action="a", resource="r", authorized=True, result="3")

    lines = isolated_audit_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(l)["result"] for l in lines] == ["1", "2", "3"]
