"""JOB #1591 — the mobile pass's structural guards.

A reflow cannot be asserted in pytest and this file does not pretend
otherwise (the brief says so; acceptance is the named screenshots and
the measured viewport run in the delivery). What CAN be guarded is the
two lines whose silent loss would undo the whole pass without any other
test noticing: the viewport declaration, and the phone breakpoint with
its nav pattern.
"""
from __future__ import annotations

import re

from perch_source import PERCH_DIR, markup


def test_the_shell_declares_a_mobile_viewport() -> None:
    """Without `width=device-width` every phone renders the desktop
    layout zoomed out, and every rule in the phone breakpoint below is
    dead code — the one-line dependency of the entire mobile pass."""
    head = markup()
    assert re.search(
        r'<meta\s+name="viewport"\s+content="[^"]*width=device-width', head
    ), "index.html lost its viewport meta — the mobile pass is inert without it"


def test_base_css_carries_the_phone_breakpoint() -> None:
    """The breakpoint exists and the nav's chosen pattern (a horizontal
    scroll strip — the delivery states why) survives inside it. This
    asserts presence, not appearance: appearance is the screenshots'."""
    css = (PERCH_DIR / "css" / "base.css").read_text()
    m = re.search(r"@media\s*\(max-width:\s*640px\)\s*\{(.*)", css, re.S)
    assert m, "base.css lost its phone breakpoint (@media max-width: 640px)"
    phone = m.group(1)
    assert "overflow-x: auto" in phone and "nav" in phone, (
        "the phone block no longer makes the nav a scroll strip — if the "
        "pattern changed on purpose, update this test with the new one"
    )
    # The body guard is a safety net, not the mechanism (the delivery's
    # canary run proves the containers fit without it) — but it should
    # not vanish by accident either.
    assert "overflow-x: clip" in phone
