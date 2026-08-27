"""The COO's natural-language interface (backend/coo_chat.py; addendum 38
§4.5/§11, TQ-27, SPEC_RECONCILIATION §77).

The requirement is that the COO "answer using actual system state/status data
rather than inventing an answer" (§4.5). A prompt that merely *asks* a model
to be truthful is a hope, so what is tested here is the structure that makes
it true: the state is gathered first, it is the only material handed over, and
an unavailable model produces a reported error rather than a fabricated reply.
"""

import pytest

from backend import coo_chat, fi_db, metadata_engine, status_events


class FakeProvider:
    """Records what it was asked and returns a fixed reply."""

    def __init__(self, text="All quiet.", fail=None):
        self.system = None
        self.messages = None
        self._text = text
        self._fail = fail

    def complete(self, system, messages, tools, max_tokens=2048):
        self.system, self.messages = system, messages
        if self._fail:
            raise self._fail
        from types import SimpleNamespace

        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])

    def stream(self, system, messages, tools, max_tokens=2048):
        self.system, self.messages = system, messages
        if self._fail:
            raise self._fail
        for word in self._text.split():
            yield {"type": "text", "text": word + " "}
        yield {"type": "final", "content": [], "stop_reason": "end_turn"}


# --- the digest is the whole grounding mechanism ----------------------------------


def test_digest_carries_the_organizations_real_state(conn):
    metadata_engine.run(conn)
    fi_db.register_agent(conn, "explorer-1", "explorer", 100)

    digest = coo_chat.state_digest(conn)
    assert digest["configuration"]["lifecycle_stage"] == "PRE_ALPHA"
    assert any(a["role"] == "explorer" for a in digest["organization"]["agents"])
    assert any("Metadata ready" in e["message"] for e in digest["events"]["recent_narration"])


def test_digest_names_what_is_deliberately_unbuilt(conn):
    """Rule 3 of the prompt needs material: absence looks identical to quiet
    from inside a snapshot, so what does not exist is stated rather than left
    to be inferred."""
    digest = coo_chat.state_digest(conn)
    unbuilt = digest["not_built_yet"]
    # Parliament is built (TQ-81, §123); what is still absent from addendum 32
    # is elections, ministers, committees and the weekly session. Re-aimed rather
    # than deleted - the rule this defends is unchanged, only its subject moved.
    # tests/test_parliament.py holds the detailed version.
    assert "parliament" in unbuilt and "elections" in unbuilt["parliament"]
    assert "cannot act" in unbuilt["coo_actions"] or "report but cannot act" in unbuilt["coo_actions"]


def test_one_broken_section_does_not_mute_the_coo(conn, monkeypatch):
    """38 §12's rule applied to the reporter: a failure in one section must
    leave it able to answer about the others."""
    monkeypatch.setattr(coo_chat, "_dig_organization",
                        lambda c: (_ for _ in ()).throw(RuntimeError("registry down")))
    digest = coo_chat.state_digest(conn)
    assert "unavailable" in digest["organization"]
    assert digest["events"]  # the rest survived


# --- what actually reaches the model ----------------------------------------------


def test_the_state_is_handed_over_as_the_only_source_of_truth(conn):
    metadata_engine.run(conn)
    provider = FakeProvider()
    coo_chat.answer(conn, "what stage are we in?", provider=provider)

    assert "only source of truth" in provider.messages[-1]["content"]
    assert "PRE_ALPHA" in provider.messages[-1]["content"]
    # The rules that make grounding structural rather than hoped for.
    assert "Answer ONLY from the snapshot" in provider.system
    assert "You REPORT; you cannot ACT" in provider.system


def test_language_reaches_the_prompt(conn):
    provider = FakeProvider()
    coo_chat.answer(conn, "நிலை என்ன?", language="ta", provider=provider)
    assert "Tamil" in provider.system

    provider = FakeProvider()
    coo_chat.answer(conn, "status?", language="en-IN", provider=provider)
    assert "Indian" in provider.system


def test_an_unknown_language_passes_through_rather_than_being_refused(conn):
    """The label is a pass-through, so a language nobody enumerated still
    works without a code change."""
    provider = FakeProvider()
    coo_chat.answer(conn, "hei", language="fi", provider=provider)
    assert "fi" in provider.system


def test_history_is_bounded(conn):
    provider = FakeProvider()
    history = [{"role": "user", "content": f"q{i}"} for i in range(30)]
    coo_chat.answer(conn, "and now?", history=history, provider=provider)
    assert len(provider.messages) <= 9  # 8 remembered turns plus this question


# --- honest failure ----------------------------------------------------------------


def test_an_unavailable_model_is_reported_never_fabricated(conn):
    """The failure that matters most: a console that invents an answer when
    the model is down is worse than one that says the model is down."""
    result = coo_chat.answer(conn, "status?", provider=FakeProvider(fail=RuntimeError("no key")))
    assert result["answer"] == ""
    assert "RuntimeError: no key" in result["error"]


def test_empty_question_is_refused_without_calling_the_model(conn):
    provider = FakeProvider()
    result = coo_chat.answer(conn, "   ", provider=provider)
    assert result["error"] == "empty question"
    assert provider.messages is None  # nothing was spent


# --- streaming, which is what makes it interruptible --------------------------------


def test_stream_yields_text_then_final(conn):
    system, messages = coo_chat.prepare(conn, "what is happening?")
    events = list(coo_chat.stream_answer(system, messages, provider=FakeProvider("two words")))
    assert [e["type"] for e in events] == ["text", "text", "final"]
    assert "".join(e["text"] for e in events if e["type"] == "text").strip() == "two words"


def test_stream_reports_failure_as_an_event_not_an_exception(conn):
    """A stream that dies silently leaves the console waiting for a completion
    that never arrives - gateway/streaming.py's own reasoning."""
    system, messages = coo_chat.prepare(conn, "hello")
    events = list(coo_chat.stream_answer(system, messages,
                                         provider=FakeProvider(fail=RuntimeError("boom"))))
    assert events[-1]["type"] == "error"
    assert "boom" in events[-1]["error"]


def test_prepare_reads_the_database_so_the_worker_thread_need_not(conn):
    """The thread split gateway/streaming.py requires: sqlite connections
    belong to the thread that opened them, so the digest is read here and
    only plain strings cross into the worker."""
    metadata_engine.run(conn)
    system, messages = coo_chat.prepare(conn, "who is running?")
    assert isinstance(system, str)
    assert all(isinstance(m["content"], str) for m in messages)
    assert "PRE_ALPHA" in messages[-1]["content"]
