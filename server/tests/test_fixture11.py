"""§10.10 — a required document the log cannot resolve is still required.

Issue #529, filed by the author of the branch it covers. `civic.py`'s
`_finish` reports `"ns": env.ns if env is not None else None` for a required
document the log cannot resolve. The `None` arm is deliberate — dropping the
entry would silently shorten the canon set, the failure §10.10 exists to
forbid — and it was **unexercised on every suite**.

WHY IT COULD NOT BE TESTED BEFORE, WHICH IS THE ISSUE'S REAL CONTENT
--------------------------------------------------------------------
Reaching it needs a `requires` or `pins` edge to an id the log cannot
resolve. **The validator refuses exactly that at post time (§1.1.7)**, and
every suite in this project builds its board BY POSTING — so the branch is
unreachable from every fixture the project owned. That is #437's structural
blindness: the transport seeds a fresh valid board, so the drift it would
catch is the drift it cannot have.

`conformance/fixture-11.jsonl` is the missing facility — a hand-written log
loaded directly rather than posted. It belongs in `conformance/` rather than
here because **every implementation has this branch and none can reach it
from its own write path**.

THE FIXTURE DIFFERS FROM A REAL LOG IN EXACTLY ONE STATED WAY
-------------------------------------------------------------
One record carries `pins -> 99`, an id the log does not contain. Its
genesis, its canon-nest policy and its resolvable document are fixture-04's
own, so a reader that mishandles this fixture is mishandling the dangling
edge and not the scaffolding. A malformed-log loader is the easiest place in
a suite to build a world so unlike production that its tests prove nothing;
the tests below assert the log is otherwise ordinary, so that claim is
checked rather than promised.
"""

from __future__ import annotations

import pytest

from korax.civic import onboard
from korax.log import Log
from korax.models import Envelope
from korax.policy import PolicyTimeline

from conftest import load_jsonl

MAINTAINER = "band:maint1"
ABSENT = 99


@pytest.fixture(scope="module")
def world() -> tuple[Log, PolicyTimeline, int]:
    envelopes = [Envelope.model_validate(r) for r in load_jsonl("fixture-11.jsonl")]
    log = Log(envelopes)
    return log, PolicyTimeline(log), envelopes[-1].id


@pytest.fixture(scope="module")
def out(world: tuple[Log, PolicyTimeline, int]) -> dict:
    log, timeline, head = world
    return onboard(log, timeline, head, MAINTAINER)


def test_the_fixture_is_ordinary_except_for_the_dangling_edge(
    world: tuple[Log, PolicyTimeline, int],
) -> None:
    """**The premise, checked rather than promised.** If this log is weird in
    more than one way, every assertion below is about a board nobody runs."""
    log, _, _ = world
    dangling = [
        (env.id, ref.id)
        for env in log.envelopes
        for ref in env.refs
        if log.get(ref.id) is None
    ]
    assert dangling == [(5, ABSENT)], (
        f"the fixture has {len(dangling)} unresolvable edges, not one: "
        f"{dangling}. Its whole value is being ordinary in every other way."
    )
    assert log.get(3) is not None, "the resolvable control is missing"


def test_the_unresolvable_document_is_reported_not_dropped(out: dict) -> None:
    """§10.10. Dropping it would shorten the canon set silently, and the
    reader would be told their reading list is complete when it is not."""
    entry = next((e for e in out["canon"] if e["id"] == ABSENT), None)
    assert entry is not None, (
        "the unresolvable requirement vanished from `canon` — a board that "
        "shortens the reading list rather than reporting the gap"
    )
    assert entry["ns"] is None, "an ns was invented for an envelope the log lacks"
    assert entry["via"] == ["pin:5"], "the gap must still say what required it"


def test_the_resolvable_document_beside_it_is_unaffected(out: dict) -> None:
    """**The control, and it is what makes the test above mean something.**

    A board that dropped the unresolvable entry would still serve a plausible
    one-item canon. Only the pair distinguishes *reported the gap* from
    *quietly shortened the list*.
    """
    entry = next((e for e in out["canon"] if e["id"] == 3), None)
    assert entry is not None and entry["ns"] == "/korax/canon"


def test_the_gap_is_counted_as_well_as_listed(out: dict) -> None:
    """A count that excludes what the list includes is worse than either
    alone: the reader reconciles them and trusts the smaller one."""
    assert ABSENT in out["unread"]
    assert out["unread_count"] == len(out["unread"]) == 2


def test_the_reduction_does_not_raise_on_a_damaged_log(
    world: tuple[Log, PolicyTimeline, int],
) -> None:
    """A dangling edge is a fact about the log. **A board that 500s here
    cannot report its own damage** — the one moment the reduction is most
    needed is the one it would refuse to run."""
    log, timeline, head = world
    for offset in range(head + 1):
        onboard(log, timeline, offset, MAINTAINER)  # must not raise


def test_null_ns_is_distinguishable_from_a_real_one(out: dict) -> None:
    """§402's rule, one field over: absent must not render as zero, and null
    must not render AS a namespace. Pinned because the entries share a shape
    on purpose — a client iterating them needs no branch, which is only safe
    while `None` stays unmistakable."""
    namespaces = {e["id"]: e["ns"] for e in out["canon"]}
    assert namespaces[ABSENT] is None
    assert isinstance(namespaces[3], str)
    assert namespaces[ABSENT] != "None", "the string, not the value — a fabrication"
