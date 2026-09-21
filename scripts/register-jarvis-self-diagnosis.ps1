# Registers the nightly self-diagnosis (Task 01, Deliverable C).
#
# Krish must run this: the classifier will not let an agent create a scheduled
# task, and that restriction is correct.
#
# What it runs is `python -m app.self_diagnosis --if-due`, which decides for
# itself what is owed - the nightly always, the weekly roll-up on its weekday,
# the skills audit on the first of the month - and writes nothing twice.
# The schedule lives in config/router.yaml (`self_diagnosis.hour`), so this
# task deliberately fires HOURLY rather than at a fixed time: a machine that
# was asleep at 03:00 would otherwise skip a night silently, and a fixed
# trigger here would be a second copy of a schedule that already has one file.
#
# The report reads logs/model_calls.jsonl and writes into reports/. Both are
# gitignored: they are what this machine did, not what the code is.

$root   = 'C:\Users\Krish\ClaudeStuff\my-ai'
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) { throw "MISSING: $python" }

$me = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute $python `
            -Argument '-m app.self_diagnosis --if-due' -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
            -RepetitionInterval (New-TimeSpan -Hours 1)

$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
         -StartWhenAvailable -MultipleInstances IgnoreNew `
         -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive

Register-ScheduledTask -TaskName 'JarvisSelfDiagnosis' -Action $action -Trigger $trigger `
  -Settings $set -Principal $principal -Force `
  -Description 'Jarvis reads his own model call log and writes reports/self_diagnosis_*.md.' | Out-Null

Write-Host "Registered JarvisSelfDiagnosis. It checks hourly and writes when config/router.yaml says it is due."
Write-Host "Run one now with:  $python -m app.self_diagnosis --nightly"
