"""Tests for the Universal Human Query Interface (addendum 14 §7).

The property under test throughout is that a UQI answer comes from the agent's
own running process, not from the database being read on its behalf. That
distinction is the entire reason this exists alongside GET /admin/agents/{id}.
"""

import json
from unittest.mock import MagicMock

from agents import introspection
from backend import fi_db


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


# --- the request/answer contract ---


def test_a_question_is_addressed_to_one_identity_not_a_role(panel_conn):
    """A sibling in the same role answering on another's behalf would defeat
    the point of asking a specific process."""
    fi_db.ask_agent(panel_conn, "operator", "explorer-1", "Who are you?")

    assert fi_db.fetch_next_uqi_request(panel_conn, "explorer-1") is not None
    assert fi_db.fetch_next_uqi_request(panel_conn, "explorer-2") is None


def test_answering_records_the_process_that_replied(panel_conn):
    """The pid is what makes the answer meaningful - it proves a live process
    replied rather than the database being read on the agent's behalf."""
    request_id = fi_db.ask_agent(panel_conn, "operator", "explorer-1", "Who are you?")
    fi_db.answer_uqi_request(panel_conn, request_id, "I am Explorer.", pid=4242)

    row = fi_db.get_uqi_request(panel_conn, request_id)
    assert row["status"] == fi_db.UQI_ANSWERED
    assert row["answered_by_pid"] == 4242


def test_an_already_answered_question_is_not_overwritten(panel_conn):
    request_id = fi_db.ask_agent(panel_conn, "operator", "explorer-1", "Who are you?")
    fi_db.answer_uqi_request(panel_conn, request_id, "first", pid=1)
    fi_db.answer_uqi_request(panel_conn, request_id, "second", pid=2)
    assert fi_db.get_uqi_request(panel_conn, request_id)["answer"] == "first"


def test_an_unanswered_question_expires_rather_than_hanging(panel_conn):
    """A dormant or crashed agent cannot answer. Saying so is a real diagnostic
    result, not a failure of the interface."""
    request_id = fi_db.ask_agent(panel_conn, "operator", "explorer-1", "Are you alive?")
    assert fi_db.expire_stale_uqi_requests(panel_conn, timeout_seconds=0) == 1
    assert fi_db.get_uqi_request(panel_conn, request_id)["status"] == fi_db.UQI_UNANSWERED


def test_expiry_leaves_fresh_questions_alone(panel_conn):
    fi_db.ask_agent(panel_conn, "operator", "explorer-1", "q")
    assert fi_db.expire_stale_uqi_requests(panel_conn, timeout_seconds=3600) == 0


def test_history_is_kept_as_the_audit_trail(panel_conn):
    """§7 requires the UQI to be auditable. Questions and answers are retained,
    not discarded once read."""
    for i in range(3):
        fi_db.ask_agent(panel_conn, "operator", "coo-1", f"question {i}")
    history = fi_db.list_uqi_requests(panel_conn)
    assert len(history) == 3
    assert history[0]["question"] == "question 2"  # newest first
    assert all(row["asked_by"] == "operator" for row in history)


# --- how an agent composes its answer ---


def test_the_agent_answers_only_from_its_organizational_record(panel_conn, monkeypatch):
    """§6 scopes self-awareness to organizational facts and excludes
    "unrestricted introspection into hidden model internals". The model is a
    presenter of known facts, never a source of them - so the facts must
    actually reach it."""
    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    captured = {}

    def fake_call(system, messages, tools, max_tokens):
        captured["system"] = system
        captured["content"] = messages[0]["content"]
        return _Resp("I am Explorer, the quantitative discovery agent.")

    monkeypatch.setattr("app.model_gateway.call_reasoning_model", fake_call)

    answer = introspection.answer_question(panel_conn, "explorer-1", "What are you not allowed to do?")

    assert answer == "I am Explorer, the quantitative discovery agent."
    assert "ONLY from the facts provided" in captured["system"]
    # the charter's prohibitions were actually supplied, not merely alluded to
    assert "Perform deep reasoning" in captured["content"]


def test_an_unreachable_model_degrades_to_the_raw_record(panel_conn, monkeypatch):
    """An operator diagnosing a sick system needs the facts more than prose. An
    agent that could not answer at all would look broken when only the model
    was."""
    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    monkeypatch.setattr("app.model_gateway.call_reasoning_model",
                        MagicMock(side_effect=RuntimeError("model unavailable")))

    answer = introspection.answer_question(panel_conn, "explorer-1", "Who are you?")

    assert "unable to compose a reply" in answer
    assert "model unavailable" in answer
    assert "explorer-1" in answer  # the record itself still came through


def test_an_unknown_identity_says_so_rather_than_inventing_a_self(panel_conn):
    answer = introspection.answer_question(panel_conn, "ghost-9", "Who are you?")
    assert "no organizational record" in answer


# --- routes ---


def test_asking_returns_a_request_id_without_blocking(panel_client, panel_conn):
    """The handler must not wait on another process's poll loop."""
    fi_db.register_agent(panel_conn, "coo-1", "coo", 1)

    body = panel_client.post("/admin/agents/coo-1/uqi", json={"question": "Are you healthy?"}).json()

    assert body["status"] == fi_db.UQI_PENDING
    assert fi_db.get_uqi_request(panel_conn, body["request_id"])["question"] == "Are you healthy?"


def test_asking_a_nonexistent_agent_is_an_error_not_a_timeout(panel_client):
    response = panel_client.post("/admin/agents/ghost-9/uqi", json={"question": "hello"})
    assert response.status_code == 404


def test_polling_reports_the_answering_source_only_once_answered(panel_client, panel_conn):
    """answered_by distinguishes a live agent reply from the organizational
    record that /admin/agents/{id} returns."""
    fi_db.register_agent(panel_conn, "coo-1", "coo", 1)
    request_id = panel_client.post("/admin/agents/coo-1/uqi", json={"question": "q"}).json()["request_id"]

    pending = panel_client.get(f"/admin/uqi/{request_id}").json()
    assert pending["answered_by"] is None
    assert pending["answered_by_pid"] is None

    fi_db.answer_uqi_request(panel_conn, request_id, "I am the COO.", pid=99)
    answered = panel_client.get(f"/admin/uqi/{request_id}").json()
    assert answered["answered_by"] == "agent"
    assert answered["answered_by_pid"] == 99
    assert answered["answer"] == "I am the COO."


def test_polling_an_unknown_request_is_404(panel_client):
    assert panel_client.get("/admin/uqi/9999").status_code == 404


def test_history_route_exposes_the_audit_trail(panel_client, panel_conn):
    """asked_by is taken from the authenticated session, not the request body.
    An audit trail whose author field the caller can set is not an audit
    trail - so the field is absent from the request model entirely rather than
    accepted and quietly overridden."""
    fi_db.register_agent(panel_conn, "coo-1", "coo", 1)
    panel_client.post("/admin/agents/coo-1/uqi", json={"question": "q1", "asked_by": "somebody-else"})

    row = panel_client.get("/admin/uqi").json()["requests"][0]
    assert row["asked_by"] == "test-admin"  # the session identity
    assert row["question"] == "q1"


def test_the_uqi_timeout_exceeds_the_slowest_agents_answer_latency():
    """The timeout must clear a full work cycle of the slowest agent plus its
    own answer call, or a busy-but-healthy agent reads as unresponsive.

    Measured against a real backend (docs/TIMING_CONSTANTS.md): procedural
    agents answer in 2-4s, but analysis-1 - whose cycle is a deep-reasoning
    call - took up to 24.0s. The first value tried was 15s, which turned two of
    three samples into 'unanswered'. This encodes the measurement so the
    constant cannot drift back under it unnoticed."""
    worst_observed_answer_seconds = 24.0
    assert fi_db.UQI_TIMEOUT_SECONDS > worst_observed_answer_seconds * 2


def test_a_slow_agent_is_not_reported_unresponsive_before_the_timeout(panel_conn):
    """'unanswered' is meant to be a real health finding - a dormant or crashed
    agent - not a rendering of impatience with a working one."""
    request_id = fi_db.ask_agent(panel_conn, "krish", "analysis-1", "Are you healthy?")
    # 24s is the worst latency observed from a *healthy* Analysis
    assert fi_db.expire_stale_uqi_requests(panel_conn, timeout_seconds=25.0) == 0
    assert fi_db.get_uqi_request(panel_conn, request_id)["status"] == fi_db.UQI_PENDING
