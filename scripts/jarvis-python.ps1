# Which Python runs Jarvis. Dot-sourced by every script that starts him.
#
#   . (Join-Path $PSScriptRoot 'jarvis-python.ps1')
#   $python = Find-JarvisPython $root
#
# Written 2026-10-19, when Jarvis had been offline for weeks on the PC he lives
# on: every script named C:\Python314\python.exe, that machine has Python 3.13 in
# the user profile and a .venv in the repository, and Start-Process on a path
# that does not exist fails into a hidden window. The keep-alive loop then
# reported "gateway not answering" for ever with no cause.
#
# Order, first that exists wins:
#   1. $env:JARVIS_PYTHON         - an explicit choice beats every guess
#   2. <repo>\.venv\Scripts\python.exe - the repository's own environment
#   3. C:\Python314\python.exe   - the old hard-coded path, kept for the PC
#                                  it was written on
#   4. the py launcher's default 3.x, then `python` on PATH
#
# Returns $null when none exists. Callers say so and stop; starting nothing
# loudly beats starting the wrong interpreter quietly.

function Find-JarvisPython([string]$root) {
  $candidates = @()
  if ($env:JARVIS_PYTHON) { $candidates += $env:JARVIS_PYTHON }
  $candidates += (Join-Path $root '.venv\Scripts\python.exe')
  $candidates += 'C:\Python314\python.exe'
  foreach ($one in $candidates) {
    if ($one -and (Test-Path -LiteralPath $one)) { return $one }
  }
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if ($launcher) {
    $found = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
    if ($LASTEXITCODE -eq 0 -and $found -and (Test-Path -LiteralPath $found)) {
      return $found.Trim()
    }
  }
  $onPath = Get-Command python -ErrorAction SilentlyContinue
  if ($onPath) { return $onPath.Source }
  return $null
}
