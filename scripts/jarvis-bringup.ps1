# Runs the bring-up check. One line, so that "does it work on my PC" is one line.
#
#   powershell -File scripts\jarvis-bringup.ps1
#   powershell -File scripts\jarvis-bringup.ps1 --make-key
#
# Deliberately thin. Every decision is in desktop/readiness.py and app/keystore.py
# where it is tested; this file exists only because `python` is not necessarily on
# PATH in the shell Krish happens to have open, and a status command that fails
# with "python is not recognized" is a status command that answers nothing.
#
# The interpreter is the same one keep-jarvis-up.ps1 uses, and for the same
# reason: a bring-up that checks a different Python than the one Jarvis runs in
# is checking the wrong machine.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

. (Join-Path $PSScriptRoot 'jarvis-python.ps1')
$python = Find-JarvisPython $root
if (-not $python) {
    Write-Host "No Python found: not `$env:JARVIS_PYTHON, not .venv, not on PATH."
    Write-Host "Install Python 3.11 or newer, then run this again."
    exit 1
}
Write-Host "using $python"

Push-Location $root
try {
    & $python -m desktop.bringup @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
