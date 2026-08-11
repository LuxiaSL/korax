"""§10.8 ordering — `gated-by`, `blocked_by`, `ready`. JOB #387.

Design #906, endorsed #907, ruling AGAINST the brief on its central
point: the brief said a job depending on another carries
`part-of:<blocker>`. It must not.

    §12.7: "A campaign is a parent with children; an enactor may claim
    the parent to take the lot, or ANY SUBSET OF THE CHILDREN."

Read breakdown as blocking and every child of an OPEN parent renders
blocked — `ready` empties exactly when a campaign is most claimable, so
the reduction would be most wrong in the case the edge exists for. That
is `test_part_of_does_not_block`, and it is the case the board's only
live `part-of` edge CANNOT distinguish: #507 is `part-of` #385 and #385
is closed, so both readings agree there and a test built on real data
alone would pin nothing.

The finding underneath (#906 D0): this board HAS recorded a job
dependency exactly once, and recorded it as English. JOB #507 carries
`part-of → 385` in its refs and the words "GATES ON #385's MERGE" in
its payload — two relations in one breath, one machine-readable. This
edge is the second one getting a carrier.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

JOBS = "/dag/jobs"
PTR = {"uri": "https://example.invalid/b.md", "sha256": "0" * 64}
LEASE = {"lease_until": "2030-01-01T00:00:00Z"}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _raw(world: dict, token: str, **body: object):
    return world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "grade": "n/a", "refs": [], "ext": {}, **body,
    })


def _post(world: dict, token: str, **body: object) -> dict:
    r = _raw(world, token, **body)
    assert r.status_code == 200, r.text
    return r.json()


def _jobs(world: dict, token: str, ns: str = "/dag") -> dict:
    r = world["client"].get("/view/jobs", headers=auth(token), params={"ns": ns})
    assert r.status_code == 200, r.text
    return r.json()["output"]


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    client = TestClient(create_app(board))
    out: dict = {"store": store, "board": board, "client": client,
                 "operator": operator, "op_token": op_token}
    for who in ("desk", "worker"):
        ident, token = store.create_identity(who)
        out[who], out[who + "_token"] = ident, token
    _post(out, op_token, author=operator, ns="/", type="POLICY", payload={"grants": [
        {"identity": operator, "ns": "/**", "band": "human"},
        {"identity": "band:*", "ns": "/**", "band": "reader"},
        {"identity": out["desk"], "ns": "/dag/**", "band": "desk"},
        {"identity": out["desk"], "ns": "/other/**", "band": "desk"},
        {"identity": out["worker"], "ns": "/dag/**", "band": "claimant"},
    ]})
    for ns in (JOBS, "/other/jobs"):
        _post(out, out["desk_token"], author=out["desk"], ns=ns, type="POLICY",
              payload={"acts": ["JOB", "CLAIM", "FINDING", "SUPERSEDE"],
                       "grades": True, "require_lease": True})
    return out


def _job(world: dict, payload: str, refs: list | None = None, ns: str = JOBS) -> int:
    return _post(world, world["desk_token"], author=world["desk"], ns=ns,
                 type="JOB", payload=payload, pointer=PTR,
                 refs=refs or [])["id"]


# ── the ruling that separates the two readings ───────────────────────


def test_part_of_does_not_block(world: dict) -> None:
    """D1, and the whole reason this job exists.

    A campaign with an OPEN parent. §12.7 says any subset of the children
    is claimable, so both children must be `ready`. Under the brief's
    proposed reading — `part-of` as blocked-by — both would be blocked
    and `ready` would hold only the parent, which is the one thing an
    enactor taking "any subset of the children" is not doing."""
    parent = _job(world, "the campaign")
    a = _job(world, "child a", [{"edge": "part-of", "id": parent}])
    b = _job(world, "child b", [{"edge": "part-of", "id": parent}])

    out = _jobs(world, world["desk_token"])
    assert out["forest"] == {str(parent): [a, b]}, "breakdown still renders"
    assert out["blocked_by"] == {}, (
        "part-of is work breakdown, not ordering (§12.7) — reading it as "
        "blocked-by empties `ready` exactly when a campaign is claimable"
    )
    assert out["ready"] == [parent, a, b]


def test_gated_by_blocks_until_the_blocker_closes(world: dict) -> None:
    blocker = _job(world, "the substrate")
    gated = _job(world, "waits for it", [{"edge": "gated-by", "id": blocker}])

    out = _jobs(world, world["desk_token"])
    assert out["blocked_by"] == {str(gated): [blocker]}
    assert out["ready"] == [blocker], "the gated job is not offered"
    assert gated in out["open"], "blocked is still OPEN — it is not a bucket"

    _post(world, world["desk_token"], author=world["desk"], ns=JOBS,
          type="FINDING", payload="delivered", grade="verified",
          refs=[{"edge": "closes", "id": blocker}])

    out = _jobs(world, world["desk_token"])
    assert out["blocked_by"] == {}
    assert out["ready"] == [gated]


def test_a_superseded_blocker_releases_what_it_gated(world: dict) -> None:
    """X1's forwarding address doubles as a release: a re-pinned JOB is
    replaced, so work waiting on it is no longer waiting on anything."""
    blocker = _job(world, "the original")
    gated = _job(world, "waits", [{"edge": "gated-by", "id": blocker}])
    assert _jobs(world, world["desk_token"])["blocked_by"] == {str(gated): [blocker]}

    _job(world, "the re-pin", [{"edge": "supersedes", "id": blocker}])

    out = _jobs(world, world["desk_token"])
    assert out["blocked_by"] == {}, "a replaced blocker blocks nothing"


def test_a_taken_blocker_still_blocks(world: dict) -> None:
    """The distinction `_job_released` exists to make: being worked is
    emphatically not being finished."""
    blocker = _job(world, "someone is on it")
    gated = _job(world, "waits", [{"edge": "gated-by", "id": blocker}])
    _post(world, world["worker_token"], author=world["worker"], ns=JOBS,
          type="CLAIM", payload="taking the blocker", ext=LEASE,
          refs=[{"edge": "claims", "id": blocker}])

    out = _jobs(world, world["desk_token"])
    assert [t["job"] for t in out["taken"]] == [blocker]
    assert out["blocked_by"] == {str(gated): [blocker]}
    assert out["ready"] == [], "nothing is takeable: one held, one blocked"


def test_a_blocker_in_another_namespace_still_blocks(world: dict) -> None:
    """Ordering is ordering. The blocker is looked up on the log rather
    than in the subtree scan, so a job gated on another project's work
    reports honestly instead of reporting free."""
    outside = _job(world, "another project's job", ns="/other/jobs")
    gated = _job(world, "waits on /other", [{"edge": "gated-by", "id": outside}])

    out = _jobs(world, world["desk_token"])
    assert out["blocked_by"] == {str(gated): [outside]}
    assert outside not in out["open"], "the blocker is not in this ns's scan"
    assert out["ready"] == []


def test_delivered_work_is_never_reported_blocked(world: dict) -> None:
    blocker = _job(world, "still open")
    gated = _job(world, "gated but delivered anyway",
                 [{"edge": "gated-by", "id": blocker}])
    _post(world, world["desk_token"], author=world["desk"], ns=JOBS,
          type="FINDING", payload="shipped it early", grade="verified",
          refs=[{"edge": "closes", "id": gated}])

    out = _jobs(world, world["desk_token"])
    assert [d["job"] for d in out["delivered"]] == [gated]
    assert out["blocked_by"] == {}, "finished work is not waiting on anything"


def test_a_lapsed_job_carries_its_blockers_to_the_next_taker(world: dict) -> None:
    """`ready` covers `open` only, deliberately — but the blocker data is
    computed for lapsed jobs too, so a reader unioning the two buckets
    gets both stories rather than a flattened one."""
    blocker = _job(world, "the substrate")
    gated = _job(world, "gated", [{"edge": "gated-by", "id": blocker}])
    _post(world, world["worker_token"], author=world["worker"], ns=JOBS,
          type="CLAIM", payload="taking it", ext=LEASE,
          refs=[{"edge": "claims", "id": gated}])
    out = _jobs(world, world["desk_token"])
    assert out["blocked_by"] == {str(gated): [blocker]}
    assert [t["job"] for t in out["taken"]] == [gated], (
        "a TAKEN job with a live blocker is a claimant working ahead of "
        "their substrate, and the reduction says so"
    )


def test_ready_excludes_held_work(world: dict) -> None:
    free = _job(world, "free")
    held = _job(world, "held")
    _post(world, world["worker_token"], author=world["worker"], ns=JOBS,
          type="CLAIM", payload="mine", ext=LEASE,
          refs=[{"edge": "claims", "id": held}])
    out = _jobs(world, world["desk_token"])
    assert out["ready"] == [free]


# ── the edge itself ──────────────────────────────────────────────────


def test_gated_by_runs_job_to_job_only(world: dict) -> None:
    """The rule is checkable from types alone, so it is refused at post
    time and the reduction never sees a dangling or mistyped gate."""
    job = _job(world, "a job")
    note = _post(world, world["desk_token"], author=world["desk"], ns=JOBS,
                 type="FINDING", payload="not a job", grade="verified")

    bad_target = _raw(world, world["desk_token"], author=world["desk"], ns=JOBS,
                      type="JOB", payload="gated on a FINDING", pointer=PTR,
                      refs=[{"edge": "gated-by", "id": note["id"]}])
    assert bad_target.status_code == 400
    assert "may not target" in bad_target.json()["message"]

    bad_source = _raw(world, world["desk_token"], author=world["desk"], ns=JOBS,
                      type="FINDING", payload="a FINDING may not gate",
                      grade="verified",
                      refs=[{"edge": "gated-by", "id": job}])
    assert bad_source.status_code == 400
    assert "may not originate" in bad_source.json()["message"]


def test_the_conformance_matrix_carries_the_new_edge(world: dict) -> None:
    """`edge_rules` is generated from the validator's own constants
    (api.py), so a client pre-flighting an edge learns about `gated-by`
    without anyone hand-copying a table — #511's defect avoided by
    construction rather than by care."""
    body = world["client"].get("/conformance").json()
    assert "gated-by" in body["edges"]
    assert body["edge_rules"]["gated-by"] == {"sources": ["JOB"], "targets": ["JOB"]}


def test_an_older_client_survives_the_new_edge(world: dict) -> None:
    """§13, and the reason this addition has no client leg: both clients
    type `edge` as a plain string on purpose, so an unrecognised edge
    renders rather than raising. Asserted here at the wire shape the
    clients validate against."""
    blocker = _job(world, "b")
    gated = _job(world, "g", [{"edge": "gated-by", "id": blocker}])
    env = world["client"].get(f"/envelope/{gated}",
                              headers=auth(world["desk_token"])).json()
    edges = [r["edge"] for r in env["refs"]]
    assert edges == ["gated-by"]
    assert isinstance(edges[0], str), (
        "the wire carries the edge as a bare string, which is why an older "
        "client renders it instead of raising (§13)"
    )
