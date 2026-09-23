"""Two things that work here and fail on the machine this is for.

Jarvis is written on Linux and runs on Krish's Windows PC. Everything in this
file is a bug that passed every local run, passed review, and failed only on the
platform that matters - which is the worst shape a bug can have, because the
evidence arrives last and from the place you cannot debug.

Both were found on 2026-09-23 by the Windows CI runner, in code that had been
merged and looked fine:

- `f"{due:%-d %B}"` - `%-d` is a glibc extension rather than C, and Windows
  raises `ValueError: Invalid format string`. It took out every noticing there
  is, which is to say the whole feature whose job is to speak up first.
- `Path.read_text()` with no encoding, on a file containing an em-dash. Python
  falls back to the locale encoding, which on Windows is cp1252, and the
  constitution's amendment headings came back mangled. A test comparing them
  failed; had nothing compared them, Krish would have read the mangled text.

Neither is caught by reading the code, because neither looks wrong. They are
caught by a rule, applied to all of it, which is what this file is.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Where our own code lives. Not the whole tree: a vendored dependency is not
# ours to hold to this, and `.venv` would make the run take minutes.
OURS = ("app", "backend", "dba", "desktop", "gateway", "scripts", "tests")

# `%-d` is glibc, `%#d` is the Microsoft C runtime, and each raises on the
# other's platform. There is no portable spelling, which is the point: the
# number has to be built rather than formatted.
PLATFORM_ONLY = re.compile(r"%[-#][a-zA-Z]")


def _our_python():
    for directory in OURS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _date_formats(tree):
    """Every string used as a date format: an f-string's format spec, and the
    argument to `strftime`. Deliberately not every string in the file - "50%-off"
    is not a date format, and a scan that flags it gets turned off."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FormattedValue) and node.format_spec:
            for piece in ast.walk(node.format_spec):
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    yield piece
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "strftime"):
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    yield argument


def test_no_date_format_that_only_works_on_one_platform():
    """`%-d` on Windows and `%#d` on Linux both raise rather than degrade, so
    this cannot be left to whoever writes the next date."""
    found = []
    for path in _our_python():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _date_formats(tree):
            if PLATFORM_ONLY.search(node.value):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}: "
                             f"{node.value!r}")
    assert not found, (
        "these use a strftime directive that exists on one platform and raises "
        "on the other; build the number instead, as gateway.noticing._day "
        "does:\n  " + "\n  ".join(found))


def test_every_text_file_is_read_and_written_as_utf8():
    """Without `encoding=`, Python uses the locale's - cp1252 on Krish's machine
    - and a file this repository wrote as UTF-8 comes back wrong or raises. The
    failure is in the data rather than in the code, so it surfaces late and
    somewhere else."""
    found = []
    for path in _our_python():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("read_text", "write_text")
                    and not any(word.arg == "encoding" for word in node.keywords)):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}: "
                             f".{node.func.attr}()")
    assert not found, (
        "these read or write text with no encoding, so they use the machine's "
        "locale; pass encoding=\"utf-8\":\n  " + "\n  ".join(found))


def test_the_day_helper_gives_the_day_without_a_leading_zero():
    """The thing `%-d` was reached for, which is why it has to still be true."""
    from datetime import datetime, timezone

    from gateway import noticing

    assert noticing._day(datetime(2026, 10, 3, tzinfo=timezone.utc)) == "3 October"
    assert noticing._day(datetime(2026, 10, 30, tzinfo=timezone.utc)) == "30 October"


def test_this_file_would_notice_the_two_bugs_it_was_written_for(tmp_path):
    """A guard nobody has seen fail is a guard nobody knows is connected.

    Rather than trust that the scan works, run it over a file that has both
    faults in it and check each one is named."""
    guilty = tmp_path / "guilty.py"
    guilty.write_text(
        'from pathlib import Path\n'
        'def f(due, path):\n'
        '    said = f"due on {due:%-d %B}"\n'
        '    return said, Path(path).read_text()\n', encoding="utf-8")

    tree = ast.parse(guilty.read_text(encoding="utf-8"))

    formats = [node.value for node in _date_formats(tree)
               if PLATFORM_ONLY.search(node.value)]
    assert formats, "the scan did not see a %-d inside an f-string format spec"

    unencoded = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "read_text"
                 and not any(word.arg == "encoding" for word in node.keywords)]
    assert len(unencoded) == 1
