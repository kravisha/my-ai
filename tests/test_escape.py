"""The way out of the shell, which is what makes the shell safe to try.

Owner directive, 2026-09-23: *"please design it such a way that the escape key
should give user the option to exit the shell."*

Probed per his rule of the same day: every behaviour asserted here was run
against code with that behaviour removed before the test was kept.
"""

import pytest

from desktop import escape


class FakeHost:
    """Records effects and performs none. The adapter's shape, without Windows."""

    def __init__(self, *, desktop_restores=True, restart_accepted=True):
        self.calls = []
        self.menus = []
        self.texts = []
        self.desktop_restores = desktop_restores
        self.restart_accepted = restart_accepted

    def hide(self): self.calls.append("hide")
    def close(self): self.calls.append("close")
    def show_menu(self, lines): self.menus.append(lines)
    def show_text(self, text): self.texts.append(text)

    def restore_desktop(self):
        self.calls.append("restore_desktop")
        return self.desktop_restores

    def request_restart(self):
        self.calls.append("request_restart")
        return self.restart_accepted


def _hatch(host=None, **kwargs):
    done = []
    wired = {step: (lambda step=step: done.append(step))
             for step in (escape.PAUSE_TASKS, escape.CHECKPOINT, escape.RECORD_EVENT)}
    wired.update(kwargs.pop("before_exit", {}))
    hatch = escape.Hatch(host or FakeHost(), before_exit=wired, **kwargs)
    hatch.done = done
    return hatch


# =============================================================================
# Rule 1: the dangerous option is never the default, and never the same key
# =============================================================================


def test_escape_opens_the_menu_rather_than_exiting():
    host = FakeHost()
    hatch = _hatch(host)

    outcome = hatch.key("Escape")

    assert outcome.menu_open is True
    assert outcome.action == escape.KEEP_WORKING
    assert host.menus, "the menu was not shown"
    assert "close" not in host.calls


def test_escape_twice_dismisses_and_does_not_exit():
    """The key that opened the menu cannot also be the key that exits through
    it. A stray double-press during a long task must be harmless."""
    host = FakeHost()
    hatch = _hatch(host)

    hatch.key("Escape")
    outcome = hatch.key("Escape")

    assert outcome.menu_open is False
    assert outcome.ends_session is False
    assert "close" not in host.calls


def test_enter_takes_the_default_which_is_keep_working():
    host = FakeHost()
    hatch = _hatch(host)
    hatch.key("Escape")

    outcome = hatch.key("Enter")

    assert outcome.action == escape.KEEP_WORKING
    assert escape.DEFAULT == escape.KEEP_WORKING
    assert "close" not in host.calls


def test_the_default_never_ends_the_session():
    """Asserted on the declaration, so a future edit that made exit the default
    fails here rather than on somebody's machine."""
    assert escape.BY_ACTION[escape.DEFAULT].ends_session is False


def test_keys_do_nothing_until_the_menu_is_open():
    """Otherwise "3" typed into a document would exit the shell."""
    host = FakeHost()
    hatch = _hatch(host)

    for key in ("3", "4", "Enter"):
        outcome = hatch.key(key)
        assert outcome.ends_session is False
    assert host.calls == []


def test_an_unknown_key_says_so_and_leaves_the_menu_open():
    hatch = _hatch()
    hatch.key("Escape")
    outcome = hatch.key("q")
    assert outcome.menu_open is True
    assert "not one of these" in outcome.message


# =============================================================================
# Rule 2: exiting is never silent
# =============================================================================


def test_exiting_checkpoints_pauses_and_records_first():
    host = FakeHost()
    hatch = _hatch(host)
    hatch.key("Escape")

    outcome = hatch.key("3")

    assert outcome.action == escape.EXIT
    assert hatch.done == [escape.PAUSE_TASKS, escape.CHECKPOINT, escape.RECORD_EVENT]
    assert outcome.clean is True
    assert "close" in host.calls


def test_the_pause_comes_before_the_checkpoint():
    """So the checkpoint describes the paused state rather than the running
    one. A checkpoint of a task mid-step restores to a step half-applied."""
    owed = escape.OWED_BEFORE[escape.EXIT]
    assert owed.index(escape.PAUSE_TASKS) < owed.index(escape.CHECKPOINT)


def test_a_missing_checkpoint_is_a_failure_and_not_a_skip():
    """The whole point of the owed list: an exit cannot quietly drop the
    checkpoint, and a caller that forgot to wire one finds out here rather than
    after a restart that lost an afternoon."""
    hatch = escape.Hatch(FakeHost(), before_exit={})
    hatch.key("Escape")

    outcome = hatch.key("3")

    assert outcome.clean is False
    assert any(escape.CHECKPOINT in item for item in outcome.failed)
    assert "not everything was saved" in outcome.message


def test_a_checkpoint_that_raises_still_closes_the_window_and_says_so():
    """An exit must not be blocked by its own bookkeeping - he pressed Escape
    because he wants out - but it must not be reported as clean either."""
    def explode():
        raise RuntimeError("the DBA is unreachable")

    host = FakeHost()
    hatch = _hatch(host, before_exit={escape.CHECKPOINT: explode})
    hatch.key("Escape")

    outcome = hatch.key("3")

    assert "close" in host.calls
    assert outcome.clean is False
    assert "the DBA is unreachable" in " ".join(outcome.failed)
    assert "may not remember" in outcome.message


def test_minimising_owes_nothing_because_nothing_stops():
    host = FakeHost()
    hatch = _hatch(host)
    hatch.key("Escape")

    outcome = hatch.key("2")

    assert outcome.owed == ()
    assert hatch.done == []
    assert host.calls == ["hide"]
    assert "close" not in host.calls


# =============================================================================
# Rule 4: exiting leaves a desktop behind
# =============================================================================


def test_exiting_restores_the_desktop():
    """Free under a kiosk. Under shell replacement it is the difference between
    exiting and a black screen, which is the outcome this feature exists to
    prevent."""
    host = FakeHost()
    hatch = _hatch(host)
    hatch.key("Escape")
    hatch.key("3")

    assert "restore_desktop" in host.calls
    assert escape.RESTORE_DESKTOP in escape.OWED_BEFORE[escape.EXIT]


def test_a_desktop_that_would_not_come_back_is_reported():
    host = FakeHost(desktop_restores=False)
    hatch = _hatch(host)
    hatch.key("Escape")

    outcome = hatch.key("3")

    assert outcome.clean is False
    assert escape.RESTORE_DESKTOP in outcome.failed


def test_restarting_does_not_restore_the_desktop():
    """Jarvis is coming straight back; starting Explorer underneath would leave
    the owner with two shells."""
    host = FakeHost()
    hatch = _hatch(host)
    hatch.key("Escape")
    hatch.key("4")

    assert "restore_desktop" not in host.calls
    assert "request_restart" in host.calls


def test_a_supervisor_that_refuses_the_restart_is_reported():
    host = FakeHost(restart_accepted=False)
    hatch = _hatch(host)
    hatch.key("Escape")

    outcome = hatch.key("4")

    assert outcome.clean is False
    assert "request_restart" in outcome.failed


# =============================================================================
# Rule 3: the menu does not depend on the thing it is escaping from
# =============================================================================


def test_the_menu_is_produced_here_and_not_by_the_page():
    """If the page has hung, failed to load or thrown, Escape must still work.
    An escape hatch that needs the thing it is escaping from is not one."""
    lines = _hatch().lines()
    assert len(lines) == len(escape.OPTIONS)
    assert any("Exit to the desktop" in line for line in lines)
    assert any("(default)" in line for line in lines)


def test_every_option_says_what_it_will_do():
    """He pressed Escape because something was wrong; the menu has to be
    readable by somebody not in the mood to interpret it."""
    for option in escape.OPTIONS:
        assert option.consequence and option.consequence[0].isupper()
        assert option.label


def test_diagnostics_shows_and_keeps_the_menu_open():
    """Dropping him back into the shell after showing him the diagnosis is the
    wrong direction."""
    host = FakeHost()
    hatch = _hatch(host, diagnostics=lambda: "logs are at C:/x/logs")
    hatch.key("Escape")

    outcome = hatch.key("5")

    assert outcome.menu_open is True
    assert host.texts == ["logs are at C:/x/logs"]
    assert "close" not in host.calls


def test_broken_diagnostics_still_say_something():
    """This is the screen somebody reaches when things are already wrong."""
    def explode():
        raise RuntimeError("no log directory")

    host = FakeHost()
    hatch = _hatch(host, diagnostics=explode)
    hatch.key("Escape")
    hatch.key("5")

    assert "could not be gathered" in host.texts[0]
    assert "no log directory" in host.texts[0]


def test_missing_diagnostics_are_reported_rather_than_blank():
    host = FakeHost()
    hatch = _hatch(host, diagnostics=None)
    hatch.key("Escape")
    hatch.key("5")
    assert "itself worth reporting" in host.texts[0]


# =============================================================================
# Rule 5, and the shape of the whole thing
# =============================================================================


def test_there_is_no_password():
    """Being locked into a shell is the opposite of what was asked for."""
    assert escape.describe()["no_password"] is True
    source = (__import__("pathlib").Path(__file__).resolve().parent.parent
              / "desktop" / "escape.py").read_text(encoding="utf-8")
    import ast
    names = {node.id for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Name)}
    assert not (names & {"password", "pin", "passcode", "credential"})


def test_every_action_declares_what_it_owes():
    """A new option added without deciding what it must save first fails here."""
    assert set(escape.OWED_BEFORE) == set(escape.ACTIONS)
    for option in escape.OPTIONS:
        owed = escape.OWED_BEFORE[option.action]
        if option.ends_session:
            assert escape.CHECKPOINT in owed, option.action
            assert escape.PAUSE_TASKS in owed, option.action
        else:
            assert owed == (), option.action


def test_the_hatch_holds_no_state_but_whether_the_menu_is_open():
    """An escape hatch with modes has modes in which it does not work."""
    hatch = _hatch()
    fields = {name for name in vars(hatch)
              if not name.startswith("_") and name != "done"}
    assert fields == {"host", "open", "before_exit", "diagnostics"}


# =============================================================================
# The Gateway side: what the shell asks for when it closes
# =============================================================================


def test_the_closing_sequence_pauses_then_checkpoints(monkeypatch, tmp_path):
    """The shell is a separate process and desktop/ knows nothing about the
    organization, so the sequence lives in the Gateway - which also makes it
    testable instead of living in a pywebview callback nobody can run."""
    import json as _json

    from fastapi.testclient import TestClient

    from dba import agent as agent_module, main as dba_main, registry, store
    from gateway import (checkpoint as checkpoint_module, dbaclient, identity,
                         ledger, persistence, upkeep)

    token = "test-token-for-jarvis"
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), token)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, token)
    monkeypatch.setenv(identity.VERSION_ENV, "f" * 40)
    agent_module._AGENT = None
    registry.reset_sync()
    try:
        with TestClient(dba_main.app) as service:
            def transport(method, path, payload):
                response = service.request(
                    method, path, json=payload if method != "GET" else None,
                    headers={"X-DBA-Agent": "JARVIS", "X-DBA-Token": token})
                try:
                    return response.status_code, response.json()
                except ValueError:
                    return response.status_code, {}

            client = dbaclient.DBAClient(transport=transport)
            monkeypatch.setattr(dbaclient, "DBAClient", lambda **kw: client)

            persistence.put(client, persistence.TASK, "september",
                            {"state": "running", "step": "2 of 4"})
            persistence.put(client, persistence.TASK, "done-already",
                            {"state": "finished"})

            result = upkeep.closing_down(client, reason="the owner pressed Escape")

            assert result["clean"] is True
            assert result["paused"] == ["september"]
            assert result["performed"] == [upkeep.PAUSE_TASKS, upkeep.CHECKPOINT,
                                           upkeep.RECORD_EVENT]
            # The pause is visible in the state the checkpoint then describes.
            assert persistence.get(client, persistence.TASK,
                                   "september")["state"] == "paused"
            assert persistence.get(client, persistence.TASK,
                                   "done-already")["state"] == "finished"
            assert result["checkpoint"].startswith("checkpoint_")
            assert ledger.tip(client)["event_type"] == ledger.STATE_TRANSITION
            assert "Escape" in ledger.tip(client)["name"]
    finally:
        agent_module._AGENT = None
        registry.reset_sync()


def test_closing_without_a_reachable_store_reports_rather_than_raises(monkeypatch):
    from gateway import dbaclient, upkeep

    monkeypatch.delenv(dbaclient.TOKEN_ENV, raising=False)
    result = upkeep.closing_down()

    assert result["performed"] == []
    assert any("no DBA token" in item for item in result["failed"])


def test_the_shell_reports_a_missing_token_as_a_failure_not_a_skip(monkeypatch):
    """A silent skip here would be the exact failure OWED_BEFORE exists to
    prevent - the window closes, and Jarvis quietly forgets the afternoon."""
    from desktop import shell

    monkeypatch.delenv(shell.SHELL_TOKEN_ENV, raising=False)
    result = shell.closing_steps("http://127.0.0.1:8100", "test")

    assert result["performed"] == []
    assert any(shell.SHELL_TOKEN_ENV in item for item in result["failed"])


def test_the_shells_owed_steps_are_the_gateways_owed_steps():
    """Two lists of the same three strings in two packages. If they drift, an
    exit reports a step done that the Gateway never performed."""
    from gateway import upkeep

    from desktop import escape

    assert {upkeep.PAUSE_TASKS, upkeep.CHECKPOINT, upkeep.RECORD_EVENT} == {
        escape.PAUSE_TASKS, escape.CHECKPOINT, escape.RECORD_EVENT}


def test_fullscreen_is_off_unless_asked_for(monkeypatch):
    """So a developer opening the window is not suddenly unable to see anything
    else."""
    from desktop import shell

    monkeypatch.delenv(shell.FULLSCREEN_ENV, raising=False)
    assert shell.fullscreen_wanted() is False
    monkeypatch.setenv(shell.FULLSCREEN_ENV, "1")
    assert shell.fullscreen_wanted() is True
    assert shell.fullscreen_wanted(False) is False, "an explicit argument wins"


def test_the_escape_key_is_scoped_to_jarvis_and_not_global():
    """A global Escape would steal the key from Excel the moment Jarvis opens it
    for him, which is the one thing this shell exists to do."""
    from desktop import shell

    assert "addEventListener('keydown'" in shell.ESCAPE_SCRIPT
    assert "RegisterHotKey" not in shell.ESCAPE_SCRIPT
    for global_api in ("keyboard.add_hotkey", "GlobalHotKey", "win32con.MOD_"):
        assert global_api not in shell.ESCAPE_SCRIPT


def test_the_menu_is_a_second_window_not_an_overlay_in_the_page():
    """An escape hatch that renders through the thing it is escaping from does
    not work when that thing has hung, which is when it is wanted."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "desktop" / "shell.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    host = next(node for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef) and node.name == "WebviewHost")
    show_menu = next(node for node in host.body
                     if isinstance(node, ast.FunctionDef) and node.name == "show_menu")
    called = {node.func.attr for node in ast.walk(show_menu)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "create_window" in called
    assert "run_js" not in called, "the menu must not be injected into the page"


# =============================================================================
# The failsafe below the escape hatch
# =============================================================================


def _supervisor() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parent.parent
            / "scripts" / "keep-jarvis-up.ps1").read_text(encoding="utf-8")


def test_the_supervisor_stops_relaunching_a_build_that_will_not_come_up():
    """Five identical failures is not bad luck, and a loop that restarts a
    broken build for ever is how a machine becomes unusable while appearing to
    be looked after."""
    import re

    script = _supervisor()
    assert re.search(r"\$maxFailures\s*=\s*\d+", script)
    assert re.search(r"if \(\$gwFailures -ge \$maxFailures\)", script)
    assert "standing down" in script
    # and it says where to look, because standing down silently is no better
    # than looping silently
    assert "gateway.err.log" in script


def test_standing_down_makes_sure_a_desktop_exists():
    """The precondition for TQ-116b. Under a kiosk it costs nothing; under shell
    replacement it is the difference between a recoverable machine and a black
    screen - and it has to exist and be exercised BEFORE the shell is the only
    thing Windows starts."""
    import re

    script = _supervisor()
    assert re.search(r"function Ensure-Desktop", script)
    assert re.search(r"Start-Process explorer\.exe", script)
    body = script[script.index("if ($gwFailures -ge $maxFailures)"):]
    assert "Ensure-Desktop" in body[:600], (
        "standing down must ensure a desktop, not merely be able to")


def test_a_recovered_gateway_clears_the_failure_count():
    """Otherwise the count only ever rises and the supervisor stands down over
    five failures spread across a month."""
    script = _supervisor()
    assert "gateway is back after" in script
    assert "$gwFailures = 0" in script


def test_the_shell_can_ask_the_supervisor_to_restart_and_it_listens():
    """Both halves: the shell writes the marker, the supervisor acts on it and
    removes it. A marker nobody clears is a restart loop."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "desktop" / "shell.py").read_text(encoding="utf-8")
    assert "RESTART-REQUESTED" in source

    script = _supervisor()
    assert "RESTART-REQUESTED" in script
    assert "restart requested by the shell" in script
    assert "Remove-Item $restartReq" in script


# =============================================================================
# The hatch is actually connected to the window
# =============================================================================


class _Signal:
    """pywebview's event slot: `window.events.loaded += handler`.

    A list will not do. `+=` on a list of one callable raises, and modelling it
    wrongly is how a fake proves the wiring works against an API that does not
    exist."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __bool__(self):
        return bool(self.handlers)

    def __getitem__(self, index):
        return self.handlers[index]


class _FakeEvents:
    def __init__(self):
        self.loaded = _Signal()


class _FakeWindow:
    def __init__(self):
        self.exposed = []
        self.events = _FakeEvents()
        self.scripts = []
        self.destroyed = False

    def expose(self, *functions):
        self.exposed.extend(functions)

    def run_js(self, script):
        self.scripts.append(script)

    def destroy(self):
        self.destroyed = True

    def hide(self):
        pass


class _FakeWebview:
    """Enough of pywebview to prove the wiring runs, and nothing more."""

    def __init__(self):
        self.window = _FakeWindow()
        self.created = []
        self.started = False

    def create_window(self, title, **kwargs):
        self.created.append({"title": title, **kwargs})
        return self.window

    def start(self, *args, **kwargs):
        self.started = True


@pytest.fixture()
def fake_webview(monkeypatch):
    import sys

    fake = _FakeWebview()
    monkeypatch.setitem(sys.modules, "webview", fake)
    return fake


def test_running_the_shell_actually_binds_the_escape_hatch(fake_webview):
    """Probing found this missing: the hatch was fully tested and NOTHING
    asserted it was connected. Removing the wiring from `run()` broke no test,
    which is the machinery-with-no-user problem turned on the escape hatch of
    all things."""
    from desktop import shell

    shell.run("http://127.0.0.1:8100/voice", fullscreen=True)

    window = fake_webview.window
    assert fake_webview.started is True
    assert window.exposed, "nothing was exposed to the page, so Escape cannot reach Python"
    # The exposed callable is the hatch's key handler, and calling it opens the menu.
    assert any(getattr(fn, "__name__", "") == "key" for fn in window.exposed)
    # And the listener is injected once the page has loaded.
    assert window.events.loaded, "no loaded handler, so the key listener is never installed"
    window.events.loaded[0]()
    assert any("keydown" in script for script in window.scripts)


def test_the_window_is_created_fullscreen_when_asked(fake_webview):
    from desktop import shell

    shell.run("http://127.0.0.1:8100/voice", fullscreen=True)
    assert fake_webview.created[0]["fullscreen"] is True

    fake_webview.created.clear()
    shell.run("http://127.0.0.1:8100/voice", fullscreen=False)
    assert fake_webview.created[0]["fullscreen"] is False


def test_pressing_escape_through_the_exposed_bridge_opens_the_menu(fake_webview):
    """End to end through the real wiring: the page's keydown reaches
    `escape.Hatch` and a second window is created for the menu."""
    from desktop import shell

    shell.run("http://127.0.0.1:8100/voice", fullscreen=True)
    key = next(fn for fn in fake_webview.window.exposed
               if getattr(fn, "__name__", "") == "key")

    outcome = key("Escape")

    assert outcome.menu_open is True
    menus = [row for row in fake_webview.created if row["title"] == "Jarvis"]
    assert menus, "the escape menu was not opened"
    assert "html" in menus[0], "the menu must not depend on the page it escapes"


def test_a_window_that_cannot_bind_the_hatch_says_so_and_still_runs(fake_webview, capsys):
    """§15: a failing renderer must not cost the operator the console. But a
    fullscreen window whose Escape does nothing must be announced before he is
    looking at it."""
    from desktop import shell

    def broken(host, url):
        raise RuntimeError("no bridge available")

    shell.run("http://127.0.0.1:8100/voice", fullscreen=True, hatch_factory=broken)

    assert fake_webview.started is True, "the shell must still open"
    said = capsys.readouterr().err
    assert "ESCAPE HATCH COULD NOT BE BOUND" in said
    assert "Alt+F4" in said
