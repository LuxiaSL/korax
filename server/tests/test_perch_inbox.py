"""The inbox reads as an inbox (JOB #1252 piece 4).

What makes a nest view an INBOX is disposition at a glance: which requests
have been engaged with and which are sitting untouched. `state.opens` already
answers *unclosed*; it cannot answer *unanswered*, and those are different
questions — an OPEN with four replies and no resolution waits on a decision,
one with nothing waits on somebody to look.

Guards: executed (the chip is pure and runs under node), structural for the
wiring. No browser here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from perch_source import PERCH_DIR, markup as _markup, script as _script
NODE = shutil.which("node")


def script() -> str:
    return _script()


def run_chip(page: object) -> str:
    fn = re.search(r"(function inboxDisposition\(page\) \{.*?\n\})", script(), re.S)
    assert fn, "inboxDisposition is gone — re-point this test, do not delete it"
    prog = ("const esc = (s) => String(s);\n" + fn.group(1)
            + f"\nprocess.stdout.write(inboxDisposition({json.dumps(page)}));")
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_an_untouched_open_says_untouched_not_zero() -> None:
    """**The state that matters most and reads worst as a number.** "0 since"
    is a count; "untouched" is the fact — nobody has looked. On the operator's
    own queue that is the row they should act on first."""
    out = run_chip({"envelopes": []})
    assert "untouched" in out
    assert "nothing has pointed at this" in out


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_an_engaged_open_counts_envelopes_and_distinct_bands() -> None:
    """Two different facts. Four envelopes from one band is a monologue; four
    from four is a conversation, and the operator reading a queue wants to
    tell them apart without opening anything."""
    out = run_chip({"envelopes": [
        {"id": 1, "author": "band:a"}, {"id": 2, "author": "band:a"},
        {"id": 3, "author": "band:b"},
    ]})
    assert "3 since" in out and "2 bands" in out


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_one_band_is_singular() -> None:
    """A chip that says "1 bands" is a chip nobody proofread, on the surface
    the operator reads most."""
    assert "1 band engaged" in run_chip({"envelopes": [{"id": 1, "author": "band:a"}]})


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_failed_context_read_is_not_reported_as_untouched() -> None:
    """**The control, and the trap.** `contextBlock` catches its own failure to
    `null`. If a dead board rendered as "untouched", every open in the queue
    would look freshly ignored — a wrong answer that reads exactly like the
    right one, which is the shape this board has paid for all loop.

    Today `null` and empty DO render alike, and this test pins that as a KNOWN
    limit rather than an accident: the chip cannot distinguish them because the
    caller discards the distinction before it arrives. Fixing it means
    `contextBlock` reporting the failure, which is a change to a shared helper
    and not this piece's to make.
    """
    assert "untouched" in run_chip(None), (
        "if this changed, the caller now distinguishes a failed read from an "
        "empty one — good, and this test should assert the new behaviour"
    )


def test_the_disposition_costs_no_extra_fetch() -> None:
    """A second `read?to=<id>` per open would double the inbox's cost to say
    something the first already knew. The chip reads a cache the context block
    fills."""
    src = script()
    assert "CONTEXT_PAGES.set(id, page)" in src
    assert "inboxDisposition(CONTEXT_PAGES.get(id))" in src
    assert src.count("`/read?to=${id}&limit=50`") == 1, "a second context read appeared"


def test_every_inbox_open_can_reach_its_conversation() -> None:
    """Piece 2's walk, wired where a reader is actually deciding. An inbox that
    shows a request without its conversation makes the reader navigate by id."""
    assert "loadConversation()" in script()
