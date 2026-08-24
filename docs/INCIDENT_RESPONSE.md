# Incident Response Runbook

A maintained document (addendum 28 §15, §32 items 15–16; TASK_QUEUE TQ-08). What to actually do,
in order, on suspected compromise or serious malfunction of this deployment — one machine, loopback
services, a local agent population. Written for the operator at the keyboard, not for a SOC that
does not exist. Steps assume the repository root as working directory.

The ordering below is addendum 28 §15.2's: when evidence indicates active compromise, containment
comes before perfect diagnosis — but evidence preservation comes before anything destructive.

## 1. Preserve evidence first

Take a backup *before* changing anything — the stores as they are now are the evidence, and every
later step mutates them:

```bash
.venv/Scripts/python.exe -m backend.continuity backup
```

Note the printed backup id. Do not delete or "clean up" databases, logs, or `user_data/` during an
incident; audit trails are append-only records and addendum 28 §1.9 forbids erasing them.

## 2. Stop the organization

**Cleanly, if the backend is responsive:** press Ctrl+C in the uvicorn terminal. A clean shutdown
runs `Controller.shutdown_agents()` — the agent population exits with the server.

**If the backend died or was force-killed:** the agents are separate processes and are still
running and writing (observed behavior, `SPEC_RECONCILIATION.md` §48). Find and stop them:

```bash
powershell -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object { $_.CommandLine -match '-m agents\.' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
```

The Controller reconciles registry state against reality on the next start, so killed processes do
not need registry cleanup by hand.

**A single misbehaving agent** does not require stopping the world: the registry's
`stop_requested` / `retire_requested` flags and the Controller's directives are the kill switch
(§50 item 17) — usable through the admin panel while the backend is up.

## 3. Revoke credentials

In escalating order of suspected exposure:

- **Client sessions (desktop/CLI logins):** delete `sessions.json` in the repository root. Every
  logged-in client must log in again. This file is a bearer-token store; treat its deletion as
  routine during any credential incident.
- **Gateway Super User sessions:** session rows live in `gateway.db`'s sessions table and are
  credentials. With the Gateway stopped:
  `.venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('gateway.db'); c.execute('DELETE FROM sessions'); c.commit()"`
  (Delete session rows only — the conversation transcript in the same store is evidence.)
- **Anthropic API key:** revoke it at https://console.anthropic.com (the key, not just locally),
  issue a new one, update `.env`. Local deletion alone does not revoke a leaked key.
- **Gateway password:** run `.venv/Scripts/python.exe -m gateway.hash_password` and replace
  `GATEWAY_PASSWORD_HASH` in `.env`.
- **User account passwords:** there is no forced-reset mechanism; deleting the affected user's
  entry in `users.json` (after the step-1 backup) forces re-registration. Crude, and recorded here
  as such rather than pretended otherwise.

## 4. Assess before restoring

Addendum 29 §30: recovery must not restore the attacker with the service. Before restarting:

- Read the audit trails (`user_data/<user>/audit_log.jsonl`, organizational records via the panel)
  for what happened and when.
- Verify backup integrity, and prefer a set that predates the suspected compromise:
  `.venv/Scripts/python.exe -m backend.continuity list` then `... verify <backup_id>`.
- `git status` / `git diff` — uncommitted changes to the code you did not make are part of the
  incident, and `behavior_version`'s `-dirty` marker in the agent registry will have recorded
  whether agents ran modified code.

## 5. Restore and restart

If stores must be rolled back:
`.venv/Scripts/python.exe -m backend.continuity restore <backup_id> <dest> [--overwrite]` —
restore refuses corrupt sets and refuses to overwrite without the explicit flag; both refusals are
deliberate. Restore to a scratch destination and inspect before overwriting live state.

Then restart (`.venv/Scripts/python.exe -m uvicorn backend.main:app`), confirm the Controller's
reconcile-on-start line in the log, and confirm the agent population's `behavior_version` matches
the commit you intend to be running.

## 6. Review

Every real incident gets a written record: what happened, what was done, what the audit trail
lacked, what this runbook got wrong. Addendum 28 §20.7 requires it for emergency actions; the
reconciliation file is where such records already live.

---

*Known limits, stated rather than implied: no MFA, no production secret store, no security-event
envelope — these are exposure preconditions tracked in `SPEC_RECONCILIATION.md` §50 and become
blocking the day anything binds beyond loopback. This runbook covers the deployment that exists.*
