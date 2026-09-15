# Registers Jarvis's logon greeting, which also opens Claude Code.
#
# Krish must run this: the classifier will not let an agent create a scheduled
# task, and that restriction is correct.
#
# Third and last of the logon tasks, and they do different jobs:
#
#   JarvisGateway    keeps the Gateway answering, so Krish can SEND from abroad
#   ClaudeDevWake    polls for his messages, so someone ANSWERS (currently
#                    blocked on headless OAuth - see the handoff)
#   JarvisGreeting   THIS ONE: says hello with the right part of the day, tells
#                    his phone the machine came back, and opens an interactive
#                    Claude Code window he can type Providence into
#
# A 20-second delay so the Gateway is usually up before the greeting claims the
# system is back. Claiming readiness before it is true is the failure we have
# spent all day naming.

$me     = "$env:USERDOMAIN\$env:USERNAME"
$script = 'C:\Users\Krish\ClaudeStuff\my-ai\scripts\jarvis-good-morning.ps1'

if (-not (Test-Path -LiteralPath $script)) { throw "MISSING: $script" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $script)

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
$trigger.Delay = 'PT20S'

$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
         -StartWhenAvailable -MultipleInstances IgnoreNew `
         -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive

Register-ScheduledTask -TaskName 'JarvisGreeting' -Action $action -Trigger $trigger `
  -Settings $set -Principal $principal -Force `
  -Description 'Jarvis greets Krish at logon, tells his phone the machine is back, and opens Claude Code.' | Out-Null

Write-Host 'All three logon tasks:'
Get-ScheduledTask -TaskName 'JarvisGateway','ClaudeDevWake','JarvisGreeting' -ErrorAction SilentlyContinue |
  Select-Object TaskName, State | Format-Table -AutoSize

Write-Host 'Log:      $env:TEMP\jarvis-good-morning.log'
Write-Host 'Remove:   Unregister-ScheduledTask -TaskName JarvisGreeting -Confirm:$false'
