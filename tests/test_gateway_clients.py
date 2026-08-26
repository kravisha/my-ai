"""The client registry (gateway/clients.py; TQ-43, SPEC_RECONCILIATION §98).

Everything downstream of a client session has been per-client for days —
conversations, the representative's identity, holdings — and all of it keyed off
a subject that only one person could ever be, because the Gateway had one
credential per *role*. The isolation was real and tested; the doorway was not
there.

What this suite holds is mostly about the door: that two clients are two
identities, that a credential resolves to an identity rather than to a boolean,
that a suspended client cannot get in, and that failing to log in tells an
outsider nothing about who exists.
"""

import pytest

from gateway import auth, clients, roles, store


# --- two clients are two people ---------------------------------------------------


def test_two_clients_authenticate_as_themselves(gateway_conn):
    """The whole point. Before TQ-43 both would have shared a credential and
    therefore a subject, and every per-client table below would have been
    keyed to the same person."""
    _, alice_password = clients.register(gateway_conn, "alice")
    _, bob_password = clients.register(gateway_conn, "bob")

    assert clients.authenticate(gateway_conn, "alice", alice_password) == "alice"
    assert clients.authenticate(gateway_conn, "bob", bob_password) == "bob"
    # And neither password opens the other's door.
    assert clients.authenticate(gateway_conn, "alice", bob_password) is None
    assert clients.authenticate(gateway_conn, "bob", alice_password) is None


def test_authentication_returns_an_identity_not_a_boolean(gateway_conn):
    """A caller that verified a credential and then trusted the typed name would
    be taking a claim as an identity at the exact moment the answer is known
    (addendum 44 §9.2)."""
    _, password = clients.register(gateway_conn, "alice")
    assert clients.authenticate(gateway_conn, "  ALICE  ", password) == "alice"


def test_the_session_subject_is_what_the_registry_resolved(gateway_conn):
    """Asserted at the source, because this is the line where a typed name would
    become an identity if anybody let it."""
    import inspect

    from gateway import main

    source = inspect.getsource(main.login)
    assert "clients.authenticate" in source
    assert "subject=subject" in source
    assert "subject=request.username" not in source


# --- the password is never recoverable ---------------------------------------------


def test_only_the_hash_is_stored(gateway_conn):
    """A registry that could show a client's password would be a registry worth
    stealing."""
    _, password = clients.register(gateway_conn, "alice")

    row = gateway_conn.fetchone(
        "SELECT password_hash FROM clients WHERE client_id = 'alice'")
    assert password not in row["password_hash"]
    assert row["password_hash"].startswith("$2b$")


def test_nothing_in_the_reading_surface_returns_a_hash(gateway_conn):
    """Nothing outside this module has a reason to hold one, and a listing that
    carried them would put them into whatever printed it."""
    clients.register(gateway_conn, "alice")

    for record in (clients.get(gateway_conn, "alice"), *clients.listing(gateway_conn)):
        assert "password_hash" not in record
        assert "password" not in record


def test_a_generated_password_is_not_guessable(gateway_conn):
    """Generated rather than chosen: a provisioning command that accepted one
    would invite a memorable password, and these are credentials to somebody
    else's financial data."""
    generated = {clients.generate_password() for _ in range(50)}
    assert len(generated) == 50
    assert all(len(p) >= 20 for p in generated)


def test_a_new_password_replaces_the_old_one(gateway_conn):
    _, first = clients.register(gateway_conn, "alice")
    second = clients.set_password(gateway_conn, "alice")

    assert clients.authenticate(gateway_conn, "alice", second) == "alice"
    assert clients.authenticate(gateway_conn, "alice", first) is None


# --- refusals -----------------------------------------------------------------------


def test_a_client_cannot_take_a_configured_role_name(gateway_conn, monkeypatch):
    """A client and a role answering to one name is an ambiguity about who
    somebody is. Refused at creation rather than resolved at the login route,
    because the login route's resolution would have to pick a winner."""
    monkeypatch.setenv("GATEWAY_SUPER_USER", "boss")
    monkeypatch.setenv("GATEWAY_PASSWORD_HASH", "$2b$12$" + "x" * 53)

    with pytest.raises(clients.ClientRefused, match="role credential"):
        clients.register(gateway_conn, "boss")


def test_a_duplicate_client_is_refused(gateway_conn):
    clients.register(gateway_conn, "alice")
    with pytest.raises(clients.ClientRefused, match="already registered"):
        clients.register(gateway_conn, "ALICE")


@pytest.mark.parametrize("bad", [
    "", "  ", "a", "Alice Smith", "alice@example.com", "../etc", "alice\nbob",
    "x" * 64, "-alice",
])
def test_an_unusable_client_id_is_refused(gateway_conn, bad):
    """Ids end up in log lines, audit rows and error messages. A handle
    containing a newline or a quote is a formatting bug waiting to be an
    injection one."""
    with pytest.raises(clients.ClientRefused):
        clients.register(gateway_conn, bad)


def test_a_suspended_client_cannot_log_in_but_is_not_deleted(gateway_conn):
    """Suspension is not deletion.

    This used to also assert that the client's stored holdings survived. There
    are none to survive (§111) - a client's positions live at their own external
    sources, so suspending a login cannot touch them by construction rather than
    by care. The registration surviving is what is left to check, and it is the
    part that was ever this module's."""
    _, password = clients.register(gateway_conn, "alice")

    clients.set_status(gateway_conn, "alice", clients.STATUS_SUSPENDED)
    assert clients.authenticate(gateway_conn, "alice", password) is None
    assert clients.get(gateway_conn, "alice") is not None, "suspension deleted the client"

    clients.set_status(gateway_conn, "alice", clients.STATUS_ACTIVE)
    assert clients.authenticate(gateway_conn, "alice", password) == "alice"


def test_an_unrecognised_status_denies_rather_than_defaulting(gateway_conn):
    """Fail closed: a status this build cannot interpret is not one it may act
    on, and guessing what it permits is the wrong direction to guess in."""
    _, password = clients.register(gateway_conn, "alice")
    gateway_conn.execute("UPDATE clients SET status = 'pending-review'")

    with pytest.raises(clients.UnknownStatus):
        clients.authenticate(gateway_conn, "alice", password)


def test_an_unknown_status_is_refused_when_set(gateway_conn):
    clients.register(gateway_conn, "alice")
    with pytest.raises(clients.UnknownStatus):
        clients.set_status(gateway_conn, "alice", "probation")


def test_a_malformed_stored_hash_refuses_rather_than_raising(gateway_conn):
    """One bad row must not become a 500 that leaks a stack trace to an external
    caller."""
    clients.register(gateway_conn, "alice")
    gateway_conn.execute("UPDATE clients SET password_hash = 'not-a-hash'")
    assert clients.authenticate(gateway_conn, "alice", "anything") is None


# --- §9.3: an outsider learns nothing about who exists ------------------------------


def test_an_unknown_username_costs_the_same_as_a_wrong_password(gateway_conn):
    """Addendum 44 §9.3 says an error must not reveal that another client
    exists. Returning early for an unregistered name would leak exactly that
    through timing, so an unknown name is compared against a decoy hash.

    Asserted structurally rather than by stopwatch - a timing assertion on a
    shared CI runner measures the runner."""
    import inspect

    source = inspect.getsource(clients.authenticate)
    assert "_DECOY_HASH" in source
    early_return = source.index("return None")
    checkpw = source.index("bcrypt.checkpw")
    assert checkpw < early_return, "authenticate returns before hashing for unknown users"


def test_an_unknown_user_and_a_wrong_password_are_the_same_answer(gateway_conn):
    clients.register(gateway_conn, "alice")
    assert clients.authenticate(gateway_conn, "alice", "wrong") is None
    assert clients.authenticate(gateway_conn, "nobody", "wrong") is None


# --- removing a login is not removing a person --------------------------------------


def test_removing_a_login_touches_nothing_but_the_login(gateway_conn):
    """Deleting somebody's financial records as a side effect of revoking a login
    is not a decision this function is entitled to make - and since §111 it is
    not a decision anything here *could* make, because there are no records to
    delete. The client's positions are at their own external sources.

    What remains checkable is that removal is scoped to the registry."""
    clients.register(gateway_conn, "alice")
    clients.register(gateway_conn, "bob")

    assert clients.remove(gateway_conn, "alice") is True

    assert clients.get(gateway_conn, "alice") is None
    assert clients.get(gateway_conn, "bob") is not None


def test_removing_somebody_who_is_not_there_says_so(gateway_conn):
    assert clients.remove(gateway_conn, "nobody") is False


# --- the demo clients now have doors ------------------------------------------------


def _pre_alpha(monkeypatch, tmp_path):
    import json

    from backend import boot_config

    config = tmp_path / "boot-dev.json"
    config.write_text(json.dumps({
        "lifecycle_stage": "PRE_ALPHA",
        "global_asset_classes": ["stock", "stock_option"],
        "implemented_asset_classes": ["stock", "stock_option"],
        "current_focus": ["REFERENCE_DATA"],
        "simulation_focus": ["OPTIONS_ON_EQUITIES_PRICING"],
    }), encoding="utf-8")
    monkeypatch.setenv(boot_config.PATH_ENV, str(config))


def test_every_demo_client_can_log_in_as_itself(gateway_conn, monkeypatch, tmp_path):
    """The gap TQ-42's demo recorded and TQ-43 closes: three clients, three
    logins, three subjects. The isolation can now be walked into rather than
    only asserted."""
    from gateway import demo_clients

    _pre_alpha(monkeypatch, tmp_path)
    demo_clients.seed(gateway_conn)

    for client_id in demo_clients.DEMO_CLIENTS:
        assert clients.authenticate(
            gateway_conn, client_id, demo_clients.DEMO_PASSWORD) == client_id


def test_demo_logins_are_flagged_and_cleared_with_the_rest(gateway_conn, monkeypatch, tmp_path):
    from gateway import demo_clients

    _pre_alpha(monkeypatch, tmp_path)
    demo_clients.seed(gateway_conn)
    assert len(clients.listing(gateway_conn)) == len(demo_clients.DEMO_CLIENTS)

    demo_clients.clear(gateway_conn)

    assert clients.listing(gateway_conn) == []
    assert demo_clients.outstanding(gateway_conn)["clean"] is True


def test_clearing_demo_data_leaves_a_real_client_alone(gateway_conn, monkeypatch, tmp_path):
    from gateway import demo_clients

    _pre_alpha(monkeypatch, tmp_path)
    demo_clients.seed(gateway_conn)
    _, password = clients.register(gateway_conn, "real-person")

    demo_clients.clear(gateway_conn)

    assert clients.authenticate(gateway_conn, "real-person", password) == "real-person"
