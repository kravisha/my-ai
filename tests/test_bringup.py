"""The command Krish runs on his PC.

`desktop/bringup.py` is mostly printing, and the parts that are not are the four
actions - each of which writes something that cannot be undone. A key that
replaces another key is every amendment gone, silently, until somebody needs
one. So what is tested here is the refusals.

Probed by `tests/probes/readiness_probes.py`, which covers the two modules the
decisions live in.
"""

import pytest

from desktop import bringup


def test_a_status_run_asks_for_nothing_and_changes_nothing(monkeypatch, capsys):
    """It has to be safe to run when you have no idea what state you are in -
    that is the entire point of it."""
    calls = []
    monkeypatch.setattr(bringup.machine, "read",
                        lambda: _record(calls, "read"))
    monkeypatch.setattr(bringup, "make_key",
                        lambda: pytest.fail("status wrote a key"))
    monkeypatch.setattr(bringup, "install_constitution",
                        lambda: pytest.fail("status installed something"))
    bringup.main([])
    assert calls == ["read"]
    printed = capsys.readouterr().out
    assert "overall:" in printed


def _record(calls, name):
    from desktop import readiness

    calls.append(name)
    return readiness.Machine()


def test_two_actions_at_once_are_refused_rather_than_ordered(capsys):
    """A guess about which one he meant is a guess about which irreversible
    thing to do."""
    assert bringup.main(["--make-key", "--restore-key"]) == 1
    assert "one at a time" in capsys.readouterr().out


def test_making_a_key_over_an_existing_one_is_refused(monkeypatch, tmp_path,
                                                      capsys):
    """The mistake with no way back: the sealed documents open with the key that
    sealed them, a new key opens nothing, and nothing says so until he needs an
    amendment."""
    (tmp_path / "charter.key").write_bytes(b"the one that works")
    monkeypatch.setattr(bringup.machine, "state_directory", lambda: tmp_path)

    assert bringup.main(["--make-key"]) == 1
    printed = capsys.readouterr().out
    assert "Refusing to replace it" in printed
    assert "--restore-key" in printed
    assert (tmp_path / "charter.key").read_bytes() == b"the one that works"


def test_making_a_key_off_windows_is_refused_rather_than_written_in_the_clear(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(bringup.machine, "state_directory", lambda: tmp_path)
    monkeypatch.setattr(bringup.dpapi, "available", lambda: False)

    assert bringup.main(["--make-key"]) == 1
    assert "Run this on the PC" in capsys.readouterr().out
    assert not (tmp_path / "charter.key").exists()


def test_restoring_with_no_escrow_says_the_truth_about_what_that_means(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(bringup.machine, "state_directory", lambda: tmp_path)

    assert bringup.main(["--restore-key"]) == 1
    printed = capsys.readouterr().out
    assert "nothing to restore" in printed
    assert "recovered by anybody" in printed


def test_a_wrong_escrow_passphrase_does_not_overwrite_the_key(
        monkeypatch, tmp_path, capsys):
    from app import keystore, secretbox

    key = secretbox.new_key()
    (tmp_path / "charter.key.escrow").write_bytes(
        keystore.wrap_for_escrow(key, passphrase="the right passphrase"))
    (tmp_path / "charter.key").write_bytes(b"whatever is here now")
    monkeypatch.setattr(bringup.machine, "state_directory", lambda: tmp_path)
    monkeypatch.setattr(bringup.getpass, "getpass", lambda _: "the wrong one")

    assert bringup.main(["--restore-key"]) == 1
    assert (tmp_path / "charter.key").read_bytes() == b"whatever is here now"
    printed = capsys.readouterr().out
    assert "did not open the escrow" in printed
    assert "look the same to the" in printed


def test_an_escrow_passphrase_typed_differently_twice_writes_nothing(
        monkeypatch, tmp_path, capsys):
    from app import secretbox

    monkeypatch.setattr(bringup.machine, "state_directory", lambda: tmp_path)
    said = iter(["a long enough passphrase", "a different one entirely"])
    monkeypatch.setattr(bringup.getpass, "getpass", lambda _: next(said))

    assert bringup._write_escrow(secretbox.new_key()) == 1
    assert "did not match" in capsys.readouterr().out
    assert not (tmp_path / "charter.key.escrow").exists()


def test_a_short_escrow_passphrase_is_refused_and_writes_nothing(
        monkeypatch, tmp_path, capsys):
    from app import secretbox

    monkeypatch.setattr(bringup.machine, "state_directory", lambda: tmp_path)
    monkeypatch.setattr(bringup.getpass, "getpass", lambda _: "short")

    assert bringup._write_escrow(secretbox.new_key()) == 1
    assert "at least" in capsys.readouterr().out
    assert not (tmp_path / "charter.key.escrow").exists()


def test_a_good_escrow_round_trips_through_the_command(monkeypatch, tmp_path,
                                                       capsys):
    from app import keystore, secretbox

    key = secretbox.new_key()
    monkeypatch.setattr(bringup.machine, "state_directory", lambda: tmp_path)
    monkeypatch.setattr(bringup.getpass, "getpass",
                        lambda _: "a long enough passphrase")

    assert bringup._write_escrow(key) == 0
    written = (tmp_path / "charter.key.escrow").read_bytes()
    assert keystore.unwrap_escrow(
        written, passphrase="a long enough passphrase") == key
    assert "off this machine" in capsys.readouterr().out


def test_installing_the_constitution_twice_is_refused(monkeypatch, capsys):
    """Krish edits `AI-CONSTITUTION.md` by hand or it does not change, and
    nothing here is a second writer for it."""
    import gateway.constitution as constitution

    monkeypatch.setattr(constitution, "installed", lambda: True)
    assert bringup.main(["--install-constitution"]) == 1
    printed = capsys.readouterr().out
    assert "already installed" in printed
    assert "by hand" in printed


def test_the_status_exit_code_says_whether_to_worry(monkeypatch, capsys):
    """Zero for green and yellow, one for red - so the supervisor or a scheduled
    task can act on it without parsing the words."""
    from desktop import readiness

    monkeypatch.setattr(bringup.machine, "read", lambda: readiness.Machine())
    assert bringup.main([]) == 1

    good = readiness.Machine(
        python_version=(3, 12), state_directory_writable=True,
        jarvis_token=True, operator_token=True, dba_answering=True,
        gateway_answering=True, gateway_reaches_dba=True,
        keystore_state="ready", constitution_installed=True,
        constitution_intact=True, ledger_intact=True, checkpoint_age_hours=1.0,
        supervisor_registered=True, log_written_within_hours=0.1, windows=True)
    monkeypatch.setattr(bringup.machine, "read", lambda: good)
    assert bringup.main([]) == 0
    capsys.readouterr()
