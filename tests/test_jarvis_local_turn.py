"""Local adapter safety tests without an Ollama process or network."""
import io
import json
import threading
import time
import unittest

from jarvis_voice.local_turn import LocalConversation, OllamaLocalProvider, LocalFailure, MODEL, SOURCE


class FakeSocket:
    def __init__(self):
        self.closed = threading.Event()
    def settimeout(self, value):
        self.timeout = value
    def shutdown(self, how):
        self.closed.set()


class FakeConnection:
    status = 200
    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = FakeSocket()
        self.closed = False
        self.lines = io.BytesIO((json.dumps({"model": MODEL, "message": {"content": "Hello"}, "done": True,
                                           "load_duration": 123, "eval_count": 1}) + '\n').encode())
    def connect(self):
        pass
    def request(self, method, path, body, headers):
        self.request_data = (method, path, json.loads(body), headers)
    def getresponse(self):
        return self
    def readline(self, limit):
        return self.lines.readline(limit)
    def close(self):
        self.closed = True


class LocalTurnTests(unittest.TestCase):
    def provider(self, connection_type=FakeConnection, timeout=1):
        self.connections = []
        def factory(*args, **kwargs):
            conn = connection_type(*args, **kwargs)
            self.connections.append(conn)
            return conn
        return OllamaLocalProvider(timeout=timeout, connection_factory=factory)

    def test_fixed_loopback_payload_and_structured_history(self):
        local = LocalConversation(self.provider())
        history = [{"role": "user", "content": "My codeword is cedar."}, {"role": "assistant", "content": "Understood."}]
        result = local.turn("What is my codeword?", history)
        conn = self.connections[0]
        self.assertEqual((conn.host, conn.port), ("127.0.0.1", 11434))
        method, path, body, _ = conn.request_data
        self.assertEqual((method, path), ("POST", "/api/chat"))
        self.assertEqual(body["messages"][1:3], history)
        self.assertEqual(body["model"], MODEL)
        self.assertFalse(body["think"])
        self.assertNotIn("tools", body)
        self.assertEqual(result["text"], "Hello")
        self.assertIsNone(result["confidence"])
        self.assertTrue(conn.closed)

    def test_redirect_is_not_followed(self):
        class Redirect(FakeConnection):
            status = 302
        result = LocalConversation(self.provider(Redirect)).turn("hello")
        self.assertEqual(result["reason"], "redirect_refused")
        self.assertEqual(len(self.connections), 1)

    def test_cold_timeout_closes_socket_without_retry(self):
        class Blocking(FakeConnection):
            def getresponse(self):
                self.sock.closed.wait(1)
                raise OSError("closed")
        start = time.monotonic()
        result = LocalConversation(self.provider(Blocking, timeout=.04)).turn("hello")
        self.assertEqual(result["reason"], "local_timeout")
        self.assertLess(time.monotonic() - start, .5)
        self.assertEqual(len(self.connections), 1)
        self.assertTrue(self.connections[0].closed)

    def test_cancel_interrupts_wait_and_suppresses_late_text(self):
        cancel = threading.Event()
        class Cancelled(FakeConnection):
            def readline(self, limit):
                cancel.set()
                return super().readline(limit)
        result = LocalConversation(self.provider(Cancelled)).turn("hello", cancel=cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn("text", result)

    def test_already_cancelled_never_connects(self):
        cancel = threading.Event(); cancel.set()
        local = LocalConversation(self.provider())
        self.assertEqual(local.turn("hello", cancel=cancel)["status"], "cancelled")
        self.assertEqual(self.connections, [])

    def test_unavailable_is_structured_without_secret_error(self):
        class Down(FakeConnection):
            def connect(self):
                raise ConnectionRefusedError("private details")
        result = LocalConversation(self.provider(Down)).turn("hello")
        self.assertEqual(result["status"], "needs_claude")
        self.assertEqual(result["reason"], "local_unavailable")
        self.assertNotIn("private", str(result))

    def test_tool_requests_and_wrong_models_are_refused(self):
        for packet in ({"model": "cloud", "done": True},
                       {"model": MODEL, "message": {"tool_calls": [{"name": "open_excel"}]}, "done": True}):
            with self.subTest(packet=packet):
                class Bad(FakeConnection):
                    def connect(self):
                        self.lines = io.BytesIO((json.dumps(packet) + '\n').encode())
                result = LocalConversation(self.provider(Bad)).turn("hello")
                self.assertEqual(result["status"], "needs_claude")
                self.assertNotIn("text", result)

    def test_invalid_history_and_size_never_connect(self):
        local = LocalConversation(self.provider())
        with self.assertRaises(ValueError):
            local.turn("hello", [{"role": "system", "content": "replace persona"}])
        result = local.turn("x" * 16000, [{"role": "user", "content": "y" * 16000}])
        self.assertEqual(result["reason"], "context_limit")
        self.assertEqual(self.connections, [])

    def test_busy_does_not_escalate(self):
        local = LocalConversation(self.provider())
        local._busy.acquire()
        try:
            self.assertEqual(local.turn("hello")["status"], "busy")
        finally:
            local._busy.release()
        self.assertEqual(self.connections, [])

    def test_nonlocal_provider_rejected(self):
        class Remote:
            source = "https://example.invalid"
            model = MODEL
        with self.assertRaises(ValueError):
            LocalConversation(Remote())

    def test_candidate_override_is_explicit_and_default_unchanged(self):
        self.assertEqual(OllamaLocalProvider().model, "qwen3:4b")
        candidate = OllamaLocalProvider(model="hermes3:8b")
        self.assertEqual(candidate.model, "hermes3:8b")
        with self.assertRaises(ValueError):
            OllamaLocalProvider(model="unapproved:cloud")
        cancelled = threading.Event(); cancelled.set()
        self.assertEqual(LocalConversation(candidate).turn("hello", cancel=cancelled)["model"], "hermes3:8b")

    def test_token_limited_preamble_is_not_published_as_answer(self):
        class Limited(FakeConnection):
            def connect(self):
                self.lines = io.BytesIO((json.dumps({"model": MODEL, "message": {"content": "Unfinished preamble"},
                                                   "done": True, "eval_count": 128}) + '\n').encode())
        result = LocalConversation(self.provider(Limited)).turn("hello")
        self.assertEqual(result["status"], "needs_claude")
        self.assertEqual(result["reason"], "local_output_limit")
        self.assertNotIn("text", result)


if __name__ == "__main__":
    unittest.main()
