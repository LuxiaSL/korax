"""§11 / JOB #163 — the board says goodbye instead of severing.

THE MECHANISM UNDER TEST IS ONE CLAUSE, NOT THE LIFESPAN HANDLER.
`Board.wait_for` is `asyncio.Condition.wait_for`, which RE-EVALUATES its
predicate after every notify and parks again if it is still false. So a
shutdown that only called `notify_all()` would wake every parked caller and
put it straight back to sleep — the board would sever them exactly as it did
before, after politely waking them once. What makes the goodbye work is that
the predicates themselves admit the shutdown.

AND THERE ARE TWO PREDICATE SHAPES, NOT ONE (#854). `/wait` and `/feed` park
on `hits_now()`; `/subscribe` parks on `board.head > cursor`. A clause
written once against the first form does not cover the third endpoint, and
`board.head > cursor` is *plausibly* true during a shutdown for unrelated
reasons — so an uncovered `/subscribe` can pass a test that happens to post
an envelope and fail in production when nothing is arriving. Each endpoint
therefore gets its own assertion here rather than being covered by
proximity.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from korax.api import create_app
from korax.board import DEFAULT_RETRY_AFTER_S, Board
from korax.seed import seed_board
from korax.store import Store


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    return {"store": store, "board": board, "client": TestClient(create_app(board)),
            "operator": operator, "op_token": op_token}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _shutdown(board: Board, retry_after_s: int | None = None) -> None:
    asyncio.new_event_loop().run_until_complete(
        board.begin_shutdown(retry_after_s=retry_after_s))


def test_wait_returns_a_goodbye_page_rather_than_severing(world: dict) -> None:
    head = world["board"].head
    _shutdown(world["board"], retry_after_s=12)
    # `since` AT HEAD, so this call genuinely parks. With a lower `since`
    # there is real content to deliver and the board correctly delivers it —
    # see test_pending_content_beats_the_goodbye below.
    r = world["client"].get(
        "/wait", params={"ns": "/commons/rakes", "since": head, "timeout": 5},
        headers=auth(world["op_token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["envelopes"] == []
    assert body["system_notice"]["kind"] == "restart"
    assert body["system_notice"]["retry_after_s"] == 12


def test_feed_returns_a_goodbye_page_too(world: dict) -> None:
    """The second call site sharing the `hits_now()` shape."""
    _shutdown(world["board"])
    r = world["client"].get(
        "/feed", params={"since": 3, "timeout": 5}, headers=auth(world["op_token"]))
    assert r.status_code == 200
    assert r.json()["system_notice"]["retry_after_s"] == DEFAULT_RETRY_AFTER_S


def test_subscribe_gets_the_notice_on_its_OWN_predicate(world: dict) -> None:
    """THE THIRD CALL SITE, whose predicate is a different shape (#854).

    `/subscribe` parks on `board.head > cursor`. This test posts NOTHING —
    deliberately — so that a version relying on new envelopes to break the
    park cannot pass. The only thing that can end this stream is the
    shutdown clause.
    """
    _shutdown(world["board"], retry_after_s=9)
    with world["client"].stream(
        "GET", "/subscribe", params={"since": world["board"].head},
        headers=auth(world["op_token"]),
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "event: system_notice" in body
    assert '"retry_after_s": 9' in body or '"retry_after_s":9' in body


def test_the_goodbye_page_does_not_advance_the_cursor(world: dict) -> None:
    """A cursor is a receipt for delivery; a page with no envelopes has
    delivered nothing to issue a receipt for (#854)."""
    head = world["board"].head
    _shutdown(world["board"])
    r = world["client"].get(
        "/wait", params={"ns": "/commons/rakes", "since": head, "timeout": 5},
        headers=auth(world["op_token"]))
    assert r.json()["cursor"] == head, "the goodbye certified a read that never happened"


def test_a_post_during_shutdown_is_503_and_writes_nothing(world: dict) -> None:
    """Clean refusal BEFORE the store is touched: a half-write during
    shutdown is the one failure an append-only log cannot walk back."""
    head_before = world["board"].head
    _shutdown(world["board"], retry_after_s=15)
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": "korax/0.1", "author": world["operator"],
        "ns": "/commons/rakes", "type": "WARN", "grade": "n/a",
        "payload": "posted into a closing board",
    })
    assert r.status_code == 503
    assert "restarting" in r.json()["message"]
    assert world["board"].head == head_before


def test_the_notice_always_carries_a_number(world: dict) -> None:
    """Ruled at #854. A `retry_after_s` supplied only by the well-behaved
    path is absent exactly when things are going badly — a hand-typed
    `systemctl restart`, an OOM that still runs lifespan, an operator
    bouncing the box at 3am. The ops lane exists for those, so the server
    defaults rather than emitting null."""
    _shutdown(world["board"], retry_after_s=None)
    r = world["client"].get(
        "/feed", params={"since": 3, "timeout": 5}, headers=auth(world["op_token"]))
    notice = r.json()["system_notice"]
    assert isinstance(notice["retry_after_s"], int)
    assert notice["retry_after_s"] > 0


def test_a_healthy_board_sends_no_notice(world: dict) -> None:
    """THE CANARY (#10). Every assertion above would also pass on a build
    that attached the notice to every page unconditionally, which would be a
    board permanently announcing its own death. A field that is always
    present carries no information."""
    r = world["client"].get(
        "/wait", params={"ns": "/commons/rakes", "since": 3, "timeout": 1},
        headers=auth(world["op_token"]))
    assert r.status_code == 200
    assert r.json().get("system_notice") is None


def test_pending_content_beats_the_goodbye(world: dict) -> None:
    """A goodbye replaces a PARK, never a DELIVERY.

    Discovered by two tests failing for the right reason: with real matching
    content, a shutting-down board still returns the envelopes rather than a
    notice. That is correct and worth pinning — the alternative would drop
    envelopes a caller had already earned, on the way out, which is exactly
    the silent loss #163 exists to end.
    """
    _shutdown(world["board"], retry_after_s=5)
    r = world["client"].get(
        "/wait", params={"ns": "/commons/rakes", "since": 3, "timeout": 5},
        headers=auth(world["op_token"]))
    body = r.json()
    assert body["envelopes"], "a shutting-down board dropped deliverable content"
    assert body.get("system_notice") is None
    assert body["cursor"] > 3
