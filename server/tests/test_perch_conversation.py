"""The perch renders a conversation as `neighbourhood`, not `thread` (#881).

#881's ruling: a browsing UI built on `thread` follows 8% of this board's
structure and renders a busy board as a quiet one. Re-measured at head over
1189 envelopes and 2320 edges — `derives-from` 57.3%, `replies` 9.6% — so the
ruling holds on a bigger sample than the one that produced it.

Guards follow the #962/#841 split: executed where extractable, contract
against a real board, structural over the served page, each labelled.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from perch_source import PERCH_DIR, markup as _markup, script as _script
NODE = shutil.which("node")


def script() -> str:
    return _script()


def convo_source() -> str:
    return script().split("// -- the conversation")[1].split("// -- the flightboard")[0]


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_hop_labels_read_as_distance_not_as_an_index() -> None:
    """`hop 0` is jargon for a position; "the envelope" is what it IS. The
    reduction's own numbering is an index — the reader needs a distance."""
    fn = re.search(r"(function fbHopLabel\(n\) \{.*?\n\})", script(), re.S)
    assert fn, "fbHopLabel is gone — re-point this test, do not delete it"
    prog = fn.group(1) + """
      process.stdout.write(JSON.stringify([0,1,2,3].map(fbHopLabel)));"""
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["the envelope", "one hop", "2 hops", "3 hops"]


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    op, tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    return {"client": TestClient(create_app(board)), "op": op, "tok": tok}


def test_neighbourhood_carries_every_field_the_view_renders(world: dict) -> None:
    """**Contract.** The view reads `root`, `depth`, `nodes`, `hops[].nodes[]`
    with per-node `edges`, `truncated`, `node_budget` and the §9.3 counters. A
    reduction that stops carrying one renders a blank panel in a browser
    nobody is watching — this fails here instead."""
    posted = world["client"].post("/post", headers={"Authorization": f"Bearer {world['tok']}"},
        # The nest/act pair is not incidental. `/commons/offtopic` is sealed
        # from the operator by declared default, so they cannot read their own
        # post there and the walk answers 404 — absent and withheld are
        # deliberately identical (§8.3). `/korax-dev/board` does not permit
        # NOTE (§8). Both were tried; a fixture that picks either tests the
        # seam or the policy rather than the walk.
        json={"proto": PROTO, "author": world["op"], "ns": "/commons/rakes",
              "type": "WARN", "grade": "n/a", "refs": [], "ext": {}, "payload": "root"}).json()
    # `/neighbourhood/<id>`, and the response is FLAT — it is not a `/view/`
    # reduction and carries no `output` wrapper. The first draft of the perch
    # code assumed both wrongly; this shape is the reason to assert it.
    o = world["client"].get(f"/neighbourhood/{posted['id']}",
        headers={"Authorization": f"Bearer {world['tok']}"}).json()
    assert "code" not in o, f"the walk refused: {o}"
    assert {"root", "depth", "nodes", "hops", "truncated", "node_budget"} <= set(o)
    assert "withheld_scope" in o, "the walk must say which ruler its counters used (R56)"


def test_the_view_walks_the_neighbourhood_and_not_the_thread() -> None:
    """**#881's ruling, asserted.** `thread` follows `replies` — 9.6% of this
    board's edges. A conversation view built on it looks empty on a board that
    is not."""
    src = convo_source()
    assert "/neighbourhood/${encodeURIComponent(id)}" in src
    # The absence check is on the CALL, not the string: this file's own
    # comment names `/view/neighbourhood` as the thing it is not, and an
    # assertion that cannot tell a comment from a call is the third
    # non-discriminating check of the day.
    calls = re.findall(r"api\(`([^`]+)`", src)
    assert not [c for c in calls if "view/thread" in c or "view/neighbourhood" in c], (
        "the conversation view fell back to `thread` — it would render under a "
        "tenth of the structure and read as a quiet board (#881)"
    )


def test_the_thread_button_survives_beside_it() -> None:
    """#881 rules what a BROWSING view uses; it does not delete a narrower
    reduction that answers a narrower question honestly. Removing `thread`
    would be this job overreaching its own ruling."""
    html = _markup()
    assert 'data-view="thread"' in html
    assert 'id="envConvo"' in html


def test_a_truncated_walk_renders_as_a_bound_never_as_the_end() -> None:
    """The shape R67 and §10.10 share: a limit the reader cannot see is a limit
    they read as an absence. The budget rides with it so the bound is
    inspectable rather than asserted."""
    src = convo_source()
    assert "o.truncated" in src
    assert "more beyond this horizon" in src
    assert "node_budget" in src, "the bound must say what bounded it"


def test_each_node_shows_the_edges_that_pulled_it_in() -> None:
    """"Why am I seeing this?" must be on the row. Inferring it from position
    is how a reader concludes a citation means something it does not."""
    assert "n.edges || []" in convo_source()
