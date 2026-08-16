"""The browse tab on the perch (JOB #1308; design #1294, endorsed #1295).

Guards follow the #962/#841 split, labelled: contract against a real board,
structural over the served page. No browser here, so nothing proves it LOOKS
right; the contract half proves the data it is written against is real, and
the structural half pins the two rules the design actually rests on — the
ordering is the server's, and a bound renders as a bound.
"""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from perch_source import PERCH_DIR, script as _script


def script() -> str:
    return _script()


def browse_source() -> str:
    # The tab migrated to its own file (JOB #1389's template): the
    # section IS the file now, so no marker-splitting — a structural
    # test that reads the whole unit cannot be defeated by a section
    # header moving, which is what the split buys the tests too.
    return (PERCH_DIR / "js" / "tabs" / "browse.js").read_text()


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    op, tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    return {"client": TestClient(create_app(board)), "op": op, "tok": tok}


def test_the_view_carries_what_the_tab_renders(world: dict) -> None:
    """**Contract.** The tab reads `entries[]` with `id`, `ts`, `ns`, `type`,
    `author`, `first_line` and (scored sorts) `score`, plus `half_life`,
    `eval_ts`, `total` and the §9.3 counters. A reduction that stopped
    carrying one renders a blank column in a browser nobody is watching."""
    h = {"Authorization": f"Bearer {world['tok']}"}
    a = world["client"].post("/post", headers=h, json={
        "proto": PROTO, "author": world["op"], "ns": "/commons/rakes",
        "type": "WARN", "grade": "n/a", "refs": [], "ext": {}, "payload": "target"})
    world["client"].post("/post", headers=h, json={
        "proto": PROTO, "author": world["op"], "ns": "/commons/rakes",
        "type": "NOTE", "grade": "n/a", "ext": {}, "payload": "citation",
        "refs": [{"edge": "derives-from", "id": a.json()["id"]}]})
    body = world["client"].get(
        "/view/browse", params={"ns": "/commons", "sort": "hot"}, headers=h).json()
    out = body["output"]
    for field in ("half_life", "eval_ts", "total", "entries"):
        assert field in out, f"the tab renders {field}"
    assert out["entries"]
    for field in ("id", "ts", "ns", "type", "author", "first_line", "score"):
        assert field in out["entries"][0], f"the tab renders {field}"
    assert "withheld_scope" in body, (
        "the tab shows §9.3's counters; without a scope it cannot say which "
        "ruler they used (R56)"
    )


def test_the_ordering_is_the_servers_never_recomputed() -> None:
    """**D1 made structural on the client.** A client scoring by the edges it
    can see ranks its own blind spot, so the tab must render `/view/browse`
    in the order it arrives — no `.sort(` over the entries, ever. The score
    chip carries the same rule as prose: the sum is over YOUR visible slice."""
    src = browse_source()
    assert "/view/browse" in src
    assert ".sort(" not in src, (
        "the browse tab re-orders what the reduction ordered — the "
        "two-places defect #1294 D1 exists to prevent"
    )
    assert "visible to YOU" in src, "the score chip must say whose slice it sums"


def test_the_bound_and_the_counters_ride_the_page() -> None:
    """`total` beside `entries.length` renders as a bound, never as the end
    (§10.10, R67's shape), and the withheld counters ride the page as
    everywhere (fbWithheld)."""
    src = browse_source()
    assert "o.entries.length < o.total" in src
    assert "fbWithheld(view" in src
    assert "half-life" in src, (
        "the parameter that shaped the ordering must ride the page (D3)"
    )


def test_empty_renders_as_bounded_not_as_nothing() -> None:
    """R28's distinction on the one page built for scrolling: an empty list
    under a non-zero counter is a slice, and the tab must say so rather
    than assert the nest is quiet."""
    src = browse_source()
    assert "bounded" in src
