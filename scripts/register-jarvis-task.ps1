# Registers the logon task that boots Jarvis (DEV-CANONICAL-BOOT-01).
#
# Claude Code's safety classifier will not let an agent create a scheduled
# task, so this is the one step Krish has to run himself. It is small, it is
# reversible, and the removal command is printed at the end.
#
# WHAT CHANGED, AND WHY (CANONICAL-BOOT-PROPOSAL R3):
# - It runs scripts/jarvis-boot.ps1, a ONE-SHOT (DBA gate first, then the
#   Gateway), not the old start-jarvis-gateway.ps1 daemon. The 5-minute
#   repetition IS the retry: a one-shot that dies is simply run again, a daemon
#   that wedges stays dead.
# - No RestartOnFailure. jarvis-boot exits 3 when it starts the Gateway
#   degraded; with a restart policy that exit would loop. RestartCount is 0.
# - No hard-coded user path. The boot script is resolved from this file's own
#   location, so the same file works on any host and any user.
# - The definition is a PURE function (New-JarvisTaskDefinition), so what gets
#   registered is tested without registering anything (tests/ps/test-jarvis-boot.ps1, B6).
#
# NOT YET RUN ANYWHERE. Migrating DEPLOYMENT-PC from its live "Jarvis Gateway"
# task is a separate, separately authorised step: read that host's existing task
# settings first and compare them with this definition.

$TaskName = 'JarvisGateway'

function New-JarvisTaskDefinition {
    <#
      Everything that will be registered, as plain data. No cmdlet that touches
      the scheduler is called here.
    #>
    param([Parameter(Mandatory)] [string]$BootScript)
    [pscustomobject]@{
        TaskName          = $TaskName
        Execute           = 'powershell.exe'
        # -File with the path QUOTED: a root with spaces must survive.
        Argument          = ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $BootScript)
        AtLogOn           = $true
        RepetitionMinutes = 5
        RestartCount      = 0
        MultipleInstances = 'IgnoreNew'
        ExecutionLimit    = [TimeSpan]::FromMinutes(10)
    }
}

function Register-JarvisTask([Parameter(Mandatory)] $Definition) {
    $me = "$env:USERDOMAIN\$env:USERNAME"
    $action  = New-ScheduledTaskAction -Execute $Definition.Execute -Argument $Definition.Argument
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
    # The repetition rides on the logon trigger: every 5 minutes, indefinitely.
    $repeat  = New-ScheduledTaskTrigger -Once -At (Get-Date) `
                 -RepetitionInterval (New-TimeSpan -Minutes $Definition.RepetitionMinutes)
    $trigger.Repetition = $repeat.Repetition
    $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -ExecutionTimeLimit $Definition.ExecutionLimit -StartWhenAvailable `
             -MultipleInstances $Definition.MultipleInstances
    $p = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive
    Register-ScheduledTask -TaskName $Definition.TaskName -Action $action -Trigger $trigger `
        -Settings $set -Principal $p -Force `
        -Description 'Boots Jarvis: DBA gate first, then one Gateway. One-shot; the 5-minute repetition is the retry.' | Out-Null
}

# Run only when executed, not when dot-sourced by the tests.
if ($MyInvocation.InvocationName -ne '.') {
    $boot = (Resolve-Path (Join-Path $PSScriptRoot 'jarvis-boot.ps1')).Path
    $def = New-JarvisTaskDefinition -BootScript $boot
    Register-JarvisTask $def
    Get-ScheduledTask -TaskName $def.TaskName | Select-Object TaskName, State | Format-Table -AutoSize
    Write-Host ''
    Write-Host 'To remove it later:'
    Write-Host "  Unregister-ScheduledTask -TaskName $($def.TaskName) -Confirm:`$false"
}
