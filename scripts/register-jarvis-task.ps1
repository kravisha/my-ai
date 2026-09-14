# Registers the logon task that keeps the Jarvis Gateway alive.
#
# Claude Code's safety classifier will not let an agent create a scheduled
# task, so this is the one step Krish has to run himself. It is small, it is
# reversible, and the removal command is printed at the end.
#
# What it does: at every logon, starts scripts/start-jarvis-gateway.ps1 hidden,
# which polls http://127.0.0.1:8100/health every 30 seconds and restarts the
# Gateway whenever it stops answering. Tested 2026-09-14 18:09: the Gateway was
# killed deliberately and the keepalive brought it back in 15 seconds.
#
# Tailscale is NOT handled here and does not need to be. Its service is
# Automatic and the serve configuration persists in tailscaled's own state, so
# https://<your-host>.ts.net returns by itself after a reboot.

$me     = "$env:USERDOMAIN\$env:USERNAME"
$script = 'C:\Users\Krish\ClaudeStuff\my-ai\scripts\start-jarvis-gateway.ps1'

if (-not (Test-Path -LiteralPath $script)) { throw "MISSING: $script" }

$action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
             -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $script)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
$set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
             -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$p       = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive

Register-ScheduledTask -TaskName 'JarvisGateway' -Action $action -Trigger $trigger `
  -Settings $set -Principal $p -Force `
  -Description 'Keeps the Jarvis Gateway on 127.0.0.1:8100 alive so the Tailscale phone URL keeps answering.' | Out-Null

Start-ScheduledTask -TaskName 'JarvisGateway'
Start-Sleep -Seconds 12

Get-ScheduledTask -TaskName 'JarvisGateway' | Select-Object TaskName, State | Format-Table -AutoSize
try {
  $code = (Invoke-WebRequest 'http://127.0.0.1:8100/health' -TimeoutSec 5 -UseBasicParsing).StatusCode
  Write-Host "gateway health: $code"
} catch { Write-Host 'gateway health: NOT ANSWERING' }

Write-Host ''
Write-Host 'To remove it later:'
Write-Host '  Unregister-ScheduledTask -TaskName JarvisGateway -Confirm:$false'
