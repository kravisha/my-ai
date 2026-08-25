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


def available() -> bool:
    """Whether a native shell can be opened at all on this machine."""
    try:
        import webview  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means no shell
        return False
    return True


def run(url: str, *, waking: bool = True) -> None:
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
    print(f"[desktop] {'resuming' if waking else 'opening'} the workspace at {url}")
    webview.create_window(
        WINDOW_TITLE,
        url=url,                       # never html= - see the module docstring
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        text_select=True,              # an operator copying an event id is normal
        confirm_close=False,           # closing is sleep, not loss (§4.2)
    )
    try:
        webview.start()
    except Exception as exc:  # noqa: BLE001 - §15: the renderer failing is not fatal
        print(
            f"[desktop] the window could not be opened ({type(exc).__name__}: {exc}).\n"
            f"[desktop] the organization is still running - the console is at {url}.",
            file=sys.stderr,
        )
