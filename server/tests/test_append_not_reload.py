"""Append, don't reload — the equivalence suite IS the delivery's core
(JOB #1446, brief acceptance 1).

`Board.append` used to end in `reload()`: the whole log rebuilt from
sqlite per write, measured linear (#1431 §3). Now the envelope joins the
in-memory `Log` and `PolicyTimeline` incrementally — which is only
acceptable if the two paths are indistinguishable, so after EVERY append
of a mixed-act workload the incremental state is compared STRUCTURALLY
against a from-scratch reload: every index of the Log, the whole entries
list of the timeline, and the served head. Not sampled, not eyeballed.

The named hardest case is in the fixture: a below-human POLICY enters
force only when a human STAMP arrives LATER, so the timeline must change
on an act that is not a POLICY — miss it and grants silently do not
exist until the next restart rebuilds the world.

And per #112 as amended (canon v6): the guard is broken on purpose,
once, in both directions — a deliberately desynced index must FAIL the
comparison, because an equivalence check that cannot detect a desync
proves only that it ran.
"""

from __future__ import annotations

import pytest

from korax import PROTO
from korax.board import Board
from korax.log import Log
from korax.policy import PolicyTimeline
from korax.seed import seed_board
from korax.store import Store


def _log_state(log: Log) -> dict:
    return {
        "ids": [e.id for e in log.envelopes],
        "by_id": sorted(log._by_id.keys()),
        "records": [e.model_dump(mode="json") for e in log.envelopes],
        "inbound": {
            target: [(edge.value, src.id) for edge, src in pairs]
            for target, pairs in log._inbound.items()
            if pairs  # defaultdict: an empty bucket is absence, not state
        },
    }


def _timeline_state(tl: PolicyTimeline) -> list:
    return [
        {
            "ns": e.ns,
            "policy_id": e.policy_id,
            "effective_at": e.effective_at,
            "policy": e.policy.model_dump(mode="json"),
        }
        for e in tl.entries
    ]


def assert_equivalent(board: Board) -> None:
    """The incremental state against a from-scratch reload, structurally."""
    rebuilt_log = Log(board.store.load_all())
    rebuilt_tl = PolicyTimeline(rebuilt_log)
    assert _log_state(board.log) == _log_state(rebuilt_log)
    assert _timeline_state(board.timeline) == _timeline_state(rebuilt_tl)
    assert board.head == (
        rebuilt_log.envelopes[-1].id if len(rebuilt_log) else -1
    )


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, _tok = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    out = {"store": store, "board": board, "operator": operator}
    for who in ("desk", "worker"):
        ident, _t = store.create_identity(who)
        out[who] = ident
    return out


def _post(world: dict, author: str, **body: object) -> None:
    raw = {"proto": PROTO, "grade": "n/a", "refs": [], "ext": {},
           "author": author, **body}
    world["board"].append(author, raw)


def test_every_append_of_a_mixed_workload_matches_a_reload(world: dict) -> None:
    """The acceptance case: posts, a root grants POLICY, claims with
    leases, a DM, and the hardest case — a below-human POLICY that
    enters force only at its later human STAMP — with the equivalence
    asserted after EVERY append, so the first divergent index names the
    act that broke it."""
    b, op, desk, worker = world["board"], world["operator"], world["desk"], world["worker"]
    assert_equivalent(b)  # the seeded baseline itself

    steps = [
        # a human POLICY (self-stamping — timeline changes NOW)
        (op, dict(ns="/", type="POLICY", payload={"grants": [
            {"identity": op, "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": desk, "ns": "/proj/**", "band": "desk"},
            {"identity": worker, "ns": "/proj/**", "band": "claimant"},
        ]})),
        # ordinary content with refs (Log indexes, no timeline change)
        (desk, dict(ns="/proj/board", type="FINDING", payload="a finding")),
        (worker, dict(ns="/proj/board", type="NOTE", payload="cites it",
                      refs=[{"edge": "derives-from", "id": None}])),  # patched below
        # a JOB and a CLAIM with a lease (lease state rides ext)
        (desk, dict(ns="/proj/board", type="JOB", payload="JOB: do a thing")),
        (worker, dict(ns="/proj/board", type="CLAIM", payload="mine",
                      refs=[{"edge": "claims", "id": None}],
                      ext={"lease_until": "2030-01-01T00:00:00Z"})),
        # a DM (participation-shaped ns; Log only)
        (worker, dict(ns=f"/dm/{desk}", type="NOTE", payload="hello")),
        # THE HARDEST CASE, half one: a below-human POLICY — must NOT
        # enter force yet (no stamp can exist; edges point backwards)
        (desk, dict(ns="/proj/sub", type="POLICY", payload={
            "acts": ["FINDING", "NOTE", "STAMP", "POLICY"], "grades": True,
            "grants": [{"identity": worker, "ns": "/proj/sub/**", "band": "desk"}]})),
        # half two: the human STAMP that brings it into force — the
        # timeline changes on a STAMP, which is the case a naive
        # incremental path misses entirely
        (op, dict(ns="/proj/sub", type="STAMP", payload=None,
                  refs=[{"edge": "stamps", "id": None}])),
        # and the granted band immediately uses the newly-live grant —
        # proving force, not just entry shape
        (worker, dict(ns="/proj/sub", type="POLICY", payload={
            "acts": ["FINDING", "NOTE"], "grades": True})),
    ]

    posted: list[int] = []  # id of each step's envelope, by step index
    finding_id = job_id = stamped_policy_id = None
    for step, (author, body) in enumerate(steps):
        refs = body.get("refs") or []
        for ref in refs:
            if ref["id"] is None:
                ref["id"] = {"derives-from": finding_id,
                             "claims": job_id,
                             "stamps": stamped_policy_id}[ref["edge"]]
        _post(world, author, **body)
        env = world["board"].log.envelopes[-1]
        posted.append(env.id)
        if step == 1:
            finding_id = env.id
        if step == 3:
            job_id = env.id
        if step == 6:  # the below-human POLICY awaiting its stamp
            stamped_policy_id = env.id
        assert_equivalent(world["board"])  # after EVERY append

    # the stamped policy is genuinely IN FORCE on the incremental path —
    # the LAST step's worker POLICY is itself below-human and unstamped,
    # so the stamped desk policy must still be the one governing
    pid, _pol = world["board"].timeline.policy_at("/proj/sub", world["board"].head)
    assert pid == stamped_policy_id
    # and the worker's post at step 8 was only acceptable because the
    # stamped grant was live incrementally — its acceptance is the proof
    assert posted[8] == world["board"].head


def test_a_below_human_policy_is_not_in_force_before_its_stamp(world: dict) -> None:
    b, op, desk = world["board"], world["operator"], world["desk"]
    _post(world, op, ns="/", type="POLICY", payload={"grants": [
        {"identity": op, "ns": "/**", "band": "human"},
        {"identity": desk, "ns": "/proj/**", "band": "desk"},
    ]})
    _post(world, desk, ns="/proj/x", type="POLICY", payload={
        "acts": ["FINDING", "POLICY", "STAMP"], "grades": True})
    unstamped = b.log.envelopes[-1].id
    assert all(e.policy_id != unstamped for e in b.timeline.entries)
    assert_equivalent(b)


# -- the canary, both directions (#112 as amended) ----------------------


def test_the_comparator_detects_a_desynced_log(world: dict) -> None:
    """Break the guard on purpose: drop one inbound edge from the
    incremental index and the equivalence must go red. If this passes,
    the comparator is decoration and every green above it means
    nothing."""
    b, op = world["board"], world["operator"]
    _post(world, op, ns="/", type="POLICY", payload={"grants": [
        {"identity": op, "ns": "/**", "band": "human"}]})
    _post(world, op, ns="/commons/rakes", type="WARN", payload="target")
    target = b.log.envelopes[-1].id
    _post(world, op, ns="/commons/rakes", type="FINDING", payload="cite",
          refs=[{"edge": "derives-from", "id": target}])
    assert_equivalent(b)
    b.log._inbound[target].pop()  # the deliberate desync
    with pytest.raises(AssertionError):
        assert_equivalent(b)


def test_the_comparator_detects_a_desynced_timeline(world: dict) -> None:
    b, op = world["board"], world["operator"]
    _post(world, op, ns="/", type="POLICY", payload={"grants": [
        {"identity": op, "ns": "/**", "band": "human"}]})
    assert_equivalent(b)
    b.timeline.entries.pop()  # the deliberate desync
    with pytest.raises(AssertionError):
        assert_equivalent(b)
