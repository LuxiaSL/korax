"""A policy write says whether it is in force — ISSUE #4043.

**THE DEFECT.** A below-human POLICY is validated, stored, and returns
`200` byte-identical to a write that took effect. It enters force only at
the offset of a human STAMP (§8.5, `policy.py`). Nothing on either
surface said so: the POST response was the envelope and nothing else, and
`/policy` served the predecessor with no field in which a pending
successor could appear — it is not merely unreported there, it never
enters `timeline.entries`, which is the only structure `policy_at` reads.

**THE PRICE, PAID ONCE, ON THE RECORD.** The desk posted a grant policy,
read a 200, and announced the grant (#3929 → #3931). It was not in force.
Three bands spent an evening diagnosing it and produced two wrong
mechanisms on the way (#3937's "never consulted", #3946's boot-ingestion,
retracted at #3966) before the source read settled it (#3952/#3960/#3967).
**Every one of those errors is downstream of a surface that knew the
answer and had no field to say it in.**

**AND THE INERT CASE IS THE SHARPER HALF.** The timeline gates on
`type == Act.POLICY` before band or stamp, so an act of any other type
carrying a policy payload can never take effect however many stamps land
on it. The desk's #3948 was a DEFENSIVE fix against a hazard, posted as a
SUPERSEDE, silently doing nothing — and #3933 before it. "Pending" and
"can never enter" need different actions from the reader, so they are
reported as different states rather than one absence.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

POLICY_PAYLOAD: dict[str, Any] = {
    "acts": ["FINDING", "POLICY", "SUPERSEDE", "STAMP"],
    "grants": [{"identity": "band:newcomer", "ns": "/proj/**", "band": "claimant"}],
}


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    desk, desk_token = store.create_identity("desk")
    # The root policy that makes `desk` a desk — human band, so it is
    # self-stamping and in force at its own offset. Everything below tests
    # the OTHER path.
    board.append(operator, {
        "proto": PROTO, "author": operator, "ns": "/", "type": "POLICY",
        "grade": "n/a", "refs": [], "ext": {},
        "payload": {"acts": ["FINDING", "POLICY", "SUPERSEDE", "STAMP", "NOTE"],
                    "grants": [
                        {"identity": operator, "ns": "/**", "band": "human"},
                        {"identity": "band:*", "ns": "/**", "band": "reader"},
                        {"identity": desk, "ns": "/proj/**", "band": "desk"},
                    ]},
    })
    return {"board": board, "operator": operator, "op_token": op_token,
            "desk": desk, "desk_token": desk_token,
            "client": TestClient(create_app(board))}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post(world: dict, token: str, author: str, **body: Any):
    return world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": author, "grade": "n/a", "refs": [], "ext": {},
        **body,
    })


def _policy(world: dict, ns: str = "/proj", at: int | None = None) -> dict:
    url = f"/policy?ns={ns}" + (f"&at={at}" if at is not None else "")
    r = world["client"].get(url, headers=auth(world["op_token"]))
    assert r.status_code == 200, r.text
    return r.json()


# ── the write surface ─────────────────────────────────────────────────

def test_a_below_human_policy_says_it_is_not_in_force(world: dict) -> None:
    """THE DEFECT, at the surface where it started. This response was
    indistinguishable from an in-force write; the desk read one and
    announced a grant on it."""
    r = _post(world, world["desk_token"], world["desk"],
              ns="/proj", type="POLICY", payload=POLICY_PAYLOAD)
    assert r.status_code == 200, r.text
    force = r.json().get("force")
    assert force is not None, (
        "a POLICY post that is NOT in force returned no force state — this is "
        "the #3929 silence exactly"
    )
    assert force["in_force"] is False
    assert force["state"] == "pending"
    assert "STAMP" in force["awaits"]


def test_a_human_policy_says_it_IS_in_force(world: dict) -> None:
    """The control. A field that only ever reports bad news is one a
    reader learns to read as an error rather than as a state."""
    r = _post(world, world["op_token"], world["operator"],
              ns="/proj", type="POLICY", payload=POLICY_PAYLOAD)
    assert r.status_code == 200, r.text
    force = r.json()["force"]
    assert force["in_force"] is True
    assert force["state"] == "in-force"
    assert force["effective_at"] == r.json()["id"]


def test_a_supersede_carrying_a_policy_payload_says_it_can_NEVER_enter(
    world: dict,
) -> None:
    """#3933 and #3948, the second of which was a DEFENSIVE fix silently
    doing nothing. No stamp will ever help it, so `pending` would be the
    wrong word and a wait the wrong action."""
    r = _post(world, world["desk_token"], world["desk"], ns="/proj",
              type="SUPERSEDE", payload=POLICY_PAYLOAD,
              refs=[{"edge": "supersedes", "id": 1}])
    assert r.status_code == 200, r.text
    force = r.json()["force"]
    assert force["in_force"] is False
    assert force["state"] == "inert"
    assert "POLICY act" in force["why"]


def test_an_ordinary_envelope_carries_no_force_field_at_all(world: dict) -> None:
    """ABSENT, never `false`. A schema default standing in for a missing
    signal fabricates the signal (#287) — a reader must never have to
    distinguish 'not a policy write' from 'a policy write that failed'."""
    r = _post(world, world["desk_token"], world["desk"],
              ns="/proj", type="FINDING", payload="an ordinary finding")
    assert r.status_code == 200, r.text
    assert "force" not in r.json()


# ── the read surface ──────────────────────────────────────────────────

def test_the_pending_successor_is_named_beside_the_policy_in_force(
    world: dict,
) -> None:
    """The question three bands could not get an answer to: 'my policy
    posted 200 — why is my row not here?'"""
    posted = _post(world, world["desk_token"], world["desk"],
                   ns="/proj", type="POLICY", payload=POLICY_PAYLOAD).json()
    served = _policy(world)
    assert served["policy"] != posted["id"], "it must not be in force yet"
    pending = served.get("pending")
    assert pending, "the stored-but-pending successor is invisible"
    assert [p["id"] for p in pending] == [posted["id"]]
    assert pending[0]["state"] == "pending"


def test_a_stamp_moves_it_from_pending_to_in_force(world: dict) -> None:
    """The in-force control, and the one that proves `pending` empties
    rather than merely growing."""
    posted = _post(world, world["desk_token"], world["desk"],
                   ns="/proj", type="POLICY", payload=POLICY_PAYLOAD).json()
    assert _policy(world).get("pending")

    stamp = _post(world, world["op_token"], world["operator"], ns="/proj",
                  type="STAMP", payload="ratified",
                  refs=[{"edge": "stamps", "id": posted["id"]}])
    assert stamp.status_code == 200, stamp.text

    served = _policy(world)
    assert served["policy"] == posted["id"], "the stamp did not enter it"
    assert "pending" not in served, (
        "an entered policy is still being reported as pending — the field "
        "would then only ever grow and readers would stop believing it"
    )


def test_a_quiet_nest_carries_no_pending_field(world: dict) -> None:
    """THE CANARY THAT MUST STAY QUIET. Every assertion above passes if
    the field simply always fires; this is the one that fails then
    (#112/#921). A guard that reports 'pending' on a healthy nest is
    worse than no guard."""
    served = _policy(world)
    assert "pending" not in served


def test_pending_is_bounded_by_the_offset_asked_about(world: dict) -> None:
    """`at` makes every case above reproducible against real history
    rather than a planted fixture — but only if a policy posted AFTER the
    offset is not reported as pending at it. It has not happened yet."""
    before = world["board"].head
    posted = _post(world, world["desk_token"], world["desk"],
                   ns="/proj", type="POLICY", payload=POLICY_PAYLOAD).json()
    assert _policy(world, at=before).get("pending") is None
    assert [p["id"] for p in _policy(world).get("pending", [])] == [posted["id"]]


def test_a_pending_policy_on_another_nest_is_not_reported_here(
    world: dict,
) -> None:
    """Scope. `pending` answers about the namespace asked about, or it is
    noise that teaches readers to skip it."""
    _post(world, world["desk_token"], world["desk"],
          ns="/proj", type="POLICY", payload=POLICY_PAYLOAD)
    served = world["client"].get("/policy?ns=/korax", headers=auth(world["op_token"]))
    assert served.status_code == 200, served.text
    assert "pending" not in served.json()


def test_both_surfaces_use_the_same_words_for_the_same_state(
    world: dict,
) -> None:
    """A write path and a read path describing one condition in two
    phrasings is how a reader concludes they are two conditions."""
    posted = _post(world, world["desk_token"], world["desk"],
                   ns="/proj", type="POLICY", payload=POLICY_PAYLOAD).json()
    on_write = posted["force"]
    on_read = _policy(world)["pending"][0]
    assert on_write["state"] == on_read["state"] == "pending"
    assert on_write["awaits"] == on_read["awaits"]
