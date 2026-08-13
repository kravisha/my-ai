"""Login/register screen. Mirrors vibe-agent's desktop/screens/login.py
(destroy-and-rebuild toggle between two sub-forms, blocking submit handlers,
messagebox.showerror on failure) but calls UserStore/SessionStore directly
instead of an HTTP client - there's no server here to talk to. Kept
synchronous like vibe-agent's own login screen: bcrypt's hash time
(~200-300ms) is far shorter than the network calls vibe-agent's login
blocks on, so a brief freeze here is an acceptable, deliberate trade-off.
"""

import tkinter as tk
from tkinter import messagebox

from app.users import UserStore, normalize_username


class LoginScreen(tk.Frame):
    def __init__(self, root, users: UserStore, sessions, on_success):
        super().__init__(root)
        self.users = users
        self.sessions = sessions
        self.on_success = on_success
        self._build_login_form()

    def _build_login_form(self):
        for widget in self.winfo_children():
            widget.destroy()

        tk.Label(self, text="My AI — Sign In", font=("", 14, "bold")).pack(pady=(20, 10))

        form = tk.Frame(self)
        form.pack(pady=10)

        tk.Label(form, text="Username").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        username_entry = tk.Entry(form, width=30)
        username_entry.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(form, text="Password").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        password_entry = tk.Entry(form, width=30, show="*")
        password_entry.grid(row=1, column=1, padx=5, pady=5)
        password_entry.bind("<Return>", lambda event: do_login())

        def do_login():
            username = username_entry.get().strip()
            password = password_entry.get()
            if not self.users.authenticate(username, password):
                messagebox.showerror("Login failed", "Invalid username or password.")
                return
            normalized = normalize_username(username)
            self.sessions.create(normalized)
            self.on_success(normalized)

        tk.Button(self, text="Log In", command=do_login).pack(pady=(10, 0))
        tk.Button(self, text="Create a new account", command=self._build_register_form).pack(pady=(5, 20))

    def _build_register_form(self):
        for widget in self.winfo_children():
            widget.destroy()

        tk.Label(self, text="Create an Account", font=("", 14, "bold")).pack(pady=(20, 10))

        form = tk.Frame(self)
        form.pack(pady=10)

        fields = {}
        for row, (key, label) in enumerate(
            [
                ("username", "Username"),
                ("password", "Password"),
                ("confirm", "Confirm Password"),
            ]
        ):
            tk.Label(form, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=5)
            entry = tk.Entry(form, width=30, show="*" if key in ("password", "confirm") else "")
            entry.grid(row=row, column=1, padx=5, pady=5)
            fields[key] = entry

        def do_register():
            username = fields["username"].get().strip()
            password = fields["password"].get()
            confirm = fields["confirm"].get()
            if password != confirm:
                messagebox.showerror("Registration failed", "Passwords did not match.")
                return
            try:
                normalized = self.users.register(username, password)
            except ValueError as e:
                messagebox.showerror("Registration failed", str(e))
                return
            self.sessions.create(normalized)
            self.on_success(normalized)

        tk.Button(self, text="Register", command=do_register).pack(pady=(10, 0))
        tk.Button(self, text="Back to login", command=self._build_login_form).pack(pady=(5, 20))
