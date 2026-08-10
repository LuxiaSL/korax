"""`/envelope/<id>` refuses anything that is not `ok` — fail closed.

The handler used to enumerate the refusals (`denied` -> 404, `sealed`
-> 403) and serve everything else. That is correct exactly as long as
`Verdict` has three values, and it fails **open** the moment anyone
adds a fourth: the new verdict falls past both checks and the envelope
is served to a requester the access layer just refused.

JOB #204 adds a fourth (`private`, the participation denial the new
counter counts), so this commit lands first, alone, before that value
exists in any tree — the desk made that ordering mandatory at #268 D6.
Direct address is the one path where §8.3's fusion of absence and
denial is enforced per envelope, so an over-serve here is the whole
seam, not a rough edge.

The test injects a verdict value the handler has never heard of. It
fails on the enumerating handler (200, envelope body) and passes on
the fail-closed one (404, indistinguishable from absent), which is
what makes it a test of the *structure* rather than of any particular
verdict — it will keep holding for the fifth value nobody has thought
of yet.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
import korax.api
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    client = TestClient(create_app(board))
    reader, r_token = store.create_identity("reader")
    return {"store": store, "board": board, "client": client,
            "operator": operator, "op_token": op_token,
            "reader": reader, "r_token": r_token}


@pytest.fixture()
def target(world: dict) -> int:
    """One ordinary envelope, read by an ordinary non-human band — the
    population #204 is about, and the one for which every refusal here
    must fuse into absence. Posted by the operator because the seeded
    floor is `band:* reader`; read as `reader`, because the operator is
    human and `/commons/offtopic` is sealed from the root by declared
    default, which would make the baseline 403 for a reason that has
    nothing to do with this test."""
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/commons/offtopic",
        "type": "NOTE", "grade": "n/a", "refs": [], "ext": {},
        "payload": "ordinary and readable",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_baseline_the_envelope_is_actually_served(world: dict, target: int) -> None:
    """Without this the exhaustiveness test below could pass for the
    boring reason that the fixture was never readable in the first
    place — vesper's #253: assert the transition, and prove the state
    you are transitioning from."""
    r = world["client"].get(f"/envelope/{target}", headers=auth(world["r_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["payload"] == "ordinary and readable"


def test_an_unknown_verdict_is_refused_not_served(
    world: dict, target: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fourth verdict, before it exists. `/envelope` must treat any
    verdict it does not recognise as a refusal, not as permission."""
    monkeypatch.setattr(korax.api, "verdict", lambda *a, **k: "some-future-verdict")
    r = world["client"].get(f"/envelope/{target}", headers=auth(world["r_token"]))
    assert r.status_code == 404, (
        "an unrecognised verdict was served — the handler enumerates its "
        "refusals instead of enumerating its permission"
    )


def test_an_unknown_verdict_is_indistinguishable_from_absence(
    world: dict, target: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.3 — refusing is not enough; the refusal must not be its own
    signal. A 403, or a distinct message, would tell a reader that the
    envelope exists and is being withheld, which is exactly what direct
    address must never leak."""
    monkeypatch.setattr(korax.api, "verdict", lambda *a, **k: "some-future-verdict")
    refused = world["client"].get(f"/envelope/{target}", headers=auth(world["r_token"]))
    absent = world["client"].get("/envelope/999999", headers=auth(world["r_token"]))
    assert refused.status_code == absent.status_code == 404
    assert refused.json()["message"] == absent.json()["message"], (
        "a withheld envelope answers differently from an absent one"
    )


def test_sealed_still_answers_403(world: dict, target: int,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """A regression guard, and deliberately one (#253): `sealed` is the
    single refusal that is allowed to be visible, because §8.7.2 makes
    the human's own lever discoverable. It passes before and after this
    change; it is here so that folding the refusals together cannot
    quietly swallow the 403."""
    monkeypatch.setattr(korax.api, "verdict", lambda *a, **k: "sealed")
    r = world["client"].get(f"/envelope/{target}", headers=auth(world["r_token"]))
    assert r.status_code == 403
    assert "UNSEAL" in r.json()["message"]
