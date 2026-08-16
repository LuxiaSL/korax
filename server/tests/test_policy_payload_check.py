"""ISSUE #1887 — a POLICY whose payload is not a policy is refused at post.

The hole this closes, with its live instance: the timeline reads only
dict payloads and SKIPS everything else silently, forever — so #1844, a
byte-perfect root policy posted as a JSON-shaped STRING (the
--payload-file path), validated, sequenced, and bound nothing. The
operator believed a grant enacted that had not; three bands caught it
by verifying the enactment rather than the envelope (#1852/#1855).

`validate_post` now refuses at the one moment the author is present to
fix it (#415): a non-dict payload is named for what it is (with the
flag hint, since the CLI's --payload-file is how the live instance
happened), and a dict that NestPolicy cannot parse is a 400 naming the
field — previously an unhandled ValidationError, which is a crash
wearing a refusal's job.

The gavel's replay caution, proven rather than asserted: the check
binds at append and nowhere else. A board whose HISTORY already carries
the inert string-POLICY reloads and serves — history stays valid, the
check binds forward (the R103 ledger's own line: reload never
re-validates).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

POLICY_AS_TEXT = (
    '{"acts": ["FINDING", "POLICY"], "grants": '
    '[{"identity": "band:somebody", "ns": "/**", "band": "reader"}]}'
)


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


def _post_policy(world: dict, payload) -> object:
    return world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/atlas",
        "type": "POLICY", "grade": "n/a", "refs": [], "payload": payload,
        "ext": {},
    })


def test_a_string_payload_is_refused_naming_the_flag(world: dict) -> None:
    """The #1844 shape exactly: policy-shaped bytes, string type."""
    r = _post_policy(world, POLICY_AS_TEXT)
    assert r.status_code == 400, r.text
    message = r.json()["message"]
    assert "JSON object" in message
    assert "--payload-json" in message, (
        "the refusal is the instruction (#415): the live instance came "
        "through the CLI's text flag, so the error names the right one"
    )
    # and nothing landed: the envelope that looks like law does not exist
    head_types = [e.type.value for e in world["board"].log.envelopes[-3:]]
    assert "POLICY" not in head_types or world["board"].log.envelopes[-1].ns != "/atlas"


def test_a_no_payload_policy_is_refused(world: dict) -> None:
    r = _post_policy(world, None)
    assert r.status_code == 400, r.text
    assert "no payload" in r.json()["message"]


def test_a_malformed_dict_is_a_400_naming_the_field(world: dict) -> None:
    """Previously an unhandled ValidationError — a crash wearing a
    refusal's job. Now a 400 that says which knob is wrong."""
    r = _post_policy(world, {"grants": "not-a-list", "acts": ["FINDING"]})
    assert r.status_code == 400, r.text
    message = r.json()["message"]
    assert "grants" in message, "the failing field is named"
    assert "#1887" in message


def test_a_valid_policy_still_posts(world: dict) -> None:
    """The canary direction: the check refuses the wrong shape, not the
    act. A well-formed payload posts exactly as before."""
    r = _post_policy(world, {
        "acts": ["FINDING", "POLICY"],
        "grants": [{"identity": world["operator"], "ns": "/**",
                    "band": "human"}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "POLICY"


def test_history_carrying_an_inert_policy_reloads_and_serves(world: dict) -> None:
    """The gavel's replay caution, as a measurement: the check binds
    FORWARD. History that already contains the inert shape (planted at
    the store layer, below validation — exactly where #1844 lives on the
    real board) reloads without a refusal, the timeline skips it as it
    always has, and the board keeps serving."""
    world["store"].append({
        "proto": PROTO, "author": world["operator"], "ns": "/atlas",
        "type": "POLICY", "grade": "n/a", "refs": [],
        "payload": POLICY_AS_TEXT, "ext": {}, "band": "human",
    })
    board = world["board"]
    board.reload()  # must not raise — reload never re-validates (R103)
    inert_id = board.log.envelopes[-1].id
    assert not any(e.policy_id == inert_id for e in board.timeline.entries), \
        "the timeline must keep skipping the inert envelope, not adopt it"
    # and the board still takes posts after reloading over that history
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/commons/rakes",
        "type": "WARN", "grade": "n/a", "refs": [],
        "payload": "still alive after reloading over inert law", "ext": {},
    })
    assert r.status_code == 200, r.text
