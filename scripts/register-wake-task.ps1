# Registers the task that wakes Claude Dev after a reboot and every 15 minutes.
#
# Krish must run this himself: Claude Code's safety classifier will not let an
# agent create a scheduled task. That is the correct restriction and this is the
# seam it leaves.
#
# Pairs with JarvisGateway. That one keeps the Gateway answering so Krish can
# SEND; this one keeps Claude Dev reading so someone ANSWERS. Both are needed:
# on 2026-09-14 every component was healthy and the system was still silent,
# because nothing restarted the only thing that reads.

$me     = "$env:USERDOMAIN\$env:USERNAME"
$script = 'C:\Users\Krish\ClaudeStuff\my-ai\scripts\wake-claude-dev.ps1'

if (-not (Test-Path -LiteralPath $script)) { throw "MISSING: $script" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $script)

# Two triggers. Logon covers the reboot Krish actually wants to test; the
# repeating one covers the ordinary case where the machine never restarted but a
# message arrived. Without the second, a reboot would be the only thing that
# ever made Claude Dev read his phone.
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $me
$every15 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
             -RepetitionInterval (New-TimeSpan -Minutes 15) `
             -RepetitionDuration (New-TimeSpan -Days 30)

$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
         -StartWhenAvailable -MultipleInstances IgnoreNew `
         -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive

Register-ScheduledTask -TaskName 'ClaudeDevWake' -Action $action `
  -Trigger @($atLogon, $every15) -Settings $set -Principal $principal -Force `
  -Description 'Wakes Claude Dev to read Krish phone messages and reply via CLAUDE-TO-KRISH.md.' | Out-Null

Get-ScheduledTask -TaskName 'ClaudeDevWake' | Select-Object TaskName, State | Format-Table -AutoSize

Write-Host ''
Write-Host 'Both tasks should now exist:'
Get-ScheduledTask -TaskName 'JarvisGateway','ClaudeDevWake' -ErrorAction SilentlyContinue |
  Select-Object TaskName, State | Format-Table -AutoSize
Write-Host 'Log after it runs:  $env:TEMP\claude-dev-wake.log'
Write-Host 'To remove:  Unregister-ScheduledTask -TaskName ClaudeDevWake -Confirm:$false'
