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
#   0  Gateway health-CONFIRMED, DBA healthy
#   2  a Gateway start was attempted and did not produce a process
#   3  DEGRADED: Gateway running or started, but the DBA is not confirmed healthy
#   4  the venv python is missing - no guess from PATH
#   5  something FOREIGN holds the Gateway port - not ours, not killed
#   6  the Gateway port's state is UNKNOWN - no start decided on an unknown
#   7  our own Gateway holds the port and does not answer - no second process
#   8  the whole-boot budget ran out (or a stage overran it); nothing decided on the overrun
#   9  a Gateway was LAUNCHED but its health was NOT confirmed (launched is not healthy)
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
        [Parameter(Mandatory)] [scriptblock]$StartGateway,   # param($Python, $Root, [bool]$Degraded, [int]$RemainingMs) -> process or $null
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
    # A stage that RETURNS after the budget is gone has overrun it, whatever it
    # saw. The whole-boot bound is the contract, so the run ends here (Arya
    # 5819049570: no post-probe elapsed check existed).
    if ((Remaining) -le 0) { return Done 8 "the Gateway probe overran the budget (it saw '$gw'); no decision taken on it" }

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
    # DEGRADED is a LAUNCHER-SIDE record only: nothing tells the Gateway process
    # that the DBA was not confirmed healthy. Whatever it reports about the DBA is
    # its own observation, not this flag.
    Note ("starting Gateway{0}" -f $(if ($degraded) { ' DEGRADED (DBA not confirmed healthy; launcher-side record only, the Gateway is not told)' } else { '' }))
    $proc = & $StartGateway $Python $Root $degraded (Remaining)
    if ($null -eq $proc) { return Done 2 'the Gateway start produced no process' }
    Note "Gateway launched pid=$($proc.Id)"
    if ((Remaining) -le 0) { return Done 8 'the start overran the budget; health not confirmed' }

    # LAUNCHED IS NOT HEALTHY. One re-probe within what is left; no waiting loop -
    # the next scheduler tick re-checks a Gateway still coming up.
    $after = & $GatewayProbe (Remaining)
    if ($script:GatewayStates -notcontains $after) { $after = 'Unknown' }
    Note "gateway after start=$after"
    if ((Remaining) -le 0) { return Done 8 "the confirming probe overran the budget (it saw '$after')" }
    if ($after -ne 'Healthy') { return Done 9 "Gateway launched (pid $($proc.Id)) but health NOT confirmed: $after" }
    if ($degraded) { return Done 3 "Gateway started and healthy but DEGRADED; DBA is $dbaState" }
    return Done 0 'Gateway started and health-confirmed; DBA healthy'
}

function Get-GatewayPortState {
    <#
      The real probe's DECISIONS, over injected stages, so the budget arithmetic
      is tested without a socket. One deadline for the whole probe: each stage
      gets only what the stages before it left (Arya 5819049570).

        Connect { param($ms) } -> 'refused' | 'connected' | 'timeout' | 'error'
        Owner   { param($ms) } -> the listening process's command line, or $null.
                                  The real adapter bounds BOTH its CIM queries with
                                  -OperationTimeoutSec (whole seconds, so up to one
                                  extra second per query is possible). That is an
                                  enforced client-side timeout, but its behaviour
                                  against a hung local WMI provider is UNMEASURED; an
                                  overrun still turns the answer into Unknown.
        Health  { param($ms) } -> $true | $false
    #>
    param([int]$RemainingMs, [scriptblock]$Connect, [scriptblock]$Owner,
          [scriptblock]$Health, [scriptblock]$ElapsedMs, [int]$StageCapMs = 3000)
    $start = & $ElapsedMs
    function Left { [int]($RemainingMs - ((& $ElapsedMs) - $start)) }
    if ((Left) -le 0) { return 'Unknown' }
    $tcp = & $Connect ([math]::Min($StageCapMs, (Left)))
    if ($tcp -eq 'refused') { return 'Absent' }
    if ($tcp -ne 'connected') { return 'Unknown' }
    if ((Left) -le 0) { return 'Unknown' }
    $cmd = & $Owner ([math]::Min($StageCapMs, (Left)))
    if ((Left) -le 0) { return 'Unknown' }                 # the owner stage overran
    if (-not $cmd) { return 'Unknown' }                    # someone listens; owner unreadable
    if ($cmd -notmatch 'gateway\.run') { return 'Foreign' }
    $ok = & $Health ([math]::Min($StageCapMs, (Left)))
    if ((Left) -lt 0) { return 'Unknown' }
    if ($ok -eq $true) { return 'Healthy' }
    return 'OwnUnresponsive'
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
    # Thin adapters only; every decision is in Get-GatewayPortState.
    $connect = {
        param($ms)
        $client = New-Object Net.Sockets.TcpClient
        try {
            $task = $client.ConnectAsync('127.0.0.1', $Port)
            if (-not $task.Wait([math]::Max(1, $ms))) { return 'timeout' }
            'connected'
        } catch {
            $inner = $_.Exception.GetBaseException()
            if ($inner -is [Net.Sockets.SocketException] -and $inner.SocketErrorCode -eq 'ConnectionRefused') { 'refused' } else { 'error' }
        } finally { $client.Dispose() }
    }.GetNewClosure()
    $owner = {
        param($ms)
        # Both queries through CIM so both take -OperationTimeoutSec (the
        # Get-NetTCPConnection cmdlet exposes no timeout; its class does). Split
        # the stage's time between them; whole seconds, minimum 1.
        $sec = [math]::Max(1, [int][math]::Floor($ms / 2000))
        $l = Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection `
                 -Filter "LocalPort=$Port AND State=2" -OperationTimeoutSec $sec -ErrorAction SilentlyContinue |
             Select-Object -First 1
        if ($l) {
            (Get-CimInstance Win32_Process -Filter "ProcessId=$($l.OwningProcess)" `
                 -OperationTimeoutSec $sec -ErrorAction SilentlyContinue).CommandLine
        }
    }.GetNewClosure()
    $health = {
        param($ms)
        # Invoke-WebRequest takes whole seconds: round UP only within the cap, never past it.
        $sec = [math]::Max(1, [int][math]::Floor($ms / 1000))
        try { (Invoke-WebRequest "http://127.0.0.1:$Port/health" -TimeoutSec $sec -UseBasicParsing).StatusCode -eq 200 }
        catch { $false }
    }.GetNewClosure()
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $elapsed = { $clock.ElapsedMilliseconds }.GetNewClosure()
    return {
        param($RemainingMs)
        Get-GatewayPortState -RemainingMs $RemainingMs -Connect $connect -Owner $owner -Health $health -ElapsedMs $elapsed
    }.GetNewClosure()
}

function Get-RealGatewayStarter {
    return {
        # $RemainingMs is received so the contract is uniform; Start-Process
        # -PassThru does not wait for the child, so it has nothing to bound.
        param($Python, $Root, [bool]$Degraded, [int]$RemainingMs)
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
