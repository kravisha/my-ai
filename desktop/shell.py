"""The native window (addendum 40 §7; TQ-30, docs/SPEC_RECONCILIATION.md §82).

A resident workspace rather than a browser tab: native startup, native
lifecycle, and the console inside it. §7.1's rule is what keeps this thin —
"the UI layer must remain separable from COO logic. The backend should not
care whether the current window is native desktop, browser Gateway, future
mobile, or another surface." So this module knows how to open a window and
nothing about the organization.

## It hosts the existing console, and does not reimplement it

§18's Phase A says "move the existing web views into the shell ... without
changing core business logic". The console is already one dependency-free file
over a handful of read endpoints, so the shell points at it. A second
implementation of the same views would be two sources of truth about what the
organization looks like, and they would drift.

## Loaded over loopback, never as inline HTML

Measured, not assumed (§82): a pywebview window given an HTML *string* has no
origin, and therefore no secure context — `getUserMedia` is absent,
`localStorage` throws, and with them goes the microphone that addendum 40 §11
makes the default input path. The same page served from `http://127.0.0.1`
reports `secureContext: true` and all of it works, because Chromium treats
loopback as secure. Hence `url=`, and hence the runtime starting first.

## Degrading rather than failing

§15: "If a renderer or avatar subsystem fails, the COO must remain usable
through fallback text/voice interfaces." A shell that cannot open a window
says where the console is and exits cleanly, rather than taking the runtime
down with it - the operator still has a browser.
"""

from __future__ import annotations

import sys

WINDOW_TITLE = "My AI — COO"

# FULLSCREEN, on the owner's instruction of 2026-09-23: *"a full fledged shell
# that on startup covers the whole of windows screen and not just a window"*.
#
# A kiosk over a running Explorer, NOT a shell replacement. Alt-Tab still works,
# the taskbar is still underneath, and nothing has been written to the registry.
# Replacing explorer.exe (TQ-116b) is a separate, frozen decision, because a bug
# in Jarvis would then mean a machine that logs in to nothing.
#
# Off by default and on by `--fullscreen` or JARVIS_SHELL_FULLSCREEN, so that a
# developer opening the window is not suddenly unable to see anything else.
FULLSCREEN_ENV = "JARVIS_SHELL_FULLSCREEN"

# How the escape hatch reaches Python from the page. See `desktop/escape.py` for
# what it then decides - none of that is here, because none of it needs Windows.
#
# Scoped to this window rather than a global hotkey, deliberately: a global
# Escape would steal the key from Excel the moment Jarvis opens it for him,
# which is the one thing this shell exists to do.
ESCAPE_SCRIPT = """
(function () {
  if (window.__jarvisEscapeBound) { return; }
  window.__jarvisEscapeBound = true;
  document.addEventListener('keydown', function (event) {
    var name = event.key;
    if (name !== 'Escape' && !window.__jarvisMenuOpen) { return; }
    if (window.pywebview && window.pywebview.api && window.pywebview.api.key) {
      event.preventDefault();
      window.pywebview.api.key(name);
    }
  }, true);
})();
"""
# Sized for the console's two-thirds/one-third split rather than a square: the
# desks need width, and the COO conversation needs a readable line length.
DEFAULT_WIDTH = 1440
DEFAULT_HEIGHT = 900
MIN_WIDTH = 1024
MIN_HEIGHT = 680


def claim_taskbar_identity() -> None:
    """Tell Windows this window belongs to My AI, not to Python.

    Without an explicit AppUserModelID the shell groups the window under
    `python.exe`, so the taskbar button is Python's - pinning it pins Python,
    and launching from the pin produces a second button unrelated to the
    running window. The id must match the one stamped on the Start Menu
    shortcut exactly (`desktop/install.py`), because the taskbar treats two
    different ids as two different applications.

    Best-effort by design: on a machine where this fails the window still
    opens, it just groups under Python. A launcher that refused to start over
    a taskbar grouping detail would be trading the application for its icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        from desktop.install import APP_ID

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001
        pass


def fullscreen_wanted(override: bool | None = None) -> bool:
    """Whether to cover the screen. Explicit argument wins over environment."""
    if override is not None:
        return override
    import os

    return (os.environ.get(FULLSCREEN_ENV, "") or "").strip() in ("1", "true", "yes")


class WebviewHost:
    """The effects `desktop/escape.Hatch` asks for, against a pywebview window.

    Every method here is one effect with no decision in it. That is the whole
    split: the decisions are in `escape.py` and are tested, and this file cannot
    be tested from a machine without Windows, so it is not allowed to decide
    anything.

    The menu is a SECOND window rather than an overlay injected into the page.
    An escape hatch that renders itself through the thing it is escaping from
    does not work when that thing has hung, which is when it is wanted."""

    def __init__(self, window, *, closing=None) -> None:
        self.window = window
        self.menu = None
        self._closing = closing

    def hide(self) -> None:
        self.window.hide()

    def close(self) -> None:
        self._dismiss_menu()
        self.window.destroy()

    def show_menu(self, lines: list[str]) -> None:
        import webview

        self._dismiss_menu()
        body = "<br>".join(lines)
        self.menu = webview.create_window(
            "Jarvis", html=_MENU_HTML.replace("{{BODY}}", body),
            width=520, height=300, frameless=False, on_top=True)

    def show_text(self, text: str) -> None:
        import webview

        self._dismiss_menu()
        self.menu = webview.create_window(
            "Jarvis — diagnostics",
            html=_MENU_HTML.replace("{{BODY}}", text.replace("\n", "<br>")),
            width=720, height=480, on_top=True)

    def _dismiss_menu(self) -> None:
        if self.menu is not None:
            try:
                self.menu.destroy()
            except Exception:  # noqa: BLE001 - a menu that is already gone
                pass
            self.menu = None

    def restore_desktop(self) -> bool:
        """Start Explorer if it is not running.

        A no-op under a kiosk, where Explorer never stopped - and the difference
        between exiting and a black screen under shell replacement. Written now
        so that TQ-116b, when it is taken, is a configuration change rather than
        a new piece of code written under pressure."""
        if sys.platform != "win32":
            return True
        import subprocess

        try:
            running = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq explorer.exe"],
                capture_output=True, text=True, timeout=10, check=False)
            if "explorer.exe" in (running.stdout or ""):
                return True
            subprocess.Popen(["explorer.exe"])
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def request_restart(self) -> bool:
        """Ask the supervisor to start everything again.

        A file rather than a signal, for the reason `gateway/selfmod.py` writes
        one: the supervisor is a separate process on its own loop, and a request
        it can pick up when it next looks is more robust than one that needs it
        to be listening at the moment it is sent."""
        from pathlib import Path

        try:
            marker = Path(__file__).resolve().parent.parent / "RESTART-REQUESTED"
            marker.write_text("requested by the shell\n", encoding="utf-8")
            return True
        except OSError:
            return False


_MENU_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>
 body { font: 16px/1.6 "Segoe UI", system-ui, sans-serif; background: #12141a;
        color: #e8eaf0; margin: 0; padding: 28px; }
 h1 { font-size: 15px; letter-spacing: .08em; text-transform: uppercase;
      color: #8b93a7; margin: 0 0 18px; font-weight: 600; }
 .body { white-space: normal; }
 .hint { margin-top: 22px; color: #8b93a7; font-size: 14px; }
</style></head><body>
<h1>Jarvis</h1><div class="body">{{BODY}}</div>
<div class="hint">Press the number, or Escape to go back.</div>
</body></html>"""


# How the shell authenticates to its own Gateway when it closes. The route that
# pauses work and checkpoints sits behind `session`, because an unauthenticated
# caller able to make Jarvis stop what he is doing would be a denial of service
# with a friendly name.
#
# OPEN, and deliberately failing loudly rather than quietly: if no token is
# configured the owed steps are reported as FAILED, the window still closes, and
# the owner is told that the last few minutes may not be remembered. A silent
# skip here would be the exact failure `escape.OWED_BEFORE` exists to prevent.
SHELL_TOKEN_ENV = "JARVIS_SHELL_TOKEN"

CLOSING_PATH = "/shell/closing"
CLOSING_TIMEOUT_SECONDS = 20


def closing_steps(url: str, reason: str) -> dict:
    """Ask the Gateway to do what is owed, and report what it managed.

    One HTTP call rather than three, because the order matters and the Gateway
    is where that order is written down (`gateway/upkeep.closing_down`)."""
    import os

    import requests

    token = (os.environ.get(SHELL_TOKEN_ENV, "") or "").strip()
    if not token:
        return {"performed": [], "failed": [
            f"no {SHELL_TOKEN_ENV} is configured, so nothing could be saved"]}
    try:
        response = requests.post(
            f"{url.rstrip('/')}{CLOSING_PATH}", params={"reason": reason},
            headers={"Authorization": f"Bearer {token}"},
            timeout=CLOSING_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - any transport failure is a failure
        return {"performed": [], "failed": [f"the Gateway did not answer: {exc}"]}
    if response.status_code != 200:
        return {"performed": [], "failed": [
            f"the Gateway answered {response.status_code}"]}
    try:
        return response.json()
    except ValueError:
        return {"performed": [], "failed": ["the Gateway's answer was not JSON"]}


def _default_hatch(host, url: str):
    """Wire `escape.Hatch` to this Gateway.

    Each owed step is a callable that raises on failure, because that is the
    contract `Hatch._settle` reads: a step that raises is recorded as failed and
    the exit is not reported as clean."""
    from desktop import escape

    state = {"asked": False, "result": None}

    def ask_once():
        if not state["asked"]:
            state["result"] = closing_steps(url, "the owner closed the shell")
            state["asked"] = True
        return state["result"]

    def step(name):
        def run():
            result = ask_once()
            if name not in (result.get("performed") or []):
                raise RuntimeError("; ".join(result.get("failed") or ["not done"]))
        return run

    return escape.Hatch(
        host,
        before_exit={name: step(name) for name in
                     (escape.PAUSE_TASKS, escape.CHECKPOINT, escape.RECORD_EVENT)},
        diagnostics=lambda: _diagnostics(url))


def _diagnostics(url: str) -> str:
    """What to show somebody who pressed Escape because something was wrong.

    Paths first, because the next thing he does is send them to somebody."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    lines = [f"Gateway:   {url}",
             f"Logs:      {root / 'logs'}",
             f"Crashes:   {root / 'logs' / 'crashes'}",
             f"Startups:  {root / 'logs' / 'startup.jsonl'}",
             f"Supervisor:{root / 'logs' / 'gateway.err.log'}"]
    try:
        import requests

        health = requests.get(f"{url.rstrip('/')}/health", timeout=5)
        lines.append(f"Health:    {health.status_code} {health.text[:200]}")
    except Exception as exc:  # noqa: BLE001 - this screen must always render
        lines.append(f"Health:    unreachable ({exc})")
    return "\n".join(lines)


def available() -> bool:
    """Whether a native shell can be opened at all on this machine."""
    try:
        import webview  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means no shell
        return False
    return True


def run(url: str, *, waking: bool = True, fullscreen: bool | None = None,
        hatch_factory=None) -> None:
    """Open the window on `url` and block until the operator closes it.

    Returns normally when the window closes - which is the signal for the
    bootstrap to put the runtime back to sleep (§4.2's "normal shutdown
    should behave like putting the organization to sleep")."""
    if not available():
        print(
            "[desktop] no native shell available (pywebview is not installed).\n"
            f"[desktop] the console is served at {url} - open it in a browser.",
            file=sys.stderr,
        )
        return

    import webview

    claim_taskbar_identity()
    covering = fullscreen_wanted(fullscreen)
    print(f"[desktop] {'resuming' if waking else 'opening'} the workspace at {url}"
          f"{' (fullscreen)' if covering else ''}")
    window = webview.create_window(
        WINDOW_TITLE,
        url=url,                       # never html= - see the module docstring
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        fullscreen=covering,
        text_select=True,              # an operator copying an event id is normal
        confirm_close=False,           # closing is sleep, not loss (§4.2)
    )

    # The escape hatch. Bound before the window is shown, because a window the
    # owner cannot leave is one he should never have been given.
    #
    # Guarded, because §15 says a failing renderer must not cost the operator the
    # console - and the first version of this wiring broke that: with a pywebview
    # that returned something unexpected it raised, and the runtime went down
    # with it. `tests/test_desktop_bootstrap.py` caught it, which is what that
    # test is for.
    #
    # A window with no escape hatch is reported loudly rather than opened
    # quietly: it is still usable (Alt+F4 closes it) and the owner needs to know
    # that Escape will not work before he is looking at a fullscreen window.
    try:
        hatch = (hatch_factory or _default_hatch)(WebviewHost(window), url)
        window.expose(hatch.key)
        window.events.loaded += lambda: window.run_js(ESCAPE_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - see above
        print(f"[desktop] THE ESCAPE HATCH COULD NOT BE BOUND "
              f"({type(exc).__name__}: {exc}).\n"
              f"[desktop] Escape will not open the menu. Alt+F4 still closes the "
              f"window, and the console is at {url}.", file=sys.stderr)

    try:
        webview.start()
    except Exception as exc:  # noqa: BLE001 - §15: the renderer failing is not fatal
        print(
            f"[desktop] the window could not be opened ({type(exc).__name__}: {exc}).\n"
            f"[desktop] the organization is still running - the console is at {url}.",
            file=sys.stderr,
        )
