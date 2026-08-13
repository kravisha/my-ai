"""My AI server monitor: a standalone operator tool, not a user client - no
login, since it watches every account's conversation via the backend's
unauthenticated /admin/* routes (see backend/main.py). Run as
`python -m monitor.app` from the my-ai/ project root, alongside a running
backend (`uvicorn backend.main:app`).

Polls rather than pushes (see the plan behind this feature): a Listbox of
client usernames on the left, a read-only transcript on the right, both
refreshed every couple seconds via root.after(...). Uses `requests` directly
rather than api_client.APIClient, since none of APIClient's bearer-token
machinery applies to these two unauthenticated routes.
"""

import tkinter as tk
from tkinter import scrolledtext

import requests

BASE_URL = "http://localhost:8000"
POLL_INTERVAL_MS = 2000


class MonitorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("My AI - Server Monitor")
        self.root.geometry("900x600")
        self.selected_client: str | None = None
        self._last_entry_count = 0

        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(paned)
        tk.Label(left_frame, text="Connected Clients", font=("", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
        self.client_listbox = tk.Listbox(left_frame)
        self.client_listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.client_listbox.bind("<<ListboxSelect>>", self._on_select_client)
        paned.add(left_frame, width=200)

        right_frame = tk.Frame(paned)
        tk.Label(right_frame, text="Conversation", font=("", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
        self.transcript_area = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, state="disabled")
        self.transcript_area.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        paned.add(right_frame)

        self.root.after(0, self._poll)

    def _on_select_client(self, event):
        selection = self.client_listbox.curselection()
        if not selection:
            return
        self.selected_client = self.client_listbox.get(selection[0])
        self._last_entry_count = 0
        self._refresh_transcript(force_redraw=True)

    def _poll(self):
        self._refresh_client_list()
        if self.selected_client is not None:
            self._refresh_transcript()
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _refresh_client_list(self):
        try:
            response = requests.get(f"{BASE_URL}/admin/clients", timeout=5)
            response.raise_for_status()
            clients = response.json()["clients"]
        except requests.RequestException:
            return

        current_items = list(self.client_listbox.get(0, tk.END))
        if current_items == clients:
            return  # nothing changed, avoid disturbing the current selection/scroll position

        self.client_listbox.delete(0, tk.END)
        for client in clients:
            self.client_listbox.insert(tk.END, client)
        if self.selected_client in clients:
            self.client_listbox.selection_set(clients.index(self.selected_client))

    def _refresh_transcript(self, force_redraw=False):
        try:
            response = requests.get(f"{BASE_URL}/admin/clients/{self.selected_client}/transcript", timeout=5)
            response.raise_for_status()
            entries = response.json()["entries"]
        except requests.RequestException:
            return

        if not force_redraw and len(entries) == self._last_entry_count:
            return

        self.transcript_area.configure(state="normal")
        self.transcript_area.delete("1.0", tk.END)
        for entry in entries:
            label = "User" if entry["role"] == "user" else "Assistant"
            self.transcript_area.insert(tk.END, f"{label}: {entry['text']}\n\n")
        self.transcript_area.configure(state="disabled")
        self.transcript_area.see(tk.END)
        self._last_entry_count = len(entries)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    MonitorApp().run()
