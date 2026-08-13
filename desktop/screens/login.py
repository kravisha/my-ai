"""Login/register screen. Same widgets/layout/toggle pattern as before (and
as vibe-agent's own login.py) - only the submit handlers changed, from
calling UserStore/SessionStore directly to calling api_client.APIClient
over HTTP, now that the backend owns all of this. Kept synchronous, same
as vibe-agent's login and as before: a login/register call is quick enough
that a brief window freeze is an acceptable trade-off against the added
complexity of threading it too.
"""

import tkinter as tk
from tkinter import messagebox

from api_client import APIClient, APIError
from app.users import normalize_username


class LoginScreen(tk.Frame):
    def __init__(self, root, client: APIClient, on_success):
        super().__init__(root)
        self.client = client
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
            try:
                self.client.login(username, password)
            except APIError as e:
                messagebox.showerror("Login failed", str(e))
                return
            self.on_success(normalize_username(username))

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
                self.client.register(username, password)
            except APIError as e:
                messagebox.showerror("Registration failed", str(e))
                return
            self.on_success(normalize_username(username))

        tk.Button(self, text="Register", command=do_register).pack(pady=(10, 0))
        tk.Button(self, text="Back to login", command=self._build_login_form).pack(pady=(5, 20))
