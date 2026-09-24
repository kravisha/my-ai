# jarvis-boot.ps1 - the canonical, ONE-SHOT Jarvis boot (DEV-CANONICAL-BOOT-01).
#
# One run: bring the DBA up through its gate, then make sure exactly one Gateway
# is running, then exit with a code that says what happened. The scheduler's
# 5-minute timer is the retry; nothing here loops. A one-shot that dies is
# retried on the next tick, a daemon that wedges stays dead (Deploy's rationale,
# CANONICAL-BOOT-PROPOSAL R3).
#
# Every decision is made in Invoke-JarvisBoot from TYPED answers, so the tests
# (tests/ps/test-jarvis-boot.ps1) drive it with fakes and nothing real starts.
# The real probes and starter are thin adapters at the bottom.
#
# Exit codes (the scheduler and any host wrapper must pass them through):
#   0  Gateway healthy, DBA healthy
#   2  a Gateway start was attempted and did not produce a process
#   3  DEGRADED: Gateway running or started, but the DBA is not confirmed healthy
#   4  the venv python is missing - no guess from PATH
#   5  something FOREIGN holds the Gateway port - not ours, not killed
#   6  the Gateway port's state is UNKNOWN - no start decided on an unknown
#   7  our own Gateway holds the port and does not answer - no second process
#   8  the whole-boot budget ran out before a start could be decided
#
# The DBA gate is Claude Deploy's (scripts/dba-gate.ps1, his to move into the
# repo). This script only CONSUMES its typed result {State, Healthy}; Healthy is
# $true / $false / $null and $null means NOT MEASURED, never absent.

param([string]$Root = '', [string]$Python = '', [string]$LogDir = '',
      [int]$BudgetSeconds = 60)

$ErrorActionPreference = 'Stop'

# Gateway port states the probe may return. Anything else is treated as UNKNOWN.
$script:GatewayStates = @('Healthy', 'Absent', 'Foreign', 'OwnUnresponsive', 'Unknown')

function Invoke-JarvisBoot {
    param(
        [Parameter(Mandatory)] [string]$Root,
        [Parameter(Mandatory)] [string]$Python,
        [Parameter(Mandatory)] [string]$LogDir,
        [Parameter(Mandatory)] [scriptblock]$DbaGate,        # param([int]$RemainingMs) -> {State; Healthy}
        [Parameter(Mandatory)] [scriptblock]$GatewayProbe,   # param([int]$RemainingMs) -> one of GatewayStates
        [Parameter(Mandatory)] [scriptblock]$StartGateway,   # param($Python, $Root, [bool]$Degraded) -> process or $null
        [int]$BudgetSeconds = 60,
        [scriptblock]$ElapsedMs = $null                      # injected clock for tests
    )
    $clock = [Diagnostics.Stopwatch]::StartNew()
    if (-not $ElapsedMs) { $ElapsedMs = { $clock.ElapsedMilliseconds }.GetNewClosure() }
    $budgetMs = $BudgetSeconds * 1000
    $trace = New-Object System.Collections.Generic.List[string]

    # One file per attempt, never appended over the last (F5): the attempt that
    # failed is the one whose log matters, and the next run must not erase it.
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss-fff')
    $log = Join-Path $LogDir ("boot-{0}-{1}-{2}.log" -f $stamp, $PID, [guid]::NewGuid().ToString('N').Substring(0, 6))
    function Note([string]$m) {
        $line = '{0} {1}' -f (Get-Date -Format 'HH:mm:ss.fff'), $m
        $trace.Add($m); Add-Content -LiteralPath $log -Value $line -Encoding utf8
    }
    function Done([int]$code, [string]$why) {
        Note "EXIT $code : $why"
        return [pscustomobject]@{ ExitCode = $code; Trace = @($trace); Log = $log }
    }
    function Remaining { [int]($budgetMs - (& $ElapsedMs)) }

    Note "boot root=$Root python=$Python budget=${BudgetSeconds}s"
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        return Done 4 "the venv python is missing at '$Python'; refusing to guess an interpreter from PATH"
    }

    # --- 1. the DBA gate, FIRST ---------------------------------------------------
    if ((Remaining) -le 0) { return Done 8 'budget exhausted before the DBA gate' }
    $dba = & $DbaGate (Remaining)
    $dbaHealthy = ($null -ne $dba) -and ($dba.Healthy -eq $true)
    $dbaState = if ($dba) { $dba.State } else { 'NoAnswer' }
    Note ("dba state={0} healthy={1}" -f $dbaState, $(if ($null -eq $dba -or $null -eq $dba.Healthy) { 'UNKNOWN' } else { $dba.Healthy }))

    # --- 2. the Gateway, only after the gate has answered -------------------------
    if ((Remaining) -le 0) { return Done 8 'budget exhausted before the Gateway probe; nothing started' }
    $gw = & $GatewayProbe (Remaining)
    if ($script:GatewayStates -notcontains $gw) { $gw = 'Unknown' }
    Note "gateway state=$gw"

    switch ($gw) {
        'Healthy' {
            if ($dbaHealthy) { return Done 0 'Gateway already healthy, DBA healthy; nothing started' }
            return Done 3 "Gateway already healthy but DBA is $dbaState (not confirmed healthy): DEGRADED; nothing started"
        }
        'Foreign'         { return Done 5 'a process that is not our gateway.run holds the port; not killed, no second start' }
        'Unknown'         { return Done 6 'the port state could not be established; no start decided on an unknown' }
        'OwnUnresponsive' { return Done 7 'our own Gateway holds the port and does not answer; no second process started' }
    }

    # Absent: the one state that permits a start.
    if ((Remaining) -le 0) { return Done 8 'budget exhausted before the start; nothing started' }
    $degraded = -not $dbaHealthy
    Note ("starting Gateway{0}" -f $(if ($degraded) { ' DEGRADED (DBA not confirmed healthy)' } else { '' }))
    $proc = & $StartGateway $Python $Root $degraded
    if ($null -eq $proc) { return Done 2 'the Gateway start produced no process' }
    Note "Gateway started pid=$($proc.Id)"
    if ($degraded) { return Done 3 "Gateway started DEGRADED; DBA is $dbaState" }
    return Done 0 'Gateway started; DBA healthy'
}

# ------------------------------------------------------------------------------
# Real adapters. One function per effect, no decisions: the decisions above are
# the part that is tested.
# ------------------------------------------------------------------------------

function Get-RealDbaGate([string]$Root) {
    # The ONE entry point this script expects from Deploy's gate:
    #     Invoke-DbaGateForBoot -Root <repo> -RemainingMs <int>  ->  {State; Healthy}
    # It wires his real probe/port-owner/starter itself, so their shapes stay his.
    # PROPOSED, not yet agreed: until the gate file exists AND exports it, the DBA
    # is reported NOT MEASURED ($null) - never absent, never guessed.
    $gate = Join-Path $Root 'scripts\dba-gate.ps1'
    if (-not (Test-Path -LiteralPath $gate)) {
        return { param($RemainingMs) [pscustomobject]@{ State = 'GateMissing'; Healthy = $null } }
    }
    return {
        param($RemainingMs)
        . $gate
        if (-not (Get-Command Invoke-DbaGateForBoot -ErrorAction SilentlyContinue)) {
            return [pscustomobject]@{ State = 'GateIntegrationPending'; Healthy = $null }
        }
        Invoke-DbaGateForBoot -Root $Root -RemainingMs $RemainingMs
    }.GetNewClosure()
}

function Get-RealGatewayProbe([int]$Port = 8100) {
    return {
        param($RemainingMs)
        $ms = [math]::Min(3000, [math]::Max(0, $RemainingMs))
        if ($ms -le 0) { return 'Unknown' }
        $client = New-Object Net.Sockets.TcpClient
        try {
            $task = $client.ConnectAsync('127.0.0.1', $Port)
            if (-not $task.Wait($ms)) { return 'Unknown' }
        } catch {
            $inner = $_.Exception.GetBaseException()
            if ($inner -is [Net.Sockets.SocketException] -and $inner.SocketErrorCode -eq 'ConnectionRefused') { return 'Absent' }
            return 'Unknown'
        } finally { $client.Dispose() }
        $owner = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        $cmd = if ($owner) { (Get-CimInstance Win32_Process -Filter "ProcessId=$($owner.OwningProcess)").CommandLine } else { '' }
        if ($cmd -notmatch 'gateway\.run') { return 'Foreign' }
        try {
            $sec = [math]::Max(1, [int]([math]::Min(3000, $RemainingMs) / 1000))
            $code = (Invoke-WebRequest "http://127.0.0.1:$Port/health" -TimeoutSec $sec -UseBasicParsing).StatusCode
            if ($code -eq 200) { 'Healthy' } else { 'OwnUnresponsive' }
        } catch { 'OwnUnresponsive' }
    }.GetNewClosure()
}

function Get-RealGatewayStarter {
    return {
        param($Python, $Root, [bool]$Degraded)
        try {
            Start-Process -FilePath $Python -ArgumentList @('-m', 'gateway.run') -WorkingDirectory $Root `
                -WindowStyle Hidden -PassThru
        } catch { $null }
    }
}

# Run only when executed, not when dot-sourced by the tests.
if ($MyInvocation.InvocationName -ne '.') {
    if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path }
    if (-not $Python) { $Python = Join-Path $Root '.venv\Scripts\python.exe' }
    if (-not $LogDir) { $LogDir = Join-Path $Root 'logs\boot' }
    $r = Invoke-JarvisBoot -Root $Root -Python $Python -LogDir $LogDir -BudgetSeconds $BudgetSeconds `
        -DbaGate (Get-RealDbaGate $Root) -GatewayProbe (Get-RealGatewayProbe) -StartGateway (Get-RealGatewayStarter)
    exit $r.ExitCode
}
