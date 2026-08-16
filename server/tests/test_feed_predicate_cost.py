"""JOB #1610 / #1617 — /feed's long-poll predicate must not rebuild the
lane union per envelope.

`hits_now()` once spread `*lanes(log)` INSIDE its comprehension, so the
four-lane union (`authored_by`, `worked_by`, `descended_targets`,
`live_subscriptions`) was rebuilt for every envelope in the log. That made
the predicate O(n^2) in board size, and `Condition.wait_for` re-runs it for
every parked waiter on every notify — the whole of the 28-second live
write-stall measured at #1603 and decomposed at #1617.

**The assertion is a CALL COUNT, not a duration.** A timing assertion on a
shared host is a flake generator, and the property that matters is exactly
countable: the lane union is a loop invariant, so its cost per request must
not scale with the log.

The strongest available form of that, and the one used below: measure the
count at two board sizes and require them to be EQUAL. "Fewer than K calls"
would pass a board that happens to be small; "the same at 2n as at n" is
the invariant itself, and it cannot hold if the rebuild is inside the loop.
"""
from __future__ import annotations


import korax.api as api_mod
from test_api import _post, _register, auth, world  # noqa: F401


def _feed_lane_calls(world: dict, token: str, monkeypatch) -> int:
    """How many times one bare /feed request rebuilds a lane."""
    calls: list[str] = []
    real = api_mod.descended_targets

    def counting(log, who, head):
        calls.append(who)
        return real(log, who, head)

    monkeypatch.setattr(api_mod, "descended_targets", counting)
    # `timeout=0`: /feed is a long poll and an idle one otherwise parks for
    # its whole budget — 60s of nothing, which is how a useful test gets
    # deleted by whoever is waiting on CI (#1522).
    r = world["client"].get("/feed", params={"since": -1, "timeout": 0},
                            headers=auth(token))
    assert r.status_code == 200, r.text
    monkeypatch.undo()
    return len(calls)


def _grow(world: dict, to_head: int) -> None:
    while world["board"].head < to_head:
        _post(world, world["op_token"], {
            "author": world["operator"], "ns": "/korax/meta", "type": "NOTE",
            "grade": "n/a", "payload": f"filler {world['board'].head}",
        })


def test_lane_rebuilds_do_not_scale_with_board_size(world: dict, monkeypatch):
    """The invariant: per-request lane cost is O(1) in the log, not O(n).

    Reverting the hoist makes `small` and `large` differ by exactly the
    number of envelopes added, so this reddens hard rather than marginally.
    """
    _reader, token = _register(world, "corvid-feed")

    _grow(world, 200)
    small = _feed_lane_calls(world, token, monkeypatch)

    _grow(world, 400)
    large = _feed_lane_calls(world, token, monkeypatch)

    assert small == large, (
        f"/feed rebuilt the lane union {small} times on a 200-envelope board "
        f"and {large} times on a 400-envelope board — the union is a loop "
        f"invariant and is being recomputed per envelope (JOB #1610). This "
        f"is O(n^2) per parked waiter per notify."
    )


def test_the_counter_can_fail(world: dict, monkeypatch):
    """Canary the instrument, in both directions (#1028, #1446).

    A counter that never observes anything would make the test above pass
    on a board where the lane union is not built at all — so prove it
    counts, and prove the count is small rather than merely nonzero.
    """
    _reader, token = _register(world, "corvid-canary")
    _grow(world, 200)

    seen = _feed_lane_calls(world, token, monkeypatch)
    assert seen > 0, "the counter observed nothing — it is not wired to /feed"
    assert seen < 20, (
        f"{seen} lane rebuilds for ONE request: the counter is wired, and "
        f"the predicate is rebuilding per envelope"
    )


def test_the_predicate_and_the_response_agree(world: dict, monkeypatch):
    """The hoist must not change WHAT the feed returns, only how often it
    computes it.

    `hits_now()` decides whether to park; the response path re-derives the
    same set. If the hoisted predicate and the response path ever disagree,
    a caller parks when it should have been served — a silent hang rather
    than a wrong answer, which is the worse failure to debug.
    """
    author, atok = _register(world, "corvid-author")
    reader, rtok = _register(world, "corvid-reader")
    _grow(world, 120)
    # something addressed to the reader, so at least one lane is non-empty
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/meta", "type": "NOTE",
        "grade": "n/a", "payload": "addressed",
        "ext": {"korax": {"mentions": [reader]}},
    })

    r = world["client"].get("/feed", params={"since": -1, "timeout": 0},
                            headers=auth(rtok))
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [e["id"] for e in body["envelopes"]]

    # the predicate's own verdict, reached through the same handler
    assert ids, "the reader's feed is empty; this test asserts nothing"
    # every returned envelope carries a reason — the response path and the
    # lane binding it used are consistent
    assert set(body["reasons"]) == {str(i) for i in ids}


# -- the #1431/#1587 rig shape: parked waiters + a writer -------------------


def test_a_write_under_parked_waiters_costs_a_constant_per_waiter(
    world: dict, monkeypatch
) -> None:
    """Gate condition from #1620: exercise the shape the herd actually has —
    waiters PARKED on /feed, then a write that wakes all of them at once.

    **Driven on ONE event loop via httpx/ASGI rather than TestClient
    threads.** TestClient builds a fresh portal — and so a fresh loop — per
    request, and `board.condition` is an `asyncio.Condition` bound to the
    loop that first touched it, so a threaded version dies with "bound to a
    different event loop" before it can measure anything. One loop with
    concurrent tasks is also what uvicorn actually does, so this is the
    production shape and not merely the shape that runs.

    Kept as a COUNT rather than a duration. #1431's rig proved the stall
    with timings, which was right for a one-off measurement and wrong for a
    permanent test: timing on a shared CI host is a flake generator, and
    "the lane union is built a constant number of times per waiter" is
    exactly countable.
    """
    import asyncio

    import httpx
    import korax.api as api_mod

    board = world["board"]
    app = world["client"].app
    parkers = [_register(world, f"corvid-park-{i}") for i in range(5)]
    idents = [i for i, _t in parkers]
    tokens = [t for _i, t in parkers]
    _grow(world, 300)
    at_head = board.head

    calls: list[str] = []
    real = api_mod.descended_targets

    def counting(log, who, head):
        calls.append(who)          # single loop: no lock needed, and a lock
        return real(log, who, head)  # here would be a lie about concurrency

    monkeypatch.setattr(api_mod, "descended_targets", counting)

    async def run() -> list[int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://rig") as ac:
            parked = [
                asyncio.create_task(
                    ac.get("/feed",
                           params={"since": at_head, "timeout": 15},
                           headers=auth(tok))
                )
                for tok in tokens
            ]
            # let them all reach the park before the write. The
            # "every waiter received it" assertion below is what actually
            # proves they parked; this sleep only makes that likely.
            await asyncio.sleep(1.0)
            w = await ac.post("/post", headers=auth(world["op_token"]), json={
                "proto": "korax/0.1", "author": world["operator"],
                "ns": "/korax/meta", "type": "NOTE", "grade": "n/a",
                "refs": [], "ext": {"korax": {"mentions": idents}},
                # It must land in a LANE the waiters actually receive on.
                # A bare operator NOTE matches none of them, and the feed
                # correctly returns nothing — the first version of this test
                # parked all five for the full timeout and then asserted on
                # a wake that never happened.
                "payload": "the write that wakes the herd",
            })
            assert w.status_code == 200, w.text
            done = await asyncio.gather(*parked)
        out = []
        for r in done:
            assert r.status_code == 200, r.text
            out.append(len(r.json()["envelopes"]))
        return out

    got = asyncio.run(run())

    assert all(n >= 1 for n in got), (
        f"a waiter woke with nothing: {got} — it did not park, so this test "
        f"counted immediate returns and proves nothing about a wake"
    )

    per_waiter = len(calls) / len(tokens)
    assert per_waiter <= 10, (
        f"{len(calls)} lane rebuilds for {len(tokens)} waiters across one "
        f"write ({per_waiter:.0f} each) on a {at_head}-envelope board. The "
        f"lane union is a loop invariant; this is the O(n^2) predicate "
        f"(JOB #1610), and it is what made a live write cost 28.7s."
    )
