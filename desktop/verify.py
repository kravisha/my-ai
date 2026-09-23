"""The checks that need eyes, asked one at a time.

    python -m desktop.verify

`tests/test_real_machine.py` covers everything a machine can decide by itself.
This covers what it cannot: whether the window actually covered the screen,
whether the escape menu appeared, whether Jarvis was audible. A test asserting
any of those would be asserting something it did not observe, and the honest
form of an unobservable claim is a question put to somebody who can see.

## Human-attested, and the report says so

Every answer here is Krish's word, not a measurement. The report records it that
way - `attested` rather than `passed` - because six months from now the
difference between "the machine verified this" and "somebody said yes" is the
difference between evidence and a memory.

## It opens the shell first, and the first question is the way out

The very first check is that Escape works. If it does not, he is looking at a
fullscreen window he was told he could leave, and the next thing he needs is
Alt+F4 and to know that the answer is no. Asking anything else first would be
asking him to evaluate a screen he cannot get off.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_NAME = "verify-report.txt"


@dataclass(frozen=True)
class Check:
    """One thing only a person can confirm."""

    key: str
    what: str
    do: str
    ask: str
    # What it means if the answer is no. Written here rather than worked out in
    # the moment, because the moment is when somebody is tired and wants to
    # move on.
    if_no: str


CHECKS: tuple[Check, ...] = (
    Check(
        "escape",
        "the way out works",
        "Press Escape.",
        "Did a small Jarvis window appear listing 'Keep working', 'Minimise', "
        "'Exit to the desktop', 'Restart' and 'Diagnostics'?",
        "The shell cannot be left by design's intended route. Close it with "
        "Alt+F4 and stop here - nothing else on this list matters until the "
        "way out works.",
    ),
    Check(
        "escape_default",
        "Escape twice is harmless",
        "With the menu open, press Escape again.",
        "Did the menu close and leave Jarvis running, WITHOUT exiting?",
        "The dangerous option is reachable by repeating the key that opened the "
        "menu - a stray double-press would kill the shell mid-task.",
    ),
    Check(
        "fullscreen",
        "it covers the whole screen",
        "Look at the screen.",
        "Does Jarvis cover the entire screen, with no title bar and no taskbar "
        "visible over it?",
        "It opened as a window rather than a shell. Check that "
        "JARVIS_SHELL_FULLSCREEN=1 is set for the process that started it.",
    ),
    Check(
        "readable",
        "it is legible at arm's length",
        "Sit at your normal distance.",
        "Can you read Jarvis's text comfortably without leaning in?",
        "A shell that has to be squinted at will not be used as a shell.",
    ),
    Check(
        "minimise",
        "minimising leaves Jarvis running",
        "Press Escape, then 2.",
        "Did the window disappear and leave your desktop, with Jarvis still "
        "running (check the taskbar or that his voice still answers)?",
        "Minimise is closing rather than hiding, so there is no way to step "
        "away without stopping work.",
    ),
    Check(
        "diagnostics",
        "diagnostics say where the logs are",
        "Bring Jarvis back, press Escape, then 5.",
        "Did a window appear listing the Gateway URL and the paths to logs, "
        "crashes and startups?",
        "The screen somebody reaches when things are going wrong does not tell "
        "them where to look.",
    ),
    Check(
        "exit_saves",
        "exiting saves the work",
        "Press Escape, then 3.",
        "Did Jarvis say he saved where he was - rather than warning that the "
        "last few minutes may not be remembered?",
        "JARVIS_SHELL_TOKEN is probably not set, so the shell could not ask the "
        "Gateway to checkpoint. Exiting still works; it just forgets.",
    ),
    Check(
        "exit_leaves_desktop",
        "exiting leaves a usable desktop",
        "Look at the screen after exiting.",
        "Are you looking at your normal Windows desktop, with the taskbar and "
        "your icons?",
        "Exiting led somewhere unusable. This is the failure the escape hatch "
        "exists to prevent and it must be fixed before anything else.",
    ),
)


@dataclass
class Answer:
    check: Check
    attested: bool | None   # None = not asked, or skipped
    note: str = ""


def ask(check: Check, prompt=input, say=print) -> Answer:
    """Put one question. `y`, `n`, or `s` to skip.

    Anything else is asked again rather than guessed at - a verification that
    interprets an ambiguous answer is worth less than one that stops."""
    say("")
    say(f"--- {check.what} ---")
    say(f"    {check.do}")
    say(f"    {check.ask}")
    while True:
        answer = (prompt("    [y] yes  [n] no  [s] skip > ") or "").strip().lower()
        if answer in ("y", "yes"):
            return Answer(check, True)
        if answer in ("n", "no"):
            say(f"    -> {check.if_no}")
            note = (prompt("    anything to add? (enter to skip) > ") or "").strip()
            return Answer(check, False, note)
        if answer in ("s", "skip", ""):
            return Answer(check, None, "skipped")
        say("    please answer y, n or s.")


def run_checks(checks=CHECKS, prompt=input, say=print) -> list[Answer]:
    """Walk the list, stopping if the way out does not work.

    Stopping is deliberate. If Escape does not open the menu he is looking at a
    fullscreen window he was told he could leave, and asking him to evaluate
    legibility next would be asking him to review a screen he cannot get off."""
    answers = []
    for check in checks:
        answer = ask(check, prompt=prompt, say=say)
        answers.append(answer)
        if check.key == "escape" and answer.attested is False:
            say("")
            say("    Stopping here. Close Jarvis with Alt+F4.")
            break
    return answers


def report(answers: list[Answer], *, when: str | None = None) -> str:
    """The text he sends back. Attested, never 'passed'."""
    stamp = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "Jarvis shell verification - human attested",
        f"at: {stamp}",
        f"on: {sys.platform}",
        "",
        "Every line below is somebody's word, not a measurement. "
        "tests/test_real_machine.py holds what the machine can decide alone.",
        "",
    ]
    for answer in answers:
        mark = {True: "ATTESTED", False: "FAILED  ", None: "skipped "}[answer.attested]
        lines.append(f"{mark}  {answer.check.key:<22} {answer.check.what}")
        if answer.attested is False:
            lines.append(f"          -> {answer.check.if_no}")
        if answer.note and answer.note != "skipped":
            lines.append(f"          note: {answer.note}")

    failed = [a for a in answers if a.attested is False]
    skipped = [a for a in answers if a.attested is None]
    lines += ["",
              f"{len(answers) - len(failed) - len(skipped)} attested, "
              f"{len(failed)} failed, {len(skipped)} skipped, "
              f"{len(CHECKS) - len(answers)} not reached"]
    return "\n".join(lines)


def write_report(text: str, directory: Path | None = None) -> Path:
    target = (directory or PROJECT_ROOT / "logs")
    target.mkdir(parents=True, exist_ok=True)
    path = target / REPORT_NAME
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - interactive
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m desktop.verify",
        description="Ask the questions a test cannot answer about the shell.")
    parser.add_argument("--no-shell", action="store_true",
                        help="do not open the window; just ask the questions")
    parser.add_argument("--url", default=None,
                        help="the Gateway URL to open (default: the configured one)")
    args = parser.parse_args(argv)

    from desktop import bootstrap, shell

    url = args.url or bootstrap.console_url()

    def walk():
        answers = run_checks()
        text = report(answers)
        print("")
        print(text)
        print("")
        print(f"written to {write_report(text)}")
        print("Send that file back; it is the other half of "
              "`pytest -m real_machine`.")

    if args.no_shell or not shell.available():
        if not args.no_shell:
            print("[verify] pywebview is not installed, so the window cannot be "
                  "opened. Answering the questions anyway will produce a report "
                  "that says so.\n"
                  "         pip install -r requirements-desktop.txt")
        walk()
        return 0

    # The questions run on a worker while pywebview owns the main thread, which
    # is what it requires on macOS and prefers everywhere.
    import webview

    shell.run(url, fullscreen=True)
    del webview
    walk()
    return 0


if __name__ == "__main__":  # pragma: no cover - a script
    raise SystemExit(main())
