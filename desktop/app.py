"""Entry point for My AI's desktop GUI. Run as `python -m desktop.app` from
the my-ai/ project root. Now a thin HTTP client (Milestone 4): talks to
backend/main.py over HTTP via api_client.APIClient instead of touching
app/*.py stores directly - the backend must be running first
(`uvicorn backend.main:app --reload`).

Structure is otherwise unchanged from before: a single Tk root, frame-swap
navigation between LoginScreen and DashboardScreen via an on_success/
on_logout callback pair. The "Welcome back" session-skip convenience (which
vibe-agent's own desktop client doesn't have, but this project already
built and shouldn't regress) now works by caching the bearer token locally
and verifying it against GET /auth/me on launch, rather than checking a
local SessionStore file - a separate cache file from the CLI's
(.gui_session vs .cli_session) so running both at once doesn't clobber
each other.
"""

import tkinter as tk
from pathlib import Path

from api_client import APIClient, APIError
from desktop.screens.dashboard import DashboardScreen
from desktop.screens.login import LoginScreen

GUI_SESSION_PATH = Path(__file__).resolve().parent.parent / ".gui_session"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("My AI")
        self.root.geometry("700x600")
        self.client = APIClient()
        self.current_screen = None

        username = self._load_cached_session()
        if username is not None:
            self._show_dashboard(username)
        else:
            self._show_login()

    def _load_cached_session(self) -> str | None:
        if not GUI_SESSION_PATH.exists():
            return None
        token = GUI_SESSION_PATH.read_text(encoding="utf-8").strip()
        if not token:
            return None
        self.client.token = token
        try:
            return self.client.me()
        except APIError:
            self.client.token = None
            GUI_SESSION_PATH.unlink(missing_ok=True)
            return None

    def _show_login(self):
        self._set_screen(LoginScreen(self.root, self.client, on_success=self._show_dashboard))

    def _show_dashboard(self, username):
        GUI_SESSION_PATH.write_text(self.client.token, encoding="utf-8")
        self._set_screen(DashboardScreen(self.root, self.client, username, on_logout=self._handle_logout))

    def _handle_logout(self):
        GUI_SESSION_PATH.unlink(missing_ok=True)
        self._show_login()

    def _set_screen(self, screen):
        if self.current_screen is not None:
            self.current_screen.destroy()
        self.current_screen = screen
        self.current_screen.pack(fill=tk.BOTH, expand=True)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
