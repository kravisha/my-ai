# The Second Failure Domain

**Maintained document.** How this system stops depending on one machine, what
is already true, and what you have to do by hand.

Addendum 29 §1.3 requires no single point of irrecoverable failure. Everything
this organization has ever written lives on one Windows disk, so until
2026-08-25 that requirement was unmet in the plainest possible way. This
document records the two halves of fixing it — the half that is done, and the
half that needs you.

---

## Two different capabilities, often confused

| | **Data domain** | **Host domain** |
|---|---|---|
| Question it answers | Does my *state* survive this machine dying? | Can the organization *run* if this machine dies? |
| Measured by | RPO — how much you lose | RTO — how long you are down |
| Status | **Done** (§69) | **Not provisioned** — needs an owner decision |
| Cost | Free (a synced folder) | A machine, with a recurring bill |

The first is worth having whether or not you ever build the second. They are
listed as one row in most disaster-recovery writing, and conflating them is
how a team ends up believing backups give them failover.

---

## What is already true (the data domain)

`CONTINUITY_SECONDARY_ROOT` points at a Dropbox-synced folder, so every
backup cycle writes twice: plaintext to `backups/` on this disk, and
**Fernet-encrypted** to Dropbox, which leaves the failure domain.

- **Encryption is not optional there.** `backend/continuity.py` wraps any
  secondary destination in `EncryptedProvider` unconditionally. Dropbox holds
  ciphertext and never the key (addendum 29 §10.1–§10.2).
- **The repository is not backed up, on purpose.** Source code is Git's job
  (§48's exclusion list). What travels is the state that cannot be
  reproduced from code: both SQLite databases, `users.json`, `sessions.json`,
  and `user_data/`, plus a manifest with per-file SHA-256 hashes.
- **`.env` is not backed up either.** An API key recovers by re-issuance at
  the provider, not by restore, and copying secrets to more places adds
  exposure without adding recoverability.
- **Cadence:** every `CONTINUITY_BACKUP_INTERVAL_SECONDS` (default 6h) while
  the backend runs, plus one on clean shutdown. That interval *is* your RPO
  for a crash.

### The one thing only you can do: key custody

`backup.key` is Tier-0 recovery material and it is not in Dropbox — key and
ciphertext in one place is the same as no encryption at all.

**But that means the disaster which takes this disk takes the key with it,
and every Dropbox copy becomes noise.** A perfectly encrypted backup with a
lost key is not a backup.

Put a copy of `C:\Users\ADMIN\my-ai\backup.key` somewhere that is neither
this machine nor this Dropbox account — a password manager entry, a
different cloud account, or printed on paper in a drawer. Nothing in this
repository can do this step for you, and nothing will remind you.

### Verify it any time

```bash
python -m backend.continuity backup
```

Two labelled lines, `primary` and `secondary`, mean both domains were
written. One line means the secondary is unconfigured and you are back to a
single domain.

---

## What is not built (the host domain)

No second machine exists. The steps below are written to be run by you on a
fresh Linux host; nothing here is automated, because provisioning
infrastructure spends money and requires accounts.

**Why Linux is viable at all:** the test suite is verified green on
`ubuntu-latest` as well as Windows — identical counts, 1758 passing
(SPEC_RECONCILIATION §68). The codebase was already written portable. So a
second domain does not require a second Windows licence.

### 1. Provision the host

Any provider. A small instance is enough — this is a recovery target, not a
production peer. Requirements: **Ubuntu 24.04 LTS or similar**, Python
**3.12**, ~2 GB RAM, and enough disk for your restored state plus headroom.

Loopback-only, like the primary: do **not** open the Gateway port to the
internet. Addendum 28's exposure preconditions (TQ-04, §50) all still apply,
and none of them have been met.

### 2. Install the code

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git
git clone <your-repo-url> my-ai && cd my-ai
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

### 3. Prove the host before trusting it

```bash
.venv/bin/python -m pytest -q
```

Expect `1758 passed, 5 deselected`. A host that cannot pass the suite cannot
be trusted to restore onto.

### 4. Bring the key and the backups

Copy `backup.key` from wherever you stored it (**not** from Dropbox — it is
not there) to the host, and get the encrypted backup set across, either by
installing a Dropbox client or by copying the `bk-*` directory by hand.

```bash
chmod 600 backup.key            # it is a credential
export CONTINUITY_SECONDARY_ROOT=/path/to/the/encrypted/backups
export CONTINUITY_KEY_PATH=/path/to/backup.key
```

### 5. Rehearse the restore — this is the step that matters

```bash
.venv/bin/python -m backend.continuity list --secondary
.venv/bin/python -m backend.continuity verify <backup-id> --secondary
.venv/bin/python -m backend.continuity restore <backup-id> /tmp/rehearsal --secondary
```

Then confirm the restored state is genuinely readable, not merely present:

```bash
.venv/bin/python -c "import sqlite3; d=sqlite3.connect('/tmp/rehearsal/financial_intelligence.db'); print(d.execute('PRAGMA integrity_check').fetchone()[0])"
```

`ok` is the answer you want. **Addendum 29 §1.4: a backup that has never been
restored is not a recovery asset.** Until this rehearsal passes on the host,
you have a hypothesis rather than a recovery plan.

Delete `/tmp/rehearsal` afterwards — a restored set contains decrypted
credentials (`users.json`, `sessions.json`, Gateway session rows).

### 6. Record the result

Add a line to `SPEC_RECONCILIATION.md`: what host, what date, whether the
rehearsal passed. A rehearsal nobody wrote down gets re-argued in six months.

---

## What this still does not give you

Named plainly, because a recovery plan that oversells itself is worse than a
modest one:

- **Not failover.** Nothing promotes the second host automatically. Recovery
  is a human following `INCIDENT_RESPONSE.md`.
- **Not live replication.** Your RPO is the backup interval, not zero. A
  crash loses up to six hours of state by default.
- **Not geographic separation.** A Dropbox folder and a VPS in one region are
  better than one disk, and are not multi-region (addendum 29 §14, still
  deferred).
- **Not tested until you test it.** Step 5 is the whole document. Everything
  before it is preparation.
