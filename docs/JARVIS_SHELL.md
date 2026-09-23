# Jarvis as the shell — design plan

**Owner directive, 2026-09-23:** *"I want Jarvis to be a self evolving OS... a full fledged shell
that on startup covers the whole of windows screen and not just a window... search for all installed
programs on my PC and bring them up on the screen and work on them right before me under my
supervision while clearing any doubts he may have while doing the assigned task interactively like a
student doing a task for the teacher."*

**And the constraint that shapes all of it:** *"please design it such a way that the escape key should
give user the option to exit the shell."*

Queue entries: TQ-116, TQ-119, TQ-120, TQ-121, TQ-122.

---

## 0. The constraint that decides the architecture

**Nothing here can be verified from the machine it is being written on.** No Windows, no screen, no
microphone, no Store, no Excel. CI has a Windows runner, which proves logic and cannot prove "it
covered the screen" or "the mic heard me".

So every piece is split in two, and the split is not cosmetic:

| Half | Where | Tested how |
|---|---|---|
| **The decision** — what Escape offers, which of four sources an app came from, whether a step may run unsupervised, what a narration says | pure Python, no OS calls | fully, here, with probes |
| **The effect** — open a window, list the registry, launch a process, click a control | a thin adapter, one function per effect | a fake in CI; the real one by Krish at the keyboard |

The rule: **if it can be decided, it is decided in tested code.** The adapter is allowed to be
untestable only because it contains no decisions. Anything that reads like a judgement inside the
adapter is a bug in the split.

---

## 1. The escape hatch, first, because it is what makes trying this safe

> *"the escape key should give user the option to exit the shell"*

Note the wording: **the option to exit**, not an immediate exit. Escape opens a menu. That is better
than an instant quit for a reason worth stating — an instant quit means a stray keypress during a
long task kills the shell mid-work, and a menu costs one extra keystroke and removes that entirely.

### What Escape offers

```
  ESC  ┌─────────────────────────────────────────────┐
       │  Jarvis                                     │
       │                                             │
       │  1  Keep working            (dismiss)       │
       │  2  Minimise Jarvis         (stays running) │
       │  3  Exit to the desktop     (Jarvis sleeps) │
       │  4  Restart Jarvis                          │
       │  5  Diagnostics             (logs, health)  │
       └─────────────────────────────────────────────┘
```

**Design rules, each with its reason:**

- **Default is "keep working".** Escape again, or Enter, dismisses. The dangerous option is never the
  default and never reachable by repeating the same key.
- **Exit is never silent.** Exiting writes a ledger event and takes the §9 before-shutdown checkpoint,
  so "Jarvis forgot what he was doing because I pressed Escape" cannot happen.
- **The menu works when the page is broken.** It is rendered by the shell host, not by the web app.
  If the page has failed to load, hung, or thrown, Escape must still work — an escape hatch that
  needs the thing it is escaping from is not one.
- **It also works when Jarvis is mid-task.** Exiting during a supervised task leaves that task
  `paused` with its next action recorded, never half-applied.
- **No password.** Windows already authenticated him at logon; adding a second credential to get out
  of a shell only means being locked in when he most wants out.

### The failsafe below it

Escape is the *supervised* exit. Two more exist for when the shell itself is the problem:

1. **The supervisor restores the desktop.** `keep-jarvis-up.ps1` counts consecutive failures to come
   up. Past a threshold it stops relaunching and starts Explorer instead — so a crash loop ends at a
   usable desktop, not at a black screen. This is the mechanism that makes shell *replacement*
   (TQ-116b) survivable, and it is built now even though replacement is not.
2. **Ctrl+Alt+Del always works.** It is reserved by Windows and no application can intercept it, so
   Task Manager is always reachable. Documented rather than implemented — the point is that it exists
   and the owner should know it.

---

## 2. What the shell actually is

`desktop/shell.py` already opens a pywebview window at 1440×900 pointed at the Gateway over
loopback, with a documented reason for `url=` over `html=` (an HTML string has no origin, so no
secure context, so no microphone).

**pywebview is not installed and not in `requirements.txt`.** It has therefore never run here or in
CI, and `shell.py` currently degrades to printing a URL. Two candidate hosts:

| Host | Fullscreen | Deterministic exit | New dependency |
|---|---|---|---|
| **pywebview** | `fullscreen=True` | Yes — Python owns the window and can destroy it | pywebview + WebView2 runtime (present on Windows 11) |
| **Edge `--app=` `--start-fullscreen`** | Yes | **No** — `window.close()` only works on script-opened windows | none |

**Chosen: pywebview**, because the escape hatch is a hard requirement and it needs a window Python
can actually close. Edge remains the documented fallback for a machine where pywebview will not
install, with the honest note that exit there is Alt+F4 rather than a menu.

### Kiosk, not shell replacement — yet

Fullscreen over a running Explorer. Alt-Tab still works, the taskbar is still underneath, and
nothing has been written to the registry. TQ-116b (replacing `explorer.exe`) stays frozen until the
owner says so, and the supervisor failsafe above is the precondition being built now so that the
answer can be yes later without it being a leap.

---

## 3. Finding and opening what is installed

> *"search for all installed programs on my PC and bring them up on the screen"*

**No single source lists what is installed.** Four, and the union is the answer:

| Source | Covers | Misses |
|---|---|---|
| Registry `Uninstall` keys (HKLM + HKCU, 32- and 64-bit views) | most desktop software | Store apps, portable apps |
| Start Menu `.lnk` files | what the owner actually launches | anything unpinned |
| `winget list` | what winget knows | much pre-installed software |
| `Get-AppxPackage` | Store and UWP apps | everything Win32 |

Anything that claims completeness from one source will be **wrong and confident**, which is the
failure this table exists to prevent.

**Reconciliation is the tested part.** Deduplicate across sources, prefer the entry with a launch
path, keep every source that mentioned an app so a diagnosis can say where it was found, and rank a
search by how the owner actually refers to things — "the spreadsheet" has to find Excel. The
adapter's only job is to return raw rows per source.

**Launching, and the part that is not obvious:** the process you start is often not the process that
owns the window. A launcher that exits and hands off is the common case, and waiting on the wrong pid
looks exactly like a program that did not start. So: launch, then wait for a *window* matching the
app, with a timeout and an honest "it started but I could not find its window" rather than a hang.

---

## 4. Working on it in front of him

> *"work on them right before me under my supervision ... like a student doing a task for the
> teacher"*

This is a different **execution model**, not a feature. Four properties, and each becomes a
mechanism rather than an intention:

**Visible.** The app is on screen and actions happen where he can see them. No invisible driving —
an agent whose mistakes are only discoverable in the result is not being supervised.

**Narrated.** Jarvis says what he is about to do *before* doing it. A correct action nobody could
follow is indistinguishable from a lucky one.

**Interruptible.** Stoppable mid-task, and stopping leaves a state he can take over from — never
half a transaction. Implemented as a step queue where each step is individually atomic and
individually recorded.

**Doubt-first.** *"clearing any doubts he may have"* — the question arrives **before** the action it
blocks, never in a summary afterwards. A question in a summary is a confession.

**The speed limit is the feature.** An agent driving a GUI as fast as it can is one nobody can
supervise. Deliberate pacing, one visible step at a time, is what makes "supervision" mean anything.

### The step

```
Step:  intent        what this step is for, in his words
       narration     what Jarvis is about to do, said before it happens
       action        the adapter call
       reversible    whether it can be undone, and how
       question      what must be answered first, if anything
       evidence      what was observed after
```

A step with an unanswered question does not run. A step that is not reversible and not confirmed
does not run. Both are enforced, not documented.

---

## 5. The interactive task (TQ-119)

> *"Jarvis prepare my expense statements by looking into my business account — ask me questions while
> you are working ... use last year's statement as a model and ask me questions when you can't find
> the data that you seek."*

Four requirements, none needing a Windows API:

1. **A long-running task that survives interruption.** `persistence.TASK` and `record_task_state`
   already persist progress; `rehydrate` already restores it. A task resumed after a restart knows its
   next action.
2. **A question queue**, asked while working. The DBA's §45 ask-back is the pattern and
   `dba/askback.py` the vocabulary: a clarification is not a failure, and nothing is committed on
   that path.
3. **A prior artefact as the template.** Last year's statement *is* the specification for this
   year's: read its structure, map this year's data onto it, and report the fields that did not map.
4. **Stopping rather than guessing.** The one that decides whether this is usable at all. A statement
   with a plausible invented figure is worse than no statement; the honest output is the statement
   plus what is missing and why.

**Read-only against his money** until there is a specific reason otherwise, and the write path is
its own entry with its own approval — never an implied consequence of the read path.

---

## 6. Order of work, and why this order

1. **The escape hatch and the fullscreen host.** First because it is what makes tomorrow's test safe,
   and because a shell you cannot leave is not testable at all.
2. **The supervisor failsafe.** Second because it is the other half of the same safety property, and
   it is small.
3. **The support bundle (TQ-122).** Third because tomorrow's failures need to be diagnosable, and a
   failure on his machine that produces no bundle costs a day.
4. **The program inventory and launch.** The first thing that does something he asked for.
5. **The supervised step runner.** The execution model above.
6. **The interactive task.** The example he described in the most detail.

Items 1, 2, 3, 5 and 6 are largely testable from here. Item 4 is mostly adapter and will be
faked in CI and verified by him.

---

## 7. What will not be built, and is not pretended

- **Shell replacement** (TQ-116b). Frozen pending his decision; the failsafe it needs is built.
- **On-device speech** (TQ-117). Voice keeps working as it does, and **voice does not become the
  approval channel** until STT is local — `webkitSpeechRecognition` sends audio off the machine.
- **UI Automation** (TQ-120 layer 4). The inventory and launch come first; driving arbitrary
  applications is a larger increment and the place where a guess does the most damage.
- **Write access to his business account.** Read-only, deliberately.
