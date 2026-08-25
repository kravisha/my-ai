"""The desktop entrypoint. A bootstrapper only.

Addendum 40 §4.1 states the invariant this file exists to keep: "main.py (or
equivalent launcher) must not become the business application. It is a
bootstrapper only." Everything here hands off immediately; the flow lives in
`desktop/bootstrap.py` and the organization lives behind it.

`tests/test_desktop_bootstrap.py` enforces that, because a launcher degrades
the same way an import-time side effect does — one convenient addition at a
time, unnoticed until it owns half the system.

Run as:  python -m desktop
"""

from desktop import bootstrap

if __name__ == "__main__":
    raise SystemExit(bootstrap.main())
