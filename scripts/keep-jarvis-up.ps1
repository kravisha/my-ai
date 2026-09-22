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
#
# THREE CHILDREN NOW, AND THE ORDER MATTERS. The DBA Agent starts first, because
# Jarvis rehydrates through it: a Gateway that comes up before the DBA reports
# DBA_UNAVAILABLE and operates with no memory, which is honest but useless when
# the memory was there all along. The Persistence specification's SS3 step 3 is
# "bring the DBA Agent online", and this is where that happens - not inside
# Jarvis, who must not be able to start and stop the service holding his own
# memory.
#
# THIS SCRIPT IS ALSO THE BUILD/RELAUNCH CONTROLLER (SS19). When Jarvis writes
# an approved change to deploy-request.json, scripts/deploy_jarvis.py verifies
# the approval against the DBA, checks the commit out, runs the suite, and only
# a green suite gets restarted into. Jarvis cannot do any of that himself, which
# is the point: the process being replaced is never the process performing the
# replacement.

$ErrorActionPreference = 'Continue'
$root        = Split-Path -Parent $PSScriptRoot
$python      = 'C:\Python314\python.exe'
$cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$port        = 8100
$dbaPort     = 8200
$urlFile     = Join-Path $root 'CURRENT-URL.txt'
$cfLog       = Join-Path $env:TEMP 'jarvis-tunnel.log'
$runLog      = Join-Path $env:TEMP 'jarvis-keepup.log'
$channel     = 'C:\Users\Krish\Documents\Aria-Claude-Communications\Arya-Claude - Ongoing Conversation.md'
$deployReq   = Join-Path $root 'deploy-request.json'

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

function DBA-Alive {
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:$dbaPort/health" -TimeoutSec 5 -UseBasicParsing
    return $r.StatusCode -eq 200
  } catch { return $false }
}

function Start-DBA {
  Say 'starting DBA agent'
  Start-Process -FilePath $python `
    -ArgumentList '-m','uvicorn','dba.main:app','--port',"$dbaPort" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru
}

# SS19. Returns $true when a new build was deployed and the Gateway should be
# restarted into it. Everything else - a refused request, a red suite, a failed
# checkout - leaves the running build exactly where it was, and the deployer
# writes deploy-result.json either way so that Jarvis can read afterwards what
# was done to him.
function Deploy-IfRequested {
  if (-not (Test-Path $deployReq)) { return $false }
  Say 'deploy request found - verifying approval and running the suite'
  & $python (Join-Path $root 'scripts\deploy_jarvis.py')
  if ($LASTEXITCODE -eq 0) {
    Say 'approved change deployed and green - restarting into it'
    return $true
  }
  Say 'deploy refused or tests failed - staying on the current build'
  return $false
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
$dba = $null
$tun = @{ Proc = $null; Url = $null }

while ($true) {
  # The DBA first, and before the Gateway is even checked. Jarvis restores
  # through it; bringing him up against a store that is not there costs a boot
  # that has to report it has no memory.
  if (-not (DBA-Alive)) {
    Say 'DBA not answering /health'
    if ($dba -and -not $dba.HasExited) { Stop-Process -Id $dba.Id -Force -ErrorAction SilentlyContinue }
    $dba = Start-DBA
    Start-Sleep -Seconds 5
  }

  if (Deploy-IfRequested) {
    if ($gw -and -not $gw.HasExited) { Stop-Process -Id $gw.Id -Force -ErrorAction SilentlyContinue }
    $gw = Start-Gateway
    Start-Sleep -Seconds 8
  }

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
