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

while ($true) {
  if (-not (Alive)) {
    Say 'gateway not answering /health - starting it'
    Start-Process -FilePath $python -ArgumentList '-m','gateway.run' `
      -WorkingDirectory $root -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 10
    if (Alive) { Say 'gateway is up' } else { Say 'STILL DOWN after start attempt' }
  }
  Start-Sleep -Seconds 30
}
