"""Main dashboard screen: Chat / Access & Privacy / Activity tabs. Same
tab structure and widget choices as before - only the plumbing changed,
from calling app/*.py stores directly (in-process) to calling
api_client.APIClient over HTTP, now that backend/main.py owns all of that.

The consent-pause bridge got simpler with the HTTP move: no more
threading.Event blocking a worker thread waiting for a dialog answer.
Instead, a chat call either succeeds (reply) or pauses (needs_consent) as
just another possible response shape - answering the dialog kicks off a
*second* background-thread HTTP call (with the answer attached) rather than
unblocking anything. Still runs on background threads throughout
(threading.Thread + self.after(0, ...)) so the window never freezes during
a call.
"""

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from api_client import APIClient, APIError


class ConsentDialog(tk.Toplevel):
    """Always/Once/Never prompt. Closing the window (instead of picking a
    button) is treated as "once" - the least-committal choice."""

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
    def __init__(self, root, client: APIClient, username: str, on_logout):
        super().__init__(root)
        self.client = client
        self.username = username
        self.on_logout = on_logout
        self.messages: list = []

        header = tk.Frame(self)
        header.pack(fill=tk.X, padx=8, pady=(8, 0))
        tk.Label(header, text=f"Logged in as {username}", font=("", 10, "bold")).pack(side=tk.LEFT)
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
        self.client.logout()
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
        self.messages.append({"role": "user", "content": user_text})
        try:
            body = self.client.chat(self.messages)
        except APIError as exc:
            self.after(0, self._append_chat_line, f"[Error contacting My AI: {exc}]")
            return
        self._handle_chat_response(body)

    def _handle_chat_response(self, body):
        """Runs on whichever background thread made the call. A reply ends
        the turn; needs_consent shows a dialog on the main thread and waits
        for a button click to kick off the resume call - no thread-blocking
        needed, unlike the old in-process bridge, since this is now just
        two independent HTTP calls instead of one paused function call."""
        self.messages[:] = body["messages"]
        if "needs_consent" in body:
            prompt = body["needs_consent"]["prompt"]
            consent_key = body["needs_consent"]["consent_key"]
            self.after(0, self._show_consent_dialog, prompt, consent_key)
            return
        self.after(0, self._append_chat_line, f"My AI: {body['reply']}")
        self.after(0, self._refresh_access_tab)

    def _show_consent_dialog(self, prompt, consent_key):
        def on_choice(choice):
            threading.Thread(target=self._resume_chat, args=(choice, consent_key), daemon=True).start()

        ConsentDialog(self, prompt, on_choice)

    def _resume_chat(self, answer, consent_key):
        try:
            body = self.client.chat(self.messages, consent_answer=answer, consent_key=consent_key)
        except APIError as exc:
            self.after(0, self._append_chat_line, f"[Error contacting My AI: {exc}]")
            return
        self._handle_chat_response(body)

    # --- Access & Privacy tab ---

    def _build_access_tab(self):
        tk.Label(self.access_tab, text="Resource Access", font=("", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
        self.resource_rows_frame = tk.Frame(self.access_tab)
        self.resource_rows_frame.pack(fill=tk.X, padx=8)

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
        try:
            self.client.grant(resource)
        except APIError as exc:
            messagebox.showerror("Grant failed", str(exc))
            return
        self._refresh_access_tab()

    def _revoke(self, resource):
        try:
            self.client.revoke(resource)
        except APIError as exc:
            messagebox.showerror("Revoke failed", str(exc))
            return
        self._refresh_access_tab()

    def _reset_selected_preference(self):
        selection = self.preferences_tree.selection()
        if not selection:
            return
        key = self.preferences_tree.item(selection[0], "values")[0]
        try:
            self.client.reset_preference(key)
        except APIError as exc:
            messagebox.showerror("Reset failed", str(exc))
            return
        self._refresh_access_tab()

    def _refresh_access_tab(self):
        for widget in self.resource_rows_frame.winfo_children():
            widget.destroy()
        try:
            permissions = self.client.list_permissions()
        except APIError as exc:
            messagebox.showerror("Could not load permissions", str(exc))
            permissions = {}
        for resource, granted in permissions.items():
            row = tk.Frame(self.resource_rows_frame)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=resource, width=16, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text="Granted" if granted else "Not granted", width=14, anchor="w").pack(side=tk.LEFT)
            tk.Button(row, text="Grant", command=lambda r=resource: self._grant(r)).pack(side=tk.LEFT, padx=4)
            tk.Button(row, text="Revoke", command=lambda r=resource: self._revoke(r)).pack(side=tk.LEFT, padx=4)

        self.preferences_tree.delete(*self.preferences_tree.get_children())
        try:
            preferences = self.client.list_preferences()
        except APIError as exc:
            messagebox.showerror("Could not load preferences", str(exc))
            preferences = {}
        for key, entry in preferences.items():
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
        try:
            entries = self.client.list_activity()
        except APIError as exc:
            messagebox.showerror("Could not load activity", str(exc))
            return
        for entry in entries:
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
