"""Controller control panel: the operator's window onto the agent organization
(addendum 14 §7).

A sibling of monitor/app.py, not a replacement. That tool watches client
conversations; this one watches the organization itself - who exists, on which
of the two lifecycle axes, what intelligence is in force, what the market looks
like, and where Explorer and Speculator disagreed.

Run as `python -m panel.app` from the my-ai/ project root, alongside a running
backend (`uvicorn backend.main:app`).

Read-only, deliberately. Lifecycle actions belong to the Controller alone
(addendum 11 §15), so spawn/retire/resume controls are a separate, audited
increment rather than something an observability window quietly acquires.

Polls rather than pushes, like monitor/app.py, and for the same reason: the
whole system is built on polling a database, and a panel that needed pushes
would be the only component demanding a different mechanism.

All formatting lives in panel/render.py so the decisions that matter are
testable without a Tk window. This module is widgets, polling, and HTTP.
"""

import tkinter as tk
from tkinter import scrolledtext, ttk

import requests

from panel import render

BASE_URL = "http://localhost:8000"
POLL_INTERVAL_MS = 2000
REQUEST_TIMEOUT_SECONDS = 5


class ControlPanel:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.selected_identity: str | None = None
        self._offline = False

        self.root = tk.Tk()
        self.root.title("My AI - Controller Control Panel")
        self.root.geometry("1150x720")

        self.status = tk.Label(self.root, text="connecting...", anchor="w", fg="#666")
        self.status.pack(fill=tk.X, padx=8, pady=(6, 0))

        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(paned)
        tk.Label(left, text="Agents", font=("", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        tk.Label(left, text=render.AGENT_HEADER, font=("Courier New", 8), fg="#666").pack(anchor="w", padx=8)
        self.agent_list = tk.Listbox(left, font=("Courier New", 9), exportselection=False)
        self.agent_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.agent_list.bind("<<ListboxSelect>>", self._on_select_agent)
        paned.add(left, width=520)

        right = tk.Frame(paned)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.views = {
            name: self._add_tab(label)
            for name, label in (
                ("agent", "Agent"),
                ("uqi", "Ask Agent"),
                ("intelligence", "Intelligence"),
                ("regime", "Market Regime"),
                ("cross_checks", "Disagreement"),
                ("discovery", "Discovery"),
            )
        }
        # The ask box lives under the UQI tab, not beside the roster: it acts on
        # the currently selected agent, and putting it anywhere else would
        # obscure which agent is about to be questioned.
        ask_frame = tk.Frame(self.views["uqi"].master)
        ask_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.question_entry = tk.Entry(ask_frame)
        self.question_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), pady=6)
        self.question_entry.bind("<Return>", lambda _e: self._ask_selected_agent())
        tk.Button(ask_frame, text="Ask", command=self._ask_selected_agent).pack(side=tk.LEFT, pady=6)

        paned.add(right)

        self._identities: list[str] = []
        self._uqi_request_id: int | None = None
        self.root.after(0, self._poll)

    def _add_tab(self, label: str) -> scrolledtext.ScrolledText:
        frame = tk.Frame(self.tabs)
        area = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state="disabled", font=("Courier New", 9))
        area.pack(fill=tk.BOTH, expand=True)
        self.tabs.add(frame, text=label)
        return area

    def _ask_selected_agent(self):
        """Put the typed question to the selected agent (addendum 14 §7).

        Fire-and-poll rather than fire-and-wait: the answer arrives on the
        agent's own cycle, and blocking the UI on another process's schedule
        would freeze the panel exactly when an operator is diagnosing a system
        that is already misbehaving."""
        question = self.question_entry.get().strip()
        if not question or self.selected_identity is None:
            self._write("uqi", "Select an agent, then type a question.")
            return
        try:
            response = requests.post(
                f"{self.base_url}/admin/agents/{self.selected_identity}/uqi",
                json={"question": question, "asked_by": "panel"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            self._uqi_request_id = response.json()["request_id"]
        except requests.RequestException as exc:
            self._write("uqi", f"Could not ask {self.selected_identity}: {exc}")
            return
        self.question_entry.delete(0, tk.END)
        self._write("uqi", f"Asked {self.selected_identity}: {question}\n\n(waiting for the agent to answer)")

    def _refresh_uqi(self):
        if self._uqi_request_id is None:
            return
        body = self._get(f"/admin/uqi/{self._uqi_request_id}")
        if body is not None:
            self._write("uqi", render.format_uqi_exchange(body))

    # --- HTTP ---

    def _get(self, path: str):
        """Returns None on any failure. A panel that raised when the backend
        was restarting would be useless precisely when an operator most wants
        to be watching."""
        try:
            response = requests.get(f"{self.base_url}{path}", timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            return None

    # --- polling ---

    def _poll(self):
        agents = self._get("/admin/agents")
        if agents is None:
            self._set_offline(True)
        else:
            self._set_offline(False)
            self._refresh_agents(agents["agents"])
            self._refresh_panels()
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _set_offline(self, offline: bool):
        self._offline = offline
        if offline:
            self.status.configure(text=f"backend unreachable at {self.base_url} - retrying", fg="#b00")
        else:
            self.status.configure(text=f"connected to {self.base_url}", fg="#060")

    def _refresh_agents(self, agents: list[dict]):
        rows = [render.agent_row(a) for a in agents]
        identities = [a["identity"] for a in agents]
        # Only redraw on an actual change, so the operator's selection and
        # scroll position survive a poll that changed nothing.
        if rows != list(self.agent_list.get(0, tk.END)):
            self.agent_list.delete(0, tk.END)
            for row in rows:
                self.agent_list.insert(tk.END, row)
        self._identities = identities
        if self.selected_identity in identities:
            self.agent_list.selection_clear(0, tk.END)
            self.agent_list.selection_set(identities.index(self.selected_identity))

    def _on_select_agent(self, _event):
        selection = self.agent_list.curselection()
        if selection and selection[0] < len(self._identities):
            self.selected_identity = self._identities[selection[0]]
            self._refresh_agent_detail()

    def _refresh_panels(self):
        self._refresh_agent_detail()
        self._refresh_uqi()
        for name, path, formatter, key in (
            ("intelligence", "/admin/intelligence", render.format_intelligence, "artifacts"),
            ("cross_checks", "/admin/cross-checks", render.format_cross_checks, "cross_checks"),
        ):
            body = self._get(path)
            if body is not None:
                self._write(name, formatter(body[key]))

        regime = self._get("/admin/regime")
        if regime is not None:
            self._write("regime", render.format_regime(regime))

        discovery = self._get("/admin/discovery")
        if discovery is not None:
            self._write("discovery", render.format_discovery(discovery))

    def _refresh_agent_detail(self):
        if self.selected_identity is None:
            self._write("agent", "Select an agent to see how it describes itself (addendum 14 §6).")
            return
        body = self._get(f"/admin/agents/{self.selected_identity}")
        if body is not None:
            self._write("agent", render.format_agent_detail(body))

    def _write(self, view: str, text: str):
        area = self.views[view]
        area.configure(state="normal")
        # Preserve the scroll position across refreshes - a view that snapped
        # back to the top every two seconds would be unreadable.
        position = area.yview()[0]
        area.delete("1.0", tk.END)
        area.insert(tk.END, text)
        area.yview_moveto(position)
        area.configure(state="disabled")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    ControlPanel().run()
