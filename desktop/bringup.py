"""The one command Krish runs on his PC.

    python -m desktop.bringup

Prints every check, worst first, with what to do about each. Nothing else here
happens on its own: the flags below each do one thing and say what they did.

    --make-key             create the charter key, sealed to this Windows account
    --write-escrow         wrap the key in a passphrase and write it out
    --restore-key          put a key back from the escrow, after a rebuild
    --install-constitution seal AI-CONSTITUTION.md into the store, once

## Why the actions are flags rather than something it just does

A status command that fixes things is a status command nobody can run to find
out where they stand. Each of these writes something that is hard to undo - a
key that replaces another key is every amendment gone - so each is asked for
explicitly, and every one of them refuses to overwrite what is already there.

## What it will not do

It will not start the Gateway, the DBA or the supervisor. `keep-jarvis-up.ps1`
owns that, on purpose: the thing that restarts Jarvis has to be the thing that
survives him, and a bring-up script that also ran him would be a second
supervisor with different opinions. What this does instead is tell you which of
them is not running and the exact line that starts it.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app import dpapi, keystore, secretbox
from desktop import machine, readiness


def status() -> int:
    report = readiness.look(machine.read())
    print()
    print("\n".join(readiness.summary(report)))
    print()
    print(f"overall: {report.status.upper()}"
          f"{'' if report.runnable else '  - he will not start like this'}")
    return 0 if report.status in (readiness.GREEN, readiness.YELLOW) else 1


def make_key() -> int:
    """Create the key. Refuses if one is there, because replacing it is the one
    mistake with no way back: the sealed documents do not open with the new one
    and nothing says so until they are needed."""
    where = keystore.key_path(machine.state_directory())
    if where.exists():
        print(f"there is already a key at {where}.")
        print("Refusing to replace it: the sealed constitution and every")
        print("amendment open with the key that sealed them, and a new key")
        print("does not open them. If this one no longer works, restore the")
        print("escrow copy instead: --restore-key")
        return 1
    if not dpapi.available():
        print("this is not Windows, so there is nowhere to put a key that does")
        print("not involve a person typing it. Run this on the PC.")
        return 1

    key = secretbox.new_key()
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_bytes(dpapi.protect(key))
    print(f"key created at {where}")
    print(f"fingerprint: {secretbox.fingerprint(key)}")
    print()
    print("It is sealed to this Windows account. If this account is ever lost")
    print("or rebuilt, the only way back is the escrow copy - write one now:")
    return _write_escrow(key)


def write_escrow() -> int:
    return _write_escrow(_open_key())


def _write_escrow(key: bytes) -> int:
    where = keystore.escrow_path(machine.state_directory())
    print()
    print("Choose a passphrase for the escrow copy. You will need it only if")
    print("this Windows account is lost, so write it down somewhere that is")
    print(f"not this machine. At least {keystore.ESCROW_PASSPHRASE_MIN}")
    print("characters.")
    passphrase = getpass.getpass("passphrase: ")
    again = getpass.getpass("again: ")
    if passphrase != again:
        print("those did not match; nothing was written")
        return 1
    try:
        blob = keystore.wrap_for_escrow(key, passphrase=passphrase)
    except keystore.WeakPassphrase as refused:
        print(str(refused))
        return 1
    where.write_bytes(blob)
    print()
    print(f"escrow written to {where}")
    print("Copy it somewhere off this machine. It is useless without the")
    print("passphrase, so where it sits matters less than that it exists.")
    return 0


def restore_key() -> int:
    where = keystore.key_path(machine.state_directory())
    escrow = keystore.escrow_path(machine.state_directory())
    if not escrow.exists():
        print(f"no escrow copy at {escrow}, so there is nothing to restore")
        print("from. If the key here does not open, the amendments cannot be")
        print("recovered by anybody. Nothing this program can do changes that.")
        return 1
    passphrase = getpass.getpass("escrow passphrase: ")
    try:
        key = keystore.unwrap_escrow(escrow.read_bytes(), passphrase=passphrase)
    except (secretbox.Tampered, secretbox.NotSealed) as refused:
        print(f"that did not open the escrow: {refused}")
        print("A wrong passphrase and an edited file look the same to the")
        print("cryptography, so this cannot tell you which it was.")
        return 1
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_bytes(dpapi.protect(key))
    print(f"key restored to {where}")
    print(f"fingerprint: {secretbox.fingerprint(key)}")
    return 0


def install_constitution() -> int:
    from gateway import constitution, dbaclient

    if constitution.installed():
        print("a sealed constitution is already installed. It is never")
        print("replaced from here - Krish edits AI-CONSTITUTION.md by hand or")
        print("it does not change, and additions go in the amendments file.")
        return 1
    source = machine.PROJECT_ROOT / "AI-CONSTITUTION.md"
    if not source.exists():
        print(f"no {source.name} to install")
        return 1
    key = _open_key()
    constitution.install(source.read_text(encoding="utf-8"), key=key,
                         granted_by="krish",
                         client=dbaclient.DBAClient())
    print("constitution sealed and installed.")
    print()
    print("The plaintext file is still in the repository and in git history;")
    print("sealing it here does not remove it from past commits.")
    return 0


def _open_key() -> bytes:
    where = keystore.key_path(machine.state_directory())
    if not where.exists():
        raise SystemExit(f"no key at {where}. Run --make-key first.")
    return dpapi.unprotect(where.read_bytes())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m desktop.bringup",
        description="Whether Jarvis can run on this machine, and what is "
                    "stopping him.")
    parser.add_argument("--make-key", action="store_true")
    parser.add_argument("--write-escrow", action="store_true")
    parser.add_argument("--restore-key", action="store_true")
    parser.add_argument("--install-constitution", action="store_true")
    said = parser.parse_args(argv)

    asked = [name for name in ("make_key", "write_escrow", "restore_key",
                               "install_constitution")
             if getattr(said, name)]
    if len(asked) > 1:
        print("one at a time, please: " + ", ".join(asked))
        return 1
    if not asked:
        return status()
    return {"make_key": make_key, "write_escrow": write_escrow,
            "restore_key": restore_key,
            "install_constitution": install_constitution}[asked[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
