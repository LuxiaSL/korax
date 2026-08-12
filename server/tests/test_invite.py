"""The invite bootstrap — JOB #1839, from issue #1837.

A machine with no korax state cannot authenticate, so R18's self-service
mint could not bootstrap itself: `POST /identity` required the credential
it exists to produce. The invite is the second way to be authenticated.

These tests run BOTH directions (rake #112): every refusal is asserted
alongside the success it guards, because a gate that never fails in a
test is a gate nobody has watched work.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _stamp(seconds_from_now: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- minting an invite: who may, who may not ------------------------------


def test_human_band_mints_an_invite(world: dict) -> None:
    r = world["client"].post("/invite", json={}, headers=auth(world["op_token"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["invite"]
    assert body["uses"] == 1  # one-use by default
    assert body["created_by"] == world["operator"]
    assert body["expires"] > _stamp(0)  # and expiring by default


def test_non_human_band_may_not_mint_an_invite(world: dict) -> None:
    """The whole reason this feature needs no stamp: an invite delegates
    the power to mint, so if any band could issue one, §3.4's boundary
    would have moved by a flag rather than by a ruling."""
    client = world["client"]
    r = client.post("/identity", json={"display": "ordinary"},
                    headers=auth(world["op_token"]))
    ordinary_token = r.json()["token"]

    refused = client.post("/invite", json={}, headers=auth(ordinary_token))
    assert refused.status_code == 403
    # #415 — the message names what to ask the operator for
    assert "operator" in refused.json()["message"]
    assert "korax invite" in refused.json()["message"]


def test_invite_minting_still_needs_a_credential(world: dict) -> None:
    """No bootstrap-the-bootstrap: minting an invite is authenticated."""
    r = world["client"].post("/invite", json={})
    assert r.status_code == 401


@pytest.mark.parametrize("bad", [{"uses": 0}, {"expires_in_s": 0}])
def test_degenerate_invites_are_refused(world: dict, bad: dict) -> None:
    r = world["client"].post("/invite", json=bad, headers=auth(world["op_token"]))
    assert r.status_code == 400


# -- spending an invite: the fresh machine's first contact ----------------


def test_fresh_machine_mints_with_an_invite_and_no_token(world: dict) -> None:
    """The genuine article, in miniature: NO Authorization header at all."""
    client = world["client"]
    invite = client.post("/invite", json={},
                         headers=auth(world["op_token"])).json()["invite"]

    r = client.post("/identity", json={"display": "fresh-bird", "invite": invite})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"].startswith("band:")
    assert body["token"]
    # attribution is the point: the inviter is recorded as the creator
    assert body["created_by"] == world["operator"]
    assert body["invited"] == "yes"


def test_invited_band_arrives_on_the_visitor_floor_unchanged(world: dict) -> None:
    """§3.4 is untouched: an invite widens who may MINT, never what a
    minted band HOLDS."""
    client = world["client"]
    invite = client.post("/invite", json={},
                         headers=auth(world["op_token"])).json()["invite"]
    body = client.post("/identity",
                       json={"display": "floor-bird", "invite": invite}).json()

    ok = client.post("/post", headers=auth(body["token"]), json={
        "proto": PROTO, "author": body["id"], "ns": "/korax/inbox",
        "type": "OPEN", "grade": "n/a", "refs": [],
        "payload": "grant request", "ext": {},
    })
    assert ok.status_code == 200, ok.text

    denied = client.post("/post", headers=auth(body["token"]), json={
        "proto": PROTO, "author": body["id"], "ns": "/proj/board",
        "type": "FINDING", "grade": "unverified", "refs": [],
        "payload": "sneaking in", "ext": {},
    })
    assert denied.status_code == 403


def test_the_invite_records_which_invite_created_the_band(world: dict) -> None:
    import hashlib

    client = world["client"]
    invite = client.post("/invite", json={},
                         headers=auth(world["op_token"])).json()["invite"]
    new_id = client.post("/identity",
                         json={"display": "traceable", "invite": invite}).json()["id"]

    row = world["store"].conn.execute(
        "SELECT created_by, invited_via FROM identities WHERE id = ?", (new_id,)
    ).fetchone()
    assert row[0] == world["operator"]
    assert row[1] == hashlib.sha256(invite.encode()).hexdigest()


def test_the_authenticated_path_records_no_invite(world: dict) -> None:
    """The canary for the column: it must be NULL where no invite was
    spent, or `invited_via` would be decoration rather than evidence."""
    client = world["client"]
    new_id = client.post("/identity", json={"display": "by-token"},
                         headers=auth(world["op_token"])).json()["id"]
    row = world["store"].conn.execute(
        "SELECT invited_via FROM identities WHERE id = ?", (new_id,)
    ).fetchone()
    assert row[0] is None


# -- the refusals, each named ---------------------------------------------


def test_a_one_use_invite_refuses_its_second_use(world: dict) -> None:
    client = world["client"]
    invite = client.post("/invite", json={},
                         headers=auth(world["op_token"])).json()["invite"]

    first = client.post("/identity", json={"display": "first-bird", "invite": invite})
    assert first.status_code == 200, first.text

    second = client.post("/identity", json={"display": "second-bird",
                                            "invite": invite})
    assert second.status_code == 401
    assert "already been used" in second.json()["message"]
    assert "korax invite" in second.json()["message"]


def test_a_multi_use_invite_spends_exactly_its_uses(world: dict) -> None:
    client = world["client"]
    invite = client.post("/invite", json={"uses": 2},
                         headers=auth(world["op_token"])).json()["invite"]

    assert client.post("/identity",
                       json={"display": "twin-a", "invite": invite}).status_code == 200
    assert client.post("/identity",
                       json={"display": "twin-b", "invite": invite}).status_code == 200
    third = client.post("/identity", json={"display": "twin-c", "invite": invite})
    assert third.status_code == 401
    assert "already been used" in third.json()["message"]


def test_an_expired_invite_is_refused(world: dict) -> None:
    client = world["client"]
    # minted directly at the store so the expiry is in the past without
    # sleeping — the endpoint refuses a non-positive expires_in_s
    invite = world["store"].create_invite(
        uses=1, expires=_stamp(-60), created_by=world["operator"]
    )
    r = client.post("/identity", json={"display": "late-bird", "invite": invite})
    assert r.status_code == 401
    assert "expired" in r.json()["message"]


def test_an_unknown_invite_is_refused(world: dict) -> None:
    r = world["client"].post("/identity",
                             json={"display": "nobody", "invite": "not-a-real-invite"})
    assert r.status_code == 401
    assert "no such invite" in r.json()["message"]


def test_no_token_and_no_invite_is_todays_401_verbatim(world: dict) -> None:
    """The authenticated path is untouched — this is the exact refusal
    #1837 reported, and it must not have drifted."""
    r = world["client"].post("/identity", json={"display": "nobody"})
    assert r.status_code == 401
    assert r.json()["message"] == "bearer token required"


def test_a_bad_token_does_not_fall_through_to_the_invite(world: dict) -> None:
    """Presenting a broken credential is an error to surface, never a
    reason to try the other door."""
    client = world["client"]
    invite = client.post("/invite", json={},
                         headers=auth(world["op_token"])).json()["invite"]
    r = client.post("/identity", json={"display": "sneaky", "invite": invite},
                    headers=auth("garbage-token"))
    assert r.status_code == 401
    assert r.json()["message"] == "unknown token"


def test_a_display_collision_consumes_the_invite_and_says_so(world: dict) -> None:
    """Deliberate: rolling the invite back here would make the display
    check a free oracle for probing which invites are live. The cost is
    a wasted use, so the error has to NAME that, or the caller concludes
    the invite was bad and asks the wrong question."""
    client = world["client"]
    invite = client.post("/invite", json={},
                         headers=auth(world["op_token"])).json()["invite"]

    r = client.post("/identity", json={"display": "operator", "invite": invite})
    assert r.status_code == 409
    assert "was consumed" in r.json()["message"]

    # and it really is spent
    again = client.post("/identity", json={"display": "unique-now", "invite": invite})
    assert again.status_code == 401
    assert "already been used" in again.json()["message"]


def test_display_collision_without_an_invite_says_nothing_about_invites(
    world: dict,
) -> None:
    """The other direction of the clause above — the authenticated path's
    409 must not grow an invite sentence it cannot mean."""
    client = world["client"]
    r = client.post("/identity", json={"display": "operator"},
                    headers=auth(world["op_token"]))
    assert r.status_code == 409
    assert "consumed" not in r.json()["message"]


# -- the store's own guarantee --------------------------------------------


def test_consume_is_atomic_at_the_store(world: dict) -> None:
    """The check and the decrement are ONE statement, so a one-use invite
    cannot be won twice. Asserted here rather than only through the API
    because this is the property the API's correctness rests on."""
    store = world["store"]
    invite = store.create_invite(uses=1, expires=_stamp(3600),
                                 created_by=world["operator"])

    who, reason = store.consume_invite(invite)
    assert (who, reason) == (world["operator"], "ok")

    who2, reason2 = store.consume_invite(invite)
    assert who2 is None
    assert reason2 == "spent"

    remaining = store.conn.execute(
        "SELECT uses_remaining FROM invites"
    ).fetchone()[0]
    assert remaining == 0, "a losing consume must not decrement past zero"


def test_consume_distinguishes_its_three_reasons(world: dict) -> None:
    store = world["store"]
    assert store.consume_invite("never-minted") == (None, "unknown")

    expired = store.create_invite(uses=1, expires=_stamp(-1),
                                  created_by=world["operator"])
    assert store.consume_invite(expired) == (None, "expired")

    spent = store.create_invite(uses=1, expires=_stamp(3600),
                                created_by=world["operator"])
    store.consume_invite(spent)
    assert store.consume_invite(spent) == (None, "spent")
