"""The console is a studio, not a terminal (backend/console/index.html;
addendum 41; TQ-33, SPEC_RECONCILIATION §85/§86).

Addendum 41 §18 asks for something unusual: that one requirement be
*re-checked throughout implementation review* rather than read once and
trusted. A specification sentence cannot do that on its own, so the checkable
part of it lives here, where it runs on every commit.

Two families of assertion, and the second is the one that has already caught a
real defect twice in this file's history.

**The look.** §2's explicit prohibitions - monospaced terminal aesthetics,
tables of small numbers - are testable at the level of "what does the stylesheet
actually say". They cannot prove the result is *beautiful*; they can prove it is
not the specific thing §18 forbids, which is what was asked.

**The wiring.** This file is one document holding markup and the script that
drives it, with no build step to notice when the two drift apart. Every defect
this console has shipped came from that seam: a handler bound to an id the
markup no longer had, a state field the renderer never initialised. A rewrite of
the presentation is exactly when that seam breaks, so the test walks it.
"""

import re
from pathlib import Path

import pytest

CONSOLE = Path(__file__).resolve().parent.parent / "backend" / "console" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return CONSOLE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script(html: str) -> str:
    body = re.search(r"<script>(.*)</script>", html, re.S)
    assert body, "the console has no script block"
    return body.group(1)


# --- the wiring: markup and script must agree ---------------------------------


def test_every_element_the_script_reaches_for_exists(html: str, script: str):
    """The defect class this file keeps producing: a handler bound to an id the
    markup does not have. It fails silently - `$("x")` returns null, the
    listener is never attached, and the control is simply dead - which is why
    it survived a green suite twice before."""
    defined = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', html))
    referenced = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', script))
    referenced |= set(re.findall(r'getElementById\("([A-Za-z0-9_-]+)"\)', script))
    missing = sorted(referenced - defined)
    assert not missing, f"the script reaches for ids the markup does not define: {missing}"


def test_every_desk_the_rundown_names_has_a_surface(html: str):
    """A button in the running order with no panel behind it is a dead click."""
    named = set(re.findall(r'data-tab="([a-z_]+)"', html))
    surfaces = set(re.findall(r'class="tab[^"]*" id="tab-([a-z_]+)"', html))
    assert named, "no desks in the rundown"
    assert named == surfaces, (
        f"rundown and surfaces disagree: {sorted(named ^ surfaces)}"
    )


def test_state_fields_the_renderers_read_are_initialised(script: str):
    """`S.tab` once had no initial value, so the first `selectTab` recorded
    `undefined` as the previous view and "go back" went nowhere."""
    declared = re.search(r"const S=\{(.*?)\};", script, re.S)
    assert declared, "the console state object is not declared as expected"
    initialised = set(re.findall(r"(\w+)\s*:", declared.group(1)))
    for field in ("tab", "follow", "attention", "source", "speak", "tapeWidth"):
        assert field in initialised, f"S.{field} is read but never initialised"


# --- the look: §2's prohibitions, §18's repeated check ------------------------


def test_the_reading_surface_is_not_monospaced(html: str):
    """§2 forbids "monospaced financial-terminal aesthetics". Monospace is
    allowed for digits and identifiers, where alignment is the whole point -
    but the body must not be set in it, which is what made the old console
    read as a terminal at a glance."""
    body_rule = re.search(r"\bbody\{([^}]*)\}", html, re.S)
    assert body_rule, "no body rule found"
    font = re.search(r"font:[^;]*;", body_rule.group(1))
    assert font, "the body sets no font"
    assert "monospace" not in font.group(0), (
        "the body is set in a monospaced font - addendum 41 §18: "
        "'If an implementation looks like a Bloomberg Terminal, it has failed.'"
    )


def test_no_desk_renders_a_table(script: str):
    """§2 forbids "dense grids of tiny numbers" and "excessive table density".
    The previous console built five of them. Cards and rows carry the same
    data with hierarchy, which is what §19's adaptive density asks for."""
    assert "<table" not in script, (
        "a desk still emits a <table> - §2 asks for information surfaces, not grids"
    )


def test_every_desk_leads_with_a_story(script: str):
    """§16's rhythm starts with a main story, and §19 wants overview density
    low - both of which mean the top of a desk is one large sentence, not the
    first row of its data.

    The briefing failed this when the redesign first ran: seven desks led with
    a headline and the eighth, the one that *is* the live briefing, opened
    straight into a card grid. It looked fine in the markup and was only
    visible by loading the page and asking each surface what its headline
    was."""
    desks = re.findall(r"function (render\w+)\(", script)
    surfaces = [d for d in desks if d not in
                ("renderFeed", "renderSources", "renderStanding", "renderTape", "renderLead")]
    assert len(surfaces) >= 7, f"expected the desks, found {surfaces}"
    for name in surfaces:
        block = re.search(rf"function {name}\(.*?\n\}}", script, re.S)
        assert block, f"could not read {name}"
        assert "lead(" in block.group(0) or "headline" in block.group(0), (
            f"{name} opens without a headline"
        )
    # The briefing's lead is computed rather than fixed, so it is asserted
    # separately: it is the one desk whose main story changes every poll.
    assert "function renderLead(" in script
    assert "renderLead(d);" in script, "the briefing's lead is never actually rendered"


def test_the_status_vocabulary_is_complete(html: str):
    """§20 names six states that must be visually distinguishable. Five of them
    already have a treatment; the point of asserting it is that a later
    stylesheet edit cannot quietly drop one and leave two states looking
    identical."""
    for state in ("active", "waiting", "completed", "silent"):
        assert f".st-{state}" in html, f"no visual treatment for '{state}'"
    for kind in (".tag.ok", ".tag.attn", ".tag.bad"):
        assert kind in html, f"no visual treatment for '{kind}'"


def test_motion_is_bounded(html: str):
    """§15 asks for restrained camera-like transitions and §7 forbids
    meaningless animation. Neither is provable from a stylesheet, but a
    transition measured in whole seconds is not restraint by any reading, and
    this file has already pegged a renderer once with an animation nobody
    budgeted for."""
    durations = [float(d) for d in re.findall(r"(?:transition|animation)[^;]*?([\d.]+)s", html)]
    assert durations, "no transitions declared - §14 asks panels to move, not cut"
    assert max(durations) <= 2.5, f"a {max(durations)}s transition is not restraint"


# --- identity and honesty -----------------------------------------------------


def test_the_presenter_is_named(html: str):
    """Addenda 41 §3 and 42 §19: Kumbhakarnan is the COO's identity, and
    "changing implementation versions must not silently replace" it. Until
    TQ-35 makes that identity persisted state, the console at least has to
    stop calling him "COO"."""
    assert "Kumbhakarnan" in html
    assert ">COO<" not in html, "the COO is addressed by title rather than by name"


def test_the_presenter_frame_does_not_pretend(html: str):
    """§3 rules out a static avatar standing in for the animated presenter.
    The honest placeholder says what it is waiting for - and saying so in the
    interface, not only in the task queue, is what stops the placeholder from
    quietly becoming the deliverable."""
    assert "not built yet" in html, (
        "the presenter frame should say the animated presenter does not exist yet"
    )


def test_the_finance_desk_still_says_simulated(script: str):
    """Unchanged by the redesign and non-negotiable: a finance page is the one
    place in this system where blurring synthetic and real would be genuinely
    dangerous. A visual rewrite is exactly the kind of change that drops a
    banner by accident."""
    assert "SIMULATED" in script
    assert "note sim" in script, "the simulated banner lost its distinct treatment"
