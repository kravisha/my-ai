# Keeps Jarvis reachable from Krish's phone without anyone at the keyboard.
#
# Two children: the Gateway on loopback, and the tunnel that publishes it. Either
# can die; neither is allowed to stay dead. Written because Krish leaves on
# vacation tomorrow and the failure he cannot recover from is a tunnel that
# restarts while he is away, because a quick tunnel issues a NEW hostname each
# time and he would have no way to learn it.
#
# So: every restart writes the current URL to CURRENT-URL.txt AND appends it to
# the shared developer channel, which Claude Dev polls. If the address changes
# while Krish is away, Claude knows the new one and can tell him.
#
# Deliberately not a Windows service. A service runs as SYSTEM in session 0,
# which cannot see the user's Ollama instance or profile paths, and debugging one
# remotely is miserable. A scheduled task at logon runs as Krish, in his session,
# with his environment - which is the environment the Gateway was built against.

$ErrorActionPreference = 'Continue'
$root        = Split-Path -Parent $PSScriptRoot
$python      = 'C:\Python314\python.exe'
$cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$port        = 8100
$urlFile     = Join-Path $root 'CURRENT-URL.txt'
$cfLog       = Join-Path $env:TEMP 'jarvis-tunnel.log'
$runLog      = Join-Path $env:TEMP 'jarvis-keepup.log'
$channel     = 'C:\Users\Krish\Documents\Aria-Claude-Communications\Arya-Claude - Ongoing Conversation.md'

function Say($m) {
  $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
  Write-Host $line
  Add-Content -LiteralPath $runLog -Value $line -Encoding utf8
}

function Gateway-Alive {
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:$port/health" -TimeoutSec 5 -UseBasicParsing
    return $r.StatusCode -eq 200
  } catch { return $false }
}

function Start-Gateway {
  Say 'starting gateway'
  Start-Process -FilePath $python -ArgumentList '-m','gateway.run' `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru
}

function Start-Tunnel {
  if (Test-Path $cfLog) { Remove-Item $cfLog -Force -ErrorAction SilentlyContinue }
  Say 'starting tunnel'
  $p = Start-Process -FilePath $cloudflared `
        -ArgumentList @('tunnel','--no-autoupdate','--logfile',$cfLog,'--url',"http://127.0.0.1:$port") `
        -WindowStyle Hidden -PassThru
  # The hostname only exists once the tunnel registers; wait for it rather than
  # reporting a URL we have not seen.
  $url = $null
  for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $cfLog) {
      $m = Select-String -Path $cfLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($m) { $url = $m.Matches[0].Value; break }
    }
  }
  return @{ Proc = $p; Url = $url }
}

function Publish-Url($url) {
  if (-not $url) { Say 'TUNNEL PRODUCED NO URL'; return }
  Set-Content -LiteralPath $urlFile -Value $url -Encoding utf8
  Say "public URL: $url"
  if (Test-Path $channel) {
    $stamp = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
    $entry = @"

## $stamp | JARVIS-TUNNEL-URL | published by keep-jarvis-up
The phone URL has (re)started and is now:

    $url/voice

Quick tunnels issue a new hostname on every restart, so any earlier URL is dead.
Claude Dev: if Krish asks where to reach Jarvis, this is the current address.
"@
    Add-Content -LiteralPath $channel -Value $entry -Encoding utf8
    Say 'url written to shared channel'
  }
}

Say '=== keep-jarvis-up starting ==='
$gw  = $null
$tun = @{ Proc = $null; Url = $null }

while ($true) {
  if (-not (Gateway-Alive)) {
    Say 'gateway not answering /health'
    if ($gw -and -not $gw.HasExited) { Stop-Process -Id $gw.Id -Force -ErrorAction SilentlyContinue }
    $gw = Start-Gateway
    Start-Sleep -Seconds 8
  }

  if (-not $tun.Proc -or $tun.Proc.HasExited) {
    if ($tun.Proc) { Say 'tunnel exited - the URL will change' }
    $tun = Start-Tunnel
    Publish-Url $tun.Url
  }

  Start-Sleep -Seconds 20
}
