# Brings the Jarvis Gateway back after a reboot and keeps it up.
#
# Written because Krish is away and the failure he cannot recover from is a
# machine that reboots overnight and never answers his phone again. Windows
# Update alone is enough to cause it.
#
# The tunnel is NOT handled here and does not need to be: Tailscale runs as an
# Automatic Windows service and its serve configuration is persisted in
# tailscaled's own state, so https://<your-host>.ts.net comes back by
# itself. That is the whole reason Tailscale beat the quick tunnel -- a
# cloudflared restart would have issued a NEW hostname that Krish could not
# have learned from a beach.
#
# Deliberately a scheduled task at logon rather than a Windows service. A
# service runs as SYSTEM in session 0 and cannot see the user profile paths or
# the local Ollama instance the Gateway was built against.

$ErrorActionPreference = 'Continue'
$root   = Split-Path -Parent $PSScriptRoot
$python = 'C:\Python314\python.exe'
$port   = 8100
$log    = Join-Path $env:TEMP 'jarvis-gateway-keepalive.log'

function Say($m) {
  $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
  Add-Content -LiteralPath $log -Value $line -Encoding utf8
}

function Alive {
  try {
    (Invoke-WebRequest "http://127.0.0.1:$port/health" -TimeoutSec 5 -UseBasicParsing).StatusCode -eq 200
  } catch { $false }
}

Say '=== start-jarvis-gateway launched ==='

function Clear-WedgedGateway {
  <#
    A DEAD gateway frees port 8100 and the replacement binds cleanly. A WEDGED
    one does not: it still owns the port, accepts the connection and never
    answers, so /health fails while the socket stays held. Starting a second
    process then achieves nothing - it cannot bind, it exits, and the loop
    repeats every 30 seconds forever while Krish sees only silence.

    That is not a hypothetical. Today alone robocopy, MTP enumeration, iCloud
    hydration and a local model all failed by STOPPING rather than by erroring.
    It is the house failure mode and the first version of this script had no
    answer to it.

    Only processes whose command line is our own `gateway.run` are killed. If
    something ELSE owns the port we log it loudly and leave it alone: killing a
    stranger's process on an unattended machine is worse than staying down and
    saying so.
  #>
  $ours = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'gateway\.run' })
  foreach ($p in $ours) {
    Say ("killing unresponsive gateway pid " + $p.ProcessId + " (holds the port, fails /health)")
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
  if ($ours.Count -gt 0) { Start-Sleep -Seconds 3 }

  # Whatever still holds 8100 after that is not ours.
  try {
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($owner) {
      $proc = Get-Process -Id $owner.OwningProcess -ErrorAction SilentlyContinue
      Say ("PORT $port IS HELD BY A FOREIGN PROCESS: " + $proc.ProcessName +
           " pid " + $owner.OwningProcess + " - NOT killing it. The Gateway cannot start " +
           "until that is resolved by a human.")
    }
  } catch { }
}

while ($true) {
  if (-not (Alive)) {
    Say 'gateway not answering /health'
    Clear-WedgedGateway
    Say 'starting gateway'
    Start-Process -FilePath $python -ArgumentList '-m','gateway.run' `
      -WorkingDirectory $root -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 10
    if (Alive) { Say 'gateway is up' } else { Say 'STILL DOWN after start attempt' }
  }
  Start-Sleep -Seconds 30
}
