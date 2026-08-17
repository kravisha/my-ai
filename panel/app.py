"""Controller control panel: the operator's window onto the agent organization
(addendum 14 §7).

A sibling of monitor/app.py, not a replacement. That tool watches client
conversations; this one watches the organization itself - who exists, on which
of the two lifecycle axes, what intelligence is in force, what the market looks
like, and where Explorer and Speculator disagreed.

Run as `python -m panel.app` from the my-ai/ project root, alongside a running
backend (`uvicorn backend.main:app`).

The panel can retire and resume agents, but it never changes lifecycle state
itself. It files a directive and the Controller executes it, because addendum
11 §15 makes the Controller the *exclusive* executor of lifecycle actions - a
panel that wrote lifecycle_state directly would become a second executor and
quietly end that guarantee. The buttons say "Ask Controller to..." for the same
reason. Spawning new agents is not offered yet; only the reversible pair is.

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
        self._denied = False
        self.token: str | None = None
        self.username: str | None = None

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
        self.agent_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))
        self.agent_list.bind("<<ListboxSelect>>", self._on_select_agent)

        # The panel never changes lifecycle state itself. These file a
        # directive; the Controller executes it (addendum 11 §15). The button
        # labels say "Ask Controller to..." because that is literally what
        # happens, and an operator should not be led to believe the window in
        # front of them is the thing with the authority.
        controls = tk.Frame(left)
        controls.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Button(controls, text="Ask Controller to retire",
                  command=lambda: self._request_lifecycle("retire")).pack(side=tk.LEFT)
        tk.Button(controls, text="Ask Controller to resume",
                  command=lambda: self._request_lifecycle("resume")).pack(side=tk.LEFT, padx=6)
        self.lifecycle_status = tk.Label(left, text="", anchor="w", fg="#666", wraplength=490, justify="left")
        self.lifecycle_status.pack(fill=tk.X, padx=8, pady=(0, 8))
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
                ("knowledge", "Knowledge"),
                ("directives", "Lifecycle Log"),
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
                json={"question": question},
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            self._uqi_request_id = response.json()["request_id"]
        except requests.RequestException as exc:
            self._write("uqi", f"Could not ask {self.selected_identity}: {exc}")
            return
        self.question_entry.delete(0, tk.END)
        self._write("uqi", f"Asked {self.selected_identity}: {question}\n\n(waiting for the agent to answer)")

    def _request_lifecycle(self, action: str):
        """File a retire/resume directive for the selected agent.

        Reports the directive id rather than claiming the action happened. The
        Controller executes it on its own poll cycle, and the roster will show
        the change a moment later - saying "retired" here would assert an
        outcome this window does not control and cannot confirm."""
        if self.selected_identity is None:
            self.lifecycle_status.configure(text="Select an agent first.", fg="#b00")
            return
        try:
            response = requests.post(
                f"{self.base_url}/admin/agents/{self.selected_identity}/{action}",
                json={"reason": f"operator {action} via control panel"},
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                detail = response.json().get("detail", response.text)
                self.lifecycle_status.configure(text=f"Refused: {detail}", fg="#b00")
                return
            directive_id = response.json()["directive_id"]
        except requests.RequestException as exc:
            self.lifecycle_status.configure(text=f"Could not reach the backend: {exc}", fg="#b00")
            return
        self.lifecycle_status.configure(
            text=f"Directive #{directive_id} filed: {action} {self.selected_identity}. "
                 "The Controller executes it on its next cycle.",
            fg="#060",
        )

    def _refresh_uqi(self):
        if self._uqi_request_id is None:
            return
        body = self._get(f"/admin/uqi/{self._uqi_request_id}")
        if body is not None:
            self._write("uqi", render.format_uqi_exchange(body))

    # --- HTTP ---

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def sign_in(self, username: str, password: str) -> str | None:
        """Exchange credentials for a session token. Returns an error message,
        or None on success.

        The panel holds a token in memory and never a password. Nothing is
        written to disk: an operator tool that cached a superuser credential
        would turn "someone opened the panel once" into standing access."""
        try:
            response = requests.post(
                f"{self.base_url}/auth/login",
                json={"username": username, "password": password},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            return f"Could not reach the backend: {exc}"
        if response.status_code != 200:
            try:
                return response.json().get("detail", response.text)
            except ValueError:
                return response.text
        self.token = response.json()["token"]
        self.username = username
        return None

    def _get(self, path: str):
        """Returns None on any failure. A panel that raised when the backend
        was restarting would be useless precisely when an operator most wants
        to be watching.

        A 403 is surfaced rather than swallowed, though - silently showing
        empty panes to an unauthorized operator would look like a dead system
        instead of a refused one."""
        try:
            response = requests.get(
                f"{self.base_url}{path}", headers=self._headers(), timeout=REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code in (401, 403):
                self._denied = True
                return None
            response.raise_for_status()
            self._denied = False
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
        """Three states, not two. "Refused" and "unreachable" need different
        fixes - one is a credential problem, the other a process problem - and
        an operator staring at empty panes deserves to know which."""
        self._offline = offline
        if offline and self._denied:
            self.status.configure(
                text=f"signed in as {self.username or '(nobody)'} but refused: this account is not a "
                     f"configured superuser (MY_AI_ADMIN_USERS)", fg="#b00")
        elif offline:
            self.status.configure(text=f"backend unreachable at {self.base_url} - retrying", fg="#b00")
        else:
            self.status.configure(text=f"connected to {self.base_url} as {self.username}", fg="#060")

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

        knowledge = self._get("/admin/knowledge")
        if knowledge is not None:
            self._write("knowledge", render.format_knowledge(knowledge))

        directives = self._get("/admin/directives")
        if directives is not None:
            self._write("directives", render.format_directives(directives))

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


def prompt_for_credentials(root: tk.Tk, base_url: str) -> tuple[str, str] | None:
    """A modal sign-in, so no superuser credential is ever stored anywhere.

    Read from the operator each time rather than from an environment variable
    or a config file: a cached admin password turns "someone opened the panel
    once" into standing access to retire agents and read every conversation."""
    dialog = tk.Toplevel(root)
    dialog.title("Sign in")
    dialog.transient(root)
    dialog.grab_set()
    result: dict = {}

    tk.Label(dialog, text=f"Superuser sign-in for {base_url}").grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 8))
    tk.Label(dialog, text="Username").grid(row=1, column=0, sticky="e", padx=(12, 4), pady=4)
    tk.Label(dialog, text="Password").grid(row=2, column=0, sticky="e", padx=(12, 4), pady=4)
    username_entry = tk.Entry(dialog, width=28)
    password_entry = tk.Entry(dialog, width=28, show="*")
    username_entry.grid(row=1, column=1, padx=(0, 12), pady=4)
    password_entry.grid(row=2, column=1, padx=(0, 12), pady=4)
    username_entry.focus_set()

    def submit(_event=None):
        result["credentials"] = (username_entry.get().strip(), password_entry.get())
        dialog.destroy()

    tk.Button(dialog, text="Sign in", command=submit).grid(row=3, column=0, columnspan=2, pady=(8, 12))
    dialog.bind("<Return>", submit)
    root.wait_window(dialog)
    return result.get("credentials")


def main() -> None:
    panel = ControlPanel()
    panel.root.withdraw()
    credentials = prompt_for_credentials(panel.root, panel.base_url)
    if credentials is None:
        panel.root.destroy()
        return
    error = panel.sign_in(*credentials)
    panel.root.deiconify()
    if error:
        # Not fatal. The panel still opens and its status line explains the
        # refusal - an operator who mistyped a password should see why, not a
        # window that vanishes.
        panel.status.configure(text=f"sign-in failed: {error}", fg="#b00")
    panel.run()


if __name__ == "__main__":
    main()
