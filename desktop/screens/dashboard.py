"""Main dashboard screen: Chat / Access & Privacy / Activity tabs. Mirrors
vibe-agent's desktop/screens/dashboard.py structure (ttk.Notebook, one
tk.Frame per tab, <<NotebookTabChanged>> refresh) but calls app.main's
existing chat_turn()/tool logic directly in-process instead of an HTTP
client - there's no server here.

The one new piece vibe-agent's dashboard doesn't need: a way to answer the
"needs_consent" pause that chat_turn's tool-use loop can hit mid-reply.
That pause happens on the background thread the chat call runs on (same
threading.Thread + self.after(0, ...) pattern vibe-agent already uses for
its own chat send handler), so it can't just pop a dialog directly - see
_gui_resolve_consent/ConsentDialog below for the thread-safe bridge.
"""

import json
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from app.main import chat_turn
from app.permissions import RESOURCE_PATHS
from desktop.session_context import AppSession


class ConsentDialog(tk.Toplevel):
    """Always/Once/Never prompt, the GUI equivalent of main.py's
    resolve_consent(). Closing the window (instead of picking a button) is
    treated as "once" - the least-committal choice - rather than leaving the
    waiting background thread hung forever."""

    def __init__(self, parent, prompt: str, on_choice):
        super().__init__(parent)
        self.title("My AI needs your input")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=prompt, wraplength=360, justify=tk.LEFT).pack(padx=16, pady=(16, 12))

        button_frame = tk.Frame(self)
        button_frame.pack(pady=(0, 16))
        for label, choice in (("Always", "always"), ("Once", "once"), ("Never", "never")):
            tk.Button(button_frame, text=label, width=8, command=lambda c=choice: self._choose(c, on_choice)).pack(
                side=tk.LEFT, padx=4
            )

        self.protocol("WM_DELETE_WINDOW", lambda: self._choose("once", on_choice))

    def _choose(self, choice, on_choice):
        on_choice(choice)
        self.destroy()


class DashboardScreen(tk.Frame):
    def __init__(self, root, session: AppSession, sessions, on_logout):
        super().__init__(root)
        self.session = session
        self.sessions = sessions
        self.on_logout = on_logout

        header = tk.Frame(self)
        header.pack(fill=tk.X, padx=8, pady=(8, 0))
        tk.Label(header, text=f"Logged in as {session.username}", font=("", 10, "bold")).pack(side=tk.LEFT)
        tk.Button(header, text="Logout", command=self._logout).pack(side=tk.RIGHT)

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.chat_tab = tk.Frame(notebook)
        self.access_tab = tk.Frame(notebook)
        self.activity_tab = tk.Frame(notebook)

        notebook.add(self.chat_tab, text="Chat")
        notebook.add(self.access_tab, text="Access & Privacy")
        notebook.add(self.activity_tab, text="Activity")
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_chat_tab()
        self._build_access_tab()
        self._build_activity_tab()

    def _logout(self):
        self.sessions.revoke()
        self.on_logout()

    # --- Chat tab ---

    def _build_chat_tab(self):
        self.chat_area = scrolledtext.ScrolledText(self.chat_tab, wrap=tk.WORD, state="disabled")
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        input_frame = tk.Frame(self.chat_tab)
        input_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.entry = tk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda event: self._send_message())

        tk.Button(input_frame, text="Send", command=self._send_message).pack(side=tk.LEFT, padx=(8, 0))

    def _append_chat_line(self, text):
        self.chat_area.configure(state="normal")
        self.chat_area.insert(tk.END, text + "\n")
        self.chat_area.configure(state="disabled")
        self.chat_area.see(tk.END)

    def _send_message(self):
        user_text = self.entry.get().strip()
        if not user_text:
            return
        self.entry.delete(0, tk.END)
        self._append_chat_line(f"You: {user_text}")
        threading.Thread(target=self._get_reply, args=(user_text,), daemon=True).start()

    def _get_reply(self, user_text):
        try:
            reply = chat_turn(
                user_text,
                self.session.messages,
                self.session.permissions,
                self.session.preferences,
                self.session.audit_log,
                resolve_consent_fn=self._gui_resolve_consent,
            )
        except Exception as exc:
            reply = f"[Error contacting My AI: {exc}]"
        self.after(0, self._append_chat_line, f"My AI: {reply}")
        self.after(0, self._refresh_access_tab)

    def _gui_resolve_consent(self, result, preferences):
        """Runs on the background chat thread (see _get_reply). Schedules
        the actual dialog on the main thread via self.after(0, ...) - only
        the main thread may touch Tk widgets - then blocks this thread on a
        plain threading.Event until the user answers. This is the same
        hand-off direction vibe-agent's dashboard.py already uses
        (background thread -> self.after(0, callback)), just also waiting
        for a reply to come back the other way."""
        answer_box = {}
        done = threading.Event()

        def show_dialog():
            def on_choice(choice):
                if choice in ("always", "never"):
                    preferences.set(result["consent_key"], choice)
                answer_box["answer"] = choice
                done.set()

            ConsentDialog(self, result["prompt"], on_choice)

        self.after(0, show_dialog)
        done.wait()
        return answer_box["answer"]

    # --- Access & Privacy tab ---

    def _build_access_tab(self):
        tk.Label(self.access_tab, text="Resource Access", font=("", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 4))

        self.resource_status_labels = {}
        for resource in RESOURCE_PATHS:
            row = tk.Frame(self.access_tab)
            row.pack(fill=tk.X, padx=8, pady=2)
            tk.Label(row, text=resource, width=16, anchor="w").pack(side=tk.LEFT)
            status_label = tk.Label(row, text="", width=14, anchor="w")
            status_label.pack(side=tk.LEFT)
            tk.Button(row, text="Grant", command=lambda r=resource: self._grant(r)).pack(side=tk.LEFT, padx=4)
            tk.Button(row, text="Revoke", command=lambda r=resource: self._revoke(r)).pack(side=tk.LEFT, padx=4)
            self.resource_status_labels[resource] = status_label

        tk.Label(self.access_tab, text="Privacy Preferences", font=("", 11, "bold")).pack(
            anchor="w", padx=8, pady=(16, 4)
        )

        pref_toolbar = tk.Frame(self.access_tab)
        pref_toolbar.pack(fill=tk.X, padx=8)
        tk.Button(pref_toolbar, text="Reset Selected", command=self._reset_selected_preference).pack(side=tk.LEFT)

        columns = ("key", "disposition", "set_at")
        self.preferences_tree = ttk.Treeview(self.access_tab, columns=columns, show="headings", height=6)
        for col, label in zip(columns, ("Key", "Disposition", "Set At")):
            self.preferences_tree.heading(col, text=label)
        self.preferences_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        self._refresh_access_tab()

    def _grant(self, resource):
        self.session.permissions.grant(resource)
        self._refresh_access_tab()

    def _revoke(self, resource):
        self.session.permissions.revoke(resource)
        self._refresh_access_tab()

    def _reset_selected_preference(self):
        selection = self.preferences_tree.selection()
        if not selection:
            return
        key = self.preferences_tree.item(selection[0], "values")[0]
        self.session.preferences.forget(key)
        self._refresh_access_tab()

    def _refresh_access_tab(self):
        for resource, label in self.resource_status_labels.items():
            granted = self.session.permissions.is_granted(resource)
            label.configure(text="Granted" if granted else "Not granted")

        self.preferences_tree.delete(*self.preferences_tree.get_children())
        for key, entry in self.session.preferences.list_all().items():
            self.preferences_tree.insert("", tk.END, values=(key, entry["disposition"], entry["set_at"]))

    # --- Activity tab ---

    def _build_activity_tab(self):
        toolbar = tk.Frame(self.activity_tab)
        toolbar.pack(fill=tk.X, padx=8, pady=8)
        tk.Button(toolbar, text="Refresh", command=self._refresh_activity).pack(side=tk.LEFT)

        columns = ("timestamp", "action", "resource", "authorized", "result")
        self.activity_tree = ttk.Treeview(self.activity_tab, columns=columns, show="headings")
        for col, label in zip(columns, ("Timestamp", "Action", "Resource", "Authorized", "Result")):
            self.activity_tree.heading(col, text=label)
        self.activity_tree.column("result", width=280)
        self.activity_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._refresh_activity()

    def _refresh_activity(self):
        self.activity_tree.delete(*self.activity_tree.get_children())
        path = self.session.audit_log.path
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            self.activity_tree.insert(
                "",
                tk.END,
                values=(entry["timestamp"], entry["action"], entry["resource"], entry["authorized"], entry["result"]),
            )

    def _on_tab_changed(self, event):
        tab_text = event.widget.tab(event.widget.select(), "text")
        if tab_text == "Access & Privacy":
            self._refresh_access_tab()
        elif tab_text == "Activity":
            self._refresh_activity()
