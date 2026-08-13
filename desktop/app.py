"""Entry point for My AI's desktop GUI. Run as `python -m desktop.app` from
the my-ai/ project root (not `cd desktop && python app.py` like vibe-agent -
these modules use absolute imports like `from app.main import chat_turn`
since app/ is a sibling package, not a server this talks to over HTTP).

Structure mirrors vibe-agent's desktop/app.py almost exactly: a single Tk
root, frame-swap navigation between LoginScreen and DashboardScreen, driven
by an on_success/on_logout callback pair instead of any router.
"""

import tkinter as tk

from app.session import SessionStore
from app.users import UserStore
from desktop.screens.dashboard import DashboardScreen
from desktop.screens.login import LoginScreen
from desktop.session_context import build_session


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("My AI")
        self.root.geometry("700x600")
        self.users = UserStore()
        self.sessions = SessionStore()
        self.current_screen = None

        username = self.sessions.validate()
        if username is not None:
            self._show_dashboard(username)
        else:
            self._show_login()

    def _show_login(self):
        self._set_screen(LoginScreen(self.root, self.users, self.sessions, on_success=self._show_dashboard))

    def _show_dashboard(self, username):
        session = build_session(username)
        self._set_screen(DashboardScreen(self.root, session, self.sessions, on_logout=self._show_login))

    def _set_screen(self, screen):
        if self.current_screen is not None:
            self.current_screen.destroy()
        self.current_screen = screen
        self.current_screen.pack(fill=tk.BOTH, expand=True)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
