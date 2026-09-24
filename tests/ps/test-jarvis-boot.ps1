# test-jarvis-boot.ps1 - B1..B12 from CANONICAL-BOOT-PROPOSAL R3, fakes only.
# Nothing real is probed or started: every probe, gate and starter is injected,
# and the only process launched is a child `powershell -File` for the exit-code
# tests, which exits before any probe because its python does not exist.
#   powershell -NoProfile -ExecutionPolicy Bypass -File tests\ps\test-jarvis-boot.ps1
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$boot = Join-Path $repo 'scripts\jarvis-boot.ps1'
. $boot
$script:fail = 0; $script:pass = 0
function Check($name, $cond, $detail = '') {
    if ($cond) { $script:pass++; Write-Output "  PASS  $name" }
    else { $script:fail++; Write-Output "  FAIL  $name  $detail" }
}

# A root with spaces and nothing DevPC-shaped in it (B1).
$root = Join-Path $env:TEMP ("Jarvis Test Root " + [guid]::NewGuid().ToString('N').Substring(0, 6))
New-Item -ItemType Directory -Force -Path (Join-Path $root '.venv\Scripts') | Out-Null
$py = Join-Path $root '.venv\Scripts\python.exe'
Set-Content -LiteralPath $py -Value 'fake' -Encoding ascii          # exists; never executed
$logs = Join-Path $root 'logs\boot'

function Gate($state, $healthy) { { param($RemainingMs) [pscustomobject]@{ State = $state; Healthy = $healthy } }.GetNewClosure() }
function Probe($answer) { { param($RemainingMs) $answer }.GetNewClosure() }
function New-Starter {
    $s = [pscustomobject]@{ Calls = New-Object System.Collections.ArrayList; Order = $null }
    $s | Add-Member ScriptMethod Block { $self = $this; { param($Python, $Root, $Degraded) [void]$self.Calls.Add(@($Python, $Root, $Degraded)); [pscustomobject]@{ Id = 4242 } }.GetNewClosure() }
    $s
}
function Boot($gate, $probe, $starter, [int]$budget = 60, $elapsed = $null) {
    $a = @{ Root = $root; Python = $py; LogDir = $logs; DbaGate = $gate; GatewayProbe = $probe
            StartGateway = $starter; BudgetSeconds = $budget }
    if ($elapsed) { $a.ElapsedMs = $elapsed }
    Invoke-JarvisBoot @a
}

Write-Output 'B1  root with spaces, non-DevPC path: exact paths reach the starter'
$s = New-Starter; $r = Boot (Gate 'AlreadyUp' $true) (Probe 'Absent') $s.Block()
Check 'exit 0' ($r.ExitCode -eq 0) $r.ExitCode
Check 'starter got the exact python path' ($s.Calls.Count -eq 1 -and $s.Calls[0][0] -eq $py) ($s.Calls | Out-String)
Check 'starter got the exact root (spaces intact)' ($s.Calls[0][1] -eq $root)
Check 'source has no C:\Users literal' (-not (Select-String -LiteralPath $boot -Pattern 'C:\\Users' -SimpleMatch -Quiet))
$realStarter = (Get-RealGatewayStarter).ToString()
Check 'real starter passes argv as an array (-m gateway.run), not a joined string' ($realStarter -match "@\('-m', 'gateway\.run'\)")

Write-Output 'B2  order: the Gateway is never touched before the DBA gate answers'
$order = New-Object System.Collections.ArrayList
$g = { param($RemainingMs) [void]$order.Add('gate'); [pscustomobject]@{ State = 'AlreadyUp'; Healthy = $true } }.GetNewClosure()
$p = { param($RemainingMs) [void]$order.Add('probe'); 'Absent' }.GetNewClosure()
$st = { param($Python, $Root, $Degraded) [void]$order.Add('start'); [pscustomobject]@{ Id = 1 } }.GetNewClosure()
$null = Boot $g $p $st
Check 'gate -> probe -> start' (($order -join ',') -eq 'gate,probe,start') ($order -join ',')

Write-Output 'B3  DBA not healthy: Gateway started DEGRADED, exit 3, trace says so'
foreach ($case in @(@('StartFailed', $false), @('HealthTimeout', $false), @('ForeignPort', $false),
                    @('ProbeUnavailable', $null), @('GateMissing', $null))) {
    $s = New-Starter; $r = Boot (Gate $case[0] $case[1]) (Probe 'Absent') $s.Block()
    Check "$($case[0]): exit 3" ($r.ExitCode -eq 3) $r.ExitCode
    Check "$($case[0]): started once, flagged degraded" ($s.Calls.Count -eq 1 -and $s.Calls[0][2] -eq $true)
    Check "$($case[0]): trace says DEGRADED" (($r.Trace -join "`n") -match 'DEGRADED')
}
Check 'a null Healthy is logged UNKNOWN, not false' ((Boot (Gate 'ProbeUnavailable' $null) (Probe 'Absent') (New-Starter).Block()).Trace -join "`n" -match 'healthy=UNKNOWN')

Write-Output 'B4  both healthy: nothing started, exit 0'
$s = New-Starter; $r = Boot (Gate 'AlreadyUp' $true) (Probe 'Healthy') $s.Block()
Check 'exit 0' ($r.ExitCode -eq 0); Check 'starter never called' ($s.Calls.Count -eq 0)
$s = New-Starter; $r = Boot (Gate 'HealthTimeout' $false) (Probe 'Healthy') $s.Block()
Check 'Gateway healthy but DBA not: exit 3, still no start' ($r.ExitCode -eq 3 -and $s.Calls.Count -eq 0)

Write-Output 'B5  own Gateway still bound but unresponsive: no second process'
$s = New-Starter; $r = Boot (Gate 'AlreadyUp' $true) (Probe 'OwnUnresponsive') $s.Block()
Check 'exit 7' ($r.ExitCode -eq 7) $r.ExitCode; Check 'starter never called' ($s.Calls.Count -eq 0)

Write-Output 'B5b a start that produces no process is exit 2, never success (found missing by mutation)'
foreach ($gate in @((Gate 'AlreadyUp' $true), (Gate 'HealthTimeout' $false))) {
    $r = Boot $gate (Probe 'Absent') { param($a, $b, $c) $null }
    Check 'exit 2' ($r.ExitCode -eq 2) $r.ExitCode
    Check 'trace says no process' (($r.Trace -join ' ') -match 'produced no process')
}

Write-Output 'B6  the task definition, as data (nothing registered)'
# Shadow the scheduler cmdlets BEFORE dot-sourcing, so a registration at load
# time would be recorded rather than performed.
$script:schedCalls = New-Object System.Collections.ArrayList
function Register-ScheduledTask { [void]$script:schedCalls.Add('Register-ScheduledTask') }
function Start-ScheduledTask { [void]$script:schedCalls.Add('Start-ScheduledTask') }
. (Join-Path $repo 'scripts\register-jarvis-task.ps1')
Check 'dot-sourcing the register script registered and started nothing' ($script:schedCalls.Count -eq 0) ($script:schedCalls -join ',')
Remove-Item function:Register-ScheduledTask, function:Start-ScheduledTask
$bootInSpaces = Join-Path $root 'scripts\jarvis-boot.ps1'
$def = New-JarvisTaskDefinition -BootScript $bootInSpaces
Check 'runs powershell.exe' ($def.Execute -eq 'powershell.exe')
Check '-File path is QUOTED (a root with spaces survives)' ($def.Argument -like "*-File `"$bootInSpaces`"")
Check 'at logon' ($def.AtLogOn -eq $true)
# Literals, not constants: these three ARE the policy (Arya's migration check).
Check 'repeats every 5 minutes' ($def.RepetitionMinutes -eq 5) $def.RepetitionMinutes
Check 'RestartCount 0 (exit 3 must not loop)' ($def.RestartCount -eq 0) $def.RestartCount
Check 'MultipleInstances IgnoreNew' ($def.MultipleInstances -eq 'IgnoreNew') $def.MultipleInstances
$regSrc = Join-Path $repo 'scripts\register-jarvis-task.ps1'
Check 'no absolute user path literal in the register script' (-not (Select-String -LiteralPath $regSrc -Pattern 'C:\\Users' -SimpleMatch -Quiet))
Check 'no RestartInterval / restart-on-failure in the register script' (-not (Select-String -LiteralPath $regSrc -Pattern '-RestartInterval|-RestartCount' -Quiet))
Check 'the registration uses the definition, not its own literals' ((Get-Content -Raw -LiteralPath $regSrc) -match 'MultipleInstances \$Definition\.MultipleInstances')
Write-Output 'B7  missing venv python: loud, named, nothing probed'
$touched = New-Object System.Collections.ArrayList
$r = Invoke-JarvisBoot -Root $root -Python (Join-Path $root 'nope\python.exe') -LogDir $logs `
    -DbaGate { param($m) [void]$touched.Add('gate') }.GetNewClosure() -GatewayProbe { param($m) [void]$touched.Add('probe') }.GetNewClosure() `
    -StartGateway { param($a, $b, $c) [void]$touched.Add('start') }.GetNewClosure()
Check 'exit 4' ($r.ExitCode -eq 4) $r.ExitCode
Check 'the reason names the missing path' (($r.Trace -join ' ') -match [regex]::Escape('nope\python.exe'))
Check 'no gate, probe or start was attempted' ($touched.Count -eq 0) ($touched -join ',')
Check 'source has no PATH python fallback' (-not (Select-String -LiteralPath $boot -Pattern "Get-Command python|'python\.exe'\)|FilePath python\b" -Quiet))

Write-Output 'B8  logs: one new file per attempt, the previous one survives'
$before = @(Get-ChildItem -LiteralPath $logs -Filter 'boot-*.log')
$r1 = Boot (Gate 'AlreadyUp' $true) (Probe 'Healthy') (New-Starter).Block()
$r2 = Boot (Gate 'AlreadyUp' $true) (Probe 'Healthy') (New-Starter).Block()
Check 'two attempts, two different files' ($r1.Log -ne $r2.Log)
Check 'both files exist afterwards' ((Test-Path -LiteralPath $r1.Log) -and (Test-Path -LiteralPath $r2.Log))
Check 'file count grew by exactly 2' (@(Get-ChildItem -LiteralPath $logs -Filter 'boot-*.log').Count -eq $before.Count + 2)

Write-Output 'B9  foreign process on the Gateway port: reported, not ours, no start'
$s = New-Starter; $r = Boot (Gate 'AlreadyUp' $true) (Probe 'Foreign') $s.Block()
Check 'exit 5' ($r.ExitCode -eq 5) $r.ExitCode; Check 'starter never called' ($s.Calls.Count -eq 0)
Check 'trace does not call it healthy' (($r.Trace -join ' ') -notmatch 'healthy; nothing started')

Write-Output 'B10 unknown port state: never absent, never healthy, no start'
foreach ($answer in @('Unknown', $null, 'garbage', 42)) {
    $s = New-Starter; $r = Boot (Gate 'AlreadyUp' $true) (Probe $answer) $s.Block()
    Check "probe '$answer': exit 6, no start" ($r.ExitCode -eq 6 -and $s.Calls.Count -eq 0) $r.ExitCode
}

Write-Output 'B11 one whole-boot budget, passed into every blocking stage'
$seen = New-Object System.Collections.ArrayList
$t = [ref]0
$clock = { $t.Value }.GetNewClosure()
$g = { param($RemainingMs) [void]$seen.Add(@('gate', $RemainingMs)); $t.Value += 25000; [pscustomobject]@{ State = 'HealthTimeout'; Healthy = $false } }.GetNewClosure()
$p = { param($RemainingMs) [void]$seen.Add(@('probe', $RemainingMs)); $t.Value += 10000; 'Absent' }.GetNewClosure()
$s = New-Starter; $r = Boot $g $p $s.Block() 30 $clock
Check 'gate received the full 30000 ms' ($seen[0][1] -eq 30000) ($seen[0][1])
Check 'probe received only what the gate left (5000 ms)' ($seen[1][1] -eq 5000) ($seen[1][1])
Check 'budget spent before the start: exit 8, no start' ($r.ExitCode -eq 8 -and $s.Calls.Count -eq 0) $r.ExitCode
$t.Value = 0
$slowGate = { param($RemainingMs) $t.Value += 31000; [pscustomobject]@{ State = 'HealthTimeout'; Healthy = $false } }.GetNewClosure()
$s = New-Starter; $probed = [ref]$false
$r = Boot $slowGate { param($m) $probed.Value = $true; 'Absent' }.GetNewClosure() $s.Block() 30 $clock
Check 'a gate that overran the budget: exit 8, probe NOT run, no start' ($r.ExitCode -eq 8 -and -not $probed.Value -and $s.Calls.Count -eq 0)
# Real time: a boot whose stages each block ~400 ms must finish near the sum, not an unbounded wait.
$sw = [Diagnostics.Stopwatch]::StartNew()
$r = Boot { param($m) Start-Sleep -Milliseconds 400; [pscustomobject]@{ State = 'AlreadyUp'; Healthy = $true } } `
          { param($m) Start-Sleep -Milliseconds 400; 'Healthy' } (New-Starter).Block() 5
Check 'measured elapsed stays within the stated budget (5 s)' ($sw.ElapsedMilliseconds -lt 5000) "$($sw.ElapsedMilliseconds) ms"

Write-Output 'B12 exit codes survive powershell -File and a host wrapper'
$ErrorActionPreference = 'Continue'
& powershell -NoProfile -ExecutionPolicy Bypass -File $boot -Root $root -Python (Join-Path $root 'missing.exe') -LogDir $logs | Out-Null
$direct = $LASTEXITCODE
$wrapper = Join-Path $root 'host-wrapper.ps1'
Set-Content -LiteralPath $wrapper -Encoding utf8 -Value @(
    '# DEPLOYMENT-PC-style wrapper: host hooks, then the canonical boot; the code passes through.',
    "& '$boot' -Root '$root' -Python '$(Join-Path $root 'missing.exe')' -LogDir '$logs'",
    'exit $LASTEXITCODE')
& powershell -NoProfile -ExecutionPolicy Bypass -File $wrapper | Out-Null
$wrapped = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
Check 'direct -File run returns 4 to its caller' ($direct -eq 4) $direct
Check 'the wrapper returns the same 4 to the scheduler' ($wrapped -eq 4) $wrapped

Remove-Item -Recurse -Force -LiteralPath $root -ErrorAction SilentlyContinue
Write-Output ("RESULT: {0} passed, {1} failed" -f $script:pass, $script:fail)
if ($script:fail) { exit 1 } else { exit 0 }
