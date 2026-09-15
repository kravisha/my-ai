# Jarvis greets Krish at logon, then opens Claude Code for him.
#
# His instruction, 2026-09-14: "Can you make Jarvis say hello, I'm Jarvis, good
# morning or good afternoon or good evening, whatever the appropriate time is,
# and then go on to open Claude Code."
#
# Two audiences, and they need different things:
#
#   THE PHONE gets the greeting appended to CLAUDE-TO-KRISH.md, which box 3
#   polls and reads aloud. This matters more than the pleasantry: if the machine
#   reboots at 3am while he is on another continent, that line is how he learns
#   it happened. A greeting with a timestamp is a heartbeat.
#
#   THE PC gets an INTERACTIVE Claude Code window. Interactive, specifically -
#   `claude -p` cannot authenticate here ("OAuth session expired and could not
#   be refreshed", and it exits 0 while failing). An interactive session signs
#   in normally. So the automatic path deliberately opens a window a human can
#   type into rather than pretending to be headless.
#
# It does NOT type "Providence" for him. A session that wakes itself and starts
# acting on a week-old channel with nobody watching is exactly the unattended
# behaviour we spent the evening building guards against. It opens, it waits.

$ErrorActionPreference = 'Continue'
$workdir = 'C:\Users\Krish\ClaudeStuff'
$inbox   = 'C:\Users\Krish\Documents\Aria-Claude-Communications\CLAUDE-TO-KRISH.md'
$claude  = "$env:USERPROFILE\.local\bin\claude.exe"
$log     = Join-Path $env:TEMP 'jarvis-good-morning.log'

function Say($m) {
  Add-Content -LiteralPath $log -Encoding utf8 `
    -Value ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
}

$hour = (Get-Date).Hour
$partOfDay =
  if     ($hour -lt 12) { 'Good morning'   }
  elseif ($hour -lt 17) { 'Good afternoon' }
  elseif ($hour -lt 22) { 'Good evening'   }
  else                  { 'Good evening'   }

$stamp = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
$when  = (Get-Date).ToString('dddd d MMMM, h:mm tt')

# Was this a reboot, or just a fresh logon? He should be told which.
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$sinceBoot = [int]((Get-Date) - $boot).TotalMinutes
$bootNote = if ($sinceBoot -le 10) {
  "This machine restarted $sinceBoot minute(s) ago, so something rebooted it."
} else {
  "The machine has been up for $([int]($sinceBoot/60)) hour(s) - this is a logon, not a restart."
}

$greeting = @"

## $stamp | CLAUDE-TO-KRISH

Hello, I'm Jarvis. $partOfDay. It is $when.

$bootNote

I am back up and answering. Claude Code has been opened on the PC but nobody has
typed anything into it - say Providence there when you want him to load the full
state. Until someone does, messages you send here are stored safely and read on
his next poll rather than immediately.
"@

try {
  Add-Content -LiteralPath $inbox -Value $greeting -Encoding utf8
  Say "greeted Krish on the phone: $partOfDay, $bootNote"
} catch {
  Say "COULD NOT WRITE THE GREETING: $_"
}

# Speak it on the PC too, for when he is actually sitting here. Wrapped because
# a machine with no audio device must not stop the rest of this script.
try {
  Add-Type -AssemblyName System.Speech
  $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $voice.Speak("Hello, I'm Jarvis. $partOfDay. Opening Claude Code for you now.")
} catch { Say "no speech available: $_" }

if (-not (Test-Path $claude)) { Say "MISSING: $claude"; exit 1 }

# A visible window. He has to be able to see it and type into it - that is the
# whole point, and a hidden one would be indistinguishable from not running.
Say 'opening an interactive Claude Code window'
Start-Process -FilePath 'cmd.exe' `
  -ArgumentList '/k', "cd /d $workdir && `"$claude`"" `
  -WorkingDirectory $workdir
Say 'done'
