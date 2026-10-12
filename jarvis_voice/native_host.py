"""Standalone native host with explicit local composition, never Gateway bootstrap.

Opening a window reads state only. Start/Connect publishes through Comm's public
start hook. Local inference and browser speech are explicit independent options.
The default no-playback speaker reports no_speech_path through Comm's contract.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from collections import deque
from pathlib import Path

from .native_dispatch import NativeApi, NativeDispatcher


PAGE = Path(__file__).resolve().parents[1] / "gateway" / "static" / "voice.html"


class MicrophoneWorker:
    """Opt-in recognizer owner. Callbacks never touch UI or the COMM worker."""
    def __init__(self, epoch, factory, capacity=64):
        self.epoch, self.factory, self.capacity = epoch, factory, capacity
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._events = deque()
        self._seen = set()
        self._seen_order = deque()
        self._sequence = 0
        self._thread = None
        self._closed = False
        self._state = "not_started"
        self._error = None

    def start(self, epoch):
        with self._lock:
            if epoch != self.epoch or self._closed:
                return {"ok": False, "error": "closed_or_stale"}
            if self._thread is None:
                self._state = "starting"
                self._thread = threading.Thread(target=self._run, name="jarvis-microphone", daemon=True)
                self._thread.start()
        return {"ok": True}

    def emit(self, kind, text="", *, key=None, confidence=0, grammar=""):
        with self._lock:
            if self._closed or self._stop.is_set():
                return
            if kind == "error":
                self._state, self._error = "error", text
                self._stop.set()
                return
            if kind not in ("hypothesis", "final", "activity") or type(text) is not str or len(text) > 16000:
                return
            if kind == "final":
                if key is None or key in self._seen:
                    return
                self._seen.add(key); self._seen_order.append(key)
                if len(self._seen_order) > 256:
                    self._seen.discard(self._seen_order.popleft())
            if kind == "hypothesis":
                self._events = deque(e for e in self._events if e["kind"] != "hypothesis")
            if len(self._events) >= self.capacity:
                # Never silently lose a final/control and continue as if complete.
                self._state, self._error = "error", "voice_queue_overflow"
                self._stop.set()
                return
            self._sequence += 1
            self._events.append({"id": self._sequence, "kind": kind, "text": text,
                                 "confidence": confidence, "grammar": grammar})

    def _run(self):
        engine = None
        try:
            engine = self.factory(self.emit)
            if self._stop.is_set():
                return
            engine.start()  # The only path that opens input; requires explicit --microphone.
            with self._lock:
                if not self._closed and not self._stop.is_set():
                    self._state = "listening"
            self._stop.wait()
        except Exception as error:
            with self._lock:
                if not self._closed:
                    self._state, self._error = "error", type(error).__name__
        finally:
            if engine is not None:
                try:
                    engine.close()
                except Exception as error:
                    with self._lock:
                        self._error = "dispose_" + type(error).__name__

    def drain(self, epoch):
        with self._lock:
            if epoch != self.epoch or self._closed:
                return {"ok": False, "host_epoch": self.epoch, "error": "closed_or_stale", "events": []}
            events = list(self._events); self._events.clear()
            return {"ok": True, "host_epoch": self.epoch, "state": self._state, "error": self._error, "events": events}

    def close(self, timeout=.5):
        with self._lock:
            self._closed = True; self._state = "closed"; self._events.clear(); self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return {"closed": True, "worker_stopped": thread is None or not thread.is_alive()}


class SystemSpeechInput:
    """Installed en-US SAPI recognizer; construction never opens the microphone."""
    def __init__(self, emit):
        import clr
        base = Path(os.environ["WINDIR"]) / "Microsoft.NET" / "assembly" / "GAC_MSIL" / "System.Speech"
        assemblies = sorted(base.glob("v4.0_4.0.0.0__*/System.Speech.dll"))
        if not assemblies:
            raise RuntimeError("installed_SystemSpeech_missing")
        clr.AddReference(str(assemblies[0]))
        from System import Array, String
        from System.Speech.Recognition import SpeechRecognitionEngine, DictationGrammar, Grammar, GrammarBuilder, Choices, RecognizeMode
        info = next((r for r in SpeechRecognitionEngine.InstalledRecognizers() if str(r.Culture) == "en-US"), None)
        if info is None:
            raise RuntimeError("installed_en_US_recognizer_missing")
        self.engine = SpeechRecognitionEngine(info)
        self._multiple = RecognizeMode.Multiple
        self._started = False
        self._handlers = []
        try:
            builder = GrammarBuilder(); builder.Culture = info.Culture
            builder.Append(Choices(Array[String]([
                "Silence", "Jarvis back to voice mode", "Jarvis shut down", "Jarvis close without saving",
            ])))
            commands = Grammar(builder); commands.Name = "jarvis-controls"; commands.Priority = 127
            dictation = DictationGrammar(); dictation.Name = "jarvis-dictation"
            self.engine.LoadGrammar(commands); self.engine.LoadGrammar(dictation)
            def hypothesis(sender, args):
                emit("hypothesis", str(args.Result.Text))
            def final(sender, args):
                try:
                    r = args.Result
                    key = (int(r.Audio.AudioPosition.Ticks), int(r.Audio.Duration.Ticks))
                    emit("final", str(r.Text), key=key, confidence=int(float(r.Confidence) * 100), grammar=str(r.Grammar.Name))
                except Exception:
                    emit("error", "recognition_result_error")
            def completed(sender, args):
                emit("error", "recognition_ended")
            self._handlers = [hypothesis, final, completed]
            self.engine.SpeechHypothesized += hypothesis
            self.engine.SpeechRecognized += final
            self.engine.RecognizeCompleted += completed
        except Exception:
            self.engine.Dispose()
            raise

    def start(self):
        self.engine.SetInputToDefaultAudioDevice()
        self.engine.RecognizeAsync(self._multiple)
        self._started = True

    def close(self):
        try:
            if self._started:
                self.engine.RecognizeAsyncCancel()
            if self._handlers:
                self.engine.SpeechHypothesized -= self._handlers[0]
                self.engine.SpeechRecognized -= self._handlers[1]
                self.engine.RecognizeCompleted -= self._handlers[2]
        finally:
            self.engine.Dispose()


def native_html(page, host_epoch, *, local_model=None, speech_available=False, microphone_available=False, comm_available=False):
    # Host-only configuration. Native mode returns before legacy storage/login/ws.
    config = json.dumps({"epoch": host_epoch, "local_model": local_model, "speech_available": speech_available,
                         "microphone_available": microphone_available, "comm_available": comm_available}, ensure_ascii=True).replace("<", "\\u003c")
    marker = '<script>window.__JARVIS_NATIVE__=Object.freeze(' + config + ');</script>'
    csp = ('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
           'script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; '
           'connect-src \'none\'; media-src \'none\'; frame-src \'none\'; form-action \'none\'">')
    html = page.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + csp + marker, 1)
    return html.replace("__INSTANCE__", "NATIVE · LOCAL").replace("__VERSION__", "native-integration").replace("__BUILD__", "local")


class CloseGuard:
    """Keep the window/listener usable unless final save is known or force is explicit."""
    def __init__(self, dispatcher, finish, notify, *, persistence=True):
        self.dispatcher, self.finish, self.notify = dispatcher, finish, notify
        self.persistence = persistence
        self.allowed = False
        self._lock = threading.Lock()

    def request(self, epoch, force=False):
        if epoch != self.dispatcher.epoch or type(force) is not bool:
            return {"ok": False, "error": "invalid_close", "host_epoch": self.dispatcher.epoch}
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "close_busy", "host_epoch": epoch}
        try:
            if self.allowed:
                return {"ok": True, "host_epoch": epoch, "close_allowed": True}
            result = {"ok": True, "host_epoch": epoch}
            if self.persistence and not force:
                result = self.dispatcher.request("shutdown", epoch)
                receipt = result.get("result") or {}
                view = result.get("view") or {}
                snapshot = view.get("snapshot") or {}
                binding = snapshot.get("binding") or {}
                # Setup/recognition-only windows have no selected conversation to
                # checkpoint. Require positive empty-state evidence from the same
                # serialized shutdown response, never a UI-provided bypass flag.
                empty_session = (result.get("ok") is True and "conversation_id" in binding
                    and binding["conversation_id"] is None and view.get("transcript") == []
                    and snapshot.get("pending", "unknown") is None
                    and receipt.get("pending", "unknown") is None
                    and receipt.get("cancel_outstanding") == [] and receipt.get("unsaved") == []
                    and receipt.get("error") is None
                    and snapshot.get("recovery", {}).get("state") in ("ok", "not_run"))
                if not empty_session and (not result.get("ok") or receipt.get("checkpoint_persisted") is not True or receipt.get("error") is not None or receipt.get("unsaved") != []):
                    result = dict(result, close_allowed=False)
                    self.notify(result)
                    return result
            self.allowed = True
            self.finish()
            return dict(result, close_allowed=True, forced=force)
        finally:
            self._lock.release()

    def on_closing(self):
        if self.allowed:
            return None
        threading.Thread(target=self.request, args=(self.dispatcher.epoch,), daemon=True,
                         name="jarvis-close-check").start()
        return False


def run(*, profile_root, api=None, local=None, speech_available=False, microphone_factory=None, window_module=None):
    # Importing this module creates neither windows nor communication state.
    if window_module is None:
        import webview as window_module
    root = Path(profile_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    dispatcher = NativeDispatcher(api, local=local, speech_available=speech_available)
    microphone = MicrophoneWorker(dispatcher.epoch, microphone_factory) if microphone_factory is not None else None
    try:
        local_model = local._provider.model if local is not None else None
        native_api = NativeApi(dispatcher, microphone=microphone)
        window = window_module.create_window("Jarvis", html=native_html(PAGE.read_text(encoding="utf-8"), dispatcher.epoch,
                                                                       local_model=local_model, speech_available=speech_available,
                                                                       microphone_available=microphone is not None, comm_available=api is not None),
                                             js_api=native_api, width=1280, height=900,
                                             min_size=(420, 500), text_select=True)
        def notify_close(result):
            encoded = json.dumps(result, ensure_ascii=True).replace("<", "\\u003c")
            window.evaluate_js("window.jarvisCloseResult && window.jarvisCloseResult(" + encoded + ");")
        guard = CloseGuard(dispatcher, window.destroy, notify_close, persistence=api is not None)
        native_api._close_handler = guard.request
        window.events.closing += guard.on_closing
        def on_closed():
            # pywebview collects event results in a set; do not return the
            # dispatcher's structured close report from a window callback.
            dispatcher.close()
            if microphone is not None:
                microphone.close()
        window.events.closed += on_closed
        window_module.start(gui="edgechromium", private_mode=True, storage_path=str(root), http_server=False)
    finally:
        dispatcher.close()
        if microphone is not None:
            microphone.close()


class BrowserSpeaker:
    blocking_completion = False
    def __init__(self, enabled=False):
        self.playback = enabled
    def speak(self, descriptor):
        return "queued" if self.playback else "refused"
    def stop(self):
        # Browser cancels immediately; Comm invalidates tokens before this call.
        pass


class SilentDisplay:
    def show(self, **event):
        # The facade's atomic view is the display source; no nested callbacks.
        pass


def build_comm(root, participant, peer, *, speech_available=False, store_root=None):
    from .comm.launch import parse_args, build
    from .comm.bridge import CommApi
    ns = parse_args(["--root", str(root), "--participant", participant, "--peer", peer, "--plane", "local"])
    store = None
    if store_root is not None:
        # Accepted R4 reference c28df6c; COMM is the sole writer.
        from .persist_store import FileStore
        store = FileStore(Path(store_root).resolve())
    return CommApi(build(ns, speaker=BrowserSpeaker(speech_available), display=SilentDisplay(), store=store))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jarvis native host; explicit local composition, no paid provider")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--comm-root", help="Explicit owned local spool/outbox/ledger directory")
    parser.add_argument("--participant")
    parser.add_argument("--peer")
    parser.add_argument("--store-root", help="Explicit owned R4 durable conversation directory; omitted means non-durable demo")
    parser.add_argument("--local-model", choices=("qwen3:4b", "hermes3:8b"))
    parser.add_argument("--speech", action="store_true", help="Explicitly permit browser playback; off by default")
    parser.add_argument("--microphone", action="store_true", help="Explicitly start installed en-US microphone recognition on page readiness")
    parser.add_argument("--profile-root", required=True, help="New task-owned profile directory; must not exist")
    args = parser.parse_args(argv)
    if args.store_root and not args.comm_root:
        parser.error("--store-root requires --comm-root")
    api = None
    if args.comm_root:
        if not args.participant or not args.peer:
            parser.error("--comm-root requires explicit --participant and --peer")
        api = build_comm(args.comm_root, args.participant, args.peer, speech_available=args.speech, store_root=args.store_root)
    local = None
    if args.local_model:
        from .local_turn import LocalConversation, OllamaLocalProvider
        local = LocalConversation(OllamaLocalProvider(model=args.local_model))
    run(profile_root=args.profile_root, api=api, local=local, speech_available=args.speech,
        microphone_factory=SystemSpeechInput if args.microphone else None)


if __name__ == "__main__":
    main()
