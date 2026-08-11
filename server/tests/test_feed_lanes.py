"""§11.2 R19c — every feed lane is classified self-excluded or exempt (#595).

D2 (#317, endorsed #324) specifies R19c **per lane**. `reasons_for`
implements it as one gate after `mailbox`. Both readings are correct about
the current lane set — which is exactly why #594's paired comparison could
not distinguish them — and they diverge the moment a lane is added: the new
lane inherits R19c silently, and nobody finds out until a bird stops hearing
something it should.

THE ONLY VERSION OF THIS TEST THAT IS WORTH WRITING
---------------------------------------------------
The easy one asserts `set(FEED_LANES) == SELF_EXEMPT_LANES |
SELF_EXCLUDED_LANES`, which is true by the definition one line above it and
**cannot fail**. It would pass forever, including on the day someone adds a
sixth lane, which is the only day it matters.

So the lanes are enumerated from **where they are produced** — the string
literals `reasons_for` actually emits, read out of the source by AST — and
compared against the classification. The two sides have independent origins,
so a lane added to the code and not to the set appears on one side only.

Read out of the AST rather than by exercising fixtures deliberately: a
fixture-driven census can only discover lanes somebody remembered to write a
fixture for, and the failure being guarded is precisely the one nobody
remembered.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from korax import feed
from korax.feed import (
    DEFAULT_LANES,
    FEED_LANES,
    SELF_EXCLUDED_LANES,
    SELF_EXEMPT_LANES,
)


def _emitted_lanes() -> set[str]:
    """Every `{"lane": "<literal>"}` `reasons_for` can append, from the AST.

    Independent of `FEED_LANES` by construction — this reads the function
    body, that is a hand-maintained set, and the whole point is that they
    can disagree.
    """
    source = Path(inspect.getsourcefile(feed)).read_text()
    tree = ast.parse(source)
    fn = next(
        (
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "reasons_for"
        ),
        None,
    )
    # A bare StopIteration here would be a guard failing without teaching:
    # the reader sees a traceback into a test helper and has to reconstruct
    # that the census, not the code under test, is what broke.
    assert fn is not None, (
        "the lane census cannot find `reasons_for` in korax.feed — it was "
        "renamed or moved, and this census is now blind. Point it at the new "
        "name; do NOT delete these tests to go green, because a blind census "
        "passes every other assertion in this file vacuously."
    )
    lanes: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant) and key.value == "lane"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                lanes.add(value.value)
    return lanes


def test_the_census_actually_finds_lanes() -> None:
    """A guard on the guard. Every assertion below passes vacuously if the
    AST walk returns nothing — a renamed function, a changed literal shape,
    a moved module. This is the one that notices."""
    found = _emitted_lanes()
    assert len(found) >= 5, (
        f"the lane census found {len(found)} lanes in reasons_for; it has "
        "stopped seeing the code and every other test in this file is now "
        "passing on an empty set"
    )
    assert "mailbox" in found and "to_author" in found


def test_every_emitted_lane_is_classified() -> None:
    """**THE canary #595 asks for.** A lane in neither set is a lane whose
    R19c status nobody decided — the silent inheritance the issue names."""
    unclassified = _emitted_lanes() - FEED_LANES
    assert not unclassified, (
        f"lane(s) emitted by reasons_for but classified in neither "
        f"SELF_EXCLUDED_LANES nor SELF_EXEMPT_LANES: {sorted(unclassified)}. "
        "R19c is per-lane (D2, #317/#324) — decide, and say which, rather "
        "than letting the gate's position decide silently."
    )


def test_no_lane_is_classified_that_cannot_be_emitted() -> None:
    """The other direction. A classified lane nothing emits is dead
    vocabulary that reads as coverage — the reader believes a lane exists
    and is handled, and neither is true."""
    phantom = FEED_LANES - _emitted_lanes()
    assert not phantom, (
        f"lane(s) classified but never emitted: {sorted(phantom)} — either "
        "the lane was removed and its classification outlived it, or it is "
        "spelled differently in the two places"
    )


def test_the_two_classifications_are_disjoint() -> None:
    """A lane both exempt and excluded is a contradiction the gate would
    resolve by position, which is the thing this issue exists to stop."""
    assert not (SELF_EXEMPT_LANES & SELF_EXCLUDED_LANES)


def test_mailbox_is_the_only_exemption_and_the_reason_is_structural() -> None:
    """Pinned deliberately. `mailbox` is exempt because a message you send
    lands in the RECIPIENT's box — your own mailbox holds other birds'
    envelopes by construction, so R19c's question does not arise rather
    than being answered 'no'. Any second exemption is a real design change
    and should not arrive as a one-word diff."""
    assert SELF_EXEMPT_LANES == {"mailbox"}


def test_the_default_lanes_are_all_real_lanes() -> None:
    """§11.2 — the lanes a band receives without subscribing. A typo here
    would silently narrow every band's default feed, and `DEFAULT_LANES` is
    a separate tuple that nothing else cross-checks."""
    assert set(DEFAULT_LANES) <= FEED_LANES, (
        f"DEFAULT_LANES names {set(DEFAULT_LANES) - FEED_LANES}, which "
        "reasons_for never emits — those lanes are off by default and by "
        "accident"
    )
