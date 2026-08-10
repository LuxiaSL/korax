"""§11.1 R19c — a notification stream does not notify you of yourself.

`to_author` and `to_worked` matched self-authored envelopes, so the
downstream watch fired hardest exactly while its owner worked and every
such wake carried something already in the owner's context. Found live
twice on one board, from two bands on two different jobs (F3, #76 and
#93). `to=<id>` is deliberately left dumb.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    client = TestClient(create_app(board))
    return {"store": store, "board": board, "client": client,
            "operator": operator, "op_token": op_token}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register(world: dict, display: str) -> tuple[str, str]:
    r = world["client"].post("/identity", json={"display": display},
                             headers=auth(world["op_token"]))
    return r.json()["id"], r.json()["token"]


def grant(world: dict, *pairs: tuple[str, str, str]) -> None:
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/",
        "type": "POLICY", "grade": "n/a", "refs": [], "ext": {},
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            *({"identity": i, "ns": ns, "band": b} for i, ns, b in pairs),
        ]},
    })
    assert r.status_code == 200, r.text


def post(world: dict, token: str, author: str, **body) -> dict:
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": author, "ns": "/work",
        "grade": "n/a", "refs": [], "ext": {}, **body,
    })
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def scene(world: dict) -> dict:
    """A worker holding a claim, its own delivery hanging off that claim,
    and a colleague's envelope hanging off the same one. The colleague's
    is signal; the worker's own is the noise R19c removes."""
    worker, w_token = register(world, "worker")
    peer, p_token = register(world, "peer")
    grant(world, (worker, "/work/**", "claimant"), (peer, "/work/**", "claimant"))
    post(world, world["op_token"], world["operator"], ns="/work", type="POLICY",
         payload={
             "acts": ["OPEN", "CLAIM", "FINDING", "NOTE", "WARN", "POLICY", "STAMP"],
             "grades": True,
             "require_lease": False,
             "view_floor": "unverified",
             "retention": {"mode": "permanent"},
             "grants": [{"identity": worker, "band": "claimant"},
                        {"identity": peer, "band": "claimant"}],
         })

    anchor = post(world, world["op_token"], world["operator"],
                  type="OPEN", payload="work on offer")
    claim = post(world, w_token, worker, type="CLAIM", payload="taking it",
                 refs=[{"edge": "claims", "id": anchor["id"]}],
                 ext={"lease_until": "2099-01-01T00:00:00Z"})
    # both carry an edge to the OPEN (which to_worked resolves, since the
    # worker claimed it) and to the worker's own CLAIM (which to_author
    # resolves, since the worker authored it) — so one scene exercises both
    # filters, and the only difference between the two envelopes is who
    # wrote them
    hooks = [{"edge": "derives-from", "id": anchor["id"]},
             {"edge": "derives-from", "id": claim["id"]}]
    mine = post(world, w_token, worker, type="FINDING", payload="my own progress",
                refs=hooks)
    theirs = post(world, p_token, peer, type="FINDING", payload="somebody else's",
                  refs=hooks)
    return {"worker": worker, "w_token": w_token, "peer": peer,
            "anchor": anchor["id"], "claim": claim["id"],
            "mine": mine["id"], "theirs": theirs["id"], **world}


def read(scene: dict, **params) -> list[int]:
    r = scene["client"].get("/read", params=params, headers=auth(scene["w_token"]))
    assert r.status_code == 200, r.text
    return [e["id"] for e in r.json()["envelopes"]]


def test_to_author_drops_your_own_envelopes(scene: dict) -> None:
    got = read(scene, to_author=scene["worker"])
    assert scene["mine"] not in got
    assert scene["theirs"] in got


def test_to_worked_drops_your_own_envelopes(scene: dict) -> None:
    """The live repro: the worker's own delivery carries an edge to the
    thing it claimed, so it matched its own downstream watch."""
    got = read(scene, to_worked=scene["worker"])
    assert scene["mine"] not in got
    assert scene["theirs"] in got


def test_include_self_restores_the_old_behaviour(scene: dict) -> None:
    for filt in ("to_author", "to_worked"):
        got = read(scene, **{filt: scene["worker"]}, include_self="true")
        assert scene["mine"] in got, filt
        assert scene["theirs"] in got, filt


def test_to_is_a_dumb_tripwire_and_stays_that_way(scene: dict) -> None:
    """§11.1 — a monitor on one referent fires on anything touching it,
    the requester's own envelopes included. Narrowing it would break the
    one filter people use to watch a single thing happen."""
    got = read(scene, to=scene["anchor"])
    assert scene["mine"] in got
    assert scene["theirs"] in got


def test_exclusion_is_keyed_on_the_requester_not_the_filtered_identity(
    scene: dict,
) -> None:
    """Watching a COLLEAGUE's stream still shows their own posts — which is
    most of what you would be watching them for. The brief's wording drops
    envelopes authored by the identity the filter names; the rationale
    ("the author is already aware") is a fact about the requester, so the
    exclusion follows the requester. Flip this and the peer-watching case
    goes silent."""
    r = scene["client"].get("/read", params={"to_worked": scene["worker"]},
                            headers=auth(scene["op_token"]))
    got = [e["id"] for e in r.json()["envelopes"]]
    assert scene["mine"] in got     # the worker's own work, seen by another
    assert scene["theirs"] in got


def test_wait_does_not_park_on_your_own_envelope(scene: dict) -> None:
    """The cost R19c is really about: a park/wake/re-arm cycle, and a
    harness turn, per envelope you post about your own job."""
    r = scene["client"].get(
        "/wait",
        params={"to_worked": scene["worker"], "since": scene["claim"], "timeout": 0.2},
        headers=auth(scene["w_token"]),
    )
    woke = [e["id"] for e in r.json()["envelopes"]]
    assert scene["mine"] not in woke
    assert scene["theirs"] in woke


def test_plain_filters_are_untouched(scene: dict) -> None:
    """No listen filter, no exclusion: a plain nest drain still shows you
    everything you wrote."""
    got = read(scene, ns="/work")
    assert scene["mine"] in got
    assert scene["theirs"] in got
