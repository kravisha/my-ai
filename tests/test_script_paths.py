"""The PC scripts find the repository and Python where they are, not where they
were written.

2026-10-19: Jarvis had been offline on the PC he lives on for weeks. Every
startup script named `C:\\Python314\\python.exe` and every task registration named
`C:\\Users\\Krish\\ClaudeStuff\\my-ai`. That machine has neither - the repository
is under `Deployments` and Python is 3.13 in the user profile - so the logon
tasks had nothing to run and the keep-alive launched a path that did not exist,
into a hidden window, for ever. Nothing on Linux could see it.

These read the scripts as text because PowerShell is not here to run them.
"""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _scripts():
    found = sorted(SCRIPTS.glob("*.ps1"))
    assert len(found) >= 10, "the scripts directory moved or emptied"
    return found


def _code(path):
    """The script without its comments, which are allowed to tell the history."""
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))


def test_no_script_assumes_the_folder_it_was_written_in():
    stuck = [one.name for one in _scripts()
             if re.search(r"ClaudeStuff", _code(one), re.IGNORECASE)]
    assert stuck == []


def test_no_script_assigns_a_fixed_python():
    """`C:\\Python314` may appear only as one candidate inside the finder."""
    stuck = [one.name for one in _scripts()
             if one.name != "jarvis-python.ps1"
             and re.search(r"\$python\s*=\s*'", _code(one))]
    assert stuck == []


def test_every_script_that_runs_python_finds_it_the_same_way():
    runs_python = [one for one in _scripts()
                   if re.search(r"\$python\b", _code(one))
                   and one.name != "jarvis-python.ps1"]
    assert sorted(one.name for one in runs_python) == [
        "jarvis-bringup.ps1", "keep-jarvis-up.ps1",
        "register-jarvis-self-diagnosis.ps1", "start-jarvis-gateway.ps1"]
    for one in runs_python:
        code = _code(one)
        assert "jarvis-python.ps1" in code, one.name
        assert "Find-JarvisPython $root" in code, one.name


def test_the_finder_tries_the_explicit_choice_then_the_repository_s_own():
    code = _code(SCRIPTS / "jarvis-python.ps1")
    order = [code.index(marker) for marker in (
        "$env:JARVIS_PYTHON", r".venv\Scripts\python.exe",
        r"C:\Python314\python.exe", "Get-Command py", "Get-Command python")]
    assert order == sorted(order)
    assert "return $null" in code


def test_the_supervisors_stop_and_say_so_when_there_is_no_python():
    """Rather than Start-Process on nothing every 30 seconds."""
    for name in ("keep-jarvis-up.ps1", "start-jarvis-gateway.ps1"):
        code = _code(SCRIPTS / name)
        assert "if (-not $python)" in code, name
        assert "NO PYTHON FOR JARVIS" in code, name
