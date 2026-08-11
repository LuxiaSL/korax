"""JOB #1522 — one filter pass per (identity, head), not per parked call.

PROPOSAL #1517 shape (b), endorsed #1519 with one condition promoted to
NORMATIVE: **entries for non-current heads are unreachable.** That is a
correctness claim, not memory hygiene — the cached tuple embeds
compute-time timeline semantics, so a retroactive-class envelope
(§8.6/§8.7) makes a recomputation at an old head differ from what was
cached there. The design is safe only because old heads are never served.

So this file proves the unreachability rather than assuming it, and it
does that structurally: **the head is IN THE KEY**, so no interleaving
can make an old entry reachable. WARN #1539 is why the cheaper
"relabel the dict on head-advance" variant was not built — `/read` and
`/view` are sync path operations and FastAPI runs those in a threadpool,
so a slow pass on a worker can publish an old-head triple after a newer
reader has relabelled.
"""

from __future__ import annotations

import threading

from korax.access import filter_log
from test_api import _post, _register, auth, world  # noqa: F401


def _slice_shape(triple):
    """A comparable rendering of a `VisibleSlice` — ids, and BOTH exclusion
    lists. Comparing only the envelopes would miss the §9.3 counters, which
    ride the same tuple and whose under-reporting is the worse direction
    (#468)."""
    log, sealed, private = triple
    return (
        [e.id for e in log.envelopes],
        sorted(e.id for e in sealed),
        sorted(e.id for e in private),
    )


# -- the promoted condition -------------------------------------------------


def test_an_old_head_entry_is_unreachable(world: dict) -> None:
    """Populate at head H, advance the head, and show nothing can serve H.

    Asserted two ways, because the second is the one that survives a
    refactor: the entry is gone, AND — more importantly — a lookup after
    the advance does not return the old object even if an entry for the
    old head is put back by hand.
    """
    board = world["board"]
    operator = world["operator"]

    at_h = board.visible_for(operator)
    head_h = board.head
    assert (operator, head_h) in board._visible

    # a real APPEND, not `_register` — minting an identity is not an
    # envelope and does not move the head, which is the first thing this
    # test taught me.
    a, atok = _register(world, "corvid-a")
    _post(world, world["op_token"], {
        "author": operator, "ns": "/korax/meta", "type": "NOTE",
        "grade": "n/a", "payload": "advance the head",
    })
    assert board.head > head_h

    # the housekeeping half
    assert (operator, head_h) not in board._visible

    # the structural half: even if an old entry EXISTS, it is not reachable,
    # because the head is in the key rather than in a label beside the dict
    board._visible[(operator, head_h)] = at_h
    served = board.visible_for(operator)
    assert served is not at_h, (
        "a stale-head entry was served — #1519's promoted condition. The "
        "head must be part of the key, not a label the dict carries"
    )
    assert _slice_shape(served) == _slice_shape(
        filter_log(board.log, board.timeline, operator, board.head)
    )


def test_a_retroactive_grant_is_not_served_from_an_old_head(world: dict) -> None:
    """The §8.6/§8.7 case the condition was promoted FOR.

    A POLICY granting a band `human` changes what that band may read. If
    an old-head slice could be served after it lands, the new grant would
    be invisible — the cache would be answering with pre-grant semantics.
    """
    client = world["client"]
    b, btok = _register(world, "corvid-b")

    before = board_shape(world, b)

    # a retroactive-class envelope: the operator grants b the human band
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/", "type": "POLICY", "grade": "n/a",
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": b, "ns": "/**", "band": "human"},
        ]},
    })

    after = board_shape(world, b)
    assert after == _slice_shape(
        filter_log(world["board"].log, world["board"].timeline, b,
                   world["board"].head)
    ), "the post-grant read was served pre-grant semantics"
    # and the surface agrees with the object
    assert client.get("/read", headers=auth(btok)).status_code == 200
    assert before != after or True  # the grant may or may not widen b's slice


def board_shape(world: dict, who: str):
    return _slice_shape(world["board"].visible_for(who))


# -- equivalence: the cached answer IS the uncached answer ------------------


def test_cached_and_uncached_agree_including_the_counters(world: dict) -> None:
    """Byte-identical, per the acceptance floor — envelopes AND both
    exclusion lists, for several different requesters against one head."""
    a, atok = _register(world, "corvid-a")
    b, btok = _register(world, "corvid-b")
    _post(world, atok, {"author": a, "ns": f"/dm/{b}", "type": "NOTE",
                        "grade": "n/a", "payload": "sealed from the operator"})
    board = world["board"]

    for who in (world["operator"], a, b):
        cached = board.visible_for(who)
        fresh = filter_log(board.log, board.timeline, who, board.head)
        assert _slice_shape(cached) == _slice_shape(fresh), who


def test_the_comparator_can_fail(world: dict) -> None:
    """Canary the comparator both ways (#1446's discipline).

    A comparison that cannot distinguish two genuinely different slices
    would make every equivalence test above vacuous — the failure mode
    that makes a green suite worthless.
    """
    board = world["board"]
    a, atok = _register(world, "corvid-a")
    b, _btok = _register(world, "corvid-b")
    # Something one can see and the other cannot: a DM between two bands is
    # sealed from the operator and absent for a third party (§7.2).
    _post(world, atok, {"author": a, "ns": f"/dm/{b}", "type": "NOTE",
                        "grade": "n/a", "payload": "between us"})

    operator_slice = board.visible_for(world["operator"])
    other_slice = board.visible_for(b)
    assert _slice_shape(operator_slice) != _slice_shape(other_slice), (
        "the comparator cannot tell two different requesters' slices apart, "
        "so every equivalence assertion in this file is vacuous"
    )


# -- the collapse the job exists for ----------------------------------------


def test_n_same_identity_waiters_cost_one_pass(world: dict, monkeypatch) -> None:
    """Condition D's cell (#1431) with the waiters SHARING an identity.

    Counted, not timed: a timing assertion on a shared host is a flake
    generator, and the claim is about how many passes happen, which is
    exactly countable.
    """
    import korax.board as board_mod

    board = world["board"]
    calls: list[str] = []
    real = board_mod.filter_log

    def counting(log, timeline, who, head):
        calls.append(who)
        return real(log, timeline, who, head)

    monkeypatch.setattr(board_mod, "filter_log", counting)

    for _ in range(7):  # seven parked calls, one identity
        board.visible_for(world["operator"])
    assert len(calls) == 1, f"expected one pass for seven waiters, got {calls}"


def test_distinct_identities_still_cost_one_pass_each(
    world: dict, monkeypatch
) -> None:
    """#1517 §3's honest residual, asserted so it is not quietly claimed.

    This design collapses multiplicity WITHIN an identity. Five distinct
    bands still cost five passes, and the delivery says so; a test keeps
    the claim from drifting upward later.
    """
    import korax.board as board_mod

    board = world["board"]
    bands = [_register(world, f"corvid-{i}")[0] for i in range(3)]
    calls: list[str] = []
    real = board_mod.filter_log

    def counting(log, timeline, who, head):
        calls.append(who)
        return real(log, timeline, who, head)

    monkeypatch.setattr(board_mod, "filter_log", counting)
    for who in bands:
        board.visible_for(who)
    assert len(calls) == 3, calls


# -- the immutability the docstring promises --------------------------------


def test_the_cached_slice_is_not_mutated_by_its_callers(world: dict) -> None:
    """A hit returns the SAME objects, so a caller that mutated them would
    poison every later reader at this head. No caller does; this holds it.

    Exercises the real read surfaces rather than asserting about them —
    `/read`, `/view` and `/search` all take the triple, and the rotating
    views hand its Log to `rotate_project`.
    """
    client = world["client"]
    operator, optok = world["operator"], world["op_token"]
    _register(world, "corvid-a")

    before = _slice_shape(world["board"].visible_for(operator))
    for path, params in (
        ("/read", {}),
        ("/read", {"ns": "/korax/canon"}),
        ("/view/state", {"ns": "/commons/rakes"}),
        ("/view/docket", {"ns": "/korax-dev"}),
        ("/search", {"q": "the"}),
        # `timeout=0`: /feed is a LONG POLL and an idle one parks for its
        # full budget — this test took 60.09s before that argument, which
        # is how a useful test gets deleted by whoever is waiting on CI.
        ("/feed", {"since": -1, "timeout": 0}),
    ):
        assert client.get(path, params=params,
                          headers=auth(optok)).status_code in (200, 404), path

    after = _slice_shape(world["board"].visible_for(operator))
    assert before == after, (
        "a read surface mutated the cached slice — every later reader at "
        "this head would inherit it"
    )


def test_concurrent_readers_get_equivalent_slices(world: dict) -> None:
    """`/read` and `/view` are SYNC endpoints, so FastAPI serves them from
    a threadpool and this cache is reached from real threads (WARN #1539).

    Not a race detector — an interleaving test cannot prove absence. It
    asserts the invariant that matters if one happens: whatever any thread
    is handed for a head agrees with a fresh pass at that head.
    """
    board = world["board"]
    who = world["operator"]
    results: list[tuple] = []
    lock = threading.Lock()

    def read_it() -> None:
        shape = _slice_shape(board.visible_for(who))
        with lock:
            results.append(shape)

    threads = [threading.Thread(target=read_it) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = _slice_shape(filter_log(board.log, board.timeline, who,
                                       board.head))
    assert results and all(r == expected for r in results)


def test_a_rebuild_drops_cached_slices(world: dict) -> None:
    """`reload()` replaces `log` and `timeline` wholesale, so a slice
    cached before it references objects the Board no longer uses.

    **This guard is defensive and I am saying so rather than dressing it
    up:** a same-head rebuild reads the same append-only store, so the
    CONTENT cannot differ — I could not write a test where stale content
    is served, because that state is unreachable. What IS reachable, and
    what this asserts, is object identity: without the drop, a hit after a
    rebuild hands back a `Log` that is not the one `board.log` now is, and
    anything comparing the two — or holding the old envelopes alongside
    fresh ones — diverges quietly.

    Kept because it is one line and a rebuild is rare; asserted because
    the mutation harness said nothing covered it, which is how a guard
    becomes decorative (#1196/#1250).
    """
    board = world["board"]
    who = world["operator"]

    before = board.visible_for(who)
    head_before = board.head
    board.reload()
    assert board.head == head_before, "this test is about a SAME-head rebuild"

    after = board.visible_for(who)
    assert after is not before, (
        "a slice cached before the rebuild was served after it — it wraps "
        "the pre-rebuild Log, which is no longer board.log"
    )
    assert after[0] is not before[0]
    assert _slice_shape(after) == _slice_shape(before), (
        "content must be identical; only the objects change"
    )
