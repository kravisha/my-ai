# Wakes Claude Dev to read Krish's phone messages and answer them.
#
# Krish's design, 2026-09-14: "Jarvis will survive a reboot. Then he will read
# the reboot directive at startup and do the needful, which is starting you up
# and then jogging your memory."
#
# This is the gap that nothing else closed. The Gateway self-heals, Tailscale
# survives a reboot, and his messages queue safely in the channel - but nothing
# RESTARTS CLAUDE DEV, so after one Windows update his messages would sit unread
# for a week while everything else reported healthy. Exactly the failure shape
# that bit us six times that day: every component green, the system silent.
#
# One-shot, not a daemon. `claude -p` reads, acts, replies, exits. The scheduled
# task's repetition is what makes it a poller. A one-shot that dies is retried in
# fifteen minutes; a daemon that wedges is dead until someone notices, and we had
# four wedged processes that day.
#
# SCOPED PERMISSIONS, NOT --dangerously-skip-permissions. An agent running
# unattended for a week with all checks bypassed is not a risk worth taking to
# save typing a tool list. Read and search are unrestricted; writes are not.

$ErrorActionPreference = 'Continue'
$claude    = "$env:USERPROFILE\.local\bin\claude.exe"
$workdir   = 'C:\Users\Krish\ClaudeStuff'
$directive = Join-Path $workdir 'REBOOT-DIRECTIVE.md'
$log       = Join-Path $env:TEMP 'claude-dev-wake.log'

function Say($m) {
  Add-Content -LiteralPath $log -Encoding utf8 `
    -Value ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
}

if (-not (Test-Path $claude))    { Say "MISSING: $claude";    exit 1 }
if (-not (Test-Path $directive)) { Say "MISSING: $directive"; exit 1 }

# Cheap pre-check: has Krish actually said anything since we last answered?
# Waking a full session every 15 minutes to discover nothing happened burns his
# budget for no benefit. The channel only grows, so its size is a sufficient
# "has anything arrived" test and costs one stat call.
$channel = 'C:\Users\Krish\Documents\Aria-Claude-Communications\Arya-Claude - Ongoing Conversation.md'
$marker  = Join-Path $workdir '.last-channel-size'
$size    = (Get-Item -LiteralPath $channel -ErrorAction SilentlyContinue).Length
$last    = if (Test-Path $marker) { [int64](Get-Content $marker -Raw).Trim() } else { 0 }

if ($size -eq $last) { Say "no change ($size bytes) - not waking"; exit 0 }
Say "channel grew $last -> $size, waking Claude Dev"

$prompt = @"
Read $directive and follow it exactly. You were started automatically; there is
no human here to answer questions. Krish is abroad and reachable ONLY by
appending to CLAUDE-TO-KRISH.md.
"@

& $claude -p $prompt `
  --add-dir $workdir `
  --allowedTools 'Read' 'Grep' 'Glob' 'Edit' 'Write' 'Bash(git status:*)' 'Bash(git log:*)' `
  2>&1 | ForEach-Object { Say "  $_" }

Set-Content -LiteralPath $marker -Value $size -Encoding utf8
Say 'done'
