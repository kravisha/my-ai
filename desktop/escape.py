"""The way out of the shell. Escape opens this; nothing else does.

Owner directive, 2026-09-23: *"please design it such a way that the escape key
should give user the option to exit the shell."*

Read the wording: **the option to exit**, not an exit. Escape opens a menu, and
that is better than an instant quit for a concrete reason - a stray keypress
during a long task would otherwise kill the shell mid-work. A menu costs one
extra keystroke and removes that entirely.

## Five rules, each of which is a mechanism here rather than an intention

1. **The dangerous option is never the default**, and never reachable by
   repeating the key that opened the menu. Escape twice dismisses; it does not
   exit. `DEFAULT` is `keep_working` and a test asserts it.

2. **Exiting is never silent.** Every exit path returns the work that must
   happen first - the before-shutdown checkpoint and a ledger event - so
   "pressing Escape made Jarvis forget what he was doing" is not a thing that
   can happen. The caller performs them; this module decides that they are owed
   and refuses to report a clean exit without them.

3. **The menu is decided here and rendered by the host**, not by the web page.
   An escape hatch that needs the thing it is escaping from is not an escape
   hatch: if the page has hung, failed to load or thrown, Escape must still
   work.

4. **Exiting leaves a desktop behind.** Under a kiosk that is free - Explorer is
   already running. Under shell replacement (TQ-116b) it is not, and exiting to
   a black screen would be the worst possible outcome of the feature designed to
   prevent exactly that. So `EXIT` carries `restore_desktop`, which the adapter
   makes a no-op or a real action depending on which the shell is.

5. **No password.** Windows authenticated him at logon. A second credential to
   get *out* of a shell only means being locked in at the moment he most wants
   out.

## What is decided here and what is not

Everything in this module is a decision and is tested. The effects - hide a
window, destroy it, start Explorer, ask the supervisor to restart - are a
`Host`, one method per effect, with no branching inside. A judgement that
appeared in a `Host` implementation would be a bug in that split, because the
implementations are the part that cannot be tested from a machine without
Windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

# --- the actions ---------------------------------------------------------------

KEEP_WORKING = "keep_working"
MINIMISE = "minimise"
EXIT = "exit"
RESTART = "restart"
DIAGNOSTICS = "diagnostics"

ACTIONS = (KEEP_WORKING, MINIMISE, EXIT, RESTART, DIAGNOSTICS)

# The one Escape-Escape and Enter both land on. Named rather than implied,
# because "which option is safe by accident" is exactly the thing that rots.
DEFAULT = KEEP_WORKING


@dataclass(frozen=True)
class Option:
    """One line of the menu.

    `consequence` is shown to the owner, not logged - the menu has to be
    readable by somebody who pressed Escape because something was wrong and who
    is not in the mood to interpret."""

    action: str
    key: str
    label: str
    consequence: str
    reversible: bool
    # Whether choosing this ends the shell session. Used to decide what must be
    # persisted first, and asserted against `owed_before` so the two cannot
    # disagree.
    ends_session: bool = False


OPTIONS: tuple[Option, ...] = (
    Option(KEEP_WORKING, "1", "Keep working",
           "Closes this menu. Nothing changes.", reversible=True),
    Option(MINIMISE, "2", "Minimise Jarvis",
           "Hides the window. Jarvis keeps working and keeps listening.",
           reversible=True),
    Option(EXIT, "3", "Exit to the desktop",
           "Closes the Jarvis window. The services keep running, so Jarvis is "
           "still reachable from your phone.", reversible=True,
           ends_session=True),
    Option(RESTART, "4", "Restart Jarvis",
           "Closes the window and asks the supervisor to start everything "
           "again. Unfinished work is checkpointed first.", reversible=True,
           ends_session=True),
    Option(DIAGNOSTICS, "5", "Diagnostics",
           "Shows where the logs are, what is running, and the last failure. "
           "Changes nothing.", reversible=True),
)

BY_KEY = {option.key: option for option in OPTIONS}
BY_ACTION = {option.action: option for option in OPTIONS}

# What must be done before a session-ending action, in order. Returned rather
# than performed, so that this module stays decidable and the caller stays
# honest about whether it happened.
CHECKPOINT = "checkpoint_before_shutdown"
RECORD_EVENT = "record_ledger_event"
PAUSE_TASKS = "pause_running_tasks"
RESTORE_DESKTOP = "restore_desktop"

OWED_BEFORE: dict[str, tuple[str, ...]] = {
    KEEP_WORKING: (),
    MINIMISE: (),
    DIAGNOSTICS: (),
    # A task interrupted by an exit is paused with its next action recorded,
    # never left half-applied - and the checkpoint comes after the pause so the
    # checkpoint describes the paused state rather than the running one.
    EXIT: (PAUSE_TASKS, CHECKPOINT, RECORD_EVENT, RESTORE_DESKTOP),
    RESTART: (PAUSE_TASKS, CHECKPOINT, RECORD_EVENT),
}


class Host(Protocol):
    """The effects. One method per effect, no decisions inside any of them."""

    def hide(self) -> None: ...
    def close(self) -> None: ...
    def show_menu(self, lines: list[str]) -> None: ...
    def show_text(self, text: str) -> None: ...
    def restore_desktop(self) -> bool: ...
    def request_restart(self) -> bool: ...


@dataclass
class Outcome:
    """What the keypress meant, and what it obliges.

    `performed` and `failed` are filled in by `Hatch` as it carries out the
    owed work, so a caller can tell a clean exit from one that could not
    checkpoint - and say so, rather than reporting success either way."""

    action: str
    message: str
    owed: tuple[str, ...] = ()
    performed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    menu_open: bool = False

    @property
    def clean(self) -> bool:
        return not self.failed

    @property
    def ends_session(self) -> bool:
        option = BY_ACTION.get(self.action)
        return bool(option and option.ends_session)


class Hatch:
    """The escape hatch's state and the decisions it makes.

    Created once per shell session. Holds whether the menu is open and nothing
    else - there is no other state, deliberately, because an escape hatch with
    modes has modes in which it does not work."""

    def __init__(self, host: Host, *,
                 before_exit: dict[str, Callable[[], None]] | None = None,
                 diagnostics: Callable[[], str] | None = None) -> None:
        self.host = host
        self.open = False
        # Each owed step, by name, supplied by the caller. A step with no
        # callable is reported as failed rather than skipped: silently not
        # checkpointing is the failure this whole arrangement exists to prevent.
        self.before_exit = dict(before_exit or {})
        self.diagnostics = diagnostics

    # --- keys -----------------------------------------------------------------

    def key(self, name: str) -> Outcome:
        """One keypress. `name` is a key name, not a character.

        Escape opens the menu and, when it is already open, dismisses it. That
        asymmetry is rule 1: the key that opened the menu cannot also be the key
        that exits through it."""
        if name == "Escape":
            return self.dismiss() if self.open else self.present()
        if not self.open:
            # Keys mean nothing until the menu is open. Otherwise "3" typed into
            # a document would exit the shell.
            return Outcome(KEEP_WORKING, "", menu_open=False)
        if name in ("Enter", "Return"):
            return self.choose(BY_ACTION[DEFAULT].key)
        if name in BY_KEY:
            return self.choose(name)
        return Outcome(KEEP_WORKING,
                       f"{name} is not one of these. Press Escape to go back.",
                       menu_open=True)

    def present(self) -> Outcome:
        self.open = True
        self.host.show_menu(self.lines())
        return Outcome(KEEP_WORKING, "menu open", menu_open=True)

    def dismiss(self) -> Outcome:
        self.open = False
        return Outcome(KEEP_WORKING, "Back to work.", menu_open=False)

    def lines(self) -> list[str]:
        """The menu, in the words the owner reads."""
        return [f"{option.key}  {option.label}" + ("  (default)" if option.action == DEFAULT else "")
                for option in OPTIONS]

    def describe(self) -> list[dict]:
        """The menu as data, for the host that renders it and for a test."""
        return [{"key": option.key, "action": option.action,
                 "label": option.label, "consequence": option.consequence,
                 "default": option.action == DEFAULT,
                 "ends_session": option.ends_session,
                 "owed": list(OWED_BEFORE[option.action])}
                for option in OPTIONS]

    # --- choosing -------------------------------------------------------------

    def choose(self, key: str) -> Outcome:
        option = BY_KEY.get(key)
        if option is None:
            return Outcome(KEEP_WORKING, f"{key} is not one of these.",
                           menu_open=self.open)

        owed = OWED_BEFORE[option.action]
        outcome = Outcome(option.action, "", owed=owed)

        if option.action == KEEP_WORKING:
            self.open = False
            outcome.message = "Back to work."
            return outcome

        if option.action == DIAGNOSTICS:
            # Deliberately does not close the menu: he opened it because
            # something was wrong, and dropping him back into the shell after
            # showing him the diagnosis is the wrong direction.
            self.host.show_text(self._diagnostics_text())
            outcome.message = "Diagnostics shown."
            outcome.menu_open = True
            return outcome

        if option.action == MINIMISE:
            self.open = False
            self.host.hide()
            outcome.message = ("Minimised. Jarvis is still working - say his "
                               "name or click the taskbar to come back.")
            return outcome

        # EXIT and RESTART: the owed work first, then the window.
        self._settle(outcome)
        self.open = False
        self.host.close()
        if option.action == RESTART:
            if not self.host.request_restart():
                outcome.failed.append("request_restart")
        outcome.message = self._closing_message(option, outcome)
        return outcome

    def _settle(self, outcome: Outcome) -> None:
        """Do the owed work, recording what happened to each item.

        A missing callable is a **failure**, not a skip. The whole point of
        `OWED_BEFORE` is that an exit cannot quietly drop the checkpoint, and a
        caller that forgot to supply one should find that out here rather than
        after a restart that lost an afternoon."""
        for step in outcome.owed:
            if step == RESTORE_DESKTOP:
                try:
                    ok = self.host.restore_desktop()
                except Exception as exc:  # noqa: BLE001 - see below
                    outcome.failed.append(f"{step}: {exc}")
                    continue
                (outcome.performed if ok else outcome.failed).append(step)
                continue

            work = self.before_exit.get(step)
            if work is None:
                outcome.failed.append(f"{step}: nothing was wired up to do it")
                continue
            try:
                work()
            except Exception as exc:  # noqa: BLE001 - an exit must not be
                # blocked by its own bookkeeping. The window still closes; what
                # changes is that the outcome is not reported as clean.
                outcome.failed.append(f"{step}: {exc}")
            else:
                outcome.performed.append(step)

    def _closing_message(self, option: Option, outcome: Outcome) -> str:
        if outcome.clean:
            return ("Saved where I was. Goodbye." if option.action == EXIT
                    else "Saved where I was. Starting again.")
        # Said plainly, because the next session will have to explain a gap and
        # this is the only moment the owner can act on it.
        return (f"Closing, but not everything was saved: "
                f"{'; '.join(outcome.failed)}. Jarvis may not remember the last "
                f"few minutes when he comes back.")

    def _diagnostics_text(self) -> str:
        if self.diagnostics is None:
            return ("No diagnostics were wired up, which is itself worth "
                    "reporting. The logs are under the project's logs/ folder.")
        try:
            return self.diagnostics()
        except Exception as exc:  # noqa: BLE001 - a broken diagnostic must
            # still say something. This is the screen somebody reaches when
            # things are already going wrong.
            return f"The diagnostics could not be gathered: {exc}"


def describe() -> dict:
    """The design, as data. What a test and a renderer both read."""
    return {
        "opens_on": "Escape",
        "default": DEFAULT,
        "dismiss_with": ["Escape", "Enter"],
        "options": [{"key": option.key, "action": option.action,
                     "label": option.label, "consequence": option.consequence,
                     "ends_session": option.ends_session}
                    for option in OPTIONS],
        "owed_before": {action: list(steps) for action, steps in OWED_BEFORE.items()},
        "no_password": True,
    }
