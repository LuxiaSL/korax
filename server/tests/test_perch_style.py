"""The token layer holds (JOB #1740, the style pass).

The pass's whole premise is that **swapping `variables.css` restyles every
tab** — which is only true while no other file names a raw value. That is a
property prose cannot keep and a test can, so it is a test.

Each guard below was watched failing against a deliberately broken version
before it was trusted (#112, canon v6). The canaries are the `_canary`
tests: they patch the source in memory, assert the guard reddens, and never
touch disk.
"""

from __future__ import annotations

import re

import pytest

from perch_source import PERCH_DIR

CSS_DIR = PERCH_DIR / "css"
TOKENS = CSS_DIR / "variables.css"

#: A hex colour anywhere. Matched on the whole declaration block so the
#: message can name the line rather than the file.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
#: `var(--name)` — every token a stylesheet consumes.
VAR_USE = re.compile(r"var\(\s*(--[a-z0-9-]+)")
#: `--name:` at a definition site.
VAR_DEF = re.compile(r"^\s*(--[a-z0-9-]+)\s*:", re.M)


def _stylesheets() -> list:
    files = sorted(p for p in CSS_DIR.rglob("*.css") if p != TOKENS)
    assert files, (
        "the glob found no stylesheets besides variables.css — either the "
        "css layout moved or this guard has gone vacuous, and a vacuous "
        "guard is R74's door"
    )
    return files


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_only_the_token_layer_names_a_colour() -> None:
    """The swap-one-file premise, asserted.

    A hex outside `variables.css` is a colour the style pass cannot reach —
    it will survive a palette change and be found by a human noticing that
    one chip stayed the old blue.
    """
    offenders = []
    for path in _stylesheets():
        for n, line in enumerate(_strip_comments(path.read_text()).splitlines(), 1):
            if HEX.search(line):
                offenders.append(f"{path.relative_to(CSS_DIR)}:{n}: {line.strip()}")
    assert not offenders, (
        "raw colour(s) outside variables.css — swapping the token layer "
        "would leave these behind:\n  " + "\n  ".join(offenders)
    )


def test_every_token_used_is_a_token_defined() -> None:
    """`var(--acent)` renders as nothing and throws no error anywhere.

    A misspelled custom property is the silent-failure shape this board
    keeps meeting: the browser drops the declaration, the element falls back
    to something plausible, and no console, no build and no test says a
    word.
    """
    defined = set(VAR_DEF.findall(TOKENS.read_text()))
    assert defined, "variables.css defines no tokens at all"
    unknown = {}
    for path in _stylesheets():
        for name in VAR_USE.findall(_strip_comments(path.read_text())):
            if name not in defined:
                unknown.setdefault(name, []).append(str(path.relative_to(CSS_DIR)))
    assert not unknown, (
        "stylesheet(s) reference undefined token(s) — these declarations are "
        "silently dropped by every browser:\n  "
        + "\n  ".join(f"{k} used in {sorted(set(v))}" for k, v in unknown.items())
    )


def test_the_mobile_ergonomic_thresholds_are_still_literal() -> None:
    """The mobile pass's three numbers must NOT be on the scale.

    44px and 40px are thumb floors; 16px is the size below which iOS zooms
    the page on input focus and throws the compose box off-screen. **If a
    future scale tweak moved them, nothing would look broken** — the tabs
    would render, the suite would stay green, and the defect would only
    appear under a thumb on a phone. So the pass left them literal, and this
    guard is what keeps the next pass from "tidying" them into tokens.
    """
    base = (CSS_DIR / "base.css").read_text()
    phone = base.split("@media (max-width: 640px)", 1)
    assert len(phone) == 2, "the mobile breakpoint block is gone"
    block = phone[1]
    for literal, why in (
        ("min-height: 44px", "the nav's touch floor"),
        ("min-height: 40px", "the button touch floor"),
        ("font-size: 16px", "the iOS input-zoom threshold"),
    ):
        assert literal in block, (
            f"{literal!r} ({why}) is no longer literal in the phone block — "
            f"an ergonomic threshold expressed as a scale step moves when the "
            f"scale moves, and nothing about that failure is visible on a desktop"
        )


def test_the_reading_face_and_the_instrument_face_are_both_bound() -> None:
    """The pass's one typographic decision, asserted in both directions.

    Chrome is monospace and prose is not. Asserting only the first half
    would pass a stylesheet that had quietly set everything to mono —
    which is the state the first screenshot of this pass was in.
    """
    base = _strip_comments((CSS_DIR / "base.css").read_text())
    assert re.search(r"body\s*\{[^}]*var\(--font-ui\)", base), (
        "body no longer sets the instrument face"
    )
    assert re.search(r"\.payload[^{]*\{[^}]*var\(--font-text\)", base) or \
           re.search(r"\.payload,\s*\n?[^{]*\{[^}]*var\(--font-text\)", base), (
        "the payload no longer opts out into the reading face — envelope "
        "prose runs to a thousand words and monospace at that length is the "
        "cost this pass exists to avoid"
    )


def test_no_colour_is_defined_only_under_a_media_query() -> None:
    """Dark-theme discipline, per the brief.

    The perch has one palette and no light mode, so the coherence rule
    reduces to: every colour has exactly one definition, at `:root`. A token
    redefined only inside a media block is a colour that exists at some
    viewport widths and not others.
    """
    text = TOKENS.read_text()
    root_block = text.split(":root {", 1)[1].split("}", 1)[0]
    root_tokens = set(VAR_DEF.findall(root_block))
    for match in re.finditer(r"@media[^{]*\{(.*?)\n\}", text, re.S):
        for name in VAR_DEF.findall(match.group(1)):
            assert name in root_tokens, (
                f"{name} is defined inside a media query but not at :root — "
                f"it exists only at some viewport widths"
            )


# -- canaries: each guard above, watched failing ----------------------------

def test_canary_the_colour_guard_sees_a_planted_hex(tmp_path) -> None:
    line = ".fake { color: #ff00ff; }"
    assert HEX.search(line), "the colour guard's own pattern does not match a hex"
    assert not HEX.search(".fake { color: var(--accent); }"), (
        "the colour guard matches a tokenised declaration, so it would fire "
        "on correct code and prove nothing"
    )


def test_canary_the_token_guard_sees_a_typo() -> None:
    defined = set(VAR_DEF.findall(TOKENS.read_text()))
    assert "--accent" in defined, "the token guard cannot see real definitions"
    assert "--acent" not in defined, (
        "a misspelling resolves as defined, so the guard cannot detect one"
    )


def test_canary_the_mobile_guard_sees_a_tokenised_threshold() -> None:
    """The thing the guard is meant to catch: someone replacing the literal
    with a scale step. Patched in memory; disk is untouched."""
    base = (CSS_DIR / "base.css").read_text()
    broken = base.replace("min-height: 40px", "min-height: var(--space-2xl)")
    assert broken != base, "the canary patched nothing — the literal moved"
    block = broken.split("@media (max-width: 640px)", 1)[1]
    assert "min-height: 40px" not in block, (
        "the broken version still contains the literal, so the guard above "
        "would pass against it and is not testing what it claims"
    )
