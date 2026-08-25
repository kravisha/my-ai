"""The desktop bootstrap, and the invariant it exists to keep (addendum 40
§4.1, §7.1; TQ-30, SPEC_RECONCILIATION §82).

Addendum 40 states one hard invariant: "main.py (or equivalent launcher) must
not become the business application. It is a bootstrapper only." That is the
same class of rule as this repository's import-time-side-effect guard, and it
fails the same way — one convenient addition at a time, unnoticed until the
launcher owns half the system. So it is enforced here rather than trusted to
a comment.

The other load-bearing test is the loopback one. It looks pedantic and is not:
a window given inline HTML has no origin, so no secure context, so no
microphone — which silently removes the input channel §11 makes the default.
"""

import ast
from pathlib import Path

import pytest

from desktop import bootstrap, shell

DESKTOP = Path(__file__).resolve().parent.parent / "desktop"
ENTRYPOINT = DESKTOP / "__main__.py"


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


# --- §4.1's hard invariant --------------------------------------------------------


def test_the_entrypoint_is_only_a_bootstrapper():
    """It may import the bootstrap and hand off. It may not define the
    application: no functions, no classes, no domain logic."""
    tree = _module(ENTRYPOINT)
    defined = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    assert not defined, (
        f"the entrypoint defines {[n.name for n in defined]}; addendum 40 §4.1 says it is a "
        "bootstrapper only - move this behind desktop/bootstrap.py"
    )
    statements = [n for n in tree.body if not isinstance(n, (ast.Expr, ast.Import, ast.ImportFrom))]
    assert len(statements) <= 2, (
        f"the entrypoint has grown to {len(statements)} statements; it should locate the "
        "bootstrap and hand control away"
    )


def test_the_entrypoint_imports_no_domain_modules():
    """It must not reach into the organization directly. Knowing about
    `backend.fi_db` or an agent is how a launcher starts absorbing the
    business it is supposed to start."""
    source = ENTRYPOINT.read_text(encoding="utf-8")
    tree = _module(ENTRYPOINT)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
    forbidden = imported & {"backend", "agents", "simulation", "providers", "gateway", "app"}
    assert not forbidden, f"the entrypoint imports domain module(s) {sorted(forbidden)}"
    assert "bootstrap" in source


def test_the_bootstrap_hands_control_away_rather_than_holding_it():
    """`main` should read as a sequence that ends by handing off, not as the
    application. Pinned loosely - a length bound, not a shape - so the test
    catches accretion without dictating style."""
    tree = _module(DESKTOP / "bootstrap.py")
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert len(main.body) <= 20, (
        f"bootstrap.main has {len(main.body)} statements; §4.1's sequence is short by design and "
        "anything longer probably belongs in the runtime or a manager behind it"
    )


# --- §7.1: the shell knows nothing about the organization -------------------------


def test_the_shell_is_separable_from_coo_logic():
    """§7.1: "the backend should not care whether the current window is
    native desktop, browser Gateway, future mobile, or another surface." The
    converse has to hold too, or the separation is one-directional."""
    tree = _module(DESKTOP / "shell.py")
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
    assert not (imported & {"backend", "agents", "simulation", "providers", "gateway"}), (
        f"the shell imports organization modules: {sorted(imported)}"
    )


# --- the loopback requirement -----------------------------------------------------


def test_the_window_is_loaded_over_loopback_not_inline_html():
    """Measured, not assumed (§82): an inline-HTML window has no origin, so no
    secure context, so no getUserMedia - which silently removes the microphone
    that addendum 40 §11 makes the default input path. This is why the runtime
    starts before the window."""
    source = (DESKTOP / "shell.py").read_text(encoding="utf-8")
    assert "url=url" in source, "the shell must load a URL"
    assert "html=" not in source.replace("html= - see", ""), (
        "the shell must not load inline HTML: it loses the secure context and with it the mic"
    )
    assert bootstrap.console_url().startswith("http://127.0.0.1"), (
        "the console must be served from loopback, which Chromium treats as a secure origin"
    )


# --- runtime lifecycle ------------------------------------------------------------


def test_it_never_starts_a_second_runtime(monkeypatch):
    """Two servers on one database is the duplicate-brain error §13.1 forbids,
    turned on ourselves."""
    monkeypatch.setattr(bootstrap, "runtime_is_listening", lambda timeout=0.4: True)
    called = []
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *a, **k: called.append(a))
    assert bootstrap.start_runtime() is None
    assert not called, "a runtime was already listening and the bootstrap started another"


def test_the_port_is_configurable_and_read_at_call_time(monkeypatch):
    monkeypatch.delenv(bootstrap.PORT_ENV, raising=False)
    assert bootstrap.port() == bootstrap.DEFAULT_PORT
    monkeypatch.setenv(bootstrap.PORT_ENV, "8123")
    assert bootstrap.port() == 8123
    assert bootstrap.console_url() == "http://127.0.0.1:8123/console"


def test_first_run_and_waking_are_distinguishable(monkeypatch, tmp_path):
    """§4.2 wants a restart to feel like waking the same entity rather than
    starting a new session - a promise only checkable if the system knows
    which one happened."""
    from backend import fi_db

    monkeypatch.setattr(fi_db, "DB_PATH", tmp_path / "absent.db")
    assert bootstrap.has_run_before() is False

    existing = tmp_path / "fi.db"
    existing.write_bytes(b"")
    monkeypatch.setattr(fi_db, "DB_PATH", existing)
    assert bootstrap.has_run_before() is True


# --- §15: degrade, do not take the organization down ------------------------------


def test_a_missing_shell_reports_where_the_console_is(monkeypatch, capsys):
    """§15: a renderer failure must not end the runtime. The operator still
    has a browser, and should be told where to point it."""
    monkeypatch.setattr(shell, "available", lambda: False)
    shell.run("http://127.0.0.1:8000/console")
    assert "8000/console" in capsys.readouterr().err


def test_a_window_that_will_not_open_is_not_fatal(monkeypatch, capsys):
    monkeypatch.setattr(shell, "available", lambda: True)

    class _Boom:
        @staticmethod
        def create_window(*a, **k):
            return None

        @staticmethod
        def start(*a, **k):
            raise RuntimeError("no display")

    monkeypatch.setitem(__import__("sys").modules, "webview", _Boom)
    shell.run("http://127.0.0.1:8000/console")   # must not raise
    assert "still running" in capsys.readouterr().err
