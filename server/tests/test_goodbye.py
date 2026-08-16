"""§11 / JOB #163 — the board says goodbye instead of severing.

THE MECHANISM IS ONE CLAUSE, AND THESE TESTS EXIST TO EXERCISE IT.
`Board.wait_for` is `asyncio.Condition.wait_for`, which RE-EVALUATES its
predicate after every notify and parks again if it is still false. So a
shutdown that only called `notify_all()` would wake every parked caller and
put it straight back to sleep — the board would sever them exactly as it did
before, after politely waking them once. What makes the goodbye work is that
the predicates themselves admit the shutdown.

**THE FIRST VERSION OF THIS FILE TESTED NONE OF THAT, AND A MUTATION PASS IS
WHAT SAID SO.** It armed the shutdown BEFORE issuing each request, so no call
ever parked: every one went straight to the post-park return and the
predicate clause was never reached. Four separate mutants survived —
deleting the clause from `/wait` and `/feed`, deleting it from `/subscribe`,
advancing the cursor to head, and attaching the notice unconditionally — all
with eight green tests. That is #112 wearing a green tick, and it is the
exact failure mode the desk warned about at #854 when it said `/subscribe`
must be covered by an assertion of its own rather than by proximity.

So every test below **parks a real request first and shuts the board down
underneath it**. If the clause is removed, the request hangs until its
timeout and the assertion fails on an empty page rather than a goodbye.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from fastapi.testclient import TestClient

from korax.api import create_app
from korax.board import DEFAULT_RETRY_AFTER_S, Board
from korax.seed import seed_board
from korax.store import Store

# A selector that matches NOTHING, so a request using it genuinely PARKS
# while `since` stays far below head — which is what lets the cursor
# assertion tell `since` and `board.head` apart.
#
# `/korax/notices` alone is not empty: its own seed POLICY lives there, which
# is why the first attempt at this still returned content. Pairing it with an
# act nobody has posted there is what makes the park real.
PARKS = {"ns": "/korax/notices", "type": "WARN"}


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    return {"store": store, "board": board, "app": create_app(board),
            "operator": operator, "op_token": op_token}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def park_then_shutdown(world: dict, path: str, params: dict,
                       retry_after_s: int | None = None) -> httpx.Response:
    """Issue a request that PARKS, then shut the board down under it.

    This is the whole point of the file: the request must already be blocked
    inside `cond.wait_for` when the shutdown arrives, because that is the
    only state in which the predicate clause does any work.
    """
    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=world["app"])
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://board.test") as client:
            task = asyncio.create_task(
                client.get(path, params=params, headers=auth(world["op_token"])))
            await asyncio.sleep(0.25)          # let it actually park
            assert not task.done(), (
                f"{path} returned before the shutdown — it never parked, so "
                "this test would not exercise the predicate clause"
            )
            await world["board"].begin_shutdown(retry_after_s=retry_after_s)
            # PROMPTLY, and the bound is the assertion. Without the clause in
            # the predicate the caller still eventually gets a goodbye — from
            # the post-park check, after its FULL timeout — and a mutation
            # pass showed that version passing every content assertion here.
            # In production that is the original bug: uvicorn's shutdown
            # either waits out the timeout or force-closes the socket, which
            # is the severance this job exists to end. So the goodbye has to
            # arrive because the predicate admitted the shutdown, not because
            # the long poll gave up.
            started = asyncio.get_running_loop().time()
            response = await asyncio.wait_for(task, timeout=10)
            elapsed = asyncio.get_running_loop().time() - started
            assert elapsed < 2.0, (
                f"the goodbye took {elapsed:.1f}s with an 8s poll budget — it "
                "came from the timeout expiring, not from the shutdown clause"
            )
            return response

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scenario())
    finally:
        loop.close()


def test_a_parked_wait_gets_a_goodbye_rather_than_severing(world: dict) -> None:
    head = world["board"].head
    r = park_then_shutdown(world, "/wait",
                           {**PARKS, "since": head, "timeout": 8},
                           retry_after_s=12)
    assert r.status_code == 200
    body = r.json()
    assert body["envelopes"] == []
    assert body["system_notice"]["kind"] == "restart"
    assert body["system_notice"]["retry_after_s"] == 12


def test_a_parked_feed_gets_one_too(world: dict) -> None:
    """The second call site sharing the `hits_now()` shape."""
    head = world["board"].head
    r = park_then_shutdown(world, "/feed", {"since": head, "timeout": 8})
    assert r.status_code == 200
    assert r.json()["system_notice"]["retry_after_s"] == DEFAULT_RETRY_AFTER_S


def test_a_parked_subscribe_gets_the_notice_on_its_OWN_predicate(world: dict) -> None:
    """THE THIRD CALL SITE, whose predicate is a different shape (#854).

    `/subscribe` parks on `board.head > cursor`, not on `hits_now()`. Nothing
    is posted here — deliberately — so a version relying on new envelopes to
    break the park cannot pass, and the stream can only end via the shutdown
    clause.
    """
    async def scenario() -> str:
        transport = httpx.ASGITransport(app=world["app"])
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://board.test") as client:
            chunks: list[str] = []

            async def read_stream() -> None:
                async with client.stream(
                    "GET", "/subscribe",
                    params={"since": world["board"].head},
                    headers=auth(world["op_token"]),
                ) as response:
                    assert response.status_code == 200
                    async for text in response.aiter_text():
                        chunks.append(text)

            task = asyncio.create_task(read_stream())
            await asyncio.sleep(0.25)
            assert not task.done(), "/subscribe returned before the shutdown"
            await world["board"].begin_shutdown(retry_after_s=9)
            await asyncio.wait_for(task, timeout=10)
            return "".join(chunks)

    loop = asyncio.new_event_loop()
    try:
        body = loop.run_until_complete(scenario())
    finally:
        loop.close()
    assert "event: system_notice" in body
    assert '"retry_after_s": 9' in body or '"retry_after_s":9' in body


def test_the_goodbye_does_not_advance_the_cursor(world: dict) -> None:
    """A cursor is a receipt for delivery (#854).

    `since` is deliberately far BELOW head, against an empty nest, so the
    request parks while `since != board.head`. The earlier version used
    `since == head` and could not tell the two apart — a mutant that returned
    `board.head` passed it.
    """
    head = world["board"].head
    assert head > 3
    r = park_then_shutdown(world, "/wait",
                           {**PARKS, "since": 3, "timeout": 8})
    assert r.json()["cursor"] == 3, "the goodbye certified a read that never happened"


def test_a_healthy_board_sends_no_notice(world: dict) -> None:
    """THE CANARY (#10). Without this, a build that attached the notice to
    every page — a board permanently announcing its own death — passes
    everything above. A field that is always present carries no information.
    """
    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=world["app"])
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://board.test") as client:
            return await client.get(
                "/wait", params={**PARKS, "since": 3, "timeout": 1},
                headers=auth(world["op_token"]))

    loop = asyncio.new_event_loop()
    try:
        r = loop.run_until_complete(scenario())
    finally:
        loop.close()
    body = r.json()
    assert r.status_code == 200
    assert body.get("system_notice") is None
    assert body["cursor"] == 3
    # AND it is a real page, not a goodbye that happens to carry no notice.
    # `goodbye_page` emits only `sealed_excluded`; a served page carries the
    # full §9.3 counter set. Without this, a build that returned a goodbye
    # for every empty result — a board permanently announcing its own death —
    # passes, because on a healthy board that notice is None.
    assert "participation_excluded" in body, (
        "an ordinary empty page lost its exclusion counters — this is a "
        "goodbye page wearing a healthy board's clothes"
    )


def test_pending_content_beats_the_goodbye(world: dict) -> None:
    """A goodbye replaces a PARK, never a DELIVERY.

    A shutting-down board with content matching the caller's filter still
    returns the content. The alternative would drop envelopes a caller had
    already earned, on the way out — the silent loss #163 exists to end.
    """
    asyncio.new_event_loop().run_until_complete(
        world["board"].begin_shutdown(retry_after_s=5))

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=world["app"])
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://board.test") as client:
            return await client.get(
                "/wait", params={"ns": "/commons/rakes", "since": 3, "timeout": 5},
                headers=auth(world["op_token"]))

    loop = asyncio.new_event_loop()
    try:
        r = loop.run_until_complete(scenario())
    finally:
        loop.close()
    body = r.json()
    assert body["envelopes"], "a shutting-down board dropped deliverable content"
    assert body.get("system_notice") is None
    assert body["cursor"] > 3


def test_a_post_during_shutdown_is_503_and_writes_nothing(world: dict) -> None:
    """Clean refusal BEFORE the store is touched: a half-write during
    shutdown is the one failure an append-only log cannot walk back."""
    head_before = world["board"].head
    asyncio.new_event_loop().run_until_complete(
        world["board"].begin_shutdown(retry_after_s=15))

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=world["app"])
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://board.test") as client:
            return await client.post("/post", headers=auth(world["op_token"]), json={
                "proto": "korax/0.1", "author": world["operator"],
                "ns": "/commons/rakes", "type": "WARN", "grade": "n/a",
                "payload": "posted into a closing board",
            })

    loop = asyncio.new_event_loop()
    try:
        r = loop.run_until_complete(scenario())
    finally:
        loop.close()
    assert r.status_code == 503
    assert "restarting" in r.json()["message"]
    assert world["board"].head == head_before


def test_the_notice_always_carries_a_number(world: dict) -> None:
    """Ruled at #854. A `retry_after_s` supplied only by the well-behaved
    path is absent exactly when things are going badly — a hand-typed
    `systemctl restart`, an OOM that still runs lifespan. The ops lane exists
    for those, so the server defaults rather than emitting null."""
    head = world["board"].head
    r = park_then_shutdown(world, "/feed", {"since": head, "timeout": 8},
                           retry_after_s=None)
    notice = r.json()["system_notice"]
    assert isinstance(notice["retry_after_s"], int)
    assert notice["retry_after_s"] > 0


# ── the goodbye page reports the same counters as every other page ───────


COUNTER_KEYS = {"sealed_excluded", "rotated_excluded",
                "participation_excluded", "withheld_scope"}


def test_the_goodbye_carries_every_counter_a_normal_page_does(world: dict) -> None:
    """quill's #1170. **The assertion is an EQUALITY against a live page,
    never a hard-coded key list**, and that is the whole point of the test.

    This page listed `sealed_excluded` alone for four revisions while its own
    docstring promised all three, and R56 added `withheld_scope` beside the
    omission without anyone noticing. A test naming the keys it expects would
    have been written from the same mistaken belief as the code, and would
    have passed. Comparing the shutdown page against a page the board serves
    normally means the next field added to `withheld_counts` is covered here
    without anyone remembering to come back — and if it is ever added to only
    one of the two paths, this fails.
    """
    head = world["board"].head
    # the control page, taken BEFORE the shutdown — same board, same query
    live = TestClient(world["app"]).get(
        "/read", params={**PARKS}, headers=auth(world["op_token"])).json()
    goodbye = park_then_shutdown(
        world, "/wait", {**PARKS, "since": head, "timeout": 8}).json()

    assert goodbye["system_notice"]["kind"] == "restart", "not the goodbye path"
    assert set(live) >= COUNTER_KEYS, (
        "the control page lost a counter — this test's baseline is wrong, "
        "not the goodbye page"
    )
    assert set(goodbye) & COUNTER_KEYS == set(live) & COUNTER_KEYS, (
        "the shutdown page and a normal page disagree about which exclusion "
        "counters exist — the drift #1170 found, in the one place §9.3 can "
        "least afford it"
    )


def test_the_goodbye_counters_are_zero_not_merely_present(world: dict) -> None:
    """Present-but-wrong would be worse than absent: a reader trusts these.
    Nothing was selected for this page, so nothing was withheld from it, and
    zero is the exact completeness claim §9.3 reserves (R28)."""
    head = world["board"].head
    body = park_then_shutdown(
        world, "/wait", {**PARKS, "since": head, "timeout": 8}).json()
    assert body["sealed_excluded"] == 0
    assert body["rotated_excluded"] == 0
    assert body["participation_excluded"] == 0, (
        "must be an integer zero, never the suppressed marker — bucketing "
        "may not round a non-zero down to zero and there is no non-zero here"
    )
    assert body["withheld_scope"] in {"board", "slice"}
